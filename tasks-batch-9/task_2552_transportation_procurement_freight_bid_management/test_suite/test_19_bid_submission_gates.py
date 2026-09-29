"""The gates a lane bid passes on its way into an open round.

Two of them are boundaries: the rate floor is inclusive, so one hundredth below
it is refused and the floor value itself is priced normally, and the transit
requirement is inclusive too. The last pair is an ordering: an absent invitation
and an unaccepted one are different answers, and the second check only runs once
the first has passed.
"""

from test_helpers import (
    ANALYST,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
    api_client,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    invite_carrier,
    lane_bid_payload,
    make_carrier_rep_headers,
    open_round,
    read_event,
    second_carrier_overrides,
    set_clock,
    setup_open_round_with_bidder,
    submit_bid,
    validate_error,
    validate_paginated,
    validate_success,
)

#: The event's declared floor, and the two rates that straddle it.
RATE_FLOOR_PER_MILE = TEST_DEFAULTS["EVENT_RATE_FLOOR_PER_MILE"]
RATE_BELOW_FLOOR = 1.4900
RATE_AT_FLOOR = 1.5000
#: What adding the fuel index to the refused rate would have produced.
FUEL_ADJUSTED_RATE = 1.9700

# round(1147 x 1.5000, 2), round(137.55 x 1.15, 2), and their sum.
FLOOR_LINEHAUL_USD = 1720.50
FLOOR_ACCESSORIAL_USD = 158.18
FLOOR_COST_PER_LOAD_USD = 1878.68
#: min(600 committed, round(550 x 1.20) == 660).
FLOOR_AWARDABLE_LOADS = 600
FLOOR_EVALUATED_TOTAL_USD = 1127208.00
# The 90.60-scoring carrier earns the capped 5% credit: round(1127208.00 x 0.95, 2).
FLOOR_SERVICE_CREDIT_PCT = 0.0500
FLOOR_COST_RANK_SCORE = 1070847.60

#: The lane accepts three transit days; the refused bid offers four.
LANE_SERVICE_DAYS = TEST_DEFAULTS["LANE_A_SERVICE_DAYS_REQUIRED"]
TRANSIT_DAYS_TOO_MANY = 4
COMPETITIVE_RATE_PER_MILE = 1.6000

#: A third carrier, so that "invited but unaccepted" and "never invited" can be
#: told apart within one event.
THIRD_CARRIER = {"legal_name": "Gamma Freight Systems", "scac_code": "CFLT"}
UNINVITED_BID = {
    "rate_per_mile": 1.9000,
    "committed_volume_loads": 300,
    "transit_days_offered": 3,
}


def _attempt_bid(round_id, lane_id, carrier_id, **overrides):
    """Submits a lane bid as its owning carrier, without asserting the outcome."""
    return api_client.create_lane_bid(
        round_id,
        lane_bid_payload(lane_id, carrier_id, **overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _count_bids(round_id):
    _rows, meta = validate_paginated(
        api_client.list_lane_bids(ANALYST, {"bid_round_id": round_id})
    )
    return meta["total_count"]


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


def _three_carrier_open_round():
    """An OPEN round where one bidder accepted, one never replied, one was never asked."""
    set_clock(DEFAULT_CLOCK)
    accepted = create_qualified_carrier()
    unanswered = create_qualified_carrier(carrier_overrides=second_carrier_overrides())
    uninvited = create_qualified_carrier(carrier_overrides=dict(THIRD_CARRIER))
    event, lanes = create_event_with_locked_lanes()
    invite_and_accept(event["id"], accepted["id"])
    invite_carrier(event["id"], unanswered["id"])
    return {
        "accepted": accepted,
        "unanswered": unanswered,
        "uninvited": uninvited,
        "event": event,
        "lane": lanes[0],
        "bid_round": open_round(event["id"]),
    }


class TestRateFloorIsMeasuredOnTheSubmittedRate:
    """The floor reads the quoted rate, before any fuel adjustment."""

    def test_one_hundredth_below_the_floor_is_refused_with_nothing_written(self):
        """422, and the round's rollups must not move on a refused bid.

        PRD §3.5: "Finally the two money gates: `rate_per_mile` must be greater than or
        equal to the event's `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR`
        (422)"
        PRD §2.9: "A submitted or proposed per-mile rate must be at or above the event's
        rate floor (`ERR_RATE_BELOW_FLOOR`)"
        PRD §3.5: "When `fuel_surcharge_included` is `true`, the effective per-mile rate
        is the quoted `rate_per_mile` unchanged. When it is `false`, add the event's
        `fuel_index_per_mile` to `rate_per_mile` and round the sum to 4 decimal places."
        PRD §2.9: "**the first violated check decides the response** — no later check is
        evaluated and no partial write is retained."

        Design: Corner/validations/bid_below_the_event_rate_floor_returns_rate_below_floor
        """
        ctx = setup_open_round_with_bidder()
        assert RATE_BELOW_FLOOR < RATE_FLOOR_PER_MILE

        refused = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=RATE_BELOW_FLOOR,
        )
        validate_error(refused, "ERR_RATE_BELOW_FLOOR", 422)

        # The same rate quoted net of fuel is refused identically: the gate never
        # reads the fuel-adjusted effective rate, which would clear the floor.
        assert FUEL_ADJUSTED_RATE > RATE_FLOOR_PER_MILE
        net_of_fuel = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=RATE_BELOW_FLOOR,
            fuel_surcharge_included=False,
        )
        validate_error(net_of_fuel, "ERR_RATE_BELOW_FLOOR", 422)

        assert _count_bids(ctx["bid_round"]["id"]) == 0
        bid_round = _read_round(ctx["bid_round"]["id"])
        assert bid_round["submitted_bid_count"] == 0
        assert bid_round["lowest_rate_per_mile"] is None
        assert bid_round["status"] == "OPEN"

    def test_the_floor_value_itself_is_accepted_and_priced_in_full(self):
        """201 at 1.5000, with the whole six-step evaluation written at submission.

        PRD §3.5: "Multiply the lane's `mileage` by `effective_rate_per_mile` and round
        to 2 decimal places, giving `linehaul_per_load_usd`."
        PRD §3.5: "Under the `FORECAST` variant, multiply the lane's
        `annual_volume_loads` by the forecast growth factor of `1.20` and round to a
        whole number of loads."
        PRD §3.5: "Then take `awardable_volume_loads` as the smaller of the carrier's
        `committed_volume_loads` and that volume basis"
        PRD §3.5: "Its evaluated cost figures and its cost-rank score are computed at
        once, `rank_in_lane` is written, and the `rank_in_lane` of every other bid on the
        same lane in the same round is recomputed so the lane's ordering stays
        consistent."

        Design: Corner/validations/bid_exactly_at_the_rate_floor_is_accepted_and_priced
        """
        ctx = setup_open_round_with_bidder()

        bid = validate_success(
            _attempt_bid(
                ctx["bid_round"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                rate_per_mile=RATE_AT_FLOOR,
            ),
            201,
        )
        assert bid["status"] == "SUBMITTED"
        assert float(bid["rate_per_mile"]) == RATE_AT_FLOOR
        assert float(bid["effective_rate_per_mile"]) == RATE_AT_FLOOR
        assert float(bid["linehaul_per_load_usd"]) == FLOOR_LINEHAUL_USD
        assert float(bid["accessorial_per_load_usd"]) == FLOOR_ACCESSORIAL_USD
        assert float(bid["cost_per_load_usd"]) == FLOOR_COST_PER_LOAD_USD
        assert bid["awardable_volume_loads"] == FLOOR_AWARDABLE_LOADS
        assert float(bid["evaluated_total_cost_usd"]) == FLOOR_EVALUATED_TOTAL_USD
        assert bid["evaluated_basis"] == "FORECAST"
        assert float(bid["service_credit_pct"]) == FLOOR_SERVICE_CREDIT_PCT
        assert float(bid["cost_rank_score"]) == FLOOR_COST_RANK_SCORE
        assert bid["rank_in_lane"] == 1
        assert bid["is_incumbent"] is False

        bid_round = _read_round(ctx["bid_round"]["id"])
        assert bid_round["submitted_bid_count"] == 1
        assert float(bid_round["lowest_rate_per_mile"]) == RATE_AT_FLOOR


class TestTransitDaysAreEnforcedAtSubmission:
    """Service capability is a submission gate, not an optimiser filter."""

    def test_a_fourth_day_on_a_three_day_lane_is_refused_and_then_accepted_at_three(
        self,
    ):
        """The rate would have won the lane outright; the transit field decides.

        PRD §3.5: "`transit_days_offered` must be less than or equal to the lane's
        `service_days_required`, otherwise `ERR_TRANSIT_DAYS_EXCEEDED` (409) — offering
        exactly the required number of days is acceptable."
        PRD §2.9: "`transit_days_offered` must not exceed the lane's
        `service_days_required` (`ERR_TRANSIT_DAYS_EXCEEDED`)"
        PRD §3.5: "The round's `submitted_bid_count` and `lowest_rate_per_mile` are then
        recomputed."

        Design: Corner/validations/transit_days_beyond_the_lane_requirement_is_rejected
        """
        ctx = setup_open_round_with_bidder()
        assert TRANSIT_DAYS_TOO_MANY > LANE_SERVICE_DAYS

        refused = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=COMPETITIVE_RATE_PER_MILE,
            transit_days_offered=TRANSIT_DAYS_TOO_MANY,
        )
        validate_error(refused, "ERR_TRANSIT_DAYS_EXCEEDED", 409)
        assert _count_bids(ctx["bid_round"]["id"]) == 0
        assert _read_round(ctx["bid_round"]["id"])["submitted_bid_count"] == 0

        accepted = validate_success(
            _attempt_bid(
                ctx["bid_round"]["id"],
                ctx["lane"]["id"],
                ctx["carrier"]["id"],
                rate_per_mile=COMPETITIVE_RATE_PER_MILE,
                transit_days_offered=LANE_SERVICE_DAYS,
            ),
            201,
        )
        assert accepted["status"] == "SUBMITTED"
        assert accepted["transit_days_offered"] == LANE_SERVICE_DAYS
        assert _read_round(ctx["bid_round"]["id"])["submitted_bid_count"] == 1


class TestBiddingRelationshipIsCheckedInTwoSteps:
    """No invitation at all is a different answer from one still unanswered."""

    def test_a_carrier_that_was_never_invited_is_refused_as_not_invited(self):
        """The absence of the row decides before any status could be read.

        PRD §3.5: "An invitation must exist for this pairing of event and carrier,
        otherwise `ERR_CARRIER_NOT_INVITED` (409)"
        PRD §2.9: "an invitation must exist for that pairing of event and carrier,
        otherwise `ERR_CARRIER_NOT_INVITED` (409), and that invitation's status must be
        `ACCEPTED`, otherwise `ERR_INVITATION_NOT_ACCEPTED` (409)"

        Design: Corner/validations/carrier_invitation_existence_is_checked_before_its_acceptance_status
        """
        ctx = _three_carrier_open_round()

        refused = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["uninvited"]["id"],
            **UNINVITED_BID,
        )
        validate_error(refused, "ERR_CARRIER_NOT_INVITED", 409)
        assert refused.json()["data"]["error_id"] != "ERR_INVITATION_NOT_ACCEPTED"

        assert _count_bids(ctx["bid_round"]["id"]) == 0
        bid_round = _read_round(ctx["bid_round"]["id"])
        assert bid_round["submitted_bid_count"] == 0
        assert bid_round["lowest_rate_per_mile"] is None

    def test_an_invitation_still_sent_is_refused_as_not_accepted(self):
        """The row exists, so the second check runs and gives the other answer.

        PRD §3.5: "and that invitation's `status` must be `ACCEPTED`, otherwise
        `ERR_INVITATION_NOT_ACCEPTED` (409) — a carrier that was invited but has not yet
        accepted, or that declined, cannot bid"
        PRD §2.12: "`BidEvent.invited_carrier_count` counts invitations whose status is
        `SENT`, `ACCEPTED` or `DECLINED`, so a revoked invitation drops out of it."
        PRD §3.4: "The event's `invited_carrier_count` is recomputed, and on the first
        invitation the event moves from `LANES_LOCKED` to `INVITING`."

        Design: Corner/validations/carrier_invitation_existence_is_checked_before_its_acceptance_status
        """
        ctx = _three_carrier_open_round()

        refused = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["unanswered"]["id"],
            **UNINVITED_BID,
        )
        validate_error(refused, "ERR_INVITATION_NOT_ACCEPTED", 409)

        event = read_event(ctx["event"]["id"])
        assert event["invited_carrier_count"] == 2
        assert event["accepted_invitation_count"] == 1

        # The identical payload from the carrier that did accept is admitted.
        accepted = submit_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["accepted"]["id"],
            **UNINVITED_BID,
        )
        assert accepted["status"] == "SUBMITTED"
        assert _count_bids(ctx["bid_round"]["id"]) == 1
