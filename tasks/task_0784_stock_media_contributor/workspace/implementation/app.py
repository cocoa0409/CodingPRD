"""Stock-Media Contributor Platform API — Flask entry point.

In-memory only. No seeding at startup. Restarting the process wipes all state.
"""

import functools
import os
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request

from response import ApiError, error, success
from store import db, fmt_ts, new_id, parse_ts

app = Flask(__name__)

# --------------------------------------------------------------------------
# Constants
# --------------------------------------------------------------------------
ROLES = {"Contributor", "Reviewer", "ComplianceOfficer", "FinanceAdmin"}

PAYOUT_THRESHOLD_CENTS = 10000
CLEARING_DAYS = 30
SUSPEND_STRIKE_THRESHOLD = 3
TAKEDOWN_HOLD_DAYS = 90
TAKEDOWN_BUFFER_DAYS = 14
SIMILAR_MAX_DISTANCE = 5

LEVEL_SILVER_MIN = 25000
LEVEL_GOLD_MIN = 100000
LEVEL_PLATINUM_MIN = 500000

DEFAULT_FOREIGN_WITHHOLDING = Decimal("0.30")
EDITORIAL_BONUS = Decimal("0.05")
RATE_CAP = Decimal("0.45")

ROYALTY_MATRIX = {
    "NON_EXCLUSIVE": {
        "BRONZE": Decimal("0.15"),
        "SILVER": Decimal("0.20"),
        "GOLD": Decimal("0.25"),
        "PLATINUM": Decimal("0.30"),
    },
    "EXCLUSIVE": {
        "BRONZE": Decimal("0.25"),
        "SILVER": Decimal("0.30"),
        "GOLD": Decimal("0.35"),
        "PLATINUM": Decimal("0.40"),
    },
}

MEDIA_TYPES = {"PHOTO", "VIDEO", "VECTOR"}
CONTENT_CATEGORIES = {"COMMERCIAL", "EDITORIAL"}
TIER_CODES = {"STANDARD", "ENHANCED", "EXTENDED", "EDITORIAL"}
TAXFORM_TYPES = {"W9", "W8BEN"}
TAXFORM_REJECT_REASONS = {"INVALID_ID", "MISMATCH", "INCOMPLETE"}
RELEASE_TYPES = {"MODEL", "PROPERTY"}
RELEASE_REJECT_REASONS = {"ILLEGIBLE", "UNSIGNED", "EXPIRED"}
ASSET_REJECT_REASONS = {"QUALITY", "SIMILAR", "METADATA", "MISSING_RELEASE"}
CLAIM_TYPES = {"COPYRIGHT", "TRADEMARK", "PRIVACY", "MODEL_RELEASE"}


# --------------------------------------------------------------------------
# Concurrency: serialize all request handling to keep the store consistent.
# --------------------------------------------------------------------------
def synchronized(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        with db.lock:
            return fn(*args, **kwargs)

    return wrapper


# --------------------------------------------------------------------------
# Serialization
# --------------------------------------------------------------------------
def serialize(entity):
    from datetime import datetime as _dt

    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        if isinstance(value, _dt):
            out[key] = fmt_ts(value)
        elif isinstance(value, Decimal):
            out[key] = float(value)
        else:
            out[key] = value
    return out


def serialize_contributor(contributor):
    out = serialize(contributor)
    out["exclusivity"] = compute_exclusivity(contributor["id"])
    return out


# --------------------------------------------------------------------------
# Common entity fields
# --------------------------------------------------------------------------
def common_fields():
    now = db.now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(entity):
    entity["version"] += 1
    entity["updated_at"] = db.now()


# --------------------------------------------------------------------------
# Auth
# --------------------------------------------------------------------------
def authenticate(allowed_roles):
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unknown auth headers")
    if role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this endpoint")
    return user_id, role


def require_owner(user_id, owner_contributor_id):
    if user_id != owner_contributor_id:
        raise ApiError("ERR_NOT_RESOURCE_OWNER", 403, "not the resource owner")


# --------------------------------------------------------------------------
# Request body / validation helpers
# --------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True, force=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be a JSON object")
    return data


def invalid(message):
    raise ApiError("ERR_VALIDATION", 422, message)


def require_str(data, field, max_len=None, min_len=1):
    value = data.get(field)
    if not isinstance(value, str):
        invalid(f"{field} must be a string")
    if len(value) < min_len:
        invalid(f"{field} must be non-empty")
    if max_len is not None and len(value) > max_len:
        invalid(f"{field} exceeds max length {max_len}")
    return value


def require_enum(data, field, choices):
    value = data.get(field)
    if value not in choices:
        invalid(f"{field} must be one of {sorted(choices)}")
    return value


def require_int(data, field, minimum=None):
    value = data.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        invalid(f"{field} must be an integer")
    if minimum is not None and value < minimum:
        invalid(f"{field} must be >= {minimum}")
    return value


# --------------------------------------------------------------------------
# Pagination
# --------------------------------------------------------------------------
def parse_pagination():
    limit = request.args.get("limit")
    offset = request.args.get("offset")
    if limit is None:
        limit_val = 10
    else:
        try:
            limit_val = int(limit)
        except (TypeError, ValueError):
            invalid("limit must be an integer")
        if limit_val < 1 or limit_val > 100:
            invalid("limit must be between 1 and 100")
    if offset is None:
        offset_val = 0
    else:
        try:
            offset_val = int(offset)
        except (TypeError, ValueError):
            invalid("offset must be an integer")
        if offset_val < 0:
            invalid("offset must be >= 0")
    return limit_val, offset_val


def paginate(items):
    """items: list of raw entities sorted; returns (page_items, pagination_meta)."""
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, meta


# --------------------------------------------------------------------------
# Lookups
# --------------------------------------------------------------------------
def get_or_404(collection, entity_id):
    entity = collection.get(entity_id)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", 404, "resource not found")
    return entity


def tier_by_code(code):
    for tier in db.license_tiers.values():
        if tier["code"] == code:
            return tier
    return None


# --------------------------------------------------------------------------
# Calculations
# --------------------------------------------------------------------------
def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_exclusivity(contributor_id):
    now = db.now()
    for window in db.exclusivity_windows.values():
        if window["contributor_id"] != contributor_id:
            continue
        if window["status"] != "ACTIVE":
            continue
        if window["start_at"] <= now < window["end_at"]:
            return "EXCLUSIVE"
    return "NON_EXCLUSIVE"


def compute_royalty_level(lifetime_cents):
    if lifetime_cents < LEVEL_SILVER_MIN:
        return "BRONZE"
    if lifetime_cents < LEVEL_GOLD_MIN:
        return "SILVER"
    if lifetime_cents < LEVEL_PLATINUM_MIN:
        return "GOLD"
    return "PLATINUM"


def recompute_royalty_level(contributor):
    contributor["royalty_level"] = compute_royalty_level(
        contributor["lifetime_earnings_cents"]
    )


def royalty_rate(contributor, asset):
    exclusivity = compute_exclusivity(contributor["id"])
    level = contributor["royalty_level"]
    base = ROYALTY_MATRIX[exclusivity][level]
    bonus = EDITORIAL_BONUS if asset["content_category"] == "EDITORIAL" else Decimal("0")
    rate = base + bonus
    if rate > RATE_CAP:
        rate = RATE_CAP
    return rate


def hamming_distance(hash_a, hash_b):
    return bin(int(hash_a, 16) ^ int(hash_b, 16)).count("1")


def withholding_rate(contributor):
    verified = [
        tf
        for tf in db.tax_forms.values()
        if tf["contributor_id"] == contributor["id"] and tf["status"] == "VERIFIED"
    ]
    if not verified:
        return Decimal("0")
    verified.sort(key=lambda t: (t["created_at"], t["_seq"]))
    form = verified[-1]
    if form["form_type"] == "W8BEN":
        rate = form.get("treaty_rate_pct")
        if rate is None:
            return DEFAULT_FOREIGN_WITHHOLDING
        return Decimal(str(rate))
    return Decimal("0")


def compute_withholding(contributor):
    rate = withholding_rate(contributor)
    total = 0
    for download in db.downloads.values():
        asset = db.assets.get(download["asset_id"])
        if asset is None or asset["contributor_id"] != contributor["id"]:
            continue
        if download["earning_status"] != "AVAILABLE":
            continue
        total += round_half_up(Decimal(download["royalty_amount_cents"]) * rate)
    return total


# --------------------------------------------------------------------------
# Error handlers
# --------------------------------------------------------------------------
@app.errorhandler(ApiError)
def handle_api_error(err):
    return error(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(err):
    return error("ERR_NOT_FOUND", 404, "resource not found")


@app.errorhandler(405)
def handle_405(err):
    return error("ERR_NOT_FOUND", 404, "method not allowed")


@app.errorhandler(500)
def handle_500(err):
    return error("ERR_INTERNAL", 500, "internal server error")


@app.get("/")
def health():
    return success({"status": "ok"})


# ==========================================================================
# Contributors
# ==========================================================================
COUNTRY_RE = None


def _valid_country(code):
    return isinstance(code, str) and len(code) == 2 and code.isalpha() and code.isupper()


@app.post("/contributors")
@synchronized
def create_contributor():
    data = body()
    display_name = require_str(data, "display_name", max_len=120)
    country_code = data.get("country_code")
    if not _valid_country(country_code):
        invalid("country_code must be two uppercase letters")
    contributor = common_fields()
    contributor.update({
        "display_name": display_name,
        "country_code": country_code,
        "onboarding_status": "PENDING",
        "tax_form_status": "MISSING",
        "royalty_level": "BRONZE",
        "lifetime_earnings_cents": 0,
        "available_balance_cents": 0,
        "accepted_asset_count": 0,
        "strike_count": 0,
    })
    db.contributors[contributor["id"]] = contributor
    return success(serialize_contributor(contributor), http_status=201)


@app.get("/contributors/<cid>")
@synchronized
def get_contributor(cid):
    authenticate(ROLES)
    contributor = get_or_404(db.contributors, cid)
    return success(serialize_contributor(contributor))


@app.get("/contributors")
@synchronized
def list_contributors():
    authenticate(ROLES)
    page, meta = paginate(list(db.contributors.values()))
    return success([serialize_contributor(c) for c in page], "array", pagination=meta)


# ==========================================================================
# Tax forms
# ==========================================================================
@app.post("/contributors/<cid>/tax-forms")
@synchronized
def create_tax_form(cid):
    user_id, role = authenticate({"Contributor"})
    contributor = get_or_404(db.contributors, cid)
    require_owner(user_id, cid)
    data = body()
    form_type = require_enum(data, "form_type", TAXFORM_TYPES)
    tax_id = require_str(data, "tax_id")
    treaty_rate = data.get("treaty_rate_pct")
    if treaty_rate is not None:
        if isinstance(treaty_rate, bool) or not isinstance(treaty_rate, (int, float)):
            invalid("treaty_rate_pct must be a number")
        if treaty_rate < 0 or treaty_rate > 0.30:
            invalid("treaty_rate_pct must be between 0.00 and 0.30")
    stored_treaty = treaty_rate if form_type == "W8BEN" else None
    form = common_fields()
    form.update({
        "contributor_id": cid,
        "form_type": form_type,
        "tax_id": tax_id,
        "treaty_rate_pct": stored_treaty,
        "status": "SUBMITTED",
        "reject_reason": None,
    })
    db.tax_forms[form["id"]] = form
    contributor["tax_form_status"] = "SUBMITTED"
    touch(contributor)
    return success(serialize(form), http_status=201)


@app.get("/contributors/<cid>/tax-forms")
@synchronized
def list_tax_forms(cid):
    authenticate({"Contributor", "ComplianceOfficer", "FinanceAdmin"})
    get_or_404(db.contributors, cid)
    forms = [f for f in db.tax_forms.values() if f["contributor_id"] == cid]
    page, meta = paginate(forms)
    return success([serialize(f) for f in page], "array", pagination=meta)


@app.post("/tax-forms/<fid>/decision")
@synchronized
def decide_tax_form(fid):
    authenticate({"ComplianceOfficer"})
    form = get_or_404(db.tax_forms, fid)
    if form["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "tax form is not SUBMITTED")
    data = body()
    decision = data.get("decision")
    if decision not in {"VERIFY", "REJECT"}:
        invalid("decision must be VERIFY or REJECT")
    contributor = db.contributors.get(form["contributor_id"])
    if decision == "VERIFY":
        form["status"] = "VERIFIED"
        touch(form)
        contributor["tax_form_status"] = "VERIFIED"
        if contributor["onboarding_status"] == "PENDING":
            contributor["onboarding_status"] = "ACTIVE"
        touch(contributor)
    else:
        reason = data.get("reject_reason")
        if reason is None:
            raise ApiError("ERR_MISSING_REJECT_REASON", 422, "reject_reason required")
        if reason not in TAXFORM_REJECT_REASONS:
            invalid("invalid reject_reason")
        form["reject_reason"] = reason
        form["status"] = "REJECTED"
        touch(form)
        contributor["tax_form_status"] = "REJECTED"
        touch(contributor)
    return success(serialize(form))


# ==========================================================================
# Model releases
# ==========================================================================
@app.post("/contributors/<cid>/model-releases")
@synchronized
def create_model_release(cid):
    user_id, role = authenticate({"Contributor"})
    get_or_404(db.contributors, cid)
    require_owner(user_id, cid)
    data = body()
    release_type = require_enum(data, "release_type", RELEASE_TYPES)
    releaser_name = require_str(data, "releaser_name")
    release = common_fields()
    release.update({
        "contributor_id": cid,
        "release_type": release_type,
        "releaser_name": releaser_name,
        "status": "PENDING",
        "reject_reason": None,
    })
    db.model_releases[release["id"]] = release
    return success(serialize(release), http_status=201)


@app.get("/contributors/<cid>/model-releases")
@synchronized
def list_model_releases(cid):
    authenticate({"Contributor", "ComplianceOfficer"})
    get_or_404(db.contributors, cid)
    releases = [r for r in db.model_releases.values() if r["contributor_id"] == cid]
    page, meta = paginate(releases)
    return success([serialize(r) for r in page], "array", pagination=meta)


@app.post("/model-releases/<rid>/decision")
@synchronized
def decide_model_release(rid):
    authenticate({"ComplianceOfficer"})
    release = get_or_404(db.model_releases, rid)
    if release["status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "release is not PENDING")
    data = body()
    decision = data.get("decision")
    if decision not in {"VERIFY", "REJECT"}:
        invalid("decision must be VERIFY or REJECT")
    if decision == "VERIFY":
        release["status"] = "VERIFIED"
        touch(release)
    else:
        reason = data.get("reject_reason")
        if reason is None:
            raise ApiError("ERR_MISSING_REJECT_REASON", 422, "reject_reason required")
        if reason not in RELEASE_REJECT_REASONS:
            invalid("invalid reject_reason")
        release["reject_reason"] = reason
        release["status"] = "REJECTED"
        touch(release)
    return success(serialize(release))


# ==========================================================================
# Exclusivity windows
# ==========================================================================
@app.post("/contributors/<cid>/exclusivity-windows")
@synchronized
def create_exclusivity_window(cid):
    user_id, role = authenticate({"Contributor"})
    contributor = get_or_404(db.contributors, cid)
    require_owner(user_id, cid)
    data = body()
    raw_start = data.get("start_at")
    raw_end = data.get("end_at")
    try:
        start_at = parse_ts(raw_start)
        end_at = parse_ts(raw_end)
    except (ValueError, TypeError):
        invalid("start_at and end_at must be ISO 8601 timestamps")
    # Overlap against existing ACTIVE windows (half-open, touching allowed).
    for window in db.exclusivity_windows.values():
        if window["contributor_id"] != cid or window["status"] != "ACTIVE":
            continue
        if start_at < window["end_at"] and window["start_at"] < end_at:
            raise ApiError("ERR_EXCLUSIVITY_OVERLAP", 409, "overlaps an active window")
    if end_at <= start_at:
        invalid("end_at must be strictly after start_at")
    window = common_fields()
    window.update({
        "contributor_id": cid,
        "start_at": start_at,
        "end_at": end_at,
        "status": "ACTIVE",
    })
    db.exclusivity_windows[window["id"]] = window
    touch(contributor)
    return success(serialize(window), http_status=201)


@app.get("/contributors/<cid>/exclusivity-windows")
@synchronized
def list_exclusivity_windows(cid):
    authenticate({"Contributor", "ComplianceOfficer", "FinanceAdmin"})
    get_or_404(db.contributors, cid)
    windows = [w for w in db.exclusivity_windows.values() if w["contributor_id"] == cid]
    page, meta = paginate(windows)
    return success([serialize(w) for w in page], "array", pagination=meta)


# ==========================================================================
# Earning adjustments
# ==========================================================================
@app.post("/contributors/<cid>/earning-adjustments")
@synchronized
def create_earning_adjustment(cid):
    authenticate({"FinanceAdmin"})
    contributor = get_or_404(db.contributors, cid)
    data = body()
    amount = require_int(data, "amount_cents", minimum=1)
    reason = require_str(data, "reason")
    adjustment = common_fields()
    adjustment.update({
        "contributor_id": cid,
        "amount_cents": amount,
        "reason": reason,
    })
    db.earning_adjustments[adjustment["id"]] = adjustment
    contributor["lifetime_earnings_cents"] += amount
    contributor["available_balance_cents"] += amount
    recompute_royalty_level(contributor)
    touch(contributor)
    return success(serialize(adjustment), http_status=201)


@app.get("/contributors/<cid>/earning-adjustments")
@synchronized
def list_earning_adjustments(cid):
    authenticate({"Contributor", "FinanceAdmin"})
    get_or_404(db.contributors, cid)
    items = [a for a in db.earning_adjustments.values() if a["contributor_id"] == cid]
    page, meta = paginate(items)
    return success([serialize(a) for a in page], "array", pagination=meta)


# ==========================================================================
# Payouts
# ==========================================================================
@app.post("/contributors/<cid>/payouts")
@synchronized
def create_payout(cid):
    user_id, role = authenticate({"Contributor"})
    contributor = get_or_404(db.contributors, cid)
    require_owner(user_id, cid)
    data = body()
    expected = data.get("expected_contributor_version")
    if expected is not None:
        if isinstance(expected, bool) or not isinstance(expected, int) \
                or expected != contributor["version"]:
            raise ApiError(
                "ERR_STALE_CONTRIBUTOR_VERSION", 412, "contributor version is stale"
            )
    if contributor["onboarding_status"] == "SUSPENDED":
        raise ApiError("ERR_CONTRIBUTOR_SUSPENDED", 403, "contributor is suspended")
    gross = contributor["available_balance_cents"]
    if gross < PAYOUT_THRESHOLD_CENTS:
        raise ApiError(
            "ERR_BELOW_PAYOUT_THRESHOLD", 422, "available balance below payout threshold"
        )
    withholding = compute_withholding(contributor)
    payout = common_fields()
    payout.update({
        "contributor_id": cid,
        "gross_amount_cents": gross,
        "withholding_cents": withholding,
        "net_amount_cents": gross - withholding,
        "status": "REQUESTED",
    })
    db.payouts[payout["id"]] = payout
    contributor["available_balance_cents"] = 0
    touch(contributor)
    return success(serialize(payout), http_status=201)


@app.get("/contributors/<cid>/payouts")
@synchronized
def list_payouts(cid):
    authenticate({"Contributor", "FinanceAdmin"})
    get_or_404(db.contributors, cid)
    items = [p for p in db.payouts.values() if p["contributor_id"] == cid]
    page, meta = paginate(items)
    return success([serialize(p) for p in page], "array", pagination=meta)


@app.post("/payouts/<pid>/process")
@synchronized
def process_payout(pid):
    authenticate({"FinanceAdmin"})
    payout = get_or_404(db.payouts, pid)
    if payout["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "payout is not REQUESTED")
    payout["status"] = "PROCESSING"
    touch(payout)
    return success(serialize(payout))


@app.post("/payouts/<pid>/complete")
@synchronized
def complete_payout(pid):
    authenticate({"FinanceAdmin"})
    payout = get_or_404(db.payouts, pid)
    if payout["status"] != "PROCESSING":
        raise ApiError("ERR_INVALID_STATE", 409, "payout is not PROCESSING")
    data = body()
    failed = bool(data.get("failed"))
    if failed:
        payout["status"] = "FAILED"
        touch(payout)
        contributor = db.contributors.get(payout["contributor_id"])
        if contributor is not None:
            contributor["available_balance_cents"] += payout["gross_amount_cents"]
            touch(contributor)
    else:
        payout["status"] = "PAID"
        touch(payout)
    return success(serialize(payout))


# ==========================================================================
# Assets
# ==========================================================================
def _valid_hash(value):
    if not isinstance(value, str):
        return False
    n = len(value)
    if n < 4 or n > 16 or n % 2 != 0:
        return False
    return all(c in "0123456789abcdef" for c in value)


def _validate_keywords(value):
    if not isinstance(value, list) or not (1 <= len(value) <= 50):
        invalid("keywords must be an array of 1..50 items")
    for kw in value:
        if not isinstance(kw, str) or len(kw) < 1:
            invalid("each keyword must be a non-empty string")


@app.post("/assets")
@synchronized
def create_asset():
    user_id, role = authenticate({"Contributor"})
    data = body()
    contributor_id = data.get("contributor_id")
    if not isinstance(contributor_id, str) or not contributor_id:
        invalid("contributor_id is required")
    get_or_404(db.contributors, contributor_id)
    model_release_id = data.get("model_release_id")
    if model_release_id is not None:
        get_or_404(db.model_releases, model_release_id)
    require_owner(user_id, contributor_id)
    title = require_str(data, "title", max_len=200)
    media_type = require_enum(data, "media_type", MEDIA_TYPES)
    content_category = require_enum(data, "content_category", CONTENT_CATEGORIES)
    _validate_keywords(data.get("keywords"))
    perceptual_hash = data.get("perceptual_hash")
    if not _valid_hash(perceptual_hash):
        invalid("perceptual_hash must be 4..16 lowercase hex chars of even length")
    requires_release = data.get("requires_release", False)
    if not isinstance(requires_release, bool):
        invalid("requires_release must be a boolean")
    asset = common_fields()
    asset.update({
        "contributor_id": contributor_id,
        "model_release_id": model_release_id,
        "title": title,
        "media_type": media_type,
        "content_category": content_category,
        "keywords": list(data["keywords"]),
        "perceptual_hash": perceptual_hash,
        "requires_release": requires_release,
        "status": "DRAFT",
        "reject_reason": None,
    })
    db.assets[asset["id"]] = asset
    return success(serialize(asset), http_status=201)


@app.get("/assets/<aid>")
@synchronized
def get_asset(aid):
    authenticate(ROLES)
    asset = get_or_404(db.assets, aid)
    return success(serialize(asset))


@app.get("/assets")
@synchronized
def list_assets():
    authenticate(ROLES)
    items = list(db.assets.values())
    contributor_id = request.args.get("contributor_id")
    model_release_id = request.args.get("model_release_id")
    status = request.args.get("status")
    if contributor_id is not None:
        items = [a for a in items if a["contributor_id"] == contributor_id]
    if model_release_id is not None:
        items = [a for a in items if a["model_release_id"] == model_release_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, meta = paginate(items)
    return success([serialize(a) for a in page], "array", pagination=meta)


@app.patch("/assets/<aid>")
@synchronized
def patch_asset(aid):
    user_id, role = authenticate({"Contributor"})
    asset = get_or_404(db.assets, aid)
    require_owner(user_id, asset["contributor_id"])
    if asset["status"] not in {"DRAFT", "REJECTED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "asset is not editable in this state")
    data = body()
    if "title" in data:
        asset["title"] = require_str(data, "title", max_len=200)
    if "keywords" in data:
        _validate_keywords(data.get("keywords"))
        asset["keywords"] = list(data["keywords"])
    if "perceptual_hash" in data:
        if not _valid_hash(data.get("perceptual_hash")):
            invalid("perceptual_hash must be 4..16 lowercase hex chars of even length")
        asset["perceptual_hash"] = data["perceptual_hash"]
    touch(asset)
    return success(serialize(asset))


@app.post("/assets/<aid>/submit")
@synchronized
def submit_asset(aid):
    user_id, role = authenticate({"Contributor"})
    asset = get_or_404(db.assets, aid)
    require_owner(user_id, asset["contributor_id"])
    if asset["status"] not in {"DRAFT", "REJECTED"}:
        raise ApiError("ERR_INVALID_STATE", 409, "asset cannot be submitted from this state")
    contributor = db.contributors.get(asset["contributor_id"])
    if contributor is not None and contributor["onboarding_status"] == "SUSPENDED":
        raise ApiError("ERR_CONTRIBUTOR_SUSPENDED", 403, "contributor is suspended")
    if not asset["keywords"]:
        invalid("keywords must be non-empty")
    if asset["requires_release"] and not asset["model_release_id"]:
        raise ApiError("ERR_RELEASE_REQUIRED", 422, "model_release_id required")
    asset["reject_reason"] = None
    asset["status"] = "SUBMITTED"
    touch(asset)
    return success(serialize(asset))


@app.post("/assets/<aid>/claim")
@synchronized
def claim_asset(aid):
    authenticate({"Reviewer"})
    asset = get_or_404(db.assets, aid)
    if asset["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "asset is not SUBMITTED")
    asset["status"] = "IN_REVIEW"
    touch(asset)
    return success(serialize(asset))


@app.post("/assets/<aid>/reviews")
@synchronized
def review_asset(aid):
    user_id, role = authenticate({"Reviewer"})
    asset = get_or_404(db.assets, aid)
    data = body()
    similar_id = data.get("similar_to_asset_id")
    if similar_id is not None:
        get_or_404(db.assets, similar_id)
    if asset["status"] != "IN_REVIEW":
        raise ApiError("ERR_INVALID_STATE", 409, "asset is not IN_REVIEW")
    decision = data.get("decision")
    if decision not in {"ACCEPT", "REJECT"}:
        invalid("decision must be ACCEPT or REJECT")
    contributor = db.contributors.get(asset["contributor_id"])
    if decision == "ACCEPT":
        if contributor is None or contributor["onboarding_status"] != "ACTIVE":
            raise ApiError("ERR_CONTRIBUTOR_NOT_ACTIVE", 409, "contributor is not ACTIVE")
        if asset["requires_release"]:
            release = db.model_releases.get(asset["model_release_id"])
            if release is None or release["status"] != "VERIFIED":
                raise ApiError("ERR_RELEASE_NOT_VERIFIED", 422, "release not verified")
        review = _make_review(aid, "ACCEPT", None, None, user_id)
        asset["status"] = "ACCEPTED"
        touch(asset)
        contributor["accepted_asset_count"] += 1
        touch(contributor)
        return success(serialize(review), http_status=201)
    # REJECT
    reason = data.get("reject_reason")
    if reason is None:
        raise ApiError("ERR_MISSING_REJECT_REASON", 422, "reject_reason required")
    if reason not in ASSET_REJECT_REASONS:
        invalid("invalid reject_reason")
    recorded_similar = None
    if reason == "SIMILAR":
        if similar_id is None:
            raise ApiError("ERR_MISSING_SIMILAR_TARGET", 422, "similar_to_asset_id required")
        other = db.assets[similar_id]
        if other["status"] != "ACCEPTED" or \
                hamming_distance(asset["perceptual_hash"], other["perceptual_hash"]) > SIMILAR_MAX_DISTANCE:
            raise ApiError("ERR_NOT_SIMILAR_ENOUGH", 422, "assets are not similar enough")
        recorded_similar = similar_id
    review = _make_review(aid, "REJECT", reason, recorded_similar, user_id)
    asset["reject_reason"] = reason
    asset["status"] = "REJECTED"
    touch(asset)
    return success(serialize(review), http_status=201)


def _make_review(asset_id, decision, reject_reason, similar_id, reviewer_id):
    now = db.now()
    review = {
        "id": new_id(),
        "created_at": now,
        "_seq": db.next_seq(),
        "asset_id": asset_id,
        "decision": decision,
        "reject_reason": reject_reason,
        "similar_to_asset_id": similar_id,
        "reviewer_id": reviewer_id,
    }
    db.reviews[review["id"]] = review
    return review


@app.get("/reviews")
@synchronized
def list_reviews():
    authenticate({"Contributor", "Reviewer", "ComplianceOfficer"})
    items = list(db.reviews.values())
    asset_id = request.args.get("asset_id")
    similar_id = request.args.get("similar_to_asset_id")
    if asset_id is not None:
        items = [r for r in items if r["asset_id"] == asset_id]
    if similar_id is not None:
        items = [r for r in items if r["similar_to_asset_id"] == similar_id]
    page, meta = paginate(items)
    return success([serialize(r) for r in page], "array", pagination=meta)


@app.get("/reviews/<rid>")
@synchronized
def get_review(rid):
    authenticate({"Contributor", "Reviewer", "ComplianceOfficer"})
    review = get_or_404(db.reviews, rid)
    return success(serialize(review))


# ==========================================================================
# License tiers
# ==========================================================================
@app.post("/license-tiers")
@synchronized
def create_license_tier():
    authenticate({"FinanceAdmin"})
    data = body()
    code = require_enum(data, "code", TIER_CODES)
    base_price = require_int(data, "base_price_cents", minimum=1)
    if tier_by_code(code) is not None:
        invalid("license tier code must be unique")
    tier = common_fields()
    tier.update({"code": code, "base_price_cents": base_price})
    db.license_tiers[tier["id"]] = tier
    return success(serialize(tier), http_status=201)


@app.get("/license-tiers")
@synchronized
def list_license_tiers():
    authenticate(ROLES)
    page, meta = paginate(list(db.license_tiers.values()))
    return success([serialize(t) for t in page], "array", pagination=meta)


# ==========================================================================
# Downloads
# ==========================================================================
@app.post("/downloads")
@synchronized
def create_download():
    authenticate({"FinanceAdmin"})
    data = body()
    asset_id = data.get("asset_id")
    if not isinstance(asset_id, str) or not asset_id:
        invalid("asset_id is required")
    asset = get_or_404(db.assets, asset_id)
    code = data.get("license_tier_code")
    if not isinstance(code, str) or not code:
        invalid("license_tier_code is required")
    tier = tier_by_code(code)
    if tier is None:
        raise ApiError("ERR_NOT_FOUND", 404, "license tier not found")
    if asset["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "asset is not ACCEPTED")
    buyer_reference = require_str(data, "buyer_reference")
    contributor = db.contributors.get(asset["contributor_id"])
    rate = royalty_rate(contributor, asset)
    sale_price = tier["base_price_cents"]
    royalty_amount = round_half_up(Decimal(sale_price) * rate)
    download = common_fields()
    download.update({
        "asset_id": asset_id,
        "license_tier_code": code,
        "buyer_reference": buyer_reference,
        "sale_price_cents": sale_price,
        "royalty_rate_snapshot_pct": float(rate),
        "royalty_amount_cents": royalty_amount,
        "earning_status": "PENDING",
        "available_at": download["created_at"] + timedelta(days=CLEARING_DAYS),
    })
    db.downloads[download["id"]] = download
    return success(serialize(download), http_status=201)


@app.get("/downloads/<did>")
@synchronized
def get_download(did):
    authenticate({"Contributor", "FinanceAdmin"})
    download = get_or_404(db.downloads, did)
    return success(serialize(download))


@app.get("/downloads")
@synchronized
def list_downloads():
    authenticate({"Contributor", "FinanceAdmin"})
    items = list(db.downloads.values())
    asset_id = request.args.get("asset_id")
    contributor_id = request.args.get("contributor_id")
    if asset_id is not None:
        items = [d for d in items if d["asset_id"] == asset_id]
    if contributor_id is not None:
        filtered = []
        for d in items:
            asset = db.assets.get(d["asset_id"])
            if asset is not None and asset["contributor_id"] == contributor_id:
                filtered.append(d)
        items = filtered
    page, meta = paginate(items)
    return success([serialize(d) for d in page], "array", pagination=meta)


@app.post("/downloads/<did>/settle")
@synchronized
def settle_download(did):
    authenticate({"FinanceAdmin"})
    download = get_or_404(db.downloads, did)
    if download["earning_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "download is not PENDING")
    if db.now() < download["available_at"]:
        raise ApiError("ERR_NOT_YET_CLEARED", 409, "download has not cleared yet")
    download["earning_status"] = "AVAILABLE"
    touch(download)
    contributor = db.contributors.get(_download_contributor_id(download))
    if contributor is not None:
        amount = download["royalty_amount_cents"]
        contributor["lifetime_earnings_cents"] += amount
        contributor["available_balance_cents"] += amount
        recompute_royalty_level(contributor)
        touch(contributor)
    return success(serialize(download))


@app.post("/downloads/<did>/reverse")
@synchronized
def reverse_download(did):
    authenticate({"FinanceAdmin"})
    download = get_or_404(db.downloads, did)
    data = body()
    if download["earning_status"] not in {"PENDING", "AVAILABLE"}:
        raise ApiError("ERR_INVALID_STATE", 409, "download cannot be reversed")
    was_available = download["earning_status"] == "AVAILABLE"
    download["earning_status"] = "REVERSED"
    download["reason"] = data.get("reason")
    touch(download)
    if was_available:
        contributor = db.contributors.get(_download_contributor_id(download))
        if contributor is not None:
            amount = download["royalty_amount_cents"]
            contributor["lifetime_earnings_cents"] -= amount
            contributor["available_balance_cents"] -= amount
            recompute_royalty_level(contributor)
            touch(contributor)
    return success(serialize(download))


def _download_contributor_id(download):
    asset = db.assets.get(download["asset_id"])
    return asset["contributor_id"] if asset else None


# ==========================================================================
# Takedowns
# ==========================================================================
@app.post("/assets/<aid>/takedowns")
@synchronized
def create_takedown(aid):
    authenticate({"ComplianceOfficer"})
    asset = get_or_404(db.assets, aid)
    data = body()
    now = db.now()
    for td in db.takedowns.values():
        if td["asset_id"] == aid and td["status"] == "UPHELD":
            if now < td["hold_end"] + timedelta(days=TAKEDOWN_BUFFER_DAYS):
                raise ApiError(
                    "ERR_TAKEDOWN_HOLD_CONFLICT", 409, "within takedown hold buffer"
                )
    claim_type = require_enum(data, "claim_type", CLAIM_TYPES)
    claimant_name = require_str(data, "claimant_name")
    takedown = common_fields()
    takedown.update({
        "asset_id": aid,
        "claim_type": claim_type,
        "claimant_name": claimant_name,
        "hold_start": now,
        "hold_end": now + timedelta(days=TAKEDOWN_HOLD_DAYS),
        "status": "OPEN",
        "resolution_note": None,
    })
    db.takedowns[takedown["id"]] = takedown
    return success(serialize(takedown), http_status=201)


@app.get("/takedowns/<tid>")
@synchronized
def get_takedown(tid):
    authenticate({"Contributor", "ComplianceOfficer"})
    takedown = get_or_404(db.takedowns, tid)
    return success(serialize(takedown))


@app.get("/takedowns")
@synchronized
def list_takedowns():
    authenticate({"Contributor", "ComplianceOfficer"})
    items = list(db.takedowns.values())
    asset_id = request.args.get("asset_id")
    if asset_id is not None:
        items = [t for t in items if t["asset_id"] == asset_id]
    page, meta = paginate(items)
    return success([serialize(t) for t in page], "array", pagination=meta)


@app.post("/takedowns/<tid>/decision")
@synchronized
def decide_takedown(tid):
    authenticate({"ComplianceOfficer"})
    takedown = get_or_404(db.takedowns, tid)
    if takedown["status"] != "OPEN":
        raise ApiError("ERR_INVALID_STATE", 409, "takedown is not OPEN")
    data = body()
    decision = data.get("decision")
    if decision not in {"UPHOLD", "DISMISS"}:
        invalid("decision must be UPHOLD or DISMISS")
    if decision == "DISMISS":
        takedown["resolution_note"] = data.get("resolution_note")
        takedown["status"] = "DISMISSED"
        touch(takedown)
        return success(serialize(takedown))
    # UPHOLD
    asset = db.assets.get(takedown["asset_id"])
    if asset is None or asset["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "asset is not ACCEPTED")
    _apply_takedown_cascade(asset)
    takedown["resolution_note"] = data.get("resolution_note")
    takedown["status"] = "UPHELD"
    touch(takedown)
    return success(serialize(takedown))


def _apply_takedown_cascade(asset):
    contributor = db.contributors.get(asset["contributor_id"])
    # Reverse every PENDING/AVAILABLE download of this asset.
    for download in db.downloads.values():
        if download["asset_id"] != asset["id"]:
            continue
        if download["earning_status"] not in {"PENDING", "AVAILABLE"}:
            continue
        was_available = download["earning_status"] == "AVAILABLE"
        download["earning_status"] = "REVERSED"
        touch(download)
        if was_available and contributor is not None:
            amount = download["royalty_amount_cents"]
            contributor["lifetime_earnings_cents"] -= amount
            contributor["available_balance_cents"] -= amount
            touch(contributor)
    asset["status"] = "TAKEN_DOWN"
    touch(asset)
    if contributor is not None:
        contributor["accepted_asset_count"] -= 1
        contributor["strike_count"] += 1
        recompute_royalty_level(contributor)
        touch(contributor)
        if contributor["strike_count"] >= SUSPEND_STRIKE_THRESHOLD \
                and contributor["onboarding_status"] == "ACTIVE":
            contributor["onboarding_status"] = "SUSPENDED"
            touch(contributor)


# ==========================================================================
# Logical clock
# ==========================================================================
@app.post("/_clock/set_current_utc")
@synchronized
def set_clock():
    authenticate({"FinanceAdmin"})
    data = body()
    raw = data.get("to_iso8601")
    try:
        new_clock = parse_ts(raw)
    except (ValueError, TypeError):
        invalid("to_iso8601 must be an ISO 8601 timestamp")
    db.clock = new_clock
    return success({"current_utc": fmt_ts(db.clock)})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
