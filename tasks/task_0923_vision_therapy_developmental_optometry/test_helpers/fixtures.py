"""Composite setup helpers.

Every helper here acts as an ordinary API client: it builds all of its
preconditions from scratch through published endpoints, because the server
starts each test against an empty database.  Setup calls use the lenient
`get_success_data` validator so a broken precondition surfaces as a clear
"Setup step failed" message rather than a confusing downstream assertion.
"""

from typing import Any, Dict, List, Optional

from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import BASE_CLOCK_UTC
from .test_users import (
    make_billing_specialist_headers,
    make_clinic_admin_headers,
    make_front_desk_headers,
    make_optometrist_headers,
    make_patient_user_headers,
    make_therapy_assistant_headers,
    make_vision_therapist_headers,
)


# --------------------------------------------------------------------------
# Tier 0: primitives
# --------------------------------------------------------------------------


def set_clock(to_iso8601: str, headers: Optional[dict] = None) -> dict:
    """Move the server's logical UTC clock."""
    return get_success_data(
        api_client.set_clock(to_iso8601, headers or make_clinic_admin_headers())
    )


def new_patient(**overrides) -> dict:
    return get_success_data(
        api_client.create_patient(
            f.create_patient_payload(**overrides), make_front_desk_headers()
        )
    )


def new_therapist(**overrides) -> dict:
    return get_success_data(
        api_client.create_therapist(
            f.create_therapist_payload(**overrides), make_clinic_admin_headers()
        )
    )


def new_room(**overrides) -> dict:
    return get_success_data(
        api_client.create_room(f.create_room_payload(**overrides), make_clinic_admin_headers())
    )


def new_medical_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer(
            f.create_medical_payer_payload(**overrides), make_clinic_admin_headers()
        )
    )


def new_vision_payer(**overrides) -> dict:
    return get_success_data(
        api_client.create_payer(
            f.create_vision_payer_payload(**overrides), make_clinic_admin_headers()
        )
    )


def new_coverage(patient_id: str, payer_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_coverage(
            f.create_coverage_payload(patient_id, payer_id, **overrides),
            make_billing_specialist_headers(),
        )
    )


def new_authorization(patient_id: str, coverage_id: str, **overrides) -> dict:
    return get_success_data(
        api_client.create_authorization(
            f.create_authorization_payload(patient_id, coverage_id, **overrides),
            make_billing_specialist_headers(),
        )
    )


def read_authorization(authorization_id: str) -> dict:
    return get_success_data(
        api_client.get_authorization(authorization_id, make_billing_specialist_headers())
    )


def read_coverage(coverage_id: str) -> dict:
    return get_success_data(
        api_client.get_coverage(coverage_id, make_billing_specialist_headers())
    )


def read_plan(plan_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.get_therapy_plan(plan_id, headers or make_front_desk_headers())
    )


def read_session(session_id: str) -> dict:
    return get_success_data(api_client.get_session(session_id, make_front_desk_headers()))


def read_assessment(assessment_id: str) -> dict:
    return get_success_data(
        api_client.get_assessment(assessment_id, make_front_desk_headers())
    )


def read_patient(patient_id: str) -> dict:
    return get_success_data(api_client.get_patient(patient_id, make_front_desk_headers()))


def read_kit_item(kit_item_id: str) -> dict:
    return get_success_data(api_client.get_kit_item(kit_item_id, make_front_desk_headers()))


def read_kit_loan(loan_id: str) -> dict:
    return get_success_data(api_client.get_kit_loan(loan_id, make_front_desk_headers()))


def read_claim(claim_id: str) -> dict:
    return get_success_data(
        api_client.get_claim(claim_id, make_billing_specialist_headers())
    )


def read_referral(referral_id: str) -> dict:
    return get_success_data(api_client.get_referral(referral_id, make_front_desk_headers()))


def read_prescription(prescription_id: str) -> dict:
    return get_success_data(
        api_client.get_occlusion_prescription(prescription_id, make_front_desk_headers())
    )


def read_phase(plan_id: str, phase_id: str) -> dict:
    """Phases are addressed through their plan; return the one row wanted."""
    data = get_success_data(
        api_client.list_phases(plan_id, make_front_desk_headers(), {"limit": 100, "offset": 0})
    )
    for row in data:
        if row["id"] == phase_id:
            return row
    raise AssertionError(f"Setup step failed: phase {phase_id} not present on plan {plan_id}")


def auth_version(authorization_id: str) -> int:
    """Re-read the pool's current version for the next OCC-guarded booking."""
    return read_authorization(authorization_id)["version"]


def coverage_version(coverage_id: str) -> int:
    return read_coverage(coverage_id)["version"]


def plan_version(plan_id: str) -> int:
    return read_plan(plan_id)["version"]


# --------------------------------------------------------------------------
# Tier 1: the binocular battery
# --------------------------------------------------------------------------

DEFAULT_EVAL_MEASUREMENTS: List[dict] = [
    f.npc_measurement_payload(12.0, 16.0),
    f.amplitude_measurement_payload(8.0),
    f.vergence_measurement_payload(8.0),
    f.symptom_measurement_payload(34),
]


def open_assessment(patient_id: str, therapist_id: str, **overrides) -> dict:
    """Open a battery in DRAFT, acting as the optometrist who performs it."""
    return get_success_data(
        api_client.create_assessment(
            f.create_assessment_payload(patient_id, therapist_id, **overrides),
            make_optometrist_headers(therapist_id),
        )
    )


def append_measurement(assessment_id: str, payload: dict, therapist_id: str) -> dict:
    return get_success_data(
        api_client.create_measurement(
            assessment_id, payload, make_optometrist_headers(therapist_id)
        )
    )


def finalize(assessment_id: str, therapist_id: str) -> dict:
    return get_success_data(
        api_client.finalize_assessment(assessment_id, make_optometrist_headers(therapist_id))
    )


def sign(assessment_id: str, therapist_id: str) -> dict:
    return get_success_data(
        api_client.sign_assessment(assessment_id, make_optometrist_headers(therapist_id))
    )


def build_battery(
    patient_id: str,
    performed_by: str,
    measurements: Optional[List[dict]] = None,
    finalize_it: bool = True,
    sign_by: Optional[str] = None,
    **assessment_overrides,
) -> dict:
    """Open a battery, append readings, optionally finalize and sign it."""
    assessment = open_assessment(patient_id, performed_by, **assessment_overrides)
    for payload in measurements if measurements is not None else DEFAULT_EVAL_MEASUREMENTS:
        append_measurement(assessment["id"], payload, performed_by)
    if finalize_it:
        assessment = finalize(assessment["id"], performed_by)
    if sign_by is not None:
        assessment = sign(assessment["id"], sign_by)
    return assessment


def build_signed_evaluation(
    patient_id: str, optometrist_id: str, measurements: Optional[List[dict]] = None
) -> dict:
    """The intake battery: DRAFT -> FINALIZED -> SIGNED by one optometrist."""
    return build_battery(
        patient_id,
        optometrist_id,
        measurements=measurements,
        finalize_it=True,
        sign_by=optometrist_id,
    )


def build_signed_reassessment(
    patient_id: str,
    plan_id: str,
    performed_by: str,
    signed_by: str,
    measurements: Optional[List[dict]] = None,
    purpose: str = "PROGRESS",
    encounter_date: str = "2026-06-01",
) -> dict:
    """A progress battery; the signer must differ from the performer."""
    return build_battery(
        patient_id,
        performed_by,
        measurements=measurements if measurements is not None else [f.npc_measurement_payload(7.0, 9.0)],
        finalize_it=True,
        sign_by=signed_by,
        assessment_type="REASSESSMENT",
        purpose=purpose,
        encounter_date=encounter_date,
        plan_id=plan_id,
    )


# --------------------------------------------------------------------------
# Tier 2: the standard clinic scenario
# --------------------------------------------------------------------------


class Scenario(dict):
    """A dict of the ids a fully wired clinic scenario produced.

    Attribute access is provided purely for readability inside tests.
    """

    def __getattr__(self, item):
        try:
            return self[item]
        except KeyError as exc:  # pragma: no cover - developer error
            raise AttributeError(item) from exc


def setup_clinic_configuration(clock: Optional[str] = BASE_CLOCK_UTC, **patient_overrides) -> Scenario:
    """Clock, one patient, one medical payer + coverage, four clinicians, three rooms."""
    if clock is not None:
        set_clock(clock)

    patient = new_patient(**patient_overrides)
    payer_med = new_medical_payer()
    coverage_kwargs = {
        "member_number": "M-1001",
        "deductible_total": 200.00,
        "deductible_met": 150.00,
    }
    cov_med = new_coverage(patient["id"], payer_med["id"], **coverage_kwargs)

    od1 = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    od2 = new_therapist(full_name="Dr Osei", credential="OPTOMETRIST")
    cvt1 = new_therapist(full_name="Kim CVT", credential="CERTIFIED_VISION_THERAPIST")
    vta1 = new_therapist(full_name="Sam VTA", credential="VISION_THERAPY_ASSISTANT")

    room_a = new_room(name="Room A", equipment_class="STANDARD")
    room_b = new_room(name="Room B", equipment_class="VECTOGRAM_SUITE")
    room_c = new_room(name="Room C", equipment_class="COMPUTER_ORTHOPTICS")

    return Scenario(
        pt=patient["id"],
        patient=patient,
        payer_med=payer_med["id"],
        payer_med_row=payer_med,
        cov_med=cov_med["id"],
        cov_med_v=cov_med["version"],
        cov_med_row=cov_med,
        od1=od1["id"],
        od2=od2["id"],
        cvt1=cvt1["id"],
        vta1=vta1["id"],
        od1_row=od1,
        od2_row=od2,
        cvt1_row=cvt1,
        vta1_row=vta1,
        room_a=room_a["id"],
        room_b=room_b["id"],
        room_c=room_c["id"],
        hdr_admin=make_clinic_admin_headers(),
        hdr_front=make_front_desk_headers(),
        hdr_biller=make_billing_specialist_headers(),
        hdr_od1=make_optometrist_headers(od1["id"]),
        hdr_od2=make_optometrist_headers(od2["id"]),
        hdr_cvt1=make_vision_therapist_headers(cvt1["id"]),
        hdr_vta1=make_therapy_assistant_headers(vta1["id"]),
        hdr_patient=make_patient_user_headers(patient["id"]),
    )


def setup_active_plan(
    clock: Optional[str] = BASE_CLOCK_UTC,
    patient_overrides: Optional[Dict[str, Any]] = None,
    eval_measurements: Optional[List[dict]] = None,
    visits_authorized: int = 12,
    window_start_date: str = "2026-06-01",
    window_end_date: str = "2026-12-01",
    discharge_criteria_mode: str = "METRIC",
    prescribed_home_sessions_per_week: int = 1,
    phase_count: int = 2,
    required_mastery_count: int = 2,
    activate: bool = True,
    coverage_overrides: Optional[Dict[str, Any]] = None,
) -> Scenario:
    """The scenario nearly every claim needs.

    Clock -> patient -> medical payer + coverage -> clinicians -> rooms ->
    signed EVALUATION -> authorization pool -> therapy plan -> phases ->
    activation.  Returns every id the tests reference.
    """
    scn = setup_clinic_configuration(clock=clock, **(patient_overrides or {}))

    if coverage_overrides:
        cov = new_coverage(scn["pt"], scn["payer_med"], **coverage_overrides)
        scn["cov_med"] = cov["id"]
        scn["cov_med_v"] = cov["version"]
        scn["cov_med_row"] = cov

    ev1 = build_signed_evaluation(
        scn["pt"],
        scn["od1"],
        measurements=eval_measurements if eval_measurements is not None else DEFAULT_EVAL_MEASUREMENTS,
    )
    scn["ev1"] = ev1["id"]
    scn["ev1_row"] = ev1

    auth = new_authorization(
        scn["pt"],
        scn["cov_med"],
        visits_authorized=visits_authorized,
        window_start_date=window_start_date,
        window_end_date=window_end_date,
    )
    scn["auth"] = auth["id"]
    scn["auth_v1"] = auth["version"]

    plan = get_success_data(
        api_client.create_therapy_plan(
            f.create_plan_payload(
                scn["pt"],
                scn["ev1"],
                discharge_criteria_mode=discharge_criteria_mode,
                prescribed_home_sessions_per_week=prescribed_home_sessions_per_week,
            ),
            scn["hdr_od1"],
        )
    )
    scn["plan"] = plan["id"]
    scn["plan_row"] = plan

    phase_ids = []
    for index in range(1, phase_count + 1):
        phase = get_success_data(
            api_client.create_phase(
                scn["plan"],
                f.create_phase_payload(index, required_mastery_count=required_mastery_count),
                scn["hdr_od1"],
            )
        )
        phase_ids.append(phase["id"])
    scn["phases"] = phase_ids
    for position, phase_id in enumerate(phase_ids, start=1):
        scn[f"ph{position}"] = phase_id

    if activate:
        activated = get_success_data(
            api_client.activate_plan(
                scn["plan"], {"authorization_id": scn["auth"]}, scn["hdr_od1"]
            )
        )
        scn["plan_v"] = activated["version"]
        scn["plan_row"] = activated

    return scn


# --------------------------------------------------------------------------
# Tier 3: session lifecycle shortcuts
# --------------------------------------------------------------------------


def schedule_session(
    scn: Scenario,
    therapist_id: Optional[str] = None,
    room_id: Optional[str] = None,
    scheduled_start_at: str = "2026-06-10T09:00:00Z",
    scheduled_end_at: str = "2026-06-10T10:00:00Z",
    procedure_code: str = "TIMED_THERAPEUTIC_ACTIVITY",
    expected_authorization_version: Optional[int] = None,
    headers: Optional[dict] = None,
) -> dict:
    """Book one in-office session, re-reading the pool version when not pinned."""
    version = (
        expected_authorization_version
        if expected_authorization_version is not None
        else auth_version(scn["auth"])
    )
    return get_success_data(
        api_client.create_session(
            scn["plan"],
            f.create_session_payload(
                therapist_id or scn["cvt1"],
                room_id or scn["room_a"],
                scheduled_start_at,
                scheduled_end_at,
                version,
                procedure_code=procedure_code,
            ),
            headers or scn["hdr_front"],
        )
    )


def check_in(scn: Scenario, session_id: str) -> dict:
    return get_success_data(api_client.check_in_session(session_id, scn["hdr_front"]))


def complete_session(
    scn: Scenario,
    session_id: str,
    performed_at: str,
    timed_minutes: int,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    return get_success_data(
        api_client.complete_session(
            session_id,
            f.complete_session_payload(performed_at, timed_minutes, **overrides),
            headers or scn["hdr_cvt1"],
        )
    )


def deliver_session(
    scn: Scenario,
    scheduled_start_at: str = "2026-06-10T09:00:00Z",
    scheduled_end_at: str = "2026-06-10T10:00:00Z",
    performed_at: str = "2026-06-10T09:55:00Z",
    timed_minutes: int = 45,
    procedure_code: str = "TIMED_THERAPEUTIC_ACTIVITY",
    therapist_id: Optional[str] = None,
    room_id: Optional[str] = None,
    complete_headers: Optional[dict] = None,
    **complete_overrides,
) -> dict:
    """Schedule -> check in -> complete, returning the COMPLETED session row."""
    session = schedule_session(
        scn,
        therapist_id=therapist_id,
        room_id=room_id,
        scheduled_start_at=scheduled_start_at,
        scheduled_end_at=scheduled_end_at,
        procedure_code=procedure_code,
    )
    check_in(scn, session["id"])
    return complete_session(
        scn,
        session["id"],
        performed_at,
        timed_minutes,
        headers=complete_headers,
        **complete_overrides,
    )


def log_home_session(
    scn: Scenario, performed_at: str, timed_minutes: int = 20, **overrides
) -> dict:
    return get_success_data(
        api_client.create_home_session(
            scn["plan"],
            f.create_home_session_payload(performed_at, timed_minutes, **overrides),
            scn["hdr_patient"],
        )
    )


def attest_home_session(scn: Scenario, session_id: str, statement: str = "Completed as prescribed") -> dict:
    return get_success_data(
        api_client.attest_session(
            session_id, {"attestation_statement": statement}, scn["hdr_patient"]
        )
    )


def log_and_attest_home_sessions(
    scn: Scenario, performed_ats: List[str], timed_minutes: int = 20
) -> List[dict]:
    """Log and attest one home session per instant; only attested rows count."""
    rows = []
    for performed_at in performed_ats:
        logged = log_home_session(scn, performed_at, timed_minutes)
        rows.append(attest_home_session(scn, logged["id"]))
    return rows


def record_mastery(scn: Scenario, phase_id: str, mastered_delta: int = 2) -> dict:
    return get_success_data(
        api_client.record_mastery(phase_id, {"mastered_delta": mastered_delta}, scn["hdr_od1"])
    )


def advance_phase(scn: Scenario, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.advance_phase(scn["plan"], headers or scn["hdr_od1"])
    )


# --------------------------------------------------------------------------
# Tier 4: kit, claims, referrals, occlusion
# --------------------------------------------------------------------------


def new_kit_item(**overrides) -> dict:
    return get_success_data(
        api_client.create_kit_item(
            f.create_kit_item_payload(**overrides), make_clinic_admin_headers()
        )
    )


def request_loan(scn: Scenario, kit_item_id: str, quantity: int = 1) -> dict:
    return get_success_data(
        api_client.create_kit_loan(
            f.create_kit_loan_payload(kit_item_id, scn["pt"], scn["plan"], quantity=quantity),
            scn["hdr_front"],
        )
    )


def fulfill_loan(scn: Scenario, loan_id: str, due_at: Optional[str] = "2026-07-01T00:00:00Z") -> dict:
    payload = {"due_at": due_at} if due_at else {}
    return get_success_data(
        api_client.fulfill_kit_loan(loan_id, scn["hdr_front"], payload)
    )


def checked_out_loan(scn: Scenario, quantity: int = 1, **item_overrides) -> tuple:
    """Catalogue an item, request it and hand it over.  Returns (item, loan)."""
    item = new_kit_item(**item_overrides)
    loan = request_loan(scn, item["id"], quantity=quantity)
    loan = fulfill_loan(scn, loan["id"])
    return item, loan


def open_claim(
    scn: Scenario,
    service_class: str = "THERAPY_SESSION",
    service_date: str = "2026-06-10",
    coverage_id: Optional[str] = None,
    expected_coverage_version: Optional[int] = None,
    headers: Optional[dict] = None,
    **overrides,
) -> dict:
    cov_id = coverage_id or scn["cov_med"]
    version = (
        expected_coverage_version
        if expected_coverage_version is not None
        else coverage_version(cov_id)
    )
    return get_success_data(
        api_client.create_claim(
            f.create_claim_payload(
                scn["pt"], cov_id, service_class, service_date, version, **overrides
            ),
            headers or scn["hdr_biller"],
        )
    )


def submit_claim(scn: Scenario, claim_id: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.submit_claim(claim_id, headers or scn["hdr_biller"])
    )


def adjudicate(scn: Scenario, claim_id: str, outcome: str, headers: Optional[dict] = None, **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api_client.adjudicate_claim(claim_id, payload, headers or scn["hdr_biller"])
    )


def denied_claim(
    scn: Scenario,
    session_id: str,
    service_date: str = "2026-06-10",
    submit_headers: Optional[dict] = None,
    adjudicate_headers: Optional[dict] = None,
) -> dict:
    """Open, submit, accept and then deny a therapy-session claim."""
    claim = open_claim(scn, service_date=service_date, session_id=session_id)
    submit_claim(scn, claim["id"], headers=submit_headers)
    adjudicate(scn, claim["id"], "ACCEPTED", headers=adjudicate_headers)
    return adjudicate(
        scn,
        claim["id"],
        "DENIED",
        headers=adjudicate_headers,
        denial_reason="Medical necessity",
    )


def new_referral(scn: Scenario, **overrides) -> dict:
    return get_success_data(
        api_client.create_referral(
            f.create_referral_payload(scn["pt"], **overrides), scn["hdr_front"]
        )
    )


def respond_referral(scn: Scenario, referral_id: str, outcome: str, **overrides) -> dict:
    payload = {"response_outcome": outcome}
    payload.update(overrides)
    return get_success_data(
        api_client.respond_referral(referral_id, payload, scn["hdr_front"])
    )


def accepted_outbound_referral(scn: Scenario, **overrides) -> dict:
    """The precondition the TRANSFERRED discharge reason needs."""
    referral = new_referral(scn, plan_id=scn["plan"], **overrides)
    return respond_referral(scn, referral["id"], "ACCEPTED")


def discharge(scn: Scenario, reason: str, headers: Optional[dict] = None) -> dict:
    return get_success_data(
        api_client.discharge_patient(
            scn["pt"], {"discharge_reason": reason}, headers or scn["hdr_od1"]
        )
    )


def prescribe_occlusion(
    scn: Scenario, source_assessment_id: Optional[str] = None, **overrides
) -> dict:
    return get_success_data(
        api_client.create_occlusion_prescription(
            f.create_occlusion_payload(
                scn["pt"], source_assessment_id or scn["ev1"], **overrides
            ),
            scn["hdr_od1"],
        )
    )


def log_adherence(scn: Scenario, prescription_id: str, logged_days: int, adherent_days: int) -> dict:
    return get_success_data(
        api_client.log_adherence(
            prescription_id,
            {"logged_days_delta": logged_days, "adherent_days_delta": adherent_days},
            scn["hdr_patient"],
        )
    )


def taper(scn: Scenario, prescription_id: str, current_acuity_logmar: float) -> dict:
    return get_success_data(
        api_client.taper_occlusion(
            prescription_id, {"current_acuity_logmar": current_acuity_logmar}, scn["hdr_od1"]
        )
    )


def setup_occlusion_scenario(
    severity: str = "MODERATE",
    baseline_acuity_logmar: float = 0.40,
    diagnosis_category: str = "AMBLYOPIA",
    date_of_birth: str = "2016-06-01",
) -> tuple:
    """Clock, patient, optometrist, signed EVALUATION and one prescription."""
    set_clock(BASE_CLOCK_UTC)
    patient = new_patient(
        date_of_birth=date_of_birth, diagnosis_category=diagnosis_category
    )
    od1 = new_therapist(full_name="Dr Lee", credential="OPTOMETRIST")
    evaluation = build_signed_evaluation(
        patient["id"], od1["id"], measurements=[f.npc_measurement_payload(12.0, 16.0)]
    )
    scn = Scenario(
        pt=patient["id"],
        od1=od1["id"],
        ev1=evaluation["id"],
        hdr_od1=make_optometrist_headers(od1["id"]),
        hdr_patient=make_patient_user_headers(patient["id"]),
        hdr_front=make_front_desk_headers(),
        hdr_admin=make_clinic_admin_headers(),
    )
    prescription = prescribe_occlusion(
        scn, severity=severity, baseline_acuity_logmar=baseline_acuity_logmar
    )
    return scn, prescription
