"""Invoices: the priced line set, the statutory cap and the seven-step waterfall."""

from flask import Blueprint, request

import calc
import store
import validation as v
from envelope import created, ok, ok_list
from errors import ApiError
from events import append_event
from security import ALL_ROLES, actor, own_request

bp = Blueprint("invoices", __name__)


def _get_invoice(id):
    inv = store.invoices.get(id)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return inv


def _emit_line(inv, sequence, line_type, quantity, unit_millicents, amount_cents=None):
    line = store.common_fields(full=False)
    line["invoice_id"] = inv["id"]
    line["sequence"] = sequence
    line["line_type"] = line_type
    line["quantity"] = quantity
    line["unit_millicents"] = unit_millicents
    line["amount_cents"] = (
        calc.line_amount(quantity, unit_millicents) if amount_cents is None else amount_cents
    )
    store.invoice_lines[line["id"]] = line
    return line


def _lines_of(invoice_id):
    rows = [l for l in store.invoice_lines.values() if l["invoice_id"] == invoice_id]
    return sorted(rows, key=lambda l: l["sequence"])


@bp.post("/roi/invoices")
def create_invoice():
    uid, role = actor(["BillingClerk"])
    body = v.body()
    request_id = v.req_id(body, "request_id")
    expected_request_version = v.req_int(body, "expected_request_version")

    req = store.requests.get(request_id)
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    if expected_request_version != req["version"]:
        raise ApiError("ERR_STALE_REQUEST_VERSION")
    if req["fulfillment_status"] not in ("RELEASE_READY", "RELEASED"):
        raise ApiError("ERR_REQUEST_NOT_RELEASE_READY")
    if calc.redactions_open(req["id"]):
        raise ApiError("ERR_REDACTION_NOT_APPROVED")

    existing = calc.invoices_of(req["id"])
    for other in existing:
        if other["status"] in ("ISSUED", "PAID", "WAIVED"):
            raise ApiError("ERR_INVOICE_ALREADY_EXISTS")

    priced_pages = req.get("billable_page_count", 0)
    priced = calc.build_priced_lines(req, priced_pages)
    subtotal = calc.subtotal_of(priced)
    if req["billing_status"] == "NOT_BILLABLE" or subtotal == 0:
        raise ApiError("ERR_NOTHING_TO_INVOICE")

    # a DRAFT invoice never blocks: it is superseded by this re-price
    for other in existing:
        if other["status"] == "DRAFT":
            calc.void_invoice(other, "SUPERSEDED_BY_REPRICE")

    # step 1 — the penalty snapshot at the current logical clock
    calc.refresh_penalties(req, uid)
    penalty_snapshot = req.get("penalty_exposure_cents", 0)

    inv = store.common_fields()
    inv["request_id"] = req["id"]
    inv["variant"] = calc.invoice_variant(req)
    inv["billable_page_count_snapshot"] = priced_pages
    inv["subtotal_cents"] = subtotal
    # steps 3 to 5 — the cap bites only on strict excess
    applicable_cap = calc.applicable_cap(req)
    cap_adjustment = min(0, applicable_cap - subtotal)
    gross_total = subtotal + cap_adjustment
    inv["applicable_cap_cents"] = applicable_cap
    inv["cap_adjustment_cents"] = cap_adjustment
    inv["gross_total_cents"] = gross_total
    inv["penalty_snapshot_cents"] = penalty_snapshot

    # step 6 — the forfeiture is measured against the CAPPED figure
    rule = calc.rule_of_request(req)
    forfeiture = 0
    if rule is not None and rule["fee_forfeiture_on_late"] \
            and req["access_basis"] == "PATIENT_RIGHT_OF_ACCESS" and penalty_snapshot > 0:
        forfeiture = min(gross_total, penalty_snapshot)
    inv["forfeiture_cents"] = forfeiture
    inv["amount_due_cents"] = gross_total - forfeiture
    inv["paid_cents"] = 0
    inv["status"] = "DRAFT"
    inv["issued_at"] = None
    inv["settled_at"] = None
    inv["void_reason"] = None
    inv["waiver_reason"] = None
    store.invoices[inv["id"]] = inv

    sequence = 0
    for line_type, quantity, unit_millicents in priced:
        sequence += 1
        _emit_line(inv, sequence, line_type, quantity, unit_millicents)
    if cap_adjustment != 0:
        sequence += 1
        _emit_line(inv, sequence, "CAP_ADJUSTMENT", 1,
                   cap_adjustment * store.MILLICENTS_PER_CENT, cap_adjustment)
        append_event(req["id"], "FEE_CAP_APPLIED", uid,
                     detail="cap_adjustment_cents=%d" % cap_adjustment)
    if forfeiture > 0:
        sequence += 1
        _emit_line(inv, sequence, "LATE_FEE_FORFEITURE", 1,
                   -forfeiture * store.MILLICENTS_PER_CENT, -forfeiture)

    store.touch(req)
    return created(store.public(inv))


@bp.get("/roi/invoices/<id>")
def read_invoice(id):
    uid, role = actor(ALL_ROLES)
    inv = store.invoices.get(id)
    own_request(role, uid, store.requests.get(inv["request_id"]) if inv else None)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    return ok(store.public(inv))


@bp.get("/roi/invoices")
def list_invoices():
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    rows = store.ordered(list(store.invoices.values()))
    if role == "Requester":
        rows = [r for r in rows
                if (store.requests.get(r["request_id"]) or {}).get("requester_id") == uid]
    for field in ("request_id", "status"):
        value = request.args.get(field)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


@bp.get("/roi/invoices/<id>/lines")
def list_invoice_lines(id):
    uid, role = actor(ALL_ROLES)
    limit, offset = v.paging()
    inv = store.invoices.get(id)
    own_request(role, uid, store.requests.get(inv["request_id"]) if inv else None)
    if inv is None:
        raise ApiError("ERR_INVOICE_NOT_FOUND")
    rows = _lines_of(inv["id"])
    data, total = v.page(rows, limit, offset)
    return ok_list(data, limit, offset, total)


# ============================================================ issue
@bp.post("/roi/invoices/<id>/issue")
def issue_invoice(id):
    uid, role = actor(["BillingClerk"])
    v.body()

    inv = _get_invoice(id)
    # priority 13 — the invoice's own state is tested before the request's
    if inv["status"] != "DRAFT":
        raise ApiError("ERR_INVOICE_STATE_INVALID")

    req = store.requests.get(inv["request_id"])
    if req is None:
        raise ApiError("ERR_REQUEST_NOT_FOUND")
    if req["fulfillment_status"] not in ("RELEASE_READY", "RELEASED"):
        raise ApiError("ERR_REQUEST_NOT_RELEASE_READY")
    if inv["amount_due_cents"] <= 0:
        raise ApiError("ERR_NOTHING_TO_INVOICE")

    inv["status"] = "ISSUED"
    inv["issued_at"] = store.fmt(store.now())
    store.touch(inv)

    req["billing_status"] = "INVOICED"
    store.touch(req)
    calc.refresh_facility_money(req["facility_id"])
    return ok(store.public(inv))


# ============================================================ settlement
@bp.post("/roi/invoices/<id>/settlement")
def settle_invoice(id):
    uid, role = actor(["BillingClerk"])
    body = v.body()
    action = v.req_enum(body, "action", ["PAY", "WAIVE", "VOID"])
    amount_cents = v.opt_int(body, "amount_cents")
    reason = v.opt_str(body, "reason", max_len=500)

    inv = _get_invoice(id)

    # priority 13 — every settlement is gated on the invoice's own state
    if action in ("PAY", "WAIVE"):
        if inv["status"] != "ISSUED":
            raise ApiError("ERR_INVOICE_STATE_INVALID")
    else:
        if inv["status"] not in ("DRAFT", "ISSUED", "WAIVED"):
            raise ApiError("ERR_INVOICE_STATE_INVALID")

    # priority 46 — a payment settles the whole amount due or nothing at all;
    # an absent amount_cents is this same mismatch, not a schema violation
    if action == "PAY" and amount_cents != inv["amount_due_cents"]:
        raise ApiError("ERR_PAYMENT_AMOUNT_MISMATCH")

    req = store.requests.get(inv["request_id"])
    settled_at = store.fmt(store.now())

    if action == "PAY":
        inv["status"] = "PAID"
        inv["paid_cents"] = amount_cents
        inv["settled_at"] = settled_at
        if req is not None:
            req["billing_status"] = "PAID"
    elif action == "WAIVE":
        inv["status"] = "WAIVED"
        inv["waiver_reason"] = reason
        inv["settled_at"] = settled_at
        if req is not None:
            req["billing_status"] = "WAIVED"
    else:
        inv["status"] = "VOIDED"
        inv["void_reason"] = reason if reason is not None else "BILLING_CLERK_VOID"
        inv["paid_cents"] = 0
        inv["settled_at"] = settled_at
        if req is not None:
            req["billing_status"] = "PENDING_INVOICE"
    store.touch(inv)

    if req is not None:
        store.touch(req)
        # the ledger is re-derived, so each bucket reverses exactly
        calc.refresh_facility_money(req["facility_id"])
    return ok(store.public(inv))
