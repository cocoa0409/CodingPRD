"""Endorsement routes: draft/get/list, apply (OCC-guarded), reject."""
from flask import Blueprint, request

import calc
import clock
import db
import lookups
import response
import serializers
import validators as V
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_policy_access

bp = Blueprint("endorsements", __name__)

ENDORSEMENT_TYPES = {"ADD_ITEM", "REMOVE_ITEM", "CHANGE_DEDUCTIBLE"}
DEDUCTIBLE_OPTIONS = {"ZERO", "LOW", "STANDARD", "HIGH"}


@bp.route("/policies/<pid>/endorsements", methods=["POST"])
def draft_endorsement(pid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)
    body = V.get_json(request)
    etype = V.require_enum(body, "endorsement_type", ENDORSEMENT_TYPES)
    target_item_id = body.get("target_item_id")
    new_deductible = body.get("new_deductible_option")
    if new_deductible is not None and new_deductible not in DEDUCTIBLE_OPTIONS:
        raise err("ERR_INVALID_REQUEST", "new_deductible_option out of range")
    if target_item_id is not None and (not isinstance(target_item_id, str) or target_item_id == ""):
        raise err("ERR_INVALID_REQUEST", "target_item_id must be a string")

    rec = {
        "id": db.new_id(),
        "policy_id": policy["id"],
        "endorsement_type": etype,
        "target_item_id": target_item_id,
        "new_deductible_option": new_deductible,
        "premium_delta_cents": 0,
        "status": "DRAFT",
    }
    db.stamp_create(rec)
    db.endorsements[rec["id"]] = rec
    return response.success(serializers.endorsement(rec), status=201)


@bp.route("/endorsements/<eid>", methods=["GET"])
def get_endorsement(eid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_endorsement(eid)
    policy = db.policies.get(rec["policy_id"])
    if policy is not None:
        assert_policy_access(policy, user_id, role)
    return response.success(serializers.endorsement(rec), status=200)


@bp.route("/endorsements", methods=["GET"])
def list_endorsements():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    policy_id = request.args.get("policy_id")
    target_item_id = request.args.get("target_item_id")
    records = list(db.endorsements.values())
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if target_item_id is not None:
        records = [r for r in records if r.get("target_item_id") == target_item_id]
    if role == "Policyholder":
        owned = {p["id"] for p in db.policies.values() if p["policyholder_id"] == user_id}
        records = [r for r in records if r["policy_id"] in owned]
    return paginate_and_respond(records, serializers.endorsement)


@bp.route("/policies/<pid>/endorsements/<eid>/apply", methods=["POST"])
def apply_endorsement(pid, eid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)
    endorsement = lookups.get_endorsement(eid)
    if endorsement["policy_id"] != policy["id"]:
        raise err("ERR_NOT_FOUND", "Endorsement does not belong to this policy")

    body = V.get_json(request)
    expected_version = V.require(body, "expected_policy_version")

    # State legality (priority 5): endorsement must be DRAFT.
    if endorsement["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Endorsement is not DRAFT")
    # Parent policy must be BOUND or ACTIVE.
    if policy["coverage_status"] not in ("BOUND", "ACTIVE"):
        raise err("ERR_INVALID_STATE", "Policy is not BOUND or ACTIVE")

    # OCC (priority 21).
    lookups.check_version(expected_version, policy["version"])

    etype = endorsement["endorsement_type"]
    target = None
    if etype in ("ADD_ITEM", "REMOVE_ITEM"):
        target = lookups.get_scheduled_item(endorsement["target_item_id"])

    if etype == "REMOVE_ITEM":
        if target["item_status"] == "SUSPENDED":
            raise err("ERR_ITEM_LOCKED_BY_CLAIM", "Item is locked by an open claim")

    if etype == "CHANGE_DEDUCTIBLE":
        new_opt = endorsement["new_deductible_option"]
        if new_opt is None or new_opt == policy["deductible_option"]:
            raise err("ERR_NO_OP_ENDORSEMENT",
                      "new_deductible_option must differ from current")

    # ---- Compute prorated premium delta ----
    bound_at = clock.parse_iso(policy.get("bound_at_iso"))
    now = clock.now()
    proration = calc.proration_fraction(bound_at, now)

    if etype == "ADD_ITEM":
        # Item activates first so it is priced at its current value.
        target["item_status"] = "ACTIVE"
        if target.get("current_value_cents") is None:
            target["current_value_cents"] = target["scheduled_value_cents"]
        target["revaluation_epoch"] = target.get("revaluation_epoch", 0)
        db.touch(target)
        full_premium = calc.item_annual_premium(target, policy)
        delta = calc.round_half_up(calc.Decimal(full_premium) * proration)
    elif etype == "REMOVE_ITEM":
        full_premium = calc.item_annual_premium(target, policy)
        delta = -calc.round_half_up(calc.Decimal(full_premium) * proration)
        target["item_status"] = "REMOVED"
        db.touch(target)
    else:  # CHANGE_DEDUCTIBLE
        old_total, _ = calc.policy_aggregates(policy)
        new_total, _ = calc.policy_aggregates(policy, deductible_option=endorsement["new_deductible_option"])
        delta = calc.round_half_up(calc.Decimal(new_total - old_total) * proration)
        policy["deductible_option"] = endorsement["new_deductible_option"]
        policy["deductible_cents"] = calc.resolve_deductible(policy["deductible_option"])

    # Recompute aggregates against the post-change item set, then apply delta.
    calc.recompute_policy_aggregates(policy)
    policy["annual_premium_cents"] = policy["annual_premium_cents"] + delta

    endorsement["premium_delta_cents"] = delta
    endorsement["status"] = "APPLIED"
    db.touch(endorsement)
    db.touch(policy)
    return response.success(serializers.endorsement(endorsement), status=200)


@bp.route("/policies/<pid>/endorsements/<eid>/reject", methods=["POST"])
def reject_endorsement(pid, eid):
    _, role = get_identity()
    require_role(role, {"Underwriter"})
    policy = lookups.get_policy(pid)
    endorsement = lookups.get_endorsement(eid)
    if endorsement["policy_id"] != policy["id"]:
        raise err("ERR_NOT_FOUND", "Endorsement does not belong to this policy")
    if endorsement["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Endorsement is not DRAFT")
    endorsement["status"] = "REJECTED"
    db.touch(endorsement)
    return response.success(serializers.endorsement(endorsement), status=200)
