"""Billing: invoices, lines, the allowance plan, payments and voids."""

from flask import Blueprint

import calcs
import clock as clockmod
import envelope
import ladder
import serializers as ser
import services
from constants import INVOICE_STATUSES, LINE_SOURCES, PAYMENT_METHODS
from errors import ApiError
from store import db, stamp_new, touch

bp = Blueprint("billing", __name__)

INVOICE_SPEC = ladder.Spec(
    required=[("account_id", "string")],
    optional=[("service_request_id", "string"), ("billing_period", "string")],
    periods=["billing_period"],
)

PAYMENT_SPEC = ladder.Spec(
    required=[
        ("amount_cents", "integer"),
        ("method", "string"),
        ("expected_invoice_version", "integer"),
    ],
    enums={"method": PAYMENT_METHODS},
    ranges={"amount_cents": (1, None)},
)


def _in_period(request_row, period):
    if request_row["completed_at"] is None:
        return False
    stamp = request_row["completed_at"]
    return (stamp.year, stamp.month) == period


def _covered_items(requests):
    items = []
    for request_row in requests:
        items.extend(ser.request_items(request_row["id"]))
    items.sort(key=lambda i: (i["created_at"], i["_seq"]))
    return [
        i for i in items if i["service_status"] not in ("RETURNED_UNSERVICED", "ABANDONED")
    ]


def _allowance_plan(requests):
    """PRD 3.10: the dearest candidate items absorb the allowance."""
    plans = {}
    for request_row in requests:
        subscription_id = request_row["subscription_id"]
        if not subscription_id:
            continue
        subscription = db.subscriptions.get(subscription_id)
        if subscription is None or subscription["status"] != "ACTIVE":
            continue
        if request_row["channel"] == "REWORK":
            continue
        for item in ser.request_items(request_row["id"]):
            if item["service_status"] in ("RETURNED_UNSERVICED", "ABANDONED"):
                continue
            plans.setdefault(subscription_id, []).append(item)

    absorbed = set()
    consumption = {}
    for subscription_id, candidates in plans.items():
        subscription = db.subscriptions[subscription_id]
        candidates.sort(
            key=lambda i: (-i["final_gross_cents"], i["created_at"], i["_seq"])
        )
        k = min(len(candidates), subscription["allowance_remaining"])
        chosen = candidates[:k]
        for item in chosen:
            absorbed.add(item["id"])
        consumption[subscription_id] = chosen
    return absorbed, consumption


def _charged_amounts(items, absorbed):
    """PRD 3.10 steps zero through five, in the pinned order."""
    amounts = {}
    for item in items:
        request_row = db.service_requests[item["service_request_id"]]
        if request_row["channel"] == "REWORK":
            amounts[item["id"]] = (0, 0)
            continue
        if item["id"] in absorbed:
            base = 0
        else:
            subscription = db.subscriptions.get(request_row["subscription_id"])
            if subscription is not None and subscription["status"] == "ACTIVE":
                tier = db.plan_tiers.get(subscription["plan_tier_id"])
                pct = tier["overage_discount_pct"] if tier else 0
                base = calcs.discounted_base(item["final_gross_cents"], pct)
            else:
                base = item["final_gross_cents"]
        if request_row["priority"] == "RUSH":
            base = base + calcs.rush_surcharge(base)
        amounts[item["id"]] = (base, calcs.part_fee_for(item["assessed_damage_tier"]))
    return amounts


# ---------------------------------------------------------------------------
# POST /sharpening/invoices
# ---------------------------------------------------------------------------
@bp.route("/sharpening/invoices", methods=["POST"])
def create_invoice():
    ctx = ladder.begin("BillingClerk")
    INVOICE_SPEC.validate(ctx.body)
    services.account_active(db.accounts.get(ctx.body["account_id"]))
    account = ladder.must_exist(db.accounts, ctx.body["account_id"], "Account")
    named_request = None
    if ctx.body.get("service_request_id"):
        named_request = ladder.must_exist(
            db.service_requests, ctx.body["service_request_id"], "ServiceRequest"
        )
        # Rung 13 / 14 on the request's billing and fulfilment axes.
        if named_request["billing_status"] == "CREDITED":
            raise ApiError("ERR_ALREADY_TERMINAL")
        if named_request["status"] != "COMPLETED":
            raise ApiError("ERR_INVALID_STATE", "The request is not COMPLETED.")

    mode = account["billing_mode"]
    period_raw = ctx.body.get("billing_period")
    # Rung 30.
    if mode == "PER_VISIT":
        if named_request is None or period_raw is not None:
            raise ApiError("ERR_INVOICE_SCOPE_MISMATCH")
    else:
        if period_raw is None or named_request is not None:
            raise ApiError("ERR_INVOICE_SCOPE_MISMATCH")
    # Rung 47.
    for existing in db.invoices.values():
        if existing["account_id"] == account["id"] and existing["status"] == "DRAFT":
            raise ApiError("ERR_DUPLICATE_DRAFT_INVOICE")

    if mode == "PER_VISIT":
        covered = [named_request]
    else:
        period = clockmod.parse_period(period_raw)
        covered = [
            r
            for r in db.service_requests.values()
            if r["account_id"] == account["id"]
            and r["status"] == "COMPLETED"
            and r["billing_status"] == "UNBILLED"
            and _in_period(r, period)
        ]
        covered.sort(key=lambda r: (r["created_at"], r["_seq"]))
    # Rung 48.
    for request_row in covered:
        if request_row["billing_status"] != "UNBILLED":
            raise ApiError("ERR_DUPLICATE_INVOICE")

    absorbed, consumption = _allowance_plan(covered)
    items = _covered_items(covered)
    amounts = _charged_amounts(items, absorbed)

    subscription_fee_line = None
    if mode == "MONTHLY_ROLLUP":
        subscription = services.account_subscription(account["id"])
        if subscription is not None:
            subscription_fee_line = subscription["effective_monthly_fee_cents"]

    # Rung 55 -- decided before anything is written.
    line_count = len(items) + sum(1 for i in items if amounts[i["id"]][1] > 0)
    if subscription_fee_line is not None:
        line_count += 1
    if line_count == 0:
        raise ApiError("ERR_EMPTY_INVOICE")

    invoice = services.new_invoice(
        account,
        service_request_id=named_request["id"] if named_request else None,
        billing_period=period_raw,
    )
    if subscription_fee_line is not None:
        services.append_line(
            invoice, "SUBSCRIPTION_FEE", "Subscription monthly fee", subscription_fee_line
        )
    for item in items:
        charged, part_fee = amounts[item["id"]]
        item["charged_service_cents"] = charged
        item["part_fee_cents"] = part_fee
        item["allowance_applied"] = item["id"] in absorbed
        touch(item)
        services.append_line(
            invoice, "SERVICE", "Sharpening service", charged, request_item_id=item["id"]
        )
    for item in items:
        _, part_fee = amounts[item["id"]]
        if part_fee > 0:
            services.append_line(
                invoice, "PART", "Parts", part_fee, request_item_id=item["id"]
            )

    for subscription_id, chosen in consumption.items():
        subscription = db.subscriptions[subscription_id]
        for item in chosen:
            services.append_allowance_entry(
                subscription, "CONSUMED", 1, "INVOICE", request_item_id=item["id"]
            )
        if chosen:
            subscription["allowance_remaining"] -= len(chosen)
            touch(subscription)

    for request_row in covered:
        request_row["billing_status"] = "INVOICED"
        request_row["_invoice_id"] = invoice["id"]
        touch(request_row)

    services.recompute_invoice(invoice)
    return envelope.created(ser.invoice(invoice))


# ---------------------------------------------------------------------------
# Invoice reads
# ---------------------------------------------------------------------------
@bp.route("/sharpening/invoices/<id>", methods=["GET"])
def get_invoice(id):
    ctx = ladder.begin("BillingClerk", "AccountOwner", "PlatformAdmin")
    row = ladder.must_exist(db.invoices, id, "Invoice")
    services.own_account(ctx, row["account_id"])
    return envelope.ok(ser.invoice(row))


@bp.route("/sharpening/invoices", methods=["GET"])
def list_invoices():
    ctx = ladder.begin("BillingClerk", "AccountOwner", "PlatformAdmin")
    ladder.check_query_enums(ctx.query, {"status": INVOICE_STATUSES})
    limit, offset = ladder.pagination(ctx.query)
    rows = list(db.invoices.values())
    for field in ("account_id", "service_request_id", "status", "billing_period"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.invoice(r) for r in page], limit, offset, total)


@bp.route("/sharpening/invoices/<id>/lines", methods=["GET"])
def list_invoice_lines(id):
    ctx = ladder.begin("BillingClerk", "AccountOwner", "PlatformAdmin")
    invoice = ladder.must_exist(db.invoices, id, "Invoice")
    limit, offset = ladder.pagination(ctx.query)
    services.own_account(ctx, invoice["account_id"])
    rows = ser.invoice_lines(invoice["id"])
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.invoice_line(r) for r in page], limit, offset, total)


@bp.route("/sharpening/invoice-lines/<id>", methods=["GET"])
def get_invoice_line(id):
    ctx = ladder.begin("BillingClerk", "AccountOwner", "PlatformAdmin")
    row = ladder.must_exist(db.invoice_lines, id, "InvoiceLine")
    invoice = db.invoices.get(row["invoice_id"])
    services.own_account(ctx, invoice["account_id"] if invoice else None)
    return envelope.ok(ser.invoice_line(row))


@bp.route("/sharpening/invoice-lines", methods=["GET"])
def list_lines():
    ctx = ladder.begin("BillingClerk", "AccountOwner", "PlatformAdmin")
    ladder.check_query_enums(ctx.query, {"source": LINE_SOURCES})
    limit, offset = ladder.pagination(ctx.query)
    rows = list(db.invoice_lines.values())
    for field in ("invoice_id", "request_item_id", "source_warranty_claim_id", "source"):
        value = ctx.query.get(field)
        if value is not None:
            rows = [r for r in rows if r[field] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.invoice_line(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /sharpening/invoices/{id}/issue
# ---------------------------------------------------------------------------
@bp.route("/sharpening/invoices/<id>/issue", methods=["POST"])
def issue_invoice(id):
    ladder.begin("BillingClerk")
    invoice = ladder.must_exist(db.invoices, id, "Invoice")
    services.account_active(db.accounts.get(invoice["account_id"]))
    if invoice["status"] in ("PAID", "VOID"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "The invoice is not DRAFT.")
    # Rung 55.
    if not services.invoice_has_lines(invoice):
        raise ApiError("ERR_EMPTY_INVOICE")
    invoice["status"] = "ISSUED"
    touch(invoice)
    return envelope.ok(ser.invoice(invoice))


# ---------------------------------------------------------------------------
# POST /sharpening/invoices/{id}/void
# ---------------------------------------------------------------------------
@bp.route("/sharpening/invoices/<id>/void", methods=["POST"])
def void_invoice(id):
    ladder.begin("BillingClerk")
    invoice = ladder.must_exist(db.invoices, id, "Invoice")
    services.account_active(db.accounts.get(invoice["account_id"]))
    if invoice["status"] in ("PAID", "VOID"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["status"] not in ("DRAFT", "ISSUED"):
        raise ApiError("ERR_INVALID_STATE", "The invoice cannot be voided.")
    if invoice["status"] == "ISSUED" and ser.invoice_amount_paid(invoice) != 0:
        raise ApiError("ERR_INVALID_STATE", "A partly paid invoice cannot be voided.")

    for request_row in services.invoice_covered_requests(invoice):
        if request_row["billing_status"] == "INVOICED":
            request_row["billing_status"] = "UNBILLED"
        request_row["_invoice_id"] = None
        for item in ser.request_items(request_row["id"]):
            if not item["allowance_applied"]:
                continue
            subscription = db.subscriptions.get(request_row["subscription_id"])
            if subscription is not None:
                services.append_allowance_entry(
                    subscription, "RESTORED", 1, "INVOICE_VOID", request_item_id=item["id"]
                )
                subscription["allowance_remaining"] += 1
                touch(subscription)
            item["allowance_applied"] = False
            touch(item)
        touch(request_row)
    invoice["status"] = "VOID"
    touch(invoice)
    return envelope.ok(ser.invoice(invoice))


# ---------------------------------------------------------------------------
# POST /sharpening/invoices/{id}/payments
# ---------------------------------------------------------------------------
@bp.route("/sharpening/invoices/<id>/payments", methods=["POST"])
def apply_payment(id):
    ctx = ladder.begin("AccountOwner", "BillingClerk")
    invoice = ladder.must_exist(db.invoices, id, "Invoice")
    PAYMENT_SPEC.validate(ctx.body)
    # Rung 8 -- a BillingClerk is opaque and skips this rung entirely.
    services.own_account(ctx, invoice["account_id"])
    services.account_active(db.accounts.get(invoice["account_id"]))
    # Rung 12.
    services.occ(ctx.body, "expected_invoice_version", invoice)
    if invoice["status"] in ("PAID", "VOID"):
        raise ApiError("ERR_ALREADY_TERMINAL")
    if invoice["status"] not in ("ISSUED", "PARTIALLY_PAID"):
        raise ApiError("ERR_INVALID_STATE", "The invoice is not payable in this state.")
    due = ser.invoice_amount_due(invoice)
    # Rung 18.
    if due < 1:
        raise ApiError("ERR_INVOICE_NOT_PAYABLE")
    # Rung 56.
    if ctx.body["amount_cents"] > due:
        raise ApiError("ERR_OVERPAYMENT")

    amount = ctx.body["amount_cents"]
    resulting = "PAID" if amount == due else "PARTIALLY_PAID"
    payment = stamp_new(
        {
            "invoice_id": invoice["id"],
            "amount_cents": amount,
            "method": ctx.body["method"],
            "applied_at": clockmod.now(),
            "resulting_invoice_status": resulting,
        },
        versioned=False,
    )
    db.payments[payment["id"]] = payment
    invoice["status"] = resulting
    touch(invoice)
    if resulting == "PAID":
        for request_row in services.invoice_covered_requests(invoice):
            if request_row["billing_status"] == "INVOICED":
                request_row["billing_status"] = "SETTLED"
                touch(request_row)
    return envelope.created(ser.payment(payment))


@bp.route("/sharpening/payments/<id>", methods=["GET"])
def get_payment(id):
    ctx = ladder.begin("BillingClerk", "AccountOwner")
    row = ladder.must_exist(db.payments, id, "Payment")
    invoice = db.invoices.get(row["invoice_id"])
    services.own_account(ctx, invoice["account_id"] if invoice else None)
    return envelope.ok(ser.payment(row))


@bp.route("/sharpening/payments", methods=["GET"])
def list_payments():
    ctx = ladder.begin("BillingClerk", "AccountOwner")
    limit, offset = ladder.pagination(ctx.query)
    rows = list(db.payments.values())
    value = ctx.query.get("invoice_id")
    if value is not None:
        rows = [r for r in rows if r["invoice_id"] == value]
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    page, total = ladder.paginate(rows, limit, offset)
    return envelope.listing([ser.payment(r) for r in page], limit, offset, total)
