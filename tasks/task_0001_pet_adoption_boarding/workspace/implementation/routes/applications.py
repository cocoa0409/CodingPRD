"""Adoption application routes."""

from flask import Blueprint, request, g

from db import store, new_id, now_dt, lock
from middleware import auth_required
from response import success_object, success_array
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INSUFFICIENT_PERMISSIONS,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_HOME_VISIT_REQUIRED,
    ERR_VACCINATION_NON_COMPLIANT,
    ERR_ANIMAL_UNAVAILABLE,
    ERR_ANIMAL_ALREADY_RESERVED,
    ERR_ADOPTER_DISQUALIFIED,
    ERR_FEE_NOT_SETTLED,
    ERR_STALE_PINNED_REFERENCE,
    ERR_ANIMAL_ADOPTED,
)
from services.validation import (
    get_json_body, require_field, pagination,
    get_adopter_or_404, get_animal_or_404, get_application_or_404,
)
from services.serializers import serialize_application
from services.compliance import compute_compliance, snapshot_compliance, write_incident
from services.home_visit import compute_adopter_home_visit_status
from services.pricing import compute_adoption_fee

bp = Blueprint("applications", __name__)


@bp.route("/adoption-applications", methods=["POST"])
@auth_required(allowed_roles={"Adopter"})
def create_application():
    body = get_json_body(required=True)
    adopter_id = require_field(body, "adopter_id", types=str)
    animal_id = require_field(body, "animal_id", types=str)
    review_notes = body.get("review_notes", "")
    if not isinstance(review_notes, str):
        raise_err(ERR_INVALID_REQUEST, "review_notes must be a string")
    adopter = get_adopter_or_404(adopter_id)
    animal = get_animal_or_404(animal_id)
    # Business checks — animal already reserved / unavailable / adopter disqualified
    # Priority: animal availability first, then disqualified.
    # Existence of ANOTHER APPROVED/FINALIZED app -> ERR_ANIMAL_ALREADY_RESERVED
    for other in store.applications.values():
        if other["animal_id"] == animal_id and other["status"] in ("APPROVED", "FINALIZED"):
            raise_err(ERR_ANIMAL_ALREADY_RESERVED, "Animal already reserved")
    if animal["status"] not in ("AVAILABLE", "HELD"):
        raise_err(ERR_ANIMAL_UNAVAILABLE, f"Animal status is {animal['status']}")
    if adopter.get("disqualified"):
        raise_err(ERR_ADOPTER_DISQUALIFIED, "Adopter disqualified")
    with lock:
        aid = new_id()
        now = now_dt()
        rec = {
            "id": aid,
            "adopter_id": adopter_id,
            "animal_id": animal_id,
            "shelter_id": animal["shelter_id"],
            "pinned_animal_version": None,
            "pinned_vaccination_snapshot": None,
            "pinned_fee": None,
            "review_notes": review_notes,
            "reviewer_user_id": None,
            "submitter_user_id": g.user_id,
            "status": "SUBMITTED",
            "created_at": now,
            "updated_at": now,
            "version": 1,
        }
        store.applications[aid] = rec
    return success_object(serialize_application(rec), status_code=201)


@bp.route("/adoption-applications", methods=["GET"])
@auth_required(allowed_roles={"AdoptionReviewer", "AdoptionApprover", "ShelterAdmin"})
def list_applications():
    limit, offset = pagination()
    status_f = request.args.get("status")
    adopter_f = request.args.get("adopter_id")
    animal_f = request.args.get("animal_id")
    apps = list(store.applications.values())
    if status_f:
        apps = [a for a in apps if a["status"] == status_f]
    if adopter_f:
        apps = [a for a in apps if a["adopter_id"] == adopter_f]
    if animal_f:
        apps = [a for a in apps if a["animal_id"] == animal_f]
    apps.sort(key=lambda r: r["created_at"])
    total = len(apps)
    page = apps[offset: offset + limit]
    return success_array([serialize_application(a) for a in page], limit, offset, total)


@bp.route("/adoption-applications/<aid>", methods=["GET"])
@auth_required(allowed_roles={"AdoptionReviewer", "AdoptionApprover", "Adopter", "ShelterAdmin"})
def get_application(aid):
    rec = get_application_or_404(aid)
    return success_object(serialize_application(rec))


@bp.route("/adoption-applications/<aid>/begin-review", methods=["POST"])
@auth_required(allowed_roles={"AdoptionReviewer"})
def begin_review(aid):
    app = get_application_or_404(aid)
    if app["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, f"Application in {app['status']}")
    adopter = store.adopters.get(app["adopter_id"])
    if adopter and adopter.get("disqualified"):
        raise_err(ERR_ADOPTER_DISQUALIFIED, "Adopter disqualified")
    with lock:
        app["status"] = "UNDER_REVIEW"
        app["reviewer_user_id"] = g.user_id
        app["updated_at"] = now_dt()
        app["version"] += 1
    return success_object(serialize_application(app))


@bp.route("/adoption-applications/<aid>/request-home-visit", methods=["POST"])
@auth_required(allowed_roles={"AdoptionReviewer"})
def request_home_visit(aid):
    app = get_application_or_404(aid)
    if app["status"] != "UNDER_REVIEW":
        raise_err(ERR_INVALID_STATE, f"Application in {app['status']}")
    with lock:
        app["status"] = "HOME_VISIT_REQUIRED"
        app["updated_at"] = now_dt()
        app["version"] += 1
    return success_object(serialize_application(app))


@bp.route("/adoption-applications/<aid>/approve", methods=["POST"])
@auth_required(allowed_roles={"AdoptionApprover"})
def approve(aid):
    app = get_application_or_404(aid)
    # Race-aware short-circuit (PRD §2.8): if another application already holds
    # this animal as APPROVED or FINALIZED, this approve loses the race and
    # must surface ERR_ANIMAL_ALREADY_RESERVED, regardless of whether this
    # application has since been cascaded to REJECTED.
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["animal_id"] == app["animal_id"] and other["status"] in ("APPROVED", "FINALIZED"):
            raise_err(ERR_ANIMAL_ALREADY_RESERVED, "Another application already holds this animal")
    if app["status"] not in ("UNDER_REVIEW", "HOME_VISIT_REQUIRED"):
        raise_err(ERR_INVALID_STATE, f"Cannot approve from {app['status']}")
    # 7a Segregation of duties
    if app.get("reviewer_user_id") and app["reviewer_user_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Approver must not be the reviewer")
    # 7b Home visit requirement
    hv_status, _ = compute_adopter_home_visit_status(app["adopter_id"])
    if hv_status != "PASSED":
        raise_err(ERR_HOME_VISIT_REQUIRED, f"Home visit not passed: {hv_status}")
    # 7c Vaccination compliance
    comp = compute_compliance(app["animal_id"])
    if comp["status"] != "COMPLIANT":
        write_incident(app["animal_id"], "ADOPTION_BLOCKED",
                       "POST /adoption-applications/{id}/approve",
                       f"missing={comp['missing']} expired={comp['expired']}")
        raise_err(ERR_VACCINATION_NON_COMPLIANT, "Vaccination non-compliant")
    # 8a Animal availability / already reserved
    animal = store.animals.get(app["animal_id"])
    if animal is None:
        raise_err(ERR_ANIMAL_UNAVAILABLE, "Animal missing")
    # Another APPROVED/FINALIZED app for same animal?
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["animal_id"] == app["animal_id"] and other["status"] in ("APPROVED", "FINALIZED"):
            raise_err(ERR_ANIMAL_ALREADY_RESERVED, "Another application already holds this animal")
    if animal["status"] not in ("AVAILABLE", "HELD"):
        raise_err(ERR_ANIMAL_UNAVAILABLE, f"Animal status is {animal['status']}")
    # 8c Adopter disqualified
    adopter = store.adopters.get(app["adopter_id"])
    if adopter and adopter.get("disqualified"):
        raise_err(ERR_ADOPTER_DISQUALIFIED, "Adopter disqualified")
    # Perform approval
    with lock:
        shelter = store.shelters.get(animal["shelter_id"])
        fee = compute_adoption_fee(animal, shelter)
        now = now_dt()
        # Pin
        app["pinned_animal_version"] = animal["version"]
        app["pinned_vaccination_snapshot"] = snapshot_compliance(app["animal_id"])
        app["pinned_fee"] = fee
        app["status"] = "APPROVED"
        app["updated_at"] = now
        app["version"] += 1
        # Animal -> HELD
        if animal["status"] != "HELD":
            animal["status"] = "HELD"
            animal["updated_at"] = now
            animal["version"] += 1
            # Pin captured version BEFORE this bump, since PRD says pin = current version
            # but we pinned before transition. Re-sync to post-transition value? PRD §3.4:
            # "pins pinned_animal_version to the live Animal.version at that moment" — at approval moment.
            # Since our approval mutates animal.status => version++, the pin must match that latest value.
            app["pinned_animal_version"] = animal["version"]
        # Cascade-reject sibling applications
        for other in store.applications.values():
            if other["id"] == app["id"]:
                continue
            if other["animal_id"] == app["animal_id"] and other["status"] in ("SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED"):
                other["status"] = "REJECTED"
                other["rejection_reason"] = "ERR_ANIMAL_ALREADY_RESERVED"
                other["updated_at"] = now
                other["version"] += 1
    return success_object(serialize_application(app))


@bp.route("/adoption-applications/<aid>/reject", methods=["POST"])
@auth_required(allowed_roles={"AdoptionApprover"})
def reject(aid):
    app = get_application_or_404(aid)
    if app["status"] not in ("SUBMITTED", "UNDER_REVIEW", "HOME_VISIT_REQUIRED"):
        raise_err(ERR_INVALID_STATE, f"Cannot reject from {app['status']}")
    if app.get("reviewer_user_id") and app["reviewer_user_id"] == g.user_id:
        raise_err(ERR_SEGREGATION_OF_DUTIES, "Approver must not be the reviewer")
    body = get_json_body(required=False)
    with lock:
        if body and "review_notes" in body:
            if not isinstance(body["review_notes"], str):
                raise_err(ERR_INVALID_REQUEST, "review_notes must be string")
            app["review_notes"] = body["review_notes"]
        app["status"] = "REJECTED"
        app["updated_at"] = now_dt()
        app["version"] += 1
        _release_animal_if_sole_hold(app)
    return success_object(serialize_application(app))


def _release_animal_if_sole_hold(app):
    animal = store.animals.get(app["animal_id"])
    if animal is None or animal["status"] != "HELD":
        return
    for other in store.applications.values():
        if other["id"] == app["id"]:
            continue
        if other["animal_id"] == app["animal_id"] and other["status"] in ("APPROVED", "FINALIZED"):
            return
    animal["status"] = "AVAILABLE"
    animal["updated_at"] = now_dt()
    animal["version"] += 1


@bp.route("/adoption-applications/<aid>/finalize", methods=["POST"])
@auth_required(allowed_roles={"AdoptionApprover"})
def finalize(aid):
    app = get_application_or_404(aid)
    if app["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, f"Cannot finalize from {app['status']}")
    # Completed fee settlement exists?
    settled = False
    for s in store.settlements.values():
        if (s["subject_type"] == "ADOPTION" and s["subject_id"] == app["id"]
                and s["status"] == "COMPLETED"):
            settled = True
            break
    if not settled:
        raise_err(ERR_FEE_NOT_SETTLED, "Fee not settled")
    animal = store.animals.get(app["animal_id"])
    if animal is None or animal["version"] != app["pinned_animal_version"]:
        raise_err(ERR_STALE_PINNED_REFERENCE, "Animal version changed")
    comp = compute_compliance(app["animal_id"])
    if comp["status"] != "COMPLIANT":
        write_incident(app["animal_id"], "ADOPTION_BLOCKED",
                       "POST /adoption-applications/{id}/finalize",
                       f"missing={comp['missing']} expired={comp['expired']}")
        raise_err(ERR_VACCINATION_NON_COMPLIANT, "Vaccination non-compliant")
    with lock:
        now = now_dt()
        app["status"] = "FINALIZED"
        app["updated_at"] = now
        app["version"] += 1
        animal["status"] = "ADOPTED"
        animal["updated_at"] = now
        animal["version"] += 1
        # Cascade: RESERVED BoardingReservation for this animal -> CANCELLED
        for r in store.reservations.values():
            if r["animal_id"] == app["animal_id"] and r["status"] == "RESERVED":
                r["status"] = "CANCELLED"
                r["cancel_reason"] = "ERR_ANIMAL_ADOPTED"
                r["updated_at"] = now
                r["version"] += 1
                # Fail pending settlements for this reservation
                for s in store.settlements.values():
                    if (s["subject_type"] == "BOARDING" and s["subject_id"] == r["id"]
                            and s["status"] == "PENDING"):
                        s["status"] = "FAILED"
                        s["updated_at"] = now
                        s["version"] += 1
    return success_object(serialize_application(app))


@bp.route("/adoption-applications/<aid>/withdraw", methods=["POST"])
@auth_required(allowed_roles={"Adopter"})
def withdraw(aid):
    app = get_application_or_404(aid)
    # Adopter must be the applicant (the X-User-ID who originally submitted the
    # application, or if not recorded, the adopter_id of the application).
    applicant_id = app.get("submitter_user_id") or app["adopter_id"]
    if g.user_id != applicant_id:
        raise_err(ERR_INSUFFICIENT_PERMISSIONS, "Only the applicant may withdraw")
    if app["status"] == "FINALIZED":
        raise_err(ERR_INVALID_STATE, "Cannot withdraw FINALIZED")
    if app["status"] in ("REJECTED", "WITHDRAWN"):
        raise_err(ERR_INVALID_STATE, f"Already {app['status']}")
    with lock:
        now = now_dt()
        app["status"] = "WITHDRAWN"
        app["updated_at"] = now
        app["version"] += 1
        _release_animal_if_sole_hold(app)
        # Fail PENDING settlements for this application
        for s in store.settlements.values():
            if (s["subject_type"] == "ADOPTION" and s["subject_id"] == app["id"]
                    and s["status"] == "PENDING"):
                s["status"] = "FAILED"
                s["updated_at"] = now
                s["version"] += 1
    return success_object(serialize_application(app))
