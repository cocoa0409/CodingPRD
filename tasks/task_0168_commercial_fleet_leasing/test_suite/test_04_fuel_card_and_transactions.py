"""Fuel cards and pump transactions — PRD §3.3.

Covers: card issuance, ifta_eligible derivation by vehicle_class,
ERR_CARD_INACTIVE, monthly cap boundary, reversal, and the temporal
quarter-closed rule.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    api_client,
    assert_fuel_card,
    assert_fuel_card_transaction,
    create_fuel_card_payload,
    create_fuel_card_transaction_payload,
    file_ifta_quarter,
    get_fuel_card,
    issue_fuel_card,
    open_ifta_quarter,
    post_fuel_card_transaction,
    prepare_ifta_quarter,
    setup_active_lease,
    setup_active_lease_with_card,
    setup_class8_lease_with_card,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Fuel card issuance — PRD §3.3
# ===========================================================================
class TestFuelCardIssue:

    def test_issue_card_initial_state(
        self, api, fleet_manager_headers,
    ):
        """PRD §3.3: "The card is born `ACTIVE` with
        `current_period_spend_cents` initialised to zero."

        Claim: a freshly issued card has card_status=ACTIVE and
        current_period_spend_cents=0.
        """
        _, _, lease = setup_active_lease()
        payload = create_fuel_card_payload(
            card_pan_last4="1234", monthly_limit_cents=100_000,
        )
        resp = api.create_fuel_card(
            lease["id"], payload, fleet_manager_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_fuel_card(data)
        assert data["card_status"] == "ACTIVE"
        assert data["current_period_spend_cents"] == 0


# ===========================================================================
# Fuel card transaction posting — PRD §3.3
# ===========================================================================
class TestFuelCardTransactionPost:

    def test_post_txn_on_class_5_is_not_ifta_eligible(self, api):
        """PRD §3.3: "a transaction is eligible if and only if the
        parent `FuelCard`'s vehicle has a `vehicle_class` in the set
        `CLASS_7` or `CLASS_8` at the moment of `posted_at` — lighter
        classes are out of scope for federal fuel-tax accounting and
        remain ineligible regardless of jurisdiction."

        Claim: a transaction on a CLASS_5 vehicle's card has
        ifta_eligible == false.
        """
        _, _, _, card = setup_active_lease_with_card()  # CLASS_5
        from test_helpers import iso_now
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-15T12:00:00.000Z",
                jurisdiction="CA",
                gallons=10.0,
                amount_cents=4000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_fuel_card_transaction(data)
        assert data["ifta_eligible"] is False, (
            "CLASS_5 txn must have ifta_eligible=false"
        )
        assert data["txn_status"] == "POSTED"

    def test_post_txn_on_class_8_is_ifta_eligible(self, api):
        """PRD §3.3: "a transaction is eligible if and only if the
        parent `FuelCard`'s vehicle has a `vehicle_class` in the set
        `CLASS_7` or `CLASS_8` at the moment of `posted_at`."

        Claim: a transaction on a CLASS_8 vehicle's card has
        ifta_eligible == true.
        """
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        _, _, _, card = setup_class8_lease_with_card()
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-15T12:00:00.000Z",
                jurisdiction="CA",
                gallons=10.0,
                amount_cents=4000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["ifta_eligible"] is True

    def test_card_inactive_blocks_post(self, api):
        """PRD §3.3: "A posted transaction is rejected if the parent
        card's `card_status` is not `ACTIVE` or the parent lease's
        `lease_state` is not `ACTIVE`; the rejection in either case
        is `ERR_CARD_INACTIVE`."

        Claim: posting after the lessee suspension cascades the
        lease to DEFAULTED and the card to BLOCKED returns
        ERR_CARD_INACTIVE.
        """
        from test_helpers import (
            push_outstanding_balance_via_collision,
            suspend_lessee,
            DEFAULT_THRESHOLD_CENTS,
        )
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        lessee, vehicle, lease, card = setup_active_lease_with_card()
        # Push outstanding above DEFAULT_THRESHOLD_CENTS via collision
        # approval.
        push_outstanding_balance_via_collision(
            lessee=lessee, vehicle=vehicle, lease=lease,
            deductible_cents=DEFAULT_THRESHOLD_CENTS,
        )
        # Now suspend — PRD §3.8 cascades to DEFAULTED → BLOCKED.
        suspend_lessee(lessee_id=lessee["id"])
        # Posting on a BLOCKED card → ERR_CARD_INACTIVE.
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-16T12:00:00.000Z",
                jurisdiction="CA",
                gallons=10.0,
                amount_cents=4000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_CARD_INACTIVE.value)

    def test_card_limit_equal_succeeds(self, api):
        """PRD §3.3: "Equality with the cap is permitted — the
        boundary is non-strict on the way up — and the request is
        rejected with `ERR_CARD_LIMIT_EXCEEDED` only when the sum
        strictly exceeds the cap."

        Claim: a transaction whose amount equals the cap is accepted.
        """
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        _, _, _, card = setup_active_lease_with_card(
            monthly_limit_cents=100_000,
        )
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-15T12:00:00.000Z",
                jurisdiction="CA",
                gallons=50.0,
                amount_cents=100_000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert data["amount_cents"] == 100_000
        c = get_fuel_card(card["id"])
        assert c["current_period_spend_cents"] == 100_000

    def test_card_limit_exceeded_by_one_cent_rejected(self, api):
        """PRD §3.3: "the proposed `amount_cents` plus the card's
        current `current_period_spend_cents` for the calendar month
        must not exceed the card's `monthly_limit_cents`. Equality
        with the cap is permitted ... and the request is rejected
        with `ERR_CARD_LIMIT_EXCEEDED` only when the sum strictly
        exceeds the cap."

        Claim: posting one cent over the cap yields
        ERR_CARD_LIMIT_EXCEEDED.
        """
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        _, _, _, card = setup_active_lease_with_card(
            monthly_limit_cents=100_000,
        )
        # First post — fills cap to 100000 - 1 = 99999.
        ok = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-15T12:00:00.000Z",
                jurisdiction="CA",
                gallons=49.999,
                amount_cents=99_999,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        validate_success(ok, expected_status=201)
        # Second post — 2 cents would push to 100001, strictly over.
        bad = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-03-15T13:00:00.000Z",
                jurisdiction="CA",
                gallons=0.5,
                amount_cents=2,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        validate_error(bad, ApiErrorId.ERR_CARD_LIMIT_EXCEEDED.value)


# ===========================================================================
# Reversal — PRD §3.3
# ===========================================================================
class TestFuelCardTransactionReverse:

    def test_reverse_recomputes_period_spend(self, api):
        """PRD §3.3: "A `FleetManager` may reverse a posted
        transaction by invoking the reversal capability on its `id`;
        reversal flips `txn_status` to `REVERSED` and triggers the
        same monthly-spend recomputation, which decrements the card's
        running total."

        Claim: reversal flips txn_status to REVERSED and decrements
        the card's current_period_spend_cents.
        """
        advance_clock_to_iso("2026-03-15T00:00:00.000Z")
        _, _, _, card = setup_active_lease_with_card(
            monthly_limit_cents=100_000,
        )
        txn = post_fuel_card_transaction(
            fuel_card_id=card["id"],
            posted_at="2026-03-15T12:00:00.000Z",
            jurisdiction="CA",
            gallons=10.0,
            amount_cents=4000,
        )
        c = get_fuel_card(card["id"])
        assert c["current_period_spend_cents"] == 4000
        # Reverse.
        resp = api.reverse_fuel_card_transaction(
            txn["id"], TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp)
        assert data["txn_status"] == "REVERSED"
        c2 = get_fuel_card(card["id"])
        assert c2["current_period_spend_cents"] == 0, (
            f"after reversal, current_period_spend_cents must be 0, "
            f"got {c2['current_period_spend_cents']!r}"
        )


# ===========================================================================
# Quarter-closed rule — PRD §3.3, §3.9
# ===========================================================================
class TestQuarterClosedRule:

    def test_post_into_closed_quarter_rejected(self, api):
        """PRD §3.9: "Once closed, the quarter accepts no new
        IFTA-influencing activity in its window; new transactions
        whose `posted_at` falls inside a closed quarter are rejected
        with `ERR_QUARTER_CLOSED`, and a quarter cannot be reopened."

        Claim: after Q1 2026 is filed (CLOSED), a new transaction
        with posted_at inside Q1 is rejected with ERR_QUARTER_CLOSED.
        """
        # Build a CLASS_8 lease so the txns are ifta_eligible.
        advance_clock_to_iso("2026-01-15T00:00:00.000Z")
        lessee, vehicle, lease, card = setup_class8_lease_with_card()
        # Post some Q1 txns first.
        post_fuel_card_transaction(
            fuel_card_id=card["id"],
            posted_at="2026-01-20T10:00:00.000Z",
            jurisdiction="CA", gallons=10.0, amount_cents=4000,
        )
        # Open + prepare + file Q1 2026.
        advance_clock_to_iso("2026-04-01T00:00:00.000Z")
        quarter = open_ifta_quarter(
            lessee_id=lessee["id"], year=2026, quarter=1,
        )
        prepare_ifta_quarter(quarter["id"])
        file_ifta_quarter(quarter["id"])
        # New POST with posted_at inside Q1 window → ERR_QUARTER_CLOSED.
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-02-15T12:00:00.000Z",
                jurisdiction="CA", gallons=5.0, amount_cents=2000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_QUARTER_CLOSED.value)

    def test_post_outside_closed_window_succeeds(self, api):
        """PRD §3.9: "once a quarter is filed, no further
        IFTA-influencing activity may land in its window"; outside
        the window posting remains permitted (the rule is scoped to
        the closed quarter's window).

        Claim: after Q1 is CLOSED, posting a transaction dated in Q2
        succeeds.
        """
        advance_clock_to_iso("2026-01-15T00:00:00.000Z")
        lessee, vehicle, lease, card = setup_class8_lease_with_card()
        post_fuel_card_transaction(
            fuel_card_id=card["id"],
            posted_at="2026-01-20T10:00:00.000Z",
            jurisdiction="CA", gallons=10.0, amount_cents=4000,
        )
        advance_clock_to_iso("2026-04-01T00:00:00.000Z")
        q = open_ifta_quarter(
            lessee_id=lessee["id"], year=2026, quarter=1,
        )
        prepare_ifta_quarter(q["id"])
        file_ifta_quarter(q["id"])
        # Post a txn dated in Q2 (April 15).
        resp = api.create_fuel_card_transaction(
            create_fuel_card_transaction_payload(
                fuel_card_id=card["id"],
                posted_at="2026-04-15T12:00:00.000Z",
                jurisdiction="CA", gallons=5.0, amount_cents=2000,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        validate_success(resp, expected_status=201)
