"""Accounts and content items (PRD §3.1)."""

from flask import Blueprint

import ser
from core import (
    ACCOUNT_TIERS, DEFAULT_APPEAL_CREDITS, LANGUAGES, MEDIA_KINDS,
    REVIEW_STATUSES, UPPER2, VISIBILITY_STATUSES, base_fields, body, created,
    db, enum_filter, fail, listing, now_iso, ok, opt_enum, opt_int,
    paginate_args, req_enum, req_str, require, str_filter,
)
from svc import find

bp = Blueprint("accounts", __name__)


@bp.post("/accounts")
def create_account():
    require("TrustSafetyAdmin")
    payload = body()
    external_handle = req_str(payload, "external_handle", 1, 64)
    region_code = req_str(payload, "region_code", 2, 2)
    if not UPPER2.match(region_code):
        fail("ERR_INVALID_REQUEST", "region_code must be exactly two uppercase letters.")
    tier = opt_enum(payload, "tier", ACCOUNT_TIERS, "STANDARD")
    credits = opt_int(payload, "appeal_credits_remaining", 0, None, DEFAULT_APPEAL_CREDITS)

    for existing in db.accounts.values():
        if existing["external_handle"] == external_handle:
            fail("ERR_DUPLICATE_HANDLE", "An account with this external_handle already exists.")

    record = {
        "external_handle": external_handle,
        "region_code": region_code,
        "tier": tier,
        "appeal_credits_remaining": credits,
        "strike_points": 0,
        "lifetime_removed_count": 0,
        "standing": "GOOD_STANDING",
    }
    base_fields(record)
    db.accounts[record["id"]] = record
    return created(ser.account(record))


@bp.get("/accounts/<account_id>")
def get_account(account_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    record = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    return ok(ser.account(record))


@bp.post("/content-items")
def create_content_item():
    require("TrustSafetyAdmin")
    payload = body()
    account_id = req_str(payload, "account_id", 1, None)
    language = req_enum(payload, "language", LANGUAGES)
    media_kind = req_enum(payload, "media_kind", MEDIA_KINDS)
    graphic_weight = opt_int(payload, "graphic_weight", 0, 10, 0)

    account = find(db.accounts, account_id, "ERR_ACCOUNT_NOT_FOUND")
    if account["standing"] == "BANNED":
        fail("ERR_ACCOUNT_BANNED", "The authoring account is BANNED.")

    record = {
        "account_id": account_id,
        "language": language,
        "media_kind": media_kind,
        "graphic_weight": graphic_weight,
        "posted_at": now_iso(),
        "visibility_status": "LIVE",
        "review_status": "CLEAR",
        "open_case_count": 0,
        "reinstated_at": None,
    }
    base_fields(record)
    db.content_items[record["id"]] = record
    return created(ser.content_item(record))


@bp.get("/content-items/<content_id>")
def get_content_item(content_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer",
            "LegalCounsel", "AccountHolder")
    record = find(db.content_items, content_id, "ERR_CONTENT_NOT_FOUND")
    return ok(ser.content_item(record))


@bp.get("/content-items")
def list_content_items():
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer", "LegalCounsel")
    limit, offset = paginate_args()
    account_id = str_filter("account_id")
    visibility = enum_filter("visibility_status", VISIBILITY_STATUSES)
    review = enum_filter("review_status", REVIEW_STATUSES)
    records = []
    for record in db.content_items.values():
        if account_id is not None and record["account_id"] != account_id:
            continue
        if visibility is not None and record["visibility_status"] != visibility:
            continue
        if review is not None and record["review_status"] != review:
            continue
        records.append(record)
    return listing(records, limit, offset, ser.content_item)


@bp.get("/content-items/<content_id>/detection-signals")
def list_signals_for_content(content_id):
    require("TrustSafetyAdmin", "PolicyManager", "QAAuditor", "Reviewer")
    limit, offset = paginate_args()
    find(db.content_items, content_id, "ERR_CONTENT_NOT_FOUND")
    records = [s for s in db.detection_signals.values()
               if s["content_item_id"] == content_id]
    return listing(records, limit, offset, ser.detection_signal)
