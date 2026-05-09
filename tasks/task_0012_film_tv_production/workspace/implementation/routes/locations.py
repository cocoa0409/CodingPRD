"""Locations and location reservations."""
import copy
from flask import Blueprint, g

import errors as E
from db import store, init_common, touch
from clock import parse_iso8601
from middleware import require_roles
from response import ok_object
from body import (
    get_json_body, require_string, require_int, require_enum, optional_bool,
)
from services.occ import check_version
from services.serializers import serialize_location, serialize_reservation


bp = Blueprint("locations", __name__)


PERMIT_VALUES = {"NOT_REQUIRED", "PENDING", "APPROVED", "REJECTED", "EXPIRED"}
WEATHER_VALUES = {"UNKNOWN", "ACCEPTABLE", "BLOCKED"}
PERMIT_PATCH_VALUES = {"PENDING", "APPROVED", "REJECTED", "EXPIRED"}
WEATHER_PATCH_VALUES = {"ACCEPTABLE", "BLOCKED", "UNKNOWN"}


@bp.route("/locations", methods=["POST"])
@require_roles("ProductionCoordinator")
def create_location():
    body = get_json_body()
    name = require_string(body, "name")
    zone = require_string(body, "zone")
    requires_permit = optional_bool(body, "requires_permit", default=False)
    max_units = body.get("max_parallel_units", 1)
    if max_units is None:
        max_units = 1
    if not isinstance(max_units, int) or isinstance(max_units, bool) or max_units < 1:
        E.validation_err("max_parallel_units must be integer >= 1")
    rec = {
        "name": name,
        "zone": zone,
        "requires_permit": requires_permit,
        "max_parallel_units": max_units,
    }
    init_common(rec)
    store.locations[rec["id"]] = rec
    return ok_object(serialize_location(rec), http_status=201)


def _overlaps(a_start, a_end, b_start, b_end) -> bool:
    """Half-open interval overlap: [a_start, a_end) intersects [b_start, b_end)."""
    return a_start < b_end and b_start < a_end


@bp.route("/location-reservations", methods=["POST"])
@require_roles("ProductionCoordinator")
def create_reservation():
    body = get_json_body()
    location_id = require_string(body, "location_id")
    production_id = require_string(body, "production_id")
    scene_id = require_string(body, "scene_id")
    unit_label = require_string(body, "unit_label")
    start_at_str = require_string(body, "start_at")
    end_at_str = require_string(body, "end_at")

    with store.lock:
        loc = store.locations.get(location_id)
        if not loc:
            E.reference_mismatch(f"Location {location_id} not found")
        prod = store.productions.get(production_id)
        if not prod:
            E.reference_mismatch(f"Production {production_id} not found")
        scene = store.scenes.get(scene_id)
        if not scene:
            E.reference_mismatch(f"Scene {scene_id} not found")
        # Scene must belong to production
        if scene["production_id"] != production_id:
            E.reference_mismatch("Scene does not belong to the specified production")

        # Posture gate
        if prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")

        # Interval validation
        try:
            start_at = parse_iso8601(start_at_str)
            end_at = parse_iso8601(end_at_str)
        except Exception:
            E.invalid_interval("Bad datetime format")
        if start_at >= end_at:
            E.invalid_interval("start_at must be < end_at")
        sw_start = parse_iso8601(prod["shoot_window_start"])
        sw_end = parse_iso8601(prod["shoot_window_end"])
        if start_at < sw_start or end_at > sw_end:
            E.invalid_interval("Interval not within production shoot window")

        # Capacity & unit_label check
        active_overlap = []
        for r in store.location_reservations.values():
            if r["location_id"] != location_id:
                continue
            if r["status"] not in {"HELD", "CONFIRMED", "RESCHEDULING"}:
                continue
            r_start = parse_iso8601(r["start_at"])
            r_end = parse_iso8601(r["end_at"])
            if _overlaps(start_at, end_at, r_start, r_end):
                active_overlap.append(r)
        if len(active_overlap) >= loc["max_parallel_units"]:
            E.location_over_capacity("Max parallel units reached")
        for r in active_overlap:
            if r["unit_label"] == unit_label:
                E.location_over_capacity("Duplicate unit_label among overlapping reservations")

        permit_status = "PENDING" if loc.get("requires_permit") else "NOT_REQUIRED"
        rec = {
            "location_id": location_id,
            "production_id": production_id,
            "scene_id": scene_id,
            "unit_label": unit_label,
            "start_at": start_at_str,
            "end_at": end_at_str,
            "permit_status": permit_status,
            "weather_status": "UNKNOWN",
            "status": "HELD",
        }
        init_common(rec)
        store.location_reservations[rec["id"]] = rec
        return ok_object(serialize_reservation(rec), http_status=201)


def _get_reservation(rid):
    r = store.location_reservations.get(rid)
    if not r:
        E.not_found(f"Reservation {rid} not found")
    return r


@bp.route("/location-reservations/<rid>/confirm", methods=["POST"])
@require_roles("ProductionCoordinator")
def confirm_reservation(rid):
    body = get_json_body()
    with store.lock:
        r = _get_reservation(rid)
        check_version(r, body)
        prod = store.productions.get(r["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        if r["status"] != "HELD":
            E.invalid_state("confirm requires HELD")
        loc = store.locations.get(r["location_id"])
        if loc and loc.get("requires_permit") and r.get("permit_status") != "APPROVED":
            E.permit_required("Permit not approved")
        if r.get("weather_status") == "BLOCKED":
            E.weather_blocked("Weather BLOCKED on this reservation")
        # Capacity check repeats at confirm time
        start_at = parse_iso8601(r["start_at"])
        end_at = parse_iso8601(r["end_at"])
        active_overlap = []
        for o in store.location_reservations.values():
            if o["id"] == rid:
                continue
            if o["location_id"] != r["location_id"]:
                continue
            if o["status"] not in {"HELD", "CONFIRMED", "RESCHEDULING"}:
                continue
            o_start = parse_iso8601(o["start_at"])
            o_end = parse_iso8601(o["end_at"])
            if start_at < o_end and o_start < end_at:
                active_overlap.append(o)
        if loc and len(active_overlap) + 1 > loc["max_parallel_units"]:
            E.location_over_capacity("Max parallel units reached on confirm")
        r["status"] = "CONFIRMED"
        touch(r)
        return ok_object(serialize_reservation(r))


@bp.route("/location-reservations/<rid>/release", methods=["POST"])
@require_roles("ProductionCoordinator")
def release_reservation(rid):
    body = get_json_body()
    with store.lock:
        r = _get_reservation(rid)
        check_version(r, body)
        prod = store.productions.get(r["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        if r["status"] != "HELD":
            E.invalid_state("release (this endpoint) requires HELD")
        r["status"] = "RELEASED"
        touch(r)
        return ok_object(serialize_reservation(r))


@bp.route("/location-reservations/<rid>/permit-status", methods=["PATCH"])
@require_roles("ProductionCoordinator")
def patch_permit_status(rid):
    body = get_json_body()
    with store.lock:
        r = _get_reservation(rid)
        check_version(r, body)
        prod = store.productions.get(r["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        new_val = require_enum(body, "permit_status", PERMIT_PATCH_VALUES)
        r["permit_status"] = new_val
        touch(r)
        return ok_object(serialize_reservation(r))


@bp.route("/location-reservations/<rid>/weather-status", methods=["PATCH"])
@require_roles("ProductionCoordinator")
def patch_weather_status(rid):
    body = get_json_body()
    with store.lock:
        r = _get_reservation(rid)
        check_version(r, body)
        prod = store.productions.get(r["production_id"])
        if prod and prod.get("posture") == "FROZEN":
            E.posture_blocked("Production posture is FROZEN")
        new_val = require_enum(body, "weather_status", WEATHER_PATCH_VALUES)
        r["weather_status"] = new_val
        touch(r)
        return ok_object(serialize_reservation(r))
