"""The global compliance checkpoint: its four marking passes, the batch count
report, overdue-to-late-completion recovery, and the posture band boundaries."""
from test_helpers import (
    CO,
    MLEAD,
    PSC,
    ApiErrorId,
    api_client,
    complete_inspection_payload,
    create_contractor,
    create_equipment,
    create_hot_work_permit_payload,
    create_reported_incident,
    create_suspected_leak,
    get_facility,
    make_contractor_rep_headers,
    qualify_contractor,
    run_checkpoint,
    schedule_inspection,
    set_clock,
    setup_facility_system_operator,
    setup_facility_with_operator,
    setup_facility_with_system,
    setup_issued_permit,
    validate_error,
    validate_success,
)


class TestCheckpointBatch:

    def test_checkpoint_batch_effects_count(self):
        """PRD section 2.5: "Separately, a `ComplianceOfficer` may run the
        global compliance checkpoint, a sweep against the current logical clock
        with four marking passes and one recomputation pass."
        PRD section 2.5: "The sweep closes by recomputing every facility's
        `overdue_inspection_count`, `expired_training_count`, `posture_score`,
        and `compliance_posture`, and its response reports the size of each
        marking pass as `inspections_marked_overdue`, `contractors_expired`,
        `permits_expired`, and `notifications_marked_overdue`."

        Design: Corner/complexity_layers/checkpoint_batch_effects_count
        """
        set_clock("2026-08-01T00:00:00Z", CO)
        facility, system, employee, op_headers = setup_facility_system_operator()
        equipment = create_equipment(system["id"], tag_number="V-101",
                                     inspection_interval_days=180,
                                     inspection_method="FIXED")
        schedule_inspection(equipment["id"], "2026-08-05T00:00:00Z")
        contractor = create_contractor()
        qualify_contractor(contractor["id"], "2026-08-15T00:00:00Z")
        rep_headers = make_contractor_rep_headers(contractor["id"])
        permit = validate_success(
            api_client.create_hot_work_permit(
                create_hot_work_permit_payload(
                    facility["id"], system["id"], contractor["id"],
                    valid_from="2026-08-10T08:00:00Z",
                    valid_until="2026-08-10T12:00:00Z"),
                rep_headers),
            expected_status=201)
        validate_success(api_client.issue_permit(permit["id"], MLEAD), 200)
        leak = create_suspected_leak(system["id"], op_headers,
                                     estimated_release_lbs=120.0,
                                     source_description="PRV lift")
        validate_success(api_client.confirm_leak(
            leak["id"], {"final_release_lbs": 120.0}, CO), 200)

        set_clock("2026-08-20T00:00:00Z", CO)
        report = run_checkpoint()
        assert report["inspections_marked_overdue"] == 1
        assert report["contractors_expired"] == 1
        assert report["permits_expired"] == 1
        assert report["notifications_marked_overdue"] == 1

        facility_after = get_facility(facility["id"], headers=CO)
        assert facility_after["overdue_inspection_count"] == 1
        # 5 for the overdue inspection + 3 for the open leak auto-incident
        assert facility_after["posture_score"] == 8
        assert facility_after["compliance_posture"] == "DEGRADED"


class TestCheckpointMarkingPasses:

    def test_contractor_expires_via_checkpoint(self):
        """PRD section 2.5: "Second, every contractor standing `QUALIFIED`
        whose `qualified_until` lies strictly before the current time is marked
        `EXPIRED`."
        PRD section 3.7: "Independently, the checkpoint expires any `QUALIFIED`
        contractor whose `qualified_until` has passed."

        Design: Corner/state_machines/contractor_expires_via_checkpoint
        """
        contractor = create_contractor()
        qualify_contractor(contractor["id"], "2026-08-15T00:00:00Z")
        set_clock("2026-08-16T00:00:00Z", CO)
        report = run_checkpoint()
        assert report["contractors_expired"] == 1
        after = validate_success(api_client.get_contractor(contractor["id"], MLEAD),
                                 expected_status=200)
        assert after["qualification_status"] == "EXPIRED"

    def test_permit_expires_via_checkpoint(self):
        """PRD section 2.5: "Third, every hot work permit standing `ISSUED`
        whose `valid_until` has been reached is marked `EXPIRED`."
        PRD section 3.7: "`CLOSED`, `VOIDED`, and `EXPIRED` are terminal."

        Design: Corner/state_machines/permit_expires_via_checkpoint
        """
        facility, system, contractor, permit, rep_headers = setup_issued_permit(
            valid_from="2026-08-10T08:00:00Z", valid_until="2026-08-10T12:00:00Z")
        set_clock("2026-08-20T00:00:00Z", CO)
        report = run_checkpoint()
        assert report["permits_expired"] == 1
        after = validate_success(api_client.get_hot_work_permit(permit["id"], MLEAD),
                                 expected_status=200)
        assert after["status"] == "EXPIRED"
        # EXPIRED is terminal: start is not a declared transition from it
        resp = api_client.start_permit(permit["id"], rep_headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE, expected_status=409)


class TestOverdueAndLateCompletion:

    def test_inspection_overdue_then_late_completion(self):
        """PRD section 2.5: "First, every inspection still `SCHEDULED` whose
        `due_at` lies strictly before the current time is marked `OVERDUE`, and
        the affected equipment's integrity status and the owning facility's
        posture are recomputed."
        PRD section 3.3: "The platform stamps `completed_at` from the logical
        clock and sets `completed_late` to true only when the inspection stood
        `OVERDUE` at completion; an on-cycle completion from `SCHEDULED`
        records `completed_late` false."
        PRD section 3.3: "And when the completed inspection had stood
        `OVERDUE`, the facility's `overdue_inspection_count` decrements and its
        posture recomputes."

        Design: Corner/state_machines/inspection_overdue_then_late_completion
        """
        facility, system = setup_facility_with_system()
        equipment = create_equipment(system["id"], tag_number="V-101",
                                     inspection_interval_days=180,
                                     inspection_method="FIXED")
        inspection = schedule_inspection(equipment["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        report = run_checkpoint()
        assert report["inspections_marked_overdue"] == 1

        during = get_facility(facility["id"], headers=CO)
        assert during["overdue_inspection_count"] == 1
        # 5 points for one overdue inspection: DEGRADED band
        assert during["posture_score"] == 5
        assert during["compliance_posture"] == "DEGRADED"

        done = validate_success(
            api_client.complete_inspection(
                inspection["id"],
                complete_inspection_payload(result="PASS",
                                            findings="no anomalies"),
                MLEAD),
            expected_status=200)
        assert done["status"] == "COMPLETED"
        assert done["completed_late"] is True

        after = get_facility(facility["id"], headers=CO)
        assert after["overdue_inspection_count"] == 0
        assert after["compliance_posture"] == "COMPLIANT"


class TestPostureBandBoundaries:

    def test_posture_score_exactly_ten_noncompliant(self):
        """PRD section 2.7: "From these counts the platform computes the
        `posture_score`: five points for every overdue inspection, three for
        every open incident, and two for every expired training record, summed
        as integers with no rounding. The `compliance_posture` then bands the
        score — `COMPLIANT` when the score is zero, `DEGRADED` when it sits
        between one and nine inclusive, and `NONCOMPLIANT` once it reaches
        ten."

        Design: Corner/calculations/posture_score_exactly_ten_noncompliant
        """
        facility, system = setup_facility_with_system()
        eq1 = create_equipment(system["id"], tag_number="V-101",
                               inspection_interval_days=180,
                               inspection_method="FIXED")
        eq2 = create_equipment(system["id"], tag_number="V-102",
                               inspection_interval_days=180,
                               inspection_method="FIXED")
        schedule_inspection(eq1["id"], "2026-08-05T00:00:00Z")
        schedule_inspection(eq2["id"], "2026-08-05T00:00:00Z")
        set_clock("2026-08-10T00:00:00Z")
        run_checkpoint()
        facility_after = get_facility(facility["id"], headers=CO)
        assert facility_after["overdue_inspection_count"] == 2
        assert facility_after["posture_score"] == 10
        # score exactly 10 reaches the NONCOMPLIANT band (>= boundary)
        assert facility_after["compliance_posture"] == "NONCOMPLIANT"

    def test_posture_score_nine_stays_degraded(self):
        """PRD section 2.7: "From these counts the platform computes the
        `posture_score`: five points for every overdue inspection, three for
        every open incident, and two for every expired training record, summed
        as integers with no rounding. The `compliance_posture` then bands the
        score — `COMPLIANT` when the score is zero, `DEGRADED` when it sits
        between one and nine inclusive, and `NONCOMPLIANT` once it reaches
        ten."

        Design: Corner/calculations/posture_score_nine_stays_degraded
        """
        facility, reporter_emp, op_headers = setup_facility_with_operator(
            operator_name="Rita Reporter")
        for i in (1, 2, 3):
            incident = create_reported_incident(
                facility["id"], reporter_emp["id"], severity="RECORDABLE",
                description=f"incident number {i}")
            assert incident["status"] == "REPORTED"
        facility_after = get_facility(facility["id"], headers=CO)
        assert facility_after["open_incident_count"] == 3
        # 3 open incidents x 3 points = 9: one below the NONCOMPLIANT floor
        assert facility_after["posture_score"] == 9
        assert facility_after["compliance_posture"] == "DEGRADED"


class TestCheckpointRbac:

    def test_pscoordinator_cannot_run_checkpoint(self):
        """PRD section 2.1: "`ComplianceOfficer` is the compliance officer,
        owning incident investigation assignment and closure, corrective-action
        creation, the compliance audit cycle, leak confirmation and regulatory
        notification, and the global checkpoint run."
        PRD section 2.1: "A request whose role is not permitted for the target
        endpoint, or that fails an entity-backed ownership check, is rejected
        with `ERR_FORBIDDEN` (403)."

        Design: Corner/rbac/pscoordinator_cannot_run_checkpoint
        """
        resp = api_client.run_checkpoint(PSC)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN, expected_status=403)
