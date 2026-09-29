"""Long-term monitoring: laboratory window reservations and result filing."""

from flask import Blueprint

import db
import response
import validation as V
from errors import ApiError
from middleware import endpoint
from routes.common import acting_party_of_type, apply_filter, fetch
from services import calc, derive
from services.constants import (
    CONTROL_CONDITION,
    EVENT_STATUS,
    EVENT_TYPES,
)
from services.serialize import dump_event

bp = Blueprint("monitoring", __name__)

READ_ROLES = ["EnvironmentalConsultant", "StateAgencyReviewer", "Redeveloper",
              "Lender", "Insurer"]


@bp.post("/monitoring-events")
@endpoint(["EnvironmentalConsultant"])
def create_event():
    body = V.json_body()
    site_id = V.id_field(body, "site_id", True)
    laboratory_id = V.id_field(body, "laboratory_id", True)
    goal_id = V.id_field(body, "cleanup_goal_id", True)
    event_type = V.enum_field(body, "event_type", EVENT_TYPES, True)
    period_code = V.string_field(body, "monitoring_period_code", True, 1, 16)
    sample_date = V.date_field(body, "sample_date", True)
    window_start = V.datetime_field(body, "window_start", True)
    window_end = V.datetime_field(body, "window_end", True)
    control_id = V.id_field(body, "site_control_id", False)
    if window_end <= window_start:
        V.fail("Field window_end must be strictly after window_start.")
    if event_type == "CONTROL_INSPECTION" and control_id is None:
        V.fail("Field site_control_id is required for a CONTROL_INSPECTION event.")

    site = fetch("sites", site_id)
    lab = fetch("laboratories", laboratory_id)
    goal = fetch("cleanup_goals", goal_id)
    control = fetch("site_controls", control_id) if control_id else None
    derive.assert_not_frozen(site)

    overlapping = 0
    for other in db.all_rows("monitoring_events"):
        if (other["laboratory_id"] != lab["id"]
                or other["status"] not in ("SCHEDULED", "REPORTED")):
            continue
        other_start = db.parse_datetime(other["window_start"])
        other_end = db.parse_datetime(other["window_end"])
        if window_start < other_end and other_start < window_end:
            overlapping += 1
    if overlapping >= int(lab["concurrent_capacity"]):
        raise ApiError("ERR_LAB_CAPACITY_EXCEEDED",
                       "Laboratory %s already holds %d overlapping reservations "
                       "against a concurrent_capacity of %s."
                       % (lab["id"], overlapping, lab["concurrent_capacity"]))

    if goal["site_id"] != site["id"]:
        raise ApiError("ERR_PLAN_SITE_MISMATCH",
                       "The named cleanup goal belongs to a different parcel.")
    if control is not None and control["site_id"] != site["id"]:
        raise ApiError("ERR_PLAN_SITE_MISMATCH",
                       "The named site control belongs to a different parcel.")

    row = db.insert("monitoring_events", {
        "site_id": site["id"],
        "laboratory_id": lab["id"],
        "cleanup_goal_id": goal["id"],
        "site_control_id": control["id"] if control is not None else None,
        "event_type": event_type,
        "monitoring_period_code": period_code,
        "sample_date": sample_date.isoformat(),
        "window_start": db.iso_ts(window_start),
        "window_end": db.iso_ts(window_end),
        "status": "SCHEDULED",
        "result_value_ugl": None,
        "result_status": "PENDING",
        "control_condition": None,
    })
    return response.created(dump_event(row))


@bp.get("/monitoring-events")
@endpoint(READ_ROLES)
def list_events():
    rows = db.ordered(db.all_rows("monitoring_events"))
    rows = apply_filter(rows, "site_id", V.query_string("site_id"))
    rows = apply_filter(rows, "laboratory_id", V.query_string("laboratory_id"))
    rows = apply_filter(rows, "cleanup_goal_id", V.query_string("cleanup_goal_id"))
    rows = apply_filter(rows, "site_control_id", V.query_string("site_control_id"))
    rows = apply_filter(rows, "event_type",
                        V.query_enum("event_type", EVENT_TYPES))
    rows = apply_filter(rows, "status", V.query_enum("status", EVENT_STATUS))
    return response.list_response(rows, dump_event)


@bp.get("/monitoring-events/<event_id>")
@endpoint(READ_ROLES)
def get_event(event_id):
    return response.object_response(
        dump_event(fetch("monitoring_events", event_id)))


@bp.post("/monitoring-events/<event_id>/results")
@endpoint(["EnvironmentalConsultant"])
def file_results(event_id):
    body = V.json_body()
    result_value = V.number_field(body, "result_value_ugl", False, ge=0)
    condition = V.enum_field(body, "control_condition", CONTROL_CONDITION, False)

    event = fetch("monitoring_events", event_id)
    acting_party_of_type("CONSULTANT")
    site = db.get("sites", event["site_id"])
    if site is not None:
        derive.assert_not_frozen(site)
    if event["status"] == "REPORTED":
        raise ApiError("ERR_EVENT_ALREADY_REPORTED",
                       "Results have already been filed for this event.")
    if db.now() < db.parse_datetime(event["window_start"]):
        raise ApiError("ERR_RESULTS_BEFORE_WINDOW",
                       "The reserved laboratory window has not opened yet.")
    if event["event_type"] == "SAMPLING":
        if result_value is None:
            V.fail("Field result_value_ugl is required for a SAMPLING event.")
        condition = None
    else:
        if condition is None:
            V.fail("Field control_condition is required for a CONTROL_INSPECTION "
                   "event.")

    goal = db.get("cleanup_goals", event["cleanup_goal_id"])
    event["status"] = "REPORTED"
    event["control_condition"] = condition
    if event["event_type"] == "SAMPLING":
        event["result_value_ugl"] = result_value
        compliant = (goal is not None
                     and calc.D(result_value) <= calc.D(goal["goal_ugl"]))
        event["result_status"] = "COMPLIANT" if compliant else "EXCEEDANCE"
    db.touch(event)

    if goal is not None:
        derive.replay_attainment(goal)
        db.touch(goal)

    if event["result_status"] == "EXCEEDANCE" and event["site_control_id"]:
        control = db.get("site_controls", event["site_control_id"])
        if (control is not None and site is not None
                and control["status"] == "OPERATING"):
            derive.impair_control(control, site, revoke_letters=True,
                                  source_event_reason="CONTROL_FAILURE")
    return response.object_response(dump_event(event))
