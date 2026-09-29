"""Incidents: the two independent lifecycle dimensions and the chronic ladder.

An incident carries a response dimension and an escalation dimension on the same
row. They advance separately, they are coupled in exactly one direction, and only
resolution feeds the chronic history of the circuit underneath.
"""

from test_helpers import (
    SHIFT_LEAD_HEADERS,
    SHIFT_LEAD_USER_ID,
    advance_clock,
    advance_incident,
    assert_carrier_ledger,
    assert_circuit_posture,
    assert_incident_classification,
    assert_instant,
    build_pft_single_leg,
    build_srg_single_gold,
    clear_alarm,
    incident_escalate_payload,
    read_carrier,
    read_circuit,
    read_incident,
    resolve_incident,
    run_fault_cycle,
    stamped,
    validate_success,
    walk_incident_to_mitigated,
)


def _escalate(api, incident_id: str, target_escalation_state: str) -> dict:
    """Climb one escalation rung as the shift lead on duty."""
    return validate_success(
        api.escalate_incident(
            incident_id,
            incident_escalate_payload(target_escalation_state),
            SHIFT_LEAD_HEADERS,
        )
    )["data"]


class TestIncidentOpening:
    """The incident is a side effect of the first alarm, never a client create."""

    def test_incident_opens_detected_with_no_management_attention(self, api):
        """Both dimensions start at their floor and every later stamp is null.

        PRD 3.4: "Opening stamps `detected_at` from the logical clock, sets `response_state` to `DETECTED` and `escalation_state` to `NONE`, starts `alarm_count` at 1 and `reopen_count` at 0, and leaves `triaged_at`, `mitigated_at` and `resolved_at` null."
        PRD 3.4: "It is anchored to a circuit — recorded as `primary_circuit_id`, which is the root alarm's own circuit for a circuit-sourced alarm and the alarming device's `primary_uplink_circuit_id` for a device-sourced one — and it remembers the alarm that opened it in `root_alarm_id`."

        Design: Corner/state_machines/corner_incident_opens_in_detected_with_no_escalation
        """
        state = build_pft_single_leg(
            api, "2026-08-01T03:00:00Z", alarm_raised_at="2026-08-01T03:00:00Z"
        )
        incident = read_incident(api, state["incident_id"])

        assert_incident_classification(
            incident,
            severity="SEV3",
            impact_score=20,
            response_state="DETECTED",
            escalation_state="NONE",
            alarm_count=1,
            reopen_count=0,
        )
        assert incident["root_alarm_id"] == state["alarm_id"], (
            "the incident remembers the alarm that opened it"
        )
        assert incident["primary_circuit_id"] == state["circuit_id"], (
            "a circuit-sourced alarm anchors the incident to its own circuit"
        )
        assert_instant(
            incident["detected_at"], stamped("2026-08-01", "03:00"), "detected_at"
        )
        for field in ("triaged_at", "mitigated_at", "resolved_at"):
            assert incident[field] is None, (
                f"a freshly opened incident leaves {field} null, got {incident[field]!r}"
            )
        assert_instant(
            incident["response_due_at"],
            stamped("2026-08-01", "05:00"),
            "response_due_at",
        )
        assert_instant(
            incident["escalation_due_at"],
            stamped("2026-08-01", "07:00"),
            "escalation_due_at",
        )
        assert incident["version"] == 1, (
            f"the opening cascade leaves the new incident at version 1, "
            f"got {incident['version']}"
        )


class TestTwoLifecycleDimensions:
    """Escalation climbs on its own; only mitigation reaches across to relax it."""

    def test_escalation_climbs_while_the_response_dimension_stands_still(self, api):
        """Two escalate calls reach `L2` with `response_state` still `DETECTED`.

        PRD 3.4: "The two lifecycle dimensions are genuinely parallel: `response_state` advances through triage, mitigation and resolution while `escalation_state` moves independently through management levels, and each advances on the same record without disturbing the other."
        PRD 3.4: "Escalation leaves `response_state` untouched and advances `version` by 1."

        Design: Difficulty/non_linear_state_machine/incident_escalation_dimension_de_escalates_on_mitigated
        """
        state = build_srg_single_gold(
            api, "2026-08-12T00:00:00Z", alarm_raised_at="2026-08-12T00:00:00Z"
        )
        incident_id = state["incident_id"]

        opened = read_incident(api, incident_id)
        assert_incident_classification(opened, severity="SEV1", impact_score=50)

        after_l1 = _escalate(api, incident_id, "L1")
        assert after_l1["escalation_state"] == "L1", (
            f"the first rung is L1, got {after_l1['escalation_state']}"
        )
        assert after_l1["response_state"] == "DETECTED", (
            "escalating must not move the response dimension"
        )

        advance_clock(api, "2026-08-12T00:30:00Z")
        after_l2 = _escalate(api, incident_id, "L2")
        assert after_l2["escalation_state"] == "L2", (
            f"the second rung is L2, got {after_l2['escalation_state']}"
        )
        assert after_l2["response_state"] == "DETECTED", (
            "two escalations still leave the response dimension at DETECTED"
        )
        assert after_l2["triaged_at"] is None, (
            "escalation stamps nothing on the response dimension"
        )

    def test_reaching_mitigated_relaxes_management_by_exactly_one_step(self, api):
        """`L2` becomes `L1` on mitigation — one step down, not a reset to `NONE`.

        PRD 3.4: "Reaching `MITIGATED` also relaxes management attention by exactly one step, without touching `response_state`: an incident at `EXEC` moves to `L2` and one at `L2` moves to `L1`, while `NONE` and `L1` are left where they are."
        PRD 3.4: "Only single steps forward are legal: `DETECTED → TRIAGED` stamps `triaged_at` with the current clock instant, and `TRIAGED → MITIGATED` stamps `mitigated_at`."

        Design: Difficulty/non_linear_state_machine/incident_escalation_dimension_de_escalates_on_mitigated
        """
        state = build_srg_single_gold(
            api, "2026-08-12T00:00:00Z", alarm_raised_at="2026-08-12T00:00:00Z"
        )
        incident_id = state["incident_id"]

        _escalate(api, incident_id, "L1")
        advance_clock(api, "2026-08-12T00:30:00Z")
        _escalate(api, incident_id, "L2")

        triaged = advance_incident(
            api, incident_id, "TRIAGED", note="field tech dispatched"
        )
        assert triaged["escalation_state"] == "L2", (
            "a response step below MITIGATED leaves the escalation dimension alone"
        )

        mitigated = advance_incident(
            api, incident_id, "MITIGATED", note="traffic rerouted over the backup path"
        )
        assert_incident_classification(
            mitigated,
            severity="SEV1",
            impact_score=50,
            response_state="MITIGATED",
            escalation_state="L1",
        )
        assert_instant(
            mitigated["mitigated_at"], stamped("2026-08-12", "00:30"), "mitigated_at"
        )
        assert mitigated["resolved_at"] is None, (
            "mitigation is not resolution, so resolved_at stays null"
        )


class TestResolutionAndChronicHistory:
    """Resolution is the only trigger of the circuit's chronic re-evaluation."""

    def test_first_resolution_counts_one_fault_and_stays_normal(self, api):
        """One resolved incident leaves `fault_count_period` 1 and the ladder at `NORMAL`.

        PRD 3.4: "On success `resolved_at` is stamped with the current instant, `escalation_state` is forced back to `NONE` regardless of where it stood, and the anchor circuit's chronic posture is re-evaluated; the incident's `version`, the circuit's `version` and the carrier's `version` each advance by 1."
        PRD 3.4: "From that count the circuit's `chronic_state` is chosen: three or more faults makes it `CHRONIC`, two makes it `CHRONIC_CANDIDATE`, fewer than two returns it to `NORMAL`."

        Design: Corner/state_machines/corner_incident_resolve_stamps_and_counts_first_fault
        """
        state = build_pft_single_leg(
            api, "2026-08-19T00:00:00Z", alarm_raised_at="2026-08-19T00:00:00Z"
        )
        incident_id = state["incident_id"]

        advance_clock(api, "2026-08-19T00:30:00Z")
        clear_alarm(api, state["alarm_id"], "2026-08-19T00:30:00Z")
        walk_incident_to_mitigated(api, incident_id)

        advance_clock(api, "2026-08-19T01:00:00Z")
        resolved = resolve_incident(
            api,
            incident_id,
            resolution_note="carrier confirmed a cleaned connector",
            user_id=SHIFT_LEAD_USER_ID,
        )

        assert_incident_classification(
            resolved, response_state="RESOLVED", escalation_state="NONE"
        )
        assert_instant(
            resolved["resolved_at"], stamped("2026-08-19", "01:00"), "resolved_at"
        )

        circuit = read_circuit(api, state["circuit_id"])
        assert_circuit_posture(circuit, fault_count_period=1, chronic_state="NORMAL")
        assert_instant(
            circuit["last_incident_at"],
            stamped("2026-08-19", "00:00"),
            "circuit.last_incident_at",
        )
        assert_carrier_ledger(read_carrier(api, state["carrier_id"]), chronic_circuit_count=0)

    def test_third_resolved_fault_in_the_window_makes_the_circuit_chronic(self, api):
        """Two faults are a candidate; the third promotes the circuit and the carrier counter.

        PRD 3.4: "A cutoff instant is computed as the current clock instant minus 90 days, and the boundary is inclusive."
        PRD 3.4: "Entering `CHRONIC` raises the carrier's `chronic_circuit_count` by 1 and leaving it lowers that count by 1; more precisely, `chronic_circuit_count` is the number of that carrier's circuits whose `chronic_state` is `CHRONIC` or `REPLACEMENT_APPROVED`."

        Design: Corner/calculations/corner_three_resolved_incidents_in_window_mark_circuit_chronic
        """
        state = build_pft_single_leg(api, "2026-08-01T00:00:00Z")
        circuit_id = state["circuit_id"]

        first = run_fault_cycle(
            api, circuit_id, "2026-08-01T00:00:00Z", "2026-08-01T00:30:00Z", "fault 1 cleared"
        )
        assert_circuit_posture(
            read_circuit(api, circuit_id), fault_count_period=1, chronic_state="NORMAL"
        )

        second = run_fault_cycle(
            api, circuit_id, "2026-08-04T00:00:00Z", "2026-08-04T00:30:00Z", "fault 2 cleared"
        )
        assert_circuit_posture(
            read_circuit(api, circuit_id),
            fault_count_period=2,
            chronic_state="CHRONIC_CANDIDATE",
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), chronic_circuit_count=0
        )

        third = run_fault_cycle(
            api, circuit_id, "2026-08-07T00:00:00Z", "2026-08-07T00:30:00Z", "fault 3 cleared"
        )

        circuit = read_circuit(api, circuit_id)
        assert_circuit_posture(circuit, fault_count_period=3, chronic_state="CHRONIC")
        assert_instant(
            circuit["last_incident_at"],
            stamped("2026-08-07", "00:00"),
            "circuit.last_incident_at",
        )
        assert_carrier_ledger(
            read_carrier(api, state["carrier_id"]), chronic_circuit_count=1
        )

        for label, cycle in (("first", first), ("second", second), ("third", third)):
            incident = read_incident(api, cycle["incident_id"])
            assert_incident_classification(
                incident, response_state="RESOLVED", reopen_count=0
            )
            assert incident["resolved_at"] is not None, (
                f"the {label} fault is a resolved fault and carries a resolved_at"
            )
