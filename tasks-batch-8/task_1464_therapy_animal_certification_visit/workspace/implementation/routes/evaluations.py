"""Evaluation endpoints (temperament testing pipeline)."""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import err, err_not_found, err_invalid_request
from middleware import get_auth, require_roles, err_ownership
from response import success_object, success_list, paginate
from services import scoring
from services.records import new_record, touch, public
from util import now_dt, now_iso, parse_datetime, fmt_dt
from validate import get_body, validate_body

bp = Blueprint("evaluations", __name__)

ALL_ROLES = ["ProgramAdmin", "Handler", "Evaluator", "FacilityCoordinator", "ComplianceOfficer"]


def _get_evaluation(evaluation_id):
    e = store.evaluations.get(evaluation_id)
    if e is None:
        raise err_not_found("evaluation")
    return e


def _owning_team(evaluation):
    return store.teams.get(evaluation["team_id"])


@bp.post("/v1/evaluations")
def create_evaluation():
    auth = get_auth()
    require_roles(auth, ["Handler"])
    body = validate_body(get_body(), {"team_id": ("string", True, None)})
    team = store.teams.get(body["team_id"])
    if team is None:
        raise err_not_found("team")
    if team["handler_id"] != auth.user_id:
        raise err_ownership()
    handler = store.handlers.get(team["handler_id"])
    if handler is None or handler["status"] != "ACTIVE":
        raise err("ERR_HANDLER_NOT_ACTIVE", 409, "Handler is not ACTIVE")
    if team["status"] != "FORMING":
        raise err("ERR_TEAM_NOT_FORMING", 409, "Team is not FORMING")
    rec = new_record(store.evaluations, {
        "team_id": team["id"],
        "evaluator_id": None,
        "attempt_number": 1,
        "scheduled_start": None,
        "scheduled_end": None,
        "aptitude_score": None,
        "obedience_score": None,
        "composite_score": None,
        "status": "REQUESTED",
        "requested_at": now_iso(),
        "scored_at": None,
        "failed_at": None,
    })
    return success_object(public(rec), 201)


@bp.get("/v1/evaluations/<evaluation_id>")
def get_evaluation(evaluation_id):
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    return success_object(public(_get_evaluation(evaluation_id)), 200)


@bp.get("/v1/evaluations")
def list_evaluations():
    auth = get_auth()
    require_roles(auth, ALL_ROLES)
    records = list(store.evaluations.values())
    team_id = request.args.get("team_id")
    evaluator_id = request.args.get("evaluator_id")
    status = request.args.get("status")
    if team_id is not None:
        records = [r for r in records if r["team_id"] == team_id]
    if evaluator_id is not None:
        records = [r for r in records if r.get("evaluator_id") == evaluator_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records, request.args)
    return success_list([public(r) for r in page], limit, offset, total)


@bp.post("/v1/evaluations/<evaluation_id>/schedule")
def schedule_evaluation(evaluation_id):
    auth = get_auth()
    require_roles(auth, ["ProgramAdmin"])
    ev = _get_evaluation(evaluation_id)
    body = validate_body(get_body(), {
        "evaluator_id": ("string", True, None),
        "scheduled_start": ("datetime", True, None),
        "scheduled_end": ("datetime", True, None),
    })
    evaluator = store.evaluators.get(body["evaluator_id"])
    if evaluator is None:
        raise err_not_found("evaluator")
    start = parse_datetime(body["scheduled_start"])
    end = parse_datetime(body["scheduled_end"])
    if end <= start:
        raise err_invalid_request("scheduled_start must be strictly before scheduled_end")

    # State precondition
    if ev["status"] not in ("REQUESTED", "APPEALED"):
        raise err("ERR_EVALUATION_NOT_SCHEDULABLE", 409,
                  "Evaluation is not in REQUESTED or APPEALED")
    # Evaluator must be ACTIVE
    if evaluator["status"] != "ACTIVE":
        raise err("ERR_EVALUATOR_NOT_ACTIVE", 409, "Evaluator is not ACTIVE")
    # Species specialization
    team = _owning_team(ev)
    animal = store.animals.get(team["animal_id"]) if team else None
    if animal is None or animal["species"] not in evaluator["specializations"]:
        raise err("ERR_EVALUATOR_SPECIES_MISMATCH", 409,
                  "Evaluator is not certified to score this species")
    now = now_dt()
    if start < now:
        raise err("ERR_EVALUATION_SCHEDULE_IN_PAST", 409,
                  "scheduled_start lies in the past")
    duration = int((end - start).total_seconds() // 60)
    if duration < 30 or duration > 120:
        raise err("ERR_EVALUATION_DURATION_INVALID", 409,
                  "Evaluation duration must be 30..120 minutes")
    # Buffered conflict: new raw interval vs [s-30m, e+30m) of each SCHEDULED eval
    buffer = timedelta(minutes=30)
    for other in store.evaluations.values():
        if other["id"] == ev["id"] or other.get("evaluator_id") != evaluator["id"]:
            continue
        if other["status"] != "SCHEDULED" or not other.get("scheduled_start"):
            continue
        os_ = parse_datetime(other["scheduled_start"]) - buffer
        oe = parse_datetime(other["scheduled_end"]) + buffer
        if start < oe and os_ < end:
            raise err("ERR_EVALUATOR_SCHEDULING_CONFLICT", 409,
                      "The evaluation conflicts with a buffered interval of another evaluation")
    # Daily cap on that UTC day
    day = start.date()
    count = 0
    for other in store.evaluations.values():
        if other["id"] == ev["id"] or other.get("evaluator_id") != evaluator["id"]:
            continue
        if other["status"] == "SCHEDULED" and other.get("scheduled_start"):
            if parse_datetime(other["scheduled_start"]).date() == day:
                count += 1
    if count >= evaluator["max_evaluations_per_day"]:
        raise err("ERR_EVALUATOR_DAILY_CAP_EXCEEDED", 422,
                  "Evaluator daily scheduling cap reached")

    was_appealed = ev["status"] == "APPEALED"
    ev["evaluator_id"] = evaluator["id"]
    ev["scheduled_start"] = fmt_dt(start)
    ev["scheduled_end"] = fmt_dt(end)
    ev["status"] = "SCHEDULED"
    if was_appealed:
        ev["attempt_number"] = ev.get("attempt_number", 1) + 1
    touch(ev)
    return success_object(public(ev), 200)


@bp.post("/v1/evaluations/<evaluation_id>/score")
def score_evaluation(evaluation_id):
    auth = get_auth()
    require_roles(auth, ["Evaluator"])
    ev = _get_evaluation(evaluation_id)
    body = validate_body(get_body(), {
        "aptitude_score": ("integer", True, None),
        "obedience_score": ("integer", True, None),
    })
    for field in ("aptitude_score", "obedience_score"):
        if not (0 <= body[field] <= 100):
            raise err_invalid_request("%s must be in 0..100" % field)
    if ev["status"] != "SCHEDULED":
        raise err("ERR_EVALUATION_NOT_SCHEDULED", 409, "Evaluation is not SCHEDULED")
    if ev.get("evaluator_id") != auth.user_id:
        raise err_ownership()
    if now_dt() < parse_datetime(ev["scheduled_end"]):
        raise err("ERR_EVALUATION_NOT_CONCLUDED", 409,
                  "The evaluation session has not concluded")
    composite = scoring.composite_score(body["aptitude_score"], body["obedience_score"])
    passed = scoring.evaluation_passes(body["aptitude_score"], body["obedience_score"],
                                       composite, ev.get("attempt_number", 1))
    ev["aptitude_score"] = body["aptitude_score"]
    ev["obedience_score"] = body["obedience_score"]
    ev["composite_score"] = composite
    ev["scored_at"] = now_iso()
    if passed:
        ev["status"] = "PASSED"
    else:
        ev["status"] = "FAILED"
        ev["failed_at"] = now_iso()
    touch(ev)
    return success_object(public(ev), 200)


@bp.post("/v1/evaluations/<evaluation_id>/appeal")
def appeal_evaluation(evaluation_id):
    auth = get_auth()
    require_roles(auth, ["Handler"])
    ev = _get_evaluation(evaluation_id)
    team = _owning_team(ev)
    if team is not None and team["handler_id"] != auth.user_id:
        raise err_ownership()
    if ev["status"] != "FAILED":
        raise err("ERR_EVALUATION_NOT_FAILED", 409, "Evaluation is not FAILED")
    if now_dt() > parse_datetime(ev["failed_at"]) + timedelta(days=14):
        raise err("ERR_EVALUATION_APPEAL_WINDOW_CLOSED", 409,
                  "The 14-day appeal window has closed")
    ev["status"] = "APPEALED"
    touch(ev)
    return success_object(public(ev), 200)


@bp.post("/v1/evaluations/<evaluation_id>/cancel")
def cancel_evaluation(evaluation_id):
    auth = get_auth()
    require_roles(auth, ["Handler", "ProgramAdmin"])
    ev = _get_evaluation(evaluation_id)
    team = _owning_team(ev)
    if auth.role == "Handler" and team is not None and team["handler_id"] != auth.user_id:
        raise err_ownership()
    if ev["status"] not in ("REQUESTED", "SCHEDULED", "APPEALED"):
        raise err("ERR_EVALUATION_NOT_CANCELLABLE", 409,
                  "Evaluation is in a terminal state")
    ev["status"] = "CANCELLED"
    touch(ev)
    return success_object(public(ev), 200)
