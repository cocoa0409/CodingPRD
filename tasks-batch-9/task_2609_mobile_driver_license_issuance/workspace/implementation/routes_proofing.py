"""Identity proofing: sessions, evidence, preview, submission and adjudication."""

from datetime import timedelta

from flask import Blueprint, g

import calc
import cascade
import derive
import gates
import lookup
import serialize
import validate as v
from auth import endpoint
from envelope import ok, ok_list
from errors import ApiError
from store import base_row, db, now, profile_settings, sort_rows, touch

bp = Blueprint("proofing", __name__, url_prefix="/mdl")

EVIDENCE_TYPES = (
    "DOCUMENT_SCAN", "BIOMETRIC_MATCH", "KNOWLEDGE_CHECK", "ADDRESS_CORROBORATION",
)
QUALITIES = ("STRONG", "FAIR", "WEAK")
DECISIONS = ("VERIFY", "RETURN", "DENY")


@endpoint(bp, "/proofing-sessions", ["POST"], ["ProofingAgent"])
def create_proofing_session():
    body = v.body()
    holder_id = v.req_str(body, "holder_id")
    requested = v.req_enum(body, "requested_assurance_level", ("IAL1_5", "IAL2"))

    holder = lookup.holder(holder_id)
    gates.require_physical_eligible(holder)

    row = base_row("IdentityProofingSession")
    row["holder_id"] = holder["id"]
    row["requested_assurance_level"] = requested
    row["state"] = "COLLECTING"
    row["proofing_agent_user_id"] = g.user_id
    row["adjudicator_user_id"] = None
    row["submission_count"] = 0
    row["adjudication_score"] = None
    row["achieved_assurance_level"] = None
    row["verified_at"] = None
    row["assurance_expires_at"] = None
    row["return_reason"] = None
    db.proofing_sessions[row["id"]] = row
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/proofing-sessions/<session_id>", ["GET"],
          ["ProofingAgent", "CredentialAdjudicator", "SystemAdmin"])
def read_proofing_session(session_id):
    session = lookup.proofing_session(session_id)
    cascade.lazy_expire_proofing(session)
    return ok(serialize.dump(session))


@endpoint(bp, "/proofing-sessions/<session_id>/evidence", ["POST"], ["ProofingAgent"])
def append_evidence(session_id):
    body = v.body()
    evidence_type = v.req_enum(body, "evidence_type", EVIDENCE_TYPES)
    quality = v.req_enum(body, "quality", QUALITIES)
    captured_at = v.req_dt(body, "captured_at")
    source_reference = v.req_str(body, "source_reference")

    session = lookup.proofing_session(session_id)
    if session["state"] not in ("COLLECTING", "RETURNED"):
        raise ApiError("ERR_INVALID_STATE")

    row = base_row("ProofingEvidence", common_fields=False)
    row["proofing_session_id"] = session["id"]
    row["evidence_type"] = evidence_type
    row["quality"] = quality
    row["captured_at"] = captured_at
    row["source_reference"] = source_reference
    row["strength_points"] = calc.POINTS[evidence_type][quality]
    row["superseded"] = False
    db.evidence[row["id"]] = row

    if session["state"] == "RETURNED":
        session["state"] = "COLLECTING"
        session["return_reason"] = None
    touch(session)
    return ok(serialize.dump(row), 201)


@endpoint(bp, "/proofing-sessions/<session_id>/evidence", ["GET"],
          ["ProofingAgent", "CredentialAdjudicator", "SystemAdmin"])
def list_evidence(session_id):
    limit, offset = v.pagination()
    evidence_type = v.q_enum("evidence_type", EVIDENCE_TYPES)
    session = lookup.proofing_session(session_id)
    rows = derive.evidence_of_session(session["id"])
    if evidence_type is not None:
        rows = [e for e in rows if e["evidence_type"] == evidence_type]
    return ok_list(serialize.dump_many(sort_rows(rows)), limit, offset)


@endpoint(bp, "/proofing-sessions/<session_id>/assurance-preview", ["GET"],
          ["ProofingAgent", "CredentialAdjudicator", "SystemAdmin"])
def assurance_preview(session_id):
    session = lookup.proofing_session(session_id)
    preview = calc.optimistic_score(session)
    strict = calc.strict_score(session)
    return ok({
        "preview_score": preview,
        "preview_assurance_level": calc.assurance_level_for(preview),
        "adjudication_score": strict,
        "adjudication_assurance_level": calc.assurance_level_for(strict),
        "submission_count": session["submission_count"],
        "evidence_type_count": calc.evidence_type_count(session),
    })


@endpoint(bp, "/proofing-sessions/<session_id>/submit", ["POST"], ["ProofingAgent"])
def submit_proofing_session(session_id):
    session = lookup.proofing_session(session_id)
    if session["state"] != "COLLECTING":
        raise ApiError("ERR_INVALID_STATE")
    holder = db.holders.get(session["holder_id"])
    gates.require_physical_eligible(holder)
    if derive.evidence_count(session["id"]) < 2:
        raise ApiError("ERR_INSUFFICIENT_EVIDENCE")

    session["state"] = "SUBMITTED"
    session["submission_count"] += 1
    touch(session)
    return ok(serialize.dump(session))


@endpoint(bp, "/proofing-sessions/<session_id>/adjudicate", ["POST"],
          ["CredentialAdjudicator"])
def adjudicate_proofing_session(session_id):
    body = v.body()
    decision = v.req_enum(body, "decision", DECISIONS)
    return_reason = v.opt_str(body, "return_reason")
    if decision == "RETURN" and return_reason is None:
        raise v.bad_request("Field 'return_reason' is required for a RETURN decision.")

    session = lookup.proofing_session(session_id)
    if session["state"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE")
    if g.user_id == session["proofing_agent_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    score = calc.strict_score(session)
    if decision == "VERIFY" and score < calc.IAL1_5_MIN_SCORE:
        raise ApiError("ERR_ASSURANCE_LEVEL_INSUFFICIENT")

    calc.recompute_superseded(session["id"])
    session["adjudication_score"] = score
    session["adjudicator_user_id"] = g.user_id

    if decision == "VERIFY":
        session["state"] = "VERIFIED"
        session["achieved_assurance_level"] = calc.assurance_level_for(score)
        session["verified_at"] = now()
        session["assurance_expires_at"] = now() + timedelta(
            days=profile_settings()["proofing_validity_days"]
        )
        session["return_reason"] = None
    elif decision == "RETURN":
        session["state"] = "RETURNED"
        session["return_reason"] = return_reason
    else:
        session["state"] = "DENIED"
        session["achieved_assurance_level"] = None

    touch(session)
    return ok(serialize.dump(session))
