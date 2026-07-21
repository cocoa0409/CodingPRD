from flask import Blueprint, request

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, touch, parse_dt
from envelope import ok, created, list_response
from validation import (
    get_body, require_str, require_date, require_int_nonneg, require_enum,
    parse_pagination,
)

bp = Blueprint("policies", __name__)


# ---------------------------------------------------------------- StopLossPolicy
@bp.post("/stop-loss-policies")
def create_policy():
    require_auth({"TPAAdmin"})
    body = get_body()
    plan_id = require_str(body, "plan_id")
    if plan_id not in db.plans:
        fail(errors.ERR_PLAN_NOT_FOUND, "Plan not found")
    pol = {
        "id": new_id(),
        "plan_id": plan_id,
        "carrier_name": require_str(body, "carrier_name"),
        "contract_basis": require_enum(body, "contract_basis", {"PAID", "INCURRED"}),
        "effective_date": require_date(body, "effective_date"),
        "expiry_date": require_date(body, "expiry_date"),
        "specific_deductible_cents": require_int_nonneg(body, "specific_deductible_cents"),
        "aggregate_attachment_cents": require_int_nonneg(body, "aggregate_attachment_cents"),
        "total_specific_reimbursed_cents": 0,
        "total_aggregate_reimbursed_cents": 0,
        "status": "DRAFT",
    }
    stamp_new(pol)
    db.policies[pol["id"]] = pol
    return created(serializers.policy(pol))


@bp.get("/stop-loss-policies/<pid>")
def get_policy(pid):
    require_auth(ANY_ROLE)
    pol = db.policies.get(pid)
    if not pol:
        fail(errors.ERR_STOP_LOSS_POLICY_NOT_FOUND, "Stop-loss policy not found")
    return ok(serializers.policy(pol))


@bp.get("/stop-loss-policies")
def list_policies():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.policies.values())
    plan_id = request.args.get("plan_id")
    if plan_id is not None:
        items = [p for p in items if p["plan_id"] == plan_id]
    return list_response(items, serializers.policy, limit, offset)


@bp.post("/stop-loss-policies/<pid>/activate")
def activate_policy(pid):
    require_auth({"TPAAdmin"})
    pol = db.policies.get(pid)
    if not pol:
        fail(errors.ERR_STOP_LOSS_POLICY_NOT_FOUND, "Stop-loss policy not found")
    if pol["status"] != "DRAFT":
        fail(errors.ERR_INVALID_STATE, "Policy is not DRAFT")
    a1, e1 = parse_dt(pol["effective_date"]), parse_dt(pol["expiry_date"])
    for other in db.policies.values():
        if other["id"] == pol["id"]:
            continue
        if other["plan_id"] != pol["plan_id"] or other["status"] != "ACTIVE":
            continue
        a2, e2 = parse_dt(other["effective_date"]), parse_dt(other["expiry_date"])
        # half-open [effective, expiry): overlap iff a1 < e2 and a2 < e1
        if a1 < e2 and a2 < e1:
            fail(errors.ERR_POLICY_PERIOD_OVERLAP, "Policy period overlaps an active policy")
    pol["status"] = "ACTIVE"
    touch(pol)
    return ok(serializers.policy(pol))


@bp.post("/stop-loss-policies/<pid>/settle-aggregate")
def settle_aggregate(pid):
    require_auth({"TPAAdmin", "Auditor"})
    pol = db.policies.get(pid)
    if not pol:
        fail(errors.ERR_STOP_LOSS_POLICY_NOT_FOUND, "Stop-loss policy not found")
    if pol["status"] != "ACTIVE":
        fail(errors.ERR_POLICY_NOT_ACTIVE, "Policy is not ACTIVE")

    basis = pol["contract_basis"]
    eff, exp = parse_dt(pol["effective_date"]), parse_dt(pol["expiry_date"])
    plan_id = pol["plan_id"]

    gross = 0
    for c in db.claims.values():
        m = db.members.get(c["member_id"])
        if not m or m["plan_id"] != plan_id:
            continue
        if basis == "INCURRED":
            if c["status"] in ("ADJUDICATED", "PAID"):
                sd = parse_dt(c["service_date"])
                if eff <= sd <= exp:
                    gross += c["plan_paid_cents"] or 0
        else:  # PAID
            if c["status"] == "PAID" and c["paid_at"] is not None:
                pd = parse_dt(c["paid_at"])
                if eff <= pd <= exp:
                    gross += c["plan_paid_cents"] or 0

    net = gross - pol["total_specific_reimbursed_cents"]
    excess = max(0, net - pol["aggregate_attachment_cents"])
    new_aggregate = excess - pol["total_aggregate_reimbursed_cents"]
    if new_aggregate <= 0:
        fail(errors.ERR_AGGREGATE_NOT_REACHED, "Aggregate net plan-paid does not exceed attachment")

    r = {
        "id": new_id(),
        "stop_loss_policy_id": pol["id"],
        "claim_id": None,
        "member_id": None,
        "reimbursement_type": "AGGREGATE",
        "amount_cents": new_aggregate,
        "basis_note": basis,
    }
    stamp_new(r)
    db.reimbursements[r["id"]] = r
    pol["total_aggregate_reimbursed_cents"] += new_aggregate
    pol["status"] = "SETTLED"
    touch(pol)
    return created(serializers.reimbursement(r))


# ------------------------------------------------------------------------ Laser
@bp.post("/lasers")
def create_laser():
    require_auth({"TPAAdmin"})
    body = get_body()
    policy_id = require_str(body, "stop_loss_policy_id")
    if policy_id not in db.policies:
        fail(errors.ERR_STOP_LOSS_POLICY_NOT_FOUND, "Stop-loss policy not found")
    member_id = require_str(body, "member_id")
    if member_id not in db.members:
        fail(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    laser_ded = require_int_nonneg(body, "laser_deductible_cents")
    eff = require_date(body, "effective_date")
    exp = require_date(body, "expiry_date")

    pol = db.policies[policy_id]
    m = db.members[member_id]
    # state: policy must be ACTIVE
    if pol["status"] != "ACTIVE":
        fail(errors.ERR_POLICY_NOT_ACTIVE, "Lasers require an ACTIVE policy")
    # referential: member belongs to policy's plan
    if m["plan_id"] != pol["plan_id"]:
        fail(errors.ERR_LASER_MEMBER_MISMATCH, "Laser member does not belong to the policy's plan")
    # window overlap: closed intervals, touching endpoints conflict
    ne, nx = parse_dt(eff), parse_dt(exp)
    for other in db.lasers.values():
        if other["stop_loss_policy_id"] != policy_id or other["member_id"] != member_id:
            continue
        oe, ox = parse_dt(other["effective_date"]), parse_dt(other["expiry_date"])
        if ne <= ox and oe <= nx:
            fail(errors.ERR_LASER_WINDOW_OVERLAP, "Laser window overlaps an existing laser")

    laser = {
        "id": new_id(),
        "stop_loss_policy_id": policy_id,
        "member_id": member_id,
        "laser_deductible_cents": laser_ded,
        "effective_date": eff,
        "expiry_date": exp,
    }
    stamp_new(laser)
    db.lasers[laser["id"]] = laser
    return created(serializers.laser(laser))


@bp.get("/lasers/<lid>")
def get_laser(lid):
    require_auth(ANY_ROLE)
    laser = db.lasers.get(lid)
    if not laser:
        fail(errors.ERR_LASER_NOT_FOUND, "Laser not found")
    return ok(serializers.laser(laser))


@bp.get("/lasers")
def list_lasers():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.lasers.values())
    policy_id = request.args.get("stop_loss_policy_id")
    member_id = request.args.get("member_id")
    if policy_id is not None:
        items = [l for l in items if l["stop_loss_policy_id"] == policy_id]
    if member_id is not None:
        items = [l for l in items if l["member_id"] == member_id]
    return list_response(items, serializers.laser, limit, offset)


# ------------------------------------------------------- StopLossReimbursement
@bp.get("/stop-loss-reimbursements/<rid>")
def get_reimbursement(rid):
    require_auth(ANY_ROLE)
    r = db.reimbursements.get(rid)
    if not r:
        fail(errors.ERR_REIMBURSEMENT_NOT_FOUND, "Reimbursement not found")
    return ok(serializers.reimbursement(r))


@bp.get("/stop-loss-reimbursements")
def list_reimbursements():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.reimbursements.values())
    policy_id = request.args.get("stop_loss_policy_id")
    claim_id = request.args.get("claim_id")
    if policy_id is not None:
        items = [r for r in items if r["stop_loss_policy_id"] == policy_id]
    if claim_id is not None:
        items = [r for r in items if r["claim_id"] == claim_id]
    return list_response(items, serializers.reimbursement, limit, offset)
