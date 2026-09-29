"""Financing agreements: issue, signature, oral confirmation, rescission."""

from flask import Blueprint

import calc
import db
import response
import services
import validation as v
from errors import fail
from middleware import (
    ALL_ROLES,
    ROLE_COMPLIANCE_OFFICER,
    ROLE_PROPERTY_OWNER,
    ROLE_UNDERWRITING_ANALYST,
    authorize,
    require_property_owner,
)

bp = Blueprint("agreement", __name__)


def _signature_matches(submitted, owner_full_name):
    """PRD 2.6 stage 26: case-sensitive after trimming surrounding whitespace."""
    return submitted.strip() == str(owner_full_name).strip()


@bp.post("/pace/financing-agreements")
def issue_agreement():
    authorize([ROLE_UNDERWRITING_ANALYST])
    payload = v.body()
    application_id = v.req_id(payload, "application_id")
    term_years = v.req_int(payload, "term_years")
    apr_bps = v.opt_int(payload, "apr_bps", 800, minimum=1, maximum=1500)
    expected_version = v.req_int(payload, "expected_application_version", minimum=0)
    application = services.get_application(application_id)
    if expected_version != int(application["version"]):
        fail(
            "ERR_APPLICATION_VERSION_CONFLICT",
            "expected_application_version does not match the application version",
        )
    if application["status"] != "APPROVED":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not APPROVED")
    weighted_life = application.get("weighted_useful_life_years")
    if term_years not in v.ALLOWED_TERMS or (
        weighted_life is not None and term_years > int(weighted_life)
    ):
        fail(
            "ERR_TERM_EXCEEDS_USEFUL_LIFE",
            "term_years is not an allowed term within the weighted useful life",
        )
    for prior in services.agreements_of(application["id"]):
        if prior["status"] == "ISSUED":
            prior["status"] = "VOID"
            db.touch(prior)
    composition = calc.financed_amount_composition(application["requested_principal_cents"])
    agreement = db.create(
        "agreements",
        {
            "application_id": application["id"],
            "term_years": term_years,
            "apr_bps": apr_bps,
            "principal_cents": composition["principal_cents"],
            "admin_fee_cents": composition["admin_fee_cents"],
            "county_recording_fee_cents": composition["county_recording_fee_cents"],
            "financed_amount_cents": composition["financed_amount_cents"],
            "annual_installment_cents": calc.level_payment_cents(
                composition["financed_amount_cents"], apr_bps, term_years
            ),
            "contractor_payable_cents": composition["contractor_payable_cents"],
            "status": "ISSUED",
            "signature_name": None,
            "signed_at": None,
            "rescission_expires_at": None,
            "oral_confirmation_required": application["oral_confirmation_required"],
            "oral_confirmation_completed_at": None,
            "oral_confirmation_reference": None,
            "rescinded_at": None,
            "effective_at": None,
        },
    )
    db.touch(application)
    return response.created(db.public(agreement))


@bp.get("/pace/financing-agreements/<row_id>")
def read_agreement(row_id):
    authorize(ALL_ROLES)
    return response.ok(db.public(services.get_agreement(row_id)))


@bp.post("/pace/financing-agreements/<row_id>/sign")
def sign_agreement(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    signature_name = v.req_str(payload, "signature_name")
    agreement = services.get_agreement(row_id)
    application = services.get_application(agreement["application_id"])
    require_property_owner(caller, application["property_id"])
    if application["status"] != "APPROVED":
        fail("ERR_APPLICATION_STATE_INVALID", "Application is not APPROVED")
    if agreement["status"] != "ISSUED":
        fail("ERR_AGREEMENT_STATE_INVALID", "Agreement is not ISSUED")
    prop = services.get_property(application["property_id"])
    if not _signature_matches(signature_name, prop["owner_full_name"]):
        fail("ERR_SIGNATURE_NAME_MISMATCH", "signature_name does not match the record owner")
    instant = db.now()
    agreement["signature_name"] = signature_name
    agreement["signed_at"] = db.iso(instant)
    agreement["rescission_expires_at"] = db.iso(calc.rescission_expiry(instant))
    agreement["status"] = "SIGNED"
    db.touch(agreement)
    application["status"] = "FUNDING_PENDING"
    db.touch(application)
    services.recompute_property_rollups(prop)
    return response.ok(db.public(agreement))


@bp.post("/pace/financing-agreements/<row_id>/oral-confirmation")
def log_oral_confirmation(row_id):
    authorize([ROLE_COMPLIANCE_OFFICER])
    payload = v.body()
    reference = v.req_str(payload, "oral_confirmation_reference")
    agreement = services.get_agreement(row_id)
    if agreement["status"] not in ("ISSUED", "SIGNED"):
        fail("ERR_AGREEMENT_STATE_INVALID", "Agreement is not ISSUED or SIGNED")
    agreement["oral_confirmation_reference"] = reference
    agreement["oral_confirmation_completed_at"] = db.now_iso()
    db.touch(agreement)
    return response.ok(db.public(agreement))


@bp.post("/pace/financing-agreements/<row_id>/rescind")
def rescind_agreement(row_id):
    caller = authorize([ROLE_PROPERTY_OWNER])
    payload = v.body()
    v.opt_str(payload, "reason")
    agreement = services.get_agreement(row_id)
    application = services.get_application(agreement["application_id"])
    require_property_owner(caller, application["property_id"])
    if agreement["status"] != "SIGNED":
        fail("ERR_AGREEMENT_STATE_INVALID", "Agreement is not SIGNED")
    expiry = db.parse_instant(agreement.get("rescission_expires_at"))
    if expiry is None or db.now() >= expiry:
        fail("ERR_AGREEMENT_STATE_INVALID", "The right of rescission has lapsed")
    for draw in services.disbursements_of_application(application["id"]):
        if draw["status"] == "RELEASED":
            fail("ERR_FUNDS_ALREADY_RELEASED", "Funds have already been released")
    agreement["status"] = "RESCINDED"
    agreement["rescinded_at"] = db.now_iso()
    db.touch(agreement)
    application["status"] = "WITHDRAWN"
    db.touch(application)
    for measure in services.measures_of(application["id"]):
        if measure["status"] == "APPROVED":
            measure["status"] = "INELIGIBLE"
            db.touch(measure)
    for certificate in services.certificates_of(application["id"]):
        if certificate["status"] in ("CONTRACTOR_ATTESTED", "HOMEOWNER_SIGNED"):
            certificate["status"] = "REJECTED"
            certificate["rejection_reason"] = "AGREEMENT_RESCINDED"
            db.touch(certificate)
    services.recompute_property_rollups(services.get_property(application["property_id"]))
    return response.ok(db.public(agreement))
