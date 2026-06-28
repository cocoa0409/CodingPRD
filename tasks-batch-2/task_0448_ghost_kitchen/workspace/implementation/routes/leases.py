"""KitchenLease endpoints (PRD §3.3)."""
from flask import Blueprint, request

import errors
from db import store
from middleware import get_identity, require_role
from response import object_response, array_response
from services.common import new_entity, touch, serialize, paginate, get_or_404
from validation import get_body, require_str, require_int

bp = Blueprint("leases", __name__)


def _check_stall_owner_for_lease(role, user_id, lease):
    """StallOperator must own the stall referenced by the lease."""
    if role == "StallOperator" and user_id != lease["stall_id"]:
        raise errors.forbidden()


def _rank_collision(stall_id, priority_rank, exclude_lease_id):
    """True iff another ACTIVE lease at the stall already holds this rank."""
    for l in store.leases.values():
        if l["id"] == exclude_lease_id:
            continue
        if (l["stall_id"] == stall_id and l["status"] == "ACTIVE"
                and l["priority_rank"] == priority_rank):
            return True
    return False


@bp.route("/leases", methods=["POST"])
def create_lease():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    body = get_body()
    stall_id = require_str(body, "stall_id")
    brand_id = require_str(body, "brand_id")
    monthly_fee = require_int(body, "monthly_fee_cents")
    priority_rank = require_int(body, "priority_rank")
    with store.lock:
        # Existence (priority 3) of body FKs before field-shape (priority 12).
        get_or_404(store.stalls, stall_id)
        get_or_404(store.brands, brand_id)
        if monthly_fee <= 0:
            raise errors.invalid_request("monthly_fee_cents must be > 0.")
        if priority_rank < 1:
            raise errors.invalid_request("priority_rank must be >= 1.")
        rec = new_entity("KitchenLease", {
            "stall_id": stall_id,
            "brand_id": brand_id,
            "monthly_fee_cents": monthly_fee,
            "priority_rank": priority_rank,
            "status": "PENDING",
        })
        store.leases[rec["id"]] = rec
        return object_response(serialize(rec), 201)


@bp.route("/leases/<lid>", methods=["GET"])
def get_lease(lid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator", "BrandOwner"])
    with store.lock:
        rec = get_or_404(store.leases, lid)
        return object_response(serialize(rec))


@bp.route("/leases", methods=["GET"])
def list_leases():
    user_id, role = get_identity()
    require_role(role, ["PlatformOps", "StallOperator", "BrandOwner"])
    with store.lock:
        recs = list(store.leases.values())
        stall_id = request.args.get("stall_id")
        brand_id = request.args.get("brand_id")
        if stall_id is not None:
            recs = [l for l in recs if l["stall_id"] == stall_id]
        if brand_id is not None:
            recs = [l for l in recs if l["brand_id"] == brand_id]
        items, limit, offset, total = paginate(recs)
        return array_response(items, limit, offset, total)


@bp.route("/leases/<lid>/activate", methods=["POST"])
def activate_lease(lid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.leases, lid)
        _check_stall_owner_for_lease(role, user_id, rec)
        if rec["status"] != "PENDING":
            raise errors.invalid_state()
        # Referenced stall must exist (priority 3 surfaced as a transition guard).
        get_or_404(store.stalls, rec["stall_id"])
        if _rank_collision(rec["stall_id"], rec["priority_rank"], rec["id"]):
            raise errors.duplicate_priority_rank()
        rec["status"] = "ACTIVE"
        touch(rec)
        # Cascade hop 2: brand ONBOARDING -> ACTIVE.
        brand = store.brands.get(rec["brand_id"])
        if brand is not None and brand["status"] == "ONBOARDING":
            brand["status"] = "ACTIVE"
            touch(brand)
        return object_response(serialize(rec))


@bp.route("/leases/<lid>/suspend", methods=["POST"])
def suspend_lease(lid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    with store.lock:
        rec = get_or_404(store.leases, lid)
        if rec["status"] != "ACTIVE":
            raise errors.invalid_state()
        rec["status"] = "SUSPENDED"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/leases/<lid>/reinstate", methods=["POST"])
def reinstate_lease(lid):
    user_id, role = get_identity()
    require_role(role, ["PlatformOps"])
    with store.lock:
        rec = get_or_404(store.leases, lid)
        if rec["status"] != "SUSPENDED":
            raise errors.invalid_state()
        if _rank_collision(rec["stall_id"], rec["priority_rank"], rec["id"]):
            raise errors.duplicate_priority_rank()
        rec["status"] = "ACTIVE"
        touch(rec)
        return object_response(serialize(rec))


@bp.route("/leases/<lid>/terminate", methods=["POST"])
def terminate_lease(lid):
    user_id, role = get_identity()
    require_role(role, ["StallOperator"])
    with store.lock:
        rec = get_or_404(store.leases, lid)
        _check_stall_owner_for_lease(role, user_id, rec)
        if rec["status"] not in ("ACTIVE", "SUSPENDED"):
            raise errors.invalid_state()
        rec["status"] = "TERMINATED"
        touch(rec)
        return object_response(serialize(rec))
