"""Calculation corners of the EAS Compliance API.

Every test in this module drives one derived number — relay-rule selection,
duplicate-suppression phase ordering, accessibility deficiency points, filing
penalty points, the station compliance score, the pre-test readiness score, a
log line's retention term, an inspection completeness score or the two downtime
clocks — to a boundary where two plausible readings of the arithmetic diverge,
and pins the value the PRD requires.

The harness restarts the API server before every individual test, so each test
starts against an empty database with the logical clock at its startup default
2026-08-01T00:00:00Z and builds every precondition itself.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    ENGINEER_USER_ID,
    INSPECTOR,
    OFFICER,
    api_client,
    append_log_entry,
    assign_source,
    create_active_plan,
    create_plan,
    create_ready_device,
    create_relay_rule,
    draft_response_payload,
    evaluate_readiness,
    file_results,
    get_success_data,
    log_alert,
    record_wireless_notice,
    register_device,
    register_station,
    run_log_review,
    schedule_test_event,
    set_clock,
    setup_inspection,
    setup_outage,
    station_summary,
    station_version,
    validate_success,
    verify_alert_accessibility,
)

CLOCK_START = "2026-08-01T00:00:00Z"


# ---------------------------------------------------------------------------
# Relay rule selection
# ---------------------------------------------------------------------------
class TestRelayRuleSelection:
    """The candidate pool, the ranking order and the mandatory upgrade."""

    @staticmethod
    def _plan_station_and_two_rules():
        """Plan KS 2026-R1 with a statewide and a county-scoped OPTIONAL TOR rule.

        The county rule carries the *worse* priority integer (9 against 1), so
        only a selector that ranks specificity before priority picks it.
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        rule_state = create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=5,
        )
        rule_county = create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=["20173"],
            relay_class="OPTIONAL",
            priority=9,
            forward_delay_seconds=45,
        )
        return plan, station, rule_state, rule_county

    def test_specificity_is_derived_from_the_location_scope(self):
        """PRD §3.1: "The server derives `specificity` from the location scope: 2 when `fips_codes` holds at least one entry, meaning the rule is county-scoped, and 1 when `fips_codes` is empty, meaning the rule is statewide."

        Design: Corner/calculations/selector_specificity_outranks_the_lower_priority_integer
        """
        _plan, _station, rule_state, rule_county = self._plan_station_and_two_rules()

        assert rule_state["specificity"] == 1, (
            f"an empty fips_codes array is statewide, got specificity "
            f"{rule_state['specificity']}"
        )
        assert rule_county["specificity"] == 2, (
            f"a non-empty fips_codes array is county-scoped, got specificity "
            f"{rule_county['specificity']}"
        )

    def test_county_rule_outranks_statewide_rule_with_smaller_priority(self):
        """PRD §3.5: "Candidates are ranked by `specificity` descending, so that a county-scoped rule with `specificity` 2 always outranks a statewide rule with `specificity` 1; among candidates of equal `specificity` the smaller `priority` integer ranks earlier; and when both `specificity` and `priority` tie, the earlier `created_at` wins."
        PRD §3.5: "When a rule is selected, the alert moves `RECEIVED` → `RELAY_PENDING`, `matched_relay_rule_id` is set to that rule's `id`, and `forward_delay_seconds_applied` is copied from the rule's `forward_delay_seconds`."

        Design: Corner/calculations/selector_specificity_outranks_the_lower_priority_integer
        """
        _plan, station, _rule_state, rule_county = self._plan_station_and_two_rules()

        alert = validate_success(
            api_client.create_alert_event(
                {
                    "station_id": station["id"],
                    "event_code": "TOR",
                    "originator_sequence": "KSAXS-1001",
                    "fips_codes": ["20173"],
                    "received_at": CLOCK_START,
                },
                ENGINEER,
            ),
            201,
        )

        assert alert["matched_relay_rule_id"] == rule_county["id"], (
            "specificity DESC is applied before priority ASC, so the county rule "
            f"must win; got {alert['matched_relay_rule_id']}"
        )
        assert alert["forward_delay_seconds_applied"] == 45, (
            "forward_delay_seconds_applied is copied from the selected rule, got "
            f"{alert['forward_delay_seconds_applied']}"
        )
        assert alert["relay_state"] == "RELAY_PENDING", (
            f"a selected rule moves the alert to RELAY_PENDING, got {alert['relay_state']}"
        )

    def test_selected_optional_rule_under_a_plan_without_the_code_stays_optional(self):
        """PRD §3.5: "The effective `relay_class_applied` is `MANDATORY` when either the selected rule's `relay_class` is `MANDATORY` **or** the alert's `event_code` appears in the governing plan's `mandatory_relay_event_codes`; otherwise it is `OPTIONAL`."

        Design: Corner/calculations/selector_specificity_outranks_the_lower_priority_integer
        """
        _plan, station, _rule_state, _rule_county = self._plan_station_and_two_rules()

        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-1002",
            fips_codes=["20173"],
        )

        assert alert["relay_class_applied"] == "OPTIONAL", (
            "the selected rule is OPTIONAL and TOR is not in the plan's "
            f"mandatory_relay_event_codes, got {alert['relay_class_applied']}"
        )
        assert alert["suppression_source"] == "NONE", (
            f"no suppression fired, got suppression_source {alert['suppression_source']}"
        )
        assert alert["suppression_reference_alert_id"] is None

    def test_fips_disjoint_county_rule_leaves_the_candidate_pool(self):
        """PRD §3.5: "The candidate pool is every relay rule that belongs to the receiving station's plan — that is, whose `state_plan_id` equals the station's `state_plan_id` — whose `status` is `ACTIVE`, whose `event_code` equals the alert's `event_code`, and whose location scope admits the alert: either the rule's `fips_codes` array is empty, making it statewide and therefore always in scope, or the rule's `fips_codes` shares at least one code with the alert's `fips_codes`."

        Design: Corner/calculations/retired_and_fips_disjoint_rules_leave_the_candidate_pool
        """
        _plan, station, rule_state, _rule_county = self._plan_station_and_two_rules()

        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-2001",
            fips_codes=["20999"],
        )

        assert alert["matched_relay_rule_id"] == rule_state["id"], (
            "['20173'] and ['20999'] do not intersect, so the county rule is "
            f"excluded from the pool; got {alert['matched_relay_rule_id']}"
        )
        assert alert["forward_delay_seconds_applied"] == 5, (
            "the statewide rule's forward_delay_seconds is 5, got "
            f"{alert['forward_delay_seconds_applied']}"
        )
        assert alert["suppression_source"] == "NONE"

    def test_retired_rule_leaves_the_candidate_pool_for_a_matching_alert(self):
        """PRD §3.1: "Retirement by a `ComplianceAdmin` moves a rule `ACTIVE` → `RETIRED` and takes it out of the selector's candidate pool for every future alert; retiring a rule that is already `RETIRED` is rejected with `ERR_RELAY_RULE_NOT_ACTIVE`."

        Design: Corner/calculations/retired_and_fips_disjoint_rules_leave_the_candidate_pool
        """
        _plan, station, rule_state, rule_county = self._plan_station_and_two_rules()

        retired = validate_success(
            api_client.retire_relay_rule(rule_county["id"], ADMIN), 200
        )
        assert retired["status"] == "RETIRED", (
            f"retire moves the rule to RETIRED, got {retired['status']}"
        )

        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-2002",
            fips_codes=["20173"],
        )

        assert alert["matched_relay_rule_id"] == rule_state["id"], (
            "the retired county rule is out of the pool even though its FIPS list "
            f"matches; got {alert['matched_relay_rule_id']}"
        )
        assert alert["forward_delay_seconds_applied"] == 5

    def test_alert_event_code_with_no_active_rule_is_unmatched_optional(self):
        """PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."

        Design: Corner/calculations/retired_and_fips_disjoint_rules_leave_the_candidate_pool
        """
        _plan, station, _rule_state, _rule_county = self._plan_station_and_two_rules()

        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="SVR",
            originator_sequence="KSAXS-2003",
            fips_codes=["20173"],
        )

        assert alert["relay_state"] == "UNMATCHED_OPTIONAL", (
            f"no ACTIVE rule carries event_code SVR, got {alert['relay_state']}"
        )
        assert alert["matched_relay_rule_id"] is None
        assert alert["relay_class_applied"] == "NONE"
        assert alert["forward_delay_seconds_applied"] == 0

    def test_plan_mandatory_event_code_upgrades_an_optional_rule(self):
        """PRD §3.5: "The effective `relay_class_applied` is `MANDATORY` when either the selected rule's `relay_class` is `MANDATORY` **or** the alert's `event_code` appears in the governing plan's `mandatory_relay_event_codes`; otherwise it is `OPTIONAL`."
        PRD §3.5: "That second clause is the statewide override: a plan can force an event code to be mandatory even where the matching rule is written as `OPTIONAL`."

        Design: Corner/calculations/plan_mandatory_event_code_upgrades_an_optional_rule
        """
        set_clock(CLOCK_START)
        plan_ks = create_active_plan(("PEP",), ("TOR",), state_code="KS")
        plan_ne = create_active_plan(("PEP",), (), state_code="NE")
        station_ks = register_station(plan_ks["id"], call_sign="KWEA")
        station_ne = register_station(plan_ne["id"], call_sign="KNEB")
        rule_ks = create_relay_rule(
            plan_ks["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        rule_ne = create_relay_rule(
            plan_ne["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )

        alert_ks = log_alert(
            station_ks["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-3001",
            fips_codes=["20173"],
        )
        alert_ne = log_alert(
            station_ne["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="NEAXS-3001",
            fips_codes=["31055"],
        )

        assert alert_ks["matched_relay_rule_id"] == rule_ks["id"]
        assert alert_ks["relay_class_applied"] == "MANDATORY", (
            "plan_ks lists TOR in mandatory_relay_event_codes, so the OPTIONAL "
            f"rule is upgraded; got {alert_ks['relay_class_applied']}"
        )
        assert alert_ne["matched_relay_rule_id"] == rule_ne["id"]
        assert alert_ne["relay_class_applied"] == "OPTIONAL", (
            "the identical rule under a plan without the code stays OPTIONAL, got "
            f"{alert_ne['relay_class_applied']}"
        )
        assert alert_ks["relay_state"] == "RELAY_PENDING"
        assert alert_ne["relay_state"] == "RELAY_PENDING"
        assert alert_ks["forward_delay_seconds_applied"] == 0
        assert alert_ne["forward_delay_seconds_applied"] == 0

        stored_rule_ks = get_success_data(api_client.get_relay_rule(rule_ks["id"], ADMIN))
        assert stored_rule_ks["relay_class"] == "OPTIONAL", (
            "the upgrade is per-alert and must not rewrite the rule, got "
            f"{stored_rule_ks['relay_class']}"
        )


# ---------------------------------------------------------------------------
# Duplicate suppression phase ordering
# ---------------------------------------------------------------------------
class TestDuplicateSuppressionPhaseOrder:
    """Phase A runs before phase B, and the winning phase is observable."""

    @staticmethod
    def _station_with_rule_and_wireless_notice():
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        record_wireless_notice(
            station["id"],
            "2026-08-01T00:00:00Z",
            originator_sequence="KSAXS-4001",
            event_code="TOR",
            fips_codes=["20173"],
        )
        # Both probe alerts are back-dated inside the notice's buffered window.
        set_clock("2026-08-01T00:30:00Z")
        return station

    def test_wireless_notice_suppression_leaves_the_reference_alert_id_null(self):
        """PRD §3.5: "When both conditions hold, the alert again moves `RECEIVED` → `SUPPRESSED_DUPLICATE`, `suppression_source` becomes `WIRELESS_NOTICE`, and `suppression_reference_alert_id` is left null — the suppressing artefact is a carrier notice, not an alert row, so there is nothing to point at."
        PRD §3.5: "For each such notice the phase B window is **closed at both ends**: it starts 120 seconds before that notice's `wea_sent_at` and ends 1800 seconds plus 120 seconds after it — that is, from two minutes before the wireless send to thirty-two minutes after it — with both bounds included."

        Design: Corner/calculations/phase_a_station_repeat_wins_when_a_wireless_notice_also_matches
        """
        station = self._station_with_rule_and_wireless_notice()

        alert_first = log_alert(
            station["id"],
            "2026-08-01T00:20:00Z",
            event_code="TOR",
            originator_sequence="KSAXS-4001",
            fips_codes=["20173"],
        )

        assert alert_first["relay_state"] == "SUPPRESSED_DUPLICATE", (
            "00:20:00Z lies inside the closed buffered window, got "
            f"{alert_first['relay_state']}"
        )
        assert alert_first["suppression_source"] == "WIRELESS_NOTICE", (
            f"phase A's pool was empty, got {alert_first['suppression_source']}"
        )
        assert alert_first["suppression_reference_alert_id"] is None, (
            "a carrier notice is not an alert row, so the reference id stays null"
        )
        assert alert_first["matched_relay_rule_id"] is None, (
            "suppression skips the selector even though a statewide rule matches"
        )
        assert alert_first["relay_class_applied"] == "NONE"

    def test_station_repeat_wins_over_a_matching_wireless_notice(self):
        """PRD §3.5: "Phase A looks for a station repeat. Its pool is every existing alert row of the *same* `station_id` with the *same* `originator_sequence` and the *same* `event_code`, regardless of that row's `relay_state`."
        PRD §3.5: "If any pool row's `received_at` falls inside that window, the new alert is suppressed by moving `RECEIVED` → `SUPPRESSED_DUPLICATE`: `suppression_source` becomes `STATION_REPEAT`, and `suppression_reference_alert_id` is set to the `id` of the pool row with the greatest `received_at`, breaking a tie on equal `received_at` by taking the row with the earliest `created_at`."
        PRD §3.5: "Phase A stopping the pipeline means phase B never runs and the relay selector never runs."

        Design: Corner/calculations/phase_a_station_repeat_wins_when_a_wireless_notice_also_matches
        """
        station = self._station_with_rule_and_wireless_notice()

        alert_first = log_alert(
            station["id"],
            "2026-08-01T00:20:00Z",
            event_code="TOR",
            originator_sequence="KSAXS-4001",
            fips_codes=["20173"],
        )
        alert_third = log_alert(
            station["id"],
            "2026-08-01T00:25:00Z",
            event_code="TOR",
            originator_sequence="KSAXS-4001",
            fips_codes=["20173"],
        )

        assert alert_third["relay_state"] == "SUPPRESSED_DUPLICATE"
        assert alert_third["suppression_source"] == "STATION_REPEAT", (
            "both phases would fire, and phase A runs first, got "
            f"{alert_third['suppression_source']}"
        )
        assert alert_third["suppression_reference_alert_id"] == alert_first["id"], (
            "the phase A pool admits rows in any relay_state, including the "
            f"already-suppressed first alert; got "
            f"{alert_third['suppression_reference_alert_id']}"
        )
        assert alert_third["matched_relay_rule_id"] is None
        assert alert_third["forward_delay_seconds_applied"] == 0


# ---------------------------------------------------------------------------
# Accessibility deficiency points
# ---------------------------------------------------------------------------
class TestAccessibilityDeficiencyPoints:
    """One second of crawl separates the two accessibility verdicts."""

    @pytest.mark.parametrize(
        ("visual_crawl_seconds", "expected_points", "expected_state"),
        [
            (41, 0.95, "ACCESSIBILITY_PASSED"),
            (40, 1.00, "ACCESSIBILITY_PASSED"),
            (39, 1.05, "ACCESSIBILITY_FAILED"),
        ],
    )
    def test_pass_boundary_is_inclusive_at_exactly_one_point(
        self, visual_crawl_seconds, expected_points, expected_state
    ):
        """PRD §3.5: "The crawl shortfall in seconds is the amount by which the measured `visual_crawl_seconds` falls below the 60-second minimum crawl duration, floored at zero — so a 75-second crawl has a shortfall of zero, and a 40-second crawl has a shortfall of 20."
        PRD §3.5: "Add the base term, the capped coupling term and the caption penalty; take the smaller of that sum and the overall deficiency ceiling of 8.00 points; and round the result half-up to two decimal places."
        PRD §3.5: "The verdict is inclusive at the boundary: `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_PASSED` when `accessibility_deficiency_points` is 1.00 or less, and `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_FAILED` when it is strictly greater than 1.00."

        Design: Corner/calculations/accessibility_pass_boundary_is_inclusive_at_exactly_one_point
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence=f"KSAXS-50{visual_crawl_seconds}",
            fips_codes=["20173"],
        )

        verified = validate_success(
            api_client.verify_accessibility(
                alert["id"],
                {
                    "visual_crawl_seconds": visual_crawl_seconds,
                    "audio_loudness_lufs": -26.0,
                    "caption_interaction": "NONE",
                },
                ENGINEER,
            ),
            200,
        )

        assert verified["accessibility_deficiency_points"] == pytest.approx(
            expected_points, abs=0.01
        ), (
            f"expected accessibility_deficiency_points {expected_points} for a "
            f"{visual_crawl_seconds}s crawl, got "
            f"{verified['accessibility_deficiency_points']}"
        )
        assert verified["accessibility_state"] == expected_state, (
            f"expected {expected_state} at {expected_points} points, got "
            f"{verified['accessibility_state']}"
        )

    def test_loudness_exactly_at_the_tolerance_edge_yields_no_excess(self):
        """PRD §3.5: "The loudness excess in loudness units is the absolute difference between `audio_loudness_lufs` and the -24.0 LUFS target, reduced by the 2.0-unit tolerance and floored at zero — so a reading of -25.0 is inside tolerance and yields zero excess, while a reading of -30.0 deviates by 6.0 and yields an excess of 4.0."
        PRD §3.5: "The coupling term multiplies the crawl shortfall in seconds by the loudness excess in loudness units and by a coupling rate of 0.01, then takes the smaller of that product and a coupling ceiling of 3.00 points — audio deviation is amplified when the crawl is also short, but the amplification alone can never exceed 3.00 points."

        Design: Corner/calculations/accessibility_pass_boundary_is_inclusive_at_exactly_one_point
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-5001",
            fips_codes=["20173"],
        )

        verified = verify_alert_accessibility(
            alert["id"],
            visual_crawl_seconds=40,
            audio_loudness_lufs=-26.0,
            caption_interaction="NONE",
        )

        # -26.0 sits exactly the 2.0-unit tolerance below the -24.0 target, so the
        # excess is 0.0 and the coupling term contributes nothing: the total is the
        # crawl term alone, 20 * 0.05 == 1.00.
        assert verified["accessibility_deficiency_points"] == pytest.approx(
            1.00, abs=0.01
        ), (
            "a reading exactly at the tolerance edge yields zero excess and zero "
            f"coupling, got {verified['accessibility_deficiency_points']}"
        )

    def test_accessibility_verdict_leaves_the_forwarding_dimension_alone(self):
        """PRD §3.5: "Both outcomes write the three measurement fields and `accessibility_deficiency_points`, and neither touches `relay_state`."

        Design: Corner/calculations/accessibility_pass_boundary_is_inclusive_at_exactly_one_point
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="TOR",
            originator_sequence="KSAXS-5002",
            fips_codes=["20173"],
        )
        assert alert["relay_state"] == "UNMATCHED_OPTIONAL"

        verified = verify_alert_accessibility(
            alert["id"],
            visual_crawl_seconds=39,
            audio_loudness_lufs=-26.0,
            caption_interaction="NONE",
        )

        assert verified["accessibility_state"] == "ACCESSIBILITY_FAILED"
        assert verified["relay_state"] == "UNMATCHED_OPTIONAL", (
            "the accessibility dimension moves alone, got relay_state "
            f"{verified['relay_state']}"
        )


# ---------------------------------------------------------------------------
# Filing penalty points
# ---------------------------------------------------------------------------
class TestFilingPenaltyPoints:
    """late_days, the per-line rounding order and the unconfirmed relay pool."""

    @staticmethod
    def _station_with_covered_source(mandatory_relay_event_codes=()):
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), mandatory_relay_event_codes)
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])
        assign_source(
            station["id"], device["id"], source_type="PEP", source_call_sign="WXPEP"
        )
        return plan, station, device

    @staticmethod
    def _log_and_close(station_id, device_id):
        """Schedule the canonical weekly window, take it READY, log one
        TRANSMISSION plus one RECEIPT line and close the logging phase."""
        event = schedule_test_event(
            station_id, "2026-08-12T00:00:00Z", "2026-08-12T01:00:00Z", test_type="WEEKLY"
        )
        set_clock("2026-08-12T00:30:00Z")
        event = evaluate_readiness(event["id"], ENGINEER)
        append_log_entry(event["id"], device_id, "TRANSMISSION")
        append_log_entry(event["id"], device_id, "RECEIPT", source_call_sign="WXPEP")
        closed = get_success_data(api_client.close_logging(event["id"], ENGINEER))
        return event, closed

    def _three_mandatory_alerts_one_confirmed(self, station_id):
        set_clock("2026-08-02T00:00:00Z")
        alerts = []
        for index in range(3):
            alerts.append(
                log_alert(
                    station_id,
                    "2026-08-02T00:00:00Z",
                    event_code="TOR",
                    originator_sequence=f"KSAXS-600{index + 1}",
                    fips_codes=["20173"],
                )
            )
        get_success_data(api_client.confirm_relay(alerts[2]["id"], ENGINEER))
        return alerts

    def test_unconfirmed_mandatory_relays_charge_half_a_point_each(self):
        """PRD §3.7: "`unconfirmed_relay_points` charges 0.50 points for each mandatory relay the station still has not confirmed: count the station's alert events whose `relay_class_applied` is `MANDATORY`, whose `relay_state` is still `RELAY_PENDING`, and whose `received_at` falls inside the **closed** interval running from 30 days before `filed_at` through `filed_at` itself, multiply that count by 0.50, and round half-up to two decimals."
        PRD §3.5: "Its one downstream effect is fiscal: a confirmed alert leaves the unconfirmed-mandatory-relay pool that the filing penalty of §3.7 counts, so confirming relays promptly is how a station keeps its filing penalties down."

        Design: Corner/calculations/unconfirmed_mandatory_relays_add_half_a_point_each_to_a_filing
        """
        plan, station, device = self._station_with_covered_source(("TOR",))
        create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        alerts = self._three_mandatory_alerts_one_confirmed(station["id"])
        for alert in alerts:
            assert alert["relay_class_applied"] == "MANDATORY"

        event, _closed = self._log_and_close(station["id"], device["id"])
        set_clock("2026-08-18T01:00:00Z")
        filing = validate_success(
            api_client.create_filing_record(
                {
                    "test_event_id": event["id"],
                    "expected_test_event_version": get_success_data(
                        api_client.get_test_event(event["id"], OFFICER)
                    )["version"],
                    "attestation_note": "weekly test filed one day late",
                },
                OFFICER,
            ),
            201,
        )

        assert filing["unconfirmed_relay_points"] == pytest.approx(1.00, abs=0.01), (
            "only the two alerts still RELAY_PENDING are in the pool, got "
            f"{filing['unconfirmed_relay_points']}"
        )

    def test_late_filing_rounds_every_per_line_term_before_summing(self):
        """PRD §3.7: "Lateness comes first: `late_days` is 0 when `filed_at` is at or before the event's `filing_deadline_at`, and otherwise the number of whole days obtained by dividing the elapsed time between `filing_deadline_at` and `filed_at` by 86400 seconds and rounding that quotient **up** to the next whole number — so any part of a day late counts as a full day late."
        PRD §3.7: "Each log line of the event carries a kind weight: 1.0 for a `RECEIPT` line and 1.8 for a `TRANSMISSION` line."
        PRD §3.7: "For each log line — taking every line whose `test_event_id` matches, in `created_at` ascending order, with no status filter whatsoever since log lines have no status — multiply `late_days` by a per-entry late rate of 0.065 points and by that line's kind weight, and **round that per-line product half-up to two decimal places immediately**."
        PRD §3.7: "`lateness_points` is `late_days` multiplied by 0.75 points per late day, rounded half-up to two decimals."
        PRD §3.7: "`penalty_points` is then the smaller of a per-filing cap of 25.00 points and the sum of `entry_subtotal_points`, `lateness_points` and `unconfirmed_relay_points`, rounded half-up to two decimal places."

        Design: Corner/calculations/unconfirmed_mandatory_relays_add_half_a_point_each_to_a_filing
        """
        plan, station, device = self._station_with_covered_source(("TOR",))
        create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        self._three_mandatory_alerts_one_confirmed(station["id"])

        event, _closed = self._log_and_close(station["id"], device["id"])
        assert event["filing_deadline_at"].startswith("2026-08-17T01:00:00"), (
            f"filing_deadline_at is window_end_at + 5 days, got "
            f"{event['filing_deadline_at']}"
        )
        set_clock("2026-08-18T01:00:00Z")
        filing = file_results(event["id"], note="weekly test filed one day late")

        assert filing["late_days"] == 1, (
            f"exactly one whole day past the deadline, got {filing['late_days']}"
        )
        assert filing["entry_subtotal_points"] == pytest.approx(0.19, abs=0.01), (
            "round(1 * 0.065 * 1.8, 2) + round(1 * 0.065 * 1.0, 2) == 0.12 + 0.07, "
            f"got {filing['entry_subtotal_points']}"
        )
        assert filing["lateness_points"] == pytest.approx(0.75, abs=0.01), (
            f"expected lateness_points 0.75, got {filing['lateness_points']}"
        )
        assert filing["unconfirmed_relay_points"] == pytest.approx(1.00, abs=0.01)
        assert filing["penalty_points"] == pytest.approx(1.94, abs=0.01), (
            "penalty_points is 0.19 + 0.75 + 1.00 under the 25.00 cap, got "
            f"{filing['penalty_points']}"
        )

    def test_submitted_filing_resynchronises_the_station_ledger_provisionally(self):
        """PRD §3.7: "Finally the station's ledger is resynchronised: `penalty_points_total` becomes the sum of `penalty_points` across all of that station's filing records whose `status` is `SUBMITTED` or `ACCEPTED`, rounded half-up to two decimal places."
        PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."

        Design: Corner/calculations/unconfirmed_mandatory_relays_add_half_a_point_each_to_a_filing
        """
        plan, station, device = self._station_with_covered_source(("TOR",))
        create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        self._three_mandatory_alerts_one_confirmed(station["id"])
        event, _closed = self._log_and_close(station["id"], device["id"])
        set_clock("2026-08-18T01:00:00Z")
        filing = file_results(event["id"])
        assert filing["status"] == "SUBMITTED"

        summary = station_summary(station["id"])

        assert summary["penalty_points_total"] == pytest.approx(1.94, abs=0.01), (
            "the one SUBMITTED filing is the whole ledger, got "
            f"{summary['penalty_points_total']}"
        )
        assert summary["compliance_variant_applied"] == "PROVISIONAL", (
            "no filing is ACCEPTED, so the station is not certified-eligible; got "
            f"{summary['compliance_variant_applied']}"
        )
        assert summary["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            "the PROVISIONAL variant never charges penalty_points_total, got "
            f"{summary['compliance_score']}"
        )

    def test_recent_alert_ratio_caps_the_readiness_activity_term_at_the_target(self):
        """PRD §3.6: "The **recent-activity ratio** is the number of the station's alert events, in any `relay_state`, whose `received_at` falls inside the closed interval running from 30 days before the current logical clock through the current logical clock, divided by a target of 3 recent alerts, and likewise capped at 1."
        PRD §3.6: "The score is 40 times the device ratio plus 40 times the coverage ratio plus 20 times the recent-activity ratio, rounded half-up to two decimal places once, after the weighted sum has been formed."

        Design: Corner/calculations/unconfirmed_mandatory_relays_add_half_a_point_each_to_a_filing
        """
        plan, station, device = self._station_with_covered_source(("TOR",))
        create_relay_rule(
            plan["id"],
            event_code="TOR",
            fips_codes=[],
            relay_class="OPTIONAL",
            priority=1,
            forward_delay_seconds=0,
        )
        self._three_mandatory_alerts_one_confirmed(station["id"])

        event = schedule_test_event(
            station["id"],
            "2026-08-12T00:00:00Z",
            "2026-08-12T01:00:00Z",
            test_type="WEEKLY",
        )
        set_clock("2026-08-12T00:30:00Z")
        evaluated = evaluate_readiness(event["id"], ENGINEER)

        assert evaluated["readiness_score"] == pytest.approx(100.00, abs=0.01), (
            "40 * (1/1) + 40 * min(1, 1/1) + 20 * min(1, 3/3) == 100.00 with the "
            f"three alerts of 2026-08-02 inside the window, got "
            f"{evaluated['readiness_score']}"
        )
        assert evaluated["status"] == "READY"

    def test_filing_exactly_on_the_deadline_instant_charges_zero_points(self):
        """PRD §3.7: "Lateness comes first: `late_days` is 0 when `filed_at` is at or before the event's `filing_deadline_at`, and otherwise the number of whole days obtained by dividing the elapsed time between `filing_deadline_at` and `filed_at` by 86400 seconds and rounding that quotient **up** to the next whole number — so any part of a day late counts as a full day late."
        PRD §3.7: "A successful filing is stored in `SUBMITTED` with `reversal_reason` null, increments the event's `version` by one, and advances the event to `FILED`."

        Design: Corner/calculations/on_time_filing_charges_zero_points_and_certified_variant_stays_at_full_score
        """
        _plan, station, device = self._station_with_covered_source(())
        event, _closed = self._log_and_close(station["id"], device["id"])
        version_before = get_success_data(
            api_client.get_test_event(event["id"], OFFICER)
        )["version"]

        set_clock("2026-08-17T01:00:00Z")
        filing = file_results(
            event["id"], note="filed exactly at the deadline instant"
        )

        assert filing["late_days"] == 0, (
            "the deadline comparison is at-or-before, got late_days "
            f"{filing['late_days']}"
        )
        assert filing["entry_subtotal_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["lateness_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["unconfirmed_relay_points"] == pytest.approx(0.00, abs=0.01)
        assert filing["penalty_points"] == pytest.approx(0.00, abs=0.01), (
            f"expected penalty_points 0.00, got {filing['penalty_points']}"
        )
        assert filing["filed_at"].startswith("2026-08-17T01:00:00"), (
            f"filed_at is stamped from the logical clock, got {filing['filed_at']}"
        )

        stored_event = get_success_data(api_client.get_test_event(event["id"], ADMIN))
        assert stored_event["status"] == "FILED"
        assert stored_event["version"] == version_before + 1, (
            f"the filing increments the event's version, got "
            f"{stored_event['version']} from {version_before}"
        )

    def test_certified_variant_after_accept_keeps_a_zero_penalty_station_at_full_score(self):
        """PRD §3.7: "Acceptance fires a station recompute event, and its consequence is significant: an accepted filing is what makes the station eligible for the certified scoring variant of §3.8, so a station scoring a perfect 100.00 provisionally can drop two posture bands the moment its first filing is accepted."
        PRD §3.8: "Certified eligibility holds when at least one filing record belonging to a test event of this station has `status` `ACCEPTED` with a `filed_at` inside the **closed** interval running from 365 days before the current logical clock through the current logical clock."
        PRD §3.8: "When it is certified-eligible, `compliance_variant_applied` is `CERTIFIED` and all six deductions are applied."

        Design: Corner/calculations/on_time_filing_charges_zero_points_and_certified_variant_stays_at_full_score
        """
        _plan, station, device = self._station_with_covered_source(())
        event, _closed = self._log_and_close(station["id"], device["id"])
        set_clock("2026-08-17T01:00:00Z")
        filing = file_results(event["id"])

        accepted = validate_success(
            api_client.accept_filing(filing["id"], ADMIN), 200
        )
        assert accepted["status"] == "ACCEPTED"

        summary = station_summary(station["id"])

        assert summary["compliance_variant_applied"] == "CERTIFIED", (
            "an ACCEPTED filing inside the 365-day window flips the variant, got "
            f"{summary['compliance_variant_applied']}"
        )
        assert summary["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert summary["unfiled_test_count"] == 0
        assert summary["compliance_score"] == pytest.approx(100.00, abs=0.01), (
            "the CERTIFIED variant charges 0.00 for both extra deductions here, "
            f"got {summary['compliance_score']}"
        )
        assert summary["compliance_posture"] == "COMPLIANT"


# ---------------------------------------------------------------------------
# Station compliance score inputs and clamping
# ---------------------------------------------------------------------------
class TestStationComplianceScoreInputs:
    """accessible_source_count filtering, and the floor at 0.00."""

    def test_assignment_for_an_unrequired_source_type_raises_no_coverage(self):
        """PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"

        Design: Corner/calculations/accessible_source_count_ignores_source_types_the_plan_does_not_require
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP", "SATELLITE"), ())
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])
        assign_source(
            station["id"], device["id"], source_type="PEP", source_call_sign="WXPEP"
        )

        assignment_lp1 = assign_source(
            station["id"], device["id"], source_type="LP1", source_call_sign="WXLP1"
        )
        assert assignment_lp1["status"] == "ACTIVE"

        summary = station_summary(station["id"])
        assert summary["required_source_count"] == 2, (
            "required_source_count is the number of entries in "
            f"required_source_types, got {summary['required_source_count']}"
        )
        assert summary["accessible_source_count"] == 1, (
            "LP1 is not in required_source_types, so it adds no coverage; got "
            f"{summary['accessible_source_count']}"
        )
        assert summary["missing_source_count"] == 1
        assert summary["silent_assignment_count"] == 0
        assert summary["compliance_score"] == pytest.approx(75.00, abs=0.01), (
            "100.00 - 25.00 for the missing SATELLITE source, got "
            f"{summary['compliance_score']}"
        )
        assert summary["compliance_posture"] == "WATCH"

    def test_covering_the_missing_required_source_restores_the_full_score(self):
        """PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
        PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."

        Design: Corner/calculations/accessible_source_count_ignores_source_types_the_plan_does_not_require
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP", "SATELLITE"), ())
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])
        assign_source(
            station["id"], device["id"], source_type="PEP", source_call_sign="WXPEP"
        )
        assign_source(
            station["id"], device["id"], source_type="LP1", source_call_sign="WXLP1"
        )

        assign_source(
            station["id"],
            device["id"],
            source_type="SATELLITE",
            source_call_sign="WXSAT",
        )

        summary = station_summary(station["id"])
        assert summary["accessible_source_count"] == 2, (
            "every assignment sits on the same device, so distinct source_type is "
            f"what counts; got {summary['accessible_source_count']}"
        )
        assert summary["missing_source_count"] == 0
        assert summary["compliance_score"] == pytest.approx(100.00, abs=0.01)
        assert summary["compliance_posture"] == "COMPLIANT"

    def test_each_assignment_create_increments_the_station_version(self):
        """PRD §2.7: "A successful create increments the station's `version` by one, so a client that reads the station once and then creates two assignments must re-read between them."

        Design: Corner/calculations/accessible_source_count_ignores_source_types_the_plan_does_not_require
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP", "SATELLITE"), ())
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])

        version_one = station_version(station["id"])
        assign_source(
            station["id"], device["id"], source_type="PEP", source_call_sign="WXPEP"
        )
        version_two = station_version(station["id"])
        assign_source(
            station["id"], device["id"], source_type="LP1", source_call_sign="WXLP1"
        )
        version_three = station_version(station["id"])

        assert version_two > version_one, (
            f"the first assignment create must bump the version, {version_one} -> "
            f"{version_two}"
        )
        assert version_three > version_two, (
            f"the second assignment create must bump the version, {version_two} -> "
            f"{version_three}"
        )

    def test_score_clamps_at_zero_instead_of_going_negative(self):
        """PRD §3.8: "In both cases the running total is floored at 0.00 — the score never goes negative — and then rounded half-up to two decimal places into `compliance_score`."
        PRD §3.8: "a flat 15.00 points when `plan_revalidation_required` is true, and nothing when it is false;"
        PRD §2.11: "Hop 2 is caused by that row becoming `SUPERSEDED`, not by the activate call itself: every `Station` whose `state_plan_id` points at the now-superseded plan sets `plan_revalidation_required` to true and re-runs the station scoring, which moves `compliance_posture` per the bands."

        Design: Corner/calculations/score_clamps_at_zero_instead_of_going_negative
        """
        set_clock(CLOCK_START)
        plan_one = create_active_plan(("PEP", "SATELLITE", "LP1", "LP2"), ())
        station = register_station(plan_one["id"])

        reviewed = run_log_review(station["id"])
        assert reviewed["compliance_score"] == pytest.approx(0.00, abs=0.01), (
            "four uncovered required sources cost 4 * 25.00 == 100.00, got "
            f"{reviewed['compliance_score']}"
        )
        assert reviewed["compliance_posture"] == "SUSPENDED_FILINGS"

        plan_two = create_plan(("PEP",), (), plan_version_label="2026-R2")
        validate_success(api_client.activate_state_plan(plan_two["id"], ADMIN), 200)

        superseded = get_success_data(api_client.get_state_plan(plan_one["id"], ADMIN))
        assert superseded["status"] == "SUPERSEDED", (
            f"activating a second KS plan supersedes the first, got "
            f"{superseded['status']}"
        )

        summary = station_summary(station["id"])
        assert summary["plan_revalidation_required"] is True, (
            "hop 2 of the plan-supersede cascade sets the flag on the station"
        )
        assert summary["required_source_count"] == 4, (
            "activation does not repoint the station's plan reference, got "
            f"required_source_count {summary['required_source_count']}"
        )
        assert summary["compliance_score"] == pytest.approx(0.00, abs=0.01), (
            "the unclamped arithmetic is 100.00 - 100.00 - 15.00 == -15.00, so the "
            f"floor is the only thing keeping the field non-negative; got "
            f"{summary['compliance_score']}"
        )
        assert summary["compliance_posture"] == "SUSPENDED_FILINGS"
        assert summary["unfiled_test_count"] == 0


# ---------------------------------------------------------------------------
# Pre-test readiness denominator
# ---------------------------------------------------------------------------
class TestReadinessDeviceDenominator:
    """A DECOMMISSIONED unit leaves the device ratio's denominator."""

    @staticmethod
    def _station_with_one_ready_and_one_registered_device():
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        ready_device = create_ready_device(station["id"])
        registered_device = register_device(
            station["id"], model_code="SAGE-EN", device_role="ENCODER",
            firmware_version="3.0.0",
        )
        assign_source(
            station["id"],
            ready_device["id"],
            source_type="PEP",
            source_call_sign="WXPEP",
        )
        event = schedule_test_event(
            station["id"],
            "2026-08-12T00:00:00Z",
            "2026-08-12T01:00:00Z",
            test_type="WEEKLY",
        )
        set_clock("2026-08-12T00:30:00Z")
        return station, ready_device, registered_device, event

    def test_registered_device_in_the_denominator_halves_the_device_ratio(self):
        """PRD §3.6: "The **device ratio** is the number of the station's units in `READY` divided by the number of the station's countable units, where countable means units whose `status` is `REGISTERED`, `READY` or `FAILED`; `DECOMMISSIONED` units leave the denominator entirely, and the denominator is treated as 1 whenever the countable count is 0, so a station with no equipment scores a device ratio of 0 rather than failing to compute."
        PRD §3.6: "The threshold is inclusive at exactly 80.00. A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."

        Design: Corner/calculations/decommissioned_device_leaves_the_readiness_denominator
        """
        _station, _ready, _registered, event = (
            self._station_with_one_ready_and_one_registered_device()
        )

        evaluated = validate_success(
            api_client.evaluate_readiness(event["id"], ENGINEER), 200
        )

        assert evaluated["readiness_score"] == pytest.approx(60.00, abs=0.01), (
            "40 * (1/2) + 40 * min(1, 1/1) + 20 * 0 == 60.00, got "
            f"{evaluated['readiness_score']}"
        )
        assert evaluated["status"] == "READINESS_PENDING", (
            f"60.00 is below the inclusive 80.00 threshold, got {evaluated['status']}"
        )
        assert evaluated["readiness_evaluated_at"].startswith("2026-08-12T00:30:00"), (
            "readiness_evaluated_at is the evaluation instant, got "
            f"{evaluated['readiness_evaluated_at']}"
        )

    def test_decommissioning_the_unchecked_device_lifts_readiness_to_the_threshold(self):
        """PRD §3.2: "Decommissioning has one lasting consequence for scoring: a `DECOMMISSIONED` unit leaves the readiness denominator described in §3.6 entirely, whereas units in `REGISTERED`, `READY` and `FAILED` all remain counted there."
        PRD §3.6: "The threshold is inclusive at exactly 80.00. A score of 80.00 or greater advances the event to `READY`, whether it came from `SCHEDULED` → `READY` or from `READINESS_PENDING` → `READY` on a re-run; a score below 80.00 leaves the event in `READINESS_PENDING`, reached as `SCHEDULED` → `READINESS_PENDING` on a first evaluation or as `READINESS_PENDING` → `READINESS_PENDING` on a re-run that still falls short."

        Design: Corner/calculations/decommissioned_device_leaves_the_readiness_denominator
        """
        _station, _ready, registered, event = (
            self._station_with_one_ready_and_one_registered_device()
        )
        first = evaluate_readiness(event["id"], ENGINEER)
        assert first["readiness_score"] == pytest.approx(60.00, abs=0.01)

        decommissioned = validate_success(
            api_client.decommission_device(registered["id"], ADMIN), 200
        )
        assert decommissioned["status"] == "DECOMMISSIONED", (
            "the unchecked unit carries no live assignment, so decommission "
            f"succeeds; got {decommissioned['status']}"
        )

        second = validate_success(
            api_client.evaluate_readiness(event["id"], ENGINEER), 200
        )
        assert second["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "no device became READY: only the denominator changed from 2 to 1, got "
            f"{second['readiness_score']}"
        )
        assert second["status"] == "READY", (
            f"80.00 is the inclusive pass threshold, got {second['status']}"
        )


# ---------------------------------------------------------------------------
# Log retention terms
# ---------------------------------------------------------------------------
class TestLogRetentionTerms:
    """A NATIONAL test logged at a SUSPENDED_FILINGS station stacks both terms."""

    @staticmethod
    def _suspended_station_with_a_ready_national_event():
        """Four assignments where only PEP is required: refreshing PEP alone leaves
        three rows to be flagged SILENT, costing 30.00 points and driving the
        station below the 75.00 WATCH floor while required coverage holds."""
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])
        assignments = {}
        for source_type, call_sign in (
            ("PEP", "WXPEP"),
            ("SATELLITE", "WXSAT"),
            ("LP1", "WXLP1"),
            ("LP2", "WXLP2"),
        ):
            assignments[source_type] = assign_source(
                station["id"],
                device["id"],
                source_type=source_type,
                source_call_sign=call_sign,
            )
        event = schedule_test_event(
            station["id"],
            "2026-08-25T00:00:00Z",
            "2026-08-25T01:00:00Z",
            test_type="NATIONAL",
        )

        set_clock("2026-08-24T00:00:00Z")
        get_success_data(
            api_client.record_receipt(assignments["PEP"]["id"], ENGINEER)
        )
        set_clock("2026-08-25T00:00:00Z")
        reviewed = run_log_review(station["id"])
        set_clock("2026-08-25T00:30:00Z")
        event = evaluate_readiness(event["id"], ENGINEER)
        return station, device, event, reviewed

    def test_silence_sweep_drives_the_station_into_suspended_filings(self):
        """PRD §3.8: "**Phase 1 — silence sweep.** Every monitoring assignment of the station whose `status` is `ACTIVE` and whose last evidence of life is strictly earlier than the current logical clock less eight days is pushed `ACTIVE` → `SILENT`, with `silence_flagged_at` stamped."
        PRD §3.8: "10.00 points for each assignment counted in `silent_assignment_count`;"

        Design: Corner/calculations/national_test_at_a_suspended_station_stacks_both_retention_terms
        """
        station, _device, event, reviewed = (
            self._suspended_station_with_a_ready_national_event()
        )

        assert reviewed["compliance_score"] == pytest.approx(70.00, abs=0.01), (
            "three silent assignments cost 30.00 while PEP coverage holds, got "
            f"{reviewed['compliance_score']}"
        )
        assert reviewed["compliance_posture"] == "SUSPENDED_FILINGS"

        summary = station_summary(station["id"])
        assert summary["silent_assignment_count"] == 3, (
            "the PEP row was refreshed by the receipt, got "
            f"{summary['silent_assignment_count']}"
        )
        assert summary["accessible_source_count"] == 1
        assert event["readiness_score"] == pytest.approx(80.00, abs=0.01), (
            "the suspended posture blocks scheduling, not evaluation, got "
            f"{event['readiness_score']}"
        )
        assert event["status"] == "READY"

    def test_national_test_at_a_suspended_station_stacks_both_retention_terms(self):
        """PRD §3.6: "The base term is 1095 days — three years — when the owning event's `test_type` is `NATIONAL`, and 730 days — two years — for `WEEKLY` and `MONTHLY` alike."
        PRD §3.6: "If, at that moment, the owning station's `compliance_posture` is `SUSPENDED_FILINGS`, a further 365 days is added; under any other posture nothing is added."
        PRD §3.6: "The resulting figure is stored as `retention_days_applied`, and `retention_until` is `logged_at` advanced by that many whole calendar days in UTC."

        Design: Corner/calculations/national_test_at_a_suspended_station_stacks_both_retention_terms
        """
        _station, device, event, _reviewed = (
            self._suspended_station_with_a_ready_national_event()
        )

        entry = validate_success(
            api_client.create_test_log_entry(
                {
                    "test_event_id": event["id"],
                    "device_id": device["id"],
                    "entry_kind": "RECEIPT",
                    "source_call_sign": "WXPEP",
                },
                ENGINEER,
            ),
            201,
        )

        assert entry["retention_days_applied"] == 1460, (
            "1095 for NATIONAL plus 365 for the SUSPENDED_FILINGS posture, got "
            f"{entry['retention_days_applied']}"
        )
        assert entry["logged_at"].startswith("2026-08-25T00:30:00"), (
            f"logged_at is stamped from the logical clock, got {entry['logged_at']}"
        )
        assert entry["logged_by_user_id"] == ENGINEER_USER_ID, (
            f"the acting operator is recorded, got {entry['logged_by_user_id']}"
        )
        assert entry["retention_until"].startswith("2030-08-24T00:30:00"), (
            "2026-08-25T00:30:00Z advanced by 1460 calendar days lands on "
            f"2030-08-24T00:30:00Z, got {entry['retention_until']}"
        )

    def test_close_logging_refreshes_retention_until_max(self):
        """PRD §3.6: "The event's `retention_until_max` holds the greatest `retention_until` across the event's lines, and is refreshed when the logging phase closes."
        PRD §3.6: "Closing the logging phase moves the event `READY` → `LOGGED`."

        Design: Corner/calculations/national_test_at_a_suspended_station_stacks_both_retention_terms
        """
        _station, device, event, _reviewed = (
            self._suspended_station_with_a_ready_national_event()
        )
        entry = append_log_entry(
            event["id"], device["id"], "RECEIPT", source_call_sign="WXPEP"
        )

        closed = validate_success(api_client.close_logging(event["id"], ENGINEER), 200)

        assert closed["status"] == "LOGGED"
        assert closed["logged_entry_count"] == 1
        assert closed["retention_until_max"] == entry["retention_until"], (
            "the only line's retention_until is the maximum, got "
            f"{closed['retention_until_max']} against {entry['retention_until']}"
        )


# ---------------------------------------------------------------------------
# Inspection completeness
# ---------------------------------------------------------------------------
class TestInspectionCompletenessScore:
    """A late partial response takes the flat 20.00-point deduction."""

    @staticmethod
    def _late_partial_response():
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        request = setup_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])
        get_success_data(
            api_client.draft_response(
                request["id"],
                draft_response_payload(["STATION_LOG", "PLAN_COPY"]),
                ENGINEER,
            )
        )
        set_clock("2026-08-10T00:00:00Z")
        return request

    def test_response_due_at_is_seven_days_after_the_request(self):
        """PRD §3.9: "The request opens in `OPEN` with `requested_at` stamped from the logical clock, `provided_document_kinds` an empty array, `responded_at` null and `completeness_score` null, and the server derives `response_due_at` as `requested_at` plus seven days."

        Design: Corner/calculations/inspection_late_partial_response_takes_the_flat_deduction
        """
        request = self._late_partial_response()

        assert request["requested_at"].startswith("2026-08-01T00:00:00"), (
            f"requested_at is stamped from the logical clock, got "
            f"{request['requested_at']}"
        )
        assert request["response_due_at"].startswith("2026-08-08T00:00:00"), (
            f"response_due_at is requested_at + 7 days, got "
            f"{request['response_due_at']}"
        )

    def test_late_partial_response_scores_the_raw_figure_less_twenty_points(self):
        """PRD §3.9: "Count the distinct document kinds that appear in both `provided_document_kinds` and `requested_document_kinds`; multiply that matched count by 100, divide by the number of entries in `requested_document_kinds` — treating that divisor as 1 if it is somehow 0 — and round half-up to two decimal places to obtain the raw figure."
        PRD §3.9: "If `responded_at` is later than `response_due_at`, `completeness_score` is the raw figure less a flat 20.00 points, floored at 0.00 and rounded half-up to two decimals."
        PRD §3.9: "Submission is also time-boxed: when the logical clock has passed `response_due_at` plus a further seven days, the submission is rejected outright with `ERR_INSPECTION_RESPONSE_WINDOW_CLOSED`."

        Design: Corner/calculations/inspection_late_partial_response_takes_the_flat_deduction
        """
        request = self._late_partial_response()

        responded = validate_success(
            api_client.submit_response(request["id"], OFFICER), 200
        )

        assert responded["responded_at"].startswith("2026-08-10T00:00:00"), (
            "2026-08-10 is inside the hard cutoff of 2026-08-15, got "
            f"{responded['responded_at']}"
        )
        assert responded["status"] == "RESPONDED"
        assert responded["completeness_score"] == pytest.approx(30.00, abs=0.01), (
            "PLAN_COPY was never requested, so matched is 1 of 2 giving a raw "
            f"50.00, less the flat 20.00; got {responded['completeness_score']}"
        )

    def test_deficient_close_retains_the_provided_document_kinds(self):
        """PRD §3.9: "The outcome is decided by the score alone and is inclusive at the boundary: a `completeness_score` of 100.00 or greater closes the request `RESPONDED` → `CLOSED_SATISFIED`, and anything below 100.00 closes it `RESPONDED` → `CLOSED_DEFICIENT`."
        PRD §3.9: "A `StationEngineer` drafts by supplying `provided_document_kinds`, an array whose members are drawn from the same five document kinds."

        Design: Corner/calculations/inspection_late_partial_response_takes_the_flat_deduction
        """
        request = self._late_partial_response()
        get_success_data(api_client.submit_response(request["id"], OFFICER))

        closed = validate_success(
            api_client.close_inspection(request["id"], INSPECTOR), 200
        )

        assert closed["status"] == "CLOSED_DEFICIENT", (
            f"30.00 is below 100.00, got {closed['status']}"
        )
        assert sorted(closed["provided_document_kinds"]) == [
            "PLAN_COPY",
            "STATION_LOG",
        ], (
            "the drafted inputs are retained on the closed row, got "
            f"{closed['provided_document_kinds']}"
        )


# ---------------------------------------------------------------------------
# The two downtime clocks
# ---------------------------------------------------------------------------
class TestDowntimeClocks:
    """An outage entirely outside the obligation window costs zero owed hours."""

    @staticmethod
    def _overnight_outage_restored():
        set_clock("2026-08-12T00:30:00Z")
        plan = create_active_plan(("PEP",), ())
        station = register_station(plan["id"])
        device = create_ready_device(station["id"])
        assign_source(
            station["id"], device["id"], source_type="PEP", source_call_sign="WXPEP"
        )
        outage = setup_outage(device["id"], "2026-08-12T00:30:00Z")
        set_clock("2026-08-12T01:00:00Z")
        get_success_data(api_client.start_repair(outage["id"], ENGINEER))
        set_clock("2026-08-12T06:00:00Z")
        return station, device, outage

    def test_continuous_clock_counts_every_elapsed_second(self):
        """PRD §3.4: "The *continuous* clock counts every wall-clock second that elapsed. Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Then `continuous_clock_breached` is true when `continuous_downtime_hours` is strictly greater than 60 hours — two and a half days of unbroken outage — and false when it equals 60 hours or is less."

        Design: Corner/calculations/overnight_only_outage_yields_zero_obligation_hours
        """
        _station, _device, outage = self._overnight_outage_restored()

        restored = validate_success(
            api_client.restore_outage(outage["id"], ENGINEER), 200
        )

        assert restored["status"] == "RESTORED"
        assert restored["restored_at"].startswith("2026-08-12T06:00:00"), (
            f"restored_at is stamped from the logical clock, got "
            f"{restored['restored_at']}"
        )
        assert restored["continuous_downtime_hours"] == pytest.approx(5.50, abs=0.01), (
            "00:30Z to 06:00Z is 19800 seconds, i.e. 5.50 hours, got "
            f"{restored['continuous_downtime_hours']}"
        )
        assert restored["continuous_clock_breached"] is False, (
            "5.50 is not strictly greater than 60 hours"
        )

    def test_obligation_clock_ignores_hours_outside_the_daily_window(self):
        """PRD §3.4: "The *obligation* clock counts only the hours during which the station actually owed alert reception, which this specification fixes as a daily window running from 08:00:00 UTC up to but not including 20:00:00 UTC."
        PRD §3.4: "For each such day, form that day's obligation window from 08:00:00 UTC (included) to 20:00:00 UTC (excluded), and take the overlap between that window and the outage interval: the overlap begins at the later of `detected_at` and the window start, ends at the earlier of `restored_at` and the window end, and contributes zero seconds whenever that end is not after that beginning."
        PRD §3.4: "Then `obligation_breached` is true when `obligation_downtime_hours` is strictly greater than 48 hours — the statutory repair deadline — and false at exactly 48 hours or below."
        PRD §3.4: "Because overnight hours fall entirely outside every obligation window, an outage detected at 21:00 UTC and restored at 07:00 UTC the following morning accrues ten continuous hours and zero obligation hours."

        Design: Corner/calculations/overnight_only_outage_yields_zero_obligation_hours
        """
        _station, _device, outage = self._overnight_outage_restored()

        restored = validate_success(
            api_client.restore_outage(outage["id"], ENGINEER), 200
        )

        assert restored["obligation_downtime_hours"] == pytest.approx(0.00, abs=0.01), (
            "the whole outage sat before 08:00Z on its only candidate day, got "
            f"{restored['obligation_downtime_hours']}"
        )
        assert restored["obligation_breached"] is False
        assert restored["continuous_downtime_hours"] == pytest.approx(5.50, abs=0.01), (
            "the same call wrote both figures from identical inputs, and they "
            f"differ by the full duration; got {restored['continuous_downtime_hours']}"
        )

    def test_unbreached_outage_contributes_nothing_to_the_outage_breach_count(self):
        """PRD §3.8: "The outage breach count is the number of equipment outages whose `device_id` belongs to this station, whose `obligation_breached` is true, and whose `status` is `OPEN`, `REPAIR_IN_PROGRESS`, `RESTORED` or `VERIFICATION_FAILED` — a `CLOSED` outage stops counting even if it breached."
        PRD §2.11: "Hop 3 is caused by those assignments leaving `ACTIVE`: the station's `accessible_source_count` is recomputed and the station scoring re-runs, moving `compliance_posture` per the bands in §2.10."
        PRD §3.4: "Only the obligation flag feeds station scoring; the continuous flag is reported for engineering review."

        Design: Corner/calculations/overnight_only_outage_yields_zero_obligation_hours
        """
        station, _device, outage = self._overnight_outage_restored()
        get_success_data(api_client.restore_outage(outage["id"], ENGINEER))

        summary = station_summary(station["id"])

        assert summary["outage_breach_count"] == 0, (
            "obligation_breached is false, so the outage is outside the count; got "
            f"{summary['outage_breach_count']}"
        )
        assert summary["accessible_source_count"] == 0, (
            "hop 2 suspended the only assignment, got "
            f"{summary['accessible_source_count']}"
        )
        assert summary["compliance_score"] == pytest.approx(75.00, abs=0.01), (
            "100.00 - 25.00 for the now-uncovered required source, got "
            f"{summary['compliance_score']}"
        )
        assert summary["compliance_posture"] == "WATCH"
