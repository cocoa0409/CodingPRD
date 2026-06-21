"""Policy endpoints (PRD §3.2, §3.3, §3.5)."""
from flask import Blueprint, request, g

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, policy_ops
from services.store_helpers import (
    make_record, touch, get_plan, get_traveler, get_policy, get_insured,
    covered_insured_for_policy,
)

bp = Blueprint("policies", __name__)


def _ensure_owner(policy):
    """Traveler-role ownership check (priority 4). Opaque roles are not checked."""
    if g.user_role == "Traveler" and policy["owner_traveler_id"] != g.user_id:
        raise errors.not_resource_owner("Traveler does not own this policy.")


# --------------------------------------------------------------------------
# Create / read / list
# --------------------------------------------------------------------------
@bp.route("/policies", methods=["POST"])
@require_roles("Underwriter", "Traveler")
def create_policy():
    body = common.get_json_body()

    plan_id = common.require_str(body, "plan_id")
    owner_traveler_id = common.require_str(body, "owner_traveler_id")
    trip_cost_cents = common.require_int(body, "trip_cost_cents", minimum=1)
    initial_deposit_at = common.require_datetime(body, "initial_deposit_at")
    trip_start_at = common.require_datetime(body, "trip_start_at")
    trip_end_at = common.require_datetime(body, "trip_end_at")
    cfar_opted = common.opt_bool(body, "cfar_opted", default=False)

    if trip_end_at <= trip_start_at:
        raise errors.invalid_request("trip_end_at must be strictly later than trip_start_at.")

    # Existence of FK resources (priority 3), left-to-right.
    plan = get_plan(plan_id)
    owner = get_traveler(owner_traveler_id)

    # Traveler may only quote a policy they will own.
    if g.user_role == "Traveler" and owner_traveler_id != g.user_id:
        raise errors.not_resource_owner("Traveler may only create a policy they own.")

    rec = make_record()
    rec.update({
        "plan_id": plan_id,
        "owner_traveler_id": owner_traveler_id,
        "trip_cost_cents": trip_cost_cents,
        "initial_deposit_at": body["initial_deposit_at"],
        "trip_start_at": body["trip_start_at"],
        "trip_end_at": body["trip_end_at"],
        "_initial_deposit_at_dt": initial_deposit_at,
        "_trip_start_at_dt": trip_start_at,
        "_trip_end_at_dt": trip_end_at,
        "cfar_opted": cfar_opted,
        "base_premium_cents": 0,
        "premium_cents": 0,
        "aggregate_limit_cents": 0,
        "amount_reimbursed_cents": 0,
        "remaining_aggregate_cents": 0,
        "net_premium_collected_cents": 0,
        "preexisting_waiver_granted": False,
        "issued_at": None,
        "free_look_ends_at": None,
        "_issued_at_dt": None,
        "_free_look_ends_at_dt": None,
        "payment_status": "PENDING",
        "coverage_status": "QUOTED",
    })
    policy_ops.recompute_premium(rec)
    db.policies[rec["id"]] = rec
    return response.success_object(serialize.policy_out(rec), status=201)


@bp.route("/policies/<policy_id>", methods=["GET"])
@require_roles("Any")
def get_policy_route(policy_id):
    rec = get_policy(policy_id)
    return response.success_object(serialize.policy_out(rec), status=200)


@bp.route("/policies", methods=["GET"])
@require_roles("Any")
def list_policies():
    items = list(db.policies.values())
    for field in ("plan_id", "owner_traveler_id", "coverage_status", "payment_status"):
        val = request.args.get(field)
        if val is not None:
            items = [p for p in items if p[field] == val]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.policy_out(p) for p in page], limit, offset, total)


# --------------------------------------------------------------------------
# Insured travelers
# --------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/insured-travelers", methods=["POST"])
@require_roles("Underwriter", "Traveler")
def add_insured(policy_id):
    policy = get_policy(policy_id)
    _ensure_owner(policy)

    body = common.get_json_body()
    traveler_id = common.require_str(body, "traveler_id")
    age_at_departure = common.require_int(body, "age_at_departure", minimum=0)
    covered_trip_cost_cents = common.require_int(body, "covered_trip_cost_cents", minimum=0)
    has_preexisting_condition = common.opt_bool(body, "has_preexisting_condition", default=False)

    # FK existence
    get_traveler(traveler_id)

    # State: only QUOTED policies accept new insured travelers.
    if policy["coverage_status"] != "QUOTED":
        raise errors.invalid_state("Policy is not QUOTED.")

    rec = make_record()
    rec.update({
        "policy_id": policy_id,
        "traveler_id": traveler_id,
        "age_at_departure": age_at_departure,
        "has_preexisting_condition": has_preexisting_condition,
        "covered_trip_cost_cents": covered_trip_cost_cents,
        "status": "COVERED",
    })

    # Coverage-overlap guard (priority 14) against this traveler's other policies.
    policy_ops.enforce_coverage_overlap(policy, traveler_id)

    db.insured_travelers[rec["id"]] = rec

    # Recompute premium (senior loading may now apply) and bump policy version.
    policy_ops.recompute_premium(policy)
    touch(policy)

    return response.success_object(serialize.insured_out(rec), status=201)


@bp.route("/policies/<policy_id>/insured-travelers", methods=["GET"])
@require_roles("Any")
def list_policy_insured(policy_id):
    get_policy(policy_id)
    items = [it for it in db.insured_travelers.values() if it["policy_id"] == policy_id]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.insured_out(i) for i in page], limit, offset, total)


@bp.route("/insured-travelers/<insured_id>", methods=["GET"])
@require_roles("Any")
def get_insured_route(insured_id):
    rec = get_insured(insured_id)
    return response.success_object(serialize.insured_out(rec), status=200)


@bp.route("/insured-travelers", methods=["GET"])
@require_roles("Any")
def list_insured():
    items = list(db.insured_travelers.values())
    for field in ("policy_id", "traveler_id", "status"):
        val = request.args.get(field)
        if val is not None:
            items = [it for it in items if it[field] == val]
    items = common.sort_by_created(items)
    page, limit, offset, total = common.paginate(items)
    return response.success_array([serialize.insured_out(i) for i in page], limit, offset, total)


# --------------------------------------------------------------------------
# Record payment (OCC-guarded)
# --------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/record-payment", methods=["POST"])
@require_roles("Underwriter", "Traveler")
def record_payment(policy_id):
    policy = get_policy(policy_id)
    _ensure_owner(policy)

    body = common.get_json_body()
    # expected_policy_version is mandatory on this request (PRD §2.9).
    expected_version = common.require_int(body, "expected_policy_version", minimum=0)

    # State (priority 6) before OCC (priority 7).
    if policy["payment_status"] != "PENDING":
        raise errors.invalid_state("Payment status is not PENDING.")

    if expected_version != policy["version"]:
        raise errors.ApiError(errors.ERR_STALE_VERSION, 412, "expected_policy_version does not match policy version.")

    policy["payment_status"] = "PAID"
    policy_ops.recompute_net_premium(policy)
    touch(policy)
    return response.success_object(serialize.policy_out(policy), status=200)


# --------------------------------------------------------------------------
# Issue
# --------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/issue", methods=["POST"])
@require_roles("Underwriter")
def issue(policy_id):
    policy = get_policy(policy_id)
    policy_ops.issue_policy(policy)
    return response.success_object(serialize.policy_out(policy), status=200)


# --------------------------------------------------------------------------
# Cancellations
# --------------------------------------------------------------------------
@bp.route("/policies/<policy_id>/free-look-cancel", methods=["POST"])
@require_roles("Traveler")
def free_look_cancel(policy_id):
    policy = get_policy(policy_id)
    _ensure_owner(policy)
    policy_ops.free_look_cancel(policy)
    return response.success_object(serialize.policy_out(policy), status=200)


@bp.route("/policies/<policy_id>/cancel", methods=["POST"])
@require_roles("Traveler")
def cancel(policy_id):
    policy = get_policy(policy_id)
    _ensure_owner(policy)
    policy_ops.post_free_look_cancel(policy)
    return response.success_object(serialize.policy_out(policy), status=200)
