from flask import Blueprint, request
from db import (
    adoption_applications,
    animals,
    adopters,
    shelters,
    home_visits,
    fee_invoices,
    gen_id,
    now_iso,
)
from errors import (
    raise_error,
    ERR_INVALID_REQUEST,
    ERR_SHELTER_NOT_FOUND,
    ERR_ANIMAL_NOT_FOUND,
    ERR_ADOPTER_NOT_FOUND,
    ERR_APPLICATION_NOT_FOUND,
    ERR_INVALID_STATE,
    ERR_ANIMAL_NOT_AVAILABLE,
    ERR_ADOPTER_BLACKLISTED,
    ERR_SHELTER_SUSPENDED,
    ERR_REVIEWER_MISMATCH,
    ERR_HOME_VISIT_REQUIRED,
    ERR_SELF_APPROVAL,
    ERR_STALE_ANIMAL_DATA,
    ERR_STALE_ADOPTER_DATA,
    ERR_COMPLIANCE_HOLD_ACTIVE,
    ERR_FEE_NOT_PAID,
)
from middleware import require_roles, parse_pagination, get_auth
from response import success_response, list_response
from services.animal_service import (
    serialize_application,
    compute_requires_home_visit,
    has_active_high_critical_hold,
)
from services.fee_service import compute_adoption_fee, serialize_invoice

applications_bp = Blueprint("applications", __name__)


@applications_bp.route("/petcare/adoption-applications", methods=["POST"])
def create_application():
    require_roles("CaseWorker")
    body = request.get_json(silent=True) or {}

    animal_id = body.get("animal_id")
    adopter_id = body.get("adopter_id")
    reason = body.get("reason")

    if not animal_id:
        raise_error(ERR_INVALID_REQUEST, "animal_id is required")
    if not adopter_id:
        raise_error(ERR_INVALID_REQUEST, "adopter_id is required")
    if reason is None or not isinstance(reason, str):
        raise_error(ERR_INVALID_REQUEST, "reason is required")

    animal = animals.get(animal_id)
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    adopter = adopters.get(adopter_id)
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")

    shelter = shelters.get(animal["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    aid = gen_id()
    ts = now_iso()
    app = {
        "id": aid,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": animal["shelter_id"],
        "animal_id": animal_id,
        "adopter_id": adopter_id,
        "reason": reason,
        "home_visit_id": None,
        "animal_version_pinned": None,
        "adopter_version_pinned": None,
        "reviewer_id": None,
        "approver_id": None,
        "rejection_reason": None,
        "fee_invoice_id": None,
        "status": "SUBMITTED",
    }
    adoption_applications[aid] = app
    return success_response(serialize_application(app), status_code=201)


@applications_bp.route("/petcare/adoption-applications", methods=["GET"])
def list_applications():
    require_roles("ShelterManager", "CaseWorker")
    limit, offset = parse_pagination()
    shelter_id = request.args.get("shelter_id")
    adopter_id = request.args.get("adopter_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    items = []
    for a in adoption_applications.values():
        if shelter_id and a["shelter_id"] != shelter_id:
            continue
        if adopter_id and a["adopter_id"] != adopter_id:
            continue
        if animal_id and a["animal_id"] != animal_id:
            continue
        if status and a["status"] != status:
            continue
        items.append(a)
    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return list_response([serialize_application(x) for x in page], total, limit, offset)


@applications_bp.route("/petcare/adoption-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    require_roles("ShelterManager", "CaseWorker")
    a = adoption_applications.get(app_id)
    if not a:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    return success_response(serialize_application(a))


@applications_bp.route("/petcare/adoption-applications/<app_id>/start-review", methods=["POST"])
def start_review(app_id):
    user_id, _ = require_roles("CaseWorker")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Application must be SUBMITTED")
    animal = animals.get(app["animal_id"])
    adopter = adopters.get(app["adopter_id"])
    shelter = shelters.get(app["shelter_id"])
    if shelter and shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")
    if not animal or animal["status"] != "AVAILABLE":
        raise_error(ERR_ANIMAL_NOT_AVAILABLE, "Animal is not available")
    if not adopter or adopter["status"] != "ACTIVE":
        raise_error(ERR_ADOPTER_BLACKLISTED, "Adopter is blacklisted")
    app["status"] = "UNDER_REVIEW"
    app["reviewer_id"] = user_id
    app["animal_version_pinned"] = animal["version"]
    app["adopter_version_pinned"] = adopter["version"]
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/require-home-visit", methods=["POST"])
def require_home_visit(app_id):
    user_id, _ = require_roles("CaseWorker")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW")
    if app.get("reviewer_id") != user_id:
        raise_error(ERR_REVIEWER_MISMATCH, "Only the assigned reviewer may call this")
    app["status"] = "HOME_VISIT_REQUIRED"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/complete-review", methods=["POST"])
def complete_review(app_id):
    user_id, _ = require_roles("CaseWorker")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW")
    if app.get("reviewer_id") != user_id:
        raise_error(ERR_REVIEWER_MISMATCH, "Only the assigned reviewer may call this")
    animal = animals.get(app["animal_id"])
    if animal and compute_requires_home_visit(animal):
        raise_error(ERR_HOME_VISIT_REQUIRED,
                    "Application requires home visit before complete-review")
    app["status"] = "REVIEWED"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/approve", methods=["POST"])
def approve_application(app_id):
    user_id, _ = require_roles("ShelterManager")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    # Resolve referenced entities first (existence checks, priority 4-5).
    shelter = shelters.get(app["shelter_id"])
    if not shelter:
        raise_error(ERR_SHELTER_NOT_FOUND, "Shelter not found")
    animal = animals.get(app["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")
    adopter = adopters.get(app["adopter_id"])
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")
    # Priority 6: shelter must be OPEN.
    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")
    # Priority 7: state must be REVIEWED.
    if app["status"] != "REVIEWED":
        raise_error(ERR_INVALID_STATE, "Application must be REVIEWED")
    # Priority 9: no ACTIVE HIGH/CRITICAL ComplianceHold on animal.
    if has_active_high_critical_hold(animal["id"]):
        raise_error(ERR_COMPLIANCE_HOLD_ACTIVE, "Animal has active HIGH/CRITICAL hold")
    # Priority 11: animal must still be AVAILABLE.
    if animal["status"] != "AVAILABLE":
        raise_error(ERR_ANIMAL_NOT_AVAILABLE, "Animal is no longer available")
    # Priority 13: approver must differ from reviewer.
    if app.get("reviewer_id") == user_id:
        raise_error(ERR_SELF_APPROVAL, "Approver must differ from reviewer")
    # Priority 14: pinned animal version must match.
    if animal["version"] != app.get("animal_version_pinned"):
        raise_error(ERR_STALE_ANIMAL_DATA, "Animal data has changed since review started")
    # Priority 15: pinned adopter version must match.
    if adopter["version"] != app.get("adopter_version_pinned"):
        raise_error(ERR_STALE_ADOPTER_DATA, "Adopter data has changed since review started")

    app["status"] = "APPROVED"
    app["approver_id"] = user_id
    app["updated_at"] = now_iso()
    app["version"] += 1

    animal["status"] = "ADOPTION_PENDING"
    animal["updated_at"] = now_iso()
    animal["version"] += 1

    # Create the fee invoice
    fee = compute_adoption_fee(animal, adopter, shelter)
    inv_id = gen_id()
    ts = now_iso()
    invoice = {
        "id": inv_id,
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": shelter["id"],
        "reference_type": "ADOPTION",
        "reference_id": app["id"],
        "line_items": fee["line_items"],
        "subtotal_cents": fee["subtotal_cents"],
        "discount_cents": fee["discount_cents"],
        "tax_cents": fee["tax_cents"],
        "total_amount_cents": fee["total_amount_cents"],
        "paid_amount_cents": 0,
        "refund_amount_cents": 0,
        "settlement_batch_id": None,
        "status": "ISSUED",
        "paid_at": None,
        "refunded_at": None,
    }
    fee_invoices[inv_id] = invoice
    app["fee_invoice_id"] = inv_id

    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/reject", methods=["POST"])
def reject_application(app_id):
    user_id, _ = require_roles("ShelterManager")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "REVIEWED":
        raise_error(ERR_INVALID_STATE, "Application must be REVIEWED")
    if app.get("reviewer_id") == user_id:
        raise_error(ERR_SELF_APPROVAL, "Rejector must differ from reviewer")
    body = request.get_json(silent=True) or {}
    rejection_reason = body.get("rejection_reason")
    if not rejection_reason or not isinstance(rejection_reason, str):
        raise_error(ERR_INVALID_REQUEST, "rejection_reason is required")
    app["status"] = "REJECTED"
    app["rejection_reason"] = rejection_reason
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/complete", methods=["POST"])
def complete_application(app_id):
    require_roles("CaseWorker")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Application must be APPROVED")
    invoice_id = app.get("fee_invoice_id")
    if not invoice_id:
        raise_error(ERR_FEE_NOT_PAID, "Fee invoice missing")
    invoice = fee_invoices.get(invoice_id)
    if not invoice or invoice["status"] != "PAID":
        raise_error(ERR_FEE_NOT_PAID, "Fee invoice is not PAID")

    app["status"] = "COMPLETED"
    app["updated_at"] = now_iso()
    app["version"] += 1

    animal = animals.get(app["animal_id"])
    if animal and animal["status"] == "ADOPTION_PENDING":
        animal["status"] = "ADOPTED"
        animal["updated_at"] = now_iso()
        animal["version"] += 1

    return success_response(serialize_application(app))


@applications_bp.route("/petcare/adoption-applications/<app_id>/withdraw", methods=["POST"])
def withdraw_application(app_id):
    require_roles("CaseWorker")
    app = adoption_applications.get(app_id)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] in ("APPROVED", "COMPLETED", "REJECTED", "WITHDRAWN"):
        raise_error(ERR_INVALID_STATE, "Application cannot be withdrawn in current state")

    animal = animals.get(app["animal_id"])
    if animal and animal["status"] == "ADOPTION_PENDING":
        animal["status"] = "AVAILABLE"
        animal["updated_at"] = now_iso()
        animal["version"] += 1

    hv_id = app.get("home_visit_id")
    if hv_id:
        hv = home_visits.get(hv_id)
        if hv and hv["status"] == "SCHEDULED":
            hv["status"] = "CANCELLED"
            hv["updated_at"] = now_iso()
            hv["version"] += 1

    app["status"] = "WITHDRAWN"
    app["home_visit_id"] = None
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_response(serialize_application(app))
