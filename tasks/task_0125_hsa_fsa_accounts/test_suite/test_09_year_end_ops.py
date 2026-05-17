"""Year-end checkpoint sweeps and OpsRun — PRD §3.6, §3.7.

Coverage targets:
- YEAR_END_CLOSE on each policy:
  * NONE -> CLOSED with full forfeiture.
  * GRACE_PERIOD -> GRACE_PERIOD with grace_period_end_date set.
  * CARRYOVER -> CARRYOVER_PENDING.
- HSA closes with forfeited_cents = 0.
- OpsRun uniqueness: (kind, as_of_date) -> ERR_DUPLICATE_OPS_RUN.
- OpsRun strict monotonicity: as_of_date strictly greater than every
  prior as_of_date -> ERR_OPS_RUN_NOT_MONOTONIC.
- Index increments by 1.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    advance_clock_to,
    assert_ops_run,
    create_ops_run_payload,
    get_plan_year,
    iso_datetime_utc,
    open_plan_year,
    post_contribution,
    post_ops_run,
    setup_active_plan_year,
    setup_holder_and_account,
    setup_carryover_chain_with_successor,
    validate_error,
    validate_success,
)


# ===========================================================================
# YEAR_END_CLOSE — PRD §3.6, §3.7
# ===========================================================================
class TestYearEndClose:

    def test_health_fsa_none_policy_closes_with_full_forfeit(self, api):
        """PRD §3.6: "For an HSA, or for a Health FSA or Dependent Care
        FSA whose year_end_policy is NONE, the plan year goes directly
        to CLOSED. ... For a Health FSA or Dependent Care FSA with
        NONE, forfeited_cents is set to the maximum of 0 and
        contributions_ytd_cents minus claims_paid_ytd_cents."

        Claim: HEALTH_FSA NONE with $1_000 contributed and no claims
        paid -> after YEAR_END_CLOSE, status CLOSED and forfeited_cents
        == 100_000.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="NONE", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "CLOSED"
        assert py_after["forfeited_cents"] == 100_000

    def test_hsa_closes_with_zero_forfeit(self, api):
        """PRD §3.6: "For an HSA, forfeited_cents is set to 0 — HSA
        balances roll forward indefinitely on the same account, and
        plan-year close is purely a reporting event."

        Claim: HSA with $1_000 contributed -> after YEAR_END_CLOSE,
        forfeited_cents == 0.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        _, acct, py = setup_active_plan_year(
            account_type="HSA", coverage_tier="SELF_ONLY",
            year_end_policy="NONE", calendar_year=2025,
        )
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "CLOSED"
        assert py_after["forfeited_cents"] == 0

    def test_health_fsa_grace_period_transitions_to_grace(self, api):
        """PRD §3.6: "For a Health FSA or Dependent Care FSA whose
        year_end_policy is GRACE_PERIOD, the plan year transitions to
        GRACE_PERIOD status and grace_period_end_date is set to March
        15 of calendar_year + 1 at the instant YYYY-03-15T00:00:00Z."

        Claim: HEALTH_FSA GRACE_PERIOD -> after YEAR_END_CLOSE,
        status == GRACE_PERIOD and grace_period_end_date ==
        2026-03-15T00:00:00Z.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="GRACE_PERIOD", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "GRACE_PERIOD"
        # PRD §3.6 pins the instant to YYYY-03-15T00:00:00Z; PRD §2.2
        # (also §2.0 entity timestamp rules) requires all UTC ISO 8601
        # outputs to carry three fractional digits, so the serialized
        # representation is '2026-03-15T00:00:00.000Z'.
        assert py_after["grace_period_end_date"] == "2026-03-15T00:00:00.000Z"

    def test_health_fsa_carryover_transitions_to_pending(self, api):
        """PRD §3.6: "For a Health FSA whose year_end_policy is
        CARRYOVER, the plan year transitions to CARRYOVER_PENDING."

        Claim: HEALTH_FSA CARRYOVER -> after YEAR_END_CLOSE, status ==
        CARRYOVER_PENDING.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        holder, acct = setup_holder_and_account(
            account_type="HEALTH_FSA", coverage_tier=None,
            year_end_policy="CARRYOVER", birth_date="1980-01-01",
        )
        py = open_plan_year(acct["id"], calendar_year=2025)
        post_contribution(py["id"], amount_cents=100_000, source="PAYROLL")
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        py_after = get_plan_year(acct["id"], py["id"])
        assert py_after["status"] == "CARRYOVER_PENDING"


# ===========================================================================
# Carryover transfer at successor opening — PRD §3.6
# ===========================================================================
class TestCarryoverTransfer:

    def test_successor_opens_after_carryover_pending(self, api):
        """PRD §3.6: "If no successor exists yet, the carryover is
        held on the predecessor (which stays in CARRYOVER_PENDING)
        until a successor plan year is opened via the standard
        plan-year creation flow, at which point the carryover is
        moved into the new plan year's carryover_in_cents and the
        predecessor is immediately closed (the predecessor's
        forfeited_cents is then the maximum of 0 and the leftover
        balance minus the applied carryover)."

        Claim: after opening the successor, predecessor status ==
        CLOSED, successor.carryover_in_cents == min(leftover,
        CARRYOVER_CAP=64_000), and predecessor.forfeited_cents ==
        max(0, leftover - applied_carryover).

        Setup: pred has $1_000 contributions, $200 paid, leftover
        $800. Applied carryover = min(800, 640) = $640. Forfeited =
        800 - 640 = $160.
        """
        holder, acct, pred, succ = setup_carryover_chain_with_successor(
            predecessor_year=2025, successor_year=2026,
            contribution_cents=100_000, pay_claim_cents=20_000,
        )
        assert pred["status"] == "CLOSED"
        assert pred["forfeited_cents"] == 16_000
        assert succ["carryover_in_cents"] == 64_000
        # PRD §3.6: 'successor.contributions_ytd_cents is unchanged'
        # i.e. carryover is tracked separately.
        assert succ["contributions_ytd_cents"] == 0


# ===========================================================================
# OpsRun uniqueness and monotonicity — PRD §3.7
# ===========================================================================
class TestOpsRunUniqueness:

    def test_ops_run_index_starts_at_one(
        self, api, plan_admin_headers,
    ):
        """PRD §3.7: "Each successful run is assigned a monotonic
        index starting at 1 for the first ever run and incrementing
        by exactly 1 thereafter".

        Claim: a single successful POST /ops-runs returns index == 1.
        """
        advance_clock_to(iso_datetime_utc(2026, 1, 2))
        payload = create_ops_run_payload(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        resp = api.create_ops_run(payload, plan_admin_headers)
        data = validate_success(resp, expected_status=201)
        assert_ops_run(data)
        assert data["index"] == 1

    def test_duplicate_kind_and_date_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.7: "The pair (kind, as_of_date) is unique; submitting
        a duplicate returns ERR_DUPLICATE_OPS_RUN."

        Claim: a second OpsRun with the same (kind, as_of_date) ->
        ERR_DUPLICATE_OPS_RUN.
        """
        advance_clock_to(iso_datetime_utc(2026, 6, 1))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        payload = create_ops_run_payload(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        resp = api.create_ops_run(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_OPS_RUN.value)

    def test_earlier_as_of_date_rejected(
        self, api, plan_admin_headers,
    ):
        """PRD §3.7: "The as_of_date must be strictly later than the
        most recent prior OpsRun.as_of_date — that is, ops runs are
        strictly monotonic; non-monotonic dates are rejected with
        ERR_OPS_RUN_NOT_MONOTONIC."

        Claim: an as_of_date earlier than the last successful run ->
        ERR_OPS_RUN_NOT_MONOTONIC.
        """
        advance_clock_to(iso_datetime_utc(2026, 6, 1))
        post_ops_run(
            kind="YEAR_END_CLOSE",
            as_of_date=iso_datetime_utc(2026, 1, 2),
        )
        # Try an earlier date with a different kind, but PRD requires
        # global monotonicity ('strictly later than the most recent
        # prior OpsRun.as_of_date'), so this still fails.
        payload = create_ops_run_payload(
            kind="GRACE_PERIOD_EXPIRY",
            as_of_date=iso_datetime_utc(2025, 12, 31),
        )
        resp = api.create_ops_run(payload, plan_admin_headers)
        validate_error(resp, ApiErrorId.ERR_OPS_RUN_NOT_MONOTONIC.value)


# ===========================================================================
# Clock monotonicity — PRD §2.7
# ===========================================================================
class TestClockMonotonicity:

    def test_clock_cannot_go_backwards(self, api, plan_admin_headers):
        """PRD §2.7: "Advancing the clock is non-decreasing — a
        request to advance to an instant earlier than the current
        value is rejected with ERR_BAD_REQUEST."

        Claim: advancing the clock to an earlier instant ->
        ERR_BAD_REQUEST.
        """
        advance_clock_to(iso_datetime_utc(2025, 6, 1))
        resp = api.clock_advance(
            {"to": iso_datetime_utc(2024, 1, 1)}, plan_admin_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)
