"""Fleet onboarding, uniqueness constraints, and entry-point access control."""
import pytest

from test_helpers import (
    validate_success, validate_error, build_user_headers,
    create_aircraft_payload, create_owner_payload, create_agreement_payload,
    setup_owner_and_aircraft, setup_pending_agreement,
    UNKNOWN_UUID, TEST_USERS,
)

AE = TEST_USERS["account_executive_headers"]


def test_aircraft_create_missing_tail_number_rejected(api):
    """PRD §3.1: "The same role then registers airframes under that owner, each
    registration carrying the owning `owner_id`, the `tail_number`, the `model`
    designation, and the `home_base_icao` of its home airport."
    PRD §2.8: "Fourth, request schema is enforced: required fields present,
    enum values valid, ISO dates parseable, `amount_cents` strictly greater than
    zero, `block_hours_est` strictly greater than zero, rates non-negative,
    `duty_start_at` strictly earlier than `duty_end_at`, `term_start` strictly
    earlier than `term_end`, and `period` matching the YYYY-MM shape; violations
    yield `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/entities/aircraft_create_missing_required_tail_number
    """
    owner, _aircraft = setup_owner_and_aircraft(tail_number="N210AA")
    payload = {
        "owner_id": owner["id"],
        "model": "G650",
        "home_base_icao": "KTEB",
    }
    res = api.create_aircraft(payload, AE)
    validate_error(res, "ERR_VALIDATION", expected_status=400)


def test_aircraft_get_nonexistent_returns_not_found(api):
    """PRD §2.8: "Third, every path identifier and every body-supplied
    foreign-key reference — `owner_id`, `aircraft_id`, `trip_id`,
    `crew_member_id`, the entries of `record_ids`, and so on — must resolve to
    an existing resource, validated left-to-right along the path; any unresolved
    reference yields `ERR_NOT_FOUND` (HTTP 404)."

    Design: Corner/entities/aircraft_get_nonexistent_returns_not_found
    """
    res = api.get_aircraft(UNKNOWN_UUID, AE)
    validate_error(res, "ERR_NOT_FOUND", expected_status=404)


def test_duplicate_tail_number_rejected(api):
    """PRD §3.1: "The `tail_number` must be unique across every registered
    aircraft; a duplicate is rejected with `ERR_TAIL_NUMBER_EXISTS`."

    Design: Corner/validations/duplicate_tail_number_rejected
    """
    owner, _aircraft = setup_owner_and_aircraft(tail_number="N360JX")
    owner2 = validate_success(
        api.create_owner(
            create_owner_payload(
                legal_name="Borealis Aviation Inc",
                contact_email="ops@borealis.example",
            ),
            AE,
        ),
        201,
    )
    res = api.create_aircraft(
        create_aircraft_payload(
            owner2["id"], tail_number="N360JX", model="G550", home_base_icao="KPDK"
        ),
        AE,
    )
    validate_error(res, "ERR_TAIL_NUMBER_EXISTS", expected_status=409)


def test_second_live_agreement_rejected(api):
    """PRD §3.1: "At most one agreement per aircraft may be live — that is, in
    `PENDING`, `ACTIVE`, `TERMINATION_PENDING`, or `HANDOVER_IN_PROGRESS`;
    attempting to create a second live agreement for the same aircraft is
    rejected with `ERR_AGREEMENT_CONFLICT_EXISTS`."

    Design: Corner/validations/agreement_conflict_exists_rejected
    """
    scenario = setup_pending_agreement(tail_number="N410JX")
    owner = scenario["owner"]
    aircraft = scenario["aircraft"]
    res = api.create_agreement(
        create_agreement_payload(
            owner["id"],
            aircraft["id"],
            monthly_management_fee_cents=600000,
            variable_fee_pct=0.12,
            charter_owner_share_pct=0.80,
            tax_allocation_method="TRIP_LEGS",
        ),
        AE,
    )
    validate_error(res, "ERR_AGREEMENT_CONFLICT_EXISTS", expected_status=409)


def test_owners_create_with_undeclared_role_rejected(api):
    """PRD §2.1: "Every API request must carry two HTTP headers: `X-User-ID`
    and `X-User-Role`. If either header is absent, or if the role value is not
    one of the declared roles below, the request is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

    Design: Corner/validations/owners_create_missing_auth_headers
    """
    bogus_headers = build_user_headers("test-bogus-1", "NoSuchRole")
    res = api.create_owner(create_owner_payload(), bogus_headers)
    validate_error(
        res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400
    )


def test_platform_admin_cannot_onboard_owner(api, platform_admin_headers):
    """PRD §2.1: "When the acting role is not listed among an endpoint's
    authorized roles, the request is rejected with `ERR_FORBIDDEN_ROLE`
    (HTTP 403)."
    PRD §4: POST /owners is authorized for AccountExecutive only.

    Design: Corner/rbac/platform_admin_cannot_onboard_owner
    """
    res = api.create_owner(create_owner_payload(), platform_admin_headers)
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)
