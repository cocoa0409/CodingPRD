"""Producer endpoints (PRD §3.1, §3.2)."""

from flask import Blueprint, request

import db
from errors import invalid_state, invalid_request
from middleware import require_roles, ALL_ROLES
from response import success_object, paginate
from services.helpers import get_producer_or_404
from validation import (
    body, require_string, require_enum, require_non_negative_int,
    optional_string,
)

bp = Blueprint("producers", __name__)

ENTITY_TYPES = ("INDIVIDUAL", "CORPORATION", "PARTNERSHIP", "TRUST", "LLC")


@bp.post("/fsa/producers")
def create_producer():
    require_roles(["CountySpecialist"])
    data = body()
    producer_name = require_string(data, "producer_name")
    tax_id_last4 = require_string(data, "tax_id_last4")
    entity_type = require_enum(data, "entity_type", ENTITY_TYPES)

    producer = db.common_fields()
    producer.update({
        "producer_name": producer_name,
        "tax_id_last4": tax_id_last4,
        "entity_type": entity_type,
        "agi_attestation_status": "NOT_FILED",
        "adjusted_gross_income": None,
        "payment_limitation_cap_cents": 12500000,
        "conservation_status": "PENDING",
    })
    db.producers[producer["id"]] = producer
    return success_object(producer, 201)


@bp.get("/fsa/producers/<producer_id>")
def get_producer(producer_id):
    require_roles(ALL_ROLES)
    return success_object(get_producer_or_404(producer_id))


@bp.get("/fsa/producers")
def list_producers():
    require_roles(ALL_ROLES)
    entity_type = request.args.get("entity_type")
    items = list(db.producers.values())
    if entity_type is not None:
        items = [p for p in items if p["entity_type"] == entity_type]
    items.sort(key=lambda p: p["created_at"])
    return paginate(items, request.args)


@bp.post("/fsa/producers/<producer_id>/agi-attestations")
def file_agi_attestation(producer_id):
    user_id, _ = require_roles(["Producer"])
    producer = get_producer_or_404(producer_id)
    # Only NOT_FILED or NONCOMPLIANT may (re-)file (PRD §3.2, state machine).
    if producer["agi_attestation_status"] not in ("NOT_FILED", "NONCOMPLIANT"):
        raise invalid_state("AGI attestation cannot be filed from current status")
    data = body()
    agi = require_non_negative_int(data, "adjusted_gross_income")
    producer["adjusted_gross_income"] = agi
    producer["agi_attestation_status"] = "FILED"
    db.touch(producer)
    return success_object(producer, 201)


@bp.post("/fsa/producers/<producer_id>/agi-attestations/verify")
def verify_agi(producer_id):
    require_roles(["CountySpecialist"])
    producer = get_producer_or_404(producer_id)
    if producer["agi_attestation_status"] != "FILED":
        raise invalid_state("AGI attestation is not FILED")
    producer["agi_attestation_status"] = "VERIFIED"
    db.touch(producer)
    return success_object(producer)


@bp.post("/fsa/producers/<producer_id>/agi-attestations/flag-noncompliant")
def flag_agi_noncompliant(producer_id):
    require_roles(["CountySpecialist"])
    producer = get_producer_or_404(producer_id)
    if producer["agi_attestation_status"] != "FILED":
        raise invalid_state("AGI attestation is not FILED")
    producer["agi_attestation_status"] = "NONCOMPLIANT"
    db.touch(producer)
    return success_object(producer)


@bp.post("/fsa/producers/<producer_id>/conservation-certifications")
def file_conservation_cert(producer_id):
    user_id, _ = require_roles(["Producer"])
    producer = get_producer_or_404(producer_id)
    data = body()
    remediation_plan = optional_string(data, "remediation_plan")
    status = producer["conservation_status"]
    if status == "PENDING":
        producer["conservation_status"] = "CERTIFIED"
    elif status == "VIOLATION":
        # Re-certification from VIOLATION requires a remediation plan (PRD §3.2).
        if remediation_plan is None:
            raise invalid_request(
                "A remediation plan attestation must accompany re-certification from VIOLATION")
        producer["conservation_status"] = "CERTIFIED"
    else:
        raise invalid_state("Conservation certification not allowed from current status")
    db.touch(producer)
    return success_object(producer, 201)


@bp.post("/fsa/producers/<producer_id>/conservation-violations")
def record_conservation_violation(producer_id):
    require_roles(["CountyExecutiveDirector"])
    producer = get_producer_or_404(producer_id)
    data = body()
    require_string(data, "violation_code")
    if producer["conservation_status"] != "CERTIFIED":
        raise invalid_state("Conservation violation requires CERTIFIED status")
    producer["conservation_status"] = "VIOLATION"
    db.touch(producer)
    return success_object(producer, 201)


@bp.post("/fsa/producers/<producer_id>/conservation-exemptions")
def grant_conservation_exemption(producer_id):
    require_roles(["CountyExecutiveDirector"])
    producer = get_producer_or_404(producer_id)
    data = body()
    require_string(data, "exemption_reason")
    if producer["conservation_status"] != "PENDING":
        raise invalid_state("Conservation exemption requires PENDING status")
    producer["conservation_status"] = "EXEMPT"
    db.touch(producer)
    return success_object(producer, 201)
