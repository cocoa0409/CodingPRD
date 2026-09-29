"""Digital asset inventory, transferability reviews and subscription terms
(PRD sections 3.4, 3.7).
"""
from flask import Blueprint, request

from authz import (ALL_ROLES, FIDUCIARY, authenticate,
                   require_fiduciary_estate, require_role)
from clock import inclusive_days, parse_date
from db import DB, bump, stamp_new
from errors import ApiError
from response import public, single
from routes.common import paged
from services import authority, lookup
from services import estate as estate_svc
from validation import (bad, parse_body, v_bool, v_date, v_enum, v_id, v_int,
                        v_str, v_text, validate)

bp = Blueprint("assets", __name__)

ASSET_CATEGORIES = ("FINANCIAL_ACCOUNT", "EMAIL", "CLOUD_STORAGE",
                    "SUBSCRIPTION", "LOYALTY_PROGRAM", "SOCIAL_PROFILE")
BILLING_INTERVALS = ("MONTHLY", "ANNUAL")
MAX_PERIOD_FEE_CENTS = 100000000


@bp.route("/estates/<estate_id>/digital-assets", methods=["POST"])
def create_asset(estate_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "platform_id": v_id(),
        "category": v_enum(ASSET_CATEGORIES),
        "account_handle": v_str(120),
        "quoted_value_cents": v_int(0),
    }, optional={
        "loyalty_points": v_int(0),
        "inventory_note": v_text(),
    }, ignore=("transferability", "transferability_reason"))

    estate = lookup.get_estate(estate_id)
    platform = lookup.get_platform(body["platform_id"])
    require_fiduciary_estate(user_id, role, estate_id)
    estate_svc.require_open(estate)

    handle = body["account_handle"]
    for existing in lookup.estate_assets(estate_id):
        if (existing["platform_id"] == platform["id"]
                and existing["account_handle"] == handle):
            raise ApiError("ERR_DUPLICATE_ASSET_HANDLE")

    category = body["category"]
    asset = {
        "estate_id": estate_id,
        "platform_id": platform["id"],
        "category": category,
        "account_handle": handle,
        "quoted_value_cents": body["quoted_value_cents"],
        "loyalty_points": body.get("loyalty_points", 0),
        "inventory_note": body.get("inventory_note"),
        "transferability": None,
        "transferability_reason": None,
        "access_status": "UNVERIFIED",
        "content_clamp_reason": "NONE",
        "disposition_status": "PENDING",
        "subscription_billing_state": (
            "ACTIVE" if category == "SUBSCRIPTION" else "NOT_APPLICABLE"),
        "appraised_value_cents": None,
        "appraised_basis": None,
        "disclosed_at": None,
        "disposed_at": None,
    }
    klass, reason = authority.classify_transferability(asset, platform)
    asset["transferability"] = klass
    asset["transferability_reason"] = reason
    stamp_new(asset)
    DB.assets[asset["id"]] = asset
    estate_svc.recompute(estate)
    return single(public(asset), 201)


@bp.route("/digital-assets/<asset_id>", methods=["GET"])
def read_asset(asset_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_asset(asset_id)), 200)


@bp.route("/digital-assets", methods=["GET"])
def list_assets():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.assets.values(), request.args, {
        "estate_id": "estate_id",
        "platform_id": "platform_id",
        "category": "category",
        "access_status": "access_status",
        "disposition_status": "disposition_status",
        "transferability": "transferability",
    })


@bp.route("/digital-assets/<asset_id>/transferability-reviews", methods=["POST"])
def transferability_review(asset_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    # review_note is an accepted input with no declared storage field.
    validate(parse_body(request), optional={"review_note": v_text()})
    asset = lookup.get_asset(asset_id)
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    estate = lookup.estate_of_asset(asset)
    estate_svc.require_open(estate)

    platform = DB.platforms.get(asset["platform_id"])
    klass, reason = authority.classify_transferability(asset, platform)
    asset["transferability"] = klass
    asset["transferability_reason"] = reason
    bump(asset)
    return single(public(asset), 200)


# ------------------------------------------------------- SubscriptionTerm

@bp.route("/digital-assets/<asset_id>/subscription-terms", methods=["POST"])
def create_term(asset_id):
    user_id, role = authenticate(request)
    require_role(role, (FIDUCIARY,))
    body = validate(parse_body(request), required={
        "term_start_date": v_date(),
        "term_end_date": v_date(),
        "billing_interval": v_enum(BILLING_INTERVALS),
        "period_fee_cents": v_int(0, MAX_PERIOD_FEE_CENTS),
        "auto_renew": v_bool(),
    })
    start = parse_date(body["term_start_date"])
    end = parse_date(body["term_end_date"])
    if end < start:
        raise bad("term_end_date must not fall before term_start_date.")

    asset = lookup.get_asset(asset_id)
    require_fiduciary_estate(user_id, role, asset["estate_id"])
    estate = lookup.estate_of_asset(asset)
    estate_svc.require_open(estate)

    if asset["category"] != "SUBSCRIPTION" or lookup.asset_terms(asset_id):
        raise ApiError("ERR_SUBSCRIPTION_TERM_EXISTS")

    term = {
        "asset_id": asset_id,
        "term_start_date": body["term_start_date"],
        "term_end_date": body["term_end_date"],
        "billing_interval": body["billing_interval"],
        "period_fee_cents": body["period_fee_cents"],
        "auto_renew": body["auto_renew"],
        "term_days": inclusive_days(start, end),
        "state": "ACTIVE",
        "cancelled_effective_date": None,
        "claimed_days_total": 0,
    }
    stamp_new(term)
    DB.terms[term["id"]] = term
    return single(public(term), 201)


@bp.route("/subscription-terms/<term_id>", methods=["GET"])
def read_term(term_id):
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return single(public(lookup.get_term(term_id)), 200)


@bp.route("/subscription-terms", methods=["GET"])
def list_terms():
    _, role = authenticate(request)
    require_role(role, ALL_ROLES)
    return paged(DB.terms.values(), request.args, {
        "asset_id": "asset_id",
        "state": "state",
        "billing_interval": "billing_interval",
    })
