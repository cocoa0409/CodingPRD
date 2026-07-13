"""Patient intake and risk stratification: risk-score banding, the consent default, the
readmission-window boundary, and risk recomputation on a new admission."""
from test_helpers import (
    validate_success,
    bootstrap, create_patient,
    create_patient_payload, create_ed_event_payload,
)


def test_readmission_at_exactly_30_days_flagged(api):
    """PRD 3.2: "the number of whole days between that prior discharge_date and this
    event_date is 30 or fewer. Exactly 30 days still counts as a readmission; 31 days does
    not."
    A second admission on 2026-04-09, exactly 30 days after a prior discharge on 2026-03-10,
    sets is_readmission true.

    Design: Difficulty/boundary_precision_check/readmission_exactly_30_days
    """
    org = bootstrap(api)
    patient = create_patient(api, org, full_name="Pat Readmit",
                             baseline_ed_visits_12mo=6, chronic_conditions_count=3)
    api.create_ed_event(create_ed_event_payload(
        patient["id"], "INPATIENT_ADMISSION", "2026-03-01T00:00:00Z",
        discharge_date="2026-03-10T00:00:00Z"), org["coord_headers"])
    resp = api.create_ed_event(create_ed_event_payload(
        patient["id"], "INPATIENT_ADMISSION", "2026-04-09T00:00:00Z",
        discharge_date="2026-04-15T00:00:00Z"), org["coord_headers"])
    event = validate_success(resp, 201)
    assert event["is_readmission"] is True, "exactly 30 days must count as a readmission"


def test_readmission_at_31_days_not_flagged(api):
    """PRD 3.2: "Exactly 30 days still counts as a readmission; 31 days does not."
    A second admission on 2026-04-10, 31 days after a prior discharge on 2026-03-10, does not
    set is_readmission.

    Design: Difficulty/boundary_precision_check/readmission_exactly_30_days
    """
    org = bootstrap(api)
    patient = create_patient(api, org, full_name="Pat NoReadmit",
                             baseline_ed_visits_12mo=6, chronic_conditions_count=3)
    api.create_ed_event(create_ed_event_payload(
        patient["id"], "INPATIENT_ADMISSION", "2026-03-01T00:00:00Z",
        discharge_date="2026-03-10T00:00:00Z"), org["coord_headers"])
    resp = api.create_ed_event(create_ed_event_payload(
        patient["id"], "INPATIENT_ADMISSION", "2026-04-10T00:00:00Z",
        discharge_date="2026-04-16T00:00:00Z"), org["coord_headers"])
    event = validate_success(resp, 201)
    assert event["is_readmission"] is False, "31 days must not count as a readmission"


def test_patient_create_computes_high_risk_tier(api):
    """PRD 3.2: "The score is then the patient's baseline_ed_visits_12mo multiplied by two,
    plus the chronic_conditions_count multiplied by three, plus that recent-admission count
    multiplied by five. The tier follows from the score: a score of at least 20 is HIGH".
    A patient with baseline 8 and 3 chronic conditions scores 8*2 + 3*3 = 25 -> HIGH.

    Design: Corner/entities/patient_create_computes_risk_tier_high
    """
    org = bootstrap(api)
    resp = api.create_patient(create_patient_payload(
        full_name="Pat RiskHigh", date_of_birth="1950-01-01",
        baseline_ed_visits_12mo=8, chronic_conditions_count=3), org["coord_headers"])
    patient = validate_success(resp, 201)
    assert patient["risk_score"] == 25, f"expected risk_score 25, got {patient['risk_score']}"
    assert patient["risk_tier"] == "HIGH", f"expected HIGH, got {patient['risk_tier']}"


def test_patient_consent_defaults_false_when_omitted(api):
    """PRD 3.2: "a consent_on_file flag that defaults to false when omitted."

    Design: Corner/entities/patient_consent_defaults_false
    """
    org = bootstrap(api)
    payload = create_patient_payload(full_name="Pat NoConsent",
                                     baseline_ed_visits_12mo=2, chronic_conditions_count=0)
    payload.pop("consent_on_file", None)
    resp = api.create_patient(payload, org["coord_headers"])
    patient = validate_success(resp, 201)
    assert patient["consent_on_file"] is False, "omitted consent_on_file must default to false"


def test_risk_recomputed_on_new_admission(api):
    """PRD 3.2: "because a new event changes the patient's utilization history, the system
    recomputes the patient's risk_score and risk_tier."
    A patient scoring 6*2 + 2*3 = 18 (MODERATE) is re-scored to 6*2 + 2*3 + 1*5 = 23 (HIGH)
    once an INPATIENT_ADMISSION within the trailing year is recorded.

    Design: Corner/cross_cutting_complexity_layers/patient_risk_recomputed_on_admission_derived_field
    """
    org = bootstrap(api)
    patient = create_patient(api, org, full_name="Pat Reco",
                             baseline_ed_visits_12mo=6, chronic_conditions_count=2)
    assert patient["risk_tier"] == "MODERATE", f"pre: expected MODERATE, got {patient['risk_tier']}"
    api.create_ed_event(create_ed_event_payload(
        patient["id"], "INPATIENT_ADMISSION", "2026-02-15T00:00:00Z",
        discharge_date="2026-02-20T00:00:00Z"), org["coord_headers"])
    refreshed = validate_success(api.get_patient(patient["id"], org["coord_headers"]), 200)
    assert refreshed["risk_score"] == 23, f"expected risk_score 23, got {refreshed['risk_score']}"
    assert refreshed["risk_tier"] == "HIGH", f"expected HIGH, got {refreshed['risk_tier']}"
