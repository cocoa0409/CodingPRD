"""Open-shift bid winner selection and optimistic-concurrency award guard.

Covers Corner: award_non_winning_bid (BID winner selection),
occ_stale_shift_version_on_award (OCC 412).
"""
from test_helpers import (
    validate_success, validate_error, get_success_data, ApiErrorId,
    make_manager_headers, make_worker_headers, set_clock, setup_location,
    setup_worker, setup_pay_period, create_posted_shift,
)


M = make_manager_headers()


def test_award_non_winning_bid_rejected(api):
    """PRD §3.11: "The winner is selected among the shift's SUBMITTED bids only
    (AWARDED, REJECTED, and WITHDRAWN bids are excluded) by highest seniority_score,
    breaking ties toward the earliest created_at; the resource id is never used as a
    tie-break. A manager who names any other bid is rejected with ERR_BID_NOT_WINNER."

    Two SUBMITTED bids (seniority 9 and 3); awarding the seniority-3 (non-winning)
    bid -> ERR_BID_NOT_WINNER.

    Design: Corner/state_machines/award_non_winning_bid_returns_bid_not_winner
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com", base_hourly_rate_cents=2000)
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    sv = s["version"]
    get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 9},
                                    make_worker_headers(wa["id"])))
    bid_b = get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 3},
                                            make_worker_headers(wb["id"])))
    resp = api.award_shift(loc["id"], s["id"],
                           {"bid_id": bid_b["id"], "expected_shift_version": sv}, M)
    validate_error(resp, ApiErrorId.ERR_BID_NOT_WINNER.value)


def test_award_winning_bid_creates_bid_assignment(api):
    """PRD §3.11: "Awarding the winner creates an assignment for that worker with
    source set to BID in SCHEDULED status ... moves the winning bid to AWARDED, and
    increments the shift's version by one."

    Complement to the non-winner rejection: awarding the highest-seniority bid (9)
    creates a SCHEDULED BID assignment for that bidder.

    Design: Corner/state_machines/award_non_winning_bid_returns_bid_not_winner
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com", base_hourly_rate_cents=2000)
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=1)
    sv = s["version"]
    bid_a = get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 9},
                                            make_worker_headers(wa["id"])))
    get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 3},
                                    make_worker_headers(wb["id"])))
    resp = api.award_shift(loc["id"], s["id"],
                           {"bid_id": bid_a["id"], "expected_shift_version": sv}, M)
    data = validate_success(resp, 201)
    assert data["status"] == "SCHEDULED"
    assert data["source"] == "BID"
    assert data["worker_id"] == wa["id"]


def test_stale_shift_version_on_second_award_returns_412(api):
    """PRD §2.11: "The server compares it to the shift's current version; if another
    award has advanced the version since the manager read it ... the write is refused
    with ERR_STALE_SHIFT_VERSION (HTTP 412)."
    PRD §2.11: "a successful award is itself what increments the shift's version by
    one."

    A two-seat shift with two SUBMITTED bids: the first award (carrying the observed
    version) succeeds and bumps the version; a second award still carrying the now-stale
    pre-award version -> ERR_STALE_SHIFT_VERSION (412).

    Design: Corner/cross_cutting_complexity_layers/occ_stale_shift_version_on_award_returns_412
    """
    set_clock(api, "2026-06-01T00:00:00Z")
    loc = setup_location(api, predictability_pay_enabled=False, advance_notice_days=1)
    wa = setup_worker(api, loc["id"], full_name="WA", email="wa@x.com", base_hourly_rate_cents=2000)
    wb = setup_worker(api, loc["id"], full_name="WB", email="wb@x.com", base_hourly_rate_cents=2000)
    setup_pay_period(api, loc["id"], start_utc="2026-06-01T00:00:00Z",
                     end_utc="2026-06-08T00:00:00Z")
    s = create_posted_shift(api, loc["id"], start_utc="2026-06-05T09:00:00Z",
                            end_utc="2026-06-05T13:00:00Z", headcount_required=2)
    sv = s["version"]  # observed BEFORE the first award
    bid_a = get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 9},
                                            make_worker_headers(wa["id"])))
    bid_b = get_success_data(api.create_bid(loc["id"], s["id"], {"seniority_score": 5},
                                            make_worker_headers(wb["id"])))
    get_success_data(api.award_shift(loc["id"], s["id"],
                                     {"bid_id": bid_a["id"], "expected_shift_version": sv}, M))
    resp = api.award_shift(loc["id"], s["id"],
                           {"bid_id": bid_b["id"], "expected_shift_version": sv}, M)
    validate_error(resp, ApiErrorId.ERR_STALE_SHIFT_VERSION.value, 412)
