"""Loss-of-use claims for non-owned vehicles."""
from flask import Blueprint, request

import db
from errors import api_error, bad_request
from middleware import ALL_ROLES, require_roles
from response import ok
from services import (bump, check_body_fk, get_claim, new_entity, need_date,
                      need_enum, need_int, need_str, opt_str,
                      require_claim_open, sorted_by_creation, view)

bp = Blueprint("lou", __name__)

RESERVATION_CONFLICT_STATUSES = ("DRAFT", "AUTHORIZED", "ACTIVE", "EXTENSION_REVIEW", "RETURNED")


def body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def get_lou(lou_id):
    lou = db.lou_claims.get(lou_id)
    if lou is None:
        raise api_error("ERR_LOSS_OF_USE_CLAIM_NOT_FOUND", 404,
                        "loss-of-use claim not found: %s" % lou_id)
    return lou


@bp.post("/loss-of-use-claims")
def create_lou():
    caller = require_roles(["Customer"])
    b = body()
    # rung 4: body FK existence
    check_body_fk(b, "claim_id", db.claims, "ERR_CLAIM_NOT_FOUND")
    # shape
    claim_id = b.get("claim_id")
    if not isinstance(claim_id, str) or not claim_id:
        raise bad_request("claim_id is required")
    vehicle_description = need_str(b, "vehicle_description")
    period_start = need_date(b, "period_start")
    period_end = need_date(b, "period_end")
    claimed_amount = need_int(b, "claimed_amount_cents")
    if claimed_amount <= 0:
        raise bad_request("claimed_amount_cents must be greater than zero")
    payout_method = need_enum(b, "payout_method", ("STANDARD_PER_DIEM", "COMPARABLE_VEHICLE"))
    claim = get_claim(claim_id)
    # rung 5: the claimant must own the claim
    if claim["policyholder_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403, "caller does not own this claim")
    # rung 6
    require_claim_open(claim)
    # rung 10: closed interval — end on or after start
    if period_end < period_start:
        raise api_error("ERR_INVALID_PERIOD", 400,
                        "period_end must be on or after period_start")
    # rung 11: latest non-SUPERSEDED verification must be VERIFIED with loss_of_use_eligible
    verifications = sorted_by_creation(
        [v for v in db.verifications.values()
         if v["claim_id"] == claim_id and v["status"] != "SUPERSEDED"])
    latest = verifications[-1] if verifications else None
    if latest is None or latest["status"] != "VERIFIED" or latest["loss_of_use_eligible"] is not True:
        raise api_error("ERR_LOU_NOT_ELIGIBLE", 409,
                        "latest verification is not VERIFIED with loss_of_use_eligible")
    # rung 12: closed-interval conflict with any live reservation window (closed both ends)
    for r in db.reservations.values():
        if r["claim_id"] != claim_id:
            continue
        if r["status"] not in RESERVATION_CONFLICT_STATUSES:
            continue
        if period_start <= r["authorized_return_date"] and r["pickup_date"] <= period_end:
            raise api_error("ERR_LOU_PERIOD_CONFLICT", 409,
                            "loss-of-use period conflicts with a reservation on the claim")
    e = new_entity()
    e.update({
        "claim_id": claim_id,
        "vehicle_description": vehicle_description,
        "period_start": period_start,
        "period_end": period_end,
        "claimed_amount_cents": claimed_amount,
        "payout_method": payout_method,
        "documentation_provided": False,
        "payout_cents": None,
        "status": "SUBMITTED",
    })
    db.lou_claims[e["id"]] = e
    claim["loss_of_use_track_status"] = "LOU_SUBMITTED"
    bump(claim)
    return ok(view(e), status=201)


@bp.get("/loss-of-use-claims/<lid>")
def get_one_lou(lid):
    require_roles(ALL_ROLES)
    return ok(view(get_lou(lid)))


@bp.post("/loss-of-use-claims/<lid>/attach-documentation")
def attach_documentation(lid):
    caller = require_roles(["Customer"])
    lou = get_lou(lid)
    claim = get_claim(lou["claim_id"])
    # rung 5
    if claim["policyholder_id"] != caller.id:
        raise api_error("ERR_NOT_RESOURCE_OWNER", 403, "caller does not own this claim")
    # rung 6
    require_claim_open(claim)
    # rung 8
    if lou["status"] != "SUBMITTED":
        raise api_error("ERR_LOU_INVALID_STATE", 409,
                        "documentation can only be attached to a SUBMITTED loss-of-use claim")
    lou["status"] = "DOCUMENTED"
    lou["documentation_provided"] = True
    bump(lou)
    claim["loss_of_use_track_status"] = "LOU_DOCUMENTED"
    bump(claim)
    return ok(view(lou))


@bp.post("/loss-of-use-claims/<lid>/approve")
def approve_lou(lid):
    require_roles(["ClaimsAdjuster"])
    lou = get_lou(lid)
    claim = get_claim(lou["claim_id"])
    require_claim_open(claim)
    if lou["status"] not in ("SUBMITTED", "DOCUMENTED"):
        raise api_error("ERR_LOU_INVALID_STATE", 409,
                        "only a SUBMITTED or DOCUMENTED loss-of-use claim can be approved")
    if lou["payout_method"] == "COMPARABLE_VEHICLE" and not lou["documentation_provided"]:
        raise api_error("ERR_DOCUMENTATION_REQUIRED", 409,
                        "COMPARABLE_VEHICLE payout requires documentation")
    # loss_of_use_payout: closed-interval day count, capped at the duration cap
    reasonable_days = (lou["period_end"] - lou["period_start"]).days + 1
    billable_days = min(reasonable_days, claim["coverage_duration_cap_days"])
    if lou["payout_method"] == "STANDARD_PER_DIEM":
        payout = claim["loss_of_use_per_diem_cents"] * billable_days
    else:
        payout = min(lou["claimed_amount_cents"],
                     claim["coverage_daily_limit_cents"] * billable_days)
    lou["payout_cents"] = payout
    lou["status"] = "APPROVED"
    bump(lou)
    claim["loss_of_use_track_status"] = "LOU_APPROVED"
    bump(claim)
    return ok(view(lou))


@bp.post("/loss-of-use-claims/<lid>/deny")
def deny_lou(lid):
    require_roles(["ClaimsAdjuster"])
    lou = get_lou(lid)
    claim = get_claim(lou["claim_id"])
    require_claim_open(claim)
    b = body()
    opt_str(b, "decision_reason")  # accepted input; the entity schema has no such field
    if lou["status"] not in ("SUBMITTED", "DOCUMENTED"):
        raise api_error("ERR_LOU_INVALID_STATE", 409,
                        "only a SUBMITTED or DOCUMENTED loss-of-use claim can be denied")
    lou["status"] = "DENIED"
    bump(lou)
    claim["loss_of_use_track_status"] = "LOU_DENIED"
    bump(claim)
    return ok(view(lou))


@bp.post("/loss-of-use-claims/<lid>/pay")
def pay_lou(lid):
    require_roles(["SettlementApprover"])
    lou = get_lou(lid)
    claim = get_claim(lou["claim_id"])
    # rung 6
    require_claim_open(claim)
    # rung 8
    if lou["status"] != "APPROVED":
        raise api_error("ERR_LOU_INVALID_STATE", 409,
                        "only an APPROVED loss-of-use claim can be paid")
    lou["status"] = "PAID"
    bump(lou)
    claim["loss_of_use_track_status"] = "LOU_PAID"
    bump(claim)
    return ok(view(lou))
