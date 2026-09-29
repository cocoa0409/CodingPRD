"""Delivery partners, risk assessment, couriers and courier certifications."""
from decimal import Decimal

from flask import Blueprint, g

from db import (
    CERT_MIN_TRAINING_SCORE,
    CERT_REMEDIAL_TRAINING_SCORE,
    RESTRICTION_CLASSES,
    TIER_MULTIPLIER,
    TRAINING_FRESHNESS_DAYS,
    db,
    new_row,
    now,
    now_str,
    sort_key,
    touch,
)
from errors import ApiError
from middleware import (
    COMPLIANCE_OFFICER,
    COURIER,
    PARTNER_MANAGER,
    PLATFORM_ADMIN,
    auth,
    fetch,
    scope_check,
    scope_if,
)
from response import created, listing, ok, pagination, public
from services.parties import (
    abort_open_attempts,
    partner_scores,
    rederive_courier_gates,
)
from util import add_days, date_midnight, fmt_dt, parse_date, parse_dt

import validate as v

bp = Blueprint("partners", __name__)

CONTRACT_TIERS = ("STANDARD", "PREFERRED", "PROBATIONARY")
POSTURES = ("OPEN", "RESTRICTED", "SUSPENDED")
CERT_STATES = ("ACTIVE", "EXPIRED", "SUSPENDED", "REVOKED")
COURIER_CERT_STATES = ("UNCERTIFIED", "CERTIFIED", "SUSPENDED")


# ---------------------------------------------------------------------------
# Delivery partners
# ---------------------------------------------------------------------------
@bp.post("/delivery-partners")
def create_partner():
    auth(PLATFORM_ADMIN)
    body = v.body()
    legal_name = v.req_str(body, "legal_name")
    contract_tier = v.req_enum(body, "contract_tier", CONTRACT_TIERS)
    license_reference = v.req_str(body, "license_reference")
    for existing in db.partners.values():
        if existing["license_reference"] == license_reference:
            raise ApiError("ERR_DUPLICATE_CODE", "license_reference is already in use")
    row = new_row(
        legal_name=legal_name,
        contract_tier=contract_tier,
        license_reference=license_reference,
        license_risk_score=Decimal("0.00"),
        lifetime_risk_score=Decimal("0.00"),
        open_case_count=0,
        open_critical_case_count=0,
        posture="OPEN",
    )
    db.partners[row["id"]] = row
    return created(public(row))


@bp.get("/delivery-partners/<partner_id>")
def get_partner(partner_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    scope_if(PARTNER_MANAGER, partner_id)
    return ok(public(fetch("partners", partner_id)))


@bp.get("/delivery-partners")
def list_partners():
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER)
    posture = v.enum_filter("posture", POSTURES)
    contract_tier = v.enum_filter("contract_tier", CONTRACT_TIERS)
    limit, offset = pagination()
    rows = list(db.partners.values())
    if posture is not None:
        rows = [r for r in rows if r["posture"] == posture]
    if contract_tier is not None:
        rows = [r for r in rows if r["contract_tier"] == contract_tier]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


@bp.get("/delivery-partners/<partner_id>/risk-assessment")
def risk_assessment(partner_id):
    """Non-mutating replay of both risk variants against the current clock."""
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    scope_if(PARTNER_MANAGER, partner_id)
    partner = fetch("partners", partner_id)
    clock = now()
    rolling, lifetime, terms, tier = partner_scores(partner, clock)
    breakdown = []
    for term in terms:
        case = term["case"]
        breakdown.append({
            "violation_case_id": case["id"],
            "assessed_severity": case["assessed_severity"],
            "decided_at": case["decided_at"],
            "age_days": term["age_days"],
            "included_in_rolling": term["included_in_rolling"],
            "rolling_points": term["rolling_points"],
            "lifetime_weight": term["lifetime_weight"],
            "lifetime_points": term["lifetime_points"],
        })
    return ok({
        "delivery_partner_id": partner["id"],
        "evaluated_at": fmt_dt(clock),
        "contract_tier": partner["contract_tier"],
        "tier_multiplier": tier,
        "rolling_90d_score": rolling,
        "lifetime_weighted_score": lifetime,
        "open_case_count": partner["open_case_count"],
        "open_critical_case_count": partner["open_critical_case_count"],
        "posture": partner["posture"],
        "case_breakdown": breakdown,
    })


# ---------------------------------------------------------------------------
# Couriers
# ---------------------------------------------------------------------------
@bp.post("/couriers")
def create_courier():
    user_id, role = auth(PARTNER_MANAGER)
    body = v.body()
    partner_id = body.get("delivery_partner_id")
    if isinstance(partner_id, str) and partner_id.strip() != "":
        scope_check(partner_id)
    else:
        raise ApiError("ERR_VALIDATION", "delivery_partner_id is required")
    fetch("partners", partner_id)
    full_name = v.req_str(body, "full_name")
    hired_at = v.req_date(body, "hired_at")
    row = new_row(
        delivery_partner_id=partner_id,
        full_name=full_name,
        hired_at=hired_at.isoformat(),
        compliance_score=Decimal("100.00"),
        compliant_handover_count=0,
        certification_state="UNCERTIFIED",
        dispatch_eligible=False,
    )
    db.couriers[row["id"]] = row
    return created(public(row))


@bp.get("/couriers/<courier_id>")
def get_courier(courier_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    courier = fetch("couriers", courier_id)
    scope_if(PARTNER_MANAGER, courier["delivery_partner_id"])
    return ok(public(courier))


@bp.get("/couriers")
def list_couriers():
    user_id, role = auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER)
    partner_filter = v.str_filter("delivery_partner_id")
    certification_state = v.enum_filter("certification_state", COURIER_CERT_STATES)
    dispatch_eligible = v.bool_filter("dispatch_eligible")
    limit, offset = pagination()
    if role == PARTNER_MANAGER:
        if partner_filter is not None and partner_filter != user_id:
            raise ApiError("ERR_FORBIDDEN_RESOURCE_SCOPE")
        partner_filter = user_id
    rows = list(db.couriers.values())
    if partner_filter is not None:
        rows = [r for r in rows if r["delivery_partner_id"] == partner_filter]
    if certification_state is not None:
        rows = [r for r in rows if r["certification_state"] == certification_state]
    if dispatch_eligible is not None:
        rows = [r for r in rows if r["dispatch_eligible"] == dispatch_eligible]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


# ---------------------------------------------------------------------------
# Courier certifications
# ---------------------------------------------------------------------------
@bp.post("/courier-certifications")
def issue_certification():
    auth(PARTNER_MANAGER)
    body = v.body()
    courier_id = body.get("courier_id")
    if not isinstance(courier_id, str) or courier_id.strip() == "":
        raise ApiError("ERR_VALIDATION", "courier_id is required")
    courier = fetch("couriers", courier_id)
    scope_check(courier["delivery_partner_id"])
    restriction_type = v.req_enum(body, "restriction_type", RESTRICTION_CLASSES)
    training_score = v.req_int(body, "training_score", 0, 100)
    training_completed_at = v.req_date(body, "training_completed_at")
    valid_days = v.req_int(body, "valid_days", 30, 1095)
    if training_score < CERT_MIN_TRAINING_SCORE:
        raise ApiError("ERR_TRAINING_SCORE_TOO_LOW")
    issued = now()
    row = new_row(
        courier_id=courier_id,
        restriction_type=restriction_type,
        training_score=training_score,
        training_completed_at=training_completed_at.isoformat(),
        valid_days=valid_days,
        issued_at=fmt_dt(issued),
        expires_at=fmt_dt(add_days(issued, valid_days)),
        renewal_count=0,
        state="ACTIVE",
        revocation_reason=None,
    )
    db.certifications[row["id"]] = row
    rederive_courier_gates(courier)
    return created(public(row))


@bp.get("/courier-certifications/<certification_id>")
def get_certification(certification_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    certification = fetch("certifications", certification_id)
    courier = db.couriers.get(certification["courier_id"])
    if courier is not None:
        scope_if(PARTNER_MANAGER, courier["delivery_partner_id"])
    return ok(public(certification))


@bp.get("/couriers/<courier_id>/certifications")
def list_courier_certifications(courier_id):
    auth(PLATFORM_ADMIN, COMPLIANCE_OFFICER, PARTNER_MANAGER, COURIER)
    courier = fetch("couriers", courier_id)
    scope_if(PARTNER_MANAGER, courier["delivery_partner_id"])
    state = v.enum_filter("state", CERT_STATES)
    restriction_type = v.enum_filter("restriction_type", RESTRICTION_CLASSES)
    limit, offset = pagination()
    rows = [c for c in db.certifications.values() if c["courier_id"] == courier_id]
    if state is not None:
        rows = [r for r in rows if r["state"] == state]
    if restriction_type is not None:
        rows = [r for r in rows if r["restriction_type"] == restriction_type]
    rows.sort(key=sort_key)
    return listing(rows, limit, offset)


@bp.post("/courier-certifications/<certification_id>/renew")
def renew_certification(certification_id):
    auth(PARTNER_MANAGER)
    certification = fetch("certifications", certification_id)
    courier = db.couriers.get(certification["courier_id"])
    if courier is not None:
        scope_check(courier["delivery_partner_id"])
    body = v.body()
    training_score = v.req_int(body, "training_score", 0, 100)
    training_completed_at = v.req_date(body, "training_completed_at")
    valid_days = v.req_int(body, "valid_days", 30, 1095)

    state = certification["state"]
    if state == "EXPIRED":
        bar = CERT_MIN_TRAINING_SCORE
    elif state == "SUSPENDED":
        bar = CERT_REMEDIAL_TRAINING_SCORE
    else:
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")
    if training_score < bar:
        raise ApiError("ERR_TRAINING_SCORE_TOO_LOW")
    clock = now()
    if (clock - date_midnight(training_completed_at)).total_seconds() > TRAINING_FRESHNESS_DAYS * 86400:
        raise ApiError("ERR_TRAINING_STALE")

    certification["training_score"] = training_score
    certification["training_completed_at"] = training_completed_at.isoformat()
    certification["valid_days"] = valid_days
    certification["issued_at"] = fmt_dt(clock)
    certification["expires_at"] = fmt_dt(add_days(clock, valid_days))
    certification["renewal_count"] += 1
    certification["state"] = "ACTIVE"
    certification["revocation_reason"] = None
    touch(certification)
    if courier is not None:
        rederive_courier_gates(courier)
    return ok(public(certification))


@bp.post("/courier-certifications/<certification_id>/revoke")
def revoke_certification(certification_id):
    auth(COMPLIANCE_OFFICER)
    certification = fetch("certifications", certification_id)
    body = v.body()
    reason = v.req_str(body, "revocation_reason")
    if certification["state"] == "REVOKED":
        raise ApiError("ERR_INVALID_CERTIFICATION_STATE")
    certification["state"] = "REVOKED"
    certification["revocation_reason"] = reason
    touch(certification)
    courier = db.couriers.get(certification["courier_id"])
    if courier is not None:
        abort_open_attempts(courier, "CERTIFICATION_SUSPENDED")
        rederive_courier_gates(courier)
    return ok(public(certification))
