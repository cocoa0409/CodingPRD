"""Consent capture, supersession, suspension and reinstatement (§3.2)."""

from flask import Blueprint

import lookup
import validation as v
from db import base_row, by_created_at, db, now_iso, public
from derive import (
    consents_of_contact,
    recompute_contact,
    remove_internal_entries_for,
    rows,
    touch_contact,
)
from db import touch
from errors import ApiError
from middleware import endpoint, payload
from response import created, listing, ok

bp = Blueprint("consent", __name__)

CHANNELS = ("VOICE", "SMS")
CONSENT_TYPES = ("EXPRESS_WRITTEN", "EXPRESS_ORAL", "ESTABLISHED_BUSINESS_RELATIONSHIP")
CAPTURE_METHODS = (
    "WEB_FORM",
    "PAPER_FORM",
    "IVR_RECORDING",
    "SMS_DOUBLE_OPT_IN",
    "AGENT_ATTESTATION",
)
STATUSES = ("ACTIVE", "SUSPENDED", "REVOKED", "SUPERSEDED")
READ_ROLES = ["ComplianceOfficer", "CampaignManager", "DialerOperator", "Consumer"]


@bp.post("/compliance/consent-records")
@endpoint(["Consumer", "ComplianceOfficer"], consumer_owns_contact=True)
def capture_consent():
    body = payload()
    contact_id = v.req_str(body, "contact_id")
    channel = v.req_enum(body, "channel", CHANNELS)
    consent_type = v.req_enum(body, "consent_type", CONSENT_TYPES)
    capture_method = v.req_enum(body, "capture_method", CAPTURE_METHODS)
    disclosure_script_id = v.req_str(body, "disclosure_script_id")
    disclosure_text_version = v.req_int(body, "disclosure_text_version", 1)
    if consent_type == "EXPRESS_WRITTEN":
        signature_evidence = v.req_str(body, "signature_evidence", allow_empty=False)
    else:
        signature_evidence = v.opt_str(body, "signature_evidence")
    expected_contact_version = v.req_int(body, "expected_contact_version")

    contact = lookup.contact(contact_id)
    lookup.agent_script(disclosure_script_id)

    recompute_contact(contact)
    if expected_contact_version != contact["version"]:
        raise ApiError(
            "ERR_STALE_CONTACT_VERSION",
            "expected_contact_version does not match the contact's current version.",
        )

    for record in by_created_at(consents_of_contact(contact_id)):
        if record["channel"] == channel and record["status"] == "ACTIVE":
            record["status"] = "SUPERSEDED"
            touch(record)

    row = base_row()
    row.update(
        {
            "contact_id": contact_id,
            "channel": channel,
            "consent_type": consent_type,
            "capture_method": capture_method,
            "disclosure_script_id": disclosure_script_id,
            "disclosure_text_version": disclosure_text_version,
            "signature_evidence": signature_evidence,
            "captured_at": now_iso(),
            "status": "ACTIVE",
            "suspended_reason": None,
            "revoked_at": None,
            "reinstatement_count": 0,
        }
    )
    db.consent_records[row["id"]] = row
    touch_contact(contact)
    return created(public(row))


@bp.get("/compliance/consent-records/<record_id>")
@endpoint(READ_ROLES)
def read_consent(record_id):
    return ok(public(lookup.consent_record(record_id)))


@bp.get("/compliance/consent-records")
@endpoint(READ_ROLES)
def list_consent():
    limit, offset = v.pagination()
    contact_id = v.query_str("contact_id")
    disclosure_script_id = v.query_str("disclosure_script_id")
    channel = v.query_enum("channel", CHANNELS)
    status = v.query_enum("status", STATUSES)

    matches = rows("consent_records")
    if contact_id is not None:
        matches = [r for r in matches if r["contact_id"] == contact_id]
    if disclosure_script_id is not None:
        matches = [r for r in matches if r["disclosure_script_id"] == disclosure_script_id]
    if channel is not None:
        matches = [r for r in matches if r["channel"] == channel]
    if status is not None:
        matches = [r for r in matches if r["status"] == status]
    matches = by_created_at(matches)
    page, total = v.paginate(matches, limit, offset)
    return listing([public(r) for r in page], limit, offset, total)


@bp.post("/compliance/consent-records/<record_id>/suspend")
@endpoint(["ComplianceOfficer"])
def suspend_consent(record_id):
    body = payload()
    reason = v.req_str(body, "reason")
    record = lookup.consent_record(record_id)
    if record["status"] != "ACTIVE":
        raise ApiError("ERR_CONSENT_STATE_INVALID", "Only an ACTIVE consent record may be suspended.")

    record["status"] = "SUSPENDED"
    record["suspended_reason"] = reason
    touch(record)
    contact = db.contacts.get(record["contact_id"])
    if contact is not None:
        touch_contact(contact)
    return ok(public(record))


@bp.post("/compliance/consent-records/<record_id>/reinstate")
@endpoint(["ComplianceOfficer"])
def reinstate_consent(record_id):
    body = payload()
    v.req_str(body, "reinstatement_note")
    record = lookup.consent_record(record_id)
    if record["status"] not in ("SUSPENDED", "REVOKED"):
        raise ApiError(
            "ERR_CONSENT_STATE_INVALID",
            "Only a SUSPENDED or REVOKED consent record may be reinstated.",
        )

    for other in consents_of_contact(record["contact_id"]):
        if other["id"] == record["id"]:
            continue
        if other["channel"] == record["channel"] and other["status"] == "ACTIVE":
            raise ApiError(
                "ERR_CONSENT_CHANNEL_CONFLICT",
                "Another ACTIVE consent record already covers this contact and channel.",
            )

    was_revoked = record["status"] == "REVOKED"
    record["status"] = "ACTIVE"
    record["reinstatement_count"] = record["reinstatement_count"] + 1
    if was_revoked:
        record["revoked_at"] = None
    else:
        record["suspended_reason"] = None
    touch(record)

    contact = db.contacts.get(record["contact_id"])
    if contact is not None:
        touch_contact(contact)
        if was_revoked and contact["internal_dnc_status"] == "CLEAR":
            remove_internal_entries_for(contact["phone_number"])
    return ok(public(record))
