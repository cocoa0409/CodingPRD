"""Settlement endpoints (PRD §3.8)."""
from flask import Blueprint, request

import db
from errors import err, ERR_INVALID_STATE, ERR_STALE_VERSION, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers, ledger

bp = Blueprint("settlements", __name__)


def _customer_of_settlement(settlement):
    res = db.reservations.get(settlement["reservation_id"])
    return res["customer_id"] if res else None


@bp.route("/settlements/<sid>", methods=["GET"])
def get_settlement(sid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    settlement = helpers.find("Settlement", sid)
    if role == "Customer" and user_id != _customer_of_settlement(settlement):
        raise err(ERR_FORBIDDEN, "Customer may only access their own settlements")
    return success(views.settlement_view(settlement))


@bp.route("/settlements", methods=["GET"])
def list_settlements():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.settlements.values())
    if role == "Customer":
        records = [s for s in records if _customer_of_settlement(s) == user_id]
    reservation_id = request.args.get("reservation_id")
    disposition = request.args.get("disposition")
    if reservation_id is not None:
        records = [s for s in records if s["reservation_id"] == reservation_id]
    if disposition is not None:
        records = [s for s in records if s["disposition"] == disposition]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.settlement_view(s) for s in page], limit, offset, total)


@bp.route("/settlements/<sid>/finalize", methods=["POST"])
def finalize_settlement(sid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    settlement = helpers.find("Settlement", sid)
    reservation = db.reservations.get(settlement["reservation_id"])

    # Finalize only when reservation is RETURNED or OVERDUE (PRD §3.8).
    if reservation is None or reservation["status"] not in ("RETURNED", "OVERDUE"):
        raise err(ERR_INVALID_STATE, "Reservation is not RETURNED or OVERDUE")

    # Post DEPOSIT_RELEASE for the un-applied portion of the deposit.
    refund = settlement["deposit_refund_cents"]
    if refund > 0:
        ledger.post(
            reservation["customer_id"],
            "DEPOSIT_RELEASE",
            -refund,
            reservation_id=reservation["id"],
        )

    reservation["status"] = "SETTLED"
    db.touch(reservation)
    return success(views.settlement_view(settlement))


@bp.route("/settlements/<sid>/waive-fee", methods=["POST"])
def waive_fee(sid):
    _, role = authenticate()
    require_role(role, {"StoreManager"})
    settlement = helpers.find("Settlement", sid)
    body = helpers.get_json_body()

    waive_amount_cents = helpers.as_int_min(body, "waive_amount_cents", 0)
    # OCC: expected_settlement_version must match (ERR_STALE_VERSION).
    expected = body.get("expected_settlement_version")
    if expected is None or expected != settlement["version"]:
        raise err(ERR_STALE_VERSION, "expected_settlement_version mismatch")

    reservation = db.reservations.get(settlement["reservation_id"])

    # FEE_WAIVE posting (negative magnitude); reduces net_charge_cents.
    ledger.post(
        reservation["customer_id"],
        "FEE_WAIVE",
        -waive_amount_cents,
        reservation_id=reservation["id"],
    )
    settlement["net_charge_cents"] = max(0, settlement["net_charge_cents"] - waive_amount_cents)
    db.touch(settlement)
    return success(views.settlement_view(settlement))
