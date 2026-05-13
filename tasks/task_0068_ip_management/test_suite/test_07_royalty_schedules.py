"""RoyaltySchedule tests for the IP Management API.

Covers PRD §3.5:
- provisional_royalty_cents computed on creation
- Period contiguity (no overlap, no gap) — ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP
- Settlement: final_royalty_cents = max(raw, min_guarantee_cents) for
  EXCLUSIVE_LICENSE; raw otherwise
"""

from test_helpers import (
    ApiErrorId,
    assert_royalty_schedule,
    create_royalty_period,
    create_royalty_schedule_payload,
    iso_at,
    setup_contract_filed_for_royalty,
    settle_royalty_payload,
    validate_error,
    validate_success,
)


# ─────────────────────────────────────────────────────────────
# Provisional computation (PRD §3.5)
# ─────────────────────────────────────────────────────────────


class TestProvisionalComputation:
    """PRD §3.5 provisional_royalty_cents on creation."""

    def test_provisional_cents_is_forecast_times_rate_round_half_up(
        self, api, ip_manager_headers
    ):
        """PRD §3.5: "`provisional_royalty_cents` is computed as the
        `forecast_revenue_cents` multiplied by the parent contract's
        `royalty_rate`, rounded half-up to the nearest integer cent."

        Claim: forecast=10_000_000, rate=0.10 → provisional=1_000_000.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        sched = create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            forecast_revenue_cents=10_000_000,
        )
        assert_royalty_schedule(sched)
        assert sched["provisional_royalty_cents"] == 1_000_000
        assert sched["status"] == "FORECAST"


# ─────────────────────────────────────────────────────────────
# Period contiguity (PRD §3.5)
# ─────────────────────────────────────────────────────────────


class TestPeriodContiguity:
    """PRD §3.5 — periods must not overlap and must be contiguous."""

    def test_period_overlap_rejected(self, api, ip_manager_headers):
        """PRD §3.5: "Royalty schedules under the same contract must not
        overlap and must cover a contiguous timeline — the `period_end` of
        period N must equal the `period_start` of period N+1, and there must
        be no gaps. Any violation returns `ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP`."

        Claim: a second period whose period_start < first period's period_end
        → ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            period_index=1,
            period_start=iso_at(2026, 1, 1),
            period_end=iso_at(2026, 4, 1),
        )
        # Overlap: starts before previous period_end.
        bad = create_royalty_schedule_payload(
            period_index=2,
            period_start=iso_at(2026, 3, 1),  # overlap
            period_end=iso_at(2026, 6, 1),
            forecast_revenue_cents=1_000_000,
        )
        resp = api.create_royalty_schedule(
            seed["contract"]["id"], bad, ip_manager_headers
        )
        validate_error(
            resp,
            ApiErrorId.ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP,
            expected_status=422,
        )

    def test_period_gap_rejected(self, api, ip_manager_headers):
        """PRD §3.5: "Royalty schedules under the same contract must not
        overlap and must cover a contiguous timeline — the `period_end` of
        period N must equal the `period_start` of period N+1, and there must
        be no gaps. Any violation returns `ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP`."

        Claim: a second period with period_start > previous period_end (gap)
        → ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            period_index=1,
            period_start=iso_at(2026, 1, 1),
            period_end=iso_at(2026, 4, 1),
        )
        bad = create_royalty_schedule_payload(
            period_index=2,
            period_start=iso_at(2026, 5, 1),  # gap
            period_end=iso_at(2026, 8, 1),
            forecast_revenue_cents=1_000_000,
        )
        resp = api.create_royalty_schedule(
            seed["contract"]["id"], bad, ip_manager_headers
        )
        validate_error(
            resp,
            ApiErrorId.ERR_ROYALTY_PERIOD_GAP_OR_OVERLAP,
            expected_status=422,
        )

    def test_period_contiguous_succeeds(self, api, ip_manager_headers):
        """PRD §3.5: "the `period_end` of period N must equal the
        `period_start` of period N+1".

        Claim: second period whose period_start == previous period_end →
        success.
        """
        seed = setup_contract_filed_for_royalty(
            api, contract_type="EXCLUSIVE_LICENSE", royalty_rate=0.10
        )
        create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            period_index=1,
            period_start=iso_at(2026, 1, 1),
            period_end=iso_at(2026, 4, 1),
        )
        ok = create_royalty_schedule_payload(
            period_index=2,
            period_start=iso_at(2026, 4, 1),
            period_end=iso_at(2026, 7, 1),
            forecast_revenue_cents=1_000_000,
        )
        resp = api.create_royalty_schedule(
            seed["contract"]["id"], ok, ip_manager_headers
        )
        validate_success(resp, expected_status=201)


# ─────────────────────────────────────────────────────────────
# Settlement (PRD §3.5)
# ─────────────────────────────────────────────────────────────


class TestSettlement:
    """PRD §3.5 settlement formula with EXCLUSIVE_LICENSE floor."""

    def test_settlement_non_exclusive_uses_raw(
        self, api, finance_manager_headers
    ):
        """PRD §3.5: "When the contract's `contract_type` is
        `EXCLUSIVE_LICENSE`, the `final_royalty_cents` is the maximum of
        that raw amount and the contract's `min_guarantee_cents` (the
        licensee's minimum-guarantee floor kicks in here). For every other
        contract type, the `final_royalty_cents` equals the raw amount
        with no floor applied."

        Claim: NON_EXCLUSIVE_LICENSE, actual=9_000_000, rate=0.10 →
        final_royalty_cents == 900_000 (no min_guarantee floor).
        """
        seed = setup_contract_filed_for_royalty(
            api,
            contract_type="NON_EXCLUSIVE_LICENSE",
            royalty_rate=0.10,
            min_guarantee_cents=None,
        )
        sched = create_royalty_period(
            api,
            contract_id=seed["contract"]["id"],
            forecast_revenue_cents=10_000_000,
        )
        resp = api.settle_royalty_schedule(
            sched["id"],
            settle_royalty_payload(actual_revenue_cents=9_000_000),
            finance_manager_headers,
        )
        data = validate_success(resp, expected_status=200)
        assert data["status"] == "SETTLED"
        assert data["final_royalty_cents"] == 900_000
