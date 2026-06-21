"""Minor labor-law hour caps, suspended-worker block, worker availability /
double-booking, and cross-location referential integrity.

Covers Difficulty: dual_variant_calc (minor day-vs-week), boundary_precision_check
(minor weekly cap equal), resource_temporal_overlap (double-book + unavailable).
Covers Corner: error_cross_location_assignment.
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, make_worker_headers, set_clock, setup_location,
    setup_worker, setup_pay_period, create_posted_shift, assign_worker,
    add_availability,
)


M = make_manager_headers()


def test_minor_daily_cap_breached_by_same_day_pair(api):
    """PRD §3.9: "The daily projection sums the worker's SCHEDULED and CONFIRMED
    hours whose shift starts fall on the same location-local calendar day as the new
    shift, adds the new shift's hours, and the assignment is rejected if that daily
    total is strictly greater than the worker's daily cap."

    A 6h shift plus a 4h shift on the same Monday total 10h, breaching the 8h daily
    cap while staying under the 18h weekly cap -> ERR_MINOR_HOUR_CAP_EXCEEDED.

    Design: Difficulty/dual_variant_calc/minor_daily_vs_weekly_cap_window_divergence
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    minor = setup_worker(api, loc["id"], full_name="M", email="m@x.com",
                         base_hourly_rate_cents=2000, is_minor=True,
                         minor_daily_cap_hours=8, minor_weekly_cap_hours=18)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s6 = create_posted_shift(api, loc["id"], start_utc="2026-06-01T08:00:00Z",
                             end_utc="2026-06-01T14:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s6["id"], minor["id"])
    s4 = create_posted_shift(api, loc["id"], start_utc="2026-06-01T15:00:00Z",
                             end_utc="2026-06-01T19:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s4["id"], "worker_id": minor["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_MINOR_HOUR_CAP_EXCEEDED.value)


def test_minor_weekly_cap_breached_across_distinct_days(api):
    """PRD §3.9: "The weekly projection sums the worker's SCHEDULED and CONFIRMED
    hours across the new assignment's pay-period, adds the new shift's hours, and the
    assignment is rejected if that weekly total is strictly greater than the worker's
    weekly cap."

    Two 10h shifts on distinct days (each under the 24h daily cap) sum to 20h,
    breaching the 18h weekly cap -> ERR_MINOR_HOUR_CAP_EXCEEDED. This exercises the
    weekly window (distinct from the same-day daily-cap sibling).

    Design: Difficulty/dual_variant_calc/minor_daily_vs_weekly_cap_window_divergence
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    minor = setup_worker(api, loc["id"], full_name="M", email="m@x.com",
                         base_hourly_rate_cents=2000, is_minor=True,
                         minor_daily_cap_hours=24, minor_weekly_cap_hours=18)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s10a = create_posted_shift(api, loc["id"], start_utc="2026-06-01T08:00:00Z",
                               end_utc="2026-06-01T18:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s10a["id"], minor["id"])
    s10b = create_posted_shift(api, loc["id"], start_utc="2026-06-02T08:00:00Z",
                               end_utc="2026-06-02T18:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s10b["id"], "worker_id": minor["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_MINOR_HOUR_CAP_EXCEEDED.value)


def test_minor_weekly_cap_exactly_equal_allowed_via_award(api):
    """PRD §3.9: "A total exactly equal to a cap is allowed; only a strict excess
    violates."
    PRD §3.11: "Awarding the winner creates an assignment for that worker with source
    set to BID in SCHEDULED status — which runs the full scheduling battery of §3.9
    and §3.10."

    Minor already scheduled to 10h this pay-week; awarding an 8h open shift makes the
    weekly total exactly 18h (the cap), which is allowed, so the award succeeds with
    a BID assignment for the minor.

    Design: Difficulty/boundary_precision_check/minor_weekly_cap_exactly_equal_allowed
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    minor = setup_worker(api, loc["id"], full_name="M", email="m@x.com",
                         base_hourly_rate_cents=2000, is_minor=True,
                         minor_daily_cap_hours=24, minor_weekly_cap_hours=18)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s10 = create_posted_shift(api, loc["id"], start_utc="2026-06-01T08:00:00Z",
                              end_utc="2026-06-01T18:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s10["id"], minor["id"])
    s8 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T08:00:00Z",
                             end_utc="2026-06-02T16:00:00Z", headcount_required=1)
    s8v = s8["version"]
    bid = get_success_data(api.create_bid(loc["id"], s8["id"], {"seniority_score": 5},
                                          make_worker_headers(minor["id"])))
    resp = api.award_shift(loc["id"], s8["id"],
                           {"bid_id": bid["id"], "expected_shift_version": s8v}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["worker_id"] == minor["id"]


def test_minor_weekly_cap_one_over_rejected_via_award(api):
    """PRD §3.9: "the assignment is rejected if that weekly total is strictly greater
    than the worker's weekly cap. A total exactly equal to a cap is allowed; only a
    strict excess violates."
    PRD §3.11: "Awarding the winner creates an assignment for that worker with source
    set to BID in SCHEDULED status — which runs the full scheduling battery of §3.9
    and §3.10."

    Boundary partner of the equal-to-cap award: minor already at 10h, awarding a 9h
    shift would make the weekly total 19h, one hour over the 18h cap -> rejected.

    Design: Difficulty/boundary_precision_check/minor_weekly_cap_exactly_equal_allowed
    """
    set_clock(api, "2026-05-30T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    minor = setup_worker(api, loc["id"], full_name="M", email="m@x.com",
                         base_hourly_rate_cents=2000, is_minor=True,
                         minor_daily_cap_hours=24, minor_weekly_cap_hours=18)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s10 = create_posted_shift(api, loc["id"], start_utc="2026-06-01T08:00:00Z",
                              end_utc="2026-06-01T18:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s10["id"], minor["id"])
    s9 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T08:00:00Z",
                             end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    s9v = s9["version"]
    bid = get_success_data(api.create_bid(loc["id"], s9["id"], {"seniority_score": 5},
                                          make_worker_headers(minor["id"])))
    resp = api.award_shift(loc["id"], s9["id"],
                           {"bid_id": bid["id"], "expected_shift_version": s9v}, M)
    validate_error(resp, ApiErrorId.ERR_MINOR_HOUR_CAP_EXCEEDED.value)


def test_worker_double_book_overlap_rejected(api):
    """PRD §3.9: "no other non-terminal assignment for the worker may overlap the
    shift, where overlap is judged on a half-open basis so that exact adjacency — one
    shift ending precisely as the next begins, a zero gap — is allowed."

    A new shift 13:00..17:00 overlaps an existing 10:00..14:00 assignment by 1h ->
    ERR_WORKER_UNAVAILABLE.

    Design: Difficulty/resource_temporal_overlap/worker_double_book_overlap_halfopen_adjacency_ok
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s1 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T10:00:00Z",
                             end_utc="2026-06-02T14:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s1["id"], worker["id"])
    s2 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T13:00:00Z",
                             end_utc="2026-06-02T17:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s2["id"], "worker_id": worker["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_WORKER_UNAVAILABLE.value)


def test_worker_back_to_back_adjacency_allowed(api):
    """PRD §3.9: "no other non-terminal assignment for the worker may overlap the
    shift, where overlap is judged on a half-open basis so that exact adjacency — one
    shift ending precisely as the next begins, a zero gap — is allowed."

    A back-to-back shift starting 14:00 exactly when the prior 10:00..14:00 shift
    ends is a zero-gap adjacency under half-open semantics and is allowed.

    Design: Difficulty/resource_temporal_overlap/worker_double_book_overlap_halfopen_adjacency_ok
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s1 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T10:00:00Z",
                             end_utc="2026-06-02T14:00:00Z", headcount_required=1)
    assign_worker(api, loc["id"], s1["id"], worker["id"])
    s2 = create_posted_shift(api, loc["id"], start_utc="2026-06-02T14:00:00Z",
                             end_utc="2026-06-02T18:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s2["id"], "worker_id": worker["id"]}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_unavailable_window_closed_boundary_touch_blocks(api):
    """PRD §3.9: "no UNAVAILABLE availability window and no APPROVED time-off window
    may collide with the shift, where those windows are judged on a closed-interval
    basis so that merely touching a boundary instant is a collision."

    A shift starting 14:00 exactly at the closing instant of an UNAVAILABLE window
    [10:00,14:00] touches the closed boundary and is blocked -> ERR_WORKER_UNAVAILABLE.

    Design: Difficulty/resource_temporal_overlap/unavailable_window_closed_boundary_touch_blocks
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    add_availability(api, worker["id"], kind="UNAVAILABLE",
                     start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T14:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T14:00:00Z",
                            end_utc="2026-06-02T18:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s["id"], "worker_id": worker["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_WORKER_UNAVAILABLE.value)


def test_available_window_does_not_block_assignment(api):
    """PRD §3.1: "An AVAILABLE window is advisory only — it signals bid-eligibility
    and never blocks a scheduling decision on its own."

    An AVAILABLE window overlapping the shift (the same geometry that an UNAVAILABLE
    window would block on) is advisory and never blocks — assignment succeeds. This
    is the complement to the closed-boundary block on UNAVAILABLE windows.

    Design: Difficulty/resource_temporal_overlap/unavailable_window_closed_boundary_touch_blocks
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    worker = setup_worker(api, loc["id"], base_hourly_rate_cents=2000, email="w@x.com")
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    add_availability(api, worker["id"], kind="AVAILABLE",
                     start_utc="2026-06-02T10:00:00Z", end_utc="2026-06-02T18:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-02T14:00:00Z",
                            end_utc="2026-06-02T18:00:00Z", headcount_required=1)
    resp = api.create_assignment(loc["id"], {"shift_id": s["id"], "worker_id": worker["id"]}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"


def test_cross_location_assignment_rejected(api):
    """PRD §3.9: "the worker being assigned, awarded, or bidding must belong to the
    same location_id as the shift, and in a swap the counter assignment must belong
    to the counterparty being asked to take the shift; a mismatch is rejected with
    ERR_CROSS_LOCATION."

    Assigning a worker registered at L2 to an OPEN shift in L1 -> ERR_CROSS_LOCATION.

    Design: Corner/errors/error_cross_location_assignment
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    l1 = setup_location(api, name="L1", predictability_pay_enabled=False, advance_notice_days=1)
    l2 = setup_location(api, name="L2", predictability_pay_enabled=False, advance_notice_days=1)
    w2 = setup_worker(api, l2["id"], full_name="W2", email="w2@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, l1["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s1 = create_posted_shift(api, l1["id"], start_utc="2026-06-05T09:00:00Z",
                             end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    resp = api.create_assignment(l1["id"], {"shift_id": s1["id"], "worker_id": w2["id"]}, M)
    validate_error(resp, ApiErrorId.ERR_CROSS_LOCATION.value)
