"""Treatment-run validation branching, wash-verdict thresholds, and the lab
testing cadence (due flips, overdue grace, auto-scheduling)."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_treatment_run,
    create_permit,
    create_plant,
    create_source_raw_test,
    create_treatment_run,
    create_wash_batch,
    get_success_data,
    passing_parameters_payload,
    record_result_payload,
    run_compliance,
    set_clock,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, COMPLIANCE_OFFICER, PL1, QA1, QA2, SL1,
)


def _start_and_record(api, plant_id, permit_id, parameters, **run_overrides):
    """Create a run, start it, record the given parameters as pl-1. Returns run."""
    run = create_treatment_run(plant_id, permit_id, **run_overrides)
    validate_success(api.start_treatment_run(run["id"], PL1))
    validate_success(api.record_run_parameters(run["id"], parameters, PL1))
    return run


class TestTreatmentVerdictBranching:
    def test_spring_run_at_exact_thresholds_validates(self, api):
        """PRD §3.3: "a `turbidity_ntu` strictly above 0.3 fails, so exactly
        0.3 passes. Next, a `uv_dose_mj_cm2` strictly below 40.0 fails, so
        exactly 40.0 passes. Next, an `ozone_ct_mg_min_l` strictly below 1.6
        fails. Finally ... for a `SPRING` source, a `micro_pore_micron`
        strictly above 0.2 fails".

        Design: Difficulty/combinatorial_formula/treatment_verdict_branching_thresholds
        """
        plant = create_plant("Plant CF1")
        perm_s = create_permit(plant["id"], permit_number="SP-CF1",
                               source_classification="SPRING")
        r1 = _start_and_record(api, plant["id"], perm_s["id"],
                               passing_parameters_payload())
        validated = validate_success(api.validate_treatment_run(r1["id"], QA1))
        assert validated["status"] == "VALIDATED"
        assert validated["validation_round"] == 1

    def test_spring_run_fails_on_micro_pore_but_well_run_passes_on_ro(self, api):
        """PRD §3.3: "for a `SPRING` source, a `micro_pore_micron` strictly
        above 0.2 fails, so the microfiltration step governs spring water; for
        any other classification, an `ro_rejection_pct` that is absent or
        strictly below 95.0 fails, so reverse-osmosis rejection governs
        purified water."

        Design: Difficulty/combinatorial_formula/treatment_verdict_branching_thresholds
        """
        plant = create_plant("Plant CF1")
        perm_s = create_permit(plant["id"], permit_number="SP-CF1",
                               source_classification="SPRING")
        perm_w = create_permit(plant["id"], permit_number="WL-CF1",
                               source_classification="WELL")

        # Spring run with micro_pore 0.21 -> FAIL on the spring branch.
        r2 = _start_and_record(
            api, plant["id"], perm_s["id"],
            passing_parameters_payload(micro_pore_micron=0.21),
            scheduled_start="2026-08-03T08:00:00Z",
            scheduled_end="2026-08-03T10:00:00Z",
        )
        failed = validate_success(api.validate_treatment_run(r2["id"], QA1))
        assert failed["status"] == "FAILED"
        assert failed["validation_round"] == 1

        # Well run with the same 0.21 micron reading but RO 96.0 -> PASS:
        # the non-spring branch never consults micro_pore_micron.
        r3 = _start_and_record(
            api, plant["id"], perm_w["id"],
            passing_parameters_payload(micro_pore_micron=0.21, ro_rejection_pct=96.0),
            scheduled_start="2026-08-03T10:00:00Z",
            scheduled_end="2026-08-03T12:00:00Z",
        )
        validated = validate_success(api.validate_treatment_run(r3["id"], QA1))
        assert validated["status"] == "VALIDATED"
        assert validated["validation_round"] == 1


class TestTreatmentRunLifecycle:
    def test_treatment_run_validated_terminal_rejects_start_and_reprocess(self, api):
        """PRD §3.3: "`VALIDATED` is terminal" and §2.7 rung 5: "the target
        resource must be in a state that admits the operation, per the state
        machines of §3 (`ERR_INVALID_STATE` ...)".

        Design: Corner/state_machines/treatment_run_validated_terminal_rejects_start_and_reprocess
        """
        plant = create_plant("Plant SM9")
        permit = create_permit(plant["id"], permit_number="SP-SM9")
        run = _start_and_record(api, plant["id"], permit["id"],
                                passing_parameters_payload())
        validate_success(api.validate_treatment_run(run["id"], QA1))

        err1 = api.start_treatment_run(run["id"], PL1)
        from test_helpers import validate_error
        validate_error(err1, ApiErrorId.ERR_INVALID_STATE)
        err2 = api.reprocess_treatment_run(run["id"], PL1)
        validate_error(err2, ApiErrorId.ERR_INVALID_STATE)

    def test_treatment_run_reprocess_cycle_second_round_validates(self, api):
        """PRD §3.3: "a `FAILED` run is not — a `ProductionLead` may move it
        to `REPROCESSING` and start it again" and "`validation_round`
        increments by 1 on every validation call".

        Design: Corner/state_machines/treatment_run_reprocess_cycle_second_round_validates
        """
        plant = create_plant("Plant SM10")
        permit = create_permit(plant["id"], permit_number="SP-SM10")
        run = _start_and_record(
            api, plant["id"], permit["id"],
            passing_parameters_payload(uv_dose_mj_cm2=30.0),
        )
        failed = validate_success(api.validate_treatment_run(run["id"], QA1))
        assert failed["status"] == "FAILED"
        assert failed["validation_round"] == 1

        reprocessing = validate_success(api.reprocess_treatment_run(run["id"], PL1))
        assert reprocessing["status"] == "REPROCESSING"
        in_progress = validate_success(api.start_treatment_run(run["id"], PL1))
        assert in_progress["status"] == "IN_PROGRESS"
        validate_success(api.record_run_parameters(
            run["id"], passing_parameters_payload(uv_dose_mj_cm2=42.0), PL1
        ))
        validated = validate_success(api.validate_treatment_run(run["id"], QA1))
        assert validated["status"] == "VALIDATED"
        assert validated["validation_round"] == 2

    def test_treatment_run_start_on_suspended_permit_rejected(self, api):
        """PRD §3.3: "Starting a run ... is admitted from `SCHEDULED` and
        again from `REPROCESSING`, and in both cases the run's source permit
        must be `ACTIVE`, otherwise `ERR_PERMIT_NOT_ACTIVE`".

        Design: Corner/state_machines/treatment_run_start_on_suspended_permit_rejected
        """
        plant = create_plant("Plant SM11")
        permit = create_permit(plant["id"], permit_number="SP-SM11")
        run = _start_and_record(
            api, plant["id"], permit["id"],
            passing_parameters_payload(uv_dose_mj_cm2=30.0),
        )
        validate_success(api.validate_treatment_run(run["id"], QA1))  # -> FAILED
        validate_success(api.suspend_permit(permit["id"], COMPLIANCE_OFFICER))

        reprocessing = validate_success(api.reprocess_treatment_run(run["id"], PL1))
        assert reprocessing["status"] == "REPROCESSING"

        from test_helpers import validate_error
        resp = api.start_treatment_run(run["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_PERMIT_NOT_ACTIVE)

        validate_success(api.reinstate_permit(permit["id"], COMPLIANCE_OFFICER))
        started = validate_success(api.start_treatment_run(run["id"], PL1))
        assert started["status"] == "IN_PROGRESS"

    def test_validate_sod_same_user_rejected(self, api):
        """PRD §2.10: "A treatment run may not be validated by the operator
        who recorded its parameters: validation compares `X-User-ID` against
        the run's `parameters_recorded_by_user_id` and rejects a match with
        `ERR_SEGREGATION_OF_DUTIES` (HTTP 409)."

        Design: Corner/state_machines/validate_sod_same_user_rejected
        """
        from test_helpers import validate_error
        plant = create_plant("Plant SM19")
        permit = create_permit(plant["id"], permit_number="SP-SM19")
        run = create_treatment_run(plant["id"], permit["id"])
        validate_success(api.start_treatment_run(run["id"], PL1))
        # record-parameters is shared with QAOfficer; qa-1 records here.
        validate_success(api.record_run_parameters(
            run["id"], passing_parameters_payload(), QA1
        ))

        resp = api.validate_treatment_run(run["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        validated = validate_success(api.validate_treatment_run(run["id"], QA2))
        assert validated["status"] == "VALIDATED"
        assert validated["validated_by_user_id"] == "qa-2"

    def test_treatment_run_cancel_from_scheduled_then_locked(self, api):
        """PRD §3.3: "Cancellation by a `ProductionLead` is admitted from
        `SCHEDULED` and from `FAILED`, moving the run to the terminal
        `CANCELLED` state."

        Design: Corner/endpoints/treatment_run_cancel_from_scheduled_then_locked
        """
        from test_helpers import validate_error
        plant = create_plant("Plant EP6")
        permit = create_permit(plant["id"], permit_number="SP-EP6")
        run = create_treatment_run(plant["id"], permit["id"])

        cancelled = validate_success(api.cancel_treatment_run(run["id"], PL1))
        assert cancelled["status"] == "CANCELLED"

        resp = api.cancel_treatment_run(run["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestWashVerdictThresholds:
    def test_wash_verdict_threshold_boundaries(self, api):
        """PRD §3.8: "the batch passes when the rinse temperature is at least
        71.1 degrees Celsius and the sanitizer concentration is at least 50.0
        parts per million, with parameters compared exactly as recorded and
        values at the thresholds passing; anything else fails."

        Design: Corner/calculations/wash_verdict_threshold_boundaries
        """
        plant = create_plant("Plant CA2")
        w1 = create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T09:00:00Z", scheduled_end="2026-08-06T10:00:00Z",
        )
        w2 = create_wash_batch(
            plant["id"], washer_unit="WASHER_B",
            scheduled_start="2026-08-06T09:00:00Z", scheduled_end="2026-08-06T10:00:00Z",
        )
        w3 = create_wash_batch(
            plant["id"], washer_unit="WASHER_A",
            scheduled_start="2026-08-06T10:30:00Z", scheduled_end="2026-08-06T11:30:00Z",
        )
        validate_success(api.start_wash_batch(w1["id"], SL1))
        validate_success(api.start_wash_batch(w2["id"], SL1))

        s1 = validate_success(api.complete_wash_batch(
            w1["id"], {"rinse_temp_c": 71.1, "sanitizer_ppm": 50.0}, SL1
        ))
        s2 = validate_success(api.complete_wash_batch(
            w2["id"], {"rinse_temp_c": 71.09, "sanitizer_ppm": 50.0}, SL1
        ))
        validate_success(api.start_wash_batch(w3["id"], SL1))
        s3 = validate_success(api.complete_wash_batch(
            w3["id"], {"rinse_temp_c": 71.1, "sanitizer_ppm": 49.9}, SL1
        ))
        assert s1["status"] == "PASSED", "both parameters exactly at threshold pass"
        assert s2["status"] == "FAILED", "71.09 < 71.1"
        assert s3["status"] == "FAILED", "49.9 < 50.0"


class TestLabTestingCadence:
    def test_lab_test_due_window_flip(self, api):
        """PRD §3.4: "Compliance runs move a `SCHEDULED` test to `DUE` when
        its `due_date` is no earlier than the current logical date and no more
        than three days away — a test exactly three days out flips, as does
        one due today".

        Design: Corner/state_machines/lab_test_due_window_flip
        """
        plant = create_plant("Plant SM12")
        permit = create_permit(plant["id"], permit_number="SP-SM12")
        t1 = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-05")
        t2 = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-10")

        set_clock("2026-08-03T00:00:00Z")
        summary = run_compliance(plant["id"])
        assert summary["tests_flipped"] == 1

        s1 = validate_success(api.get_lab_test(t1["id"], QA1))
        s2 = validate_success(api.get_lab_test(t2["id"], QA1))
        assert s1["status"] == "DUE"
        assert s2["status"] == "SCHEDULED"

    def test_lab_test_overdue_grace_boundary_suspends_at_eight_days(self, api):
        """PRD §3.4: "when a `SOURCE_RAW` test remains overdue by more than
        seven days — the current logical date more than seven days past its
        `due_date` — the subject permit is suspended with `suspension_reason`
        `TEST_OVERDUE`" and PRD §3.2: "It reads `BREACH` when ... any
        raw-source lab test of the plant is `OVERDUE`."

        Design: Corner/state_machines/lab_test_overdue_grace_boundary_suspends_at_eight_days
        """
        plant = create_plant("Plant SM13")
        permit = create_permit(plant["id"], permit_number="SP-SM13")
        test = create_source_raw_test(plant["id"], permit["id"], due_date="2026-08-01")

        # 2026-08-08 is exactly 7 days overdue: not "more than seven".
        set_clock("2026-08-08T00:00:00Z")
        summary1 = run_compliance(plant["id"])
        assert summary1["permits_suspended"] == 0
        assert summary1["posture"] == "BREACH", (
            "an OVERDUE SOURCE_RAW test alone already forces BREACH"
        )
        p1 = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert p1["status"] == "ACTIVE"

        # 2026-08-09 is 8 days overdue: the grace is crossed.
        set_clock("2026-08-09T00:00:00Z")
        summary2 = run_compliance(plant["id"])
        assert summary2["permits_suspended"] == 1
        p2 = validate_success(api.get_permit(permit["id"], COMPLIANCE_OFFICER))
        assert p2["status"] == "SUSPENDED"
        assert p2["suspension_reason"] == "TEST_OVERDUE"
        ts = validate_success(api.get_lab_test(test["id"], QA1))
        assert ts["status"] == "OVERDUE"

    def test_compliance_run_auto_source_test_scheduling(self, api):
        """PRD §3.4: "the auto-scheduler keeps exactly one upcoming
        raw-source test per `ACTIVE` permit, creating one with `origin` `AUTO`
        and a `due_date` seven days out whenever no `SOURCE_RAW` test for that
        permit exists in `SCHEDULED` or `DUE` status with a `due_date` on or
        after the current date."

        Design: Corner/calculations/compliance_run_auto_source_test_scheduling
        """
        plant = create_plant("Plant CA6")
        permit = create_permit(plant["id"], permit_number="SP-CA6")

        summary1 = run_compliance(plant["id"])
        assert summary1["tests_auto_created"] == 1
        assert summary1["ops_run_index"] == 1

        page, meta = validate_paginated(api.list_lab_tests(
            QA1, params={"subject_permit_id": permit["id"], "test_type": "SOURCE_RAW"}
        ))
        assert meta["total_count"] == 1
        assert page[0]["due_date"] == "2026-08-08"
        assert page[0]["origin"] == "AUTO"
        assert page[0]["status"] == "SCHEDULED"

        summary2 = run_compliance(plant["id"])
        assert summary2["tests_auto_created"] == 0
        assert summary2["ops_run_index"] == 2

    def test_testing_due_schedule_type_defaults(self, api):
        """PRD §3.4: "The `due_date` is an optional override; when omitted it
        defaults relative to the current logical date — seven days out for
        `SOURCE_RAW` (weekly source monitoring), two days out for
        `FINISHED_PRODUCT` (per-lot release testing), and one day out for
        `BOTTLE_SANITATION` (per-batch sanitation micro)."

        Design: Corner/calculations/testing_due_schedule_type_defaults
        """
        from test_helpers.fixtures import (
            setup_line_with_preforms, create_lot_on_line,
        )
        plant = create_plant("Plant CA5")
        permit = create_permit(plant["id"], permit_number="SP-CA5")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=500)
        run = create_treatment_run(plant["id"], permit["id"])
        lot = create_lot_on_line(line["id"], run["id"], planned_units=100)
        batch = create_wash_batch(plant["id"])

        t1 = validate_success(api.create_lab_test(
            plant["id"], {"test_type": "SOURCE_RAW", "subject_permit_id": permit["id"]}, QA1
        ), expected_status=201)
        t2 = validate_success(api.create_lab_test(
            plant["id"], {"test_type": "FINISHED_PRODUCT", "subject_lot_id": lot["id"]}, QA1
        ), expected_status=201)
        t3 = validate_success(api.create_lab_test(
            plant["id"], {"test_type": "BOTTLE_SANITATION", "subject_wash_batch_id": batch["id"]}, QA1
        ), expected_status=201)
        # Clock at the startup default 2026-08-01 (§2.4).
        assert t1["due_date"] == "2026-08-08"
        assert t2["due_date"] == "2026-08-03"
        assert t3["due_date"] == "2026-08-02"

    def test_lab_test_subject_type_mismatch_rejected(self, api):
        """PRD §3.4: "exactly one subject foreign key must be supplied, and
        it must match the type ... A missing subject, an extra subject, or a
        subject of the wrong kind is rejected with
        `ERR_SUBJECT_TYPE_MISMATCH` (HTTP 409)".

        Design: Corner/validations/lab_test_subject_type_mismatch_rejected
        """
        from test_helpers import validate_error
        from test_helpers.fixtures import setup_line_with_preforms, create_lot_on_line
        plant = create_plant("Plant VA11")
        permit = create_permit(plant["id"], permit_number="SP-VA11")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=500)
        run = create_treatment_run(plant["id"], permit["id"])
        lot = create_lot_on_line(line["id"], run["id"], planned_units=100)

        # Wrong kind of subject for the declared type.
        resp1 = api.create_lab_test(
            plant["id"],
            {"test_type": "FINISHED_PRODUCT", "subject_permit_id": permit["id"]},
            QA1,
        )
        validate_error(resp1, ApiErrorId.ERR_SUBJECT_TYPE_MISMATCH)

        # An extra subject alongside the matching one.
        resp2 = api.create_lab_test(
            plant["id"],
            {"test_type": "SOURCE_RAW", "subject_permit_id": permit["id"],
             "subject_lot_id": lot["id"]},
            QA1,
        )
        validate_error(resp2, ApiErrorId.ERR_SUBJECT_TYPE_MISMATCH)
