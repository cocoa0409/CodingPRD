"""Chargebacks: representment, resolution and the compensating reversal."""
from flask import Blueprint

from core import (
    CHARGEBACK_REPRESENT_WINDOW_DAYS,
    authenticate,
    clock_now,
    days,
    db,
    fail,
    filter_eq,
    get_body,
    iso,
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
    req_str,
    touch,
)
from services import (
    executed_refunds,
    lookup,
    recompute_accrual,
    recompute_risk,
    write_entry,
)

bp = Blueprint("chargebacks", __name__)


@bp.post("/api/purchases/<purchase_id>/chargebacks")
def create_chargeback(purchase_id):
    authenticate({"StorefrontService"})
    purchase = lookup("purchases", purchase_id)
    body = get_body()
    network_case_ref = req_str(body, "network_case_ref")
    amount_cents = req_int(body, "amount_cents", minimum=1)
    for existing in ordered(db.chargebacks):
        if existing["network_case_ref"] == network_case_ref:
            fail("ERR_INVALID_REQUEST", "network_case_ref must be unique.")
    rec = new_record(
        purchase_id=purchase["id"],
        network_case_ref=network_case_ref,
        amount_cents=amount_cents,
        status="RECEIVED",
        received_at=iso(clock_now()),
        clawback_cents=0,
    )
    db.chargebacks[rec["id"]] = rec
    return ok(public(rec), 201)


@bp.get("/api/chargebacks")
def list_chargebacks():
    authenticate({"StorefrontService", "FinanceOps", "PlatformAdmin", "Developer"})
    limit, offset = pagination()
    rows = ordered(db.chargebacks)
    rows = filter_eq(rows, "purchase_id")
    rows = filter_eq(rows, "status")
    items, total = paginate(rows, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.get("/api/chargebacks/<chargeback_id>")
def read_chargeback(chargeback_id):
    authenticate({"StorefrontService", "FinanceOps", "PlatformAdmin", "Developer"})
    rec = lookup("chargebacks", chargeback_id)
    return ok(public(rec))


@bp.post("/api/chargebacks/<chargeback_id>/represent")
def represent(chargeback_id):
    authenticate({"FinanceOps"})
    rec = lookup("chargebacks", chargeback_id)
    body = get_body()
    req_str(body, "evidence_ref")
    if rec["status"] != "RECEIVED":
        fail("ERR_INVALID_STATE", "Chargeback is not RECEIVED.")
    received_at = parse_iso(rec["received_at"])
    if clock_now() >= received_at + days(CHARGEBACK_REPRESENT_WINDOW_DAYS):
        fail("ERR_REPRESENTMENT_WINDOW_EXPIRED", "The representment window has closed.")
    rec["status"] = "REPRESENTED"
    touch(rec)
    return ok(public(rec))


@bp.post("/api/chargebacks/<chargeback_id>/resolve")
def resolve(chargeback_id):
    authenticate({"FinanceOps"})
    rec = lookup("chargebacks", chargeback_id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"WON", "LOST"})
    if rec["status"] not in ("RECEIVED", "REPRESENTED"):
        fail("ERR_INVALID_STATE", "Chargeback is not resolvable from its current state.")

    if outcome == "WON":
        rec["status"] = "WON"
        touch(rec)
        return ok(public(rec))

    purchase = db.purchases.get(rec["purchase_id"])
    if purchase is None or purchase["payment_status"] not in ("CAPTURED", "PARTIALLY_REFUNDED"):
        fail("ERR_INVALID_STATE", "Purchase is not in a chargeback-eligible state.")

    prior_net = sum(
        r["developer_net_reversal_cents"] or 0 for r in executed_refunds(purchase["id"])
    )
    clawback = max(0, (purchase["provisional_developer_net_cents"] or 0) - prior_net)

    rec["status"] = "LOST"
    rec["clawback_cents"] = clawback
    touch(rec)

    purchase["payment_status"] = "CHARGED_BACK"
    purchase["settlement_status"] = "CLAWED_BACK"
    touch(purchase)

    dev = db.developers.get(purchase["developer_id"])
    if dev is not None:
        write_entry(dev["id"], "CLAWBACK", -clawback,
                    "Chargeback clawback of developer net", purchase_id=purchase["id"])
        recompute_accrual(dev)
        if dev["negative_balance_cents"] > 0:
            dev["payout_hold"] = True
        recompute_risk(dev)
        touch(dev)
    return ok(public(rec))


@bp.post("/api/chargebacks/<chargeback_id>/reverse")
def reverse(chargeback_id):
    authenticate({"FinanceOps"})
    rec = lookup("chargebacks", chargeback_id)
    body = get_body()
    req_str(body, "reason")
    if rec["status"] != "LOST":
        fail("ERR_INVALID_STATE", "Chargeback is not LOST.")

    rec["status"] = "REVERSED"
    touch(rec)

    purchase = db.purchases.get(rec["purchase_id"])
    if purchase is not None:
        purchase["payment_status"] = (
            "CAPTURED" if purchase["refunded_gross_cents"] == 0 else "PARTIALLY_REFUNDED"
        )
        purchase["settlement_status"] = "ACCRUED"
        touch(purchase)
        dev = db.developers.get(purchase["developer_id"])
        if dev is not None:
            write_entry(dev["id"], "CLAWBACK_REVERSAL", rec["clawback_cents"],
                        "Chargeback reversal credit", purchase_id=purchase["id"])
            recompute_accrual(dev, recompute_negative_balance=True)
            if dev["negative_balance_cents"] == 0:
                dev["payout_hold"] = False
            recompute_risk(dev)
            touch(dev)
    return ok(public(rec))
