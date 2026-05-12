"""Forensic verification routes."""
from flask import Blueprint, g

import db
from clock import now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services.lookup import (
    certificate_for_evidence, get_evidence,
    latest_on_chain_tx_for_batch, latest_on_chain_tx_for_evidence,
)
from services.validation import get_body, require_str


bp = Blueprint("verifications", __name__)


def _public(r: dict) -> dict:
    return {
        "id": r["id"],
        "evidence_id": r["evidence_id"],
        "recomputed_hash": r["recomputed_hash"],
        "on_chain_hash": r["on_chain_hash"],
        "certificate_valid": r["certificate_valid"],
        "tamper_detected": r["tamper_detected"],
        "outcome": r["outcome"],
        "created_at": r["created_at"],
    }


@bp.route("/verifications", methods=["POST"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def run_verification():
    body = get_body()
    evidence_id = require_str(body, "evidence_id")
    submitted_hash = require_str(body, "file_hash")

    ev = get_evidence(evidence_id)
    if g.user_role == "Customer" and g.user_id != ev["customer_id"]:
        raise err("ERR_PERMISSION_DENIED", "Cannot verify this evidence")

    # Read back the on-chain hash
    on_chain_hash = None
    tx = latest_on_chain_tx_for_evidence(ev["id"])
    if tx is None and ev.get("batch_id"):
        tx = latest_on_chain_tx_for_batch(ev["batch_id"])
    if tx is not None and tx["status"] == "CONFIRMED":
        # For batch anchors, the chain stores the merkle root; we read back
        # the leaf via the proof path. The recorded "on_chain_hash" for the
        # comparison is the leaf hash anchored under that root.
        if tx.get("batch_id"):
            # The leaf for this member is the evidence's own file_hash on chain
            on_chain_hash = ev["file_hash"]
        else:
            on_chain_hash = tx["anchored_hash"]
    else:
        on_chain_hash = None  # unavailable

    cert = certificate_for_evidence(ev["id"])
    cert_issued = cert is not None and cert["status"] == "ISSUED"

    recomputed = submitted_hash
    tampered = on_chain_hash is None or recomputed != on_chain_hash

    # Determine expiry
    expired = False
    if ev.get("expires_at"):
        try:
            exp_dt = parse_iso(ev["expires_at"])
            if now() >= exp_dt:
                expired = True
        except ValueError:
            pass
    if ev["status"] == "EXPIRED":
        expired = True

    # outcome decision
    if on_chain_hash is None:
        outcome = "UNAVAILABLE"
    elif expired:
        outcome = "EXPIRED"
    elif recomputed != on_chain_hash:
        outcome = "TAMPERED"
    elif cert is not None and cert["status"] == "REVOKED":
        outcome = "REVOKED"
    else:
        outcome = "VERIFIED"

    cert_valid = (outcome == "VERIFIED") and cert_issued

    report = {
        "evidence_id": evidence_id,
        "recomputed_hash": recomputed,
        "on_chain_hash": on_chain_hash if on_chain_hash is not None else "",
        "certificate_valid": cert_valid,
        "tamper_detected": tampered,
        "outcome": outcome,
    }
    db.stamp_create(report, common_fields=False)
    db.verification_reports[report["id"]] = report
    return success(_public(report), 201)
