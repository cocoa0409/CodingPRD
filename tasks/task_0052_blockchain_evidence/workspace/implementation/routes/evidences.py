"""Evidence routes (create, read, list, submit, resubmit)."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_auth, get_pagination
from response import success, success_list
from services import lifecycle
from services.lookup import get_customer, get_evidence
from services.validation import (
    get_body, is_hex_lower, maybe_check_version, require_enum, require_int, require_str,
)


bp = Blueprint("evidences", __name__)


VALID_TYPES = {"DOCUMENT", "IMAGE", "VIDEO", "CODE_REPOSITORY", "DATASET"}
VALID_PERIODS = {30, 90, 365, 1095}
VALID_HASH_ALGOS = {"SHA256", "SM3"}
VALID_CHAINS = {"ETHEREUM", "FABRIC", "BSN", "COSMOS"}
VALID_STATUSES = {"PENDING", "SUBMITTING", "CONFIRMED", "FAILED", "EXPIRED"}


def _evidence_public(e: dict) -> dict:
    return {
        "id": e["id"],
        "customer_id": e["customer_id"],
        "evidence_type": e["evidence_type"],
        "storage_period_days": e["storage_period_days"],
        "hash_algorithm": e["hash_algorithm"],
        "file_hash": e["file_hash"],
        "original_data_b64": e.get("original_data_b64"),
        "chain_id": e["chain_id"],
        "status": e["status"],
        "submission_attempts": e.get("submission_attempts", 0),
        "per_evidence_fee_cents": e.get("per_evidence_fee_cents"),
        "batch_id": e.get("batch_id"),
        "confirmed_at": e.get("confirmed_at"),
        "expires_at": e.get("expires_at"),
        "idempotency_key": e.get("idempotency_key"),
        "created_at": e["created_at"],
        "updated_at": e["updated_at"],
        "version": e["version"],
    }


def _can_read(e: dict) -> bool:
    if g.user_role in ("PlatformAdmin", "JudicialOfficer"):
        return True
    if g.user_role == "Customer":
        return g.user_id == e["customer_id"]
    return False


@bp.route("/evidences", methods=["POST"])
@require_auth(roles={"Customer"})
def create_evidence():
    body = get_body()
    customer_id = require_str(body, "customer_id")
    evidence_type = require_enum(body, "evidence_type", VALID_TYPES)
    storage_period_days = require_int(body, "storage_period_days")
    hash_algorithm = require_enum(body, "hash_algorithm", VALID_HASH_ALGOS)
    file_hash = require_str(body, "file_hash")
    chain_id = require_enum(body, "chain_id", VALID_CHAINS)
    original_data_b64 = body.get("original_data_b64")
    idempotency_key = body.get("idempotency_key")

    if original_data_b64 is not None and not isinstance(original_data_b64, str):
        raise err("ERR_VALIDATION_FAILED", "original_data_b64 must be a string or null")
    if idempotency_key is not None and not isinstance(idempotency_key, str):
        raise err("ERR_VALIDATION_FAILED", "idempotency_key must be a string or null")

    # Priority 3: caller ownership on POST /evidences — Customer must match body customer_id
    if g.user_id != customer_id:
        raise err("ERR_PERMISSION_DENIED",
                  "X-User-ID does not match body customer_id")

    # Priority 5: Customer existence
    get_customer(customer_id, body_ref=True)

    # Priority 8: hash format
    if not is_hex_lower(file_hash, 64):
        raise err("ERR_HASH_FORMAT_INVALID",
                  "file_hash must be 64 lowercase hex chars matching the declared algorithm")

    # Priority 11: storage period validity
    if storage_period_days not in VALID_PERIODS:
        raise err("ERR_PERIOD_INVALID",
                  "storage_period_days must be one of 30, 90, 365, 1095")

    # Priority 20: idempotency uniqueness
    if idempotency_key is not None:
        key = (customer_id, idempotency_key)
        if key in db.idempotency_index:
            raise err("ERR_DUPLICATE_IDEMPOTENCY_KEY",
                      "Duplicate (customer_id, idempotency_key) on Evidence")

    evidence = {
        "customer_id": customer_id,
        "evidence_type": evidence_type,
        "storage_period_days": storage_period_days,
        "hash_algorithm": hash_algorithm,
        "file_hash": file_hash,
        "original_data_b64": original_data_b64,
        "chain_id": chain_id,
        "status": "PENDING",
        "submission_attempts": 0,
        "per_evidence_fee_cents": None,
        "batch_id": None,
        "confirmed_at": None,
        "expires_at": None,
        "idempotency_key": idempotency_key,
    }
    db.stamp_create(evidence, common_fields=True)
    db.evidences[evidence["id"]] = evidence
    if idempotency_key is not None:
        db.idempotency_index[(customer_id, idempotency_key)] = evidence["id"]

    return success(_evidence_public(evidence), 201)


@bp.route("/evidences/<ev_id>", methods=["GET"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def read_evidence(ev_id):
    e = get_evidence(ev_id)
    if not _can_read(e):
        raise err("ERR_PERMISSION_DENIED", "Cannot read this evidence")
    return success(_evidence_public(e), 200)


@bp.route("/evidences", methods=["GET"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def list_evidences():
    status = request.args.get("status")
    customer_id = request.args.get("customer_id")
    limit, offset = get_pagination()

    if status is not None and status not in VALID_STATUSES:
        raise err("ERR_VALIDATION_FAILED",
                  f"status filter must be one of {sorted(list(VALID_STATUSES))}")

    rows = list(db.evidences.values())
    if g.user_role == "Customer":
        # Customer can only see their own
        rows = [e for e in rows if e["customer_id"] == g.user_id]
        if customer_id is not None and customer_id != g.user_id:
            # Customer querying someone else: empty
            rows = []
    elif customer_id is not None:
        rows = [e for e in rows if e["customer_id"] == customer_id]

    if status is not None:
        rows = [e for e in rows if e["status"] == status]

    rows.sort(key=lambda r: r["_seq"])  # created_at ascending
    total = len(rows)
    page = rows[offset: offset + limit]
    return success_list([_evidence_public(e) for e in page], limit, offset, total)


@bp.route("/evidences/<ev_id>/submit", methods=["POST"])
@require_auth(roles={"Customer"})
def submit_evidence(ev_id):
    body = get_body()
    e = get_evidence(ev_id)
    if g.user_id != e["customer_id"]:
        raise err("ERR_PERMISSION_DENIED",
                  "Customer X-User-ID does not match evidence customer_id")
    maybe_check_version(body, e)
    lifecycle.evidence_submit(e)
    return success(_evidence_public(e), 200)


@bp.route("/evidences/<ev_id>/resubmit", methods=["POST"])
@require_auth(roles={"Customer"})
def resubmit_evidence(ev_id):
    body = get_body()
    e = get_evidence(ev_id)
    if g.user_id != e["customer_id"]:
        raise err("ERR_PERMISSION_DENIED",
                  "Customer X-User-ID does not match evidence customer_id")
    maybe_check_version(body, e)
    lifecycle.evidence_resubmit(e)
    return success(_evidence_public(e), 200)
