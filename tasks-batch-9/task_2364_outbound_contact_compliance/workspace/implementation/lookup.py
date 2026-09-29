"""Existence resolution in the family order of PRD §2.8 step 5."""

from db import db
from errors import ApiError

_FAMILIES = {
    "contacts": "ERR_CONTACT_NOT_FOUND",
    "campaigns": "ERR_CAMPAIGN_NOT_FOUND",
    "consent_records": "ERR_CONSENT_RECORD_NOT_FOUND",
    "revocation_requests": "ERR_REVOCATION_REQUEST_NOT_FOUND",
    "suppression_entries": "ERR_SUPPRESSION_ENTRY_NOT_FOUND",
    "scrub_jobs": "ERR_SCRUB_JOB_NOT_FOUND",
    "dialer_profiles": "ERR_DIALER_PROFILE_NOT_FOUND",
    "agent_scripts": "ERR_AGENT_SCRIPT_NOT_FOUND",
    "calling_window_policies": "ERR_CALLING_WINDOW_POLICY_NOT_FOUND",
    "contact_attempts": "ERR_CONTACT_ATTEMPT_NOT_FOUND",
    "complaints": "ERR_COMPLAINT_NOT_FOUND",
}


def find(collection, row_id):
    if not isinstance(row_id, str):
        raise ApiError(_FAMILIES[collection])
    row = getattr(db, collection).get(row_id)
    if row is None:
        raise ApiError(_FAMILIES[collection])
    return row


def contact(row_id):
    return find("contacts", row_id)


def campaign(row_id):
    return find("campaigns", row_id)


def consent_record(row_id):
    return find("consent_records", row_id)


def revocation_request(row_id):
    return find("revocation_requests", row_id)


def suppression_entry(row_id):
    return find("suppression_entries", row_id)


def scrub_job(row_id):
    return find("scrub_jobs", row_id)


def dialer_profile(row_id):
    return find("dialer_profiles", row_id)


def agent_script(row_id):
    return find("agent_scripts", row_id)


def calling_window_policy(row_id):
    return find("calling_window_policies", row_id)


def contact_attempt(row_id):
    return find("contact_attempts", row_id)


def complaint(row_id):
    return find("complaints", row_id)
