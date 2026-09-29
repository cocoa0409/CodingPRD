"""Informed decisions (PRD 3.9)."""

from flask import Blueprint, request

import auth
import calc
import response
import serialize
import store
import validation as v
from errors import ApiError

bp = Blueprint("decisions", __name__)

DECISION_TYPES = (
    "FILE_AFFIRMATIVE",
    "PURSUE_RELIEF_IN_COURT",
    "ACCEPT_VOLUNTARY_DEPARTURE",
    "APPEAL_DECISION",
    "WITHDRAW_CASE",
    "DECLINE_RELIEF",
)

REVOCATION_REASONS = (
    "CLIENT_CHANGED_MIND",
    "NEW_FACTS",
    "COUNSEL_ERROR",
    "LANGUAGE_ACCESS_DEFECT",
)

STAFFED = ("STAFFED", "SUPERVISED_STAFFED")
FILING_DECISION_TYPES = ("FILE_AFFIRMATIVE", "PURSUE_RELIEF_IN_COURT")


def _certified_declaration(matter_id):
    for row in store.db["declarations"].values():
        if row.get("matter_id") == matter_id and row.get("status") == "CERTIFIED":
            return row
    return None


@bp.post("/informed-decisions")
@auth.requires("CaseRepresentative", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def create_decision():
    payload = v.body()
    matter_id = v.as_id(payload, "matter_id")
    auth.scope_matter(matter_id)
    matter = store.get("matters", matter_id)
    if matter is None:
        raise ApiError("ERR_MATTER_NOT_FOUND")
    assignment_id = v.as_id(payload, "counseled_by_assignment_id")
    assignment = store.get("assignments", assignment_id)
    if assignment is None:
        raise ApiError("ERR_NOT_FOUND", "The counseling assignment does not exist.")
    session_id = v.as_id(payload, "readback_session_id", required=False, default=None)
    session = None
    if session_id is not None:
        session = store.get("sessions", session_id)
        if session is None:
            raise ApiError("ERR_NOT_FOUND", "The interpretation session does not exist.")

    decision_type = v.as_enum(payload, "decision_type", DECISION_TYPES)
    risks = v.as_str_list(payload, "risks_disclosed", allowed=sorted(calc.RISKS),
                          non_empty=False)
    alternatives = v.as_str_list(payload, "alternatives_disclosed",
                                 allowed=sorted(calc.ALTERNATIVES), non_empty=False)
    language = v.language_code(payload, "counseling_language_code")
    expected = v.as_int(payload, "expected_matter_version")

    if _certified_declaration(matter_id) is None:
        raise ApiError("ERR_DECLARATION_NOT_CERTIFIED",
                       "The matter carries no CERTIFIED declaration.")
    if assignment.get("matter_id") != matter_id:
        raise ApiError("ERR_ASSIGNMENT_MATTER_MISMATCH",
                       "counseled_by_assignment_id belongs to another matter.")
    if assignment.get("status") != "ACTIVE":
        raise ApiError("ERR_ASSIGNMENT_NOT_ACTIVE",
                       "The counseling assignment is not ACTIVE.")

    client = store.get("clients", matter.get("client_id"))
    if not risks or not alternatives:
        raise ApiError("ERR_CONSENT_SCOPE_INSUFFICIENT",
                       "risks_disclosed and alternatives_disclosed must both be "
                       "non-empty.")
    if client is None or client.get("confidentiality_consent_scope") == "NONE":
        raise ApiError("ERR_CONSENT_SCOPE_INSUFFICIENT",
                       "The client's confidentiality consent scope is NONE.")

    verified = client.get("preferred_language_code") == language
    if not verified and session is not None:
        if (session.get("matter_id") == matter_id
                and session.get("status") == "COMPLETED"
                and session.get("language_code") == language):
            verified = True
    if not verified:
        raise ApiError("ERR_COUNSELING_LANGUAGE_UNVERIFIED",
                       "The counseling language is neither the client's preferred "
                       "language nor covered by a completed interpretation session.")

    if int(matter.get("version") or 0) != expected:
        raise ApiError("ERR_STALE_MATTER_VERSION")

    row = store.insert("decisions", store.new_row({
        "matter_id": matter_id,
        "counseled_by_assignment_id": assignment_id,
        "readback_session_id": session_id,
        "decision_type": decision_type,
        "risks_disclosed": list(risks),
        "alternatives_disclosed": list(alternatives),
        "counseling_language_code": language,
        "language_match_verified": True,
        "status": "PENDING",
        "acknowledged_at_utc": None,
        "superseded_by_decision_id": None,
        "revocation_reason_code": None,
    }))
    for other in store.rows("decisions"):
        if other["id"] == row["id"]:
            continue
        if other.get("matter_id") != matter_id:
            continue
        if other.get("decision_type") != decision_type:
            continue
        if other.get("status") != "DOCUMENTED":
            continue
        other["status"] = "SUPERSEDED"
        other["superseded_by_decision_id"] = row["id"]
        store.touch(other)
    store.touch(matter)
    return response.created(serialize.decision(row))


@bp.get("/informed-decisions")
@auth.requires("ProgramDirector", "SupervisingAttorney", "CaseRepresentative",
               "ClientPortalUser", scoped=True)
def list_decisions():
    client_id = auth.portal_client_id()
    auth.check_rep_active()
    rows = store.rows("decisions")
    args = request.args
    if client_id is not None:
        rows = [r for r in rows
                if calc.matter_client_id(r.get("matter_id")) == client_id]
    for key in ("matter_id", "counseled_by_assignment_id", "readback_session_id",
                "superseded_by_decision_id", "decision_type", "status"):
        if args.get(key):
            rows = [r for r in rows if r.get(key) == args[key]]
    page, meta = store.paginate(rows, args)
    return response.collection([serialize.decision(r) for r in page], meta)


@bp.post("/informed-decisions/<decision_id>/transition")
@auth.requires("ClientPortalUser", "SupervisingAttorney", "ProgramDirector",
               scoped=True)
def transition_decision(decision_id):
    row = store.get("decisions", decision_id)
    if row is None:
        raise ApiError("ERR_NOT_FOUND", "The informed decision does not exist.")
    auth.scope_matter(row.get("matter_id"))
    payload = v.body()
    action = v.as_enum(payload, "action", ("ACKNOWLEDGE", "REVOKE"))
    matter = store.get("matters", row.get("matter_id"))

    if action == "ACKNOWLEDGE":
        if auth.role() != "ClientPortalUser":
            raise ApiError("ERR_ROLE_NOT_PERMITTED",
                           "Only the client may acknowledge an informed decision.")
        if row["status"] != "PENDING":
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "ACKNOWLEDGE is only legal from PENDING.")
        if not row.get("language_match_verified"):
            raise ApiError("ERR_COUNSELING_LANGUAGE_UNVERIFIED",
                           "The counseling language was never verified.")
        if matter is None or matter.get("representation_status") not in STAFFED:
            raise ApiError("ERR_INVALID_STATE_TRANSITION",
                           "The matter must be STAFFED or SUPERVISED_STAFFED.")
        row["status"] = "DOCUMENTED"
        row["acknowledged_at_utc"] = store.clock_iso()
        store.touch(row)
        return response.ok(serialize.decision(row))

    if auth.role() == "ClientPortalUser":
        raise ApiError("ERR_ROLE_NOT_PERMITTED",
                       "A client portal user may not revoke an informed decision.")
    if row["status"] not in ("PENDING", "DOCUMENTED"):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "REVOKE is only legal from PENDING or DOCUMENTED.")
    reason = v.as_enum(payload, "revocation_reason_code", REVOCATION_REASONS)
    if (matter is not None and matter.get("filing_status") == "FILED"
            and row["decision_type"] in FILING_DECISION_TYPES):
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "A filed matter's filing consent may not be revoked.")
    row["status"] = "REVOKED"
    row["revocation_reason_code"] = reason
    store.touch(row)
    return response.ok(serialize.decision(row))
