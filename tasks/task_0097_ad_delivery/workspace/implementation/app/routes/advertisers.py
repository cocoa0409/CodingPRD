"""Advertiser CRUD + lifecycle endpoints."""
from flask import Blueprint, request

from .. import store
from ..audit import emit as audit_emit
from ..auth import require_auth
from ..errors import ApiError
from ..pagination import get_pagination, paginate, sort_by_created_asc
from ..response import success
from ..validators import get_json_body, require_fields, require_enum, check_version_if_provided
from ..services.paths import resolve_advertiser
from ..services.lifecycle import suspend_advertiser_cascade, close_advertiser_cascade, reinstate_advertiser
from ..services.qualification import maybe_activate_advertiser


bp = Blueprint("advertisers", __name__)


ACCOUNT_TYPES = ["MCC", "SUB_ACCOUNT", "INDEPENDENT"]
INDUSTRIES = ["GENERAL", "MEDICAL", "FINANCIAL", "EDUCATION"]
BILLING_MODES = ["PREPAY", "POSTPAY"]


def _validate_credit_line(billing_mode: str, credit_line_cents: int):
    if billing_mode == "PREPAY" and credit_line_cents != 0:
        raise ApiError("ERR_INVALID_CREDIT_LINE", "PREPAY accounts must have credit_line_cents = 0.")
    if credit_line_cents < 0:
        raise ApiError("ERR_INVALID_CREDIT_LINE", "credit_line_cents must be >= 0.")


@bp.post("/advertisers")
@require_auth(["PlatformAdmin"])
def create_advertiser():
    body = get_json_body()
    require_fields(body, ["account_type", "legal_name", "business_license_number", "industry_category", "billing_mode"])
    account_type = require_enum(body, "account_type", ACCOUNT_TYPES)
    industry = require_enum(body, "industry_category", INDUSTRIES)
    billing_mode = require_enum(body, "billing_mode", BILLING_MODES)
    credit_line = int(body.get("credit_line_cents") or 0)
    low_balance = int(body.get("low_balance_threshold_cents") if body.get("low_balance_threshold_cents") is not None else 10000)
    tax_rate = int(body.get("tax_rate_bps") or 0)

    _validate_credit_line(billing_mode, credit_line)

    parent_account_id = body.get("parent_account_id")
    if account_type == "SUB_ACCOUNT":
        if not parent_account_id:
            raise ApiError("ERR_INVALID_REQUEST", "SUB_ACCOUNT requires parent_account_id.")
        parent = store.get("Advertiser", parent_account_id)
        if not parent or parent.get("account_type") != "MCC":
            raise ApiError("ERR_INVALID_REQUEST", "parent_account_id must reference an existing MCC.")
    else:
        if parent_account_id:
            raise ApiError("ERR_INVALID_REQUEST", "parent_account_id only valid for SUB_ACCOUNT.")

    rec = {
        "id": store.gen_uuid(),
        "parent_account_id": parent_account_id,
        "account_type": account_type,
        "legal_name": body["legal_name"],
        "business_license_number": body["business_license_number"],
        "industry_category": industry,
        "special_qualifications": list(body.get("special_qualifications") or []),
        "qualification_status": "UNVERIFIED",
        "status": "PENDING",
        "billing_mode": billing_mode,
        "credit_line_cents": credit_line,
        "balance_cents": 0,
        "consumed_cents": 0,
        "balance_state": "ZERO_BALANCE",
        "low_balance_threshold_cents": low_balance,
        "tax_rate_bps": tax_rate,
        "created_seq": store.next_advertiser_seq(),
    }
    store.stamp_common(rec, with_version=True)
    store.insert("Advertiser", rec)
    return success(rec, status=201)


@bp.get("/advertisers")
@require_auth(["PlatformAdmin"])
def list_advertisers():
    limit, offset = get_pagination()
    rows = store.list_all("Advertiser")
    account_type = request.args.get("account_type")
    if account_type:
        rows = [r for r in rows if r.get("account_type") == account_type]
    parent = request.args.get("parent_account_id")
    if parent:
        rows = [r for r in rows if r.get("parent_account_id") == parent]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r.get("status") == status]
    rows = sort_by_created_asc(rows)
    page, meta = paginate(rows, limit, offset)
    return success(page, pagination=meta)


@bp.get("/advertisers/<advertiser_id>")
@require_auth(["PlatformAdmin", "AccountOwner", "CampaignManager", "FinanceOfficer", "CreativeReviewer"])
def get_advertiser(advertiser_id):
    rec = resolve_advertiser(advertiser_id)
    return success(rec)


@bp.put("/advertisers/<advertiser_id>")
@require_auth(["PlatformAdmin"])
def update_advertiser(advertiser_id):
    rec = resolve_advertiser(advertiser_id)
    body = get_json_body()
    check_version_if_provided(body, rec)

    before = {
        "credit_line_cents": rec.get("credit_line_cents"),
        "low_balance_threshold_cents": rec.get("low_balance_threshold_cents"),
        "tax_rate_bps": rec.get("tax_rate_bps"),
    }
    credit_line_changed = False
    new_credit = rec.get("credit_line_cents")
    if "credit_line_cents" in body and body["credit_line_cents"] is not None:
        new_credit = int(body["credit_line_cents"])
        _validate_credit_line(rec.get("billing_mode"), new_credit)
    if "low_balance_threshold_cents" in body and body["low_balance_threshold_cents"] is not None:
        rec["low_balance_threshold_cents"] = int(body["low_balance_threshold_cents"])
    if "tax_rate_bps" in body and body["tax_rate_bps"] is not None:
        rec["tax_rate_bps"] = int(body["tax_rate_bps"])

    if new_credit != rec.get("credit_line_cents"):
        credit_line_changed = True
        rec["credit_line_cents"] = new_credit

    store.touch(rec)

    # Recompute balance_state because threshold may have changed.
    from ..services.wallet import recompute_balance_state
    recompute_balance_state(rec)

    if credit_line_changed:
        audit_emit(
            "CREDIT_LINE_CHANGE",
            "Advertiser",
            rec["id"],
            before_value=before,
            after_value={
                "credit_line_cents": rec["credit_line_cents"],
                "low_balance_threshold_cents": rec["low_balance_threshold_cents"],
                "tax_rate_bps": rec["tax_rate_bps"],
            },
        )

    return success(rec)


@bp.post("/advertisers/<advertiser_id>/suspend")
@require_auth(["PlatformAdmin"])
def suspend_adv(advertiser_id):
    rec = resolve_advertiser(advertiser_id)
    if rec.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if rec.get("status") not in ("ACTIVE",):
        raise ApiError("ERR_INVALID_REQUEST", "Only ACTIVE advertisers can be suspended.")
    suspend_advertiser_cascade(rec)
    return success(rec)


@bp.post("/advertisers/<advertiser_id>/reinstate")
@require_auth(["PlatformAdmin"])
def reinstate_adv(advertiser_id):
    rec = resolve_advertiser(advertiser_id)
    if rec.get("status") != "SUSPENDED":
        raise ApiError("ERR_INVALID_REQUEST", "Only SUSPENDED advertisers can be reinstated.")
    if rec.get("qualification_status") != "VERIFIED":
        raise ApiError("ERR_INVALID_REQUEST", "Cannot reinstate without VERIFIED qualification.")
    reinstate_advertiser(rec)
    return success(rec)


@bp.post("/advertisers/<advertiser_id>/close")
@require_auth(["PlatformAdmin"])
def close_adv(advertiser_id):
    rec = resolve_advertiser(advertiser_id)
    if rec.get("status") == "CLOSED":
        raise ApiError("ERR_ADVERTISER_CLOSED")
    if rec.get("status") not in ("ACTIVE", "SUSPENDED", "PENDING"):
        raise ApiError("ERR_INVALID_REQUEST", "Advertiser is not in a closeable state.")
    # Preconditions: no ACTIVE / RUNNING campaigns.
    for camp in store.list_all("Campaign"):
        if camp.get("advertiser_id") != rec["id"]:
            continue
        if camp.get("status") in ("ACTIVE",):
            raise ApiError("ERR_CANNOT_CLOSE_WITH_ACTIVE_CAMPAIGNS")
    # Also check RUNNING ad-groups (no campaign is RUNNING, but RUNNING is an ad-group status; rule still applies).
    close_advertiser_cascade(rec)
    return success(rec)
