"""Brewery registration, credit profile, cash receipts, volume adjustments."""

from flask import Blueprint

from calc import recompute_brewer
from cascades import post_receivable
from db import db, new_entity, now, set_dt, touch
from errors import ApiError
from middleware import ALL_ROLES, require
from response import object_response
from serialize import brewer_out
from util import D
from validation import body, f_bool, f_dec, f_dt, f_int, f_str, f_version, must_exist

bp = Blueprint("brewers", __name__)


@bp.post("/brewers")
def create_brewer():
    require(("CreditManager", "PlatformAdmin"))
    payload = body()
    name = f_str(payload, "name", min_len=1, max_len=120)
    license_no = f_str(payload, "brewery_license_no", min_len=1, max_len=40)
    credit_terms_days = f_int(
        payload, "credit_terms_days", required=False, choices=(0, 15, 30, 45), default=30
    )
    credit_limit_cents = f_int(
        payload, "credit_limit_cents", required=False, minimum=1, default=500000
    )
    cold_chain_certified = f_bool(
        payload, "cold_chain_certified", required=False, default=False
    )
    legacy_trailing_lbs = f_dec(
        payload, "legacy_trailing_lbs", required=False, scale=2, minimum=0, default=D(0)
    )

    for existing in db.brewers.values():
        if existing["brewery_license_no"] == license_no:
            raise ApiError(
                "ERR_DUPLICATE_BREWERY_LICENSE",
                "brewery_license_no is already registered",
            )

    brewer = new_entity()
    brewer.update(
        {
            "name": name,
            "brewery_license_no": license_no,
            "credit_terms_days": credit_terms_days,
            "credit_limit_cents": credit_limit_cents,
            "cold_chain_certified": cold_chain_certified,
            "legacy_trailing_lbs": legacy_trailing_lbs,
            "ar_balance_cents": 0,
            "open_order_exposure_cents": 0,
            "credit_exposure_cents": 0,
            "credit_utilization_pct": D("0.00"),
            "credit_status": "GOOD_STANDING",
            "trailing_12mo_volume_lbs": D(0),
            "freight_program_tier": "TIER_1",
        }
    )
    db.brewers[brewer["id"]] = brewer
    recompute_brewer(brewer, bump=False)
    return object_response(brewer_out(brewer), 201)


@bp.get("/brewers/<brewer_id>")
def get_brewer(brewer_id):
    require(ALL_ROLES)
    brewer = must_exist("brewers", brewer_id)
    return object_response(brewer_out(brewer))


@bp.put("/brewers/<brewer_id>/credit-profile")
def update_credit_profile(brewer_id):
    require(("CreditManager",))
    payload = body()
    expected_version = f_version(payload, "expected_brewer_version")
    credit_limit_cents = f_int(payload, "credit_limit_cents", required=False, minimum=1)
    credit_terms_days = f_int(
        payload, "credit_terms_days", required=False, choices=(0, 15, 30, 45)
    )
    cold_chain_certified = f_bool(payload, "cold_chain_certified", required=False)

    brewer = must_exist("brewers", brewer_id)
    if expected_version != brewer["version"]:
        raise ApiError(
            "ERR_STALE_BREWER_VERSION",
            "expected_brewer_version does not match the brewery's current version",
        )
    if credit_limit_cents is not None:
        brewer["credit_limit_cents"] = credit_limit_cents
    if credit_terms_days is not None:
        brewer["credit_terms_days"] = credit_terms_days
    if cold_chain_certified is not None:
        brewer["cold_chain_certified"] = cold_chain_certified
    recompute_brewer(brewer, bump=False)
    touch(brewer)
    return object_response(brewer_out(brewer))


@bp.post("/brewers/<brewer_id>/payments")
def post_payment(brewer_id):
    require(("CreditManager",))
    payload = body()
    amount_cents = f_int(payload, "amount_cents", required=True, minimum=1)
    f_dt(payload, "received_at", required=False)
    f_str(payload, "reference", required=False, max_len=200)

    brewer = must_exist("brewers", brewer_id)
    if amount_cents > int(brewer["ar_balance_cents"]):
        raise ApiError(
            "ERR_PAYMENT_EXCEEDS_BALANCE",
            "amount_cents exceeds the brewery's outstanding receivable balance",
        )
    post_receivable(brewer, -amount_cents)
    return object_response(brewer_out(brewer))


@bp.post("/brewers/<brewer_id>/volume-adjustments")
def post_volume_adjustment(brewer_id):
    require(("AllocationManager", "PlatformAdmin"))
    payload = body()
    legacy_trailing_lbs = f_dec(
        payload, "legacy_trailing_lbs", required=True, scale=2, minimum=0
    )
    f_str(payload, "reason", required=False, max_len=500)

    brewer = must_exist("brewers", brewer_id)
    brewer["legacy_trailing_lbs"] = legacy_trailing_lbs
    recompute_brewer(brewer, bump=False)
    touch(brewer)
    return object_response(brewer_out(brewer))
