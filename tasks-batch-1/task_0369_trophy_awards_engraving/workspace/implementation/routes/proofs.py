from flask import Blueprint
from db import db
from errors import err
from response import ok, ok_list
from middleware import authenticate, require_role
from services import serialize
from services.common import (
    get_json_body, stamp_create, touch, paginate, page_slice,
    require_fields, is_str,
)
from db import now_iso
from services.orders import (
    get_line_or_404, get_proof_or_404, enforce_order_ownership, proofs_for_line,
)

bp = Blueprint("proofs", __name__)


def _line_and_order(line_id):
    line = get_line_or_404(line_id)
    order = db.orders.get(line["order_id"])
    return line, order


def _proof_on_line(line_id, proof_id):
    """Validate line then proof, and that the proof belongs to the line."""
    line = get_line_or_404(line_id)
    proof = get_proof_or_404(proof_id)
    if proof["order_line_id"] != line_id:
        raise err("ERR_NOT_FOUND", "Proof not found on this line")
    return line, proof


@bp.route("/order-lines/<line_id>/proofs", methods=["POST"])
def create_proof(line_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    line, order = _line_and_order(line_id)
    body = get_json_body()
    require_fields(body, ["proof_kind", "content_ref"])
    kind = body["proof_kind"]
    content_ref = body["content_ref"]
    if kind not in ("TEXT", "LOGO"):
        raise err("ERR_INVALID_REQUEST", "proof_kind must be TEXT or LOGO")
    if not is_str(content_ref):
        raise err("ERR_INVALID_REQUEST", "content_ref must be a string")

    proof = {
        "order_line_id": line_id,
        "proof_kind": kind,
        "content_ref": content_ref,
        "proof_status": "DRAFT",
        "revision_round": 1,
        "approved_text_snapshot": None,
        "sent_at": None,
    }
    stamp_create(proof)
    db.proofs[proof["id"]] = proof
    return ok(serialize.proof(proof), 201)


@bp.route("/order-lines/<line_id>/proofs", methods=["GET"])
def list_proofs(line_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    line, order = _line_and_order(line_id)
    if order is not None:
        enforce_order_ownership(caller, order)
    items = proofs_for_line(line_id)
    limit, offset = paginate()
    page, total = page_slice(items, limit, offset)
    return ok_list([serialize.proof(p) for p in page], limit, offset, total)


@bp.route("/proofs/<proof_id>", methods=["GET"])
def get_proof(proof_id):
    caller = authenticate()
    require_role(caller, ("Customer", "ShopStaff", "ShopManager"))
    proof = get_proof_or_404(proof_id)
    line = db.order_lines.get(proof["order_line_id"])
    if line is not None:
        order = db.orders.get(line["order_id"])
        if order is not None:
            enforce_order_ownership(caller, order)
    return ok(serialize.proof(proof))


@bp.route("/order-lines/<line_id>/proofs/<proof_id>/send", methods=["POST"])
def send_proof(line_id, proof_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    line, proof = _proof_on_line(line_id, proof_id)
    order = db.orders.get(line["order_id"])
    if proof["proof_status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Proof must be DRAFT to send")
    if order["production_status"] not in ("DRAFT", "PRICED", "IN_PRODUCTION"):
        raise err("ERR_INVALID_STATE", "Proof cannot be sent in the order's current state")
    proof["sent_at"] = now_iso()
    proof["proof_status"] = "SENT"
    touch(proof)
    return ok(serialize.proof(proof))


@bp.route("/order-lines/<line_id>/proofs/<proof_id>/approve", methods=["POST"])
def approve_proof(line_id, proof_id):
    caller = authenticate()
    require_role(caller, ("Customer",))
    line, proof = _proof_on_line(line_id, proof_id)
    order = db.orders.get(line["order_id"])
    if order is not None:
        enforce_order_ownership(caller, order)
    if proof["proof_status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Proof must be SENT to approve")
    proof["approved_text_snapshot"] = proof["content_ref"]
    proof["proof_status"] = "APPROVED"
    touch(proof)
    return ok(serialize.proof(proof))


@bp.route("/order-lines/<line_id>/proofs/<proof_id>/request-changes", methods=["POST"])
def request_changes(line_id, proof_id):
    caller = authenticate()
    require_role(caller, ("Customer",))
    line, proof = _proof_on_line(line_id, proof_id)
    order = db.orders.get(line["order_id"])
    if order is not None:
        enforce_order_ownership(caller, order)
    if proof["proof_status"] != "SENT":
        raise err("ERR_INVALID_STATE", "Proof must be SENT to request changes")
    proof["proof_status"] = "CHANGES_REQUESTED"
    touch(proof)

    # Cascade: if owning line is ALLOCATED or ENGRAVING, revert to PENDING
    if line["line_status"] in ("ALLOCATED", "ENGRAVING"):
        line["line_status"] = "PENDING"
        line["assembled_count"] = 0
        touch(line)
        # reserved allocations are kept RESERVED

    return ok(serialize.proof(proof))


@bp.route("/order-lines/<line_id>/proofs/<proof_id>/revise", methods=["POST"])
def revise_proof(line_id, proof_id):
    caller = authenticate()
    require_role(caller, ("ShopStaff",))
    line, proof = _proof_on_line(line_id, proof_id)
    body = get_json_body()
    if proof["proof_status"] != "CHANGES_REQUESTED":
        raise err("ERR_INVALID_STATE", "Proof must be CHANGES_REQUESTED to revise")
    if "content_ref" in body:
        if not is_str(body["content_ref"]):
            raise err("ERR_INVALID_REQUEST", "content_ref must be a string")
        proof["content_ref"] = body["content_ref"]
    proof["revision_round"] += 1
    proof["sent_at"] = None
    proof["approved_text_snapshot"] = None
    proof["proof_status"] = "DRAFT"
    touch(proof)
    return ok(serialize.proof(proof))
