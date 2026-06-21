"""Customer CRUD, CDD lifecycle, risk assessments (PRD §3.1, §3.2, §3.3)."""

from flask import Blueprint, request

import db
import calculations as calc
import services
from errors import (
    err,
    ERR_TYPE_FIELD_MISMATCH,
    ERR_INVALID_STATE,
    ERR_STALE_VERSION,
    ERR_OPEN_HITS_BLOCK_CLEARANCE,
    ERR_NO_UNAPPLIED_ASSESSMENT,
)
from middleware import authenticate, require_role
from response import object_response, array_response
from validation import (
    get_body,
    require_found,
    require_string,
    require_enum,
    require_country,
    require_int,
    require_field,
    optional_bool,
    parse_pagination,
    sort_and_paginate,
)

bp = Blueprint("customers", __name__)

CUSTOMER_TYPES = {"INDIVIDUAL", "LEGAL_ENTITY"}
READ_ROLES = {"ComplianceOfficer", "Analyst", "QualityReviewer", "PlatformAdmin"}


def _public_customer(c):
    return db.public(c)


# ---------------------------------------------------------------------------
# POST /customers  (ComplianceOfficer, PlatformAdmin)
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["POST"])
def create_customer():
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer", "PlatformAdmin"})
    body = get_body()

    legal_name = require_string(body, "legal_name")
    customer_type = require_enum(body, "customer_type", CUSTOMER_TYPES)
    country_code = require_country(body, "country_code")
    is_pep = optional_bool(body, "is_pep_self_declared", False)

    dob = body.get("date_of_birth")
    inc = body.get("incorporation_date")

    # priority 5: customer_type-conditional fields (PRD §3.1)
    if customer_type == "INDIVIDUAL":
        if dob is None or inc is not None:
            raise err(
                ERR_TYPE_FIELD_MISMATCH,
                "INDIVIDUAL requires date_of_birth and null incorporation_date.",
            )
    else:  # LEGAL_ENTITY
        if inc is None or dob is not None:
            raise err(
                ERR_TYPE_FIELD_MISMATCH,
                "LEGAL_ENTITY requires incorporation_date and null date_of_birth.",
            )

    base = db.common_create_fields()
    customer = {
        **base,
        "legal_name": legal_name,
        "customer_type": customer_type,
        "country_code": country_code,
        "date_of_birth": dob,
        "incorporation_date": inc,
        "is_pep_self_declared": is_pep,
        "cdd_status": "NEW",
        "risk_rating": None,
        "risk_score": None,
        "edd_required": False,
        "periodic_review_due_at": None,
        "open_hit_count": 0,
    }
    db.customers[customer["id"]] = customer
    services.audit("Customer", customer["id"], "CUSTOMER_CREATED", user_id, role)
    return object_response(_public_customer(customer), 201)


# ---------------------------------------------------------------------------
# GET /customers/{id}
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>", methods=["GET"])
def get_customer(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    customer = require_found(db.customers.get(cid))
    return object_response(_public_customer(customer))


# ---------------------------------------------------------------------------
# GET /customers  (filter by cdd_status)
# ---------------------------------------------------------------------------
@bp.route("/customers", methods=["GET"])
def list_customers():
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    limit, offset = parse_pagination(request.args)
    rows = list(db.customers.values())
    cdd_filter = request.args.get("cdd_status")
    if cdd_filter is not None:
        rows = [c for c in rows if c["cdd_status"] == cdd_filter]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([_public_customer(c) for c in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /customers/{id}/risk-assessments  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/risk-assessments", methods=["POST"])
def create_risk_assessment(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))
    body = get_body()

    variant = require_enum(body, "variant", {"PROVISIONAL", "FINAL"})
    geo = require_int(body, "geography_factor", 1, 5)
    prod = require_int(body, "product_factor", 1, 5)
    pep = require_int(body, "pep_factor", 1, 5)
    media = require_int(body, "adverse_media_factor", 1, 5)

    # FINAL variant: +1 to pep_factor (capped 5) when a CONFIRMED derogatory hit
    # exists at compute time, applied BEFORE the weighted formula (PRD §3.2).
    effective_pep = pep
    if variant == "FINAL" and services.has_confirmed_derogatory(cid):
        effective_pep = min(pep + 1, 5)

    total_score, risk_band = calc.risk_scoring(geo, prod, effective_pep, media)

    base = db.common_create_fields()
    assessment = {
        **base,
        "customer_id": cid,
        "variant": variant,
        "geography_factor": geo,
        "product_factor": prod,
        "pep_factor": pep,
        "adverse_media_factor": media,
        "total_score": total_score,
        "risk_band": risk_band,
        "applied": False,
    }
    db.risk_assessments[assessment["id"]] = assessment
    services.audit("RiskAssessment", assessment["id"], "RISK_ASSESSMENT_CREATED", user_id, role)
    return object_response(db.public(assessment), 201)


# ---------------------------------------------------------------------------
# GET /customers/{id}/risk-assessments
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/risk-assessments", methods=["GET"])
def list_risk_assessments(cid):
    user_id, role = authenticate()
    require_role(role, READ_ROLES)
    require_found(db.customers.get(cid))
    limit, offset = parse_pagination(request.args)
    rows = [a for a in db.risk_assessments.values() if a["customer_id"] == cid]
    page, total = sort_and_paginate(rows, limit, offset)
    return array_response([db.public(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------------------
# POST /customers/{id}/apply-rating  (ComplianceOfficer; OCC-guarded)
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/apply-rating", methods=["POST"])
def apply_rating(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))
    body = get_body()

    assessment_id = require_field(body, "risk_assessment_id")
    expected_version = require_field(body, "expected_customer_version")

    # state legality (priority 7) — apply requires NEW (PRD §3.1)
    if customer["cdd_status"] != "NEW":
        raise err(ERR_INVALID_STATE, "apply-rating requires customer in NEW.")

    # OCC (priority 8) — after state check (PRD §2.7, §2.11)
    if expected_version != customer["version"]:
        raise err(ERR_STALE_VERSION, "expected_customer_version mismatch.")

    # priority 24: matching unapplied assessment must exist (PRD §3.1)
    assessment = db.risk_assessments.get(assessment_id)
    if (
        assessment is None
        or assessment["customer_id"] != cid
        or assessment["applied"] is not False
    ):
        raise err(ERR_NO_UNAPPLIED_ASSESSMENT, "No matching unapplied assessment.")

    # Apply (NEW -> RISK_RATED)
    customer["risk_rating"] = assessment["risk_band"]
    customer["risk_score"] = assessment["total_score"]
    assessment["applied"] = True
    db.touch(assessment)
    customer["cdd_status"] = "RISK_RATED"
    services.recompute_customer_gates(customer)
    db.touch(customer)
    services.audit("Customer", cid, "RATING_APPLIED", user_id, role)

    # PROHIBITED -> immediate REJECTED + cascade (PRD §3.1)
    if assessment["risk_band"] == "PROHIBITED":
        customer["cdd_status"] = "REJECTED"
        db.touch(customer)
        services.cascade_block_freeze_accounts(customer)
        services.audit("Customer", cid, "CUSTOMER_REJECTED", user_id, role)

    return object_response(_public_customer(customer))


# ---------------------------------------------------------------------------
# POST /customers/{id}/clear-screening  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/clear-screening", methods=["POST"])
def clear_screening(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))

    # state legality (priority 7)
    if customer["cdd_status"] != "RISK_RATED":
        raise err(ERR_INVALID_STATE, "clear-screening requires customer in RISK_RATED.")

    # priority 9: open hits / prohibited block clearance (PRD §3.1)
    if customer["risk_rating"] == "PROHIBITED" or customer["open_hit_count"] > 0:
        raise err(
            ERR_OPEN_HITS_BLOCK_CLEARANCE,
            "Open derogatory exposure or PROHIBITED rating blocks clearance.",
        )

    # LEGAL_ENTITY: every UBO must be screened (PRD §3.1)
    if customer["customer_type"] == "LEGAL_ENTITY":
        for ubo in db.beneficial_owners.values():
            if ubo["customer_id"] == cid and ubo["screening_status"] == "UNSCREENED":
                raise err(ERR_INVALID_STATE, "All beneficial owners must be screened.")

    customer["cdd_status"] = "SCREENING_CLEARED"
    services.recompute_customer_gates(customer)
    db.touch(customer)
    services.audit("Customer", cid, "SCREENING_CLEARED", user_id, role)
    return object_response(_public_customer(customer))


# ---------------------------------------------------------------------------
# POST /customers/{id}/approve  (ComplianceOfficer) — routes by edd_required
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/approve", methods=["POST"])
def approve(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))

    if customer["cdd_status"] != "SCREENING_CLEARED":
        raise err(ERR_INVALID_STATE, "approve requires customer in SCREENING_CLEARED.")

    if customer["edd_required"]:
        customer["cdd_status"] = "EDD_REQUIRED"
        db.touch(customer)
        services.audit("Customer", cid, "EDD_REQUIRED", user_id, role)
    else:
        customer["cdd_status"] = "APPROVED"
        customer["periodic_review_due_at"] = calc.review_due_at(
            customer["created_at"], customer["risk_rating"]
        )
        db.touch(customer)
        services.cascade_approve_accounts(customer)
        services.audit("Customer", cid, "CUSTOMER_APPROVED", user_id, role)
    return object_response(_public_customer(customer))


# ---------------------------------------------------------------------------
# POST /customers/{id}/complete-edd  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/complete-edd", methods=["POST"])
def complete_edd(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))

    if customer["cdd_status"] != "EDD_REQUIRED":
        raise err(ERR_INVALID_STATE, "complete-edd requires customer in EDD_REQUIRED.")
    if customer["open_hit_count"] != 0:
        raise err(ERR_INVALID_STATE, "complete-edd requires open_hit_count==0.")

    customer["cdd_status"] = "APPROVED"
    customer["periodic_review_due_at"] = calc.review_due_at(
        customer["created_at"], customer["risk_rating"]
    )
    db.touch(customer)
    services.cascade_approve_accounts(customer)
    services.audit("Customer", cid, "EDD_COMPLETED", user_id, role)
    return object_response(_public_customer(customer))


# ---------------------------------------------------------------------------
# POST /customers/{id}/offboard  (ComplianceOfficer)
# ---------------------------------------------------------------------------
@bp.route("/customers/<cid>/offboard", methods=["POST"])
def offboard(cid):
    user_id, role = authenticate()
    require_role(role, {"ComplianceOfficer"})
    customer = require_found(db.customers.get(cid))

    if customer["cdd_status"] != "APPROVED":
        raise err(ERR_INVALID_STATE, "offboard requires customer in APPROVED.")

    customer["cdd_status"] = "OFFBOARDED"
    db.touch(customer)
    services.cascade_block_freeze_accounts(customer)
    services.audit("Customer", cid, "CUSTOMER_OFFBOARDED", user_id, role)
    return object_response(_public_customer(customer))
