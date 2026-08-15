"""Enrollments, benefits investigation, and discontinuation."""

from flask import Blueprint

from db import store, new_id, now_iso
from errors import ApiError, ERR_ENROLLMENT_DISCONTINUED, ERR_INVALID_TRANSITION
from middleware import require_roles, get_auth
from response import success_object, success_array
from services.common import (
    body, body_optional, req_string, req_bool, req_int,
    get_enrollment_or_404, get_program_or_404, pagination_params, paginate,
    touch,
)
from services.calc import (
    serialize_enrollment, serialize_bi, bi_for_enrollment,
    activate_reserved_assistance, release_all_nonterminal_assistances,
    cancel_pending_shipments,
)

bp = Blueprint("enrollments", __name__)


@bp.post("/hub/enrollments")
def create_enrollment():
    user_id, _ = require_roles("CaseManager")
    data = body()
    program_id = req_string(data, "program_id")
    patient_ref = req_string(data, "patient_ref")
    diagnosis_code = req_string(data, "diagnosis_code")
    # Path-equivalent existence: program_id must resolve.
    get_program_or_404(program_id)

    ts = now_iso()
    enrollment = {
        "id": new_id(),
        "program_id": program_id,
        "patient_ref": patient_ref,
        "diagnosis_code": diagnosis_code,
        "case_manager_id": user_id,
        "status": "INTAKE",
        "training_sessions_completed": 0,
        "fills_delivered_count": 0,
        "therapy_start_date": None,
        "payer_accumulated_oop_cents": 0,
        "remaining_oop_cents": None,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    store.enrollments[enrollment["id"]] = enrollment
    return success_object(serialize_enrollment(enrollment), 201)


@bp.get("/hub/enrollments/<eid>")
def get_enrollment(eid):
    get_auth()
    e = get_enrollment_or_404(eid)
    return success_object(serialize_enrollment(e), 200)


@bp.get("/hub/enrollments")
def list_enrollments():
    get_auth()
    limit, offset = pagination_params()
    status_filter = None
    program_filter = None
    from flask import request
    if "status" in request.args:
        status_filter = request.args.get("status")
    if "program_id" in request.args:
        program_filter = request.args.get("program_id")
    items = list(store.enrollments.values())
    if status_filter is not None:
        items = [e for e in items if e["status"] == status_filter]
    if program_filter is not None:
        items = [e for e in items if e["program_id"] == program_filter]
    page, total = paginate(items, limit, offset)
    return success_array([serialize_enrollment(e) for e in page],
                         limit, offset, total, 200)


@bp.post("/hub/enrollments/<eid>/discontinue")
def discontinue_enrollment(eid):
    require_roles("CaseManager")
    body_optional()  # optional `reason` accepted, not persisted
    e = get_enrollment_or_404(eid)
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is already terminal.", 409)
    if e["status"] == "INTAKE":
        # PRD 3.2: discontinuation applies to enrollments in
        # BENEFITS_VERIFIED / PA_PENDING / PA_DENIED / APPROVED / ACTIVE.
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Enrollment in INTAKE cannot be discontinued.", 409)
    e["status"] = "DISCONTINUED"
    touch(e)
    release_all_nonterminal_assistances(e)
    cancel_pending_shipments(e)
    return success_object(serialize_enrollment(e), 200)


@bp.post("/hub/enrollments/<eid>/benefits-investigation")
def create_bi(eid):
    require_roles("CaseManager")
    e = get_enrollment_or_404(eid)
    data = body()
    payer_name = req_string(data, "payer_name")
    member_id = req_string(data, "member_id")
    requires_prior_auth = req_bool(data, "requires_prior_auth")
    plan_has_accumulator = req_bool(data, "plan_has_accumulator")
    patient_cost_share_cents = req_int(data, "patient_cost_share_cents")
    oop_max_cents = req_int(data, "oop_max_cents")

    # State validity: terminal enrollment rejects child-mutating ops.
    if e["status"] in ("DISCONTINUED", "DENIED_CLOSED"):
        raise ApiError(ERR_ENROLLMENT_DISCONTINUED,
                       "Enrollment is terminal.", 409)
    # Exactly one BI per enrollment; creation only valid from INTAKE.
    if e["status"] != "INTAKE" or bi_for_enrollment(eid) is not None:
        raise ApiError(ERR_INVALID_TRANSITION,
                       "Benefits investigation already exists or enrollment "
                       "is not in INTAKE.", 409)

    ts = now_iso()
    bi = {
        "id": new_id(),
        "enrollment_id": eid,
        "payer_name": payer_name,
        "member_id": member_id,
        "requires_prior_auth": requires_prior_auth,
        "plan_has_accumulator": plan_has_accumulator,
        "patient_cost_share_cents": patient_cost_share_cents,
        "oop_max_cents": oop_max_cents,
        "created_at": ts,
    }
    store.benefits_investigations[bi["id"]] = bi

    # Enrollment INTAKE -> BENEFITS_VERIFIED; remaining_oop_cents := oop_max.
    e["status"] = "BENEFITS_VERIFIED"
    e["remaining_oop_cents"] = oop_max_cents
    touch(e)

    # When no PA required, immediately advance to APPROVED + approval cascade.
    if not requires_prior_auth:
        e["status"] = "APPROVED"
        touch(e)
        activate_reserved_assistance(e)

    return success_object(serialize_bi(bi), 201)


@bp.get("/hub/enrollments/<eid>/benefits-investigation")
def get_bi(eid):
    get_auth()
    get_enrollment_or_404(eid)
    bi = bi_for_enrollment(eid)
    items = [serialize_bi(bi)] if bi is not None else []
    # Sorted by created_at ASC (trivially, 0 or 1 elements).
    limit, offset = pagination_params()
    page, total = paginate(
        [bi] if bi is not None else [], limit, offset)
    return success_array([serialize_bi(b) for b in page],
                         limit, offset, total, 200)
