"""Treatment courses (PRD 3.1, 3.8, 3.9): prescription, complete/discontinue,
adaptation trigger."""
from flask import Blueprint

from db import store, new_entity, touch, sorted_all
from errors import (err, ERR_NOT_FOUND, ERR_COURSE_NOT_ON_TREATMENT,
                    ERR_OPEN_SESSIONS_EXIST, ERR_COURSE_TERMINAL)
from middleware import require_roles, ALL_ROLES, get_body
from response import success, paginate
from serializers import course_json
from services import calc
from services.billing import auto_reopen_finalized
from timeutil import new_id
from validate import req_str, req_enum, req_num, req_int, opt_bool

bp = Blueprint("courses", __name__)

INTENTS = {"CURATIVE", "PALLIATIVE"}
TECHNIQUES = {"THREE_DCRT", "IMRT", "SBRT"}
TERMINAL = {"COMPLETED", "DISCONTINUED"}


def get_course_or_404(cid):
    c = store.courses.get(cid)
    if c is None:
        err(ERR_NOT_FOUND, "treatment course not found")
    return c


@bp.post("/oncology/patients/<pid>/treatment-courses")
@require_roles("RadiationOncologist")
def create_course(pid, user_id):
    patient = store.patients.get(pid)
    if patient is None:
        err(ERR_NOT_FOUND, "patient not found")
    body = get_body()
    diagnosis_code = req_str(body, "diagnosis_code")
    intent = req_enum(body, "intent", INTENTS)
    technique = req_enum(body, "technique", TECHNIQUES)
    total = req_int(body, "prescribed_total_dose_cGy", minimum=1)
    planned = req_int(body, "planned_fractions", minimum=1)
    c = new_entity()
    c.update({
        "id": new_id(), "patient_id": pid,
        "diagnosis_code": diagnosis_code, "intent": intent, "technique": technique,
        "prescribed_total_dose_cGy": total, "planned_fractions": planned,
        "dose_per_fraction_cGy": calc.alloc_base(total, planned),
        "delivered_fractions": 0, "delivered_dose_cGy": 0,
        "fractions_since_chart_review": 0,
        "baseline_weight_kg": None,
        "weekend_makeup_allowance": 0, "open_interruption_count": 0,
        "status": "CONSULT",
    })
    store.courses[c["id"]] = c
    return success(course_json(c), 201)


@bp.get("/oncology/patients/<pid>/treatment-courses")
@require_roles(*ALL_ROLES)
def list_patient_courses(pid, user_id):
    if pid not in store.patients:
        err(ERR_NOT_FOUND, "patient not found")
    items = sorted_all(c for c in store.courses.values() if c["patient_id"] == pid)
    page, meta = paginate(items)
    return success([course_json(c) for c in page], 200, pagination=meta)


@bp.get("/oncology/treatment-courses/<cid>")
@require_roles(*ALL_ROLES)
def get_course(cid, user_id):
    return success(course_json(get_course_or_404(cid)), 200)


@bp.post("/oncology/treatment-courses/<cid>/complete")
@require_roles("RadiationOncologist")
def complete_course(cid, user_id):
    course = get_course_or_404(cid)
    get_body()
    if course["status"] != "ON_TREATMENT":
        err(ERR_COURSE_NOT_ON_TREATMENT, "Course completion requires ON_TREATMENT")
    for s in store.sessions.values():
        if s["course_id"] == cid and s["status"] == "SCHEDULED":
            err(ERR_OPEN_SESSIONS_EXIST,
                "Course completion blocked: fraction sessions still SCHEDULED")
    for p in store.plans.values():
        if p["course_id"] == cid and p["status"] == "ACTIVE":
            p["status"] = "COMPLETED"
            touch(p)
    course["status"] = "COMPLETED"
    touch(course)
    return success(course_json(course), 200)


@bp.post("/oncology/treatment-courses/<cid>/discontinue")
@require_roles("RadiationOncologist")
def discontinue_course(cid, user_id):
    course = get_course_or_404(cid)
    get_body()  # accepts an optional free-text reason
    if course["status"] in TERMINAL:
        err(ERR_COURSE_TERMINAL, "Course is already terminal")
    if course["status"] == "ON_TREATMENT":
        err(ERR_COURSE_NOT_ON_TREATMENT,
            "An ON_TREATMENT course is not discontinuable directly")
    # teardown cascade — each affected resource bumps its own version/updated_at
    for a in store.simulations.values():
        if a["course_id"] == cid and a["status"] == "SCHEDULED":
            a["status"] = "CANCELLED"
            touch(a)
    for s in store.sessions.values():
        if s["course_id"] == cid and s["status"] == "SCHEDULED":
            s["status"] = "CANCELLED"
            s["cancellation_reason"] = "OTHER"
            touch(s)
    for p in store.plans.values():
        if p["course_id"] == cid and p["status"] in (
                "DRAFT", "PENDING_PRIMARY_CHECK", "PENDING_SECOND_CHECK",
                "APPROVED_FOR_DELIVERY", "ACTIVE"):
            p["status"] = "SUPERSEDED"
            touch(p)
    auto_reopen_finalized(cid)
    course["status"] = "DISCONTINUED"
    touch(course)
    return success(course_json(course), 200)


@bp.post("/oncology/treatment-courses/<cid>/adaptation-checks")
@require_roles("RadiationOncologist")
def adaptation_check(cid, user_id):
    course = get_course_or_404(cid)
    body = get_body()
    current_weight = req_num(body, "current_weight_kg", minimum_exclusive=0)
    override = opt_bool(body, "physician_override", default=False)
    if course["status"] != "ON_TREATMENT":
        err(ERR_COURSE_NOT_ON_TREATMENT,
            "Adaptation evaluation requires the course ON_TREATMENT")
    # full float precision, no rounding before comparison (PRD 3.8)
    baseline = course["baseline_weight_kg"]
    weight_loss_pct = (baseline - current_weight) / baseline * 100.0
    if weight_loss_pct >= calc.WEIGHT_LOSS_THRESHOLD_PCT or override:
        course["status"] = "ADAPTATION_REQUIRED"
        for p in store.plans.values():
            if p["course_id"] == cid and p["status"] == "ACTIVE":
                p["status"] = "SUPERSEDED"
                touch(p)
                for s in store.sessions.values():
                    if s["plan_id"] == p["id"] and s["status"] == "SCHEDULED":
                        s["status"] = "CANCELLED"
                        s["cancellation_reason"] = "ADAPTATION"
                        touch(s)
        auto_reopen_finalized(cid)
        touch(course)
    return success(course_json(course), 200)
