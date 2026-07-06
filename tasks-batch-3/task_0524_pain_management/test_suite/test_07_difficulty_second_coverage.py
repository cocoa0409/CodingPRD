"""Second-coverage tests for the depth (difficulty) design instances. Each test below
targets a distinct facet of an instance already covered once elsewhere, so every
difficulty instance carries at least two tests. Every assertion remains grounded in a
verbatim PRD sentence.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    TEST_USERS,
    make_prescriber_headers,
    make_compliance_officer_headers,
    setup_active_medication_patient,
    setup_active_procedure_patient,
    setup_scheduled_procedure,
    setup_collected_uds,
    propose_prescription,
    activate_prescription,
    create_active_agreement,
    create_draft_agreement,
    create_pdmp_check,
    create_approved_prescription_pa,
    submit_prescription_pa,
    create_approved_procedure_pa,
    submit_procedure_pa,
    request_procedure,
    schedule_procedure_with_current_version,
    create_active_below_threshold_rx,
    get_prescription,
    assert_med_conservation,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _ledger(api, clinic_id, patient_id, headers):
    ledgers = validate_success(api.get_patient_ledger(clinic_id, patient_id, headers), 200)
    return ledgers[0] if isinstance(ledgers, list) else ledgers


# --- dual_variant_calc / rx_provisional_vs_final_med_diverge (2nd) ---
def test_final_med_equals_provisional_when_full_course_elapsed(api):
    """PRD 3.5: "Because a prescription discontinued before its full course elapses is scaled
    below unity, its `final_daily_med_mg` is lower than its `provisional_daily_med_mg` for
    identical dose inputs; the two are equal only when the full course has elapsed."

    Design: Difficulty/dual_variant_calc/rx_provisional_vs_final_med_diverge
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    create_active_agreement(clinic_id, patient_id, prescriber_id)
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=30)
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    set_clock(clinic_id, "2026-07-05T00:00:00Z")  # 34 elapsed days > 30 day_supply -> capped, full course
    pres_h = make_prescriber_headers(prescriber_id)
    data = validate_success(api.discontinue_prescription(clinic_id, patient_id, rx["id"], pres_h), 200)
    assert data["final_daily_med_mg"] == pytest.approx(135.00, abs=0.01)
    assert data["final_daily_med_mg"] == pytest.approx(data["provisional_daily_med_mg"], abs=0.01)


# --- dual_variant_calc / pillcount_forward_vs_chronological_diverge (2nd) ---
def test_pillcount_variants_coincide_for_whole_units_per_day(api):
    """PRD 3.9: "only when `units_per_day` is already a whole number do they coincide."

    Design: Difficulty/dual_variant_calc/pillcount_forward_vs_chronological_diverge
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="tramadol", dose_mg=5, units_per_day=2, conversion_factor=1.0,
        day_supply=40, pills_dispensed=80,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    set_clock(clinic_id, "2026-06-21T00:00:00Z")  # 20 days
    co_h = make_compliance_officer_headers(co_id)
    data = validate_success(
        api.create_pill_count_audit(
            clinic_id, patient_id,
            {"prescription_id": rx["id"], "audit_utc": "2026-06-21T00:00:00Z", "counted_pills": 40}, co_h,
        ), 201,
    )
    # forward: 80 - 2*20 = 40 ; chronological: 80 - ceil(2)*20 = 40
    assert data["expected_pills_forward"] == pytest.approx(40, abs=0.01)
    assert data["expected_pills_chronological"] == pytest.approx(40, abs=0.01)


# --- combinatorial_formula / provisional_med_multiinput_threshold_selection (2nd) ---
def test_provisional_med_product_rounds_two_places(api):
    """PRD 3.5: "it is the product of `dose_mg`, `units_per_day`, and `conversion_factor`,
    rounded to two decimal places."

    Design: Difficulty/combinatorial_formula/provisional_med_multiinput_threshold_selection
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    # 12.5 * 3 * 1.2 = 45.00
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="tramadol", dose_mg=12.5, units_per_day=3, conversion_factor=1.2,
        day_supply=30, pills_dispensed=90,
    )
    assert rx["provisional_daily_med_mg"] == pytest.approx(45.00, abs=0.01)


# --- combinatorial_formula / pillcount_perday_ceil_then_sum_order (2nd) ---
def test_pillcount_consistent_within_tolerance(api):
    """PRD 3.9: "The `result` is `CONSISTENT` when `discrepancy_pills` is at or below the
    clinic's `pill_count_tolerance`, and `INCONSISTENT` otherwise."

    Design: Difficulty/combinatorial_formula/pillcount_perday_ceil_then_sum_order
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="tramadol", dose_mg=50, units_per_day=1.5, conversion_factor=0.1,
        day_supply=40, pills_dispensed=60,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    set_clock(clinic_id, "2026-06-21T00:00:00Z")
    co_h = make_compliance_officer_headers(co_id)
    # chronological expected = 20 ; counted 22 -> discrepancy 2 == tolerance -> CONSISTENT
    data = validate_success(
        api.create_pill_count_audit(
            clinic_id, patient_id,
            {"prescription_id": rx["id"], "audit_utc": "2026-06-21T00:00:00Z", "counted_pills": 22}, co_h,
        ), 201,
    )
    assert data["discrepancy_pills"] == pytest.approx(2, abs=0.01)
    assert data["result"] == "CONSISTENT"


# --- non_linear_state_machine / uds_recollect_cycle_back_to_scheduled (2nd) ---
def test_uds_recollect_only_from_inconsistent(api):
    """PRD 3.8: "recollection moves the screen from `RESULTED_INCONSISTENT` back to
    `SCHEDULED`, permitted only while the screen is `RESULTED_INCONSISTENT` (otherwise
    `ERR_UDS_STATE_INVALID`)."

    Design: Difficulty/non_linear_state_machine/uds_recollect_cycle_back_to_scheduled
    """
    ctx = setup_collected_uds(expected_substances=["oxycodone"])
    clinic_id, patient_id, co_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["compliance_officer"]["id"]
    uds_id = ctx["uds"]["id"]
    co_h = make_compliance_officer_headers(co_id)
    # Screen is COLLECTED (not RESULTED_INCONSISTENT) -> recollect must be rejected.
    resp = api.recollect_urine_drug_screen(clinic_id, patient_id, uds_id, {"due_utc": "2026-06-05T00:00:00Z"}, co_h)
    validate_error(resp, ApiErrorId.ERR_UDS_STATE_INVALID.value)


# --- non_linear_state_machine / rx_taper_reescalate_cycle (2nd) ---
def test_reescalate_only_from_tapering(api):
    """PRD 3.5: "Re-escalating returns a `TAPERING` prescription to `ACTIVE`, permitted only
    while the prescription is `TAPERING` (otherwise `ERR_RX_STATE_INVALID`)."

    Design: Difficulty/non_linear_state_machine/rx_taper_reescalate_cycle
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = create_active_below_threshold_rx(ctx, taper_step_pct=10)  # ACTIVE, not TAPERING
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.re_escalate(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_RX_STATE_INVALID.value)


# --- transitive_cascade / uds_inconsistent_flag_suspend_ledger_depth3 (2nd) ---
def test_inconsistent_uds_conserves_ledger_total_into_suspended(api):
    """PRD 2.9: "the sum of `total_active_med_mg`, `suspended_med_mg`, and
    `discontinued_med_mg` is invariant: MED is never created or destroyed by a state change,
    only moved between these three accounts."

    Design: Difficulty/transitive_cascade/uds_inconsistent_flag_suspend_ledger_depth3
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    create_active_below_threshold_rx(ctx)  # provisional 20 in total_active
    co_h = make_compliance_officer_headers(co_id)
    uds = validate_success(
        api.create_urine_drug_screen(
            clinic_id, patient_id, {"due_utc": "2026-06-01T00:00:00Z", "expected_substances": ["tramadol"]}, co_h
        ), 201,
    )
    validate_success(api.collect_urine_drug_screen(clinic_id, patient_id, uds["id"], INTAKE), 200)
    validate_success(
        api.result_urine_drug_screen(clinic_id, patient_id, uds["id"], {"detected_substances": []}, co_h), 200
    )
    pres_h = make_prescriber_headers(prescriber_id)
    ledger = _ledger(api, clinic_id, patient_id, pres_h)
    assert_med_conservation(ledger, 20.00)
    assert ledger["total_active_med_mg"] == pytest.approx(0.00, abs=0.01)


# --- transitive_cascade / discharge_cancels_procedures_releases_suite_depth2 (2nd) ---
def test_discharge_cancels_non_terminal_treatment_plan(api):
    """PRD 3.10: "additionally, every treatment plan for the patient that is not already in a
    terminal state is moved to `CANCELLED`."

    Design: Difficulty/transitive_cascade/discharge_cancels_procedures_releases_suite_depth2
    """
    ctx = setup_scheduled_procedure(duration_minutes=30)
    clinic_id, patient_id, prescriber_id, plan_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["plan"]["id"],
    )
    pres_h = make_prescriber_headers(prescriber_id)
    validate_success(api.discharge_patient(clinic_id, patient_id, pres_h), 200)
    plans = validate_success(api.list_treatment_plans(clinic_id, patient_id, pres_h), 200)
    assert [p for p in plans if p["id"] == plan_id][0]["status"] == "CANCELLED"


# --- priority_pair_validation_conflict / referential_vs_fiscal_priorauth_approval_wins (2nd) ---
def test_authorized_units_error_when_prior_auth_approved(api):
    """PRD 3.5: "and that authorization's `authorized_units` must be at least the requested
    `day_supply` (otherwise `ERR_AUTHORIZED_UNITS_EXCEEDED`)."

    Design: Difficulty/priority_pair_validation_conflict/referential_vs_fiscal_priorauth_approval_wins
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    create_active_agreement(clinic_id, patient_id, prescriber_id)
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=1)  # APPROVED but units 1 < 30
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_AUTHORIZED_UNITS_EXCEEDED.value, expected_status=402)


# --- boundary_precision_check / uds_result_empty_expected_set_is_consistent (2nd) ---
def test_uds_matching_nonempty_sets_consistent(api):
    """PRD 3.8: "If the set of `detected_substances` equals the set of `expected_substances`,
    the screen moves from `COLLECTED` to `RESULTED_CONSISTENT` with no further effect."

    Design: Difficulty/boundary_precision_check/uds_result_empty_expected_set_is_consistent
    """
    ctx = setup_collected_uds(expected_substances=["oxycodone"])
    clinic_id, patient_id, co_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["compliance_officer"]["id"]
    uds_id = ctx["uds"]["id"]
    co_h = make_compliance_officer_headers(co_id)
    result = validate_success(
        api.result_urine_drug_screen(clinic_id, patient_id, uds_id, {"detected_substances": ["oxycodone"]}, co_h), 200
    )
    assert result["status"] == "RESULTED_CONSISTENT"
    patient = validate_success(api.get_patient(clinic_id, patient_id, co_h), 200)
    assert patient["compliance_flag"] == "NONE"


# --- cross_entity_state_dependency / procedure_schedule_requires_prior_auth_approved (2nd) ---
def test_schedule_requires_plan_on_procedure_path(api):
    """PRD 3.7: "The referenced `TreatmentPlan` must be on `PROCEDURE_PATH` (otherwise
    `ERR_PLAN_NOT_ON_PROCEDURE_PATH`)."

    Design: Difficulty/cross_entity_state_dependency/procedure_schedule_requires_prior_auth_approved
    """
    # Build a patient active via a MEDICATION plan (so no PROCEDURE_PATH plan exists), then
    # reference that medication plan when requesting a procedure.
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, plan_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"]
    suite = validate_success(api.create_fluoroscopy_suite(clinic_id, {"name": "Suite-B"}, ADMIN), 201)
    pa = create_approved_procedure_pa(clinic_id, patient_id)
    proc = request_procedure(clinic_id, patient_id, plan_id, suite["id"], pa["id"],
                             start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    clinic = validate_success(api.get_clinic(clinic_id, ADMIN), 200)
    resp = api.schedule_procedure(
        clinic_id, patient_id, proc["id"], {"expected_clinic_version": clinic["version"]}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_PLAN_NOT_ON_PROCEDURE_PATH.value)


# --- resource_temporal_overlap / suite_buffered_overlap_within_cleanup_conflicts (2nd) ---
def test_exact_same_start_conflicts(api):
    """PRD 3.7: "The requested procedure conflicts with an existing `SCHEDULED` procedure in
    the same suite when the requested start falls strictly before the existing procedure's
    buffered end and the existing procedure's start falls strictly before the requested
    procedure's buffered end. Any such overlap is rejected with `ERR_SUITE_TIME_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/suite_buffered_overlap_within_cleanup_conflicts
    """
    ctx = setup_active_procedure_patient(modality="INJECTION")
    clinic_id, patient_id, plan_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"],
    )
    pa1 = create_approved_procedure_pa(clinic_id, patient_id)
    pa2 = create_approved_procedure_pa(clinic_id, patient_id)
    proc1 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa1["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    schedule_procedure_with_current_version(clinic_id, patient_id, proc1["id"])
    proc2 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa2["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    clinic = validate_success(api.get_clinic(clinic_id, ADMIN), 200)
    resp = api.schedule_procedure(
        clinic_id, patient_id, proc2["id"], {"expected_clinic_version": clinic["version"]}, INTAKE
    )
    validate_error(resp, ApiErrorId.ERR_SUITE_TIME_CONFLICT.value)


# --- resource_temporal_overlap / suite_back_to_back_after_buffer_no_conflict (2nd) ---
def test_non_overlapping_far_apart_schedules_succeed(api):
    """PRD 3.7: "When scheduling succeeds, the suite's `booked_minutes` is increased by the
    procedure's `duration_minutes`, and the clinic's `version` is incremented by one."

    Design: Difficulty/resource_temporal_overlap/suite_back_to_back_after_buffer_no_conflict
    """
    ctx = setup_active_procedure_patient(modality="INJECTION")
    clinic_id, patient_id, plan_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["plan"]["id"], ctx["suite"]["id"],
    )
    pa1 = create_approved_procedure_pa(clinic_id, patient_id)
    pa2 = create_approved_procedure_pa(clinic_id, patient_id)
    proc1 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa1["id"],
                              start_utc="2026-06-10T10:00:00Z", duration_minutes=30)
    schedule_procedure_with_current_version(clinic_id, patient_id, proc1["id"])
    proc2 = request_procedure(clinic_id, patient_id, plan_id, suite_id, pa2["id"],
                              start_utc="2026-06-10T15:00:00Z", duration_minutes=30)
    scheduled = schedule_procedure_with_current_version(clinic_id, patient_id, proc2["id"])
    assert scheduled["status"] == "SCHEDULED"
    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, INTAKE), 200)
    assert [s for s in suites if s["id"] == suite_id][0]["booked_minutes"] == 60


# --- compensating_invariant / med_ledger_prescribe_discontinue_conserves_total (2nd) ---
def test_activate_moves_med_into_active_account(api):
    """PRD 3.5: "On successful activation the prescription's `provisional_daily_med_mg` is
    added to the ledger's `total_active_med_mg`."

    Design: Difficulty/compensating_invariant/med_ledger_prescribe_discontinue_conserves_total
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    create_active_below_threshold_rx(ctx)  # provisional 20
    pres_h = make_prescriber_headers(prescriber_id)
    ledger = _ledger(api, clinic_id, patient_id, pres_h)
    assert ledger["total_active_med_mg"] == pytest.approx(20.00, abs=0.01)
    assert ledger["discontinued_med_mg"] == pytest.approx(0.00, abs=0.01)
    assert_med_conservation(ledger, 20.00)


# --- compensating_invariant / suite_schedule_cancel_conserves_booked_minutes (2nd) ---
def test_complete_procedure_debits_booked_minutes(api):
    """PRD 3.7: "Completing a scheduled procedure moves it from `SCHEDULED` to `COMPLETED` ...
    On completion the suite's `booked_minutes` is decreased by the procedure's
    `duration_minutes`."

    Design: Difficulty/compensating_invariant/suite_schedule_cancel_conserves_booked_minutes
    """
    ctx = setup_scheduled_procedure(clock_utc="2026-06-11T00:00:00Z", start_utc="2026-06-10T10:00:00Z",
                                    duration_minutes=30)
    clinic_id, patient_id, prescriber_id, proc_id, suite_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"],
        ctx["procedure"]["id"], ctx["suite"]["id"],
    )
    pres_h = make_prescriber_headers(prescriber_id)
    done = validate_success(api.complete_procedure(clinic_id, patient_id, proc_id, pres_h), 200)
    assert done["status"] == "COMPLETED"
    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, pres_h), 200)
    assert [s for s in suites if s["id"] == suite_id][0]["booked_minutes"] == 0
