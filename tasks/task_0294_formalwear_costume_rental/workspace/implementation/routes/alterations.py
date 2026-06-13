"""Alteration endpoints (PRD §3.5)."""
from flask import Blueprint, request

import db
from errors import err, ERR_INVALID_STATE, ERR_FORBIDDEN
from middleware import authenticate, require_role
from response import success, list_success
from services import views, helpers, ledger

bp = Blueprint("alterations", __name__)


def _owns_reservation(user_id, reservation_id):
    res = db.reservations.get(reservation_id)
    return res is not None and res["customer_id"] == user_id


@bp.route("/alterations", methods=["POST"])
def create_alteration():
    user_id, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    body = helpers.get_json_body()

    reservation_id = helpers.as_str(body, "reservation_id")
    reservation = helpers.find("Reservation", reservation_id)
    if role == "Customer" and user_id != reservation["customer_id"]:
        raise err(ERR_FORBIDDEN, "Customer may only request alterations on own reservations")
    kind = helpers.as_enum(body, "kind", helpers.ALTERATION_KINDS)
    fee_cents = helpers.as_int_min(body, "fee_cents", 0)

    alteration = {
        "reservation_id": reservation_id,
        "kind": kind,
        "fee_cents": fee_cents,
        "status": "REQUESTED",
    }
    db.stamp_create(alteration)
    db.alterations[alteration["id"]] = alteration
    return success(views.alteration_view(alteration), status=201)


@bp.route("/alterations/<aid>", methods=["GET"])
def get_alteration(aid):
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    alteration = helpers.find("Alteration", aid)
    if role == "Customer" and not _owns_reservation(user_id, alteration["reservation_id"]):
        raise err(ERR_FORBIDDEN, "Customer may only access alterations on own reservations")
    return success(views.alteration_view(alteration))


@bp.route("/alterations", methods=["GET"])
def list_alterations():
    user_id, role = authenticate()
    require_role(role, {"StoreManager", "StoreClerk", "Customer"})
    limit, offset = helpers.parse_pagination()
    records = list(db.alterations.values())
    if role == "Customer":
        records = [a for a in records if _owns_reservation(user_id, a["reservation_id"])]
    reservation_id = request.args.get("reservation_id")
    status = request.args.get("status")
    if reservation_id is not None:
        records = [a for a in records if a["reservation_id"] == reservation_id]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    page, total = helpers.paginate_sorted(records, limit, offset)
    return list_success([views.alteration_view(a) for a in page], limit, offset, total)


@bp.route("/alterations/<aid>/complete", methods=["POST"])
def complete_alteration(aid):
    _, role = authenticate()
    require_role(role, {"StoreClerk"})
    alteration = helpers.find("Alteration", aid)

    # State: must be REQUESTED (priority 6).
    if alteration["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Alteration is not REQUESTED")
    # Parent reservation must be CONFIRMED (PRD §3.5).
    reservation = db.reservations.get(alteration["reservation_id"])
    if reservation is None or reservation["status"] != "CONFIRMED":
        raise err(ERR_INVALID_STATE, "Parent reservation is not CONFIRMED")

    alteration["status"] = "COMPLETED"
    db.touch(alteration)

    # Charge the fee via reservation-scoped FEE_CHARGE.
    ledger.post(
        reservation["customer_id"],
        "FEE_CHARGE",
        alteration["fee_cents"],
        reservation_id=reservation["id"],
    )
    return success(views.alteration_view(alteration))


@bp.route("/alterations/<aid>/cancel", methods=["POST"])
def cancel_alteration(aid):
    user_id, role = authenticate()
    require_role(role, {"StoreClerk", "Customer"})
    alteration = helpers.find("Alteration", aid)
    if role == "Customer" and not _owns_reservation(user_id, alteration["reservation_id"]):
        raise err(ERR_FORBIDDEN, "Customer may only cancel alterations on own reservations")

    if alteration["status"] != "REQUESTED":
        raise err(ERR_INVALID_STATE, "Alteration is not REQUESTED")
    alteration["status"] = "CANCELLED"
    db.touch(alteration)
    return success(views.alteration_view(alteration))
