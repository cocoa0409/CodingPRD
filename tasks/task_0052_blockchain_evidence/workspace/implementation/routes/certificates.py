"""Certificate routes (issue, read, download, revoke)."""
from flask import Blueprint, g, request

import db
from clock import now, parse_iso
from errors import err
from middleware import require_auth
from response import success
from services import audit
from services.lifecycle import new_verification_code
from services.lookup import (
    certificate_for_evidence, get_certificate, get_evidence,
    latest_on_chain_tx_for_evidence, notarization_for_evidence,
)
from services.validation import get_body, maybe_check_version, require_enum, require_str


bp = Blueprint("certificates", __name__)

VALID_TEMPLATES = {"STANDARD", "PREMIUM", "JUDICIAL"}
VALID_FORMATS = {"pdf", "png", "json"}


def _public(c: dict) -> dict:
    return {
        "id": c["id"],
        "evidence_id": c["evidence_id"],
        "template_code": c["template_code"],
        "verification_code": c["verification_code"],
        "embedded_timestamp": c["embedded_timestamp"],
        "tx_hash_ref": c["tx_hash_ref"],
        "chain_id": c["chain_id"],
        "hash_snapshot": c["hash_snapshot"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _can_read(c: dict) -> bool:
    if g.user_role in ("PlatformAdmin", "JudicialOfficer"):
        return True
    if g.user_role == "Customer":
        ev = db.evidences.get(c["evidence_id"])
        return ev is not None and ev["customer_id"] == g.user_id
    return False


@bp.route("/certificates", methods=["POST"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def issue_certificate():
    body = get_body()
    evidence_id = require_str(body, "evidence_id")
    template_code = require_enum(body, "template_code", VALID_TEMPLATES)

    ev = get_evidence(evidence_id)

    if g.user_role == "Customer" and g.user_id != ev["customer_id"]:
        raise err("ERR_PERMISSION_DENIED",
                  "Customer X-User-ID does not match evidence customer_id")

    if ev["status"] != "CONFIRMED":
        raise err("ERR_EVIDENCE_NOT_CONFIRMED",
                  f"Evidence must be CONFIRMED; current status: {ev['status']}")

    notar = notarization_for_evidence(evidence_id)
    if notar is None:
        raise err("ERR_TIMESTAMP_REQUIRED",
                  "Evidence has no TimestampNotarization")

    tx = latest_on_chain_tx_for_evidence(evidence_id)
    if tx is None:
        # In the batch path the evidence has no per-evidence tx; we still
        # need a tx_hash_ref — use the batch's confirmed tx.
        batch_id = ev.get("batch_id")
        if batch_id:
            from services.lookup import latest_on_chain_tx_for_batch
            tx = latest_on_chain_tx_for_batch(batch_id)
    if tx is None:
        raise err("ERR_INVALID_STATE", "No on-chain transaction for this evidence")

    # Mint a unique verification code
    code = new_verification_code()
    while code in db.verification_code_index:
        code = new_verification_code()

    cert = {
        "evidence_id": evidence_id,
        "template_code": template_code,
        "verification_code": code,
        "embedded_timestamp": notar["trusted_time"],
        "tx_hash_ref": tx["tx_hash"],
        "chain_id": ev["chain_id"],
        "hash_snapshot": ev["file_hash"],
        "status": "ISSUED",
    }
    db.stamp_create(cert, common_fields=True)
    db.certificates[cert["id"]] = cert
    db.verification_code_index[code] = cert["id"]

    audit.append(
        event_type="CERTIFICATE_ISSUED",
        target_entity="Certificate",
        target_id=cert["id"],
        detail={"evidence_id": evidence_id, "template_code": template_code},
    )
    return success(_public(cert), 201)


@bp.route("/certificates/<c_id>", methods=["GET"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def read_certificate(c_id):
    c = get_certificate(c_id)
    if not _can_read(c):
        raise err("ERR_PERMISSION_DENIED", "Cannot read this certificate")
    return success(_public(c), 200)


@bp.route("/certificates/<c_id>/download", methods=["GET"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def download_certificate(c_id):
    c = get_certificate(c_id)
    if not _can_read(c):
        raise err("ERR_PERMISSION_DENIED", "Cannot read this certificate")

    fmt = request.args.get("format")
    if fmt not in VALID_FORMATS:
        raise err("ERR_VALIDATION_FAILED",
                  f"format must be one of {sorted(list(VALID_FORMATS))}")

    ev = db.evidences.get(c["evidence_id"])
    if ev is not None and ev.get("expires_at"):
        try:
            exp_dt = parse_iso(ev["expires_at"])
            if now() >= exp_dt:
                raise err("ERR_EVIDENCE_EXPIRED",
                          "Evidence has expired; certificate download is blocked")
        except ValueError:
            pass

    payload = {
        "certificate_id": c["id"],
        "format": fmt,
        "verification_code": c["verification_code"],
        "hash_snapshot": c["hash_snapshot"],
        "tx_hash_ref": c["tx_hash_ref"],
        "chain_id": c["chain_id"],
        "embedded_timestamp": c["embedded_timestamp"],
        "template_code": c["template_code"],
        "status": c["status"],
        "content": f"<certificate id={c['id']} format={fmt}>",
    }
    return success(payload, 200)


@bp.route("/certificates/<c_id>/revoke", methods=["POST"])
@require_auth(roles={"PlatformAdmin"})
def revoke_certificate(c_id):
    body = get_body()
    c = get_certificate(c_id)
    maybe_check_version(body, c)
    if c["status"] != "ISSUED":
        raise err("ERR_INVALID_STATE",
                  f"Certificate is in {c['status']}, expected ISSUED")
    c["status"] = "REVOKED"
    db.stamp_update(c)
    return success(_public(c), 200)
