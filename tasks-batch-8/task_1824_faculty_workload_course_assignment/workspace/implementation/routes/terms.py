"""WorkloadTerm endpoints: create/list/get, policy PATCH (OCC), lifecycle
transitions, close-census, and the department load summary."""

import db
from errors import (
    ApiError,
    ERR_TERM_NOT_FOUND,
    ERR_DUPLICATE_TERM_CODE,
    ERR_VALIDATION,
    ERR_INVALID_TERM_STATE,
    ERR_STALE_VERSION,
    ERR_CENSUS_NOT_REACHED,
    ERR_UNSTAFFED_SECTIONS,
    ERR_UNCOVERED_OVERLOAD,
)
from middleware import authenticate, ALL_ROLES, CHAIR
from response import success_obj, success_list
from routes import make_blueprint
from util import (
    body_json, check_shape, present, pagination_params, paginate, apply_filters,
    parse_date, today, dec,
)
import services

bp = make_blueprint("terms")

TERM_STATUSES = ["DRAFT", "OPEN", "LOCKED", "PUBLISHED"]

_POLICY_SPEC = {
    "base_teaching_credits": {"type": "number"},
    "lecture_multiplier": {"type": "number"},
    "lab_multiplier": {"type": "number"},
    "seminar_multiplier": {"type": "number"},
    "online_premium_credits": {"type": "number"},
    "large_class_threshold": {"type": "integer"},
    "large_class_bonus_credits": {"type": "number"},
    "overload_comp_rate_cents": {"type": "integer"},
    "union_max_overload_credits": {"type": "number"},
    "reassignment_notice_days": {"type": "integer"},
    "late_cancel_stipend_cents": {"type": "integer"},
    "flat_release_rate_cents": {"type": "integer"},
}

POLICY_DEFAULTS = {
    "base_teaching_credits": 12,
    "lecture_multiplier": 1.0,
    "lab_multiplier": 0.75,
    "seminar_multiplier": 1.25,
    "online_premium_credits": 0.5,
    "large_class_threshold": 40,
    "large_class_bonus_credits": 1.0,
    "overload_comp_rate_cents": 150000,
    "union_max_overload_credits": 6,
    "reassignment_notice_days": 14,
    "late_cancel_stipend_cents": 100000,
    "flat_release_rate_cents": 80000,
}


def require_term(term_id):
    term = db.get("workload_terms", term_id)
    if term is None:
        raise ApiError(ERR_TERM_NOT_FOUND, 404, "term not found")
    return term


@bp.post("/workload-terms")
def create_term():
    authenticate([CHAIR])
    body = body_json()
    spec = {
        "term_code": {"type": "string", "required": True},
        "title": {"type": "string", "required": True},
        "start_date": {"type": "date", "required": True},
        "census_date": {"type": "date", "required": True},
        "comp_budget_cents": {"type": "integer", "required": True},
    }
    spec.update(_POLICY_SPEC)
    check_shape(body, spec)
    start = parse_date(body["start_date"], "start_date")
    census = parse_date(body["census_date"], "census_date")
    if census < start:
        raise ApiError(ERR_VALIDATION, 400, "census_date must not precede start_date")
    # Uniqueness (priority 8): term_code is globally unique.
    for existing in db.all_of("workload_terms"):
        if existing["term_code"] == body["term_code"]:
            raise ApiError(ERR_DUPLICATE_TERM_CODE, 409, "term_code already exists")
    fields = {
        "term_code": body["term_code"],
        "title": body["title"],
        "start_date": body["start_date"],
        "census_date": body["census_date"],
        "comp_budget_cents": body["comp_budget_cents"],
        "comp_budget_spent_cents": 0,
        "status": "DRAFT",
    }
    for name, default in POLICY_DEFAULTS.items():
        fields[name] = body[name] if present(body, name) else default
    term = db.new_entity("workload_terms", fields)
    return success_obj(db.public(term), 201)


@bp.get("/workload-terms")
def list_terms():
    authenticate(ALL_ROLES)
    limit, offset = pagination_params()
    items = apply_filters(db.all_of("workload_terms"), ["status"])
    page, total, has_more = paginate(items, limit, offset)
    return success_list([db.public(t) for t in page], limit, offset, total, has_more)


@bp.get("/workload-terms/<termId>")
def get_term(termId):
    authenticate(ALL_ROLES)
    return success_obj(db.public(require_term(termId)), 200)


@bp.patch("/workload-terms/<termId>")
def patch_term(termId):
    authenticate([CHAIR])
    body = body_json()
    spec = {
        "expected_term_version": {"type": "integer", "required": True},
        "title": {"type": "string"},
        "census_date": {"type": "date"},
        "comp_budget_cents": {"type": "integer"},
    }
    spec.update(_POLICY_SPEC)
    check_shape(body, spec)
    term = require_term(termId)
    # Shape-level cross-field rule: census_date must not precede start_date.
    if present(body, "census_date"):
        if parse_date(body["census_date"], "census_date") < parse_date(term["start_date"], "start_date"):
            raise ApiError(ERR_VALIDATION, 400, "census_date must not precede start_date")
    # State gate: policy edits only while DRAFT (PRD §2.5: fires before OCC).
    if term["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_TERM_STATE, 409, "policy edits are allowed only while the term is DRAFT")
    # OCC (priority 5.1).
    if body["expected_term_version"] != term["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_term_version does not match the term's current version")
    for name in ("title", "census_date", "comp_budget_cents", *_POLICY_SPEC.keys()):
        if present(body, name):
            term[name] = body[name]
    db.touch(term)
    return success_obj(db.public(term), 200)


@bp.post("/workload-terms/<termId>/transition")
def transition_term(termId):
    authenticate([CHAIR])
    body = body_json()
    check_shape(body, {"to_state": {"type": "enum", "values": TERM_STATUSES, "required": True}})
    term = require_term(termId)
    to_state = body["to_state"]
    current = term["status"]
    if to_state == "OPEN" and current in ("DRAFT", "LOCKED"):
        term["status"] = "OPEN"
    elif to_state == "LOCKED" and current == "OPEN":
        term["status"] = "LOCKED"
    elif to_state == "PUBLISHED" and current == "LOCKED":
        # Publish preconditions, evaluated in order (PRD §3.1).
        for section in db.all_of("course_sections"):
            if section["term_id"] == term["id"] and section["status"] in ("PROPOSED", "SCHEDULED"):
                raise ApiError(ERR_UNSTAFFED_SECTIONS, 409, "sections remain in PROPOSED or SCHEDULED")
        for sheet in db.all_of("load_sheets"):
            if sheet["term_id"] == term["id"] and sheet["overload_credits"] > 0:
                covered = any(
                    r["term_id"] == term["id"] and r["faculty_id"] == sheet["faculty_id"]
                    and r["status"] == "DEAN_APPROVED"
                    for r in db.all_of("overload_requests")
                )
                if not covered:
                    raise ApiError(ERR_UNCOVERED_OVERLOAD, 409, "overload_credits > 0 without a DEAN_APPROVED overload request")
        term["status"] = "PUBLISHED"
    else:
        raise ApiError(ERR_INVALID_TERM_STATE, 409, f"cannot move a {current} term to {to_state}")
    db.touch(term)
    return success_obj(db.public(term), 200)


@bp.post("/workload-terms/<termId>/close-census")
def close_census(termId):
    authenticate([CHAIR])
    body_json()  # body ignored; no inputs declared
    term = require_term(termId)
    if term["status"] == "DRAFT":
        raise ApiError(ERR_INVALID_TERM_STATE, 409, "close-census is not available while the term is DRAFT")
    if today() < parse_date(term["census_date"], "census_date"):
        raise ApiError(ERR_CENSUS_NOT_REACHED, 409, "the logical clock has not reached census_date")
    # Step 1: freeze final_credit_units for every CONFIRMED assignment using the
    # section's CURRENT enrolled_count.
    for a in db.all_of("assignments"):
        if a["term_id"] == term["id"] and a["status"] == "CONFIRMED":
            section = db.get("course_sections", a["section_id"])
            course = db.get("courses", section["course_id"])
            a["final_credit_units"] = services.assignment_credits(section, course, term, section["enrolled_count"])
            db.touch(a)
    # Step 2 + 3: recompute every sheet of the term (final preferred over
    # provisional); the auto-withdraw rule fires inside each recompute.
    for sheet in db.all_of("load_sheets"):
        if sheet["term_id"] == term["id"]:
            services.recompute_sheet(sheet)
    # Not a state transition of the term: WorkloadTerm.version is unchanged.
    return success_obj(db.public(term), 200)


@bp.get("/workload-terms/<termId>/load-summary")
def load_summary(termId):
    authenticate(ALL_ROLES)
    term = require_term(termId)
    sheets = []
    for sheet in db.all_of("load_sheets"):
        if sheet["term_id"] != term["id"]:
            continue
        faculty = db.get("faculty_members", sheet["faculty_id"])
        if faculty is not None and faculty["status"] != "SEPARATED":
            sheets.append(sheet)
    total_teaching = sum((dec(s["teaching_credits"]) for s in sheets), dec(0))
    overloaded = sum(1 for s in sheets if dec(s["overload_credits"]) > 0)
    underloaded = sum(1 for s in sheets if dec(s["underload_credits"]) > 0)
    if sheets:
        spread = max(dec(s["teaching_credits"]) for s in sheets) - min(dec(s["teaching_credits"]) for s in sheets)
    else:
        spread = dec(0)
    satisfied = unsatisfied = 0
    for a in db.all_of("assignments"):
        if a["term_id"] == term["id"] and a["status"] in ("PROPOSED", "CONFIRMED"):
            if a["matches_preference"]:
                satisfied += 1
            else:
                unsatisfied += 1
    spent = term["comp_budget_spent_cents"]
    summary = {
        "term_id": term["id"],
        "total_teaching_credits": float(total_teaching),
        "overloaded_faculty_count": overloaded,
        "underloaded_faculty_count": underloaded,
        "fairness_spread_credits": float(spread),
        "comp_budget_spent_cents": spent,
        "comp_budget_remaining_cents": term["comp_budget_cents"] - spent,
        "preference_satisfied_count": satisfied,
        "preference_unsatisfied_count": unsatisfied,
    }
    return success_obj(summary, 200)
