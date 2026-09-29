"""MemberBank and StockSubscription endpoints."""

from flask import g

import config
import services as svc
from envelope import list_response, object_response
from errors import ApiError
from routing import endpoint, get_member, get_subscription
from store import db, touch
from validation import (
    get_body,
    q_enum,
    q_pagination,
    q_str,
    v_bool,
    v_datetime,
    v_enum,
    v_int,
    v_string,
)

ALL = list(config.ALL_ROLES)


# ------------------------------------------------------------- member banks --


@endpoint("/fhlb/member-banks", ["POST"], [config.ROLE_SYSTEM_ADMIN])
def create_member_bank():
    body = get_body()
    name = v_string(body, "name")
    charter_type = v_enum(body, "charter_type", config.CHARTER_TYPES)
    total_assets_cents = v_int(body, "total_assets_cents", minimum=100_000_000)
    credit_rating_tier = v_int(body, "credit_rating_tier", required=False, default=2,
                               minimum=1, maximum=4)
    cdfi_certified = v_bool(body, "cdfi_certified", required=False, default=False)
    member = svc.create_member(name, charter_type, total_assets_cents,
                               credit_rating_tier, cdfi_certified)
    return object_response(svc.serialize_member(member), 201)


@endpoint("/fhlb/member-banks/<member_bank_id>", ["GET"], ALL)
def get_member_bank(member_bank_id):
    member = get_member(member_bank_id)
    svc.require_own_member(member["id"])
    return object_response(svc.serialize_member(member))


@endpoint("/fhlb/member-banks/<member_bank_id>/borrowing-capacity", ["GET"],
          [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
           config.ROLE_TREASURY_OFFICER, config.ROLE_COLLATERAL_REVIEW_AUDITOR,
           config.ROLE_COMMUNITY_LENDING_MANAGER])
def read_borrowing_capacity(member_bank_id):
    variant = q_enum("variant", config.CAPACITY_VARIANTS) or "CERTIFIED"
    member = get_member(member_bank_id)
    svc.require_own_member(member["id"])
    return object_response(svc.capacity_breakdown(member, variant))


@endpoint("/fhlb/member-banks/<member_bank_id>/activate", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def activate_member_bank(member_bank_id):
    get_body()
    member = get_member(member_bank_id)
    if member["membership_status"] != "APPLICANT":
        raise ApiError("ERR_INVALID_STATE")
    svc.derive_pure(member)
    if member["stock_held_cents"] < member["required_membership_stock_cents"]:
        raise ApiError("ERR_MEMBERSHIP_STOCK_DEFICIENT")
    member["membership_status"] = "ACTIVE"
    svc.refresh_member_assets(member)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize_member(member))


_CONDITION_TRANSITIONS = {
    ("ACTIVE", "PROBATION"),
    ("PROBATION", "ACTIVE"),
    ("ACTIVE", "SUSPENDED"),
    ("PROBATION", "SUSPENDED"),
    ("SUSPENDED", "TERMINATED"),
}


@endpoint("/fhlb/member-banks/<member_bank_id>/condition", ["PATCH"],
          [config.ROLE_CREDIT_OFFICER])
def amend_member_condition(member_bank_id):
    body = get_body()
    membership_status = v_enum(body, "membership_status", config.MEMBERSHIP_STATUSES,
                              required=False)
    credit_rating_tier = v_int(body, "credit_rating_tier", required=False,
                               minimum=1, maximum=4)
    member = get_member(member_bank_id)
    svc.derive_pure(member)
    if membership_status is not None:
        current = member["membership_status"]
        if (current, membership_status) not in _CONDITION_TRANSITIONS:
            raise ApiError("ERR_INVALID_STATE")
        if (current, membership_status) == ("PROBATION", "ACTIVE") \
                and member["shortfall_status"] == "ESCALATED":
            raise ApiError("ERR_INVALID_STATE")
        if (current, membership_status) == ("SUSPENDED", "TERMINATED") \
                and member["total_outstanding_advances_cents"] != 0:
            raise ApiError("ERR_INVALID_STATE")
        member["membership_status"] = membership_status
        if membership_status == "TERMINATED":
            for sub in svc.member_subscriptions(member["id"]):
                if sub["status"] in ("ISSUED", "REDEMPTION_REQUESTED"):
                    sub["status"] = "REPURCHASED"
                    sub["repurchased_at"] = db.now_iso()
                    touch(sub)
    if credit_rating_tier is not None:
        member["credit_rating_tier"] = credit_rating_tier
    svc.derive_pure(member)
    svc.refresh_member_assets(member)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize_member(member))


@endpoint("/fhlb/member-banks/<member_bank_id>/pledge-agreement", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def execute_pledge_agreement(member_bank_id):
    body = get_body()
    pledge_mode = v_enum(body, "pledge_mode", config.PLEDGE_AGREEMENT_MODES)
    effective_date = v_datetime(body, "effective_date")
    member = get_member(member_bank_id)
    member["pledge_mode"] = pledge_mode
    member["pledge_agreement_status"] = "EXECUTED"
    member["pledge_agreement_effective_date"] = effective_date
    svc.derive_pure(member)
    svc.refresh_member_assets(member)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize_member(member))


@endpoint("/fhlb/member-banks/<member_bank_id>/escalate-shortfall", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def escalate_shortfall(member_bank_id):
    get_body()
    member = get_member(member_bank_id)
    if member["shortfall_status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE")
    deadline = member.get("shortfall_cure_deadline")
    if deadline is not None:
        from store import parse_dt
        if db.now() <= parse_dt(deadline):
            raise ApiError("ERR_SHORTFALL_CURE_PERIOD_ACTIVE")
    member["shortfall_status"] = "ESCALATED"
    if member["membership_status"] == "ACTIVE":
        member["membership_status"] = "PROBATION"
    member["collateral_posture"] = "FROZEN"
    svc.derive_pure(member)
    svc.refresh_member_assets(member)
    svc.derive_pure(member)
    svc.bump_member(member)
    return object_response(svc.serialize_member(member))


# ------------------------------------------------------- stock subscriptions --


@endpoint("/fhlb/stock-subscriptions", ["POST"],
          [config.ROLE_TREASURY_OFFICER, config.ROLE_CREDIT_OFFICER])
def create_stock_subscription():
    body = get_body()
    member_bank_id = v_string(body, "member_bank_id")
    subscription_type = v_enum(body, "subscription_type", config.SUBSCRIPTION_TYPES)
    amount_cents = v_int(body, "amount_cents", minimum=1)
    if amount_cents % config.STOCK_PAR_VALUE_CENTS != 0:
        raise ApiError("ERR_STOCK_NOT_PAR_MULTIPLE")
    member = get_member(member_bank_id)
    svc.require_own_member(member["id"])
    sub = svc.create_subscription(member["id"], subscription_type, amount_cents)
    return object_response(svc.serialize(sub), 201)


_SUB_READ_ROLES = [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                   config.ROLE_TREASURY_OFFICER, config.ROLE_COLLATERAL_REVIEW_AUDITOR]


@endpoint("/fhlb/stock-subscriptions", ["GET"], _SUB_READ_ROLES)
def list_stock_subscriptions():
    limit, offset = q_pagination()
    member_bank_id = q_str("member_bank_id")
    advance_id = q_str("advance_id")
    subscription_type = q_enum("subscription_type", config.SUBSCRIPTION_TYPES)
    status = q_enum("status", config.SUBSCRIPTION_STATUSES)
    if svc.is_treasury():
        member_bank_id = g.user_id if member_bank_id in (None, g.user_id) else "\0"
    records = []
    for sub in db.subscriptions.values():
        if member_bank_id is not None and sub["member_bank_id"] != member_bank_id:
            continue
        if advance_id is not None and sub["advance_id"] != advance_id:
            continue
        if subscription_type is not None and sub["subscription_type"] != subscription_type:
            continue
        if status is not None and sub["status"] != status:
            continue
        records.append(sub)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/stock-subscriptions/<stock_subscription_id>", ["GET"], _SUB_READ_ROLES)
def read_stock_subscription(stock_subscription_id):
    sub = get_subscription(stock_subscription_id)
    svc.require_own_member(sub["member_bank_id"])
    return object_response(svc.serialize(sub))


@endpoint("/fhlb/stock-subscriptions/<stock_subscription_id>/issue", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def issue_stock_subscription(stock_subscription_id):
    get_body()
    sub = get_subscription(stock_subscription_id)
    member = get_member(sub["member_bank_id"])
    if sub["status"] != "SUBSCRIBED" or member["membership_status"] == "TERMINATED":
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = "ISSUED"
    touch(sub)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(sub))


@endpoint("/fhlb/stock-subscriptions/<stock_subscription_id>/request-redemption",
          ["POST"], [config.ROLE_TREASURY_OFFICER])
def request_stock_redemption(stock_subscription_id):
    get_body()
    sub = get_subscription(stock_subscription_id)
    svc.require_own_member(sub["member_bank_id"])
    member = get_member(sub["member_bank_id"])
    if sub["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE")
    svc.derive_pure(member)
    if member["stock_held_cents"] - sub["amount_cents"] < member["required_total_stock_cents"]:
        raise ApiError("ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT")
    sub["status"] = "REDEMPTION_REQUESTED"
    sub["redemption_requested_at"] = db.now_iso()
    touch(sub)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(sub))


@endpoint("/fhlb/stock-subscriptions/<stock_subscription_id>/repurchase", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def repurchase_stock_subscription(stock_subscription_id):
    get_body()
    sub = get_subscription(stock_subscription_id)
    member = get_member(sub["member_bank_id"])
    if sub["status"] != "REDEMPTION_REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    svc.derive_pure(member)
    if member["stock_held_cents"] - sub["amount_cents"] < member["required_total_stock_cents"]:
        raise ApiError("ERR_STOCK_REDEMPTION_WOULD_BREACH_REQUIREMENT")
    sub["status"] = "REPURCHASED"
    sub["repurchased_at"] = db.now_iso()
    touch(sub)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(sub))
