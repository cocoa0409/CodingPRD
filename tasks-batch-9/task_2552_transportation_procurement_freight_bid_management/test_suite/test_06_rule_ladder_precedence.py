"""Requests that violate two rules at once, where only the higher rung may answer.

Each pair here is set up so both checks are genuinely armed: a control call proves
the lower-ranked rule fires on its own, and the doubly-violating call proves the
higher-ranked rule outranks it. The lower rule must not surface, and no partial
write may survive either rejection.
"""

from test_helpers import (
    ANALYST,
    COMPLIANCE,
    CONTRACT_ADMIN,
    DEFAULT_CLOCK,
    add_lane,
    api_client,
    carrier_status_change_payload,
    close_round,
    create_bid_event,
    create_event_with_locked_lanes,
    create_qualified_carrier,
    get_success_data,
    invite_and_accept,
    lane_bid_payload,
    load_rate_record,
    make_carrier_rep_headers,
    open_round,
    read_contract,
    read_rate_record,
    second_carrier_overrides,
    set_clock,
    setup_open_round_with_bidder,
    setup_staged_rate_record,
    stage_rate_record,
    validate_error,
)

# The event's rate floor is 1.5000 per mile, so this quote is below it.
BELOW_FLOOR_RATE = 1.0000

# Rate record R2's interval sits strictly inside R1's [2026-09-01, 2027-09-01).
R2_EFFECTIVE_FROM = "2026-11-01T00:00:00Z"
R2_EFFECTIVE_TO = "2027-01-01T00:00:00Z"


def _attempt_bid(round_id, lane_id, carrier_id, **overrides):
    """Submits a lane bid without asserting success, so the error can be read."""
    return api_client.create_lane_bid(
        round_id,
        lane_bid_payload(lane_id, carrier_id, **overrides),
        make_carrier_rep_headers(carrier_id),
    )


def _lane_bids(**params):
    body = get_success_data(api_client.list_lane_bids(ANALYST, params or None))
    return body["data"] if isinstance(body, dict) and "data" in body else body


def _read_round(round_id):
    return get_success_data(api_client.get_bid_round(round_id, ANALYST))


class TestClosedRoundOutranksTheRateFloor:
    """Rung 9's state conflict answers before rung 17's money limit."""

    def test_a_below_floor_bid_into_a_closed_round_reports_the_closed_round(self):
        """The state precondition decides, and the 422 never surfaces.

        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and
        no partial write is retained."
        PRD §2.9: "submitting or withdrawing a bid on a round that is not `OPEN`
        raises `ERR_ROUND_NOT_OPEN`"
        PRD §3.5: "`rate_per_mile` must be greater than or equal to the event's
        `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR` (422)"

        Design: Difficulty/priority_pair_validation_conflict/closed_round_state_beats_rate_below_floor
        """
        ctx = setup_open_round_with_bidder(rounds_allowed=2)
        close_round(ctx["bid_round"]["id"])

        response = _attempt_bid(
            ctx["bid_round"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=BELOW_FLOOR_RATE,
        )
        validate_error(response, "ERR_ROUND_NOT_OPEN", 409)
        assert response.json()["data"]["error_id"] != "ERR_RATE_BELOW_FLOOR"
        assert response.status_code != 422

    def test_the_same_below_floor_rate_is_rejected_on_an_open_round(self):
        """The control: the money rule was armed all along and merely outranked.

        PRD §2.9: "A submitted or proposed per-mile rate must be at or above the
        event's rate floor (`ERR_RATE_BELOW_FLOOR`)"
        PRD §3.5: "Finally the two money gates: `rate_per_mile` must be greater than
        or equal to the event's `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR`
        (422)"
        PRD §2.9: "no later check is evaluated and no partial write is retained"

        Design: Difficulty/priority_pair_validation_conflict/closed_round_state_beats_rate_below_floor
        """
        ctx = setup_open_round_with_bidder(rounds_allowed=2)
        close_round(ctx["bid_round"]["id"])
        round_2 = open_round(ctx["event"]["id"], closes_at="2026-08-28T00:00:00Z")

        response = _attempt_bid(
            round_2["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            rate_per_mile=BELOW_FLOOR_RATE,
        )
        validate_error(response, "ERR_RATE_BELOW_FLOOR", 422)

        # Neither rejection may leave a bid behind on either round.
        assert _lane_bids(bid_round_id=ctx["bid_round"]["id"]) == []
        assert _lane_bids(bid_round_id=round_2["id"]) == []
        assert _read_round(ctx["bid_round"]["id"])["submitted_bid_count"] == 0
        assert _read_round(round_2["id"])["submitted_bid_count"] == 0


class TestUninvitedCarrierOutranksOutOfScopeLane:
    """Rung 12's bidding relationship answers before rung 15's structural check."""

    @staticmethod
    def _two_events():
        """EVT-1 with an open round and only ALFL invited, plus EVT-2's own lane."""
        set_clock(DEFAULT_CLOCK)
        invited = create_qualified_carrier()
        uninvited = create_qualified_carrier(
            carrier_overrides=second_carrier_overrides()
        )
        event_1, lanes_1 = create_event_with_locked_lanes()
        invite_and_accept(event_1["id"], invited["id"])
        round_1 = open_round(event_1["id"])

        event_2 = create_bid_event(name="EVT-2")
        lane_2 = add_lane(event_2["id"], lane_code="L-EVT2")
        return {
            "invited": invited,
            "uninvited": uninvited,
            "round_1": round_1,
            "lane_1": lanes_1[0],
            "lane_2": lane_2,
        }

    def test_an_uninvited_carrier_bidding_an_out_of_scope_lane_reports_the_invitation(self):
        """The relationship rung decides; the scope error must not surface.

        PRD §2.9: "an invitation must exist for that pairing of event and carrier,
        otherwise `ERR_CARRIER_NOT_INVITED` (409)"
        PRD §3.5: "An invitation must exist for this pairing of event and carrier,
        otherwise `ERR_CARRIER_NOT_INVITED` (409)"
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and
        no partial write is retained."

        Design: Difficulty/priority_pair_validation_conflict/carrier_not_invited_beats_lane_out_of_event_scope
        """
        ctx = self._two_events()
        response = _attempt_bid(
            ctx["round_1"]["id"], ctx["lane_2"]["id"], ctx["uninvited"]["id"]
        )
        validate_error(response, "ERR_CARRIER_NOT_INVITED", 409)
        assert response.json()["data"]["error_id"] != "ERR_LANE_NOT_IN_EVENT_SCOPE"

    def test_the_invited_carrier_on_the_same_lane_reports_the_scope_violation(self):
        """The control, which also shows neither rejection is a body-FK 404.

        PRD §2.9: "The bid's lane must belong to the round's event
        (`ERR_LANE_NOT_IN_EVENT_SCOPE`)"
        PRD §3.5: "The named lane must belong to the same bid event as the round,
        otherwise `ERR_LANE_NOT_IN_EVENT_SCOPE` (409)."
        PRD §2.9: "Every foreign key supplied in the request **body** must resolve to
        an existing row, checked in the order the fields are declared for that
        endpoint"

        Design: Difficulty/priority_pair_validation_conflict/carrier_not_invited_beats_lane_out_of_event_scope
        """
        ctx = self._two_events()
        response = _attempt_bid(
            ctx["round_1"]["id"], ctx["lane_2"]["id"], ctx["invited"]["id"]
        )
        validate_error(response, "ERR_LANE_NOT_IN_EVENT_SCOPE", 409)
        # The lane and both carriers exist, so no rung-5 404 could have fired.
        assert response.status_code != 404
        assert _lane_bids(bid_round_id=ctx["round_1"]["id"]) == []


class TestSuspendedCarrierOutranksTheIntervalCollision:
    """Rung 10's fitness gate answers before rung 14's time-window integrity."""

    @staticmethod
    def _overlapping_pair():
        """R1 loaded over the whole contract window, R2 staged strictly inside it."""
        ctx = setup_staged_rate_record()
        load_rate_record(ctx["rate_record"]["id"])
        ctx["rate_2"] = stage_rate_record(
            ctx["contract"]["id"],
            ctx["lane"]["id"],
            ctx["carrier"]["id"],
            ctx["allocation"]["id"],
            effective_from=R2_EFFECTIVE_FROM,
            effective_to=R2_EFFECTIVE_TO,
        )
        return ctx

    def test_loading_for_a_suspended_carrier_reports_the_suspension(self):
        """Carrier fitness decides even though the interval also collides.

        PRD §2.9: "The carrier being bound is fit, per §2.10, otherwise
        `ERR_CARRIER_SUSPENDED`, `ERR_CARRIER_INSURANCE_EXPIRED` or
        `ERR_CARRIER_NOT_QUALIFIED` (all 409)."
        PRD §3.8: "The carrier's `status` must not be `SUSPENDED` or `DISQUALIFIED`,
        otherwise `ERR_CARRIER_SUSPENDED` (409)."
        PRD §2.10: "A carrier whose `status` is `SUSPENDED` or `DISQUALIFIED` is
        rejected with `ERR_CARRIER_SUSPENDED`."

        Design: Difficulty/priority_pair_validation_conflict/carrier_suspended_beats_rate_interval_overlap
        """
        ctx = self._overlapping_pair()
        get_success_data(
            api_client.change_carrier_status(
                ctx["carrier"]["id"],
                carrier_status_change_payload(
                    to_status="SUSPENDED", reason="Insurance audit in progress"
                ),
                COMPLIANCE,
            )
        )

        response = api_client.load_rate_record(ctx["rate_2"]["id"], CONTRACT_ADMIN)
        validate_error(response, "ERR_CARRIER_SUSPENDED", 409)
        assert response.json()["data"]["error_id"] != "ERR_RATE_INTERVAL_OVERLAP"

    def test_after_reinstatement_the_same_load_reports_the_interval_overlap(self):
        """The control: the collision was armed, and neither rejection wrote anything.

        PRD §3.8: "no other rate record sharing the same `lane_id`, `carrier_id` and
        `routing_position`, and whose `status` is `LOADED`, `LIVE` or `AT_RISK`, may
        have an overlapping interval, otherwise `ERR_RATE_INTERVAL_OVERLAP` (409)"
        PRD §3.1: "A carrier whose `status` is `SUSPENDED` may be moved to
        `QUALIFIED`, but only when its `insurance_expiry_date` is strictly after the
        logical clock"
        PRD §2.9: "no later check is evaluated and no partial write is retained"

        Design: Difficulty/priority_pair_validation_conflict/carrier_suspended_beats_rate_interval_overlap
        """
        ctx = self._overlapping_pair()
        get_success_data(
            api_client.change_carrier_status(
                ctx["carrier"]["id"],
                carrier_status_change_payload(
                    to_status="SUSPENDED", reason="Insurance audit in progress"
                ),
                COMPLIANCE,
            )
        )
        validate_error(
            api_client.load_rate_record(ctx["rate_2"]["id"], CONTRACT_ADMIN),
            "ERR_CARRIER_SUSPENDED",
            409,
        )

        reinstated = get_success_data(
            api_client.change_carrier_status(
                ctx["carrier"]["id"],
                carrier_status_change_payload(
                    to_status="QUALIFIED", reason="Audit cleared"
                ),
                COMPLIANCE,
            )
        )
        assert reinstated["status"] == "QUALIFIED"

        response = api_client.load_rate_record(ctx["rate_2"]["id"], CONTRACT_ADMIN)
        validate_error(response, "ERR_RATE_INTERVAL_OVERLAP", 409)

        # A rejected load leaves no partial effect on either record.
        second = read_rate_record(ctx["rate_2"]["id"])
        assert second["status"] == "STAGED"
        assert second["loaded_at"] is None
        assert read_rate_record(ctx["rate_record"]["id"])["status"] == "LOADED"
        assert read_contract(ctx["contract"]["id"])["rate_load_status"] == "LOADED"
