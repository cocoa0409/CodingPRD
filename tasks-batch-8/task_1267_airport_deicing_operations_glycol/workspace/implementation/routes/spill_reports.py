"""SpillReport routes: report, get, list, confirm, close."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import calc, derived

bp = Blueprint("spill_reports", __name__)


@bp.route("/deice-ops/spill-reports", methods=["POST"])
def create_spill():
    user_id, _ = middleware.require_roles("EnvironmentalOfficer")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["station_id", "tank_id", "quantity_liters", "occurred_at"])
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    tank = db.fluid_tanks.get(payload["tank_id"])
    if tank is None:
        raise errors.not_found("tank not found")
    if tank["station_id"] != station["id"]:
        raise errors.invalid_request("tank_id does not belong to station_id")
    quantity = float(util.to_decimal(payload["quantity_liters"], "quantity_liters"))
    if quantity <= 0:
        raise errors.invalid_request("quantity_liters must be positive")
    occurred_dt = util.parse_iso(payload["occurred_at"], "occurred_at")
    classification = "REPORTABLE" if quantity >= calc.REPORTABLE_SPILL_L else "MINOR"
    now = util.iso_now()
    spill = {
        "id": util.new_id(),
        "station_id": station["id"],
        "tank_id": tank["id"],
        "quantity_liters": quantity,
        "occurred_at": payload["occurred_at"],
        "classification": classification,
        "reporter_id": user_id,
        "confirmed_by": None,
        "closed_by": None,
        "status": "REPORTED",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    spill["_created_dt"] = db.get_clock()
    spill["_occurred_dt"] = occurred_dt
    db.spill_reports[spill["id"]] = spill
    return response.success_object(serializers.spill_report(spill), 201)


@bp.route("/deice-ops/spill-reports/<sid>", methods=["GET"])
def get_spill(sid):
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    spill = db.spill_reports.get(sid)
    if spill is None:
        raise errors.not_found("spill report not found")
    return response.success_object(serializers.spill_report(spill), 200)


@bp.route("/deice-ops/spill-reports", methods=["GET"])
def list_spills():
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    tank_id = request.args.get("tank_id")
    status = request.args.get("status")
    items = list(db.spill_reports.values())
    if station_id is not None:
        items = [s for s in items if s["station_id"] == station_id]
    if tank_id is not None:
        items = [s for s in items if s["tank_id"] == tank_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    items.sort(key=lambda s: s["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.spill_report(s) for s in page], limit, offset, total)


@bp.route("/deice-ops/spill-reports/<sid>/confirm", methods=["POST"])
def confirm_spill(sid):
    user_id, _ = middleware.require_roles("EnvironmentalOfficer")
    spill = db.spill_reports.get(sid)
    if spill is None:
        raise errors.not_found("spill report not found")
    if spill["status"] != "REPORTED":
        raise errors.invalid_state("spill must be REPORTED to confirm")
    deadline = spill["_occurred_dt"] + timedelta(minutes=120)
    if db.get_clock() > deadline:
        raise errors.spill_deadline_passed()
    spill["status"] = "CONFIRMED"
    spill["confirmed_by"] = user_id
    spill["version"] += 1
    spill["updated_at"] = util.iso_now()
    tank = db.fluid_tanks.get(spill["tank_id"])
    if tank is not None:
        new_on_hand = Decimal(str(tank["on_hand_liters"])) - Decimal(str(spill["quantity_liters"]))
        if new_on_hand < 0:
            new_on_hand = Decimal("0")
        tank["on_hand_liters"] = float(new_on_hand)
        tank["updated_at"] = util.iso_now()
        derived.recompute_tank(tank)
    derived.recompute_station_all(spill["station_id"])
    return response.success_object(serializers.spill_report(spill), 200)


@bp.route("/deice-ops/spill-reports/<sid>/close", methods=["POST"])
def close_spill(sid):
    user_id, _ = middleware.require_roles("EnvironmentalOfficer")
    spill = db.spill_reports.get(sid)
    if spill is None:
        raise errors.not_found("spill report not found")
    if spill["status"] != "CONFIRMED":
        raise errors.invalid_state("spill must be CONFIRMED to close")
    if spill["reporter_id"] == user_id:
        raise errors.sod_violation("spill reporter cannot close their own report")
    spill["status"] = "CLOSED"
    spill["closed_by"] = user_id
    spill["version"] += 1
    spill["updated_at"] = util.iso_now()
    return response.success_object(serializers.spill_report(spill), 200)
