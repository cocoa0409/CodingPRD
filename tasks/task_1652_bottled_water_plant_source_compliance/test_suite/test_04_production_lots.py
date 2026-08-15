"""Production lot lifecycle: reservation, overproduction, release gates,
segregation of duties, rework loop, line windows, and label eligibility."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_lot_in_qa_hold,
    create_lot_on_line,
    create_permit,
    create_plant,
    create_production_lot_payload,
    create_released_lot,
    create_treatment_run,
    create_validated_run,
    get_success_data,
    record_result_payload,
    setup_line_with_preforms,
    setup_released_lot_scenario,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import (
    PLANT_ADMIN, COMPLIANCE_OFFICER, PL1, QA1, find_finished_product_test,
)


def _line_with_stock_and_run(plant, accepted=1000, validate_run=True,
                             permit_overrides=None):
    """Plant fixture: SPRING permit, stocked line, one run (VALIDATED if asked)."""
    permit = create_permit(plant["id"], permit_number=f"SP-{plant['name']}",
                           **(permit_overrides or {}))
    line, _ = setup_line_with_preforms(plant["id"], accepted_units=accepted)
    if validate_run:
        run = create_validated_run(plant["id"], permit["id"])
    else:
        run = create_treatment_run(plant["id"], permit["id"])
    return permit, line, run


class TestLotReleaseGates:
    def test_release_blocked_while_run_not_validated(self, api):
        """PRD §3.6: "the lot's treatment run must be `VALIDATED`, otherwise
        `ERR_TREATMENT_NOT_VALIDATED` (HTTP 409)".

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_validated_treatment_run
        """
        plant = create_plant("Plant CE1")
        permit, line, run = _line_with_stock_and_run(plant, accepted=2000,
                                                     validate_run=False)
        lot_qa, fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=500, produced_units=500,
        )
        validate_success(api.record_lab_result(
            fptest["id"], record_result_payload(result="PASS"), QA1
        ))

        resp = api.release_production_lot(lot_qa["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_TREATMENT_NOT_VALIDATED)

    def test_release_succeeds_once_run_validated(self, api):
        """PRD §3.6: "the lot's treatment run must be `VALIDATED`, otherwise
        `ERR_TREATMENT_NOT_VALIDATED` (HTTP 409), and a `FINISHED_PRODUCT`
        test for the lot must exist in `COMPLETED_PASS` ... A successful
        release stamps `released_by_user_id` and moves the lot to `RELEASED`."

        Design: Difficulty/cross_entity_state_dependency/lot_release_requires_validated_treatment_run
        """
        plant = create_plant("Plant CE1")
        permit, line, run = _line_with_stock_and_run(plant, accepted=2000,
                                                     validate_run=False)
        lot_qa, fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=500, produced_units=500,
        )
        validate_success(api.record_lab_result(
            fptest["id"], record_result_payload(result="PASS"), QA1
        ))
        # Drive the run to VALIDATED, leaving the lot itself untouched.
        validate_success(api.start_treatment_run(run["id"], PL1))
        validate_success(api.record_run_parameters(
            run["id"],
            {"uv_dose_mj_cm2": 40.0, "ozone_ct_mg_min_l": 1.6,
             "turbidity_ntu": 0.3, "micro_pore_micron": 0.2},
            PL1,
        ))
        validate_success(api.validate_treatment_run(run["id"], QA1))

        released = validate_success(api.release_production_lot(lot_qa["id"], QA1))
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "qa-1"

    def test_release_without_passed_product_test_rejected(self, api):
        """PRD §3.6: "a `FINISHED_PRODUCT` test for the lot must exist in
        `COMPLETED_PASS`, otherwise `ERR_PRODUCT_TEST_NOT_PASSED` (HTTP 409)."

        Design: Corner/state_machines/release_without_passed_product_test_rejected
        """
        plant = create_plant("Plant SM32")
        permit, line, run = _line_with_stock_and_run(plant, accepted=500)
        lot_qa, fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=100, produced_units=100,
        )
        validate_success(api.record_lab_result(
            fptest["id"], record_result_payload(result="FAIL"), QA1
        ))

        resp = api.release_production_lot(lot_qa["id"], QA1)
        validate_error(resp, ApiErrorId.ERR_PRODUCT_TEST_NOT_PASSED)
        lot_now = validate_success(api.get_production_lot(lot_qa["id"], QA1))
        assert lot_now["status"] == "QA_HOLD"

    def test_release_sod_same_user_rejected(self, api):
        """PRD §2.10: "A production lot may not be released by the operator
        who completed it: release compares `X-User-ID` against the lot's
        `completed_by_user_id` and rejects a match with the same error."

        Design: Corner/state_machines/release_sod_same_user_rejected
        """
        plant = create_plant("Plant SM18")
        permit, line, run = _line_with_stock_and_run(plant, accepted=2000)
        lot_qa, fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=400, produced_units=400,
        )
        assert lot_qa["completed_by_user_id"] == "pl-1"
        validate_success(api.record_lab_result(
            fptest["id"], record_result_payload(result="PASS"), QA1
        ))

        # ProductionLead is allowed on the endpoint, but pl-1 completed it.
        resp = api.release_production_lot(lot_qa["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        released = validate_success(api.release_production_lot(lot_qa["id"], QA1))
        assert released["status"] == "RELEASED"
        assert released["released_by_user_id"] == "qa-1"


class TestLotReworkLoop:
    def test_rework_loop_reenters_qa_hold_and_counts_rejections(self, api):
        """PRD §3.6: "a `QAOfficer` may reject the lot from `QA_HOLD` into
        `REWORK`, incrementing `rework_count` by 1; a `ProductionLead` then
        returns a `REWORK` lot to `QA_HOLD` for a fresh review, where the
        release gates apply again against any passed finished-product test on
        the lot."

        Design: Difficulty/non_linear_state_machine/lot_rework_loop_reentry_release
        """
        plant = create_plant("Plant NL2")
        permit, line, run = _line_with_stock_and_run(plant, accepted=5000)
        lot_qa, _fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=800, produced_units=800,
        )
        r1 = validate_success(api.reject_production_lot(lot_qa["id"], QA1))
        assert r1["rework_count"] == 1
        back1 = validate_success(api.rework_complete_production_lot(lot_qa["id"], PL1))
        assert back1["status"] == "QA_HOLD"

        r2 = validate_success(api.reject_production_lot(lot_qa["id"], QA1))
        assert r2["rework_count"] == 2
        assert r2["status"] == "REWORK"
        back2 = validate_success(api.rework_complete_production_lot(lot_qa["id"], PL1))
        assert back2["status"] == "QA_HOLD"

    def test_reworked_lot_still_reaches_release(self, api):
        """PRD §3.6: "a `ProductionLead` then returns a `REWORK` lot to
        `QA_HOLD` for a fresh review, where the release gates apply again
        against any passed finished-product test on the lot."

        Design: Difficulty/non_linear_state_machine/lot_rework_loop_reentry_release
        """
        plant = create_plant("Plant NL2")
        permit, line, run = _line_with_stock_and_run(plant, accepted=5000)
        lot_qa, _fptest = create_lot_in_qa_hold(
            plant["id"], permit["id"], line["id"], run["id"],
            planned_units=800, produced_units=800,
        )
        validate_success(api.reject_production_lot(lot_qa["id"], QA1))
        validate_success(api.rework_complete_production_lot(lot_qa["id"], PL1))
        validate_success(api.reject_production_lot(lot_qa["id"], QA1))
        validate_success(api.rework_complete_production_lot(lot_qa["id"], PL1))

        fptest = find_finished_product_test(lot_qa["id"])
        validate_success(api.record_lab_result(
            fptest["id"],
            record_result_payload(result="PASS", collected_at="2026-08-04T15:00:00Z"),
            QA1,
        ))
        released = validate_success(api.release_production_lot(lot_qa["id"], QA1))
        assert released["status"] == "RELEASED"


class TestLotCompletionBoundaries:
    def test_lot_complete_overproduction_boundary(self, api):
        """PRD §3.6: "Overproduction is impossible to book: a count strictly
        above `planned_units` fails with `ERR_OVERPRODUCTION` (HTTP 422), and
        a count of zero or less fails with `ERR_INVALID_REQUEST`."

        Design: Corner/state_machines/lot_complete_overproduction_boundary
        """
        plant = create_plant("Plant SM14")
        permit, line, run = _line_with_stock_and_run(plant, accepted=1000,
                                                     validate_run=False)
        lot = create_lot_on_line(line["id"], run["id"], planned_units=500)
        validate_success(api.start_production_lot(lot["id"], PL1))

        resp = api.complete_production_lot(lot["id"], {"produced_units": 501}, PL1)
        validate_error(resp, ApiErrorId.ERR_OVERPRODUCTION)

        completed = validate_success(api.complete_production_lot(
            lot["id"], {"produced_units": 500}, PL1
        ))
        assert completed["status"] == "QA_HOLD"
        assert completed["produced_units"] == 500


class TestLotStartPostureGate:
    def test_lot_start_blocked_in_breach_posture(self, api):
        """PRD §3.6: "Starting production moves a `PLANNED` lot to
        `IN_PRODUCTION` and is refused while the plant's `compliance_posture`
        is `BREACH` — `ERR_POSTURE_BREACH` (HTTP 409)".

        Design: Corner/state_machines/lot_start_blocked_in_breach_posture
        """
        plant = create_plant("Plant SM15")
        perm_a = create_permit(plant["id"], permit_number="SP-SM15A")
        perm_b = create_permit(plant["id"], permit_number="SP-SM15B")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=1000)
        run = create_validated_run(plant["id"], perm_b["id"])
        lot = create_lot_on_line(line["id"], run["id"], planned_units=100)

        # Suspension of any permit forces the plant posture to BREACH (§3.1).
        validate_success(api.suspend_permit(perm_a["id"], COMPLIANCE_OFFICER))

        resp = api.start_production_lot(lot["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_POSTURE_BREACH)

        validate_success(api.reinstate_permit(perm_a["id"], COMPLIANCE_OFFICER))
        started = validate_success(api.start_production_lot(lot["id"], PL1))
        assert started["status"] == "IN_PRODUCTION"


class TestLotCancelRules:
    def test_lot_cancel_from_in_production_rejected(self, api):
        """PRD §3.6: "Cancellation by a `ProductionLead` is admitted only
        from `PLANNED`" — from any other state the state-admissibility rung
        yields `ERR_INVALID_STATE` (§2.7 rung 5).

        Design: Corner/state_machines/lot_cancel_from_in_production_rejected
        """
        plant = create_plant("Plant SM16")
        permit, line, run = _line_with_stock_and_run(plant, accepted=1000,
                                                     validate_run=False)
        lot = create_lot_on_line(line["id"], run["id"], planned_units=300)
        validate_success(api.start_production_lot(lot["id"], PL1))

        resp = api.cancel_production_lot(lot["id"], PL1)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_now["preform_reserved_units"] == 300, (
            "no compensating release on a rejected cancel"
        )


class TestLotRunAssignment:
    def test_lot_run_double_assignment_rejected(self, api):
        """PRD §3.6: "The run must not already be referenced by another lot
        that is not `CANCELLED` — treatment runs are assigned one-to-one among
        live lots — otherwise `ERR_RUN_ALREADY_ASSIGNED` (HTTP 409)."

        Design: Corner/state_machines/lot_run_double_assignment_rejected
        """
        plant = create_plant("Plant SM17")
        permit, line, run1 = _line_with_stock_and_run(plant, accepted=1000,
                                                      validate_run=False)
        run2 = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-03T08:00:00Z", scheduled_end="2026-08-03T10:00:00Z",
        )
        create_lot_on_line(
            line["id"], run1["id"], planned_units=100,
            scheduled_start="2026-08-04T08:00:00Z", scheduled_end="2026-08-04T10:00:00Z",
        )
        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        payload = create_production_lot_payload(
            treatment_run_id=run1["id"], planned_units=100,
            scheduled_start="2026-08-04T10:00:00Z", scheduled_end="2026-08-04T12:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp = api.create_production_lot(line["id"], payload, PL1)
        validate_error(resp, ApiErrorId.ERR_RUN_ALREADY_ASSIGNED)

    def test_lot_run_cross_plant_rejected(self, api):
        """PRD §3.6: "The referenced run must exist and must belong to the
        same plant as the line, otherwise `ERR_CROSS_PLANT_REFERENCE` (HTTP
        409)."

        Design: Corner/entities/lot_run_cross_plant_rejected
        """
        plant_a = create_plant("Plant EN11A")
        create_permit(plant_a["id"], permit_number="SP-EN11A")
        line_a, _ = setup_line_with_preforms(plant_a["id"], accepted_units=1000)

        plant_b = create_plant("Plant EN11B")
        perm_b = create_permit(plant_b["id"], permit_number="SP-EN11B")
        run_b = create_treatment_run(plant_b["id"], perm_b["id"])

        line_now = validate_success(api.get_bottling_line(line_a["id"], PL1))
        payload = create_production_lot_payload(
            treatment_run_id=run_b["id"], planned_units=100,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp = api.create_production_lot(line_a["id"], payload, PL1)
        validate_error(resp, ApiErrorId.ERR_CROSS_PLANT_REFERENCE)


class TestLineWindowsAndStock:
    def test_line_window_adjacency_allowed(self, api):
        """PRD §3.6: "The lot's window is a half-open interval — two lots on
        one line whose windows merely touch, one ending exactly when the other
        begins, do not conflict".

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency_vs_overlap
        """
        plant = create_plant("Plant TO1")
        permit, line, run1 = _line_with_stock_and_run(plant, accepted=1000,
                                                      validate_run=False)
        run2 = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-10T08:00:00Z", scheduled_end="2026-08-10T10:00:00Z",
        )
        lot1 = create_lot_on_line(
            line["id"], run1["id"], planned_units=100,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        # Adjacent: starts exactly when lot1 ends.
        lot2 = create_lot_on_line(
            line["id"], run2["id"], planned_units=100,
            scheduled_start="2026-08-10T12:00:00Z", scheduled_end="2026-08-10T14:00:00Z",
        )
        assert lot2["status"] == "PLANNED"

        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_now["preform_reserved_units"] == 200

    def test_line_window_overlap_rejected(self, api):
        """PRD §3.6: "any overlap with another lot not in `CANCELLED` status
        on the same line fails with `ERR_LINE_WINDOW_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/line_window_half_open_adjacency_vs_overlap
        """
        plant = create_plant("Plant TO1")
        permit, line, run1 = _line_with_stock_and_run(plant, accepted=1000,
                                                      validate_run=False)
        run2 = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-10T08:00:00Z", scheduled_end="2026-08-10T10:00:00Z",
        )
        run3 = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        create_lot_on_line(
            line["id"], run1["id"], planned_units=100,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        create_lot_on_line(
            line["id"], run2["id"], planned_units=100,
            scheduled_start="2026-08-10T12:00:00Z", scheduled_end="2026-08-10T14:00:00Z",
        )
        # Straddles lot2's start: 11:00-13:00 overlaps 12:00-14:00.
        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        payload = create_production_lot_payload(
            treatment_run_id=run3["id"], planned_units=100,
            scheduled_start="2026-08-10T11:00:00Z", scheduled_end="2026-08-10T13:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp = api.create_production_lot(line["id"], payload, PL1)
        validate_error(resp, ApiErrorId.ERR_LINE_WINDOW_CONFLICT)

    def test_lot_preform_insufficient_boundary(self, api):
        """PRD §3.6: "`planned_units` must not exceed the line's
        `preform_free_units`, otherwise `ERR_PREFORM_INSUFFICIENT` (HTTP 409)."

        Design: Corner/validations/lot_preform_insufficient_boundary
        """
        plant = create_plant("Plant VA10")
        permit, line, run1 = _line_with_stock_and_run(plant, accepted=500,
                                                      validate_run=False)
        run2 = create_treatment_run(
            plant["id"], permit["id"],
            scheduled_start="2026-08-03T08:00:00Z", scheduled_end="2026-08-03T10:00:00Z",
        )
        line_now = validate_success(api.get_bottling_line(line["id"], PL1))
        payload = create_production_lot_payload(
            treatment_run_id=run1["id"], planned_units=501,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp = api.create_production_lot(line["id"], payload, PL1)
        validate_error(resp, ApiErrorId.ERR_PREFORM_INSUFFICIENT)

        # planned_units == preform_free_units exactly is allowed.
        lot = create_lot_on_line(
            line["id"], run2["id"], planned_units=500,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
        )
        assert lot["status"] == "PLANNED"
        line_after = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_after["preform_free_units"] == 0


class TestLabelEligibility:
    def test_label_classification_mismatch_both_directions_rejected(self, api):
        """PRD §3.6: "a `SPRING` label requires the run's source permit to be
        classified `SPRING`, and a `PURIFIED` label requires that source not
        to be `SPRING`; a mismatch fails with
        `ERR_LABEL_CLASSIFICATION_MISMATCH` (HTTP 409)."

        Design: Corner/validations/label_classification_mismatch_both_directions_rejected
        """
        plant = create_plant("Plant VA9")
        perm_s = create_permit(plant["id"], permit_number="SP-VA9",
                               source_classification="SPRING")
        perm_w = create_permit(plant["id"], permit_number="WL-VA9",
                               source_classification="WELL")
        line, _ = setup_line_with_preforms(plant["id"], accepted_units=2000)
        run_s = create_treatment_run(
            plant["id"], perm_s["id"],
            scheduled_start="2026-08-03T06:00:00Z", scheduled_end="2026-08-03T08:00:00Z",
        )
        run_w = create_treatment_run(
            plant["id"], perm_w["id"],
            scheduled_start="2026-08-03T08:00:00Z", scheduled_end="2026-08-03T10:00:00Z",
        )
        line_now = validate_success(api.get_bottling_line(line["id"], PL1))

        # PURIFIED on a SPRING-sourced run.
        p1 = create_production_lot_payload(
            treatment_run_id=run_s["id"], label_classification="PURIFIED",
            planned_units=100,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp1 = api.create_production_lot(line["id"], p1, PL1)
        validate_error(resp1, ApiErrorId.ERR_LABEL_CLASSIFICATION_MISMATCH)

        # SPRING on a WELL-sourced run.
        p2 = create_production_lot_payload(
            treatment_run_id=run_w["id"], label_classification="SPRING",
            planned_units=100,
            scheduled_start="2026-08-10T10:00:00Z", scheduled_end="2026-08-10T12:00:00Z",
            expected_line_version=line_now["version"],
        )
        resp2 = api.create_production_lot(line["id"], p2, PL1)
        validate_error(resp2, ApiErrorId.ERR_LABEL_CLASSIFICATION_MISMATCH)

        line_after = validate_success(api.get_bottling_line(line["id"], PL1))
        assert line_after["preform_reserved_units"] == 0, (
            "no partial reservation on either rejection"
        )
