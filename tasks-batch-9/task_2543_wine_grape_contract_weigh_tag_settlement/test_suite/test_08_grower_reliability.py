"""Producer reliability: the same stored misbehaviour read at two different scopes."""
from test_helpers import (
    list_settlement_lines,
    read_grower,
    read_pick_call,
    read_weigh_tag,
    record_grading,
    setup_prior_vintage_expiry_then_current_rejection,
)


def _rejected_current_vintage_load() -> dict:
    """A 2025 pick call left to expire, then a 2026 load rejected on rot."""
    ctx = setup_prior_vintage_expiry_then_current_rejection()
    ctx["grading"] = record_grading(
        ctx["tag"]["id"], brix=24.5, ta_gl=6.5, ph=3.55, rot_pct=9.0, mog_pct=0.5
    )
    return ctx


def test_rot_at_or_above_the_rejection_threshold_rejects_the_whole_load():
    """A 9.0 percent rot reading against a specification that rejects at 8.0 condemns
    the load, and a rejected load is never priced.

    PRD: "When and only when `recommended_disposition` is `ACCEPT`, the load's
    `net_tons` is poured through three buckets, strictly in order, each bucket filling
    completely before the next receives anything."

    Design: Difficulty/dual_variant_calc/grower_reliability_vintage_scope_versus_lifetime_scope_divergence
    """
    ctx = _rejected_current_vintage_load()

    tag = read_weigh_tag(ctx["tag"]["id"])
    assert tag["disposition"] == "REJECTED_QUALITY"
    assert ctx["grading"]["recommended_disposition"] == "REJECT_QUALITY"
    assert list_settlement_lines(weigh_tag_id=tag["id"]) == []


def test_an_unacknowledged_call_expires_once_the_clock_passes_its_deadline():
    """The 2025 call was never acknowledged, so the clock closed it out.

    PRD: "When the logical clock advances strictly past `ack_deadline_at` while the call
    is still `ISSUED`, it transitions `ISSUED → EXPIRED`, and that expiry counts against
    the producer"

    Design: Difficulty/dual_variant_calc/grower_reliability_vintage_scope_versus_lifetime_scope_divergence
    """
    ctx = _rejected_current_vintage_load()

    assert read_pick_call(ctx["pick_call_2025"]["id"])["status"] == "EXPIRED"


def test_counters_are_bucketed_by_the_calendar_year_of_each_row():
    """With the clock in 2026, the rejected load counts against the current vintage
    while the 2025 expiry has moved into the prior-vintage bucket.

    PRD: "`prior_vintage_penalty_units` is the same weighted sum computed over every UTC
    calendar year strictly before the current vintage."

    Design: Difficulty/dual_variant_calc/grower_reliability_vintage_scope_versus_lifetime_scope_divergence
    """
    ctx = _rejected_current_vintage_load()

    grower = read_grower(ctx["grower"]["id"])
    assert grower["rejected_load_count_vintage"] == 1
    assert grower["expired_pick_call_count_vintage"] == 0
    assert grower["prior_vintage_penalty_units"] == 5


def test_the_two_reliability_scopes_diverge_on_identical_rows():
    """The vintage score ignores history entirely; the lifetime score halves the prior
    5 units and rounds that half up to a whole 3 before subtracting it.

    PRD: "With a current penalty of 8 units and a prior penalty of 5 units the two
    scores read 92.0 and 89.0 from identical rows"

    Design: Difficulty/dual_variant_calc/grower_reliability_vintage_scope_versus_lifetime_scope_divergence
    """
    ctx = _rejected_current_vintage_load()

    grower = read_grower(ctx["grower"]["id"])
    assert float(grower["reliability_score_vintage"]) == 92.0
    assert float(grower["reliability_score_lifetime"]) == 89.0
    assert float(grower["reliability_score_vintage"]) - float(grower["reliability_score_lifetime"]) == 3.0
