"""EstateCase endpoints (PRD §3.6): file-claim, record-payment, retrieval."""

from datetime import timedelta

from flask import Blueprint, request

from db import CASES, ESTATE_CASES, MEMBERS, WAIVERS, CLOCK, new_entity, pub, touch
from errors import (
    ApiError,
    ERR_CLAIM_NOT_FILED,
    ERR_ESTATE_FILING_LATE,
    ERR_INVALID_REQUEST,
    ERR_INVALID_STATE_TRANSITION,
    ERR_NOT_FOUND,
    ERR_PAYMENT_EXCEEDS_OUTSTANDING,
    ERR_WAIVER_PENDING_EXISTS,
)
from middleware import ALL_ROLES, require_roles
from response import success_list, success_object
from services import ESTATE_FILING_DAYS, create_notice, estate_final_claim_amount
from util import body, opt_int_positive, paginate, parse_date, req_enum, req_int, req_str

bp = Blueprint("estates", __name__)

WAIVER_TYPES = ("FULL", "PARTIAL")


@bp.get("/recovery/estate-cases/<string:estateCaseId>")
@require_roles(*ALL_ROLES)
def get_estate_case(estateCaseId):
    ec = ESTATE_CASES.get(estateCaseId)
    if ec is None:
        raise ApiError(ERR_NOT_FOUND, "Estate case not found", 404)
    return success_object(pub(ec))


@bp.get("/recovery/estate-cases")
@require_roles(*ALL_ROLES)
def list_estate_cases():
    member_id = request.args.get("member_id")
    status = request.args.get("status")
    items = []
    for ec in ESTATE_CASES.values():
        if member_id is not None and ec["member_id"] != member_id:
            continue
        if status is not None and ec["status"] != status:
            continue
        items.append(ec)
    ordered, limit, offset = paginate(items)
    page = [pub(ec) for ec in ordered[offset : offset + limit]]
    return success_list(page, limit, offset, len(ordered))


@bp.post("/recovery/estate-cases/<string:estateCaseId>/file-claim")
@require_roles("EstateRecoveryOfficer")
def file_claim(estateCaseId):
    b = body()
    probate_case_number = req_str(b, "probate_case_number")
    exempt_services_cents = req_int(b, "exempt_services_cents", minimum=0)
    ec = ESTATE_CASES.get(estateCaseId)
    if ec is None:
        raise ApiError(ERR_NOT_FOUND, "Estate case not found", 404)
    # §3.6: filing is permitted only from OPENED.
    if ec["status"] != "OPENED":
        raise ApiError(
            ERR_INVALID_STATE_TRANSITION,
            "File-claim requires the estate case to be OPENED",
            409,
        )
    # §3.6: the statute allows 365 days from the date of death (inclusive);
    # a late filing time-bars the case.
    deadline = parse_date(ec["date_of_death"]) + timedelta(days=ESTATE_FILING_DAYS)
    if CLOCK.today() > deadline:
        ec["status"] = "TIME_BARRED"
        touch(ec)
        raise ApiError(
            ERR_ESTATE_FILING_LATE,
            "The 365-day probate filing window has closed",
            409,
        )
    member = MEMBERS[ec["member_id"]]
    ec["probate_case_number"] = probate_case_number
    ec["exempt_services_cents"] = exempt_services_cents
    ec["claim_amount_cents"] = estate_final_claim_amount(member, exempt_services_cents)
    ec["claim_outstanding_cents"] = ec["claim_amount_cents"]
    ec["status"] = "CLAIM_FILED"
    # §2.11: probate claim filing queues an ESTATE_CLAIM_NOTICE.
    create_notice(ec["member_id"], None, ec["id"], "ESTATE_CLAIM_NOTICE")
    # §3.6: a final claim of exactly zero leaves nothing to collect.
    if ec["claim_amount_cents"] == 0:
        ec["status"] = "PAID"
    touch(ec)
    return success_object(pub(ec))


@bp.post("/recovery/estate-cases/<string:estateCaseId>/record-payment")
@require_roles("RecoveryAccountant")
def record_payment(estateCaseId):
    b = body()
    amount_cents = req_int(b, "amount_cents", minimum=0, exclusive_min=True)
    ec = ESTATE_CASES.get(estateCaseId)
    if ec is None:
        raise ApiError(ERR_NOT_FOUND, "Estate case not found", 404)
    # §3.6: payments are recorded only against a filed claim.
    if ec["status"] != "CLAIM_FILED":
        raise ApiError(
            ERR_CLAIM_NOT_FILED,
            "The estate case is not in CLAIM_FILED status",
            409,
        )
    if amount_cents > ec["claim_outstanding_cents"]:
        raise ApiError(
            ERR_PAYMENT_EXCEEDS_OUTSTANDING,
            "Payment exceeds the outstanding claim balance",
            409,
        )
    ec["total_paid_cents"] += amount_cents
    ec["claim_outstanding_cents"] -= amount_cents
    # §3.6: driving the outstanding balance to exactly zero pays the case.
    if ec["claim_outstanding_cents"] == 0:
        ec["status"] = "PAID"
    touch(ec)
    return success_object(pub(ec))


@bp.post("/recovery/estate-cases/<string:estateCaseId>/waivers")
@require_roles("EstateRecoveryOfficer", "RecoverySupervisor")
def create_waiver(estateCaseId):
    from flask import g

    b = body()
    waiver_type = req_enum(b, "waiver_type", WAIVER_TYPES)
    household_income = req_int(b, "household_income_annual_cents", minimum=0)
    homestead_value = req_int(b, "homestead_value_cents", minimum=0)
    # §3.7: requested_reduction_cents is required exactly when PARTIAL, and
    # must be greater than zero when present.
    if waiver_type == "PARTIAL":
        if "requested_reduction_cents" not in b or b.get("requested_reduction_cents") is None:
            raise ApiError(
                ERR_INVALID_REQUEST,
                "requested_reduction_cents is required for a PARTIAL waiver",
                400,
            )
    requested = opt_int_positive(b, "requested_reduction_cents")
    ec = ESTATE_CASES.get(estateCaseId)
    if ec is None:
        raise ApiError(ERR_NOT_FOUND, "Estate case not found", 404)
    # §3.7: a waiver application requires a filed claim.
    if ec["status"] != "CLAIM_FILED":
        raise ApiError(
            ERR_CLAIM_NOT_FILED,
            "The estate case is not in CLAIM_FILED status",
            409,
        )
    # §3.7: only one waiver may be pending at a time.
    for w in WAIVERS.values():
        if w["estate_case_id"] == estateCaseId and w["status"] == "PENDING":
            raise ApiError(
                ERR_WAIVER_PENDING_EXISTS,
                "A hardship waiver is already pending for this estate case",
                409,
            )
    w = new_entity()
    w.update(
        {
            "estate_case_id": estateCaseId,
            "waiver_type": waiver_type,
            "household_income_annual_cents": household_income,
            "homestead_value_cents": homestead_value,
            "requested_reduction_cents": requested,
            "decided_reduction_cents": None,
            "appeal_count": 0,
            "created_by_user_id": g.user_id,
            "status": "PENDING",
        }
    )
    WAIVERS[w["id"]] = w
    return success_object(pub(w), 201)
