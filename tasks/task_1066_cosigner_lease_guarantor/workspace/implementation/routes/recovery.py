"""Recovery plans and installments (PRD 3.7)."""
from flask import Blueprint, request

import db
from auth import require, body
from validation import get_or_404, req_int
from responses import success, list_response
from serializers import serialize
from errors import ApiError
from services import open_recovery_delta

bp = Blueprint("recovery", __name__)


@bp.get("/recovery-plans/<pid>")
@require("RecoveryAgent", "ComplianceOfficer", "PlatformAdmin")
def get_plan(pid):
    p = get_or_404(db.recovery_plans, pid)
    return success(serialize(p), 200)


@bp.get("/recovery-plans")
@require("RecoveryAgent", "ComplianceOfficer", "PlatformAdmin")
def list_plans():
    args = request.args
    items = list(db.recovery_plans.values())
    for key in ("claim_id", "applicant_id", "status"):
        val = args.get(key)
        if val is not None:
            items = [x for x in items if x.get(key) == val]
    return list_response(items, args)


@bp.post("/recovery-plans/<pid>/installments")
@require("RecoveryAgent")
def create_installment(pid):
    plan = get_or_404(db.recovery_plans, pid)
    b = body()
    amount = req_int(b, "amount_cents", positive=True)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    inst = {
        "recovery_plan_id": pid,
        "amount_cents": amount,
        "received_date": db.now_iso(),
        "status": "POSTED",
    }
    db.stamp_common(inst)
    db.recovery_installments[inst["id"]] = inst

    plan["recovered_cents"] += amount
    plan["outstanding_cents"] -= amount
    db.touch(plan)

    if plan["outstanding_cents"] == 0:
        plan["status"] = "SETTLED"
        db.touch(plan)
        open_recovery_delta(plan["applicant_id"], -1)

    return success(serialize(inst), 201)


@bp.get("/recovery-plans/<pid>/installments")
@require("RecoveryAgent", "ComplianceOfficer", "PlatformAdmin")
def list_installments(pid):
    get_or_404(db.recovery_plans, pid)
    items = [i for i in db.recovery_installments.values() if i["recovery_plan_id"] == pid]
    return list_response(items, request.args)


@bp.post("/recovery-installments/<iid>/reverse")
@require("RecoveryAgent")
def reverse_installment(iid):
    inst = get_or_404(db.recovery_installments, iid)
    plan = db.recovery_plans.get(inst["recovery_plan_id"])
    if inst["status"] != "POSTED" or plan is None or plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")

    inst["status"] = "REVERSED"
    db.touch(inst)
    plan["recovered_cents"] -= inst["amount_cents"]
    plan["outstanding_cents"] += inst["amount_cents"]
    db.touch(plan)
    return success(serialize(inst), 200)


@bp.post("/recovery-plans/<pid>/write-off")
@require("RecoveryAgent", "ComplianceOfficer")
def write_off_plan(pid):
    plan = get_or_404(db.recovery_plans, pid)
    if plan["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    plan["status"] = "WRITTEN_OFF"
    db.touch(plan)
    open_recovery_delta(plan["applicant_id"], -1)
    return success(serialize(plan), 200)
