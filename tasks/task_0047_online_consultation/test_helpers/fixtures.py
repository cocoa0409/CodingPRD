"""Composite setup helpers for the Online Consultation test suite.

Most interesting test claims require the system to be in a specific
state reached through 5–15 API calls. These helpers encapsulate those
preambles so test bodies stay focused on assertions.

Identity threading (PRD §2.1):

- Patient, Doctor, and Pharmacist are entity-backed. PRD §2.1: 'ownership
  checks on any resource that references a Patient compare the resource's
  patient_id field to X-User-ID' (analogous for Doctor and Pharmacist).
  Every ownership-gated call below uses `make_<role>_headers(entity['id'])`
  so the X-User-ID resolves to the real entity. Falling back to the shared
  TEST_USERS constant for an entity-backed role would make every ownership
  check fail.

- PlatformAdmin is opaque (PRD §2.1: 'an opaque operator identifier not
  tied to any persisted entity'); the shared TEST_USERS entry is canonical.

Setup helpers use get_success_data (lenient), so broken preconditions
surface as obvious errors rather than ambiguous assertion failures.
"""
from __future__ import annotations
import uuid
from typing import Any, Dict, List, Optional, Tuple

from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import (
    ALT_HOSPITAL_ID,
    DEFAULT_DEPARTMENT_CODE,
    DEFAULT_DOCTOR_BASE_FEE,
    DEFAULT_ECOMMERCE_ID,
    DEFAULT_HOSPITAL_ID,
    DEFAULT_PHARMACY_ID,
    DEFAULT_REGION_CODE,
    IN_SCOPE_DISEASE,
    OUT_OF_SCOPE_DISEASE,
)
from .factories import (
    create_consultation_payload,
    create_department_mapping_payload,
    create_doctor_payload,
    create_follow_up_payload,
    create_patient_payload,
    create_pharmacist_payload,
    create_prescription_payload,
    create_triage_session_payload,
    emit_event_payload,
    make_prescription_item,
    make_questionnaire_response,
    quality_report_payload,
    reject_prescription_payload,
    submit_form_payload,
    transfer_payload,
    verify_eligibility_payload,
)
from .test_users import (
    TEST_USERS,
    make_doctor_headers,
    make_patient_headers,
    make_pharmacist_headers,
)


ADMIN = TEST_USERS["platform_admin_headers"]


# ===========================================================================
# Top-level helpers — entity creation
# ===========================================================================
def register_department_mapping(
    *,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    disease_codes: Optional[List[str]] = None,
    triage_priority: int = 1,
) -> Dict[str, Any]:
    """Admin creates a DepartmentMapping. PRD §3.1: 'DepartmentMapping rows
    are registered by admin'."""
    payload = create_department_mapping_payload(
        department_code=department_code,
        disease_codes=disease_codes if disease_codes is not None else [
            IN_SCOPE_DISEASE, OUT_OF_SCOPE_DISEASE,
        ],
        triage_priority=triage_priority,
    )
    return get_success_data(
        api_client.create_department_mapping(payload, ADMIN)
    )


def create_patient(
    *,
    region_code: str = DEFAULT_REGION_CODE,
    insurance_policy_no: Optional[str] = "POL-001",
    preferred_hospital_id: Optional[str] = None,
    preferred_doctor_id: Optional[str] = None,
    chronic_condition_codes: Optional[List[str]] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Admin creates a Patient (PRD §3.1)."""
    return get_success_data(api_client.create_patient(
        create_patient_payload(
            region_code=region_code,
            insurance_policy_no=insurance_policy_no,
            preferred_hospital_id=preferred_hospital_id,
            preferred_doctor_id=preferred_doctor_id,
            chronic_condition_codes=chronic_condition_codes,
            **overrides,
        ),
        ADMIN,
    ))


def create_doctor(
    *,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    hospital_id: str = DEFAULT_HOSPITAL_ID,
    specialty_codes: Optional[List[str]] = None,
    licensed_region_codes: Optional[List[str]] = None,
    max_concurrent_sessions: int = 1,
    rating_score: float = 4.50,
    base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Admin creates a Doctor (PRD §3.1).

    `base_fee` is included in the create payload so downstream consultation
    fee calculations have a known base. Per PRD §3.4 the base_fee is
    snapshotted from the doctor profile at /accept.
    """
    extra: Dict[str, Any] = dict(overrides)
    if status is not None:
        extra["status"] = status
    return get_success_data(api_client.create_doctor(
        create_doctor_payload(
            department_code=department_code,
            hospital_id=hospital_id,
            specialty_codes=specialty_codes,
            licensed_region_codes=licensed_region_codes,
            max_concurrent_sessions=max_concurrent_sessions,
            rating_score=rating_score,
            base_fee=base_fee,
            **extra,
        ),
        ADMIN,
    ))


def create_pharmacist(
    *,
    status: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    """Admin creates a Pharmacist (PRD §3.1)."""
    return get_success_data(api_client.create_pharmacist(
        create_pharmacist_payload(status=status, **overrides),
        ADMIN,
    ))


# ===========================================================================
# Time-driving helpers (PRD §3.9)
# ===========================================================================
def advance_clock(seconds: int) -> None:
    """PRD §3.9: 'admin-only clock-advance capability moves the server's
    logical clock forward by a supplied seconds count'."""
    get_success_data(api_client.advance_clock(seconds, ADMIN))


def emit_event(kind: str, payload: Dict[str, Any]) -> Any:
    """PRD §3.9: admin-only event-ingest. Returns response (some events
    are idempotent and the loser carries an error_id)."""
    return api_client.emit_event(kind, payload, ADMIN)


# ===========================================================================
# Tier 1: State progression — TriageSession
# ===========================================================================
def open_triage_session(
    *,
    patient: Dict[str, Any],
    responses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Patient opens a TriageSession (PRD §3.2). Identity-threaded:
    X-User-ID == patient['id'] because PRD §2.1 makes patient_id the
    ownership key."""
    return get_success_data(api_client.create_triage_session(
        create_triage_session_payload(
            patient_id=patient["id"],
            questionnaire_responses=responses,
        ),
        make_patient_headers(patient["id"]),
    ))


def assess_triage_session(
    *,
    session: Dict[str, Any],
    patient: Dict[str, Any],
) -> Dict[str, Any]:
    """Patient triggers /assess on their own session."""
    return get_success_data(api_client.assess_triage_session(
        session["id"],
        make_patient_headers(patient["id"]),
    ))


def open_and_assess_triage(
    *,
    patient: Dict[str, Any],
    responses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Open + assess in one call; returns the assessed (or
    EMERGENCY_ROUTED) TriageSession."""
    session = open_triage_session(patient=patient, responses=responses)
    return assess_triage_session(session=session, patient=patient)


def build_responses_for_band(band: str,
                             *,
                             chronic_codes: Optional[List[str]] = None
                             ) -> List[Dict[str, Any]]:
    """Build a questionnaire_responses list so that triage_severity_score
    lands in the requested band.

    PRD §3.2: severity_score = chief_complaint_score + vital_anomaly_score
        + risk_factor_score.
        chief = sum(severity_weight) * 10
        vital = count(question_code starts 'VITAL_' and answer_value=='ABNORMAL') * 2
        risk  = sum(RISK_TABLE entries) * 3

    With chronic_codes=[], risk=0; with ['DIABETES'] or ['HYPERTENSION'],
    risk=3; with ['IMMUNOCOMPROMISED'], risk=6.
    """
    chronic_codes = chronic_codes or []
    if band == "LOW":
        # severity_score = 1*10 + 0 + 0 = 10 < 30
        return [make_questionnaire_response(
            question_code="CHEST_PAIN",
            answer_value="MILD", severity_weight=1,
        )]
    if band == "MID":
        # severity_score = 4*10 + 0 + 0 = 40 (in [30, 60))
        return [make_questionnaire_response(
            question_code="CHEST_PAIN", answer_value="YES",
            severity_weight=4,
        )]
    if band == "HIGH":
        # severity_score = 7*10 + 0 + 0 = 70 (in [60, 90))
        return [make_questionnaire_response(
            question_code="CHEST_PAIN", answer_value="YES",
            severity_weight=7,
        )]
    if band == "EMERGENCY":
        # severity_score = 10*10 + 0 + 0 = 100 >= 90
        return [make_questionnaire_response(
            question_code="CHEST_PAIN", answer_value="YES",
            severity_weight=10,
        )]
    raise ValueError(f"Unknown band: {band}")


# ===========================================================================
# Tier 2: Entity hierarchy — match doctor, create consultation
# ===========================================================================
def setup_basic_org(
    *,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    disease_codes: Optional[List[str]] = None,
    region_code: str = DEFAULT_REGION_CODE,
    hospital_id: str = DEFAULT_HOSPITAL_ID,
    doctor_specialty_codes: Optional[List[str]] = None,
    doctor_base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
    doctor_max_concurrent: int = 1,
    doctor_status: Optional[str] = None,
) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    """Register one DepartmentMapping, one matching Doctor, one
    Pharmacist. Returns (mapping, doctor, pharmacist).

    PRD §3.3: 'The candidate set is built from doctors whose department_code
    equals the triage session's recommended_department_code, whose
    licensed_region_codes contains the patient's region_code ... and whose
    specialty_codes intersect the disease codes ... in at least one element.'
    The mapping disease_codes must overlap doctor specialty_codes so the
    selector will succeed.
    """
    mapping = register_department_mapping(
        department_code=department_code,
        disease_codes=disease_codes or [
            IN_SCOPE_DISEASE, OUT_OF_SCOPE_DISEASE,
        ],
    )
    doctor = create_doctor(
        department_code=department_code,
        hospital_id=hospital_id,
        specialty_codes=doctor_specialty_codes or [
            IN_SCOPE_DISEASE, OUT_OF_SCOPE_DISEASE,
        ],
        licensed_region_codes=[region_code],
        max_concurrent_sessions=doctor_max_concurrent,
        rating_score=4.50,
        base_fee=doctor_base_fee,
        status=doctor_status,
    )
    pharmacist = create_pharmacist()
    return mapping, doctor, pharmacist


def create_consultation(
    *,
    triage: Dict[str, Any],
    patient: Dict[str, Any],
    mode: str = "REAL_TIME",
    media_type: str = "TEXT_IMAGE",
    scheduled_start_at: Optional[str] = None,
    doctor_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Patient creates a Consultation. PRD §3.3."""
    return get_success_data(api_client.create_consultation(
        create_consultation_payload(
            triage_session_id=triage["id"],
            mode=mode,
            media_type=media_type,
            scheduled_start_at=scheduled_start_at,
            doctor_id=doctor_id,
        ),
        make_patient_headers(patient["id"]),
    ))


def setup_consultation_pending(
    *,
    department_code: str = DEFAULT_DEPARTMENT_CODE,
    band: str = "MID",
    chronic_codes: Optional[List[str]] = None,
    insurance_policy_no: Optional[str] = "POL-001",
    region_code: str = DEFAULT_REGION_CODE,
    hospital_id: str = DEFAULT_HOSPITAL_ID,
    mode: str = "REAL_TIME",
    media_type: str = "TEXT_IMAGE",
    scheduled_start_at: Optional[str] = None,
    doctor_base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
    doctor_max_concurrent: int = 1,
    doctor_specialty_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Run the full preamble through Consultation creation. Returns a dict
    with patient, doctor, pharmacist, triage, consultation."""
    mapping, doctor, pharmacist = setup_basic_org(
        department_code=department_code,
        region_code=region_code,
        hospital_id=hospital_id,
        doctor_base_fee=doctor_base_fee,
        doctor_max_concurrent=doctor_max_concurrent,
        doctor_specialty_codes=doctor_specialty_codes,
    )
    patient = create_patient(
        region_code=region_code,
        insurance_policy_no=insurance_policy_no,
        chronic_condition_codes=chronic_codes or [],
    )
    triage = open_and_assess_triage(
        patient=patient,
        responses=build_responses_for_band(
            band, chronic_codes=chronic_codes,
        ),
    )
    consultation = create_consultation(
        triage=triage, patient=patient,
        mode=mode, media_type=media_type,
        scheduled_start_at=scheduled_start_at,
        doctor_id=None,
    )
    return {
        "mapping": mapping,
        "doctor": doctor,
        "pharmacist": pharmacist,
        "patient": patient,
        "triage": triage,
        "consultation": consultation,
    }


# ===========================================================================
# Tier 3: Consultation lifecycle shortcuts
# ===========================================================================
def accept_consultation(
    *,
    consultation: Dict[str, Any],
    doctor: Dict[str, Any],
) -> Dict[str, Any]:
    """Doctor accepts a QUEUED consultation (PRD §3.4). Identity-threaded:
    X-User-ID == doctor['id']."""
    return get_success_data(api_client.accept_consultation(
        consultation["id"],
        make_doctor_headers(doctor["id"]),
    ))


def start_consultation(
    *,
    consultation: Dict[str, Any],
    doctor: Dict[str, Any],
) -> Dict[str, Any]:
    """Doctor starts the session (PRD §3.4)."""
    return get_success_data(api_client.start_consultation(
        consultation["id"],
        make_doctor_headers(doctor["id"]),
    ))


def complete_consultation(
    *,
    consultation: Dict[str, Any],
    doctor: Dict[str, Any],
) -> Dict[str, Any]:
    """Doctor completes the session (PRD §3.5)."""
    return get_success_data(api_client.complete_consultation(
        consultation["id"],
        make_doctor_headers(doctor["id"]),
    ))


def setup_completed_consultation(
    *,
    elapsed_seconds: int = 600,
    media_type: str = "TEXT_IMAGE",
    band: str = "MID",
    chronic_codes: Optional[List[str]] = None,
    doctor_base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
    insurance_policy_no: Optional[str] = "POL-001",
) -> Dict[str, Any]:
    """Walk through accept -> start -> advance_clock -> complete.

    elapsed_seconds = 0 advances no time and produces duration_minutes = 0
    (PRD §3.5 ceil(0/60) = 0). Tests that need a specific duration set
    elapsed_seconds accordingly.
    """
    state = setup_consultation_pending(
        band=band, chronic_codes=chronic_codes,
        insurance_policy_no=insurance_policy_no,
        doctor_base_fee=doctor_base_fee,
        media_type=media_type,
    )
    accept_consultation(
        consultation=state["consultation"], doctor=state["doctor"],
    )
    start_consultation(
        consultation=state["consultation"], doctor=state["doctor"],
    )
    if elapsed_seconds > 0:
        advance_clock(elapsed_seconds)
    completed = complete_consultation(
        consultation=state["consultation"], doctor=state["doctor"],
    )
    state["consultation"] = completed
    return state


def setup_in_progress_consultation(
    *,
    media_type: str = "TEXT_IMAGE",
    band: str = "MID",
    chronic_codes: Optional[List[str]] = None,
    doctor_base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
    doctor_max_concurrent: int = 1,
) -> Dict[str, Any]:
    """Walk through accept -> start, leaving the consultation IN_PROGRESS."""
    state = setup_consultation_pending(
        band=band, chronic_codes=chronic_codes,
        doctor_base_fee=doctor_base_fee,
        doctor_max_concurrent=doctor_max_concurrent,
        media_type=media_type,
    )
    accept_consultation(
        consultation=state["consultation"], doctor=state["doctor"],
    )
    started = start_consultation(
        consultation=state["consultation"], doctor=state["doctor"],
    )
    state["consultation"] = started
    return state


# ===========================================================================
# Tier 3: Prescription lifecycle shortcuts
# ===========================================================================
def draft_prescription(
    *,
    consultation: Dict[str, Any],
    doctor: Dict[str, Any],
    disease_codes: Optional[List[str]] = None,
    items: Optional[List[Dict[str, Any]]] = None,
    dispatch_target_kind: str = "PHARMACY",
    dispatch_target_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Doctor drafts a Prescription. Identity-threaded:
    X-User-ID == doctor['id'] because PRD §2.1 makes drafting_doctor_id
    the ownership key for the Prescription."""
    return get_success_data(api_client.create_prescription(
        create_prescription_payload(
            consultation_id=consultation["id"],
            disease_codes=disease_codes,
            items=items,
            dispatch_target_kind=dispatch_target_kind,
            dispatch_target_id=dispatch_target_id,
        ),
        make_doctor_headers(doctor["id"]),
    ))


def submit_prescription(
    *,
    prescription: Dict[str, Any],
    doctor: Dict[str, Any],
) -> Dict[str, Any]:
    """Drafting doctor submits the draft (PRD §3.6)."""
    return get_success_data(api_client.submit_prescription(
        prescription["id"],
        make_doctor_headers(doctor["id"]),
    ))


def approve_prescription(
    *,
    prescription: Dict[str, Any],
    pharmacist: Dict[str, Any],
) -> Dict[str, Any]:
    """Pharmacist approves (PRD §3.6). Pharmacist must NOT equal
    drafting_doctor_id."""
    return get_success_data(api_client.approve_prescription(
        prescription["id"],
        make_pharmacist_headers(pharmacist["id"]),
    ))


def reject_prescription(
    *,
    prescription: Dict[str, Any],
    pharmacist: Dict[str, Any],
    reason: str = "Dosage incorrect",
) -> Dict[str, Any]:
    """Pharmacist rejects (PRD §3.6)."""
    return get_success_data(api_client.reject_prescription(
        prescription["id"],
        reject_prescription_payload(reason),
        make_pharmacist_headers(pharmacist["id"]),
    ))


def revise_prescription(
    *,
    prescription: Dict[str, Any],
    doctor: Dict[str, Any],
    items: Optional[List[Dict[str, Any]]] = None,
    disease_codes: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """Drafting doctor revises a REJECTED prescription (PRD §3.6)."""
    payload: Dict[str, Any] = {}
    if items is not None:
        payload["items"] = items
    if disease_codes is not None:
        payload["disease_codes"] = disease_codes
    return get_success_data(api_client.revise_prescription(
        prescription["id"], make_doctor_headers(doctor["id"]),
        payload,
    ))


def dispatch_prescription(
    *,
    prescription: Dict[str, Any],
    pharmacist: Dict[str, Any],
) -> Dict[str, Any]:
    """Pharmacist dispatches an APPROVED prescription (PRD §3.6)."""
    return get_success_data(api_client.dispatch_prescription(
        prescription["id"],
        make_pharmacist_headers(pharmacist["id"]),
    ))


# ===========================================================================
# Tier 5: End-to-end — through dispatch, claim, settle
# ===========================================================================
def setup_dispatched_prescription(
    *,
    items: Optional[List[Dict[str, Any]]] = None,
    disease_codes: Optional[List[str]] = None,
    insurance_policy_no: Optional[str] = "POL-001",
    elapsed_seconds: int = 600,
    chronic_codes: Optional[List[str]] = None,
    doctor_base_fee: float = DEFAULT_DOCTOR_BASE_FEE,
) -> Dict[str, Any]:
    """Drive a full pipeline through prescription /dispatch.

    PRD §3.6: dispatch 'triggers an InsuranceClaim eligibility check when
    the patient has an insurance_policy_no'. The returned dict includes
    the claim if one was created.
    """
    state = setup_completed_consultation(
        elapsed_seconds=elapsed_seconds,
        chronic_codes=chronic_codes,
        doctor_base_fee=doctor_base_fee,
        insurance_policy_no=insurance_policy_no,
    )
    pres = draft_prescription(
        consultation=state["consultation"],
        doctor=state["doctor"],
        disease_codes=disease_codes,
        items=items,
    )
    pres = submit_prescription(prescription=pres, doctor=state["doctor"])
    pres = approve_prescription(
        prescription=pres, pharmacist=state["pharmacist"],
    )
    pres = dispatch_prescription(
        prescription=pres, pharmacist=state["pharmacist"],
    )
    state["prescription"] = pres
    state["claim"] = _find_insurance_claim_for_consultation(
        state["consultation"]["id"]
    )
    return state


def _find_insurance_claim_for_consultation(
    consultation_id: str,
) -> Optional[Dict[str, Any]]:
    """List insurance claims and return the one for this consultation.

    Implementations may expose list filtering or only by-id GET; we
    iterate listings using PRD §2.3 default pagination.
    """
    # PRD §4 does not expose a /insurance-claims list endpoint; tests
    # therefore retrieve the claim by listing audit logs (PRD §3.9) for
    # the consultation. As a fallback, callers may pass the claim
    # explicitly when known. This helper is best-effort.
    try:
        resp = api_client.list_audit_logs(
            ADMIN,
            params={"target_entity": "InsuranceClaim", "limit": 100},
        )
        data, _ = validate_paginated(resp)
        # Each audit row's target_id is the claim id; we try to GET each
        # until we find one whose consultation_id matches.
        for row in data:
            tid = row.get("target_id")
            if not tid:
                continue
            try:
                claim_resp = api_client.get_insurance_claim(tid, ADMIN)
                claim = get_success_data(claim_resp)
                if claim.get("consultation_id") == consultation_id:
                    return claim
            except Exception:
                continue
    except Exception:
        return None
    return None


def verify_eligibility(
    *,
    claim: Dict[str, Any],
    insurance_status: str = "ELIGIBLE",
) -> Dict[str, Any]:
    """Admin invokes /verify-eligibility (PRD §3.7)."""
    return get_success_data(api_client.verify_eligibility(
        claim["id"],
        verify_eligibility_payload(insurance_status),
        ADMIN,
    ))


def settle_claim(*, claim: Dict[str, Any]) -> Dict[str, Any]:
    """Admin invokes /settle (PRD §3.7)."""
    return get_success_data(api_client.settle_claim(claim["id"], ADMIN))


def bureau_settled_event(
    *,
    claim: Dict[str, Any],
    bureau_ref: Optional[str] = None,
) -> Any:
    """Emit a BUREAU_SETTLED event (PRD §3.7, §3.9)."""
    return emit_event("BUREAU_SETTLED", {
        "claim_id": claim["id"],
        "bureau_ref": bureau_ref or f"BUREAU-{uuid.uuid4().hex[:8]}",
    })


def bureau_rejected_event(*, claim: Dict[str, Any]) -> Any:
    """Emit a BUREAU_REJECTED event (PRD §3.7)."""
    return emit_event("BUREAU_REJECTED", {"claim_id": claim["id"]})


# ===========================================================================
# Tier 4: Prescription revision cycle to threshold
# ===========================================================================
def cycle_prescription_revisions(
    *,
    prescription: Dict[str, Any],
    doctor: Dict[str, Any],
    pharmacist: Dict[str, Any],
    target_revision_count: int,
) -> Dict[str, Any]:
    """Cycle the prescription through DRAFT -> UNDER_REVIEW -> REJECTED ->
    DRAFT exactly `target_revision_count` times.

    PRD §3.6: 'Revision ... increments revision_count by one. The system
    caps the revision loop: once revision_count has reached the configured
    maximum, a further revise call instead drives an automatic transition
    from REJECTED to the terminal FAILED.'
    """
    current = prescription
    for _ in range(target_revision_count):
        current = submit_prescription(prescription=current, doctor=doctor)
        current = reject_prescription(
            prescription=current, pharmacist=pharmacist,
        )
        current = revise_prescription(prescription=current, doctor=doctor)
    return current


# ===========================================================================
# Follow-up task helpers (PRD §3.8)
# ===========================================================================
def create_follow_up(
    *,
    consultation: Dict[str, Any],
    doctor: Dict[str, Any],
    scheduled_reminder_at: str,
    reminder_channels: Optional[List[str]] = None,
    plan_template_code: str = "GENERIC_WEEKLY",
) -> Dict[str, Any]:
    """Doctor creates a FollowUpTask (PRD §3.8). Identity-threaded:
    X-User-ID == doctor['id']."""
    return get_success_data(api_client.create_follow_up_task(
        create_follow_up_payload(
            consultation_id=consultation["id"],
            plan_template_code=plan_template_code,
            scheduled_reminder_at=scheduled_reminder_at,
            reminder_channels=reminder_channels,
        ),
        make_doctor_headers(doctor["id"]),
    ))


def fire_reminder(task: Dict[str, Any]) -> Dict[str, Any]:
    """Admin fires the reminder (PRD §3.8 / §4)."""
    return get_success_data(api_client.fire_reminder(task["id"], ADMIN))


def submit_follow_up_form(
    *,
    task: Dict[str, Any],
    patient: Dict[str, Any],
    form_payload: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Patient submits the follow-up form. Identity-threaded."""
    return get_success_data(api_client.submit_follow_up_form(
        task["id"],
        submit_form_payload(form_payload),
        make_patient_headers(patient["id"]),
    ))


# ===========================================================================
# DoctorSchedule helper (PRD §3.4: 'a published DoctorSchedule open window')
# ===========================================================================
# Tests configure DoctorSchedule via the same PATCH endpoint on Doctor
# when supported, or via a dedicated POST when the implementation exposes
# one. PRD does not commit to the create-doctor payload including
# schedule windows; the difficulty-design recipe just says 'create
# Doctor with a published DoctorSchedule window [09:00, 18:00]'. The
# helper below is a no-op placeholder: tests that rely on schedule
# windows should skip when PRD does not commit to a publish API. The
# real test_suite is careful to NOT assert PRD-silent behavior here.

__all__ = [
    "ADMIN",
    "register_department_mapping",
    "create_patient",
    "create_doctor",
    "create_pharmacist",
    "advance_clock",
    "emit_event",
    "open_triage_session",
    "assess_triage_session",
    "open_and_assess_triage",
    "build_responses_for_band",
    "setup_basic_org",
    "create_consultation",
    "setup_consultation_pending",
    "accept_consultation",
    "start_consultation",
    "complete_consultation",
    "setup_completed_consultation",
    "setup_in_progress_consultation",
    "draft_prescription",
    "submit_prescription",
    "approve_prescription",
    "reject_prescription",
    "revise_prescription",
    "dispatch_prescription",
    "setup_dispatched_prescription",
    "verify_eligibility",
    "settle_claim",
    "bureau_settled_event",
    "bureau_rejected_event",
    "cycle_prescription_revisions",
    "create_follow_up",
    "fire_reminder",
    "submit_follow_up_form",
]
