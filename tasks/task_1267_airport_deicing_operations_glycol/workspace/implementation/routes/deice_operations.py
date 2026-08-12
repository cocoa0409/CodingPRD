"""DeiceOperation routes: get, list, start, complete, void."""
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc, derived

bp = Blueprint("deice_operations", __name__)


def _get_operation_or_404(oid):
    op = db.deice_operations.get(oid)
    if op is None:
        raise errors.not_found("operation not found")
    return op


@bp.route("/deice-ops/deice-operations/<oid>", methods=["GET"])
def get_operation(oid):
    middleware.require_roles(
        "StationAdmin", "PadOperator", "Inspector", "EnvironmentalOfficer", "BillingClerk"
    )
    op = _get_operation_or_404(oid)
    return response.success_object(serializers.deice_operation(op), 200)


@bp.route("/deice-ops/deice-operations", methods=["GET"])
def list_operations():
    middleware.require_roles(
        "StationAdmin", "PadOperator", "Inspector", "EnvironmentalOfficer", "BillingClerk"
    )
    limit, offset = util.get_pagination()
    request_id = request.args.get("request_id")
    station_id = request.args.get("station_id")
    pad_id = request.args.get("pad_id")
    tank_id = request.args.get("tank_id")
    parent_operation_id = request.args.get("parent_operation_id")
    status = request.args.get("status")
    items = list(db.deice_operations.values())
    if request_id is not None:
        items = [o for o in items if o["request_id"] == request_id]
    if station_id is not None:
        items = [o for o in items if o["station_id"] == station_id]
    if pad_id is not None:
        items = [o for o in items if o["pad_id"] == pad_id]
    if tank_id is not None:
        items = [o for o in items if o["tank_id"] == tank_id]
    if parent_operation_id is not None:
        items = [o for o in items if o.get("parent_operation_id") == parent_operation_id]
    if status is not None:
        items = [o for o in items if o["status"] == status]
    items.sort(key=lambda o: o["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.deice_operation(o) for o in page], limit, offset, total)


@bp.route("/deice-ops/deice-operations/<oid>/start", methods=["POST"])
def start_operation(oid):
    middleware.require_roles("PadOperator")
    op = _get_operation_or_404(oid)
    if op["status"] != "PLANNED":
        raise errors.invalid_state("operation must be PLANNED to start")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["oat_celsius"])
    oat_celsius = float(util.to_decimal(payload["oat_celsius"], "oat_celsius"))
    # Acceptance gate.
    acceptance_pass = False
    for ins in db.inspections.values():
        if ins["operation_id"] == op["id"] and ins["kind"] == "ACCEPTANCE" and ins["result"] == "PASS":
            acceptance_pass = True
            break
    if not acceptance_pass:
        raise errors.acceptance_required()
    req = db.deice_requests.get(op["request_id"])
    if req is None:
        raise errors.not_found("request not found")
    # Primary operations start while the request is ASSIGNED; rework children
    # (parent_operation_id non-null) start while the lineage request is
    # IN_PROGRESS — the rework lifecycle reuses the same request (PRD §3.6).
    if op.get("parent_operation_id") is None:
        if req["status"] != "ASSIGNED":
            raise errors.invalid_state("originating request must be ASSIGNED to start")
    else:
        if req["status"] != "IN_PROGRESS":
            raise errors.invalid_state(
                "rework operation requires the lineage request to be IN_PROGRESS"
            )
    # Holdover computation.
    tank = db.fluid_tanks.get(op["tank_id"])
    if tank is None:
        raise errors.not_found("tank not found")
    minutes, variant = calc.compute_holdover(tank, op["station_id"], oat_celsius)
    now = util.iso_now()
    op["oat_celsius"] = oat_celsius
    op["holdover_minutes"] = minutes
    op["holdover_variant"] = variant
    op["status"] = "SPRAYING"
    op["version"] += 1
    op["updated_at"] = now
    if op.get("parent_operation_id") is None:
        req["status"] = "IN_PROGRESS"
        req["version"] += 1
        req["updated_at"] = now
    pad = db.pads.get(op["pad_id"])
    if pad is not None:
        if pad["status"] != "OCCUPIED":
            pad["status"] = "OCCUPIED"
            pad["version"] += 1
            pad["updated_at"] = now
    return response.success_object(serializers.deice_operation(op), 200)


@bp.route("/deice-ops/deice-operations/<oid>/complete", methods=["POST"])
def complete_operation(oid):
    middleware.require_roles("PadOperator")
    op = _get_operation_or_404(oid)
    if op["status"] != "SPRAYING":
        raise errors.invalid_state("operation must be SPRAYING to complete")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["actual_liters", "collected_liters"])
    actual = util.to_decimal(payload["actual_liters"], "actual_liters")
    collected = util.to_decimal(payload["collected_liters"], "collected_liters")
    if actual <= 0:
        raise errors.invalid_request("actual_liters must be > 0")
    if collected < 0:
        raise errors.invalid_request("collected_liters must be >= 0")
    if collected > actual:
        raise errors.invalid_request("collected_liters must not exceed actual_liters")
    tank = db.fluid_tanks.get(op["tank_id"])
    if tank is None:
        raise errors.not_found("tank not found")
    if actual > Decimal(str(tank["on_hand_liters"])):
        raise errors.insufficient_fluid()
    # Snapshot storm-surcharge applicability at this moment (completion time):
    # an ACTIVE LEVEL_2/LEVEL_3 event at the station.
    event = derived.active_weather_event(op["station_id"])
    op["_storm_surcharge_applies"] = bool(
        event is not None and event["severity"] in ("LEVEL_2", "LEVEL_3")
    )
    tank["on_hand_liters"] = float(Decimal(str(tank["on_hand_liters"])) - actual)
    op["actual_liters"] = float(actual)
    op["collected_liters"] = float(collected)
    station = db.stations.get(op["station_id"])
    pct, flag = calc.collection_pct_and_flag(
        op["collected_liters"], op["actual_liters"], station["min_collection_pct"]
    )
    op["collection_pct"] = pct
    op["collection_flag"] = flag
    op["status"] = "AWAITING_INSPECTION"
    op["version"] += 1
    op["updated_at"] = util.iso_now()
    derived.recompute_tank_and_station(tank)
    return response.success_object(serializers.deice_operation(op), 200)


@bp.route("/deice-ops/deice-operations/<oid>/void", methods=["POST"])
def void_operation(oid):
    middleware.require_roles("PadOperator")
    op = _get_operation_or_404(oid)
    if op["status"] != "CLEARED":
        raise errors.invalid_state("operation must be CLEARED to void")
    for inv in db.invoices.values():
        if inv["operation_id"] == op["id"] and inv["status"] in ("DRAFT", "ISSUED"):
            raise errors.operation_invoiced()
    tank = db.fluid_tanks.get(op["tank_id"])
    if tank is not None:
        tank["on_hand_liters"] = float(
            Decimal(str(tank["on_hand_liters"])) + Decimal(str(op["actual_liters"]))
        )
        tank["updated_at"] = util.iso_now()
        derived.recompute_tank(tank)
    op["status"] = "VOIDED"
    op["version"] += 1
    op["updated_at"] = util.iso_now()
    derived.recompute_station_all(op["station_id"])
    return response.success_object(serializers.deice_operation(op), 200)
