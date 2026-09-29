"""Multi-input formulas: the effective calling window, the rolling rate, the line ceiling.

Each of these three quantities is assembled from several inputs in a fixed order, and a
single reordering of the steps produces a different, wrong number.
"""

from __future__ import annotations

from typing import Any, Dict

from test_helpers import (
    ApiErrorId,
    AttemptOutcome,
    CampaignPurpose,
    CampaignStatus,
    CaptureMethod,
    Channel,
    ComplianceWorld,
    ConsentType,
    DialerMode,
    assert_decimal_equals,
    assert_error,
    assert_fields_equal,
    assert_ok,
    assert_status,
    factories,
)

# Recipient-local 09:00 in Los Angeles (UTC-07:00) on 2026-08-03.
SMS_WINDOW_OPEN_AT = "2026-08-03T16:00:00Z"
# One minute earlier: recipient-local 08:59, below the extended, shifted start.
SMS_ONE_MINUTE_EARLY_AT = "2026-08-03T15:59:00Z"
# Recipient-local 20:30 and 20:29 on 2026-08-03.
SMS_WINDOW_CLOSE_AT = "2026-08-04T03:30:00Z"
SMS_ONE_MINUTE_BEFORE_CLOSE_AT = "2026-08-04T03:29:00Z"

DAY_ONE_ATTEMPTS_AT = (
    "2026-08-03T00:00:00Z",
    "2026-08-03T00:31:00Z",
    "2026-08-03T01:02:00Z",
)
DAY_TWO_ATTEMPTS_AT = ("2026-08-04T00:00:00Z", "2026-08-04T00:31:00Z")


def _sms_on_oral_consent(world: ComplianceWorld, clock: str) -> Dict[str, Any]:
    """A running SMS campaign whose consumer's consent is oral, not written."""
    return world.build(
        clock=clock,
        channel=Channel.SMS,
        consent_type=ConsentType.EXPRESS_ORAL,
        capture_method=CaptureMethod.SMS_DOUBLE_OPT_IN,
        campaign_purpose=CampaignPurpose.INFORMATIONAL,
    )


def _place_and_record(
    world: ComplianceWorld,
    built: Dict[str, Any],
    at_instant: str,
    **outcome: Any,
) -> Dict[str, Any]:
    """Move the clock, place one attempt, record its disposition."""
    world.set_clock(at_instant)
    attempt = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
    return world.record_outcome(attempt["id"], **outcome)


class TestEffectiveCallingWindow:
    """The window the recipient is actually reachable in, per attempt."""

    def test_01_sms_on_oral_consent_narrows_the_window_at_both_ends(self, world):
        """Oral consent lifts the start to 540 and the SMS shift pulls the end down to 1230.

        PRD §3.8:
        "Anything weaker than express written consent loses the first hour of the day: when
        the selected consent record's `consent_type` is anything other than
        `EXPRESS_WRITTEN`, a consent extension of 60 minutes applies, and when it is
        `EXPRESS_WRITTEN` the extension is zero."
        PRD §3.8:
        "The federal floor and ceiling are then applied after both of those adjustments:
        `effective_window_start_minutes` is the greater of the base start plus the consent
        extension and the federal floor of eight o'clock in the recipient's local morning
        — 480 minutes past local midnight — plus the channel shift;
        `effective_window_end_minutes` is the lesser of the base end minus the channel
        shift and the federal ceiling of nine o'clock in the recipient's local evening,
        1260 minutes past local midnight."

        Design: Difficulty/combinatorial_formula/sms_oral_consent_window_clamped_by_nested_min_max
        """
        built = _sms_on_oral_consent(world, SMS_WINDOW_OPEN_AT)

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.SMS
        )

        assert_fields_equal(
            attempt,
            recipient_local_minutes=540,
            recipient_local_time="09:00",
            effective_window_start_minutes=540,
            effective_window_end_minutes=1230,
            calling_window_policy_id=built["policy"]["id"],
            consent_record_id=built["consent"]["id"],
        )
        assert_status(attempt, AttemptOutcome.PENDING, field="outcome")

    def test_02_voice_on_written_consent_keeps_the_policy_window(self, world):
        """Written consent and a voice call leave the base 08:00-21:00 window untouched.

        PRD §3.8:
        "Texts are held to a window narrowed at *both* ends: when the attempt's `channel`
        is `SMS` a channel shift of 30 minutes applies, and for `VOICE` it is zero."
        PRD §3.8:
        "The base window runs from the policy's `window_start_minutes` to its
        `window_end_minutes`."

        Design: Difficulty/combinatorial_formula/sms_oral_consent_window_clamped_by_nested_min_max
        """
        built = world.build(
            clock=SMS_WINDOW_OPEN_AT,
            channel=Channel.VOICE,
            consent_type=ConsentType.EXPRESS_WRITTEN,
        )

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.VOICE
        )

        assert_fields_equal(
            attempt,
            recipient_local_minutes=540,
            recipient_local_time="09:00",
            effective_window_start_minutes=480,
            effective_window_end_minutes=1260,
        )

    def test_03_one_minute_before_the_raised_start_is_refused(self, world):
        """At recipient-local 08:59 the narrowed SMS window has not opened yet.

        PRD §3.8:
        "Admission is half-open: the attempt is permitted when `recipient_local_minutes` is
        greater than or equal to `effective_window_start_minutes` and strictly less than
        `effective_window_end_minutes`."
        PRD §3.8:
        "Failing this test refuses the attempt with `ERR_OUTSIDE_CALLING_WINDOW`."

        Design: Difficulty/combinatorial_formula/sms_oral_consent_window_clamped_by_nested_min_max
        """
        built = _sms_on_oral_consent(world, SMS_ONE_MINUTE_EARLY_AT)

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.SMS,
            ),
            world.operator,
        )

        assert_error(response, ApiErrorId.OUTSIDE_CALLING_WINDOW)

    def test_04_exactly_at_the_lowered_end_is_outside_the_window(self, world):
        """Recipient-local 20:30 sits exactly on the shifted end, which is excluded.

        PRD §3.8:
        "A recipient-local time exactly at the start is inside the window; a
        recipient-local time exactly at the end is outside it."

        Design: Difficulty/combinatorial_formula/sms_oral_consent_window_clamped_by_nested_min_max
        """
        built = _sms_on_oral_consent(world, SMS_WINDOW_CLOSE_AT)

        response = world.api.create_contact_attempt(
            factories.contact_attempt_payload(
                campaign_id=built["campaign"]["id"],
                contact_id=built["contact"]["id"],
                channel=Channel.SMS,
            ),
            world.operator,
        )

        assert_error(response, ApiErrorId.OUTSIDE_CALLING_WINDOW)

    def test_05_one_minute_before_the_lowered_end_is_still_inside(self, world):
        """Recipient-local 20:29 is the last admissible minute of the narrowed SMS window.

        PRD §3.8:
        "Admission is half-open: the attempt is permitted when `recipient_local_minutes` is
        greater than or equal to `effective_window_start_minutes` and strictly less than
        `effective_window_end_minutes`."

        Design: Difficulty/combinatorial_formula/sms_oral_consent_window_clamped_by_nested_min_max
        """
        built = _sms_on_oral_consent(world, SMS_ONE_MINUTE_BEFORE_CLOSE_AT)

        attempt = world.create_attempt(
            built["campaign"]["id"], built["contact"]["id"], Channel.SMS
        )

        assert_fields_equal(
            attempt,
            recipient_local_minutes=1229,
            recipient_local_time="20:29",
            effective_window_start_minutes=540,
            effective_window_end_minutes=1230,
        )


class TestRollingComplianceRate:
    """The seven-day view of the regulatory measure and its two-stage rounding."""

    def test_06_each_day_is_rounded_before_the_mean_is_taken(self, world):
        """A 33.33 day and a 50.00 day average to 41.67, not to the pooled 40.00.

        PRD §2.7:
        "One rate in this domain is rounded twice, in a fixed order: the rolling compliance
        rate first rounds each contributing day's rate to 2 decimal places and only then
        rounds the mean of those already-rounded day values to 2 decimal places."
        PRD §3.8:
        "Each day is rounded first and the mean of those rounded values is rounded second;
        pooling the days' abandoned counts and live-answer counts and dividing once is a
        different number and is not what this rate means."

        Design: Difficulty/combinatorial_formula/rolling_compliance_rate_rounds_each_day_before_averaging
        """
        built = world.build(attempt_budget_total=6, abandonment_limit_pct=60.0)

        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[0],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[1],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )
        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[2],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=2,
        )
        _place_and_record(
            world,
            built,
            DAY_TWO_ATTEMPTS_AT[0],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world,
            built,
            DAY_TWO_ATTEMPTS_AT[1],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            measurement_date="2026-08-04",
            live_answer_count_today=2,
            abandoned_count_today=1,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)
        assert_decimal_equals(campaign["rolling_compliance_rate_pct"], 41.67)
        assert_status(campaign, CampaignStatus.ACTIVE)

        history = campaign["daily_rate_history"]
        assert len(history) == 1, "expected one closed day, got %r" % (history,)
        assert_fields_equal(
            history[0], date="2026-08-03", live_answer_count=3, abandoned_count=1
        )
        assert_decimal_equals(history[0]["rate_pct"], 33.33)

    def test_07_a_day_without_live_answers_contributes_no_sample(self, world):
        """A day whose only disposition is a no-answer drops out of the average entirely.

        PRD §3.8:
        "A date with zero live answers is skipped entirely and contributes no sample at all
        — it does not contribute a `0.00`."
        PRD §3.8:
        "When no date in the window contributes a sample, `rolling_compliance_rate_pct` is
        `0.00`; otherwise it is the sum of the contributed samples divided by the number of
        contributed samples, rounded half up to two decimal places."

        Design: Difficulty/combinatorial_formula/rolling_compliance_rate_rounds_each_day_before_averaging
        """
        built = world.build(attempt_budget_total=6, abandonment_limit_pct=60.0)

        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[0],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )
        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[1],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )
        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[2],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=2,
        )
        _place_and_record(
            world, built, DAY_TWO_ATTEMPTS_AT[0], outcome=AttemptOutcome.NO_ANSWER
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_fields_equal(
            campaign,
            measurement_date="2026-08-04",
            live_answer_count_today=0,
            abandoned_count_today=0,
            no_answer_count_today=1,
        )
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 0.00)
        assert_decimal_equals(campaign["rolling_compliance_rate_pct"], 33.33)

        history = campaign["daily_rate_history"]
        assert len(history) == 1, "expected one closed day, got %r" % (history,)
        assert_decimal_equals(history[0]["rate_pct"], 33.33)


class TestDialerPacingCeiling:
    """The line ceiling, computed in five ordered steps and snapshotted per attempt."""

    def test_08_approval_computes_the_ceiling_from_a_clamped_headroom(self, world):
        """Fifty points of headroom clamp to two, giving a multiplier of 1.5 and a ceiling of 7.

        PRD §3.6:
        "Second, that headroom is clamped into the range from `0.00` to a cap of 2.00
        percentage points — negative headroom becomes zero, headroom above two points
        becomes two."
        PRD §3.6:
        "Fourth, the line ceiling is the greater of `agents_available` itself and the
        product of `agents_available` and the multiplier truncated downwards to a whole
        number — the truncation happens at this step and nowhere else, because truncating
        before the clamp or clamping after a different truncation yields a different
        answer."

        Design: Difficulty/combinatorial_formula/dialer_pacing_lines_evaluation_order_pins_ceiling
        """
        built = world.build(
            attempt_budget_total=3,
            mode=DialerMode.PREDICTIVE,
            agents_available=5,
            abandonment_limit_pct=50.0,
        )

        assert_fields_equal(built["profile"], max_lines_last_computed=7)

        attempt = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
        assert_fields_equal(attempt, max_lines_snapshot=7)

    def test_09_a_negative_headroom_clamps_the_ceiling_down_to_the_agent_count(
        self, world
    ):
        """After a 100.00 persisted rate the next attempt is pinned to the five agents on hand.

        PRD §3.6:
        "First, the headroom is the profile's `abandonment_limit_pct` less the persisted
        `regulatory_abandonment_rate_pct` of the campaign being paced, taken as `0.00` when
        there is no such campaign."
        PRD §3.6:
        "The result is stored on the profile as `max_lines_last_computed` whenever an
        approval, an outcome or a void recomputes it, and is copied onto each new attempt
        as `max_lines_snapshot`, evaluated from the state persisted before that attempt was
        accepted."

        Design: Difficulty/combinatorial_formula/dialer_pacing_lines_evaluation_order_pins_ceiling
        """
        built = world.build(
            attempt_budget_total=3, agents_available=5, abandonment_limit_pct=50.0
        )

        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[0],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 100.00)
        assert_status(campaign, CampaignStatus.ACTIVE)

        world.set_clock(DAY_ONE_ATTEMPTS_AT[1])
        second = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
        assert_fields_equal(second, max_lines_snapshot=5)

    def test_10_a_live_answer_refreshes_the_stored_ceiling(self, world):
        """With the rate sitting at the 50.00 limit the multiplier falls to one and the ceiling to 5.

        PRD §3.8:
        "The supplied value is stored, `outcome_recorded_at` is stamped, the campaign's
        `live_answer_count_today` increases by one, both abandonment measures are
        recomputed, `rolling_compliance_rate_pct` is recomputed, and the dialer profile's
        `max_lines_last_computed` is refreshed."
        PRD §3.6:
        "Third, the multiplier is one plus the clamped headroom multiplied by a gain of
        0.25 lines per percentage point."

        Design: Difficulty/combinatorial_formula/dialer_pacing_lines_evaluation_order_pins_ceiling
        """
        built = world.build(
            attempt_budget_total=3, agents_available=5, abandonment_limit_pct=50.0
        )

        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[0],
            outcome=AttemptOutcome.ABANDONED,
            abandon_message_played=True,
        )
        _place_and_record(
            world,
            built,
            DAY_ONE_ATTEMPTS_AT[1],
            outcome=AttemptOutcome.CONNECTED_LIVE,
            agent_connect_seconds=1,
        )

        campaign = world.read_campaign(built["campaign"]["id"])
        assert_decimal_equals(campaign["regulatory_abandonment_rate_pct"], 50.00)

        profile = assert_ok(
            world.api.get_dialer_profile(built["profile"]["id"], world.operator)
        )
        assert_fields_equal(profile, max_lines_last_computed=5)

    def test_11_preview_mode_never_over_dials(self, world):
        """A preview profile ignores every earlier step and pins the ceiling to its agent count.

        PRD §3.6:
        "Fifth and last, a profile in `PREVIEW` mode never over-dials: its line ceiling is
        simply `agents_available`, regardless of everything computed before."

        Design: Difficulty/combinatorial_formula/dialer_pacing_lines_evaluation_order_pins_ceiling
        """
        built = world.build(
            attempt_budget_total=3,
            mode=DialerMode.PREVIEW,
            agents_available=5,
            abandonment_limit_pct=50.0,
        )

        assert_fields_equal(built["profile"], max_lines_last_computed=5)

        attempt = world.create_attempt(built["campaign"]["id"], built["contact"]["id"])
        assert_fields_equal(attempt, max_lines_snapshot=5)
