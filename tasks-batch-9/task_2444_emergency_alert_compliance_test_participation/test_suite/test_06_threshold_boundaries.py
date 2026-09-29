"""Numeric and set-membership boundaries: the readiness threshold and its single
rounding step, the empty relay-selector candidate pool, and the obligation-clock
breach comparison feeding the COMPLIANT band edge.

Every test builds its own world from scratch — the harness restarts the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    DEFAULT_LOG_INSTANT,
    TEST_DEFAULTS,
    add_registered_device,
    api_client,
    assert_matched_rule,
    assert_not_suppressed,
    assert_score_and_posture,
    assert_summary_inputs,
    assert_unmatched,
    create_active_plan,
    create_relay_rule,
    evaluate_readiness,
    get_success_data,
    log_alert,
    register_station,
    run_log_review,
    schedule_test_event,
    set_clock,
    setup_restored_outage,
    setup_station,
    station_summary,
)

# ---------------------------------------------------------------------------
# Readiness probe windows. Each event's readiness window opens 24 hours before
# window_start_at and closes at window_end_at.
# ---------------------------------------------------------------------------
LATE_WINDOW_START = "2026-08-14T00:00:00Z"
LATE_WINDOW_END = "2026-08-14T01:00:00Z"
LATE_EVALUATION_INSTANT = "2026-08-14T00:30:00Z"
RECENT_ALERT_INSTANT = "2026-08-13T00:30:00Z"

# A county-scoped FIPS code that never appears in a probe alert's fips_codes.
OUT_OF_SCOPE_FIPS = "20177"

# ---------------------------------------------------------------------------
# Outage probe instants. detected_at lands exactly on an obligation-window open,
# so every full calendar day of the outage contributes exactly 12.00 hours.
# ---------------------------------------------------------------------------
OUTAGE_DETECTED_AT = "2026-08-03T08:00:00Z"
RESTORED_AT_OBLIGATION_LIMIT = "2026-08-06T20:00:00Z"
RESTORED_PAST_OBLIGATION_LIMIT = "2026-08-08T08:00:00Z"


def _plan_with_no_eligible_tor_rule():
    """A plan whose only two TOR rules are both out of the candidate pool: the
    county-scoped one covers a FIPS code the probe alert does not carry, and the
    statewide one has been retired.

    ``mandatory_relay_event_codes`` is left empty so the plan-level override
    cannot mask a selected rule's own ``relay_class``.
    """
    plan = create_active_plan(required_source_types=("PEP",), mandatory_relay_event_codes=())
    county_rule = create_relay_rule(
        plan["id"],
        event_code="TOR",
        fips_codes=[OUT_OF_SCOPE_FIPS],
        relay_class="MANDATORY",
        priority=10,
        forward_delay_seconds=45,
    )
    statewide_rule = create_relay_rule(
        plan["id"],
        event_code="TOR",
        fips_codes=[],
        relay_class="OPTIONAL",
        priority=20,
        forward_delay_seconds=15,
    )
    retired_rule = get_success_data(
        api_client.retire_relay_rule(statewide_rule["id"], ADMIN)
    )
    station = register_station(plan["id"])
    return {
        "plan": plan,
        "plan_id": plan["id"],
        "county_rule": county_rule,
        "retired_rule": retired_rule,
        "station_id": station["id"],
    }


class TestReadinessThresholdBoundary:
    """80.00 is the inclusive pass mark and the weighted sum is rounded once."""

    def test_readiness_score_of_exactly_80_advances_the_event_to_ready(self):
        """PRD §3.6: "The threshold is inclusive at exactly 80.00."
        PRD §3.6: "A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."
        PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."

        Design: Difficulty/boundary_precision_check/readiness_threshold_inclusive_at_exactly_80_and_single_end_rounding
        """
        # One READY device out of one countable unit, the single required source
        # covered, and no alert inside the recent window: 40 + 40 + 0 = 80.00.
        ctx = setup_station()
        event = schedule_test_event(ctx["station_id"])
        set_clock(DEFAULT_LOG_INSTANT)

        evaluated = evaluate_readiness(event["id"])

        assert evaluated["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "40 * 1/1 + 40 * 1/1 + 20 * 0/3 is 80.00, got "
            f"{evaluated['readiness_score']}"
        )
        assert evaluated["status"] == "READY", (
            "80.00 is at the inclusive threshold, so the event advances, got "
            f"{evaluated['status']}"
        )

    def test_readiness_score_below_the_threshold_leaves_the_event_pending(self):
        """PRD §3.6: "A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."
        PRD §3.6: "The **device ratio** is the number of the station's units in `READY` divided by the number of the station's countable units, where countable means units whose `status` is `REGISTERED`, `READY` or `FAILED`; `DECOMMISSIONED` units leave the denominator entirely, and the denominator is treated as 1 whenever the countable count is 0, so a station with no equipment scores a device ratio of 0 rather than failing to compute."

        Design: Difficulty/boundary_precision_check/readiness_threshold_inclusive_at_exactly_80_and_single_end_rounding
        """
        ctx = setup_station()
        # A second unit left in REGISTERED enters the denominator, halving the
        # device ratio: 40 * 1/2 + 40 * 1/1 + 20 * 0/3 = 60.00.
        add_registered_device(ctx, device_role="MONITOR", firmware_version="5.2.0")
        event = schedule_test_event(ctx["station_id"])
        set_clock(DEFAULT_LOG_INSTANT)

        evaluated = evaluate_readiness(event["id"])

        assert evaluated["readiness_score"] == pytest.approx(60.00, abs=0.01), (
            "40 * 1/2 + 40 * 1/1 + 20 * 0/3 is 60.00, got "
            f"{evaluated['readiness_score']}"
        )
        assert evaluated["status"] == "READINESS_PENDING", (
            "60.00 is below 80.00, so the event stays pending, got "
            f"{evaluated['status']}"
        )

    def test_weighted_readiness_sum_is_rounded_exactly_once_at_the_end(self):
        """PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."
        PRD §3.6: "The **device ratio** is the number of the station's units in `READY` divided by the number of the station's countable units, where countable means units whose `status` is `REGISTERED`, `READY` or `FAILED`; `DECOMMISSIONED` units leave the denominator entirely, and the denominator is treated as 1 whenever the countable count is 0, so a station with no equipment scores a device ratio of 0 rather than failing to compute."
        PRD §3.6: "The **recent-activity ratio** is the number of the station's alert events, in any `relay_state`, whose `received_at` falls inside the closed interval running from 30 days before the current logical clock through the current logical clock, divided by a target of 3 recent alerts, and likewise capped at 1."

        Design: Difficulty/boundary_precision_check/readiness_threshold_inclusive_at_exactly_80_and_single_end_rounding
        """
        ctx = setup_station()
        spare = add_registered_device(ctx, device_role="MONITOR", firmware_version="5.2.0")
        event = schedule_test_event(
            ctx["station_id"],
            window_start_at=LATE_WINDOW_START,
            window_end_at=LATE_WINDOW_END,
        )
        # The spare unit leaves the denominator entirely, restoring a 1/1 device
        # ratio, and one alert inside the 30-day window makes the activity ratio 1/3.
        get_success_data(api_client.decommission_device(spare["id"], ADMIN))
        set_clock(RECENT_ALERT_INSTANT)
        log_alert(
            ctx["station_id"],
            RECENT_ALERT_INSTANT,
            event_code="RWT",
            originator_sequence="KSRDY-0001",
        )
        set_clock(LATE_EVALUATION_INSTANT)

        evaluated = evaluate_readiness(event["id"])

        assert evaluated["readiness_score"] == pytest.approx(86.67, abs=0.01), (
            "40 * 1/1 + 40 * 1/1 + 20 * 1/3 is 86.6666..., which rounds half-up once "
            f"to 86.67, got {evaluated['readiness_score']}"
        )
        assert evaluated["status"] == "READY", (
            f"86.67 is above 80.00, so the event advances, got {evaluated['status']}"
        )
        assert evaluated["readiness_evaluated_at"].startswith("2026-08-14T00:30:00"), (
            "readiness_evaluated_at is read from the logical clock, got "
            f"{evaluated['readiness_evaluated_at']}"
        )


class TestRelaySelectorEmptyPoolBoundary:
    """The candidate pool is empty when every eligibility clause is knocked out."""

    def test_empty_candidate_pool_writes_all_four_fallback_fields(self):
        """PRD §3.5: "The candidate pool is every relay rule that belongs to the receiving station's plan — that is, whose `state_plan_id` equals the station's `state_plan_id` — whose `status` is `ACTIVE`, whose `event_code` equals the alert's `event_code`, and whose location scope admits the alert: either the rule's `fips_codes` array is empty, making it statewide and therefore always in scope, or the rule's `fips_codes` shares at least one code with the alert's `fips_codes`."
        PRD §3.1: "Retirement by a `ComplianceAdmin` moves a rule `ACTIVE` → `RETIRED` and takes it out of the selector's candidate pool for every future alert; retiring a rule that is already `RETIRED` is rejected with `ERR_RELAY_RULE_NOT_ACTIVE`."
        PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."
        PRD §3.1: "The server derives `specificity` from the location scope: 2 when `fips_codes` holds at least one entry, meaning the rule is county-scoped, and 1 when `fips_codes` is empty, meaning the rule is statewide."

        Design: Difficulty/boundary_precision_check/selector_empty_pool_fallback_versus_matched_control
        """
        ctx = _plan_with_no_eligible_tor_rule()

        assert ctx["county_rule"]["specificity"] == 2, (
            "a rule carrying at least one FIPS code is county-scoped, got "
            f"{ctx['county_rule']['specificity']}"
        )
        assert ctx["retired_rule"]["specificity"] == 1, (
            "a rule with an empty fips_codes array is statewide, got "
            f"{ctx['retired_rule']['specificity']}"
        )
        assert ctx["retired_rule"]["status"] == "RETIRED", (
            f"the statewide rule was retired, got {ctx['retired_rule']['status']}"
        )

        alert = log_alert(
            ctx["station_id"],
            "2026-08-01T00:00:00Z",
            event_code="TOR",
            originator_sequence="KSSEL-0001",
            fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        )

        assert_unmatched(alert)
        assert_not_suppressed(alert)

    def test_one_eligible_statewide_rule_takes_the_alert_to_relay_pending(self):
        """PRD §3.5: "The candidate pool is every relay rule that belongs to the receiving station's plan — that is, whose `state_plan_id` equals the station's `state_plan_id` — whose `status` is `ACTIVE`, whose `event_code` equals the alert's `event_code`, and whose location scope admits the alert: either the rule's `fips_codes` array is empty, making it statewide and therefore always in scope, or the rule's `fips_codes` shares at least one code with the alert's `fips_codes`."
        PRD §3.5: "When a rule is selected, the alert moves `RECEIVED` → `RELAY_PENDING`, `matched_relay_rule_id` is set to that rule's `id`, and `forward_delay_seconds_applied` is copied from the rule's `forward_delay_seconds`."
        PRD §3.5: "The effective `relay_class_applied` is `MANDATORY` when either the selected rule's `relay_class` is `MANDATORY` **or** the alert's `event_code` appears in the governing plan's `mandatory_relay_event_codes`; otherwise it is `OPTIONAL`."

        Design: Difficulty/boundary_precision_check/selector_empty_pool_fallback_versus_matched_control
        """
        ctx = _plan_with_no_eligible_tor_rule()
        # A fresh statewide TOR rule is the only pool member the alert admits; it
        # can take priority 30 because the duplicate-priority rule only looks at
        # ACTIVE rules of the plan.
        control_rule = create_relay_rule(
            ctx["plan_id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=30,
            forward_delay_seconds=15,
        )

        alert = log_alert(
            ctx["station_id"],
            "2026-08-01T00:00:00Z",
            event_code="TOR",
            originator_sequence="KSSEL-0002",
            fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        )

        assert_matched_rule(alert, control_rule["id"], "OPTIONAL", 15)
        assert_not_suppressed(alert)


class TestObligationClockBreachBoundary:
    """48 hours of obligation downtime is not a breach; 60 hours is."""

    @pytest.mark.parametrize(
        "restored_at,expected_obligation_hours,expected_obligation_breached,"
        "expected_continuous_hours",
        [
            (RESTORED_AT_OBLIGATION_LIMIT, 48.00, False, 84.00),
            (RESTORED_PAST_OBLIGATION_LIMIT, 60.00, True, 120.00),
        ],
    )
    def test_obligation_breach_flag_is_strict_at_48_hours(
        self,
        restored_at,
        expected_obligation_hours,
        expected_obligation_breached,
        expected_continuous_hours,
    ):
        """PRD §3.4: "Accumulate the day contributions in seconds, divide the accumulated total by 3600, and round half-up to two decimal places to obtain `obligation_downtime_hours`."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."
        PRD §3.4: "Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Then `continuous_clock_breached` is true when `continuous_downtime_hours` is strictly greater than 60 hours — two and a half days of unbroken outage — and false when it equals 60 hours or is less."

        Design: Difficulty/boundary_precision_check/obligation_clock_breach_strict_boundary_at_48_hours_and_compliant_band_at_exactly_90
        """
        ctx = setup_station()
        # The failing unit carries no monitoring assignment, so the outage cascade
        # never touches the station's source coverage.
        failing = add_registered_device(ctx, device_role="ENCODER")
        set_clock(OUTAGE_DETECTED_AT)

        outage = setup_restored_outage(failing["id"], OUTAGE_DETECTED_AT, restored_at)

        assert outage["obligation_downtime_hours"] == pytest.approx(
            expected_obligation_hours, abs=0.01
        ), (
            f"expected obligation_downtime_hours {expected_obligation_hours}, got "
            f"{outage['obligation_downtime_hours']}"
        )
        assert outage["obligation_breached"] is expected_obligation_breached, (
            f"expected obligation_breached {expected_obligation_breached} at "
            f"{expected_obligation_hours} obligation hours, got "
            f"{outage['obligation_breached']}"
        )
        assert outage["continuous_downtime_hours"] == pytest.approx(
            expected_continuous_hours, abs=0.01
        ), (
            f"expected continuous_downtime_hours {expected_continuous_hours}, got "
            f"{outage['continuous_downtime_hours']}"
        )
        assert outage["continuous_clock_breached"] is True, (
            f"{expected_continuous_hours} is strictly greater than 60 hours, so the "
            "continuous clock breaches"
        )

    def test_one_breached_outage_lands_the_score_on_exactly_90_and_stays_compliant(self):
        """PRD §3.8: "The outage breach count is the number of equipment outages whose `device_id` belongs to this station, whose `obligation_breached` is true, and whose `status` is `OPEN`, `REPAIR_IN_PROGRESS`, `RESTORED` or `VERIFICATION_FAILED` — a `CLOSED` outage stops counting even if it breached."
        PRD §3.8: "10.00 points for each outage counted in the outage breach count;"
        PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."

        Design: Difficulty/boundary_precision_check/obligation_clock_breach_strict_boundary_at_48_hours_and_compliant_band_at_exactly_90
        """
        ctx = setup_station()
        device_at_limit = add_registered_device(ctx, device_role="ENCODER")
        device_past_limit = add_registered_device(ctx, device_role="MONITOR")
        set_clock(OUTAGE_DETECTED_AT)

        outage_at_limit = setup_restored_outage(
            device_at_limit["id"], OUTAGE_DETECTED_AT, RESTORED_AT_OBLIGATION_LIMIT
        )
        outage_past_limit = setup_restored_outage(
            device_past_limit["id"], OUTAGE_DETECTED_AT, RESTORED_PAST_OBLIGATION_LIMIT
        )

        assert outage_at_limit["obligation_breached"] is False, (
            "exactly 48.00 obligation hours is not a breach, got obligation_breached "
            f"{outage_at_limit['obligation_breached']} at "
            f"{outage_at_limit['obligation_downtime_hours']} hours"
        )
        assert outage_past_limit["obligation_breached"] is True, (
            "60.00 obligation hours is strictly greater than 48, got "
            f"obligation_breached {outage_past_limit['obligation_breached']}"
        )
        for outage in (outage_at_limit, outage_past_limit):
            assert outage["status"] == "RESTORED", (
                "RESTORED is inside the counted status set, got "
                f"{outage['status']}"
            )

        run_log_review(ctx["station_id"])

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            outage_breach_count=1,
            missing_source_count=0,
            silent_assignment_count=0,
        )
        assert_score_and_posture(summary, 90.00, "COMPLIANT")
