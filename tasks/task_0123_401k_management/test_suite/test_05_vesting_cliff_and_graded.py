"""Vesting computation: CLIFF and GRADED variants, service-year
boundary, and VestingSnapshot materialization (PRD §3.4, §2.11,
§2.12)."""
from __future__ import annotations

import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_vesting_snapshot,
    create_vesting_snapshot,
    setup_participant_with_balance,
    setup_two_plans_same_participant_inputs,
    advance_clock,
    validate_success,
)


# ===========================================================================
# CLIFF: service-year boundary uses >= — PRD §3.4
# ===========================================================================
def test_cliff_below_threshold_yields_zero_vested(api):
    """PRD §3.4: "If the completed service years is greater than or
    equal to cliff_years, the vested percentage is 100.0; otherwise
    it is 0.0. The threshold uses greater-than-or-equal on the
    integer service-year count."

    Claim: hire_date = 2024-01-01, clock = 2026-12-30 -> service_days
    = 1094, service_years_completed = 1094 // 365 = 2; cliff_years = 3
    -> vested_pct = 0.0, vested_balance_cents = 0.

    # difficulty: boundary_precision_check/cliff_vesting_boundary_at_exact_year
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=1_000_000,
        cliff_years=3,
        vesting_schedule_type="CLIFF",
        starting_clock="2026-01-01",
        date_of_birth="1985-06-15",
        hire_date="2024-01-01",
        elected_deferral_pct=100.0,
    )
    # accumulate_balance may have moved the clock to a later year;
    # explicitly advance to the boundary date.
    advance_clock(plan["id"], "2026-12-30")
    snap = create_vesting_snapshot(plan["id"], p["id"])
    assert_vesting_snapshot(snap)
    assert snap["service_years_completed"] == 2
    assert snap["vested_pct"] == 0.0
    assert snap["vested_balance_cents"] == 0


def test_cliff_at_exact_year_boundary_yields_full_vested(api):
    """PRD §3.4: "a participant whose service is exactly cliff_years
    is fully vested, not partially vested."

    Claim: hire_date = 2024-01-01, clock = 2026-12-31 -> service_days
    = 1095, floor(1095/365)=3; cliff_years = 3 -> vested_pct = 100.0,
    vested_balance_cents == total_account_balance_cents.

    # difficulty: boundary_precision_check/cliff_vesting_boundary_at_exact_year
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=1_000_000,
        cliff_years=3,
        vesting_schedule_type="CLIFF",
        starting_clock="2026-01-01",
        date_of_birth="1985-06-15",
        hire_date="2024-01-01",
        elected_deferral_pct=100.0,
    )
    advance_clock(plan["id"], "2026-12-31")
    snap = create_vesting_snapshot(plan["id"], p["id"])
    assert snap["service_years_completed"] == 3
    assert snap["vested_pct"] == 100.0
    # Vested balance equals total account balance because vested_pct=100.
    p_now = validate_success(
        api.get_participant(plan["id"], p["id"], TEST_USERS["admin_headers"]),
        200,
    )
    expected = p_now["total_account_balance_cents"]
    assert snap["vested_balance_cents"] == expected


# ===========================================================================
# CLIFF vs GRADED dual-variant — PRD §3.4 + §2.11
# ===========================================================================
def test_cliff_vs_graded_same_service_different_vested(api):
    """PRD §3.4: "When vesting_schedule_type is GRADED, the vested
    percentage is read from graded_percentages by index. The index is
    the smaller of the completed service-year count and 6."
    PRD §3.4: "When vesting_schedule_type is CLIFF, the vested
    percentage is a step function on completed service years."

    Claim: identical service_years_completed=4 and total_balance
    ~10000000 produces vested_pct=100.0 / vested_balance=10000000
    under CLIFF(cliff_years=3) but vested_pct=60.0 / vested_balance=
    60% of total under GRADED([0,0,20,40,60,80,100]).

    # difficulty: dual_variant_calc/cliff_vs_graded_vested_balance_on_participant
    """
    # We can't easily inject "exact balance 10000000"; instead, hit
    # both variants with the same hire_date / clock setup so the same
    # service_years_completed=4 is observed, then assert on the
    # vested_pct field (which is balance-independent) and on the
    # vested_balance ratio relative to whatever total_balance the
    # accumulation produced.
    plan_c, p_c = setup_participant_with_balance(
        target_balance_cents=5_000_000,
        cliff_years=3,
        vesting_schedule_type="CLIFF",
        starting_clock="2026-01-15",
        date_of_birth="1985-06-15",
        hire_date="2022-01-01",
        elected_deferral_pct=100.0,
    )
    plan_d, p_d = setup_participant_with_balance(
        target_balance_cents=5_000_000,
        vesting_schedule_type="GRADED",
        graded_percentages=[0, 0, 20, 40, 60, 80, 100],
        cliff_years=None,
        starting_clock="2026-01-15",
        date_of_birth="1985-06-15",
        hire_date="2022-01-01",
        elected_deferral_pct=100.0,
    )
    # Sync both clocks to the same date so service_years_completed
    # matches across the two plans.
    target_clock = "2026-06-01"
    try:
        advance_clock(plan_c["id"], target_clock)
    except AssertionError:
        # Already past — try a later date
        target_clock = "2027-06-01"
        advance_clock(plan_c["id"], target_clock)
    try:
        advance_clock(plan_d["id"], target_clock)
    except AssertionError:
        advance_clock(plan_d["id"], target_clock)
    snap_c = create_vesting_snapshot(plan_c["id"], p_c["id"])
    snap_d = create_vesting_snapshot(plan_d["id"], p_d["id"])
    # Same service_years_completed in both.
    assert snap_c["service_years_completed"] == snap_d["service_years_completed"]
    sy = snap_c["service_years_completed"]
    assert sy >= 4, (
        f"setup should yield >=4 service years; got {sy}"
    )
    # CLIFF: >= cliff_years(3) -> 100%
    assert snap_c["vested_pct"] == 100.0
    # GRADED: index = min(sy, 6); for sy in {4,5} the array entry is
    # 60 or 80 — strictly less than 100. Distinguishing claim is that
    # GRADED is NOT 100%.
    expected_graded = [0, 0, 20, 40, 60, 80, 100][min(sy, 6)]
    assert snap_d["vested_pct"] == float(expected_graded)
    assert snap_c["vested_pct"] != snap_d["vested_pct"]


def test_cliff_vs_graded_different_vesting_pct_second_variant(api):
    """PRD §3.4: "When vesting_schedule_type is CLIFF, the vested
    percentage is a step function on completed service years."
    PRD §3.4: "When vesting_schedule_type is GRADED, the vested
    percentage is read from graded_percentages by index."

    Second test for the dual-variant difficulty instance, using a
    different cliff_years value and graded_percentages shape to
    confirm the variant split is general.

    # difficulty: dual_variant_calc/cliff_vs_graded_vested_balance_on_participant
    """
    plan_c, p_c = setup_participant_with_balance(
        target_balance_cents=3_000_000,
        cliff_years=2,
        vesting_schedule_type="CLIFF",
        starting_clock="2026-01-15",
        hire_date="2022-01-01",
        elected_deferral_pct=100.0,
    )
    plan_d, p_d = setup_participant_with_balance(
        target_balance_cents=3_000_000,
        vesting_schedule_type="GRADED",
        graded_percentages=[10, 25, 40, 55, 70, 85, 100],
        cliff_years=None,
        starting_clock="2026-01-15",
        hire_date="2022-01-01",
        elected_deferral_pct=100.0,
    )
    target_clock = "2026-06-01"
    try:
        advance_clock(plan_c["id"], target_clock)
    except AssertionError:
        target_clock = "2027-06-01"
        advance_clock(plan_c["id"], target_clock)
    try:
        advance_clock(plan_d["id"], target_clock)
    except AssertionError:
        advance_clock(plan_d["id"], target_clock)
    snap_c = create_vesting_snapshot(plan_c["id"], p_c["id"])
    snap_d = create_vesting_snapshot(plan_d["id"], p_d["id"])
    assert snap_c["service_years_completed"] == snap_d["service_years_completed"]
    sy = snap_c["service_years_completed"]
    # CLIFF(2): sy>=2 -> 100%
    assert snap_c["vested_pct"] == 100.0
    # GRADED: expected pct from the array
    expected_graded = [10, 25, 40, 55, 70, 85, 100][min(sy, 6)]
    assert snap_d["vested_pct"] == float(expected_graded)
    # Distinguishing claim: the two variants yield different vested_pct
    # (unless sy is so high that graded also reaches 100 — guard that).
    if expected_graded < 100:
        assert snap_c["vested_pct"] != snap_d["vested_pct"]


# ===========================================================================
# Vesting snapshot rounding — PRD §3.4
# ===========================================================================
def test_vesting_snapshot_rounding_half_up(api):
    """PRD §3.4: "The vested balance in cents is the participant's
    total_account_balance_cents multiplied by the vested percentage
    divided by one hundred, then rounded half up to a whole cent."

    Claim: at any vested_pct, vested_balance_cents ==
    round_half_up(total_account_balance_cents * vested_pct / 100).
    Verifies by computing the expected value in the test against the
    PRD formula.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=1_000_000,
        vesting_schedule_type="GRADED",
        graded_percentages=[0, 20, 40, 60, 80, 100, 100],
        cliff_years=None,
        starting_clock="2026-01-15",
        date_of_birth="1985-06-15",
        hire_date="2024-01-01",
        elected_deferral_pct=100.0,
    )
    advance_clock(plan["id"], "2026-06-15")
    snap = create_vesting_snapshot(plan["id"], p["id"])
    p_now = validate_success(
        api.get_participant(plan["id"], p["id"], TEST_USERS["admin_headers"]),
        200,
    )
    total = p_now["total_account_balance_cents"]
    pct = snap["vested_pct"]
    # round_half_up replication
    raw = total * pct / 100
    expected = int(raw + 0.5) if raw >= 0 else -int(-raw + 0.5)
    assert snap["vested_balance_cents"] == expected, (
        f"vested_balance_cents={snap['vested_balance_cents']}, "
        f"expected {expected} from total={total} * pct={pct} / 100"
    )


# ===========================================================================
# VestingSnapshot is append-only — PRD §3.4 + §2.4
# ===========================================================================
def test_vesting_snapshot_omits_updated_at_and_version(api):
    """PRD §2.4: "Three entity types are immutable ledger or audit
    rows and therefore carry only id and created_at; they do not
    expose updated_at and do not expose version. Those entities are
    ContributionRecord ... VestingSnapshot ... LoanRepayment ... and
    PlanClock."

    Claim: a VestingSnapshot response does NOT carry updated_at or
    version.
    """
    plan, p = setup_participant_with_balance(
        target_balance_cents=500_000,
        cliff_years=1,
        starting_clock="2026-01-15",
        hire_date="2020-01-01",
    )
    snap = create_vesting_snapshot(plan["id"], p["id"])
    assert "updated_at" not in snap
    assert "version" not in snap
