"""Recurring-issue index: RAW (all-time, weight only) vs TREND (trailing window,
recency-weighted), and the pinned round-then-sum-then-round order."""
import pytest
from test_helpers import (
    validate_success,
    new_representative, new_constituent, new_template, new_case, triage, set_clock,
    TEST_USERS,
)

CASEWORKER = TEST_USERS["caseworker_headers"]


def _triaged_housing_case(api, con_id, tmpl_id, at, priority):
    set_clock(api, at)
    case = new_case(api, con_id, category="HOUSING")
    triage(api, case["id"], tmpl_id, priority=priority)
    return case


# --- Difficulty: dual_variant_calc / recurring_index_raw_vs_trend ---

def test_recurring_index_raw_all_time(api):
    """PRD §3.8: "every case for the given representative (optionally narrowed to the
    given category) whose `status` is not `WITHDRAWN`. Each case's priority weight is
    rounded to two decimal places, those rounded contributions are summed, and the
    total is rounded again to two decimal places (round-half-up), yielding the `index`."
    PRD §3.8: "each case contributes a weight based on its priority: 0.5 for `LOW`,
    1.0 for `NORMAL`, 2.0 for `HIGH`, and 3.5 for `URGENT`."

    Design: Difficulty/dual_variant_calc/recurring_index_raw_vs_trend
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "HOUSING", response_window_hours=120)
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-01-01T00:00:00Z", "URGENT")
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-02-20T00:00:00Z", "HIGH")
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-02-25T00:00:00Z", "NORMAL")
    set_clock(api, "2026-03-01T00:00:00Z")

    data = validate_success(api.get_recurring_issues(
        CASEWORKER, params={"representative_id": rep["id"], "category": "HOUSING", "variant": "RAW"}))
    # 3.5 + 2.0 + 1.0 = 6.50 over all 3 cases.
    assert data["index"] == pytest.approx(6.50, abs=0.001), f"got index {data['index']}"
    assert data["case_count"] == 3, f"got case_count {data['case_count']}"


def test_recurring_index_trend_window(api):
    """PRD §3.8: "a cutoff is computed as the current clock minus `window_days` days
    (defaulting to 30 days when `window_days` is omitted), and only cases whose
    `created_at` is at or after that cutoff remain".
    PRD §3.8: "each surviving case contributes its priority weight multiplied by a
    recency bonus of 1.25".

    Design: Difficulty/dual_variant_calc/recurring_index_raw_vs_trend
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "HOUSING", response_window_hours=120)
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-01-01T00:00:00Z", "URGENT")  # before cutoff
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-02-20T00:00:00Z", "HIGH")
    _triaged_housing_case(api, con["id"], tmpl["id"], "2026-02-25T00:00:00Z", "NORMAL")
    set_clock(api, "2026-03-01T00:00:00Z")

    data = validate_success(api.get_recurring_issues(
        CASEWORKER,
        params={"representative_id": rep["id"], "category": "HOUSING", "variant": "TREND", "window_days": 30}))
    # cutoff 2026-01-30: HIGH (2.0*1.25=2.50) + NORMAL (1.0*1.25=1.25) = 3.75 over 2 cases.
    assert data["index"] == pytest.approx(3.75, abs=0.001), f"got index {data['index']}"
    assert data["case_count"] == 2, f"got case_count {data['case_count']}"


# --- Difficulty: combinatorial_formula / recurring_index_round_then_sum ---

def test_trend_round_then_sum_index(api):
    """PRD §3.8: "each such per-case contribution is rounded to two decimal places
    first, then all contributions are summed, then the total is rounded again — this
    round-then-sum-then-round order is required."

    Design: Difficulty/combinatorial_formula/recurring_index_round_then_sum
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "HOUSING", response_window_hours=120)
    set_clock(api, "2026-02-25T00:00:00Z")
    for _ in range(2):
        case = new_case(api, con["id"], category="HOUSING")
        triage(api, case["id"], tmpl["id"], priority="URGENT")
    set_clock(api, "2026-03-01T00:00:00Z")

    data = validate_success(api.get_recurring_issues(
        CASEWORKER,
        params={"representative_id": rep["id"], "category": "HOUSING", "variant": "TREND", "window_days": 30}))
    # round(3.5*1.25=4.375, 2)=4.38 each; 4.38 + 4.38 = 8.76 (NOT sum-then-round 8.75).
    assert data["index"] == pytest.approx(8.76, abs=0.001), f"got index {data['index']}"


def test_trend_round_then_sum_case_count(api):
    """PRD §3.8: "The `case_count` returned is the size of whichever pool the selected
    variant used."

    Design: Difficulty/combinatorial_formula/recurring_index_round_then_sum
    """
    rep = new_representative(api)
    con = new_constituent(api, rep["id"])
    tmpl = new_template(api, "HOUSING", response_window_hours=120)
    set_clock(api, "2026-02-25T00:00:00Z")
    for _ in range(2):
        case = new_case(api, con["id"], category="HOUSING")
        triage(api, case["id"], tmpl["id"], priority="URGENT")
    set_clock(api, "2026-03-01T00:00:00Z")

    data = validate_success(api.get_recurring_issues(
        CASEWORKER,
        params={"representative_id": rep["id"], "category": "HOUSING", "variant": "TREND", "window_days": 30}))
    assert data["case_count"] == 2, f"got case_count {data['case_count']}"
    assert data["index"] != pytest.approx(8.75, abs=0.001), "must be round-then-sum (8.76), not sum-then-round (8.75)"
