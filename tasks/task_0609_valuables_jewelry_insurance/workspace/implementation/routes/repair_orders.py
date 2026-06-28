"""RepairOrder routes: assign/get/list, accept, complete, deem_total_loss."""
from flask import Blueprint, request

import calc
import db
import lookups
import response
import serializers
import validators as V
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_repair_order_access

bp = Blueprint("repair_orders", __name__)


def _load_chain(pid, cid):
    policy = lookups.get_policy(pid)
    claim = lookups.get_claim(cid)
    if claim["policy_id"] != policy["id"]:
        raise err("ERR_NOT_FOUND", "Claim does not belong to this policy")
    return policy, claim


def _item_of(claim):
    return db.scheduled_items.get(claim["scheduled_item_id"])


# =============================== Assign =================================
@bp.route("/policies/<pid>/claims/<cid>/repair-order", methods=["POST"])
def assign_repair_order(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)

    body = V.get_json(request)
    repair_shop_id = V.require_str(body, "repair_shop_id")
    shop = lookups.get_repair_shop(repair_shop_id)

    # Claim must be an APPROVED PARTIAL_DAMAGE claim.
    if claim["status"] != "APPROVED" or claim["loss_type"] != "PARTIAL_DAMAGE":
        raise err("ERR_INVALID_STATE", "Claim is not an APPROVED PARTIAL_DAMAGE claim")

    if shop["status"] != "ACTIVE":
        raise err("ERR_SHOP_SUSPENDED", "Repair shop is suspended")

    # In-network shop halves the deductible for PARTIAL_DAMAGE — recompute the
    # claim settlement now that the servicing shop is known (PRD §3.12/§3.14).
    item = _item_of(claim)
    settlement, deductible_applied = calc.compute_settlement(
        claim, item, policy, repair_in_network=shop.get("in_network", False))
    claim["settlement_cents"] = settlement
    claim["deductible_applied_cents"] = deductible_applied
    db.touch(claim)

    rec = {
        "id": db.new_id(),
        "claim_id": claim["id"],
        "repair_shop_id": repair_shop_id,
        "authorized_amount_cents": claim["settlement_cents"],
        "actual_cost_cents": None,
        "status": "ASSIGNED",
    }
    db.stamp_create(rec)
    db.repair_orders[rec["id"]] = rec
    return response.success(serializers.repair_order(rec), status=201)


@bp.route("/repair-orders/<rid>", methods=["GET"])
def get_repair_order(rid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder", "RepairShop"})
    rec = lookups.get_repair_order(rid)
    assert_repair_order_access(rec, user_id, role)
    return response.success(serializers.repair_order(rec), status=200)


@bp.route("/repair-orders", methods=["GET"])
def list_repair_orders():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder", "RepairShop"})
    claim_id = request.args.get("claim_id")
    repair_shop_id = request.args.get("repair_shop_id")
    records = list(db.repair_orders.values())
    if claim_id is not None:
        records = [r for r in records if r["claim_id"] == claim_id]
    if repair_shop_id is not None:
        records = [r for r in records if r["repair_shop_id"] == repair_shop_id]
    if role == "RepairShop":
        records = [r for r in records if r["repair_shop_id"] == user_id]
    elif role == "Policyholder":
        owned_policies = {p["id"] for p in db.policies.values() if p["policyholder_id"] == user_id}
        owned_claims = {c["id"] for c in db.claims.values() if c["policy_id"] in owned_policies}
        records = [r for r in records if r["claim_id"] in owned_claims]
    return paginate_and_respond(records, serializers.repair_order)


def _load_order(pid, cid):
    policy, claim = _load_chain(pid, cid)
    ro = lookups.repair_order_for_claim(claim["id"])
    if ro is None:
        raise err("ERR_NOT_FOUND", "No repair order for this claim")
    return policy, claim, ro


@bp.route("/policies/<pid>/claims/<cid>/repair-order/accept", methods=["POST"])
def accept_repair_order(pid, cid):
    user_id, role = get_identity()
    require_role(role, {"RepairShop"})
    policy, claim, ro = _load_order(pid, cid)
    assert_repair_order_access(ro, user_id, role)
    if ro["status"] != "ASSIGNED":
        raise err("ERR_INVALID_STATE", "RepairOrder is not ASSIGNED")
    shop = db.repair_shops.get(ro["repair_shop_id"])
    if shop is None or shop["status"] != "ACTIVE":
        raise err("ERR_SHOP_SUSPENDED", "Repair shop is suspended")
    ro["status"] = "IN_PROGRESS"
    db.touch(ro)
    return response.success(serializers.repair_order(ro), status=200)


@bp.route("/policies/<pid>/claims/<cid>/repair-order/complete", methods=["POST"])
def complete_repair_order(pid, cid):
    user_id, role = get_identity()
    require_role(role, {"RepairShop"})
    policy, claim, ro = _load_order(pid, cid)
    assert_repair_order_access(ro, user_id, role)

    body = V.get_json(request)
    actual_cost = V.require_positive_int(body, "actual_cost_cents")

    if ro["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "RepairOrder is not IN_PROGRESS")
    if actual_cost > ro["authorized_amount_cents"]:
        raise err("ERR_REPAIR_EXCEEDS_AUTH", "Repair cost exceeds authorized amount")

    ro["actual_cost_cents"] = actual_cost
    ro["status"] = "REPAIRED"
    db.touch(ro)
    # REPAIRED -> CLOSED (automatic); cascade up.
    ro["status"] = "CLOSED"
    db.touch(ro)
    if claim["status"] == "APPROVED":
        claim["status"] = "SETTLED"
        db.touch(claim)
    item = _item_of(claim)
    if item is not None and item["item_status"] == "SUSPENDED":
        item["item_status"] = "ACTIVE"
        db.touch(item)
    return response.success(serializers.repair_order(ro), status=200)


@bp.route("/policies/<pid>/claims/<cid>/repair-order/deem_total_loss", methods=["POST"])
def deem_total_loss(pid, cid):
    user_id, role = get_identity()
    require_role(role, {"RepairShop", "ClaimsAdjuster"})
    policy, claim, ro = _load_order(pid, cid)
    if role == "RepairShop":
        assert_repair_order_access(ro, user_id, role)
    if ro["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "RepairOrder is not IN_PROGRESS")

    ro["status"] = "DEEMED_TOTAL_LOSS"
    db.touch(ro)
    # Reclassify the claim to TOTAL_LOSS and recompute settlement at full value.
    claim["loss_type"] = "TOTAL_LOSS"
    item = _item_of(claim)
    settlement, deductible_applied = calc.compute_settlement(
        claim, item, policy, repair_in_network=False)
    claim["settlement_cents"] = settlement
    claim["deductible_applied_cents"] = deductible_applied
    if claim["status"] == "APPROVED":
        claim["status"] = "SETTLED"
    db.touch(claim)
    # DEEMED_TOTAL_LOSS -> CLOSED (automatic).
    ro["status"] = "CLOSED"
    db.touch(ro)
    # Remove the item and recompute policy aggregates.
    if item is not None and item["item_status"] != "REMOVED":
        item["item_status"] = "REMOVED"
        db.touch(item)
    calc.recompute_policy_aggregates(policy)
    db.touch(policy)
    return response.success(serializers.repair_order(ro), status=200)
