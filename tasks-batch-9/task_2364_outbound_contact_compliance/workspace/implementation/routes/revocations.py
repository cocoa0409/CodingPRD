"""Revocation intake, validation, rejection and propagation (§3.3)."""

from flask import Blueprint

import lookup
import validation as v
from calculations import propagation_deadline
from db import base_row, db, now, now_iso, public, touch
from derive import (
    ensure_internal_suppression,
    invalidate_internal_scrubs,
    revocations_of_contact,
    revoke_consents_in_scope,
    select_policy,
    touch_contact,
)
from errors import ApiError
from middleware import endpoint, payload
from response import created, ok
from util import dt_of, iso

bp = Blueprint("revocations", __name__)

CHANNELS_RECEIVED = ("VOICE", "SMS", "EMAIL", "WEB", "MAIL")
METHODS = ("REPLY_STOP", "VERBAL_REQUEST", "EMAIL_REQUEST", "WEB_PORTAL", "POSTAL_MAIL")
SCOPES = ("ALL_CHANNELS", "VOICE", "SMS")
REJECTION_REASONS = ("NOT_CONSUMER", "UNVERIFIABLE_IDENTITY", "DUPLICATE")

METHOD_CHANNEL = {
    "REPLY_STOP": "SMS",
    "VERBAL_REQUEST": "VOICE",
    "EMAIL_REQUEST": "EMAIL",
    "WEB_PORTAL": "WEB",
    "POSTAL_MAIL": "MAIL",
}


@bp.post("/compliance/revocation-requests")
@endpoint(["Consumer", "DialerOperator", "ComplianceOfficer"], consumer_owns_contact=True)
def log_revocation():
    body = payload()
    contact_id = v.req_str(body, "contact_id")
    channel_received = v.req_enum(body, "channel_received", CHANNELS_RECEIVED)
    method = v.req_enum(body, "method", METHODS)
    scope = v.req_enum(body, "scope", SCOPES)
    received_note = v.opt_str(body, "received_note")

    contact = lookup.contact(contact_id)

    for existing in revocations_of_contact(contact_id):
        if existing["intake_status"] == "RECEIVED":
            raise ApiError(
                "ERR_DUPLICATE_REVOCATION_PENDING",
                "An unadjudicated revocation request is already outstanding for this consumer.",
            )
    if METHOD_CHANNEL[method] != channel_received:
        raise ApiError(
            "ERR_METHOD_CHANNEL_MISMATCH",
            "That revocation method is not reasonable on the channel it arrived on.",
        )

    policy = select_policy(contact["state_code"])
    holidays = policy["holiday_dates"] if policy else []
    received_at = now()
    deadline = propagation_deadline(received_at, holidays)

    row = base_row()
    row.update(
        {
            "contact_id": contact_id,
            "channel_received": channel_received,
            "method": method,
            "scope": scope,
            "received_note": received_note,
            "received_at": iso(received_at),
            "intake_status": "RECEIVED",
            "propagation_status": "NOT_STARTED",
            "propagation_deadline_at": iso(deadline),
            "validated_at": None,
            "propagated_at": None,
            "consent_records_revoked_count": 0,
            "rejection_reason": None,
            "target_systems": None,
        }
    )
    db.revocation_requests[row["id"]] = row
    return created(public(row))


@bp.get("/compliance/revocation-requests/<request_id>")
@endpoint(["ComplianceOfficer", "DialerOperator", "Consumer"])
def read_revocation(request_id):
    return ok(public(lookup.revocation_request(request_id)))


@bp.post("/compliance/revocation-requests/<request_id>/validate")
@endpoint(["ComplianceOfficer"])
def validate_revocation(request_id):
    body = payload()
    v.req_str(body, "validation_note")
    request_row = lookup.revocation_request(request_id)
    if request_row["intake_status"] != "RECEIVED":
        raise ApiError(
            "ERR_REVOCATION_STATE_INVALID", "Only a RECEIVED revocation request may be validated."
        )

    request_row["intake_status"] = "VALIDATED"
    request_row["validated_at"] = now_iso()
    request_row["propagation_status"] = "IN_PROGRESS"

    contact = db.contacts.get(request_row["contact_id"])
    revoked = 0
    if contact is not None:
        revoked = revoke_consents_in_scope(contact, request_row["scope"])
    request_row["consent_records_revoked_count"] = revoked
    touch(request_row)

    if contact is not None:
        touch_contact(contact)
        ensure_internal_suppression(contact)
        invalidate_internal_scrubs(contact["state_code"])
    return ok(public(request_row))


@bp.post("/compliance/revocation-requests/<request_id>/reject")
@endpoint(["ComplianceOfficer"])
def reject_revocation(request_id):
    body = payload()
    reason = v.req_enum(body, "rejection_reason", REJECTION_REASONS)
    request_row = lookup.revocation_request(request_id)
    if request_row["intake_status"] != "RECEIVED":
        raise ApiError(
            "ERR_REVOCATION_STATE_INVALID", "Only a RECEIVED revocation request may be rejected."
        )
    request_row["intake_status"] = "REJECTED"
    request_row["rejection_reason"] = reason
    touch(request_row)
    return ok(public(request_row))


@bp.post("/compliance/revocation-requests/<request_id>/propagate")
@endpoint(["ComplianceOfficer"])
def propagate_revocation(request_id):
    body = payload()
    target_systems = v.req_str_list(body, "target_systems", min_len=0)
    request_row = lookup.revocation_request(request_id)
    if (
        request_row["propagation_status"] != "IN_PROGRESS"
        or request_row["intake_status"] != "VALIDATED"
    ):
        raise ApiError(
            "ERR_REVOCATION_STATE_INVALID",
            "Propagation requires a VALIDATED intake with propagation IN_PROGRESS.",
        )

    stamp = now()
    request_row["target_systems"] = target_systems
    request_row["propagated_at"] = now_iso()
    deadline = dt_of(request_row["propagation_deadline_at"])
    overdue = stamp > deadline
    request_row["propagation_status"] = "OVERDUE" if overdue else "PROPAGATED"
    touch(request_row)

    if overdue:
        contact = db.contacts.get(request_row["contact_id"])
        if contact is not None:
            touch_contact(contact)
    return ok(public(request_row))
