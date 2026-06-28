"""PassGuaranteeClaim routes (PRD §3.5)."""
from flask import Blueprint, request

from db import db, stamp_create, touch
from response import success, list_success
from middleware import get_auth, require_role, pagination_params, paginate
from services import validate as V
from services.serialize import public, public_list
from services.lookups import get_enrollment, get_claim, assert_owner
from services import enrollment_service as ES
from errors import raise_err
import errors

bp = Blueprint("claims", __name__)


@bp.post("/pass-guarantee-claims")
def file_claim():
    user_id, role = get_auth()
    require_role(role, {"Learner"})
    data = V.body()
    enrollment_id = V.as_str(V.require(data, "enrollment_id"), "enrollment_id")
    remedy = V.as_enum(V.require(data, "remedy"), "remedy",
                       {"RETAKE_EXTENSION", "MONEY_BACK"})
    enr = get_enrollment(enrollment_id)
    assert_owner(enr, user_id)
    # A claim is filed against a FAILED enrollment.
    if enr["status"] != "FAILED":
        raise_err(errors.ERR_INVALID_STATE, "enrollment not FAILED")
    rec = {
        "enrollment_id": enrollment_id,
        "remedy": remedy,
        "refund_amount_cents": 0,
        "status": "SUBMITTED",
    }
    stamp_create(rec)
    db.pass_guarantee_claims[rec["id"]] = rec
    return success(public(rec), status=201)


@bp.get("/pass-guarantee-claims/<cid>")
def get_claim_route(cid):
    user_id, role = get_auth()
    require_role(role, {"Learner", "ExamProctor"})
    rec = get_claim(cid)
    if role == "Learner":
        enr = db.enrollments.get(rec["enrollment_id"])
        if enr is None or enr["learner_id"] != user_id:
            raise_err(errors.ERR_NOT_RESOURCE_OWNER, "not the resource owner")
    return success(public(rec))


@bp.get("/pass-guarantee-claims")
def list_claims():
    user_id, role = get_auth()
    require_role(role, {"Learner", "ExamProctor"})
    limit, offset = pagination_params()
    rows = list(db.pass_guarantee_claims.values())
    enrollment_id = request.args.get("enrollment_id")
    if enrollment_id is not None:
        rows = [r for r in rows if r["enrollment_id"] == enrollment_id]
    if role == "Learner":
        owned = {e["id"] for e in db.enrollments.values()
                 if e["learner_id"] == user_id}
        rows = [r for r in rows if r["enrollment_id"] in owned]
    rows.sort(key=lambda r: r["_seq"])
    window, total, has_more = paginate(rows, limit, offset)
    return list_success(public_list(window), limit, offset, total, has_more)


@bp.post("/pass-guarantee-claims/<cid>/decide")
def decide_claim(cid):
    user_id, role = get_auth()
    require_role(role, {"ExamProctor"})
    claim = get_claim(cid)
    data = V.body()
    decision = V.as_enum(V.require(data, "decision"), "decision",
                         {"APPROVE", "DENY"})
    if claim["status"] != "SUBMITTED":
        raise_err(errors.ERR_INVALID_STATE, "claim not SUBMITTED")
    enr = db.enrollments.get(claim["enrollment_id"])
    # Either decision first requires the owning enrollment to be FAILED.
    if enr is None or enr["status"] != "FAILED":
        raise_err(errors.ERR_INVALID_STATE, "owning enrollment not FAILED")
    plan = db.subscription_plans[enr["subscription_plan_id"]]

    if decision == "DENY":
        claim["status"] = "DENIED"
        touch(claim)
        return success(public(claim))

    # APPROVE additionally requires guarantee_eligible == true.
    if not enr["guarantee_eligible"]:
        raise_err(errors.ERR_GUARANTEE_NOT_ELIGIBLE, "enrollment not eligible")
    claim["status"] = "APPROVED"
    if claim["remedy"] == "RETAKE_EXTENSION":
        claim["refund_amount_cents"] = 0
        touch(claim)
        # enrollment stays FAILED (retake window extended)
    else:  # MONEY_BACK
        refund = ES.compute_refund(enr, plan)
        claim["refund_amount_cents"] = refund
        touch(claim)
        # drive enrollment FAILED -> REFUNDED (cascade). PRD §3.5: voiding every
        # remaining DUE installment brings financing_balance_cents to zero.
        ES.void_due_installments(enr["id"])
        ES.recompute_ledger(enr)
        enr["financing_balance_cents"] = 0
        ES.drop_joined_memberships(enr["id"])
        enr["status"] = "REFUNDED"
        touch(enr)
    return success(public(claim))
