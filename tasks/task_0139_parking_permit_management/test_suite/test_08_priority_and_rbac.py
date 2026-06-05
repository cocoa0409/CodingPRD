"""Validation ordering, role-based access control, and uniqueness.

PRD §2.9 fixes the validation priority order; §2.1 the RBAC matrix; §3.1/§3.3 the
uniqueness rules.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    build_user_headers,
    setup_garage_with_zone,
    setup_transient_facility,
    create_garage,
    create_motorist,
    create_plate_read,
    issue_citation,
    set_clock,
    open_session,
    make_motorist_headers,
    create_session_payload,
    create_motorist_payload,
    create_zone_payload,
    create_citation_payload,
)

ADMIN = TEST_USERS["facility_admin_headers"]
OFFICER = TEST_USERS["enforcement_officer_headers"]


def test_state_check_beats_validation_temporal_on_exit(api):
    """PRD §2.9: "a state violation surfaces before a capacity or concurrency
    conflict."
    PRD §2.9: "Only after these structural checks pass does the system evaluate
    domain-specific business constraints — zone-type eligibility, uniqueness,
    validation redeemability, event-window well-formedness, stall occupancy, gate
    admission, permit capacity, merchant budget, and finally the
    optimistic-concurrency token."

    An already-CLOSED session presented with an expired validation returns the
    state error, not the validation-redeemability error.

    Design: Difficulty/priority_pair_validation_conflict/state_beats_fiscal_on_session_exit
    """
    from test_helpers import create_merchant, issue_validation
    facility = setup_transient_facility(num_spaces=1, hourly_cents=500, daily_cap_cents=4000,
                                        monthly_permit_cents=9000, grace_minutes=15)
    garage = facility["garage"]
    merchant = create_merchant(garage["id"], validation_budget_cents=10000)
    # Validation already expired (expires before any exit time used below).
    validation = issue_validation(garage["id"], merchant["id"], "FLAT_CENTS", 300,
                                  expires_at_utc="2026-06-01T09:00:00Z")
    set_clock("2026-06-01T10:00:00Z")
    sess = open_session(garage["id"], "PRI111", "2026-06-01T10:00:00Z")
    validate_success(api.exit_session(sess["id"], {"exit_at_utc": "2026-06-01T11:00:00Z"}, ADMIN))
    # Re-exit a CLOSED session with an expired validation: state beats temporal.
    resp = api.exit_session(
        sess["id"], {"exit_at_utc": "2026-06-01T12:00:00Z", "validation_id": validation["id"]}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# RBAC
# ---------------------------------------------------------------------------
def test_motorist_cannot_issue_citation_returns_unauthorized(api):
    """PRD §2.1: "When the headers are well-formed but the declared role is not
    permitted to perform the requested operation, the request is rejected with
    `ERR_UNAUTHORIZED`."

    POST /parking/citations is EnforcementOfficer-exclusive; a Motorist is rejected.

    Design: Corner/roles/motorist_cannot_issue_citation_returns_unauthorized
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    read = create_plate_read(garage["id"], "RBC111", zone["id"], "2026-06-01T08:00:00Z")
    motorist = create_motorist("rbac@x.com", default_plate="RBC111")
    resp = api.create_citation(
        create_citation_payload(garage["id"], "RBC111", read["id"], base_fine_cents=5000),
        make_motorist_headers(motorist["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED.value)


def test_missing_role_header_returns_unauthenticated(api):
    """PRD §2.1: "If either header is missing, or if `X-User-Role` is not one of the
    recognized roles, the request is rejected with `ERR_UNAUTHENTICATED`."

    Design: Corner/roles/missing_auth_headers_returns_unauthenticated
    """
    anon_headers = {"Content-Type": "application/json"}
    resp = api.create_garage({"name": "G"}, anon_headers)
    validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED.value)


def test_motorist_cannot_pay_other_motorists_citation_returns_not_owner(api):
    """PRD §2.1: "When a `Motorist` or a `Merchant` targets a resource they do not
    own, the request is rejected with `ERR_NOT_RESOURCE_OWNER`."
    PRD §2.1: "This applies to a motorist acting on their own permits, waitlist
    entries, appeals, sessions, and to paying their own citations."

    Design: Corner/roles/motorist_cannot_pay_other_motorists_citation_returns_not_owner
    """
    facility = setup_garage_with_zone(zone_type="TRANSIENT", permit_capacity=0)
    garage, zone = facility["garage"], facility["zone"]
    m1 = create_motorist("own1@x.com", default_plate="OWN111")
    m2 = create_motorist("own2@x.com", default_plate="OWN222")
    read = create_plate_read(garage["id"], "OWN111", zone["id"], "2026-06-01T08:00:00Z")
    citation = issue_citation(garage["id"], "OWN111", read["id"], base_fine_cents=5000)
    # m2 (not the owner) tries to pay m1's citation.
    resp = api.pay_citation(
        citation["id"], {"expected_citation_version": citation["version"]},
        make_motorist_headers(m2["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_NOT_RESOURCE_OWNER.value)


# ---------------------------------------------------------------------------
# Uniqueness
# ---------------------------------------------------------------------------
def test_duplicate_motorist_email_returns_duplicate(api):
    """PRD §3.3: "an `email` that must be globally unique (a collision is rejected
    with `ERR_DUPLICATE`)".

    Design: Corner/validations/duplicate_motorist_email_returns_duplicate
    """
    create_motorist("dup@x.com", full_name="M1", default_plate="DUP001")
    resp = api.create_motorist(
        create_motorist_payload("dup@x.com", full_name="M2", default_plate="DUP002"), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)


def test_duplicate_zone_code_within_garage_returns_duplicate(api):
    """PRD §3.1: "Creating a zone whose `code` collides with an existing zone in the
    same garage is rejected with `ERR_DUPLICATE`."

    Design: Corner/validations/duplicate_zone_code_within_garage_returns_duplicate
    """
    facility = setup_garage_with_zone(zone_type="MIXED", permit_capacity=5,
                                      zone_overrides={"code": "A"})
    garage, rate_plan = facility["garage"], facility["rate_plan"]
    resp = api.create_zone(
        create_zone_payload(garage["id"], rate_plan["id"], code="A",
                            zone_type="TRANSIENT", permit_capacity=0), ADMIN)
    validate_error(resp, ApiErrorId.ERR_DUPLICATE.value)
