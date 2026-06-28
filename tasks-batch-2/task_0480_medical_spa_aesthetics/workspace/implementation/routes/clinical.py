"""Consultations, StandingOrders, ConsentPhotos (PRD §3.2, §3.5)."""
from flask import Blueprint, request

from db import db, new_id, now_iso
from errors import ApiError
from middleware import require_roles
from helpers import (get_json_body, require_string, require_enum, require_int,
                     require_datetime, optional_string, require_bool, paginate)
from response import success_object, success_array
import domain

bp = Blueprint("clinical", __name__)

PRODUCTS = {"BOTOX", "DYSPORT", "JUVEDERM", "RESTYLANE"}
PHOTO_KINDS = {"CONSENT", "BEFORE", "AFTER"}


def _base_common():
    ts = now_iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": db.next_seq(),
    }


# --------------------------------------------------------------------------
# Consultation
# --------------------------------------------------------------------------
@bp.route("/aesthetics/consultations", methods=["POST"])
@require_roles("Provider")
def create_consultation():
    body = get_json_body()
    patient_id = require_string(body, "patient_id")
    exam_provider_id = require_string(body, "exam_provider_id")
    chief_complaint = require_string(body, "chief_complaint")

    if patient_id not in db.patients:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Patient not found")
    if exam_provider_id not in db.providers:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "Provider not found")

    consultation = _base_common()
    consultation.update({
        "patient_id": patient_id,
        "exam_provider_id": exam_provider_id,
        "chief_complaint": chief_complaint,
        "exam_clock_utc": None,
        "_exam_clock_dt": None,
        "status": "DRAFT",
    })
    db.consultations[consultation["id"]] = consultation
    return success_object(domain.serialize(consultation, "Consultation"), 201)


@bp.route("/aesthetics/consultations", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_consultations():
    patient_id = request.args.get("patient_id")
    exam_provider_id = request.args.get("exam_provider_id")
    status = request.args.get("status")
    records = list(db.consultations.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if exam_provider_id is not None:
        records = [r for r in records if r["exam_provider_id"] == exam_provider_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "Consultation") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/consultations/<cid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_consultation(cid):
    consultation = db.consultations.get(cid)
    if consultation is None:
        raise ApiError("ERR_CONSULTATION_NOT_FOUND", "Consultation not found")
    return success_object(domain.serialize(consultation, "Consultation"))


@bp.route("/aesthetics/consultations/<cid>/complete-exam", methods=["POST"])
@require_roles("Provider")
def complete_exam(cid):
    consultation = db.consultations.get(cid)
    if consultation is None:
        raise ApiError("ERR_CONSULTATION_NOT_FOUND", "Consultation not found")
    if consultation["status"] != "DRAFT":
        raise ApiError("ERR_CONSULTATION_NOT_DRAFT", "Consultation not in DRAFT")
    provider = db.providers.get(consultation["exam_provider_id"])
    if provider is None or provider["role_kind"] != "INJECTOR" or provider["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ELIGIBLE", "Exam provider not eligible")
    now = domain.clock.now()
    consultation["status"] = "EXAM_COMPLETE"
    consultation["_exam_clock_dt"] = now
    consultation["exam_clock_utc"] = (
        now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z")
    domain.touch(consultation)
    return success_object(domain.serialize(consultation, "Consultation"))


@bp.route("/aesthetics/consultations/<cid>/void", methods=["POST"])
@require_roles("ClinicAdmin")
def void_consultation(cid):
    consultation = db.consultations.get(cid)
    if consultation is None:
        raise ApiError("ERR_CONSULTATION_NOT_FOUND", "Consultation not found")
    status = consultation["status"]
    if status not in ("DRAFT", "EXAM_COMPLETE"):
        raise ApiError("ERR_CONSULTATION_NOT_DRAFT", "Consultation not voidable")
    if status == "EXAM_COMPLETE":
        in_use = any(
            p["consultation_id"] == cid and p["status"] in ("PROPOSED", "ACTIVE")
            for p in db.treatment_plans.values()
        )
        if in_use:
            raise ApiError("ERR_CONSULTATION_IN_USE",
                           "Consultation referenced by a PROPOSED/ACTIVE plan")
    consultation["status"] = "VOID"
    domain.touch(consultation)
    return success_object(domain.serialize(consultation, "Consultation"))


# --------------------------------------------------------------------------
# StandingOrder
# --------------------------------------------------------------------------
@bp.route("/aesthetics/standing-orders", methods=["POST"])
@require_roles("Provider")
def create_standing_order():
    body = get_json_body()
    consultation_id = require_string(body, "consultation_id")
    director_provider_id = require_string(body, "director_provider_id")
    product = require_enum(body, "product", PRODUCTS)
    max_units_authorized = require_int(body, "max_units_authorized", positive=True)
    valid_until_dt = require_datetime(body, "valid_until_utc")

    if consultation_id not in db.consultations:
        raise ApiError("ERR_CONSULTATION_NOT_FOUND", "Consultation not found")
    director = db.providers.get(director_provider_id)
    if director is None:
        raise ApiError("ERR_PROVIDER_NOT_FOUND", "Provider not found")
    if director["role_kind"] != "MEDICAL_DIRECTOR" or director["status"] != "ACTIVE":
        raise ApiError("ERR_PROVIDER_NOT_ELIGIBLE", "Signing director not eligible")

    order = _base_common()
    order.update({
        "consultation_id": consultation_id,
        "director_provider_id": director_provider_id,
        "product": product,
        "max_units_authorized": max_units_authorized,
        "valid_until_utc": body["valid_until_utc"],
        "_valid_until_dt": valid_until_dt,
        "status": "SIGNED",
    })
    db.standing_orders[order["id"]] = order
    return success_object(domain.serialize(order, "StandingOrder"), 201)


@bp.route("/aesthetics/standing-orders", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_standing_orders():
    consultation_id = request.args.get("consultation_id")
    director_provider_id = request.args.get("director_provider_id")
    status = request.args.get("status")
    records = list(db.standing_orders.values())
    if consultation_id is not None:
        records = [r for r in records if r["consultation_id"] == consultation_id]
    if director_provider_id is not None:
        records = [r for r in records if r["director_provider_id"] == director_provider_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "StandingOrder") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/standing-orders/<oid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_standing_order(oid):
    order = db.standing_orders.get(oid)
    if order is None:
        raise ApiError("ERR_STANDING_ORDER_NOT_FOUND", "Standing order not found")
    return success_object(domain.serialize(order, "StandingOrder"))


@bp.route("/aesthetics/standing-orders/<oid>/revoke", methods=["POST"])
@require_roles("Provider")
def revoke_standing_order(oid):
    order = db.standing_orders.get(oid)
    if order is None:
        raise ApiError("ERR_STANDING_ORDER_NOT_FOUND", "Standing order not found")
    body = get_json_body()
    expected = require_int(body, "expected_standing_order_version")
    if expected != order["version"]:
        raise ApiError("ERR_STALE_STANDING_ORDER_VERSION", "Stale standing order version")
    order["status"] = "REVOKED"
    domain.touch(order)
    return success_object(domain.serialize(order, "StandingOrder"))


# --------------------------------------------------------------------------
# ConsentPhoto (immutable event record: id + created_at only)
# --------------------------------------------------------------------------
@bp.route("/aesthetics/consent-photos", methods=["POST"])
@require_roles("Provider")
def create_consent_photo():
    body = get_json_body()
    patient_id = require_string(body, "patient_id")
    kind = require_enum(body, "kind", PHOTO_KINDS)
    storage_uri = require_string(body, "storage_uri")
    treatment_session_id = optional_string(body, "treatment_session_id")
    signed = require_bool(body, "signed", default=False)

    patient = db.patients.get(patient_id)
    if patient is None:
        raise ApiError("ERR_PATIENT_NOT_FOUND", "Patient not found")
    if treatment_session_id is not None and treatment_session_id not in db.treatment_sessions:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Treatment session not found")

    photo = {
        "id": new_id(),
        "created_at": now_iso(),
        "_seq": db.next_seq(),
        "patient_id": patient_id,
        "treatment_session_id": treatment_session_id,
        "kind": kind,
        "signed": signed,
        "storage_uri": storage_uri,
    }
    db.consent_photos[photo["id"]] = photo

    if kind == "CONSENT" and signed is True:
        patient["photo_consent_on_file"] = True
        domain.touch(patient)

    return success_object(domain.serialize(photo, "ConsentPhoto"), 201)


@bp.route("/aesthetics/consent-photos", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def list_consent_photos():
    patient_id = request.args.get("patient_id")
    treatment_session_id = request.args.get("treatment_session_id")
    kind = request.args.get("kind")
    records = list(db.consent_photos.values())
    if patient_id is not None:
        records = [r for r in records if r["patient_id"] == patient_id]
    if treatment_session_id is not None:
        records = [r for r in records if r["treatment_session_id"] == treatment_session_id]
    if kind is not None:
        records = [r for r in records if r["kind"] == kind]
    page, limit, offset, total = paginate(records)
    return success_array([domain.serialize(r, "ConsentPhoto") for r in page],
                         limit, offset, total)


@bp.route("/aesthetics/consent-photos/<phid>", methods=["GET"])
@require_roles("ClinicAdmin", "Provider")
def get_consent_photo(phid):
    photo = db.consent_photos.get(phid)
    if photo is None:
        raise ApiError("ERR_SESSION_NOT_FOUND", "Consent photo not found")
    return success_object(domain.serialize(photo, "ConsentPhoto"))
