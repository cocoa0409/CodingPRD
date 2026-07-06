"""Controlled-substance ledger conservation and compliance cascades: MED conservation
across prescribe/discontinue, suite booked-minutes conservation, the inconsistent-UDS
depth-3 cascade, discharge depth-2 cascade, and immediate MED visibility.

Queue A: transitive_cascade, compensating_invariant.
Queue B: cross_cutting_complexity_layers.consistency (immediate).
"""
import pytest

from test_helpers import (
    validate_success,
    ApiErrorId,
    TEST_USERS,
    make_prescriber_headers,
    make_compliance_officer_headers,
    setup_active_medication_patient,
    setup_scheduled_procedure,
    setup_collected_uds,
    propose_prescription,
    activate_prescription,
    create_active_below_threshold_rx,
    get_prescription,
    assert_med_conservation,
)

ADMIN = TEST_USERS["clinic_admin_headers"]
INTAKE = TEST_USERS["intake_coordinator_headers"]


def _ledger(api, clinic_id, patient_id, headers):
    ledgers = validate_success(api.get_patient_ledger(clinic_id, patient_id, headers), 200)
    return ledgers[0] if isinstance(ledgers, list) else ledgers


def test_inconsistent_uds_flags_suspends_and_moves_ledger(api):
    """PRD 3.8: "the screen moves from `COLLECTED` to `RESULTED_INCONSISTENT` and triggers a
    compliance cascade: the patient's `compliance_flag` is set to `FLAGGED`, and that flagging
    then suspends each `ACTIVE` or `TAPERING` opioid prescription for the patient, moving each
    such prescription's `provisional_daily_med_mg` from the ledger's `total_active_med_mg` to
    `suspended_med_mg` and recomputing the patient's `current_daily_med_mg`."

    Design: Difficulty/transitive_cascade/uds_inconsistent_flag_suspend_ledger_depth3
    """
    ctx = setup_active_medication_patient(clock_utc="2026-06-01T00:00:00Z", intake_utc="2026-06-01T00:00:00Z")
    clinic_id, patient_id, prescriber_id, co_id = (
        ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"], ctx["compliance_officer"]["id"],
    )
    rx = create_active_below_threshold_rx(ctx)  # provisional 20
    assert rx["provisional_daily_med_mg"] == pytest.approx(20.00, abs=0.01)

    co_h = make_compliance_officer_headers(co_id)
    # UDS expecting {tramadol}, collect, then result with detected {} -> inconsistent
    uds = validate_success(
        api.create_urine_drug_screen(
            clinic_id, patient_id,
            {"due_utc": "2026-06-01T00:00:00Z", "expected_substances": ["tramadol"]}, co_h,
        ), 201,
    )
    validate_success(api.collect_urine_drug_screen(clinic_id, patient_id, uds["id"], INTAKE), 200)
    result = validate_success(
        api.result_urine_drug_screen(clinic_id, patient_id, uds["id"], {"detected_substances": []}, co_h), 200
    )
    assert result["status"] == "RESULTED_INCONSISTENT"

    pres_h = make_prescriber_headers(prescriber_id)
    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["compliance_flag"] == "FLAGGED"
    assert patient["current_daily_med_mg"] == pytest.approx(0.00, abs=0.01)

    after_rx = get_prescription(clinic_id, patient_id, prescriber_id, rx["id"])
    assert after_rx["status"] == "SUSPENDED"

    ledger = _ledger(api, clinic_id, patient_id, pres_h)
    assert ledger["suspended_med_mg"] == pytest.approx(20.00, abs=0.01)
    assert ledger["total_active_med_mg"] == pytest.approx(0.00, abs=0.01)


def test_discharge_cancels_procedure_and_releases_suite(api):
    """PRD 3.10: "every procedure for the patient that is still `REQUESTED` or `SCHEDULED` is
    moved to `CANCELLED`, and each cancelled procedure that had been `SCHEDULED` debits its
    suite by decreasing that suite's `booked_minutes` by the procedure's `duration_minutes`."

    Design: Difficulty/transitive_cascade/discharge_cancels_procedures_releases_suite_depth2
    """
    ctx = setup_scheduled_procedure(duration_minutes=30)
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    proc_id, suite_id = ctx["procedure"]["id"], ctx["suite"]["id"]

    pres_h = make_prescriber_headers(prescriber_id)
    patient = validate_success(api.discharge_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["status"] == "DISCHARGED"

    proc = validate_success(api.list_procedures(clinic_id, patient_id, pres_h), 200)
    proc = [p for p in proc if p["id"] == proc_id][0]
    assert proc["status"] == "CANCELLED"

    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, pres_h), 200)
    suite = [s for s in suites if s["id"] == suite_id][0]
    assert suite["booked_minutes"] == 0


def test_prescribe_then_discontinue_conserves_ledger_total(api):
    """PRD 2.9: "the sum of `total_active_med_mg`, `suspended_med_mg`, and
    `discontinued_med_mg` is invariant."
    PRD 3.5: "the prescription's `provisional_daily_med_mg` is moved out of whichever account
    currently holds it — `total_active_med_mg` if the prescription was `ACTIVE` or `TAPERING`
    ... and into `discontinued_med_mg`, after which the patient's `current_daily_med_mg` is
    recomputed."

    Design: Difficulty/compensating_invariant/med_ledger_prescribe_discontinue_conserves_total
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = create_active_below_threshold_rx(ctx)  # provisional 20
    pres_h = make_prescriber_headers(prescriber_id)

    ledger_before = _ledger(api, clinic_id, patient_id, pres_h)
    assert_med_conservation(ledger_before, 20.00)

    validate_success(api.discontinue_prescription(clinic_id, patient_id, rx["id"], pres_h), 200)

    ledger = _ledger(api, clinic_id, patient_id, pres_h)
    assert ledger["total_active_med_mg"] == pytest.approx(0.00, abs=0.01)
    assert ledger["discontinued_med_mg"] == pytest.approx(20.00, abs=0.01)
    assert ledger["suspended_med_mg"] == pytest.approx(0.00, abs=0.01)
    assert_med_conservation(ledger, 20.00)

    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["current_daily_med_mg"] == pytest.approx(0.00, abs=0.01)


def test_schedule_then_cancel_conserves_booked_minutes(api):
    """PRD 3.7: "if the procedure was `SCHEDULED`, cancellation is a compensating action that
    decreases the suite's `booked_minutes` by the procedure's `duration_minutes`, leaving
    `booked_minutes` unchanged across a schedule-then-cancel pair."

    Design: Difficulty/compensating_invariant/suite_schedule_cancel_conserves_booked_minutes
    """
    ctx = setup_scheduled_procedure(duration_minutes=30)
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    proc_id, suite_id = ctx["procedure"]["id"], ctx["suite"]["id"]

    pres_h = make_prescriber_headers(prescriber_id)
    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, pres_h), 200)
    booked_after_schedule = [s for s in suites if s["id"] == suite_id][0]["booked_minutes"]
    assert booked_after_schedule == 30

    proc = validate_success(api.cancel_procedure(clinic_id, patient_id, proc_id, INTAKE), 200)
    assert proc["status"] == "CANCELLED"

    suites = validate_success(api.list_fluoroscopy_suites(clinic_id, pres_h), 200)
    suite = [s for s in suites if s["id"] == suite_id][0]
    assert suite["booked_minutes"] == 0, "schedule+cancel must conserve booked_minutes back to 0"


def test_med_visible_immediately_on_activate(api):
    """PRD 2.9: "the patient's own `current_daily_med_mg` is recomputed as the sum of
    `provisional_daily_med_mg` over that patient's `ACTIVE` and `TAPERING` prescriptions,
    rounded to two decimal places, so that the patient record and the ledger's active total
    always agree."

    Design: Corner/consistency_model/immediate_visibility_of_med_on_activate
    """
    ctx = setup_active_medication_patient()
    clinic_id, patient_id, prescriber_id = ctx["clinic"]["id"], ctx["patient"]["id"], ctx["prescriber"]["id"]
    rx = create_active_below_threshold_rx(ctx)  # provisional 20
    assert rx["provisional_daily_med_mg"] == pytest.approx(20.00, abs=0.01)

    pres_h = make_prescriber_headers(prescriber_id)
    patient = validate_success(api.get_patient(clinic_id, patient_id, pres_h), 200)
    assert patient["current_daily_med_mg"] == pytest.approx(20.00, abs=0.01)
