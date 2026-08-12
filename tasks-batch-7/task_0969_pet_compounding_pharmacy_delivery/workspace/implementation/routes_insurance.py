from flask import Blueprint, request

import db
from errors import ApiError
from middleware import auth, body, require_ownership
from response import success, paged
from services import get_or_404, waterfall
from util import (new_resource, touch, req, as_str, as_int, as_num,
                  as_date_str)

bp = Blueprint("insurance", __name__)

POLICY_READ = ("Owner", "InsuranceAdjuster", "PharmacyAdmin")


def _filter(items, names):
    out = []
    for it in items:
        ok = True
        for n in names:
            v = request.args.get(n)
            if v is not None and str(it.get(n)) != v:
                ok = False
                break
        if ok:
            out.append(it)
    return out


# ---- Insurance policies ----

@bp.route("/insurance-policies", methods=["POST"])
def create_policy():
    auth("Owner", "PharmacyAdmin")
    d = body()
    pet_id = d.get("pet_id")
    if pet_id is not None:
        get_or_404(db.pets, pet_id, "pet")
    pet_id = as_str(req(d, "pet_id"), "pet_id")
    pet = db.pets[pet_id]
    insurer = as_str(req(d, "insurer_name"), "insurer_name")
    number = as_str(req(d, "policy_number"), "policy_number")
    deductible = as_int(req(d, "deductible_cents"), "deductible_cents")
    if deductible < 0:
        raise ApiError("ERR_INVALID_REQUEST", "deductible_cents must be >= 0", 400)
    coverage = as_num(req(d, "coverage_pct"), "coverage_pct")
    if coverage < 0 or coverage > 1:
        raise ApiError("ERR_INVALID_REQUEST", "coverage_pct must be in [0, 1]", 400)
    limit = as_int(req(d, "annual_limit_cents"), "annual_limit_cents")
    if limit <= 0:
        raise ApiError("ERR_INVALID_REQUEST", "annual_limit_cents must be > 0", 400)
    renewal = as_date_str(req(d, "renewal_date"), "renewal_date")
    for p in db.insurance_policies.values():
        if p["policy_number"] == number:
            raise ApiError("ERR_POLICY_NUMBER_EXISTS",
                           "policy_number already registered", 409)
    p = new_resource({
        "owner_id": pet["owner_id"], "pet_id": pet_id, "insurer_name": insurer,
        "policy_number": number, "deductible_cents": deductible,
        "deductible_met_cents": 0, "coverage_pct": coverage,
        "annual_limit_cents": limit, "annual_used_cents": 0,
        "renewal_date": renewal, "status": "ACTIVE",
    })
    db.insurance_policies[p["id"]] = p
    return success(p, 201)


@bp.route("/insurance-policies/<rid>", methods=["GET"])
def get_policy(rid):
    auth(*POLICY_READ)
    return success(get_or_404(db.insurance_policies, rid, "insurance policy"))


@bp.route("/insurance-policies", methods=["GET"])
def list_policies():
    auth(*POLICY_READ)
    return paged(_filter(list(db.insurance_policies.values()),
                         ["owner_id", "pet_id", "status"]))


@bp.route("/insurance-policies/<rid>/lapse", methods=["POST"])
def lapse_policy(rid):
    auth("InsuranceAdjuster")
    p = get_or_404(db.insurance_policies, rid, "insurance policy")
    if p["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", "policy is not ACTIVE", 409)
    p["status"] = "LAPSED"
    touch(p)
    return success(p)


# ---- Claims ----

@bp.route("/insurance-policies/<rid>/claims", methods=["POST"])
def create_claim(rid):
    auth("Owner")
    policy = get_or_404(db.insurance_policies, rid, "insurance policy")
    d = body()
    order_id = d.get("compound_order_id")
    if order_id is not None:
        get_or_404(db.compound_orders, order_id, "compound order")
    order_id = as_str(req(d, "compound_order_id"), "compound_order_id")
    order = db.compound_orders[order_id]
    claimed = as_int(req(d, "claimed_amount_cents"), "claimed_amount_cents")
    expected = as_int(req(d, "expected_policy_version"), "expected_policy_version")
    if expected != policy["version"]:
        raise ApiError("ERR_STALE_VERSION",
                       "expected_policy_version does not match the policy's "
                       "current version", 412)
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "policy is not ACTIVE", 409)
    if claimed != order["provisional_price_cents"]:
        raise ApiError("ERR_CLAIM_AMOUNT_MISMATCH",
                       "claimed_amount_cents must equal the order's "
                       "provisional_price_cents", 422)
    estimate, _ = waterfall(order["provisional_price_cents"], policy)
    claim = new_resource({
        "policy_id": policy["id"], "compound_order_id": order_id,
        "status": "SUBMITTED", "claimed_amount_cents": claimed,
        "estimate_cents": estimate, "approved_amount_cents": None,
        "deductible_applied_cents": None, "appeal_count": 0,
        "denial_reason": None,
    })
    db.claims[claim["id"]] = claim
    # claim creation recomputes the policy's deductible estimate reserve
    touch(policy)
    return success(claim, 201)


@bp.route("/claims/<rid>", methods=["GET"])
def get_claim(rid):
    auth(*POLICY_READ)
    return success(get_or_404(db.claims, rid, "claim"))


@bp.route("/claims", methods=["GET"])
def list_claims():
    auth(*POLICY_READ)
    return paged(_filter(list(db.claims.values()),
                         ["policy_id", "compound_order_id", "status"]))


@bp.route("/claims/<rid>/adjudicate", methods=["POST"])
def adjudicate(rid):
    auth("InsuranceAdjuster")
    claim = get_or_404(db.claims, rid, "claim")
    d = body()
    outcome = req(d, "outcome")
    if outcome not in ("APPROVE", "REJECT"):
        raise ApiError("ERR_INVALID_REQUEST",
                       "outcome must be APPROVE or REJECT", 400)
    if outcome == "REJECT":
        as_str(req(d, "denial_reason"), "denial_reason")
    if claim["status"] not in ("SUBMITTED", "APPEALED"):
        raise ApiError("ERR_INVALID_STATE",
                       "claim is not in SUBMITTED or APPEALED", 409)
    policy = db.insurance_policies[claim["policy_id"]]
    order = db.compound_orders[claim["compound_order_id"]]
    if outcome == "APPROVE":
        if policy["status"] != "ACTIVE":
            raise ApiError("ERR_POLICY_NOT_ACTIVE", "policy is not ACTIVE", 409)
        if claim["status"] == "SUBMITTED" and order["final_price_cents"] is None:
            raise ApiError("ERR_INVALID_STATE",
                           "order final_price_cents is not yet computed", 409)
        amount = order["final_price_cents"] if order["final_price_cents"] is not None \
            else order["provisional_price_cents"]
        payout, ded = waterfall(amount, policy)
        claim["approved_amount_cents"] = payout
        claim["deductible_applied_cents"] = ded
        claim["denial_reason"] = None
        claim["status"] = "APPROVED"
    else:
        claim["denial_reason"] = d["denial_reason"]
        claim["status"] = "REJECTED"
    touch(claim)
    return success(claim)


@bp.route("/claims/<rid>/appeal", methods=["POST"])
def appeal(rid):
    _, user_id = auth("Owner")
    claim = get_or_404(db.claims, rid, "claim")
    policy = db.insurance_policies[claim["policy_id"]]
    require_ownership(user_id, policy["owner_id"])
    if claim["status"] != "REJECTED":
        raise ApiError("ERR_INVALID_STATE", "claim is not REJECTED", 409)
    if claim["appeal_count"] >= 2:
        raise ApiError("ERR_MAX_APPEALS_EXCEEDED",
                       "appeal attempted beyond the limit of 2", 422)
    claim["appeal_count"] += 1
    claim["status"] = "APPEALED"
    touch(claim)
    return success(claim)


@bp.route("/claims/<rid>/pay", methods=["POST"])
def pay_claim(rid):
    auth("InsuranceAdjuster")
    claim = get_or_404(db.claims, rid, "claim")
    if claim["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", "claim is not APPROVED", 409)
    policy = db.insurance_policies[claim["policy_id"]]
    if policy["status"] != "ACTIVE":
        raise ApiError("ERR_POLICY_NOT_ACTIVE", "policy is not ACTIVE", 409)
    claim["status"] = "PAID"
    policy["annual_used_cents"] += claim["approved_amount_cents"]
    policy["deductible_met_cents"] += claim["deductible_applied_cents"]
    touch(policy)
    touch(claim)
    return success(claim)
