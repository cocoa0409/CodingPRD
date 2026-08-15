"""Compliance-hold cascades and the compliance gate on clinical clearance.

Covers PRD §3.4 (hold machinery on finalize) and §3.5 (clinical clearance
compliance gate, order creation patient-state gate).
"""
import pytest

from test_helpers import (
    create_order_for_plan,
    dispense_component,
    finalize_compliant_report,
    finalize_non_compliant_report,
    get_patient,
    get_plans_for,
    get_rental_contract_for,
    run_daily_sweep,
    set_clock,
    setup_therapy_patient,
    validate_error,
    validate_success,
)


class TestAdherenceFinalizeCascade:
    """Finalize -> Patient hold -> (plans suspended, rental paused): depth 3."""

    def test_finalize_below_threshold_holds_patient_and_suspends_plans(self, api):
        """PRD §3.4: "When a finalized report's `adherence_pct_final` falls
        below the payer threshold, a patient in `ACTIVE_THERAPY` moves to
        `NON_COMPLIANT_HOLD`: every supply plan in `ACTIVE` for that patient is
        suspended into `SUSPENDED_NON_COMPLIANCE`"

        Design: Difficulty/transitive_cascade/adherence_finalize_to_rental_pause_depth3
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()

        plans_before = get_plans_for(patient["id"])
        for plan in plans_before.values():
            assert plan["plan_status"] == "ACTIVE"

        finalize_non_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-09-30",
                                      nights_reported=30, compliant_nights=8)
        held = get_patient(patient["id"])
        assert held["patient_status"] == "NON_COMPLIANT_HOLD"

        plans_after = get_plans_for(patient["id"])
        for component, plan in plans_after.items():
            assert plan["plan_status"] == "SUSPENDED_NON_COMPLIANCE", (
                f"{component} plan should be SUSPENDED_NON_COMPLIANCE, got "
                f"{plan['plan_status']}")

    def test_finalize_below_threshold_pauses_billing_rental(self, api):
        """PRD §3.4: "and an active rental contract in `BILLING` pauses into
        `PAUSED_NON_COMPLIANCE` — months do not accrue while paused."

        Design: Difficulty/transitive_cascade/adherence_finalize_to_rental_pause_depth3
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        contract = ctx["rental_contract"]
        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        contract = get_rental_contract_for(patient["id"])
        assert contract["billing_status"] == "BILLING"

        finalize_non_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-09-30",
                                      nights_reported=30, compliant_nights=8)
        paused = get_rental_contract_for(patient["id"])
        assert paused["billing_status"] == "PAUSED_NON_COMPLIANCE"
        assert paused["rental_months_billed"] == 0


class TestOrderCreationPatientGate:
    def test_order_create_blocked_while_patient_on_hold(
            self, api, intake_coordinator_headers):
        """PRD §3.5: "Creation runs its checks in a fixed order: the patient
        must be in `ACTIVE_THERAPY` (`ERR_PATIENT_NOT_IN_ACTIVE_THERAPY`)"

        Design: Difficulty/cross_entity_state_dependency/order_create_gated_by_patient_status
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        finalize_non_compliant_report(patient["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-08-30",
                                      nights_reported=30, compliant_nights=10)
        assert get_patient(patient["id"])["patient_status"] == "NON_COMPLIANT_HOLD"

        mask_plan = get_plans_for(patient["id"])["MASK"]
        res = api.create_resupply_order(
            {"patient_id": patient["id"],
             "component_supply_plan_id": mask_plan["id"],
             "requested_quantity": mask_plan["quantity_per_cycle"],
             "expected_patient_version": get_patient(patient["id"])["version"]},
            intake_coordinator_headers)
        validate_error(res, "ERR_PATIENT_NOT_IN_ACTIVE_THERAPY", expected_status=409)

    def test_order_create_allowed_once_compliance_restored(
            self, api, intake_coordinator_headers):
        """PRD §3.4: "When a later finalized report meets or exceeds the
        threshold, the patient returns from `NON_COMPLIANT_HOLD` to
        `ACTIVE_THERAPY`, the suspended plans resume to `ACTIVE`"

        Design: Difficulty/cross_entity_state_dependency/order_create_gated_by_patient_status
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]
        finalize_non_compliant_report(patient["id"], enrollment["id"],
                                      window_end_on="2026-08-30",
                                      nights_reported=30, compliant_nights=10)
        finalize_compliant_report(patient["id"], enrollment["id"],
                                  window_end_on="2026-09-15",
                                  nights_reported=30, compliant_nights=25)
        restored = get_patient(patient["id"])
        assert restored["patient_status"] == "ACTIVE_THERAPY"

        mask_plan = get_plans_for(patient["id"])["MASK"]
        assert mask_plan["plan_status"] == "ACTIVE"
        order = create_order_for_plan(patient["id"], mask_plan)
        assert order["auth_status"] == "PENDING_CLINICAL_CLEARANCE"


class TestComplianceGateOnClinicalClear:
    def test_compliance_gate_blocks_clinical_clear(
            self, api, respiratory_therapist_headers):
        """PRD §3.5: "A patient whose `is_compliance_current` is false and who
        does have a finalized report fails with `ERR_COMPLIANCE_NOT_CURRENT`."

        Design: Corner/validations/compliance_gate_blocks_clinical_clear
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]

        # First fill dispensed under the first-fill grace (no finalized report).
        dispense_component(patient["id"], "MASK")

        # Flip compliance off and on again so the patient returns to
        # ACTIVE_THERAPY with a finalized (compliant) report on record.
        finalize_non_compliant_report(patient["id"], enrollment["id"],
                                      window_end_on="2026-08-30",
                                      nights_reported=30, compliant_nights=10)
        finalize_compliant_report(patient["id"], enrollment["id"],
                                  window_end_on="2026-09-15",
                                  nights_reported=30, compliant_nights=28)

        # Past the mask cadence (2026-08-01 + 90 = 2026-10-30): a second order
        # can be created while the patient is ACTIVE and compliance-current.
        set_clock("2026-11-01T00:00:00Z")
        mask_plan = get_plans_for(patient["id"])["MASK"]
        order = create_order_for_plan(patient["id"], mask_plan)

        # A fresh non-compliant finalization flips is_compliance_current false.
        finalize_non_compliant_report(patient["id"], enrollment["id"],
                                      window_end_on="2026-11-15",
                                      nights_reported=30, compliant_nights=5)
        assert get_patient(patient["id"])["is_compliance_current"] is False

        res = api.clinical_clear_order(order["id"], respiratory_therapist_headers)
        validate_error(res, "ERR_COMPLIANCE_NOT_CURRENT", expected_status=422)
