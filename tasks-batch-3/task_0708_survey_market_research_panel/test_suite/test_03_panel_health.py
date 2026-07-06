"""Panel health: rolling vs lifetime variants and the ACTIVE<->AT_RISK cycle.

Difficulty queue (A): dual_variant_calc (health rolling vs lifetime),
non_linear_state_machine (Panelist health-driven cycle).
"""
from test_helpers import (
    validate_success, TEST_USERS, setup_panelist_health_window,
)

OPS = TEST_USERS["panel_ops_headers"]


def test_health_rolling_and_lifetime_diverge_on_window(api):
    """PRD §3.6: "The persisted `health_score` uses a rolling window of that
    panelist's five most recent participations by creation time (newest first).
    Within that window, the base score is the fraction of windowed participations
    whose `completion_status` is `COMPLETED`, times 100 — or 100 if the window is
    empty."
    PRD §3.6: "A read of a panelist's health returns this rolling figure as
    `health_score` and also returns a `lifetime_health_score` computed identically
    but over **all** of the panelist's participations rather than the recent five
    (its denominator is the panelist's full `lifetime_invited_n` rather than the
    recent window), plus the panelist's `status`."

    Design: Difficulty/dual_variant_calc/health_rolling_vs_lifetime_diverge_on_window
    """
    # 1 completed (oldest) + 5 incomplete (most recent). Rolling window of the 5
    # most recent has 0 completions -> base 0. Lifetime: 1/6 *100 = 16.67 -> 17.
    study, cell, panelist = setup_panelist_health_window(
        completed_recent=1, extra_incomplete=5, target_n=10, segment_key="SEG_H")

    health = validate_success(api.get_panelist_health(panelist["id"], OPS))
    assert health["health_score"] == 0, \
        f"rolling health should be 0 (5 most recent all incomplete), got {health['health_score']}"
    assert health["lifetime_health_score"] == 17, \
        f"lifetime health should be 17 (1/6*100 round_half_up), got {health['lifetime_health_score']}"
    assert health["health_score"] != health["lifetime_health_score"], \
        "rolling and lifetime health must diverge for this window pattern"


def test_panelist_transitions_active_to_at_risk_on_low_health(api):
    """PRD §3.6: "On each health recompute, if `health_score` falls below the churn
    threshold of 50, an `ACTIVE` panelist becomes `AT_RISK` (the `ACTIVE → AT_RISK`
    transition)".

    Design: Difficulty/non_linear_state_machine/panelist_active_at_risk_health_cycle
    """
    # 2 completed + 3 incomplete = 5 participations; rolling base = 2/5 *100 = 40 < 50.
    study, cell, panelist = setup_panelist_health_window(
        completed_recent=2, extra_incomplete=3, target_n=10, segment_key="SEG_R")

    data = validate_success(api.get_panelist(panelist["id"], OPS))
    assert data["health_score"] == 40, \
        f"rolling health should be 40 (2/5 recent completed), got {data['health_score']}"
    assert data["status"] == "AT_RISK", \
        f"health 40 < 50 must drive ACTIVE -> AT_RISK, got {data['status']}"


def test_panelist_returns_active_when_health_recovers(api):
    """PRD §3.6: "if `health_score` rises back to at least 50, an `AT_RISK` panelist
    returns to `ACTIVE` (the `AT_RISK → ACTIVE` transition) — a health-driven
    cycle."

    Design: Difficulty/non_linear_state_machine/panelist_active_at_risk_health_cycle
    """
    # 4 completed + 1 incomplete = 5 participations; rolling base = 4/5 *100 = 80 >= 50.
    # A panelist whose recent window recovers to >=50 health is ACTIVE, not AT_RISK,
    # closing the ACTIVE<->AT_RISK cycle on the recovery edge.
    study, cell, panelist = setup_panelist_health_window(
        completed_recent=4, extra_incomplete=1, target_n=10, segment_key="SEG_RC")

    data = validate_success(api.get_panelist(panelist["id"], OPS))
    assert data["health_score"] == 80, \
        f"rolling health should be 80 (4/5 recent completed), got {data['health_score']}"
    assert data["status"] == "ACTIVE", \
        f"health 80 >= 50 must be ACTIVE, got {data['status']}"
