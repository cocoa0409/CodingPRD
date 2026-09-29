"""Parallel and cyclic state machines of the EAS Compliance API.

Three machines in this domain are not forward-only single-axis lines:

* an ``AlertEvent`` carries two independent dimensions — ``relay_state`` and
  ``accessibility_state`` — that advance without constraining each other;
* an ``EquipmentOutage`` is cyclic, revisiting ``REPAIR_IN_PROGRESS`` through
  ``VERIFICATION_FAILED`` while both downtime clocks keep accruing from the
  original ``detected_at``;
* a ``TestEvent`` loses ``READY`` to a station-posture cascade it never
  triggered itself and can re-enter ``READY`` afterwards.

Every test builds its own world: the harness restarts the API before each test,
so each one starts against an empty database with the logical clock at its
startup default 2026-08-01T00:00:00Z.
"""

from datetime import datetime

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    SOURCE_CALL_SIGNS,
    TEST_DEFAULTS,
    ApiErrorId,
    accessibility_payload,
    api_client,
    assign_source,
    create_active_plan,
    create_ready_device,
    create_relay_rule,
    evaluate_readiness,
    get_success_data,
    log_alert,
    register_station,
    schedule_test_event,
    set_clock,
    setup_outage,
    validate_error,
    validate_success,
)

ALERT_RECEIVED_AT = "2026-08-01T00:00:00Z"

OUTAGE_DETECTED_AT = "2026-08-03T08:00:00Z"
FIRST_RESTORE_AT = "2026-08-06T20:00:00Z"
SECOND_RESTORE_AT = "2026-08-08T08:00:00Z"

TEST_WINDOW_START = "2026-08-12T00:00:00Z"
TEST_WINDOW_END = "2026-08-12T01:00:00Z"
READINESS_AT = "2026-08-12T00:30:00Z"
IN_WINDOW_RESTORE_AT = "2026-08-12T00:40:00Z"
RE_EVALUATION_AT = "2026-08-12T00:50:00Z"


def _instant(value):
    """Parse a server-stamped ISO 8601 UTC instant so it compares by value."""
    assert value is not None, "expected a stamped instant, got null"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# ---------------------------------------------------------------------------
# AlertEvent — two dimensions advancing independently
# ---------------------------------------------------------------------------
def _relay_pending_alert():
    """A station whose single alert matched a county-scoped MANDATORY rule, so it
    sits at relay_state RELAY_PENDING / accessibility_state ACCESSIBILITY_UNVERIFIED."""
    plan = create_active_plan(("PEP",), ())
    rule = create_relay_rule(
        plan["id"],
        event_code="TOR",
        fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
        relay_class="MANDATORY",
        priority=10,
        forward_delay_seconds=30,
    )
    station = register_station(plan["id"])
    alert = log_alert(
        station["id"],
        ALERT_RECEIVED_AT,
        event_code="TOR",
        originator_sequence="KSPAR-0001",
        fips_codes=[TEST_DEFAULTS["FIPS_CODE"]],
    )
    return {"plan": plan, "rule": rule, "station": station, "alert": alert}


def _verify_accessibility_ok(alert_id, **measurements):
    return validate_success(
        api_client.verify_accessibility(
            alert_id, accessibility_payload(**measurements), ENGINEER
        ),
        200,
    )


class TestAlertRelayAndAccessibilityDimensions:
    """The forwarding axis and the accessibility axis of one alert row."""

    def test_alert_create_settles_relay_axis_leaving_accessibility_unverified(self):
        """PRD §3.5: "When a rule is selected, the alert moves `RECEIVED` → `RELAY_PENDING`, `matched_relay_rule_id` is set to that rule's `id`, and `forward_delay_seconds_applied` is copied from the rule's `forward_delay_seconds`."
        PRD §3.5: "Each alert row carries **two independent state dimensions** that advance without constraining each other."

        Design: Difficulty/non_linear_state_machine/alert_relay_and_accessibility_dimensions_advance_independently
        """
        ctx = _relay_pending_alert()
        alert = ctx["alert"]

        assert alert["relay_state"] == "RELAY_PENDING", (
            f"expected RELAY_PENDING after selection, got {alert['relay_state']}"
        )
        assert alert["matched_relay_rule_id"] == ctx["rule"]["id"]
        assert alert["relay_class_applied"] == "MANDATORY"
        assert alert["forward_delay_seconds_applied"] == 30
        assert alert["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED", (
            "the accessibility axis starts unverified whatever the relay axis did"
        )

    def test_accessibility_verification_leaves_relay_state_pending(self):
        """PRD §3.5: "Both outcomes write the three measurement fields and `accessibility_deficiency_points`, and neither touches `relay_state`."
        PRD §3.5: "The loudness excess in loudness units is the absolute difference between `audio_loudness_lufs` and the -24.0 LUFS target, reduced by the 2.0-unit tolerance and floored at zero — so a reading of -25.0 is inside tolerance and yields zero excess, while a reading of -30.0 deviates by 6.0 and yields an excess of 4.0."
        PRD §3.5: "The verdict is inclusive at the boundary: `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_PASSED` when `accessibility_deficiency_points` is 1.00 or less, and `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_FAILED` when it is strictly greater than 1.00."

        Design: Difficulty/non_linear_state_machine/alert_relay_and_accessibility_dimensions_advance_independently
        """
        ctx = _relay_pending_alert()
        alert_id = ctx["alert"]["id"]

        verified = _verify_accessibility_ok(
            alert_id,
            visual_crawl_seconds=60,
            audio_loudness_lufs=-26.0,
            caption_interaction="NONE",
        )

        assert verified["accessibility_deficiency_points"] == pytest.approx(0.00, abs=0.01), (
            "crawl shortfall 0 and loudness excess 0.0 leave 0.00 deficiency points"
        )
        assert verified["accessibility_state"] == "ACCESSIBILITY_PASSED"

        reread = get_success_data(api_client.get_alert_event(alert_id, ADMIN))
        assert reread["relay_state"] == "RELAY_PENDING", (
            f"the accessibility move must not touch the relay axis, got {reread['relay_state']}"
        )
        assert reread["matched_relay_rule_id"] == ctx["rule"]["id"]
        assert reread["relay_class_applied"] == "MANDATORY"

    def test_confirm_relay_leaves_accessibility_state_untouched(self):
        """PRD §3.5: "Confirming that the forward actually went out moves the alert `RELAY_PENDING` → `RELAYED`; attempting it on an alert whose `relay_state` is anything else is rejected with `ERR_ALERT_NOT_RELAY_PENDING`."
        PRD §3.5: "Confirmation touches only the forwarding dimension and leaves `accessibility_state` exactly as it was."

        Design: Difficulty/non_linear_state_machine/alert_relay_and_accessibility_dimensions_advance_independently
        """
        ctx = _relay_pending_alert()
        alert_id = ctx["alert"]["id"]
        _verify_accessibility_ok(
            alert_id,
            visual_crawl_seconds=60,
            audio_loudness_lufs=-26.0,
            caption_interaction="NONE",
        )

        confirmed = validate_success(api_client.confirm_relay(alert_id, ENGINEER), 200)

        assert confirmed["relay_state"] == "RELAYED"
        assert confirmed["accessibility_state"] == "ACCESSIBILITY_PASSED", (
            "the relay move must leave the accessibility axis where it was"
        )
        assert confirmed["accessibility_deficiency_points"] == pytest.approx(0.00, abs=0.01)

    def test_second_accessibility_verification_rejected_after_relay_confirmed(self):
        """PRD §3.5: "Verification is a once-only act: the alert's `accessibility_state` must be `ACCESSIBILITY_UNVERIFIED`, and a second attempt is rejected with `ERR_ACCESSIBILITY_ALREADY_VERIFIED`."
        PRD §3.5: "Both outcomes write the three measurement fields and `accessibility_deficiency_points`, and neither touches `relay_state`."

        Design: Difficulty/non_linear_state_machine/alert_relay_and_accessibility_dimensions_advance_independently
        """
        ctx = _relay_pending_alert()
        alert_id = ctx["alert"]["id"]
        _verify_accessibility_ok(
            alert_id,
            visual_crawl_seconds=60,
            audio_loudness_lufs=-26.0,
            caption_interaction="NONE",
        )
        validate_success(api_client.confirm_relay(alert_id, ENGINEER), 200)

        validate_error(
            api_client.verify_accessibility(
                alert_id,
                accessibility_payload(
                    visual_crawl_seconds=120,
                    audio_loudness_lufs=-24.0,
                    caption_interaction="NONE",
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_ACCESSIBILITY_ALREADY_VERIFIED,
            409,
        )

        reread = get_success_data(api_client.get_alert_event(alert_id, ADMIN))
        assert reread["visual_crawl_seconds"] == 60, (
            "the rejected re-verification must not rewrite the measurements"
        )
        assert reread["audio_loudness_lufs"] == pytest.approx(-26.0, abs=0.01)
        assert reread["accessibility_state"] == "ACCESSIBILITY_PASSED"
        assert reread["relay_state"] == "RELAYED", (
            "a rejected accessibility write leaves the relay axis alone too"
        )


# ---------------------------------------------------------------------------
# EquipmentOutage — the cyclic repair machine
# ---------------------------------------------------------------------------
def _outage_at_first_restore():
    """An outage detected 2026-08-03T08:00:00Z, repaired once and restored at
    2026-08-06T20:00:00Z, i.e. sitting in RESTORED awaiting verification."""
    plan = create_active_plan(("PEP",), ())
    station = register_station(plan["id"])
    device = create_ready_device(station["id"])
    set_clock(OUTAGE_DETECTED_AT)
    outage = setup_outage(
        device["id"],
        OUTAGE_DETECTED_AT,
        failure_summary="encoder audio card intermittent",
    )
    get_success_data(api_client.start_repair(outage["id"], ENGINEER))
    set_clock(FIRST_RESTORE_AT)
    restored = get_success_data(api_client.restore_outage(outage["id"], ENGINEER))
    return {
        "station": station,
        "device": device,
        "outage_id": outage["id"],
        "restored": restored,
    }


def _reject_restoration(outage_id):
    return validate_success(
        api_client.fail_verification(
            outage_id,
            ADMIN,
            {"verification_note": "audio card still dropping on the second pass"},
        ),
        200,
    )


class TestOutageRepairCycle:
    """RESTORED → VERIFICATION_FAILED → REPAIR_IN_PROGRESS → RESTORED, twice measured."""

    def test_first_restore_measures_both_clocks_from_detected_at(self):
        """PRD §3.4: "Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Then `continuous_clock_breached` is true when `continuous_downtime_hours` is strictly greater than 60 hours — two and a half days of unbroken outage — and false when it equals 60 hours or is less."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."
        PRD §3.4: "Both entries stamp `repair_started_at` from the logical clock, but only the entry from `VERIFICATION_FAILED` increases `repair_cycle_count` by one — the counter measures re-work, so the first repair attempt leaves it at 0."

        Design: Difficulty/non_linear_state_machine/outage_repair_cycle_reenters_repair_and_recomputes_from_original_detected_at
        """
        ctx = _outage_at_first_restore()
        restored = ctx["restored"]

        assert restored["status"] == "RESTORED"
        assert restored["continuous_downtime_hours"] == pytest.approx(84.00, abs=0.01), (
            "2026-08-03T08:00Z to 2026-08-06T20:00Z is 302400 s / 3600 = 84.00 h"
        )
        assert restored["obligation_downtime_hours"] == pytest.approx(48.00, abs=0.01), (
            "12.00 obligation hours on each of 08-03, 08-04, 08-05 and 08-06"
        )
        assert restored["continuous_clock_breached"] is True, "84.00 > 60"
        assert restored["obligation_breached"] is False, "48.00 is not strictly greater than 48"
        assert restored["repair_cycle_count"] == 0, (
            "the first repair attempt, entered from OPEN, leaves the counter at 0"
        )
        assert _instant(restored["restored_at"]) == _instant(FIRST_RESTORE_AT)

    def test_failed_verification_clears_restored_at_and_both_downtime_figures(self):
        """PRD §3.4: "Rejection moves the row `RESTORED` → `VERIFICATION_FAILED`, may carry an optional `verification_note`, clears `restored_at` back to null, clears both `continuous_downtime_hours` and `obligation_downtime_hours` back to null, and leaves the unit `FAILED`; the outage is then eligible to re-enter `REPAIR_IN_PROGRESS`, closing the cycle `RESTORED` → `VERIFICATION_FAILED` → `REPAIR_IN_PROGRESS` → `RESTORED`."

        Design: Difficulty/non_linear_state_machine/outage_repair_cycle_reenters_repair_and_recomputes_from_original_detected_at
        """
        ctx = _outage_at_first_restore()

        rejected = _reject_restoration(ctx["outage_id"])

        assert rejected["status"] == "VERIFICATION_FAILED"
        assert rejected["restored_at"] is None, "rejection clears restored_at back to null"
        assert rejected["continuous_downtime_hours"] is None
        assert rejected["obligation_downtime_hours"] is None

        device = get_success_data(api_client.get_device(ctx["device"]["id"], ADMIN))
        assert device["status"] == "FAILED", "rejection leaves the unit FAILED"

    def test_repair_restarted_from_verification_failed_increments_repair_cycle_count(self):
        """PRD §3.4: "Starting a repair is permitted from two starting statuses — `OPEN` → `REPAIR_IN_PROGRESS` and `VERIFICATION_FAILED` → `REPAIR_IN_PROGRESS`; starting a repair from any other status is rejected with `ERR_OUTAGE_NOT_REPAIRABLE`."
        PRD §3.4: "Both entries stamp `repair_started_at` from the logical clock, but only the entry from `VERIFICATION_FAILED` increases `repair_cycle_count` by one — the counter measures re-work, so the first repair attempt leaves it at 0."

        Design: Difficulty/non_linear_state_machine/outage_repair_cycle_reenters_repair_and_recomputes_from_original_detected_at
        """
        ctx = _outage_at_first_restore()
        _reject_restoration(ctx["outage_id"])

        restarted = validate_success(
            api_client.start_repair(ctx["outage_id"], ENGINEER), 200
        )

        assert restarted["status"] == "REPAIR_IN_PROGRESS"
        assert restarted["repair_cycle_count"] == 1, (
            "only the back-edge from VERIFICATION_FAILED increments the re-work counter"
        )

    def test_second_restore_recomputes_both_clocks_from_original_detected_at(self):
        """PRD §3.4: "Crucially, `detected_at` is never reset by any of this, so both downtime clocks keep accruing across every repair cycle from the original detection instant."
        PRD §3.4: "Accumulate the day contributions in seconds, divide the accumulated total by 3600, and round half-up to two decimal places to obtain `obligation_downtime_hours`."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."
        PRD §3.4: "Closing an outage is also what returns equipment to service."

        Design: Difficulty/non_linear_state_machine/outage_repair_cycle_reenters_repair_and_recomputes_from_original_detected_at
        """
        ctx = _outage_at_first_restore()
        _reject_restoration(ctx["outage_id"])
        get_success_data(api_client.start_repair(ctx["outage_id"], ENGINEER))
        set_clock(SECOND_RESTORE_AT)

        restored = validate_success(api_client.restore_outage(ctx["outage_id"], ENGINEER), 200)

        assert restored["status"] == "RESTORED"
        assert restored["continuous_downtime_hours"] == pytest.approx(120.00, abs=0.01), (
            "measured from the original detected_at: 432000 s / 3600 = 120.00 h"
        )
        assert restored["continuous_clock_breached"] is True, "120.00 > 60"
        assert restored["obligation_downtime_hours"] == pytest.approx(60.00, abs=0.01), (
            "12.00 h on each of 08-03..08-07; the 08:00 restore on 08-08 overlaps nothing"
        )
        assert restored["obligation_breached"] is True, "60.00 > 48"
        assert restored["repair_cycle_count"] == 1

        device = get_success_data(api_client.get_device(ctx["device"]["id"], ADMIN))
        assert device["status"] == "FAILED", (
            "restore is not a device-level transition; only closing returns the unit to service"
        )


# ---------------------------------------------------------------------------
# TestEvent — READY lost to a cascade, then regained
# ---------------------------------------------------------------------------
def _station_with_ready_test_event():
    """Plan requiring PEP and NWS, one READY device carrying both assignments, and a
    WEEKLY event evaluated to READY at 2026-08-12T00:30:00Z."""
    plan = create_active_plan(("PEP", "NWS"), ())
    station = register_station(plan["id"])
    device = create_ready_device(station["id"])
    ma1 = assign_source(
        station["id"], device["id"], source_type="PEP", source_call_sign=SOURCE_CALL_SIGNS["PEP"]
    )
    ma2 = assign_source(
        station["id"], device["id"], source_type="NWS", source_call_sign=SOURCE_CALL_SIGNS["NWS"]
    )
    event = schedule_test_event(station["id"], TEST_WINDOW_START, TEST_WINDOW_END)
    set_clock(READINESS_AT)
    event = evaluate_readiness(event["id"])
    return {
        "station_id": station["id"],
        "device_id": device["id"],
        "ma1": ma1,
        "ma2": ma2,
        "event": event,
        "event_id": event["id"],
    }


def _fail_and_recover_the_only_device(ctx):
    """File the outage that suspends both assignments, then repair, close and record a
    receipt on each assignment so the station climbs back to COMPLIANT."""
    outage = setup_outage(
        ctx["device_id"],
        READINESS_AT,
        failure_summary="decoder power supply failed mid-window",
    )
    get_success_data(api_client.start_repair(outage["id"], ENGINEER))
    set_clock(IN_WINDOW_RESTORE_AT)
    restored = get_success_data(api_client.restore_outage(outage["id"], ENGINEER))
    closed = get_success_data(api_client.close_outage(outage["id"], ADMIN))
    station_after_close = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
    ma1_after_close = get_success_data(
        api_client.get_monitoring_assignment(ctx["ma1"]["id"], ADMIN)
    )
    ma2_after_close = get_success_data(
        api_client.get_monitoring_assignment(ctx["ma2"]["id"], ADMIN)
    )
    get_success_data(api_client.record_receipt(ctx["ma1"]["id"], ENGINEER))
    station_after_first_receipt = get_success_data(
        api_client.get_station(ctx["station_id"], ADMIN)
    )
    get_success_data(api_client.record_receipt(ctx["ma2"]["id"], ENGINEER))
    station_after_second_receipt = get_success_data(
        api_client.get_station(ctx["station_id"], ADMIN)
    )
    return {
        "outage_id": outage["id"],
        "restored": restored,
        "closed": closed,
        "station_after_close": station_after_close,
        "ma1_after_close": ma1_after_close,
        "ma2_after_close": ma2_after_close,
        "station_after_first_receipt": station_after_first_receipt,
        "station_after_second_receipt": station_after_second_receipt,
    }


class TestTestEventReadinessLostAndRegained:
    """READY → READINESS_PENDING → READY on one event, driven by station posture."""

    def test_ready_event_reverts_when_station_posture_enters_suspended_filings(self):
        """PRD §3.6: "Readiness can also be *lost* without any client action: a station whose posture transitions into `SUSPENDED_FILINGS` drags every one of its `READY` events back `READY` → `READINESS_PENDING`, clearing both `readiness_score` and `readiness_evaluated_at` to null."
        PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"

        Design: Difficulty/non_linear_state_machine/test_event_reverts_ready_to_readiness_pending_and_back_to_ready
        """
        ctx = _station_with_ready_test_event()
        event = ctx["event"]
        assert event["status"] == "READY", "40 + 40 + 0 = 80.00 is the inclusive pass threshold"
        assert event["readiness_score"] == pytest.approx(80.00, abs=0.01)
        assert _instant(event["readiness_evaluated_at"]) == _instant(READINESS_AT)

        setup_outage(
            ctx["device_id"],
            READINESS_AT,
            failure_summary="decoder power supply failed mid-window",
        )

        station = get_success_data(api_client.get_station(ctx["station_id"], ADMIN))
        assert station["accessible_source_count"] == 0
        assert station["compliance_score"] == pytest.approx(50.00, abs=0.01), (
            "both required sources are missing: 100.00 - 2 * 25.00"
        )
        assert station["compliance_posture"] == "SUSPENDED_FILINGS"

        reverted = get_success_data(api_client.get_test_event(ctx["event_id"], ADMIN))
        assert reverted["status"] == "READINESS_PENDING", (
            f"the cascade must knock READY back, got {reverted['status']}"
        )
        assert reverted["readiness_score"] is None
        assert reverted["readiness_evaluated_at"] is None

    def test_posture_recovery_alone_leaves_the_event_in_readiness_pending(self):
        """PRD §2.10: "Transitions *out of* `SUSPENDED_FILINGS` (to `WATCH` or to `COMPLIANT`) and transitions between `COMPLIANT` and `WATCH` in either direction carry no such revert; they write `compliance_score` and `compliance_variant_applied` and nothing more."
        PRD §3.3: "When the outage is later closed and the unit returns to `READY`, every assignment on it sitting in `SUSPENDED` moves `SUSPENDED` → `SILENT` rather than straight back to `ACTIVE`, with `silence_flagged_at` stamped at the close instant and a station recompute event fired; a fresh receipt is required before the row counts toward coverage again."
        PRD §3.3: "On a row in `SILENT` it additionally moves the row `SILENT` → `ACTIVE` and clears `silence_flagged_at` back to null; on a row already in `ACTIVE` it leaves the status alone — `ACTIVE` → `ACTIVE` — and only refreshes `last_receipt_at`."
        PRD §3.8: "10.00 points for each assignment counted in `silent_assignment_count`;"

        Design: Difficulty/non_linear_state_machine/test_event_reverts_ready_to_readiness_pending_and_back_to_ready
        """
        ctx = _station_with_ready_test_event()
        recovery = _fail_and_recover_the_only_device(ctx)

        assert recovery["restored"]["continuous_downtime_hours"] == pytest.approx(0.17, abs=0.01), (
            "600 s / 3600 rounds half-up to 0.17"
        )
        assert recovery["restored"]["obligation_downtime_hours"] == pytest.approx(0.00, abs=0.01), (
            "00:30-00:40 lies entirely outside the 08:00-20:00 obligation window"
        )
        assert recovery["closed"]["status"] == "CLOSED"
        assert recovery["ma1_after_close"]["status"] == "SILENT"
        assert recovery["ma2_after_close"]["status"] == "SILENT"
        assert recovery["station_after_close"]["compliance_score"] == pytest.approx(
            30.00, abs=0.01
        ), "100.00 - 2 * 25.00 missing sources - 2 * 10.00 silent assignments"
        assert recovery["station_after_first_receipt"]["compliance_score"] == pytest.approx(
            65.00, abs=0.01
        ), "one source back: 100.00 - 25.00 - 10.00"
        assert recovery["station_after_second_receipt"]["compliance_score"] == pytest.approx(
            100.00, abs=0.01
        )
        assert recovery["station_after_second_receipt"]["compliance_posture"] == "COMPLIANT"
        assert recovery["station_after_second_receipt"]["silent_assignment_count"] == 0

        still_pending = get_success_data(api_client.get_test_event(ctx["event_id"], ADMIN))
        assert still_pending["status"] == "READINESS_PENDING", (
            "climbing out of SUSPENDED_FILINGS carries no revert and no restore of READY"
        )
        assert still_pending["readiness_score"] is None

    def test_reverted_event_re_enters_ready_on_a_fresh_evaluation(self):
        """PRD §3.6: "A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."
        PRD §3.6: "Every evaluation overwrites both `readiness_score` and `readiness_evaluated_at`, so a re-run replaces rather than supplements the earlier figures."

        Design: Difficulty/non_linear_state_machine/test_event_reverts_ready_to_readiness_pending_and_back_to_ready
        """
        ctx = _station_with_ready_test_event()
        _fail_and_recover_the_only_device(ctx)
        set_clock(RE_EVALUATION_AT)

        re_evaluated = validate_success(
            api_client.evaluate_readiness(ctx["event_id"], ENGINEER), 200
        )

        assert re_evaluated["status"] == "READY", (
            "READINESS_PENDING → READY is a legal re-run outcome at 80.00"
        )
        assert re_evaluated["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "1/1 ready devices, 2/2 source coverage, no recent alerts"
        )
        assert _instant(re_evaluated["readiness_evaluated_at"]) == _instant(RE_EVALUATION_AT)
