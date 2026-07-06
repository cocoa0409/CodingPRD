"""MED and pill-count calculations: provisional vs final MED, forward vs chronological
pill counts, patient MED aggregation, and the med threshold boundary.

Queue A: dual_variant_calc, combinatorial_formula, boundary_precision_check.
Queue B: calculations section.
"""
import pytest

from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    TEST_USERS,
    make_prescriber_headers,
    make_compliance_officer_headers,
    setup_active_medication_patient,
    propose_prescription,
    activate_prescription,
    create_active_agreement,
    create_pdmp_check,
    create_approved_prescription_pa,
    create_active_below_threshold_rx,
    get_prescription,
    set_clock,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]
PA_CLERK = TEST_USERS["prior_auth_clerk_headers"]


def test_provisional_and_final_med_diverge_on_early_discontinue(api):
    """PRD 3.5: "it is the product of `dose_mg`, `units_per_day`, and `conversion_factor`,
    rounded to two decimal places."
    PRD 3.5: "The `final_daily_med_mg` is `provisional_daily_med_mg` scaled by the fraction
    of effective days over `day_supply`, rounded to two decimal places."

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
    assert rx["provisional_daily_med_mg"] == pytest.approx(135.00, abs=0.01)
    activate_prescription(clinic_id, patient_id, prescriber_id, rx["id"])

    set_clock(clinic_id, "2026-06-11T00:00:00Z")  # 10 elapsed days of 30 supplied
    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.discontinue_prescription(clinic_id, patient_id, rx["id"], pres_h)
    data = validate_success(resp, 200)

    assert data["final_daily_med_mg"] == pytest.approx(45.00, abs=0.01), (
        f"Expected final_daily_med_mg 45.00, got {data['final_daily_med_mg']}"
    )
    assert data["provisional_daily_med_mg"] != data["final_daily_med_mg"]


def test_pillcount_forward_vs_chronological_diverge(api):
    """PRD 3.9: "The forward-looking expectation, `expected_pills_forward`, is the
    `pills_dispensed` minus the product of the fractional `units_per_day` and the capped
    elapsed days, rounded once at the end to two decimal places."
    PRD 3.9: "`expected_pills_chronological` equals `pills_dispensed` minus the ceiling of
    `units_per_day` multiplied by the capped elapsed days."

    Design: Difficulty/dual_variant_calc/pillcount_forward_vs_chronological_diverge
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

    set_clock(clinic_id, "2026-06-21T00:00:00Z")  # 20 elapsed days
    co_h = make_compliance_officer_headers(co_id)
    resp = api.create_pill_count_audit(
        clinic_id, patient_id,
        {"prescription_id": rx["id"], "audit_utc": "2026-06-21T00:00:00Z", "counted_pills": 22},
        co_h,
    )
    data = validate_success(resp, 201)
    # forward: 60 - (1.5 * 20) = 30.00 ; chronological: 60 - (ceil(1.5)=2 * 20) = 20
    assert data["expected_pills_forward"] == pytest.approx(30.00, abs=0.01)
    assert data["expected_pills_chronological"] == pytest.approx(20, abs=0.01)
    assert data["expected_pills_forward"] != data["expected_pills_chronological"]


def test_provisional_med_multiinput_selects_threshold_gate(api):
    """PRD 3.5: "First, an `OpioidAgreement` for the patient must be `ACTIVE` and unexpired
    (otherwise `ERR_OPIOID_AGREEMENT_REQUIRED`)."
    PRD 3.5: "only for a controlled prescription whose `provisional_daily_med_mg` is at or
    above the clinic's `med_review_threshold_mg`."

    Design: Difficulty/combinatorial_formula/provisional_med_multiinput_threshold_selection
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="oxycodone", dose_mg=15, units_per_day=6, conversion_factor=1.5,
        day_supply=30, pills_dispensed=180,
    )
    assert rx["provisional_daily_med_mg"] == pytest.approx(135.00, abs=0.01)

    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_OPIOID_AGREEMENT_REQUIRED.value)

    after = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after["status"] == "PROPOSED"


def test_pillcount_perday_ceil_then_sum_drives_result(api):
    """PRD 3.9: "each elapsed day consumes the ceiling of `units_per_day` whole pills, and
    these per-day whole-pill amounts are summed across the capped elapsed days."
    PRD 3.9: "The compliance decision uses the chronological value, not the forward one."
    PRD 3.9: "The audit's `discrepancy_pills` is the absolute difference between
    `expected_pills_chronological` and `counted_pills`."

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
    resp = api.create_pill_count_audit(
        clinic_id, patient_id,
        {"prescription_id": rx["id"], "audit_utc": "2026-06-21T00:00:00Z", "counted_pills": 15},
        co_h,
    )
    data = validate_success(resp, 201)
    # chronological = 20 ; discrepancy = |20 - 15| = 5 ; tolerance default 2 -> INCONSISTENT
    assert data["expected_pills_chronological"] == pytest.approx(20, abs=0.01)
    assert data["discrepancy_pills"] == pytest.approx(5, abs=0.01)
    assert data["result"] == "INCONSISTENT"


def test_med_threshold_at_exactly_90_triggers_gate(api):
    """PRD 3.5: "only for a controlled prescription whose `provisional_daily_med_mg` is at or
    above the clinic's `med_review_threshold_mg`."
    PRD 3.5: "First, an `OpioidAgreement` for the patient must be `ACTIVE` and unexpired
    (otherwise `ERR_OPIOID_AGREEMENT_REQUIRED`)."

    Design: Difficulty/boundary_precision_check/med_threshold_at_exactly_90_triggers_gate
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="oxycodone", dose_mg=15, units_per_day=6, conversion_factor=1.0,
        day_supply=30, pills_dispensed=180,
    )
    assert rx["provisional_daily_med_mg"] == pytest.approx(90.00, abs=0.01)

    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_OPIOID_AGREEMENT_REQUIRED.value)


def test_below_threshold_activation_requires_no_gates(api):
    """PRD 3.5: "and below the threshold none of them apply."
    Boundary companion to the exactly-90 gate: provisional 80.00 (< 90) activates with no
    agreement, PDMP, or prior-auth.

    Design: Difficulty/boundary_precision_check/med_threshold_at_exactly_90_triggers_gate
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="oxycodone", dose_mg=10, units_per_day=8, conversion_factor=1.0,
        day_supply=30, pills_dispensed=240,
    )
    assert rx["provisional_daily_med_mg"] == pytest.approx(80.00, abs=0.01)
    pres_h = make_prescriber_headers(prescriber_id)
    data = validate_success(api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h), 200)
    assert data["status"] == "ACTIVE"


def test_patient_med_aggregates_two_active_prescriptions(api):
    """PRD 2.9: "the patient's own `current_daily_med_mg` is recomputed as the sum of
    `provisional_daily_med_mg` over that patient's `ACTIVE` and `TAPERING` prescriptions,
    rounded to two decimal places."
    PRD 2.9: "`total_active_med_mg`, the sum of `provisional_daily_med_mg` across the
    patient's `ACTIVE` and `TAPERING` prescriptions."

    Design: Corner/calculations/patient_med_aggregate_two_active_rx
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    # rx1 provisional = 5*4*1 = 20 ; rx2 provisional = 15*2*1 = 30
    rx1 = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="tramadol", dose_mg=5, units_per_day=4, conversion_factor=1.0,
        day_supply=30, pills_dispensed=120,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx1["id"])
    rx2 = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        drug_name="codeine", dose_mg=15, units_per_day=2, conversion_factor=1.0,
        day_supply=30, pills_dispensed=60,
    )
    activate_prescription(clinic_id, patient_id, prescriber_id, rx2["id"])

    pres_h = make_prescriber_headers(prescriber_id)
    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["current_daily_med_mg"] == pytest.approx(50.00, abs=0.01)

    ledgers = validate_success(api.get_patient_ledger(clinic_id, patient_id, pres_h), 200)
    ledger = ledgers[0] if isinstance(ledgers, list) else ledgers
    assert ledger["total_active_med_mg"] == pytest.approx(50.00, abs=0.01)


def test_agreement_expired_blocks_activation(api):
    """PRD 3.4: "An agreement is unexpired precisely while the clinic's `current_utc` is
    strictly before `expires_utc`; at the instant `current_utc` equals `expires_utc`, the
    agreement is `EXPIRED`."
    PRD 3.5: "First, an `OpioidAgreement` for the patient must be `ACTIVE` and unexpired
    (otherwise `ERR_OPIOID_AGREEMENT_REQUIRED`)."

    Design: Corner/calculations/agreement_expired_blocks_activation
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]

    create_active_agreement(clinic_id, patient_id, prescriber_id)  # signed 2026-06-01, expires 2027-06-01
    create_pdmp_check(clinic_id, patient_id, prescriber_id)
    pa = create_approved_prescription_pa(clinic_id, patient_id, authorized_units=30)
    rx = propose_prescription(
        clinic_id, patient_id, prescriber_id,
        prior_auth_id=pa["id"], drug_name="oxycodone", dose_mg=15, units_per_day=6,
        conversion_factor=1.5, day_supply=30, pills_dispensed=180,
    )
    set_clock(clinic_id, "2027-06-01T00:00:00Z")  # == expires_utc -> EXPIRED

    pres_h = make_prescriber_headers(prescriber_id)
    resp = api.activate_prescription(clinic_id, patient_id, rx["id"], pres_h)
    validate_error(resp, ApiErrorId.ERR_OPIOID_AGREEMENT_REQUIRED.value)
    after = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after["status"] == "PROPOSED"
