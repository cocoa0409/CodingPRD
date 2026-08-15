"""Survey invites, responses, and reminder events (PRD §3.4)."""

from flask import Blueprint, request

from db import db, touch, public, stamp_new_immutable
from errors import (
    err, ERR_VALIDATION, ERR_NOT_FOUND, ERR_INVALID_STATE,
    ERR_INVITE_OWNERSHIP, ERR_ANSWERS_INCOMPLETE, ERR_WINDOW_VIOLATION,
)
from middleware import (
    require_roles, parse_pagination, paginate, get_json_body, require_fields,
    optional_fields_present, as_int, as_string,
)
from response import success_object, success_list
from services.domain import recompute_cycle_counters

bp = Blueprint("invites", __name__)

INVITE_STATUSES = {"INVITED", "REMINDED", "SUBMITTED", "PARTIAL", "EXPIRED"}


def _get_invite_or_404(invite_id):
    iv = db.survey_invites.get(invite_id)
    if iv is None:
        raise err(ERR_NOT_FOUND, "survey invite not found", 404)
    return iv


def _validate_answers(body, cycle):
    """Parse and shape-check the answers array; returns list of answer dicts."""
    answers = body.get("answers")
    if not isinstance(answers, list):
        raise err(ERR_VALIDATION, "answers must be an array", 400)
    cycle_items = {ci["id"]: ci for ci in db.cycle_items.values()
                   if ci["cycle_id"] == cycle["id"]}
    seen = set()
    parsed = []
    for ans in answers:
        if not isinstance(ans, dict):
            raise err(ERR_VALIDATION, "each answer must be an object", 400)
        if "cycle_item_id" not in ans or "score" not in ans:
            raise err(ERR_VALIDATION, "answer requires cycle_item_id and score", 400)
        ci_id = ans["cycle_item_id"]
        if not isinstance(ci_id, str) or ci_id not in cycle_items:
            raise err(ERR_VALIDATION, "answer references unknown cycle item", 400)
        if ci_id in seen:
            raise err(ERR_VALIDATION, "duplicate answer for cycle item", 400)
        seen.add(ci_id)
        score = as_int(ans["score"], "score")
        if score < 1 or score > 5:
            raise err(ERR_VALIDATION, "score must be an integer 1..5", 400)
        comment = ans.get("comment")
        if comment is not None:
            as_string(comment, "comment")
        parsed.append({"cycle_item_id": ci_id, "score": score, "comment": comment})
    return parsed, cycle_items


def _check_submit_window(cycle):
    """Submit requires cycle OPEN and clock < closes_at."""
    if cycle["status"] != "OPEN":
        raise err(ERR_INVALID_STATE,
                  f"cannot submit against a cycle in status {cycle['status']}", 409)
    if db.clock >= cycle["_closes_at"]:
        raise err(ERR_WINDOW_VIOLATION, "submission window has closed", 422)


@bp.get("/engagement/survey-invites")
def list_invites():
    require_roles("HRAdmin", "PeopleAnalyst")
    limit, offset = parse_pagination({"cycle_id", "employee_id", "status", "unit_id_at_invite"})
    cycle_id = request.args.get("cycle_id")
    employee_id = request.args.get("employee_id")
    status = request.args.get("status")
    unit_id_at_invite = request.args.get("unit_id_at_invite")
    items = list(db.survey_invites.values())
    if cycle_id is not None:
        items = [iv for iv in items if iv["cycle_id"] == cycle_id]
    if employee_id is not None:
        items = [iv for iv in items if iv["employee_id"] == employee_id]
    if status is not None:
        items = [iv for iv in items if iv["status"] == status]
    if unit_id_at_invite is not None:
        items = [iv for iv in items if iv["unit_id_at_invite"] == unit_id_at_invite]
    page, total = paginate(items, limit, offset)
    return success_list([public(iv) for iv in page], limit, offset, total)


@bp.get("/engagement/survey-invites/<invite_id>")
def get_invite(invite_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "EmployeeRole")
    iv = _get_invite_or_404(invite_id)
    if role == "EmployeeRole" and iv["employee_id"] != user_id:
        raise err(ERR_INVITE_OWNERSHIP,
                  "employees may read only their own invitation", 403)
    return success_object(public(iv))


@bp.post("/engagement/survey-invites/<invite_id>/submit")
def submit_invite(invite_id):
    user_id, role = require_roles("EmployeeRole")
    iv = _get_invite_or_404(invite_id)
    if iv["employee_id"] != user_id:
        raise err(ERR_INVITE_OWNERSHIP,
                  "X-User-ID does not match invite.employee_id", 403)
    body = get_json_body()
    optional_fields_present(body, {"answers"})
    require_fields(body, ["answers"])
    cycle = db.survey_cycles.get(iv["cycle_id"])
    parsed, cycle_items = _validate_answers(body, cycle)

    _check_submit_window(cycle)

    if iv["status"] not in ("INVITED", "REMINDED", "PARTIAL"):
        raise err(ERR_INVALID_STATE,
                  f"cannot submit an invite in status {iv['status']}", 409)

    if len(parsed) != len(cycle_items):
        raise err(ERR_ANSWERS_INCOMPLETE,
                  "submit requires answers for every cycle item", 422)

    was_partial = iv["status"] == "PARTIAL"
    response = stamp_new_immutable({
        "invite_id": iv["id"],
        "answers": parsed,
        "is_partial": False,
    })
    # Replace any existing (partial) response row for this invite.
    old_id = db.responses_by_invite.get(iv["id"])
    if old_id is not None and old_id in db.survey_responses:
        del db.survey_responses[old_id]
    db.survey_responses[response["id"]] = response
    db.responses_by_invite[iv["id"]] = response["id"]

    iv["status"] = "SUBMITTED"
    iv["submitted_at"] = public(response)["created_at"]
    touch(iv)

    cycle_obj = db.survey_cycles[iv["cycle_id"]]
    recompute_cycle_counters(cycle_obj)
    return success_object(public(iv), 201)


@bp.post("/engagement/survey-invites/<invite_id>/submit-partial")
def submit_partial_invite(invite_id):
    user_id, role = require_roles("EmployeeRole")
    iv = _get_invite_or_404(invite_id)
    if iv["employee_id"] != user_id:
        raise err(ERR_INVITE_OWNERSHIP,
                  "X-User-ID does not match invite.employee_id", 403)
    body = get_json_body()
    optional_fields_present(body, {"answers"})
    require_fields(body, ["answers"])
    cycle = db.survey_cycles.get(iv["cycle_id"])
    parsed, cycle_items = _validate_answers(body, cycle)

    _check_submit_window(cycle)

    if iv["status"] not in ("INVITED", "REMINDED"):
        raise err(ERR_INVALID_STATE,
                  f"cannot submit-partial an invite in status {iv['status']}", 409)

    # Partial must answer at least one item while leaving at least one unanswered.
    if len(parsed) == 0 or len(parsed) == len(cycle_items):
        raise err(ERR_ANSWERS_INCOMPLETE,
                  "submit-partial requires at least one answer and at least one unanswered", 422)

    response = stamp_new_immutable({
        "invite_id": iv["id"],
        "answers": parsed,
        "is_partial": True,
    })
    old_id = db.responses_by_invite.get(iv["id"])
    if old_id is not None and old_id in db.survey_responses:
        del db.survey_responses[old_id]
    db.survey_responses[response["id"]] = response
    db.responses_by_invite[iv["id"]] = response["id"]

    iv["status"] = "PARTIAL"
    touch(iv)

    cycle_obj = db.survey_cycles[iv["cycle_id"]]
    recompute_cycle_counters(cycle_obj)
    return success_object(public(iv), 201)


@bp.get("/engagement/survey-invites/<invite_id>/response")
def get_invite_response(invite_id):
    user_id, role = require_roles("HRAdmin", "PeopleAnalyst", "EmployeeRole", "UnitManager")
    iv = _get_invite_or_404(invite_id)
    # UnitManager may never read an individual survey response.
    if role == "UnitManager":
        from errors import ERR_CONFIDENTIALITY
        raise err(ERR_CONFIDENTIALITY,
                  "UnitManager may never read an individual survey response", 403)
    if role == "EmployeeRole" and iv["employee_id"] != user_id:
        raise err(ERR_INVITE_OWNERSHIP,
                  "employees may read only their own response", 403)
    resp_id = db.responses_by_invite.get(iv["id"])
    rows = []
    if resp_id is not None and resp_id in db.survey_responses:
        rows = [public(db.survey_responses[resp_id])]
    limit, offset = parse_pagination(set())
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


@bp.get("/engagement/survey-invites/<invite_id>/reminders")
def list_invite_reminders(invite_id):
    require_roles("HRAdmin", "PeopleAnalyst")
    iv = _get_invite_or_404(invite_id)
    limit, offset = parse_pagination(set())
    events = [ev for ev in db.reminder_events.values() if ev["invite_id"] == iv["id"]]
    events.sort(key=lambda ev: ev["sequence_no"])
    page, total = paginate(events, limit, offset)
    return success_list([public(ev) for ev in page], limit, offset, total)
