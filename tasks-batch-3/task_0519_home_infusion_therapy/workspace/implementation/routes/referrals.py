"""Referral routes (PRD §3.2)."""
from flask import Blueprint, request

import errors
import helpers
from db import db, stamp_create, touch
from middleware import require
from response import object_response, array_response

bp = Blueprint("referrals", __name__)

READ_ROLES = ["IntakeCoordinator", "Pharmacist", "MedicalDirector"]


@bp.route("/referrals", methods=["POST"])
def create_referral():
    require(["IntakeCoordinator"])
    body = helpers.get_body()
    # existence (3) before other body validity (4) per PRD §2.8
    patient_id = helpers.as_str(body, "patient_id")
    if patient_id not in db.patients:
        raise errors.not_found("Patient not found")
    referring_provider_npi = helpers.as_str(body, "referring_provider_npi")
    diagnosis_code = helpers.as_str(body, "diagnosis_code")

    referral = stamp_create({
        "patient_id": patient_id,
        "referring_provider_npi": referring_provider_npi,
        "diagnosis_code": diagnosis_code,
        "status": "RECEIVED",
    })
    db.referrals[referral["id"]] = referral
    return object_response(referral, 201)


@bp.route("/referrals/<id>", methods=["GET"])
def get_referral(id):
    require(READ_ROLES)
    referral = db.referrals.get(id)
    if referral is None:
        raise errors.not_found("Referral not found")
    return object_response(referral, 200)


@bp.route("/referrals", methods=["GET"])
def list_referrals():
    require(READ_ROLES)
    limit, offset = helpers.pagination_params()
    patient_id = request.args.get("patient_id")
    items = list(db.referrals.values())
    if patient_id is not None:
        items = [r for r in items if r["patient_id"] == patient_id]
    items = helpers.sort_by_created(items)
    window, total, has_more = helpers.paginate(items, limit, offset)
    return array_response(window, limit, offset, total, has_more, 200)


@bp.route("/referrals/<id>/accept", methods=["POST"])
def accept_referral(id):
    require(["IntakeCoordinator"])
    referral = db.referrals.get(id)
    if referral is None:
        raise errors.not_found("Referral not found")
    if referral["status"] != "RECEIVED":
        raise errors.invalid_state("Referral is not in RECEIVED state")
    patient = db.patients.get(referral["patient_id"])
    if patient is None or patient["status"] != "ACTIVE":
        raise errors.invalid_state("Patient must exist and be ACTIVE")
    referral["status"] = "ACCEPTED"
    touch(referral)
    return object_response(referral, 200)


@bp.route("/referrals/<id>/reject", methods=["POST"])
def reject_referral(id):
    require(["IntakeCoordinator"])
    referral = db.referrals.get(id)
    if referral is None:
        raise errors.not_found("Referral not found")
    if referral["status"] != "RECEIVED":
        raise errors.invalid_state("Referral is not in RECEIVED state")
    referral["status"] = "REJECTED"
    touch(referral)
    return object_response(referral, 200)
