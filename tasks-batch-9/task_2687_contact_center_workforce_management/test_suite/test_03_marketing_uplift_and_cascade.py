"""Marketing drivers: the capped confidence-weighted uplift and its full cascade."""

from test_helpers.assertions import assert_interval_forecast, assert_ratio
from test_helpers.constants import (
    CONFIDENCE_HIGH,
    COVERAGE_COVERED,
    COVERAGE_SHORT,
    EVENT_STATUS_CONFIRMED,
    POSTURE_INTRADAY_ALERT,
    POSTURE_SCHEDULE_PUBLISHED,
)
from test_helpers.fixtures import (
    CANONICAL_CLOCK,
    HORIZON_START,
    declare_schedule_published,
    generate_grid,
    lock_requirements,
    make_agent,
    make_coverage_forecast_group,
    make_labor_agreement,
    make_marketing_event,
    make_planning_cycle,
    make_schedule_shift,
    make_shift_template,
    publish_shift,
    read_cycle,
    read_interval,
    set_clock,
    set_event_status,
)

WINDOW_START = "2026-09-07T08:00:00Z"
WINDOW_END = "2026-09-07T10:00:00Z"


def _two_draft_events(api, cycle_id, group_id):
    """Two overlapping HIGH-confidence drivers whose raw uplifts sum past the cap."""
    first = make_marketing_event(
        api,
        cycle_id,
        group_id,
        name="Superbowl Promo",
        uplift_pct=1.20,
        confidence_tier=CONFIDENCE_HIGH,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    second = make_marketing_event(
        api,
        cycle_id,
        group_id,
        name="Email Blast",
        uplift_pct=0.80,
        confidence_tier=CONFIDENCE_HIGH,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    return first, second


class TestUpliftCompositionAndCap:
    """Curve share, confidence weight, the 1.50 cap and the handle-time ceiling."""

    def test_high_confidence_driver_weighs_its_raw_uplift_in_full(
        self, api, cycle, voice_group
    ):
        """A HIGH-tier driver carries its raw uplift into weighted_uplift_pct unchanged.

        "Creation does compute `weighted_uplift_pct` immediately: the raw
        `uplift_pct` multiplied by the confidence weight of its tier, where
        `HIGH` weighs 1.0, `MEDIUM` weighs 0.6 and `LOW` weighs 0.3, stored at
        four decimal places"

        Design: Difficulty/combinatorial_formula/interval_volume_uplift_cap_and_confidence_tiers
        """
        first, second = _two_draft_events(api, cycle["id"], voice_group["id"])

        assert_ratio(first["weighted_uplift_pct"], 1.2000, "weighted_uplift_pct")
        assert_ratio(second["weighted_uplift_pct"], 0.8000, "weighted_uplift_pct")

    def test_one_confirmed_driver_lifts_the_interval_volume_to_1056(
        self, api, cycle, voice_group, voice_intervals
    ):
        """A single 1.20 uplift multiplies the 480-contact expectation up to 1056.

        "It is then multiplied by one plus the interval's
        `applied_event_uplift_pct` (Section 3.3) and by the group's
        `reforecast_multiplier`, and the fully combined product is rounded half
        up to a whole number **exactly once** to give `volume_forecast`."

        Design: Difficulty/combinatorial_formula/interval_volume_uplift_cap_and_confidence_tiers
        """
        first, _ = _two_draft_events(api, cycle["id"], voice_group["id"])

        set_event_status(api, first["id"], EVENT_STATUS_CONFIRMED)

        inflated = read_interval(api, voice_intervals[0]["id"])
        assert inflated["volume_forecast"] == 1056
        assert_ratio(
            inflated["applied_event_uplift_pct"], 1.2000, "applied_event_uplift_pct"
        )

    def test_two_confirmed_drivers_are_summed_then_capped_at_one_and_a_half(
        self, api, cycle, voice_group, voice_intervals
    ):
        """A raw sum of 2.0000 is held at the 1.5000 cap, so volume settles at 1200.

        "Each in-scope driver contributes its raw `uplift_pct` multiplied by its
        tier's confidence weight, those contributions are added together, and the
        sum is capped at 1.50 — no interval may ever be inflated by more than one
        hundred and fifty percent of its driver-free expectation no matter how
        many campaigns pile onto it."

        Design: Difficulty/combinatorial_formula/interval_volume_uplift_cap_and_confidence_tiers
        """
        first, second = _two_draft_events(api, cycle["id"], voice_group["id"])
        set_event_status(api, first["id"], EVENT_STATUS_CONFIRMED)

        set_event_status(api, second["id"], EVENT_STATUS_CONFIRMED)

        inflated = read_interval(api, voice_intervals[0]["id"])
        assert_ratio(
            inflated["applied_event_uplift_pct"], 1.5000, "applied_event_uplift_pct"
        )
        assert_interval_forecast(
            inflated,
            volume_forecast=1200,
            required_service_level=471,
            required_occupancy_capped=454,
            required_agents=471,
        )

    def test_handle_time_stops_at_its_own_ceiling_in_both_states(
        self, api, cycle, voice_group, voice_intervals
    ):
        """The dragged handle time pins to 405 seconds under one driver and under two.

        "The system computes a dragged handle time as the group's
        `base_aht_seconds` multiplied by one plus three-tenths of the interval's
        `applied_event_uplift_pct`, and a ceiling as `base_aht_seconds`
        multiplied by 1.35 — a hard cap thirty-five percent above baseline."

        Design: Difficulty/combinatorial_formula/interval_volume_uplift_cap_and_confidence_tiers
        """
        first, second = _two_draft_events(api, cycle["id"], voice_group["id"])
        set_event_status(api, first["id"], EVENT_STATUS_CONFIRMED)
        assert read_interval(api, voice_intervals[0]["id"])["aht_forecast_seconds"] == 405

        set_event_status(api, second["id"], EVENT_STATUS_CONFIRMED)

        assert read_interval(api, voice_intervals[0]["id"])["aht_forecast_seconds"] == 405

    def test_every_overlapped_interval_scales_by_its_own_curve_share(
        self, api, cycle, voice_group, voice_intervals
    ):
        """The capped uplift reaches the second interval too, taking 360 contacts to 900.

        "On success, every interval plan in the event's scope whose half-open
        interval span overlaps the event's half-open window is fully recomputed:
        `volume_forecast`, `aht_forecast_seconds`, `applied_event_uplift_pct`,
        both staffing variants, `required_agents`, `coverage_gap` and
        `coverage_state`, and then `internal_capacity_volume`,
        `allocatable_volume` and `unserved_volume` on those same intervals."

        Design: Difficulty/combinatorial_formula/interval_volume_uplift_cap_and_confidence_tiers
        """
        first, second = _two_draft_events(api, cycle["id"], voice_group["id"])
        set_event_status(api, first["id"], EVENT_STATUS_CONFIRMED)

        set_event_status(api, second["id"], EVENT_STATUS_CONFIRMED)

        second_interval = read_interval(api, voice_intervals[1]["id"])
        assert second_interval["volume_forecast"] == 900


def _alert_world(api):
    """A live CHAT_EN week, fully covered, whose alert threshold is two shortfalls."""
    set_clock(api, CANONICAL_CLOCK)
    agreement = make_labor_agreement(api)
    cycle = make_planning_cycle(
        api, name="W37-ALERT", intraday_alert_short_threshold=2
    )
    group = make_coverage_forecast_group(api, cycle["id"])
    intervals = generate_grid(api, group["id"], HORIZON_START)
    agent = make_agent(api, agreement["id"], skills=["CHAT_EN"])
    template = make_shift_template(
        api, cycle["id"], code="T-CHAT-MON", skill_code="CHAT_EN"
    )
    shift = make_schedule_shift(
        api, cycle["id"], agent["id"], template["id"], HORIZON_START
    )
    lock_requirements(api, cycle["id"])
    publish_shift(api, shift["id"])
    cycle = declare_schedule_published(api, cycle["id"])
    event = make_marketing_event(
        api,
        cycle["id"],
        group["id"],
        name="Chat Campaign",
        uplift_pct=0.30,
        confidence_tier=CONFIDENCE_HIGH,
        window_start=WINDOW_START,
        window_end=WINDOW_END,
    )
    return {
        "cycle": cycle,
        "group": group,
        "intervals": intervals,
        "agent": agent,
        "shift": shift,
        "event": event,
    }


class TestConfirmationCascadeToPosture:
    """One status write travels from uplift all the way to the cycle posture."""

    def test_the_live_week_starts_fully_covered_with_no_shortfalls(self, api):
        """Before confirmation the week is live, every interval needs one agent and none is short.

        "`coverage_gap` is the requirement minus the effective staffing, floored
        at zero so it is never negative, and `coverage_state` is `COVERED` when
        the gap is exactly zero and `SHORT` otherwise."

        Design: Difficulty/transitive_cascade/marketing_event_confirm_four_hop_posture_alert
        """
        world = _alert_world(api)

        assert world["cycle"]["posture"] == POSTURE_SCHEDULE_PUBLISHED
        assert world["cycle"]["short_interval_count"] == 0
        first = read_interval(api, world["intervals"][0]["id"])
        assert first["required_agents"] == 1
        assert first["coverage_state"] == COVERAGE_COVERED

    def test_confirmation_recomputes_volume_handle_time_and_the_requirement(self, api):
        """Confirming the driver lifts the first interval to 21 contacts, 65 seconds, 2 agents.

        "On success, every interval plan in the event's scope whose half-open
        interval span overlaps the event's half-open window is fully recomputed:
        `volume_forecast`, `aht_forecast_seconds`, `applied_event_uplift_pct`,
        both staffing variants, `required_agents`, `coverage_gap` and
        `coverage_state`, and then `internal_capacity_volume`,
        `allocatable_volume` and `unserved_volume` on those same intervals."

        Design: Difficulty/transitive_cascade/marketing_event_confirm_four_hop_posture_alert
        """
        world = _alert_world(api)

        set_event_status(api, world["event"]["id"], EVENT_STATUS_CONFIRMED)

        first = read_interval(api, world["intervals"][0]["id"])
        assert_interval_forecast(
            first, volume_forecast=21, aht_forecast_seconds=65, required_agents=2
        )
        assert read_interval(api, world["intervals"][1]["id"])["required_agents"] == 2
        assert read_interval(api, world["intervals"][2]["id"])["required_agents"] == 1

    def test_confirmation_reaches_the_per_interval_coverage_verdict(self, api):
        """The two inflated intervals fall SHORT by one agent while the quieter one holds.

        "`coverage_gap` is the requirement minus the effective staffing, floored
        at zero so it is never negative, and `coverage_state` is `COVERED` when
        the gap is exactly zero and `SHORT` otherwise."

        Design: Difficulty/transitive_cascade/marketing_event_confirm_four_hop_posture_alert
        """
        world = _alert_world(api)

        set_event_status(api, world["event"]["id"], EVENT_STATUS_CONFIRMED)

        first = read_interval(api, world["intervals"][0]["id"])
        assert first["coverage_state"] == COVERAGE_SHORT
        assert first["coverage_gap"] == 1
        third = read_interval(api, world["intervals"][2]["id"])
        assert third["coverage_state"] == COVERAGE_COVERED
        assert third["coverage_gap"] == 0

    def test_confirmation_reaches_the_outsourcing_picture(self, api):
        """The inflated interval exposes 16 contacts of internal capacity and 5 allocatable.

        "`internal_capacity_volume` is the number of contacts the internally
        staffed agents can absorb: `effective_scheduled_agents` multiplied by one
        minus `shrinkage_pct`, multiplied by `occupancy_target_pct`, multiplied by
        the interval's length in seconds, divided by `aht_forecast_seconds`, and
        then rounded **down** to a whole number, because partial capacity never
        counts."

        Design: Difficulty/transitive_cascade/marketing_event_confirm_four_hop_posture_alert
        """
        world = _alert_world(api)

        set_event_status(api, world["event"]["id"], EVENT_STATUS_CONFIRMED)

        first = read_interval(api, world["intervals"][0]["id"])
        assert first["internal_capacity_volume"] == 16
        assert first["allocatable_volume"] == 5

    def test_confirmation_rolls_the_shortfall_count_and_escalates_the_posture(self, api):
        """Two fresh shortfalls meet the threshold of two, so the cycle escalates itself.

        "If the cycle is in `SCHEDULE_PUBLISHED` and the recomputed
        `short_interval_count` is greater than or equal to the cycle's
        `intraday_alert_short_threshold`, the cycle escalates `SCHEDULE_PUBLISHED
        → INTRADAY_ALERT` and its `version` increments by 1."

        Design: Difficulty/transitive_cascade/marketing_event_confirm_four_hop_posture_alert
        """
        world = _alert_world(api)

        confirmed = set_event_status(
            api, world["event"]["id"], EVENT_STATUS_CONFIRMED
        )

        assert confirmed["status"] == EVENT_STATUS_CONFIRMED
        assert_ratio(confirmed["weighted_uplift_pct"], 0.3000, "weighted_uplift_pct")
        after = read_cycle(api, world["cycle"]["id"])
        assert after["short_interval_count"] == 2
        assert after["posture"] == POSTURE_INTRADAY_ALERT
