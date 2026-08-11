"""Funder reports (window totals, utilization variants, adjudication cycle)
and the program summary (PRD §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error,
    TEST_USERS, make_funder_analyst_headers,
    create_funder_report_payload,
    setup_active_program, setup_settled_redemption, setup_submitted_report,
    create_settled_redemption, create_report, set_clock, get_program,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_report_window_half_open_bounds(api):
    """PRD §3.9: "The period is a half-open window of UTC dates: a redemption
    whose `redeemed_at` date equals `period_start` is included, while one
    equal to `period_end` is excluded, and a window whose start does not
    precede its end is `ERR_INVALID_DATE_RANGE`."

    Design: Corner/calculations/c_report_window_half_open_bounds
    """
    ctx = setup_settled_redemption(
        lines=[{"category": "STAPLE", "amount_cents": 1000}])
    # R1 redeemed_at 2026-05-01 (default logical clock): inside [05-01, 06-01).
    set_clock("2026-06-01T00:00:00Z")
    # R2 redeemed_at 2026-06-01: equal to period_end -> excluded.
    create_settled_redemption(
        ctx, lines=[{"category": "STAPLE", "amount_cents": 2000}])

    report = create_report(ctx, ctx["pool"]["id"], basis="CASH",
                           period_start="2026-05-01", period_end="2026-06-01")
    assert report["total_redeemed_cents"] == 1000
    assert report["total_match_cents"] == 0


def test_program_summary_computed_read(api):
    """PRD §3.9: "Finally, the program summary gives operators and funders a
    live posture readout: the pool ledger rollup `committed_cents`,
    `reserved_cents`, `disbursed_cents`, and `available_cents`; the Double-Up
    ledger `double_up_matched_cents` and `double_up_remaining_cents`; the
    `active_enrollment_count`; the tier distribution `tier_t1_count`,
    `tier_t2_count`, and `tier_t3_count`; and both A1c outcome counts,
    `a1c_improved_inclusive_count` and `a1c_improved_verified_count`, computed
    as §3.7 describes."

    Design: Corner/endpoints/c_program_summary_computed_read
    """
    ctx = setup_settled_redemption()
    summary = validate_success(
        api.get_program_summary(ctx["program"]["id"], ADMIN), 200)
    assert summary["committed_cents"] == 500000
    assert summary["reserved_cents"] == 9500
    assert summary["disbursed_cents"] == 3000
    assert summary["available_cents"] == 487500
    assert summary["double_up_matched_cents"] == 2000
    assert summary["double_up_remaining_cents"] == 198000
    assert summary["active_enrollment_count"] == 1
    assert summary["tier_t1_count"] == 1
    assert summary["a1c_improved_inclusive_count"] == 0
    assert summary["a1c_improved_verified_count"] == 0


# ---------------------------------------------------------------------------
# Depth instance: pool utilization ACCRUAL vs CASH on identical ledger data
# ---------------------------------------------------------------------------

def test_pool_utilization_accrual_counts_reserved_value(api):
    """PRD §3.9: "`utilization_cents` depends on the basis: under ACCRUAL it is
    the pool's `disbursed_cents` plus its `reserved_cents` —
    issued-but-unredeemed value counts as utilized — while under CASH it is
    `disbursed_cents` alone, counting only settled disbursements."

    Design: Difficulty/dual_variant_calc/pool_utilization_accrual_vs_cash
    """
    # After the default redemption: disbursed 3000, reserved 9500.
    ctx = setup_settled_redemption()
    report = create_report(ctx, ctx["pool"]["id"], basis="ACCRUAL",
                           period_start="2026-05-01", period_end="2026-06-01")
    assert report["utilization_cents"] == 12500  # 3000 + 9500
    assert report["basis"] == "ACCRUAL"


def test_pool_utilization_cash_counts_disbursed_only(api):
    """PRD §3.9: "`utilization_cents` depends on the basis: under ACCRUAL it is
    the pool's `disbursed_cents` plus its `reserved_cents` —
    issued-but-unredeemed value counts as utilized — while under CASH it is
    `disbursed_cents` alone, counting only settled disbursements."
    PRD §3.9: "Every metric on the report is frozen at creation."

    Design: Difficulty/dual_variant_calc/pool_utilization_accrual_vs_cash
    """
    ctx = setup_settled_redemption()
    accrual = create_report(ctx, ctx["pool"]["id"], basis="ACCRUAL",
                            period_start="2026-05-01", period_end="2026-06-01")
    cash = create_report(ctx, ctx["pool"]["id"], basis="CASH",
                         period_start="2026-06-01", period_end="2026-07-01")
    # Identical ledger state; only the basis differs.
    assert cash["utilization_cents"] == 3000
    assert accrual["utilization_cents"] != cash["utilization_cents"]


# ---------------------------------------------------------------------------
# Depth instance: funder report return / resubmit / accept cycle
# ---------------------------------------------------------------------------

def _returned_report():
    """Report created, submitted, then returned once by the pool's funder."""
    ctx = setup_submitted_report()
    report = ctx["report"]
    returned = validate_success(api_client.return_report(
        report["id"], {"return_reason": "missing narrative"},
        make_funder_analyst_headers(ctx["funder"]["id"])), 200)
    assert returned["status"] == "RETURNED"
    return ctx


def test_funder_report_return_resubmit_accept_reaches_accepted(api):
    """PRD §3.9: "The administrator submits a report from DRAFT or from
    RETURNED, moving it to SUBMITTED. The pool's own funder — a
    `FunderAnalyst` whose `X-User-ID` equals the reported pool's `funder_id`,
    anyone else drawing `ERR_FORBIDDEN` — may accept it, landing it in the
    terminal ACCEPTED state, or return it with a mandatory `return_reason`
    (missing it is `ERR_VALIDATION`), which moves it to RETURNED and
    increments `revision_count` by one, ready for resubmission."

    Design: Difficulty/non_linear_state_machine/funder_report_return_resubmit_accept_cycle
    """
    ctx = _returned_report()
    report = ctx["report"]
    validate_success(api.submit_report(report["id"], ADMIN), 200)
    accepted = validate_success(api.accept_report(
        report["id"], make_funder_analyst_headers(ctx["funder"]["id"])), 200)
    assert accepted["status"] == "ACCEPTED"


def test_funder_report_return_increments_revision_count(api):
    """PRD §3.9: "or return it with a mandatory `return_reason` (missing it is
    `ERR_VALIDATION`), which moves it to RETURNED and increments
    `revision_count` by one, ready for resubmission."

    Design: Difficulty/non_linear_state_machine/funder_report_return_resubmit_accept_cycle
    """
    ctx = _returned_report()
    report = ctx["report"]
    validate_success(api.submit_report(report["id"], ADMIN), 200)
    validate_success(api.accept_report(
        report["id"], make_funder_analyst_headers(ctx["funder"]["id"])), 200)

    final = validate_success(api.get_funder_report(report["id"], ADMIN), 200)
    assert final["status"] == "ACCEPTED"
    assert final["revision_count"] == 1
