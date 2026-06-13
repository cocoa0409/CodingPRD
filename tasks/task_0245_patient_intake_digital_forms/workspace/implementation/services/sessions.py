"""IntakeSession orchestration: readiness, forms_complete, financial cascades,
queue enqueue/eject, the clock sweep, and expiry checks.

Traces to PRD §3.3, §3.4, §3.5, §3.6, §3.7, §3.10, §3.11, §3.12.
"""
import clock
import db
from services.common import touch

FINANCIAL_READY_GATE = {"INSURED", "SELF_PAY", "COPAY_SETTLED", "WAIVED"}
QUEUE_ACTIVE_STATES = {"WAITING", "CALLED", "IN_ROOM"}


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def session_cards(session_id):
    return [c for c in db.insurance_cards.values()
            if c["intake_session_id"] == session_id]


def session_consents(session_id):
    return [c for c in db.consent_documents.values()
            if c["intake_session_id"] == session_id]


def session_questionnaire(session_id):
    for q in db.questionnaire_responses.values():
        if q["intake_session_id"] == session_id:
            return q
    return None


def session_active_queue_entry(session_id):
    for q in db.queue_entries.values():
        if q["intake_session_id"] == session_id and q["status"] in QUEUE_ACTIVE_STATES:
            return q
    return None


def session_scheduled_reminders(session_id):
    return [r for r in db.reminders.values()
            if r["intake_session_id"] == session_id and r["status"] == "SCHEDULED"]


# --------------------------------------------------------------------------
# Expiry
# --------------------------------------------------------------------------
def is_expired(session):
    """A session is expired at-or-after expires_at by the clinic clock (PRD §2.6)."""
    clinic = db.clinics[session["clinic_id"]]
    now = clock.parse_instant(clinic["current_utc"])
    expires = clock.parse_instant(session["expires_at"])
    return now >= expires


# --------------------------------------------------------------------------
# forms_complete (PRD §3.4 / calc forms_complete)
# --------------------------------------------------------------------------
def compute_forms_complete(session):
    provider = db.providers[session["provider_id"]]
    required_codes = provider.get("required_consent_codes") or []
    required_sections = provider.get("questionnaire_required_sections") or []

    # consents_ok: every required code has a SIGNED ConsentDocument.
    signed_codes = {c["consent_code"] for c in session_consents(session["id"])
                    if c["status"] == "SIGNED"}
    consents_ok = all(code in signed_codes for code in required_codes)

    # questionnaire_ok: required sections empty OR an ACCEPTED response exists.
    if not required_sections:
        questionnaire_ok = True
    else:
        q = session_questionnaire(session["id"])
        questionnaire_ok = q is not None and q["status"] == "ACCEPTED"

    # eligibility_ok: the session's card resolved ELIGIBLE or INELIGIBLE.
    cards = session_cards(session["id"])
    eligibility_ok = any(c["eligibility_status"] in {"ELIGIBLE", "INELIGIBLE"}
                         for c in cards)

    return consents_ok and questionnaire_ok and eligibility_ok


def recompute_forms_complete(session):
    """Recompute the stored forms_complete flag; touch on change."""
    new_val = compute_forms_complete(session)
    if session["forms_complete"] != new_val:
        session["forms_complete"] = new_val
        touch(session)
    return new_val


# --------------------------------------------------------------------------
# Queue enqueue / eject
# --------------------------------------------------------------------------
def enqueue(session):
    """Create one WAITING KioskQueueEntry; bump clinic counters (PRD §3.4)."""
    clinic = db.clinics[session["clinic_id"]]
    now = db.now_iso()
    entry = {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
        "intake_session_id": session["id"],
        "clinic_id": session["clinic_id"],
        "exam_room_id": None,
        "enqueued_seq": db.next_enqueue_seq(session["clinic_id"]),
        "status": "WAITING",
    }
    db.queue_entries[entry["id"]] = entry
    clinic["active_queue_count"] += 1
    touch(clinic)
    return entry


def eject_queue_entry(entry):
    """Move an active queue entry to NO_SHOW; decrement clinic counter."""
    clinic = db.clinics[entry["clinic_id"]]
    entry["status"] = "NO_SHOW"
    touch(entry)
    clinic["active_queue_count"] -= 1
    touch(clinic)


# --------------------------------------------------------------------------
# Readiness advance (PRD §3.4)
# --------------------------------------------------------------------------
def try_advance_ready(session):
    """If forms_complete and the financial gate is met, advance IN_PROGRESS ->
    READY_FOR_VISIT and enqueue. Returns True when it advances."""
    if session["workflow_status"] != "IN_PROGRESS":
        return False
    if not session["forms_complete"]:
        return False
    if session["financial_status"] not in FINANCIAL_READY_GATE:
        return False
    session["workflow_status"] = "READY_FOR_VISIT"
    touch(session)
    enqueue(session)
    return True


def revert_ready_to_in_progress(session):
    """Revert READY_FOR_VISIT -> IN_PROGRESS and NO_SHOW its WAITING entry."""
    if session["workflow_status"] != "READY_FOR_VISIT":
        return
    session["workflow_status"] = "IN_PROGRESS"
    touch(session)
    entry = session_active_queue_entry(session["id"])
    if entry is not None:
        eject_queue_entry(entry)


def bubble_up(session):
    """Recompute forms_complete and attempt readiness (PRD §3.4, §3.7, §3.8)."""
    complete = recompute_forms_complete(session)
    if complete:
        try_advance_ready(session)
    else:
        # If a previously-ready session lost completeness, it reverts.
        if session["workflow_status"] == "READY_FOR_VISIT":
            revert_ready_to_in_progress(session)


# --------------------------------------------------------------------------
# Financial cascades (PRD §3.5, §3.6, §3.10)
# --------------------------------------------------------------------------
def set_financial(session, new_status):
    if session["financial_status"] != new_status:
        session["financial_status"] = new_status
        touch(session)


# --------------------------------------------------------------------------
# Clock sweep (PRD §3.12)
# --------------------------------------------------------------------------
def target_incomplete(session, target_kind):
    """Is the reminder's polymorphic target step still incomplete? (PRD §3.12)."""
    provider = db.providers[session["provider_id"]]
    if target_kind == "CONSENT":
        required_codes = provider.get("required_consent_codes") or []
        signed_codes = {c["consent_code"] for c in session_consents(session["id"])
                        if c["status"] == "SIGNED"}
        return not all(code in signed_codes for code in required_codes)
    if target_kind == "QUESTIONNAIRE":
        required_sections = provider.get("questionnaire_required_sections") or []
        if not required_sections:
            return False
        q = session_questionnaire(session["id"])
        return not (q is not None and q["status"] == "ACCEPTED")
    if target_kind == "COPAY":
        return session["financial_status"] == "COPAY_DUE"
    # GENERIC: incomplete while the overall packet is not yet complete.
    return not session["forms_complete"]


def run_sweep(clinic):
    """Expiration sweep then reminder sweep over one clinic (PRD §3.12)."""
    now = clock.parse_instant(clinic["current_utc"])

    # Expiration sweep: DRAFT/IN_PROGRESS sessions at-or-after expires_at -> EXPIRED.
    for session in db.intake_sessions.values():
        if session["clinic_id"] != clinic["id"]:
            continue
        if session["workflow_status"] not in {"DRAFT", "IN_PROGRESS"}:
            continue
        expires = clock.parse_instant(session["expires_at"])
        if now >= expires:
            session["workflow_status"] = "EXPIRED"
            touch(session)
            # Cascade: every SCHEDULED reminder on it -> SUPPRESSED.
            for r in session_scheduled_reminders(session["id"]):
                r["status"] = "SUPPRESSED"
                touch(r)

    # Reminder sweep: SCHEDULED reminders at-or-after scheduled_utc fire/suppress.
    for r in db.reminders.values():
        if r["status"] != "SCHEDULED":
            continue
        session = db.intake_sessions.get(r["intake_session_id"])
        if session is None or session["clinic_id"] != clinic["id"]:
            continue
        fire_at = clock.parse_instant(r["scheduled_utc"])
        if now < fire_at:
            continue
        session_dead = session["workflow_status"] in {"EXPIRED", "CANCELLED", "COMPLETED"}
        if not session_dead and target_incomplete(session, r["target_kind"]):
            r["status"] = "SENT"
        else:
            r["status"] = "SUPPRESSED"
        touch(r)
