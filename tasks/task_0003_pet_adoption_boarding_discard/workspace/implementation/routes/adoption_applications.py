"""Adoption application endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_APPLICATION_NOT_FOUND, ERR_ANIMAL_NOT_FOUND,
                    ERR_ADOPTER_NOT_FOUND, ERR_SHELTER_SUSPENDED,
                    ERR_ANIMAL_NOT_AVAILABLE, ERR_ADOPTER_BLACKLISTED,
                    ERR_INVALID_STATE, ERR_REVIEWER_MISMATCH,
                    ERR_HOME_VISIT_REQUIRED, ERR_SELF_APPROVAL,
                    ERR_STALE_ANIMAL_DATA, ERR_STALE_ADOPTER_DATA,
                    ERR_FEE_NOT_PAID, ERR_INVALID_REQUEST)
from services.compliance import recompute_animal_eligibility, recompute_shelter_compliance_score
from services.fees import compute_adoption_fee, create_invoice

bp = Blueprint("adoption_applications", __name__)


def serialize_app(a):
    return {k: v for k, v in a.items()}


@bp.route("/adoption-applications", methods=["POST"])
def create_application():
    user_id, role = require_role("CaseWorker")
    body = request.get_json(force=True, silent=True) or {}

    required = ["animal_id", "adopter_id", "reason"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    animal = db.animals.get(body["animal_id"])
    if not animal:
        raise_error(ERR_ANIMAL_NOT_FOUND, "Animal not found")

    adopter = db.adopters.get(body["adopter_id"])
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")

    shelter = db.shelters.get(animal["shelter_id"])
    if not shelter:
        raise_error(ERR_INVALID_REQUEST, "Associated shelter not found")

    if shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    if animal["status"] != "AVAILABLE":
        raise_error(ERR_ANIMAL_NOT_AVAILABLE, "Animal is not available")

    if adopter["status"] != "ACTIVE":
        raise_error(ERR_ADOPTER_BLACKLISTED, "Adopter is blacklisted")

    ts = now_iso()
    app = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "shelter_id": animal["shelter_id"],
        "animal_id": body["animal_id"],
        "adopter_id": body["adopter_id"],
        "reason": body["reason"],
        "home_visit_id": None,
        "animal_version": None,
        "adopter_version": None,
        "reviewer_id": None,
        "approver_id": None,
        "rejection_reason": None,
        "fee_invoice_id": None,
        "status": "SUBMITTED",
    }
    db.adoption_applications[app["id"]] = app
    return success_object(serialize_app(app), 201)


@bp.route("/adoption-applications", methods=["GET"])
def list_applications():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.adoption_applications.values())
    shelter_id = request.args.get("shelter_id")
    adopter_id = request.args.get("adopter_id")
    animal_id = request.args.get("animal_id")
    status = request.args.get("status")
    if shelter_id:
        items = [a for a in items if a["shelter_id"] == shelter_id]
    if adopter_id:
        items = [a for a in items if a["adopter_id"] == adopter_id]
    if animal_id:
        items = [a for a in items if a["animal_id"] == animal_id]
    if status:
        items = [a for a in items if a["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_app(a) for a in page], total, limit, offset)


@bp.route("/adoption-applications/<applicationId>", methods=["GET"])
def get_application(applicationId):
    require_role("ShelterManager", "CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/start-review", methods=["POST"])
def start_review(applicationId):
    user_id, role = require_role("CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "SUBMITTED":
        raise_error(ERR_INVALID_STATE, "Application must be SUBMITTED")

    animal = db.animals.get(app["animal_id"])
    if not animal or animal["status"] != "AVAILABLE":
        raise_error(ERR_ANIMAL_NOT_AVAILABLE, "Animal is not available")

    adopter = db.adopters.get(app["adopter_id"])
    if not adopter or adopter["status"] != "ACTIVE":
        raise_error(ERR_ADOPTER_BLACKLISTED, "Adopter is blacklisted")

    app["status"] = "UNDER_REVIEW"
    app["reviewer_id"] = user_id
    app["animal_version"] = animal["version"]
    app["adopter_version"] = adopter["version"]
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/require-home-visit", methods=["POST"])
def require_home_visit(applicationId):
    user_id, role = require_role("CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW")
    if app["reviewer_id"] != user_id:
        raise_error(ERR_REVIEWER_MISMATCH, "Only the assigned reviewer can perform this operation")

    app["status"] = "HOME_VISIT_REQUIRED"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/complete-review", methods=["POST"])
def complete_review(applicationId):
    user_id, role = require_role("CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "UNDER_REVIEW":
        raise_error(ERR_INVALID_STATE, "Application must be UNDER_REVIEW")
    if app["reviewer_id"] != user_id:
        raise_error(ERR_REVIEWER_MISMATCH, "Only the assigned reviewer can perform this operation")

    # Check home visit requirement for DOGs
    animal = db.animals.get(app["animal_id"])
    if animal and animal["species"] == "DOG":
        adopter = db.adopters.get(app["adopter_id"])
        if not adopter or not adopter.get("home_visit_passed", False):
            raise_error(ERR_HOME_VISIT_REQUIRED, "Home visit required for DOG adoptions")

    app["status"] = "REVIEWED"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/approve", methods=["POST"])
def approve_application(applicationId):
    user_id, role = require_role("ShelterManager")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "REVIEWED":
        raise_error(ERR_INVALID_STATE, "Application must be REVIEWED")

    # Shelter must be OPEN
    shelter = db.shelters.get(app["shelter_id"])
    if shelter and shelter["status"] != "OPEN":
        raise_error(ERR_SHELTER_SUSPENDED, "Shelter is suspended")

    # Animal must be AVAILABLE
    animal = db.animals.get(app["animal_id"])
    if not animal or animal["status"] != "AVAILABLE":
        raise_error(ERR_ANIMAL_NOT_AVAILABLE, "Animal is not available")

    # Segregation of duties
    if app["reviewer_id"] == user_id:
        raise_error(ERR_SELF_APPROVAL, "Approver cannot be the same as reviewer")

    # Version pinning checks
    if app["animal_version"] is not None and app["animal_version"] != animal["version"]:
        raise_error(ERR_STALE_ANIMAL_DATA, "Animal record has been modified since review")

    adopter = db.adopters.get(app["adopter_id"])
    if app["adopter_version"] is not None and adopter and app["adopter_version"] != adopter["version"]:
        raise_error(ERR_STALE_ADOPTER_DATA, "Adopter record has been modified since review")

    # Create fee invoice
    line_items, subtotal, tax_amount, discount_amount, total_amount = compute_adoption_fee(
        app["shelter_id"], animal, adopter
    )
    invoice = create_invoice(
        app["shelter_id"], "ADOPTION", app["id"],
        line_items, subtotal, tax_amount, discount_amount, total_amount
    )

    app["approver_id"] = user_id
    app["fee_invoice_id"] = invoice["id"]
    app["status"] = "APPROVED"
    app["updated_at"] = now_iso()
    app["version"] += 1

    # Animal -> ADOPTION_PENDING
    animal["status"] = "ADOPTION_PENDING"
    animal["adoption_eligible"] = False
    animal["updated_at"] = now_iso()
    animal["version"] += 1

    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/reject", methods=["POST"])
def reject_application(applicationId):
    user_id, role = require_role("ShelterManager")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "REVIEWED":
        raise_error(ERR_INVALID_STATE, "Application must be REVIEWED")

    body = request.get_json(force=True, silent=True) or {}
    app["rejection_reason"] = body.get("rejection_reason", "Rejected")
    app["status"] = "REJECTED"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/complete", methods=["POST"])
def complete_application(applicationId):
    user_id, role = require_role("CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Application must be APPROVED")

    # Check fee invoice is paid
    if app.get("fee_invoice_id"):
        invoice = db.fee_invoices.get(app["fee_invoice_id"])
        if not invoice or invoice["status"] != "PAID":
            raise_error(ERR_FEE_NOT_PAID, "Fee invoice must be fully paid before completing adoption")

    app["status"] = "COMPLETED"
    app["updated_at"] = now_iso()
    app["version"] += 1

    # Animal -> ADOPTED
    animal = db.animals.get(app["animal_id"])
    if animal:
        animal["status"] = "ADOPTED"
        animal["adoption_eligible"] = False
        animal["updated_at"] = now_iso()
        animal["version"] += 1

    # Increment shelter adoption_count
    shelter = db.shelters.get(app["shelter_id"])
    if shelter:
        shelter["adoption_count"] = shelter.get("adoption_count", 0) + 1
        shelter["updated_at"] = now_iso()
        shelter["version"] += 1

    # Increment adopter adoption_history_count
    adopter = db.adopters.get(app["adopter_id"])
    if adopter:
        adopter["adoption_history_count"] = adopter.get("adoption_history_count", 0) + 1
        adopter["updated_at"] = now_iso()
        adopter["version"] += 1

    # Recompute shelter compliance score (animal status changed to ADOPTED)
    recompute_shelter_compliance_score(app["shelter_id"])

    return success_object(serialize_app(app))


@bp.route("/adoption-applications/<applicationId>/withdraw", methods=["POST"])
def withdraw_application(applicationId):
    user_id, role = require_role("CaseWorker")
    app = db.adoption_applications.get(applicationId)
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")

    allowed_states = ["SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED", "HOME_VISIT_SCHEDULED", "REVIEWED"]
    if app["status"] not in allowed_states:
        raise_error(ERR_INVALID_STATE, "Application cannot be withdrawn in current state")

    # If animal was ADOPTION_PENDING, revert to AVAILABLE
    animal = db.animals.get(app["animal_id"])
    if animal and animal["status"] == "ADOPTION_PENDING":
        animal["status"] = "AVAILABLE"
        animal["updated_at"] = now_iso()
        animal["version"] += 1
        recompute_animal_eligibility(animal["id"])

    # If home visit was SCHEDULED, cancel it
    if app.get("home_visit_id"):
        hv = db.home_visits.get(app["home_visit_id"])
        if hv and hv["status"] == "SCHEDULED":
            hv["status"] = "CANCELLED"
            hv["updated_at"] = now_iso()
            hv["version"] += 1

    app["status"] = "WITHDRAWN"
    app["updated_at"] = now_iso()
    app["version"] += 1
    return success_object(serialize_app(app))
