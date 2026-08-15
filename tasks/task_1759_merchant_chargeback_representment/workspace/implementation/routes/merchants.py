"""Merchant endpoints + reserve policy + sub-resource listings (PRD 3.1)."""

from flask import Blueprint, g, request

from db import db
from errors import ApiError
from middleware import is_merchant_user
from records import new_merchant, new_reserve_account, touch
from response import ok_object
from routes.common import ALL_ROLES, authenticate, get_or_404, hide_if_cross_merchant, json_body, list_response
from serializers import serialize_education_assignment, serialize_merchant, serialize_ratio_snapshot
from services.reserve import recompute_target
from util import (
    ASSIGNMENT_STATUSES, MERCHANT_STATUSES, RESERVE_MODES, RISK_TIERS, Body, filter_enum,
)

bp = Blueprint("merchants", __name__)


@bp.post("/acquirer/merchants")
def create_merchant():
    authenticate(("AcquirerOps",))
    b = Body(json_body())
    legal_name = b.req_str("legal_name")
    mcc = b.req_str("merchant_category_code")
    risk_tier = b.opt_enum("risk_tier", RISK_TIERS, default="STANDARD")
    reserve_mode = b.opt_enum("reserve_mode", RESERVE_MODES, default="FIXED_TIER")
    reserve_rate_bps = b.opt_int("reserve_rate_bps", minv=0, maxv=10000)
    if reserve_rate_bps is None:
        reserve_rate_bps = 500
    b.raise_pending()

    merchant = new_merchant(legal_name, mcc, risk_tier, reserve_mode, reserve_rate_bps)
    db.merchants[merchant["id"]] = merchant
    # Onboarding cascade: the 1:1 ReserveAccount, held/target both zero.
    acct = new_reserve_account(merchant["id"])
    db.reserve_accounts[acct["id"]] = acct
    return ok_object(serialize_merchant(merchant), status=201)


@bp.get("/acquirer/merchants")
def list_merchants():
    authenticate(ALL_ROLES)
    status = filter_enum(request.args, "status", MERCHANT_STATUSES)
    risk_tier = filter_enum(request.args, "risk_tier", RISK_TIERS)
    records = list(db.merchants.values())
    if is_merchant_user():
        # Force-scoped to the caller's own merchant regardless of filters (PRD 2.7).
        records = [m for m in records if m["id"] == g.uid]
    if status is not None:
        records = [m for m in records if m["status"] == status]
    if risk_tier is not None:
        records = [m for m in records if m["risk_tier"] == risk_tier]
    return list_response(records, serialize_merchant)


@bp.get("/acquirer/merchants/<mid>")
def get_merchant(mid):
    authenticate(ALL_ROLES)
    merchant = get_or_404(db.merchants, mid, "Merchant")
    hide_if_cross_merchant(merchant["id"])
    return ok_object(serialize_merchant(merchant))


@bp.patch("/acquirer/merchants/<mid>/reserve-policy")
def patch_reserve_policy(mid):
    authenticate(("RiskOfficer",))
    merchant = get_or_404(db.merchants, mid, "Merchant")
    b = Body(json_body())

    # Priority 4 (OCC): expected_merchant_version must equal Merchant.version.
    emv_raw = b.d.get("expected_merchant_version")
    if emv_raw is not None:
        if not isinstance(emv_raw, int) or isinstance(emv_raw, bool):
            b._fail(("ERR_INVALID_REQUEST", 400), "Field 'expected_merchant_version' must be an integer")
        elif emv_raw != merchant["version"]:
            raise ApiError(412, "ERR_STALE_VERSION", "expected_merchant_version does not match the merchant's current version")
    else:
        b._fail(("ERR_INVALID_REQUEST", 400), "Field 'expected_merchant_version' is required")

    # Blind-overwrite policy update (PRD 3.1).
    rate = b.opt_int("reserve_rate_bps", minv=0, maxv=10000)
    mode = b.opt_enum("reserve_mode", RESERVE_MODES)
    b.raise_pending()

    if rate is not None:
        merchant["reserve_rate_bps"] = rate
    if mode is not None:
        merchant["reserve_mode"] = mode
    touch(merchant)  # OCC write
    acct = recompute_target(merchant)
    if acct is not None:
        touch(acct)
    return ok_object(serialize_merchant(merchant))


@bp.post("/acquirer/merchants/<mid>/suspend")
def suspend_merchant(mid):
    authenticate(("RiskOfficer",))
    merchant = get_or_404(db.merchants, mid, "Merchant")
    merchant["status"] = "SUSPENDED"
    touch(merchant)
    return ok_object(serialize_merchant(merchant))


@bp.post("/acquirer/merchants/<mid>/reinstate")
def reinstate_merchant(mid):
    authenticate(("RiskOfficer",))
    merchant = get_or_404(db.merchants, mid, "Merchant")
    merchant["status"] = "ACTIVE"
    touch(merchant)
    return ok_object(serialize_merchant(merchant))


@bp.get("/acquirer/merchants/<mid>/ratio-snapshots")
def list_ratio_snapshots(mid):
    authenticate(ALL_ROLES)
    merchant = get_or_404(db.merchants, mid, "Merchant")
    hide_if_cross_merchant(merchant["id"])
    period_month = request.args.get("period_month")
    records = [s for s in db.ratio_snapshots.values() if s["merchant_id"] == merchant["id"]]
    if period_month is not None:
        records = [s for s in records if s["period_month"] == period_month]
    return list_response(records, serialize_ratio_snapshot)


@bp.get("/acquirer/merchants/<mid>/education-assignments")
def list_education_assignments(mid):
    authenticate(ALL_ROLES)
    merchant = get_or_404(db.merchants, mid, "Merchant")
    hide_if_cross_merchant(merchant["id"])
    status = filter_enum(request.args, "status", ASSIGNMENT_STATUSES)
    records = [a for a in db.education_assignments.values() if a["merchant_id"] == merchant["id"]]
    if status is not None:
        records = [a for a in records if a["status"] == status]
    return list_response(records, serialize_education_assignment)
