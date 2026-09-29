"""Presentation sessions: trust gates, minimisation, consent, disclosure, voiding."""

from flask import Blueprint, g

import calc
import cascade
import derive
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import (active_profile_row, base_row, db, newest_snapshot, now,
                   profile_settings, sort_rows, touch)

bp = Blueprint("presentation", __name__, url_prefix="/mdl")

CONTEXTS = ("ROUTINE", "AGE_ONLY", "LAW_ENFORCEMENT")
HANDLING = ("NO_SURRENDER", "TAP_TO_READ", "SURRENDER_REQUESTED")
SESSION_STATES = (
    "REQUESTED", "CONSENT_PENDING", "CONSENT_GRANTED", "COMPLETED",
    "DENIED_BY_HOLDER", "BLOCKED_BY_POLICY", "ABORTED",
)
CONSENT_DECISIONS = ("APPROVE", "DENY")
UNLOCK_METHODS = ("BIOMETRIC", "PASSCODE")


@endpoint(bp, "/presentation-sessions", ["POST"], ["VerifierOperator"])
def open_presentation_session():
    body = v.body()
    credential_id = v.req_str(body, "credential_id")
    reader_app_id = v.req_str(body, "reader_app_id")
    context = v.req_enum(body, "context", CONTEXTS)
    purpose = v.req_str(body, "purpose")
    requested_elements = v.req_array_str(body, "requested_elements")
    handset_handling = v.req_enum(body, "handset_handling", HANDLING)
    retention_days = v.req_int(body, "retention_days", 0)

    # step 5: body foreign keys in declared order
    credential = lookup.credential(credential_id)
    reader_app = lookup.reader_app(reader_app_id)
    verifier = db.verifiers.get(reader_app["verifier_id"])

    # step 6: an operator presents only through its own reader application
    if g.user_role == "VerifierOperator" and g.user_id != reader_app["verifier_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # step 13: the handset is never surrendered, at the roadside or the till
    if handset_handling == "SURRENDER_REQUESTED":
        raise ApiError("ERR_HANDSET_SURRENDER_PROHIBITED")

    # step 14: only a law-enforcement organisation may claim that context
    if context == "LAW_ENFORCEMENT" and verifier["category"] != "LAW_ENFORCEMENT":
        raise ApiError("ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED")

    # step 15: the reader must be listed and the trust list must cover now
    snapshot = newest_snapshot(active_profile_row())
    covered = (snapshot is not None
               and snapshot["effective_from"] <= now() < snapshot["effective_until"])
    if reader_app["trust_state"] != "LISTED" or not covered:
        raise ApiError("ERR_READER_NOT_TRUSTED")

    # step 16: the organisation itself must still be trusted
    if verifier["trust_status"] not in ("APPROVED", "PROBATION"):
        raise ApiError("ERR_VERIFIER_NOT_TRUSTED")

    # step 27: minimisation; AGE_ONLY is strict and no row is created
    projection = calc.minimization(context, requested_elements, reader_app, verifier)
    if context == "AGE_ONLY" and projection["excess_element_count"] > 0:
        raise ApiError("ERR_DATA_MINIMIZATION_VIOLATION")

    # step 31: the contractual retention ceiling, inclusive
    if retention_days > verifier["retention_ceiling_days"]:
        raise ApiError("ERR_RETENTION_CEILING_EXCEEDED")

    # the fork: lazy expiry first, then presentability
    cascade.lazy_expire_credential(credential)
    if credential["lifecycle_state"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    row = base_row("PresentationSession")
    row["credential_id"] = credential["id"]
    row["reader_app_id"] = reader_app["id"]
    row["context"] = context
    row["purpose"] = purpose
    row["requested_elements"] = list(requested_elements)
    row["handset_handling"] = handset_handling
    row["retention_days"] = retention_days
    row["state"] = "REQUESTED"
    row["minimized_elements"] = projection["minimized_elements"]
    row["withheld_elements"] = projection["withheld_elements"]
    row["excess_element_count"] = projection["excess_element_count"]
    row["age_attestation_only"] = projection["age_attestation_only"]
    row["disclosed_element_count"] = 0
    row["billed_amount_cents"] = 0
    row["billing_state"] = "UNBILLED"
    row["consent_unlock_method"] = None
    row["abort_reason"] = None
    row["opened_at"] = now()
    db.presentation_sessions[row["id"]] = row

    status = calc.revocation_status(credential)
    freshness = profile_settings()["revocation_freshness_seconds"]
    presentable = (credential["sync_state"] == "IN_SYNC"
                   and status["staleness_seconds"] <= freshness)
    if presentable:
        row["state"] = "CONSENT_PENDING"
    else:
        row["state"] = "BLOCKED_BY_POLICY"
        cascade.append_log_entry(row, "BLOCKED_BY_POLICY")

    return ok(serialize.dump(row), 201)


@endpoint(bp, "/presentation-sessions/<session_id>", ["GET"],
          ["VerifierOperator", "Holder", "PrivacyAuditor", "SystemAdmin"])
def read_presentation_session(session_id):
    return ok(serialize.dump(lookup.presentation_session(session_id)))


@endpoint(bp, "/presentation-sessions", ["GET"],
          ["VerifierOperator", "PrivacyAuditor", "SystemAdmin", "Holder"])
def list_presentation_sessions():
    limit, offset = v.pagination()
    credential_id = v.q_str("credential_id")
    reader_app_id = v.q_str("reader_app_id")
    state = v.q_enum("state", SESSION_STATES)

    rows = list(db.presentation_sessions.values())
    if credential_id is not None:
        rows = [s for s in rows if s["credential_id"] == credential_id]
    if reader_app_id is not None:
        rows = [s for s in rows if s["reader_app_id"] == reader_app_id]
    if state is not None:
        rows = [s for s in rows if s["state"] == state]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/presentation-sessions/<session_id>/consent", ["POST"], ["Holder"])
def record_consent(session_id):
    body = v.body()
    decision = v.req_enum(body, "consent_decision", CONSENT_DECISIONS)
    unlock_method = v.opt_str(body, "unlock_method")
    if decision == "APPROVE" and unlock_method is None:
        raise v.bad_request("Field 'unlock_method' is required to APPROVE consent.")

    session = lookup.presentation_session(session_id)
    credential = db.credentials.get(session["credential_id"])

    # step 6: consent belongs to the resident and to nobody else
    if g.user_role == "Holder" and g.user_id != credential["holder_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # step 9: the session must still be awaiting the holder's decision
    if session["state"] != "CONSENT_PENDING":
        raise ApiError("ERR_SESSION_NOT_CONSENT_PENDING")

    # step 28: the bound unlock method must be reproduced exactly
    if decision == "APPROVE":
        if unlock_method != credential["protection_method_at_activation"]:
            raise ApiError("ERR_PROTECTION_METHOD_MISMATCH")
        session["state"] = "CONSENT_GRANTED"
        session["consent_unlock_method"] = unlock_method
        touch(session)
    else:
        session["state"] = "DENIED_BY_HOLDER"
        touch(session)
        # a reader that over-asks accrues exposure even on a refusal
        cascade.append_log_entry(session, "DENIED_BY_HOLDER")

    return ok(serialize.dump(session))


@endpoint(bp, "/presentation-sessions/<session_id>/disclose", ["POST"],
          ["VerifierOperator"])
def disclose(session_id):
    session = lookup.presentation_session(session_id)
    reader_app = db.reader_apps.get(session["reader_app_id"])
    verifier = db.verifiers.get(reader_app["verifier_id"])

    # step 6: the disclosure belongs to the reader app's own operator
    if g.user_role == "VerifierOperator" and g.user_id != reader_app["verifier_id"]:
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # step 7: only a consented session may complete
    if session["state"] != "CONSENT_GRANTED":
        raise ApiError("ERR_INVALID_STATE")

    # step 31: the retention ceiling is enforced at both ends
    if session["retention_days"] > verifier["retention_ceiling_days"]:
        raise ApiError("ERR_RETENTION_CEILING_EXCEEDED")

    # step 32: unsettled query charges bar further disclosure
    balance = derive.billable_query_balance_cents(verifier["id"])
    if balance > calc.MAX_UNBILLED_BALANCE_CENTS:
        raise ApiError("ERR_VERIFIER_ACCOUNT_DELINQUENT")

    billed = reader_app["base_rate_cents"]
    session["state"] = "COMPLETED"
    session["disclosed_element_count"] = len(session["minimized_elements"])
    session["billed_amount_cents"] = billed
    session["billing_state"] = "BILLED"
    touch(session)

    cascade.append_log_entry(
        session, "DISCLOSED",
        billed_amount_cents=billed,
        billing_state="BILLED",
        disclosed_element_count=session["disclosed_element_count"],
    )

    index, _count = calc.rolling_window_index(verifier)
    verifier["exposure_index"] = index
    touch(verifier)
    calc.apply_exposure_thresholds(verifier, index)

    return ok(serialize.dump(session))


@endpoint(bp, "/presentation-sessions/<session_id>/void-billing", ["POST"],
          ["PrivacyAuditor"])
def void_billing(session_id):
    session = lookup.presentation_session(session_id)

    # step 10: only a live billing can be voided, and only once
    if session["billing_state"] != "BILLED":
        raise ApiError("ERR_BILLING_ALREADY_VOIDED")

    voided = session["billed_amount_cents"]
    session["billing_state"] = "VOIDED"
    touch(session)

    for entry in derive.log_entries_of_session(session["id"]):
        entry["billing_state"] = "VOIDED"

    reader_app = db.reader_apps.get(session["reader_app_id"])
    verifier = db.verifiers.get(reader_app["verifier_id"]) if reader_app else None
    if verifier is not None:
        # the exposure index is deliberately left alone: a billing
        # compensation must never move the privacy score.
        verifier["credited_amount_cents"] += voided
        touch(verifier)

    return ok(serialize.dump(session))


@endpoint(bp, "/presentation-sessions/<session_id>/log-entries", ["GET"],
          ["PrivacyAuditor", "SystemAdmin", "Holder"])
def list_session_log_entries(session_id):
    limit, offset = v.pagination()
    session = lookup.presentation_session(session_id)
    rows = sorted(derive.log_entries_of_session(session["id"]),
                  key=lambda e: (e["recorded_at"], e["_seq"]))
    return ok_list(serialize.dump_many(rows), limit, offset)
