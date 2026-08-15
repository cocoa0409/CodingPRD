"""Study endpoints including OCC-guarded amend and cohort summary."""

import db
from middleware import require_roles
from response import success, parse_pagination, paginate_list
from routes import make_blueprint
from util import (
    get_payload, require_string, require_int, require_array,
    stamp_new, touch, check_unique,
)
from errors import (
    raise_error, ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INVALID_REQUEST,
    ERR_STALE_VERSION,
)
from services.serializers import public
from services.calculations import cohort_build_summary

bp = make_blueprint("studies")


def _get_study(sid):
    s = db.studies.get(sid)
    if s is None:
        raise_error(ERR_NOT_FOUND, "Study not found")
    return s


@bp.route("/playtests/studies", methods=["POST"])
def create_study():
    require_roles("ResearchOpsAdmin")
    body = get_payload()
    title = require_string(body, "title")
    code = require_string(body, "code")
    min_age = require_int(body, "min_age")
    max_age = require_int(body, "max_age")
    if max_age < min_age:
        raise_error(ERR_INVALID_REQUEST, "max_age must be >= min_age")
    allowed_regions = require_array(body, "allowed_regions")
    required_platforms = require_array(body, "required_platforms")
    cohort_capacity = require_int(body, "cohort_capacity", minimum=1)
    incentive_budget_cents = require_int(body, "incentive_budget_cents", minimum=0)
    check_unique(db.studies, "code", code)
    rec = {
        "title": title,
        "code": code,
        "min_age": min_age,
        "max_age": max_age,
        "allowed_regions": list(allowed_regions),
        "required_platforms": list(required_platforms),
        "cohort_capacity": cohort_capacity,
        "incentive_budget_cents": incentive_budget_cents,
        "status": "DRAFT",
        "enrolled_count": 0,
        "budget_committed_cents": 0,
        "budget_spent_cents": 0,
    }
    stamp_new(rec)
    db.studies[rec["id"]] = rec
    return success(public(rec, "study"), status=201)


@bp.route("/playtests/studies", methods=["GET"])
def list_studies():
    require_roles("ResearchOpsAdmin", "Researcher", "IncentiveOfficer", "LegalCounsel", "Moderator")
    from flask import request
    limit, offset = parse_pagination(request.args)
    items = list(db.studies.values())
    status = request.args.get("status")
    if status is not None:
        items = [s for s in items if s["status"] == status]
    page, pagination = paginate_list(items, limit, offset)
    return success([public(s, "study") for s in page], status=200, pagination=pagination)


@bp.route("/playtests/studies/<sid>", methods=["GET"])
def get_study(sid):
    require_roles("ResearchOpsAdmin", "Researcher", "IncentiveOfficer", "LegalCounsel",
                  "Moderator", "Participant")
    s = _get_study(sid)
    return success(public(s, "study"), status=200)


@bp.route("/playtests/studies/<sid>", methods=["PATCH"])
def amend_study(sid):
    require_roles("ResearchOpsAdmin")
    s = _get_study(sid)
    body = get_payload()

    if "expected_study_version" not in body or body["expected_study_version"] is None:
        raise_error(ERR_INVALID_REQUEST, "expected_study_version is required")
    expected = body["expected_study_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_error(ERR_INVALID_REQUEST, "expected_study_version must be an integer")
    if expected != s["version"]:
        raise_error(ERR_STALE_VERSION, "Study version mismatch")

    if s["status"] not in ("DRAFT", "RECRUITING"):
        raise_error(ERR_INVALID_STATE, "Study may only be amended while DRAFT or RECRUITING")

    new_min_age = s["min_age"]
    new_max_age = s["max_age"]

    if "title" in body:
        if not isinstance(body["title"], str):
            raise_error(ERR_INVALID_REQUEST, "title must be a string")
        s["title"] = body["title"]
    if "min_age" in body:
        v = body["min_age"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error(ERR_INVALID_REQUEST, "min_age must be an integer")
        new_min_age = v
    if "max_age" in body:
        v = body["max_age"]
        if isinstance(v, bool) or not isinstance(v, int):
            raise_error(ERR_INVALID_REQUEST, "max_age must be an integer")
        new_max_age = v
    if new_max_age < new_min_age:
        raise_error(ERR_INVALID_REQUEST, "max_age must be >= min_age")
    s["min_age"] = new_min_age
    s["max_age"] = new_max_age
    if "allowed_regions" in body:
        if not isinstance(body["allowed_regions"], list):
            raise_error(ERR_INVALID_REQUEST, "allowed_regions must be an array")
        s["allowed_regions"] = list(body["allowed_regions"])
    if "required_platforms" in body:
        if not isinstance(body["required_platforms"], list):
            raise_error(ERR_INVALID_REQUEST, "required_platforms must be an array")
        s["required_platforms"] = list(body["required_platforms"])
    if "cohort_capacity" in body:
        v = body["cohort_capacity"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 1:
            raise_error(ERR_INVALID_REQUEST, "cohort_capacity must be an integer >= 1")
        s["cohort_capacity"] = v
    if "incentive_budget_cents" in body:
        v = body["incentive_budget_cents"]
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise_error(ERR_INVALID_REQUEST, "incentive_budget_cents must be an integer >= 0")
        s["incentive_budget_cents"] = v
    touch(s)
    return success(public(s, "study"), status=200)


def _study_transition(sid, from_status, to_status, allowed_roles):
    require_roles(*allowed_roles)
    s = _get_study(sid)
    if s["status"] != from_status:
        raise_error(ERR_INVALID_STATE, "Study must be %s" % from_status)
    s["status"] = to_status
    touch(s)
    return success(public(s, "study"), status=200)


@bp.route("/playtests/studies/<sid>/open-recruitment", methods=["POST"])
def open_recruitment(sid):
    return _study_transition(sid, "DRAFT", "RECRUITING", ("ResearchOpsAdmin",))


@bp.route("/playtests/studies/<sid>/close-recruitment", methods=["POST"])
def close_recruitment(sid):
    return _study_transition(sid, "RECRUITING", "CLOSED", ("ResearchOpsAdmin",))


@bp.route("/playtests/studies/<sid>/begin-analysis", methods=["POST"])
def begin_analysis(sid):
    return _study_transition(sid, "CLOSED", "ANALYSIS", ("Researcher",))


@bp.route("/playtests/studies/<sid>/complete", methods=["POST"])
def complete_study(sid):
    return _study_transition(sid, "ANALYSIS", "COMPLETED", ("ResearchOpsAdmin",))


@bp.route("/playtests/studies/<sid>/cohort-summary", methods=["GET"])
def cohort_summary(sid):
    require_roles("ResearchOpsAdmin", "Researcher")
    _get_study(sid)
    result = cohort_build_summary(sid)
    return success(result, status=200)
