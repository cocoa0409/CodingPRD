"""LandlordPartner and HousingReferral endpoints."""

from flask import Blueprint

from db import clock_date, db, public, touch
from errors import ApiError
from middleware import (ROLE_AGENCY_ADMIN, ROLE_HOUSING_SPECIALIST, acting_staff_id, auth)
from response import created, ok
from routes.common import (by_created, filtered, get_client, get_partner, get_referral,
                           insert, list_page)
from services import calc, derive
from validation import (date_out, get_body, q_enum, q_str, req_date, req_enum, req_int,
                        req_str)

bp = Blueprint("housing", __name__)

SUBSIDY_TYPES = ("HOUSING_CHOICE_VOUCHER", "RAPID_REHOUSING_SUBSIDY", "NONE")
PROGRAM_TYPES = ("TRANSITIONAL_HOUSING", "RAPID_REHOUSING")
REFERRAL_STATUSES = ("SUBMITTED", "MATCHED", "REJECTED", "LEASED")
PARTNER_ROLES = (ROLE_HOUSING_SPECIALIST, ROLE_AGENCY_ADMIN)


def _active_plans(client_id):
    return derive.where("safety_plans", client_id=client_id, status="ACTIVE")


def _require_active_plan(client_id):
    if len(_active_plans(client_id)) != 1:
        raise ApiError("ERR_NO_ACTIVE_SAFETY_PLAN")


@bp.post("/landlord-partners")
def create_partner():
    auth(PARTNER_ROLES)
    body = get_body()
    name = req_str(body, "name", 1, 120)
    units_pledged = req_int(body, "units_pledged", 1, 50)
    accepts = req_enum(body, "accepts_subsidy_type", SUBSIDY_TYPES)
    base_incentive = req_int(body, "base_incentive_cents", 0, 500000)

    partner = insert("landlord_partners", {
        "name": name,
        "units_pledged": units_pledged,
        "accepts_subsidy_type": accepts,
        "base_incentive_cents": base_incentive,
        "units_committed": 0,
        "units_available": units_pledged,
        "engagement_score": 0.0,
        "incentive_tier": "BASE",
        "incentive_accrued_cents": 0,
    })
    return created(public(partner))


@bp.get("/landlord-partners/<partner_id>")
def read_partner(partner_id):
    auth(PARTNER_ROLES)
    return ok(public(get_partner(partner_id)))


@bp.post("/housing-referrals")
def create_referral():
    user_id, role = auth((ROLE_HOUSING_SPECIALIST,))
    body = get_body()
    client_id = req_str(body, "client_id")
    partner_id = req_str(body, "landlord_partner_id")
    program_type = req_enum(body, "program_type", PROGRAM_TYPES)
    subsidy_type = req_enum(body, "subsidy_type", SUBSIDY_TYPES)
    client = get_client(client_id)
    partner = get_partner(partner_id)

    _require_active_plan(client["id"])
    if subsidy_type != partner["accepts_subsidy_type"]:
        raise ApiError("ERR_SUBSIDY_TYPE_MISMATCH")

    referral = insert("housing_referrals", {
        "client_id": client["id"],
        "landlord_partner_id": partner["id"],
        "created_by_staff_id": acting_staff_id(user_id, role),
        "program_type": program_type,
        "subsidy_type": subsidy_type,
        "status": "SUBMITTED",
        "monthly_rent_cents": None,
        "incentive_fee_cents": None,
        "incentive_tier_applied": None,
        "rejection_reason": None,
        "lease_start_date": None,
        "withdraw_count": 0,
    })
    return created(public(referral))


@bp.get("/housing-referrals/<referral_id>")
def read_referral(referral_id):
    auth(PARTNER_ROLES)
    return ok(public(get_referral(referral_id)))


@bp.get("/housing-referrals")
def list_referrals():
    auth(PARTNER_ROLES)
    filters = {
        "client_id": q_str("client_id"),
        "landlord_partner_id": q_str("landlord_partner_id"),
        "created_by_staff_id": q_str("created_by_staff_id"),
        "status": q_enum("status", REFERRAL_STATUSES),
    }
    return list_page(by_created(filtered("housing_referrals", filters)))


@bp.post("/housing-referrals/<referral_id>/match")
def match_referral(referral_id):
    auth((ROLE_HOUSING_SPECIALIST,))
    body = get_body()
    monthly_rent_cents = req_int(body, "monthly_rent_cents", 0, 100000000)
    expected_version = req_int(body, "expected_landlord_partner_version", 0)
    referral = get_referral(referral_id)
    partner = db.landlord_partners.get(referral["landlord_partner_id"])
    client = db.clients.get(referral["client_id"])

    if partner is None:
        raise ApiError("ERR_LANDLORD_PARTNER_NOT_FOUND")
    if expected_version != partner["version"]:
        raise ApiError("ERR_STALE_LANDLORD_VERSION")

    if referral["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a SUBMITTED referral may be matched")

    if client is not None and client["confidentiality_posture"] == "SEALED":
        raise ApiError("ERR_CONFIDENTIALITY_HOLD")

    _require_active_plan(referral["client_id"])

    if referral["subsidy_type"] != partner["accepts_subsidy_type"]:
        raise ApiError("ERR_SUBSIDY_TYPE_MISMATCH")

    if partner["units_available"] < 1:
        raise ApiError("ERR_LANDLORD_NO_UNITS_AVAILABLE")

    # the tier is read from the PRE-COMMITMENT engagement score
    pre_score = calc.engagement_score_of(partner["units_committed"],
                                         partner["units_pledged"])
    tier = calc.incentive_tier_of(pre_score)
    fee = calc.incentive_fee(partner["base_incentive_cents"], tier,
                             referral["program_type"])

    referral["status"] = "MATCHED"
    referral["monthly_rent_cents"] = monthly_rent_cents
    referral["incentive_fee_cents"] = fee
    referral["incentive_tier_applied"] = tier
    touch(referral)

    # only now is the commitment counted
    derive.recompute_partner(partner)
    return ok(public(referral))


@bp.post("/housing-referrals/<referral_id>/withdraw-match")
def withdraw_match(referral_id):
    auth((ROLE_HOUSING_SPECIALIST,))
    body = get_body()
    req_str(body, "withdraw_reason", 1, 2000)
    referral = get_referral(referral_id)

    if referral["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a MATCHED referral may have its match withdrawn")

    referral["status"] = "SUBMITTED"
    referral["withdraw_count"] = referral["withdraw_count"] + 1
    referral["incentive_fee_cents"] = None
    referral["incentive_tier_applied"] = None
    touch(referral)

    derive.recompute_partner(db.landlord_partners.get(referral["landlord_partner_id"]))
    return ok(public(referral))


@bp.post("/housing-referrals/<referral_id>/lease")
def lease_referral(referral_id):
    auth((ROLE_HOUSING_SPECIALIST,))
    body = get_body()
    lease_start_date = req_date(body, "lease_start_date")
    referral = get_referral(referral_id)

    if referral["status"] != "MATCHED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION",
                       "only a MATCHED referral may be leased")
    if lease_start_date < clock_date():
        raise ApiError("ERR_INVALID_DATE_WINDOW",
                       "lease_start_date may not precede the logical clock date")

    referral["status"] = "LEASED"
    referral["lease_start_date"] = date_out(lease_start_date)
    touch(referral)

    client = db.clients.get(referral["client_id"])
    if client is not None:
        client["status"] = "EXITED"
        touch(client)
    return ok(public(referral))
