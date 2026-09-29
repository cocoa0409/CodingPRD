"""Dining venue registration, temperature compliance and seat availability."""
from flask import Blueprint

import serialize
from auth import authenticate
from clock import clock
from constants import CARE_LEVELS, MEAL_PERIODS, PROBE_POINTS, VENUE_KINDS
from db import base_row, db, snapshot, sort_created, touch_if_changed
from errors import api_error
from response import created, ok, ok_list
from routes.common import (
    BS, CS, DSM, EVERY_ROLE, PA, RD, SKL, get_community, get_venue,
)
from services import calc, derive
from shape import (
    body_json, opt_int, opt_str, paginate, q_bool, q_enum,
    q_required_date, q_required_enum, req_decimal, req_enum, req_enum_array,
    req_int, req_str,
)

bp = Blueprint("venues", __name__)


@bp.get("/venues/<venue_id>")
def read_venue(venue_id):
    authenticate(EVERY_ROLE)
    return ok(serialize.venue(get_venue(venue_id)))


@bp.get("/venues/<venue_id>/temperature-logs")
def list_temperature_logs(venue_id):
    authenticate([PA, RD, DSM, SKL])
    get_venue(venue_id)
    probe_point = q_enum("probe_point", PROBE_POINTS)
    in_range = q_bool("in_range")
    rows = [t for t in db.temperature_logs.values() if t["venue_id"] == venue_id]
    if probe_point is not None:
        rows = [t for t in rows if t["probe_point"] == probe_point]
    if in_range is not None:
        rows = [t for t in rows if t["in_range"] is in_range]
    window, pagination = paginate(sort_created(rows))
    return ok_list(serialize.many(serialize.temperature_log, window), pagination)


@bp.get("/venues/<venue_id>/seat-availability")
def seat_availability(venue_id):
    authenticate([PA, CS, RD, DSM, SKL, BS])
    venue = get_venue(venue_id)
    service_date_str, _service_date = q_required_date("service_date")
    meal_period = q_required_enum("meal_period", MEAL_PERIODS)
    committed, rows = calc.venue_committed_seats(venue_id, service_date_str, meal_period)
    return ok({
        "venue_id": venue_id,
        "service_date": service_date_str,
        "meal_period": meal_period,
        "seat_capacity": venue["seat_capacity"],
        "committed_seats": committed,
        "open_seats": max(0, venue["seat_capacity"] - committed),
        "blocking_reservation_ids": [r["id"] for r in rows],
    })


@bp.post("/venues")
def create_venue():
    authenticate([PA])
    body = body_json()
    community_id = req_str(body, "community_id")
    name = req_str(body, "name")
    venue_kind = req_enum(body, "venue_kind", VENUE_KINDS)
    seat_capacity = req_int(body, "seat_capacity", minimum=1)
    care_levels_served = req_enum_array(body, "care_levels_served", CARE_LEVELS)
    seating_turn = opt_int(body, "seating_turn_minutes", default=60, minimum=15)
    turnover_buffer = opt_int(body, "turnover_buffer_minutes", default=20, minimum=0)

    community = get_community(community_id)

    offered = community["care_levels_offered"]
    for level in care_levels_served:
        if level not in offered:
            raise api_error(
                "ERR_CROSS_COMMUNITY_REFERENCE",
                "care_levels_served must be a subset of the community's care_levels_offered",
            )

    row = base_row()
    row.update({
        "community_id": community_id,
        "name": name,
        "venue_kind": venue_kind,
        "seat_capacity": seat_capacity,
        "seating_turn_minutes": seating_turn,
        "turnover_buffer_minutes": turnover_buffer,
        "care_levels_served": care_levels_served,
        "temp_compliance_posture": "COMPLIANT",
        "consecutive_temp_violation_count": 0,
        "status": "OPEN",
    })
    db.venues[row["id"]] = row
    return created(serialize.venue(row))


@bp.post("/venues/<venue_id>/temperature-logs")
def log_temperature(venue_id):
    ctx = authenticate([SKL])
    body = body_json()
    probe_point = req_enum(body, "probe_point", PROBE_POINTS)
    temperature_f = req_decimal(body, "temperature_f", 1)
    corrective_action_code = opt_str(body, "corrective_action_code")

    venue = get_venue(venue_id)

    in_range = calc.temperature_in_range(probe_point, temperature_f)
    count = venue["consecutive_temp_violation_count"]
    if in_range and corrective_action_code is not None:
        count = 0
    elif not in_range:
        count = count + 1

    snap = snapshot(venue, ["consecutive_temp_violation_count", "temp_compliance_posture"])
    venue["consecutive_temp_violation_count"] = count
    venue["temp_compliance_posture"] = calc.posture_from_count(count)
    touch_if_changed(venue, snap)

    row = base_row(versioned=False)
    row.update({
        "venue_id": venue_id,
        "probe_point": probe_point,
        "temperature_f": temperature_f,
        "corrective_action_code": corrective_action_code,
        "logged_at_utc": clock.iso(),
        "in_range": in_range,
        "violation_sequence_index": count,
        "logged_by_user_id": ctx["user_id"],
    })
    db.temperature_logs[row["id"]] = row

    if venue["temp_compliance_posture"] == "SUSPENDED":
        derive.suspend_venue_reservations(venue)

    return created(serialize.temperature_log(row))
