"""Refund request, decision and execution."""
from flask import Blueprint, g

from core import (
    REFUND_WINDOW_DAYS,
    authenticate,
    bps_of,
    clock_now,
    days,
    db,
    fail,
    filter_eq,
    get_body,
    new_record,
    ok,
    ok_list,
    ordered,
    pagination,
    paginate,
    parse_iso,
    public,
    req_enum,
    req_int,
    opt_str,
    tax_from_inclusive,
    touch,
)
from services import (
    executed_refunds,
    lookup,
    recompute_accrual,
    recompute_risk,
    write_entry,
)

bp = Blueprint("refunds", __name__)

REFUND_REASONS = {"BUYER_REQUEST", "FRAUD", "POLICY", "DUPLICATE"}
REFUNDABLE = {"CAPTURED", "PARTIALLY_REFUNDED"}


@bp.post("/api/purchases/<purchase_id>/refunds")
def request_refund(purchase_id):
    authenticate({"StorefrontService"})
    purchase = lookup("purchases", purchase_id)
    body = get_body()
    amount_cents = req_int(body, "amount_cents", minimum=1)
    reason = req_enum(body, "reason", REFUND_REASONS)

    if purchase["payment_status"] not in REFUNDABLE:
        fail("ERR_PURCHASE_NOT_REFUNDABLE", "Purchase is not refundable.")

    captured_at = parse_iso(purchase.get("captured_at")) if purchase.get("captured_at") else None
    if captured_at is None or clock_now() > captured_at + days(REFUND_WINDOW_DAYS):
        fail("ERR_REFUND_WINDOW_EXPIRED", "The refund window has expired.")

    remaining = purchase["gross_cents"] - purchase["refunded_gross_cents"]
    if amount_cents > remaining:
        fail("ERR_REFUND_EXCEEDS_REMAINING", "Refund exceeds the remaining refundable amount.")

    rec = new_record(
        purchase_id=purchase["id"],
        amount_cents=amount_cents,
        reason=reason,
        status="REQUESTED",
        decided_by_user_id=None,
        developer_net_reversal_cents=None,
        tax_reversal_cents=None,
    )
    db.refunds[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/refunds")
def list_refunds():
    authenticate({"StorefrontService", "FinanceOps", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.refunds)
    rows = filter_eq(rows, "purchase_id")
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/refunds/<refund_id>")
def read_refund(refund_id):
    authenticate({"StorefrontService", "FinanceOps", "PlatformAdmin", "Developer"})
    rec = lookup("refunds", refund_id)
    return ok(public(rec))


@bp.post("/api/refunds/<refund_id>/decide")
def decide_refund(refund_id):
    authenticate({"FinanceOps"})
    rec = lookup("refunds", refund_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"APPROVED", "DENIED"})
    opt_str(body, "note")
    if rec["status"] != "REQUESTED":
        fail("ERR_INVALID_STATE", "Refund is not REQUESTED.")
    rec["status"] = outcome
    rec["decided_by_user_id"] = g.user_id
    touch(rec)
    return ok(public(rec))


@bp.post("/api/refunds/<refund_id>/execute")
def execute_refund(refund_id):
    authenticate({"FinanceOps"})
    rec = lookup("refunds", refund_id)
    if rec["status"] != "APPROVED":
        fail("ERR_INVALID_STATE", "Refund is not APPROVED.")
    purchase = db.purchases.get(rec["purchase_id"])
    if purchase is None or purchase["payment_status"] not in REFUNDABLE:
        fail("ERR_PURCHASE_NOT_REFUNDABLE", "Purchase is not refundable.")

    jurisdiction = db.tax_jurisdictions.get(purchase["tax_jurisdiction_id"])
    rate = jurisdiction["vat_rate_bps"] if jurisdiction else 0

    prior = executed_refunds(purchase["id"])
    prior_tax = sum(r["tax_reversal_cents"] or 0 for r in prior)
    prior_net = sum(r["developer_net_reversal_cents"] or 0 for r in prior)

    if purchase["refunded_gross_cents"] + rec["amount_cents"] == purchase["gross_cents"]:
        tax_reversal = purchase["tax_cents"] - prior_tax
        net_reversal = (purchase["provisional_developer_net_cents"] or 0) - prior_net
    else:
        tax_reversal = tax_from_inclusive(rec["amount_cents"], rate)
        refund_base = rec["amount_cents"] - tax_reversal
        net_reversal = bps_of(refund_base, purchase["provisional_share_bps"] or 0)

    rec["status"] = "EXECUTED"
    rec["tax_reversal_cents"] = tax_reversal
    rec["developer_net_reversal_cents"] = net_reversal
    touch(rec)

    purchase["refunded_gross_cents"] += rec["amount_cents"]
    if purchase["refunded_gross_cents"] >= purchase["gross_cents"]:
        purchase["payment_status"] = "REFUNDED"
    else:
        purchase["payment_status"] = "PARTIALLY_REFUNDED"
    touch(purchase)

    dev = db.developers.get(purchase["developer_id"])
    if dev is not None:
        write_entry(dev["id"], "REFUND_REVERSAL", -net_reversal,
                    "Refund reversal of developer net", purchase_id=purchase["id"])
        recompute_accrual(dev)
        recompute_risk(dev)
        touch(dev)
    return ok(public(rec))
