"""DamageClaim + ClaimItem routes (PRD §3.10).

Filing snapshots coverage/deductible from the accepted estimate and is eligible
only for a DELIVERED job with an accepted estimate. Adjudication is governed
first by segregation of duties (the filer may not adjudicate), then state, then
the DELIVERED requirement and (for approve) the at-least-one-item requirement.
Approve adds the settlement to refunded_cents; reopen reverses it exactly.
"""
from flask import Blueprint, request

import db
from errors import err
from middleware import authenticate, require_roles
from response import object_response, array_response
from serialize import public, public_list
from services import common
from services import calculations

bp = Blueprint("damage_claims", __name__)


def _accepted_estimate(job):
    eid = job.get("accepted_estimate_id")
    if not eid:
        return None
    return db.estimates.get(eid)


@bp.route("/damage-claims", methods=["POST"])
def file_claim():
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster", "Customer"})
    body = common.get_json_body()
    common.require_fields(body, ["move_job_id"])

    job = common.lookup_fk(db.move_jobs, body["move_job_id"])

    # Eligibility (priority 18): job DELIVERED and has an accepted estimate.
    estimate = _accepted_estimate(job)
    if job["job_status"] != "DELIVERED" or estimate is None:
        raise err("ERR_CLAIM_NOT_ELIGIBLE", "Claims may only be filed on a delivered job with an accepted estimate.")

    record = db.new_common({
        "move_job_id": body["move_job_id"],
        "filed_by_user_id": user_id,
        "adjudicated_by_user_id": None,
        "coverage_snapshot": estimate["valuation_coverage"],
        "deductible_cents": estimate["deductible_cents"],
        "settlement_cents": 0,
        "status": "UNDER_REVIEW",
    })
    db.damage_claims[record["id"]] = record
    return object_response(public(record), 201)


@bp.route("/damage-claims/<cid>", methods=["GET"])
def get_claim(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster", "PlatformAdmin", "Customer"})
    record = common.lookup(db.damage_claims, cid)
    return object_response(public(record), 200)


@bp.route("/damage-claims", methods=["GET"])
def list_claims():
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster", "PlatformAdmin", "Customer"})
    limit, offset = common.parse_pagination()
    move_job_id = request.args.get("move_job_id")
    status = request.args.get("status")
    records = list(db.damage_claims.values())
    if move_job_id is not None:
        records = [r for r in records if r["move_job_id"] == move_job_id]
    if status is not None:
        records = [r for r in records if r["status"] == status]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


@bp.route("/damage-claims/<cid>/items", methods=["POST"])
def add_claim_item(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster", "Customer"})
    claim = common.lookup(db.damage_claims, cid)
    body = common.get_json_body()
    common.require_fields(body, ["label", "item_weight_lbs", "repair_cost_cents", "replacement_value_cents"])
    common.require_int_field(body, "item_weight_lbs", minimum=1)
    common.require_int_field(body, "repair_cost_cents", minimum=0)
    common.require_int_field(body, "replacement_value_cents", minimum=0)

    item = db.new_line_item({
        "claim_id": cid,
        "label": body["label"],
        "item_weight_lbs": body["item_weight_lbs"],
        "repair_cost_cents": body["repair_cost_cents"],
        "replacement_value_cents": body["replacement_value_cents"],
    })
    db.claim_items[item["id"]] = item
    return object_response(public(item), 201)


@bp.route("/damage-claims/<cid>/items", methods=["GET"])
def list_claim_items(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster", "PlatformAdmin", "Customer"})
    common.lookup(db.damage_claims, cid)
    limit, offset = common.parse_pagination()
    records = [it for it in db.claim_items.values() if it["claim_id"] == cid]
    page, total = common.paginate(records, limit, offset)
    return array_response(public_list(page), limit, offset, total, 200)


def _check_segregation(claim, user_id):
    """SoD (priority 5): acting user may not be the filer."""
    if user_id == claim["filed_by_user_id"]:
        raise err("ERR_SEGREGATION_OF_DUTIES", "The filer of a claim may not adjudicate it.")


@bp.route("/damage-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster"})
    claim = common.lookup(db.damage_claims, cid)
    job = common.lookup(db.move_jobs, claim["move_job_id"])

    # SoD (priority 5) before state.
    _check_segregation(claim, user_id)
    # State (priority 6): approve only from UNDER_REVIEW.
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim may be approved.")
    # DELIVERED requirement (priority 20).
    if job["job_status"] != "DELIVERED":
        raise err("ERR_NOT_DELIVERED", "The linked job is no longer DELIVERED.")
    # At-least-one-item (priority 21).
    items = [it for it in db.claim_items.values() if it["claim_id"] == cid]
    if not items:
        raise err("ERR_CLAIM_NO_ITEMS", "A claim must have at least one item to be approved.")

    settlement = calculations.claim_settlement(
        claim["coverage_snapshot"], claim["deductible_cents"], items
    )
    claim["settlement_cents"] = settlement
    claim["adjudicated_by_user_id"] = user_id
    claim["status"] = "APPROVED"
    db.touch(claim)

    job["refunded_cents"] += settlement
    common.recompute_balance(job)
    db.touch_updated_only(job)

    return object_response(public(claim), 200)


@bp.route("/damage-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster"})
    claim = common.lookup(db.damage_claims, cid)
    job = common.lookup(db.move_jobs, claim["move_job_id"])

    _check_segregation(claim, user_id)
    if claim["status"] != "UNDER_REVIEW":
        raise err("ERR_INVALID_STATE", "Only an UNDER_REVIEW claim may be denied.")
    if job["job_status"] != "DELIVERED":
        raise err("ERR_NOT_DELIVERED", "The linked job is no longer DELIVERED.")

    claim["adjudicated_by_user_id"] = user_id
    claim["status"] = "DENIED"
    db.touch(claim)
    return object_response(public(claim), 200)


@bp.route("/damage-claims/<cid>/reopen", methods=["POST"])
def reopen_claim(cid):
    user_id, role = authenticate()
    require_roles(role, {"ClaimsAdjuster"})
    claim = common.lookup(db.damage_claims, cid)
    job = common.lookup(db.move_jobs, claim["move_job_id"])

    _check_segregation(claim, user_id)
    # State (priority 6): reopen only from APPROVED.
    if claim["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Only an APPROVED claim may be reopened.")
    # Reopen is undefined when the linked job is CLOSED (PRD §3.10 / scaffold
    # reopen precondition MoveJob.job_status != CLOSED). Treated as an invalid
    # state transition.
    if job["job_status"] == "CLOSED":
        raise err("ERR_INVALID_STATE", "Cannot reopen a claim on a closed job.")

    prior = claim["settlement_cents"]
    job["refunded_cents"] -= prior
    common.recompute_balance(job)
    db.touch_updated_only(job)

    claim["settlement_cents"] = 0
    claim["adjudicated_by_user_id"] = None
    claim["status"] = "UNDER_REVIEW"
    db.touch(claim)

    return object_response(public(claim), 200)
