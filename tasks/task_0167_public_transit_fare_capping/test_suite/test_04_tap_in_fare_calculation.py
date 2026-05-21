"""Tap-in mechanics and provisional fare calculation — PRD §3.5.

Covers per-discount base fares (STANDARD 275, REDUCED_FARE 138,
LOW_INCOME 165), fallback when low_income_verified is false,
duplicate tap idempotency, second-trip-while-open conflict, card
validity window, and the basic side-effects on wallet and FSA.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    BASE_FARE_CENTS,
    LOW_INCOME_BASE_CENTS,
    REDUCED_FARE_BASE_CENTS,
    advance_clock_to_iso,
    assert_trip,
    create_card_payload,
    create_rider,
    create_trip_payload,
    issue_card,
    make_rider_headers,
    setup_rider_with_funded_card,
    setup_rider_with_low_income_card,
    setup_rider_with_reduced_fare_card,
    tap_in,
    unique_idempotency_key,
    validate_error,
    validate_success,
)


# ===========================================================================
# Per-discount-class base fare at tap-in
# ===========================================================================
class TestProvisionalBaseFare:

    def test_standard_card_charges_275_cents(self, api):
        """PRD §3.5: "for `STANDARD` cards it is the configured base
        fare of 275 cents".

        Claim: a STANDARD card's first tap-in charges
        provisional_fare_cents=275."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(
            topup_cents=1000, discount_class="STANDARD",
        )
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert_trip(trip)
        assert trip["provisional_fare_cents"] == BASE_FARE_CENTS, (
            f"Expected provisional_fare_cents=275, got "
            f"{trip['provisional_fare_cents']}"
        )

    def test_reduced_fare_card_charges_138_cents(self, api):
        """PRD §3.5: "for `REDUCED_FARE` cards it is the base fare
        multiplied by 0.50, rounded half-up to the nearest whole cent
        (so 275 times 0.50 is 137.5, which rounds to 138 cents)".

        Claim: REDUCED_FARE tap-in charges provisional_fare_cents=138
        (round_half_up(275*0.5) = 138)."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, _cert, card = setup_rider_with_reduced_fare_card(
            topup_cents=1000,
        )
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert trip["provisional_fare_cents"] == REDUCED_FARE_BASE_CENTS, (
            f"Expected provisional_fare_cents=138, got "
            f"{trip['provisional_fare_cents']}"
        )

    def test_low_income_card_charges_165_cents(self, api):
        """PRD §3.5: "for `LOW_INCOME` cards it is the base fare
        multiplied by 0.60, rounded half-up (so 275 times 0.60 is 165
        cents)".

        Claim: LOW_INCOME tap-in with low_income_verified=true charges
        provisional_fare_cents=165."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, _v, card = setup_rider_with_low_income_card(
            topup_cents=1000,
        )
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert trip["provisional_fare_cents"] == LOW_INCOME_BASE_CENTS, (
            f"Expected provisional_fare_cents=165, got "
            f"{trip['provisional_fare_cents']}"
        )


# ===========================================================================
# Tap-in validations
# ===========================================================================
class TestTapInValidations:

    def test_duplicate_idempotency_returns_original_trip(self, api):
        """PRD §3.5: "a second tap-in carrying the same pair returns
        the original `Trip` resource with no new debit".

        Claim: two tap-ins with the same (card_id, idempotency_key)
        return the same Trip id and do NOT double-charge the wallet."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        rh = make_rider_headers(rider["id"])
        key = unique_idempotency_key()
        payload = create_trip_payload(
            card_id=card["id"], idempotency_key=key,
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        r1 = api.create_trip(payload, rh)
        t1 = validate_success(r1, expected_status=201)
        r2 = api.create_trip(payload, rh)
        # PRD §3.5: idempotent re-tap returns the same Trip with no new
        # debit. The two-reader test permits the implementation to use
        # either 201 or 200 — but the returned id MUST match and the
        # wallet MUST NOT be debited twice.
        assert 200 <= r2.status_code < 300, (
            f"Idempotent retry must succeed; got {r2.status_code}"
        )
        body = r2.json()
        t2 = body.get("data", body)
        assert t2.get("id") == t1["id"], (
            f"Idempotent retry must return original Trip id "
            f"{t1['id']}, got {t2.get('id')}"
        )
        # Inspect the card after — wallet must reflect one (not two) charges.
        from test_helpers import get_card
        card_after = get_card(card["id"])
        assert card_after["wallet_balance_cents"] == (
            card["wallet_balance_cents"] - t1["provisional_fare_cents"]
        ), (
            "Wallet must be debited exactly once for duplicate tap "
            "(card_id, idempotency_key); got "
            f"wallet={card_after['wallet_balance_cents']}"
        )

    def test_second_tap_in_while_first_open_rejected(self, api):
        """PRD §3.5: "no other trip on this card has `travel_status`
        `TAPPED_IN` (concurrent attempts serialise first-writer-wins on
        `Trip.travel_status` equal to `TAPPED_IN`, with the loser
        receiving `ERR_TRIP_ALREADY_OPEN`)".

        Claim: a tap-in on a card with an in-flight TAPPED_IN trip
        receives ERR_TRIP_ALREADY_OPEN."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        # First tap-in, NO tap-out.
        tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        # Second tap-in must be rejected.
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:30:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_TRIP_ALREADY_OPEN.value)

    def test_tap_in_outside_card_validity_rejected(self, api):
        """PRD §3.5 + §2.11: tap-in checks "that `tap_in_at` lies
        within the card's `[valid_from, valid_until]` window (otherwise
        `ERR_CARD_OUTSIDE_VALIDITY`)".

        Claim: a tap_in_at strictly before card.valid_from is rejected
        with ERR_CARD_OUTSIDE_VALIDITY."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(
            topup_cents=1000,
            valid_from="2026-06-01T00:00:00.000Z",
            valid_until="2026-12-31T23:59:59.000Z",
        )
        rh = make_rider_headers(rider["id"])
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-15T10:00:00.000Z",  # before valid_from
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_CARD_OUTSIDE_VALIDITY.value)

    def test_insufficient_funds_rejected_before_state_mutation(self, api):
        """PRD §3.5: "Before any state is mutated, the system checks
        that this remainder does not exceed the card's
        `wallet_balance_cents`; if the wallet plus the FSA share
        together cannot cover the fare, the tap-in is rejected with
        `ERR_INSUFFICIENT_FUNDS` and nothing has been written."

        Claim: tap-in on a STANDARD card with insufficient wallet (no
        FSA enrolled) is rejected with ERR_INSUFFICIENT_FUNDS and the
        card's wallet balance is unchanged."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=100)
        rh = make_rider_headers(rider["id"])
        # Wallet has 100 cents, fare needs 275.
        resp = api.create_trip(
            create_trip_payload(
                card_id=card["id"],
                idempotency_key=unique_idempotency_key(),
                tap_in_at="2026-05-20T10:00:00.000Z",
            ),
            rh,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_FUNDS.value)
        # Wallet balance must be unchanged.
        from test_helpers import get_card
        unchanged = get_card(card["id"])
        assert unchanged["wallet_balance_cents"] == 100, (
            "wallet_balance_cents must be unchanged after"
            " ERR_INSUFFICIENT_FUNDS rejection; got "
            f"{unchanged['wallet_balance_cents']}"
        )


# ===========================================================================
# Tap-in side effects on wallet
# ===========================================================================
class TestTapInWalletDebit:

    def test_standard_tap_debits_wallet_by_provisional(self, api):
        """PRD §3.5: "the card's `wallet_balance_cents` is decremented
        by the remainder".

        Claim: for a non-FSA rider, the card's wallet is debited by
        provisional_fare_cents exactly."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        pre_wallet = card["wallet_balance_cents"]
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        from test_helpers import get_card
        post = get_card(card["id"])
        assert post["wallet_balance_cents"] == (
            pre_wallet - trip["provisional_fare_cents"]
        ), (
            f"Wallet debit mismatch: pre {pre_wallet}, "
            f"post {post['wallet_balance_cents']}, "
            f"provisional {trip['provisional_fare_cents']}"
        )

    def test_tap_in_paid_from_fsa_zero_when_no_employer(self, api):
        """PRD §3.5: "If the rider's `employer_id` is null, or there is
        no `CommuterBenefitAccount`, or the account's `status` is not
        `ACTIVE`, then `paid_from_fsa_cents` is zero."

        Claim: a Rider with no Employer has Trip.paid_from_fsa_cents=0."""
        advance_clock_to_iso("2026-05-20T08:00:00.000Z")
        rider, card = setup_rider_with_funded_card(topup_cents=1000)
        trip = tap_in(
            card_id=card["id"], rider_id=rider["id"],
            tap_in_at="2026-05-20T10:00:00.000Z",
        )
        assert trip["paid_from_fsa_cents"] == 0, (
            "paid_from_fsa_cents must be 0 for rider without employer; "
            f"got {trip['paid_from_fsa_cents']}"
        )
