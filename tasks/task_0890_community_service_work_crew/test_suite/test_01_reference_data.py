"""Reference-data intake: participants, referrals creation/defaults, and the
site / insurance-policy state machines.

Covers Corner queue instances under sections `entities` and `state_machines`.
"""
import pytest
from test_helpers import (
    api_client,
    validate_success, validate_error,
    assert_participant, assert_referral,
    create_participant_payload, create_referral_payload, create_site_payload,
    create_insurance_policy_payload,
    TEST_USERS, NON_EXISTENT_UUID,
)
from test_helpers import fixtures as fx

COORD = TEST_USERS["coordinator_headers"]
CLERK = TEST_USERS["clerk_headers"]


def test_participant_create_returns_201_with_fields(api):
    """PRD §3.2: "A participant is registered separately with a `full_name`, `date_of_birth`, `contact_email`,
    and an optional `risk_level` (one of `LOW`, `MEDIUM`, or `HIGH`, defaulting to `LOW`)."
    PRD §2.4: "an integer `version` that starts at 1 and increments by 1 on every mutation."

    Design: Corner/entities/participant_create_returns_201_with_fields
    """
    res = api.create_participant(
        create_participant_payload(full_name="Pat Doe"), COORD)
    data = validate_success(res, 201)
    assert_participant(data)
    assert data["full_name"] == "Pat Doe"
    assert data["version"] == 1


def test_participant_default_risk_level_low_when_omitted(api):
    """PRD §3.2: "an optional `risk_level` (one of `LOW`, `MEDIUM`, or `HIGH`, defaulting to `LOW`)."

    Design: Corner/entities/participant_default_risk_level_low_when_omitted
    """
    payload = create_participant_payload(full_name="Dee Fault",
                                         contact_email="dee@example.org")
    res = api.create_participant(payload, COORD)
    data = validate_success(res, 201)
    assert data["risk_level"] == "LOW"


def test_referral_default_indigency_none_and_system_status_active(api):
    """PRD §3.2: "an optional `indigency_status` (one of `NONE`, `PARTIAL`, or `FULL`, defaulting to `NONE`)
    that later drives the sliding-scale conversion rate."
    PRD §3.2: "A new referral opens in `ACTIVE` with its ledger initialized: `hours_completed`,
    `hours_converted`, and `fees_settled_cents` at 0, `hours_outstanding` equal to
    `hours_ordered`, `certificate_id` null, and `version` at 1."

    Design: Corner/entities/referral_default_indigency_none_and_system_status_active
    """
    part = fx.new_participant()
    payload = create_referral_payload(part["id"], court_case_number="CR-D1",
                                      offense_class="INFRACTION", hours_ordered=8)
    del payload["indigency_status"]
    res = api.create_referral(payload, CLERK)
    data = validate_success(res, 201)
    assert_referral(data)
    assert data["indigency_status"] == "NONE"
    assert data["status"] == "ACTIVE"
    assert data["hours_outstanding"] == 8


def test_referral_missing_hours_ordered_returns_validation(api):
    """PRD §2.6: "Any hours value supplied as input — `hours_ordered` on a referral, `hours_to_convert` on a
    conversion, an `attested_hours` override on verification — must be strictly positive and
    an exact multiple of 0.25; otherwise the request is rejected with `ERR_VALIDATION` (HTTP
    400)."
    PRD §3.2: "the `hours_ordered` (strictly positive and on the quarter-hour grid)".

    Design: Corner/entities/referral_missing_hours_ordered_returns_validation
    """
    part = fx.new_participant()
    payload = create_referral_payload(part["id"], court_case_number="CR-D2",
                                      offense_class="INFRACTION")
    del payload["hours_ordered"]
    res = api.create_referral(payload, CLERK)
    validate_error(res, "ERR_VALIDATION", 400)


def test_referral_invalid_offense_class_enum_returns_validation(api):
    """PRD §3.2: "the `offense_class` (one of `INFRACTION`, `MISDEMEANOR`, or `FELONY`)".
    PRD §2.9: "body/field validation — enum membership, positivity, the quarter-hour grid, `scheduled_end`
    after `scheduled_start`, `check_out_at` after `check_in_at`, and fee-amount matching —
    else `ERR_VALIDATION`".

    Design: Corner/entities/referral_invalid_offense_class_enum_returns_validation
    """
    part = fx.new_participant()
    payload = create_referral_payload(part["id"], court_case_number="CR-D3",
                                      offense_class="PARKING", hours_ordered=8)
    res = api.create_referral(payload, CLERK)
    validate_error(res, "ERR_VALIDATION", 400)


def test_referral_get_nonexistent_returns_not_found(api):
    """PRD §2.8: "any body-referenced resource that does not exist yields `ERR_NOT_FOUND`."
    PRD §2.9: "existence of all path- and body-referenced resources, left to right, else `ERR_NOT_FOUND`".

    Design: Corner/entities/referral_get_nonexistent_returns_not_found
    """
    res = api.get_referral(NON_EXISTENT_UUID, COORD)
    validate_error(res, "ERR_NOT_FOUND", 404)


def test_pause_prospective_site_returns_invalid_state(api):
    """PRD §3.1: "Pausing a site moves it from `ACCEPTING` to `PAUSED`".
    PRD §2.9: "the generic state check that a resource admits the requested transition, else
    `ERR_INVALID_STATE`".

    Design: Corner/state_machines/pause_prospective_site_returns_invalid_state
    """
    site = validate_success(api.create_site(create_site_payload(), COORD), 201)
    assert site["status"] == "PROSPECTIVE"
    res = api.pause_site(site["id"], COORD)
    validate_error(res, "ERR_INVALID_STATE", 409)


def test_verify_expired_insurance_policy_rejected(api):
    """PRD §3.1: "Verification is only allowed while the policy has not yet expired: if the policy's
    `expiry_date` is at or before the current clock, verification is refused with
    `ERR_INSURANCE_INVALID` (HTTP 409)."

    Design: Corner/state_machines/verify_expired_insurance_policy_rejected
    """
    fx.set_clock("2026-06-01T00:00:00Z")
    site = fx.new_site()
    policy = validate_success(api.create_insurance_policy(
        create_insurance_policy_payload(site["id"], expiry_date="2026-05-15T00:00:00Z"),
        COORD), 201)
    res = api.verify_insurance_policy(policy["id"], COORD)
    validate_error(res, "ERR_INSURANCE_INVALID", 409)
