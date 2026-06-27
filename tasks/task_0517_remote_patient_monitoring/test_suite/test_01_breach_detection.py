"""Vitals breach evaluation: non-linear band selection and boundary precision.

Covers difficulty rules combinatorial_formula (breach) and boundary_precision_check
(breach), plus the corner service_date computed-field and non-breach endpoint claims.
"""
from test_helpers import (
    api_client, validate_success, get_success_data,
    create_vitals_payload, TEST_USERS, set_clock,
    setup_enrolled_patient_with_active_device,
)

CLIN = TEST_USERS["clinician_headers"]
CC = TEST_USERS["care_coordinator_headers"]


def _alert_for_reading(reading_id):
    alerts = get_success_data(api_client.list_alerts(CLIN, params={"vitals_reading_id": reading_id}))
    return alerts


def test_bp_systolic_185_diastolic_95_is_critical_via_systolic_branch(api):
    """PRD §2.9: "a `CRITICAL` breach occurs when the systolic value is at least 180
    or the diastolic value is at least 120."
    PRD §2.9: "When a reading falls into the `CRITICAL` band, that band wins over `WARNING`."
    PRD §3.5: "When a breach is detected, the system creates a `ThresholdAlert` linked
    to the reading."

    Design: Difficulty/combinatorial_formula/breach_evaluation_multi_input_nonlinear_bands
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-BR-1", serial_number="SN-BR-1", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 185, "2026-06-10T08:00:00Z",
                              secondary_value=95),
        CLIN), 201)
    assert reading["breach_flag"] is True, "systolic 185 must breach"
    alerts = _alert_for_reading(reading["id"])
    assert len(alerts) == 1, "exactly one alert for the breaching reading"
    # systolic 185 >= 180 => CRITICAL wins even though diastolic 95 alone is only WARNING
    assert alerts[0]["severity"] == "CRITICAL"


def test_bp_critical_band_wins_over_warning_diastolic(api):
    """PRD §2.9: "When a reading falls into the `CRITICAL` band, that band wins over `WARNING`."
    PRD §2.9: "a `CRITICAL` breach occurs when the systolic value is at least 180
    or the diastolic value is at least 120."

    Design: Difficulty/combinatorial_formula/breach_evaluation_multi_input_nonlinear_bands
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-BR-2", serial_number="SN-BR-2", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    # diastolic 130 >= 120 => CRITICAL via the diastolic branch; systolic 150 alone is WARNING.
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 150, "2026-06-10T09:00:00Z",
                              secondary_value=130),
        CLIN), 201)
    assert reading["breach_flag"] is True
    alerts = _alert_for_reading(reading["id"])
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "CRITICAL"


def test_bp_systolic_exactly_140_is_warning_breach(api):
    """PRD §2.9: "a `WARNING` breach occurs when the systolic value is at least 140
    or the diastolic value is at least 90."
    PRD §2.9: "A systolic of exactly 140 is a `WARNING` breach; 139 is not."

    Design: Difficulty/boundary_precision_check/bp_systolic_exactly_140_is_warning_breach
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-B1-1", serial_number="SN-B1-1", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 140, "2026-06-10T08:00:00Z",
                              secondary_value=85),
        CLIN), 201)
    assert reading["breach_flag"] is True, "systolic exactly 140 is a WARNING breach"
    alerts = _alert_for_reading(reading["id"])
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "WARNING", "140 is WARNING, not CRITICAL"


def test_bp_systolic_139_does_not_breach(api):
    """PRD §2.9: "A systolic of exactly 140 is a `WARNING` breach; 139 is not."
    PRD §2.9: "If the reading enters any breach band the system sets `breach_flag`
    to true; otherwise it is false."

    Design: Difficulty/boundary_precision_check/bp_systolic_exactly_140_is_warning_breach
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-B1-2", serial_number="SN-B1-2", consent_type="RPM")
    set_clock("2026-06-10T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 139, "2026-06-10T08:00:00Z",
                              secondary_value=85),
        CLIN), 201)
    assert reading["breach_flag"] is False, "systolic 139 does not breach"
    assert _alert_for_reading(reading["id"]) == [], "no alert when below the band"


def test_vitals_service_date_computed_from_measured_at(api):
    """PRD §3.5: "the system derives `service_date`, the UTC calendar date (formatted
    `YYYY-MM-DD`) extracted from `measured_at`, which is the device-day the reading
    counts toward."

    Design: Corner/entities/vitals_service_date_computed_from_measured_at
    """
    ctx = setup_enrolled_patient_with_active_device(
        mrn="M-EC6-1", serial_number="SN-EC6-1", consent_type="RPM")
    set_clock("2026-06-09T00:00:00Z", CC)
    reading = validate_success(api.create_vitals(
        ctx["patient"]["id"],
        create_vitals_payload(ctx["device"]["id"], 118, "2026-06-09T23:30:00Z",
                              secondary_value=78),
        CLIN), 201)
    assert reading["service_date"] == "2026-06-09", "service_date is the UTC date of measured_at"
    assert reading["breach_flag"] is False
