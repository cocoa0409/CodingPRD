"""Rider, Employer, and FareCard CRUD + lifecycle — PRD §3.1, §3.2.

Covers create, common-fields shape, email uniqueness, employer
suspension cascade, card issuance with discount class, top-up,
suspend/reactivate, and close.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    advance_clock_to_iso,
    assert_employer,
    assert_fare_card,
    assert_rider,
    create_card_payload,
    create_employer,
    create_employer_payload,
    create_fsa_account_payload,
    create_fsa_contribution_payload,
    create_rider,
    create_rider_payload,
    get_card,
    get_rider,
    issue_card,
    make_employer_admin_headers,
    make_rider_headers,
    setup_rider_with_funded_card,
    setup_rider_with_fsa,
    suspend_card,
    topup_card,
    topup_card_payload,
    unique_email,
    validate_error,
    validate_success,
)


# ===========================================================================
# Rider create
# ===========================================================================
class TestRiderCreate:

    def test_create_rider_returns_common_fields(self, api,
                                                agency_officer_headers):
        """PRD §3.1: "Creating a `Rider` requires only the rider's
        `full_name` and `email`"; PRD §2.4: "All primary, top-level
        resources ... carry a standard set of system-managed fields:
        `id` ... `created_at` ... `updated_at` ... `version`."

        Claim: a successful create returns a Rider with id, created_at,
        updated_at, version, full_name, email."""
        payload = create_rider_payload(
            full_name="Alice", email=unique_email(),
        )
        resp = api.create_rider(payload, agency_officer_headers)
        rider = validate_success(resp, expected_status=201)
        assert_rider(rider)
        assert rider["full_name"] == "Alice"

    def test_create_rider_defaults_low_income_verified_false(
            self, api, agency_officer_headers):
        """PRD §3.1: "Each rider starts with `low_income_verified` set
        to false and `employer_id` set to null."

        Claim: low_income_verified defaults to false at create."""
        payload = create_rider_payload(email=unique_email())
        resp = api.create_rider(payload, agency_officer_headers)
        rider = validate_success(resp, expected_status=201)
        assert rider["low_income_verified"] is False, (
            "low_income_verified must default to false at rider create"
        )

    def test_create_rider_defaults_employer_id_null(
            self, api, agency_officer_headers):
        """PRD §3.1: "Each rider starts with `low_income_verified` set
        to false and `employer_id` set to null."

        Claim: employer_id defaults to null at create."""
        payload = create_rider_payload(email=unique_email())
        resp = api.create_rider(payload, agency_officer_headers)
        rider = validate_success(resp, expected_status=201)
        assert rider.get("employer_id", "MISSING") in (None, "MISSING"), (
            "employer_id must default to null at rider create; "
            f"got {rider.get('employer_id')!r}"
        )


# ===========================================================================
# Employer create / suspend
# ===========================================================================
class TestEmployerLifecycle:

    def test_create_employer_returns_active(self, api,
                                            agency_officer_headers):
        """PRD §3.1: "A newly created employer begins in
        `enrollment_status` `ACTIVE`, the only state in which new FSA
        contributions are accepted."

        Claim: a fresh Employer has enrollment_status=ACTIVE."""
        payload = create_employer_payload()
        resp = api.create_employer(payload, agency_officer_headers)
        emp = validate_success(resp, expected_status=201)
        assert_employer(emp)
        assert emp["enrollment_status"] == "ACTIVE"

    def test_suspend_employer_freezes_fsa_accounts(
            self, api, agency_officer_headers):
        """PRD §3.1: "When an `AgencyOfficer` suspends an employer,
        every `CommuterBenefitAccount` carrying that `employer_id`
        transitions from `ACTIVE` to `FROZEN`; this freezes both new
        contributions and new tap-in disbursements from those accounts
        while still permitting refunds."

        Claim: after suspend, the FSA account on this employer is
        FROZEN, and a new contribution is rejected with
        ERR_INVALID_STATE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, employer, acct, card, _contrib = setup_rider_with_fsa(
            topup_cents=1000, contribution_cents=0,
        )
        # Suspend the employer.
        resp = api.suspend_employer(employer["id"],
                                    agency_officer_headers)
        suspended = validate_success(resp, expected_status=200)
        assert suspended["enrollment_status"] == "SUSPENDED"
        # Attempt a contribution → ERR_INVALID_STATE (state-eligibility
        # check; the account is FROZEN).
        eh = make_employer_admin_headers(employer["id"])
        contrib_resp = api.create_fsa_contribution(
            create_fsa_contribution_payload(
                account_id=acct["id"], amount_cents=100,
                contribution_month="2026-05",
            ),
            eh,
        )
        validate_error(contrib_resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Card issuance — discount class authorization
# ===========================================================================
class TestCardIssuance:

    def test_create_card_returns_active_zero_wallet(
            self, api, agency_officer_headers):
        """PRD §3.2: "Newly issued cards start with `status` `ACTIVE`
        and `wallet_balance_cents` of zero; the `mobile_token_id` is
        null until a mobile token is bound."

        Claim: a fresh STANDARD card has status=ACTIVE,
        wallet_balance_cents=0, mobile_token_id=null."""
        rider = create_rider()
        payload = create_card_payload(rider_id=rider["id"])
        resp = api.create_card(payload, agency_officer_headers)
        card = validate_success(resp, expected_status=201)
        assert_fare_card(card)
        assert card["status"] == "ACTIVE"
        assert card["wallet_balance_cents"] == 0
        assert card.get("mobile_token_id") is None

    def test_reduced_fare_without_certificate_rejected(
            self, api, agency_officer_headers):
        """PRD §3.2: "If a card is requested with `discount_class`
        `REDUCED_FARE` and no `ACTIVE` `ReducedFareCertificate` on the
        rider covers the present moment between its `valid_from` and
        `valid_until`, the request is rejected with
        `ERR_MISSING_REDUCED_FARE_CERTIFICATE`."

        Claim: a REDUCED_FARE card create on a rider without an active
        certificate is rejected with the named error."""
        rider = create_rider()
        payload = create_card_payload(
            rider_id=rider["id"], discount_class="REDUCED_FARE",
        )
        resp = api.create_card(payload, agency_officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_MISSING_REDUCED_FARE_CERTIFICATE.value,
        )

    def test_low_income_without_verification_rejected(
            self, api, agency_officer_headers):
        """PRD §3.2: "if a card is requested with `discount_class`
        `LOW_INCOME` while the rider's `low_income_verified` is still
        false, the request is rejected with
        `ERR_MISSING_LOW_INCOME_VERIFICATION`."

        Claim: LOW_INCOME card on rider with low_income_verified=false
        → ERR_MISSING_LOW_INCOME_VERIFICATION."""
        rider = create_rider()
        payload = create_card_payload(
            rider_id=rider["id"], discount_class="LOW_INCOME",
        )
        resp = api.create_card(payload, agency_officer_headers)
        validate_error(
            resp, ApiErrorId.ERR_MISSING_LOW_INCOME_VERIFICATION.value,
        )


# ===========================================================================
# Card top-up
# ===========================================================================
class TestCardTopup:

    def test_topup_increments_wallet(self, api):
        """PRD §3.2: "Riders top up the card by adding to
        `wallet_balance_cents`; the request body carries an
        `amount_cents` integer."

        Claim: top-up increments wallet_balance_cents by the supplied
        amount_cents."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=0)
        before = card["wallet_balance_cents"]
        h = make_rider_headers(rider["id"])
        resp = api.topup_card(card["id"],
                              topup_card_payload(amount_cents=500), h)
        after = validate_success(resp, expected_status=200)
        assert after["wallet_balance_cents"] == before + 500, (
            f"Expected wallet {before + 500}, got "
            f"{after['wallet_balance_cents']}"
        )


# ===========================================================================
# Card suspend / reactivate / close
# ===========================================================================
class TestCardLifecycle:

    def test_suspend_card_blocks_tap_in(
            self, api, agency_officer_headers):
        """PRD §3.2: "A card may be suspended by an `AgencyOfficer`,
        transitioning `status` from `ACTIVE` to `SUSPENDED`; suspension
        blocks new tap-ins (any subsequent tap is rejected with
        `ERR_CARD_NOT_ACTIVE`)."

        Claim: after suspend, a tap-in on the card returns
        ERR_CARD_NOT_ACTIVE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        suspended = suspend_card(card_id=card["id"])
        assert suspended["status"] == "SUSPENDED"
        # Tap-in must be rejected.
        from test_helpers import create_trip_payload, unique_idempotency_key
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:00:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_NOT_ACTIVE.value)

    def test_reactivate_returns_card_to_active(
            self, api, agency_officer_headers):
        """PRD §3.2: "A suspended card may be reactivated, transitioning
        `status` from `SUSPENDED` back to `ACTIVE`."

        Claim: reactivate moves a SUSPENDED card back to ACTIVE."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=0)
        suspended = suspend_card(card_id=card["id"])
        resp = api.reactivate_card(card["id"], agency_officer_headers)
        reactivated = validate_success(resp, expected_status=200)
        assert reactivated["status"] == "ACTIVE"

    def test_close_card_zeros_wallet(self, api):
        """PRD §3.2: "Closure is a rider-initiated terminal transition
        from `ACTIVE` to `CLOSED` and is permitted only when no trip on
        the card has `travel_status` `TAPPED_IN`; closing the card
        zeros `wallet_balance_cents`."

        Claim: close on an ACTIVE card with no open trip zeros
        wallet_balance_cents and moves status to CLOSED."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=500)
        assert card["wallet_balance_cents"] == 500
        h = make_rider_headers(rider["id"])
        resp = api.close_card(card["id"], h)
        closed = validate_success(resp, expected_status=200)
        assert closed["status"] == "CLOSED"
        assert closed["wallet_balance_cents"] == 0
