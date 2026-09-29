"""Investor endpoints (PRD 3.4) — two independent status dimensions."""
from flask import Blueprint

import clock
import constants as C
import db
import middleware
from errors import ApiError, bad_request
from response import created_response, object_response
from routes._common import listing, read_one
from services import calc, domain
from util import add_days

bp = Blueprint("investors", __name__)


@bp.post("/investors")
def create_investor():
    middleware.actor([C.SPONSOR, C.ADMIN])
    payload = middleware.body_or_400()
    legal_name = middleware.req_str(payload, "legal_name")
    entity_type = middleware.req_enum(payload, "entity_type", C.ENTITY_TYPES)
    accreditation_method = middleware.req_enum(
        payload, "accreditation_method", C.ACCREDITATION_METHODS)
    annual_income_cents = middleware.req_int(payload, "annual_income_cents", 0)
    net_worth_cents = middleware.req_int(payload, "net_worth_cents", 0)
    liquid_net_worth_cents = middleware.req_int(payload, "liquid_net_worth_cents", 0)

    row = db.new_row(db.investors, {
        "legal_name": legal_name,
        "entity_type": entity_type,
        "accreditation_method": accreditation_method,
        "annual_income_cents": annual_income_cents,
        "net_worth_cents": net_worth_cents,
        "liquid_net_worth_cents": liquid_net_worth_cents,
        "accreditation_status": "UNVERIFIED",
        "accreditation_verified_at": None,
        "accreditation_expires_at": None,
        "suitability_status": "NOT_REVIEWED",
        "suitability_cap_cents": None,
        "suitability_offering_id": None,
        "suitability_reviewed_by_user_id": None,
    })
    return created_response(db.serialize(row))


@bp.get("/investors/<investor_id>")
def get_investor(investor_id):
    return read_one("investor", C.READ_EXCHANGE_SIDE, investor_id)


@bp.get("/investors")
def list_investors():
    return listing(db.investors, C.READ_EXCHANGE_SIDE,
                   str_filters=("entity_type", "accreditation_status",
                                "suitability_status", "suitability_offering_id"))


@bp.post("/investors/<investor_id>/verify-accreditation")
def verify_accreditation(investor_id):
    middleware.actor([C.COMPLIANCE])
    payload = middleware.body_or_400()
    middleware.req_str(payload, "evidence_reference")

    investor = domain.require("investor", investor_id)

    # rung 30 — a RULE_506C offering will not accept self-certification
    scoped = db.offerings.get(investor.get("suitability_offering_id")) \
        if investor.get("suitability_offering_id") else None
    if scoped is not None and scoped["exemption_rule"] == "RULE_506C" \
            and investor["accreditation_method"] in C.SELF_CERT_METHODS:
        raise ApiError("ERR_ACCREDITATION_METHOD_NOT_PERMITTED")

    if investor["accreditation_status"] != "UNVERIFIED":
        raise bad_request("Accreditation may only be verified from UNVERIFIED.")

    now = clock.now()
    investor["accreditation_status"] = "VERIFIED"
    investor["accreditation_verified_at"] = now
    investor["accreditation_expires_at"] = add_days(now, C.ACCREDITATION_VALID_DAYS)
    db.touch(investor)
    return object_response(db.serialize(investor))


@bp.post("/investors/<investor_id>/lapse-accreditation")
def lapse_accreditation(investor_id):
    middleware.actor([C.COMPLIANCE])
    investor = domain.require("investor", investor_id)

    if investor["accreditation_status"] != "VERIFIED":
        raise bad_request("Accreditation may only lapse from VERIFIED.")
    expires_at = investor.get("accreditation_expires_at")
    if expires_at is None or clock.now() < expires_at:
        raise bad_request("A live verification cannot be lapsed early.")

    investor["accreditation_status"] = "EXPIRED"
    db.touch(investor)
    return object_response(db.serialize(investor))


@bp.post("/investors/<investor_id>/review-suitability")
def review_suitability(investor_id):
    user_id, _role = middleware.actor([C.COMPLIANCE])
    payload = middleware.body_or_400()
    decision = middleware.req_enum(payload, "decision", C.SUITABILITY_DECISIONS)
    offering_id = middleware.req_str(payload, "offering_id")

    investor = domain.require("investor", investor_id)
    offering = domain.require("offering", offering_id)
    if offering["status"] != "EFFECTIVE":
        raise ApiError("ERR_OFFERING_NOT_EFFECTIVE")
    if investor["suitability_status"] != "NOT_REVIEWED":
        raise bad_request("Suitability may only be reviewed from NOT_REVIEWED.")

    investor["suitability_status"] = decision
    investor["suitability_offering_id"] = offering["id"]
    investor["suitability_reviewed_by_user_id"] = user_id
    if decision == "DECLINED":
        investor["suitability_cap_cents"] = 0
    else:
        investor["suitability_cap_cents"] = calc.suitability_cap(
            investor["entity_type"], investor["accreditation_method"],
            investor["annual_income_cents"], investor["net_worth_cents"],
            investor["liquid_net_worth_cents"], offering["target_equity_cents"],
        )
    db.touch(investor)
    return object_response(db.serialize(investor))
