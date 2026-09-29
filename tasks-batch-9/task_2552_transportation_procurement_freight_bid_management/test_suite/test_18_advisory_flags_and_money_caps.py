"""Two one-cent boundaries: an advisory lane flag and a fiscal adjustment cap.

Both comparisons are strict on one side, so a single cent decides them. The lane
flag must not change the arithmetic it annotates — the flagged lane still carries
its full baseline into the locked scope — while the adjustment cap must refuse the
proposal outright and leave the window reusable.
"""

from test_helpers import (
    ANALYST,
    CLOCK_MINI_BID_APPLY,
    DEFAULT_CLOCK,
    TEST_DEFAULTS,
    add_lane,
    api_client,
    assert_same_instant,
    create_bid_event,
    create_qualified_carrier,
    make_carrier_rep_headers,
    mini_bid_proposal_payload,
    read_contract,
    read_lane,
    read_mini_bid,
    read_rate_record,
    request_mini_bid,
    set_clock,
    setup_live_rate_record,
    validate_error,
    validate_success,
)

# ── Two lanes that straddle the accessorial ceiling by one cent ───────────────

#: round(1147 x 2.4000, 2) x 0.10, the reference the flag compares against.
ACCESSORIAL_CEILING_USD = 275.28
ACCESSORIAL_ONE_CENT_OVER_USD = 275.29

#: Everything but the accessorial, shared by both lanes.
SHARED_LANE = {
    "incumbent_rate_per_mile": TEST_DEFAULTS["LANE_A_INCUMBENT_RATE_PER_MILE"],
}

# round(2752.80 + 275.28, 2) x 550, and the same at one cent more.
BASELINE_AT_CEILING_USD = 1665444.00
BASELINE_OVER_CEILING_USD = 1665449.50
LANE_PLAN_LOADS = TEST_DEFAULTS["LANE_A_ANNUAL_VOLUME_LOADS"]
LOCKED_SCOPE_LOADS = 1100
LOCKED_SCOPE_BASELINE_USD = 3330893.50

# ── A proposal one half of one percent past the adjustment cap ────────────────

#: The rate the live record currently stores, which the cap is measured against.
CURRENT_RATE_PER_MILE = TEST_DEFAULTS["RATE_A_PER_MILE"]
RATE_AT_CAP = 2.2400
RATE_OVER_CAP = 2.2500
ADJUSTMENT_CAP_PCT = 12.00
REFUSED_ADJUSTMENT_PCT = 12.50
CONTRACT_VALUE_USD = 1267629.99


def _two_lanes_one_cent_apart():
    """A DRAFT event holding two otherwise identical lanes, both still DRAFT."""
    set_clock(DEFAULT_CLOCK)
    incumbent = create_qualified_carrier()
    event = create_bid_event()
    shared = dict(SHARED_LANE, incumbent_carrier_id=incumbent["id"])
    at_ceiling = add_lane(
        event["id"],
        lane_code="L-EXACT",
        accessorial_history_usd_per_load=ACCESSORIAL_CEILING_USD,
        **shared,
    )
    over_ceiling = add_lane(
        event["id"],
        lane_code="L-OVER",
        accessorial_history_usd_per_load=ACCESSORIAL_ONE_CENT_OVER_USD,
        **shared,
    )
    return event, at_ceiling, over_ceiling


def _validate(lane_id):
    return validate_success(api_client.validate_lane(lane_id, ANALYST))


def _requested_mini_bid():
    """A LIVE record at 2.0000 with one REQUESTED window, the clock inside it."""
    ctx = setup_live_rate_record()
    ctx["mini_bid"] = request_mini_bid(
        ctx["event"]["id"], ctx["lane"]["id"], ctx["rate_record"]["id"]
    )
    set_clock(CLOCK_MINI_BID_APPLY)
    return ctx


def _propose(mini_bid_id, carrier_id, rate_per_mile):
    """Proposes a replacement rate without asserting the outcome."""
    return api_client.propose_mini_bid_rate(
        mini_bid_id,
        mini_bid_proposal_payload(carrier_id, proposed_rate_per_mile=rate_per_mile),
        make_carrier_rep_headers(carrier_id),
    )


class TestAccessorialOutlierUsesAStrictComparison:
    """At exactly the rounded ceiling the flag stays silent; one cent over it fires."""

    def test_the_lane_at_the_ceiling_validates_with_no_flag_at_all(self):
        """275.28 is not strictly greater than 275.28, so nothing is annotated.

        PRD §3.3: "`ACCESSORIAL_OUTLIER` fires only when an incumbent rate exists.
        Multiply `mileage` by `incumbent_rate_per_mile` and round to 2 decimal places to
        obtain a linehaul reference; multiply that reference by the outlier ratio of
        `0.10`, round to 2 decimal places, and fire the flag when
        `accessorial_history_usd_per_load` is strictly greater than that product."
        PRD §3.3: "First, multiply `mileage` by `incumbent_rate_per_mile` and round to 2
        decimal places to obtain the baseline linehaul per load."
        PRD §3.3: "Otherwise `unallocated_volume_loads` is reset to
        `annual_volume_loads`, `baseline_cost_usd` is computed, `validated_at` is set to
        the logical clock, and the lane moves from `DRAFT` to `VALIDATED`."

        Design: Corner/calculations/accessorial_outlier_flag_uses_the_rounded_ceiling_and_a_strict_comparison
        """
        _event, at_ceiling, _over = _two_lanes_one_cent_apart()

        validated = _validate(at_ceiling["id"])
        assert validated["status"] == "VALIDATED"
        assert validated["data_quality_flags"] == []
        assert float(validated["baseline_cost_usd"]) == BASELINE_AT_CEILING_USD
        assert validated["unallocated_volume_loads"] == LANE_PLAN_LOADS
        assert_same_instant(validated["validated_at"], DEFAULT_CLOCK, "validated_at")

    def test_one_cent_over_the_ceiling_flags_the_lane_but_does_not_block_it(self):
        """The flag is advisory, so the validate still succeeds and the baseline stands.

        PRD §3.3: "The other four — `VOLUME_VARIANCE_HIGH`, `SEASONALITY_EXTREME`,
        `NO_INCUMBENT_BASELINE` and `ACCESSORIAL_OUTLIER` — are advisory: they are
        recorded and they can affect downstream arithmetic, but they never stop a lane
        from progressing."
        PRD §3.3: "Two of the six are **blocking**: `MILEAGE_IMPLAUSIBLE` and
        `MISSING_TRAILING_VOLUME`."
        PRD §3.3: "Second, add `accessorial_history_usd_per_load` to that already-rounded
        figure and round the sum to 2 decimal places to obtain the baseline cost per
        load."

        Design: Corner/calculations/accessorial_outlier_flag_uses_the_rounded_ceiling_and_a_strict_comparison
        """
        _event, _at_ceiling, over_ceiling = _two_lanes_one_cent_apart()

        validated = _validate(over_ceiling["id"])
        assert validated["status"] == "VALIDATED", (
            "an advisory flag never raises ERR_LANE_DATA_QUALITY_BLOCKED"
        )
        assert validated["data_quality_flags"] == ["ACCESSORIAL_OUTLIER"]
        assert float(validated["baseline_cost_usd"]) == BASELINE_OVER_CEILING_USD

    def test_the_flagged_lane_still_counts_in_full_toward_the_locked_scope(self):
        """Only `NO_INCUMBENT_BASELINE` removes a lane from the baseline roll-up.

        PRD §3.3: "`baseline_cost_usd` is the sum of `baseline_cost_usd` over those same
        lanes, **excluding any lane whose `data_quality_flags` contain
        `NO_INCUMBENT_BASELINE`**, rounded to 2 decimal places."
        PRD §3.3: "`total_scope_volume_loads` is the sum of `annual_volume_loads` over
        the event's lanes whose `status` is `VALIDATED`, `LOCKED`, `AWARDED` or
        `UNDER_REBID`."
        PRD §3.3: "The lock then does three things: every `VALIDATED` lane of the event
        moves to `LOCKED`; each locked lane's `baseline_cost_usd` is recomputed so the
        frozen scope carries current figures; and the event's `total_scope_volume_loads`
        and `baseline_cost_usd` are rolled up."

        Design: Corner/calculations/accessorial_outlier_flag_uses_the_rounded_ceiling_and_a_strict_comparison
        """
        event, at_ceiling, over_ceiling = _two_lanes_one_cent_apart()
        _validate(at_ceiling["id"])
        _validate(over_ceiling["id"])

        locked = validate_success(api_client.lock_lanes(event["id"], ANALYST))
        assert locked["status"] == "LANES_LOCKED"
        assert locked["total_scope_volume_loads"] == LOCKED_SCOPE_LOADS
        assert float(locked["baseline_cost_usd"]) == LOCKED_SCOPE_BASELINE_USD, (
            "the outlier lane contributes its whole baseline to the roll-up"
        )
        assert read_lane(over_ceiling["id"])["data_quality_flags"] == [
            "ACCESSORIAL_OUTLIER"
        ]


class TestMiniBidAdjustmentCapIsInclusive:
    """12.00 is admitted, 12.50 is refused, and the refusal reopens nothing."""

    def test_twelve_and_a_half_percent_is_refused_and_leaves_the_window_requested(self):
        """A fiscal 422 that writes nothing, so the carrier can re-propose.

        PRD §3.9: "The absolute value of `adjustment_pct` must not exceed the adjustment
        cap of `12.00`, otherwise the proposal is rejected with
        `ERR_ADJUSTMENT_EXCEEDS_CAP` (422)."
        PRD §3.9: "Take the `rate_per_mile` of the targeted rate record **as it is
        currently stored**."
        PRD §3.9: "Subtract that current rate from `proposed_rate_per_mile`, multiply the
        difference by `100.00`, divide by the current rate, and round to 2 decimal
        places."
        PRD §2.9: "Checks are evaluated in a single fixed ascending order, and **the
        first violated check decides the response** — no later check is evaluated and no
        partial write is retained."

        Design: Corner/calculations/mini_bid_adjustment_cap_admits_exactly_twelve_percent_and_refuses_twelve_and_a_half
        """
        ctx = _requested_mini_bid()
        assert ctx["mini_bid"]["status"] == "REQUESTED"
        assert float(ctx["rate_record"]["rate_per_mile"]) == CURRENT_RATE_PER_MILE

        refused = _propose(
            ctx["mini_bid"]["id"], ctx["carrier"]["id"], RATE_OVER_CAP
        )
        validate_error(refused, "ERR_ADJUSTMENT_EXCEEDS_CAP", 422)
        assert REFUSED_ADJUSTMENT_PCT > ADJUSTMENT_CAP_PCT

        unchanged = read_mini_bid(ctx["mini_bid"]["id"])
        assert unchanged["status"] == "REQUESTED"
        assert unchanged["proposed_rate_per_mile"] is None
        assert unchanged["proposed_by_carrier_id"] is None
        assert unchanged["adjustment_pct"] is None

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "LIVE"
        assert float(record["rate_per_mile"]) == CURRENT_RATE_PER_MILE
        assert (
            float(read_contract(ctx["contract"]["id"])["total_committed_value_usd"])
            == CONTRACT_VALUE_USD
        )

    def test_exactly_twelve_percent_opens_the_window_and_moves_no_money(self):
        """2.2400 against 2.0000 sits on the cap, and `abs() <= cap` admits it.

        PRD §3.9: "On success the mini-bid records `proposed_rate_per_mile`,
        `proposed_by_carrier_id` and `adjustment_pct`, and moves from `REQUESTED` to
        `OPEN`."
        PRD §3.9: "That is `adjustment_pct`, which is positive for an increase and
        negative for a decrease."
        PRD §3.9: "`proposed_rate_per_mile` must be greater than or equal to the event's
        `rate_floor_per_mile`, otherwise `ERR_RATE_BELOW_FLOOR` (422)."

        Design: Corner/calculations/mini_bid_adjustment_cap_admits_exactly_twelve_percent_and_refuses_twelve_and_a_half
        """
        ctx = _requested_mini_bid()

        opened = validate_success(
            _propose(ctx["mini_bid"]["id"], ctx["carrier"]["id"], RATE_AT_CAP)
        )
        assert opened["status"] == "OPEN"
        assert float(opened["adjustment_pct"]) == ADJUSTMENT_CAP_PCT
        assert float(opened["proposed_rate_per_mile"]) == RATE_AT_CAP
        assert opened["proposed_by_carrier_id"] == ctx["carrier"]["id"]
        assert opened["applied_rate_record_id"] is None
        assert opened["applied_at"] is None

        record = read_rate_record(ctx["rate_record"]["id"])
        assert record["status"] == "LIVE", "a proposal supersedes nothing"
        assert float(record["rate_per_mile"]) == CURRENT_RATE_PER_MILE
        contract = read_contract(ctx["contract"]["id"])
        assert contract["status"] == "EXECUTED"
        assert contract["amendment_count"] == 0
        assert float(contract["total_committed_value_usd"]) == CONTRACT_VALUE_USD
