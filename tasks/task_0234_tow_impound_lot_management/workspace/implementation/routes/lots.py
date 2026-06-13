"""ImpoundLot endpoints."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import get_json_body, require_role, require_user_context
from response import object_response
from services import rotation
from services.serialize import public
from validators import optional_int, require_int, require_str

bp = Blueprint("lots", __name__)


def get_lot_or_404(lot_id):
    lot = db.impound_lots.get(lot_id)
    if lot is None:
        raise ApiError("ERR_NOT_FOUND", "Impound lot not found")
    return lot


@bp.route("/impound-lots", methods=["POST"])
def create_lot():
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    body = get_json_body()
    name = require_str(body, "name")
    jurisdiction_code = require_str(body, "jurisdiction_code")
    daily_rate = require_int(body, "daily_storage_rate_cents", minimum=1)
    admin_fee = require_int(body, "admin_fee_cents", minimum=0)
    lien_fee = require_int(body, "lien_processing_fee_cents", minimum=0)
    statutory_hold_days = require_int(body, "statutory_hold_days", minimum=1)
    notice_grace_days = require_int(body, "notice_grace_days", minimum=0)
    max_offers = optional_int(body, "max_provider_concurrent_offers", default=2, minimum=1)

    lot = {
        "name": name,
        "jurisdiction_code": jurisdiction_code,
        "daily_storage_rate_cents": daily_rate,
        "admin_fee_cents": admin_fee,
        "lien_processing_fee_cents": lien_fee,
        "statutory_hold_days": statutory_hold_days,
        "notice_grace_days": notice_grace_days,
        "max_provider_concurrent_offers": max_offers,
        "rotation_cursor": 0,
        "status": "OPEN",
    }
    db.stamp_create(lot)
    db.impound_lots[lot["id"]] = lot
    return object_response(public(lot), 201)


@bp.route("/impound-lots/<lot_id>", methods=["GET"])
def get_lot(lot_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator", "PoliceOfficer", "TowProvider", "Claimant", "AuctionOfficial"})
    lot = get_lot_or_404(lot_id)
    return object_response(public(lot), 200)


@bp.route("/impound-lots/<lot_id>/suspend", methods=["POST"])
def suspend_lot(lot_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    lot = get_lot_or_404(lot_id)
    body = get_json_body()
    expected = require_int(body, "expected_lot_version")
    # state check before OCC? PRD ordering: structural state (priority 6) before
    # OCC (priority 15). Lot suspend has no defined "from-state" transition error,
    # but SUSPENDED -> SUSPENDED is undefined; treat re-suspend as invalid state.
    if lot["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", "Lot is not OPEN")
    if expected != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", "expected_lot_version does not match current version")
    lot["status"] = "SUSPENDED"
    db.touch(lot)
    return object_response(public(lot), 200)


@bp.route("/impound-lots/<lot_id>/dispatch-rotation", methods=["POST"])
def dispatch_rotation(lot_id):
    user_id, role = require_user_context()
    require_role(role, {"LotOperator"})
    lot = get_lot_or_404(lot_id)
    body = get_json_body()
    expected = require_int(body, "expected_lot_version")
    offer_ttl = optional_int(body, "offer_ttl_minutes", default=30, minimum=1)
    # OCC check (priority 15).
    if expected != lot["version"]:
        raise ApiError("ERR_STALE_LOT_VERSION", "expected_lot_version does not match current version")
    assignment = rotation.dispatch(lot, offer_ttl)
    db.touch(lot)  # increments lot version
    return object_response(public(assignment), 201)
