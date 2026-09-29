"""Half-open rate intervals against closed mini-bid windows.

The two window semantics in this system are deliberately different. A rate record's
effective interval excludes its end, so two records that meet at an instant are a
clean handover; a mini-bid window includes both endpoints, so windows that merely
touch do collide. The cooldown and the rolling quota then sit behind the conflict
check, and only become reachable once it has passed.
"""

from test_helpers import (
    api_client,
    assert_same_instant,
    CATEGORY_MANAGER,
    CONTRACT_ADMIN,
    get_success_data,
    load_rate_record,
    mini_bid_payload,
    propose_mini_bid_rate,
    read_contract,
    read_rate_record,
    set_clock,
    setup_applied_mini_bid,
    setup_awarded_event,
    stage_rate_record,
    validate_error,
)

# Three rate intervals inside the contract window: two adjacent, one straddling.
R1_WINDOW = {"effective_from": "2026-09-01T00:00:00Z", "effective_to": "2026-12-01T00:00:00Z"}
R2_WINDOW = {"effective_from": "2026-12-01T00:00:00Z", "effective_to": "2027-03-01T00:00:00Z"}
R3_WINDOW = {"effective_from": "2026-11-01T00:00:00Z", "effective_to": "2027-01-01T00:00:00Z"}

# The applied mini-bid's closed window, and the rate it moved the lane to.
MB1_WINDOW = {
    "window_open_at": "2026-09-01T00:00:00Z",
    "window_close_at": "2026-09-11T00:00:00Z",
}
MB1_PROPOSED_RATE = 2.2000
MB1_APPLIED_AT = "2026-09-05T00:00:00Z"

# The cooldown of 7 days measured from 2026-09-05 lands exactly on 2026-09-12.
COOLDOWN_BOUNDARY = "2026-09-12T00:00:00Z"


def _attempt_mini_bid(ctx, rate_record_id, **overrides):
    """Requests a mini-bid window without asserting success."""
    return api_client.create_mini_bid(
        mini_bid_payload(
            ctx["event"]["id"], ctx["lane"]["id"], rate_record_id, **overrides
        ),
        CATEGORY_MANAGER,
    )


def _lane_mini_bids(lane_id):
    body = get_success_data(
        api_client.list_mini_bids(CATEGORY_MANAGER, {"lane_id": lane_id})
    )
    return body["data"] if isinstance(body, dict) and "data" in body else body


def _three_staged_records():
    """An awarded contract carrying R1, R2 and R3 all staged, none loaded."""
    ctx = setup_awarded_event()
    for key, window in (("r1", R1_WINDOW), ("r2", R2_WINDOW), ("r3", R3_WINDOW)):
        ctx[key] = stage_rate_record(
            ctx["contract"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            ctx["allocation"]["id"],
            **window,
        )
    return ctx


class TestRateIntervalHalfOpenSemantics:
    """Rate intervals exclude their end, so touching is adjacency, not collision."""

    def test_two_adjacent_intervals_sharing_one_instant_both_load(self):
        """R1 ends where R2 begins, and both reach LOADED.

        PRD §3.8: "Intervals are **half-open**, running from `effective_from`
        inclusive to `effective_to` exclusive, so two records where one's
        `effective_to` is exactly the other's `effective_from` are adjacent and do
        **not** overlap — that is how a mid-contract rate change is expressed as a
        clean handover rather than a collision."
        PRD §3.8: "On success the record moves from `STAGED` to `LOADED`, `loaded_at`
        is set to the logical clock, and on the contract's first loaded record the
        contract's `rate_load_status` moves from `STAGED` to `LOADED`."

        Design: Difficulty/resource_temporal_overlap/rate_record_half_open_interval_overlap_and_adjacency
        """
        ctx = _three_staged_records()
        load_rate_record(ctx["r1"]["id"])
        assert read_rate_record(ctx["r1"]["id"])["status"] == "LOADED"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LOADED"

        load_rate_record(ctx["r2"]["id"])
        assert read_rate_record(ctx["r2"]["id"])["status"] == "LOADED", (
            "sharing the 2026-12-01 instant is adjacency, because R1 excludes its end"
        )

    def test_an_interval_straddling_the_handover_is_rejected_as_an_overlap(self):
        """R3 intersects both loaded records, so the load is refused.

        PRD §3.8: "the record's effective interval must not collide with an existing
        one: no other rate record sharing the same `lane_id`, `carrier_id` and
        `routing_position`, and whose `status` is `LOADED`, `LIVE` or `AT_RISK`, may
        have an overlapping interval, otherwise `ERR_RATE_INTERVAL_OVERLAP` (409)"
        PRD §2.9: "Rate intervals and mini-bid windows must not collide, raising
        `ERR_RATE_INTERVAL_OVERLAP`, `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW`,
        `ERR_MINI_BID_WINDOW_CONFLICT` or `ERR_MINI_BID_COOLDOWN_ACTIVE` (all 409)"

        Design: Difficulty/resource_temporal_overlap/rate_record_half_open_interval_overlap_and_adjacency
        """
        ctx = _three_staged_records()
        load_rate_record(ctx["r1"]["id"])
        load_rate_record(ctx["r2"]["id"])

        response = api_client.load_rate_record(ctx["r3"]["id"], CONTRACT_ADMIN)
        validate_error(response, "ERR_RATE_INTERVAL_OVERLAP", 409)

        rejected = read_rate_record(ctx["r3"]["id"])
        assert rejected["status"] == "STAGED"
        assert rejected["loaded_at"] is None
        assert read_rate_record(ctx["r1"]["id"])["status"] == "LOADED"
        assert read_rate_record(ctx["r2"]["id"])["status"] == "LOADED"

    def test_the_collision_check_lives_on_loading_and_not_on_staging(self):
        """All three records stage without complaint, overlaps included.

        PRD §2.9: "Rate intervals and mini-bid windows must not collide, raising
        `ERR_RATE_INTERVAL_OVERLAP`, `ERR_RATE_NOT_IN_EFFECTIVE_WINDOW`,
        `ERR_MINI_BID_WINDOW_CONFLICT` or `ERR_MINI_BID_COOLDOWN_ACTIVE` (all 409) as
        detailed in §3.8 and §3.9. This rung applies to rate-record loading, rate
        go-live, mini-bid creation and mini-bid apply."
        PRD §2.12: "`Contract.rate_record_count` counts the contract's rate records
        whose status is `STAGED`, `LOADED`, `LIVE` or `AT_RISK`."

        Design: Difficulty/resource_temporal_overlap/rate_record_half_open_interval_overlap_and_adjacency
        """
        ctx = setup_awarded_event()
        r1 = stage_rate_record(
            ctx["contract"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            ctx["allocation"]["id"],
            **R1_WINDOW,
        )
        load_rate_record(r1["id"])
        # R3 overlaps a record that is already LOADED, and still stages cleanly.
        for window in (R2_WINDOW, R3_WINDOW):
            staged = stage_rate_record(
                ctx["contract"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                ctx["allocation"]["id"],
                **window,
            )
            assert staged["status"] == "STAGED"
        assert read_contract(ctx["contract"]["id"])["rate_record_count"] == 3


class TestMiniBidWindowCooldownAndQuota:
    """Three distinct temporal gates, reachable only in ladder order."""

    @staticmethod
    def _lane_with_one_applied_mini_bid():
        """A lane whose rate was adjusted to 2.2000 by a mini-bid applied on 09-05."""
        ctx = setup_applied_mini_bid(
            proposed_rate_per_mile=MB1_PROPOSED_RATE,
            mini_bid_overrides=dict(MB1_WINDOW),
            proposal_clock=MB1_APPLIED_AT,
        )
        assert ctx["mini_bid"]["status"] == "APPLIED"
        assert float(ctx["mini_bid"]["adjustment_pct"]) == 10.00
        assert_same_instant(ctx["mini_bid"]["applied_at"], MB1_APPLIED_AT, "applied_at")
        return ctx

    def test_a_window_touching_the_applied_window_is_a_conflict(self):
        """Closed intervals mean an intersecting window is refused outright.

        PRD §3.9: "The requested window must not intersect the window of any other
        mini-bid on the same lane whose `status` is `REQUESTED`, `OPEN` or `APPLIED`."
        PRD §3.9: "The comparison treats each window as a **closed** interval from
        `window_open_at` through `window_close_at` inclusive, so windows that merely
        touch at an endpoint do conflict."

        Design: Difficulty/resource_temporal_overlap/mini_bid_closed_window_conflict_cooldown_and_rolling_quota
        """
        ctx = self._lane_with_one_applied_mini_bid()
        response = _attempt_mini_bid(
            ctx,
            ctx["replacement_record"]["id"],
            window_open_at="2026-09-08T00:00:00Z",
            window_close_at="2026-09-18T00:00:00Z",
        )
        validate_error(response, "ERR_MINI_BID_WINDOW_CONFLICT", 409)
        assert len(_lane_mini_bids(ctx["lane"]["id"])) == 1

    def test_a_window_clear_of_the_conflict_can_still_sit_inside_the_cooldown(self):
        """Half a day past the closed window clears rung 14's first check only.

        PRD §3.9: "`window_open_at` must be at least the cooldown of 7 days after the
        `applied_at` of the lane's most recently applied mini-bid."
        PRD §3.9: "A lane whose rate was adjusted three days ago cannot immediately be
        reopened; the attempt is rejected with `ERR_MINI_BID_COOLDOWN_ACTIVE` (409)."

        Design: Difficulty/resource_temporal_overlap/mini_bid_closed_window_conflict_cooldown_and_rolling_quota
        """
        ctx = self._lane_with_one_applied_mini_bid()
        response = _attempt_mini_bid(
            ctx,
            ctx["replacement_record"]["id"],
            window_open_at="2026-09-11T12:00:00Z",
            window_close_at="2026-09-20T00:00:00Z",
        )
        validate_error(response, "ERR_MINI_BID_COOLDOWN_ACTIVE", 409)
        assert len(_lane_mini_bids(ctx["lane"]["id"])) == 1

    def test_the_cooldown_boundary_is_inclusive_at_exactly_seven_days(self):
        """Twelve hours later the identical shape of window is accepted.

        PRD §3.9: "`window_open_at` must be at least the cooldown of 7 days after the
        `applied_at` of the lane's most recently applied mini-bid."
        PRD §3.9: "The mini-bid is created with `status` `REQUESTED` and `origin`
        `MANUAL`, distinguishing it from the automatically generated ones"

        Design: Difficulty/resource_temporal_overlap/mini_bid_closed_window_conflict_cooldown_and_rolling_quota
        """
        ctx = self._lane_with_one_applied_mini_bid()
        validate_error(
            _attempt_mini_bid(
                ctx,
                ctx["replacement_record"]["id"],
                window_open_at="2026-09-11T12:00:00Z",
                window_close_at="2026-09-20T00:00:00Z",
            ),
            "ERR_MINI_BID_COOLDOWN_ACTIVE",
            409,
        )

        accepted = get_success_data(
            _attempt_mini_bid(
                ctx,
                ctx["replacement_record"]["id"],
                window_open_at=COOLDOWN_BOUNDARY,
                window_close_at="2026-09-22T00:00:00Z",
            ),
            201,
        )
        assert accepted["status"] == "REQUESTED"
        assert accepted["origin"] == "MANUAL"
        assert_same_instant(
            accepted["window_open_at"], COOLDOWN_BOUNDARY, "window_open_at"
        )
        assert len(_lane_mini_bids(ctx["lane"]["id"])) == 2

    def test_a_third_negotiated_window_inside_ninety_days_exceeds_the_quota(self):
        """The quota only becomes reachable once both temporal checks pass.

        PRD §3.9: "A lane may hold at most 2 mini-bids whose `status` is `OPEN` or
        `APPLIED` and whose `window_open_at` falls within the trailing quota window of
        90 days measured back from the requested `window_open_at`."
        PRD §3.9: "The quota counts windows that actually reached negotiation or
        adjustment; mini-bids still `REQUESTED`, or that ended `DENIED` or `REVERTED`,
        do not consume quota."
        PRD §2.9: "A lane may not exceed its rolling mini-bid quota, otherwise
        `ERR_MINI_BID_QUOTA_EXCEEDED` (409). This applies to mini-bid creation."

        Design: Difficulty/resource_temporal_overlap/mini_bid_closed_window_conflict_cooldown_and_rolling_quota
        """
        ctx = self._lane_with_one_applied_mini_bid()
        second = get_success_data(
            _attempt_mini_bid(
                ctx,
                ctx["replacement_record"]["id"],
                window_open_at=COOLDOWN_BOUNDARY,
                window_close_at="2026-09-22T00:00:00Z",
            ),
            201,
        )
        # A REQUESTED window consumes no quota, so it must be negotiated first.
        set_clock(COOLDOWN_BOUNDARY)
        opened = propose_mini_bid_rate(
            second["id"], ctx["carrier"]["id"], proposed_rate_per_mile=2.3000
        )
        assert opened["status"] == "OPEN"

        response = _attempt_mini_bid(
            ctx,
            ctx["replacement_record"]["id"],
            window_open_at="2026-09-23T00:00:00Z",
            window_close_at="2026-09-30T00:00:00Z",
        )
        validate_error(response, "ERR_MINI_BID_QUOTA_EXCEEDED", 409)
        assert len(_lane_mini_bids(ctx["lane"]["id"])) == 2, (
            "no rejected request may leave a mini-bid row behind"
        )
