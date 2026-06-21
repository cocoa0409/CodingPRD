"""Composite setup helpers for multi-step test prerequisites.

Uses get_success_data() (lenient validator) internally so setup failures surface
as clear "setup failed" errors rather than confusing assertion failures.

The harness restarts the server before every test, so each fixture builds its
preconditions from scratch using only PRD-declared endpoints.

Identity threading: Therapist is entity_backed. Any ownership-gated call
(render / complete / sign / cosign) MUST use make_therapist_headers(therapist_id)
with the rendering clinician's id — never the shared therapist constant.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .factories import (
    create_therapist_payload, create_state_license_payload,
    create_patient_payload, create_payer_contract_payload,
    create_insurance_policy_payload, create_appointment_payload,
    create_clinical_note_payload, create_crisis_assessment_payload,
    create_safety_plan_payload,
)
from .test_users import TEST_USERS, make_therapist_headers

CD = TEST_USERS["clinical_director_headers"]
FD = TEST_USERS["front_desk_headers"]
BILLER = TEST_USERS["biller_headers"]


# ─── Clock ────────────────────────────────────────────────
def set_clock(iso8601: str):
    """Set server UTC clock (director-only test capability)."""
    get_success_data(api_client.set_clock(iso8601, CD))


# ─── Tier 1: Therapist credential progression ─────────────
def create_associate_therapist(**overrides):
    """Create a fresh ASSOCIATE therapist. Returns the therapist dict."""
    return get_success_data(api_client.create_therapist(
        create_therapist_payload(**overrides), CD))


def create_independent_therapist(state_code="CA", license_number="L-IND",
                                 expires_on="2030-01-01T00:00:00Z",
                                 telehealth_authorized=None, **overrides):
    """Create a therapist, inject the hours needed for INDEPENDENT, issue a
    state license, and promote twice (ASSOCIATE -> SUPERVISED_PRACTICE -> INDEPENDENT).
    Returns the INDEPENDENT therapist dict (re-fetched, so version is current)."""
    t = create_associate_therapist(**overrides)
    tid = t["id"]
    get_success_data(api_client.inject_therapist_hours(
        {"therapist_id": tid, "verified_direct_hours": 3000,
         "verified_supervision_hours": 200}, CD))
    lic_payload = create_state_license_payload(
        tid, state_code=state_code, license_number=license_number, expires_on=expires_on)
    if telehealth_authorized is not None:
        lic_payload["telehealth_authorized"] = telehealth_authorized
    get_success_data(api_client.create_state_license(lic_payload, CD))
    # Injecting hours bumps the therapist version, so re-fetch the current
    # version immediately before the first promote (avoid stale-version setup failure).
    current = get_success_data(api_client.get_therapist(tid, CD))
    p1 = get_success_data(api_client.promote_therapist(
        tid, {"expected_therapist_version": current["version"]}, CD))
    get_success_data(api_client.promote_therapist(
        tid, {"expected_therapist_version": p1["version"]}, CD))
    return get_success_data(api_client.get_therapist(tid, CD))


def create_licensed_associate(state_code="CA", license_number="L-ASC",
                              expires_on="2030-01-01T00:00:00Z",
                              telehealth_authorized=None, supervisor_id=None, **overrides):
    """Create an ASSOCIATE therapist (requires_supervision true) with one ACTIVE
    license. Returns the therapist dict."""
    payload = create_therapist_payload(**overrides)
    if supervisor_id is not None:
        payload["supervisor_id"] = supervisor_id
    t = get_success_data(api_client.create_therapist(payload, CD))
    lic_payload = create_state_license_payload(
        t["id"], state_code=state_code, license_number=license_number, expires_on=expires_on)
    if telehealth_authorized is not None:
        lic_payload["telehealth_authorized"] = telehealth_authorized
    get_success_data(api_client.create_state_license(lic_payload, CD))
    return t


# ─── Tier 1: Patients and coverage ────────────────────────
def create_patient(income=90000, household=1, state_code="CA", **overrides):
    return get_success_data(api_client.create_patient(
        create_patient_payload(annual_household_income=income, household_size=household,
                               location_state_code=state_code, **overrides), FD))


def create_payer_contract(in_network=True, rate_90791=18000, rate_90834=13000,
                          payer_name="Payer"):
    return get_success_data(api_client.create_payer_contract(
        create_payer_contract_payload(in_network=in_network, payer_name=payer_name,
                                      contracted_rate_90791_cents=rate_90791,
                                      contracted_rate_90834_cents=rate_90834), BILLER))


def create_policy(patient_id, contract_id, cost_share_model="COPAY", copay_cents=None,
                  coinsurance_rate=None, deductible_total_cents=0):
    overrides = {"deductible_total_cents": deductible_total_cents}
    if copay_cents is not None:
        overrides["copay_cents"] = copay_cents
    if coinsurance_rate is not None:
        overrides["coinsurance_rate"] = coinsurance_rate
    return get_success_data(api_client.create_insurance_policy(
        create_insurance_policy_payload(patient_id, contract_id,
                                        cost_share_model=cost_share_model, **overrides), FD))


# ─── Tier 2/3: Appointment lifecycle helpers ──────────────
def schedule_appointment(therapist_id, patient_id, **overrides):
    """Create a SCHEDULED appointment. Returns the appointment dict."""
    return get_success_data(api_client.create_appointment(
        create_appointment_payload(therapist_id, patient_id, **overrides), FD))


def render_appointment(appointment_id, therapist_id):
    """Render an appointment as the owning therapist. Returns the rendered dict."""
    return get_success_data(api_client.render_appointment(
        appointment_id, make_therapist_headers(therapist_id)))


def sign_note_for(appointment_id, therapist_id):
    """Create a draft note for an appointment and sign it as the rendering
    therapist. Returns the SIGNED note dict."""
    note = get_success_data(api_client.create_clinical_note(
        create_clinical_note_payload(appointment_id), make_therapist_headers(therapist_id)))
    return get_success_data(api_client.sign_clinical_note(
        note["id"], make_therapist_headers(therapist_id)))


def cosign_note(note_id, supervisor_id):
    """Co-sign a SIGNED note as the supervisor. Returns the CO_SIGNED note dict."""
    return get_success_data(api_client.cosign_clinical_note(
        note_id, make_therapist_headers(supervisor_id)))


def complete_appointment(appointment_id, therapist_id):
    """Complete a rendered appointment (note already SIGNED/CO_SIGNED).
    Returns the COMPLETED appointment dict."""
    return get_success_data(api_client.complete_appointment(
        appointment_id, make_therapist_headers(therapist_id)))


def render_sign_complete(appointment_id, therapist_id):
    """Render -> create+sign note -> complete, for an INDEPENDENT therapist
    (note need not be co-signed). Returns the COMPLETED appointment dict."""
    render_appointment(appointment_id, therapist_id)
    sign_note_for(appointment_id, therapist_id)
    return complete_appointment(appointment_id, therapist_id)


def setup_completed_insurance_appointment(
        clock="2026-06-01T12:00:00Z", appt_start="2026-06-01T08:00:00Z",
        cpt_code="90834", duration_minutes=45,
        in_network=True, rate_90791=18000, rate_90834=13000,
        cost_share_model="COPAY", copay_cents=2500, coinsurance_rate=None,
        deductible_total_cents=0):
    """Full chain to a COMPLETED INSURANCE appointment by an INDEPENDENT CA therapist.

    Returns dict with keys: therapist, patient, contract, policy, appointment
    (the COMPLETED appointment, version current).
    """
    set_clock(clock)
    therapist = create_independent_therapist()
    contract = create_payer_contract(in_network=in_network, rate_90791=rate_90791,
                                     rate_90834=rate_90834)
    patient = create_patient()
    policy = create_policy(patient["id"], contract["id"], cost_share_model=cost_share_model,
                           copay_cents=copay_cents, coinsurance_rate=coinsurance_rate,
                           deductible_total_cents=deductible_total_cents)
    appt = schedule_appointment(
        therapist["id"], patient["id"], cpt_code=cpt_code, duration_minutes=duration_minutes,
        start_at=appt_start, payment_path="INSURANCE", insurance_policy_id=policy["id"])
    completed = render_sign_complete(appt["id"], therapist["id"])
    return {"therapist": therapist, "patient": patient, "contract": contract,
            "policy": policy, "appointment": completed}


def setup_submitted_claim(**kwargs):
    """Build a COMPLETED insurance appointment, then open a claim (COMPLETED -> CLAIMED).

    Returns dict adding 'claim' (SUBMITTED, version current) to
    setup_completed_insurance_appointment's keys.
    """
    ctx = setup_completed_insurance_appointment(**kwargs)
    appt = ctx["appointment"]
    claim = get_success_data(api_client.create_claim(
        {"appointment_id": appt["id"], "expected_appointment_version": appt["version"]}, BILLER))
    ctx["claim"] = claim
    return ctx


def adjudicate(claim_id, version):
    return get_success_data(api_client.adjudicate_claim(
        claim_id, {"expected_claim_version": version}, BILLER))


# ─── Crisis assessment / safety plan ──────────────────────
def create_crisis_assessment(patient_id, therapist_id, ideation=0, plan=0, means=0, prior=0):
    """Create a crisis assessment as the assessing therapist. Returns the dict."""
    return get_success_data(api_client.create_crisis_assessment(
        create_crisis_assessment_payload(
            patient_id, therapist_id, ideation_score=ideation, plan_score=plan,
            means_access_score=means, prior_attempts_score=prior),
        make_therapist_headers(therapist_id)))


def setup_high_risk_assessment(with_safety_plan=False, resolve=False):
    """Create a patient + therapist + a HIGH-risk OPEN crisis assessment
    (3/3/3/3 -> patient ON_CLINICAL_HOLD). Optionally attach a SafetyPlan and resolve.

    Returns dict with keys: therapist, patient, assessment (+ safety_plan if added).
    """
    therapist = create_associate_therapist(full_name="Crisis Clinician")
    patient = create_patient()
    assessment = create_crisis_assessment(
        patient["id"], therapist["id"], ideation=3, plan=3, means=3, prior=3)
    out = {"therapist": therapist, "patient": patient, "assessment": assessment}
    if with_safety_plan or resolve:
        sp = get_success_data(api_client.create_safety_plan(
            create_safety_plan_payload(assessment["id"]),
            make_therapist_headers(therapist["id"])))
        out["safety_plan"] = sp
    if resolve:
        get_success_data(api_client.resolve_crisis_assessment(
            assessment["id"], make_therapist_headers(therapist["id"])))
    return out
