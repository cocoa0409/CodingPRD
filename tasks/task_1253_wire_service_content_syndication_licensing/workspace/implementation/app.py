#!/usr/bin/env python3
"""Wire Service & Content Syndication Licensing API.

In-memory REST implementation of the PRD in workspace/PRD.md.
All state lives in module-level dicts; nothing is persisted or seeded.
"""

import calendar
import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# =====================================================================
# In-memory store (empty at boot; the logical clock is system state,
# not entity data, and starts at the PRD-mandated instant)
# =====================================================================
STORE = {
    "packages": {},
    "tiers": {},
    "feeds": {},
    "subscribers": {},
    "subscriptions": {},
    "entitlements": {},
    "articles": {},
    "assets": {},
    "publications": {},
    "invoices": {},
}
_SEQ = [0]
INITIAL_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)
CLOCK = {"current_utc": INITIAL_CLOCK}
CHECKPOINT = {"id": str(uuid.uuid4()), "created_at": INITIAL_CLOCK}

ROLES = {
    "PlatformAdmin", "SalesOps", "Editor", "Legal",
    "Auditor", "Billing", "SubscriberRep",
}

MEDIA_RIGHTS = {"TEXT_ONLY", "TEXT_AND_PHOTO", "TEXT_PHOTO_VIDEO"}
TOPICS = {"NATIONAL", "WORLD", "BUSINESS", "SPORTS", "FEATURES"}
ASSET_KINDS = {"PHOTO", "VIDEO"}
RIGHTS_SCOPES = {"WIRE", "EDITORIAL_ONLY", "MEMBER_ONLY"}
PACKAGE_STATUSES = {"ACTIVE", "RETIRED"}
TIER_STATUSES = {"ACTIVE", "RETIRED"}
FEED_STATUSES = {"LIVE", "SUSPENDED"}
SUBSCRIBER_STATUSES = {"ACTIVE", "SUSPENDED", "TERMINATED"}
SUBSCRIPTION_STATUSES = {"DRAFT", "ACTIVE", "SUSPENDED", "EXPIRED", "CANCELLED"}
ENTITLEMENT_STATUSES = {"LIVE", "REVOKED"}
ARTICLE_STATUSES = {"DRAFT", "PUBLISHED", "WITHDRAWN", "TAKEN_DOWN"}
EMBARGO_STATUSES = {"CLEAR", "EMBARGOED", "EMBARGO_LIFTED"}
ASSET_STATUSES = {"ACTIVE", "TAKEN_DOWN"}
PUBLICATION_STATUSES = {"RECORDED", "AUDIT_FLAGGED", "DISMISSED"}
INVOICE_STATUSES = {"DRAFT", "ISSUED", "PAID", "VOIDED"}


# =====================================================================
# Errors & envelope
# =====================================================================
class ApiError(Exception):
    def __init__(self, http_status, error_id, message):
        super().__init__(message)
        self.http_status = http_status
        self.error_id = error_id
        self.message = message


def _meta():
    return {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": rdt(datetime.now(timezone.utc)),
    }


def err_validation(msg):
    return ApiError(400, "ERR_VALIDATION", msg)


def err_not_found(msg="Referenced id or FK not found"):
    return ApiError(404, "ERR_NOT_FOUND", msg)


def err_invalid_state(msg):
    return ApiError(409, "ERR_INVALID_STATE", msg)


def ok_object(data, status=200):
    return jsonify({
        "meta": _meta(),
        "response_type": "object",
        "data": data,
    }), status


def ok_list(items, limit, offset, total_count):
    meta = _meta()
    meta["limit"] = limit
    meta["offset"] = offset
    meta["total_count"] = total_count
    meta["has_more"] = (offset + len(items)) < total_count
    return jsonify({
        "meta": meta,
        "response_type": "array",
        "data": items,
    }), 200


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }), e.http_status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND",
                 "message": "Referenced id or FK not found"},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND",
                 "message": "Method not allowed on this path"},
    }), 405


@app.errorhandler(500)
def handle_500(e):
    return jsonify({
        "meta": _meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_VALIDATION",
                 "message": "Internal server error"},
    }), 500


# =====================================================================
# Datetime helpers
# =====================================================================
def rdt(dt):
    """Render a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def pdt(value, field):
    """Parse an ISO 8601 datetime string; ERR_VALIDATION on failure."""
    if not isinstance(value, str):
        raise err_validation("%s must be an ISO 8601 datetime string" % field)
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        raise err_validation("%s must be an ISO 8601 datetime string" % field)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def add_months(dt, n):
    idx = dt.month - 1 + n
    year = dt.year + idx // 12
    month = idx % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


def whole_months_between(start, end):
    if end < start:
        return 0
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if add_months(start, months) > end:
        months -= 1
    return max(months, 0)


def month_bucket(dt):
    return "%04d-%02d" % (dt.year, dt.month)


def round_half_up_int(numer, denom):
    return int((Decimal(numer) / Decimal(denom)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


# =====================================================================
# Record helpers
# =====================================================================
def new_id():
    return str(uuid.uuid4())


def make_record():
    _SEQ[0] += 1
    now = CLOCK["current_utc"]
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": _SEQ[0],
    }


def bump(rec):
    rec["version"] += 1
    rec["updated_at"] = CLOCK["current_utc"]


# =====================================================================
# Request helpers: auth, body, field validation, pagination, filters
# =====================================================================
def authenticate(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or not role or role not in ROLES:
        raise ApiError(401, "ERR_UNAUTHENTICATED",
                       "Missing or malformed auth headers")
    if role not in allowed_roles:
        raise ApiError(403, "ERR_UNAUTHORIZED",
                       "Role not permitted for this endpoint")
    return uid, role


def body():
    raw = request.get_data()
    if raw is None or len(raw.strip()) == 0:
        return {}
    data = request.get_json(force=True, silent=True)
    if data is None:
        raise err_validation("Request body must be valid JSON")
    if not isinstance(data, dict):
        raise err_validation("Request body must be a JSON object")
    return data


def req_str(data, field):
    v = data.get(field)
    if not isinstance(v, str) or v == "":
        raise err_validation("%s is required and must be a non-empty string" % field)
    return v


def req_int(data, field, minimum=None, maximum=None):
    v = data.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise err_validation("%s is required and must be an integer" % field)
    if minimum is not None and v < minimum:
        raise err_validation("%s is out of range" % field)
    if maximum is not None and v > maximum:
        raise err_validation("%s is out of range" % field)
    return v


def opt_int(data, field, default=None, minimum=None, maximum=None):
    if field not in data or data.get(field) is None:
        return default
    return req_int(data, field, minimum=minimum, maximum=maximum)


def opt_bool(data, field, default=False):
    if field not in data or data.get(field) is None:
        return default
    v = data.get(field)
    if not isinstance(v, bool):
        raise err_validation("%s must be a boolean" % field)
    return v


def req_enum(data, field, allowed):
    v = data.get(field)
    if not isinstance(v, str) or v not in allowed:
        raise err_validation("%s must be one of %s" % (field, sorted(allowed)))
    return v


def req_datetime(data, field):
    if field not in data or data.get(field) is None:
        raise err_validation("%s is required" % field)
    return pdt(data.get(field), field)


def opt_nullable_int(data, field, minimum=None):
    """Field must be present; null is allowed (returns None)."""
    if field not in data:
        raise err_validation("%s is required" % field)
    v = data.get(field)
    if v is None:
        return None
    return req_int(data, field, minimum=minimum)


def pagination_params():
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        if not re.fullmatch(r"-?\d+", raw_limit.strip()):
            raise err_validation("limit must be an integer")
        limit = int(raw_limit)
        if limit < 1 or limit > 100:
            raise err_validation("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        if not re.fullmatch(r"-?\d+", raw_offset.strip()):
            raise err_validation("offset must be an integer")
        offset = int(raw_offset)
        if offset < 0:
            raise err_validation("offset must be >= 0")
    return limit, offset


def filter_enum(name, allowed):
    v = request.args.get(name)
    if v is None:
        return None
    if v not in allowed:
        raise err_validation("%s must be one of %s" % (name, sorted(allowed)))
    return v


def filter_bool(name):
    v = request.args.get(name)
    if v is None:
        return None
    low = v.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    raise err_validation("%s must be true or false" % name)


def paged(records, serializer):
    limit, offset = pagination_params()
    ordered = sorted(records, key=lambda r: (r["created_at"], r["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return ok_list([serializer(r) for r in page], limit, offset, total)


def get_or_404(collection, rid):
    rec = STORE[collection].get(rid)
    if rec is None:
        raise err_not_found()
    return rec


def check_rep_owns(uid, role, subscriber_id):
    if role == "SubscriberRep" and uid != subscriber_id:
        raise ApiError(403, "ERR_FORBIDDEN_CROSS_ACCOUNT",
                       "SubscriberRep may only access own subscriber's resources")


# =====================================================================
# Serializers
# =====================================================================
def ser_package(p):
    return {
        "id": p["id"],
        "code": p["code"],
        "display_name": p["display_name"],
        "media_rights": p["media_rights"],
        "base_monthly_fee_cents": p["base_monthly_fee_cents"],
        "status": p["status"],
        "created_at": rdt(p["created_at"]),
        "updated_at": rdt(p["updated_at"]),
        "version": p["version"],
    }


def ser_tier(t):
    return {
        "id": t["id"],
        "code": t["code"],
        "min_audience": t["min_audience"],
        "max_audience": t["max_audience"],
        "circulation_multiplier_basis_points": t["circulation_multiplier_basis_points"],
        "monthly_republish_quota": t["monthly_republish_quota"],
        "overage_per_article_cents": t["overage_per_article_cents"],
        "member_discount_pct": t["member_discount_pct"],
        "status": t["status"],
        "created_at": rdt(t["created_at"]),
        "updated_at": rdt(t["updated_at"]),
        "version": t["version"],
    }


def ser_feed(f):
    return {
        "id": f["id"],
        "code": f["code"],
        "topic": f["topic"],
        "embargo_window_minutes": f["embargo_window_minutes"],
        "status": f["status"],
        "created_at": rdt(f["created_at"]),
        "updated_at": rdt(f["updated_at"]),
        "version": f["version"],
    }


def ser_subscriber(s):
    return {
        "id": s["id"],
        "legal_name": s["legal_name"],
        "billing_email": s["billing_email"],
        "declared_audience": s["declared_audience"],
        "is_member": s["is_member"],
        "member_credit_balance_cents": s["member_credit_balance_cents"],
        "status": s["status"],
        "termination_notice_at": rdt(s["termination_notice_at"]),
        "termination_effective_at": rdt(s["termination_effective_at"]),
        "created_at": rdt(s["created_at"]),
        "updated_at": rdt(s["updated_at"]),
        "version": s["version"],
    }


def ser_subscription(sub):
    # months_used_current_period is derived from the logical clock and the
    # current period anchor (start_at or the last renewal boundary).
    sub["months_used_current_period"] = whole_months_between(
        sub["_period_start"], CLOCK["current_utc"])
    return {
        "id": sub["id"],
        "subscriber_id": sub["subscriber_id"],
        "package_id": sub["package_id"],
        "tier_id": sub["tier_id"],
        "monthly_price_cents": sub["monthly_price_cents"],
        "start_at": rdt(sub["start_at"]),
        "renewal_due_at": rdt(sub["renewal_due_at"]),
        "renewal_notice_sent_at": rdt(sub["renewal_notice_sent_at"]),
        "months_used_current_period": sub["months_used_current_period"],
        "republish_count_current_month": sub["republish_count_current_month"],
        "current_month_bucket": sub["current_month_bucket"],
        "status": sub["status"],
        "created_at": rdt(sub["created_at"]),
        "updated_at": rdt(sub["updated_at"]),
        "version": sub["version"],
    }


def ser_entitlement(e):
    return {
        "id": e["id"],
        "subscription_id": e["subscription_id"],
        "feed_id": e["feed_id"],
        "granted_at": rdt(e["granted_at"]),
        "revoked_at": rdt(e["revoked_at"]),
        "status": e["status"],
        "created_at": rdt(e["created_at"]),
        "updated_at": rdt(e["updated_at"]),
        "version": e["version"],
    }


def ser_article(a):
    return {
        "id": a["id"],
        "feed_id": a["feed_id"],
        "headline": a["headline"],
        "body_word_count": a["body_word_count"],
        "slug": a["slug"],
        "published_at": rdt(a["published_at"]),
        "embargo_until": rdt(a["embargo_until"]),
        "embargo_status": a["embargo_status"],
        "contributing_member_subscriber_id": a["contributing_member_subscriber_id"],
        "member_credit_cents": a["member_credit_cents"],
        "status": a["status"],
        "created_at": rdt(a["created_at"]),
        "updated_at": rdt(a["updated_at"]),
        "version": a["version"],
    }


def ser_asset(a):
    return {
        "id": a["id"],
        "article_id": a["article_id"],
        "kind": a["kind"],
        "rights_scope": a["rights_scope"],
        "file_ref": a["file_ref"],
        "status": a["status"],
        "created_at": rdt(a["created_at"]),
        "updated_at": rdt(a["updated_at"]),
        "version": a["version"],
    }


def ser_publication(p):
    return {
        "id": p["id"],
        "subscriber_id": p["subscriber_id"],
        "subscription_id": p["subscription_id"],
        "article_id": p["article_id"],
        "republished_at": rdt(p["republished_at"]),
        "billed_amount_cents": p["billed_amount_cents"],
        "within_quota": p["within_quota"],
        "status": p["status"],
        "created_at": rdt(p["created_at"]),
        "updated_at": rdt(p["updated_at"]),
        "version": p["version"],
    }


def ser_invoice(inv):
    return {
        "id": inv["id"],
        "subscriber_id": inv["subscriber_id"],
        "subscription_id": inv["subscription_id"],
        "billing_month": inv["billing_month"],
        "base_fee_cents": inv["base_fee_cents"],
        "overage_cents": inv["overage_cents"],
        "member_credit_applied_cents": inv["member_credit_applied_cents"],
        "total_due_cents": inv["total_due_cents"],
        "provisional_total_due_cents": inv["provisional_total_due_cents"],
        "status": inv["status"],
        "created_at": rdt(inv["created_at"]),
        "updated_at": rdt(inv["updated_at"]),
        "version": inv["version"],
    }


def ser_checkpoint():
    return {
        "id": CHECKPOINT["id"],
        "created_at": rdt(CHECKPOINT["created_at"]),
        "current_utc": rdt(CLOCK["current_utc"]),
    }


# =====================================================================
# Business helpers
# =====================================================================
def revoke_entitlements_for(subscription_id):
    now = CLOCK["current_utc"]
    for e in STORE["entitlements"].values():
        if e["subscription_id"] == subscription_id and e["status"] == "LIVE":
            e["status"] = "REVOKED"
            e["revoked_at"] = now
            bump(e)


def expiry_sweep():
    now = CLOCK["current_utc"]
    for sub in STORE["subscriptions"].values():
        if (sub["status"] == "ACTIVE"
                and sub["renewal_due_at"] is not None
                and now >= sub["renewal_due_at"]):
            sub["status"] = "EXPIRED"
            bump(sub)
            revoke_entitlements_for(sub["id"])


def matching_active_tiers(audience):
    return [t for t in STORE["tiers"].values()
            if t["status"] == "ACTIVE"
            and t["min_audience"] <= audience
            and (t["max_audience"] is None or audience < t["max_audience"])]


def price_monthly(package, tier, subscriber):
    gross = round_half_up_int(
        package["base_monthly_fee_cents"]
        * tier["circulation_multiplier_basis_points"], 10000)
    if subscriber["is_member"] and tier["member_discount_pct"] > 0:
        discount = round_half_up_int(gross * tier["member_discount_pct"], 100)
    else:
        discount = 0
    return gross - discount


def member_credit_for(article):
    words = article["body_word_count"]
    if words < 400:
        base = 2000
    elif words < 900:
        base = 5000
    elif words < 1500:
        base = 9000
    else:
        base = 14000
    photos = sum(1 for a in STORE["assets"].values()
                 if a["article_id"] == article["id"] and a["kind"] == "PHOTO")
    videos = sum(1 for a in STORE["assets"].values()
                 if a["article_id"] == article["id"] and a["kind"] == "VIDEO")
    return base + 1500 * photos + 4000 * videos


# =====================================================================
# Logical clock
# =====================================================================
@app.route("/wire/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"PlatformAdmin"})
    data = body()
    new_time = req_datetime(data, "to_iso8601")
    CLOCK["current_utc"] = new_time
    expiry_sweep()
    return ok_object(ser_checkpoint(), 200)


# =====================================================================
# Content packages
# =====================================================================
@app.route("/wire/packages", methods=["POST"])
def create_package():
    authenticate({"PlatformAdmin"})
    data = body()
    code = req_str(data, "code")
    display_name = req_str(data, "display_name")
    media_rights = req_enum(data, "media_rights", MEDIA_RIGHTS)
    base_fee = req_int(data, "base_monthly_fee_cents", minimum=0)
    if any(p["code"] == code for p in STORE["packages"].values()):
        raise err_validation("code must be unique")
    rec = make_record()
    rec.update({
        "code": code,
        "display_name": display_name,
        "media_rights": media_rights,
        "base_monthly_fee_cents": base_fee,
        "status": "ACTIVE",
    })
    STORE["packages"][rec["id"]] = rec
    return ok_object(ser_package(rec), 201)


@app.route("/wire/packages", methods=["GET"])
def list_packages():
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    status = filter_enum("status", PACKAGE_STATUSES)
    recs = [p for p in STORE["packages"].values()
            if status is None or p["status"] == status]
    return paged(recs, ser_package)


@app.route("/wire/packages/<pid>", methods=["GET"])
def get_package(pid):
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    return ok_object(ser_package(get_or_404("packages", pid)), 200)


@app.route("/wire/packages/<pid>/retire", methods=["POST"])
def retire_package(pid):
    authenticate({"PlatformAdmin"})
    rec = get_or_404("packages", pid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("Package is not ACTIVE")
    rec["status"] = "RETIRED"
    bump(rec)
    return ok_object(ser_package(rec), 200)


# =====================================================================
# Subscriber tiers
# =====================================================================
@app.route("/wire/tiers", methods=["POST"])
def create_tier():
    authenticate({"PlatformAdmin"})
    data = body()
    code = req_str(data, "code")
    min_aud = req_int(data, "min_audience", minimum=0)
    max_aud = opt_nullable_int(data, "max_audience", minimum=0)
    mult = req_int(data, "circulation_multiplier_basis_points", minimum=0)
    quota = req_int(data, "monthly_republish_quota", minimum=0)
    overage = req_int(data, "overage_per_article_cents", minimum=0)
    discount = opt_int(data, "member_discount_pct", default=0, minimum=0, maximum=90)
    if any(t["code"] == code for t in STORE["tiers"].values()):
        raise err_validation("code must be unique")
    rec = make_record()
    rec.update({
        "code": code,
        "min_audience": min_aud,
        "max_audience": max_aud,
        "circulation_multiplier_basis_points": mult,
        "monthly_republish_quota": quota,
        "overage_per_article_cents": overage,
        "member_discount_pct": discount,
        "status": "ACTIVE",
    })
    STORE["tiers"][rec["id"]] = rec
    return ok_object(ser_tier(rec), 201)


@app.route("/wire/tiers", methods=["GET"])
def list_tiers():
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    status = filter_enum("status", TIER_STATUSES)
    recs = [t for t in STORE["tiers"].values()
            if status is None or t["status"] == status]
    return paged(recs, ser_tier)


@app.route("/wire/tiers/<tid>", methods=["GET"])
def get_tier(tid):
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    return ok_object(ser_tier(get_or_404("tiers", tid)), 200)


@app.route("/wire/tiers/<tid>/retire", methods=["POST"])
def retire_tier(tid):
    authenticate({"PlatformAdmin"})
    rec = get_or_404("tiers", tid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("SubscriberTier is not ACTIVE")
    rec["status"] = "RETIRED"
    bump(rec)
    return ok_object(ser_tier(rec), 200)


# =====================================================================
# Feeds
# =====================================================================
@app.route("/wire/feeds", methods=["POST"])
def create_feed():
    authenticate({"PlatformAdmin"})
    data = body()
    code = req_str(data, "code")
    topic = req_enum(data, "topic", TOPICS)
    window = req_int(data, "embargo_window_minutes", minimum=0)
    if any(f["code"] == code for f in STORE["feeds"].values()):
        raise err_validation("code must be unique")
    rec = make_record()
    rec.update({
        "code": code,
        "topic": topic,
        "embargo_window_minutes": window,
        "status": "LIVE",
    })
    STORE["feeds"][rec["id"]] = rec
    return ok_object(ser_feed(rec), 201)


@app.route("/wire/feeds", methods=["GET"])
def list_feeds():
    authenticate({"PlatformAdmin", "SalesOps", "Editor", "Auditor"})
    status = filter_enum("status", FEED_STATUSES)
    recs = [f for f in STORE["feeds"].values()
            if status is None or f["status"] == status]
    return paged(recs, ser_feed)


@app.route("/wire/feeds/<fid>", methods=["GET"])
def get_feed(fid):
    authenticate({"PlatformAdmin", "SalesOps", "Editor", "Auditor"})
    return ok_object(ser_feed(get_or_404("feeds", fid)), 200)


# =====================================================================
# Subscribers
# =====================================================================
@app.route("/wire/subscribers", methods=["POST"])
def create_subscriber():
    authenticate({"SalesOps"})
    data = body()
    legal_name = req_str(data, "legal_name")
    billing_email = req_str(data, "billing_email")
    audience = req_int(data, "declared_audience", minimum=0)
    is_member = opt_bool(data, "is_member", default=False)
    rec = make_record()
    rec.update({
        "legal_name": legal_name,
        "billing_email": billing_email,
        "declared_audience": audience,
        "is_member": is_member,
        "member_credit_balance_cents": 0,
        "status": "ACTIVE",
        "termination_notice_at": None,
        "termination_effective_at": None,
    })
    STORE["subscribers"][rec["id"]] = rec
    return ok_object(ser_subscriber(rec), 201)


@app.route("/wire/subscribers", methods=["GET"])
def list_subscribers():
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    status = filter_enum("status", SUBSCRIBER_STATUSES)
    is_member = filter_bool("is_member")
    recs = [s for s in STORE["subscribers"].values()
            if (status is None or s["status"] == status)
            and (is_member is None or s["is_member"] == is_member)]
    return paged(recs, ser_subscriber)


@app.route("/wire/subscribers/<sid>", methods=["GET"])
def get_subscriber(sid):
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    return ok_object(ser_subscriber(get_or_404("subscribers", sid)), 200)


@app.route("/wire/subscribers/<sid>/suspend", methods=["POST"])
def suspend_subscriber(sid):
    authenticate({"SalesOps"})
    rec = get_or_404("subscribers", sid)
    if rec["status"] != "ACTIVE":
        raise err_invalid_state("Subscriber is not ACTIVE")
    rec["status"] = "SUSPENDED"
    bump(rec)
    for sub in STORE["subscriptions"].values():
        if (sub["subscriber_id"] == sid
                and sub["status"] in ("ACTIVE", "DRAFT")):
            sub["status"] = "SUSPENDED"
            bump(sub)
            revoke_entitlements_for(sub["id"])
    return ok_object(ser_subscriber(rec), 200)


@app.route("/wire/subscribers/<sid>/reinstate", methods=["POST"])
def reinstate_subscriber(sid):
    authenticate({"SalesOps"})
    rec = get_or_404("subscribers", sid)
    if rec["status"] != "SUSPENDED":
        raise err_invalid_state("Subscriber is not SUSPENDED")
    rec["status"] = "ACTIVE"
    bump(rec)
    return ok_object(ser_subscriber(rec), 200)


@app.route("/wire/subscribers/<sid>/give-termination-notice", methods=["POST"])
def give_termination_notice(sid):
    authenticate({"SalesOps"})
    rec = get_or_404("subscribers", sid)
    if rec["status"] == "TERMINATED":
        raise err_invalid_state("Subscriber is TERMINATED")
    now = CLOCK["current_utc"]
    rec["termination_notice_at"] = now
    rec["termination_effective_at"] = now + timedelta(days=30)
    bump(rec)
    return ok_object(ser_subscriber(rec), 200)


@app.route("/wire/subscribers/<sid>/terminate", methods=["POST"])
def terminate_subscriber(sid):
    authenticate({"SalesOps"})
    rec = get_or_404("subscribers", sid)
    if rec["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Subscriber is TERMINATED")
    effective = rec["termination_effective_at"]
    now = CLOCK["current_utc"]
    if effective is None or now < effective:
        raise ApiError(422, "ERR_TEMPORAL_VIOLATION",
                       "Termination requires the 30-day notice period to elapse")
    rec["status"] = "TERMINATED"
    bump(rec)
    for sub in STORE["subscriptions"].values():
        if (sub["subscriber_id"] == sid
                and sub["status"] not in ("CANCELLED", "EXPIRED")):
            sub["status"] = "CANCELLED"
            bump(sub)
            revoke_entitlements_for(sub["id"])
    for inv in STORE["invoices"].values():
        if inv["subscriber_id"] == sid and inv["status"] == "DRAFT":
            inv["status"] = "VOIDED"
            bump(inv)
    return ok_object(ser_subscriber(rec), 200)


# =====================================================================
# Subscriptions
# =====================================================================
@app.route("/wire/subscribers/<sid>/subscriptions", methods=["POST"])
def create_subscription(sid):
    authenticate({"SalesOps"})
    subscriber = get_or_404("subscribers", sid)
    data = body()
    if "package_id" not in data or data.get("package_id") is None:
        raise err_validation("package_id is required")
    package_id = data.get("package_id")
    if not isinstance(package_id, str):
        raise err_validation("package_id must be a string")
    start_at = req_datetime(data, "start_at")
    get_or_404("packages", package_id)
    rec = make_record()
    rec.update({
        "subscriber_id": subscriber["id"],
        "package_id": package_id,
        "tier_id": None,
        "monthly_price_cents": None,
        "start_at": start_at,
        "renewal_due_at": None,
        "renewal_notice_sent_at": None,
        "months_used_current_period": 0,
        "republish_count_current_month": 0,
        "current_month_bucket": None,
        "status": "DRAFT",
        "_period_start": start_at,
    })
    STORE["subscriptions"][rec["id"]] = rec
    return ok_object(ser_subscription(rec), 201)


@app.route("/wire/subscribers/<sid>/subscriptions", methods=["GET"])
def list_subscriber_subscriptions(sid):
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    get_or_404("subscribers", sid)
    status = filter_enum("status", SUBSCRIPTION_STATUSES)
    recs = [s for s in STORE["subscriptions"].values()
            if s["subscriber_id"] == sid
            and (status is None or s["status"] == status)]
    return paged(recs, ser_subscription)


@app.route("/wire/subscriptions", methods=["GET"])
def list_subscriptions():
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    status = filter_enum("status", SUBSCRIPTION_STATUSES)
    subscriber_id = request.args.get("subscriber_id")
    package_id = request.args.get("package_id")
    tier_id = request.args.get("tier_id")
    recs = [s for s in STORE["subscriptions"].values()
            if (status is None or s["status"] == status)
            and (subscriber_id is None or s["subscriber_id"] == subscriber_id)
            and (package_id is None or s["package_id"] == package_id)
            and (tier_id is None or s["tier_id"] == tier_id)]
    return paged(recs, ser_subscription)


@app.route("/wire/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    uid, role = authenticate(
        {"PlatformAdmin", "SalesOps", "Auditor", "Billing", "SubscriberRep"})
    sub = get_or_404("subscriptions", sid)
    check_rep_owns(uid, role, sub["subscriber_id"])
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    data = body()
    expected = req_int(data, "expected_subscriber_version")
    if sub["status"] != "DRAFT":
        raise err_invalid_state("Subscription is not DRAFT")
    subscriber = STORE["subscribers"][sub["subscriber_id"]]
    if subscriber["status"] != "ACTIVE":
        raise err_invalid_state("Subscriber is not ACTIVE")
    package = STORE["packages"][sub["package_id"]]
    if package["status"] != "ACTIVE":
        raise err_invalid_state("Package is not ACTIVE")
    candidates = matching_active_tiers(subscriber["declared_audience"])
    if len(candidates) > 1:
        raise ApiError(422, "ERR_AMBIGUOUS_TIER",
                       "More than one ACTIVE tier matches declared_audience")
    if len(candidates) == 0:
        raise ApiError(422, "ERR_NO_MATCHING_TIER",
                       "No ACTIVE tier matches declared_audience")
    if expected != subscriber["version"]:
        raise ApiError(412, "ERR_STALE_VERSION",
                       "expected_subscriber_version does not match subscriber version")
    tier = candidates[0]
    sub["tier_id"] = tier["id"]
    sub["monthly_price_cents"] = price_monthly(package, tier, subscriber)
    sub["renewal_due_at"] = add_months(sub["start_at"], 12)
    sub["current_month_bucket"] = month_bucket(sub["start_at"])
    sub["status"] = "ACTIVE"
    bump(sub)
    bump(subscriber)
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/suspend", methods=["POST"])
def suspend_subscription(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    if sub["status"] != "ACTIVE":
        raise err_invalid_state("Subscription is not ACTIVE")
    subscriber = STORE["subscribers"][sub["subscriber_id"]]
    if subscriber["status"] != "ACTIVE":
        raise err_invalid_state("Subscriber is not ACTIVE")
    sub["status"] = "SUSPENDED"
    bump(sub)
    revoke_entitlements_for(sub["id"])
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/reinstate", methods=["POST"])
def reinstate_subscription(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    if sub["status"] != "SUSPENDED":
        raise err_invalid_state("Subscription is not SUSPENDED")
    subscriber = STORE["subscribers"][sub["subscriber_id"]]
    if subscriber["status"] != "ACTIVE":
        raise err_invalid_state("Subscriber is not ACTIVE")
    sub["status"] = "ACTIVE"
    bump(sub)
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    if sub["status"] not in ("ACTIVE", "SUSPENDED"):
        raise err_invalid_state("Subscription is not ACTIVE or SUSPENDED")
    if sub["status"] == "ACTIVE":
        subscriber = STORE["subscribers"][sub["subscriber_id"]]
        if subscriber["status"] not in ("ACTIVE", "SUSPENDED"):
            raise err_invalid_state("Subscriber is not ACTIVE or SUSPENDED")
    months_used = whole_months_between(sub["_period_start"], CLOCK["current_utc"])
    if months_used < 3:
        raise ApiError(422, "ERR_MIN_COMMITMENT_NOT_MET",
                       "Subscription minimum commitment of 3 months not met")
    was_active = sub["status"] == "ACTIVE"
    sub["status"] = "CANCELLED"
    bump(sub)
    if was_active:
        revoke_entitlements_for(sub["id"])
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/renew", methods=["POST"])
def renew_subscription(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    if sub["status"] != "ACTIVE":
        raise err_invalid_state("Subscription is not ACTIVE")
    old_due = sub["renewal_due_at"]
    sub["renewal_due_at"] = add_months(old_due, 12)
    sub["_period_start"] = old_due
    sub["months_used_current_period"] = 0
    bump(sub)
    return ok_object(ser_subscription(sub), 200)


@app.route("/wire/subscriptions/<sid>/send-renewal-notice", methods=["POST"])
def send_renewal_notice(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    if sub["status"] != "ACTIVE":
        raise err_invalid_state("Subscription is not ACTIVE")
    now = CLOCK["current_utc"]
    if now > sub["renewal_due_at"] - timedelta(days=60):
        raise ApiError(422, "ERR_TEMPORAL_VIOLATION",
                       "Renewal notice must be sent at least 60 days before renewal_due_at")
    sub["renewal_notice_sent_at"] = now
    bump(sub)
    return ok_object(ser_subscription(sub), 200)


# =====================================================================
# Entitlements
# =====================================================================
@app.route("/wire/subscriptions/<sid>/entitlements", methods=["POST"])
def grant_entitlement(sid):
    authenticate({"SalesOps"})
    sub = get_or_404("subscriptions", sid)
    data = body()
    if "feed_id" not in data or data.get("feed_id") is None:
        raise err_validation("feed_id is required")
    feed_id = data.get("feed_id")
    if not isinstance(feed_id, str):
        raise err_validation("feed_id must be a string")
    get_or_404("feeds", feed_id)
    rec = make_record()
    rec.update({
        "subscription_id": sub["id"],
        "feed_id": feed_id,
        "granted_at": CLOCK["current_utc"],
        "revoked_at": None,
        "status": "LIVE",
    })
    STORE["entitlements"][rec["id"]] = rec
    return ok_object(ser_entitlement(rec), 201)


@app.route("/wire/subscriptions/<sid>/entitlements", methods=["GET"])
def list_subscription_entitlements(sid):
    uid, role = authenticate(
        {"PlatformAdmin", "SalesOps", "Auditor", "Billing", "SubscriberRep"})
    sub = get_or_404("subscriptions", sid)
    check_rep_owns(uid, role, sub["subscriber_id"])
    status = filter_enum("status", ENTITLEMENT_STATUSES)
    recs = [e for e in STORE["entitlements"].values()
            if e["subscription_id"] == sid
            and (status is None or e["status"] == status)]
    return paged(recs, ser_entitlement)


@app.route("/wire/entitlements", methods=["GET"])
def list_entitlements():
    authenticate({"PlatformAdmin", "SalesOps", "Auditor", "Billing"})
    status = filter_enum("status", ENTITLEMENT_STATUSES)
    subscription_id = request.args.get("subscription_id")
    feed_id = request.args.get("feed_id")
    recs = [e for e in STORE["entitlements"].values()
            if (status is None or e["status"] == status)
            and (subscription_id is None or e["subscription_id"] == subscription_id)
            and (feed_id is None or e["feed_id"] == feed_id)]
    return paged(recs, ser_entitlement)


@app.route("/wire/entitlements/<eid>", methods=["GET"])
def get_entitlement(eid):
    uid, role = authenticate(
        {"PlatformAdmin", "SalesOps", "Auditor", "Billing", "SubscriberRep"})
    ent = get_or_404("entitlements", eid)
    sub = STORE["subscriptions"].get(ent["subscription_id"])
    if sub is not None:
        check_rep_owns(uid, role, sub["subscriber_id"])
    return ok_object(ser_entitlement(ent), 200)


@app.route("/wire/entitlements/<eid>/revoke", methods=["POST"])
def revoke_entitlement(eid):
    authenticate({"SalesOps"})
    ent = get_or_404("entitlements", eid)
    if ent["status"] != "LIVE":
        raise err_invalid_state("Entitlement is not LIVE")
    ent["status"] = "REVOKED"
    ent["revoked_at"] = CLOCK["current_utc"]
    bump(ent)
    return ok_object(ser_entitlement(ent), 200)


# =====================================================================
# Articles
# =====================================================================
@app.route("/wire/articles", methods=["POST"])
def create_article():
    authenticate({"Editor"})
    data = body()
    if "feed_id" not in data or data.get("feed_id") is None:
        raise err_validation("feed_id is required")
    feed_id = data.get("feed_id")
    if not isinstance(feed_id, str):
        raise err_validation("feed_id must be a string")
    headline = req_str(data, "headline")
    word_count = req_int(data, "body_word_count", minimum=0)
    slug = req_str(data, "slug")
    contributor = data.get("contributing_member_subscriber_id")
    if contributor is not None and not isinstance(contributor, str):
        raise err_validation("contributing_member_subscriber_id must be a string")
    get_or_404("feeds", feed_id)
    if contributor is not None:
        get_or_404("subscribers", contributor)
    if any(a["slug"] == slug for a in STORE["articles"].values()):
        raise err_validation("slug must be unique")
    rec = make_record()
    rec.update({
        "feed_id": feed_id,
        "headline": headline,
        "body_word_count": word_count,
        "slug": slug,
        "published_at": None,
        "embargo_until": None,
        "embargo_status": None,
        "contributing_member_subscriber_id": contributor,
        "member_credit_cents": None,
        "status": "DRAFT",
    })
    STORE["articles"][rec["id"]] = rec
    return ok_object(ser_article(rec), 201)


@app.route("/wire/articles", methods=["GET"])
def list_articles():
    authenticate({"PlatformAdmin", "Editor", "Auditor", "Legal"})
    status = filter_enum("status", ARTICLE_STATUSES)
    embargo_status = filter_enum("embargo_status", EMBARGO_STATUSES)
    feed_id = request.args.get("feed_id")
    contributor = request.args.get("contributing_member_subscriber_id")
    recs = [a for a in STORE["articles"].values()
            if (status is None or a["status"] == status)
            and (embargo_status is None or a["embargo_status"] == embargo_status)
            and (feed_id is None or a["feed_id"] == feed_id)
            and (contributor is None
                 or a["contributing_member_subscriber_id"] == contributor)]
    return paged(recs, ser_article)


@app.route("/wire/articles/<aid>", methods=["GET"])
def get_article(aid):
    authenticate({"PlatformAdmin", "Editor", "Auditor", "Legal", "SubscriberRep"})
    return ok_object(ser_article(get_or_404("articles", aid)), 200)


def _apply_publish(rec):
    feed = STORE["feeds"][rec["feed_id"]]
    now = CLOCK["current_utc"]
    rec["published_at"] = now
    rec["embargo_until"] = now + timedelta(minutes=feed["embargo_window_minutes"])
    rec["embargo_status"] = ("EMBARGOED" if rec["embargo_until"] > now
                             else "CLEAR")


@app.route("/wire/articles/<aid>/publish", methods=["POST"])
def publish_article(aid):
    authenticate({"Editor"})
    rec = get_or_404("articles", aid)
    if rec["status"] != "DRAFT":
        raise err_invalid_state("Article is not DRAFT")
    feed = STORE["feeds"][rec["feed_id"]]
    if feed["status"] != "LIVE":
        raise err_invalid_state("Feed is not LIVE")
    rec["status"] = "PUBLISHED"
    _apply_publish(rec)
    contributor_id = rec["contributing_member_subscriber_id"]
    if contributor_id is not None:
        member = STORE["subscribers"].get(contributor_id)
        if member is not None and member["is_member"]:
            credit = member_credit_for(rec)
            rec["member_credit_cents"] = credit
            member["member_credit_balance_cents"] += credit
            bump(member)
    bump(rec)
    return ok_object(ser_article(rec), 200)


@app.route("/wire/articles/<aid>/embargo", methods=["POST"])
def extend_embargo(aid):
    authenticate({"Editor"})
    rec = get_or_404("articles", aid)
    data = body()
    new_until = req_datetime(data, "new_embargo_until")
    if rec["status"] != "PUBLISHED":
        raise err_invalid_state("Article is not PUBLISHED")
    if rec["embargo_until"] is None or new_until <= rec["embargo_until"]:
        raise ApiError(422, "ERR_TEMPORAL_VIOLATION",
                       "new_embargo_until must be strictly later than current embargo_until")
    rec["embargo_until"] = new_until
    rec["embargo_status"] = "EMBARGOED"
    bump(rec)
    return ok_object(ser_article(rec), 200)


@app.route("/wire/articles/<aid>/lift-embargo", methods=["POST"])
def lift_embargo(aid):
    authenticate({"Editor"})
    rec = get_or_404("articles", aid)
    if rec["status"] != "PUBLISHED":
        raise err_invalid_state("Article is not PUBLISHED")
    if rec["embargo_status"] != "EMBARGOED":
        raise err_invalid_state("Article embargo_status is not EMBARGOED")
    rec["embargo_status"] = "EMBARGO_LIFTED"
    bump(rec)
    return ok_object(ser_article(rec), 200)


@app.route("/wire/articles/<aid>/withdraw", methods=["POST"])
def withdraw_article(aid):
    authenticate({"Editor"})
    rec = get_or_404("articles", aid)
    if rec["status"] != "PUBLISHED":
        raise err_invalid_state("Article is not PUBLISHED")
    rec["status"] = "WITHDRAWN"
    bump(rec)
    for pub in STORE["publications"].values():
        if pub["article_id"] == aid and pub["status"] == "RECORDED":
            pub["status"] = "AUDIT_FLAGGED"
            bump(pub)
    return ok_object(ser_article(rec), 200)


@app.route("/wire/articles/<aid>/republish", methods=["POST"])
def republish_article(aid):
    authenticate({"Editor"})
    rec = get_or_404("articles", aid)
    data = body()
    expected = req_int(data, "expected_article_version")
    if rec["status"] != "WITHDRAWN":
        raise err_invalid_state("Article is not WITHDRAWN")
    if expected != rec["version"]:
        raise ApiError(412, "ERR_STALE_VERSION",
                       "expected_article_version does not match article version")
    rec["status"] = "PUBLISHED"
    _apply_publish(rec)
    bump(rec)
    return ok_object(ser_article(rec), 200)


@app.route("/wire/articles/<aid>/takedown", methods=["POST"])
def takedown_article(aid):
    authenticate({"Legal"})
    rec = get_or_404("articles", aid)
    if rec["status"] not in ("PUBLISHED", "WITHDRAWN"):
        raise err_invalid_state("Article is not PUBLISHED or WITHDRAWN")
    rec["status"] = "TAKEN_DOWN"
    bump(rec)
    for asset in STORE["assets"].values():
        if asset["article_id"] == aid and asset["status"] != "TAKEN_DOWN":
            asset["status"] = "TAKEN_DOWN"
            bump(asset)
    for pub in STORE["publications"].values():
        if pub["article_id"] == aid and pub["status"] != "AUDIT_FLAGGED":
            pub["status"] = "AUDIT_FLAGGED"
            bump(pub)
    contributor_id = rec["contributing_member_subscriber_id"]
    credit = rec["member_credit_cents"] or 0
    if contributor_id is not None and credit > 0:
        member = STORE["subscribers"].get(contributor_id)
        if member is not None:
            new_balance = max(0, member["member_credit_balance_cents"] - credit)
            if new_balance != member["member_credit_balance_cents"]:
                member["member_credit_balance_cents"] = new_balance
                bump(member)
    return ok_object(ser_article(rec), 200)


# =====================================================================
# Assets
# =====================================================================
@app.route("/wire/articles/<aid>/assets", methods=["POST"])
def create_asset(aid):
    authenticate({"Editor"})
    article = get_or_404("articles", aid)
    data = body()
    kind = req_enum(data, "kind", ASSET_KINDS)
    rights_scope = req_enum(data, "rights_scope", RIGHTS_SCOPES)
    file_ref = req_str(data, "file_ref")
    rec = make_record()
    rec.update({
        "article_id": article["id"],
        "kind": kind,
        "rights_scope": rights_scope,
        "file_ref": file_ref,
        "status": "ACTIVE",
    })
    STORE["assets"][rec["id"]] = rec
    return ok_object(ser_asset(rec), 201)


@app.route("/wire/articles/<aid>/assets", methods=["GET"])
def list_article_assets(aid):
    authenticate({"PlatformAdmin", "Editor", "Auditor", "Legal"})
    get_or_404("articles", aid)
    kind = filter_enum("kind", ASSET_KINDS)
    status = filter_enum("status", ASSET_STATUSES)
    recs = [a for a in STORE["assets"].values()
            if a["article_id"] == aid
            and (kind is None or a["kind"] == kind)
            and (status is None or a["status"] == status)]
    return paged(recs, ser_asset)


@app.route("/wire/assets", methods=["GET"])
def list_assets():
    authenticate({"PlatformAdmin", "Editor", "Auditor", "Legal"})
    kind = filter_enum("kind", ASSET_KINDS)
    status = filter_enum("status", ASSET_STATUSES)
    article_id = request.args.get("article_id")
    recs = [a for a in STORE["assets"].values()
            if (kind is None or a["kind"] == kind)
            and (status is None or a["status"] == status)
            and (article_id is None or a["article_id"] == article_id)]
    return paged(recs, ser_asset)


# =====================================================================
# Publications
# =====================================================================
@app.route("/wire/publications", methods=["POST"])
def create_publication():
    uid, role = authenticate({"SubscriberRep"})
    data = body()
    if "subscription_id" not in data or data.get("subscription_id") is None:
        raise err_validation("subscription_id is required")
    if "article_id" not in data or data.get("article_id") is None:
        raise err_validation("article_id is required")
    subscription_id = data.get("subscription_id")
    article_id = data.get("article_id")
    if not isinstance(subscription_id, str):
        raise err_validation("subscription_id must be a string")
    if not isinstance(article_id, str):
        raise err_validation("article_id must be a string")
    sub = get_or_404("subscriptions", subscription_id)
    article = get_or_404("articles", article_id)
    # Cross-account ownership applies first among the business checks (PRD §3.6).
    if sub["subscriber_id"] != uid:
        raise ApiError(403, "ERR_FORBIDDEN_CROSS_ACCOUNT",
                       "SubscriberRep may only record republications for own subscriptions")
    now = CLOCK["current_utc"]
    # Temporal gate: still-embargoed copy may not be republished. A lifted
    # embargo permits immediate republication regardless of embargo_until.
    if (article["embargo_status"] == "EMBARGOED"
            and article["embargo_until"] is not None
            and article["embargo_until"] > now):
        raise ApiError(422, "ERR_TEMPORAL_VIOLATION",
                       "Article embargo_until lies in the future")
    # Rights gate: article not TAKEN_DOWN; every asset compatible with the
    # package's media_rights and licensed for syndication (rights_scope WIRE).
    if article["status"] == "TAKEN_DOWN":
        raise ApiError(422, "ERR_RIGHTS_VIOLATION",
                       "Article is TAKEN_DOWN")
    package = STORE["packages"].get(sub["package_id"])
    media_rights = package["media_rights"] if package is not None else None
    for asset in STORE["assets"].values():
        if asset["article_id"] != article["id"]:
            continue
        if asset["rights_scope"] != "WIRE":
            raise ApiError(422, "ERR_RIGHTS_VIOLATION",
                           "Asset rights_scope is excluded from syndication")
        if asset["kind"] == "PHOTO" and media_rights == "TEXT_ONLY":
            raise ApiError(422, "ERR_RIGHTS_VIOLATION",
                           "Package media_rights does not admit photos")
        if asset["kind"] == "VIDEO" and media_rights in ("TEXT_ONLY", "TEXT_AND_PHOTO"):
            raise ApiError(422, "ERR_RIGHTS_VIOLATION",
                           "Package media_rights does not admit video")
    # Entitlement gate.
    entitled = any(
        e["subscription_id"] == sub["id"]
        and e["feed_id"] == article["feed_id"]
        and e["status"] == "LIVE"
        for e in STORE["entitlements"].values())
    if not entitled:
        raise ApiError(422, "ERR_NO_ENTITLEMENT",
                       "No LIVE entitlement for (subscription, feed)")
    # Quota bookkeeping against the resolved tier.
    bucket = month_bucket(now)
    if sub["current_month_bucket"] != bucket:
        sub["republish_count_current_month"] = 0
        sub["current_month_bucket"] = bucket
    sub["republish_count_current_month"] += 1
    tier = STORE["tiers"].get(sub["tier_id"]) if sub["tier_id"] else None
    if tier is not None:
        within_quota = (sub["republish_count_current_month"]
                        <= tier["monthly_republish_quota"])
        billed = 0 if within_quota else tier["overage_per_article_cents"]
    else:
        within_quota = True
        billed = 0
    bump(sub)
    rec = make_record()
    rec.update({
        "subscriber_id": sub["subscriber_id"],
        "subscription_id": sub["id"],
        "article_id": article["id"],
        "republished_at": now,
        "billed_amount_cents": billed,
        "within_quota": within_quota,
        "status": "RECORDED",
    })
    STORE["publications"][rec["id"]] = rec
    return ok_object(ser_publication(rec), 201)


@app.route("/wire/publications", methods=["GET"])
def list_publications():
    uid, role = authenticate({"PlatformAdmin", "Auditor", "Billing", "SubscriberRep"})
    status = filter_enum("status", PUBLICATION_STATUSES)
    subscriber_id = request.args.get("subscriber_id")
    subscription_id = request.args.get("subscription_id")
    article_id = request.args.get("article_id")
    if role == "SubscriberRep":
        if subscriber_id is not None and subscriber_id != uid:
            raise ApiError(403, "ERR_FORBIDDEN_CROSS_ACCOUNT",
                           "SubscriberRep may only list own publications")
        subscriber_id = uid
    recs = [p for p in STORE["publications"].values()
            if (status is None or p["status"] == status)
            and (subscriber_id is None or p["subscriber_id"] == subscriber_id)
            and (subscription_id is None or p["subscription_id"] == subscription_id)
            and (article_id is None or p["article_id"] == article_id)]
    return paged(recs, ser_publication)


@app.route("/wire/publications/<pid>", methods=["GET"])
def get_publication(pid):
    uid, role = authenticate({"PlatformAdmin", "Auditor", "Billing", "SubscriberRep"})
    pub = get_or_404("publications", pid)
    check_rep_owns(uid, role, pub["subscriber_id"])
    return ok_object(ser_publication(pub), 200)


@app.route("/wire/publications/<pid>/flag", methods=["POST"])
def flag_publication(pid):
    authenticate({"Auditor"})
    pub = get_or_404("publications", pid)
    if pub["status"] != "RECORDED":
        raise err_invalid_state("Publication is not RECORDED")
    pub["status"] = "AUDIT_FLAGGED"
    bump(pub)
    return ok_object(ser_publication(pub), 200)


@app.route("/wire/publications/<pid>/dismiss", methods=["POST"])
def dismiss_publication(pid):
    authenticate({"Auditor"})
    pub = get_or_404("publications", pid)
    if pub["status"] != "AUDIT_FLAGGED":
        raise err_invalid_state("Publication is not AUDIT_FLAGGED")
    pub["status"] = "DISMISSED"
    bump(pub)
    if pub["billed_amount_cents"] > 0:
        subscriber = STORE["subscribers"].get(pub["subscriber_id"])
        if subscriber is not None:
            subscriber["member_credit_balance_cents"] += pub["billed_amount_cents"]
            bump(subscriber)
    return ok_object(ser_publication(pub), 200)


# =====================================================================
# Invoices
# =====================================================================
_BILLING_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def _month_range(billing_month):
    year = int(billing_month[:4])
    month = int(billing_month[5:7])
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


@app.route("/wire/subscriptions/<sid>/invoices", methods=["POST"])
def create_invoice(sid):
    authenticate({"Billing"})
    sub = get_or_404("subscriptions", sid)
    data = body()
    billing_month = data.get("billing_month")
    if not isinstance(billing_month, str) or not _BILLING_MONTH_RE.match(billing_month):
        raise err_validation("billing_month must be a YYYY-MM string")
    start, end = _month_range(billing_month)
    overage = sum(
        p["billed_amount_cents"] for p in STORE["publications"].values()
        if p["subscription_id"] == sid
        and p["status"] in ("RECORDED", "AUDIT_FLAGGED")
        and start <= p["republished_at"] < end)
    base_fee = sub["monthly_price_cents"]
    tier = STORE["tiers"].get(sub["tier_id"]) if sub["tier_id"] else None
    package = STORE["packages"].get(sub["package_id"])
    if tier is not None and package is not None:
        gross = round_half_up_int(
            package["base_monthly_fee_cents"]
            * tier["circulation_multiplier_basis_points"], 10000)
        provisional = gross + overage
    else:
        provisional = None
    rec = make_record()
    rec.update({
        "subscriber_id": sub["subscriber_id"],
        "subscription_id": sub["id"],
        "billing_month": billing_month,
        "base_fee_cents": base_fee,
        "overage_cents": overage,
        "member_credit_applied_cents": None,
        "total_due_cents": None,
        "provisional_total_due_cents": provisional,
        "status": "DRAFT",
    })
    STORE["invoices"][rec["id"]] = rec
    return ok_object(ser_invoice(rec), 201)


@app.route("/wire/subscriptions/<sid>/invoices", methods=["GET"])
def list_subscription_invoices(sid):
    uid, role = authenticate({"PlatformAdmin", "Billing", "Auditor", "SubscriberRep"})
    sub = get_or_404("subscriptions", sid)
    check_rep_owns(uid, role, sub["subscriber_id"])
    status = filter_enum("status", INVOICE_STATUSES)
    recs = [i for i in STORE["invoices"].values()
            if i["subscription_id"] == sid
            and (status is None or i["status"] == status)]
    return paged(recs, ser_invoice)


@app.route("/wire/invoices", methods=["GET"])
def list_invoices():
    authenticate({"PlatformAdmin", "Billing", "Auditor"})
    status = filter_enum("status", INVOICE_STATUSES)
    subscriber_id = request.args.get("subscriber_id")
    subscription_id = request.args.get("subscription_id")
    recs = [i for i in STORE["invoices"].values()
            if (status is None or i["status"] == status)
            and (subscriber_id is None or i["subscriber_id"] == subscriber_id)
            and (subscription_id is None or i["subscription_id"] == subscription_id)]
    return paged(recs, ser_invoice)


@app.route("/wire/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    uid, role = authenticate({"PlatformAdmin", "Billing", "Auditor", "SubscriberRep"})
    inv = get_or_404("invoices", iid)
    check_rep_owns(uid, role, inv["subscriber_id"])
    return ok_object(ser_invoice(inv), 200)


@app.route("/wire/invoices/<iid>/issue", methods=["POST"])
def issue_invoice(iid):
    authenticate({"Billing"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise err_invalid_state("Invoice is not DRAFT")
    sub = STORE["subscriptions"].get(inv["subscription_id"])
    if sub is None:
        raise err_not_found()
    if sub["status"] == "DRAFT":
        raise err_invalid_state("Subscription is DRAFT")
    subscriber = STORE["subscribers"].get(inv["subscriber_id"])
    if subscriber is None:
        raise err_not_found()
    gross_due = (inv["base_fee_cents"] or 0) + inv["overage_cents"]
    credit_available = subscriber["member_credit_balance_cents"]
    applied = min(credit_available, gross_due)
    total_due = gross_due - applied
    if total_due < 0 or applied > credit_available:
        raise ApiError(422, "ERR_FISCAL_INCONSISTENCY",
                       "Invoice arithmetic would produce a negative total or over-apply credit")
    inv["member_credit_applied_cents"] = applied
    inv["total_due_cents"] = total_due
    inv["status"] = "ISSUED"
    bump(inv)
    if applied > 0:
        subscriber["member_credit_balance_cents"] -= applied
        bump(subscriber)
    return ok_object(ser_invoice(inv), 200)


@app.route("/wire/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    authenticate({"Billing"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "ISSUED":
        raise err_invalid_state("Invoice is not ISSUED")
    inv["status"] = "PAID"
    bump(inv)
    return ok_object(ser_invoice(inv), 200)


@app.route("/wire/invoices/<iid>/void", methods=["POST"])
def void_invoice(iid):
    authenticate({"Billing"})
    inv = get_or_404("invoices", iid)
    if inv["status"] != "DRAFT":
        raise err_invalid_state("Invoice is not DRAFT")
    inv["status"] = "VOIDED"
    bump(inv)
    return ok_object(ser_invoice(inv), 200)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "10000")))
