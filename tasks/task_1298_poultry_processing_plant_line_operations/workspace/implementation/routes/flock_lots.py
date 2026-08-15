"""Flock lots: booking, receiving, settle/reopen."""

from flask import Blueprint

import db
from errors import (
    ApiError,
    ERR_NOT_FOUND,
    ERR_INVALID_REQUEST,
    ERR_SHIFT_CAPACITY_EXCEEDED,
    ERR_FLOCK_LOT_NOT_RECEIVABLE,
    ERR_LOT_NOT_SETTLABLE,
    ERR_INVALID_STATE_TRANSITION,
    ERR_INSUFFICIENT_PERMISSIONS,
)
from middleware import (
    require_roles,
    get_json_body,
    check_required,
    check_no_unknown,
    check_int,
    check_number,
    check_string,
)
from response import success_object
from services.core import (
    new_entity,
    _touch,
    lazy_lot,
    recompute_lot_aggregates,
    recompute_certified_yield_for_lot,
    apply_routing_flip,
)
from services.serializers import serialize_flock_lot

bp = Blueprint("flock_lots", __name__)

ALL_ROLES = (
    "PlantManager", "ShiftSupervisor", "ReceivingClerk", "LineOperator",
    "QATechnician", "SanitationLead", "USDAInspector", "OrderPlanner",
)


@bp.route("/poultry/flock-lots", methods=["POST"])
def create_flock_lot():
    require_roles("ReceivingClerk")
    body = get_json_body()
    check_no_unknown(
        body,
        {
            "lot_code", "grower_name", "booked_head_count",
            "expected_avg_live_weight_lb", "receiving_shift_id",
        },
    )
    check_required(
        body,
        {
            "lot_code", "grower_name", "booked_head_count",
            "expected_avg_live_weight_lb", "receiving_shift_id",
        },
    )
    check_string(body["lot_code"], "lot_code")
    check_string(body["grower_name"], "grower_name")
    check_int(body["booked_head_count"], "booked_head_count", min_value=1)
    check_number(
        body["expected_avg_live_weight_lb"], "expected_avg_live_weight_lb",
        min_value=0, exclusive_min=True,
    )
    check_string(body["receiving_shift_id"], "receiving_shift_id")

    shift = db.shifts.get(body["receiving_shift_id"])
    if not shift:
        raise ApiError(ERR_NOT_FOUND, "Receiving shift not found", 404)

    # Capacity: strictly above capacity rejects; equality allowed
    total_booked = sum(
        l["booked_head_count"]
        for l in db.flock_lots.values()
        if l["receiving_shift_id"] == shift["id"]
    )
    if total_booked + body["booked_head_count"] > shift["shackle_capacity_birds"]:
        raise ApiError(
            ERR_SHIFT_CAPACITY_EXCEEDED,
            "Booking would push the shift's total booked birds above shackle_capacity_birds",
            422,
        )

    lot = new_entity()
    lot.update({
        "lot_code": body["lot_code"],
        "grower_name": body["grower_name"],
        "booked_head_count": body["booked_head_count"],
        "expected_avg_live_weight_lb": body["expected_avg_live_weight_lb"],
        "receiving_shift_id": shift["id"],
        "status": "BOOKED",
        "head_count_received": None,
        "doa_count": None,
        "total_live_weight_lb": None,
        "birds_hung_total": 0,
        "condemned_accounted": 0,
        "carcasses_to_chill": 0,
        "carcass_weight_total_lb": 0,
        "provisional_yield_pct": None,
        "certified_yield_pct": None,
        "settled_at": None,
    })
    db.flock_lots[lot["id"]] = lot
    return success_object(serialize_flock_lot(lot), 201)


@bp.route("/poultry/flock-lots/<lot_id>", methods=["GET"])
def get_flock_lot(lot_id):
    require_roles(*ALL_ROLES)
    lot = db.flock_lots.get(lot_id)
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
    lazy_lot(lot)
    return success_object(serialize_flock_lot(lot))


@bp.route("/poultry/flock-lots/<lot_id>/receive", methods=["POST"])
def receive_flock_lot(lot_id):
    require_roles("ReceivingClerk")
    lot = db.flock_lots.get(lot_id)
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
    lazy_lot(lot)
    body = get_json_body()
    check_no_unknown(body, {"head_count_received", "doa_count", "total_live_weight_lb"})
    check_required(body, ["head_count_received", "doa_count", "total_live_weight_lb"])
    check_int(body["head_count_received"], "head_count_received", min_value=1)
    check_int(body["doa_count"], "doa_count", min_value=0)
    check_number(
        body["total_live_weight_lb"], "total_live_weight_lb", min_value=0, exclusive_min=True
    )

    if lot["status"] != "BOOKED":
        raise ApiError(
            ERR_FLOCK_LOT_NOT_RECEIVABLE, "Receive attempted on a lot not in BOOKED", 409
        )

    lot["head_count_received"] = body["head_count_received"]
    lot["doa_count"] = body["doa_count"]
    lot["total_live_weight_lb"] = body["total_live_weight_lb"]
    lot["status"] = "RECEIVED"
    _touch(lot)
    return success_object(serialize_flock_lot(lot))


@bp.route("/poultry/flock-lots/<lot_id>/advance", methods=["POST"])
def advance_flock_lot(lot_id):
    user_id, role = require_roles("ShiftSupervisor", "USDAInspector")
    lot = db.flock_lots.get(lot_id)
    if not lot:
        raise ApiError(ERR_NOT_FOUND, "Flock lot not found", 404)
    lazy_lot(lot)
    body = get_json_body()
    check_no_unknown(body, {"to_status"})
    check_required(body, ["to_status"])
    from middleware import check_enum
    check_enum(body["to_status"], ("SETTLED", "REOPENED"), "to_status")
    to_status = body["to_status"]

    if to_status == "SETTLED":
        if role != "ShiftSupervisor":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if lot["status"] not in ("CHILLED", "REOPENED"):
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION,
                "SETTLED permitted only from CHILLED or REOPENED",
                409,
            )
        # All condemnation records on this lot's runs CERTIFIED
        runs = [r for r in db.line_runs.values() if r["flock_lot_id"] == lot["id"]]
        for r in runs:
            for c in db.condemnation_records.values():
                if c["line_run_id"] == r["id"] and c["status"] != "CERTIFIED":
                    raise ApiError(
                        ERR_LOT_NOT_SETTLABLE,
                        "Settle attempted with uncertified condemnation records",
                        409,
                    )
        # At least one RECONCILED run
        if not any(r["status"] == "RECONCILED" for r in runs):
            raise ApiError(
                ERR_LOT_NOT_SETTLABLE, "Settle attempted with no RECONCILED run", 409
            )

        # Settlement computes the certified variant; PRD 3.4 does not list
        # settling among the provisional variant's recompute triggers.
        recompute_lot_aggregates(lot, recompute_provisional=False)
        old, new = recompute_certified_yield_for_lot(lot)
        lot["status"] = "SETTLED"
        lot["settled_at"] = db.clock_now()
        _touch(lot)
        apply_routing_flip(lot, old, new)
    elif to_status == "REOPENED":
        if role != "USDAInspector":
            raise ApiError(ERR_INSUFFICIENT_PERMISSIONS, "Role not permitted for this action", 403)
        if lot["status"] != "SETTLED":
            raise ApiError(
                ERR_INVALID_STATE_TRANSITION, "REOPENED permitted only from SETTLED", 409
            )
        lot["status"] = "REOPENED"
        _touch(lot)

    return success_object(serialize_flock_lot(lot))
