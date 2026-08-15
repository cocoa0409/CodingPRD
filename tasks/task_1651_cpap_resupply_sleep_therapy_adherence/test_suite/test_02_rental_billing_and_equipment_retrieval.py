"""Rental contract lifecycle: setup seeding, sweep activation, monthly billing,
conversion to ownership, and discontinuation/retrieval terminal flows.

Covers PRD §3.3 (setup cascade), §3.7 (rental billing and conversion), and
§3.8 (discontinuation and equipment retrieval).
"""
import pytest

from test_helpers import (
    assert_component_supply_plan,
    assert_rental_contract,
    assert_retrieval_case,
    drive_retrieval_to_received,
    finalize_compliant_report,
    finalize_non_compliant_report,
    get_patient,
    get_plans_for,
    get_rental_contract_for,
    get_retrieval_case_for,
    initiate_discontinuation_for,
    run_daily_sweep,
    set_clock,
    setup_discontinuing_patient,
    setup_therapy_patient,
    validate_error,
    validate_success,
)


class TestSetupSeedingCascade:
    def test_complete_setup_creates_supply_plans_and_rental(
            self, api, ops_admin_headers):
        """PRD §3.3: "Four **component supply plans** are created for the
        patient — one each for `MASK`, `CUSHION`, `FILTER`, and `TUBING` — all
        in `ACTIVE` plan status, with `last_dispensed_on` and `next_eligible_on`
        null because nothing has been dispensed yet."

        Design: Corner/cross_cutting_layers/cascade_complete_setup_creates_supply_plans_and_rental
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        plans = ctx["plans"]
        assert set(plans.keys()) == {"MASK", "CUSHION", "FILTER", "TUBING"}
        for component, plan in plans.items():
            assert_component_supply_plan(plan)
            assert plan["plan_status"] == "ACTIVE", f"{component} plan not ACTIVE"
            assert plan["last_dispensed_on"] is None
            assert plan["next_eligible_on"] is None

    def test_complete_setup_creates_rental_contract_and_activates_patient(
            self, api, ops_admin_headers):
        """PRD §3.3: "If the enrollment's `acquisition_type` is `RENTAL`, a
        **rental contract** is created: `billing_status` starts `SCHEDULED`,
        `equipment_status` starts `WITH_PATIENT`, `rental_start_on` equals the
        enrollment's setup completion date, `rental_months_billed` starts at
        zero, the contract's `payer_policy_id` snapshots the patient's policy at
        creation, and the patient's `current_rental_contract_id` points at the
        new contract."

        Design: Corner/cross_cutting_layers/cascade_complete_setup_creates_supply_plans_and_rental
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        contract = ctx["rental_contract"]
        assert_rental_contract(contract)
        assert contract["billing_status"] == "SCHEDULED"
        assert contract["equipment_status"] == "WITH_PATIENT"
        assert contract["rental_start_on"] == "2026-08-01"
        assert contract["rental_months_billed"] == 0
        assert contract["payer_policy_id"] == ctx["policy"]["id"]
        patient = ctx["patient"]
        assert patient["patient_status"] == "ACTIVE_THERAPY"
        assert patient["therapy_started_on"] == "2026-08-01"
        assert patient["current_device_enrollment_id"] == ctx["enrollment"]["id"]
        assert patient["current_rental_contract_id"] == contract["id"]


class TestRentalSweepActivation:
    def test_rental_activation_only_at_first_monthly_anniversary(
            self, api, ops_admin_headers):
        """PRD §3.7: "Billing activation is automatic: when the daily sweep
        observes the current date reaching one calendar month after
        `rental_start_on` while the contract is still `SCHEDULED`, the contract
        moves to `BILLING`."

        Design: Corner/cross_cutting_layers/scheduled_action_rental_activation_via_sweep
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        contract = ctx["rental_contract"]
        assert contract["billing_status"] == "SCHEDULED"

        set_clock("2026-08-15T00:00:00Z")
        run_daily_sweep()
        mid = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        assert mid["billing_status"] == "SCHEDULED"

        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        after = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        assert after["billing_status"] == "BILLING"


class TestRentalBillingChecks:
    def test_bill_rental_before_period_due_rejected(
            self, api, billing_specialist_headers):
        """PRD §3.7: "Billing one month enforces three checks in a fixed order:
        the monthly anniversary must have arrived — the current date must be on
        or after `rental_start_on` plus `rental_months_billed` months plus one
        further month, inclusive (`ERR_RENTAL_PERIOD_NOT_DUE`)"

        Design: Corner/validations/rental_bill_before_period_due_rejected
        """
        ctx = setup_therapy_patient(acquisition_type="RENTAL")
        contract = ctx["rental_contract"]
        run_daily_sweep()  # at 2026-08-01: no activation (anniversary not reached)
        set_clock("2026-08-15T00:00:00Z")
        res = api.bill_rental_month(contract["id"], billing_specialist_headers)
        validate_error(res, "ERR_RENTAL_PERIOD_NOT_DUE", expected_status=409)


class TestRentalDualVariantAccrual:
    """Straight-line projection vs actual-usage accrual across a pause."""

    def _setup_paused_contract(self, api, billing_specialist_headers):
        """Drive a RENTAL contract to: 1 month billed, then PAUSED_NON_COMPLIANCE."""
        ctx = setup_therapy_patient(
            acquisition_type="RENTAL",
            payer_overrides={"rental_months_to_own": 3})
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]
        contract = ctx["rental_contract"]

        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        billed = validate_success(
            api.bill_rental_month(contract["id"], billing_specialist_headers))
        assert billed["rental_months_billed"] == 1

        # Non-compliant finalize (5/30 = 16.7 < 70) -> hold + pause.
        finalize_non_compliant_report(patient["id"], enrollment["id"],
                                      window_end_on="2026-09-10",
                                      nights_reported=30, compliant_nights=5)
        return ctx, contract

    def test_straight_line_projection_ignores_pause_and_paused_billing_rejected(
            self, api, billing_specialist_headers, ops_admin_headers):
        """PRD §3.7: "The contract projects `conversion_eligible_on` as
        `rental_start_on` plus the payer's `rental_months_to_own` calendar
        months — a straight-line projection that assumes one billed month per
        calendar month with no pauses."
        PRD §3.7: "the contract must be in `BILLING` status — not paused,
        converted, or terminated (`ERR_RENTAL_NOT_BILLING`)"

        Design: Difficulty/dual_variant_calc/rental_straight_line_vs_actual_usage_conversion
        """
        ctx, contract = self._setup_paused_contract(api, billing_specialist_headers)
        fetched = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        # Straight-line projection: 2026-08-01 + 3 months, regardless of pause.
        assert fetched["conversion_eligible_on"] == "2026-11-01"
        assert fetched["billing_status"] == "PAUSED_NON_COMPLIANCE"

        set_clock("2026-10-01T00:00:00Z")
        res = api.bill_rental_month(contract["id"], billing_specialist_headers)
        validate_error(res, "ERR_RENTAL_NOT_BILLING", expected_status=409)

    def test_actual_usage_conversion_lands_one_month_after_projection(
            self, api, billing_specialist_headers, ops_admin_headers):
        """PRD §3.7: "Months spent in `PAUSED_NON_COMPLIANCE` — entered
        automatically when the patient's adherence finalization triggers a
        compliance hold, and exited automatically back to `BILLING` when a later
        report restores compliance — do not increment `rental_months_billed`."
        PRD §3.7: "When a bill causes `rental_months_billed` to reach
        `rental_months_to_own`, the contract converts in the same request:
        `billing_status` becomes `CONVERTED_TO_OWNERSHIP` and `equipment_status`
        becomes `OWNERSHIP_TRANSFERRED`."

        Design: Difficulty/dual_variant_calc/rental_straight_line_vs_actual_usage_conversion
        """
        ctx, contract = self._setup_paused_contract(api, billing_specialist_headers)
        patient = ctx["patient"]
        enrollment = ctx["enrollment"]

        # Resume compliance -> billing resumes to BILLING.
        finalize_compliant_report(patient["id"], enrollment["id"],
                                  window_end_on="2026-10-05",
                                  nights_reported=30, compliant_nights=25)
        resumed = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        assert resumed["billing_status"] == "BILLING"
        assert resumed["rental_months_billed"] == 1

        set_clock("2026-11-01T00:00:00Z")
        month2 = validate_success(
            api.bill_rental_month(contract["id"], billing_specialist_headers))
        assert month2["rental_months_billed"] == 2

        set_clock("2026-12-01T00:00:00Z")
        month3 = validate_success(
            api.bill_rental_month(contract["id"], billing_specialist_headers))
        assert month3["rental_months_billed"] == 3
        assert month3["billing_status"] == "CONVERTED_TO_OWNERSHIP"
        assert month3["equipment_status"] == "OWNERSHIP_TRANSFERRED"
        # The pause pushed actual conversion one calendar month past the
        # straight-line projection (2026-11-01).
        assert month3["conversion_eligible_on"] == "2026-11-01"


class TestRentalMonthsBilledInvariant:
    """Pause/resume is compensating with respect to the billed-month counter."""

    def _setup_billing_contract_with_one_month(self, api,
                                               billing_specialist_headers):
        ctx = setup_therapy_patient(
            acquisition_type="RENTAL",
            payer_overrides={"rental_months_to_own": 5})
        contract = ctx["rental_contract"]
        set_clock("2026-09-01T00:00:00Z")
        run_daily_sweep()
        billed = validate_success(
            api.bill_rental_month(contract["id"], billing_specialist_headers))
        assert billed["rental_months_billed"] == 1
        return ctx, contract

    def test_pause_leaves_rental_months_billed_unchanged(
            self, api, billing_specialist_headers, ops_admin_headers):
        """PRD §3.4: "an active rental contract in `BILLING` pauses into
        `PAUSED_NON_COMPLIANCE` — months do not accrue while paused."

        Design: Difficulty/compensating_invariant/rental_months_billed_invariant_on_pause_resume_cycle
        """
        ctx, contract = self._setup_billing_contract_with_one_month(
            api, billing_specialist_headers)
        finalize_non_compliant_report(ctx["patient"]["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-09-30",
                                      nights_reported=30, compliant_nights=5)
        paused = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        assert paused["billing_status"] == "PAUSED_NON_COMPLIANCE"
        assert paused["rental_months_billed"] == 1

    def test_pause_resume_cycle_conserves_rental_months_billed(
            self, api, billing_specialist_headers, ops_admin_headers):
        """PRD §3.7: "Accrual follows **actual usage**, not the straight-line
        projection: only months in which the contract was actively billing
        count."

        Design: Difficulty/compensating_invariant/rental_months_billed_invariant_on_pause_resume_cycle
        """
        ctx, contract = self._setup_billing_contract_with_one_month(
            api, billing_specialist_headers)
        finalize_non_compliant_report(ctx["patient"]["id"], ctx["enrollment"]["id"],
                                      window_end_on="2026-09-30",
                                      nights_reported=30, compliant_nights=5)
        finalize_compliant_report(ctx["patient"]["id"], ctx["enrollment"]["id"],
                                  window_end_on="2026-10-15",
                                  nights_reported=30, compliant_nights=28)
        resumed = validate_success(
            api.get_rental_contract(contract["id"], ops_admin_headers))
        assert resumed["billing_status"] == "BILLING"
        assert resumed["rental_months_billed"] == 1, (
            f"pause/resume cycle must conserve rental_months_billed, got "
            f"{resumed['rental_months_billed']}")


class TestRetrievalReconcileCascade:
    def _setup_received_case(self, api):
        """RENTAL patient -> DISCONTINUING -> retrieval case at RECEIVED."""
        ctx = setup_discontinuing_patient()
        case = ctx["retrieval_case"]
        case = drive_retrieval_to_received(case["id"])
        assert case["retrieval_status"] == "RECEIVED"
        return ctx, case

    def test_reconcile_cascades_patient_to_discontinued(
            self, api, intake_coordinator_headers, ops_admin_headers):
        """PRD §3.8: "Reconciliation requires `RECEIVED`
        (`ERR_RETRIEVAL_NOT_RECEIVED`) and moves the case to `RECONCILED`;
        synchronously in the same request, a patient in `DISCONTINUING` cascades
        to `DISCONTINUED`"

        Design: Difficulty/transitive_cascade/retrieval_reconcile_to_patient_discontinued_depth2
        """
        ctx, case = self._setup_received_case(api)
        pre = get_patient(ctx["patient"]["id"])
        assert pre["patient_status"] == "DISCONTINUING"

        reconciled = validate_success(
            api.reconcile_case(case["id"], intake_coordinator_headers))
        assert reconciled["retrieval_status"] == "RECONCILED"
        post = get_patient(ctx["patient"]["id"])
        assert post["patient_status"] == "DISCONTINUED"

    def test_reconcile_closes_plans_and_terminates_rental(
            self, api, intake_coordinator_headers, ops_admin_headers):
        """PRD §3.8: "every supply plan closes to `CLOSED`, and the rental
        contract's `billing_status` terminates to `TERMINATED` unless it has
        already converted."

        Design: Difficulty/transitive_cascade/retrieval_reconcile_to_patient_discontinued_depth2
        """
        ctx, case = self._setup_received_case(api)
        validate_success(api.reconcile_case(case["id"], intake_coordinator_headers))

        plans = get_plans_for(ctx["patient"]["id"])
        for component, plan in plans.items():
            assert plan["plan_status"] == "CLOSED", f"{component} plan not CLOSED"

        contract = get_rental_contract_for(ctx["patient"]["id"])
        assert contract["billing_status"] == "TERMINATED"

        enrollment = validate_success(
            api.get_device_enrollment(ctx["enrollment"]["id"], ops_admin_headers))
        assert enrollment["enrollment_status"] == "RETRIEVED"


class TestDiscontinuationGuards:
    def test_patient_terminal_discontinued_lockdown(
            self, api, respiratory_therapist_headers, intake_coordinator_headers):
        """PRD §3.8: "The patient must be in `ACTIVE_THERAPY` or
        `NON_COMPLIANT_HOLD` (`ERR_PATIENT_NOT_DISCONTINUABLE` from any other
        status)."

        Design: Corner/state_machines/patient_terminal_discontinued_lockdown
        """
        ctx = setup_discontinuing_patient()
        case = drive_retrieval_to_received(ctx["retrieval_case"]["id"])
        validate_success(api.reconcile_case(case["id"], intake_coordinator_headers))
        patient = get_patient(ctx["patient"]["id"])
        assert patient["patient_status"] == "DISCONTINUED"

        res = api.initiate_discontinuation(
            patient["id"], {"reason_code": "PATIENT_REQUEST"},
            respiratory_therapist_headers)
        validate_error(res, "ERR_PATIENT_NOT_DISCONTINUABLE", expected_status=409)

    def test_close_unrecoverable_before_due_date_rejected(
            self, api, intake_coordinator_headers):
        """PRD §3.8: "only after the deadline has passed, meaning the current
        date is strictly later than `due_on` (`ERR_RETRIEVAL_NOT_OVERDUE` on or
        before the due date)." and "a `due_on` deadline fourteen days after
        creation"

        Design: Corner/validations/retrieval_close_unrecoverable_before_due_date_rejected
        """
        ctx = setup_discontinuing_patient()
        case = ctx["retrieval_case"]
        assert_retrieval_case(case)
        assert case["retrieval_status"] == "OPEN"
        # Created at 2026-08-01 -> due_on = 2026-08-01 + 14 days.
        assert case["due_on"] == "2026-08-15"

        res = api.close_unrecoverable(case["id"], intake_coordinator_headers)
        validate_error(res, "ERR_RETRIEVAL_NOT_OVERDUE", expected_status=409)
