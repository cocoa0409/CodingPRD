"""Call assignments and call logs."""
from flask import Blueprint, request

from auth import endpoint, get_body
from db import store, now, new_entity, touch
from envelope import ok, ok_list
from errors import (raise_err, ERR_NOT_FOUND, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_OWN_RESOURCE,
                    ERR_PARTICIPANT_NOT_ENROLLED, ERR_VOLUNTEER_NOT_CERTIFIED,
                    ERR_CONFIDENTIALITY_NOT_CURRENT, ERR_WINDOW_OUTSIDE_SCHEDULE,
                    ERR_WINDOW_OUTSIDE_AVAILABILITY, ERR_ASSIGNMENT_WINDOW_CONFLICT,
                    ERR_WEEKLY_LOAD_EXCEEDED, ERR_MAX_ASSIGNMENTS_REACHED,
                    ERR_NO_ELIGIBLE_VOLUNTEER, ERR_SAFETY_FIELDS_REQUIRED,
                    ERR_FUTURE_DATED_CALL_LOG)
from validate import Field, validate_payload, parse_pagination, sort_items
import calc
import cascade
import serialize
from timeutil import parse_hm, parse_date

bp = Blueprint("assignments", __name__)

PC = ["ProgramCoordinator"]
PC_QR_VC = ["ProgramCoordinator", "QualityReviewer", "VolunteerCaller"]
OUTCOMES = {"REACHED_OK", "REACHED_CONCERN", "NO_ANSWER", "BUSY", "REFUSED",
            "WRONG_NUMBER"}
CONCERN_LEVELS = {"NONE", "ROUTINE", "URGENT", "IMMEDIATE_DANGER"}
CONCERN_CATEGORIES = {"HEALTH", "SAFETY", "MOOD", "NUTRITION", "MEDICATION",
                      "HOUSING", "OTHER"}


def get_assignment_or_404(aid):
    a = store.assignments.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "Call assignment not found")
    return a


def program_or_404():
    g = calc.sole_program()
    if not g:
        raise_err(ERR_NOT_FOUND, "Program not found")
    return g


def check_assignment_fitness(p, v, date, ws, we, prog, exclude_id=None):
    """Fitness checks shared by create and reschedule for a named volunteer."""
    if v["status"] != "ACTIVE" or not calc.training_current(v):
        raise_err(ERR_VOLUNTEER_NOT_CERTIFIED,
                  "Volunteer is not ACTIVE with VALID required training")
    if not calc.agreement_current(v, prog):
        raise_err(ERR_CONFIDENTIALITY_NOT_CURRENT,
                  "Volunteer confidentiality agreement is not current")
    if not calc.schedule_contains(p, date, ws, we):
        raise_err(ERR_WINDOW_OUTSIDE_SCHEDULE,
                  "Window is not contained in an ACTIVE schedule for that weekday")
    if not calc.availability_contains(v, date, ws, we):
        raise_err(ERR_WINDOW_OUTSIDE_AVAILABILITY,
                  "Window is not contained in volunteer availability")
    if not calc.language_ok(v, p):
        raise_err(ERR_NO_ELIGIBLE_VOLUNTEER, "Volunteer lacks the participant's language")
    if calc.has_conflict(v, date, ws, we, prog["doc_buffer_minutes"],
                         exclude_id=exclude_id):
        raise_err(ERR_ASSIGNMENT_WINDOW_CONFLICT,
                  "Conflicts with an existing SCHEDULED assignment (buffer-inclusive)")
    if not calc.load_ok(v, date, we - ws, prog):
        raise_err(ERR_WEEKLY_LOAD_EXCEEDED, "Volunteer weekly load cap would be exceeded")
    if not calc.cap_ok(v):
        raise_err(ERR_MAX_ASSIGNMENTS_REACHED,
                  "Volunteer concurrent assignment cap reached")


@bp.route("/api/call-assignments", methods=["GET"])
@endpoint(PC_QR_VC)
def list_assignments(uid, role):
    limit, offset = parse_pagination(request.args)
    items = list(store.assignments.values())
    for fname in ("participant_id", "volunteer_id", "escalation_id",
                  "rescheduled_from_id", "status"):
        if fname in request.args:
            items = [a for a in items if a.get(fname) == request.args[fname]]
    if "scheduled_date" in request.args:
        d = parse_date(request.args["scheduled_date"])
        if d is None:
            raise_err(ERR_INVALID_REQUEST, "scheduled_date must be YYYY-MM-DD")
        items = [a for a in items if a["scheduled_date"] == d]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.assignment(a) for a in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/call-assignments", methods=["POST"])
@endpoint(PC)
def create_assignment(uid, role):
    data = validate_payload(get_body(), [
        Field("participant_id", "str", required=True),
        Field("scheduled_date", "date", required=True),
        Field("window_start", "hm", required=True),
        Field("window_end", "hm", required=True),
        Field("volunteer_id", "str"),
        Field("source", "enum", enum={"REGULAR", "MAKEUP", "ESCALATION_RETRY"},
              default="REGULAR"),
    ])
    if data.get("source") == "ESCALATION_RETRY":
        raise_err(ERR_INVALID_REQUEST, "ESCALATION_RETRY is system-set only")
    p = store.participants.get(data["participant_id"])
    if not p:
        raise_err(ERR_NOT_FOUND, "Participant not found")
    v = None
    if data.get("volunteer_id"):
        v = store.volunteers.get(data["volunteer_id"])
        if not v:
            raise_err(ERR_NOT_FOUND, "Volunteer not found")
    ws, we = parse_hm(data["window_start"]), parse_hm(data["window_end"])
    if ws >= we:
        raise_err(ERR_INVALID_REQUEST, "window_start must be before window_end")
    if p["status"] != "ENROLLED":
        raise_err(ERR_PARTICIPANT_NOT_ENROLLED, "Participant is not ENROLLED")
    g = program_or_404()
    date = data["scheduled_date"]
    if v is not None:
        check_assignment_fitness(p, v, date, ws, we, g)
    else:
        if not calc.schedule_contains(p, date, ws, we):
            raise_err(ERR_WINDOW_OUTSIDE_SCHEDULE,
                      "Window is not contained in an ACTIVE schedule for that weekday")
        v = calc.selector(p, date, ws, we, g)
        if v is None:
            raise_err(ERR_NO_ELIGIBLE_VOLUNTEER, "No eligible volunteer")
    a = cascade.insert_assignment(p, v["id"], date, ws, we, data.get("source", "REGULAR"))
    return ok(serialize.assignment(a), 201)


@bp.route("/api/call-assignments/<aid>", methods=["GET"])
@endpoint(PC_QR_VC)
def get_assignment(aid, uid, role):
    return ok(serialize.assignment(get_assignment_or_404(aid)))


@bp.route("/api/call-assignments/<aid>/cancel", methods=["POST"])
@endpoint(PC)
def cancel_assignment(aid, uid, role):
    a = get_assignment_or_404(aid)
    if a["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Assignment is not SCHEDULED")
    cascade.cancel_assignment(a, "MANUAL")
    return ok(serialize.assignment(a))


@bp.route("/api/call-assignments/<aid>/reschedule", methods=["POST"])
@endpoint(PC)
def reschedule(aid, uid, role):
    a = get_assignment_or_404(aid)
    data = validate_payload(get_body(), [
        Field("new_scheduled_date", "date", required=True),
        Field("new_window_start", "hm", required=True),
        Field("new_window_end", "hm", required=True),
    ])
    ws = parse_hm(data["new_window_start"])
    we = parse_hm(data["new_window_end"])
    if ws >= we:
        raise_err(ERR_INVALID_REQUEST, "new_window_start must be before new_window_end")
    if a["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Assignment is not SCHEDULED")
    g = program_or_404()
    p = store.participants[a["participant_id"]]
    date = data["new_scheduled_date"]
    v = store.volunteers.get(a["volunteer_id"]) if a.get("volunteer_id") else None
    if v is not None:
        check_assignment_fitness(p, v, date, ws, we, g, exclude_id=a["id"])
    else:
        if not calc.schedule_contains(p, date, ws, we):
            raise_err(ERR_WINDOW_OUTSIDE_SCHEDULE,
                      "Window is not contained in an ACTIVE schedule for that weekday")
        v = calc.selector(p, date, ws, we, g)
        if v is None:
            raise_err(ERR_NO_ELIGIBLE_VOLUNTEER, "No eligible volunteer")
    a["status"] = "CANCELLED"
    a["cancel_reason"] = "RESCHEDULED"
    touch(a)
    new_a = cascade.insert_assignment(p, v["id"], date, ws, we, a["source"],
                                      escalation_id=a.get("escalation_id"),
                                      rescheduled_from_id=a["id"])
    return ok(serialize.assignment(new_a), 201)


# ---------------- call logs ----------------

@bp.route("/api/call-assignments/<aid>/call-logs", methods=["GET"])
@endpoint(PC_QR_VC)
def list_logs(aid, uid, role):
    a = get_assignment_or_404(aid)
    limit, offset = parse_pagination(request.args)
    items = [lg for lg in store.logs.values() if lg["assignment_id"] == a["id"]]
    items = sort_items(items)
    total = len(items)
    return ok_list([serialize.call_log(lg) for lg in items[offset:offset + limit]],
                   total, limit, offset)


@bp.route("/api/call-assignments/<aid>/call-logs", methods=["POST"])
@endpoint(["VolunteerCaller", "ProgramCoordinator"])
def create_log(aid, uid, role):
    a = get_assignment_or_404(aid)
    if role == "VolunteerCaller" and uid != a.get("volunteer_id"):
        raise_err(ERR_NOT_OWN_RESOURCE, "Volunteers log only their own assignments")
    data = validate_payload(get_body(), [
        Field("called_at", "dt", required=True),
        Field("duration_seconds", "int", required=True, minv=0),
        Field("outcome", "enum", required=True, enum=OUTCOMES),
        Field("concern_level", "enum", enum=CONCERN_LEVELS, default="NONE"),
        Field("concern_categories", "list_str", enum=CONCERN_CATEGORIES, default=list),
        Field("follow_up_needed", "bool", default=False),
        Field("follow_up_plan", "str"),
        Field("supervisor_notified", "bool", default=False),
        Field("notes", "str"),
    ])
    if a["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Assignment is not SCHEDULED")
    concern_level = data.get("concern_level", "NONE")
    if concern_level == "IMMEDIATE_DANGER":
        plan = data.get("follow_up_plan")
        if (data.get("follow_up_needed") is not True
                or data.get("supervisor_notified") is not True
                or not isinstance(plan, str) or plan.strip() == ""):
            raise_err(ERR_SAFETY_FIELDS_REQUIRED,
                      "IMMEDIATE_DANGER requires follow_up_needed, supervisor_notified "
                      "and a non-empty follow_up_plan")
    if data["called_at"] > now():
        raise_err(ERR_FUTURE_DATED_CALL_LOG, "called_at is after the logical clock")
    g = program_or_404()
    lg = new_entity()
    lg.update({
        "assignment_id": a["id"],
        "called_at": data["called_at"],
        "duration_seconds": data["duration_seconds"],
        "outcome": data["outcome"],
        "concern_level": concern_level,
        "concern_categories": data.get("concern_categories", []),
        "concern_flag": (data["outcome"] == "REACHED_CONCERN"
                         or concern_level != "NONE"),
        "follow_up_needed": data.get("follow_up_needed", False),
        "follow_up_plan": data.get("follow_up_plan"),
        "supervisor_notified": data.get("supervisor_notified", False),
        "notes": data.get("notes"),
    })
    store.logs[lg["id"]] = lg
    cascade.process_log_side_effects(a, lg, g)
    return ok(serialize.call_log(lg), 201)
