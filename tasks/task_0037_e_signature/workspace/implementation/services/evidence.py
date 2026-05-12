"""EvidencePackage seal/export per PRD §3.10, §3.11."""

import hashlib
import json

from db import DB
from clock import now
from errors import (
    APIError, validation_failed, invalid_state, not_found,
    ERR_SEGREGATION_OF_DUTIES, ERR_NOTARY_REFERENCE_REQUIRED,
)
from services.audit import append_audit, audit_chain_tip
from services.calculations import (
    compute_evidence_strength, compute_evidence_provisional,
)
from services.contracts import _ensure_evidence_package, get_contract


VALID_NOTARY = {"NONE", "NOTARY_PUBLIC", "BLOCKCHAIN"}


def _canonical(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def get_evidence_package(contract_id: str) -> dict:
    get_contract(contract_id)
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id:
            return e
    raise not_found("EvidencePackage not found")


def get_provisional(contract_id: str):
    c = get_contract(contract_id)
    score, tier = compute_evidence_provisional(c)
    return {"provisional_score": score, "provisional_tier": tier}


def seal_evidence(contract_id: str, payload: dict, *, actor_user_id: str, actor_role: str) -> dict:
    if payload is None:
        payload = {}
    if not isinstance(payload, dict):
        raise validation_failed("Body must be a JSON object")
    c = get_contract(contract_id)
    # Make sure evidence package exists; auto-init if contract is in COMPLETED/VOIDED
    pkg = None
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id:
            pkg = e
            break
    if pkg is None:
        # Per spec, the package should already exist after Contract terminal state
        # but if absent, create one in PENDING and try to advance.
        pkg = _ensure_evidence_package(contract_id, now())

    # State check: must be GENERATING (which implies contract reached terminal state)
    if pkg["status"] != "GENERATING":
        raise invalid_state("EvidencePackage not in GENERATING")

    # Validate payload shape (priority before SoD/notary-ref content checks)
    if "notary_provider" in payload:
        if payload["notary_provider"] not in VALID_NOTARY:
            raise validation_failed("notary_provider invalid")
    if "notary_reference" in payload:
        nr = payload["notary_reference"]
        if nr is not None and not isinstance(nr, str):
            raise validation_failed("notary_reference must be a string")

    # Segregation of duties (priority 8) — checked BEFORE notary reference (priority 19)
    if actor_user_id == c["initiator_user_id"]:
        raise APIError(ERR_SEGREGATION_OF_DUTIES,
                       "EvidenceArchivist cannot be the contract initiator", 403)

    # Apply notary updates from payload only after SoD passes
    if "notary_provider" in payload:
        pkg["notary_provider"] = payload["notary_provider"]
    if "notary_reference" in payload:
        pkg["notary_reference"] = payload["notary_reference"]

    # Notary reference required when provider != NONE (priority 19)
    if pkg["notary_provider"] != "NONE":
        if not pkg.get("notary_reference"):
            raise APIError(ERR_NOTARY_REFERENCE_REQUIRED,
                           "notary_reference required when notary_provider != NONE", 422)

    n = now()
    # Compute package_sha256 over canonical bundle:
    # {document_fingerprint, all TimestampTokens for contract, all consumed
    # IdentityVerifications, audit chain tip}
    tokens = sorted(
        [t for t in DB.timestamp_tokens.values() if t["contract_id"] == contract_id],
        key=lambda t: t["created_at"]
    )
    tokens_canon = [
        {
            "id": t["id"],
            "signing_party_id": t["signing_party_id"],
            "hash_signed": t["hash_signed"],
            "drift_seconds": t["drift_seconds"],
            "verification_status": t["verification_status"],
        }
        for t in tokens
    ]
    iv_rows = sorted(
        [iv for iv in DB.identity_verifications.values()
         if iv.get("contract_id") == contract_id and iv.get("signing_party_id") is not None],
        key=lambda iv: iv["created_at"]
    )
    iv_canon = [
        {
            "id": iv["id"],
            "subject_user_id": iv["subject_user_id"],
            "factors_passed": iv["factors_passed"],
            "identity_strength": iv["identity_strength"],
            "result": iv["result"],
        }
        for iv in iv_rows
    ]
    chain_tip = audit_chain_tip(contract_id)
    bundle = {
        "document_fingerprint_sha256": c.get("document_fingerprint_sha256"),
        "timestamp_tokens": tokens_canon,
        "identity_verifications": iv_canon,
        "audit_log_chain_tip": chain_tip,
    }
    pkg_sha = hashlib.sha256(_canonical(bundle)).hexdigest()

    pkg["status"] = "SEALED"
    pkg["package_sha256"] = pkg_sha
    pkg["sealed_at"] = n
    pkg["version"] += 1
    pkg["updated_at"] = n

    # Recompute Contract.evidence_strength_score and evidence_tier with notary bonus
    score, tier, _ = compute_evidence_strength(
        c, notary_provider=pkg["notary_provider"], apply_notary_bonus=True
    )
    c["evidence_strength_score"] = score
    c["evidence_tier"] = tier
    c["version"] += 1
    c["updated_at"] = n

    append_audit(
        contract_id=contract_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="EVIDENCE_SEALED",
        payload={"contract_id": contract_id, "package_sha256": pkg_sha},
    )
    return pkg


def export_evidence(contract_id: str, *, actor_user_id: str, actor_role: str) -> dict:
    c = get_contract(contract_id)
    pkg = None
    for e in DB.evidence_packages.values():
        if e["contract_id"] == contract_id:
            pkg = e
            break
    if pkg is None:
        raise not_found("EvidencePackage not found")
    if pkg["status"] != "SEALED":
        raise invalid_state("EvidencePackage not in SEALED")
    n = now()
    pkg["status"] = "EXPORTED"
    pkg["exported_at"] = n
    pkg["version"] += 1
    pkg["updated_at"] = n
    append_audit(
        contract_id=contract_id,
        actor_user_id=actor_user_id,
        actor_role=actor_role,
        action="EVIDENCE_EXPORTED",
        payload={"contract_id": contract_id},
    )
    return pkg
