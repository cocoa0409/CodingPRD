"""AdvanceProduct, Advance, PrepaymentEvent, allocation and admin endpoints."""

from datetime import timedelta

from flask import g

import config
import services as svc
from calc import advance_rate_bps, gross_up, pct_bps
from envelope import list_response, object_response
from errors import ApiError
from routing import (
    endpoint,
    get_advance,
    get_allocation,
    get_member,
    get_prepayment,
    get_product,
)
from store import db, fmt_dt, parse_dt, sort_records, touch
from validation import (
    get_body,
    present,
    q_enum,
    q_pagination,
    q_str,
    v_bool,
    v_datetime,
    v_enum,
    v_int,
    v_string,
)

_ADVANCE_READ_ROLES = [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                       config.ROLE_TREASURY_OFFICER, config.ROLE_COLLATERAL_REVIEW_AUDITOR,
                       config.ROLE_COMMUNITY_LENDING_MANAGER]
_PREPAY_READ_ROLES = [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                      config.ROLE_TREASURY_OFFICER]


# --------------------------------------------------------------- products ----


@endpoint("/fhlb/advance-products", ["POST"], [config.ROLE_SYSTEM_ADMIN])
def create_advance_product():
    body = get_body()
    fields = {}
    fields["product_code"] = v_string(body, "product_code")
    fields["structure"] = v_enum(body, "structure", config.PRODUCT_STRUCTURES)
    fields["min_term_days"] = v_int(body, "min_term_days", minimum=1)
    fields["max_term_days"] = v_int(body, "max_term_days", minimum=1)
    fields["rate_bps"] = v_int(body, "rate_bps", minimum=1)
    fields["prepayment_fee_method"] = v_enum(body, "prepayment_fee_method",
                                             config.PREPAYMENT_FEE_METHODS)
    fields["activity_stock_pct_bps"] = v_int(body, "activity_stock_pct_bps",
                                             minimum=0, maximum=2000)
    fields["min_principal_cents"] = v_int(body, "min_principal_cents", minimum=1)
    fields["flat_prepayment_fee_bps"] = v_int(body, "flat_prepayment_fee_bps",
                                              required=False, default=0, minimum=0)
    fields["symmetric_credit_enabled"] = v_bool(body, "symmetric_credit_enabled",
                                                required=False, default=False)
    fields["requires_collateral_delivery"] = v_bool(body, "requires_collateral_delivery",
                                                    required=False, default=False)
    fields["community_program_flag"] = v_bool(body, "community_program_flag",
                                              required=False, default=False)
    if fields["max_term_days"] < fields["min_term_days"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "max_term_days must be greater than or equal to min_term_days.")
    for existing in db.products.values():
        if existing["product_code"] == fields["product_code"]:
            raise ApiError("ERR_INVALID_REQUEST", "product_code must be unique.")
    product = svc.create_product(fields)
    return object_response(svc.serialize(product), 201)


@endpoint("/fhlb/advance-products/<advance_product_id>", ["GET"],
          [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
           config.ROLE_TREASURY_OFFICER, config.ROLE_COMMUNITY_LENDING_MANAGER])
def read_advance_product(advance_product_id):
    product = get_product(advance_product_id)
    return object_response(svc.serialize(product))


# ---------------------------------------------------------------- advances ----


@endpoint("/fhlb/advances", ["POST"], [config.ROLE_TREASURY_OFFICER])
def create_advance():
    body = get_body()
    member_bank_id = v_string(body, "member_bank_id")
    advance_product_id = v_string(body, "advance_product_id")
    term_days = v_int(body, "term_days", minimum=1)
    requested_net_proceeds_cents = v_int(body, "requested_net_proceeds_cents", minimum=1)
    expected_version = v_int(body, "expected_member_bank_version")
    fund_stock_from_advance = v_bool(body, "fund_stock_from_advance", required=False,
                                     default=False)
    allocation_id = v_string(body, "community_program_allocation_id", required=False)
    community_bucket = v_enum(body, "community_bucket", config.COMMUNITY_BUCKETS,
                              required=False, default="NONE")
    requested_subsidy_cents = v_int(body, "requested_subsidy_cents", required=False,
                                    default=0, minimum=0)

    member = get_member(member_bank_id)
    product = get_product(advance_product_id)
    allocation = get_allocation(allocation_id) if allocation_id else None
    svc.require_own_member(member["id"])
    if expected_version != member["version"]:
        raise ApiError("ERR_STALE_MEMBER_VERSION")
    if member["membership_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    if member["collateral_posture"] == "FROZEN":
        raise ApiError("ERR_COLLATERAL_POSTURE_FROZEN")
    if member["collateral_posture"] == "RESTRICTED" \
            and term_days > config.RESTRICTED_MAX_TERM_DAYS:
        raise ApiError("ERR_POSTURE_RESTRICTED_TERM_LIMIT")
    if product["community_program_flag"] and allocation is None:
        raise ApiError("ERR_PRODUCT_NOT_COMMUNITY_PROGRAM")
    if allocation is not None and not product["community_program_flag"]:
        raise ApiError("ERR_PRODUCT_NOT_COMMUNITY_PROGRAM")
    svc.derive_pure(member)
    if allocation is not None and not member["community_lending_eligible"]:
        raise ApiError("ERR_NOT_COMMUNITY_LENDING_ELIGIBLE")
    if term_days < product["min_term_days"] or term_days > product["max_term_days"]:
        raise ApiError("ERR_TERM_OUT_OF_RANGE")

    gross, activity, net = gross_up(requested_net_proceeds_cents,
                                    product["activity_stock_pct_bps"],
                                    fund_stock_from_advance)
    if gross < product["min_principal_cents"]:
        raise ApiError("ERR_MIN_PRINCIPAL_NOT_MET")
    subsidy_cap = pct_bps(gross, config.MAX_SUBSIDY_PCT_OF_PRINCIPAL_BPS)
    if requested_subsidy_cents > subsidy_cap:
        raise ApiError("ERR_SUBSIDY_EXCEEDS_PRINCIPAL_CAP")
    provisional = svc.capacity_breakdown(member, "PROVISIONAL")["borrowing_capacity_cents"]
    if gross > provisional:
        raise ApiError("ERR_INSUFFICIENT_BORROWING_CAPACITY")

    subsidy_rate = allocation["subsidy_rate_bps"] if allocation is not None else 0
    advance = svc.create_advance({
        "member_bank_id": member["id"],
        "advance_product_id": product["id"],
        "community_program_allocation_id": allocation["id"] if allocation else None,
        "community_bucket": community_bucket,
        "requested_subsidy_cents": requested_subsidy_cents,
        "requested_net_proceeds_cents": requested_net_proceeds_cents,
        "fund_stock_from_advance": fund_stock_from_advance,
        "term_days": term_days,
        "gross_principal_cents": gross,
        "activity_stock_cents": activity,
        "net_proceeds_cents": net,
        "rate_bps": advance_rate_bps(product["rate_bps"], subsidy_rate),
        "capacity_at_request_cents": provisional,
    })
    svc.recompute_posture(member, exclude_advance_id=advance["id"])
    svc.bump_member(member)
    return object_response(svc.serialize(advance), 201)


@endpoint("/fhlb/advances", ["GET"], _ADVANCE_READ_ROLES)
def list_advances():
    limit, offset = q_pagination()
    member_bank_id = q_str("member_bank_id")
    advance_product_id = q_str("advance_product_id")
    allocation_id = q_str("community_program_allocation_id")
    credit_status = q_enum("credit_status", config.CREDIT_STATUSES)
    collateral_status = q_enum("collateral_status", config.COLLATERAL_STATUSES)
    if svc.is_treasury():
        member_bank_id = g.user_id if member_bank_id in (None, g.user_id) else "\0"
    records = []
    for advance in db.advances.values():
        if member_bank_id is not None and advance["member_bank_id"] != member_bank_id:
            continue
        if advance_product_id is not None \
                and advance["advance_product_id"] != advance_product_id:
            continue
        if allocation_id is not None \
                and advance["community_program_allocation_id"] != allocation_id:
            continue
        if credit_status is not None and advance["credit_status"] != credit_status:
            continue
        if collateral_status is not None \
                and advance["collateral_status"] != collateral_status:
            continue
        records.append(advance)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/advances/<advance_id>", ["GET"], _ADVANCE_READ_ROLES)
def read_advance(advance_id):
    advance = get_advance(advance_id)
    svc.require_own_member(advance["member_bank_id"])
    return object_response(svc.serialize(advance))


@endpoint("/fhlb/advances/<advance_id>/approve", ["POST"], [config.ROLE_CREDIT_OFFICER])
def approve_advance(advance_id):
    get_body()
    advance = get_advance(advance_id)
    member = get_member(advance["member_bank_id"])
    if advance["credit_status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE")
    if member["membership_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    allocation = None
    if advance["community_program_allocation_id"]:
        allocation = db.allocations.get(advance["community_program_allocation_id"])
        if allocation is not None:
            svc.refresh_allocation(allocation)
            if allocation["status"] == "CLOSED":
                raise ApiError("ERR_ALLOCATION_CLOSED")
    if member["collateral_posture"] == "FROZEN":
        raise ApiError("ERR_COLLATERAL_POSTURE_FROZEN")
    if member["collateral_posture"] == "RESTRICTED" \
            and advance["term_days"] > config.RESTRICTED_MAX_TERM_DAYS:
        raise ApiError("ERR_POSTURE_RESTRICTED_TERM_LIMIT")
    if allocation is not None:
        svc.commit_subsidy(advance, allocation)
    advance["credit_status"] = "CREDIT_APPROVED"
    advance["approved_by_user_id"] = g.user_id
    touch(advance)
    svc.derive_pure(member)
    if member["stock_deficiency_cents"] > 0:
        for sub in sort_records(svc.member_subscriptions(member["id"])):
            if sub["status"] == "REDEMPTION_REQUESTED":
                sub["status"] = "ISSUED"
                sub["redemption_requested_at"] = None
                touch(sub)
        svc.derive_pure(member)
    svc.recompute_posture(member, exclude_advance_id=advance["id"])
    svc.bump_member(member)
    return object_response(svc.serialize(advance))


@endpoint("/fhlb/advances/<advance_id>/fund", ["POST"], [config.ROLE_CREDIT_OFFICER])
def fund_advance(advance_id):
    get_body()
    advance = get_advance(advance_id)
    member = get_member(advance["member_bank_id"])
    product = db.products.get(advance["advance_product_id"])
    if advance["credit_status"] != "CREDIT_APPROVED":
        raise ApiError("ERR_INVALID_STATE")
    if member["membership_status"] not in ("ACTIVE", "PROBATION"):
        raise ApiError("ERR_MEMBERSHIP_NOT_ACTIVE")
    if g.user_id == advance["approved_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if member["collateral_posture"] != "OPEN":
        raise ApiError("ERR_COLLATERAL_POSTURE_FROZEN")
    svc.derive_pure(member)
    if product["requires_collateral_delivery"] or member["delivery_required"]:
        for asset in svc.member_assets(member["id"]):
            if asset["status"] == "ELIGIBLE" \
                    and asset["effective_listing_mode"] != "DELIVERED":
                raise ApiError("ERR_DELIVERY_NOT_CONFIRMED")
    if not advance["fund_stock_from_advance"] and member["stock_deficiency_cents"] > 0:
        raise ApiError("ERR_ACTIVITY_STOCK_DEFICIENT")
    certified = svc.capacity_breakdown(member, "CERTIFIED",
                                       exclude_advance_id=advance["id"])
    capacity = certified["borrowing_capacity_cents"]
    if advance["gross_principal_cents"] > capacity:
        raise ApiError("ERR_INSUFFICIENT_BORROWING_CAPACITY")

    advance["credit_status"] = "FUNDED"
    advance["collateral_status"] = "SECURED"
    advance["funded_by_user_id"] = g.user_id
    advance["funded_at"] = db.now_iso()
    advance["maturity_date"] = fmt_dt(db.now() + timedelta(days=advance["term_days"]))
    advance["outstanding_principal_cents"] = advance["gross_principal_cents"]
    advance["capacity_at_funding_cents"] = capacity
    touch(advance)
    if advance["fund_stock_from_advance"]:
        svc.create_subscription(member["id"], "ACTIVITY", advance["activity_stock_cents"],
                                advance_id=advance["id"], status="ISSUED")
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(advance))


@endpoint("/fhlb/advances/<advance_id>/repay", ["POST"], [config.ROLE_CREDIT_OFFICER])
def repay_advance(advance_id):
    get_body()
    advance = get_advance(advance_id)
    member = get_member(advance["member_bank_id"])
    if advance["credit_status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE")
    if not advance["maturity_date"] or db.now() < parse_dt(advance["maturity_date"]):
        raise ApiError("ERR_INVALID_STATE")
    advance["credit_status"] = "REPAID"
    if advance["collateral_status"] in ("SECURED", "SHORTFALL"):
        advance["collateral_status"] = "RELEASED"
    advance["outstanding_principal_cents"] = 0
    touch(advance)
    _release_linked_subscription(advance, member)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(advance))


def _release_linked_subscription(advance, member):
    for sub in sort_records(svc.member_subscriptions(member["id"])):
        if (sub["advance_id"] == advance["id"]
                and sub["subscription_type"] == "ACTIVITY"
                and sub["status"] == "ISSUED"):
            sub["status"] = "REDEMPTION_REQUESTED"
            sub["redemption_requested_at"] = db.now_iso()
            touch(sub)


# ------------------------------------------------------------ prepayments -----


@endpoint("/fhlb/advances/<advance_id>/prepayment-quotes", ["POST"],
          [config.ROLE_TREASURY_OFFICER, config.ROLE_CREDIT_OFFICER])
def create_prepayment_quote(advance_id):
    body = get_body()
    prepay_kind = v_enum(body, "prepay_kind", config.PREPAY_KINDS)
    prepay_amount_cents = v_int(body, "prepay_amount_cents", minimum=1)
    advance = get_advance(advance_id)
    svc.require_own_member(advance["member_bank_id"])
    if advance["credit_status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE")
    if prepay_kind == "FULL" \
            and prepay_amount_cents != advance["outstanding_principal_cents"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A FULL prepayment must equal the advance's outstanding principal.")
    product = db.products.get(advance["advance_product_id"])
    event = svc.create_prepayment(advance, product, prepay_kind, prepay_amount_cents)
    return object_response(svc.serialize(event), 201)


@endpoint("/fhlb/prepayment-events", ["GET"], _PREPAY_READ_ROLES)
def list_prepayment_events():
    limit, offset = q_pagination()
    advance_id = q_str("advance_id")
    prepay_kind = q_enum("prepay_kind", config.PREPAY_KINDS)
    status = q_enum("status", config.PREPAYMENT_EVENT_STATUSES)
    own_member = None
    if svc.is_treasury():
        own_member = g.user_id
        if advance_id is not None:
            advance = db.advances.get(advance_id)
            if advance is not None and advance["member_bank_id"] != own_member:
                raise ApiError("ERR_MEMBER_SCOPE_VIOLATION")
    records = []
    for event in db.prepayments.values():
        if advance_id is not None and event["advance_id"] != advance_id:
            continue
        if prepay_kind is not None and event["prepay_kind"] != prepay_kind:
            continue
        if status is not None and event["status"] != status:
            continue
        if own_member is not None:
            advance = db.advances.get(event["advance_id"])
            if advance is None or advance["member_bank_id"] != own_member:
                continue
        records.append(event)
    items, total = svc.paginate(records, limit, offset)
    return list_response(items, limit, offset, total)


@endpoint("/fhlb/prepayment-events/<prepayment_event_id>", ["GET"], _PREPAY_READ_ROLES)
def read_prepayment_event(prepayment_event_id):
    event = get_prepayment(prepayment_event_id)
    advance = db.advances.get(event["advance_id"])
    if advance is not None:
        svc.require_own_member(advance["member_bank_id"])
    return object_response(svc.serialize(event))


@endpoint("/fhlb/prepayment-events/<prepayment_event_id>/settle", ["POST"],
          [config.ROLE_CREDIT_OFFICER])
def settle_prepayment_event(prepayment_event_id):
    get_body()
    event = get_prepayment(prepayment_event_id)
    advance = get_advance(event["advance_id"])
    member = get_member(advance["member_bank_id"])
    product = db.products.get(advance["advance_product_id"])
    if event["status"] != "QUOTED":
        raise ApiError("ERR_INVALID_STATE")
    deadline = parse_dt(event["quote_date"]) + timedelta(
        days=config.PREPAY_QUOTE_VALIDITY_DAYS)
    if db.now() > deadline:
        event["status"] = "EXPIRED"
        touch(event)
        raise ApiError("ERR_QUOTE_EXPIRED")
    if advance["credit_status"] != "FUNDED":
        raise ApiError("ERR_INVALID_STATE")
    if event["prepay_kind"] == "FULL" \
            and event["prepay_amount_cents"] != advance["outstanding_principal_cents"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "A FULL prepayment must equal the advance's outstanding principal.")

    svc.settle_prepayment_amounts(event, advance, product)
    touch(event)
    if event["prepay_kind"] == "PARTIAL":
        advance["outstanding_principal_cents"] -= event["prepay_amount_cents"]
        touch(advance)
    else:
        advance["outstanding_principal_cents"] = 0
        advance["credit_status"] = "PREPAID"
        if advance["collateral_status"] in ("SECURED", "SHORTFALL"):
            advance["collateral_status"] = "RELEASED"
        touch(advance)
        _release_linked_subscription(advance, member)
    svc.recompute_posture(member)
    svc.bump_member(member)
    return object_response(svc.serialize(event))


# ------------------------------------------------------------- allocations ----


@endpoint("/fhlb/community-program-allocations", ["POST"],
          [config.ROLE_COMMUNITY_LENDING_MANAGER])
def create_community_allocation():
    body = get_body()
    program_code = v_enum(body, "program_code", config.PROGRAM_CODES)
    fiscal_year = v_int(body, "fiscal_year", minimum=2020)
    total_pool_cents = v_int(body, "total_pool_cents", minimum=1)
    subsidy_rate_bps = v_int(body, "subsidy_rate_bps", minimum=0, maximum=500)
    allocation = svc.create_allocation(program_code, fiscal_year, total_pool_cents,
                                       subsidy_rate_bps)
    return object_response(svc.serialize(allocation), 201)


@endpoint("/fhlb/community-program-allocations/<community_program_allocation_id>",
          ["GET"], [config.ROLE_SYSTEM_ADMIN, config.ROLE_CREDIT_OFFICER,
                    config.ROLE_TREASURY_OFFICER, config.ROLE_COMMUNITY_LENDING_MANAGER])
def read_community_allocation(community_program_allocation_id):
    allocation = get_allocation(community_program_allocation_id)
    return object_response(svc.serialize(allocation))


# -------------------------------------------------------- test-driving hooks --


@endpoint("/_clock/set_current_utc", ["POST"], [config.ROLE_SYSTEM_ADMIN])
def set_current_utc():
    body = get_body()
    now = v_datetime(body, "now")
    db.clock = parse_dt(now)
    return object_response({})


@endpoint("/_ops/set-market-rate", ["POST"], [config.ROLE_SYSTEM_ADMIN])
def set_market_rate():
    body = get_body()
    db.market_rate_bps = v_int(body, "market_rate_bps", minimum=0)
    return object_response({})
