"""Debrief reports and role adjustments."""
from flask import Blueprint, request

import errors
from db import store
from middleware import require_roles
from response import success_object, success_list
from util import (
    get_body, require_field, optional_field, as_string, as_int, as_bool, as_enum,
    logical_now, format_iso,
)
from services.core import (
    make_record, touch, paginate, sort_by_created,
    serialize_debrief, serialize_adjustment,
    get_event_or_404, get_shift_or_404, get_volunteer_or_404,
    get_debrief_or_404, get_adjustment_or_404, get_role_or_404,
    NON_TERMINAL_SIGNUP,
)

bp = Blueprint("debriefs", __name__)
ANY = ("Anonymous", "Volunteer", "Captain", "GroupLeader", "VolunteerCoordinator", "EventDirector")

SKILLS = {"NONE", "MEDICAL", "BIKE_MARSHAL", "TIMING_TECH", "COURSE_MARSHAL"}


def _is_captain_of_shift(user_id, shift_id):
    return any(
        s["shift_id"] == shift_id
        and s["volunteer_id"] == user_id
        and s.get("is_captain")
        and s["status"] in NON_TERMINAL_SIGNUP | {"COMPLETED"}
        for s in store.signups.values()
    )


# ---------------- DebriefReport ----------------

@bp.post("/volunteer-ops/debrief-reports")
def create_debrief():
    user_id, role = require_roles("Captain")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    get_event_or_404(event_id)
    shift_id = as_string(require_field(body, "shift_id"), "shift_id")
    get_shift_or_404(shift_id)
    author_volunteer_id = as_string(require_field(body, "author_volunteer_id"), "author_volunteer_id")
    get_volunteer_or_404(author_volunteer_id)
    headcount_actual = as_int(require_field(body, "headcount_actual"), "headcount_actual")
    if headcount_actual < 0:
        raise errors.invalid_request("headcount_actual must be >= 0.")
    rating = as_int(require_field(body, "role_effectiveness_rating"), "role_effectiveness_rating")
    if not (1 <= rating <= 5):
        raise errors.invalid_request("role_effectiveness_rating must be between 1 and 5.")
    supply_shortage_flag = optional_field(body, "supply_shortage_flag", False)
    supply_shortage_flag = as_bool(supply_shortage_flag, "supply_shortage_flag")
    notes = optional_field(body, "notes", None)
    if notes is not None:
        notes = as_string(notes, "notes")

    # ownership: author must be the caller and captain of the shift
    if user_id != author_volunteer_id or not _is_captain_of_shift(user_id, shift_id):
        raise errors.not_resource_owner()

    rec = make_record({
        "event_id": event_id,
        "shift_id": shift_id,
        "author_volunteer_id": author_volunteer_id,
        "headcount_actual": headcount_actual,
        "role_effectiveness_rating": rating,
        "supply_shortage_flag": supply_shortage_flag,
        "notes": notes,
        "status": "DRAFT",
    })
    store.debrief_reports[rec["id"]] = rec
    return success_object(serialize_debrief(rec), status=201)


@bp.get("/volunteer-ops/debrief-reports")
def list_debriefs():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    shift_id = request.args.get("shift_id")
    author = request.args.get("author_volunteer_id")
    items = [
        d for d in store.debrief_reports.values()
        if (event_id is None or d["event_id"] == event_id)
        and (shift_id is None or d["shift_id"] == shift_id)
        and (author is None or d["author_volunteer_id"] == author)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_debrief(d) for d in page], limit, offset, total)


@bp.get("/volunteer-ops/debrief-reports/<debriefId>")
def get_debrief(debriefId):
    require_roles(*ANY)
    deb = get_debrief_or_404(debriefId)
    return success_object(serialize_debrief(deb))


@bp.post("/volunteer-ops/debrief-reports/<debriefId>/submit")
def submit_debrief(debriefId):
    user_id, role = require_roles("Captain")
    deb = get_debrief_or_404(debriefId)
    if deb["status"] != "DRAFT":
        raise errors.debrief_invalid_state()
    ev = store.events.get(deb["event_id"])
    if ev is None or ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Submit requires event status DEBRIEF_OPEN.")
    if user_id != deb["author_volunteer_id"]:
        raise errors.not_resource_owner()
    deb["status"] = "SUBMITTED"
    touch(deb)
    return success_object(serialize_debrief(deb))


@bp.post("/volunteer-ops/debrief-reports/<debriefId>/acknowledge")
def acknowledge_debrief(debriefId):
    require_roles("VolunteerCoordinator")
    deb = get_debrief_or_404(debriefId)
    if deb["status"] != "SUBMITTED":
        raise errors.debrief_invalid_state()
    deb["status"] = "ACKNOWLEDGED"
    touch(deb)
    return success_object(serialize_debrief(deb))


# ---------------- RoleAdjustment ----------------

@bp.post("/volunteer-ops/role-adjustments")
def create_adjustment():
    require_roles("VolunteerCoordinator")
    body = get_body()
    event_id = as_string(require_field(body, "event_id"), "event_id")
    ev = get_event_or_404(event_id)
    role_entry_id = as_string(require_field(body, "role_entry_id"), "role_entry_id")
    get_role_or_404(role_entry_id)
    debrief_report_id = as_string(require_field(body, "debrief_report_id"), "debrief_report_id")
    deb = get_debrief_or_404(debrief_report_id)

    # state: event must be DEBRIEF_OPEN; debrief at least SUBMITTED
    if ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Role adjustments require event status DEBRIEF_OPEN.")
    if deb["status"] not in {"SUBMITTED", "ACKNOWLEDGED"}:
        raise errors.debrief_invalid_state()

    proposed_min_age = optional_field(body, "proposed_min_age_years", None)
    if proposed_min_age is not None:
        proposed_min_age = as_int(proposed_min_age, "proposed_min_age_years")
    proposed_skill = optional_field(body, "proposed_required_skill", None)
    if proposed_skill is not None:
        proposed_skill = as_enum(proposed_skill, "proposed_required_skill", SKILLS)
    proposed_weight = optional_field(body, "proposed_credit_weight", None)
    if proposed_weight is not None:
        if isinstance(proposed_weight, bool) or not isinstance(proposed_weight, (int, float)):
            raise errors.invalid_request("proposed_credit_weight must be a number.")
        if not (proposed_weight > 0 and proposed_weight <= 3):
            raise errors.invalid_request("proposed_credit_weight must be > 0 and <= 3.")
    proposed_retire = optional_field(body, "proposed_retire", False)
    proposed_retire = as_bool(proposed_retire, "proposed_retire")

    rec = make_record({
        "event_id": event_id,
        "role_entry_id": role_entry_id,
        "debrief_report_id": debrief_report_id,
        "proposed_min_age_years": proposed_min_age,
        "proposed_required_skill": proposed_skill,
        "proposed_credit_weight": proposed_weight,
        "proposed_retire": proposed_retire,
        "status": "PROPOSED",
        "applied_at": None,
    })
    store.role_adjustments[rec["id"]] = rec
    return success_object(serialize_adjustment(rec), status=201)


@bp.get("/volunteer-ops/role-adjustments")
def list_adjustments():
    require_roles(*ANY)
    event_id = request.args.get("event_id")
    role_entry_id = request.args.get("role_entry_id")
    debrief_report_id = request.args.get("debrief_report_id")
    items = [
        a for a in store.role_adjustments.values()
        if (event_id is None or a["event_id"] == event_id)
        and (role_entry_id is None or a["role_entry_id"] == role_entry_id)
        and (debrief_report_id is None or a["debrief_report_id"] == debrief_report_id)
    ]
    items = sort_by_created(items)
    page, limit, offset, total = paginate(items, request.args)
    return success_list([serialize_adjustment(a) for a in page], limit, offset, total)


@bp.get("/volunteer-ops/role-adjustments/<adjustmentId>")
def get_adjustment(adjustmentId):
    require_roles(*ANY)
    adj = get_adjustment_or_404(adjustmentId)
    return success_object(serialize_adjustment(adj))


@bp.post("/volunteer-ops/role-adjustments/<adjustmentId>/approve")
def approve_adjustment(adjustmentId):
    require_roles("EventDirector")
    adj = get_adjustment_or_404(adjustmentId)
    if adj["status"] != "PROPOSED":
        raise errors.adjustment_invalid_state()
    ev = store.events.get(adj["event_id"])
    if ev is None or ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Approve requires event status DEBRIEF_OPEN.")
    deb = store.debrief_reports.get(adj["debrief_report_id"])
    if deb is None or deb["status"] != "ACKNOWLEDGED":
        raise errors.debrief_not_acknowledged()
    adj["status"] = "APPROVED"
    touch(adj)
    return success_object(serialize_adjustment(adj))


@bp.post("/volunteer-ops/role-adjustments/<adjustmentId>/reject")
def reject_adjustment(adjustmentId):
    require_roles("EventDirector")
    adj = get_adjustment_or_404(adjustmentId)
    if adj["status"] != "PROPOSED":
        raise errors.adjustment_invalid_state()
    ev = store.events.get(adj["event_id"])
    if ev is None or ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Reject requires event status DEBRIEF_OPEN.")
    adj["status"] = "REJECTED"
    touch(adj)
    return success_object(serialize_adjustment(adj))


@bp.post("/volunteer-ops/role-adjustments/<adjustmentId>/apply")
def apply_adjustment(adjustmentId):
    require_roles("VolunteerCoordinator")
    adj = get_adjustment_or_404(adjustmentId)
    if adj["status"] != "APPROVED":
        raise errors.adjustment_invalid_state()
    ev = store.events.get(adj["event_id"])
    if ev is None or ev["status"] != "DEBRIEF_OPEN":
        raise errors.invalid_event_state("Apply requires event status DEBRIEF_OPEN.")
    role = store.role_catalog_entries.get(adj["role_entry_id"])
    if role is None:
        raise errors.role_entry_not_found()
    body = get_body()
    expected = require_field(body, "expected_role_version")
    expected = as_int(expected, "expected_role_version")
    if expected != role["version"]:
        raise errors.stale_version()
    if adj.get("proposed_retire"):
        shift_ids = {s["id"] for s in store.shifts.values()
                     if s["role_entry_id"] == role["id"]}
        in_use = any(
            su["shift_id"] in shift_ids and su["status"] in NON_TERMINAL_SIGNUP
            for su in store.signups.values()
        )
        if in_use:
            raise errors.role_in_use()

    if adj["proposed_min_age_years"] is not None:
        role["min_age_years"] = adj["proposed_min_age_years"]
    if adj["proposed_required_skill"] is not None:
        role["required_skill"] = adj["proposed_required_skill"]
    if adj["proposed_credit_weight"] is not None:
        role["credit_weight"] = adj["proposed_credit_weight"]
    if adj.get("proposed_retire"):
        role["status"] = "RETIRED"
    touch(role)

    adj["status"] = "APPLIED"
    adj["applied_at"] = format_iso(logical_now())
    touch(adj)
    return success_object(serialize_adjustment(adj))
