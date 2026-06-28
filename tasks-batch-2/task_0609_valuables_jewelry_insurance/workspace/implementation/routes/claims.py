"""Claim routes: file/get/list and the adjudication lifecycle."""
from flask import Blueprint, request

import calc
import db
import lookups
import response
import serializers
import validators as V
from errors import err
from middleware import get_identity, require_role
from routes.common import paginate_and_respond, assert_policy_access

bp = Blueprint("claims", __name__)

PERILS = {"THEFT", "FIRE", "FLOOD", "ACCIDENTAL_DAMAGE", "MYSTERIOUS_DISAPPEARANCE"}
LOSS_TYPES = {"TOTAL_LOSS", "PARTIAL_DAMAGE"}


# =============================== File / read =============================
@bp.route("/policies/<pid>/claims", methods=["POST"])
def file_claim(pid):
    user_id, role = get_identity()
    require_role(role, {"Policyholder", "ClaimsAdjuster"})
    policy = lookups.get_policy(pid)
    assert_policy_access(policy, user_id, role)

    body = V.get_json(request)
    scheduled_item_id = V.require_str(body, "scheduled_item_id")
    peril = V.require_enum(body, "peril", PERILS)
    loss_type = V.require_enum(body, "loss_type", LOSS_TYPES)
    claimed_amount = V.require_positive_int(body, "claimed_amount_cents")
    loss_zip = body.get("loss_zip")
    if loss_zip is not None:
        loss_zip = V.require_zip(body, "loss_zip")
    occurred_outside = V.opt_bool(body, "occurred_outside_country", default=False)

    # Existence of the referenced item (path-adjacent body reference).
    item = lookups.get_scheduled_item(scheduled_item_id)

    # Filing requires the parent policy ACTIVE.
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Policy coverage_status is not ACTIVE")

    rec = {
        "id": db.new_id(),
        "policy_id": policy["id"],
        "scheduled_item_id": scheduled_item_id,
        "peril": peril,
        "loss_type": loss_type,
        "loss_zip": loss_zip,
        "occurred_outside_country": occurred_outside,
        "claimed_amount_cents": claimed_amount,
        "settlement_cents": 0,
        "deductible_applied_cents": 0,
        "info_request_count": 0,
        "status": "FNOL",
    }
    db.stamp_create(rec)
    db.claims[rec["id"]] = rec
    return response.success(serializers.claim(rec), status=201)


@bp.route("/claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    rec = lookups.get_claim(cid)
    policy = db.policies.get(rec["policy_id"])
    if policy is not None:
        assert_policy_access(policy, user_id, role)
    return response.success(serializers.claim(rec), status=200)


@bp.route("/claims", methods=["GET"])
def list_claims():
    user_id, role = get_identity()
    require_role(role, {"Underwriter", "ClaimsAdjuster", "Policyholder"})
    policy_id = request.args.get("policy_id")
    scheduled_item_id = request.args.get("scheduled_item_id")
    records = list(db.claims.values())
    if policy_id is not None:
        records = [r for r in records if r["policy_id"] == policy_id]
    if scheduled_item_id is not None:
        records = [r for r in records if r["scheduled_item_id"] == scheduled_item_id]
    if role == "Policyholder":
        owned = {p["id"] for p in db.policies.values() if p["policyholder_id"] == user_id}
        records = [r for r in records if r["policy_id"] in owned]
    return paginate_and_respond(records, serializers.claim)


# =============================== Helpers =================================
def _load_chain(pid, cid):
    policy = lookups.get_policy(pid)
    claim = lookups.get_claim(cid)
    if claim["policy_id"] != policy["id"]:
        raise err("ERR_NOT_FOUND", "Claim does not belong to this policy")
    return policy, claim


def _item_of(claim):
    return db.scheduled_items.get(claim["scheduled_item_id"])


# =============================== Transitions ============================
@bp.route("/policies/<pid>/claims/<cid>/start_review", methods=["POST"])
def start_review(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)

    if claim["status"] != "FNOL":
        raise err("ERR_INVALID_STATE", "Claim is not in FNOL")

    # Parent policy must be ACTIVE.
    if policy["coverage_status"] != "ACTIVE":
        raise err("ERR_POLICY_NOT_ACTIVE", "Policy coverage_status is not ACTIVE")

    # NAMED_PERIL: claimed peril must be listed (priority 6).
    if policy["coverage_type"] == "NAMED_PERIL" and claim["peril"] not in policy["listed_perils"]:
        raise err("ERR_PERIL_NOT_COVERED", "Peril not covered by this NAMED_PERIL policy")

    # Worldwide (priority 7).
    if claim["occurred_outside_country"] and not policy["worldwide_coverage"]:
        raise err("ERR_WORLDWIDE_NOT_COVERED", "Loss abroad requires worldwide coverage")

    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)
    item = _item_of(claim)
    if item is not None and item["item_status"] == "ACTIVE":
        item["item_status"] = "SUSPENDED"
        db.touch(item)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/request_info", methods=["POST"])
def request_info(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")
    if claim["info_request_count"] >= calc.MAX_INFO_REQUESTS:
        raise err("ERR_INFO_REQUEST_LIMIT", "Info request limit reached")
    claim["status"] = "INFO_REQUESTED"
    claim["info_request_count"] += 1
    db.touch(claim)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/provide_info", methods=["POST"])
def provide_info(pid, cid):
    user_id, role = get_identity()
    require_role(role, {"Policyholder"})
    policy, claim = _load_chain(pid, cid)
    assert_policy_access(policy, user_id, role)
    if claim["status"] != "INFO_REQUESTED":
        raise err("ERR_INVALID_STATE", "Claim is not INFO_REQUESTED")
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/approve", methods=["POST"])
def approve_claim(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)

    body = V.get_json(request)
    expected_version = V.require(body, "expected_claim_version")

    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Claim is not UNDER_REVIEW")

    # OCC guard (priority 21) on the Claim.
    lookups.check_version(expected_version, claim["version"])

    item = _item_of(claim)
    settlement, deductible_applied = calc.compute_settlement(
        claim, item, policy, repair_in_network=False)
    claim["settlement_cents"] = settlement
    claim["deductible_applied_cents"] = deductible_applied
    claim["status"] = "APPROVED"
    db.touch(claim)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/deny", methods=["POST"])
def deny_claim(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)
    if claim["status"] not in ("UNDER_REVIEW", "INFO_REQUESTED"):
        raise err("ERR_INVALID_STATE", "Claim cannot be denied from its current state")
    claim["status"] = "DENIED"
    claim["settlement_cents"] = 0
    db.touch(claim)
    item = _item_of(claim)
    if item is not None and item["item_status"] == "SUSPENDED":
        item["item_status"] = "ACTIVE"
        db.touch(item)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/settle", methods=["POST"])
def settle_claim(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim is not APPROVED")
    if claim["loss_type"] != "TOTAL_LOSS":
        raise err("ERR_PARTIAL_REQUIRES_REPAIR",
                  "PARTIAL_DAMAGE claims settle through repair-order closure")
    claim["status"] = "SETTLED"
    db.touch(claim)
    item = _item_of(claim)
    if item is not None and item["item_status"] != "REMOVED":
        item["item_status"] = "REMOVED"
        db.touch(item)
    calc.recompute_policy_aggregates(policy)
    db.touch(policy)
    return response.success(serializers.claim(claim), status=200)


@bp.route("/policies/<pid>/claims/<cid>/close", methods=["POST"])
def close_claim(pid, cid):
    _, role = get_identity()
    require_role(role, {"ClaimsAdjuster"})
    policy, claim = _load_chain(pid, cid)
    if claim["status"] != "SETTLED":
        raise err("ERR_INVALID_STATE", "Claim is not SETTLED")
    claim["status"] = "CLOSED"
    db.touch(claim)
    return response.success(serializers.claim(claim), status=200)
