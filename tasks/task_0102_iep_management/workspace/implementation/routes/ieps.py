"""IEP routes: draft/list/get/activate/begin-amendment/finalize-amendment/lre-summary."""

from flask import Blueprint, request

from core.auth import require_role
from core.envelope import success_object, success_array
from core.errors import APIError
from core.pagination import parse_pagination, paginate
from core.store import (
    IEPS, GOALS, EVALUATIONS, CONSENTS, TRANSITION_PLANS, STUDENTS, stamp_create, stamp_update,
)
from core.validation import (
    get_district, get_student, get_iep, require_json_body, check_version,
)
from core.clock import (
    parse_dt, datetime_at_or_before, advance_days, format_dt,
    datetime_strictly_before,
)

from services.cascades import cascade_iep_supersede
from services.computations import (
    compute_requires_transition_plan,
    recompute_iep_lre,
    recompute_student_lre_classification,
    classify_lre_from_instructional,
    sped_pullout_minutes_for_iep,
)
from services.serializers import iep_dto


bp = Blueprint("ieps", __name__)


@bp.route("/districts/<district_id>/students/<student_id>/ieps", methods=["POST"])
def create_iep(district_id, student_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    body = require_json_body()

    meeting_held_at = body.get("meeting_held_at")
    effective_start_date = body.get("effective_start_date")
    total_instr = body.get("total_instructional_minutes_per_week")
    total_school = body.get("total_school_day_minutes_per_week")

    if not isinstance(meeting_held_at, str) or not meeting_held_at:
        raise APIError("ERR_INVALID_REQUEST", "meeting_held_at is required.")
    if not isinstance(effective_start_date, str) or not effective_start_date:
        raise APIError("ERR_INVALID_REQUEST", "effective_start_date is required.")
    if not isinstance(total_instr, int) or isinstance(total_instr, bool) or total_instr <= 0:
        raise APIError("ERR_INVALID_REQUEST", "total_instructional_minutes_per_week must be a positive integer.")
    if not isinstance(total_school, int) or isinstance(total_school, bool) or total_school <= 0:
        raise APIError("ERR_INVALID_REQUEST", "total_school_day_minutes_per_week must be a positive integer.")
    if total_school < total_instr:
        # School-day denominator is the larger of the two (PRD §3.8).
        raise APIError(
            "ERR_INVALID_REQUEST",
            "total_school_day_minutes_per_week must be >= total_instructional_minutes_per_week.",
        )

    iep = {
        "student_id": student_id,
        "district_id": district_id,
        "meeting_held_at": meeting_held_at,
        "effective_start_date": effective_start_date,
        "scheduled_review_date": advance_days(effective_start_date, 365),
        "total_instructional_minutes_per_week": total_instr,
        "total_school_day_minutes_per_week": total_school,
        "special_education_minutes_per_week": 0,
        "lre_percentage_instructional": 0.00,
        "lre_percentage_school_day": 0.00,
        "requires_transition_plan": False,
        "transition_plan_id": None,
        "status": "DRAFT",
    }
    stamp_create(iep)
    IEPS[iep["id"]] = iep
    return success_object(iep_dto(iep), http_status=201)


@bp.route("/districts/<district_id>/students/<student_id>/ieps", methods=["GET"])
def list_ieps(district_id, student_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher", "RelatedServiceProvider",
                                  "SchoolPsychologist", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    limit, offset = parse_pagination()
    status_q = request.args.get("status")
    rows = [i for i in IEPS.values() if i.get("student_id") == student_id]
    if status_q:
        rows = [i for i in rows if i.get("status") == status_q]
    rows.sort(key=lambda r: r.get("created_at", ""))
    page, total = paginate([iep_dto(i) for i in rows], limit, offset)
    return success_array(page, limit=limit, offset=offset, total_count=total)


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>", methods=["GET"])
def get_iep_route(district_id, student_id, iep_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher", "RelatedServiceProvider",
                                  "SchoolPsychologist", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    iep = get_iep(district_id, student_id, iep_id)
    return success_object(iep_dto(iep))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/lre-summary", methods=["GET"])
def lre_summary(district_id, student_id, iep_id):
    user_id, role = require_role(["DistrictAdmin", "SpecialEducationTeacher", "RelatedServiceProvider",
                                  "SchoolPsychologist", "Parent"])
    student = get_student(district_id, student_id)
    if role == "Parent" and user_id != student.get("parent_user_id"):
        raise APIError("ERR_PARENT_OWNERSHIP_MISMATCH", "Parent may only act on their own student.")
    iep = get_iep(district_id, student_id, iep_id)

    # Recompute fresh values, but only persist if anything changed materially.
    recompute_iep_lre(iep)
    # PRD §3.8: `total_sped_minutes` is the pull-out-minutes numerator
    # (PULL_OUT + COMMUNITY only — PUSH_IN does not contribute).
    total_sped = sped_pullout_minutes_for_iep(iep_id)
    classification = classify_lre_from_instructional(iep.get("lre_percentage_instructional", 0.0))
    return success_object({
        "lre_percentage_instructional": iep.get("lre_percentage_instructional", 0.00),
        "lre_percentage_school_day": iep.get("lre_percentage_school_day", 0.00),
        "lre_classification": classification,
        "total_sped_minutes": total_sped,
    })


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/activate", methods=["POST"])
def activate_iep(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    district = get_district(district_id)
    student = get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()
    check_version(body.get("version"), iep.get("version", 1))

    # Validations in priority order (PRD §2.9 priorities 5+).
    if iep.get("status") != "DRAFT":
        raise APIError("ERR_IEP_NOT_DRAFT", "IEP is not in DRAFT.")

    # Priority 8: student eligibility
    ev_id = student.get("current_eligibility_evaluation_id")
    eligible = False
    if ev_id:
        ev = EVALUATIONS.get(ev_id)
        eligible = bool(ev and ev.get("status") == "ELIGIBLE")
    if not eligible:
        raise APIError("ERR_STUDENT_NOT_ELIGIBLE", "Student is not eligible.")

    # Priority 9: IEP-implementation consent in APPROVED for this IEP
    has_consent = False
    for c in CONSENTS.values():
        if (c.get("scope") == "IEP_IMPLEMENTATION"
                and c.get("target_resource_type") == "IEP"
                and c.get("target_resource_id") == iep_id
                and c.get("status") == "APPROVED"):
            has_consent = True
            break
    if not has_consent:
        raise APIError("ERR_IEP_CONSENT_NOT_APPROVED", "No APPROVED IEP_IMPLEMENTATION consent.")

    # IEP meeting must be at or before current_date
    meeting = iep.get("meeting_held_at")
    if not meeting or not datetime_at_or_before(meeting, district["current_date"]):
        raise APIError("ERR_IEP_MEETING_NOT_HELD", "meeting_held_at is null or in the future.")

    # At least one PROPOSED goal
    proposed_goals = [g for g in GOALS.values() if g.get("iep_id") == iep_id and g.get("status") == "PROPOSED"]
    if not proposed_goals:
        raise APIError("ERR_IEP_NO_GOALS", "IEP has no PROPOSED goals.")

    # Priority 11: transition plan requirement
    requires_tp = compute_requires_transition_plan(
        {**student, "current_iep_id": "_pending_"}, district["current_date"]
    )
    # compute_requires_transition_plan requires current_iep_id non-null; for activation we
    # are evaluating the prospective state (student will have THIS IEP). The PRD says
    # "if requires_transition_plan is true for the student" — see §3.3.
    if requires_tp:
        tp = _transition_plan_for_iep(iep_id)
        if tp is None or tp.get("status") != "FINALIZED":
            raise APIError("ERR_TRANSITION_PLAN_REQUIRED", "TransitionPlan required and not FINALIZED.")

    # Priority 12: at-most-one-active IEP per student (excluding this iep)
    prior_active_iep = None
    for other in IEPS.values():
        if other["id"] == iep_id:
            continue
        if other.get("student_id") != student_id:
            continue
        if other.get("status") in ("ACTIVE", "AMENDMENT_PENDING"):
            prior_active_iep = other
            # The PRD says this raises ERR_IEP_ALREADY_ACTIVE — but the supersession path
            # exists only when the prior IEP "was previously in ACTIVE". The phrasing in
            # §3.3 says "If a different IEP for this student was previously in ACTIVE,
            # that prior IEP is automatically transitioned to SUPERSEDED per §3.5."
            # However priority 12 in §2.9 says ERR_IEP_ALREADY_ACTIVE if another is currently
            # active. We treat ERR_IEP_ALREADY_ACTIVE as the validation that fires.
            raise APIError("ERR_IEP_ALREADY_ACTIVE", "Student already has an ACTIVE/AMENDMENT_PENDING IEP.")

    # Priority 15: IEP period overlap (effective_start_date strictly after prior IEP.scheduled_review_date)
    new_start = iep.get("effective_start_date")
    for other in IEPS.values():
        if other["id"] == iep_id:
            continue
        if other.get("student_id") != student_id:
            continue
        prior_review = other.get("scheduled_review_date")
        if not prior_review:
            continue
        # Only consider IEPs that have had a real lifetime — exclude DRAFTs that never activated.
        if other.get("status") == "DRAFT":
            continue
        # Half-open semantics: new_start must be strictly later than prior_review.
        if not datetime_strictly_before(prior_review, new_start):
            raise APIError(
                "ERR_IEP_PERIOD_OVERLAP",
                "effective_start_date must be strictly after the prior IEP's scheduled_review_date.",
            )

    # Activate.
    iep["status"] = "ACTIVE"
    iep["scheduled_review_date"] = advance_days(iep["effective_start_date"], 365)
    # Lock requires_transition_plan at the moment of activation.
    student_for_lock = {**student, "current_iep_id": iep_id}
    iep["requires_transition_plan"] = compute_requires_transition_plan(
        student_for_lock, district["current_date"]
    )
    # Link transition plan if present.
    tp = _transition_plan_for_iep(iep_id)
    if tp is not None:
        iep["transition_plan_id"] = tp["id"]
        if tp.get("status") == "FINALIZED":
            tp["status"] = "ACTIVE"
            stamp_update(tp)
    stamp_update(iep)

    # All PROPOSED goals → ACTIVE
    for g in proposed_goals:
        g["status"] = "ACTIVE"
        stamp_update(g)

    # Student.current_iep_id = iep.id; recompute LRE classification.
    student["current_iep_id"] = iep_id
    recompute_iep_lre(iep)
    recompute_student_lre_classification(student)
    stamp_update(student)

    return success_object(iep_dto(iep))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/begin-amendment", methods=["POST"])
def begin_amendment(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()
    check_version(body.get("version"), iep.get("version", 1))
    if iep.get("status") != "ACTIVE":
        raise APIError("ERR_IEP_NOT_ACTIVE", "IEP is not in ACTIVE.")
    iep["status"] = "AMENDMENT_PENDING"
    stamp_update(iep)
    return success_object(iep_dto(iep))


@bp.route("/districts/<district_id>/students/<student_id>/ieps/<iep_id>/finalize-amendment", methods=["POST"])
def finalize_amendment(district_id, student_id, iep_id):
    require_role(["SpecialEducationTeacher"])
    get_district(district_id)
    student = get_student(district_id, student_id)
    iep = get_iep(district_id, student_id, iep_id)
    body = require_json_body()
    check_version(body.get("version"), iep.get("version", 1))
    if iep.get("status") != "AMENDMENT_PENDING":
        raise APIError("ERR_IEP_NOT_AMENDMENT_PENDING", "IEP is not in AMENDMENT_PENDING.")
    iep["status"] = "ACTIVE"
    stamp_update(iep)
    # Re-evaluate student LRE classification and goal mastery for any in-flight progress.
    if student.get("current_iep_id") == iep_id:
        recompute_iep_lre(iep)
        recompute_student_lre_classification(student)
        stamp_update(student)
    # Goal mastery re-trigger on amendment finalize (PRD §3.7).
    from services.computations import recompute_goal_mastery
    for g in GOALS.values():
        if g.get("iep_id") == iep_id:
            recompute_goal_mastery(g)
    return success_object(iep_dto(iep))


# ---- internal ----

def _transition_plan_for_iep(iep_id: str):
    for tp in TRANSITION_PLANS.values():
        if tp.get("iep_id") == iep_id:
            return tp
    return None
