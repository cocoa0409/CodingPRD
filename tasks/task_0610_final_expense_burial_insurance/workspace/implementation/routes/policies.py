"""Policy lifecycle, beneficiaries, and funeral-home assignments
(PRD §3.5, §3.7, §3.8, §3.10)."""
from flask import Blueprint, request

import db
from errors import err
from helpers import get_body, require_fields, serialize, paginate, sort_by_created
from middleware import get_identity, require_roles, require_owner_if_policyholder
from response import success
from services import policy_ops, policy_calc

bp = Blueprint("policies", __name__)

RELATIONSHIPS = {"SPOUSE", "CHILD", "SIBLING", "PARENT", "ESTATE", "OTHER"}
TERMINAL_COVERAGE = {"TERMINATED", "SURRENDERED", "RESCINDED"}


def _get_policy_or_404(policy_id):
    policy = db.policies.get(policy_id)
    if policy is None:
        raise err("ERR_NOT_FOUND", "Policy not found")
    return policy


@bp.route("/policies/<policy_id>", methods=["GET"])
def get_policy(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "ClaimsExaminer", "Policyholder", "Underwriter"})
    policy = _get_policy_or_404(policy_id)
    with db.LOCK:
        policy_calc.recompute_policy(policy)
    return success(serialize(policy), status=200, response_type="object")


@bp.route("/policies", methods=["GET"])
def list_policies():
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "ClaimsExaminer", "Underwriter"})
    items = list(db.policies.values())
    for key in ("application_id", "product_plan_id", "applicant_id", "policyholder_user_id", "coverage_status"):
        val = request.args.get(key)
        if val:
            items = [p for p in items if p.get(key) == val]
    with db.LOCK:
        for p in items:
            policy_calc.recompute_policy(p)
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(p) for p in page], status=200, response_type="array", pagination=meta)


@bp.route("/policies/<policy_id>/lapse", methods=["POST"])
def lapse_policy(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin"})
    policy = _get_policy_or_404(policy_id)
    with db.LOCK:
        policy_ops.manual_lapse(policy)
        policy_calc.recompute_policy(policy)
    return success(serialize(policy), status=200, response_type="object")


@bp.route("/policies/<policy_id>/reinstate", methods=["POST"])
def reinstate_policy(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin"})
    policy = _get_policy_or_404(policy_id)
    with db.LOCK:
        policy_ops.reinstate(policy)
        policy_calc.recompute_policy(policy)
    return success(serialize(policy), status=200, response_type="object")


@bp.route("/policies/<policy_id>/surrender", methods=["POST"])
def surrender_policy(policy_id):
    user_id, role = get_identity()
    require_roles(role, {"Policyholder", "PolicyAdmin"})
    policy = _get_policy_or_404(policy_id)
    require_owner_if_policyholder(role, user_id, policy)
    with db.LOCK:
        policy_ops.surrender(policy)
        policy_calc.recompute_policy(policy)
    return success(serialize(policy), status=200, response_type="object")


# ---- Beneficiaries -------------------------------------------------------
@bp.route("/policies/<policy_id>/beneficiaries", methods=["POST"])
def add_beneficiary(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder"})
    policy = _get_policy_or_404(policy_id)
    # Designable only while coverage is ACTIVE or LAPSED (priority 9 before constraint).
    if policy["coverage_status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_POLICY_NOT_DESIGNABLE", "Policy coverage is not designable")
    body = get_body()
    require_fields(body, ["full_name", "relationship", "share_pct"])
    if body["relationship"] not in RELATIONSHIPS:
        raise err("ERR_VALIDATION", "Invalid relationship")
    share = body["share_pct"]
    if not isinstance(share, int) or isinstance(share, bool) or share < 1 or share > 100:
        raise err("ERR_VALIDATION", "share_pct must be between 1 and 100")
    # After the write, active shares must not exceed 100.
    current = sum(
        b["share_pct"] for b in db.beneficiaries.values()
        if b["policy_id"] == policy_id and b["status"] == "ACTIVE"
    )
    if current + share > 100:
        raise err("ERR_SHARES_EXCEED_100", "Active beneficiary shares would exceed 100")

    beneficiary = {
        "policy_id": policy_id,
        "full_name": body["full_name"],
        "relationship": body["relationship"],
        "share_pct": share,
        "status": "ACTIVE",
    }
    with db.LOCK:
        db.stamp_full(beneficiary)
        db.beneficiaries[beneficiary["id"]] = beneficiary
    return success(serialize(beneficiary), status=201, response_type="object")


@bp.route("/policies/<policy_id>/beneficiaries", methods=["GET"])
def list_beneficiaries(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    _get_policy_or_404(policy_id)
    items = [b for b in db.beneficiaries.values() if b["policy_id"] == policy_id]
    status = request.args.get("status")
    if status:
        items = [b for b in items if b["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(b) for b in page], status=200, response_type="array", pagination=meta)


@bp.route("/policies/<policy_id>/beneficiaries/<beneficiary_id>/revoke", methods=["POST"])
def revoke_beneficiary(policy_id, beneficiary_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder"})
    # Left-to-right existence: policy first, then beneficiary.
    _get_policy_or_404(policy_id)
    beneficiary = db.beneficiaries.get(beneficiary_id)
    if beneficiary is None or beneficiary["policy_id"] != policy_id:
        raise err("ERR_NOT_FOUND", "Beneficiary not found")
    with db.LOCK:
        beneficiary["status"] = "REVOKED"
        db.touch(beneficiary)
    return success(serialize(beneficiary), status=200, response_type="object")


# ---- Funeral-home assignments --------------------------------------------
@bp.route("/policies/<policy_id>/funeral-home-assignment", methods=["POST"])
def add_funeral_home(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder"})
    policy = _get_policy_or_404(policy_id)
    if policy["coverage_status"] not in ("ACTIVE", "LAPSED"):
        raise err("ERR_POLICY_NOT_DESIGNABLE", "Policy coverage is not designable")
    body = get_body()
    require_fields(body, ["funeral_home_name", "assigned_benefit_cents"])
    amount = body["assigned_benefit_cents"]
    if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
        raise err("ERR_VALIDATION", "assigned_benefit_cents must be a positive integer")

    assignment = {
        "policy_id": policy_id,
        "funeral_home_name": body["funeral_home_name"],
        "assigned_benefit_cents": amount,
        "status": "ACTIVE",
    }
    with db.LOCK:
        db.stamp_full(assignment)
        db.funeral_home_assignments[assignment["id"]] = assignment
    return success(serialize(assignment), status=201, response_type="object")


@bp.route("/policies/<policy_id>/funeral-home-assignments", methods=["GET"])
def list_funeral_homes(policy_id):
    _, role = get_identity()
    require_roles(role, {"PolicyAdmin", "Policyholder", "ClaimsExaminer"})
    _get_policy_or_404(policy_id)
    items = [f for f in db.funeral_home_assignments.values() if f["policy_id"] == policy_id]
    status = request.args.get("status")
    if status:
        items = [f for f in items if f["status"] == status]
    items = sort_by_created(items)
    page, meta = paginate(items)
    return success([serialize(f) for f in page], status=200, response_type="array", pagination=meta)
