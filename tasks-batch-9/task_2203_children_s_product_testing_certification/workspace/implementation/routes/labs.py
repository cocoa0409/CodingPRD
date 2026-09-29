"""Laboratories and accreditation scopes (PRD 3.2)."""

from flask import Blueprint

import auth
import clock
import db
import paging
import refs
import response
import validation
from errors import ApiError
from services import engine

bp = Blueprint("labs", __name__)

INDEPENDENCE_CLASSES = {"INDEPENDENT", "FIREWALLED_GOVERNMENT", "MANUFACTURER_OWNED"}
OPERATIONAL_STATES = {"ACTIVE", "BARRED"}
ACCREDITATION_STATES = {"ACCREDITED", "SUSPENDED", "EXPIRED"}
LAB_READ_ROLES = (
    "ComplianceAdministrator",
    "TestCoordinator",
    "CertificationOfficer",
    "LaboratoryUser",
)


@bp.post("/laboratories")
def create_laboratory():
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    lab_name = validation.string_field(body, "lab_name", min_len=1, max_len=160)
    accreditation_body_code = validation.string_field(
        body, "accreditation_body_code", min_len=2, max_len=20,
        pattern=validation.RE_UPPER_ALNUM,
    )
    independence_class = validation.enum_field(
        body, "independence_class", INDEPENDENCE_CLASSES
    )
    concurrent_slot_capacity = validation.int_field(
        body, "concurrent_slot_capacity", minimum=1, maximum=10
    )
    row = db.insert(
        "laboratories",
        {
            "lab_name": lab_name,
            "accreditation_body_code": accreditation_body_code,
            "independence_class": independence_class,
            "operational_state": "ACTIVE",
            "influence_attestation_state": "MISSING",
            "influence_attestation_valid_through": None,
            "concurrent_slot_capacity": concurrent_slot_capacity,
            "billed_fee_cents_total": 0,
            "credited_fee_cents_total": 0,
        },
    )
    return response.object_response(db.serialize("laboratories", row), 201)


@bp.get("/laboratories/<laboratory_id>")
def get_laboratory(laboratory_id):
    auth.require_roles(*LAB_READ_ROLES)
    row = refs.laboratory(laboratory_id)
    return response.object_response(db.serialize("laboratories", row))


@bp.post("/laboratories/<laboratory_id>/independence-attestations")
def record_attestation(laboratory_id):
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    valid_through = validation.datetime_field(body, "attestation_valid_through")
    lab = refs.laboratory(laboratory_id)
    lab["influence_attestation_state"] = "CURRENT"
    lab["influence_attestation_valid_through"] = valid_through
    engine.bump("laboratories", lab)
    return response.object_response(db.serialize("laboratories", lab))


@bp.post("/laboratories/<laboratory_id>/operational-state")
def set_operational_state(laboratory_id):
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    state = validation.enum_field(body, "operational_state", OPERATIONAL_STATES)
    lab = refs.laboratory(laboratory_id)
    lab["operational_state"] = state
    engine.bump("laboratories", lab)
    return response.object_response(db.serialize("laboratories", lab))


@bp.post("/laboratories/<laboratory_id>/accreditations")
def create_accreditation(laboratory_id):
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    rule_id = validation.id_field(body, "rule_id")
    valid_from = validation.datetime_field(body, "valid_from")
    valid_through = validation.datetime_field(body, "valid_through")
    surcharge = validation.int_field(
        body, "fee_surcharge_basis_points", minimum=0, maximum=5000,
        required=False, default=0,
    )
    lab = refs.laboratory(laboratory_id)
    rule = refs.rule(rule_id)
    if not valid_through > valid_from:
        raise ApiError("ERR_WINDOW_INVALID")
    row = db.insert(
        "lab_accreditations",
        {
            "laboratory_id": lab["id"],
            "rule_id": rule["id"],
            "test_method_code": rule["test_method_code"],
            "valid_from": valid_from,
            "valid_through": valid_through,
            "accreditation_state": "ACCREDITED",
            "suspension_reason": None,
            "fee_surcharge_basis_points": surcharge,
        },
    )
    return response.object_response(db.serialize("lab_accreditations", row), 201)


@bp.get("/lab-accreditations/<accreditation_id>")
def get_accreditation(accreditation_id):
    auth.require_roles(*LAB_READ_ROLES)
    row = refs.accreditation(accreditation_id)
    return response.object_response(db.serialize("lab_accreditations", row))


@bp.get("/lab-accreditations")
def list_accreditations():
    auth.require_roles(*LAB_READ_ROLES)
    laboratory_id = validation.query_string("laboratory_id")
    rule_id = validation.query_string("rule_id")
    state = validation.query_enum("accreditation_state", ACCREDITATION_STATES)
    return paging.build(
        "lab_accreditations",
        [
            paging.eq_filter("laboratory_id", laboratory_id),
            paging.eq_filter("rule_id", rule_id),
            paging.eq_filter("accreditation_state", state),
        ],
    )


@bp.post("/lab-accreditations/<accreditation_id>/suspend")
def suspend_accreditation(accreditation_id):
    auth.require_roles("ComplianceAdministrator")
    body = validation.json_body()
    reason = validation.string_field(body, "suspension_reason", min_len=1, max_len=200)
    accreditation = refs.accreditation(accreditation_id)
    if accreditation["accreditation_state"] != "ACCREDITED":
        raise ApiError("ERR_ACCREDITATION_STATE_INVALID")

    if reason == "COVERAGE_ELAPSED" and clock.now() > accreditation["valid_through"]:
        accreditation["accreditation_state"] = "EXPIRED"
    else:
        accreditation["accreditation_state"] = "SUSPENDED"
    accreditation["suspension_reason"] = reason
    engine.bump("lab_accreditations", accreditation)
    engine.cascade_accreditation_suspension(accreditation)
    return response.object_response(db.serialize("lab_accreditations", accreditation))
