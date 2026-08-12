"""Shared entity helpers: common fields, touch, pipeline derivation."""

import db
from db import ts_now


def new_entity():
    """Base fields for a new resource per PRD §2.4."""
    now = ts_now()
    return {
        "id": db.new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }


def touch(entity):
    """Mutation bookkeeping: updated_at refresh + version increment."""
    entity["updated_at"] = ts_now()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Participant derived fields
# ---------------------------------------------------------------------------

IDENTITY_DOC_TYPES = {"STATE_ID", "MATRICULA_CONSULAR", "MUNICIPAL_ID", "FOREIGN_PASSPORT"}


def compute_docs_complete(participant):
    docs = participant.get("id_documents") or []
    has_identity = any(
        d.get("doc_type") in IDENTITY_DOC_TYPES and d.get("status") == "VERIFIED"
        for d in docs
    )
    has_address = any(
        d.get("doc_type") == "PROOF_OF_ADDRESS" and d.get("status") == "VERIFIED"
        for d in docs
    )
    return has_identity and has_address


def recompute_pipeline(participant_id):
    """Recompute participant.pipeline_stage per participant_pipeline precedence."""
    participant = db.participants.get(participant_id)
    if participant is None:
        return

    apps = [a for a in db.account_applications.values() if a["participant_id"] == participant_id]
    refs = [r for r in db.referrals.values() if r["participant_id"] == participant_id]

    if any(a["status"] == "OPENED" for a in apps):
        stage = "ACCOUNT_OPENED"
    elif any(a["status"] in ("SUBMITTED", "REINSTATED") for a in apps):
        stage = "APPLIED"
    elif any(r["status"] == "BOOKED" for r in refs):
        stage = "EVENT_BOOKED"
    elif participant.get("docs_complete"):
        stage = "DOCS_READY"
    elif any(r["status"] in ("DOCS_PENDING", "DOCS_COMPLETE") for r in refs):
        stage = "REFERRED"
    else:
        stage = "REGISTERED"

    if participant.get("pipeline_stage") != stage:
        participant["pipeline_stage"] = stage
        touch(participant)
