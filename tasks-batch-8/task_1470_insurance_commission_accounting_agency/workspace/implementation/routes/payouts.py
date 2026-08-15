"""ProducerPayout endpoints (create carries OCC on Producer.version)."""
from flask import Blueprint

from db import DB, now_iso
from errors import ApiError
from middleware import auth, ADMIN_ACCT, ALL_ROLES
from response import ok
from services import (
    has_pending_chargebacks,
    new_resource,
    producer_balance_cents,
    ser_payout,
    touch,
)
from util import apply_filters, as_pos_int, get_body, is_int, req, respond_list

bp = Blueprint("payouts", __name__)


@bp.post("/agency/producers/<producerId>/payouts")
def create_payout(producerId):
    auth(ADMIN_ACCT)
    producer = DB["producers"].get(producerId)
    if producer is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Producer not found")
    data = get_body()
    # Priority 4: optimistic concurrency on Producer.version.
    ev = data.get("expected_producer_version")
    if is_int(ev) and ev != producer["version"]:
        raise ApiError(
            "ERR_STALE_VERSION", 412, "expected_producer_version does not match current version"
        )
    # Priority 5: compliance gate (tax hold beats producer-active per PRD 2.9).
    if not producer["tax_form_on_file"]:
        raise ApiError("ERR_PRODUCER_TAX_HOLD", 409, "Producer has no tax form on file")
    # Priority 7: cross-entity state.
    if producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", 409, "Producer is not ACTIVE")
    # Priority 9: fiscal limits.
    if has_pending_chargebacks(producer["id"]):
        raise ApiError(
            "ERR_OUTSTANDING_CHARGEBACK", 409, "Producer has PENDING chargebacks"
        )
    amount = data.get("amount_cents")
    if is_int(amount) and amount > 0 and amount > producer_balance_cents(producer["id"]):
        raise ApiError(
            "ERR_PAYOUT_EXCEEDS_BALANCE", 409, "Payout exceeds commission_balance_cents"
        )
    # Priority 10: shape.
    amount = as_pos_int(req(data, "amount_cents"), "amount_cents")
    if not is_int(ev):
        raise ApiError(
            "ERR_INVALID_REQUEST", 400, "Field expected_producer_version must be an integer"
        )
    payout = new_resource({
        "producer_id": producer["id"],
        "amount_cents": amount,
        "status": "INITIATED",
        "paid_at": None,
    })
    DB["payouts"][payout["id"]] = payout
    # Payout creation advances the producer's version by one.
    touch(producer)
    return ok(ser_payout(payout), 201)


@bp.get("/agency/payouts")
def list_payouts():
    auth(ALL_ROLES)
    items = apply_filters(
        DB["payouts"].values(), {"producer_id": "producer_id", "status": "status"}
    )
    return respond_list(items, ser_payout)


@bp.get("/agency/payouts/<payoutId>")
def get_payout(payoutId):
    auth(ALL_ROLES)
    p = DB["payouts"].get(payoutId)
    if p is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Payout not found")
    return ok(ser_payout(p))


@bp.post("/agency/payouts/<payoutId>/mark-paid")
def mark_payout_paid(payoutId):
    auth(ADMIN_ACCT)
    payout = DB["payouts"].get(payoutId)
    if payout is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Payout not found")
    # Priority 4: state.
    if payout["status"] != "INITIATED":
        raise ApiError("ERR_INVALID_STATE", 409, "Payout is not INITIATED")
    producer = DB["producers"].get(payout["producer_id"])
    # Priority 7: producer still ACTIVE.
    if producer is None or producer["status"] != "ACTIVE":
        raise ApiError("ERR_PRODUCER_NOT_ACTIVE", 409, "Producer is not ACTIVE")
    # Priority 9: amount must still fit the current balance.
    if payout["amount_cents"] > producer_balance_cents(producer["id"]):
        raise ApiError(
            "ERR_PAYOUT_EXCEEDS_BALANCE", 409, "Payout exceeds commission_balance_cents"
        )
    payout["status"] = "PAID"
    payout["paid_at"] = now_iso()
    touch(payout)
    return ok(ser_payout(payout))
