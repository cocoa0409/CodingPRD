"""Session (RON) + Signer + Document routes and state machines (PRD §3.4-§3.6)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from domain import (
    find_session, find_notary, find_signer, find_document, audit,
    recompute_lifetime_fees, compute_session_fees, session_window_conflicts,
    fee_schedule_for, ACT_TYPES, ID_METHODS,
)
from errors import err
from middleware import endpoint
from response import success, list_response
from serialize import view, view_list
from validation import (
    get_body, require_str, optional_str, require_bool, require_int, require_enum,
    require_datetime, non_negative_cents, parse_pagination, paginate,
)

bp = Blueprint("sessions", __name__)


# ---------------------------------------------------------------------------
# Session CRUD + creation
# ---------------------------------------------------------------------------

@bp.post("/sessions")
@endpoint(("Notary",))
def create_session():
    body = get_body()
    notary_id = require_str(body, "notary_id")
    start_dt = require_datetime(body, "scheduled_start_at")
    end_dt = require_datetime(body, "scheduled_end_at")
    surcharge = require_int(body, "requested_surcharge_cents", default=0)
    fee_basis = require_enum(body, "fee_basis", {"PER_ACT", "AGGREGATE"}, default="PER_ACT")

    notary = find_notary(notary_id)
    non_negative_cents(surcharge, "requested_surcharge_cents")
    if not (end_dt > start_dt):
        raise err("ERR_VALIDATION", "scheduled_end_at must be after scheduled_start_at")
    # Half-open window conflict (PRD §3.4).
    if session_window_conflicts(notary_id, start_dt, end_dt):
        raise err("ERR_SESSION_TIME_CONFLICT", "Session window overlaps another session")

    rec = dict(new_common_fields())
    rec.update({
        "notary_id": notary_id,
        "jurisdiction_id": notary["jurisdiction_id"],
        "scheduled_start_at": body["scheduled_start_at"],
        "scheduled_end_at": body["scheduled_end_at"],
        "requested_surcharge_cents": surcharge,
        "fee_basis": fee_basis,
        "status": "SCHEDULED",
        "surcharge_charged_cents": 0,
        "act_fees_total_cents": 0,
        "session_total_fee_cents": 0,
        "_scheduled_start_dt": start_dt,
        "_scheduled_end_dt": end_dt,
    })
    store.sessions[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/sessions/<session_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_session(session_id):
    return success(view(find_session(session_id)))


@bp.get("/sessions")
@endpoint(("CommissionAuthority", "Notary"))
def list_sessions():
    limit, offset = parse_pagination()
    recs = list(store.sessions.values())
    nid = request.args.get("notary_id")
    jid = request.args.get("jurisdiction_id")
    status = request.args.get("status")
    if nid is not None:
        recs = [r for r in recs if r["notary_id"] == nid]
    if jid is not None:
        recs = [r for r in recs if r["jurisdiction_id"] == jid]
    if status is not None:
        recs = [r for r in recs if r["status"] == status]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Signer CRUD
# ---------------------------------------------------------------------------

@bp.post("/sessions/<session_id>/signers")
@endpoint(("Notary",))
def create_signer(session_id):
    find_session(session_id)
    body = get_body()
    full_name = require_str(body, "full_name")
    kba = require_bool(body, "kba_passed", default=False)
    cred = require_bool(body, "credential_analysis_passed", default=False)

    rec = dict(new_common_fields())
    rec.update({
        "session_id": session_id,
        "full_name": full_name,
        "kba_passed": kba,
        "credential_analysis_passed": cred,
        "id_status": "UNVERIFIED",
    })
    store.signers[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/sessions/<session_id>/signers")
@endpoint(("CommissionAuthority", "Notary"))
def list_session_signers(session_id):
    find_session(session_id)
    limit, offset = parse_pagination()
    recs = [s for s in store.signers.values() if s["session_id"] == session_id]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.get("/signers/<signer_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_signer(signer_id):
    return success(view(find_signer(signer_id)))


@bp.get("/signers")
@endpoint(("CommissionAuthority", "Notary"))
def list_signers():
    limit, offset = parse_pagination()
    recs = list(store.signers.values())
    sid = request.args.get("session_id")
    if sid is not None:
        recs = [r for r in recs if r["session_id"] == sid]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

@bp.post("/sessions/<session_id>/documents")
@endpoint(("Notary",))
def create_document(session_id):
    find_session(session_id)
    body = get_body()
    signer_id = require_str(body, "signer_id")
    act_type = require_enum(body, "act_type", ACT_TYPES)
    requested_fee = require_int(body, "requested_fee_cents")

    # signer_id FK existence + scope (belongs to this session) -> 404.
    signer = store.signers.get(signer_id)
    if signer is None or signer["session_id"] != session_id:
        raise err("ERR_NOT_FOUND", "Signer not found in this session")
    non_negative_cents(requested_fee, "requested_fee_cents")

    rec = dict(new_common_fields())
    rec.update({
        "session_id": session_id,
        "signer_id": signer_id,
        "act_type": act_type,
        "requested_fee_cents": requested_fee,
        "capped_fee_cents": 0,
        "status": "PENDING",
    })
    store.documents[rec["id"]] = rec
    return success(view(rec), status=201)


@bp.get("/sessions/<session_id>/documents")
@endpoint(("CommissionAuthority", "Notary"))
def list_session_documents(session_id):
    find_session(session_id)
    limit, offset = parse_pagination()
    recs = [d for d in store.documents.values() if d["session_id"] == session_id]
    signer_id = request.args.get("signer_id")
    if signer_id is not None:
        recs = [r for r in recs if r["signer_id"] == signer_id]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.get("/documents/<document_id>")
@endpoint(("CommissionAuthority", "Notary"))
def get_document(document_id):
    return success(view(find_document(document_id)))


@bp.get("/documents")
@endpoint(("CommissionAuthority", "Notary"))
def list_documents():
    limit, offset = parse_pagination()
    recs = list(store.documents.values())
    sid = request.args.get("session_id")
    signer_id = request.args.get("signer_id")
    if sid is not None:
        recs = [r for r in recs if r["session_id"] == sid]
    if signer_id is not None:
        recs = [r for r in recs if r["signer_id"] == signer_id]
    page, total = paginate(recs, limit, offset)
    return list_response(view_list(page), limit, offset, total)


# ---------------------------------------------------------------------------
# Session state machine (PRD §3.5, §3.6)
# ---------------------------------------------------------------------------

@bp.post("/sessions/<session_id>/begin-identity")
@endpoint(("Notary",))
def begin_identity(session_id):
    session = find_session(session_id)
    if session["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Session is not SCHEDULED")
    notary = store.notaries.get(session["notary_id"])
    if notary is None or not notary.get("enotary_authorized"):
        raise err("ERR_ENOTARY_NOT_AUTHORIZED", "Presiding notary not e-notary authorized")
    signers = [s for s in store.signers.values() if s["session_id"] == session_id]
    if not signers:
        raise err("ERR_NO_SIGNER", "No signer attached")
    session["status"] = "IDENTITY_PENDING"
    touch(session)
    return success(view(session))


@bp.post("/sessions/<session_id>/resolve-identity")
@endpoint(("Notary",))
def resolve_identity(session_id):
    session = find_session(session_id)
    body = get_body()
    outcome = require_enum(body, "outcome", {"VERIFIED", "FAILED"})
    if session["status"] != "IDENTITY_PENDING":
        raise err("ERR_INVALID_STATE", "Session is not IDENTITY_PENDING")
    signers = [s for s in store.signers.values() if s["session_id"] == session_id]

    if outcome == "VERIFIED":
        # Every signer must have both checks passed (PRD §3.5).
        if not all(s["kba_passed"] and s["credential_analysis_passed"] for s in signers):
            raise err("ERR_CREDENTIAL_NOT_VERIFIED", "Some signer credentials not verified")
        for s in signers:
            s["id_status"] = "VERIFIED"
            touch(s)
        session["status"] = "ID_VERIFIED"
    else:  # FAILED
        # At least one signer must still be missing a check (PRD §3.5).
        if all(s["kba_passed"] and s["credential_analysis_passed"] for s in signers):
            raise err("ERR_CREDENTIAL_ALREADY_VERIFIED", "Every signer already verified")
        for s in signers:
            if not (s["kba_passed"] and s["credential_analysis_passed"]):
                s["id_status"] = "FAILED"
                touch(s)
        session["status"] = "ID_FAILED"
    touch(session)
    return success(view(session))


@bp.post("/sessions/<session_id>/start")
@endpoint(("Notary",))
def start_session(session_id):
    session = find_session(session_id)
    if session["status"] != "ID_VERIFIED":
        raise err("ERR_INVALID_STATE", "Session is not ID_VERIFIED")
    docs = [d for d in store.documents.values() if d["session_id"] == session_id]
    if not docs:
        raise err("ERR_NO_DOCUMENT", "No document attached")
    session["status"] = "ACTIVE"
    touch(session)
    return success(view(session))


@bp.post("/sessions/<session_id>/documents/<document_id>/notarize")
@endpoint(("Notary",))
def notarize_document(session_id, document_id):
    # Left-to-right path resolution: session before document (PRD §2.8).
    session = find_session(session_id)
    doc = store.documents.get(document_id)
    if doc is None or doc["session_id"] != session_id:
        raise err("ERR_NOT_FOUND", "Document not found in this session")
    body = get_body()
    # id_method optional; if present must be a valid enum.
    if body.get("id_method") is not None:
        require_enum(body, "id_method", ID_METHODS)
    if doc["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Document is not PENDING")
    if session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Session is not ACTIVE")
    signer = store.signers.get(doc["signer_id"])
    if signer is None or signer["id_status"] != "VERIFIED":
        raise err("ERR_SIGNER_NOT_VERIFIED", "Linked signer is not VERIFIED")
    doc["status"] = "NOTARIZED"
    touch(doc)
    return success(view(doc))


@bp.post("/sessions/<session_id>/documents/<document_id>/refuse")
@endpoint(("Notary",))
def refuse_document(session_id, document_id):
    find_session(session_id)
    doc = store.documents.get(document_id)
    if doc is None or doc["session_id"] != session_id:
        raise err("ERR_NOT_FOUND", "Document not found in this session")
    if doc["status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Document is not PENDING")
    doc["status"] = "REFUSED"
    touch(doc)
    return success(view(doc))


@bp.post("/sessions/<session_id>/complete")
@endpoint(("Notary",))
def complete_session(session_id):
    session = find_session(session_id)
    if session["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Session is not ACTIVE")
    notarized = [
        d for d in store.documents.values()
        if d["session_id"] == session_id and d["status"] == "NOTARIZED"
    ]
    if not notarized:
        raise err("ERR_NO_NOTARIZED_DOCUMENT", "No notarized document in session")

    # Atomic completion: stamp fees, spawn journal, re-sync ledger (PRD §3.6).
    notarized_docs = compute_session_fees(session)
    session["status"] = "COMPLETED"
    touch(session)

    notary = store.notaries.get(session["notary_id"])
    for d in sorted(notarized_docs, key=lambda x: (x["created_at"], x.get("_seq", 0))):
        entry = dict(new_common_fields())
        entry.update({
            "notary_id": session["notary_id"],
            "session_id": session_id,
            "document_id": d["id"],
            "act_type": d["act_type"],
            "signer_name": _signer_name_for(d),
            "id_method": None,
            "fee_charged_cents": d["capped_fee_cents"],
            "status": "POSTED",
            "amends_entry_id": None,
        })
        store.journal_entries[entry["id"]] = entry
    if notary is not None:
        recompute_lifetime_fees(notary)
        touch(notary)
    audit(session["notary_id"], "SESSION", session_id, "SESSION_COMPLETED", "NOTARY",
          "Session completed")
    return success(view(session))


@bp.post("/sessions/<session_id>/terminate")
@endpoint(("Notary", "CommissionAuthority"))
def terminate_session(session_id):
    session = find_session(session_id)
    # Terminate is legal from ID_FAILED or ACTIVE (PRD §3.5/§3.6).
    if session["status"] not in ("ID_FAILED", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Session cannot be terminated from this state")
    session["status"] = "TERMINATED"
    touch(session)
    for d in store.documents.values():
        if d["session_id"] == session_id and d["status"] == "PENDING":
            d["status"] = "REFUSED"
            touch(d)
    return success(view(session))


def _signer_name_for(doc):
    signer = store.signers.get(doc["signer_id"])
    return signer["full_name"] if signer else ""
