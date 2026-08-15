"""Backfill & erosion control, final inspection, lot closure, and the
version/consistency claims."""
import pytest

from test_helpers import (
    api_client, validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_backfill_plan_payload, create_final_inspection_payload,
    create_structure_survey_payload, complete_survey_payload,
    make_structural_engineer_headers,
    create_project, create_and_complete_survey,
    setup_debris_clearance, setup_final_review,
)

ADMIN = TEST_USERS["contractor_admin_headers"]
SUPERVISOR = TEST_USERS["site_supervisor_headers"]
SURVEYOR = TEST_USERS["surveyor_headers"]
INSPECTOR = TEST_USERS["municipal_inspector_headers"]


class TestBackfillErosion:
    def test_erosion_provisional_vs_final_divergence(self):
        """PRD §3.9: "Approving moves the plan to `APPROVED` and computes the
        `provisional_coverage_ratio`: the `planned_protected_area_sqft` divided
        by the `design_disturbed_area_sqft`, rounded half-up to four decimal
        places. This provisional figure is informational only — it never gates
        anything."
        PRD §3.9: "The `final_coverage_ratio` is the measured protected area
        divided by the measured disturbed area, rounded half-up to four decimal
        places; verification passes only when that ratio reaches 0.9000, and
        falls to `ERR_EROSION_COVERAGE_INSUFFICIENT` below it."

        Design: Difficulty/dual_variant_calc/erosion_provisional_vs_final_divergence
        """
        project = create_project(name="Erosion Lot", address="2 Oak St", lot_area_sqft=30000)
        plan = get_success_data(
            api_client.create_backfill_plan(
                project["id"], create_backfill_plan_payload(), SUPERVISOR
            )
        )
        approved = get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "APPROVE"}, make_structural_engineer_headers("er-e-1")
            )
        )
        # Provisional variant: 9500/10000 -> 0.95, would pass the 0.9000 bar.
        assert approved["provisional_coverage_ratio"] == 0.95
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 96.0}, SUPERVISOR
            )
        )
        # Final variant: round_half_up(8976/10200, 4) == 0.88 < 0.9000 -> rejected.
        resp = api_client.transition_backfill_plan(
            plan["id"],
            {"action": "VERIFY_EROSION",
             "measured_protected_area_sqft": 8976,
             "measured_disturbed_area_sqft": 10200},
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_EROSION_COVERAGE_INSUFFICIENT)
        listed = get_success_data(api_client.list_backfill_plans(project["id"], SUPERVISOR))
        assert listed[0]["status"] == "COMPACTION_VERIFIED"

    def test_final_coverage_exactly_0_9_passes(self):
        """PRD §3.9: "The `final_coverage_ratio` is the measured protected area
        divided by the measured disturbed area, rounded half-up to four decimal
        places; verification passes only when that ratio reaches 0.9000, and
        falls to `ERR_EROSION_COVERAGE_INSUFFICIENT` below it."
        PRD §2.5: "final erosion coverage must reach 0.9000"

        Design: Difficulty/dual_variant_calc/erosion_provisional_vs_final_divergence
        """
        project = create_project(name="ErosionOk", address="2B Oak St", lot_area_sqft=30000)
        plan = get_success_data(
            api_client.create_backfill_plan(project["id"], create_backfill_plan_payload(), SUPERVISOR)
        )
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "APPROVE"}, make_structural_engineer_headers("er2-e-1")
            )
        )
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 96.0}, SUPERVISOR
            )
        )
        ok = get_success_data(
            api_client.transition_backfill_plan(
                plan["id"],
                {"action": "VERIFY_EROSION",
                 "measured_protected_area_sqft": 9180,
                 "measured_disturbed_area_sqft": 10200},
                INSPECTOR,
            )
        )
        assert ok["status"] == "EROSION_VERIFIED"
        assert ok["final_coverage_ratio"] == 0.9


class TestCompaction:
    def _approved_plan(self, name, address):
        project = create_project(name=name, address=address, lot_area_sqft=20000)
        plan = get_success_data(
            api_client.create_backfill_plan(
                project["id"],
                create_backfill_plan_payload(design_disturbed_area_sqft=8000,
                                             planned_protected_area_sqft=7600,
                                             fill_volume_cu_yd=300,
                                             required_compaction_pct=95.0),
                SUPERVISOR,
            )
        )
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "APPROVE"}, make_structural_engineer_headers("cmp-a-1")
            )
        )
        return plan

    def test_compaction_exactly_required_passes(self):
        """PRD §3.9: "a `SiteSupervisor` records the measured `compaction_pct`,
        which must be at least the plan's `required_compaction_pct` — a reading
        below specification is rejected with `ERR_COMPACTION_BELOW_SPEC` —
        moving the plan to `COMPACTION_VERIFIED` and storing the reading as
        `compaction_pct_achieved`."

        Design: Difficulty/boundary_precision_check/compaction_exactly_required_passes
        """
        plan_a = self._approved_plan("Compact A", "51 Elm St")
        plan_b = self._approved_plan("Compact B", "53 Elm St")
        resp = api_client.transition_backfill_plan(
            plan_a["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 94.99}, SUPERVISOR
        )
        validate_error(resp, ApiErrorId.ERR_COMPACTION_BELOW_SPEC)
        ok = get_success_data(
            api_client.transition_backfill_plan(
                plan_b["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 95.0}, SUPERVISOR
            )
        )
        assert ok["status"] == "COMPACTION_VERIFIED"
        assert ok["compaction_pct_achieved"] == 95.0

    def test_compaction_below_spec_keeps_plan_approved(self):
        """PRD §3.9: "a `SiteSupervisor` records the measured `compaction_pct`,
        which must be at least the plan's `required_compaction_pct` — a reading
        below specification is rejected with `ERR_COMPACTION_BELOW_SPEC`"

        Design: Difficulty/boundary_precision_check/compaction_exactly_required_passes
        """
        plan = self._approved_plan("Compact C", "51B Elm St")
        resp = api_client.transition_backfill_plan(
            plan["id"], {"action": "RECORD_COMPACTION", "compaction_pct": 90.0}, SUPERVISOR
        )
        validate_error(resp, ApiErrorId.ERR_COMPACTION_BELOW_SPEC)
        listed = get_success_data(api_client.list_backfill_plans(plan["project_id"], SUPERVISOR))
        assert listed[0]["status"] == "APPROVED"


class TestBackfillPhaseGate:
    def test_start_backfill_without_approved_plan_rejected(self):
        """PRD §3.8: "Starting backfill moves `DEBRIS_CLEARANCE` to
        `BACKFILL_PHASE` and requires that at least one backfill plan of the
        project has reached `APPROVED` or beyond (`COMPACTION_VERIFIED`,
        `EROSION_VERIFIED`, or `COMPLETE`), else `ERR_BACKFILL_NOT_APPROVED`."

        Design: Corner/validations/start_backfill_without_approved_plan_rejected
        """
        ctx = setup_debris_clearance(name="NoAppr", address="99 Pine St")
        pid = ctx["project"]["id"]
        plan = get_success_data(
            api_client.create_backfill_plan(pid, create_backfill_plan_payload(), SUPERVISOR)
        )
        resp = api_client.transition_project(pid, {"action": "START_BACKFILL"}, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_BACKFILL_NOT_APPROVED)
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "APPROVE"}, make_structural_engineer_headers("nb-be-1")
            )
        )
        ok = get_success_data(
            api_client.transition_project(pid, {"action": "START_BACKFILL"}, SUPERVISOR)
        )
        assert ok["status"] == "BACKFILL_PHASE"


class TestFinalInspectionAndClosure:
    def test_final_pass_referential_beats_fiscal(self):
        """PRD §2.9: "10. **Referential freshness** — ... a complete backfill
        plan exists for inspection passage (`ERR_BACKFILL_INCOMPLETE`)"
        PRD §2.9: "12. **Closure compliance** — the project's achieved diversion
        rate meets its required rate (`ERR_DIVERSION_BELOW_REQUIREMENT`)."
        PRD §3.9: "Recording a `PASSED` outcome requires the project to be in
        `FINAL_REVIEW` (else `ERR_INVALID_STATE`), at least one backfill plan of
        the project to stand `COMPLETE` (else `ERR_BACKFILL_INCOMPLETE`), and the
        project's achieved `diversion_rate` to be at least its
        `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`)."

        Design: Difficulty/priority_pair_validation_conflict/final_pass_referential_beats_fiscal
        """
        # Backfill plan APPROVED but not COMPLETE; diversion 0.4 < 0.5.
        ctx = setup_debris_clearance(name="Prio 3", address="35 Elm St",
                                     tickets=[(10.0, 4.0)], required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        plan = get_success_data(
            api_client.create_backfill_plan(pid, create_backfill_plan_payload(), SUPERVISOR)
        )
        get_success_data(
            api_client.transition_backfill_plan(
                plan["id"], {"action": "APPROVE"}, make_structural_engineer_headers("p3-be-1")
            )
        )
        get_success_data(api_client.transition_project(pid, {"action": "START_BACKFILL"}, SUPERVISOR))
        get_success_data(
            api_client.transition_project(pid, {"action": "SUBMIT_FINAL_REVIEW"}, SUPERVISOR)
        )
        fi = get_success_data(
            api_client.create_final_inspection(pid, create_final_inspection_payload(), INSPECTOR)
        )
        resp = api_client.transition_final_inspection(fi["id"], {"action": "PASS"}, INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_BACKFILL_INCOMPLETE)
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["diversion_rate"] == 0.4, "fiscal violation also present but loses"
        assert project["status"] == "FINAL_REVIEW"

    def test_pass_fails_state_legality_when_inspection_failed(self):
        """PRD §3.9: "Recording a `PASSED` outcome requires the project to be in
        `FINAL_REVIEW` (else `ERR_INVALID_STATE`), at least one backfill plan of
        the project to stand `COMPLETE` (else `ERR_BACKFILL_INCOMPLETE`), and the
        project's achieved `diversion_rate` to be at least its
        `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`)."
        PRD §2.9: "5. **State legality** — the entity's state machine allows the
        requested transition from its current state"

        Design: Difficulty/priority_pair_validation_conflict/final_pass_referential_beats_fiscal
        """
        # Backfill COMPLETE and diversion at the boundary: the referential and
        # fiscal legs are clean, but PASS from FAILED is a state-machine
        # violation and surfaces as ERR_INVALID_STATE.
        ctx = setup_final_review(name="Prio3B", address="35B Elm St",
                                 tickets=[(8.0, 4.0), (4.0, 2.0)],
                                 required_diversion_rate=0.5)
        fi_id = ctx["inspection"]["id"]
        get_success_data(
            api_client.transition_final_inspection(fi_id, {"action": "FAIL"}, INSPECTOR)
        )
        resp = api_client.transition_final_inspection(fi_id, {"action": "PASS"}, INSPECTOR)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        project = get_success_data(api_client.get_project(ctx["project"]["id"], SUPERVISOR))
        assert project["status"] == "FINAL_REVIEW"

    def test_error_diversion_below_requirement_triggered(self):
        """PRD §3.9: "Recording a `PASSED` outcome requires the project to be in
        `FINAL_REVIEW` (else `ERR_INVALID_STATE`), at least one backfill plan of
        the project to stand `COMPLETE` (else `ERR_BACKFILL_INCOMPLETE`), and the
        project's achieved `diversion_rate` to be at least its
        `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`)."

        Design: Corner/errors/error_diversion_below_requirement_triggered
        """
        ctx = setup_final_review(name="LowDiv", address="84 Pine St",
                                 tickets=[(10.0, 4.0)], required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["diversion_rate"] == 0.4
        resp = api_client.transition_final_inspection(
            ctx["inspection"]["id"], {"action": "PASS"}, INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_DIVERSION_BELOW_REQUIREMENT)
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["status"] == "FINAL_REVIEW"

    def test_diversion_rate_exactly_required_passes_closure(self):
        """PRD §3.9: "the project's achieved `diversion_rate` to be at least its
        `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`)."
        PRD §3.9: "the project closes automatically: `FINAL_REVIEW` to `CLOSED`,
        the project's terminal state, its `version` incrementing by 1."
        PRD §3.8: "The `diversion_tier` reads `GOLD` when the rate reaches
        0.7500, `SILVER` when it reaches 0.5000, and `STANDARD` otherwise."

        Design: Difficulty/boundary_precision_check/diversion_rate_exactly_required_passes_closure
        """
        ctx = setup_final_review(name="Boundary Div", address="45 Elm St",
                                 tickets=[(8.0, 4.0), (4.0, 2.0)],
                                 required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        passed = get_success_data(
            api_client.transition_final_inspection(
                ctx["inspection"]["id"], {"action": "PASS"}, INSPECTOR
            )
        )
        assert passed["status"] == "PASSED"
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["diversion_rate"] == 0.5  # 6.0 / 12.0 exactly at the boundary
        assert project["diversion_tier"] == "SILVER"
        assert project["status"] == "CLOSED"

    def test_diversion_one_step_below_required_fails(self):
        """PRD §3.9: "the project's achieved `diversion_rate` to be at least its
        `required_diversion_rate` (else `ERR_DIVERSION_BELOW_REQUIREMENT`)."

        Design: Difficulty/boundary_precision_check/diversion_rate_exactly_required_passes_closure
        """
        # 5.9 / 12.0 = 0.491666.. -> 0.4917 < 0.5, one step below the boundary.
        ctx = setup_final_review(name="DivBelow", address="45B Elm St",
                                 tickets=[(8.0, 4.0), (4.0, 1.9)],
                                 required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        resp = api_client.transition_final_inspection(
            ctx["inspection"]["id"], {"action": "PASS"}, INSPECTOR
        )
        validate_error(resp, ApiErrorId.ERR_DIVERSION_BELOW_REQUIREMENT)

    def test_inspection_fail_reschedule_cycle_then_pass_closes_lot(self):
        """PRD §3.9: "Recording a `FAILED` outcome instead moves the inspection
        to `FAILED`, increments its `attempt_count` by 1, and leaves the project
        in `FINAL_REVIEW`; a failed inspection can be rescheduled back to
        `SCHEDULED` with a new `scheduled_date` in the payload — omitting it
        draws `ERR_VALIDATION`."
        PRD §3.9: "The passed inspection stamps `passed_at` from the logical
        clock as it moves from `SCHEDULED` to `PASSED`, and the project closes
        automatically: `FINAL_REVIEW` to `CLOSED`, the project's terminal state,
        its `version` incrementing by 1."

        Design: Corner/state_machines/inspection_fail_reschedule_cycle_then_pass_closes_lot
        """
        ctx = setup_final_review(name="Reinspect", address="30 Pine St",
                                 tickets=[(8.0, 4.0), (4.0, 2.0)],
                                 required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        fi_id = ctx["inspection"]["id"]
        failed = get_success_data(
            api_client.transition_final_inspection(
                fi_id, {"action": "FAIL", "inspector_note": "debris in NE corner"}, INSPECTOR
            )
        )
        assert failed["status"] == "FAILED"
        assert failed["attempt_count"] == 1
        rescheduled = get_success_data(
            api_client.transition_final_inspection(
                fi_id, {"action": "RESCHEDULE", "scheduled_date": "2026-08-27"}, INSPECTOR
            )
        )
        assert rescheduled["status"] == "SCHEDULED"
        assert rescheduled["scheduled_date"] == "2026-08-27"
        get_success_data(
            api_client.transition_final_inspection(fi_id, {"action": "PASS"}, INSPECTOR)
        )
        project = get_success_data(api_client.get_project(pid, SUPERVISOR))
        assert project["status"] == "CLOSED"

    def test_error_inspection_outstanding_blocks_second_schedule(self):
        """PRD §3.9: "only one inspection may be outstanding at a time —
        scheduling while another inspection of the project stands `SCHEDULED` is
        rejected with `ERR_INSPECTION_OUTSTANDING`."

        Design: Corner/errors/error_inspection_outstanding_blocks_second_schedule
        """
        ctx = setup_final_review(name="Outstanding", address="94 Pine St",
                                 tickets=[(8.0, 4.0), (4.0, 2.0)],
                                 required_diversion_rate=0.5)
        pid = ctx["project"]["id"]
        resp = api_client.create_final_inspection(
            pid,
            create_final_inspection_payload(inspection_type="EROSION_CLOSEOUT",
                                            scheduled_date="2026-08-21"),
            INSPECTOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSPECTION_OUTSTANDING)
        get_success_data(
            api_client.transition_final_inspection(
                ctx["inspection"]["id"], {"action": "FAIL"}, INSPECTOR
            )
        )
        ok = api_client.create_final_inspection(
            pid,
            create_final_inspection_payload(inspection_type="EROSION_CLOSEOUT",
                                            scheduled_date="2026-08-28"),
            INSPECTOR,
        )
        data = validate_success(ok, expected_status=201)
        assert isinstance(data["id"], str)


class TestVersionAndConsistency:
    def test_version_increments_on_every_mutation(self):
        """PRD §2.4: "The `version` is an integer that starts at 1 at creation
        and increments by 1 on every mutation of the resource, including
        system-driven mutations such as cascades and counter reconciliation."
        PRD §3.1: "The very first survey created under a `DRAFT` project
        automatically advances the project to `SURVEY_PHASE`, incrementing the
        project's `version` by 1."
        PRD §3.1: "the project bubbles up to `PRECONDITIONS_PENDING`, its
        `version` incrementing by 1."

        Design: Corner/cross_cutting_layers/version_increments_on_every_mutation
        """
        project = create_project(name="Ver", address="17 Role St", lot_area_sqft=12000)
        assert project["version"] == 1
        survey = get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        assert survey["version"] == 1
        v1 = get_success_data(api_client.get_project(project["id"], SUPERVISOR))["version"]
        assert v1 == 2
        completed = get_success_data(
            api_client.transition_structure_survey(survey["id"], complete_survey_payload(), SURVEYOR)
        )
        assert completed["version"] == 2, "survey version bumps independently"
        v2 = get_success_data(api_client.get_project(project["id"], SUPERVISOR))["version"]
        assert v2 == 3

    def test_immediate_consistency_read_yields_write_effects(self):
        """PRD §3.1: "The very first survey created under a `DRAFT` project
        automatically advances the project to `SURVEY_PHASE`, incrementing the
        project's `version` by 1."
        PRD §2.7: "Every such cascade mutates the affected project —
        incrementing its `version` by 1 and refreshing `updated_at` — alongside
        the primary mutation that caused it."

        Design: Corner/consistency_model/immediate_consistency_read_yields_write_effects
        """
        project = create_project(name="Cons", address="19 Role St", lot_area_sqft=12000)
        get_success_data(
            api_client.create_structure_survey(
                project["id"], create_structure_survey_payload(), SURVEYOR
            )
        )
        after = get_success_data(api_client.get_project(project["id"], SUPERVISOR))
        assert after["status"] == "SURVEY_PHASE"
        assert after["version"] == 2
