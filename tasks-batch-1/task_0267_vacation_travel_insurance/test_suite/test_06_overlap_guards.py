"""Coverage-overlap and delay-event temporal guards (§3.7).

Covers difficulty rule resource_temporal_overlap: the half-open coverage interval
(overlap rejected, adjacency allowed) and the closed-interval-plus-6h delay-event buffer.
"""
from test_helpers import (
    validate_success, validate_error,
    set_clock, create_plan, create_traveler, create_quoted_policy, add_insured,
    setup_active_policy, file_claim, make_traveler_headers,
    create_insured_traveler_payload, create_claim_payload,
)


# ─── resource_temporal_overlap: coverage interval half-open ────────────────

def test_overlapping_coverage_interval_rejected(api):
    """PRD §3.7: "the system checks the trip-coverage interval — the half-open interval from
    `trip_start_at` up to but not including `trip_end_at` — against that same underlying
    traveler's intervals on their other policies. Any overlap is rejected with
    `ERR_COVERAGE_OVERLAP`."

    Traveler covered on P1 (07-01 .. 07-15); adding the same traveler to P2 (07-10 .. 07-20)
    overlaps and is rejected.

    Design: Difficulty/resource_temporal_overlap/traveler_coverage_intervals_half_open_adjacency_allowed
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    p1 = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                              trip_start_at="2026-07-01T00:00:00Z",
                              trip_end_at="2026-07-15T00:00:00Z")
    add_insured(p1["id"], traveler["id"], covered_trip_cost_cents=500000)
    p2 = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=400000,
                              trip_start_at="2026-07-10T00:00:00Z",
                              trip_end_at="2026-07-20T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    res = api.add_insured_traveler(
        p2["id"], create_insured_traveler_payload(traveler["id"], covered_trip_cost_cents=400000),
        headers)
    validate_error(res, "ERR_COVERAGE_OVERLAP")


def test_adjacent_coverage_interval_allowed(api):
    """PRD §3.7: "Because the interval is half-open, two trips that merely touch at an endpoint
    (one's `trip_end_at` equal to the next's `trip_start_at`) do not overlap and are allowed."

    Traveler covered on P1 (07-01 .. 07-15); adding to P2 starting exactly 07-15 (back-to-back)
    does not overlap and is accepted.

    Design: Difficulty/resource_temporal_overlap/traveler_coverage_intervals_half_open_adjacency_allowed
    """
    plan = create_plan(tier="BASIC", base_rate_bps=400)
    traveler = create_traveler()
    p1 = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=500000,
                              trip_start_at="2026-07-01T00:00:00Z",
                              trip_end_at="2026-07-15T00:00:00Z")
    add_insured(p1["id"], traveler["id"], covered_trip_cost_cents=500000)
    p2 = create_quoted_policy(plan["id"], traveler["id"], trip_cost_cents=400000,
                              trip_start_at="2026-07-15T00:00:00Z",
                              trip_end_at="2026-07-25T00:00:00Z")
    headers = make_traveler_headers(traveler["id"])
    res = api.add_insured_traveler(
        p2["id"], create_insured_traveler_payload(traveler["id"], covered_trip_cost_cents=400000),
        headers)
    insured = validate_success(res, 201)
    assert insured["status"] == "COVERED", \
        "back-to-back adjacent coverage interval must be allowed (half-open semantics)"


# ─── resource_temporal_overlap: delay-event closed interval + buffer ───────

def test_second_delay_claim_within_buffer_rejected(api):
    """PRD §3.7: "When a `DELAY` claim is filed against a policy that already has a `DELAY` claim
    whose covered delay window falls within a six-hour buffer of the new one, the two are treated
    as the same event and the second is rejected with `ERR_DELAY_EVENT_OVERLAP`. The comparison
    is a closed interval extended by the six-hour merge buffer."

    First DELAY claim incident 06-05T00:00 (delay 12h, window through 06-05T12:00); a second
    DELAY claim incident 06-05T15:00 falls within the 6-hour buffer and is rejected.

    Design: Difficulty/resource_temporal_overlap/delay_claim_events_closed_interval_with_buffer_merge
    """
    active = setup_active_policy(plan_overrides={"base_rate_bps": 600}, clock="2026-06-01T00:00:00Z")
    file_claim(active["policy"]["id"], active["insured"]["id"], active["traveler_id"],
               "DELAY", "2026-06-05T00:00:00Z", delay_hours=12)
    headers = make_traveler_headers(active["traveler_id"])
    res = api.create_claim(create_claim_payload(
        active["policy"]["id"], active["insured"]["id"], "DELAY", "2026-06-05T15:00:00Z",
        delay_hours=12), headers)
    validate_error(res, "ERR_DELAY_EVENT_OVERLAP")


def test_distant_second_delay_claim_accepted(api):
    """PRD §3.7: "the two are treated as the same event and the second is rejected with
    `ERR_DELAY_EVENT_OVERLAP`. The comparison is a closed interval extended by the six-hour merge
    buffer."

    A second DELAY claim fifteen days after the first (incident 06-20 vs 06-05) is far outside
    the six-hour merge buffer and is therefore a distinct event that is accepted.

    Design: Difficulty/resource_temporal_overlap/delay_claim_events_closed_interval_with_buffer_merge
    """
    active = setup_active_policy(plan_overrides={"base_rate_bps": 600}, clock="2026-06-01T00:00:00Z")
    file_claim(active["policy"]["id"], active["insured"]["id"], active["traveler_id"],
               "DELAY", "2026-06-05T00:00:00Z", delay_hours=12)
    second = file_claim(active["policy"]["id"], active["insured"]["id"], active["traveler_id"],
                        "DELAY", "2026-06-20T00:00:00Z", delay_hours=12)
    assert second["status"] == "SUBMITTED", \
        "a delay claim far outside the 6-hour buffer must be accepted as a distinct event"
