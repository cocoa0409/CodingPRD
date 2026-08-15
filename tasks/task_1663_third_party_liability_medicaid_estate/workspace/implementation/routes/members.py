"""Member endpoints (PRD §3.1, §3.6)."""

from flask import Blueprint

from db import ESTATE_CASES, MEMBERS, new_entity, pub, touch
from errors import ApiError, ERR_ESTATE_CASE_EXISTS, ERR_NOT_FOUND
from middleware import ALL_ROLES, require_roles
from response import success_object
from util import body, req_date, req_int, req_str

bp = Blueprint("members", __name__)


@bp.post("/recovery/members")
@require_roles("SystemAdmin")
def create_member():
    b = body()
    medicaid_id = req_str(b, "medicaid_id")
    full_name = req_str(b, "full_name")
    state_code = req_str(b, "state_code")
    m = new_entity()
    m.update(
        {
            "medicaid_id": medicaid_id,
            "full_name": full_name,
            "state_code": state_code,
            # §3.1: MT/WY -> SUBROGATION; every other state -> REIMBURSEMENT.
            "recovery_approach": "SUBROGATION" if state_code in ("MT", "WY") else "REIMBURSEMENT",
            "date_of_death": None,
            "status": "ACTIVE",
        }
    )
    MEMBERS[m["id"]] = m
    return success_object(pub(m), 201)


@bp.get("/recovery/members/<string:memberId>")
@require_roles(*ALL_ROLES)
def get_member(memberId):
    m = MEMBERS.get(memberId)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, "Member not found", 404)
    return success_object(pub(m))


@bp.post("/recovery/members/<string:memberId>/mark-deceased")
@require_roles("EstateRecoveryOfficer")
def mark_deceased(memberId):
    b = body()
    date_of_death = req_date(b, "date_of_death")
    lifetime_paid_cents = req_int(b, "lifetime_paid_cents", minimum=0)
    m = MEMBERS.get(memberId)
    if m is None:
        raise ApiError(ERR_NOT_FOUND, "Member not found", 404)
    # §3.6: one estate case per member; a second recording is rejected.
    for ec in ESTATE_CASES.values():
        if ec["member_id"] == memberId:
            raise ApiError(
                ERR_ESTATE_CASE_EXISTS,
                "An estate case already exists for this member",
                409,
            )
    m["status"] = "DECEASED"
    m["date_of_death"] = date_of_death
    m["lifetime_paid_cents"] = lifetime_paid_cents
    touch(m)
    # Same action opens the EstateCase (OPENED) with the provisional claim.
    ec = new_entity()
    ec.update(
        {
            "member_id": memberId,
            "date_of_death": date_of_death,
            "lifetime_paid_cents": lifetime_paid_cents,
            "probate_case_number": None,
            "exempt_services_cents": None,
            "provisional_claim_cents": lifetime_paid_cents,
            "claim_amount_cents": None,
            "claim_outstanding_cents": 0,
            "total_paid_cents": 0,
            "status": "OPENED",
        }
    )
    ESTATE_CASES[ec["id"]] = ec
    return success_object(pub(m))
