"""Feedback rollup: pinned per-feedback-round-then-average order."""
import pytest

from test_helpers import (
    api_client,
    create_feedback_payload,
    get_feedback_request_id,
    get_success_data,
    setup_completed_showing,
    setup_vacant_auto_world,
    validate_success,
)


def _setup_three_completed_showings():
    """VACANT auto listing with three COMPLETED showings whose feedback
    requests are SENT. Returns (world, listing_id, [f1, f2, f3])."""
    world = setup_vacant_auto_world()
    listing_id = world["listing"]["id"]
    fids = []
    # Windows are spaced 3h apart so each intake satisfies the listing's
    # default min_notice_minutes=120 lead-time floor measured from the clock
    # position left behind by the previous iteration's redeem/sweep.
    for start, end, redeem_at, sweep_at in (
        ("2026-05-01T10:00:00Z", "2026-05-01T10:30:00Z", "2026-05-01T10:05:00Z", None),
        ("2026-05-01T13:00:00Z", "2026-05-01T13:30:00Z", "2026-05-01T13:05:00Z", None),
        ("2026-05-01T16:00:00Z", "2026-05-01T16:30:00Z", "2026-05-01T16:05:00Z", "2026-05-01T16:45:00Z"),
    ):
        req, _cred = setup_completed_showing(
            world, start_at=start, end_at=end, redeem_at=redeem_at,
            sweep_at=sweep_at or redeem_at,
        )
        fids.append(req["id"])
    # The last setup swept at 16:45, past every window's end; sweep once more at
    # the same reading to complete all three (idempotent for already-completed).
    from test_helpers import run_sweep, set_clock
    set_clock("2026-05-01T16:45:00Z")
    run_sweep()
    feedback_ids = [get_feedback_request_id(world, rid) for rid in fids]
    return world, listing_id, feedback_ids


def test_feedback_rollup_per_feedback_scores(api):
    """PRD §3.7: "The per-feedback leg computes the request's `overall_score`
    as a weighted blend — 0.30 of `q1`, 0.25 of `q2`, 0.20 of `q3`, 0.15 of
    `q4`, and 0.10 of `q5` — rounded half-up to exactly 1 decimal place."

    Design: Difficulty/combinatorial_formula/feedback_rollup_per_feedback_rounding_order
    """
    world, listing_id, (f1, f2, f3) = _setup_three_completed_showings()
    ba_headers = world["ba_headers"]

    # raw 0.30*4 + 0.25*5 + 0.20*4 + 0.15*4 + 0.10*4 == 4.25 -> 4.3 half-up
    r1 = validate_success(api_client.submit_feedback(
        f1, create_feedback_payload(q1=4, q2=5, q3=4, q4=4, q5=4), ba_headers))
    assert r1["overall_score"] == pytest.approx(4.3, abs=1e-9), r1

    r2 = validate_success(api_client.submit_feedback(
        f2, create_feedback_payload(q1=4, q2=5, q3=4, q4=4, q5=4), ba_headers))
    assert r2["overall_score"] == pytest.approx(4.3, abs=1e-9), r2

    # raw 0.30*4 + 0.25*4 + 0.20*5 + 0.15*4 + 0.10*4 == 4.20 -> 4.2 half-up
    r3 = validate_success(api_client.submit_feedback(
        f3, create_feedback_payload(q1=4, q2=4, q3=5, q4=4, q5=4), ba_headers))
    assert r3["overall_score"] == pytest.approx(4.2, abs=1e-9), r3


def test_feedback_rollup_listing_average_uses_rounded_scores(api):
    """PRD §3.7: "The rollup leg then recomputes the listing's
    `avg_feedback_score` as the mean of the already-rounded per-feedback scores
    across all of that listing's SUBMITTED feedback requests, itself rounded
    half-up to 1 decimal place" and "Averaging the raw unrounded blends and
    rounding once at the end is forbidden, because it diverges — raw scores of
    4.25, 4.25, and 4.20 average to 4.3 under the pinned order but 4.2 under
    the aggregate-first shortcut."

    Design: Difficulty/combinatorial_formula/feedback_rollup_per_feedback_rounding_order
    """
    world, listing_id, (f1, f2, f3) = _setup_three_completed_showings()
    ba_headers = world["ba_headers"]

    api_client.submit_feedback(f1, create_feedback_payload(q1=4, q2=5, q3=4, q4=4, q5=4), ba_headers)
    api_client.submit_feedback(f2, create_feedback_payload(q1=4, q2=5, q3=4, q4=4, q5=4), ba_headers)
    api_client.submit_feedback(f3, create_feedback_payload(q1=4, q2=4, q3=5, q4=4, q5=4), ba_headers)

    listing = validate_success(api_client.get_listing(listing_id, world["la_headers"]))
    # pinned: mean(4.3, 4.3, 4.2) = 4.2667 -> 4.3; aggregate-first would give 4.2
    assert listing["avg_feedback_score"] == pytest.approx(4.3, abs=1e-9), listing
