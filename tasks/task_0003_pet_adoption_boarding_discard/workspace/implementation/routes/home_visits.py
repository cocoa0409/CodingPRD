"""Home visit endpoints."""

from flask import Blueprint, request
import db
from db import new_id, now_iso
from middleware import require_role, get_pagination
from response import success_object, success_list
from errors import (raise_error, ERR_HOME_VISIT_NOT_FOUND, ERR_ADOPTER_NOT_FOUND,
                    ERR_APPLICATION_NOT_FOUND, ERR_INVALID_STATE,
                    ERR_ASSESSOR_MISMATCH, ERR_INVALID_REQUEST)
from services.compliance import recompute_animal_eligibility

bp = Blueprint("home_visits", __name__)


def serialize_hv(h):
    return {k: v for k, v in h.items()}


@bp.route("/home-visits", methods=["POST"])
def create_home_visit():
    user_id, role = require_role("CaseWorker")
    body = request.get_json(force=True, silent=True) or {}

    required = ["adopter_id", "application_id", "scheduled_date"]
    for field in required:
        if field not in body or body[field] is None:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    adopter = db.adopters.get(body["adopter_id"])
    if not adopter:
        raise_error(ERR_ADOPTER_NOT_FOUND, "Adopter not found")

    app = db.adoption_applications.get(body["application_id"])
    if not app:
        raise_error(ERR_APPLICATION_NOT_FOUND, "Application not found")
    if app["status"] != "HOME_VISIT_REQUIRED":
        raise_error(ERR_INVALID_STATE, "Application must be in HOME_VISIT_REQUIRED status")

    ts = now_iso()
    hv = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "adopter_id": body["adopter_id"],
        "application_id": body["application_id"],
        "case_worker_id": user_id,
        "scheduled_date": body["scheduled_date"],
        "yard_adequate": None,
        "space_adequate": None,
        "safety_hazards_found": None,
        "existing_pets_compatible": None,
        "overall_score": None,
        "result": None,
        "notes": None,
        "status": "SCHEDULED",
    }
    db.home_visits[hv["id"]] = hv

    # Transition application to HOME_VISIT_SCHEDULED
    app["status"] = "HOME_VISIT_SCHEDULED"
    app["home_visit_id"] = hv["id"]
    app["updated_at"] = now_iso()
    app["version"] += 1

    return success_object(serialize_hv(hv), 201)


@bp.route("/home-visits", methods=["GET"])
def list_home_visits():
    require_role("ShelterManager", "CaseWorker")
    limit, offset = get_pagination()

    items = list(db.home_visits.values())
    adopter_id = request.args.get("adopter_id")
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    if adopter_id:
        items = [h for h in items if h["adopter_id"] == adopter_id]
    if application_id:
        items = [h for h in items if h["application_id"] == application_id]
    if status:
        items = [h for h in items if h["status"] == status]

    items.sort(key=lambda x: x["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_hv(h) for h in page], total, limit, offset)


@bp.route("/home-visits/<homeVisitId>", methods=["GET"])
def get_home_visit(homeVisitId):
    require_role("ShelterManager", "CaseWorker")
    hv = db.home_visits.get(homeVisitId)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    return success_object(serialize_hv(hv))


@bp.route("/home-visits/<homeVisitId>/complete", methods=["POST"])
def complete_home_visit(homeVisitId):
    user_id, role = require_role("CaseWorker")
    hv = db.home_visits.get(homeVisitId)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    if hv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Home visit must be SCHEDULED")
    if hv["case_worker_id"] != user_id:
        raise_error(ERR_ASSESSOR_MISMATCH, "Only the assigned case worker can complete this visit")

    body = request.get_json(force=True, silent=True) or {}
    required_fields = ["yard_adequate", "space_adequate", "safety_hazards_found", "existing_pets_compatible", "notes"]
    for field in required_fields:
        if field not in body:
            raise_error(ERR_INVALID_REQUEST, f"Missing required field: {field}")

    hv["yard_adequate"] = body["yard_adequate"]
    hv["space_adequate"] = body["space_adequate"]
    hv["safety_hazards_found"] = body["safety_hazards_found"]
    hv["existing_pets_compatible"] = body["existing_pets_compatible"]
    hv["notes"] = body["notes"]

    # Compute score
    # Get the animal species from the application
    app = db.adoption_applications.get(hv["application_id"])
    animal = db.animals.get(app["animal_id"]) if app else None
    species = animal["species"] if animal else "OTHER"

    if species in ("CAT", "BIRD", "RABBIT"):
        # No yard variant: yard weight = 0, space weight = 45
        yard_score = 0
        space_score = 45 if body["space_adequate"] else 0
    else:
        yard_score = 25 if body["yard_adequate"] else 0
        space_score = 30 if body["space_adequate"] else 0

    hazard_score = 0 if body["safety_hazards_found"] else 25
    pets_score = 20 if body["existing_pets_compatible"] else 0

    overall_score = yard_score + space_score + hazard_score + pets_score
    hv["overall_score"] = overall_score

    if overall_score >= 70:
        hv["result"] = "PASS"
    elif overall_score >= 50:
        hv["result"] = "CONDITIONAL_PASS"
    else:
        hv["result"] = "FAIL"

    hv["status"] = "COMPLETED"
    hv["updated_at"] = now_iso()
    hv["version"] += 1

    # Update adopter
    adopter = db.adopters.get(hv["adopter_id"])
    if adopter:
        if hv["result"] in ("PASS", "CONDITIONAL_PASS"):
            adopter["home_visit_passed"] = True
        else:
            adopter["home_visit_passed"] = False
        adopter["updated_at"] = now_iso()
        adopter["version"] += 1

    # Update application based on result
    if app:
        if hv["result"] in ("PASS", "CONDITIONAL_PASS"):
            app["status"] = "REVIEWED"
            # Re-pin adopter_version since home visit updated the adopter
            if adopter:
                app["adopter_version"] = adopter["version"]
            app["updated_at"] = now_iso()
            app["version"] += 1
        else:
            # FAIL -> reject application
            app["status"] = "REJECTED"
            app["rejection_reason"] = "Home visit failed"
            app["updated_at"] = now_iso()
            app["version"] += 1
            # Revert animal if ADOPTION_PENDING
            if animal and animal["status"] == "ADOPTION_PENDING":
                animal["status"] = "AVAILABLE"
                animal["updated_at"] = now_iso()
                animal["version"] += 1
                recompute_animal_eligibility(animal["id"])

    return success_object(serialize_hv(hv))


@bp.route("/home-visits/<homeVisitId>/cancel", methods=["POST"])
def cancel_home_visit(homeVisitId):
    user_id, role = require_role("CaseWorker")
    hv = db.home_visits.get(homeVisitId)
    if not hv:
        raise_error(ERR_HOME_VISIT_NOT_FOUND, "Home visit not found")
    if hv["status"] != "SCHEDULED":
        raise_error(ERR_INVALID_STATE, "Home visit must be SCHEDULED")

    hv["status"] = "CANCELLED"
    hv["updated_at"] = now_iso()
    hv["version"] += 1

    # Revert application to HOME_VISIT_REQUIRED
    app = db.adoption_applications.get(hv["application_id"])
    if app and app["status"] == "HOME_VISIT_SCHEDULED":
        app["status"] = "HOME_VISIT_REQUIRED"
        app["updated_at"] = now_iso()
        app["version"] += 1

    return success_object(serialize_hv(hv))
