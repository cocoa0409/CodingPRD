from flask import Blueprint, request

import errors
import serializers
from errors import fail
from auth import require_auth, ANY_ROLE
from store import db, new_id, stamp_new, touch, now_dt, parse_dt, add_days
from envelope import ok, created, list_response
from validation import (
    get_body, require_str, require_date, require_billed_lines, optional_int_nonneg,
    parse_pagination, round_half_up_cents,
)

bp = Blueprint("claims", __name__)


# ------------------------------------------------------------------ submit / read
@bp.post("/claims")
def create_claim():
    require_auth({"ClaimsExaminer"})
    body = get_body()
    member_id = require_str(body, "member_id")
    if member_id not in db.members:
        fail(errors.ERR_MEMBER_NOT_FOUND, "Member not found")
    provider_id = require_str(body, "provider_id")
    if provider_id not in db.providers:
        fail(errors.ERR_PROVIDER_NOT_FOUND, "Provider not found")
    service_date = require_date(body, "service_date")
    billed_lines = require_billed_lines(body, "billed_lines")
    ucr = optional_int_nonneg(body, "ucr_amount_cents", None)
    billed_total = sum(line["billed_cents"] for line in billed_lines)
    c = {
        "id": new_id(),
        "member_id": member_id,
        "provider_id": provider_id,
        "service_date": service_date,
        "billed_lines": billed_lines,
        "billed_total_cents": billed_total,
        "ucr_amount_cents": ucr,
        "allowed_amount_cents": None,
        "deductible_applied_cents": None,
        "member_coinsurance_cents": None,
        "member_responsibility_cents": None,
        "plan_paid_cents": None,
        "denial_reason": None,
        "pended_by_user_id": None,
        "paid_at": None,
        "status": "SUBMITTED",
        "_spec_reimb_amount": 0,
        "_spec_reimb_policy_id": None,
    }
    stamp_new(c)
    db.claims[c["id"]] = c
    return created(serializers.claim(c))


@bp.get("/claims/<cid>")
def get_claim(cid):
    require_auth(ANY_ROLE)
    c = db.claims.get(cid)
    if not c:
        fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")
    return ok(serializers.claim(c))


@bp.get("/claims")
def list_claims():
    require_auth(ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(db.claims.values())
    member_id = request.args.get("member_id")
    provider_id = request.args.get("provider_id")
    status = request.args.get("status")
    if member_id is not None:
        items = [c for c in items if c["member_id"] == member_id]
    if provider_id is not None:
        items = [c for c in items if c["provider_id"] == provider_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    return list_response(items, serializers.claim, limit, offset)


# --------------------------------------------------------------------- pend / deny
@bp.post("/claims/<cid>/pend")
def pend_claim(cid):
    user_id, _ = require_auth({"ClaimsExaminer"})
    c = db.claims.get(cid)
    if not c:
        fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")
    if c["status"] != "SUBMITTED":
        fail(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED")
    c["pended_by_user_id"] = user_id
    c["status"] = "PENDED"
    touch(c)
    return ok(serializers.claim(c))


@bp.post("/claims/<cid>/deny")
def deny_claim(cid):
    require_auth({"ClaimsExaminer"})
    c = db.claims.get(cid)
    if not c:
        fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")
    body = get_body()
    reason = require_str(body, "denial_reason")
    if c["status"] not in ("SUBMITTED", "PENDED"):
        fail(errors.ERR_INVALID_STATE, "Claim is not SUBMITTED or PENDED")
    c["denial_reason"] = reason
    c["status"] = "DENIED"
    touch(c)
    return ok(serializers.claim(c))


# --------------------------------------------------------------------- adjudicate
@bp.post("/claims/<cid>/adjudicate")
def adjudicate_claim(cid):
    user_id, _ = require_auth({"ClaimsExaminer"})
    c = db.claims.get(cid)
    if not c:
        fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")

    # (4) state
    if c["status"] not in ("SUBMITTED", "PENDED", "REVERSED"):
        fail(errors.ERR_INVALID_STATE, "Claim cannot be adjudicated from its current state")
    # (6) segregation of duties (only from PENDED)
    if c["status"] == "PENDED" and user_id == c["pended_by_user_id"]:
        fail(errors.ERR_SEGREGATION_OF_DUTIES, "Adjudicating examiner pended this claim")
    # (6) duplicate
    for other in db.claims.values():
        if other["id"] == c["id"]:
            continue
        if other["status"] in ("ADJUDICATED", "PAID") and (
            other["member_id"] == c["member_id"]
            and other["provider_id"] == c["provider_id"]
            and other["service_date"] == c["service_date"]
            and other["billed_total_cents"] == c["billed_total_cents"]
        ):
            fail(errors.ERR_DUPLICATE_CLAIM, "Duplicate adjudicated/paid claim exists")

    member = db.members[c["member_id"]]
    plan = db.plans[member["plan_id"]]
    sd = parse_dt(c["service_date"])

    # (9) eligibility
    eligible = member["status"] == "ACTIVE"
    if eligible:
        if sd < parse_dt(member["coverage_effective_date"]):
            eligible = False
        elif member["coverage_term_date"] is not None and sd > parse_dt(member["coverage_term_date"]):
            eligible = False
    if not eligible:
        fail(errors.ERR_MEMBER_NOT_ELIGIBLE, "Member not eligible for the service date")

    # (9) run-out (only when plan TERMINATED)
    if plan["status"] == "TERMINATED":
        term = parse_dt(plan["terminated_at"])
        deadline = add_days(term, plan["run_out_days"])
        if not (sd <= term and now_dt() <= deadline):
            fail(errors.ERR_RUN_OUT_CLOSED, "Plan run-out window is closed for this claim")

    _run_adjudication(c, member, plan)
    return ok(serializers.claim(c))


def _run_adjudication(c, member, plan):
    provider = db.providers[c["provider_id"]]

    # --- repricing ---
    if provider["in_network"]:
        allowed = sum(
            round_half_up_cents(line["billed_cents"], 1 - provider["ppo_discount_pct"])
            for line in c["billed_lines"]
        )
    else:
        if c["ucr_amount_cents"] is None:
            allowed = c["billed_total_cents"]
        else:
            allowed = min(c["billed_total_cents"], c["ucr_amount_cents"])

    # --- member cost-share waterfall (pre-claim accumulators) ---
    D = plan["individual_deductible_cents"]
    OOP = plan["oop_max_cents"]
    CO = plan["plan_coinsurance_pct"]
    ded_remaining = max(0, D - member["deductible_met_cents"])
    deductible_applied = min(allowed, ded_remaining)
    after_deductible = allowed - deductible_applied
    member_coinsurance = round_half_up_cents(after_deductible, 1 - CO)
    resp_uncapped = deductible_applied + member_coinsurance
    oop_remaining = max(0, OOP - member["oop_met_cents"])
    member_responsibility = min(resp_uncapped, oop_remaining)
    plan_paid = allowed - member_responsibility

    c["allowed_amount_cents"] = allowed
    c["deductible_applied_cents"] = deductible_applied
    c["member_coinsurance_cents"] = member_coinsurance
    c["member_responsibility_cents"] = member_responsibility
    c["plan_paid_cents"] = plan_paid
    c["status"] = "ADJUDICATED"

    # --- accumulators ---
    member["deductible_met_cents"] += deductible_applied
    member["oop_met_cents"] += member_responsibility
    member["member_plan_paid_ytd_cents"] += plan_paid
    touch(member)

    # reset per-cycle specific bookkeeping
    c["_spec_reimb_amount"] = 0
    c["_spec_reimb_policy_id"] = None

    # --- specific stop-loss cascade ---
    _specific_stop_loss(c, member, plan)

    touch(c)


def _specific_stop_loss(c, member, plan):
    sd = parse_dt(c["service_date"])
    # governing ACTIVE policy: half-open [effective, expiry) contains service_date
    candidates = []
    for pol in db.policies.values():
        if pol["plan_id"] != plan["id"] or pol["status"] != "ACTIVE":
            continue
        if parse_dt(pol["effective_date"]) <= sd < parse_dt(pol["expiry_date"]):
            candidates.append(pol)
    if not candidates:
        return
    candidates.sort(key=lambda p: (p["_created_dt"], p["_seq"]))
    pol = candidates[0]

    # applicable laser: closed [effective, expiry] contains service_date
    lasers = []
    for l in db.lasers.values():
        if l["stop_loss_policy_id"] != pol["id"] or l["member_id"] != member["id"]:
            continue
        if parse_dt(l["effective_date"]) <= sd <= parse_dt(l["expiry_date"]):
            lasers.append(l)
    lasers.sort(key=lambda l: (l["_created_dt"], l["_seq"]))
    spec_ded = lasers[0]["laser_deductible_cents"] if lasers else pol["specific_deductible_cents"]

    eligible_excess = max(0, member["member_plan_paid_ytd_cents"] - spec_ded)
    new_reimbursement = eligible_excess - member["spec_reimbursed_cents"]
    if new_reimbursement > 0:
        r = {
            "id": new_id(),
            "stop_loss_policy_id": pol["id"],
            "claim_id": c["id"],
            "member_id": member["id"],
            "reimbursement_type": "SPECIFIC",
            "amount_cents": new_reimbursement,
            "basis_note": None,
        }
        stamp_new(r)
        db.reimbursements[r["id"]] = r
        member["spec_reimbursed_cents"] += new_reimbursement
        pol["total_specific_reimbursed_cents"] += new_reimbursement
        touch(pol)
        c["_spec_reimb_amount"] = new_reimbursement
        c["_spec_reimb_policy_id"] = pol["id"]


# --------------------------------------------------------------------- reverse
@bp.post("/claims/<cid>/reverse")
def reverse_claim(cid):
    require_auth({"ClaimsExaminer"})
    c = db.claims.get(cid)
    if not c:
        fail(errors.ERR_CLAIM_NOT_FOUND, "Claim not found")
    if c["status"] != "ADJUDICATED":
        fail(errors.ERR_INVALID_STATE, "Only an ADJUDICATED claim may be reversed")

    member = db.members[c["member_id"]]
    member["deductible_met_cents"] -= c["deductible_applied_cents"]
    member["oop_met_cents"] -= c["member_responsibility_cents"]
    member["member_plan_paid_ytd_cents"] -= c["plan_paid_cents"]

    if c["_spec_reimb_amount"] and c["_spec_reimb_policy_id"]:
        amount = c["_spec_reimb_amount"]
        member["spec_reimbursed_cents"] -= amount
        pol = db.policies.get(c["_spec_reimb_policy_id"])
        if pol:
            pol["total_specific_reimbursed_cents"] -= amount
            touch(pol)
        c["_spec_reimb_amount"] = 0
        c["_spec_reimb_policy_id"] = None
    touch(member)

    c["status"] = "REVERSED"
    touch(c)
    return ok(serializers.claim(c))
