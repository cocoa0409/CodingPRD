"""Proof endpoints."""

from flask import Blueprint, request

import db
import errors
import middleware
import models
import response as resp
import services
import util

bp = Blueprint("proofs", __name__)


def _order_for_proof(proof: dict):
    """Return the order that has proof_id == proof.id, or None."""
    for o in db.orders.values():
        if o.get("proof_id") == proof["id"]:
            return o
    return None


@bp.route("/designs/<did>/proofs", methods=["POST"])
def create_initial_proof(did):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Designer"])
    body = util.get_body()
    designer_id = util.get_str(body, "designer_id")

    # Existence: design + designer
    d = models.get_design(did)
    dsn = models.get_designer(designer_id)
    # AuthZ: designer_id must equal acting user id
    middleware.require_owner(user_id, designer_id)

    # State: design must be in PROOFING (i.e., its Order was confirmed)
    if d["status"] != "PROOFING":
        errors.raise_error(errors.ERR_INVALID_STATE, "design must be in PROOFING")

    # Find the order that references this design (should be exactly one after confirm)
    # It's the confirmed order (status past CART), and Order.proof_id was set at confirm.
    parent_order = None
    for o in db.orders.values():
        if o["design_id"] == d["id"] and o["status"] not in ("CART", "CANCELLED"):
            parent_order = o
            break
    if parent_order is None:
        errors.raise_error(errors.ERR_INVALID_STATE, "no active order for this design")
    # Find the existing DRAFT proof created at confirm
    proof = None
    if parent_order.get("proof_id"):
        proof = db.proofs.get(parent_order["proof_id"])
    if proof is None:
        errors.raise_error(errors.ERR_INVALID_STATE, "no proof exists for this design")
    # If proof already has a designer bound (i.e., initial proof was already created), reject
    if proof.get("designer_id") is not None:
        errors.raise_error(errors.ERR_INVALID_STATE, "proof already has designer bound")

    # Bind designer to proof and design
    proof["designer_id"] = designer_id
    models.bump(proof)
    d["designer_id"] = designer_id
    models.bump(d)

    return resp.created(proof)


@bp.route("/proofs/<pid>/submit", methods=["POST"])
def submit_proof(pid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Designer"])
    proof = models.get_proof(pid)
    # Check for expiry (system observation)
    services.check_proof_expiry_on_read(proof)

    # AuthZ: designer_id must be set and equal to acting user
    if proof.get("designer_id") is None:
        errors.raise_error(errors.ERR_INVALID_STATE, "proof has no designer bound; create initial proof first")
    middleware.require_owner(user_id, proof["designer_id"])

    # State
    if proof["status"] in ("APPROVED", "EXPIRED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "proof is terminal")
    if proof["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        errors.raise_error(errors.ERR_INVALID_STATE, "proof cannot be submitted from current state")

    # Design must be PROOFING
    d = db.designs.get(proof["design_id"])
    if not d or d["status"] != "PROOFING":
        errors.raise_error(errors.ERR_INVALID_STATE, "design is not in PROOFING")

    order = _order_for_proof(proof)
    if order is None:
        errors.raise_error(errors.ERR_INVALID_STATE, "no order for this proof")

    # Advance
    proof["current_revision_number"] = int(proof.get("current_revision_number", 0)) + 1
    proof["status"] = "SUBMITTED"
    proof["submitted_at"] = db.iso_now()
    proof["expires_at"] = services.compute_proof_expires_at(proof, order)
    if proof["current_revision_number"] > services.REVISION_FREE_LIMIT:
        proof["revision_fee_cents"] = int(proof.get("revision_fee_cents", 0)) + services.REVISION_FEE_CENTS
    models.bump(proof)
    # Recompute order lead days + total
    services.recompute_expected_lead_days(order)
    services.recompute_order_total(order)
    models.bump(order)
    return resp.ok(proof)


@bp.route("/proofs/<pid>/request-changes", methods=["POST"])
def request_changes(pid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    proof = models.get_proof(pid)
    services.check_proof_expiry_on_read(proof)

    # AuthZ: acting customer must own the parent design
    d = db.designs.get(proof["design_id"])
    if not d:
        errors.raise_error(errors.ERR_DESIGN_NOT_FOUND, "parent design not found")
    middleware.require_owner(user_id, d["customer_id"])

    # State
    if proof["status"] in ("APPROVED", "EXPIRED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "proof is terminal")
    if proof["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE, "proof must be SUBMITTED")

    # Check expiry - customer-side actions require not expired
    if proof.get("expires_at"):
        try:
            exp = db.parse_iso(proof["expires_at"])
            if db.get_now() > exp:
                errors.raise_error(errors.ERR_PROOF_EXPIRED, "proof has expired")
        except errors.ApiError:
            raise
        except Exception:
            pass

    proof["status"] = "CHANGES_REQUESTED"
    proof["submitted_at"] = None
    models.bump(proof)
    return resp.ok(proof)


@bp.route("/proofs/<pid>/approve", methods=["POST"])
def approve_proof(pid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["Customer"])
    proof = models.get_proof(pid)
    services.check_proof_expiry_on_read(proof)

    d = db.designs.get(proof["design_id"])
    if not d:
        errors.raise_error(errors.ERR_DESIGN_NOT_FOUND, "parent design not found")
    middleware.require_owner(user_id, d["customer_id"])

    if proof["status"] in ("APPROVED", "EXPIRED", "CANCELLED"):
        errors.raise_error(errors.ERR_ALREADY_TERMINAL, "proof is terminal")
    if proof["status"] != "SUBMITTED":
        errors.raise_error(errors.ERR_INVALID_STATE, "proof must be SUBMITTED to approve")

    if proof.get("expires_at"):
        try:
            exp = db.parse_iso(proof["expires_at"])
            if db.get_now() > exp:
                errors.raise_error(errors.ERR_PROOF_EXPIRED, "proof has expired")
        except errors.ApiError:
            raise
        except Exception:
            pass

    proof["status"] = "APPROVED"
    proof["approved_at"] = db.iso_now()
    models.bump(proof)
    d["status"] = "APPROVED"
    models.bump(d)
    # Cascade if order.deposit_paid_at is set
    order = _order_for_proof(proof)
    if order and order.get("deposit_paid_at"):
        services.try_cascade_deposit_and_approval(order)
    return resp.ok(proof)


@bp.route("/proofs/<pid>", methods=["GET"])
def get_proof(pid):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    proof = models.get_proof(pid)
    services.check_proof_expiry_on_read(proof)
    d = db.designs.get(proof["design_id"])
    if role == "Customer":
        if not d or d["customer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not the customer of this proof")
    if role == "Designer":
        if proof.get("designer_id") is not None and proof["designer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not the designer of this proof")
    return resp.ok(proof)


@bp.route("/designs/<did>/proofs", methods=["GET"])
def list_design_proofs(did):
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    d = models.get_design(did)
    if role == "Customer":
        middleware.require_owner(user_id, d["customer_id"])
    if role == "Designer":
        if d.get("designer_id") is not None and d["designer_id"] != user_id:
            errors.raise_error(errors.ERR_UNAUTHORIZED, "not the designer of this design")
    limit, offset = util.get_pagination()
    items = [p for p in db.proofs.values() if p["design_id"] == did]
    for p in items:
        services.check_proof_expiry_on_read(p)
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)


@bp.route("/proofs", methods=["GET"])
def list_proofs():
    user_id, role = middleware.get_auth()
    middleware.require_roles(role, ["ShopAdmin", "Customer", "Designer"])
    limit, offset = util.get_pagination()
    designer_id = request.args.get("designer_id")
    design_id = request.args.get("design_id")
    status = request.args.get("status")

    def match(p):
        if designer_id and p.get("designer_id") != designer_id:
            return False
        if design_id and p.get("design_id") != design_id:
            return False
        if status and p.get("status") != status:
            return False
        return True

    items = [p for p in db.proofs.values() if match(p)]
    for p in items:
        services.check_proof_expiry_on_read(p)
    # Re-filter after expiry check if status filter present
    if status:
        items = [p for p in items if p["status"] == status]
    if role == "Customer":
        items = [
            p for p in items
            if (d := db.designs.get(p["design_id"])) and d["customer_id"] == user_id
        ]
    elif role == "Designer":
        items = [p for p in items if p.get("designer_id") in (None, user_id)]
    items = util.sort_by_created_at(items)
    page, total = util.apply_pagination(items, limit, offset)
    return resp.list_ok(page, limit, offset, total)
