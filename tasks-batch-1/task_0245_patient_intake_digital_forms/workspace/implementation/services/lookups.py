"""Existence lookups that raise the correct type-specific 404 (PRD §2.5)."""
import db
from errors import (
    err,
    ERR_CLINIC_NOT_FOUND,
    ERR_PROVIDER_NOT_FOUND,
    ERR_EXAM_ROOM_NOT_FOUND,
    ERR_PATIENT_NOT_FOUND,
    ERR_APPOINTMENT_NOT_FOUND,
    ERR_SESSION_NOT_FOUND,
    ERR_INSURANCE_CARD_NOT_FOUND,
    ERR_ELIGIBILITY_CHECK_NOT_FOUND,
    ERR_CONSENT_NOT_FOUND,
    ERR_QUESTIONNAIRE_NOT_FOUND,
    ERR_PAYMENT_NOT_FOUND,
    ERR_QUEUE_ENTRY_NOT_FOUND,
    ERR_ROOM_BOOKING_NOT_FOUND,
    ERR_REMINDER_NOT_FOUND,
    ERR_SYNC_JOB_NOT_FOUND,
)


def _get(table, key, error_id):
    rec = table.get(key)
    if rec is None:
        raise err(error_id)
    return rec


def get_clinic(cid):
    return _get(db.clinics, cid, ERR_CLINIC_NOT_FOUND)


def get_provider(pid):
    return _get(db.providers, pid, ERR_PROVIDER_NOT_FOUND)


def get_exam_room(rid):
    return _get(db.exam_rooms, rid, ERR_EXAM_ROOM_NOT_FOUND)


def get_patient(pid):
    return _get(db.patients, pid, ERR_PATIENT_NOT_FOUND)


def get_appointment(aid):
    return _get(db.appointments, aid, ERR_APPOINTMENT_NOT_FOUND)


def get_session(sid):
    return _get(db.intake_sessions, sid, ERR_SESSION_NOT_FOUND)


def get_card(cid):
    return _get(db.insurance_cards, cid, ERR_INSURANCE_CARD_NOT_FOUND)


def get_eligibility_check(eid):
    return _get(db.eligibility_checks, eid, ERR_ELIGIBILITY_CHECK_NOT_FOUND)


def get_consent(cid):
    return _get(db.consent_documents, cid, ERR_CONSENT_NOT_FOUND)


def get_questionnaire(qid):
    return _get(db.questionnaire_responses, qid, ERR_QUESTIONNAIRE_NOT_FOUND)


def get_payment(pid):
    return _get(db.copay_payments, pid, ERR_PAYMENT_NOT_FOUND)


def get_queue_entry(qid):
    return _get(db.queue_entries, qid, ERR_QUEUE_ENTRY_NOT_FOUND)


def get_room_booking(bid):
    return _get(db.room_bookings, bid, ERR_ROOM_BOOKING_NOT_FOUND)


def get_reminder(rid):
    return _get(db.reminders, rid, ERR_REMINDER_NOT_FOUND)


def get_sync_job(jid):
    return _get(db.demographics_sync_jobs, jid, ERR_SYNC_JOB_NOT_FOUND)
