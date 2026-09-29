"""Candidate endpoints plus the two nested vetting collections (PRD 3.3)."""

from flask import Blueprint, request

import db
from db import (
    AVAILABILITY_STATUSES,
    BACKGROUND_SCOPE_ITEMS,
    BACKGROUND_STATUSES,
    REFERENCE_STATUSES,
    RELATIONSHIP_TYPES,
    ROLE_TYPES,
    VETTING_STATUSES,
    serialize,
    store,
    touch,
)
from errors import fail
from middleware import (
    AGENCY_PRINCIPAL,
    BILLING_ADMINISTRATOR,
    CANDIDATE,
    CLIENT,
    COMPLIANCE_OFFICER,
    PLACEMENT_CONSULTANT,
    VETTING_SPECIALIST,
    authenticate,
)
from response import created_response, list_response, object_response
from services import calc, domain
from validation import (
    apply_filters,
    body_of,
    check_enum,
    check_enum_list,
    check_int,
    check_month,
    check_non_empty,
    interval_fail,
    list_params,
    require_email,
    require_list,
    require_present,
    require_string,
)
from timeutil import month_index, parse_date

bp = Blueprint("candidates", __name__)


@bp.post("/candidates")
def create_candidate():
    authenticate({VETTING_SPECIALIST, PLACEMENT_CONSULTANT})
    body = body_of(request)

    full_name = require_string(body, "full_name", 1, 120)
    contact_email = require_email(body, "contact_email")
    require_present(body, "primary_role_type", "years_experience")
    primary_role_type = check_enum(body, "primary_role_type", ROLE_TYPES)
    years_experience = check_int(body, "years_experience", minimum=0, maximum=60)
    live_in_willing = body.get("live_in_willing")
    if live_in_willing is None:
        live_in_willing = False
    elif not isinstance(live_in_willing, bool):
        fail("ERR_INVALID_REQUEST", "Field 'live_in_willing' must be a boolean")

    row = {
        "full_name": full_name,
        "contact_email": contact_email,
        "primary_role_type": primary_role_type,
        "years_experience": years_experience,
        "live_in_willing": live_in_willing,
        "vetting_status": "UNVETTED",
        "availability_status": "AVAILABLE",
        "cooling_off_until": None,
        "verified_reference_count": 0,
        "reference_coverage_months": 0,
        "longest_contiguous_months": 0,
        "screening_score": 0,
        "placement_ready_score": 0,
    }
    db.stamp_new(row)
    store.candidates[row["id"]] = row
    return created_response(serialize(row))


@bp.get("/candidates/<candidate_id>")
def get_candidate(candidate_id):
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        BILLING_ADMINISTRATOR, COMPLIANCE_OFFICER, CLIENT, CANDIDATE,
    })
    row = domain.resolve("candidates", candidate_id)
    return object_response(serialize(row))


@bp.get("/candidates")
def list_candidates():
    authenticate({
        AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST,
        COMPLIANCE_OFFICER, CLIENT,
    })
    limit, offset, filters = list_params(
        request,
        enum_filters={
            "primary_role_type": ROLE_TYPES,
            "vetting_status": VETTING_STATUSES,
            "availability_status": AVAILABILITY_STATUSES,
        },
    )
    rows = apply_filters(list(store.candidates.values()), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Reference checks
# ---------------------------------------------------------------------------
@bp.post("/candidates/<candidate_id>/reference-checks")
def create_reference_check(candidate_id):
    user_id, _role = authenticate({VETTING_SPECIALIST})
    body = body_of(request)

    principal_employer_name = require_string(body, "principal_employer_name", 1, 120)
    contact_email = require_email(body, "contact_email")
    require_present(body, "relationship_type", "employment_start_month", "employment_end_month")
    relationship_type = check_enum(body, "relationship_type", RELATIONSHIP_TYPES)
    check_month(body, "employment_start_month")
    check_month(body, "employment_end_month")

    start_index = month_index(body["employment_start_month"])
    end_index = month_index(body["employment_end_month"])
    if end_index < start_index:
        interval_fail("employment_end_month must not precede employment_start_month")

    candidate = domain.resolve("candidates", candidate_id)

    prior = domain.resolve_optional("reference_checks", body.get("prior_reference_id"))
    if prior is not None and prior["candidate_id"] != candidate["id"]:
        fail("ERR_ENTITY_RELATIONSHIP_MISMATCH")

    # Chain continuity is examined before period overlap (PRD 2.11).
    if prior is not None:
        prior_end = month_index(prior["employment_end_month"])
        if prior_end > start_index:
            fail("ERR_REFERENCE_CHAIN_MISMATCH")

    for existing in domain.references_of(candidate["id"]):
        if existing["status"] == "UNREACHABLE":
            continue
        if calc.periods_overlap(
            start_index, end_index,
            month_index(existing["employment_start_month"]),
            month_index(existing["employment_end_month"]),
        ):
            fail("ERR_REFERENCE_PERIOD_OVERLAP")

    row = {
        "candidate_id": candidate["id"],
        "prior_reference_id": prior["id"] if prior is not None else None,
        "principal_employer_name": principal_employer_name,
        "relationship_type": relationship_type,
        "employment_start_month": body["employment_start_month"],
        "employment_end_month": body["employment_end_month"],
        "contact_email": contact_email,
        "status": "PENDING",
        "verification_note": None,
        "created_by_user_id": user_id,
        "verified_by_user_id": None,
    }
    db.stamp_new(row)
    store.reference_checks[row["id"]] = row

    if candidate["vetting_status"] in ("UNVETTED", "REJECTED"):
        candidate["vetting_status"] = "SCREENING"
        touch(candidate)
    domain.recompute_candidate(candidate)

    return created_response(serialize(row))


@bp.get("/candidates/<candidate_id>/reference-checks")
def list_candidate_reference_checks(candidate_id):
    authenticate({AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST, COMPLIANCE_OFFICER})
    limit, offset, filters = list_params(
        request,
        enum_filters={"status": REFERENCE_STATUSES, "relationship_type": RELATIONSHIP_TYPES},
    )
    candidate = domain.resolve("candidates", candidate_id)
    rows = apply_filters(domain.references_of(candidate["id"]), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Background verifications
# ---------------------------------------------------------------------------
@bp.post("/candidates/<candidate_id>/background-verifications")
def create_background_verification(candidate_id):
    authenticate({VETTING_SPECIALIST})
    body = body_of(request)

    provider_reference = require_string(body, "provider_reference", 1, 64)
    scope_items = require_list(body, "scope_items")
    check_enum_list(scope_items, "scope_items", BACKGROUND_SCOPE_ITEMS)
    check_non_empty(scope_items, "scope_items")

    candidate = domain.resolve("candidates", candidate_id)
    if candidate["vetting_status"] != "REFERENCES_VERIFIED":
        fail("ERR_INVALID_STATE_TRANSITION")

    row = {
        "candidate_id": candidate["id"],
        "provider_reference": provider_reference,
        "scope_items": list(scope_items),
        "status": "INITIATED",
        "findings_note": None,
        "rerun_count": 0,
        "recorded_by_user_id": None,
        "adjudicated_by_user_id": None,
        "waiver_note": None,
    }
    db.stamp_new(row)
    store.background_verifications[row["id"]] = row

    candidate["vetting_status"] = "BACKGROUND_PENDING"
    touch(candidate)
    domain.recompute_candidate(candidate)

    return created_response(serialize(row))


@bp.get("/candidates/<candidate_id>/background-verifications")
def list_candidate_background_verifications(candidate_id):
    authenticate({AGENCY_PRINCIPAL, PLACEMENT_CONSULTANT, VETTING_SPECIALIST, COMPLIANCE_OFFICER})
    limit, offset, filters = list_params(request, enum_filters={"status": BACKGROUND_STATUSES})
    candidate = domain.resolve("candidates", candidate_id)
    rows = apply_filters(domain.backgrounds_of(candidate["id"]), filters)
    data, total = domain.page(rows, limit, offset)
    return list_response(data, limit, offset, total)


# ---------------------------------------------------------------------------
# Availability release
# ---------------------------------------------------------------------------
@bp.post("/candidates/<candidate_id>/release-availability")
def release_availability(candidate_id):
    authenticate({VETTING_SPECIALIST, PLACEMENT_CONSULTANT})
    body_of(request)

    candidate = domain.resolve("candidates", candidate_id)
    availability = candidate["availability_status"]
    if availability not in ("COOLING_OFF", "INACTIVE"):
        fail("ERR_INVALID_STATE_TRANSITION")

    if availability == "INACTIVE":
        if candidate["vetting_status"] != "CLEARED":
            fail("ERR_CANDIDATE_NOT_VETTED")
        candidate["availability_status"] = "AVAILABLE"
    else:
        until = parse_date(candidate["cooling_off_until"]) if candidate["cooling_off_until"] else None
        if until is not None and store.today() < until:
            fail("ERR_COOLING_OFF_ACTIVE")
        candidate["availability_status"] = "AVAILABLE"
        candidate["cooling_off_until"] = None

    touch(candidate)
    return object_response(serialize(candidate))
