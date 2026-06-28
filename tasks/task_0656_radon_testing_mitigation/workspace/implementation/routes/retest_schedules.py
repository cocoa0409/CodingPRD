"""RetestSchedule endpoints: get, list, fire-due, pause, resume (PRD §3.7)."""

from flask import Blueprint, request

from db import store, format_iso8601_millis
import errors
from errors import ApiError
from middleware import get_user_context, require_role, parse_pagination
from response import object_response, array_response
from services.domain import (
    _common_create_fields,
    public,
    touch,
    now_clock,
    add_days,
    recompute_property_derived,
)
from services.listing import paginate

bp = Blueprint("retest_schedules", __name__)

GET_ROLES = {"PlatformAdmin", "ComplianceOfficer", "ClientContact"}


@bp.route("/retest-schedules/<schedule_id>", methods=["GET"])
def get_schedule(schedule_id):
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    s = store.retest_schedules.get(schedule_id)
    if s is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Retest schedule not found.")
    return object_response(public(s), 200)


@bp.route("/retest-schedules", methods=["GET"])
def list_schedules():
    _, role = get_user_context()
    require_role(role, GET_ROLES)
    limit, offset = parse_pagination()
    filters = {
        "warranty_id": request.args.get("warranty_id"),
        "property_id": request.args.get("property_id"),
        "status": request.args.get("status"),
    }
    items, total = paginate(store.retest_schedules, filters, limit, offset)
    return array_response(items, limit, offset, total, 200)


@bp.route("/retest-schedules/<schedule_id>/fire-due", methods=["POST"])
def fire_due(schedule_id):
    _, role = get_user_context()
    require_role(role, {"ComplianceOfficer", "PlatformAdmin"})
    s = store.retest_schedules.get(schedule_id)
    if s is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Retest schedule not found.")

    # state (priority 5): schedule must be ARMED.
    if s["status"] != "ARMED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Schedule is not ARMED.")

    # clock >= next_due_utc (priority 15 -> ERR_RETEST_NOT_DUE).
    if now_clock() < s["_next_due_dt"]:
        raise ApiError(errors.ERR_RETEST_NOT_DUE, 409, "Retest is not yet due.")

    # parent warranty coverage ACTIVE (-> ERR_WARRANTY_NOT_ACTIVE).
    warranty = store.warranties.get(s["warranty_id"])
    if warranty is None or warranty["coverage_status"] != "ACTIVE":
        raise ApiError(errors.ERR_WARRANTY_NOT_ACTIVE, 409, "Parent warranty is not ACTIVE.")

    # Create a RECURRING RadonTest on the property in PLACED state.
    ts = now_clock()
    prop = store.properties.get(s["property_id"])
    test = _common_create_fields()
    test.update(
        {
            "property_id": s["property_id"],
            "inspector_id": None,
            "test_kind": "SHORT_TERM_48HR",
            "purpose": "RECURRING",
            "mitigation_job_id": None,
            "placement_start_utc": format_iso8601_millis(ts),
            "_placement_dt": ts,
            "placement_window_hours": 48,
            "hourly_readings": None,
            "lab_integrated_pci_l": None,
            "result_pci_l": None,
            "action_outcome": None,
            "warmup_hours_dropped": 4,
            "status": "PLACED",
        }
    )
    store.radon_tests[test["id"]] = test
    if prop is not None:
        recompute_property_derived(prop)

    # increment fired_count; set last_fired_utc; advance cadence from prior due date.
    s["fired_count"] += 1
    s["last_fired_utc"] = format_iso8601_millis(ts)
    s["_last_fired_dt"] = ts
    new_due = add_days(s["_next_due_dt"], s["interval_days"])
    s["_next_due_dt"] = new_due
    s["next_due_utc"] = format_iso8601_millis(new_due)
    touch(s)

    return object_response(public(s), 200)


@bp.route("/retest-schedules/<schedule_id>/pause", methods=["POST"])
def pause_schedule(schedule_id):
    _, role = get_user_context()
    require_role(role, {"ClientContact", "ComplianceOfficer"})
    s = store.retest_schedules.get(schedule_id)
    if s is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Retest schedule not found.")
    if s["status"] != "ARMED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only an ARMED schedule can be paused.")
    s["status"] = "PAUSED"
    touch(s)
    return object_response(public(s), 200)


@bp.route("/retest-schedules/<schedule_id>/resume", methods=["POST"])
def resume_schedule(schedule_id):
    _, role = get_user_context()
    require_role(role, {"ClientContact", "ComplianceOfficer"})
    s = store.retest_schedules.get(schedule_id)
    if s is None:
        raise ApiError(errors.ERR_NOT_FOUND, 404, "Retest schedule not found.")
    if s["status"] != "PAUSED":
        raise ApiError(errors.ERR_INVALID_STATE, 409, "Only a PAUSED schedule can be resumed.")
    s["status"] = "ARMED"
    touch(s)
    return object_response(public(s), 200)
