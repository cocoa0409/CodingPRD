"""Vendor registration, routing guide drafting / requirements / publication,
and the test-driving logical clock."""

from decimal import Decimal

from flask import Blueprint

import lookup
import serializers as ser
from core import (
    ROLE_COMPLIANCE_OFFICER,
    SCOPE_CODES,
    DOMAINS,
    SEVERITY_TIERS,
    ApiError,
    authenticate,
    body_dict,
    clock,
    envelope,
    fmt_dt,
    invalid,
    new_record,
    object_response,
    opt_id,
    req_decimal,
    req_dt,
    req_enum,
    req_int,
    req_str,
    store,
    touch,
)
from derive import recompute_guide_requirement_count, scopes_collide

bp = Blueprint("program", __name__)

OFFICER = (ROLE_COMPLIANCE_OFFICER,)


# ---------------------------------------------------------------------------
# Vendors
# ---------------------------------------------------------------------------


@bp.post("/compliance/vendors")
def create_vendor():
    authenticate(OFFICER)
    body = body_dict()
    vendor_code = req_str(body, "vendor_code", 1, 16, pattern=r"[A-Z0-9]+")
    legal_name = req_str(body, "legal_name", 1, 160)
    payment_terms_days = req_int(body, "payment_terms_days", 1, 120)

    for existing in store.vendors.values():
        if existing["vendor_code"] == vendor_code:
            raise ApiError("ERR_VENDOR_CODE_TAKEN", "Vendor code is already registered.")

    vendor = new_record(
        vendor_code=vendor_code,
        legal_name=legal_name,
        payment_terms_days=payment_terms_days,
        status="ACTIVE",
        otif_score=Decimal("0.00"),
        open_chargeback_cents=0,
        recovered_lifetime_cents=0,
        refund_due_cents=0,
        open_violation_count=0,
        open_cap_count=0,
        repeat_offender_flag=False,
        exposure_alert_flag=False,
    )
    store.vendors[vendor["id"]] = vendor
    return object_response(ser.vendor_out(vendor), 201)


# ---------------------------------------------------------------------------
# Routing guides
# ---------------------------------------------------------------------------


@bp.post("/compliance/routing-guides")
def create_guide():
    authenticate(OFFICER)
    body = body_dict()
    guide_code = req_str(body, "guide_code", 1, 32)
    title = req_str(body, "title", 1, 160)
    scope_code = req_enum(body, "scope_code", SCOPE_CODES)
    effective_from = req_dt(body, "effective_from")
    supersedes_guide_id = opt_id(body, "supersedes_guide_id")

    if supersedes_guide_id is not None:
        lookup.guide(supersedes_guide_id)

    guide = new_record(
        guide_code=guide_code,
        title=title,
        scope_code=scope_code,
        effective_from=effective_from,
        effective_until=None,
        supersedes_guide_id=supersedes_guide_id,
        status="DRAFT",
        requirement_count=0,
        published_at=None,
        published_by_user_id=None,
    )
    store.guides[guide["id"]] = guide
    return object_response(ser.guide_out(guide), 201)


@bp.post("/compliance/routing-guides/<identifier>/requirements")
def create_requirement(identifier):
    authenticate(OFFICER)
    body = body_dict()
    requirement_code = req_str(body, "requirement_code", 1, 32)
    domain = req_enum(body, "domain", DOMAINS)
    severity_tier = req_enum(body, "severity_tier", SEVERITY_TIERS)
    min_evidence_count = req_int(body, "min_evidence_count", 0, 5)
    fixed_fee_cents = req_int(body, "fixed_fee_cents", 0)
    per_unit_recovery_cents = req_int(body, "per_unit_recovery_cents", 0)
    handling_pct = req_decimal(body, "handling_pct", 0, 25)
    min_fee_cents = req_int(body, "min_fee_cents", 0)
    cap_cents = req_int(body, "cap_cents", 1)
    if cap_cents < min_fee_cents:
        raise invalid("Field 'cap_cents' may not be smaller than 'min_fee_cents'.")

    guide = lookup.guide(identifier)
    if guide["status"] != "DRAFT":
        raise ApiError("ERR_GUIDE_NOT_DRAFT", "Requirements may only be added to a DRAFT guide.")

    for existing in store.requirements.values():
        if (
            existing["guide_id"] == guide["id"]
            and existing["requirement_code"] == requirement_code
        ):
            raise ApiError(
                "ERR_REQUIREMENT_CODE_TAKEN",
                "Requirement code is already used within this guide.",
            )

    requirement = new_record(
        guide_id=guide["id"],
        requirement_code=requirement_code,
        domain=domain,
        severity_tier=severity_tier,
        min_evidence_count=min_evidence_count,
        fixed_fee_cents=fixed_fee_cents,
        per_unit_recovery_cents=per_unit_recovery_cents,
        handling_pct=handling_pct,
        min_fee_cents=min_fee_cents,
        cap_cents=cap_cents,
        effective_until=None,
    )
    store.requirements[requirement["id"]] = requirement
    recompute_guide_requirement_count(guide)
    return object_response(ser.requirement_out(requirement), 201)


@bp.post("/compliance/routing-guides/<identifier>/publish")
def publish_guide(identifier):
    user_id, _role = authenticate(OFFICER)
    guide = lookup.guide(identifier)

    if guide["status"] != "DRAFT":
        raise ApiError("ERR_GUIDE_NOT_DRAFT", "Only a DRAFT guide may be published.")
    if guide["requirement_count"] < 1:
        raise ApiError(
            "ERR_GUIDE_HAS_NO_REQUIREMENTS", "A guide must own at least one requirement."
        )
    if guide["effective_from"] <= clock.now():
        raise ApiError(
            "ERR_GUIDE_EFFECTIVE_FROM_IN_PAST",
            "effective_from must be strictly later than the current instant.",
        )

    for other in store.guides.values():
        if other["id"] == guide["id"] or other["status"] != "PUBLISHED":
            continue
        if not scopes_collide(other["scope_code"], guide["scope_code"]):
            continue
        if other["effective_from"] >= guide["effective_from"]:
            raise ApiError(
                "ERR_GUIDE_EFFECTIVE_OVERLAP",
                "A published guide on this scope timeline starts at or after this edition.",
            )

    predecessor = None
    if guide["supersedes_guide_id"] is not None:
        predecessor = lookup.guide(guide["supersedes_guide_id"])
        if predecessor["status"] != "PUBLISHED" or not scopes_collide(
            predecessor["scope_code"], guide["scope_code"]
        ):
            raise ApiError(
                "ERR_GUIDE_EFFECTIVE_OVERLAP",
                "The declared predecessor is not a published guide on this scope timeline.",
            )

    # Cascade link 1.
    guide["status"] = "PUBLISHED"
    guide["published_at"] = clock.now()
    guide["published_by_user_id"] = user_id
    touch(guide)

    if predecessor is not None:
        # Cascade link 2.
        predecessor["status"] = "SUPERSEDED"
        predecessor["effective_until"] = guide["effective_from"]
        touch(predecessor)
        # Cascade link 3.
        for requirement in store.requirements.values():
            if requirement["guide_id"] == predecessor["id"]:
                requirement["effective_until"] = predecessor["effective_until"]
                touch(requirement)

    return object_response(ser.guide_out(guide))


# ---------------------------------------------------------------------------
# Program logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    authenticate(OFFICER)
    body = body_dict()
    instant = req_dt(body, "to_iso8601")
    clock.set(instant)
    return envelope("object", {"current_utc": fmt_dt(clock.now())}), 200
