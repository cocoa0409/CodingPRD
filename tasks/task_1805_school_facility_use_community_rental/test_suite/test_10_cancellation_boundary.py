"""Cancellation refund day-count boundary: day 14 vs day 13 (PRD §3.7)."""
import pytest

from test_helpers import (
    validate_success,
    sum_txns, txns_of_kind,
    make_renter_headers,
    setup_secured_permit,
    set_clock,
    api_client,
    TEST_USERS,
)

DIRECTOR = TEST_USERS["director_headers"]

FP_PRE_POLICY = {
    "policy_code": "FP-PRE", "rate_class": "FOR_PROFIT", "facility_tier": "PREMIUM",
    "hourly_rate_cents": 15000, "deposit_basis_points": 3000,
    "custodial_hourly_cents": 6000, "effective_from": "2026-01-01T00:00:00Z",
    "deposit_floor_cents": 20000,
}


def _setup(api, starts_at, ends_at, title, dep_key):
    return setup_secured_permit(
        24300, idempotency_key=dep_key,
        site_code="FHS",
        facility_overrides={"facility_code": "AUD", "facility_tier": "PREMIUM",
                            "capacity": 500},
        policy_overrides=FP_PRE_POLICY,
        org_name="Gala Productions LLC", rate_class="FOR_PROFIT",
        insurance_overrides={"per_occurrence_limit_cents": 200000000,
                             "aggregate_limit_cents": 400000000},
        event_title=title, headcount_estimate=400,
        starts_at=starts_at, ends_at=ends_at)


class TestCancellationDay14VsDay13Boundary:
    def test_cancel_exactly_14_days_before_full_refund(self, api):
        """PRD §3.7: "Fourteen or more days before the event likewise refunds one
        hundred percent with no fee."
        PRD §3.7: "The refund tier turns on how far ahead of the event the
        cancellation lands, measured in whole calendar days between the
        cancellation timestamp and `occupancy_start` in site-local dates, with
        every comparison inclusive of its lower bound."

        Design: Difficulty/boundary_precision_check/cancellation_day14_vs_day13_boundary
        """
        env, req, permit = _setup(api, "2026-10-15T22:00:00Z", "2026-10-16T04:00:00Z",
                                  "Gala A", "dep-g-1")
        # Oct 1 site-local vs Oct 15 site-local occupancy start: exactly 14 days.
        set_clock("2026-10-01T22:00:00Z")
        validate_success(api.cancel_permit(
            permit["id"], {"cancellation_reason": "cancel at day 14"},
            make_renter_headers(env["org"]["id"])))

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        assert sum_txns(payments, "DEPOSIT_REFUND") == 24300
        assert txns_of_kind(payments, "DEPOSIT_FORFEIT") == []

    def test_cancel_13_days_before_half_refund_minus_fee(self, api):
        """PRD §3.7: "At least seven but fewer than fourteen days before, half of
        what was paid is refundable, less a processing fee of 2500 cents."

        Design: Difficulty/boundary_precision_check/cancellation_day14_vs_day13_boundary
        """
        env, req, permit = _setup(api, "2026-10-16T22:00:00Z", "2026-10-17T04:00:00Z",
                                  "Gala B", "dep-g-2")
        # Oct 3 site-local vs Oct 16 site-local occupancy start: 13 days — one
        # calendar day short of the full-refund tier.
        set_clock("2026-10-03T22:00:00Z")
        validate_success(api.cancel_permit(
            permit["id"], {"cancellation_reason": "cancel at day 13"},
            make_renter_headers(env["org"]["id"])))

        payments = validate_success(api.list_permit_payments(permit["id"], DIRECTOR))
        # round_half_up(24300 * 0.5) - 2500 = 12150 - 2500; one day moved 14650
        # cents from refund to forfeiture.
        assert sum_txns(payments, "DEPOSIT_REFUND") == 9650
        assert sum_txns(payments, "DEPOSIT_FORFEIT") == 14650
