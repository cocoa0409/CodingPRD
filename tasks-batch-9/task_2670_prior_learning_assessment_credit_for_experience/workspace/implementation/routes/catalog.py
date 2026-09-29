"""Programmes, courses and learning outcomes."""
from flask import Blueprint

from db import db, new_row, order_rows, outcomes_of_course
from errors import ApiError
from middleware import (ALL_ROLES, ROLE_COORDINATOR, authenticate, find_or_404)
from response import created, ok, ok_list, read_pagination
from serializers import course_out, outcome_out, program_out
from services.capacity import effective_cap_program
from util import (COURSE_LEVELS, SOURCE_TYPES, as_bool, as_enum, as_int, as_str,
                  json_body, present, require, touch)

bp = Blueprint("catalog", __name__)

READ_ROLES = ALL_ROLES


def _recompute_program(program):
    program["effective_pla_cap_credits"] = effective_cap_program(program)


def _validate_source_list(value):
    if not isinstance(value, list) or not value:
        raise ApiError("ERR_INVALID_REQUEST", "allowed_source_types must be a non-empty array")
    for item in value:
        as_enum(item, "allowed_source_types", SOURCE_TYPES)
    if len(set(value)) != len(value):
        raise ApiError("ERR_INVALID_REQUEST", "allowed_source_types must not repeat a value")
    return list(value)


@bp.post("/programs")
def create_program():
    authenticate([ROLE_COORDINATOR])
    body = json_body()
    program_code = as_str(require(body, "program_code"), "program_code", 2, 16, r"^[A-Z0-9]{2,16}$")
    title = as_str(require(body, "title"), "title", 1)
    total = as_int(require(body, "total_credits_required"), "total_credits_required", 30)
    residency = as_int(require(body, "residency_min_credits"), "residency_min_credits", 0, total)
    pla_max = as_int(require(body, "pla_max_credits"), "pla_max_credits", 0)
    pla_pct = as_int(require(body, "pla_max_pct_bp"), "pla_max_pct_bp", 0, 10000)
    upper_max = as_int(require(body, "pla_upper_division_max_credits"), "pla_upper_division_max_credits", 0)
    sources = _validate_source_list(require(body, "allowed_source_types"))
    threshold = None
    if present(body, "pla_pass_threshold_bp"):
        threshold = as_int(body["pla_pass_threshold_bp"], "pla_pass_threshold_bp", 1, 10000)
    status = "ACTIVE"
    if present(body, "status"):
        status = as_enum(body["status"], "status", ["ACTIVE", "INACTIVE"])
    for existing in db.programs.values():
        if existing["program_code"] == program_code:
            raise ApiError("ERR_INVALID_REQUEST", "program_code is already registered")

    program = new_row("Program")
    program.update({
        "program_code": program_code,
        "title": title,
        "total_credits_required": total,
        "residency_min_credits": residency,
        "pla_max_credits": pla_max,
        "pla_max_pct_bp": pla_pct,
        "pla_upper_division_max_credits": upper_max,
        "pla_pass_threshold_bp": threshold,
        "allowed_source_types": sources,
        "status": status,
    })
    _recompute_program(program)
    db.programs[program["id"]] = program
    return created(program_out(program))


@bp.get("/programs/<program_id>")
def read_program(program_id):
    authenticate(READ_ROLES)
    program = find_or_404("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    return ok(program_out(program))


@bp.patch("/programs/<program_id>")
def amend_program(program_id):
    authenticate([ROLE_COORDINATOR])
    program = find_or_404("programs", program_id, "ERR_PROGRAM_NOT_FOUND")
    body = json_body()
    total = program["total_credits_required"]
    if present(body, "total_credits_required"):
        total = as_int(body["total_credits_required"], "total_credits_required", 30)
    residency = program["residency_min_credits"]
    if present(body, "residency_min_credits"):
        residency = as_int(body["residency_min_credits"], "residency_min_credits", 0)
    if residency > total:
        raise ApiError("ERR_INVALID_REQUEST", "residency_min_credits must not exceed total_credits_required")
    program["total_credits_required"] = total
    program["residency_min_credits"] = residency
    if present(body, "pla_max_credits"):
        program["pla_max_credits"] = as_int(body["pla_max_credits"], "pla_max_credits", 0)
    if present(body, "pla_max_pct_bp"):
        program["pla_max_pct_bp"] = as_int(body["pla_max_pct_bp"], "pla_max_pct_bp", 0, 10000)
    if present(body, "pla_upper_division_max_credits"):
        program["pla_upper_division_max_credits"] = as_int(
            body["pla_upper_division_max_credits"], "pla_upper_division_max_credits", 0)
    if "pla_pass_threshold_bp" in body:
        value = body["pla_pass_threshold_bp"]
        program["pla_pass_threshold_bp"] = None if value is None else as_int(
            value, "pla_pass_threshold_bp", 1, 10000)
    if present(body, "allowed_source_types"):
        program["allowed_source_types"] = _validate_source_list(body["allowed_source_types"])
    if present(body, "status"):
        program["status"] = as_enum(body["status"], "status", ["ACTIVE", "INACTIVE"])
    _recompute_program(program)
    touch(program)
    return ok(program_out(program))


# ---------------------------------------------------------------- courses
def _validate_outcomes(raw):
    if not isinstance(raw, list):
        raise ApiError("ERR_INVALID_REQUEST", "learning_outcomes must be an array")
    parsed = []
    for entry in raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", "each learning outcome must be an object")
        code = as_str(require(entry, "outcome_code"), "outcome_code", 1, 12)
        description = as_str(require(entry, "description"), "description", 1)
        weight = as_int(require(entry, "weight_bp"), "weight_bp", 1, 10000)
        mastery = None
        if present(entry, "mastery_threshold_bp"):
            mastery = as_int(entry["mastery_threshold_bp"], "mastery_threshold_bp", 1, 10000)
        parsed.append({"outcome_code": code, "description": description,
                       "weight_bp": weight, "mastery_threshold_bp": mastery})
    codes = [p["outcome_code"] for p in parsed]
    if sum(p["weight_bp"] for p in parsed) != 10000 or len(set(codes)) != len(codes) or not parsed:
        raise ApiError("ERR_OUTCOME_WEIGHTS_INVALID")
    return parsed


@bp.post("/courses")
def create_course():
    authenticate([ROLE_COORDINATOR])
    body = json_body()
    course_code = as_str(require(body, "course_code"), "course_code", 1, 32)
    title = as_str(require(body, "title"), "title", 1)
    department_code = as_str(require(body, "department_code"), "department_code", 2, 8, r"^[A-Z0-9]{2,8}$")
    credits = as_int(require(body, "credits"), "credits", 1, 12)
    level = as_enum(require(body, "level"), "level", COURSE_LEVELS)
    pla_eligible = True
    if present(body, "pla_eligible"):
        pla_eligible = as_bool(body["pla_eligible"], "pla_eligible")
    outcomes = _validate_outcomes(require(body, "learning_outcomes"))
    for existing in db.courses.values():
        if existing["course_code"] == course_code:
            raise ApiError("ERR_INVALID_REQUEST", "course_code is already registered")

    course = new_row("Course")
    course.update({
        "course_code": course_code,
        "title": title,
        "department_code": department_code,
        "credits": credits,
        "level": level,
        "pla_eligible": pla_eligible,
        "outcome_count": len(outcomes),
    })
    db.courses[course["id"]] = course
    for spec in outcomes:
        outcome = new_row("LearningOutcome", extra_lean=True)
        outcome["course_id"] = course["id"]
        outcome.update(spec)
        db.outcomes[outcome["id"]] = outcome
    return created(course_out(course))


@bp.get("/courses/<course_id>")
def read_course(course_id):
    authenticate(READ_ROLES)
    course = find_or_404("courses", course_id, "ERR_COURSE_NOT_FOUND")
    course["outcome_count"] = len(outcomes_of_course(course_id))
    return ok(course_out(course))


@bp.get("/learning-outcomes/<outcome_id>")
def read_outcome(outcome_id):
    authenticate(READ_ROLES)
    outcome = find_or_404("outcomes", outcome_id, "ERR_OUTCOME_NOT_FOUND")
    return ok(outcome_out(outcome))


@bp.get("/learning-outcomes")
def list_outcomes():
    from flask import request
    authenticate(READ_ROLES)
    limit, offset = read_pagination()
    rows = list(db.outcomes.values())
    course_id = request.args.get("course_id")
    outcome_code = request.args.get("outcome_code")
    if course_id:
        rows = [r for r in rows if r["course_id"] == course_id]
    if outcome_code:
        rows = [r for r in rows if r["outcome_code"] == outcome_code]
    rows = order_rows(rows, [(lambda r: r["outcome_code"], False)])
    return ok_list(rows, outcome_out, limit, offset)
