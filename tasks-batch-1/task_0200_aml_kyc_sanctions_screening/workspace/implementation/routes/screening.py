"""Beneficial owners and screening hits (PRD §3.4, §3.5)."""

from decimal import Decimal

from flask import Blueprint, request

import db
import services
from calculations import CONFIRM_FLOOR
from errors import (
    err,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE,
    ERR_INVALID_DECISION,
    ERR_HIT_NOT_CONFIRMABLE,
    ERR_UBO_ON_INDIVIDUAL,
    ERR_OWNERSHIP_EXCEEDS_100,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_string,
    require_enum,
    require_country,
    require_field,
    optional_bool,
    parse_pagination,
    sort_and_paginate,
    to_decimal,
)

bp = Blueprint("screening", __name__)

READ_ROLES = {"ComplianceOfficer", "Analyst", "QualityReviewer", "PlatformAdmin"}
LIST_TYPES = {"OFAC_SDN", "EU_SANCTIONS", "PEP", "ADVERSE_MEDIA"}
DEROGATORY_LISTS = {"OFAC_SDN", "EU_SANCTIONS"}


def _validate_match_score(value):
    d = to_decimal(value, "match_score")
    if d < Decimal("0") or d > Decimal("1"):
        raise err(ERR_INVALID_REQUEST, "match_score must be 0.00..1.00.")
    return d


# ===========================================================================
# Beneficial owners
# ===========================================================================
@bp.route("/customers/<cid>/beneficial-owners", methods=["POST"])
def add_beneficial_owner(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))
    body = get_body()

    full_name = require_string(body, "full_name")
    ownership_raw = require_field(body, "ownership_pct")
    pct = to_decimal(ownership_raw, "ownership_pct")
    if pct <= Decimal("0") or pct > Decimal("100"):
        raise err(ERR_INVALID_REQUEST, "ownership_pct must be 0 < pct <= 100.")
    country = require_country(body, "country_code")
    is_control = optional_bool(body, "is_control_person", False)

    # priority 17: UBO only on LEGAL_ENTITY (PRD §3.4)
    if customer["customer_type"] != "LEGAL_ENTITY":
        raise err(ERR_UBO_ON_INDIVIDUAL, "Beneficial owner requires a LEGAL_ENTITY customer.")

    # priority 18: aggregate ownership must not exceed 100.00 (PRD §3.4)
    existing = sum(
        Decimal(str(o["ownership_pct"]))
        for o in db.beneficial_owners.values()
        if o["customer_id"] == cid
    )
    if existing + pct > Decimal("100"):
        raise err(ERR_OWNERSHIP_EXCEEDS_100, "Aggregate ownership_pct would exceed 100.00.")

    base = db.common_create_fields()
    pct_num = float(pct) if pct != pct.to_integral_value() else int(pct)
    ubo = {
        **base,
        "customer_id": cid,
        "full_name": full_name,
        "ownership_pct": pct_num,
        "country_code": country,
        "is_control_person": is_control,
        "screening_status": "UNSCREENED",
    }
    db.beneficial_owners[ubo["id"]] = ubo
    services.audit("BeneficialOwner", ubo["id"], "UBO_ADDED", user_id, role)
    return object_response(db.public(ubo), 201)


@bp.route("/customers/<cid>/beneficial-owners", methods=["GET"])
def list_beneficial_owners(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.customers.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [o for o in db.beneficial_owners.values() if o["customer_id"] == cid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(o) for o in page], limit, offset, total)


@bp.route("/beneficial-owners/<oid>", methods=["GET"])
def get_beneficial_owner(oid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    ubo = require_found(db.beneficial_owners.get(oid))
    return object_response(db.public(ubo))


@bp.route("/beneficial-owners/<oid>/screening-hits", methods=["GET"])
def list_ubo_screening_hits(oid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.beneficial_owners.get(oid))
    limit, offset = parse_pagination(request.args)
    rows = [h for h in db.screening_hits.values() if h["beneficial_owner_id"] == oid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(h) for h in page], limit, offset, total)


@bp.route("/beneficial-owners/<oid>/screen", methods=["POST"])
def screen_beneficial_owner(oid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    ubo = require_found(db.beneficial_owners.get(oid))
    body = get_body()

    outcome = require_enum(body, "outcome", {"CLEARED", "HIT"})

    if outcome == "CLEARED":
        ubo["screening_status"] = "CLEARED"
        db.touch(ubo)
        services.audit("BeneficialOwner", oid, "UBO_SCREENED", user_id, role)
        return object_response(db.public(ubo))

    # HIT: set screening_status=HIT and create a ScreeningHit (PRD §3.4)
    list_type = require_enum(body, "list_type", LIST_TYPES)
    matched_name = require_string(body, "matched_name")
    score = _validate_match_score(require_field(body, "match_score"))

    ubo["screening_status"] = "HIT"
    db.touch(ubo)

    _create_hit(
        customer_id=ubo["customer_id"],
        beneficial_owner_id=oid,
        list_type=list_type,
        matched_name=matched_name,
        match_score=score,
        user_id=user_id,
        role=role,
    )
    services.audit("BeneficialOwner", oid, "UBO_SCREENED", user_id, role)
    return object_response(db.public(ubo))


# ===========================================================================
# Screening hits
# ===========================================================================
def _create_hit(customer_id, beneficial_owner_id, list_type, matched_name,
                match_score, user_id, role):
    base = db.common_create_fields()
    score_num = float(match_score) if match_score != match_score.to_integral_value() else int(match_score)
    hit = {
        **base,
        "customer_id": customer_id,
        "beneficial_owner_id": beneficial_owner_id,
        "list_type": list_type,
        "matched_name": matched_name,
        "match_score": score_num,
        "is_derogatory": list_type in DEROGATORY_LISTS,
        "disposition": "PENDING",
    }
    db.screening_hits[hit["id"]] = hit
    # recompute owning customer gates (PRD §3.4/§3.5/§2.12)
    customer = db.customers.get(customer_id)
    if customer is not None:
        services.recompute_customer_gates(customer)
        db.touch(customer)
    services.audit("ScreeningHit", hit["id"], "HIT_RECORDED", user_id, role)
    return hit


@bp.route("/customers/<cid>/screening-hits", methods=["POST"])
def record_customer_hit(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))
    body = get_body()

    list_type = require_enum(body, "list_type", LIST_TYPES)
    matched_name = require_string(body, "matched_name")
    score = _validate_match_score(require_field(body, "match_score"))

    hit = _create_hit(
        customer_id=cid,
        beneficial_owner_id=None,
        list_type=list_type,
        matched_name=matched_name,
        match_score=score,
        user_id=user_id,
        role=role,
    )
    return object_response(db.public(hit), 201)


@bp.route("/customers/<cid>/screening-hits", methods=["GET"])
def list_customer_hits(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.customers.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [h for h in db.screening_hits.values() if h["customer_id"] == cid]
    disp = request.args.get("disposition")
    if disp is not None:
        rows = [h for h in rows if h["disposition"] == disp]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(h) for h in page], limit, offset, total)


@bp.route("/screening-hits/<hid>/disposition", methods=["POST"])
def disposition_hit(hid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    hit = require_found(db.screening_hits.get(hid))
    body = get_body()

    # priority 21: decision must be in allowed set (PRD §3.5)
    decision = require_field(body, "decision")
    if decision not in {"FALSE_POSITIVE", "ESCALATE", "CONFIRM"}:
        raise err(ERR_INVALID_DECISION, "decision must be FALSE_POSITIVE, ESCALATE, or CONFIRM.")

    customer = db.customers.get(hit["customer_id"])

    if decision == "FALSE_POSITIVE":
        # PENDING -> FALSE_POSITIVE; permitted only when not a confirmable
        # sanctions match: match_score < 0.95 OR list_type in {PEP, ADVERSE_MEDIA}
        if hit["disposition"] != "PENDING":
            raise err(ERR_INVALID_STATE, "FALSE_POSITIVE requires hit in PENDING.")
        # PRD §3.5 + ScreeningHit machine: the FALSE_POSITIVE edge is defined only
        # when match_score < 0.95 OR list_type in {PEP, ADVERSE_MEDIA}. A confirmable
        # sanctions match (derogatory AND score>=0.95) has no FALSE_POSITIVE edge -> ERR_INVALID_STATE.
        confirmable = (
            hit["is_derogatory"] and Decimal(str(hit["match_score"])) >= CONFIRM_FLOOR
        )
        if confirmable:
            raise err(ERR_INVALID_STATE, "FALSE_POSITIVE edge not defined for a confirmable sanctions match.")
        hit["disposition"] = "FALSE_POSITIVE"
        db.touch(hit)
        if customer is not None:
            services.recompute_customer_gates(customer)
            db.touch(customer)
        services.audit("ScreeningHit", hid, "HIT_FALSE_POSITIVE", user_id, role)
        return object_response(db.public(hit))

    if decision == "ESCALATE":
        if hit["disposition"] != "PENDING":
            raise err(ERR_INVALID_STATE, "ESCALATE requires hit in PENDING.")
        hit["disposition"] = "ESCALATED"
        db.touch(hit)
        services.audit("ScreeningHit", hid, "HIT_ESCALATED", user_id, role)
        return object_response(db.public(hit))

    # CONFIRM: ESCALATED -> CONFIRMED
    if hit["disposition"] != "ESCALATED":
        raise err(ERR_INVALID_STATE, "CONFIRM requires hit in ESCALATED.")
    # priority 10: confirmable only when derogatory AND match_score >= 0.95
    if not hit["is_derogatory"] or Decimal(str(hit["match_score"])) < CONFIRM_FLOOR:
        raise err(ERR_HIT_NOT_CONFIRMABLE, "Hit is not derogatory or match_score < 0.95.")

    hit["disposition"] = "CONFIRMED"
    db.touch(hit)
    services.audit("ScreeningHit", hid, "HIT_CONFIRMED", user_id, role)

    # if UBO hit: set that BeneficialOwner.screening_status = HIT (PRD §3.5)
    if hit["beneficial_owner_id"] is not None:
        ubo = db.beneficial_owners.get(hit["beneficial_owner_id"])
        if ubo is not None:
            ubo["screening_status"] = "HIT"
            db.touch(ubo)

    if customer is not None:
        services.recompute_customer_gates(customer)
        customer["edd_required"] = True  # forced true on confirm (PRD §3.5)
        # if APPROVED: drive APPROVED -> EDD_REQUIRED + cascade re-review (PRD §3.5)
        if customer["cdd_status"] == "APPROVED":
            customer["cdd_status"] = "EDD_REQUIRED"
            db.touch(customer)
            services.cascade_reopen_accounts(customer)
            services.audit("Customer", customer["id"], "EDD_REQUIRED", user_id, role)
        else:
            db.touch(customer)

    return object_response(db.public(hit))


@bp.route("/screening-hits/<hid>/reopen", methods=["POST"])
def reopen_hit(hid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    hit = require_found(db.screening_hits.get(hid))

    if hit["disposition"] != "ESCALATED":
        raise err(ERR_INVALID_STATE, "reopen requires hit in ESCALATED.")
    hit["disposition"] = "PENDING"
    db.touch(hit)
    customer = db.customers.get(hit["customer_id"])
    if customer is not None:
        services.recompute_customer_gates(customer)
        db.touch(customer)
    services.audit("ScreeningHit", hid, "HIT_REOPENED", user_id, role)
    return object_response(db.public(hit))
