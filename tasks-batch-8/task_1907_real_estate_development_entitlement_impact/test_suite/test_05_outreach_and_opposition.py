"""Opposition scoring: per-disposition weights, posture thresholds, and exact
additive conservation with no clamping."""
from test_helpers import (
    assert_outreach_event,
    get_application,
    record_outreach,
    setup_submitted_application,
)


def test_two_oppose_events_score_ten_and_elevated(api):
    """PRD 3.5: "`SUPPORT` contributes −2, `NEUTRAL` contributes 0, `OPPOSE`
    contributes +5, and `ORGANIZED_OPPOSITION` contributes +12." and "the
    posture is `LOW` when the score is below 10, `ELEVATED` when the score is
    at least 10 but below 30, and `HIGH` when the score reaches 30. The
    thresholds are inclusive at their lower bound, so a score of exactly 10 is
    `ELEVATED` and exactly 30 is `HIGH`."

    Design: Difficulty/dual_variant_calc/opposition_posture_weighted_vs_threshold_recompute
    """
    ctx = setup_submitted_application(with_reviewer=True)
    first = record_outreach(ctx, "OPPOSE", "2026-08-03T00:00:00Z", attendee_count=20)
    assert_outreach_event(first)
    second = record_outreach(ctx, "OPPOSE", "2026-08-04T00:00:00Z", attendee_count=30)
    assert_outreach_event(second)

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["opposition_score"] == 10, (
        f"two OPPOSE events must score 5+5=10, got {after['opposition_score']}"
    )
    assert after["opposition_posture"] == "ELEVATED", (
        f"score 10 is ELEVATED (inclusive lower bound), got {after['opposition_posture']}"
    )


def test_support_weight_offsets_oppose_below_threshold(api):
    """PRD 3.5: "Recording an event immediately recomputes the application's
    `opposition_score` — the sum of weights across every event ever recorded
    for it — and its `opposition_posture`" with "`SUPPORT` contributes −2".
    PRD 3.5: an event carries "an `event_date`, a `disposition` of `SUPPORT`,
    `NEUTRAL`, `OPPOSE`, or `ORGANIZED_OPPOSITION`, and an informational
    `attendee_count` of at least one" — attendance plays no part in the score.

    Two OPPOSE (+10) plus one SUPPORT (−2) must land at 8 — LOW — whereas
    ignoring the SUPPORT weight would leave 10 and flip the posture to
    ELEVATED.

    Design: Difficulty/dual_variant_calc/opposition_posture_weighted_vs_threshold_recompute
    """
    ctx = setup_submitted_application(with_reviewer=True)
    record_outreach(ctx, "OPPOSE", "2026-08-03T00:00:00Z", attendee_count=500)
    record_outreach(ctx, "OPPOSE", "2026-08-04T00:00:00Z", attendee_count=500)
    record_outreach(ctx, "SUPPORT", "2026-08-05T00:00:00Z", attendee_count=1)

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["opposition_score"] == 8, (
        f"5+5−2 must equal 8 (attendee counts are informational), "
        f"got {after['opposition_score']}"
    )
    assert after["opposition_posture"] == "LOW", (
        f"score 8 is below 10, posture must be LOW, got {after['opposition_posture']}"
    )


def test_compensating_events_restore_score_to_zero(api):
    """PRD 3.5: "Recording an event immediately recomputes the application's
    `opposition_score` — the sum of weights across every event ever recorded
    for it — and its `opposition_posture`: the posture is `LOW` when the score
    is below 10".

    Two OPPOSE (+10) followed by five SUPPORT (−10) is a compensating sequence
    whose weights sum to exactly zero; the score must return to 0 with no
    clamping or drift.

    Design: Difficulty/compensating_invariant/opposition_score_add_remove_event_conservation
    """
    ctx = setup_submitted_application(with_reviewer=True)
    record_outreach(ctx, "OPPOSE", "2026-08-03T00:00:00Z")
    record_outreach(ctx, "OPPOSE", "2026-08-04T00:00:00Z")
    for day in range(5, 10):
        record_outreach(ctx, "SUPPORT", f"2026-08-{day:02d}T00:00:00Z")

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["opposition_score"] == 0, (
        f"2×(+5) + 5×(−2) must conserve the score at exactly 0, "
        f"got {after['opposition_score']}"
    )
    assert after["opposition_posture"] == "LOW"


def test_support_only_event_drives_score_negative_unclamped(api):
    """PRD 3.5: "Each event's disposition maps to a `weight`: `SUPPORT`
    contributes −2" and the score is "the sum of weights across every event
    ever recorded for it" — an arithmetic sum with no floor, so a lone SUPPORT
    event must leave the score at −2 rather than clamping to zero.

    Design: Difficulty/compensating_invariant/opposition_score_add_remove_event_conservation
    """
    ctx = setup_submitted_application(with_reviewer=True)
    event = record_outreach(ctx, "SUPPORT", "2026-08-03T00:00:00Z")
    assert event["weight"] == -2, f"SUPPORT weight must be −2, got {event['weight']}"

    after = get_application(ctx["application"]["id"], ctx["reviewer_headers"])
    assert after["opposition_score"] == -2, (
        f"raw weight sum must be −2 with no clamping, got {after['opposition_score']}"
    )
    assert after["opposition_posture"] == "LOW", (
        f"score −2 is below 10, posture must be LOW, got {after['opposition_posture']}"
    )
