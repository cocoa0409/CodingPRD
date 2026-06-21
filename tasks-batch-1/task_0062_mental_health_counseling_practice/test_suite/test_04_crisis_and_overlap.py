"""Crisis risk scoring, clinical-hold cascade, safety-plan gate, scheduling overlap.

Queue A (Difficulty): combinatorial_formula (risk score), transitive_cascade
(crisis hold), compensating_invariant (resolve restores ACTIVE),
priority_pair_validation_conflict (invalid_state vs safety_plan), resource_temporal_overlap.
Queue B (Corner): calculations (risk band), validations (safety plan).
"""
from test_helpers import (
    api_client, validate_error, get_success_data,
    create_associate_therapist, create_independent_therapist, create_patient,
    create_crisis_assessment, schedule_appointment, set_clock,
    make_therapist_headers, create_safety_plan_payload,
    TEST_USERS, ApiErrorId,
)

CD = TEST_USERS["clinical_director_headers"]
FD = TEST_USERS["front_desk_headers"]


def test_crisis_weighted_score_straddles_high_band():
    """PRD §3.8: "The raw score weights the four factors — ideation at 0.30, plan at
    0.30, means access at 0.25, and prior attempts at 0.15 — and that weighted sum is
    then divided by 3 and multiplied by 100 to normalize onto a 0-to-100 scale, rounded
    half up to two decimal places."
    PRD §3.8: "The band follows from the score: a score at or above 70 is HIGH, a score
    at or above 40 (but below 70) is MODERATE, and anything below 40 is LOW."

    Design: Difficulty/combinatorial_formula/crisis_weighted_score_nonlinear_band
    """
    therapist = create_associate_therapist(full_name="Dr C")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=2, means=2, prior=1)
    assert ca["risk_score"] == 71.67
    assert ca["risk_band"] == "HIGH"


def test_crisis_weighted_score_just_below_high_band():
    """PRD §3.8: "that weighted sum is then divided by 3 and multiplied by 100 to
    normalize onto a 0-to-100 scale, rounded half up to two decimal places."
    PRD §3.8: "The band follows from the score: a score at or above 70 is HIGH, a score
    at or above 40 (but below 70) is MODERATE, and anything below 40 is LOW."

    Design: Difficulty/combinatorial_formula/crisis_weighted_score_nonlinear_band
    """
    # 3/2/2/0: raw=0.30*3+0.30*2+0.25*2+0.15*0=1.7; 1.7/3*100=56.666...->? Recompute:
    # raw=0.9+0.6+0.5+0=2.0; 2.0/3*100=66.666...->66.67 MODERATE (just below HIGH 70).
    therapist = create_associate_therapist(full_name="Dr C2")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=2, means=2, prior=0)
    assert ca["risk_score"] == 66.67
    assert ca["risk_band"] == "MODERATE"


def test_crisis_high_risk_places_patient_on_hold():
    """PRD §3.8: "When the resulting band is HIGH, the assessment cascades to place the
    patient ON_CLINICAL_HOLD — which is precisely why a held patient's sessions cannot
    be rendered until the hold lifts."

    Design: Difficulty/transitive_cascade/crisis_high_risk_cascade_patient_hold
    """
    therapist = create_associate_therapist(full_name="Dr H")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    assert ca["risk_band"] == "HIGH"
    p = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p["status"] == "ON_CLINICAL_HOLD"


def test_crisis_high_risk_hold_blocks_subsequent_render():
    """PRD §3.8: "When the resulting band is HIGH, the assessment cascades to place the
    patient ON_CLINICAL_HOLD — which is precisely why a held patient's sessions cannot
    be rendered until the hold lifts."
    PRD §3.6: "rendering against a patient whose status is ON_CLINICAL_HOLD is rejected
    with ERR_PATIENT_ON_HOLD."

    Design: Difficulty/transitive_cascade/crisis_high_risk_cascade_patient_hold
    """
    from test_helpers import create_independent_therapist, schedule_appointment, \
        render_appointment, make_therapist_headers
    set_clock("2026-06-25T12:00:00Z")
    therapist = create_independent_therapist(license_number="LCC")
    patient = create_patient()
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-25T08:00:00Z", payment_path="SELF_PAY")
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    assert ca["risk_band"] == "HIGH"
    p = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p["status"] == "ON_CLINICAL_HOLD"
    resp = api_client.render_appointment(appt["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_PATIENT_ON_HOLD.value)


def test_resolve_high_risk_restores_patient_active():
    """PRD §3.8: "Resolving an assessment advances it from OPEN to RESOLVED"
    PRD §3.8: "When an assessment is resolved and the patient has no other open
    assessment remaining, the patient's hold is lifted and their status reverts to ACTIVE."

    Design: Difficulty/compensating_invariant/resolve_high_risk_restores_patient_active_status
    """
    therapist = create_associate_therapist(full_name="Dr R")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    get_success_data(api_client.create_safety_plan(
        create_safety_plan_payload(ca["id"]), make_therapist_headers(therapist["id"])))
    resolved = get_success_data(api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"])))
    assert resolved["status"] == "RESOLVED"
    p = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p["status"] == "ACTIVE"


def test_resolve_high_risk_advances_assessment_to_resolved():
    """PRD §3.8: "Resolving an assessment advances it from OPEN to RESOLVED, but if its
    band is HIGH and no safety plan exists for it, resolution is rejected with
    ERR_SAFETY_PLAN_REQUIRED."
    PRD §3.8: "When an assessment is resolved and the patient has no other open
    assessment remaining, the patient's hold is lifted and their status reverts to ACTIVE."

    Design: Difficulty/compensating_invariant/resolve_high_risk_restores_patient_active_status
    """
    therapist = create_associate_therapist(full_name="Dr R2")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    p_held = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p_held["status"] == "ON_CLINICAL_HOLD"
    get_success_data(api_client.create_safety_plan(
        create_safety_plan_payload(ca["id"]), make_therapist_headers(therapist["id"])))
    resolved = get_success_data(api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"])))
    assert resolved["status"] == "RESOLVED"
    p_after = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p_after["status"] == "ACTIVE"


def test_invalid_state_beats_safety_plan_on_double_resolve():
    """PRD §3.9: "Only then are state-machine preconditions evaluated — whether the
    target resource is in a state from which the requested transition is defined
    (ERR_INVALID_STATE) — followed by the domain safety and referential gates: the
    crisis safety-plan gate (ERR_SAFETY_PLAN_REQUIRED)"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_safety_plan_on_resolve
    """
    therapist = create_associate_therapist(full_name="Dr S")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    get_success_data(api_client.create_safety_plan(
        create_safety_plan_payload(ca["id"]), make_therapist_headers(therapist["id"])))
    get_success_data(api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"])))  # now RESOLVED
    resp = api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_state_check_precedes_safety_gate_on_resolved_high_assessment():
    """PRD §3.9: "Only then are state-machine preconditions evaluated — whether the
    target resource is in a state from which the requested transition is defined
    (ERR_INVALID_STATE) — followed by the domain safety and referential gates: the
    crisis safety-plan gate (ERR_SAFETY_PLAN_REQUIRED)"

    Design: Difficulty/priority_pair_validation_conflict/invalid_state_beats_safety_plan_on_resolve
    """
    # A HIGH assessment is given a safety plan and resolved. Resolving the now-RESOLVED
    # assessment again: the state check (RESOLVED has no resolve transition) fires before
    # the safety-plan gate, so ERR_INVALID_STATE — not ERR_SAFETY_PLAN_REQUIRED.
    therapist = create_associate_therapist(full_name="Dr S2")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    get_success_data(api_client.create_safety_plan(
        create_safety_plan_payload(ca["id"]), make_therapist_headers(therapist["id"])))
    first = get_success_data(api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"])))
    assert first["status"] == "RESOLVED"
    resp = api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


def test_therapist_half_open_overlap_adjacency_allowed_overlap_rejected():
    """PRD §3.5: "For the rendering clinician, the new session's interval is treated as
    half-open — running from start_at up to but not including its end — so a new session
    that overlaps any existing non-terminal session for the same clinician is rejected
    with ERR_THERAPIST_DOUBLE_BOOKED, while sessions that merely abut end-to-start are
    permitted."

    Design: Difficulty/resource_temporal_overlap/therapist_half_open_overlap_adjacency_allowed
    """
    therapist = create_associate_therapist(full_name="Dr Ov")
    p1 = create_patient(full_name="Pt O1")
    p2 = create_patient(full_name="Pt O2")
    schedule_appointment(
        therapist["id"], p1["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-12T08:00:00Z", payment_path="SELF_PAY")
    # Adjacency: starts exactly when prior ends (08:45) -> ACCEPTED.
    adj = schedule_appointment(
        therapist["id"], p2["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-12T08:45:00Z", payment_path="SELF_PAY")
    assert adj["status"] == "SCHEDULED"
    # One minute earlier overlaps -> rejected.
    resp = api_client.create_appointment(
        {"therapist_id": therapist["id"], "patient_id": p2["id"], "cpt_code": "90834",
         "modality": "IN_PERSON", "start_at": "2026-06-12T08:44:00Z",
         "duration_minutes": 45, "payment_path": "SELF_PAY"}, FD)
    validate_error(resp, ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value)


def test_therapist_exact_overlap_rejected():
    """PRD §3.5: "For the rendering clinician, the new session's interval is treated as
    half-open — running from start_at up to but not including its end — so a new session
    that overlaps any existing non-terminal session for the same clinician is rejected
    with ERR_THERAPIST_DOUBLE_BOOKED, while sessions that merely abut end-to-start are
    permitted."

    Design: Difficulty/resource_temporal_overlap/therapist_half_open_overlap_adjacency_allowed
    """
    therapist = create_associate_therapist(full_name="Dr Ov2")
    p1 = create_patient(full_name="Pt Ova")
    p2 = create_patient(full_name="Pt Ovb")
    schedule_appointment(
        therapist["id"], p1["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-15T08:00:00Z", payment_path="SELF_PAY")
    # Identical start time for the same clinician -> overlap -> rejected.
    resp = api_client.create_appointment(
        {"therapist_id": therapist["id"], "patient_id": p2["id"], "cpt_code": "90834",
         "modality": "IN_PERSON", "start_at": "2026-06-15T08:00:00Z",
         "duration_minutes": 45, "payment_path": "SELF_PAY"}, FD)
    validate_error(resp, ApiErrorId.ERR_THERAPIST_DOUBLE_BOOKED.value)


def test_patient_closed_interval_adjacency_rejected():
    """PRD §3.5: "For the patient, the interval is treated as closed — including both
    endpoints — so a new session that touches or overlaps any existing non-terminal
    session for the same patient is rejected with ERR_PATIENT_DOUBLE_BOOKED, and even
    back-to-back adjacency is disallowed."

    Design: Difficulty/resource_temporal_overlap/patient_closed_interval_adjacency_rejected
    """
    t1 = create_associate_therapist(full_name="Dr T1")
    t2 = create_associate_therapist(full_name="Dr T2")
    patient = create_patient(full_name="Pt PC")
    schedule_appointment(
        t1["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-13T08:00:00Z", payment_path="SELF_PAY")
    # Back-to-back (08:45) for same patient -> rejected (closed interval).
    resp = api_client.create_appointment(
        {"therapist_id": t2["id"], "patient_id": patient["id"], "cpt_code": "90834",
         "modality": "IN_PERSON", "start_at": "2026-06-13T08:45:00Z",
         "duration_minutes": 45, "payment_path": "SELF_PAY"}, FD)
    validate_error(resp, ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED.value)


def test_patient_overlapping_interval_rejected():
    """PRD §3.5: "For the patient, the interval is treated as closed — including both
    endpoints — so a new session that touches or overlaps any existing non-terminal
    session for the same patient is rejected with ERR_PATIENT_DOUBLE_BOOKED, and even
    back-to-back adjacency is disallowed."

    Design: Difficulty/resource_temporal_overlap/patient_closed_interval_adjacency_rejected
    """
    t1 = create_associate_therapist(full_name="Dr PT1")
    t2 = create_associate_therapist(full_name="Dr PT2")
    patient = create_patient(full_name="Pt PC2")
    schedule_appointment(
        t1["id"], patient["id"], cpt_code="90834", duration_minutes=45,
        start_at="2026-06-16T08:00:00Z", payment_path="SELF_PAY")
    # Starts mid-way through the first session for the same patient -> overlap -> rejected.
    resp = api_client.create_appointment(
        {"therapist_id": t2["id"], "patient_id": patient["id"], "cpt_code": "90834",
         "modality": "IN_PERSON", "start_at": "2026-06-16T08:30:00Z",
         "duration_minutes": 45, "payment_path": "SELF_PAY"}, FD)
    validate_error(resp, ApiErrorId.ERR_PATIENT_DOUBLE_BOOKED.value)


def test_crisis_risk_moderate_band_no_hold():
    """PRD §3.8: "The band follows from the score: a score at or above 70 is HIGH, a
    score at or above 40 (but below 70) is MODERATE, and anything below 40 is LOW."
    PRD §3.8: "When the resulting band is HIGH, the assessment cascades to place the
    patient ON_CLINICAL_HOLD"

    Design: Corner/calculations/crisis_risk_low_band_boundary
    """
    therapist = create_associate_therapist(full_name="Dr Lo")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=2, plan=2, means=1, prior=0)
    assert ca["risk_score"] == 48.33
    assert ca["risk_band"] == "MODERATE"
    p = get_success_data(api_client.get_patient(patient["id"], CD))
    assert p["status"] == "ACTIVE"


def test_safety_plan_required_on_resolve_high_risk():
    """PRD §3.8: "Resolving an assessment advances it from OPEN to RESOLVED, but if its
    band is HIGH and no safety plan exists for it, resolution is rejected with
    ERR_SAFETY_PLAN_REQUIRED."

    Design: Corner/validations/safety_plan_required_on_resolve_high_risk
    """
    therapist = create_associate_therapist(full_name="Dr SR")
    patient = create_patient()
    ca = create_crisis_assessment(patient["id"], therapist["id"],
                                  ideation=3, plan=3, means=3, prior=3)
    resp = api_client.resolve_crisis_assessment(
        ca["id"], make_therapist_headers(therapist["id"]))
    validate_error(resp, ApiErrorId.ERR_SAFETY_PLAN_REQUIRED.value)
