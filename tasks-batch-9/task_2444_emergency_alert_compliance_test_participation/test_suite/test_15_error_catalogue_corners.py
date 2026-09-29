"""Error-catalogue corners: every declared code reached on its own trigger.

These tests prove that the not-found family does not collapse onto a shared code,
that the two uniqueness conflicts have the scopes the contract gives them, that the
two future-timestamp rules are strict comparisons against the logical clock, and
that terminal rows keep refusing their own triggers.

The harness restarts the API server before every individual test, so each test
begins against an empty database with the logical clock at its startup default
2026-08-01T00:00:00Z and builds its own world from there.
"""

from datetime import datetime

from test_helpers import (
    ADMIN,
    ENGINEER,
    INSPECTOR,
    OFFICER,
    ApiErrorId,
    api_client,
    append_log_entry,
    assert_filing_record,
    assert_relay_rule,
    assert_score_and_posture,
    assert_summary_inputs,
    create_active_plan,
    evaluate_readiness,
    file_results,
    get_success_data,
    monitoring_assignment_payload,
    register_station,
    relay_rule_payload,
    schedule_test_event,
    set_clock,
    setup_station,
    station_summary,
    station_version,
    station_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared instants and probe ids
# ---------------------------------------------------------------------------
CLOCK_NOW = "2026-08-12T08:00:00Z"
ONE_SECOND_AHEAD = "2026-08-12T08:00:01Z"
WINDOW_START = "2026-08-12T00:00:00Z"
WINDOW_END = "2026-08-12T01:00:00Z"
PREFLIGHT_OPENS = "2026-08-11T00:00:00Z"
LOG_INSTANT = "2026-08-12T00:30:00Z"
FILED_AT = "2026-08-12T00:40:00Z"
REVERSAL_REASON = "attestation withdrawn by the officer"

# Well-formed UUIDs the server never minted, one per resource family.
PROBE_PLAN = "11111111-1111-4111-8111-111111111111"
PROBE_STATION = "22222222-2222-4222-8222-222222222222"
PROBE_RULE = "33333333-3333-4333-8333-333333333333"
PROBE_DEVICE = "44444444-4444-4444-8444-444444444444"
PROBE_ASSIGNMENT = "55555555-5555-4555-8555-555555555555"
PROBE_OUTAGE = "66666666-6666-4666-8666-666666666666"
PROBE_ALERT = "77777777-7777-4777-8777-777777777777"
PROBE_WEA = "88888888-8888-4888-8888-888888888888"
PROBE_TEST_EVENT = "99999999-9999-4999-8999-999999999999"
PROBE_LOG_ENTRY = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
PROBE_FILING = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
PROBE_INSPECTION = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
PROBE_BODY_STATION = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
PROBE_BODY_DEVICE = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"


def _instant(value):
    """Parse an ISO 8601 UTC instant so two spellings of one instant compare equal."""
    assert isinstance(value, str), f"expected an ISO 8601 string, got {value!r}"
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _assert_instant(actual, expected_iso, label):
    assert actual is not None, f"{label} must be set"
    assert _instant(actual) == _instant(expected_iso), (
        f"expected {label} == {expected_iso}, got {actual}"
    )


def _plan_and_station():
    """One real plan and one real station, so a not-found probe cannot be satisfied
    merely because the store is empty."""
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    return plan, station


def _two_plans_one_station_and_one_rule():
    plan_a = create_active_plan(("PEP",))
    plan_b = create_active_plan(("PEP",), state_code="NE")
    station = register_station(plan_a["id"])
    rule_a = validate_success(
        api_client.create_relay_rule(
            relay_rule_payload(
                plan_a["id"],
                event_code="TOR",
                fips_codes=["20173"],
                relay_class="MANDATORY",
                priority=1,
                forward_delay_seconds=0,
            ),
            ADMIN,
        ),
        201,
    )
    return plan_a, plan_b, station, rule_a


def _station_with_accepted_ready_filing():
    """A station whose single weekly test is filed on time, so penalty_points is 0.00
    and the filing sits in SUBMITTED."""
    ctx = setup_station()
    event = schedule_test_event(ctx["station_id"], WINDOW_START, WINDOW_END)
    set_clock(PREFLIGHT_OPENS)
    evaluate_readiness(event["id"])
    set_clock(LOG_INSTANT)
    append_log_entry(event["id"], ctx["device_id"], "RECEIPT")
    get_success_data(api_client.close_logging(event["id"], ENGINEER))
    set_clock(FILED_AT)
    ctx["filing"] = file_results(event["id"], note="weekly test filed on time")
    ctx["filing_id"] = ctx["filing"]["id"]
    ctx["test_event_id"] = event["id"]
    return ctx


def _station_with_decommissioned_assignment():
    ctx = setup_station()
    ctx["assignment_id"] = ctx["assignments"]["PEP"]["id"]
    ctx["assignment"] = get_success_data(
        api_client.decommission_assignment(ctx["assignment_id"], ENGINEER)
    )
    return ctx


class TestNotFoundFamily:
    """Twelve declared 404 codes, twelve distinct triggers."""

    def test_every_declared_not_found_code_is_reachable_on_its_own_resource(self):
        """PRD §2.9: "Each entity type has its own not-found code so that a caller can tell which reference broke: `ERR_STATE_PLAN_NOT_FOUND`, `ERR_STATION_NOT_FOUND`, `ERR_RELAY_RULE_NOT_FOUND`, `ERR_DEVICE_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_OUTAGE_NOT_FOUND`, `ERR_ALERT_EVENT_NOT_FOUND`, `ERR_WEA_NOTICE_NOT_FOUND`, `ERR_TEST_EVENT_NOT_FOUND`, `ERR_LOG_ENTRY_NOT_FOUND`, `ERR_FILING_NOT_FOUND` and `ERR_INSPECTION_NOT_FOUND`."
        PRD §2.9: "All twelve carry HTTP 404."

        Design: Corner/errors/all_twelve_declared_not_found_errors_are_triggerable_on_their_own_id
        """
        _plan_and_station()

        probes = (
            (api_client.get_state_plan(PROBE_PLAN, ADMIN),
             ApiErrorId.ERR_STATE_PLAN_NOT_FOUND),
            (api_client.get_station(PROBE_STATION, ENGINEER),
             ApiErrorId.ERR_STATION_NOT_FOUND),
            (api_client.get_relay_rule(PROBE_RULE, OFFICER),
             ApiErrorId.ERR_RELAY_RULE_NOT_FOUND),
            (api_client.get_device(PROBE_DEVICE, INSPECTOR),
             ApiErrorId.ERR_DEVICE_NOT_FOUND),
            (api_client.get_monitoring_assignment(PROBE_ASSIGNMENT, ADMIN),
             ApiErrorId.ERR_ASSIGNMENT_NOT_FOUND),
            (api_client.get_equipment_outage(PROBE_OUTAGE, ENGINEER),
             ApiErrorId.ERR_OUTAGE_NOT_FOUND),
            (api_client.get_alert_event(PROBE_ALERT, OFFICER),
             ApiErrorId.ERR_ALERT_EVENT_NOT_FOUND),
            (api_client.get_wireless_alert_notice(PROBE_WEA, INSPECTOR),
             ApiErrorId.ERR_WEA_NOTICE_NOT_FOUND),
            (api_client.get_test_event(PROBE_TEST_EVENT, ADMIN),
             ApiErrorId.ERR_TEST_EVENT_NOT_FOUND),
            (api_client.get_test_log_entry(PROBE_LOG_ENTRY, ENGINEER),
             ApiErrorId.ERR_LOG_ENTRY_NOT_FOUND),
            (api_client.get_filing_record(PROBE_FILING, OFFICER),
             ApiErrorId.ERR_FILING_NOT_FOUND),
            (api_client.get_inspection_request(PROBE_INSPECTION, INSPECTOR),
             ApiErrorId.ERR_INSPECTION_NOT_FOUND),
        )
        assert len(probes) == 12, "the catalogue declares exactly twelve 404 codes"

        for response, expected_error_id in probes:
            validate_error(response, expected_error_id)

        reported = {expected for _response, expected in probes}
        assert len(reported) == 12, (
            f"the twelve codes must be pairwise distinct, got {sorted(reported)}"
        )

    def test_leftmost_unresolvable_body_id_decides_which_not_found_is_reported(self):
        """PRD §2.9: "Concretely: a monitoring-assignment create that names both an unknown `station_id` and an unknown `device_id` reports `ERR_STATION_NOT_FOUND`, because `station_id` is listed first."
        PRD §2.9: "Identifier resolution is strictly left to right, and the first identifier that fails to resolve determines the error reported."

        Design: Corner/errors/all_twelve_declared_not_found_errors_are_triggerable_on_their_own_id
        """
        _plan, station = _plan_and_station()
        expected_version = station_version(station["id"])

        validate_error(
            api_client.create_monitoring_assignment(
                monitoring_assignment_payload(
                    PROBE_BODY_STATION, PROBE_BODY_DEVICE, expected_version,
                    source_type="PEP",
                ),
                ENGINEER,
            ),
            ApiErrorId.ERR_STATION_NOT_FOUND,
        )


class TestUniquenessConflicts:
    """Call-sign uniqueness is global; relay-priority uniqueness is scoped and only
    counts ACTIVE rules."""

    def test_duplicate_call_sign_is_refused_under_the_same_and_a_different_plan(self):
        """PRD §3.2: "The registration payload names the governing plan through `state_plan_id`, the broadcast `call_sign` (three to eight uppercase alphanumeric characters, unique across all stations — a repeat is rejected with `ERR_DUPLICATE_CALL_SIGN`), the `service_type`, which is one of `TV`, `FM`, `AM` or `CABLE`, a non-empty array of distinct opaque operator identifiers in `engineer_user_ids`, and a single opaque operator identifier in `certification_officer_user_id`."

        Design: Corner/errors/uniqueness_conflict_errors_for_call_sign_and_relay_priority_are_triggerable
        """
        plan_a, plan_b, station, _rule_a = _two_plans_one_station_and_one_rule()
        assert station["call_sign"] == "KWEA"

        validate_error(
            api_client.create_station(
                station_payload(plan_a["id"], call_sign="KWEA", service_type="FM"),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_CALL_SIGN,
        )
        validate_error(
            api_client.create_station(
                station_payload(plan_b["id"], call_sign="KWEA", service_type="TV"),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_CALL_SIGN,
        )

        _, meta = validate_paginated(
            api_client.list_stations(ADMIN, params={"call_sign": "KWEA"})
        )
        assert meta["total_count"] == 1, (
            f"only the original station may exist, got {meta['total_count']}"
        )

    def test_relay_priority_conflict_is_scoped_to_plan_event_code_and_active_status(self):
        """PRD §3.1: "Within one plan, no two rules that are both `ACTIVE` may share the same `event_code` and the same `priority`; an attempt to create such a rule is rejected with `ERR_DUPLICATE_RELAY_PRIORITY`."
        PRD §3.1: "Retirement by a `ComplianceAdmin` moves a rule `ACTIVE` → `RETIRED` and takes it out of the selector's candidate pool for every future alert; retiring a rule that is already `RETIRED` is rejected with `ERR_RELAY_RULE_NOT_ACTIVE`."
        PRD §3.1: "The server derives `specificity` from the location scope: 2 when `fips_codes` holds at least one entry, meaning the rule is county-scoped, and 1 when `fips_codes` is empty, meaning the rule is statewide."
        PRD §3.1: "Rules can be listed filtered by `state_plan_id`, `event_code`, `relay_class` and `status`."

        Design: Corner/errors/uniqueness_conflict_errors_for_call_sign_and_relay_priority_are_triggerable
        """
        plan_a, plan_b, _station, rule_a = _two_plans_one_station_and_one_rule()

        validate_error(
            api_client.create_relay_rule(
                relay_rule_payload(
                    plan_a["id"],
                    event_code="TOR",
                    fips_codes=[],
                    relay_class="OPTIONAL",
                    priority=1,
                ),
                ADMIN,
            ),
            ApiErrorId.ERR_DUPLICATE_RELAY_PRIORITY,
        )

        other_code = validate_success(
            api_client.create_relay_rule(
                relay_rule_payload(
                    plan_a["id"],
                    event_code="SVR",
                    fips_codes=[],
                    relay_class="OPTIONAL",
                    priority=1,
                ),
                ADMIN,
            ),
            201,
        )
        other_plan = validate_success(
            api_client.create_relay_rule(
                relay_rule_payload(
                    plan_b["id"],
                    event_code="TOR",
                    fips_codes=[],
                    relay_class="OPTIONAL",
                    priority=1,
                ),
                ADMIN,
            ),
            201,
        )
        assert other_code["specificity"] == 1, "an empty FIPS list is statewide"
        assert other_plan["specificity"] == 1

        retired = get_success_data(api_client.retire_relay_rule(rule_a["id"], ADMIN))
        assert retired["status"] == "RETIRED"

        reused = validate_success(
            api_client.create_relay_rule(
                relay_rule_payload(
                    plan_a["id"],
                    event_code="TOR",
                    fips_codes=["20177"],
                    relay_class="MANDATORY",
                    priority=1,
                    forward_delay_seconds=5,
                ),
                ADMIN,
            ),
            201,
        )
        assert_relay_rule(reused)
        assert reused["event_code"] == "TOR"
        assert reused["priority"] == 1
        assert reused["specificity"] == 2, "a non-empty FIPS list is county-scoped"
        assert reused["forward_delay_seconds"] == 5

        rows, meta = validate_paginated(
            api_client.list_relay_rules(ADMIN, params={"state_plan_id": plan_a["id"]})
        )
        assert meta["total_count"] == 3, (
            f"plan_a holds one RETIRED and two ACTIVE rules, got {meta['total_count']}"
        )
        assert {row["id"] for row in rows} == {
            rule_a["id"], other_code["id"], reused["id"]
        }


class TestFutureTimestampRejections:
    """Both future-timestamp rules are strictly-later comparisons against the clock."""

    def test_alert_received_one_second_ahead_is_refused_and_equal_is_accepted(self):
        """PRD §3.5: "A `received_at` later than the logical clock's current value is rejected with `ERR_ALERT_RECEIVED_IN_FUTURE`."
        PRD §3.5: "Alerts can be listed filtered by `station_id`, `matched_relay_rule_id`, `suppression_reference_alert_id`, `relay_state`, `accessibility_state`, `event_code` and `originator_sequence`."

        Design: Corner/errors/future_timestamp_errors_for_outages_and_alerts_are_triggerable_at_one_second
        """
        set_clock(CLOCK_NOW)
        ctx = setup_station()

        validate_error(
            api_client.create_alert_event(
                {
                    "station_id": ctx["station_id"],
                    "event_code": "TOR",
                    "originator_sequence": "KSAXS-8101",
                    "fips_codes": ["20173"],
                    "received_at": ONE_SECOND_AHEAD,
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_ALERT_RECEIVED_IN_FUTURE,
        )

        accepted = validate_success(
            api_client.create_alert_event(
                {
                    "station_id": ctx["station_id"],
                    "event_code": "TOR",
                    "originator_sequence": "KSAXS-8102",
                    "fips_codes": ["20173"],
                    "received_at": CLOCK_NOW,
                },
                ENGINEER,
            ),
            201,
        )
        _assert_instant(accepted["received_at"], CLOCK_NOW, "received_at")

        rows, meta = validate_paginated(
            api_client.list_alert_events(
                ADMIN, params={"station_id": ctx["station_id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the refused alert left no row, got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [accepted["id"]]

    def test_outage_detected_one_second_ahead_is_refused_and_fires_no_cascade(self):
        """PRD §3.4: "The reported `detected_at` may not be later than the logical clock's current value — a future-dated detection is rejected with `ERR_OUTAGE_DETECTED_IN_FUTURE` — and the referenced unit must not be `DECOMMISSIONED`, which is rejected with `ERR_DEVICE_DECOMMISSIONED`."
        PRD §2.11: "Hop 1 is the direct effect of the create: the referenced `EASDevice` transitions to `FAILED` from either `REGISTERED` or `READY`."
        PRD §2.11: "Hop 2 is caused by the device becoming `FAILED`: every `MonitoringAssignment` referencing that device whose status is `ACTIVE` or `SILENT` transitions to `SUSPENDED`."

        Design: Corner/errors/future_timestamp_errors_for_outages_and_alerts_are_triggerable_at_one_second
        """
        set_clock(CLOCK_NOW)
        ctx = setup_station()
        assignment_id = ctx["assignments"]["PEP"]["id"]

        validate_error(
            api_client.create_equipment_outage(
                {
                    "device_id": ctx["device_id"],
                    "detected_at": ONE_SECOND_AHEAD,
                    "failure_summary": "clock-ahead probe",
                },
                ENGINEER,
            ),
            ApiErrorId.ERR_OUTAGE_DETECTED_IN_FUTURE,
        )
        device = get_success_data(api_client.get_device(ctx["device_id"], ENGINEER))
        assert device["status"] == "READY", (
            f"the rejected create fired no cascade, got {device['status']}"
        )

        outage = validate_success(
            api_client.create_equipment_outage(
                {
                    "device_id": ctx["device_id"],
                    "detected_at": CLOCK_NOW,
                    "failure_summary": "encoder output silent",
                },
                ENGINEER,
            ),
            201,
        )
        assert outage["status"] == "OPEN"
        _assert_instant(outage["detected_at"], CLOCK_NOW, "detected_at")

        rows, meta = validate_paginated(
            api_client.list_equipment_outages(
                ADMIN, params={"device_id": ctx["device_id"]}
            )
        )
        assert meta["total_count"] == 1, (
            f"the future-dated create left no row, got {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [outage["id"]]

        assert get_success_data(
            api_client.get_device(ctx["device_id"], ENGINEER)
        )["status"] == "FAILED"
        assert get_success_data(
            api_client.get_monitoring_assignment(assignment_id, ENGINEER)
        )["status"] == "SUSPENDED"
        assert_score_and_posture(station_summary(ctx["station_id"]), 75.00, "WATCH")


class TestFilingTerminalConflicts:
    """ACCEPTED is a one-way door for accept only; REVERSED is terminal for both."""

    def test_a_second_accept_on_an_accepted_filing_is_refused(self):
        """PRD §3.7: "Acceptance moves a filing `SUBMITTED` → `ACCEPTED` and is permitted only from `SUBMITTED`; from any other status it is rejected with `ERR_FILING_NOT_SUBMITTED`."

        Design: Corner/errors/filing_accept_and_reverse_conflict_errors_are_triggerable_once_terminal
        """
        ctx = _station_with_accepted_ready_filing()
        assert_filing_record(ctx["filing"])
        assert ctx["filing"]["status"] == "SUBMITTED"
        assert ctx["filing"]["penalty_points"] == 0.00, (
            f"an on-time filing owes nothing, got {ctx['filing']['penalty_points']}"
        )

        accepted = validate_success(api_client.accept_filing(ctx["filing_id"], ADMIN))
        assert accepted["status"] == "ACCEPTED"

        validate_error(
            api_client.accept_filing(ctx["filing_id"], ADMIN),
            ApiErrorId.ERR_FILING_NOT_SUBMITTED,
        )

    def test_reverse_succeeds_from_accepted_and_then_becomes_not_reversible(self):
        """PRD §3.7: "Reversal by a `ComplianceAdmin` carries an explicit `reversal_reason` in the payload and is permitted from two starting statuses with identical effect — `SUBMITTED` → `REVERSED` and `ACCEPTED` → `REVERSED`; a filing already in `REVERSED` is rejected with `ERR_FILING_NOT_REVERSIBLE`, and `REVERSED` is terminal."
        PRD §3.7: "Acceptance moves a filing `SUBMITTED` → `ACCEPTED` and is permitted only from `SUBMITTED`; from any other status it is rejected with `ERR_FILING_NOT_SUBMITTED`."
        PRD §3.7: "Reversal writes the supplied `reversal_reason`, removes the row from the `penalty_points_total` input set so that the station's total returns to its exact pre-filing value, and fires a station recompute event."
        PRD §2.5: "Most resources — state plans, stations, relay rules, EAS devices, monitoring assignments, equipment outages, alert events, test events, filing records and inspection requests — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by one on every mutation of that row."

        Design: Corner/errors/filing_accept_and_reverse_conflict_errors_are_triggerable_once_terminal
        """
        ctx = _station_with_accepted_ready_filing()
        get_success_data(api_client.accept_filing(ctx["filing_id"], ADMIN))

        reversed_filing = validate_success(
            api_client.reverse_filing(
                ctx["filing_id"], {"reversal_reason": REVERSAL_REASON}, ADMIN
            )
        )
        assert reversed_filing["status"] == "REVERSED"
        assert reversed_filing["reversal_reason"] == REVERSAL_REASON

        validate_error(
            api_client.reverse_filing(
                ctx["filing_id"],
                {"reversal_reason": "duplicate withdrawal attempt"},
                ADMIN,
            ),
            ApiErrorId.ERR_FILING_NOT_REVERSIBLE,
        )
        validate_error(
            api_client.accept_filing(ctx["filing_id"], ADMIN),
            ApiErrorId.ERR_FILING_NOT_SUBMITTED,
        )

        final = get_success_data(api_client.get_filing_record(ctx["filing_id"], OFFICER))
        assert final["status"] == "REVERSED"
        assert final["reversal_reason"] == REVERSAL_REASON, (
            "neither refused call overwrote the stored reason"
        )
        assert final["version"] == 3, (
            f"create plus two successful writes make version 3, got {final['version']}"
        )
        assert station_summary(ctx["station_id"])["penalty_points_total"] == 0.00


class TestDeadAssignmentConflicts:
    """A DECOMMISSIONED assignment refuses both of its write actions with one code."""

    def test_record_receipt_and_decommission_share_one_conflict_code(self):
        """PRD §3.3: "Recording a receipt against a row already in `DECOMMISSIONED` is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."
        PRD §3.3: "Deliberate retirement of an assignment by a `StationEngineer` is permitted from three starting statuses with identical effect — `ACTIVE` → `DECOMMISSIONED`, `SILENT` → `DECOMMISSIONED` and `SUSPENDED` → `DECOMMISSIONED` — each recomputing the station's `accessible_source_count` and firing a station recompute event; attempting it on a row already in `DECOMMISSIONED` is rejected with `ERR_ASSIGNMENT_NOT_ACTIVE`."

        Design: Corner/errors/record_receipt_and_decommission_on_a_dead_assignment_are_rejected
        """
        ctx = _station_with_decommissioned_assignment()
        assert ctx["assignment"]["status"] == "DECOMMISSIONED"

        validate_error(
            api_client.record_receipt(ctx["assignment_id"], ENGINEER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE,
        )
        validate_error(
            api_client.decommission_assignment(ctx["assignment_id"], ENGINEER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE,
        )

    def test_the_refused_writes_leave_the_derived_counters_where_they_were(self):
        """PRD §3.3: "Recording a receipt is the routine act that proves a source is still being heard."
        PRD §3.3: "It stamps `last_receipt_at` from the logical clock."
        PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
        PRD §3.8: "`silent_assignment_count` is the plain number of the station's assignments whose `status` is `SILENT`."
        PRD §3.8: "The ten other recompute events listed in §2.10 execute **phases 3 and 4 only** — they never sweep for silence and never mark events unfiled — and they never write `last_log_review_at`."

        Design: Corner/errors/record_receipt_and_decommission_on_a_dead_assignment_are_rejected
        """
        ctx = _station_with_decommissioned_assignment()
        validate_error(
            api_client.record_receipt(ctx["assignment_id"], ENGINEER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE,
        )
        validate_error(
            api_client.decommission_assignment(ctx["assignment_id"], ENGINEER),
            ApiErrorId.ERR_ASSIGNMENT_NOT_ACTIVE,
        )

        assignment = get_success_data(
            api_client.get_monitoring_assignment(ctx["assignment_id"], INSPECTOR)
        )
        assert assignment["status"] == "DECOMMISSIONED"
        assert assignment["last_receipt_at"] is None, (
            "the refused record-receipt stamped nothing, got "
            f"{assignment['last_receipt_at']}"
        )

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            accessible_source_count=0,
            missing_source_count=1,
            silent_assignment_count=0,
        )
        assert_score_and_posture(summary, 75.00, "WATCH")
        assert summary["last_log_review_at"] is None, (
            "no station log review ran, so last_log_review_at stays null"
        )
