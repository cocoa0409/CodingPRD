"""Redelivery inspection, discrepancy pricing and return closure (PRD 3.10)."""

from flask import Blueprint, request

from db import db, touch, public
from errors import ApiError
from middleware import (
    require, check_ownership, scope_for_lessee,
    LESSOR_OPS, LESSEE, MAINTENANCE_CONTROLLER, BILLING_ADMIN,
)
from response import object_response, pagination, paged
from routes.common import find_leg, find_return, filtered
from services import calculations as C
from services import workflows as W
import validate as V

bp = Blueprint("returns", __name__)

INSPECTABLE_STATUSES = ("PENDING_INSPECTION", "DISCREPANCIES_OPEN")


@bp.get("/wetlease/return-conditions/<return_id>")
def get_return(return_id):
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSEE))
    record = find_return(return_id)
    check_ownership(actor, "return", record)
    return object_response(public(record))


@bp.get("/wetlease/return-conditions")
def list_returns():
    actor = require((LESSOR_OPS, MAINTENANCE_CONTROLLER, BILLING_ADMIN, LESSEE))
    limit, offset = pagination(request.args)
    rows = filtered(list(db.return_conditions.values()), request.args, {
        "lease_id": "lease_id",
        "aircraft_id": "aircraft_id",
        "repositioning_leg_id": "repositioning_leg_id",
        "status": "status",
    })
    rows = scope_for_lessee(actor, "return", rows)
    return paged(rows, limit, offset)


@bp.post("/wetlease/return-conditions/<return_id>/inspect")
def inspect_return(return_id):
    require((MAINTENANCE_CONTROLLER,))
    body = V.json_body()
    hours_at_return = V.req_num(body, "hours_since_check_at_return", minimum=0)
    cycles_at_return = V.req_int(body, "cycles_since_check_at_return", minimum=0)
    fuel_on_board = V.req_num(body, "fuel_on_board_kg", minimum=0)
    discrepancy_codes = V.opt_str_list(body, "discrepancy_codes", default=[])

    record = find_return(return_id)
    lease = db.leases.get(record["lease_id"])
    if lease is None:
        raise ApiError("ERR_LEASE_NOT_FOUND")

    first_inspection = record["status"] == "PENDING_INSPECTION"
    # PRD 2.8 step 9: lease state is tested before return-condition state.
    if first_inspection and lease["status"] != "TERMINATING":
        raise ApiError("ERR_LEASE_INVALID_STATE")
    if record["status"] not in INSPECTABLE_STATUSES:
        raise ApiError("ERR_RETURN_CONDITION_INVALID_STATE")

    priced = C.return_discrepancy_cost(
        lease, hours_at_return, cycles_at_return, fuel_on_board, discrepancy_codes)

    # Readings are stored exactly as recorded by the inspector.
    record["hours_since_check_at_return"] = hours_at_return
    record["cycles_since_check_at_return"] = cycles_at_return
    record["fuel_on_board_kg"] = fuel_on_board
    record["discrepancy_codes"] = list(discrepancy_codes)
    record["discrepancy_cost_cents"] = priced["discrepancy_cost_cents"]
    record["billed_to_lessee_cents"] = priced["billed_to_lessee_cents"]

    if first_inspection:
        if discrepancy_codes or priced["discrepancy_cost_cents"] > 0:
            record["status"] = "DISCREPANCIES_OPEN"
        else:
            record["status"] = "CLEARED"
    else:
        # A re-inspection clears the record once no code remains outstanding.
        if not discrepancy_codes:
            record["status"] = "CLEARED"
    touch(record)

    # The waterfall always restarts from the full original deposit.
    if (lease["return_deposit_applied_cents"] != priced["return_deposit_applied_cents"]
            or lease["return_deposit_remaining_cents"]
            != priced["return_deposit_remaining_cents"]):
        lease["return_deposit_applied_cents"] = priced["return_deposit_applied_cents"]
        lease["return_deposit_remaining_cents"] = priced["return_deposit_remaining_cents"]
        touch(lease)

    return object_response(public(record))


@bp.post("/wetlease/return-conditions/<return_id>/close")
def close_return(return_id):
    require((LESSOR_OPS,))
    body = V.json_body()
    repositioning_leg_id = V.req_str(body, "repositioning_leg_id")

    # Existence order of PRD 2.8 step 5: a leg identifier resolves before returnId.
    leg = find_leg(repositioning_leg_id)
    record = find_return(return_id)

    # DISCREPANCIES_OPEN deliberately passes this guard and falls through below.
    if record["status"] not in ("CLEARED", "DISCREPANCIES_OPEN"):
        raise ApiError("ERR_RETURN_CONDITION_INVALID_STATE")
    if record["status"] == "DISCREPANCIES_OPEN":
        raise ApiError("ERR_RETURN_DISCREPANCIES_OPEN")

    lease = db.leases.get(record["lease_id"])
    if lease is None:
        raise ApiError("ERR_LEASE_NOT_FOUND")

    if (leg["lease_id"] != record["lease_id"]
            or leg["leg_class"] != "REPOSITIONING"
            or leg["status"] != "COMPLETED"
            or leg["dest_icao"] != lease["redelivery_icao"]):
        raise ApiError("ERR_REPOSITIONING_LEG_INCOMPLETE")

    record["repositioning_leg_id"] = leg["id"]
    record["status"] = "CLOSED"
    touch(record)

    if lease["status"] == "TERMINATING":
        lease["status"] = "RETURNED"
        lease["suspension_reason"] = None
        touch(lease)
        W.release_airframe(lease)
        W.revoke_qualifications(lease)

    return object_response(public(record))
