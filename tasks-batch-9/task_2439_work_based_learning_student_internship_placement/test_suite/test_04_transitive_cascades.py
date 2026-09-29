"""Two cascades that run several hops away from the row that was written: a
substantiated critical incident reaches the worksite, the partner's score, the
placement and its open cycle; an agreement termination reaches the placements
underneath it, their cycles, and three separate committed-capacity counters.
"""

from test_helpers import (
    COORDINATOR,
    api_client,
    block_placement_with_critical_incident,
    get_success_data,
    read_agreement,
    read_cycle,
    read_incident,
    read_partner,
    read_placement,
    read_student,
    read_worksite,
    set_clock,
    setup_active_placement,
    validate_success,
)

FOUNDRY_ROW = {
    "legal_name": "Foundry Row Metalworks",
    "naics_code": "332312",
    "industry_sector": "MANUFACTURING",
}
NOOR_HADDAD = {"full_name": "Noor Haddad", "birth_date": "2009-03-18"}
NORTHLINE = {
    "legal_name": "Northline Logistics",
    "naics_code": "484121",
    "industry_sector": "PUBLIC_ADMINISTRATION",
}
IRIS_MWANGI = {"full_name": "Iris Mwangi", "birth_date": "2009-06-25"}

ONE_CYCLE_PLACEMENT = {
    "pay_classification": "PAID",
    "hourly_wage_cents": 1500,
    "stipend_total_cents": 0,
    "scheduled_weekly_hours": 12.00,
    "start_on": "2026-09-07",
    "end_on": "2026-12-18",
    "credit_target_credits": 0.50,
    "credit_award_mode": "HOURS_BASED",
    "required_evaluation_cycles": 1,
    "transportation_mode": "DISTRICT_BUS",
    "commute_round_trip_miles": 0.00,
}


def _read_supervisor(worksite_id, supervisor_id):
    rows = get_success_data(api_client.list_worksite_supervisors(worksite_id, COORDINATOR))
    return next(row for row in rows if row["id"] == supervisor_id)


def _placement_hit_by_a_substantiated_critical_incident():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="MFG-150",
        credit_hours_target=60.00,
        partner_overrides=FOUNDRY_ROW,
        worksite_overrides={"max_concurrent_students": 2},
        student_overrides=NOOR_HADDAD,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    set_clock("2026-09-15T08:00:00Z")
    incident = block_placement_with_critical_incident(
        scenario, "2026-09-14T13:20:00Z", injury_type="FRACTURE"
    )
    return scenario, incident


def _active_placement_under_a_terminated_agreement():
    scenario = setup_active_placement(
        clock="2026-09-07T08:00:00Z",
        course_code="LOG-140",
        credit_hours_target=60.00,
        partner_overrides=NORTHLINE,
        student_overrides=IRIS_MWANGI,
        permit_class="MINOR_16_17",
        placement_overrides=dict(ONE_CYCLE_PLACEMENT),
    )
    set_clock("2026-09-14T08:00:00Z")
    validate_success(
        api_client.terminate_agreement(
            scenario.agreement_id,
            {"termination_reason": "Employer closed the dispatch office for the school year"},
            COORDINATOR,
        )
    )
    return scenario


class TestCriticalIncidentCascade:
    def test_substantiation_fails_the_worksite_and_suspends_the_partner(self):
        """First, the worksite's `safety_status` is set to `FAILED` and its
        `safety_review_expires_on` to null. Subtract 50 points for each such report at
        `CRITICAL` severity. First, if any worksite of the partner has `safety_status` of
        `FAILED`, or if `safety_score` is below 50, the posture is `SUSPENDED`. A finding
        of `SUBSTANTIATED` moves the report `REPORTED → SUBSTANTIATED` and re-derives
        `osha_recordable`, which is true exactly when the report's `status` is
        `SUBSTANTIATED` or `CLOSED`, its `severity` is `MODERATE` or `CRITICAL`, and its
        `injury_type` is anything other than `NONE`.

        Design: Difficulty/transitive_cascade/critical_incident_finding_cascades_worksite_partner_placement_and_cycle
        """
        scenario, incident = _placement_hit_by_a_substantiated_critical_incident()

        stored = read_incident(incident["id"])
        assert stored["status"] == "SUBSTANTIATED"
        assert stored["osha_recordable"] is True

        worksite = read_worksite(scenario.worksite_id)
        assert worksite["safety_status"] == "FAILED"
        assert worksite["safety_review_expires_on"] is None

        partner = read_partner(scenario.partner_id)
        assert partner["substantiated_critical_count"] == 1
        assert partner["safety_score"] == 50
        assert partner["posture"] == "SUSPENDED"

    def test_the_cascade_blocks_the_placement_and_suspends_its_open_cycle(self):
        """Third, every `Placement` at that worksite whose `lifecycle_status` is
        `PROPOSED` or `ACTIVE` has its `compliance_status` moved to `BLOCKED`. Fourth,
        every `EvaluationCycle` of those placements whose `cycle_status` is `OPEN` or
        `PARTIAL` moves to `SUSPENDED`, preserving both of its dimension values so it can
        resume later.

        Design: Difficulty/transitive_cascade/critical_incident_finding_cascades_worksite_partner_placement_and_cycle
        """
        scenario, _incident = _placement_hit_by_a_substantiated_critical_incident()

        placement = read_placement(scenario.placement_id)
        assert placement["compliance_status"] == "BLOCKED"
        assert placement["lifecycle_status"] == "ACTIVE"

        cycle = read_cycle(scenario.placement_id, 1)
        assert cycle["cycle_status"] == "SUSPENDED"


class TestAgreementTerminationCascade:
    def test_termination_walks_down_to_the_placement_and_its_open_cycle(self):
        """Every `Placement` under the agreement whose `lifecycle_status` is `PROPOSED` or
        `ACTIVE` moves to `TERMINATED`; for each such placement the host worksite's
        `slots_committed` and the named supervisor's `active_student_load` are each
        decremented by 1; and every `EvaluationCycle` of those placements whose
        `cycle_status` is `OPEN` or `PARTIAL` moves to `CANCELLED`, permanently excluded
        from the placement's `closed_cycle_count`.

        Design: Difficulty/transitive_cascade/agreement_termination_cascades_to_placements_then_evaluation_cycles
        """
        scenario = _active_placement_under_a_terminated_agreement()

        assert read_agreement(scenario.agreement_id)["status"] == "TERMINATED"
        assert read_placement(scenario.placement_id)["lifecycle_status"] == "TERMINATED"
        assert read_cycle(scenario.placement_id, 1)["cycle_status"] == "CANCELLED"

    def test_termination_releases_the_worksite_supervisor_and_student_counters(self):
        """`Worksite.slots_committed` counts the worksite's placements whose
        `lifecycle_status` is `PROPOSED` or `ACTIVE`. Cascades in this domain run several
        hops deep, and every hop is a real mutation: the affected row's `updated_at` is
        refreshed and its `version` increases by 1, exactly as if it had been written
        directly.

        Design: Difficulty/transitive_cascade/agreement_termination_cascades_to_placements_then_evaluation_cycles
        """
        scenario = _active_placement_under_a_terminated_agreement()

        assert read_worksite(scenario.worksite_id)["slots_committed"] == 0
        assert _read_supervisor(scenario.worksite_id, scenario.supervisor_id)[
            "active_student_load"
        ] == 0
        assert read_student(scenario.student_id)["active_placement_count"] == 0
