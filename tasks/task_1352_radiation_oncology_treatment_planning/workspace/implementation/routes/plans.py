"""Treatment plans, dose constraints, physics checks (PRD 3.4, 3.5)."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_STALE_VERSION,
                    ERR_COURSE_NOT_PLANNING, ERR_COURSE_NOT_ADAPTING,
                    ERR_CONTOUR_NOT_APPROVED, ERR_SUPERSEDES_NOT_LATEST,
                    ERR_REMAINING_DOSE_MISMATCH, ERR_PLAN_NOT_DRAFT,
                    ERR_COURSE_TERMINAL, ERR_NO_DOSE_CONSTRAINTS,
                    ERR_DOSE_CONSTRAINT_VIOLATION, ERR_STALE_CONTOUR_SET,
                    ERR_PLAN_NOT_AWAITING_CHECK, ERR_SEGREGATION_OF_DUTIES,
                    ERR_PLAN_NOT_REVISABLE)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import plan_json, constraint_json, check_json, session_json
from services import calc
from services.billing import draft_claim, append_line
from timeutil import new_id
from validate import req_str, req_int, req_enum, opt_str

bp = Blueprint("plans", __name__)

CONSTRAINT_TYPES = {"MAX_DOSE", "MEAN_DOSE"}
CHECK_TYPES = {"PRIMARY", "SECOND"}
OUTCOMES = {"PASS", "FAIL"}


def get_plan_or_404(pid):
    p = store.plans.get(pid)
    if p is None:
        err(ERR_NOT_FOUND, "treatment plan not found")
    return p


def course_plans(cid):
    return [p for p in store.plans.values() if p["course_id"] == cid]


@bp.post("/oncology/treatment-courses/<cid>/treatment-plans")
@require_roles("MedicalDosimetrist")
def create_plan(cid, user_id):
    course = store.courses.get(cid)
    if course is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    body = get_body()
    # p3 existence: body-referenced ids validated before schema
    contour_id = body.get("contour_set_id")
    supersedes_id = body.get("supersedes_plan_id")
    if isinstance(contour_id, str) and contour_id not in store.contours:
        err(ERR_NOT_FOUND, "contour set not found")
    if supersedes_id is not None and isinstance(supersedes_id, str) \
            and supersedes_id not in store.plans:
        err(ERR_NOT_FOUND, "superseded plan not found")
    # p4 schema
    contour_id = req_str(body, "contour_set_id")
    target = req_int(body, "target_total_dose_cGy", minimum=1)
    planned = req_int(body, "planned_fractions", minimum=1)
    expected = req_int(body, "expected_course_version")
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        err(ERR_INVALID_REQUEST, "supersedes_plan_id must be a string or null")
    # p5 OCC against the course version
    if expected != course["version"]:
        err(ERR_STALE_VERSION, "expected_course_version is stale")
    # p6 course-state gate
    if supersedes_id is None:
        if course["status"] != "PLANNING":
            err(ERR_COURSE_NOT_PLANNING,
                "Initial plan creation requires course PLANNING")
    else:
        if course["status"] != "ADAPTATION_REQUIRED":
            err(ERR_COURSE_NOT_ADAPTING,
                "Adaptation plan creation requires course ADAPTATION_REQUIRED")
    # p10 cross-reference integrity, in PRD order
    contour = store.contours[contour_id]
    if contour["course_id"] != cid or contour["status"] != "APPROVED":
        err(ERR_CONTOUR_NOT_APPROVED,
            "contour_set_id is not APPROVED or belongs to another course")
    if supersedes_id is not None:
        existing = course_plans(cid)
        latest = max(existing, key=lambda p: p["plan_version"], default=None)
        if latest is None or latest["id"] != supersedes_id:
            err(ERR_SUPERSEDES_NOT_LATEST,
                "supersedes_plan_id must reference the highest plan_version plan of the course")
        if target != course["prescribed_total_dose_cGy"] - course["delivered_dose_cGy"]:
            err(ERR_REMAINING_DOSE_MISMATCH,
                "Adaptation plan target must equal prescribed minus delivered dose")
    else:
        if target != course["prescribed_total_dose_cGy"]:
            err(ERR_REMAINING_DOSE_MISMATCH,
                "Initial plan target must equal prescribed_total_dose_cGy")
    # create
    existing = course_plans(cid)
    next_version = 1 + max((p["plan_version"] for p in existing), default=0)
    plan = new_entity()
    plan.update({
        "id": new_id(), "course_id": cid, "contour_set_id": contour_id,
        "supersedes_plan_id": supersedes_id,
        "plan_version": next_version,
        "target_total_dose_cGy": target, "planned_fractions": planned,
        "dose_per_fraction_cGy": calc.alloc_base(target, planned),
        "planner_id": user_id,
        "pinned_contour_version": contour["version"],
        "primary_checker_id": None, "secondary_checker_id": None,
        "status": "DRAFT",
    })
    store.plans[plan["id"]] = plan
    # adaptation: course ADAPTATION_REQUIRED -> REPLANNING + fraction accounting
    if supersedes_id is not None:
        course["status"] = "REPLANNING"
        course["planned_fractions"] = course["delivered_fractions"] + planned
        course["dose_per_fraction_cGy"] = plan["dose_per_fraction_cGy"]
    touch(course)  # the create increments the course version by 1
    return success(plan_json(plan), 201)


@bp.get("/oncology/treatment-courses/<cid>/treatment-plans")
@require_roles(*ALL_ROLES)
def list_plans(cid, user_id):
    if cid not in store.courses:
        err(ERR_NOT_FOUND, "treatment course not found")
    items = sorted_all(course_plans(cid))
    page, meta = paginate(items)
    return success([plan_json(p) for p in page], 200, pagination=meta)


@bp.get("/oncology/treatment-plans/<pid>")
@require_roles(*ALL_ROLES)
def get_plan(pid, user_id):
    return success(plan_json(get_plan_or_404(pid)), 200)


@bp.get("/oncology/treatment-plans/<pid>/successors")
@require_roles(*ALL_ROLES)
def plan_successors(pid, user_id):
    get_plan_or_404(pid)
    items = sorted_all(p for p in store.plans.values()
                       if p["supersedes_plan_id"] == pid)
    page, meta = paginate(items)
    return success([plan_json(p) for p in page], 200, pagination=meta)


@bp.get("/oncology/contour-sets/<kid>/treatment-plans")
@require_roles(*ALL_ROLES)
def contour_plans(kid, user_id):
    if kid not in store.contours:
        err(ERR_NOT_FOUND, "contour set not found")
    items = sorted_all(p for p in store.plans.values() if p["contour_set_id"] == kid)
    page, meta = paginate(items)
    return success([plan_json(p) for p in page], 200, pagination=meta)


@bp.get("/oncology/treatment-plans/<pid>/fraction-sessions")
@require_roles(*ALL_ROLES)
def plan_sessions(pid, user_id):
    get_plan_or_404(pid)
    items = sorted_all(s for s in store.sessions.values() if s["plan_id"] == pid)
    page, meta = paginate(items)
    return success([session_json(s) for s in page], 200, pagination=meta)


@bp.post("/oncology/treatment-plans/<pid>/dose-constraints")
@require_roles("MedicalDosimetrist")
def add_constraint(pid, user_id):
    plan = get_plan_or_404(pid)
    body = get_body()
    structure = req_str(body, "structure_name")
    ctype = req_enum(body, "constraint_type", CONSTRAINT_TYPES)
    limit = req_int(body, "limit_cGy", minimum=1)
    evaluated = req_int(body, "evaluated_value_cGy", minimum=0)
    if plan["status"] != "DRAFT":
        err(ERR_PLAN_NOT_DRAFT, "Dose constraints require plan DRAFT")
    dc = new_entity()
    dc.update({
        "id": new_id(), "plan_id": pid, "structure_name": structure,
        "constraint_type": ctype, "limit_cGy": limit,
        "evaluated_value_cGy": evaluated,
        "satisfied": evaluated <= limit,
    })
    store.constraints[dc["id"]] = dc
    return success(constraint_json(dc), 201)


@bp.get("/oncology/treatment-plans/<pid>/dose-constraints")
@require_roles(*ALL_ROLES)
def list_constraints(pid, user_id):
    get_plan_or_404(pid)
    items = sorted_all(c for c in store.constraints.values() if c["plan_id"] == pid)
    page, meta = paginate(items)
    return success([constraint_json(c) for c in page], 200, pagination=meta)


@bp.post("/oncology/treatment-plans/<pid>/submit-for-check")
@require_roles("MedicalDosimetrist")
def submit_for_check(pid, user_id):
    plan = get_plan_or_404(pid)
    get_body()
    # p6 state gates
    if plan["status"] != "DRAFT":
        err(ERR_PLAN_NOT_DRAFT, "Submit-for-check requires plan DRAFT")
    course = store.courses[plan["course_id"]]
    if course["status"] in ("COMPLETED", "DISCONTINUED"):
        err(ERR_COURSE_TERMINAL, "Course is terminal")
    # p9 dose-constraint sufficiency
    constraints = [c for c in store.constraints.values() if c["plan_id"] == pid]
    if not constraints:
        err(ERR_NO_DOSE_CONSTRAINTS,
            "Submit-for-check requires at least one dose constraint")
    for c in constraints:
        if not c["satisfied"]:
            err(ERR_DOSE_CONSTRAINT_VIOLATION,
                "A dose constraint has evaluated_value_cGy > limit_cGy")
    # p10 pinned contour freshness
    contour = store.contours.get(plan["contour_set_id"])
    if contour is None or contour["status"] != "APPROVED" \
            or contour["version"] != plan["pinned_contour_version"]:
        err(ERR_STALE_CONTOUR_SET,
            "Contour set version no longer equals pinned_contour_version")
    plan["status"] = "PENDING_PRIMARY_CHECK"
    touch(plan)
    if course["status"] in ("PLANNING", "REPLANNING"):
        course["status"] = "PHYSICS_REVIEW"
        touch(course)
    return success(plan_json(plan), 200)


@bp.post("/oncology/treatment-plans/<pid>/revise")
@require_roles("MedicalDosimetrist")
def revise_plan(pid, user_id):
    plan = get_plan_or_404(pid)
    get_body()
    if plan["status"] != "CHECK_FAILED":
        err(ERR_PLAN_NOT_REVISABLE, "Revise requires plan CHECK_FAILED")
    plan["status"] = "DRAFT"
    touch(plan)
    return success(plan_json(plan), 200)


@bp.post("/oncology/treatment-plans/<pid>/physics-checks")
@require_roles("MedicalPhysicist")
def record_check(pid, user_id):
    plan = get_plan_or_404(pid)
    body = get_body()
    check_type = req_enum(body, "check_type", CHECK_TYPES)
    outcome = req_enum(body, "outcome", OUTCOMES)
    notes = opt_str(body, "notes")
    # p6: check type must match the plan's awaiting state
    if check_type == "PRIMARY" and plan["status"] != "PENDING_PRIMARY_CHECK":
        err(ERR_PLAN_NOT_AWAITING_CHECK,
            "PRIMARY check requires plan PENDING_PRIMARY_CHECK")
    if check_type == "SECOND" and plan["status"] != "PENDING_SECOND_CHECK":
        err(ERR_PLAN_NOT_AWAITING_CHECK,
            "SECOND check requires plan PENDING_SECOND_CHECK")
    # p7 segregation of duties
    if check_type == "PRIMARY" and user_id == plan["planner_id"]:
        err(ERR_SEGREGATION_OF_DUTIES,
            "The plan's dosimetrist may not perform its primary physics check")
    if check_type == "SECOND" and user_id == plan["primary_checker_id"]:
        err(ERR_SEGREGATION_OF_DUTIES,
            "The primary checker may not perform the second check")
    chk = new_entity(common=False)
    chk.update({
        "id": new_id(), "plan_id": pid, "check_type": check_type,
        "outcome": outcome, "checker_id": user_id, "notes": notes,
    })
    store.checks[chk["id"]] = chk
    course = store.courses[plan["course_id"]]
    claim = draft_claim(course["id"])
    if outcome == "PASS":
        if check_type == "PRIMARY":
            plan["primary_checker_id"] = user_id
            plan["status"] = "PENDING_SECOND_CHECK"
            touch(plan)
            if claim is not None:
                append_line(claim, "PHYSICS_CHECK", "Physics plan check",
                            calc.PHYSICS_CHECK_FEE_CENTS, chk["id"])
        else:
            plan["secondary_checker_id"] = user_id
            plan["status"] = "APPROVED_FOR_DELIVERY"
            touch(plan)
            if course["status"] == "PHYSICS_REVIEW":
                course["status"] = "TREATMENT_READY"
                touch(course)
            if claim is not None:
                append_line(claim, "PHYSICS_CHECK", "Physics plan check",
                            calc.PHYSICS_CHECK_FEE_CENTS, chk["id"])
                contour = store.contours.get(plan["contour_set_id"])
                n_targets = len(contour["target_volumes"]) if contour else 1
                amount = calc.planning_charge_cents(
                    course["technique"], n_targets,
                    plan["supersedes_plan_id"] is not None)
                append_line(claim, "PLANNING", "Treatment planning",
                            amount, plan["id"])
    else:  # FAIL at either stage -> CHECK_FAILED; course leaves PHYSICS_REVIEW
        plan["status"] = "CHECK_FAILED"
        touch(plan)
        if course["status"] == "PHYSICS_REVIEW":
            course["status"] = ("REPLANNING" if plan["supersedes_plan_id"]
                                else "PLANNING")
            touch(course)
    return success(check_json(chk), 201)


@bp.get("/oncology/treatment-plans/<pid>/physics-checks")
@require_roles(*ALL_ROLES)
def list_checks(pid, user_id):
    get_plan_or_404(pid)
    items = sorted_all(c for c in store.checks.values() if c["plan_id"] == pid)
    page, meta = paginate(items)
    return success([check_json(c) for c in page], 200, pagination=meta)
