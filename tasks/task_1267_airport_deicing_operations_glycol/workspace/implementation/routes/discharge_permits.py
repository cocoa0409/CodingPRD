"""DischargePermit and EffluentReading routes."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

import db
import errors
import middleware
import response
import serializers
import util
from services import derived

bp = Blueprint("discharge_permits", __name__)


@bp.route("/deice-ops/discharge-permits", methods=["POST"])
def create_permit():
    middleware.require_roles("StationAdmin")
    payload = request.get_json(silent=True) or {}
    util.require_fields(
        payload,
        [
            "station_id",
            "permit_number",
            "effective_from",
            "effective_to",
            "max_single_reading_mg_l",
            "rolling_window_days",
            "rolling_window_max_liters",
            "expected_station_version",
        ],
    )
    station = db.stations.get(payload["station_id"])
    if station is None:
        raise errors.not_found("station not found")
    expected_version = util.to_int(payload["expected_station_version"], "expected_station_version")
    if expected_version != station["version"]:
        raise errors.stale_version()
    permit_number = payload["permit_number"]
    if not isinstance(permit_number, str) or not permit_number:
        raise errors.invalid_request("permit_number must be a non-empty string")
    effective_from_dt = util.parse_iso(payload["effective_from"], "effective_from")
    effective_to_dt = util.parse_iso(payload["effective_to"], "effective_to")
    if not (effective_to_dt > effective_from_dt):
        raise errors.invalid_request("effective_to must be later than effective_from")
    max_single = float(util.to_decimal(payload["max_single_reading_mg_l"], "max_single_reading_mg_l"))
    rolling_window_days = util.to_int(payload["rolling_window_days"], "rolling_window_days")
    if rolling_window_days <= 0:
        raise errors.invalid_request("rolling_window_days must be positive")
    rolling_window_max = util.to_int(payload["rolling_window_max_liters"], "rolling_window_max_liters")
    if rolling_window_max <= 0:
        raise errors.invalid_request("rolling_window_max_liters must be positive")
    now = util.iso_now()
    # Supersede prior ACTIVE permit of this station.
    for p in db.discharge_permits.values():
        if p["station_id"] == station["id"] and p["status"] == "ACTIVE":
            p["status"] = "SUPERSEDED"
            p["version"] += 1
            p["updated_at"] = now
    permit = {
        "id": util.new_id(),
        "station_id": station["id"],
        "permit_number": permit_number,
        "effective_from": payload["effective_from"],
        "effective_to": payload["effective_to"],
        "max_single_reading_mg_l": max_single,
        "rolling_window_days": rolling_window_days,
        "rolling_window_max_liters": rolling_window_max,
        "status": "ACTIVE",
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    permit["_created_dt"] = db.get_clock()
    permit["_effective_to_dt"] = effective_to_dt
    permit["_effective_from_dt"] = effective_from_dt
    db.discharge_permits[permit["id"]] = permit
    station["version"] += 1
    station["updated_at"] = now
    derived.recompute_station_all(station["id"])
    return response.success_object(serializers.discharge_permit(permit), 201)


@bp.route("/deice-ops/discharge-permits/<pid>", methods=["GET"])
def get_permit(pid):
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    permit = db.discharge_permits.get(pid)
    if permit is None:
        raise errors.not_found("permit not found")
    return response.success_object(serializers.discharge_permit(permit), 200)


@bp.route("/deice-ops/discharge-permits", methods=["GET"])
def list_permits():
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    limit, offset = util.get_pagination()
    station_id = request.args.get("station_id")
    status = request.args.get("status")
    items = list(db.discharge_permits.values())
    if station_id is not None:
        items = [p for p in items if p["station_id"] == station_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    items.sort(key=lambda p: p["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.discharge_permit(p) for p in page], limit, offset, total)


@bp.route("/deice-ops/discharge-permits/<pid>/suspend", methods=["POST"])
def suspend_permit(pid):
    middleware.require_roles("EnvironmentalOfficer")
    permit = db.discharge_permits.get(pid)
    if permit is None:
        raise errors.not_found("permit not found")
    if permit["status"] != "ACTIVE":
        raise errors.invalid_state("permit must be ACTIVE to suspend")
    permit["status"] = "SUSPENDED"
    permit["version"] += 1
    permit["updated_at"] = util.iso_now()
    derived.recompute_station_all(permit["station_id"])
    return response.success_object(serializers.discharge_permit(permit), 200)


@bp.route("/deice-ops/discharge-permits/<pid>/reinstate", methods=["POST"])
def reinstate_permit(pid):
    middleware.require_roles("EnvironmentalOfficer")
    permit = db.discharge_permits.get(pid)
    if permit is None:
        raise errors.not_found("permit not found")
    if permit["status"] != "SUSPENDED":
        raise errors.invalid_state("permit must be SUSPENDED to reinstate")
    permit["status"] = "ACTIVE"
    permit["version"] += 1
    permit["updated_at"] = util.iso_now()
    derived.recompute_station_all(permit["station_id"])
    return response.success_object(serializers.discharge_permit(permit), 200)


@bp.route("/deice-ops/discharge-permits/<pid>/effluent-readings", methods=["POST"])
def create_reading(pid):
    middleware.require_roles("EnvironmentalOfficer")
    permit = db.discharge_permits.get(pid)
    if permit is None:
        raise errors.not_found("permit not found")
    if permit["status"] in ("SUPERSEDED", "EXPIRED"):
        raise errors.invalid_state("readings cannot be recorded on SUPERSEDED or EXPIRED permits")
    payload = request.get_json(silent=True) or {}
    util.require_fields(payload, ["measured_at", "concentration_mg_l", "volume_liters"])
    measured_dt = util.parse_iso(payload["measured_at"], "measured_at")
    concentration = float(util.to_decimal(payload["concentration_mg_l"], "concentration_mg_l"))
    volume = util.to_int(payload["volume_liters"], "volume_liters")
    if volume <= 0:
        raise errors.invalid_request("volume_liters must be positive")
    # Rolling window check: closed window [measured_at - days, measured_at].
    window_start = measured_dt - timedelta(days=permit["rolling_window_days"])
    window_sum = Decimal("0")
    for r in db.effluent_readings.values():
        if r["permit_id"] != permit["id"]:
            continue
        if window_start <= r["_measured_dt"] <= measured_dt:
            window_sum += Decimal(str(r["volume_liters"]))
    if window_sum + Decimal(volume) > Decimal(permit["rolling_window_max_liters"]):
        raise errors.permit_volume_exceeded()
    violation = concentration > permit["max_single_reading_mg_l"]
    now = util.iso_now()
    reading = {
        "id": util.new_id(),
        "permit_id": permit["id"],
        "measured_at": payload["measured_at"],
        "concentration_mg_l": concentration,
        "volume_liters": volume,
        "violation": violation,
        "created_at": now,
    }
    reading["_created_dt"] = db.get_clock()
    reading["_measured_dt"] = measured_dt
    db.effluent_readings[reading["id"]] = reading
    # Auto-suspend on severe breach: concentration strictly > 2x the limit.
    if concentration > 2 * permit["max_single_reading_mg_l"] and permit["status"] == "ACTIVE":
        permit["status"] = "SUSPENDED"
        permit["version"] += 1
        permit["updated_at"] = now
        derived.recompute_station_all(permit["station_id"])
    return response.success_object(serializers.effluent_reading(reading), 201)


@bp.route("/deice-ops/discharge-permits/<pid>/effluent-readings", methods=["GET"])
def list_readings(pid):
    middleware.require_roles("StationAdmin", "EnvironmentalOfficer")
    permit = db.discharge_permits.get(pid)
    if permit is None:
        raise errors.not_found("permit not found")
    limit, offset = util.get_pagination()
    items = [r for r in db.effluent_readings.values() if r["permit_id"] == pid]
    items.sort(key=lambda r: r["_created_dt"])
    total = len(items)
    page = items[offset:offset + limit]
    return response.success_list([serializers.effluent_reading(r) for r in page], limit, offset, total)
