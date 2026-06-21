"""Composite setup helpers for Patient Intake & Digital Forms tests.

Each helper builds its preconditions from scratch using only PRD-declared
endpoints, returning the created resources for assertions. All setup calls use
get_success_data() so a setup failure surfaces a clear "Setup step failed"
message instead of a confusing assertion failure.

The test harness restarts the server and empties the database before every
test, so each helper assumes a blank slate.
"""
from prd_bench_local_runner.testing import get_success_data
from .api_client import api_client
from .test_users import TEST_USERS
from . import factories as F

ADMIN = TEST_USERS["clinic_admin_headers"]
FRONT = TEST_USERS["front_desk_headers"]
PATIENT = TEST_USERS["patient_headers"]
BILLING = TEST_USERS["billing_clerk_headers"]


# ---------------------------------------------------------------------------
# Tier 1/2: Base setup — clinic, provider, patient, appointment, session
# ---------------------------------------------------------------------------
def create_clinic(**overrides) -> dict:
    """Create a clinic with the supplied configuration overrides."""
    resp = api_client.create_clinic(F.create_clinic_payload(**overrides), ADMIN)
    return get_success_data(resp)


def create_provider(clinic_id, **overrides) -> dict:
    resp = api_client.create_provider(F.create_provider_payload(clinic_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_exam_room(clinic_id, **overrides) -> dict:
    resp = api_client.create_exam_room(F.create_exam_room_payload(clinic_id, **overrides), ADMIN)
    return get_success_data(resp)


def create_patient(clinic_id, **overrides) -> dict:
    resp = api_client.create_patient(F.create_patient_payload(clinic_id, **overrides), FRONT)
    return get_success_data(resp)


def create_appointment(clinic_id, provider_id, patient_id, **overrides) -> dict:
    resp = api_client.create_appointment(
        F.create_appointment_payload(clinic_id, provider_id, patient_id, **overrides), FRONT
    )
    return get_success_data(resp)


def open_session(appointment_id) -> dict:
    resp = api_client.create_intake_session(F.create_intake_session_payload(appointment_id), FRONT)
    return get_success_data(resp)


def setup_base_session(
    clinic_overrides=None,
    provider_overrides=None,
    appointment_overrides=None,
):
    """Create clinic + provider + patient + appointment + open intake session.

    Returns (clinic, provider, patient, appointment, session) all freshly fetched.
    The session is in DRAFT / PENDING_ELIGIBILITY.
    """
    clinic = create_clinic(**(clinic_overrides or {}))
    provider = create_provider(clinic["id"], **(provider_overrides or {}))
    patient = create_patient(clinic["id"])
    appointment = create_appointment(
        clinic["id"], provider["id"], patient["id"], **(appointment_overrides or {})
    )
    session = open_session(appointment["id"])
    return clinic, provider, patient, appointment, session


# ---------------------------------------------------------------------------
# Tier 1: Insurance capture + eligibility resolution
# ---------------------------------------------------------------------------
def capture_card(session_id, **card_fields) -> dict:
    resp = api_client.create_insurance_card(
        F.create_insurance_card_payload(session_id, **card_fields), FRONT
    )
    return get_success_data(resp)


def verify_card(card_id) -> dict:
    resp = api_client.verify_insurance_card(card_id, FRONT)
    return get_success_data(resp)


def resolve_card(card_id, outcome) -> dict:
    resp = api_client.resolve_eligibility(card_id, F.resolve_eligibility_payload(outcome), FRONT)
    return get_success_data(resp)


def capture_verify_resolve(session_id, outcome="ELIGIBLE", **card_fields):
    """Capture a card on the session, verify it, and resolve to `outcome`.

    Returns (card, resolved_card).
    """
    card = capture_card(session_id, **card_fields)
    verify_card(card["id"])
    resolved = resolve_card(card["id"], outcome)
    return card, resolved


def setup_session_eligible(
    clinic_overrides=None,
    provider_overrides=None,
    card_fields=None,
    outcome="ELIGIBLE",
):
    """Base session + card captured, verified, resolved to `outcome`.

    Default card has all-zero financials (allowed 0), driving an ELIGIBLE
    resolution to INSURED. Override card_fields to drive COPAY_DUE/SELF_PAY.
    Returns (clinic, provider, patient, appointment, session, card).
    """
    clinic, provider, patient, appointment, session = setup_base_session(
        clinic_overrides=clinic_overrides, provider_overrides=provider_overrides
    )
    fields = card_fields if card_fields is not None else {
        "plan_copay_cents": 0,
        "plan_coinsurance_pct": 0,
        "facility_coinsurance_pct": 0,
        "remaining_deductible_cents": 0,
        "visit_allowed_amount_cents": 0,
    }
    card, _ = capture_verify_resolve(session["id"], outcome=outcome, **fields)
    return clinic, provider, patient, appointment, session, card


# Standard COPAY_DUE card: copay 3000 / coins 20 / ded 5000 / allowed 8000.
# With facility_fee_cents=500 this finalizes to 9100 (PRD §3.6).
COPAY_DUE_CARD_9100 = {
    "plan_copay_cents": 3000,
    "plan_coinsurance_pct": 20,
    "facility_coinsurance_pct": 0,
    "remaining_deductible_cents": 5000,
    "visit_allowed_amount_cents": 8000,
}


def setup_session_copay_due(clinic_name="Copay Clinic"):
    """Session driven to financial_status COPAY_DUE with final responsibility 9100.

    Clinic PER_LINE_THEN_SUM, facility_fee_cents 500; provider with no required
    forms; card resolved ELIGIBLE. Returns
    (clinic, provider, patient, appointment, session, card).
    """
    return setup_session_eligible(
        clinic_overrides={
            "name": clinic_name,
            "copay_rounding": "PER_LINE_THEN_SUM",
            "facility_fee_cents": 500,
        },
        card_fields=dict(COPAY_DUE_CARD_9100),
        outcome="ELIGIBLE",
    )


def get_session(session_id, headers=FRONT) -> dict:
    resp = api_client.get_intake_session(session_id, headers)
    return get_success_data(resp)


def session_version(session_id) -> int:
    return get_session(session_id, BILLING)["version"]


# ---------------------------------------------------------------------------
# Tier 3: Copay money path
# ---------------------------------------------------------------------------
def authorize_copay(session_id, amount_cents, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = session_version(session_id)
    resp = api_client.create_copay_payment(
        F.create_copay_payment_payload(session_id, amount_cents, expected_version), BILLING
    )
    return get_success_data(resp)


def capture_copay(payment_id) -> dict:
    resp = api_client.capture_copay(payment_id, BILLING)
    return get_success_data(resp)


def setup_session_copay_authorized(clinic_name="Auth Clinic"):
    """COPAY_DUE session (final 9100) with a CopayPayment AUTHORIZED for 9100.

    Returns (clinic, provider, patient, appointment, session, card, payment).
    """
    clinic, provider, patient, appointment, session, card = setup_session_copay_due(clinic_name)
    payment = authorize_copay(session["id"], 9100)
    return clinic, provider, patient, appointment, session, card, payment


def setup_session_copay_settled(clinic_name="Settled Clinic"):
    """COPAY_DUE session (final 9100), copay 9100 authorized then captured.

    Session financial_status is now COPAY_SETTLED; clinic.collected_copay_cents
    is 9100. Returns (clinic, provider, patient, appointment, session, card, payment).
    """
    clinic, provider, patient, appointment, session, card, payment = setup_session_copay_authorized(clinic_name)
    payment = capture_copay(payment["id"])
    return clinic, provider, patient, appointment, session, card, payment


# ---------------------------------------------------------------------------
# Tier 2/5: Readiness, queue, and lifecycle
# ---------------------------------------------------------------------------
def setup_session_ready(clinic_name="Ready Clinic", with_exam_room=False):
    """Session driven to READY_FOR_VISIT (no required forms, INSURED).

    Provider has empty required_consent_codes and questionnaire_required_sections;
    card resolved ELIGIBLE with allowed 0 -> INSURED, so signing nothing else the
    session auto-advances to READY_FOR_VISIT and enqueues one WAITING queue entry.

    Returns (clinic, provider, patient, appointment, session, card, queue_entry[, exam_room]).
    """
    clinic, provider, patient, appointment, session, card = setup_session_eligible(
        clinic_overrides={"name": clinic_name, "facility_fee_cents": 0},
        outcome="ELIGIBLE",
    )
    queue_entry = get_session_queue_entry(session["id"])
    if with_exam_room:
        room = create_exam_room(clinic["id"], label="Room A")
        return clinic, provider, patient, appointment, session, card, queue_entry, room
    return clinic, provider, patient, appointment, session, card, queue_entry


def get_session_queue_entry(session_id) -> dict:
    """Return the (first) KioskQueueEntry belonging to the given session."""
    resp = api_client.list_queue_entries(FRONT, params={"intake_session_id": session_id})
    data = get_success_data(resp)
    assert data, f"Setup step failed: no queue entry for session {session_id}"
    return data[0]


def setup_session_checked_in(clinic_name="CheckedIn Clinic"):
    """READY_FOR_VISIT session checked in to CHECKED_IN (no required consents).

    Returns (clinic, provider, patient, appointment, session, card, queue_entry, exam_room).
    """
    clinic, provider, patient, appointment, session, card, queue_entry, room = setup_session_ready(
        clinic_name=clinic_name, with_exam_room=True
    )
    resp = api_client.check_in_session(session["id"], FRONT)
    get_success_data(resp)
    return clinic, provider, patient, appointment, session, card, queue_entry, room


def setup_session_completed(clinic_name="Completed Clinic"):
    """Full lifecycle to workflow_status COMPLETED (no required forms, INSURED).

    READY -> check-in -> queue call/room-in/done -> complete.
    Returns (clinic, provider, patient, appointment, session, card, queue_entry, exam_room).
    """
    clinic, provider, patient, appointment, session, card, queue_entry, room = setup_session_checked_in(clinic_name)
    get_success_data(api_client.call_queue_entry(queue_entry["id"], F.call_queue_entry_payload(room["id"]), FRONT))
    get_success_data(api_client.room_in_queue_entry(queue_entry["id"], FRONT))
    get_success_data(api_client.done_queue_entry(queue_entry["id"], FRONT))
    get_success_data(api_client.complete_session(session["id"], FRONT))
    return clinic, provider, patient, appointment, session, card, queue_entry, room


# ---------------------------------------------------------------------------
# Consent helpers
# ---------------------------------------------------------------------------
def create_consent(session_id, consent_code) -> dict:
    resp = api_client.create_consent_document(
        F.create_consent_document_payload(session_id, consent_code), FRONT
    )
    return get_success_data(resp)


def sign_consent(consent_id, signer_name="Test Patient") -> dict:
    resp = api_client.sign_consent(consent_id, F.sign_consent_payload(signer_name), PATIENT)
    return get_success_data(resp)


def revoke_consent(consent_id) -> dict:
    resp = api_client.revoke_consent(consent_id, PATIENT)
    return get_success_data(resp)


def setup_consent_signed_then_revoked(clinic_name="Consent Clinic", consent_code="HIPAA_NPP"):
    """Provider requires [consent_code]; one consent created, signed, then revoked.

    Returns (clinic, provider, patient, appointment, session, consent).
    """
    clinic, provider, patient, appointment, session = setup_base_session(
        clinic_overrides={"name": clinic_name, "form_expiration_hours": 72},
        provider_overrides={"required_consent_codes": [consent_code]},
    )
    consent = create_consent(session["id"], consent_code)
    sign_consent(consent["id"])
    revoke_consent(consent["id"])
    return clinic, provider, patient, appointment, session, consent


# ---------------------------------------------------------------------------
# Questionnaire helpers
# ---------------------------------------------------------------------------
def create_questionnaire(session_id, answered_sections=None, as_patient=True) -> dict:
    headers = PATIENT if as_patient else FRONT
    resp = api_client.create_questionnaire(
        F.create_questionnaire_payload(session_id, answered_sections), headers
    )
    return get_success_data(resp)


def submit_questionnaire(qr_id) -> dict:
    resp = api_client.submit_questionnaire(qr_id, PATIENT)
    return get_success_data(resp)


def accept_questionnaire(qr_id) -> dict:
    resp = api_client.accept_questionnaire(qr_id, FRONT)
    return get_success_data(resp)


def setup_questionnaire_flagged(clinic_name="Flagged Clinic", required_sections=None, risk_weight=10):
    """Provider requires [section]; questionnaire of weight `risk_weight` submitted
    then accepted into FLAGGED (final weighted score crosses HIGH_RISK_THRESHOLD).

    risk_weight defaults to 10 (PRD caps risk_weight at 0..10); on a required
    section the x2 multiplier yields a final score of 20, exactly the >=20
    high-risk threshold, so the questionnaire lands in FLAGGED.

    Returns (clinic, provider, patient, appointment, session, questionnaire).
    """
    sections = required_sections if required_sections is not None else ["ALLERGIES"]
    clinic, provider, patient, appointment, session = setup_base_session(
        clinic_overrides={"name": clinic_name, "form_expiration_hours": 72},
        provider_overrides={"questionnaire_required_sections": sections},
    )
    qr = create_questionnaire(
        session["id"],
        answered_sections=[{"section_key": sections[0], "risk_weight": risk_weight}],
    )
    submit_questionnaire(qr["id"])
    qr = accept_questionnaire(qr["id"])
    return clinic, provider, patient, appointment, session, qr


# ---------------------------------------------------------------------------
# Reminder helper
# ---------------------------------------------------------------------------
def create_reminder(session_id, target_kind, scheduled_utc, scheduled_local_min) -> dict:
    resp = api_client.create_reminder(
        F.create_reminder_payload(session_id, target_kind, scheduled_utc, scheduled_local_min), FRONT
    )
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Clock helper
# ---------------------------------------------------------------------------
def set_clock(clinic_id, to_iso8601) -> dict:
    resp = api_client.set_current_utc(F.set_clock_payload(clinic_id, to_iso8601), ADMIN)
    return get_success_data(resp)


# ---------------------------------------------------------------------------
# Room booking helper
# ---------------------------------------------------------------------------
def get_room_version(room_id) -> int:
    resp = api_client.get_exam_room(room_id, FRONT)
    return get_success_data(resp)["version"]


def book_room(exam_room_id, queue_entry_id, start_utc, end_utc, expected_version=None) -> dict:
    if expected_version is None:
        expected_version = get_room_version(exam_room_id)
    resp = api_client.create_room_booking(
        F.create_room_booking_payload(exam_room_id, queue_entry_id, start_utc, end_utc, expected_version),
        FRONT,
    )
    return get_success_data(resp)
