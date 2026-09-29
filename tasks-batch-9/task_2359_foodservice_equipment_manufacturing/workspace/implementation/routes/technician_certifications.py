"""TechnicianCertification endpoints (PRD Section 3.9)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from errors import ApiError
from middleware import authorize, partner_scope
from response import ok, created, ok_list
from routes.helpers import find, maybe, filter_by, unique_code
from services import calc, derive
from timeutil import add_days

bp = Blueprint("technician_certifications", __name__)

STATUSES = ("ENROLLED", "PASSED", "FAILED")
READ_ROLES = ("ServicePartnerUser", "ChannelManager", "WarrantyAdjudicator", "PlatformAdmin")


@bp.post("/technician-certifications")
def enroll_technician():
    actor = authorize("ServicePartnerUser", "ChannelManager", "PlatformAdmin")
    payload = validate.body()
    raw_partner_id = payload.get("service_partner_id")
    if isinstance(raw_partner_id, str) and raw_partner_id:
        partner_scope(actor, raw_partner_id)

    service_partner_id = validate.string_field(payload, "service_partner_id")
    equipment_model_id = validate.string_field(payload, "equipment_model_id")
    technician_code = validate.string_field(payload, "technician_code", min_len=1, max_len=32)
    training_hours = validate.number_field(payload, "training_hours", ge=0)

    find(db.equipment_models, equipment_model_id, "ERR_EQUIPMENT_MODEL_NOT_FOUND")
    partner = find(db.service_partners, service_partner_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")

    if partner["status"] == "TERMINATED":
        raise ApiError("ERR_CHANNEL_STATE_INVALID",
                       "a TERMINATED partner cannot enrol technicians")

    unique_code(db.technician_certifications, service_partner_id=service_partner_id,
                equipment_model_id=equipment_model_id, technician_code=technician_code)

    cert = insert(db.technician_certifications, {
        "service_partner_id": service_partner_id,
        "equipment_model_id": equipment_model_id,
        "technician_code": technician_code,
        "training_hours": training_hours,
        "exam_score": None,
        "status": "ENROLLED",
        "certified_on": None,
        "expires_on": None,
    })
    return created(cert)


@bp.get("/technician-certifications")
def list_certifications():
    actor = authorize(*READ_ROLES)
    service_partner_id = validate.str_arg("service_partner_id")
    if service_partner_id is not None:
        partner_scope(actor, service_partner_id)
    limit, offset = validate.pagination()
    equipment_model_id = validate.str_arg("equipment_model_id")
    status = validate.enum_arg("status", STATUSES)

    items = ordered(db.technician_certifications)
    if actor.is_partner_user:
        items = [c for c in items if c["service_partner_id"] == actor.user_id]
    items = filter_by(items, "service_partner_id", service_partner_id)
    items = filter_by(items, "equipment_model_id", equipment_model_id)
    items = filter_by(items, "status", status)
    return ok_list(items, limit, offset)


@bp.get("/technician-certifications/<cert_id>")
def get_certification(cert_id):
    actor = authorize(*READ_ROLES)
    probe = maybe(db.technician_certifications, cert_id)
    partner_scope(actor, probe["service_partner_id"] if probe else None)
    cert = find(db.technician_certifications, cert_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")
    return ok(cert)


@bp.post("/technician-certifications/<cert_id>/grade")
def grade_certification(cert_id):
    authorize("ChannelManager", "PlatformAdmin")
    payload = validate.body()
    exam_score = validate.int_field(payload, "exam_score", minimum=0)

    cert = find(db.technician_certifications, cert_id, "ERR_CHANNEL_RESOURCE_NOT_FOUND")

    if cert["status"] != "ENROLLED":
        raise ApiError("ERR_CHANNEL_STATE_INVALID",
                       "a %s certification cannot be graded" % cert["status"])
    if calc.dec(cert["training_hours"]) < calc.MIN_TRAINING_HOURS:
        raise ApiError("ERR_TRAINING_HOURS_NOT_MET",
                       "at least %d documented training hours are required"
                       % calc.MIN_TRAINING_HOURS)

    cert["exam_score"] = exam_score
    if exam_score >= calc.PASS_SCORE:
        cert["status"] = "PASSED"
        cert["certified_on"] = db.clock
        cert["expires_on"] = add_days(db.clock, calc.CERT_TERM_DAYS)
    else:
        cert["status"] = "FAILED"
        cert["certified_on"] = None
        cert["expires_on"] = None
    touch(cert)

    partner = db.service_partners.get(cert["service_partner_id"])
    if partner is not None:
        derive.refresh_partner_authority(partner)
    return ok(cert)
