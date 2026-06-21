"""Cancellation, the date-keyed tiered refund, and the conserved seat / money
invariants (PRD §3.7, §2.7, §2.8)."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    make_candidate_headers,
    fixtures,
)


class TestTieredRefund:
    def test_refund_tier_partial_75_at_14_days_before_test_date(self, api):
        """PRD §3.7: "Otherwise, if it is at least 14, the tier is PARTIAL_75 and
        the refund is 75 percent of amount_paid_cents, rounded half up to whole
        cents." PRD §3.7: "The tier is keyed strictly on days before the session's
        test_date, never on days since the registration was created."

        Design: Difficulty/dual_variant_calc/tiered_refund_days_before_test_date_not_since_registration
        """
        # test_date 2026-09-01; clock 2026-08-18 -> 14 days before -> PARTIAL_75.
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            clock="2026-06-01T00:00:00.000Z",
        )
        fixtures.set_clock("2026-08-18T00:00:00.000Z")
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["refund_tier"] == "PARTIAL_75"
        assert cancelled["amount_refunded_cents"] == 4500, "75% of 6000"
        assert cancelled["lifecycle_status"] == "CANCELLED"
        center_after = get_success_data(api.get_test_center(center["id"], TEST_USERS["test_center_admin_headers"]))
        assert center_after["net_revenue_cents"] == 1500, "6000 charged - 4500 refunded"

    def test_refund_tier_keyed_on_test_date_not_registration_age(self, api):
        """PRD §3.7: "The tier is keyed strictly on days before the session's
        test_date, never on days since the registration was created." PRD §3.7:
        "If the days-before count is at least 60, the tier is FULL and the refund
        equals the full amount_paid_cents."

        Design: Difficulty/dual_variant_calc/tiered_refund_days_before_test_date_not_since_registration
        """
        # Register on 2026-06-01 (registration created "long ago" relative to the
        # cancel), but the test_date stays 90+ days ahead, so days-before >= 60 ->
        # FULL. If keyed on registration age the tier would differ; it is FULL.
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            clock="2026-06-01T00:00:00.000Z",
            session_overrides={"test_date": "2026-12-01",
                               "window_start_utc": "2026-12-01T13:00:00.000Z",
                               "window_end_utc": "2026-12-01T17:00:00.000Z"},
        )
        # Advance the clock so the registration is "old" but still >= 60 days before test_date.
        fixtures.set_clock("2026-09-01T00:00:00.000Z")  # 91 days before 2026-12-01
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["refund_tier"] == "FULL", "91 days before test_date -> FULL"
        assert cancelled["amount_refunded_cents"] == 6000

    def test_refund_tier_boundary_13_days_is_partial_50(self, api):
        """PRD §3.7: "Otherwise, if it is at least 1, the tier is PARTIAL_50 and
        the refund is 50 percent of amount_paid_cents, rounded half up to whole
        cents." PRD §3.7: "The tier boundaries are inclusive on their lower edge."

        Design: Difficulty/boundary_precision_check/refund_tier_boundary_exactly_14_days_inclusive
        """
        # clock 2026-08-19 -> 13 days before 2026-09-01 -> below the 14 boundary -> PARTIAL_50.
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            clock="2026-06-01T00:00:00.000Z",
        )
        fixtures.set_clock("2026-08-19T00:00:00.000Z")
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["refund_tier"] == "PARTIAL_50", "13 days < 14 inclusive boundary"
        assert cancelled["amount_refunded_cents"] == 3000, "50% of 6000"

    def test_refund_tier_exactly_14_days_inclusive_is_partial_75(self, api):
        """PRD §3.7: "Otherwise, if it is at least 14, the tier is PARTIAL_75 and
        the refund is 75 percent of amount_paid_cents, rounded half up to whole
        cents." PRD §3.7: "The tier boundaries are inclusive on their lower edge."

        Design: Difficulty/boundary_precision_check/refund_tier_boundary_exactly_14_days_inclusive
        """
        # clock 2026-08-18 -> exactly 14 days before -> inclusive -> PARTIAL_75.
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            clock="2026-06-01T00:00:00.000Z",
        )
        fixtures.set_clock("2026-08-18T00:00:00.000Z")
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["refund_tier"] == "PARTIAL_75", "14 days hits the inclusive boundary"
        assert cancelled["amount_refunded_cents"] == 4500

    def test_cancel_after_test_date_none_tier_succeeds_zero_refund(self, api):
        """PRD §3.7: "Otherwise — when the days-before count is zero or negative,
        meaning the cancellation falls on the test day itself or after it — the
        tier is NONE and the refund is zero." PRD §3.7: "The cancel itself always
        succeeds even in the NONE tier; only when a caller asserts that a refund
        should have been issued does a NONE-tier cancel surface as
        ERR_REFUND_WINDOW_CLOSED."

        Design: Corner/validations/cancel_after_test_date_none_tier_succeeds_zero_refund
        """
        center, candidate, session, reg = fixtures.create_reserved_registration(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
            clock="2026-06-01T00:00:00.000Z",
        )
        fixtures.set_clock("2026-09-02T00:00:00.000Z")  # day after test_date
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["lifecycle_status"] == "CANCELLED"
        assert cancelled["refund_tier"] == "NONE"
        assert cancelled["amount_refunded_cents"] == 0


class TestConservationInvariants:
    def test_seat_conservation_register_then_cancel_restores_pool(self, api):
        """PRD §2.7: "Every operation that takes or releases a seat adjusts the
        matching counter by exactly one and increments the session's version by
        one, so that the counters and the version always move together."

        Design: Difficulty/compensating_invariant/seat_conservation_register_then_cancel_restores_pool
        """
        center, candidate, session, reg = fixtures.create_reserved_registration(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
            clock="2026-06-01T00:00:00.000Z",
        )
        after_reg = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert after_reg["standard_seats_reserved"] == 1
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"])))
        after_cancel = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert after_cancel["standard_seats_reserved"] == 0, "pool back to prior value, no drift"

    def test_seat_and_version_move_together_on_register_and_cancel(self, api):
        """PRD §2.7: "Every operation that takes or releases a seat adjusts the
        matching counter by exactly one and increments the session's version by
        one, so that the counters and the version always move together."

        Design: Difficulty/compensating_invariant/seat_conservation_register_then_cancel_restores_pool
        """
        center, candidate, session = fixtures.setup_center_session_candidate(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
            clock="2026-06-01T00:00:00.000Z",
        )
        v0 = session["version"]
        reg = fixtures.create_registration(session["id"], candidate["id"], v0)
        after_reg = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert after_reg["standard_seats_reserved"] == 1
        assert after_reg["version"] == v0 + 1, "version moved with the seat (take)"
        validate_success(api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"])))
        after_cancel = get_success_data(api.get_test_session(session["id"], TEST_USERS["candidate_headers"]))
        assert after_cancel["standard_seats_reserved"] == 0, "seat conserved back to 0"
        assert after_cancel["version"] == v0 + 2, "version moved with the seat (release)"

    def test_net_revenue_conservation_charge_then_full_refund_nets_zero(self, api):
        """PRD §2.8: "Money is also conserved, tracked per center in the integer
        field net_revenue_cents on TestCenter, which holds the running sum of all
        registration fees captured at that center's sessions minus all refunds
        issued." PRD §3.7: "If the days-before count is at least 60, the tier is
        FULL and the refund equals the full amount_paid_cents."

        Design: Difficulty/compensating_invariant/net_revenue_conservation_charge_then_full_refund_nets_zero
        """
        # Clock far before test_date -> FULL tier.
        center, candidate, session, reg = fixtures.create_reserved_registration(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
            clock="2026-01-01T00:00:00.000Z",
        )
        center_charged = get_success_data(api.get_test_center(center["id"], TEST_USERS["test_center_admin_headers"]))
        assert center_charged["net_revenue_cents"] == 6000, "fee captured at reservation"
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["refund_tier"] == "FULL"
        assert cancelled["amount_refunded_cents"] == 6000
        center_after = get_success_data(api.get_test_center(center["id"], TEST_USERS["test_center_admin_headers"]))
        assert center_after["net_revenue_cents"] == 0, "6000 charged - 6000 refunded, no drift"

    def test_net_revenue_partial_refund_leaves_charge_minus_refund(self, api):
        """PRD §2.8: "Money is also conserved, tracked per center in the integer
        field net_revenue_cents on TestCenter, which holds the running sum of all
        registration fees captured at that center's sessions minus all refunds
        issued." PRD §3.7: "Second, the same refund amount is subtracted from the
        host center's net_revenue_cents, preserving money conservation."

        Design: Difficulty/compensating_invariant/net_revenue_conservation_charge_then_full_refund_nets_zero
        """
        # Charge 6000, then cancel in the PARTIAL_75 tier (14 days before) refunding
        # 4500. Ledger must read exactly 6000 - 4500 = 1500.
        center, candidate, session, reg = fixtures.create_confirmed_registration(
            center_overrides={"room_capacity_standard": 5, "room_capacity_accommodated": 5},
            clock="2026-06-01T00:00:00.000Z",
        )
        fixtures.set_clock("2026-08-18T00:00:00.000Z")  # 14 days before -> PARTIAL_75
        cancelled = validate_success(
            api.cancel_registration(reg["id"], make_candidate_headers(candidate["id"]))
        )
        assert cancelled["amount_refunded_cents"] == 4500
        center_after = get_success_data(api.get_test_center(center["id"], TEST_USERS["test_center_admin_headers"]))
        assert center_after["net_revenue_cents"] == 1500, "6000 charged - 4500 refunded"
