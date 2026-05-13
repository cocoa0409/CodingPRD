"""InsuranceClaim lifecycle."""
from db import store
from errors import (
    ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_INSUFFICIENT_EVIDENCE,
    ERR_VALIDATION_ERROR, raise_error,
)
from services.utils import stamp_update
from services.audit import append_audit


def request_evidence(claim_id: str, caller_role: str, caller_id: str) -> dict:
    if claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    c = store.insurance_claims[claim_id]
    if c["status"] != "REPORTED":
        raise_error(ERR_INVALID_STATE, "Claim must be REPORTED")
    c["status"] = "EVIDENCE_PENDING"
    stamp_update(c)
    append_audit("CLAIM_REPORTED", "InsuranceClaim", c["id"], caller_role, caller_id,
                 {"status": "EVIDENCE_PENDING"})
    return c


def attach_evidence(claim_id: str, body: dict) -> dict:
    if claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    c = store.insurance_claims[claim_id]
    if c["status"] not in {"REPORTED", "EVIDENCE_PENDING"}:
        raise_error(ERR_INVALID_STATE, "Cannot attach evidence in current state")
    if not body.get("evidence_url"):
        raise_error(ERR_VALIDATION_ERROR, "Missing evidence_url")
    ev = {
        "evidence_url": body["evidence_url"],
        "description": body.get("description", ""),
        "id": store.new_id(),
        "created_at": store.now_iso(),
    }
    store.evidence_items.setdefault(claim_id, []).append(ev)
    c["evidence_count"] = int(c.get("evidence_count", 0)) + 1
    stamp_update(c)
    return c


def file_claim(claim_id: str, caller_role: str, caller_id: str) -> dict:
    if claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    c = store.insurance_claims[claim_id]
    if c["status"] != "EVIDENCE_PENDING":
        raise_error(ERR_INVALID_STATE, "Claim must be EVIDENCE_PENDING")
    if int(c.get("evidence_count", 0)) < 2:
        raise_error(ERR_INSUFFICIENT_EVIDENCE, "At least 2 evidence items required")
    c["status"] = "FILED"
    stamp_update(c)
    append_audit("CLAIM_FILED", "InsuranceClaim", c["id"], caller_role, caller_id,
                 {"evidence_count": c["evidence_count"]})
    return c


def insurance_decision(body: dict) -> dict:
    claim_id = body.get("claim_id")
    decision = body.get("decision")
    amount = body.get("amount_cents", 0)
    if not claim_id or claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    if decision not in {"APPROVED", "REJECTED"}:
        raise_error(ERR_VALIDATION_ERROR, "decision must be APPROVED or REJECTED")
    c = store.insurance_claims[claim_id]
    if c["status"] != "FILED":
        raise_error(ERR_INVALID_STATE, "Claim must be FILED to receive decision")
    if decision == "APPROVED":
        c["status"] = "APPROVED"
        c["paid_amount_cents"] = int(amount or 0)
        append_audit("CLAIM_APPROVED", "InsuranceClaim", c["id"], "system", "",
                     {"paid_amount_cents": c["paid_amount_cents"]})
    else:
        c["status"] = "REJECTED"
        c["paid_amount_cents"] = 0
        append_audit("CLAIM_REJECTED", "InsuranceClaim", c["id"], "system", "",
                     {})
    stamp_update(c)
    return c


def mark_paid(claim_id: str, caller_role: str, caller_id: str) -> dict:
    if claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    c = store.insurance_claims[claim_id]
    if c["status"] != "APPROVED":
        raise_error(ERR_INVALID_STATE, "Claim must be APPROVED to mark paid")
    if int(c.get("paid_amount_cents", 0)) <= 0:
        raise_error(ERR_INVALID_STATE, "paid_amount_cents must be > 0")
    c["status"] = "PAID"
    stamp_update(c)
    append_audit("CLAIM_PAID", "InsuranceClaim", c["id"], caller_role, caller_id, {})
    return c


def archive_claim(claim_id: str) -> dict:
    if claim_id not in store.insurance_claims:
        raise_error(ERR_NOT_FOUND, "Claim not found")
    c = store.insurance_claims[claim_id]
    if c["status"] not in {"PAID", "REJECTED"}:
        raise_error(ERR_INVALID_STATE, "Claim must be PAID or REJECTED to archive")
    c["status"] = "ARCHIVED"
    stamp_update(c)
    return c
