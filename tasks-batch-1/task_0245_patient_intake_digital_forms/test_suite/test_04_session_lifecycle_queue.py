"""Session workflow lifecycle, queue gating, and cross-entity preconditions
(PRD §3.3, §3.4, §3.7, §3.11, §3.12).

Covers check-in requiring all consents signed, queue-call gated on session
readiness, the enqueue/cancel queue-count conservation, the revoke-reverts-ready
cascade, terminal-state lockdown, and clock-driven expiration.
"""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    TEST_USERS,
    fixtures,
)

FRONT = TEST_USERS["front_desk_headers"]
PATIENT = TEST_USERS["patient_headers"]
ADMIN = TEST_USERS["clinic_admin_headers"]


def _queue_entries_for(api, session_id):
    resp = api.list_queue_entries(FRONT, params={"intake_session_id": session_id})
    data, _meta = validate_paginated(resp)
    return data


def test_checkin_succeeds_when_all_consents_signed(api):
    """PRD §3.3: "Check-in is rejected with `ERR_SESSION_NOT_READY` if the session is not in `READY_FOR_VISIT`, and rejected with `ERR_CONSENT_NOT_SIGNED` if any required consent for the session is not currently `SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_all_consents_signed
    """
    clinic = fixtures.create_clinic(name="C13", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(
        clinic["id"], required_consent_codes=["HIPAA_NPP", "TREATMENT"]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=0, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=0,
    )
    c1 = fixtures.create_consent(session["id"], "HIPAA_NPP")
    c2 = fixtures.create_consent(session["id"], "TREATMENT")
    fixtures.sign_consent(c1["id"], "Pat M")
    fixtures.sign_consent(c2["id"], "Pat M")

    pre = validate_success(api.get_intake_session(session["id"], FRONT))
    assert pre["workflow_status"] == "READY_FOR_VISIT"

    data = validate_success(api.check_in_session(session["id"], FRONT))
    assert data["workflow_status"] == "CHECKED_IN"


def test_checkin_both_consents_signed_state(api):
    """PRD §3.4: "for every code in the provider's `required_consent_codes` there exists a consent document for this session with that `consent_code` and a `status` of `SIGNED`."

    Design: Difficulty/cross_entity_state_dependency/checkin_requires_all_consents_signed
    """
    clinic = fixtures.create_clinic(name="C13b", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(
        clinic["id"], required_consent_codes=["HIPAA_NPP", "TREATMENT"]
    )
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(session["id"], outcome="ELIGIBLE")
    c1 = fixtures.create_consent(session["id"], "HIPAA_NPP")
    c2 = fixtures.create_consent(session["id"], "TREATMENT")
    s1 = fixtures.sign_consent(c1["id"], "Pat M")
    s2 = fixtures.sign_consent(c2["id"], "Pat M")
    assert s1["status"] == "SIGNED" and s2["status"] == "SIGNED"
    validate_success(api.check_in_session(session["id"], FRONT))
    after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert after["workflow_status"] == "CHECKED_IN"


def test_queue_call_succeeds_when_session_ready(api):
    """PRD §3.11: "Calling requires the entry to be `WAITING` (otherwise `ERR_QUEUE_ENTRY_NOT_WAITING`), requires the parent session's `workflow_status` to be `READY_FOR_VISIT` or `CHECKED_IN` (otherwise `ERR_SESSION_NOT_READY`), and requires the referenced exam room to belong to the same clinic as the session (otherwise `ERR_ROOM_CLINIC_MISMATCH`)."

    Design: Difficulty/cross_entity_state_dependency/queue_call_blocked_unless_session_ready
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C14", with_exam_room=True
    )
    pre = validate_success(api.get_intake_session(session["id"], FRONT))
    assert pre["workflow_status"] == "READY_FOR_VISIT"

    data = validate_success(api.call_queue_entry(qentry["id"], {"exam_room_id": room["id"]}, FRONT))
    assert data["status"] == "CALLED"
    assert data["exam_room_id"] == room["id"]


def test_queue_call_assigns_room_on_ready_session(api):
    """PRD §3.11: "moving the entry from `WAITING` to `CALLED` and assigning that room."

    Design: Difficulty/cross_entity_state_dependency/queue_call_blocked_unless_session_ready
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_ready(
        clinic_name="C14b", with_exam_room=True
    )
    validate_success(api.call_queue_entry(qentry["id"], {"exam_room_id": room["id"]}, FRONT))
    fetched = validate_success(api.get_queue_entry(qentry["id"], FRONT))
    assert fetched["status"] == "CALLED"
    assert fetched["exam_room_id"] == room["id"]


def test_enqueue_then_cancel_conserves_queue_count(api):
    """PRD §3.3: "if a non-terminal queue entry exists, it is moved to `NO_SHOW` and the clinic's `active_queue_count` is decremented and the clinic's `version` incremented"
    PRD §2.9: "It rises by one when a session enters the queue and falls by one
    whenever an entry leaves the active set (reaching `DONE` or `NO_SHOW`)."

    Design: Difficulty/compensating_invariant/enqueue_then_cancel_queue_count_conserved
    """
    clinic, provider, patient, appt, session, card, qentry = fixtures.setup_session_ready(
        clinic_name="C18"
    )
    pre = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert pre["active_queue_count"] == 1

    cancelled = validate_success(api.cancel_session(session["id"], FRONT))
    assert cancelled["workflow_status"] == "CANCELLED"

    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["active_queue_count"] == 0, "enqueue+cancel nets to zero"

    entry_after = validate_success(api.get_queue_entry(qentry["id"], FRONT))
    assert entry_after["status"] == "NO_SHOW"


def test_cancel_no_shows_waiting_queue_entry(api):
    """PRD §3.3: "When the cancel happens from `READY_FOR_VISIT`, the queue entry that gets no-showed is precisely the `WAITING` entry that readiness enqueued."

    Design: Difficulty/compensating_invariant/enqueue_then_cancel_queue_count_conserved
    """
    clinic, provider, patient, appt, session, card, qentry = fixtures.setup_session_ready(
        clinic_name="C18b"
    )
    fixtures.api_client.cancel_session(session["id"], FRONT)
    entry_after = validate_success(api.get_queue_entry(qentry["id"], FRONT))
    assert entry_after["status"] == "NO_SHOW"
    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["active_queue_count"] == 0


def test_revoke_consent_reverts_ready_and_no_shows_queue(api):
    """PRD §3.7: "if the session was `READY_FOR_VISIT` it is reverted to `IN_PROGRESS` and its `WAITING` queue entry is moved to `NO_SHOW`, decrementing the clinic's `active_queue_count` and incrementing the clinic's `version`."

    Design: Corner/cross_cutting_complexity_layers/consent_revoke_reverts_ready_and_no_shows_queue
    """
    clinic = fixtures.create_clinic(name="CE22", form_expiration_hours=72, facility_fee_cents=0)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(clinic["id"], provider["id"], patient["id"])
    session = fixtures.open_session(appt["id"])
    fixtures.capture_verify_resolve(
        session["id"], outcome="ELIGIBLE",
        plan_copay_cents=0, plan_coinsurance_pct=0, facility_coinsurance_pct=0,
        remaining_deductible_cents=0, visit_allowed_amount_cents=0,
    )
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")
    fixtures.sign_consent(consent["id"], "Pat E2")

    revoked = validate_success(api.revoke_consent(consent["id"], PATIENT))
    assert revoked["status"] == "REVOKED"

    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["workflow_status"] == "IN_PROGRESS"
    assert session_after["forms_complete"] is False

    clinic_after = validate_success(api.get_clinic(clinic["id"], FRONT))
    assert clinic_after["active_queue_count"] == 0

    waiting = [e for e in _queue_entries_for(api, session["id"]) if e["status"] == "NO_SHOW"]
    assert len(waiting) == 1, "the WAITING entry is no-showed"


def test_cancel_completed_session_rejected(api):
    """PRD §3.3: "A `FrontDeskStaff` member may cancel a session while its `workflow_status` is `DRAFT`, `IN_PROGRESS`, or `READY_FOR_VISIT`; a cancel attempt from any other state is rejected with `ERR_SESSION_NOT_CANCELLABLE`."

    Design: Corner/state_machines/terminal_session_complete_lockdown
    """
    clinic, provider, patient, appt, session, card, qentry, room = fixtures.setup_session_completed(
        clinic_name="CE5"
    )
    pre = validate_success(api.get_intake_session(session["id"], FRONT))
    assert pre["workflow_status"] == "COMPLETED"

    resp = api.cancel_session(session["id"], FRONT)
    validate_error(resp, "ERR_SESSION_NOT_CANCELLABLE")

    after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert after["workflow_status"] == "COMPLETED"


def test_clock_advance_expires_incomplete_session(api):
    """PRD §3.12: "The expiration sweep moves every `DRAFT` or `IN_PROGRESS` session whose `current_utc` is at or after its `expires_at` to `EXPIRED`; as that session expires, every `SCHEDULED` reminder on it is moved to `SUPPRESSED"

    Design: Corner/state_machines/clock_advance_expires_incomplete_session
    """
    clinic = fixtures.create_clinic(
        name="CE8", form_expiration_hours=1, reminder_min_gap_minutes=240,
        reminder_quiet_start_min=1320, reminder_quiet_end_min=420,
    )
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="1970-01-02T10:00:00.000Z", end_utc="1970-01-02T10:30:00.000Z",
    )
    session = fixtures.open_session(appt["id"])
    fixtures.create_consent(session["id"], "HIPAA_NPP")  # session -> IN_PROGRESS
    # scheduled_local_min 600 (10:00) sits outside the wrap-around quiet window
    # [1320, 420); scheduled_utc 10:00 is after the clock target so the reminder
    # stays SCHEDULED until the expiration sweep SUPPRESSES it.
    reminder = fixtures.create_reminder(
        session["id"], "CONSENT", "1970-01-01T10:00:00.000Z", 600
    )

    fixtures.set_clock(clinic["id"], "1970-01-01T01:00:00.000Z")

    session_after = validate_success(api.get_intake_session(session["id"], FRONT))
    assert session_after["workflow_status"] == "EXPIRED"
    reminder_after = validate_success(api.get_reminder(reminder["id"], FRONT))
    assert reminder_after["status"] == "SUPPRESSED"


def test_sign_on_expired_session_blocked(api):
    """PRD §3.7: "Signing requires the document to be `PENDING` (otherwise `ERR_CONSENT_NOT_PENDING`), requires the parent session to be in none of `EXPIRED`, `CANCELLED`, or `COMPLETED` and to still be before its expiry instant (otherwise `ERR_SESSION_EXPIRED`)"

    Design: Corner/state_machines/sign_on_expired_session_blocked
    """
    clinic = fixtures.create_clinic(name="CE9", form_expiration_hours=1)
    provider = fixtures.create_provider(clinic["id"], required_consent_codes=["HIPAA_NPP"])
    patient = fixtures.create_patient(clinic["id"])
    appt = fixtures.create_appointment(
        clinic["id"], provider["id"], patient["id"],
        start_utc="1970-01-02T10:00:00.000Z", end_utc="1970-01-02T10:30:00.000Z",
    )
    session = fixtures.open_session(appt["id"])
    consent = fixtures.create_consent(session["id"], "HIPAA_NPP")
    fixtures.set_clock(clinic["id"], "1970-01-01T01:00:00.000Z")

    resp = api.sign_consent(consent["id"], {"signer_name": "Pat R2"}, PATIENT)
    validate_error(resp, "ERR_SESSION_EXPIRED")

    after = validate_success(api.get_consent_document(consent["id"], FRONT))
    assert after["status"] == "PENDING"
