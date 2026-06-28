"""Chore and ChoreCompletion endpoints (PRD §3.3)."""
from flask import Blueprint, request

import db
import domain
import serialize
import validate
from errors import err
from middleware import authenticate, require_role, get_json_body
from response import object_response, list_response

bp = Blueprint("chores", __name__)


# ------------------------------- Chore -------------------------------------
@bp.route("/child-accounts/<cid>/chores", methods=["POST"])
def create_chore(cid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    body = get_json_body()
    title = validate.require_str(body, "title")
    reward = validate.require_int(body, "reward_cents")
    payout = validate.optional_enum(body, "payout_jar_type", {"SPEND", "SAVE", "GIVE"}, "SPEND")
    recurring = validate.optional_bool(body, "is_recurring", False)
    validate.bound_positive(reward, "reward_cents")

    rec = db.base_fields()
    rec.update({
        "child_account_id": cid,
        "title": title,
        "reward_cents": reward,
        "payout_jar_type": payout,
        "is_recurring": recurring,
        "status": "AVAILABLE",
    })
    db.chores[rec["id"]] = rec
    return object_response(serialize.chore(rec), status=201)


@bp.route("/child-accounts/<cid>/chores", methods=["GET"])
def list_chores(cid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    child = domain.get_child(cid)
    domain.check_child_owner(identity, child)
    items = [c for c in db.chores.values() if c["child_account_id"] == cid]
    status = request.args.get("status")
    if status is not None:
        items = [c for c in items if c["status"] == status]
    else:
        # Default chore lists exclude soft-archived chores (PRD §3.3).
        items = [c for c in items if c["status"] != "ARCHIVED"]
    return list_response([serialize.chore(c) for c in items], request.args)


@bp.route("/chores/<chid>", methods=["GET"])
def read_chore(chid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    chore = domain.get_chore(chid)
    child = domain.get_child(chore["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.chore(chore))


@bp.route("/chores/<chid>/submit", methods=["POST"])
def submit_chore(chid):
    identity = authenticate()
    require_role(identity, {"Child"})
    chore = domain.get_chore(chid)
    child = domain.get_child(chore["child_account_id"])
    domain.check_child_owner(identity, child)

    if chore["status"] != "AVAILABLE":
        raise err("ERR_INVALID_STATE", "Chore is not AVAILABLE")
    # Cross-entity: child must be ACTIVE.
    if child["status"] == "ARCHIVED":
        raise err("ERR_CHILD_ARCHIVED", "Child account is archived")

    chore["status"] = "SUBMITTED"
    db.touch(chore)

    completion = db.base_fields()
    completion.update({
        "chore_id": chid,
        "child_account_id": chore["child_account_id"],
        "reward_cents_snapshot": chore["reward_cents"],
        "payout_jar_type_snapshot": chore["payout_jar_type"],
        "revision_count": 0,
        "status": "PENDING_REVIEW",
    })
    db.chore_completions[completion["id"]] = completion
    return object_response(serialize.chore_completion(completion), status=201)


@bp.route("/chores/<chid>/reopen", methods=["POST"])
def reopen_chore(chid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    chore = domain.get_chore(chid)
    child = domain.get_child(chore["child_account_id"])
    domain.check_child_owner(identity, child)
    if chore["status"] != "REJECTED":
        raise err("ERR_INVALID_STATE", "Chore is not REJECTED")
    chore["status"] = "AVAILABLE"
    db.touch(chore)
    return object_response(serialize.chore(chore))


@bp.route("/chores/<chid>", methods=["DELETE"])
def delete_chore(chid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    chore = domain.get_chore(chid)
    child = domain.get_child(chore["child_account_id"])
    domain.check_child_owner(identity, child)
    if chore["status"] not in ("AVAILABLE", "REJECTED"):
        raise err("ERR_INVALID_STATE", "Chore can only be archived from AVAILABLE or REJECTED")
    chore["status"] = "ARCHIVED"
    db.touch(chore)
    return object_response(serialize.chore(chore))


# --------------------------- ChoreCompletion -------------------------------
@bp.route("/chores/<chid>/completions", methods=["GET"])
def list_completions(chid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    chore = domain.get_chore(chid)
    child = domain.get_child(chore["child_account_id"])
    domain.check_child_owner(identity, child)
    items = [c for c in db.chore_completions.values() if c["chore_id"] == chid]
    return list_response([serialize.chore_completion(c) for c in items], request.args)


@bp.route("/chore-completions/<coid>", methods=["GET"])
def read_completion(coid):
    identity = authenticate()
    require_role(identity, {"Parent", "Child", "PlatformAdmin"})
    comp = domain.get_completion(coid)
    child = domain.get_child(comp["child_account_id"])
    domain.check_child_owner(identity, child)
    return object_response(serialize.chore_completion(comp))


def _resolve_chore_after_approval(chore):
    """Bubble-up: SUBMITTED -> transient APPROVED -> AVAILABLE (recurring) or
    ARCHIVED (one-shot)."""
    if chore["is_recurring"]:
        chore["status"] = "AVAILABLE"
    else:
        chore["status"] = "ARCHIVED"
    db.touch(chore)


@bp.route("/chore-completions/<coid>/approve", methods=["POST"])
def approve_completion(coid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    comp = domain.get_completion(coid)
    child = domain.get_child(comp["child_account_id"])
    domain.check_child_owner(identity, child)

    # State first (priority 8), then family/child gates (12,13), then funding (22).
    if comp["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", "Completion is not PENDING_REVIEW")
    domain.gate_money_movement(child)

    fam = db.families[child["family_id"]]
    reward = comp["reward_cents_snapshot"]
    if fam["funding_balance_cents"] < reward:
        raise err("ERR_INSUFFICIENT_FUNDING", "Funding wallet cannot cover the reward")

    # CASCADE: debit funding, credit payout jar, recompute card if SPEND.
    fam["funding_balance_cents"] -= reward
    db.touch(fam)
    jar = domain.jar_of_type(child["id"], comp["payout_jar_type_snapshot"])
    domain.credit_jar(jar, reward)

    comp["status"] = "PAID"
    db.touch(comp)

    chore = db.chores.get(comp["chore_id"])
    if chore is not None and chore["status"] == "SUBMITTED":
        _resolve_chore_after_approval(chore)

    return object_response(serialize.chore_completion(comp))


@bp.route("/chore-completions/<coid>/kick-back", methods=["POST"])
def kick_back_completion(coid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    comp = domain.get_completion(coid)
    child = domain.get_child(comp["child_account_id"])
    domain.check_child_owner(identity, child)
    if comp["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", "Completion is not PENDING_REVIEW")
    comp["status"] = "NEEDS_REVISION"
    db.touch(comp)
    return object_response(serialize.chore_completion(comp))


@bp.route("/chore-completions/<coid>/resubmit", methods=["POST"])
def resubmit_completion(coid):
    identity = authenticate()
    require_role(identity, {"Child"})
    comp = domain.get_completion(coid)
    child = domain.get_child(comp["child_account_id"])
    domain.check_child_owner(identity, child)
    if comp["status"] != "NEEDS_REVISION":
        raise err("ERR_INVALID_STATE", "Completion is not NEEDS_REVISION")
    comp["status"] = "PENDING_REVIEW"
    comp["revision_count"] += 1
    db.touch(comp)
    return object_response(serialize.chore_completion(comp))


@bp.route("/chore-completions/<coid>/deny", methods=["POST"])
def deny_completion(coid):
    identity = authenticate()
    require_role(identity, {"Parent"})
    comp = domain.get_completion(coid)
    child = domain.get_child(comp["child_account_id"])
    domain.check_child_owner(identity, child)
    if comp["status"] != "PENDING_REVIEW":
        raise err("ERR_INVALID_STATE", "Completion is not PENDING_REVIEW")
    comp["status"] = "DENIED"
    db.touch(comp)
    chore = db.chores.get(comp["chore_id"])
    if chore is not None and chore["status"] == "SUBMITTED":
        chore["status"] = "REJECTED"
        db.touch(chore)
    return object_response(serialize.chore_completion(comp))
