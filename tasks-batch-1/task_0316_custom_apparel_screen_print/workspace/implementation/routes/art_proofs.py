"""ArtProof endpoints — the cyclic revision loop with OCC on approve
(PRD §3.3, §2.9; SCAFFOLD §1.2 ArtProof state machine)."""
from flask import Blueprint, request

from db import store, new_common_fields, touch
from errors import err
from middleware import endpoint, require_owns_customer
from response import success, list_response
from serialize import view, view_list
from validation import get_body, require_str, parse_pagination, paginate
from services.lookups import get_order, get_proof_under_order, proofs_of_order

bp = Blueprint("art_proofs", __name__)


@bp.route("/orders/<order_id>/art-proofs", methods=["POST"])
@endpoint("ShopManager", "ArtStaff")
def create_proof(order_id):
    get_order(order_id)
    body = get_body()
    title = require_str(body, "title")
    art_hash = require_str(body, "art_hash")
    proof = new_common_fields()
    proof.update({
        "order_id": order_id,
        "title": title,
        "art_hash": art_hash,
        "revision_round": 0,
        "status": "DRAFT",
    })
    store.art_proofs[proof["id"]] = proof
    return success(view(proof), status=201)


@bp.route("/orders/<order_id>/art-proofs", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def list_proofs(order_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    limit, offset = parse_pagination()
    status = request.args.get("status")
    items = proofs_of_order(order_id)
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = paginate(items, limit, offset)
    return list_response(view_list(page), limit, offset, total)


@bp.route("/orders/<order_id>/art-proofs/<proof_id>", methods=["GET"])
@endpoint("ShopManager", "ArtStaff", "Customer")
def get_proof(order_id, proof_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    proof = get_proof_under_order(order_id, proof_id)
    return success(view(proof), status=200)


@bp.route("/orders/<order_id>/art-proofs/<proof_id>/submit", methods=["POST"])
@endpoint("ArtStaff")
def submit_proof(order_id, proof_id):
    order = get_order(order_id)
    proof = get_proof_under_order(order_id, proof_id)
    # State (priority 5): only DRAFT or CHANGES_REQUESTED may submit/resubmit.
    if proof["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise err("ERR_INVALID_STATE", "Proof cannot be submitted from its state")
    # Submission requires the parent order still be DRAFT (PRD §3.3).
    if order["fulfillment_status"] != "DRAFT":
        raise err("ERR_ORDER_NOT_DRAFT", "Order is not DRAFT")
    if proof["status"] == "CHANGES_REQUESTED":
        proof["revision_round"] += 1
    proof["status"] = "SUBMITTED"
    touch(proof)
    return success(view(proof), status=200)


@bp.route("/orders/<order_id>/art-proofs/<proof_id>/request-changes", methods=["POST"])
@endpoint("Customer")
def request_changes(order_id, proof_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    proof = get_proof_under_order(order_id, proof_id)
    if proof["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Proof is not SUBMITTED")
    proof["status"] = "CHANGES_REQUESTED"
    touch(proof)
    return success(view(proof), status=200)


@bp.route("/orders/<order_id>/art-proofs/<proof_id>/approve", methods=["POST"])
@endpoint("Customer")
def approve_proof(order_id, proof_id):
    order = get_order(order_id)
    require_owns_customer(order["customer_id"])
    proof = get_proof_under_order(order_id, proof_id)
    body = get_body()
    expected = body.get("expected_order_version")
    if expected is None:
        raise err("ERR_INVALID_REQUEST", "expected_order_version is required")
    # State (priority 5) before OCC: only SUBMITTED proofs may be approved.
    if proof["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Proof is not SUBMITTED")
    # OCC (priority 17): expected_order_version must equal the live version.
    try:
        expected_int = int(expected)
    except (TypeError, ValueError):
        raise err("ERR_INVALID_REQUEST", "expected_order_version must be an integer")
    if expected_int != order["version"]:
        raise err("ERR_STALE_ORDER_VERSION", "Order version is stale")

    proof["status"] = "APPROVED"
    touch(proof)
    # Side effect: bump the parent Order's version (PRD §3.3, §2.9).
    touch(order)
    return success(view(proof), status=200)
