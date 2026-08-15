"""Beneficiary designation and survivor claim endpoints."""

from datetime import timedelta

from flask import Blueprint

from db import store, make_entity, touch, public, now, fmt_dt
from errors import (
    err_not_found,
    err_invalid_request,
    err_invalid_state,
    err_member_deceased,
    err_forbidden,
    err_benefit_not_terminated,
    err_designation_revoked,
    err_no_survivor_entitlement,
    err_claim_deadline_passed,
)
from middleware import (
    auth,
    require_roles,
    body,
    req_field,
    as_str,
    as_enum,
    check_member_path,
    check_member_resource,
)
from response import ok
from services import calcs
from utils import parse_date

bp = Blueprint("beneficiaries", __name__)

OUTCOMES = {"APPROVE", "DENY"}


def get_beneficiary(beneficiary_id):
    ben = store.beneficiaries.get(beneficiary_id)
    if ben is None:
        raise err_not_found("Beneficiary designation not found")
    return ben


def _latest_benefit(member_id):
    benefits = calcs.member_benefits(member_id)
    return benefits[-1] if benefits else None


@bp.post("/members/<member_id>/beneficiaries")
def create_beneficiary(member_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    check_member_path(ctx, member_id)
    member = store.members.get(member_id)
    if member is None:
        raise err_not_found("Member not found")
    # Beneficiary management exists while the member lives; designations
    # freeze at death.
    if member["status"] == "DECEASED":
        raise err_member_deceased()
    data = body()
    full_name = as_str(req_field(data, "full_name"), "full_name")
    relationship = as_str(req_field(data, "relationship"), "relationship")
    dob = parse_date(req_field(data, "date_of_birth"))
    if dob is None:
        raise err_invalid_request("date_of_birth must be an ISO date")
    ben = make_entity(
        {
            "member_id": member_id,
            "full_name": full_name,
            "relationship": relationship,
            "date_of_birth": dob.isoformat(),
            "status": "DESIGNATED",
            "claim_filed_at": None,
            "survivor_monthly_cents": None,
        }
    )
    store.beneficiaries[ben["id"]] = ben
    return ok(public(ben), 201)


@bp.post("/beneficiaries/<beneficiary_id>/revoke")
def revoke_beneficiary(beneficiary_id):
    ctx = auth()
    require_roles(ctx, {"Member", "MemberServicesAnalyst"})
    ben = get_beneficiary(beneficiary_id)
    check_member_resource(ctx, ben["member_id"])
    member = store.members.get(ben["member_id"])
    if member is not None and member["status"] == "DECEASED":
        raise err_member_deceased("Designations freeze at the member's death")
    if ben["status"] != "DESIGNATED":
        raise err_invalid_state("Only a DESIGNATED beneficiary can be revoked")
    ben["status"] = "REVOKED"
    touch(ben)
    return ok(public(ben))


@bp.post("/beneficiaries/<beneficiary_id>/file-claim")
def file_claim(beneficiary_id):
    ctx = auth()
    require_roles(ctx, {"SurvivorClaimant", "MemberServicesAnalyst"})
    # Claimant identity is entity-backed: X-User-ID must equal the designation id.
    if ctx.role == "SurvivorClaimant" and ctx.user_id != beneficiary_id:
        raise err_forbidden("Claimant may file only on their own designation")
    ben = get_beneficiary(beneficiary_id)
    member = store.members.get(ben["member_id"])

    # Generic state gate (priority 4): only DESIGNATED can move forward;
    # REVOKED carries its own referential error at priority 6.
    if ben["status"] in ("CLAIM_FILED", "PAYABLE", "DENIED"):
        raise err_invalid_state("A claim has already been filed on this designation")

    # Resource-specific status gate (priority 4.2): the member's benefit must
    # be TERMINATED.
    benefit = _latest_benefit(ben["member_id"])
    if benefit is None or benefit["status"] != "TERMINATED":
        raise err_benefit_not_terminated()

    # Referential rules (priority 6).
    if ben["status"] == "REVOKED":
        raise err_designation_revoked()
    origin_option = benefit.get("_origin_option")
    if origin_option not in ("JOINT_50", "JOINT_100"):
        raise err_no_survivor_entitlement()

    # Temporal window (priority 7): within 365 days of the member's death,
    # inclusive at the final day.
    deceased = parse_date(member["deceased_at"]) if member and member["deceased_at"] else None
    if deceased is None or now().date() > deceased + timedelta(days=calcs.CLAIM_WINDOW_DAYS):
        raise err_claim_deadline_passed()

    ben["status"] = "CLAIM_FILED"
    ben["claim_filed_at"] = fmt_dt(now())
    touch(ben)
    return ok(public(ben))


@bp.post("/beneficiaries/<beneficiary_id>/approve")
def adjudicate_claim(beneficiary_id):
    ctx = auth()
    require_roles(ctx, {"BenefitApprover"})
    ben = get_beneficiary(beneficiary_id)
    data = body()
    outcome = as_enum(req_field(data, "outcome"), "outcome", OUTCOMES)
    if ben["status"] != "CLAIM_FILED":
        raise err_invalid_state("Only a CLAIM_FILED designation can be adjudicated")
    if outcome == "APPROVE":
        benefit = _latest_benefit(ben["member_id"])
        if benefit is None or benefit["status"] != "TERMINATED":
            raise err_benefit_not_terminated()
        ben["survivor_monthly_cents"] = calcs.survivor_monthly_cents(benefit)
        ben["status"] = "PAYABLE"
    else:
        ben["status"] = "DENIED"
    touch(ben)
    return ok(public(ben))
