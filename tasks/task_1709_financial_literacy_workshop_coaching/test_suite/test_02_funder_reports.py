"""Funder outcome reporting: COHORT vs ROLLING inclusion sets, per-participant
delta aggregation, and the empty-period null-average edge (PRD §3.9)."""
import pytest

from test_helpers import (
    create_case,
    create_certified_coach,
    create_funder_report_payload,
    create_module,
    create_participant,
    create_snapshot,
    validate_success,
)


def _setup_two_participant_report_data(api, admin_headers):
    """PA: first case intake 2026-01-10 (inside [2026-01-01, 2026-02-01)).
    PB: first case intake 2025-11-15 (before the period).
    Both have two in-period credit+savings snapshots with known deltas."""
    coach = create_certified_coach(admin_headers)
    pa = create_participant(admin_headers, full_name="PA", email="pa@test.org",
                            annual_income_cents=2000000)
    pb = create_participant(admin_headers, full_name="PB", email="pb@test.org",
                            annual_income_cents=5000000)
    create_case(pa["id"], coach["id"], admin_headers, intake_date="2026-01-10")
    create_case(pb["id"], coach["id"], admin_headers, intake_date="2025-11-15")
    # PA: credit 580 -> 610 (delta +30); savings 100000 -> 150000 (delta +50000).
    create_snapshot(pa["id"], "2026-01-05T00:00:00Z", admin_headers,
                    credit_score=580, savings_balance_cents=100000)
    create_snapshot(pa["id"], "2026-01-25T00:00:00Z", admin_headers,
                    credit_score=610, savings_balance_cents=150000)
    # PB: credit 640 -> 660 (delta +20); savings 200000 -> 210000 (delta +10000).
    create_snapshot(pb["id"], "2026-01-03T00:00:00Z", admin_headers,
                    credit_score=640, savings_balance_cents=200000)
    create_snapshot(pb["id"], "2026-01-30T00:00:00Z", admin_headers,
                    credit_score=660, savings_balance_cents=210000)
    return pa, pb


def test_funder_report_cohort_counts_only_new_entrants(api, admin_headers):
    """PRD §3.9: "`COHORT` — new-entrant reporting — includes only participants
    whose earliest coaching case by `intake_date` has its `intake_date` inside
    the window from `period_start` up to but not including `period_end`."

    Design: Difficulty/dual_variant_calc/funder_report_cohort_vs_rolling
    """
    _pa, _pb = _setup_two_participant_report_data(api, admin_headers)
    report = validate_success(
        api.create_funder_report(
            create_funder_report_payload("2026-01-01", "2026-02-01", "COHORT"),
            admin_headers,
        ),
        expected_status=201,
    )
    # Only PA qualifies (first case intake 2026-01-10 inside the window).
    assert report["participants_measured"] == 1
    assert report["avg_credit_delta_points"] == pytest.approx(30.0, abs=1e-9)
    assert report["avg_savings_delta_cents"] == 50000
    assert report["completions_count"] == 0


def test_funder_report_rolling_counts_all_served(api, admin_headers):
    """PRD §3.9: "`ROLLING` — all-served reporting — includes every participant
    with at least one coaching case of any status whose `intake_date` falls
    before `period_end`."

    Design: Difficulty/dual_variant_calc/funder_report_cohort_vs_rolling
    """
    _pa, _pb = _setup_two_participant_report_data(api, admin_headers)
    report = validate_success(
        api.create_funder_report(
            create_funder_report_payload("2026-01-01", "2026-02-01", "ROLLING"),
            admin_headers,
        ),
        expected_status=201,
    )
    # PA and PB both qualify (both have a case with intake_date < 2026-02-01).
    assert report["participants_measured"] == 2
    # Credit deltas +30 and +20 -> mean 25.0.
    assert report["avg_credit_delta_points"] == pytest.approx(25.0, abs=1e-9)
    # Savings deltas +50000 and +10000 -> mean 30000.
    assert report["avg_savings_delta_cents"] == 30000


def test_funder_report_empty_period_returns_null_averages(api, admin_headers):
    """PRD §3.9: "The report's `avg_credit_delta_points` is the mean of the
    qualifying credit deltas, expressed with one decimal place and rounded half
    up, or null when no participant qualifies; its `avg_savings_delta_cents` is
    the mean of the qualifying savings deltas rounded half up to integer cents,
    likewise null when empty."

    Design: Corner/calculations/funder_report_empty_period_returns_null_averages
    """
    create_module(admin_headers, module_code="NR-100", title="NR",
                  session_count=1, incentive_cents_per_hour=500,
                  completion_bonus_cents=0, completion_threshold=1)
    report = validate_success(
        api.create_funder_report(
            create_funder_report_payload("2026-01-01", "2026-02-01", "ROLLING"),
            admin_headers,
        ),
        expected_status=201,
    )
    assert report["participants_measured"] == 0
    assert report["avg_credit_delta_points"] is None
    assert report["avg_savings_delta_cents"] is None
    assert report["completions_count"] == 0
