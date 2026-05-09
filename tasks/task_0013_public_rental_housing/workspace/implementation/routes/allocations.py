"""Allocation, objection, and contract auto-creation routes."""
from flask import Blueprint, request

from common import (
    check_version,
    get_allocation_or_404,
    get_application_or_404,
    get_housing_unit_or_404,
    get_json_body,
    get_objection_or_404,
    get_program_or_404,
    paginate,
    require_field,
    stamp_new,
    stamp_update,
)
from db import db
from errors import api_error
from middleware import require_roles
from response import success
from services.allocation import select_application_for_unit
from services.calc import compute_deposit_amount
from services.sync import emit_audit_allocation_decision

bp = Blueprint("allocations", __name__)


# ----------------------------------------------------------------------------
# POST /allocations  — HousingOfficer
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations")
def create_allocation(program_id):
    user_id, _ = require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    body = get_json_body()
    unit_id = require_field(body, "housing_unit_id")
    unit = get_housing_unit_or_404(program_id, unit_id)

    with db.lock:
        # First-writer-wins on AVAILABLE → RESERVED
        if unit.get("status") != "AVAILABLE":
            raise api_error("ERR_UNIT_NOT_AVAILABLE",
                            "HousingUnit is not AVAILABLE")
        application = select_application_for_unit(program, unit)
        if application is None:
            raise api_error("ERR_NO_ELIGIBLE_APPLICATION",
                            "No QUEUED Application matches the unit")

        cpi = int(program["current_period_index"])
        notice_len = int(program.get("notice_period_length", 7))
        allocation = {
            "housing_program_id": program_id,
            "application_id": application["id"],
            "housing_unit_id": unit["id"],
            "notice_start_period": cpi,
            "notice_end_period": cpi + notice_len,
            "confirmation_period": None,
            "status": "PUBLISHED",
        }
        stamp_new(allocation)
        db.allocations[allocation["id"]] = allocation

        unit["status"] = "RESERVED"
        stamp_update(unit)
        application["status"] = "ALLOCATED"
        stamp_update(application)

        emit_audit_allocation_decision(
            program_id=program_id,
            subject_type="ALLOCATION",
            subject_id=allocation["id"],
            actor_user_id=user_id,
            before={"unit_status": "AVAILABLE",
                    "application_status": "QUEUED"},
            after={"unit_status": "RESERVED",
                   "application_status": "ALLOCATED",
                   "allocation_status": "PUBLISHED"},
            note="allocation published",
            current_period_index=cpi,
        )
    return success(allocation, status=201)


# ----------------------------------------------------------------------------
# GET /allocations
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/allocations")
def list_allocations(program_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    status_filter = request.args.get("status")
    items = []
    for a in db.allocations.values():
        if a.get("housing_program_id") != program_id:
            continue
        if status_filter and a.get("status") != status_filter:
            continue
        items.append(a)
    page, meta = paginate(items)
    return success(page, response_type="array", pagination=meta)


# ----------------------------------------------------------------------------
# GET /allocations/{allocId}
# ----------------------------------------------------------------------------
@bp.get("/housing-programs/<program_id>/allocations/<alloc_id>")
def get_allocation(program_id, alloc_id):
    require_roles("HousingDirector", "HousingOfficer", "Applicant", "Citizen",
                  "IntegrationGateway")
    get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    return success(allocation)


# ----------------------------------------------------------------------------
# POST /allocations/{allocId}/confirm  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations/<alloc_id>/confirm")
def confirm_allocation(program_id, alloc_id):
    user_id, _ = require_roles("Applicant")
    program = get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    body = get_json_body()
    check_version(allocation, body)

    application = get_application_or_404(program_id, allocation["application_id"])
    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may confirm this allocation")

    with db.lock:
        if allocation.get("status") != "PUBLISHED":
            raise api_error("ERR_ALLOCATION_NOT_PUBLISHED",
                            "Allocation must be PUBLISHED")
        cpi = int(program["current_period_index"])
        if cpi < int(allocation["notice_end_period"]):
            raise api_error("ERR_NOTICE_PERIOD_NOT_ELAPSED",
                            "Notice period has not elapsed")

        allocation["status"] = "CONFIRMED"
        allocation["confirmation_period"] = cpi
        stamp_update(allocation)

        # Auto-create Contract in DRAFT
        unit = db.housing_units.get(allocation["housing_unit_id"])
        deposit = compute_deposit_amount(int(unit.get("monthly_base_rent_cents", 0)))
        contract = {
            "allocation_id": allocation["id"],
            "application_id": application["id"],
            "housing_unit_id": unit["id"],
            "lease_start_period": None,
            "lease_end_period": None,
            "deposit_amount_cents": deposit,
            "deposit_paid": False,
            "signature_blob": None,
            "handover_recorded": False,
            "monthly_effective_rent_cents": 0,
            "status": "DRAFT",
            "termination_period": None,
        }
        stamp_new(contract)
        db.contracts[contract["id"]] = contract

        emit_audit_allocation_decision(
            program_id=program_id,
            subject_type="ALLOCATION",
            subject_id=allocation["id"],
            actor_user_id=user_id,
            before={"status": "PUBLISHED"},
            after={"status": "CONFIRMED",
                   "contract_id": contract["id"]},
            note="allocation confirmed",
            current_period_index=cpi,
        )
    return success(allocation)


# ----------------------------------------------------------------------------
# POST /allocations/{allocId}/reject  — Applicant
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations/<alloc_id>/reject")
def reject_allocation(program_id, alloc_id):
    user_id, _ = require_roles("Applicant")
    program = get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    body = get_json_body()
    check_version(allocation, body)

    application = get_application_or_404(program_id, allocation["application_id"])
    if application.get("applicant_user_id") != user_id:
        raise api_error("ERR_INSUFFICIENT_PERMISSIONS",
                        "Only the owning applicant may reject this allocation")

    with db.lock:
        if allocation.get("status") != "PUBLISHED":
            raise api_error("ERR_ALLOCATION_NOT_PUBLISHED",
                            "Allocation must be PUBLISHED")
        unit = db.housing_units.get(allocation["housing_unit_id"])

        allocation["status"] = "REVERTED"
        stamp_update(allocation)
        if application.get("status") == "ALLOCATED":
            application["status"] = "QUEUED"
            stamp_update(application)
        if unit and unit.get("status") == "RESERVED":
            unit["status"] = "AVAILABLE"
            stamp_update(unit)
        emit_audit_allocation_decision(
            program_id=program_id,
            subject_type="ALLOCATION",
            subject_id=allocation["id"],
            actor_user_id=user_id,
            before={"status": "PUBLISHED"},
            after={"status": "REVERTED"},
            note="allocation rejected by applicant",
            current_period_index=int(program["current_period_index"]),
        )
    return success(allocation)


# ----------------------------------------------------------------------------
# POST /allocations/{allocId}/objections  — Applicant or Citizen
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations/<alloc_id>/objections")
def create_objection(program_id, alloc_id):
    user_id, role = require_roles("Applicant", "Citizen")
    program = get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    body = get_json_body()

    reason_text = require_field(body, "reason_text")
    if not isinstance(reason_text, str) or len(reason_text) < 20:
        raise api_error("ERR_INVALID_REQUEST",
                        "reason_text must be a string of at least 20 characters")

    with db.lock:
        # Notice window check (validation order: state then temporal)
        if allocation.get("status") not in {"PUBLISHED", "UNDER_OBJECTION"}:
            raise api_error("ERR_ALLOCATION_NOT_PUBLISHED",
                            "Allocation must be PUBLISHED")
        cpi = int(program["current_period_index"])
        if cpi >= int(allocation["notice_end_period"]):
            raise api_error("ERR_NOTICE_PERIOD_CLOSED",
                            "Notice period closed")

        objection = {
            "allocation_id": allocation["id"],
            "submitter_user_id": user_id,
            "reason_text": reason_text,
            "review_decision": None,
            "review_notes": None,
            "status": "PENDING_REVIEW",
        }
        stamp_new(objection)
        db.objections[objection["id"]] = objection

        if allocation.get("status") == "PUBLISHED":
            allocation["status"] = "UNDER_OBJECTION"
            stamp_update(allocation)
    return success(objection, status=201)


# ----------------------------------------------------------------------------
# POST /allocations/{allocId}/objections/{objId}/sustain
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations/<alloc_id>/objections/<obj_id>/sustain")
def sustain_objection(program_id, alloc_id, obj_id):
    user_id, _ = require_roles("HousingOfficer")
    program = get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    objection = get_objection_or_404(alloc_id, obj_id)
    body = get_json_body()
    check_version(objection, body)
    notes = body.get("review_notes")

    with db.lock:
        if objection.get("status") != "PENDING_REVIEW":
            raise api_error("ERR_OBJECTION_NOT_PENDING",
                            "Objection must be PENDING_REVIEW")
        if allocation.get("status") not in {"PUBLISHED", "UNDER_OBJECTION"}:
            raise api_error("ERR_ALLOCATION_NOT_PUBLISHED",
                            "Allocation must be PUBLISHED or UNDER_OBJECTION")

        objection["status"] = "SUSTAINED"
        objection["review_decision"] = "SUSTAINED"
        if notes is not None:
            objection["review_notes"] = notes
        stamp_update(objection)

        # Cascade: allocation → REVERTED
        before_alloc = allocation["status"]
        allocation["status"] = "REVERTED"
        stamp_update(allocation)

        # Auto-dismiss every other PENDING_REVIEW objection on this allocation
        for o in db.objections.values():
            if o is objection:
                continue
            if o.get("allocation_id") != alloc_id:
                continue
            if o.get("status") == "PENDING_REVIEW":
                o["status"] = "DISMISSED"
                o["review_decision"] = "DISMISSED"
                o["review_notes"] = "allocation reverted"
                stamp_update(o)

        # Cascade: application → QUEUED, unit → AVAILABLE
        application = db.applications.get(allocation["application_id"])
        if application and application.get("status") == "ALLOCATED":
            application["status"] = "QUEUED"
            stamp_update(application)
        unit = db.housing_units.get(allocation["housing_unit_id"])
        if unit and unit.get("status") == "RESERVED":
            unit["status"] = "AVAILABLE"
            stamp_update(unit)

        emit_audit_allocation_decision(
            program_id=program_id,
            subject_type="ALLOCATION",
            subject_id=allocation["id"],
            actor_user_id=user_id,
            before={"status": before_alloc},
            after={"status": "REVERTED"},
            note="objection sustained",
            current_period_index=int(program["current_period_index"]),
        )
    return success(objection)


# ----------------------------------------------------------------------------
# POST /allocations/{allocId}/objections/{objId}/dismiss
# ----------------------------------------------------------------------------
@bp.post("/housing-programs/<program_id>/allocations/<alloc_id>/objections/<obj_id>/dismiss")
def dismiss_objection(program_id, alloc_id, obj_id):
    require_roles("HousingOfficer")
    get_program_or_404(program_id)
    allocation = get_allocation_or_404(program_id, alloc_id)
    objection = get_objection_or_404(alloc_id, obj_id)
    body = get_json_body()
    check_version(objection, body)
    notes = body.get("review_notes")

    with db.lock:
        if objection.get("status") != "PENDING_REVIEW":
            raise api_error("ERR_OBJECTION_NOT_PENDING",
                            "Objection must be PENDING_REVIEW")

        objection["status"] = "DISMISSED"
        objection["review_decision"] = "DISMISSED"
        if notes is not None:
            objection["review_notes"] = notes
        stamp_update(objection)

        # If this was the last open objection AND no SUSTAINED objections exist,
        # cascade allocation back to PUBLISHED.
        any_pending = False
        any_sustained = False
        for o in db.objections.values():
            if o.get("allocation_id") != alloc_id:
                continue
            if o is objection:
                continue
            if o.get("status") == "PENDING_REVIEW":
                any_pending = True
            elif o.get("status") == "SUSTAINED":
                any_sustained = True
        if (allocation.get("status") == "UNDER_OBJECTION"
                and not any_pending and not any_sustained):
            allocation["status"] = "PUBLISHED"
            stamp_update(allocation)
    return success(objection)
