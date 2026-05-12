"""Batch routes (create, read, submit, proof)."""
from flask import Blueprint, g, request

import db
from errors import err
from middleware import require_auth
from response import success
from services import lifecycle
from services.lookup import get_batch, get_customer, get_evidence
from services.merkle import merkle_proof, merkle_root
from services.validation import get_body, maybe_check_version, require_enum, require_str


bp = Blueprint("batches", __name__)


VALID_CHAINS = {"ETHEREUM", "FABRIC", "BSN", "COSMOS"}


def _public(b: dict) -> dict:
    return {
        "id": b["id"],
        "customer_id": b["customer_id"],
        "chain_id": b["chain_id"],
        "evidence_count": b["evidence_count"],
        "merkle_root": b["merkle_root"],
        "status": b["status"],
        "total_fee_cents": b.get("total_fee_cents"),
        "submission_attempts": b.get("submission_attempts", 0),
        "created_at": b["created_at"],
        "updated_at": b["updated_at"],
        "version": b["version"],
    }


@bp.route("/batches", methods=["POST"])
@require_auth(roles={"Customer"})
def create_batch():
    body = get_body()
    customer_id = require_str(body, "customer_id")
    chain_id = require_enum(body, "chain_id", VALID_CHAINS)
    evidence_ids = body.get("evidence_ids")

    if not isinstance(evidence_ids, list) or not all(isinstance(x, str) for x in evidence_ids):
        raise err("ERR_VALIDATION_FAILED", "evidence_ids must be a list of strings")

    # Priority 3: ownership
    if g.user_id != customer_id:
        raise err("ERR_PERMISSION_DENIED",
                  "X-User-ID does not match body customer_id")

    # Priority 5: customer existence
    get_customer(customer_id, body_ref=True)

    # Priority 10: size out of range (this beats member validity because
    # if the count is wrong, member checks are unreliable)
    count = len(evidence_ids)
    if count < 2 or count > 1000:
        raise err("ERR_BATCH_SIZE_OUT_OF_RANGE",
                  f"Batch evidence_count must be in [2, 1000]; got {count}")

    # Priority 9: member validity
    # First: all referenced evidences must exist (we keep this distinct from
    # PRD §1.6 ERR_BATCH_MEMBER_INVALID which is the cross-customer / state check)
    members = []
    for eid in evidence_ids:
        ev = db.evidences.get(eid)
        if ev is None:
            raise err("ERR_BATCH_MEMBER_INVALID",
                      f"Batch member {eid} does not exist")
        members.append(ev)

    for m in members:
        if m["customer_id"] != customer_id:
            raise err("ERR_BATCH_MEMBER_INVALID",
                      f"Batch member {m['id']} belongs to another customer")
        if m["status"] != "PENDING":
            raise err("ERR_BATCH_MEMBER_INVALID",
                      f"Batch member {m['id']} is not PENDING")
        if m.get("batch_id") is not None:
            raise err("ERR_BATCH_MEMBER_INVALID",
                      f"Batch member {m['id']} already belongs to a batch")

    # Compute initial Merkle root
    root = merkle_root([m["file_hash"] for m in members])

    batch = {
        "customer_id": customer_id,
        "chain_id": chain_id,
        "evidence_count": count,
        "merkle_root": root,
        "status": "PENDING",
        "total_fee_cents": None,
        "submission_attempts": 0,
    }
    db.stamp_create(batch, common_fields=True)
    db.batches[batch["id"]] = batch

    # Assign batch_id on each member in submission order — preserve ordering
    # via the order they were referenced in the request.
    for m in members:
        m["batch_id"] = batch["id"]
        db.stamp_update(m)

    return success(_public(batch), 201)


@bp.route("/batches/<b_id>", methods=["GET"])
@require_auth(roles={"Customer", "PlatformAdmin"})
def read_batch(b_id):
    b = get_batch(b_id)
    if g.user_role == "Customer" and g.user_id != b["customer_id"]:
        raise err("ERR_PERMISSION_DENIED", "Customer may only read its own batches")
    return success(_public(b), 200)


@bp.route("/batches/<b_id>/submit", methods=["POST"])
@require_auth(roles={"Customer"})
def submit_batch(b_id):
    body = get_body()
    b = get_batch(b_id)
    if g.user_id != b["customer_id"]:
        raise err("ERR_PERMISSION_DENIED",
                  "Customer X-User-ID does not match batch customer_id")
    maybe_check_version(body, b)
    lifecycle.batch_submit(b)
    return success(_public(b), 200)


@bp.route("/batches/<b_id>/proof/<evidence_id>", methods=["GET"])
@require_auth(roles={"Customer", "JudicialOfficer", "PlatformAdmin"})
def proof(b_id, evidence_id):
    b = get_batch(b_id)
    ev = get_evidence(evidence_id)
    if ev.get("batch_id") != b["id"]:
        raise err("ERR_NOT_FOUND",
                  "Evidence is not a member of the specified batch")
    if g.user_role == "Customer" and g.user_id != b["customer_id"]:
        raise err("ERR_PERMISSION_DENIED", "Cannot read proof for this batch")

    from services.lookup import batch_members
    members = batch_members(b["id"])
    leaves = [m["file_hash"] for m in members]
    try:
        idx = next(i for i, m in enumerate(members) if m["id"] == ev["id"])
    except StopIteration:
        raise err("ERR_NOT_FOUND", "Evidence not in batch")
    path = merkle_proof(leaves, idx)
    payload = {
        "batch_id": b["id"],
        "evidence_id": ev["id"],
        "leaf_hash": ev["file_hash"],
        "leaf_index": idx,
        "merkle_root": b["merkle_root"],
        "proof": path,
    }
    return success(payload, 200)
