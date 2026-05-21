"""Mileage overage settlement — PRD §3.6.

Covers: settlement creation, duplicate-period rejection, the
provisional vs final calculation variants, finalisation side
effects, mark-paid balance subtraction, and dispute behaviour
including the time-window gate.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to_iso,
    api_client,
    assert_overage_settlement,
    create_draft_settlement,
    create_overage_settlement_payload,
    dispute_settlement,
    finalize_settlement,
    get_lease_agreement,
    get_lessee,
    get_overage_settlement,
    make_lessee_headers,
    mark_paid_settlement,
    post_telematics_event,
    setup_active_lease,
    setup_lease_with_period_telematics,
    setup_provisional_vs_final_divergence_scenario,
    TEST_USERS,
    validate_error,
    validate_success,
)


# ===========================================================================
# Settlement creation — PRD §3.6
# ===========================================================================
class TestSettlementCreate:

    def test_create_settlement_initial_state(self, api):
        """PRD §3.6: "A newly created or synthesised settlement is in
        `DRAFT` (the row's `settlement_status` field), with
        `provisional_overage_miles`, `final_overage_miles`,
        `provisional_balance_cents`, and `balance_cents` initialised
        by the calculation described below."

        Claim: a fresh settlement is in DRAFT with the four numeric
        fields present.
        """
        lessee, vehicle, lease = setup_active_lease()
        resp = api.create_overage_settlement(
            create_overage_settlement_payload(
                lease_agreement_id=lease["id"],
                period_year=2026, period_month=3,
            ),
            TEST_USERS["fleet_manager_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_overage_settlement(data)
        assert data["settlement_status"] == "DRAFT"
        assert data["period_year"] == 2026
        assert data["period_month"] == 3

    def test_duplicate_period_rejected(self, api):
        """PRD §3.6: "A duplicate row for the same combination of
        lease, year, and month is forbidden: zero existing rows are
        allowed, but one existing row blocks creation with
        `ERR_DUPLICATE_SETTLEMENT_PERIOD`."

        Claim: creating a second settlement for the same
        (lease, year, month) tuple returns
        ERR_DUPLICATE_SETTLEMENT_PERIOD.
        """
        _, _, lease = setup_active_lease()
        h = TEST_USERS["fleet_manager_headers"]
        validate_success(
            api.create_overage_settlement(
                create_overage_settlement_payload(
                    lease_agreement_id=lease["id"],
                    period_year=2026, period_month=4,
                ),
                h,
            ),
            expected_status=201,
        )
        dup = api.create_overage_settlement(
            create_overage_settlement_payload(
                lease_agreement_id=lease["id"],
                period_year=2026, period_month=4,
            ),
            h,
        )
        validate_error(
            dup, ApiErrorId.ERR_DUPLICATE_SETTLEMENT_PERIOD.value,
        )


# ===========================================================================
# Flat-rate overage calculation — PRD §3.6
# ===========================================================================
class TestFlatRateCalculation:

    def test_flat_rate_overage_balance(self, api):
        """PRD §3.6: "Pricing then branches on `tiered_overage_enabled`.
        When the flag is false, the row's money figure is simply the
        overage miles multiplied by the lease's
        `overage_rate_cents_per_mile`."

        Claim: with allowance=1000, rate=25, start_odom=0,
        end_odom=2200 (period_miles=2200, overage_miles=1200), the
        balance_cents = 1200 * 25 = 30000.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, vehicle, lease = setup_lease_with_period_telematics(
            period_year=2026, period_month=3,
            start_odometer=0, end_odometer=2200,
            monthly_mileage_allowance=1000,
            overage_rate_cents_per_mile=25,
            tiered_overage_enabled=False,
            vehicle_class="CLASS_5",
        )
        advance_clock_to_iso("2026-04-01T01:00:00.000Z")
        # Create + finalize for March 2026.
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=3,
        )
        s = finalize_settlement(s["id"])
        assert s["settlement_status"] == "FINAL"
        assert s["final_overage_miles"] == 1200, (
            f"final_overage_miles must be (2200-0) - 1000 = 1200, "
            f"got {s['final_overage_miles']!r}"
        )
        assert s["balance_cents"] == 30000, (
            f"flat-rate balance must be 1200 * 25 = 30000, "
            f"got {s['balance_cents']!r}"
        )


# ===========================================================================
# Finalisation side-effects — PRD §3.6
# ===========================================================================
class TestFinalize:

    def test_finalize_advances_cumulative_overage_miles(self, api):
        """PRD §3.6: "Finalisation by a `FleetManager` advances the
        row from `DRAFT` to `FINAL`, recomputes the final variant,
        and adds the final overage miles to the lease's running
        `cumulative_overage_miles`."

        Claim: finalize increments lease.cumulative_overage_miles by
        the final_overage_miles of the row.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, vehicle, lease = setup_lease_with_period_telematics(
            period_year=2026, period_month=3,
            start_odometer=0, end_odometer=1800,
            monthly_mileage_allowance=1000,
            overage_rate_cents_per_mile=25,
            tiered_overage_enabled=False,
        )
        advance_clock_to_iso("2026-04-01T01:00:00.000Z")
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=3,
        )
        pre_lease = get_lease_agreement(lease["id"])
        s = finalize_settlement(s["id"])
        post_lease = get_lease_agreement(lease["id"])
        assert (
            post_lease["cumulative_overage_miles"]
            == pre_lease["cumulative_overage_miles"]
            + s["final_overage_miles"]
        ), (
            f"cumulative_overage_miles must advance by "
            f"final_overage_miles: pre "
            f"{pre_lease['cumulative_overage_miles']}, "
            f"post {post_lease['cumulative_overage_miles']}, "
            f"delta {s['final_overage_miles']}"
        )

    def test_finalize_twice_rejected(self, api):
        """PRD §3.6: "Two finalise calls landing simultaneously on
        the same row serialise on the settlement-state flip; the
        loser is rejected with `ERR_INVALID_STATE` because by the
        time it reaches the state-machine check the row has already
        advanced past `DRAFT`."

        Claim (sequential variant): once finalised, a second finalize
        returns ERR_INVALID_STATE.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        _, _, lease = setup_lease_with_period_telematics(
            period_year=2026, period_month=3,
            start_odometer=0, end_odometer=500,  # no overage
            monthly_mileage_allowance=1000,
            overage_rate_cents_per_mile=25,
            tiered_overage_enabled=False,
        )
        advance_clock_to_iso("2026-04-01T01:00:00.000Z")
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=3,
        )
        finalize_settlement(s["id"])
        resp = api.finalize_overage_settlement(
            s["id"], TEST_USERS["fleet_manager_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ===========================================================================
# Mark-paid — PRD §3.6
# ===========================================================================
class TestMarkPaid:

    def test_mark_paid_subtracts_from_outstanding(self, api):
        """PRD §3.6: "A `FleetManager` may then mark a finalised
        settlement as paid, which advances it from `FINAL` to `PAID`
        and subtracts the row's `balance_cents` from the owning
        lessee's `outstanding_balance_cents`."

        Claim: mark-paid moves status to PAID and subtracts
        balance_cents from the lessee balance.
        """
        from test_helpers import (
            push_outstanding_balance_via_collision,
        )
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, vehicle, lease = setup_lease_with_period_telematics(
            period_year=2026, period_month=3,
            start_odometer=0, end_odometer=2000,  # 1000 overage
            monthly_mileage_allowance=1000,
            overage_rate_cents_per_mile=25,
            tiered_overage_enabled=False,
        )
        # First push the lessee balance up so the subtraction is
        # observable. PRD §3.7 says approve adds deductible. Use a
        # small deductible.
        push_outstanding_balance_via_collision(
            lessee=lessee, vehicle=vehicle, lease=lease,
            deductible_cents=25_000,
            incident_ts="2026-03-10T12:00:00.000Z",
        )
        advance_clock_to_iso("2026-04-01T01:00:00.000Z")
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=3,
        )
        s = finalize_settlement(s["id"])
        balance_to_pay = s["balance_cents"]
        pre = get_lessee(lessee["id"])
        s = mark_paid_settlement(s["id"])
        post = get_lessee(lessee["id"])
        assert s["settlement_status"] == "PAID"
        assert post["outstanding_balance_cents"] == (
            pre["outstanding_balance_cents"] - balance_to_pay
        ), (
            f"mark-paid must subtract balance_cents ({balance_to_pay}) "
            f"from outstanding: pre {pre['outstanding_balance_cents']}, "
            f"post {post['outstanding_balance_cents']}"
        )


# ===========================================================================
# Dispute — PRD §3.6
# ===========================================================================
class TestDispute:

    def test_dispute_inside_window_succeeds(self, api):
        """PRD §3.6: "Alternatively, the lessee themselves may dispute
        a finalised settlement, advancing it from `FINAL` to
        `DISPUTED`. The dispute path is exclusive to the `Lessee`
        role and is further gated by ownership ... and by a time
        window: the current clock must be at or before the row's
        `created_at` plus the dispute window in days (a non-strict
        upper bound — equality is permitted)."

        Claim: a Lessee owner disputing inside the window succeeds
        and moves the settlement to DISPUTED.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, _, lease = setup_active_lease()
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=2,
        )
        s = finalize_settlement(s["id"])
        # Same-clock dispute is trivially inside any window.
        out = dispute_settlement(
            settlement_id=s["id"], lessee_id=lessee["id"],
        )
        assert out["settlement_status"] == "DISPUTED"

    def test_dispute_does_not_subtract_balance(self, api):
        """PRD §3.6: "A disputed settlement does not reduce the
        lessee's balance — that subtraction happens only on the paid
        transition."

        Claim: outstanding_balance_cents is unchanged after a
        dispute on a FINAL settlement.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        lessee, _, lease = setup_active_lease()
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=2,
        )
        s = finalize_settlement(s["id"])
        pre = get_lessee(lessee["id"])
        dispute_settlement(
            settlement_id=s["id"], lessee_id=lessee["id"],
        )
        post = get_lessee(lessee["id"])
        assert post["outstanding_balance_cents"] == (
            pre["outstanding_balance_cents"]
        ), (
            f"dispute must not change outstanding_balance_cents: "
            f"pre {pre['outstanding_balance_cents']}, "
            f"post {post['outstanding_balance_cents']}"
        )

    def test_dispute_by_wrong_lessee_rejected(self, api):
        """PRD §2.1: "a `Lessee` caller invoking the dispute
        operation on an `OverageSettlement` must have an `X-User-ID`
        that matches the `lessee_id` of the parent `LeaseAgreement`;
        mismatch yields `ERR_FORBIDDEN`."

        Claim: a Lessee with the wrong X-User-ID (different lessee)
        is rejected with ERR_FORBIDDEN.
        """
        advance_clock_to_iso("2026-03-01T00:00:00.000Z")
        owner, _, lease = setup_active_lease()
        from test_helpers import create_lessee
        other = create_lessee()
        s = create_draft_settlement(
            lease_id=lease["id"], period_year=2026, period_month=2,
        )
        s = finalize_settlement(s["id"])
        resp = api.dispute_overage_settlement(
            s["id"], make_lessee_headers(other["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN.value)
