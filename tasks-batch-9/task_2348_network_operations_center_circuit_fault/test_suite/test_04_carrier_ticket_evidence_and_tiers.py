"""Carrier trouble tickets: admissibility, stamped evidence and tier climbing.

A ticket is the NOC's formal assertion that the fault belongs to the carrier, so
the service refuses to open one without a monitored, genuinely faulted circuit,
and it refuses to climb the carrier's escalation ladder without evidence, dwell
time and a single-rung request.
"""

from test_helpers import (
    ANALYST_HEADERS,
    ANALYST_USER_ID,
    SHIFT_LEAD_HEADERS,
    ApiErrorId,
    advance_clock,
    assert_circuit_posture,
    assert_incident_classification,
    assert_instant,
    assert_page,
    build_approved_carrier_window,
    build_pft_single_leg,
    build_srg_single_gold,
    carrier_ticket_payload,
    clear_alarm,
    file_test_result,
    open_carrier_ticket,
    read_circuit,
    read_incident,
    read_ticket,
    read_window,
    set_window_state,
    stamped,
    ticket_escalate_payload,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestTicketCreation:
    """Opening a ticket derives most of its content from the circuit and the clock."""

    def test_ticket_creation_stamps_every_system_field(self, api):
        """Three inputs are supplied; the identity, clocks and snapshot are derived.

        PRD 3.5: "A new ticket is created in `OPEN` with `tier_level` 1, and both `tier_entered_at` and `opened_at` set to the current clock instant."
        PRD 3.5: "Its `carrier_id` is copied from the circuit rather than supplied, and `reported_circuit_identifier` snapshots the circuit's `carrier_circuit_identifier` at open time so that a later inventory rename cannot rewrite what was quoted to the carrier."
        PRD 3.5: "Everything downstream starts empty: `restored_at`, `confirmed_at`, `restoration_confirmed_by_user_id`, `restoration_minutes_carrier_clock` and `restoration_minutes_noc_clock` are null, `excluded_minutes` is 0, and `reopen_count` and `fail_test_count` are 0."

        Design: Corner/entities/corner_carrier_ticket_create_stamps_system_fields
        """
        state = build_pft_single_leg(
            api,
            "2026-08-01T00:00:00Z",
            path_name="Branch VPN Path",
            alarm_raised_at="2026-08-01T00:00:00Z",
        )

        advance_clock(api, "2026-08-01T00:45:00Z")
        response = api.create_carrier_ticket(
            carrier_ticket_payload(
                state["incident_id"], state["circuit_id"], carrier_reference="PFT-TT-1"
            ),
            ANALYST_HEADERS,
        )
        ticket = validate_success(response, 201)["data"]

        assert ticket["state"] == "OPEN", f"a new ticket opens in OPEN, got {ticket['state']}"
        assert ticket["tier_level"] == 1, (
            f"a new ticket starts at carrier tier 1, got {ticket['tier_level']}"
        )
        assert_instant(ticket["opened_at"], stamped("2026-08-01", "00:45"), "opened_at")
        assert_instant(
            ticket["tier_entered_at"], stamped("2026-08-01", "00:45"), "tier_entered_at"
        )
        assert ticket["carrier_id"] == state["carrier_id"], (
            "the carrier is copied from the circuit rather than supplied"
        )
        assert ticket["reported_circuit_identifier"] == "PFT-CKT-9001", (
            "the ticket snapshots the identifier quoted to the carrier"
        )
        assert ticket["opened_by_user_id"] == ANALYST_USER_ID, (
            "the acting analyst is recorded as the opener"
        )
        for field in (
            "restored_at",
            "confirmed_at",
            "restoration_confirmed_by_user_id",
            "restoration_minutes_carrier_clock",
            "restoration_minutes_noc_clock",
        ):
            assert ticket[field] is None, (
                f"a new ticket leaves {field} null, got {ticket[field]!r}"
            )
        assert ticket["excluded_minutes"] == 0, "excluded maintenance starts at zero"
        assert ticket["fail_test_count"] == 0, "no test evidence exists yet"
        assert ticket["reopen_count"] == 0, "the ticket has never reopened"

        incident = read_incident(api, state["incident_id"])
        assert incident["version"] == 2, (
            f"opening the ticket advanced the parent incident to version 2, "
            f"got {incident['version']}"
        )

    def test_second_open_ticket_on_the_same_circuit_is_refused(self, api):
        """A distinct carrier reference does not buy a second live case on one circuit.

        PRD 3.5: "No other ticket on the same circuit may be in a state other than `CLOSED_RESTORED` or `CLOSED_NO_FAULT`, or it is `ERR_DUPLICATE_OPEN_TICKET`."

        Design: Corner/validations/corner_second_open_ticket_on_same_circuit_rejected
        """
        state = build_pft_single_leg(
            api, "2026-08-28T00:00:00Z", alarm_raised_at="2026-08-28T00:00:00Z"
        )

        advance_clock(api, "2026-08-28T00:10:00Z")
        first = open_carrier_ticket(
            api, state["incident_id"], state["circuit_id"], "PFT-TT-10"
        )

        validate_error(
            api.create_carrier_ticket(
                carrier_ticket_payload(
                    state["incident_id"], state["circuit_id"], carrier_reference="PFT-TT-11"
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_DUPLICATE_OPEN_TICKET,
        )

        rows, meta = validate_paginated(
            api.list_carrier_tickets(
                SHIFT_LEAD_HEADERS, params={"circuit_id": state["circuit_id"]}
            )
        )
        assert_page(meta, total_count=1)
        assert rows[0]["carrier_reference"] == "PFT-TT-10", (
            "the surviving ticket is the one that was opened first"
        )

        unchanged = read_ticket(api, first["id"])
        assert unchanged["state"] == "OPEN", "the live ticket is untouched"
        assert unchanged["version"] == first["version"], (
            "a refused create must not advance the existing ticket's version"
        )

    def test_ticket_on_a_healthy_circuit_is_refused(self, api):
        """Once the alarm is cleared the circuit is up, so there is nothing to report.

        PRD 3.5: "And the circuit's `operational_state` must be `DEGRADED` or `DOWN`, or it is `ERR_CIRCUIT_NOT_FAULTED` — the NOC does not open carrier cases on healthy circuits."

        Design: Corner/validations/corner_ticket_on_healthy_circuit_rejected
        """
        state = build_pft_single_leg(
            api, "2026-08-29T00:00:00Z", alarm_raised_at="2026-08-29T00:00:00Z"
        )

        advance_clock(api, "2026-08-29T00:05:00Z")
        clear_alarm(api, state["alarm_id"], "2026-08-29T00:05:00Z")

        validate_error(
            api.create_carrier_ticket(
                carrier_ticket_payload(
                    state["incident_id"], state["circuit_id"], carrier_reference="PFT-TT-12"
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_CIRCUIT_NOT_FAULTED,
        )

        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]), operational_state="UP"
        )
        assert_incident_classification(
            read_incident(api, state["incident_id"]), response_state="DETECTED"
        )
        _, meta = validate_paginated(
            api.list_carrier_tickets(
                SHIFT_LEAD_HEADERS, params={"circuit_id": state["circuit_id"]}
            )
        )
        assert_page(meta, total_count=0)


class TestCarrierTierEscalation:
    """The carrier ladder is climbed one rung at a time, on evidence and dwell."""

    def test_skipping_a_carrier_tier_is_refused(self, api):
        """Tier 3 from tier 1 fails on sequence even when evidence and dwell are fine.

        PRD 3.5: "Five preconditions apply, evaluated in the priority order of Section 2.7: the ticket must be in `TESTING` or `ESCALATED_T2`, otherwise `ERR_TICKET_STATE_INVALID`; `target_tier` must be exactly one greater than the ticket's current `tier_level`, otherwise `ERR_TIER_SEQUENCE_INVALID`; `target_tier` must not exceed the carrier's `escalation_tier_count`, otherwise `ERR_TIER_CEILING_REACHED`; `fail_test_count` must be at least 1, so at least one failing or inconclusive test exists as evidence, otherwise `ERR_TEST_EVIDENCE_MISSING`; and the elapsed time from `tier_entered_at` to the current clock instant must have reached the carrier's `tier_escalation_min_minutes`, otherwise `ERR_TIER_DWELL_NOT_MET`."

        Design: Corner/state_machines/corner_ticket_escalation_skipping_tier_two_rejected
        """
        state = build_pft_single_leg(
            api, "2026-08-18T00:00:00Z", alarm_raised_at="2026-08-18T00:00:00Z"
        )

        advance_clock(api, "2026-08-18T00:10:00Z")
        ticket = open_carrier_ticket(
            api, state["incident_id"], state["circuit_id"], "PFT-TT-2"
        )

        advance_clock(api, "2026-08-18T00:20:00Z")
        result = file_test_result(
            api,
            ticket["id"],
            test_type="BERT",
            outcome="FAIL",
            notes="bit errors on both directions",
        )

        advance_clock(api, "2026-08-18T02:00:00Z")
        validate_error(
            api.escalate_carrier_ticket(
                ticket["id"],
                ticket_escalate_payload(3, justification="customer executive pressure"),
                SHIFT_LEAD_HEADERS,
            ),
            ApiErrorId.ERR_TIER_SEQUENCE_INVALID,
        )

        stored = read_ticket(api, ticket["id"])
        assert stored["tier_level"] == 1, (
            f"the refused escalation leaves the ticket at tier 1, got {stored['tier_level']}"
        )
        assert stored["state"] == "TESTING", (
            f"the ticket stays in TESTING, got {stored['state']}"
        )
        assert_instant(
            stored["tier_entered_at"],
            stamped("2026-08-18", "00:10"),
            "tier_entered_at",
        )
        assert stored["fail_test_count"] == 1, "the failing evidence is still counted once"
        assert_instant(
            result["performed_at"], stamped("2026-08-18", "00:20"), "performed_at"
        )
        assert result["recorded_by_user_id"] == ANALYST_USER_ID, (
            "the recording analyst is stamped on the evidence"
        )

    def test_tier_two_escalation_succeeds_on_evidence_and_exact_dwell(self, api):
        """A 60-minute dwell exactly meets the contract and restarts the dwell clock.

        PRD 3.5: "Success sets `tier_level` to `target_tier`, moves the ticket `TESTING → ESCALATED_T2` or `ESCALATED_T2 → ESCALATED_T3` accordingly, resets `tier_entered_at` to the current instant so the dwell clock restarts for the new tier, and advances `version` by 1."
        PRD 3.5: "Whenever the `outcome` is `FAIL` or `INCONCLUSIVE`, `fail_test_count` advances by 1; a `PASS` leaves it alone."

        Design: Corner/endpoints/corner_ticket_escalation_to_tier_two_succeeds_with_evidence_and_dwell
        """
        state = build_pft_single_leg(
            api, "2026-09-01T00:00:00Z", alarm_raised_at="2026-09-01T00:00:00Z"
        )

        advance_clock(api, "2026-09-01T00:10:00Z")
        ticket = open_carrier_ticket(
            api, state["incident_id"], state["circuit_id"], "PFT-TT-14"
        )

        advance_clock(api, "2026-09-01T00:20:00Z")
        file_test_result(
            api,
            ticket["id"],
            test_type="LOOPBACK",
            outcome="FAIL",
            notes="loopback fails at the carrier NID",
        )

        advance_clock(api, "2026-09-01T01:10:00Z")
        escalated = validate_success(
            api.escalate_carrier_ticket(
                ticket["id"],
                ticket_escalate_payload(
                    2,
                    justification="loopback failure unresolved after one hour at tier 1",
                ),
                SHIFT_LEAD_HEADERS,
            )
        )["data"]

        assert escalated["state"] == "ESCALATED_T2", (
            f"the ticket advances to ESCALATED_T2, got {escalated['state']}"
        )
        assert escalated["tier_level"] == 2, (
            f"the ticket now sits at tier 2, got {escalated['tier_level']}"
        )
        assert_instant(
            escalated["tier_entered_at"],
            stamped("2026-09-01", "01:10"),
            "tier_entered_at",
        )
        assert escalated["fail_test_count"] == 1, (
            "one failing result is all the evidence the ladder required"
        )

        _, meta = validate_paginated(
            api.list_test_results(
                ticket["id"], SHIFT_LEAD_HEADERS, params={"outcome": "FAIL"}
            )
        )
        assert_page(meta, total_count=1)

        assert_incident_classification(
            read_incident(api, state["incident_id"]), response_state="DETECTED"
        )


class TestTicketRequiresMonitoredCircuit:
    """Whether a ticket may open is decided by a field the window lifecycle owns."""

    def test_maintenance_suppressed_circuit_blocks_the_ticket(self, api):
        """Starting the window suppresses monitoring, and the ticket is refused.

        PRD 3.5: "The circuit's `monitoring_state` must be `MONITORED`, since an unmonitored or maintenance-suppressed circuit carries no trustworthy fault evidence, or it is `ERR_CIRCUIT_NOT_MONITORED`."
        PRD 3.7: "Moving `APPROVED → IN_PROGRESS` requires the current clock instant to be at or after `window_start` and strictly before `window_end`, otherwise `ERR_WINDOW_NOT_IN_EFFECT`; it captures the circuit's current `monitoring_state` into `monitoring_state_before_start` and, when `suppresses_monitoring` is true, sets the circuit's `monitoring_state` to `MAINTENANCE_SUPPRESSED` — which is what makes the alarms raised during the work land as suppressed noise with no incident, as described in Section 3.3."

        Design: Difficulty/cross_entity_state_dependency/carrier_ticket_open_requires_monitored_circuit_not_suppressed
        """
        state = build_srg_single_gold(
            api, "2026-08-12T00:00:00Z", alarm_raised_at="2026-08-12T00:00:00Z"
        )
        window = build_approved_carrier_window(
            api,
            state["circuit_id"],
            state["carrier_id"],
            "2026-08-12T01:00:00Z",
            "2026-08-12T02:00:00Z",
            suppresses_monitoring=True,
            risk_acknowledged=True,
        )

        advance_clock(api, "2026-08-12T01:30:00Z")
        started = set_window_state(api, window["window_id"], "IN_PROGRESS")
        assert started["state"] == "IN_PROGRESS", (
            f"the window is running, got {started['state']}"
        )
        assert started["monitoring_state_before_start"] == "MONITORED", (
            "the window captured the monitoring state it is about to override"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]),
            monitoring_state="MAINTENANCE_SUPPRESSED",
        )

        validate_error(
            api.create_carrier_ticket(
                carrier_ticket_payload(
                    state["incident_id"], state["circuit_id"], carrier_reference="SRG-TT-5501"
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_CIRCUIT_NOT_MONITORED,
        )

        _, meta = validate_paginated(
            api.list_carrier_tickets(
                SHIFT_LEAD_HEADERS, params={"incident_id": state["incident_id"]}
            )
        )
        assert_page(meta, total_count=0)

    def test_completing_the_window_unblocks_the_identical_request(self, api):
        """Completion restores the captured monitoring state and the same body succeeds.

        PRD 3.7: "Moving `IN_PROGRESS → COMPLETED` restores the circuit's `monitoring_state` to exactly the captured `monitoring_state_before_start` value, neither guessing `MONITORED` nor defaulting to `UNMONITORED`, and re-runs the posture cascade."
        PRD 3.5: "Its `carrier_id` is copied from the circuit rather than supplied, and `reported_circuit_identifier` snapshots the circuit's `carrier_circuit_identifier` at open time so that a later inventory rename cannot rewrite what was quoted to the carrier."

        Design: Difficulty/cross_entity_state_dependency/carrier_ticket_open_requires_monitored_circuit_not_suppressed
        """
        state = build_srg_single_gold(
            api, "2026-08-12T00:00:00Z", alarm_raised_at="2026-08-12T00:00:00Z"
        )
        window = build_approved_carrier_window(
            api,
            state["circuit_id"],
            state["carrier_id"],
            "2026-08-12T01:00:00Z",
            "2026-08-12T02:00:00Z",
            suppresses_monitoring=True,
            risk_acknowledged=True,
        )
        window_id = window["window_id"]

        advance_clock(api, "2026-08-12T01:30:00Z")
        set_window_state(api, window_id, "IN_PROGRESS")
        validate_error(
            api.create_carrier_ticket(
                carrier_ticket_payload(
                    state["incident_id"], state["circuit_id"], carrier_reference="SRG-TT-5501"
                ),
                ANALYST_HEADERS,
            ),
            ApiErrorId.ERR_CIRCUIT_NOT_MONITORED,
        )

        advance_clock(api, "2026-08-12T02:00:00Z")
        set_window_state(api, window_id, "COMPLETED")
        assert read_window(api, window_id)["state"] == "COMPLETED", (
            "the maintenance is over"
        )
        assert_circuit_posture(
            read_circuit(api, state["circuit_id"]), monitoring_state="MONITORED"
        )

        ticket = validate_success(
            api.create_carrier_ticket(
                carrier_ticket_payload(
                    state["incident_id"], state["circuit_id"], carrier_reference="SRG-TT-5501"
                ),
                ANALYST_HEADERS,
            ),
            201,
        )["data"]
        assert ticket["state"] == "OPEN", (
            f"the identical body now opens a ticket, got {ticket['state']}"
        )
        assert ticket["tier_level"] == 1, "the reinstated ticket starts at tier 1"
        assert ticket["reported_circuit_identifier"] == "SRG-CKT-3001", (
            "the ticket quotes the carrier's own circuit identifier"
        )
        assert ticket["carrier_id"] == state["carrier_id"], (
            "the carrier is copied from the circuit"
        )
