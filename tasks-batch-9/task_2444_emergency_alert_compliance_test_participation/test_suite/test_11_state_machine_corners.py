"""State-machine corners: pinned initial states, self-loops, terminal-state
lockdown and the cross-aggregate transitions that ride on a state change.

Every test builds its own world from scratch — the harness restarts the API
server before each individual test, so the database is empty and the logical
clock sits at its startup default 2026-08-01T00:00:00Z.
"""

import pytest

from test_helpers import (
    ADMIN,
    ENGINEER,
    INSPECTOR,
    OFFICER,
    SOURCE_CALL_SIGNS,
    TEST_DEFAULTS,
    api_client,
    append_log_entry,
    assert_alert_event,
    assert_equipment_outage,
    assert_monitoring_assignment,
    assert_score_and_posture,
    assert_summary_inputs,
    assert_unmatched,
    assign_source,
    create_active_plan,
    create_plan,
    create_ready_device,
    draft_response_payload,
    evaluate_readiness,
    factories,
    get_success_data,
    log_alert,
    readiness_check_payload,
    register_device,
    register_station,
    run_log_review,
    schedule_test_event,
    set_clock,
    setup_inspection,
    setup_logged_test_event,
    setup_outage,
    setup_ready_test_event,
    setup_station,
    station_summary,
    validate_error,
    validate_paginated,
    validate_success,
)

# ---------------------------------------------------------------------------
# Shared instants
# ---------------------------------------------------------------------------
CLOCK_START = "2026-08-01T00:00:00Z"

PLAN_ACTIVATED_AT = "2026-08-09T15:45:00Z"
FIRST_ACTIVATION_AT = "2026-08-05T09:00:00Z"
SECOND_ATTEMPT_AT = "2026-08-06T09:00:00Z"
SUCCESSOR_ACTIVATION_AT = "2026-08-20T10:00:00Z"

FAILED_CHECK_AT = "2026-08-01T00:00:00Z"
FIRST_PASSING_CHECK_AT = "2026-08-02T06:00:00Z"
SECOND_PASSING_CHECK_AT = "2026-08-03T06:00:00Z"

OUTAGE_DETECTED_AT = "2026-08-12T08:00:00Z"
REPAIR_STARTED_AT = "2026-08-12T09:00:00Z"
OUTAGE_RESTORED_AT = "2026-08-12T14:00:00Z"
OUTAGE_CLOSED_AT = "2026-08-12T14:30:00Z"

RECEIPT_AT = "2026-08-09T00:00:00Z"
LOG_REVIEW_AT = "2026-08-10T00:00:00Z"
WINDOW_START_AT = "2026-08-12T00:00:00Z"
WINDOW_END_AT = "2026-08-12T01:00:00Z"
LOGGING_INSTANT = "2026-08-12T00:30:00Z"

UNFILED_SWEEP_AT = "2026-08-18T00:00:00Z"

INSPECTION_RESPONSE_AT = "2026-08-03T00:00:00Z"


# ---------------------------------------------------------------------------
# Local composite setups — built only out of the shared helper primitives.
# ---------------------------------------------------------------------------
def _plan_and_station(required_source_types=("PEP",), **plan_overrides):
    """An ACTIVE plan plus a freshly registered station under it."""
    plan = create_active_plan(required_source_types, **plan_overrides)
    station = register_station(plan["id"])
    return plan, station


def _station_with_open_outage():
    """A fully covered station whose only device has just failed."""
    set_clock(OUTAGE_DETECTED_AT)
    ctx = setup_station()
    ctx["outage"] = setup_outage(ctx["device_id"], OUTAGE_DETECTED_AT)
    return ctx


def _station_with_restored_outage():
    """The same station with its outage driven OPEN -> REPAIR_IN_PROGRESS ->
    RESTORED, with the clock parked at 2026-08-12T14:30:00Z afterwards."""
    ctx = _station_with_open_outage()
    set_clock(REPAIR_STARTED_AT)
    get_success_data(api_client.start_repair(ctx["outage"]["id"], ENGINEER))
    set_clock(OUTAGE_RESTORED_AT)
    ctx["outage"] = get_success_data(
        api_client.restore_outage(ctx["outage"]["id"], ENGINEER)
    )
    set_clock(OUTAGE_CLOSED_AT)
    return ctx


def _station_with_silent_satellite_and_ready_event():
    """A station covering required PEP plus an unrequired SATELLITE source, the
    SATELLITE row swept to SILENT by a log review, and a READY test event."""
    plan = create_active_plan(("PEP",))
    station = register_station(plan["id"])
    device = create_ready_device(station["id"])
    ma_pep = assign_source(
        station["id"], device["id"], "PEP", SOURCE_CALL_SIGNS["PEP"]
    )
    ma_sat = assign_source(
        station["id"], device["id"], "SATELLITE", SOURCE_CALL_SIGNS["SATELLITE"]
    )
    set_clock(RECEIPT_AT)
    get_success_data(api_client.record_receipt(ma_pep["id"], ENGINEER))
    set_clock(LOG_REVIEW_AT)
    run_log_review(station["id"])
    event = schedule_test_event(station["id"], WINDOW_START_AT, WINDOW_END_AT)
    set_clock(LOGGING_INSTANT)
    event = evaluate_readiness(event["id"])
    return {
        "station_id": station["id"],
        "device_id": device["id"],
        "ma_pep_id": ma_pep["id"],
        "ma_sat_id": ma_sat["id"],
        "test_event_id": event["id"],
    }


def _responded_inspection():
    """An inspection request drafted twice and then submitted on time."""
    _, station = _plan_and_station()
    request = setup_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])
    set_clock(INSPECTION_RESPONSE_AT)
    get_success_data(
        api_client.draft_response(
            request["id"], draft_response_payload(["STATION_LOG"]), ENGINEER
        )
    )
    get_success_data(
        api_client.draft_response(
            request["id"],
            draft_response_payload(["STATION_LOG", "TEST_LOGS"]),
            ENGINEER,
        )
    )
    return station, get_success_data(api_client.submit_response(request["id"], OFFICER))


def _unmatched_alert():
    """A station whose plan carries no relay rules at all, plus one alert that
    therefore falls through the selector."""
    _, station = _plan_and_station()
    alert = log_alert(
        station["id"], CLOCK_START, originator_sequence="KSAXS-0001"
    )
    return station, alert


# ===========================================================================
# Initial states pinned on create
# ===========================================================================
class TestInitialStatesOnCreate:
    """Every create response already carries its declared initial state."""

    def test_state_plan_create_lands_in_draft_with_both_lifecycle_instants_null(self):
        """PRD §3.1: "At create time the server derives `required_source_count` as the number of entries in `required_source_types`, sets `status` to `DRAFT`, and leaves both `activated_at` and `superseded_at` null."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        plan = create_plan(("PEP",))

        assert plan["status"] == "DRAFT", (
            f"a drafted plan starts in DRAFT, got {plan['status']}"
        )
        assert plan["activated_at"] is None, (
            f"activated_at is null until activation, got {plan['activated_at']}"
        )
        assert plan["superseded_at"] is None, (
            f"superseded_at is null on create, got {plan['superseded_at']}"
        )
        assert plan["required_source_count"] == 1, (
            f"required_source_count counts required_source_types, got "
            f"{plan['required_source_count']}"
        )

    def test_station_registration_lands_in_provisioning_with_null_score(self):
        """PRD §3.2: "A freshly registered station has `compliance_posture` `PROVISIONING`, `compliance_score` and `compliance_variant_applied` both null, `accessible_source_count` 0, `silent_assignment_count` 0, `penalty_points_total` 0, `plan_revalidation_required` false, `public_file_document_count` 0, `last_log_review_at` null and `version` 1."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        plan = create_active_plan(("PEP",))
        station = register_station(plan["id"])

        assert station["compliance_posture"] == "PROVISIONING", (
            f"a new station starts in PROVISIONING, got {station['compliance_posture']}"
        )
        assert station["compliance_score"] is None, (
            f"compliance_score is null before the first recompute, got "
            f"{station['compliance_score']}"
        )
        assert station["compliance_variant_applied"] is None, (
            "compliance_variant_applied is null before the first recompute, got "
            f"{station['compliance_variant_applied']}"
        )
        assert station["accessible_source_count"] == 0
        assert station["silent_assignment_count"] == 0
        assert station["penalty_points_total"] == pytest.approx(0.00, abs=0.01)
        assert station["plan_revalidation_required"] is False
        assert station["public_file_document_count"] == 0
        assert station["last_log_review_at"] is None
        assert station["version"] == 1, (
            f"version starts at 1, got {station['version']}"
        )

    def test_device_registration_lands_in_registered_with_the_readiness_flag_false(self):
        """PRD §3.2: "A newly registered unit sits in `REGISTERED` with `readiness_check_passed` false and `last_readiness_check_at` null."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station()
        device = register_device(station["id"])

        assert device["status"] == "REGISTERED", (
            f"a new unit sits in REGISTERED, got {device['status']}"
        )
        assert device["readiness_check_passed"] is False, (
            "readiness_check_passed starts false"
        )
        assert device["last_readiness_check_at"] is None, (
            f"last_readiness_check_at starts null, got {device['last_readiness_check_at']}"
        )

    def test_monitoring_assignment_create_lands_in_active_and_counts_coverage(self):
        """PRD §3.3: "A successful create lands in `ACTIVE` with `last_receipt_at` and `silence_flagged_at` null, and sets `counts_toward_required_sources` to true exactly when the row's `status` is `ACTIVE` and its `source_type` appears in the governing plan's `required_source_types` — a row covering a source the plan does not require is stored and reported but never contributes coverage."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station(("PEP",))
        device = create_ready_device(station["id"])
        assignment = assign_source(
            station["id"], device["id"], "PEP", SOURCE_CALL_SIGNS["PEP"]
        )

        assert_monitoring_assignment(assignment)
        assert assignment["status"] == "ACTIVE", (
            f"a new assignment lands in ACTIVE, got {assignment['status']}"
        )
        assert assignment["last_receipt_at"] is None, (
            f"last_receipt_at starts null, got {assignment['last_receipt_at']}"
        )
        assert assignment["silence_flagged_at"] is None, (
            f"silence_flagged_at starts null, got {assignment['silence_flagged_at']}"
        )
        assert assignment["counts_toward_required_sources"] is True, (
            "an ACTIVE row covering a required source type counts toward coverage"
        )

    def test_equipment_outage_create_lands_in_open_with_zero_repair_cycles(self):
        """PRD §3.4: "The create stamps `notified_at` from the logical clock — note that `notified_at` records when the notification reached the system, while `detected_at` records when the engineer saw the failure, and the two are ordinarily different instants — and opens the row in `OPEN` with `repair_cycle_count` 0, `repair_started_at` and `restored_at` null, `continuous_downtime_hours` and `obligation_downtime_hours` null, and `continuous_clock_breached` and `obligation_breached` both false."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        ctx = setup_station()
        outage = setup_outage(ctx["device_id"], CLOCK_START)

        assert_equipment_outage(outage)
        assert outage["status"] == "OPEN", (
            f"a filed outage opens in OPEN, got {outage['status']}"
        )
        assert outage["repair_cycle_count"] == 0
        assert outage["repair_started_at"] is None
        assert outage["restored_at"] is None
        assert outage["continuous_downtime_hours"] is None
        assert outage["obligation_downtime_hours"] is None
        assert outage["continuous_clock_breached"] is False
        assert outage["obligation_breached"] is False

    def test_alert_event_create_never_surfaces_the_received_relay_state(self):
        """PRD §3.5: "The forwarding dimension is `relay_state`, which begins at `RECEIVED` and settles into `RELAY_PENDING`, `UNMATCHED_OPTIONAL` or `SUPPRESSED_DUPLICATE` before the create returns — because the whole decision runs inside that one request, `RECEIVED` is never observable in a response body."
        PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."
        PRD §3.5: "The accessibility dimension is `accessibility_state`, which begins at `ACCESSIBILITY_UNVERIFIED` and ends at either `ACCESSIBILITY_PASSED` or `ACCESSIBILITY_FAILED`."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        _, alert = _unmatched_alert()

        assert_alert_event(alert)
        assert alert["relay_state"] != "RECEIVED", (
            "RECEIVED is resolved inside the create and is never observable"
        )
        assert_unmatched(alert)
        assert alert["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED", (
            f"the accessibility axis begins unverified, got {alert['accessibility_state']}"
        )

    def test_inspection_request_create_lands_in_open_with_no_provided_kinds(self):
        """PRD §3.9: "The request opens in `OPEN` with `requested_at` stamped from the logical clock, `provided_document_kinds` an empty array, `responded_at` null and `completeness_score` null, and the server derives `response_due_at` as `requested_at` plus seven days."

        Design: Corner/state_machines/initial_states_pinned_on_create_across_every_entity
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station()
        request = setup_inspection(station["id"], ["STATION_LOG"])

        assert request["status"] == "OPEN", (
            f"an inspection opens in OPEN, got {request['status']}"
        )
        assert request["provided_document_kinds"] == [], (
            f"provided_document_kinds starts empty, got {request['provided_document_kinds']}"
        )
        assert request["responded_at"] is None
        assert request["completeness_score"] is None


# ===========================================================================
# State plan activation, its idempotency and the terminal SUPERSEDED status
# ===========================================================================
class TestStatePlanActivationStates:
    """DRAFT -> ACTIVE -> SUPERSEDED, and what each edge refuses."""

    def test_activate_stamps_activated_at_from_the_logical_clock(self):
        """PRD §3.1: "Activation stamps `activated_at` from the logical clock and then fires the plan-supersede cascade described in §2.11: any other plan for the same `state_code` sitting in `ACTIVE` is pushed `ACTIVE` → `SUPERSEDED`, its `superseded_at` is stamped, its stations get `plan_revalidation_required` set to true and rescored, and any `RESPONDED` inspection request of those stations falls back to `RESPONSE_DRAFTED`."
        PRD §3.1: "Plans can be listed with `state_code` and `status` filters."

        Design: Corner/state_machines/plan_activate_valid_transition_writes_activated_at_from_the_clock
        """
        set_clock(CLOCK_START)
        plan = create_plan(("PEP", "NWS"), ("EAN",))
        set_clock(PLAN_ACTIVATED_AT)

        activated = validate_success(
            api_client.activate_state_plan(plan["id"], ADMIN), 200
        )

        assert activated["status"] == "ACTIVE", (
            f"DRAFT -> ACTIVE, got {activated['status']}"
        )
        assert activated["activated_at"].startswith("2026-08-09T15:45:00"), (
            "activated_at is taken from the clock at the activate, got "
            f"{activated['activated_at']}"
        )
        assert activated["superseded_at"] is None, (
            f"superseded_at stays null, got {activated['superseded_at']}"
        )
        assert activated["required_source_count"] == 2, (
            f"required_source_count is still 2, got {activated['required_source_count']}"
        )

        rows, meta = validate_paginated(
            api_client.list_state_plans(
                ADMIN, params={"state_code": "KS", "status": "ACTIVE"}
            )
        )
        assert meta["total_count"] == 1, (
            f"exactly one ACTIVE KS plan exists, got total_count {meta['total_count']}"
        )
        assert [row["id"] for row in rows] == [plan["id"]], (
            "the ACTIVE KS filter returns the plan just activated"
        )

    def test_second_activate_is_rejected_and_does_not_restamp_activated_at(self):
        """PRD §3.1: "Activation by a `ComplianceAdmin` moves it `DRAFT` → `ACTIVE`, which is legal only while its `status` is `DRAFT` — activating a plan that is already `ACTIVE` or already `SUPERSEDED` is rejected with `ERR_PLAN_NOT_DRAFT` — and only while `required_source_types` still holds at least one entry."
        PRD §2.5: "Most resources — state plans, stations, relay rules, EAS devices, monitoring assignments, equipment outages, alert events, test events, filing records and inspection requests — additionally carry `updated_at`, an ISO 8601 UTC timestamp refreshed on every mutation of the row, and `version`, an integer that starts at 1 when the row is created and increases by one on every mutation of that row."

        Design: Corner/state_machines/plan_activate_twice_cannot_repeat_the_draft_transition
        """
        set_clock(FIRST_ACTIVATION_AT)
        plan = create_plan(("PEP",))
        first = get_success_data(api_client.activate_state_plan(plan["id"], ADMIN))
        assert first["version"] == 2, (
            f"the activation is one mutation of a version-1 row, got {first['version']}"
        )
        set_clock(SECOND_ATTEMPT_AT)

        validate_error(
            api_client.activate_state_plan(plan["id"], ADMIN),
            "ERR_PLAN_NOT_DRAFT",
            409,
        )

        stored = get_success_data(api_client.get_state_plan(plan["id"], ADMIN))
        assert stored["activated_at"].startswith("2026-08-05T09:00:00"), (
            "the rejected replay must not move activated_at, got "
            f"{stored['activated_at']}"
        )
        assert stored["version"] == 2, (
            f"the rejected call mutated nothing, got version {stored['version']}"
        )

    def test_superseded_plan_cannot_be_reactivated(self):
        """PRD §2.11: "Hop 1 is caused by the activation: every *other* `StatePlan` with the same `state_code` whose status is `ACTIVE` transitions `ACTIVE` → `SUPERSEDED` and has its `superseded_at` stamped from the logical clock."
        PRD §3.1: "`SUPERSEDED` is terminal: a superseded plan never returns to any other status."
        PRD §3.1: "Activation by a `ComplianceAdmin` moves it `DRAFT` → `ACTIVE`, which is legal only while its `status` is `DRAFT` — activating a plan that is already `ACTIVE` or already `SUPERSEDED` is rejected with `ERR_PLAN_NOT_DRAFT` — and only while `required_source_types` still holds at least one entry."

        Design: Corner/state_machines/superseded_plan_is_terminal_and_cannot_be_reactivated
        """
        set_clock(FIRST_ACTIVATION_AT)
        plan_v1 = create_active_plan(("PEP",))
        set_clock(SUCCESSOR_ACTIVATION_AT)
        plan_v2 = create_plan(
            ("PEP",),
            state_code=TEST_DEFAULTS["STATE_CODE"],
            plan_version_label=TEST_DEFAULTS["SUCCESSOR_PLAN_LABEL"],
        )

        activated = get_success_data(
            api_client.activate_state_plan(plan_v2["id"], ADMIN)
        )
        assert activated["status"] == "ACTIVE"
        assert activated["activated_at"].startswith("2026-08-20T10:00:00"), (
            f"the successor is activated at the current clock, got {activated['activated_at']}"
        )

        superseded = get_success_data(api_client.get_state_plan(plan_v1["id"], ADMIN))
        assert superseded["status"] == "SUPERSEDED", (
            f"hop 1 pushes the prior ACTIVE KS plan to SUPERSEDED, got {superseded['status']}"
        )
        assert superseded["superseded_at"].startswith("2026-08-20T10:00:00"), (
            f"superseded_at is stamped at the activation, got {superseded['superseded_at']}"
        )
        assert superseded["activated_at"].startswith("2026-08-05T09:00:00"), (
            f"the original activated_at is preserved, got {superseded['activated_at']}"
        )

        validate_error(
            api_client.activate_state_plan(plan_v1["id"], ADMIN),
            "ERR_PLAN_NOT_DRAFT",
            409,
        )
        assert (
            get_success_data(api_client.get_state_plan(plan_v1["id"], ADMIN))["status"]
            == "SUPERSEDED"
        ), "SUPERSEDED is terminal, so the row cannot return to ACTIVE"

    def test_supersede_cascade_is_scoped_to_the_same_state_code(self):
        """PRD §2.11: "Hop 1 is caused by the activation: every *other* `StatePlan` with the same `state_code` whose status is `ACTIVE` transitions `ACTIVE` → `SUPERSEDED` and has its `superseded_at` stamped from the logical clock."

        Design: Corner/state_machines/superseded_plan_is_terminal_and_cannot_be_reactivated
        """
        set_clock(FIRST_ACTIVATION_AT)
        create_active_plan(("PEP",))
        plan_ne = create_active_plan(("PEP",), state_code="NE")
        set_clock(SUCCESSOR_ACTIVATION_AT)
        plan_v2 = create_plan(
            ("PEP",),
            state_code=TEST_DEFAULTS["STATE_CODE"],
            plan_version_label=TEST_DEFAULTS["SUCCESSOR_PLAN_LABEL"],
        )
        get_success_data(api_client.activate_state_plan(plan_v2["id"], ADMIN))

        untouched = get_success_data(api_client.get_state_plan(plan_ne["id"], ADMIN))
        assert untouched["status"] == "ACTIVE", (
            f"a plan for another state_code is untouched by hop 1, got {untouched['status']}"
        )
        assert untouched["superseded_at"] is None, (
            f"its superseded_at stays null, got {untouched['superseded_at']}"
        )


# ===========================================================================
# Relay rule retirement
# ===========================================================================
class TestRelayRuleRetirement:
    """ACTIVE -> RETIRED once, and what leaving the candidate pool means."""

    def test_second_retire_is_rejected_and_the_rule_stays_out_of_the_pool(self):
        """PRD §3.1: "Retirement by a `ComplianceAdmin` moves a rule `ACTIVE` → `RETIRED` and takes it out of the selector's candidate pool for every future alert; retiring a rule that is already `RETIRED` is rejected with `ERR_RELAY_RULE_NOT_ACTIVE`."
        PRD §3.5: "When the candidate pool is empty the alert moves `RECEIVED` → `UNMATCHED_OPTIONAL`, `matched_relay_rule_id` stays null, `relay_class_applied` stays `NONE` and `forward_delay_seconds_applied` stays 0."

        Design: Corner/state_machines/retire_relay_rule_twice_cannot_repeat
        """
        set_clock(CLOCK_START)
        plan, station = _plan_and_station(("PEP",))
        rule = get_success_data(
            api_client.create_relay_rule(
                factories.relay_rule_payload(
                    plan["id"],
                    event_code="RWT",
                    fips_codes=[],
                    relay_class="OPTIONAL",
                    priority=40,
                    forward_delay_seconds=15,
                ),
                ADMIN,
            )
        )

        retired = validate_success(api_client.retire_relay_rule(rule["id"], ADMIN), 200)
        assert retired["status"] == "RETIRED", (
            f"the first retire moves ACTIVE -> RETIRED, got {retired['status']}"
        )

        validate_error(
            api_client.retire_relay_rule(rule["id"], ADMIN),
            "ERR_RELAY_RULE_NOT_ACTIVE",
            409,
        )

        alert = log_alert(
            station["id"],
            CLOCK_START,
            event_code="RWT",
            originator_sequence="KSRET-0001",
        )
        assert_unmatched(alert)


# ===========================================================================
# Device readiness self-loops and the terminal DECOMMISSIONED status
# ===========================================================================
class TestDeviceReadinessStates:
    """Two self-loops with distinct side-effect sets, plus a terminal device."""

    def test_failing_readiness_check_keeps_the_unit_registered_and_records_it(self):
        """PRD §3.2: "On a unit in `REGISTERED` where either `self_test_passed` or `firmware_current` is false, the unit stays in `REGISTERED` — `REGISTERED` → `REGISTERED` — with `readiness_check_passed` set to false and `last_readiness_check_at` still stamped; the failed attempt is recorded, not discarded."

        Design: Corner/state_machines/device_readiness_recheck_from_ready_stays_ready_and_refreshes_timestamp
        """
        set_clock(FAILED_CHECK_AT)
        _, station = _plan_and_station()
        device = register_device(
            station["id"], device_role="MONITOR", firmware_version="5.2.0"
        )

        checked = validate_success(
            api_client.readiness_check_device(
                device["id"],
                readiness_check_payload(self_test_passed=False),
                ENGINEER,
            ),
            200,
        )

        assert checked["status"] == "REGISTERED", (
            f"a failed check is the REGISTERED self-loop, got {checked['status']}"
        )
        assert checked["readiness_check_passed"] is False, (
            "readiness_check_passed is written false by the failed attempt"
        )
        assert checked["last_readiness_check_at"].startswith("2026-08-01T00:00:00"), (
            "the failed attempt still stamps last_readiness_check_at, got "
            f"{checked['last_readiness_check_at']}"
        )

    def test_readiness_recheck_from_ready_stays_ready_and_refreshes_the_timestamp(self):
        """PRD §3.2: "On a unit in `REGISTERED` where both are true, the unit advances `REGISTERED` → `READY`, `readiness_check_passed` is set to true, and `last_readiness_check_at` is stamped from the logical clock."
        PRD §3.2: "A re-run against a unit already in `READY` with both flags true keeps it in `READY` — `READY` → `READY` — and refreshes `last_readiness_check_at`."

        Design: Corner/state_machines/device_readiness_recheck_from_ready_stays_ready_and_refreshes_timestamp
        """
        set_clock(FAILED_CHECK_AT)
        _, station = _plan_and_station()
        device = register_device(
            station["id"], device_role="MONITOR", firmware_version="5.2.0"
        )

        set_clock(FIRST_PASSING_CHECK_AT)
        first = get_success_data(
            api_client.readiness_check_device(
                device["id"], readiness_check_payload(), ENGINEER
            )
        )
        assert first["status"] == "READY", (
            f"both flags true advance REGISTERED -> READY, got {first['status']}"
        )
        assert first["readiness_check_passed"] is True
        assert first["last_readiness_check_at"].startswith("2026-08-02T06:00:00"), (
            f"stamped from the clock, got {first['last_readiness_check_at']}"
        )

        set_clock(SECOND_PASSING_CHECK_AT)
        rerun = validate_success(
            api_client.readiness_check_device(
                device["id"], readiness_check_payload(), ENGINEER
            ),
            200,
        )
        assert rerun["status"] == "READY", (
            f"the READY self-loop keeps the unit READY, got {rerun['status']}"
        )
        assert rerun["readiness_check_passed"] is True, (
            "readiness_check_passed stays true across the re-run"
        )
        assert rerun["last_readiness_check_at"].startswith("2026-08-03T06:00:00"), (
            "the re-run refreshes last_readiness_check_at, got "
            f"{rerun['last_readiness_check_at']}"
        )

    def test_readiness_check_on_a_decommissioned_unit_is_rejected(self):
        """PRD §3.2: "Running a readiness check against a `DECOMMISSIONED` unit is rejected with `ERR_DEVICE_DECOMMISSIONED`."
        PRD §3.2: "`DECOMMISSIONED` is terminal for a device."

        Design: Corner/state_machines/decommissioned_device_cannot_run_a_readiness_check
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station(("PEP",))
        device = create_ready_device(station["id"])
        retired = get_success_data(
            api_client.decommission_device(device["id"], ADMIN)
        )
        assert retired["status"] == "DECOMMISSIONED", (
            f"the unit reaches the terminal status, got {retired['status']}"
        )

        validate_error(
            api_client.readiness_check_device(
                device["id"], readiness_check_payload(), ENGINEER
            ),
            "ERR_DEVICE_DECOMMISSIONED",
            409,
        )

        stored = get_success_data(api_client.get_device(device["id"], INSPECTOR))
        assert stored["status"] == "DECOMMISSIONED", (
            f"the rejected check left the terminal status alone, got {stored['status']}"
        )
        assert stored["readiness_check_passed"] == retired["readiness_check_passed"], (
            "the rejected check did not rewrite readiness_check_passed"
        )
        assert stored["last_readiness_check_at"] == retired["last_readiness_check_at"], (
            "the rejected check did not re-stamp last_readiness_check_at"
        )


# ===========================================================================
# The three outage actions, each with its own precondition and error
# ===========================================================================
class TestOutageTransitionPreconditions:
    """From the wrong status each outage action names its own conflict."""

    def test_close_from_open_is_rejected_as_not_restored(self):
        """PRD §3.4: "Both rejection and acceptance are permitted only from `RESTORED`; from any other status either is rejected with `ERR_OUTAGE_NOT_RESTORED`."

        Design: Corner/state_machines/outage_start_repair_from_restored_cannot_apply
        """
        ctx = _station_with_open_outage()

        validate_error(
            api_client.close_outage(ctx["outage"]["id"], ADMIN),
            "ERR_OUTAGE_NOT_RESTORED",
            409,
        )

        stored = get_success_data(
            api_client.get_equipment_outage(ctx["outage"]["id"], ADMIN)
        )
        assert stored["status"] == "OPEN", (
            f"the rejected close left the outage OPEN, got {stored['status']}"
        )

    def test_start_repair_from_restored_is_rejected_as_not_repairable(self):
        """PRD §3.4: "Starting a repair is permitted from two starting statuses — `OPEN` → `REPAIR_IN_PROGRESS` and `VERIFICATION_FAILED` → `REPAIR_IN_PROGRESS`; starting a repair from any other status is rejected with `ERR_OUTAGE_NOT_REPAIRABLE`."

        Design: Corner/state_machines/outage_start_repair_from_restored_cannot_apply
        """
        ctx = _station_with_restored_outage()

        validate_error(
            api_client.start_repair(ctx["outage"]["id"], ENGINEER),
            "ERR_OUTAGE_NOT_REPAIRABLE",
            409,
        )

        stored = get_success_data(
            api_client.get_equipment_outage(ctx["outage"]["id"], ADMIN)
        )
        assert stored["status"] == "RESTORED", (
            f"RESTORED is not in {{OPEN, VERIFICATION_FAILED}}, got {stored['status']}"
        )

    def test_restore_from_restored_is_rejected_and_leaves_the_downtime_pair(self):
        """PRD §3.4: "Reporting restoration is permitted only from `REPAIR_IN_PROGRESS`, moving the row `REPAIR_IN_PROGRESS` → `RESTORED`; from any other status it is rejected with `ERR_OUTAGE_NOT_IN_REPAIR`."
        PRD §3.4: "Both entries stamp `repair_started_at` from the logical clock, but only the entry from `VERIFICATION_FAILED` increases `repair_cycle_count` by one — the counter measures re-work, so the first repair attempt leaves it at 0."
        PRD §3.4: "Subtract `detected_at` from `restored_at`, divide the resulting number of seconds by 3600, and round half-up to two decimal places; the result is `continuous_downtime_hours`."
        PRD §3.4: "Accumulate the day contributions in seconds, divide the accumulated total by 3600, and round half-up to two decimal places to obtain `obligation_downtime_hours`."

        Design: Corner/state_machines/outage_start_repair_from_restored_cannot_apply
        """
        ctx = _station_with_restored_outage()

        validate_error(
            api_client.restore_outage(ctx["outage"]["id"], ENGINEER),
            "ERR_OUTAGE_NOT_IN_REPAIR",
            409,
        )

        stored = get_success_data(
            api_client.get_equipment_outage(ctx["outage"]["id"], ADMIN)
        )
        assert stored["status"] == "RESTORED"
        assert stored["repair_cycle_count"] == 0, (
            f"the first repair attempt leaves the counter at 0, got {stored['repair_cycle_count']}"
        )
        assert stored["repair_started_at"].startswith("2026-08-12T09:00:00"), (
            f"repair_started_at is unchanged, got {stored['repair_started_at']}"
        )
        assert stored["restored_at"].startswith("2026-08-12T14:00:00"), (
            f"restored_at is unchanged, got {stored['restored_at']}"
        )
        assert stored["continuous_downtime_hours"] == pytest.approx(6.00, abs=0.01), (
            "08:00Z to 14:00Z is 6.00 continuous hours, got "
            f"{stored['continuous_downtime_hours']}"
        )
        assert stored["obligation_downtime_hours"] == pytest.approx(6.00, abs=0.01), (
            "the whole interval sits inside the 08:00-20:00 obligation window, got "
            f"{stored['obligation_downtime_hours']}"
        )
        assert stored["continuous_clock_breached"] is False
        assert stored["obligation_breached"] is False


# ===========================================================================
# Closing an outage returns the device but not the coverage
# ===========================================================================
class TestOutageCloseReturnsEquipment:
    """RESTORED -> CLOSED lifts the device to READY and its rows to SILENT."""

    def test_close_returns_the_device_to_ready_and_the_assignment_to_silent(self):
        """PRD §3.4: "Acceptance moves the row `RESTORED` → `CLOSED`, which is terminal."
        PRD §3.4: "On close, the referenced unit moves `FAILED` → `READY` provided no *other* outage on that same unit is currently in `OPEN`, `REPAIR_IN_PROGRESS` or `VERIFICATION_FAILED`; if such an outage does remain, this outage still reaches `CLOSED` but the unit stays `FAILED`."
        PRD §3.3: "When the outage is later closed and the unit returns to `READY`, every assignment on it sitting in `SUSPENDED` moves `SUSPENDED` → `SILENT` rather than straight back to `ACTIVE`, with `silence_flagged_at` stamped at the close instant and a station recompute event fired; a fresh receipt is required before the row counts toward coverage again."

        Design: Corner/state_machines/outage_close_returns_device_to_ready_and_suspended_assignments_to_silent
        """
        ctx = _station_with_restored_outage()
        assignment_id = ctx["assignments"]["PEP"]["id"]

        closed = validate_success(
            api_client.close_outage(ctx["outage"]["id"], ADMIN), 200
        )
        assert closed["status"] == "CLOSED", (
            f"RESTORED -> CLOSED, got {closed['status']}"
        )
        assert closed["restored_at"].startswith("2026-08-12T14:00:00"), (
            f"restored_at is preserved through the close, got {closed['restored_at']}"
        )

        device = get_success_data(api_client.get_device(ctx["device_id"], ENGINEER))
        assert device["status"] == "READY", (
            f"the FAILED -> READY hop fires from the close, got {device['status']}"
        )

        assignment = get_success_data(
            api_client.get_monitoring_assignment(assignment_id, ENGINEER)
        )
        assert assignment["status"] == "SILENT", (
            f"a SUSPENDED row returns to SILENT, not ACTIVE, got {assignment['status']}"
        )
        assert assignment["silence_flagged_at"].startswith("2026-08-12T14:30:00"), (
            "silence_flagged_at is stamped at the close instant, got "
            f"{assignment['silence_flagged_at']}"
        )

    def test_close_leaves_the_station_suspended_on_a_silent_assignment(self):
        """PRD §3.8: "`accessible_source_count` is the number of *distinct* `source_type` values among the station's monitoring assignments whose `status` is `ACTIVE` and whose `source_type` appears in the governing plan's `required_source_types`; two `ACTIVE` assignments covering the same required source type therefore count once, and assignments in `SILENT`, `SUSPENDED` or `DECOMMISSIONED` do not count at all."
        PRD §3.8: "25.00 points for every required source type the station is missing, where the missing count is the plan's `required_source_count` less the station's `accessible_source_count`, floored at zero so that over-coverage never earns a credit;"
        PRD §3.8: "10.00 points for each assignment counted in `silent_assignment_count`;"
        PRD §2.10: "The band mapping is: a score of 90.00 or greater yields `COMPLIANT`; a score of at least 75.00 but below 90.00 yields `WATCH`; anything below 75.00 yields `SUSPENDED_FILINGS`."
        PRD §3.8: "The outage breach count is the number of equipment outages whose `device_id` belongs to this station, whose `obligation_breached` is true, and whose `status` is `OPEN`, `REPAIR_IN_PROGRESS`, `RESTORED` or `VERIFICATION_FAILED` — a `CLOSED` outage stops counting even if it breached."

        Design: Corner/state_machines/outage_close_returns_device_to_ready_and_suspended_assignments_to_silent
        """
        ctx = _station_with_restored_outage()
        get_success_data(api_client.close_outage(ctx["outage"]["id"], ADMIN))

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            accessible_source_count=0,
            missing_source_count=1,
            silent_assignment_count=1,
            outage_breach_count=0,
        )
        assert_score_and_posture(summary, 65.00, "SUSPENDED_FILINGS")


# ===========================================================================
# A RECEIPT log line reaches into the monitoring-assignment aggregate
# ===========================================================================
class TestReceiptLogEntryReactivation:
    """The test-log endpoint carries the same receipt effect as record-receipt."""

    def test_receipt_log_line_returns_a_silent_assignment_to_active(self):
        """PRD §3.8: "Every monitoring assignment of the station whose `status` is `ACTIVE` and whose last evidence of life is strictly earlier than the current logical clock less eight days is pushed `ACTIVE` → `SILENT`, with `silence_flagged_at` stamped."
        PRD §3.3: "The same receipt effect is reachable a second way: appending a test log line of kind `RECEIPT` whose `source_call_sign` equals an assignment's `source_call_sign` stamps that assignment's `last_receipt_at` and, if the assignment was `SILENT`, returns it to `ACTIVE`."
        PRD §3.6: "A `RECEIPT` line additionally refreshes the matching assignment's `last_receipt_at` and returns that assignment to `ACTIVE` if it was `SILENT`, exactly as an explicit receipt would."
        PRD §3.3: "On a row in `SILENT` it additionally moves the row `SILENT` → `ACTIVE` and clears `silence_flagged_at` back to null; on a row already in `ACTIVE` it leaves the status alone — `ACTIVE` → `ACTIVE` — and only refreshes `last_receipt_at`."

        Design: Corner/state_machines/receipt_log_entry_reactivates_a_matching_silent_assignment
        """
        ctx = _station_with_silent_satellite_and_ready_event()

        flagged = get_success_data(
            api_client.get_monitoring_assignment(ctx["ma_sat_id"], ENGINEER)
        )
        assert flagged["status"] == "SILENT", (
            f"the silence sweep flagged the SATELLITE row, got {flagged['status']}"
        )
        assert flagged["silence_flagged_at"].startswith("2026-08-10T00:00:00"), (
            f"silence_flagged_at carries the review instant, got {flagged['silence_flagged_at']}"
        )
        heard = get_success_data(
            api_client.get_monitoring_assignment(ctx["ma_pep_id"], ENGINEER)
        )
        assert heard["status"] == "ACTIVE", (
            f"the PEP row was heard inside the horizon, got {heard['status']}"
        )
        assert_score_and_posture(station_summary(ctx["station_id"]), 90.00, "COMPLIANT")

        append_log_entry(
            ctx["test_event_id"],
            ctx["device_id"],
            "RECEIPT",
            source_call_sign=SOURCE_CALL_SIGNS["SATELLITE"],
        )

        reactivated = get_success_data(
            api_client.get_monitoring_assignment(ctx["ma_sat_id"], ENGINEER)
        )
        assert reactivated["status"] == "ACTIVE", (
            f"the RECEIPT line returned the row to ACTIVE, got {reactivated['status']}"
        )
        assert reactivated["silence_flagged_at"] is None, (
            f"silence_flagged_at is cleared, got {reactivated['silence_flagged_at']}"
        )
        assert reactivated["last_receipt_at"].startswith("2026-08-12T00:30:00"), (
            f"last_receipt_at is stamped from the clock, got {reactivated['last_receipt_at']}"
        )

        event = get_success_data(
            api_client.get_test_event(ctx["test_event_id"], ADMIN)
        )
        assert event["logged_entry_count"] == 1, (
            f"the accepted line raised logged_entry_count to 1, got {event['logged_entry_count']}"
        )
        assert event["status"] == "READY", (
            f"appending a line leaves the event READY, got {event['status']}"
        )

    def test_receipt_log_line_naming_an_unknown_source_is_rejected(self):
        """PRD §3.6: "And a `RECEIPT` line's `source_call_sign` must match the `source_call_sign` of at least one monitoring assignment of that station, otherwise `ERR_LOG_ENTRY_SOURCE_UNKNOWN`."
        PRD §3.6: "It raises the event's `logged_entry_count` by one."

        Design: Corner/state_machines/receipt_log_entry_reactivates_a_matching_silent_assignment
        """
        ctx = _station_with_silent_satellite_and_ready_event()

        validate_error(
            api_client.create_test_log_entry(
                factories.test_log_entry_payload(
                    ctx["test_event_id"],
                    ctx["device_id"],
                    entry_kind="RECEIPT",
                    source_call_sign="WXGHOST",
                ),
                ENGINEER,
            ),
            "ERR_LOG_ENTRY_SOURCE_UNKNOWN",
            422,
        )

        event = get_success_data(
            api_client.get_test_event(ctx["test_event_id"], ADMIN)
        )
        assert event["logged_entry_count"] == 0, (
            f"the rejected line appended nothing, got {event['logged_entry_count']}"
        )
        silent = get_success_data(
            api_client.get_monitoring_assignment(ctx["ma_sat_id"], ENGINEER)
        )
        assert silent["status"] == "SILENT", (
            f"the rejected line reactivated nothing, got {silent['status']}"
        )


# ===========================================================================
# LOGGED seals the logging window from both endpoints
# ===========================================================================
class TestLoggedTestEventSealsLogging:
    """close-logging distinguishes its two failure modes."""

    def test_close_logging_without_entries_is_rejected_and_the_event_stays_ready(self):
        """PRD §3.6: "It is permitted only from `READY`, otherwise `ERR_TEST_NOT_READY`, and only when the event has at least one log line — an event whose `logged_entry_count` is 0 is rejected with `ERR_TEST_NO_ENTRIES`."

        Design: Corner/state_machines/logging_endpoints_on_a_logged_test_event_are_rejected
        """
        ctx = setup_ready_test_event()

        validate_error(
            api_client.close_logging(ctx["test_event_id"], ENGINEER),
            "ERR_TEST_NO_ENTRIES",
            409,
        )

        event = get_success_data(
            api_client.get_test_event(ctx["test_event_id"], ADMIN)
        )
        assert event["status"] == "READY", (
            f"the rejected close left the event READY, got {event['status']}"
        )
        assert event["logged_entry_count"] == 0, (
            f"logged_entry_count is still 0, got {event['logged_entry_count']}"
        )

    def test_close_logging_twice_is_rejected(self):
        """PRD §3.6: "Closing the logging phase moves the event `READY` → `LOGGED`."
        PRD §3.6: "It is permitted only from `READY`, otherwise `ERR_TEST_NOT_READY`, and only when the event has at least one log line — an event whose `logged_entry_count` is 0 is rejected with `ERR_TEST_NO_ENTRIES`."

        Design: Corner/state_machines/logging_endpoints_on_a_logged_test_event_are_rejected
        """
        ctx = setup_ready_test_event()
        append_log_entry(ctx["test_event_id"], ctx["device_id"], "TRANSMISSION")

        closed = validate_success(
            api_client.close_logging(ctx["test_event_id"], ENGINEER), 200
        )
        assert closed["status"] == "LOGGED", (
            f"READY -> LOGGED, got {closed['status']}"
        )
        assert closed["logged_entry_count"] == 1, (
            f"one line was appended, got {closed['logged_entry_count']}"
        )

        validate_error(
            api_client.close_logging(ctx["test_event_id"], ENGINEER),
            "ERR_TEST_NOT_READY",
            409,
        )

    def test_log_entry_after_close_logging_is_rejected(self):
        """PRD §3.6: "The event must currently be in `READY`, otherwise `ERR_TEST_NOT_READY`."

        Design: Corner/state_machines/logging_endpoints_on_a_logged_test_event_are_rejected
        """
        ctx = setup_ready_test_event()
        append_log_entry(ctx["test_event_id"], ctx["device_id"], "TRANSMISSION")
        get_success_data(api_client.close_logging(ctx["test_event_id"], ENGINEER))

        validate_error(
            api_client.create_test_log_entry(
                factories.test_log_entry_payload(
                    ctx["test_event_id"],
                    ctx["device_id"],
                    entry_kind="RECEIPT",
                    source_call_sign=SOURCE_CALL_SIGNS["PEP"],
                ),
                ENGINEER,
            ),
            "ERR_TEST_NOT_READY",
            409,
        )

        event = get_success_data(
            api_client.get_test_event(ctx["test_event_id"], ADMIN)
        )
        assert event["logged_entry_count"] == 1, (
            f"the rejected line appended nothing, got {event['logged_entry_count']}"
        )
        assert event["status"] == "LOGGED", (
            f"the event is still LOGGED, got {event['status']}"
        )


# ===========================================================================
# The unfiled sweep makes a test event terminal
# ===========================================================================
class TestFailedUnfiledTestEvent:
    """Phase 2 pushes a stale LOGGED event to its terminal status."""

    def test_unfiled_sweep_blocks_the_filing_with_its_own_error(self):
        """PRD §3.8: "Every test event of the station whose `status` is `READY` or `LOGGED` and whose `filing_deadline_at` is strictly earlier than the current logical clock is pushed to `FAILED_UNFILED`."
        PRD §3.7: "The event's `status` must be `LOGGED` or `FILED`; anything else is rejected with `ERR_TEST_NOT_LOGGED`, except that an event already in `FAILED_UNFILED` is rejected with the more specific `ERR_TEST_ALREADY_FAILED_UNFILED`."

        Design: Corner/state_machines/failed_unfiled_test_event_cannot_be_filed
        """
        ctx = setup_logged_test_event()
        set_clock(UNFILED_SWEEP_AT)
        run_log_review(ctx["station_id"])

        event = get_success_data(
            api_client.get_test_event(ctx["test_event_id"], OFFICER)
        )
        assert event["status"] == "FAILED_UNFILED", (
            "the sweep pushed the event past its filing deadline, got "
            f"{event['status']}"
        )

        validate_error(
            api_client.create_filing_record(
                factories.filing_record_payload(
                    ctx["test_event_id"], event["version"]
                ),
                OFFICER,
            ),
            "ERR_TEST_ALREADY_FAILED_UNFILED",
            409,
        )

        _, meta = validate_paginated(
            api_client.list_filing_records(
                ADMIN, params={"test_event_id": ctx["test_event_id"]}
            )
        )
        assert meta["total_count"] == 0, (
            f"the rejected filing stored no row, got total_count {meta['total_count']}"
        )

    def test_unfiled_test_count_costs_nothing_under_the_provisional_variant(self):
        """PRD §3.8: "The unfiled test count is the number of the station's test events whose `status` is `FAILED_UNFILED`, and it is consumed by the certified variant only."
        PRD §3.8: "When the station is not certified-eligible, `compliance_variant_applied` is `PROVISIONAL` and only the first four deductions are applied."
        PRD §3.8: "**Phase 4 — variant, score, posture.** The scoring variant is chosen, `compliance_score` and `compliance_variant_applied` are written, `compliance_posture` is set from the score bands, and `last_log_review_at` is stamped from the logical clock."

        Design: Corner/state_machines/failed_unfiled_test_event_cannot_be_filed
        """
        ctx = setup_logged_test_event()
        set_clock(UNFILED_SWEEP_AT)
        run_log_review(ctx["station_id"])

        summary = station_summary(ctx["station_id"])
        assert_summary_inputs(
            summary,
            unfiled_test_count=1,
            silent_assignment_count=0,
            compliance_variant_applied="PROVISIONAL",
        )
        assert_score_and_posture(summary, 100.00, "COMPLIANT")
        assert summary["last_log_review_at"].startswith("2026-08-18T00:00:00"), (
            f"last_log_review_at is stamped by the review, got {summary['last_log_review_at']}"
        )


# ===========================================================================
# Inspection response states
# ===========================================================================
class TestInspectionResponseStates:
    """Once RESPONDED the only legal move is close, and closed is terminal."""

    def test_submit_response_from_open_is_rejected_as_not_drafted(self):
        """PRD §3.9: "The request must currently be in `RESPONSE_DRAFTED` and `provided_document_kinds` must hold at least one entry; a submission that fails either condition is rejected with `ERR_INSPECTION_NOT_DRAFTED`."

        Design: Corner/state_machines/inspection_responded_cannot_be_redrafted_or_double_closed
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station()
        request = setup_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])

        validate_error(
            api_client.submit_response(request["id"], OFFICER),
            "ERR_INSPECTION_NOT_DRAFTED",
            409,
        )

        stored = get_success_data(
            api_client.get_inspection_request(request["id"], INSPECTOR)
        )
        assert stored["status"] == "OPEN", (
            f"the rejected submission left the request OPEN, got {stored['status']}"
        )

    def test_close_from_open_is_rejected_as_not_responded(self):
        """PRD §3.9: "Closing is the inspector's call, permitted only from `RESPONDED` and rejected with `ERR_INSPECTION_NOT_RESPONDED` otherwise."

        Design: Corner/state_machines/inspection_responded_cannot_be_redrafted_or_double_closed
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station()
        request = setup_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])

        validate_error(
            api_client.close_inspection(request["id"], INSPECTOR),
            "ERR_INSPECTION_NOT_RESPONDED",
            409,
        )

    def test_redraft_overwrites_provided_document_kinds_and_then_submits(self):
        """PRD §3.9: "Drafting is permitted from `OPEN` and from `RESPONSE_DRAFTED`, both landing in `RESPONSE_DRAFTED` — `OPEN` → `RESPONSE_DRAFTED` on the first draft and `RESPONSE_DRAFTED` → `RESPONSE_DRAFTED` on any re-draft — and each draft **overwrites** `provided_document_kinds` wholesale rather than merging into it."
        PRD §3.9: "A `CertifyingOfficer` then submits, moving the request `RESPONSE_DRAFTED` → `RESPONDED`."
        PRD §3.9: "Submission stamps `responded_at` from the logical clock and computes `completeness_score`."
        PRD §3.9: "Count the distinct document kinds that appear in both `provided_document_kinds` and `requested_document_kinds`; multiply that matched count by 100, divide by the number of entries in `requested_document_kinds` — treating that divisor as 1 if it is somehow 0 — and round half-up to two decimal places to obtain the raw figure."
        PRD §3.9: "If `responded_at` is at or before `response_due_at`, `completeness_score` is that raw figure unchanged."

        Design: Corner/state_machines/inspection_responded_cannot_be_redrafted_or_double_closed
        """
        set_clock(CLOCK_START)
        _, station = _plan_and_station()
        request = setup_inspection(station["id"], ["STATION_LOG", "TEST_LOGS"])
        set_clock(INSPECTION_RESPONSE_AT)

        first = get_success_data(
            api_client.draft_response(
                request["id"], draft_response_payload(["STATION_LOG"]), ENGINEER
            )
        )
        assert first["status"] == "RESPONSE_DRAFTED", (
            f"OPEN -> RESPONSE_DRAFTED on the first draft, got {first['status']}"
        )
        assert first["provided_document_kinds"] == ["STATION_LOG"]

        second = get_success_data(
            api_client.draft_response(
                request["id"],
                draft_response_payload(["STATION_LOG", "TEST_LOGS"]),
                ENGINEER,
            )
        )
        assert second["status"] == "RESPONSE_DRAFTED", (
            f"the re-draft stays in RESPONSE_DRAFTED, got {second['status']}"
        )
        assert sorted(second["provided_document_kinds"]) == ["STATION_LOG", "TEST_LOGS"], (
            "the re-draft overwrote the array wholesale, got "
            f"{second['provided_document_kinds']}"
        )

        responded = validate_success(
            api_client.submit_response(request["id"], OFFICER), 200
        )
        assert responded["status"] == "RESPONDED", (
            f"RESPONSE_DRAFTED -> RESPONDED, got {responded['status']}"
        )
        assert responded["responded_at"].startswith("2026-08-03T00:00:00"), (
            f"responded_at is stamped from the clock, got {responded['responded_at']}"
        )
        assert responded["completeness_score"] == pytest.approx(100.00, abs=0.01), (
            "two of two requested kinds produced on time scores 100.00, got "
            f"{responded['completeness_score']}"
        )

    def test_draft_response_after_responded_is_rejected(self):
        """PRD §3.9: "Drafting from any other status is rejected with `ERR_INSPECTION_NOT_DRAFTABLE`."

        Design: Corner/state_machines/inspection_responded_cannot_be_redrafted_or_double_closed
        """
        _, responded = _responded_inspection()

        validate_error(
            api_client.draft_response(
                responded["id"],
                draft_response_payload(["STATION_LOG", "TEST_LOGS", "PLAN_COPY"]),
                ENGINEER,
            ),
            "ERR_INSPECTION_NOT_DRAFTABLE",
            409,
        )

        stored = get_success_data(
            api_client.get_inspection_request(responded["id"], INSPECTOR)
        )
        assert stored["status"] == "RESPONDED", (
            f"the rejected draft left the request RESPONDED, got {stored['status']}"
        )
        assert sorted(stored["provided_document_kinds"]) == ["STATION_LOG", "TEST_LOGS"], (
            "the rejected draft did not overwrite provided_document_kinds, got "
            f"{stored['provided_document_kinds']}"
        )

    def test_closed_inspection_cannot_be_closed_again(self):
        """PRD §3.9: "The outcome is decided by the score alone and is inclusive at the boundary: a `completeness_score` of 100.00 or greater closes the request `RESPONDED` → `CLOSED_SATISFIED`, and anything below 100.00 closes it `RESPONDED` → `CLOSED_DEFICIENT`."
        PRD §3.9: "Both closed statuses are terminal."
        PRD §3.9: "Closing is the inspector's call, permitted only from `RESPONDED` and rejected with `ERR_INSPECTION_NOT_RESPONDED` otherwise."

        Design: Corner/state_machines/inspection_responded_cannot_be_redrafted_or_double_closed
        """
        _, responded = _responded_inspection()

        closed = validate_success(
            api_client.close_inspection(responded["id"], INSPECTOR), 200
        )
        assert closed["status"] == "CLOSED_SATISFIED", (
            f"completeness_score 100.00 closes satisfied, got {closed['status']}"
        )

        validate_error(
            api_client.close_inspection(responded["id"], INSPECTOR),
            "ERR_INSPECTION_NOT_RESPONDED",
            409,
        )

        stored = get_success_data(
            api_client.get_inspection_request(responded["id"], INSPECTOR)
        )
        assert stored["status"] == "CLOSED_SATISFIED", (
            f"the terminal status is not re-enterable, got {stored['status']}"
        )


# ===========================================================================
# The two alert dimensions each guard themselves
# ===========================================================================
class TestAlertDimensionGuards:
    """Neither rejected call on one axis touches the other axis."""

    def test_confirm_relay_on_an_unmatched_alert_is_rejected(self):
        """PRD §3.5: "Confirming that the forward actually went out moves the alert `RELAY_PENDING` → `RELAYED`; attempting it on an alert whose `relay_state` is anything else is rejected with `ERR_ALERT_NOT_RELAY_PENDING`."
        PRD §3.5: "Confirmation touches only the forwarding dimension and leaves `accessibility_state` exactly as it was."

        Design: Corner/state_machines/alert_axis_endpoints_cannot_apply_from_the_wrong_dimension_state
        """
        set_clock(CLOCK_START)
        _, alert = _unmatched_alert()
        assert alert["relay_state"] == "UNMATCHED_OPTIONAL", (
            f"an empty candidate pool yields UNMATCHED_OPTIONAL, got {alert['relay_state']}"
        )

        validate_error(
            api_client.confirm_relay(alert["id"], ENGINEER),
            "ERR_ALERT_NOT_RELAY_PENDING",
            409,
        )

        stored = get_success_data(api_client.get_alert_event(alert["id"], ADMIN))
        assert stored["relay_state"] == "UNMATCHED_OPTIONAL", (
            f"the rejected confirmation changed nothing, got {stored['relay_state']}"
        )
        assert stored["accessibility_state"] == "ACCESSIBILITY_UNVERIFIED", (
            f"the accessibility axis is untouched, got {stored['accessibility_state']}"
        )

    def test_second_accessibility_verification_is_rejected_and_the_first_stands(self):
        """PRD §3.5: "The caption penalty is 0.00 points when `caption_interaction` is `NONE`, 1.50 points when it is `CAPTION_SUPPRESSED`, and 2.00 points when it is `CRAWL_OVERLAP`."
        PRD §3.5: "The verdict is inclusive at the boundary: `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_PASSED` when `accessibility_deficiency_points` is 1.00 or less, and `ACCESSIBILITY_UNVERIFIED` → `ACCESSIBILITY_FAILED` when it is strictly greater than 1.00."
        PRD §3.5: "Verification is a once-only act: the alert's `accessibility_state` must be `ACCESSIBILITY_UNVERIFIED`, and a second attempt is rejected with `ERR_ACCESSIBILITY_ALREADY_VERIFIED`."
        PRD §3.5: "Both outcomes write the three measurement fields and `accessibility_deficiency_points`, and neither touches `relay_state`."

        Design: Corner/state_machines/alert_axis_endpoints_cannot_apply_from_the_wrong_dimension_state
        """
        set_clock(CLOCK_START)
        _, alert = _unmatched_alert()

        verified = validate_success(
            api_client.verify_accessibility(
                alert["id"],
                factories.accessibility_payload(
                    visual_crawl_seconds=60,
                    audio_loudness_lufs=-24.0,
                    caption_interaction="NONE",
                ),
                ENGINEER,
            ),
            200,
        )
        assert verified["accessibility_deficiency_points"] == pytest.approx(
            0.00, abs=0.01
        ), (
            "a 60-second crawl at the -24.0 LUFS target with no caption interaction "
            f"scores 0.00 points, got {verified['accessibility_deficiency_points']}"
        )
        assert verified["accessibility_state"] == "ACCESSIBILITY_PASSED", (
            f"0.00 is at or below 1.00, got {verified['accessibility_state']}"
        )

        validate_error(
            api_client.verify_accessibility(
                alert["id"],
                factories.accessibility_payload(
                    visual_crawl_seconds=0,
                    audio_loudness_lufs=-60.0,
                    caption_interaction="CRAWL_OVERLAP",
                ),
                ENGINEER,
            ),
            "ERR_ACCESSIBILITY_ALREADY_VERIFIED",
            409,
        )

        stored = get_success_data(api_client.get_alert_event(alert["id"], ADMIN))
        assert stored["visual_crawl_seconds"] == 60, (
            f"the first measurement stands, got {stored['visual_crawl_seconds']}"
        )
        assert stored["audio_loudness_lufs"] == pytest.approx(-24.0, abs=0.01), (
            f"the first measurement stands, got {stored['audio_loudness_lufs']}"
        )
        assert stored["caption_interaction"] == "NONE", (
            f"the first measurement stands, got {stored['caption_interaction']}"
        )
        assert stored["accessibility_deficiency_points"] == pytest.approx(
            0.00, abs=0.01
        ), (
            "the rejected re-verification did not rescore the alert, got "
            f"{stored['accessibility_deficiency_points']}"
        )
        assert stored["relay_state"] == "UNMATCHED_OPTIONAL", (
            f"the forwarding axis is untouched, got {stored['relay_state']}"
        )
