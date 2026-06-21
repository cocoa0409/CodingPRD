"""Failure-to-appear: the strike → disqualify → pool-recompute cascade, the
pool_size pre/post divergence, and the inclusive >= threshold boundary.

Translates difficulty-design instances `dual_variant_calc /
pool_size_provisional_vs_disqualified_pool`, `transitive_cascade /
fta_strike_threshold_pool_cascade_depth3`, and `boundary_precision_check /
fta_threshold_inclusive_boundary` (queue A).
"""
from test_helpers import (
    validate_success,
    TEST_USERS,
    set_clock, setup_qualified_pending, get_term, get_juror, get_summons,
)

_ADMIN = TEST_USERS["jury_administrator_headers"]
_CLERK = TEST_USERS["court_clerk_headers"]


def _qualified_pending_threshold1(clock, term_name, juror_name):
    set_clock(clock)
    return setup_qualified_pending(
        term_overrides={"name": term_name, "report_date": "2026-07-01T00:00:00Z",
                        "fta_disqualify_threshold": 1},
        juror_overrides={"full_name": juror_name},
    )


# ─── Difficulty: pool_size pre/post FTA disqualification ───────────────

def test_pool_size_one_before_fta(api):
    """PRD §3.1: "Two computed counters travel with the term: `pool_size`, the number
    of jurors in this term whose `qualification_status` is `QUALIFIED` and whose
    `disqualified` flag is false."

    Design: Difficulty/dual_variant_calc/pool_size_provisional_vs_disqualified_pool
    """
    s = _qualified_pending_threshold1("2026-07-05T08:00:00Z", "T2", "Boe J")
    assert get_term(s["term"]["id"])["pool_size"] == 1, "qualified non-disqualified juror counts as 1"
    assert get_juror(s["juror"]["id"])["disqualified"] is False


def test_pool_size_drops_to_zero_after_fta_disqualification(api):
    """PRD §3.6: "When that flag flips to true, the cascade continues: a juror who
    was `QUALIFIED` is driven to `INELIGIBLE`, and the term's `pool_size` is
    recomputed downward to reflect the juror's removal from the draw pool."

    Design: Difficulty/dual_variant_calc/pool_size_provisional_vs_disqualified_pool
    """
    s = _qualified_pending_threshold1("2026-07-05T08:00:00Z", "T2b", "Boe J")
    validate_success(api.mark_fta(s["summons"]["id"], _CLERK))
    juror = get_juror(s["juror"]["id"])
    assert juror["fta_strike_count"] == 1
    assert juror["disqualified"] is True
    assert juror["qualification_status"] == "INELIGIBLE"
    assert get_term(s["term"]["id"])["pool_size"] == 0, "disqualified juror must leave the pool"


# ─── Difficulty: depth-3 cascade from mark-fta ─────────────────────────

def test_fta_creates_strike_and_marks_summons(api):
    """PRD §3.6: "When a qualified juror does not show, a `CourtClerk` marks the
    summons as failed to appear, moving it from `QUALIFIED_PENDING` to the terminal
    `FAILED_TO_APPEAR` state."
    PRD §3.6: "First, a **strike** record is created against the juror — an
    append-only row recording its `juror_id`, the `summons_id` on which the failure
    occurred, and a `source` of `FTA`."

    Design: Difficulty/transitive_cascade/fta_strike_threshold_pool_cascade_depth3
    """
    s = _qualified_pending_threshold1("2026-07-06T08:00:00Z", "TC", "Gus J")
    validate_success(api.mark_fta(s["summons"]["id"], _CLERK))
    assert get_summons(s["summons"]["id"])["status"] == "FAILED_TO_APPEAR"
    strikes = validate_success(api.list_juror_strikes(s["juror"]["id"], _ADMIN))
    assert len(strikes) == 1, f"exactly one FTA strike expected, got {len(strikes)}"
    assert strikes[0]["source"] == "FTA"


def test_fta_cascade_disqualifies_and_recomputes_pool(api):
    """PRD §3.6: "Then the juror's `fta_strike_count` is recomputed as the count of
    FTA-sourced strike rows for that juror. The disqualification test is a threshold
    with an inclusive boundary: the juror's `disqualified` flag is set true exactly
    when `fta_strike_count` is greater than or equal to the term's
    `fta_disqualify_threshold`."
    PRD §3.6: "a juror who was `QUALIFIED` is driven to `INELIGIBLE`, and the term's
    `pool_size` is recomputed downward."

    Design: Difficulty/transitive_cascade/fta_strike_threshold_pool_cascade_depth3
    """
    s = _qualified_pending_threshold1("2026-07-06T08:00:00Z", "TCb", "Gus J")
    validate_success(api.mark_fta(s["summons"]["id"], _CLERK))
    juror = get_juror(s["juror"]["id"])
    assert juror["fta_strike_count"] == 1
    assert juror["disqualified"] is True
    assert juror["qualification_status"] == "INELIGIBLE"
    assert get_term(s["term"]["id"])["pool_size"] == 0


# ─── Difficulty: inclusive >= boundary at threshold 1 ──────────────────

def test_strike_count_below_threshold_not_disqualified(api):
    """PRD §3.6: "The boundary is inclusive — a count equal to the threshold
    disqualifies, and a count one below the threshold does not."

    Design: Difficulty/boundary_precision_check/fta_threshold_inclusive_boundary
    """
    s = _qualified_pending_threshold1("2026-07-13T08:00:00Z", "TG", "Jay J")
    # Before any strike: fta_strike_count 0 < threshold 1.
    juror = get_juror(s["juror"]["id"])
    assert juror["fta_strike_count"] == 0
    assert juror["disqualified"] is False


def test_strike_count_at_threshold_disqualifies(api):
    """PRD §3.6: "the juror's `disqualified` flag is set true exactly when
    `fta_strike_count` is greater than or equal to the term's
    `fta_disqualify_threshold`. The boundary is inclusive — a count equal to the
    threshold disqualifies."

    Design: Difficulty/boundary_precision_check/fta_threshold_inclusive_boundary
    """
    s = _qualified_pending_threshold1("2026-07-13T08:00:00Z", "TGb", "Jay J")
    validate_success(api.mark_fta(s["summons"]["id"], _CLERK))
    juror = get_juror(s["juror"]["id"])
    # count 1 >= threshold 1 → disqualified.
    assert juror["fta_strike_count"] == 1
    assert juror["disqualified"] is True
    assert juror["qualification_status"] == "INELIGIBLE"
