"""Inspection routes: create (drives CLEARED / REWORK cascade), list by op."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import derived

bp = Blueprint("inspections", __name__)

KINDS = {"ACCEPTANCE", "POST_TREATMENT"}
RESULTS = {"PASS", "FAIL"}


@bp.route("/deice-ops/inspections", methods=["POST"])
def create_inspection():
    user_id, role = middleware.require_roles("Inspector")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["operation_id", "kind", "result"])
    op = db.deice_operations.get(payload["operation_id"])
    if op is None:
        raise errors.not_found("operation not found")
    kind = util.require_enum(payload["kind"], KINDS, "kind")
    result = util.require_enum(payload["result"], RESULTS, "result")
    findings = payload.get("findings", "")
    if not isinstance(findings, str):
        raise errors.invalid_request("findings must be a string")
    # Uniqueness of kind per operation.
    for ins in db.inspections.values():
        if ins["operation_id"] == op["id"] and ins["kind"] == kind:
            raise errors.inspection_exists()
    if kind == "ACCEPTANCE":
        if op["status"] != "PLANNED":
            raise errors.invalid_state("operation must be PLANNED for an acceptance inspection")
    else:  # POST_TREATMENT
        if op["status"] != "AWAITING_INSPECTION":
            raise errors.invalid_state(
                "operation must be AWAITING_INSPECTION for a post-treatment inspection"
            )
        # SoD: inspector must differ from acceptance inspector.
        acceptance = None
        for ins in db.inspections.values():
            if ins["operation_id"] == op["id"] and ins["kind"] == "ACCEPTANCE":
                acceptance = ins
                break
        if acceptance is not None and acceptance["inspector_id"] == user_id:
            raise errors.sod_violation(
                "post-treatment inspector must differ from acceptance inspector"
            )
    now = util.iso_now()
    inspection = {
        "id": util.new_id(),
        "operation_id": op["id"],
        "kind": kind,
        "result": result,
        "findings": findings,
        "inspector_id": user_id,
        "created_at": now,
    }
    inspection["_created_dt"] = db.get_clock()
    db.inspections[inspection["id"]] = inspection

    if kind == "POST_TREATMENT":
        if result == "PASS":
            _apply_clear(op)
        else:
            _apply_rework(op)
    return response.success_object(serializers.inspection(inspection), 201)


def _apply_clear(op):
    """POST_TREATMENT PASS: operation -> CLEARED; lineage request COMPLETED;
    pad AVAILABLE; pool credit via recompute."""
    now = util.iso_now()
    op["status"] = "CLEARED"
    op["version"] += 1
    op["updated_at"] = now
    req = db.deice_requests.get(op["request_id"])
    if req is not None and req["status"] != "COMPLETED":
        req["status"] = "COMPLETED"
        req["version"] += 1
        req["updated_at"] = now
        # Release reservation.
        tank_id = req.get("assigned_tank_id")
        req["assigned_tank_id"] = None
        req["fluid_reservation_status"] = "UNRESERVED"
        if tank_id and tank_id in db.fluid_tanks:
            derived.recompute_tank(db.fluid_tanks[tank_id])
    pad = db.pads.get(op["pad_id"])
    if pad is not None and pad["status"] == "OCCUPIED":
        pad["status"] = "AVAILABLE"
        pad["version"] += 1
        pad["updated_at"] = now
    tank = db.fluid_tanks.get(op["tank_id"])
    if tank is not None:
        derived.recompute_tank(tank)
    derived.recompute_station_all(op["station_id"])


def _apply_rework(op):
    """POST_TREATMENT FAIL: op -> REWORK_REQUIRED; auto-create rework child;
    tank reservation recomputed; station posture recomputed."""
    now = util.iso_now()
    op["status"] = "REWORK_REQUIRED"
    op["version"] += 1
    op["updated_at"] = now
    # Rework estimated_liters = ceil(actual_liters * 0.5)
    actual = Decimal(str(op["actual_liters"]))
    rework_est = int((actual * Decimal("0.5")).to_integral_value(rounding="ROUND_CEILING"))
    rework = {
        "id": util.new_id(),
        "request_id": op["request_id"],
        "station_id": op["station_id"],
        "pad_id": op["pad_id"],
        "tank_id": op["tank_id"],
        "parent_operation_id": op["id"],
        "window_start": op["window_start"],
        "window_end": op["window_end"],
        "oat_celsius": None,
        "estimated_liters": rework_est,
        "actual_liters": None,
        "collected_liters": None,
        "collection_pct": None,
        "collection_flag": None,
        "holdover_minutes": None,
        "holdover_variant": None,
        "status": "PLANNED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    rework["_created_dt"] = db.get_clock()
    rework["_window_start_dt"] = op.get("_window_start_dt")
    rework["_window_end_dt"] = op.get("_window_end_dt")
    rework["_storm_surcharge_applies"] = False
    db.deice_operations[rework["id"]] = rework
    # Pad stays OCCUPIED (physical aircraft still on pad through rework).
    tank = db.fluid_tanks.get(op["tank_id"])
    if tank is not None:
        derived.recompute_tank(tank)
    derived.recompute_station_all(op["station_id"])


@bp.route("/deice-ops/deice-operations/<oid>/inspections", methods=["GET"])
def list_inspections(oid):
    middleware.require_roles("StationAdmin", "PadOperator", "Inspector")
    op = db.deice_operations.get(oid)
    if op is None:
        raise errors.not_found("operation not found")
    limit, offset = util.get_pagination()
    kind = request.args.get("kind")
    items = [i for i in db.inspections.values() if i["operation_id"] == oid]
    if kind is not None:
        items = [i for i in items if i["kind"] == kind]
    items.sort(key=lambda i: i["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.inspection(i) for i in page], limit, offset, total)
