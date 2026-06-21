"""Streaming Family Plan API — Flask application entry point.

Boots empty (no seeding). All state lives in process memory (db.store). The
test harness re-launches start.sh before every test under
`--isolation per-test-server`, so a fresh process == a clean store.

Endpoints, fields, side effects, and validation ordering all trace to
workspace/PRD.md (the literal contract) and SCAFFOLD.yaml.
"""
import os
import uuid

from flask import Flask, request

from db import store, utc_now_iso
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHENTICATED, ERR_FORBIDDEN_ROLE, ERR_NOT_RESOURCE_OWNER,
    ERR_NOT_FOUND, ERR_INVALID_STATE, ERR_STALE_ACCOUNT_VERSION,
    ERR_CROSS_ACCOUNT_REFERENCE, ERR_RATING_BLOCKED, ERR_CURFEW_BLOCKED,
    ERR_DAILY_LIMIT_EXCEEDED, ERR_DEVICE_BUSY, ERR_HD_NOT_ALLOWED,
    ERR_TITLE_NOT_DOWNLOADABLE, ERR_DUPLICATE, ERR_CONCURRENT_CAP_REACHED,
    ERR_DOWNLOAD_QUOTA_REACHED, ERR_PROFILE_CAP_REACHED, ERR_DEVICE_CAP_REACHED,
    ERR_INSUFFICIENT_CREDIT, ERR_INVITE_EXPIRED, ERR_INVALID_REQUEST,
)
from middleware import get_auth, require_role
from response import success_object, success_array, error_response
import calculations as calc
from calculations import (
    parse_iso_to_dt, minute_of_day, utc_day_ordinal, rating_ceiling,
    ad_break_count, download_size, watch_minutes_attributed, cycle_charge,
    RATING_RANK, RATING_ORDER, KIND_DEFAULT_RATING,
    INVITE_TTL_HOURS, DOWNLOAD_LICENSE_HOURS, INVITE_SEAT_HOLD_CENTS,
)
import services as svc
from services import (
    current_dt, current_minute_of_day, account_view, plan_view, title_view,
    profile_view, parental_control_view, invite_view, device_view,
    stream_session_view, download_view, watch_progress_view, plan_change_view,
    parental_control_for_profile, non_archived_profile_count,
    profile_active_downloads_count, recompute_profile_max_rating,
)
from datetime import timedelta


app = Flask(__name__)
app.url_map.strict_slashes = False


# ============================================================
# Global error handlers
# ============================================================
@app.errorhandler(ApiError)
def handle_api_error(err: ApiError):
    return error_response(err.error_id, err.message, err.http_status)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", "Path not found", 404)


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_INVALID_REQUEST", "Method not allowed", 400)


@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, ApiError):
        return error_response(e.error_id, e.message, e.http_status)
    return error_response("ERR_INVALID_REQUEST", "Internal error: %s" % (e,), 500)


# ============================================================
# Generic helpers
# ============================================================
def gen_id() -> str:
    return str(uuid.uuid4())


def clock_iso() -> str:
    """Current logical-clock instant as the canonical ISO string.

    created_at / updated_at / effective instants all trace to the logical clock
    so that chronological ordering is deterministic under the test seam
    (PRD §2.9 — many temporal gates read their truth from this clock).
    """
    return store.current_utc


def get_json_body() -> dict:
    if not request.data:
        return {}
    try:
        body = request.get_json(silent=False, force=True)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "Malformed JSON body")
    if body is None:
        return {}
    if not isinstance(body, dict):
        raise_err(ERR_INVALID_REQUEST, "Request body must be a JSON object")
    return body


def require_fields(body: dict, fields: list):
    for f in fields:
        if f not in body or body[f] is None:
            raise_err(ERR_INVALID_REQUEST, "Missing required field: %s" % f)


def pagination_params():
    limit_str = request.args.get("limit")
    offset_str = request.args.get("offset")
    try:
        limit = int(limit_str) if limit_str is not None else 10
        offset = int(offset_str) if offset_str is not None else 0
    except (TypeError, ValueError):
        raise_err(ERR_INVALID_REQUEST, "limit/offset must be integers")
    if limit < 1 or limit > 100:
        raise_err(ERR_INVALID_REQUEST, "limit must be between 1 and 100")
    if offset < 0:
        raise_err(ERR_INVALID_REQUEST, "offset must be >= 0")
    return limit, offset


def paginate(items: list, limit: int, offset: int):
    total = len(items)
    return items[offset:offset + limit], total


def stamp_common(obj: dict) -> dict:
    """Full-spine stamp: id, created_at, updated_at, version=1."""
    if "id" not in obj:
        obj["id"] = gen_id()
    now = clock_iso()
    obj["created_at"] = now
    obj["updated_at"] = now
    obj["version"] = 1
    return obj


def stamp_lean(obj: dict) -> dict:
    """Lean stamp for SubscriptionPlan/Title/PlanChange: id + created_at only."""
    if "id" not in obj:
        obj["id"] = gen_id()
    obj["created_at"] = clock_iso()
    return obj


def bump(obj: dict):
    """Refresh updated_at and increment version on a full-spine resource."""
    obj["updated_at"] = clock_iso()
    obj["version"] = int(obj["version"]) + 1


def as_int(value, field):
    if isinstance(value, bool) or not isinstance(value, int):
        raise_err(ERR_INVALID_REQUEST, "%s must be an integer" % field)
    return value


# ============================================================
# Existence resolvers (validation priority 4, left-to-right)
# ============================================================
def get_plan_or_404(pid):
    p = store.subscription_plans.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, "SubscriptionPlan %s not found" % pid)
    return p


def get_title_or_404(tid):
    t = store.titles.get(tid)
    if not t:
        raise_err(ERR_NOT_FOUND, "Title %s not found" % tid)
    return t


def get_account_or_404(aid):
    a = store.accounts.get(aid)
    if not a:
        raise_err(ERR_NOT_FOUND, "Account %s not found" % aid)
    return a


def get_profile_or_404(pid):
    p = store.profiles.get(pid)
    if not p:
        raise_err(ERR_NOT_FOUND, "Profile %s not found" % pid)
    return p


def get_device_or_404(did):
    d = store.devices.get(did)
    if not d:
        raise_err(ERR_NOT_FOUND, "Device %s not found" % did)
    return d


def get_invite_or_404(iid):
    i = store.invites.get(iid)
    if not i:
        raise_err(ERR_NOT_FOUND, "Invite %s not found" % iid)
    return i


def get_session_or_404(sid):
    s = store.stream_sessions.get(sid)
    if not s:
        raise_err(ERR_NOT_FOUND, "StreamSession %s not found" % sid)
    return s


def get_download_or_404(did):
    d = store.downloads.get(did)
    if not d:
        raise_err(ERR_NOT_FOUND, "Download %s not found" % did)
    return d


def get_watch_progress_or_404(wid):
    w = store.watch_progress.get(wid)
    if not w:
        raise_err(ERR_NOT_FOUND, "WatchProgress %s not found" % wid)
    return w


# ============================================================
# Ownership (validation priority 3)
# ============================================================
def owner_owns_account(user_id, account):
    """AccountOwner ownership: X-User-ID must equal the Account id."""
    if user_id != account["id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "AccountOwner does not own this Account")


def profileuser_owns_profile(user_id, profile):
    """ProfileUser ownership: X-User-ID must equal the Profile id."""
    if user_id != profile["id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Profile")


# ============================================================
# Cascade / state-effect helpers
# ============================================================
def end_session(session: dict):
    """Force a session ACTIVE -> ENDED, folding minutes (suspend/close cascade
    and normal stop share this body)."""
    title = store.titles.get(session["title_id"])
    runtime = title["runtime_minutes"] if title else 0
    mw = watch_minutes_attributed(
        session["started_at_min"], current_minute_of_day(), runtime)
    session["minutes_watched"] = mw
    session["status"] = "ENDED"
    bump(session)
    prof = store.profiles.get(session["profile_id"])
    if prof:
        prof["daily_watch_minutes_used"] = int(prof["daily_watch_minutes_used"]) + mw
        bump(prof)


def delete_download(d: dict):
    """Drive a download to DELETED (cascade); frees a quota slot implicitly."""
    d["status"] = "DELETED"
    bump(d)


def release_invite_hold(invite: dict, account: dict):
    """Compensating: return the held seat fee to the wallet."""
    account["wallet_credit_cents"] = int(account["wallet_credit_cents"]) + int(invite["hold_amount_cents"])


def account_period_open_dt(account: dict):
    """The instant the account's current OPEN period opened.

    Period open is anchored to the account's created_at clock value (PRD §2.6:
    the period spans 30 whole days from period day 0). All cycle-charge
    segmentation counts whole days from this anchor.
    """
    return parse_iso_to_dt(account["period_open"])


def collect_period_changes(account: dict):
    """PlanChanges for this account within the current OPEN period, sorted
    chronologically (created_at ASC, then id ASC to stabilize equal-ms ties)."""
    pcs = [pc for pc in store.plan_changes.values()
           if pc["account_id"] == account["id"]]
    pcs.sort(key=lambda pc: (parse_iso_to_dt(pc["created_at"]), pc["id"]))
    return [{"effective_dt": parse_iso_to_dt(pc["created_at"]),
             "fee": store.subscription_plans[pc["to_plan_id"]]["monthly_fee_cents"]}
            for pc in pcs]


def recompute_account_charge(account: dict):
    """Recompute period_charge_cents and proration_adjustment_cents via
    cycle_charge for the current OPEN period (PRD §2.6, §3.3)."""
    plan = store.subscription_plans[account["plan_id"]]
    open_plan = store.subscription_plans[account["period_open_plan_id"]]
    changes = collect_period_changes(account)
    charge = cycle_charge(account_period_open_dt(account),
                          open_plan["monthly_fee_cents"], changes)
    account["period_charge_cents"] = charge
    account["proration_adjustment_cents"] = charge - plan["monthly_fee_cents"]


# ============================================================
# Catalog / configuration
# ============================================================
PLAN_TIERS = {"AD_SUPPORTED", "AD_FREE", "PREMIUM"}


@app.route("/subscription-plans", methods=["POST"])
def create_subscription_plan():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["tier", "monthly_fee_cents", "max_profiles",
                          "concurrent_stream_cap", "max_registered_devices",
                          "download_quota_per_profile", "ad_free",
                          "hd_offline_allowed"])
    tier = body["tier"]
    if tier not in PLAN_TIERS:
        raise_err(ERR_INVALID_REQUEST, "tier must be one of %s" % sorted(PLAN_TIERS))
    monthly = as_int(body["monthly_fee_cents"], "monthly_fee_cents")
    if monthly < 0:
        raise_err(ERR_INVALID_REQUEST, "monthly_fee_cents must be >= 0")
    max_profiles = as_int(body["max_profiles"], "max_profiles")
    if max_profiles < 1:
        raise_err(ERR_INVALID_REQUEST, "max_profiles must be >= 1")
    cap = as_int(body["concurrent_stream_cap"], "concurrent_stream_cap")
    if cap < 1:
        raise_err(ERR_INVALID_REQUEST, "concurrent_stream_cap must be >= 1")
    max_dev = as_int(body["max_registered_devices"], "max_registered_devices")
    if max_dev < 1:
        raise_err(ERR_INVALID_REQUEST, "max_registered_devices must be >= 1")
    dq = as_int(body["download_quota_per_profile"], "download_quota_per_profile")
    if dq < 0:
        raise_err(ERR_INVALID_REQUEST, "download_quota_per_profile must be >= 0")
    ad_free = body["ad_free"]
    hd = body["hd_offline_allowed"]
    if not isinstance(ad_free, bool) or not isinstance(hd, bool):
        raise_err(ERR_INVALID_REQUEST, "ad_free and hd_offline_allowed must be boolean")

    obj = {
        "tier": tier,
        "monthly_fee_cents": monthly,
        "max_profiles": max_profiles,
        "concurrent_stream_cap": cap,
        "max_registered_devices": max_dev,
        "download_quota_per_profile": dq,
        "ad_free": ad_free,
        "hd_offline_allowed": hd,
    }
    stamp_lean(obj)
    store.subscription_plans[obj["id"]] = obj
    return success_object(plan_view(obj), 201)


@app.route("/subscription-plans/<pid>", methods=["GET"])
def get_subscription_plan(pid):
    _, role = get_auth()
    require_role(role, ["PlatformAdmin", "AccountOwner", "ProfileUser"])
    p = get_plan_or_404(pid)
    return success_object(plan_view(p), 200)


@app.route("/subscription-plans/<pid>/accounts", methods=["GET"])
def list_plan_accounts(pid):
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    get_plan_or_404(pid)
    limit, offset = pagination_params()
    items = [a for a in store.accounts.values() if a["plan_id"] == pid]
    items.sort(key=lambda a: (a["created_at"], a["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([account_view(a) for a in page], limit, offset, total)


@app.route("/subscription-plans/<pid>/plan-changes", methods=["GET"])
def list_plan_plan_changes(pid):
    _, role = get_auth()
    require_role(role, ["PlatformAdmin", "AccountOwner"])
    get_plan_or_404(pid)
    limit, offset = pagination_params()
    items = [pc for pc in store.plan_changes.values() if pc["to_plan_id"] == pid]
    items.sort(key=lambda pc: (pc["created_at"], pc["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([plan_change_view(pc) for pc in page], limit, offset, total)


MATURITY_RATINGS = set(RATING_ORDER)


@app.route("/titles", methods=["POST"])
def create_title():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["name", "maturity_rating", "runtime_minutes",
                          "license_size_mb"])
    name = body["name"]
    if not isinstance(name, str) or not name:
        raise_err(ERR_INVALID_REQUEST, "name must be a non-empty string")
    rating = body["maturity_rating"]
    if rating not in MATURITY_RATINGS:
        raise_err(ERR_INVALID_REQUEST, "maturity_rating must be one of %s" % RATING_ORDER)
    runtime = as_int(body["runtime_minutes"], "runtime_minutes")
    if runtime < 1:
        raise_err(ERR_INVALID_REQUEST, "runtime_minutes must be >= 1")
    size = as_int(body["license_size_mb"], "license_size_mb")
    if size < 1:
        raise_err(ERR_INVALID_REQUEST, "license_size_mb must be >= 1")
    downloadable = body.get("downloadable", True)
    if not isinstance(downloadable, bool):
        raise_err(ERR_INVALID_REQUEST, "downloadable must be boolean")

    obj = {
        "name": name,
        "maturity_rating": rating,
        "runtime_minutes": runtime,
        "downloadable": downloadable,
        "license_size_mb": size,
    }
    stamp_lean(obj)
    store.titles[obj["id"]] = obj
    return success_object(title_view(obj), 201)


@app.route("/titles/<tid>", methods=["GET"])
def get_title(tid):
    _, role = get_auth()
    require_role(role, ["PlatformAdmin", "AccountOwner", "ProfileUser"])
    t = get_title_or_404(tid)
    return success_object(title_view(t), 200)


# ============================================================
# Accounts (billing folded onto the Account)
# ============================================================
@app.route("/accounts", methods=["POST"])
def create_account():
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    body = get_json_body()
    require_fields(body, ["plan_id", "owner_email", "billing_anchor_day"])
    plan_id = body["plan_id"]
    plan = get_plan_or_404(plan_id)
    owner_email = body["owner_email"]
    if not isinstance(owner_email, str) or not owner_email:
        raise_err(ERR_INVALID_REQUEST, "owner_email must be a non-empty string")
    anchor = as_int(body["billing_anchor_day"], "billing_anchor_day")
    if anchor < 1 or anchor > 28:
        raise_err(ERR_INVALID_REQUEST, "billing_anchor_day must be in 1..28")
    initial_credit = body.get("initial_credit_cents", 0)
    initial_credit = as_int(initial_credit, "initial_credit_cents")
    if initial_credit < 0:
        raise_err(ERR_INVALID_REQUEST, "initial_credit_cents must be >= 0")

    # Uniqueness: owner_email unique among non-CLOSED Accounts (priority 14).
    for a in store.accounts.values():
        if a["status"] != "CLOSED" and a["owner_email"] == owner_email:
            raise_err(ERR_DUPLICATE, "owner_email already in use by a non-CLOSED account")

    obj = {
        "plan_id": plan_id,
        "owner_email": owner_email,
        "status": "ACTIVE",
        "billing_anchor_day": anchor,
        "wallet_credit_cents": initial_credit,
        "billing_status": "OPEN",
        "period_charge_cents": plan["monthly_fee_cents"],
        "proration_adjustment_cents": 0,
        "active_stream_count": 0,
        "registered_device_count": 0,
        # Internal bookkeeping for cycle_charge segmentation (period anchor and
        # the plan in force at period open). Not exposed in the view.
        "period_open": clock_iso(),
        "period_open_plan_id": plan_id,
    }
    stamp_common(obj)
    store.accounts[obj["id"]] = obj
    return success_object(account_view(obj), 201)


@app.route("/accounts/<aid>", methods=["GET"])
def get_account(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "PlatformAdmin"])
    a = get_account_or_404(aid)
    if role == "AccountOwner":
        owner_owns_account(uid, a)
    return success_object(account_view(a), 200)


def _account_occ_check(account, body):
    """Account-level transitions accept expected_account_version and reject a
    mismatch under the stale-version rule (PRD §2.7)."""
    if "expected_account_version" not in body or body["expected_account_version"] is None:
        raise_err(ERR_INVALID_REQUEST, "expected_account_version is required")
    expected = body["expected_account_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise_err(ERR_INVALID_REQUEST, "expected_account_version must be an integer")
    if expected != int(account["version"]):
        raise_err(ERR_STALE_ACCOUNT_VERSION,
                  "expected_account_version %s != current %s" % (expected, account["version"]))


@app.route("/accounts/<aid>/suspend", methods=["POST"])
def suspend_account(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    a = get_account_or_404(aid)
    owner_owns_account(uid, a)
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "suspend requires ACTIVE; account is %s" % a["status"])
    body = get_json_body()
    _account_occ_check(a, body)
    # Cascade: every ACTIVE StreamSession -> ENDED (fold minutes); count -> 0.
    for s in store.stream_sessions.values():
        if s["status"] == "ACTIVE" and _session_account_id(s) == aid:
            end_session(s)
    a["active_stream_count"] = 0
    a["status"] = "SUSPENDED"
    bump(a)
    return success_object(account_view(a), 200)


@app.route("/accounts/<aid>/reactivate", methods=["POST"])
def reactivate_account(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    a = get_account_or_404(aid)
    owner_owns_account(uid, a)
    if a["status"] != "SUSPENDED":
        raise_err(ERR_INVALID_STATE, "reactivate requires SUSPENDED; account is %s" % a["status"])
    body = get_json_body()
    _account_occ_check(a, body)
    plan = store.subscription_plans[a["plan_id"]]
    fee = plan["monthly_fee_cents"]
    # Fiscal sufficiency (priority 20): one full period of credit on hand.
    if int(a["wallet_credit_cents"]) < fee:
        raise_err(ERR_INSUFFICIENT_CREDIT,
                  "reactivation requires wallet >= one period fee (%s)" % fee)
    a["wallet_credit_cents"] = int(a["wallet_credit_cents"]) - fee
    a["status"] = "ACTIVE"
    bump(a)
    return success_object(account_view(a), 200)


def _invoice_open_period(account):
    """Run cycle_charge to finalize the period, debit the wallet by net charge,
    and flip billing_status to INVOICED (shared by invoice + close)."""
    recompute_account_charge(account)
    account["wallet_credit_cents"] = int(account["wallet_credit_cents"]) - int(account["period_charge_cents"])
    account["billing_status"] = "INVOICED"


@app.route("/accounts/<aid>/close", methods=["POST"])
def close_account(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    a = get_account_or_404(aid)
    owner_owns_account(uid, a)
    if a["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err(ERR_INVALID_STATE, "close requires ACTIVE or SUSPENDED; account is %s" % a["status"])
    body = get_json_body()
    _account_occ_check(a, body)

    # From ACTIVE: force-end live streams first (fold minutes; count -> 0).
    if a["status"] == "ACTIVE":
        for s in store.stream_sessions.values():
            if s["status"] == "ACTIVE" and _session_account_id(s) == aid:
                end_session(s)
        a["active_stream_count"] = 0
    # Revoke every PENDING Invite, releasing each hold (compensating).
    for inv in store.invites.values():
        if inv["account_id"] == aid and inv["status"] == "PENDING":
            release_invite_hold(inv, a)
            inv["status"] = "REVOKED"
            bump(inv)
    # Delete every {DOWNLOADING, READY} Download owned by any of the account's
    # profiles.
    account_profile_ids = {p["id"] for p in store.profiles.values() if p["account_id"] == aid}
    for d in store.downloads.values():
        if d["profile_id"] in account_profile_ids and d["status"] in ("DOWNLOADING", "READY"):
            delete_download(d)
    # If billing_status is still OPEN, invoice the current period.
    if a["billing_status"] == "OPEN":
        _invoice_open_period(a)
    a["status"] = "CLOSED"
    bump(a)
    return success_object(account_view(a), 200)


@app.route("/accounts/<aid>/invoice", methods=["POST"])
def invoice_account(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    a = get_account_or_404(aid)
    owner_owns_account(uid, a)
    # Invoice is defined for an OPEN billing period.
    if a["billing_status"] != "OPEN":
        raise_err(ERR_INVALID_STATE, "invoice requires billing_status OPEN; is %s" % a["billing_status"])
    body = get_json_body()
    _account_occ_check(a, body)
    _invoice_open_period(a)
    bump(a)
    return success_object(account_view(a), 200)


# ============================================================
# Plan changes (OCC-guarded)
# ============================================================
@app.route("/accounts/<aid>/plan-changes", methods=["POST"])
def create_plan_change(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    a = get_account_or_404(aid)
    owner_owns_account(uid, a)
    body = get_json_body()
    require_fields(body, ["to_plan_id", "expected_account_version"])
    # Existence of to_plan (priority 4) before OCC (priority 6).
    to_plan_id = body["to_plan_id"]
    to_plan = get_plan_or_404(to_plan_id)
    _account_occ_check(a, body)

    from_plan_id = a["plan_id"]
    from_plan = store.subscription_plans[from_plan_id]
    if to_plan["monthly_fee_cents"] > from_plan["monthly_fee_cents"]:
        direction = "UPGRADE"
    elif to_plan["monthly_fee_cents"] < from_plan["monthly_fee_cents"]:
        direction = "DOWNGRADE"
    else:
        direction = "LATERAL"

    pc = {
        "account_id": aid,
        "to_plan_id": to_plan_id,
        "from_plan_id": from_plan_id,
        "direction": direction,
    }
    stamp_lean(pc)
    store.plan_changes[pc["id"]] = pc

    a["plan_id"] = to_plan_id
    recompute_account_charge(a)
    bump(a)
    return success_object(plan_change_view(pc), 201)


@app.route("/accounts/<aid>/plan-changes", methods=["GET"])
def list_account_plan_changes(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "PlatformAdmin"])
    a = get_account_or_404(aid)
    if role == "AccountOwner":
        owner_owns_account(uid, a)
    limit, offset = pagination_params()
    items = [pc for pc in store.plan_changes.values() if pc["account_id"] == aid]
    items.sort(key=lambda pc: (pc["created_at"], pc["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([plan_change_view(pc) for pc in page], limit, offset, total)


# ============================================================
# Profiles
# ============================================================
PROFILE_KINDS = {"ADULT", "TEEN", "KID"}


@app.route("/profiles", methods=["POST"])
def create_profile():
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    body = get_json_body()
    require_fields(body, ["account_id", "display_name", "kind"])
    account_id = body["account_id"]
    a = get_account_or_404(account_id)
    owner_owns_account(uid, a)
    display_name = body["display_name"]
    kind = body["kind"]
    # Account must be ACTIVE (state legality, priority 5).
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "profiles may be created only on an ACTIVE account")
    # Uniqueness (priority 14): display_name unique among non-ARCHIVED profiles.
    if isinstance(display_name, str) and display_name:
        for p in store.profiles.values():
            if (p["account_id"] == account_id and p["status"] != "ARCHIVED"
                    and p["display_name"] == display_name):
                raise_err(ERR_DUPLICATE, "display_name already used by a non-ARCHIVED profile")
    # Profile cap (priority 17).
    plan = store.subscription_plans[a["plan_id"]]
    if non_archived_profile_count(account_id) >= plan["max_profiles"]:
        raise_err(ERR_PROFILE_CAP_REACHED, "non-ARCHIVED profile count at plan.max_profiles")
    # Field-level schema (priority 21, lowest).
    if not isinstance(display_name, str) or not display_name:
        raise_err(ERR_INVALID_REQUEST, "display_name must be a non-empty string")
    if kind not in PROFILE_KINDS:
        raise_err(ERR_INVALID_REQUEST, "kind must be one of %s" % sorted(PROFILE_KINDS))

    obj = {
        "account_id": account_id,
        "display_name": display_name,
        "kind": kind,
        "status": "ACTIVE",
        "max_rating_allowed": rating_ceiling(kind, None),
        "daily_watch_minutes_used": 0,
    }
    stamp_common(obj)
    store.profiles[obj["id"]] = obj
    return success_object(profile_view(obj), 201)


@app.route("/profiles/<pid>", methods=["GET"])
def get_profile(pid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    p = get_profile_or_404(pid)
    if role == "AccountOwner":
        owner_owns_account(uid, store.accounts.get(p["account_id"], {"id": None}))
    elif role == "ProfileUser":
        profileuser_owns_profile(uid, p)
    return success_object(profile_view(p), 200)


@app.route("/profiles/<pid>/archive", methods=["POST"])
def archive_profile(pid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    p = get_profile_or_404(pid)
    owner_owns_account(uid, store.accounts.get(p["account_id"], {"id": None}))
    if p["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "archive requires ACTIVE; profile is %s" % p["status"])
    # No ACTIVE StreamSession may reference this profile.
    for s in store.stream_sessions.values():
        if s["profile_id"] == pid and s["status"] == "ACTIVE":
            raise_err(ERR_INVALID_STATE, "profile has an ACTIVE stream session")
    p["status"] = "ARCHIVED"
    bump(p)
    # Cascade: every {DOWNLOADING, READY} Download owned by this profile -> DELETED.
    for d in store.downloads.values():
        if d["profile_id"] == pid and d["status"] in ("DOWNLOADING", "READY"):
            delete_download(d)
    return success_object(profile_view(p), 200)


@app.route("/profiles/<pid>/parental-control", methods=["POST"])
def set_parental_control(pid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    p = get_profile_or_404(pid)
    owner_owns_account(uid, store.accounts.get(p["account_id"], {"id": None}))
    body = get_json_body()
    require_fields(body, ["max_rating", "daily_watch_limit_minutes",
                          "curfew_start_min", "curfew_end_min"])
    # Uniqueness (priority 14): at most one control row per profile.
    if parental_control_for_profile(pid) is not None:
        raise_err(ERR_DUPLICATE, "a parental control already exists for this profile")
    max_rating = body["max_rating"]
    if max_rating not in MATURITY_RATINGS:
        raise_err(ERR_INVALID_REQUEST, "max_rating must be one of %s" % RATING_ORDER)
    daily_limit = as_int(body["daily_watch_limit_minutes"], "daily_watch_limit_minutes")
    if daily_limit < 0:
        raise_err(ERR_INVALID_REQUEST, "daily_watch_limit_minutes must be >= 0")
    cstart = as_int(body["curfew_start_min"], "curfew_start_min")
    cend = as_int(body["curfew_end_min"], "curfew_end_min")
    if not (0 <= cstart <= 1439) or not (0 <= cend <= 1439):
        raise_err(ERR_INVALID_REQUEST, "curfew minutes must be in 0..1439")

    obj = {
        "profile_id": pid,
        "max_rating": max_rating,
        "daily_watch_limit_minutes": daily_limit,
        "curfew_start_min": cstart,
        "curfew_end_min": cend,
    }
    stamp_common(obj)
    store.parental_controls[obj["id"]] = obj
    # Recompute the profile's ceiling (MIN with kind default).
    recompute_profile_max_rating(p)
    bump(p)
    return success_object(parental_control_view(obj), 201)


@app.route("/profiles/<pid>/parental-control", methods=["GET"])
def get_parental_control(pid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    p = get_profile_or_404(pid)
    if role == "AccountOwner":
        owner_owns_account(uid, store.accounts.get(p["account_id"], {"id": None}))
    elif role == "ProfileUser":
        profileuser_owns_profile(uid, p)
    pc = parental_control_for_profile(pid)
    # Sub-resource reverse-reach: array of length 0 or 1 (PRD §3.4).
    items = [parental_control_view(pc)] if pc else []
    return success_array(items, len(items), 0, len(items))


@app.route("/accounts/<aid>/profiles", methods=["GET"])
def list_account_profiles(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "PlatformAdmin"])
    a = get_account_or_404(aid)
    if role == "AccountOwner":
        owner_owns_account(uid, a)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = [p for p in store.profiles.values() if p["account_id"] == aid]
    if status_filter is not None:
        items = [p for p in items if p["status"] == status_filter]
    items.sort(key=lambda p: (p["created_at"], p["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([profile_view(p) for p in page], limit, offset, total)


# ============================================================
# Invites
# ============================================================
@app.route("/invites", methods=["POST"])
def send_invite():
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    body = get_json_body()
    require_fields(body, ["account_id", "invitee_email"])
    account_id = body["account_id"]
    a = get_account_or_404(account_id)
    owner_owns_account(uid, a)
    invitee_email = body["invitee_email"]
    if not isinstance(invitee_email, str) or not invitee_email:
        raise_err(ERR_INVALID_REQUEST, "invitee_email must be a non-empty string")
    # Fiscal sufficiency (priority 20): wallet must cover the per-seat hold.
    hold = INVITE_SEAT_HOLD_CENTS
    if int(a["wallet_credit_cents"]) < hold:
        raise_err(ERR_INSUFFICIENT_CREDIT, "wallet below the per-seat hold (%s)" % hold)

    token = uuid.uuid4().hex
    expires_at = (current_dt() + timedelta(hours=INVITE_TTL_HOURS))
    expires_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (expires_at.microsecond // 1000))
    obj = {
        "account_id": account_id,
        "invitee_email": invitee_email,
        "token": token,
        "status": "PENDING",
        "expires_at": expires_iso,
        "created_profile_id": None,
        "hold_amount_cents": hold,
    }
    stamp_common(obj)
    store.invites[obj["id"]] = obj
    # Debit the hold against the wallet.
    a["wallet_credit_cents"] = int(a["wallet_credit_cents"]) - hold
    return success_object(invite_view(obj), 201)


@app.route("/accounts/<aid>/invites", methods=["GET"])
def list_account_invites(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "PlatformAdmin"])
    a = get_account_or_404(aid)
    if role == "AccountOwner":
        owner_owns_account(uid, a)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = [i for i in store.invites.values() if i["account_id"] == aid]
    if status_filter is not None:
        items = [i for i in items if i["status"] == status_filter]
    items.sort(key=lambda i: (i["created_at"], i["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([invite_view(i) for i in page], limit, offset, total)


@app.route("/invites/<iid>/accept", methods=["POST"])
def accept_invite(iid):
    # Anonymous, token-bearing: no auth headers required.
    inv = get_invite_or_404(iid)
    body = get_json_body()
    require_fields(body, ["token"])
    # State legality (priority 5): only from PENDING.
    if inv["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "invite is %s, not PENDING" % inv["status"])
    a = store.accounts.get(inv["account_id"])
    # Token + expiry (priority 19): mismatched token or past expiry.
    if body["token"] != inv["token"]:
        raise_err(ERR_INVITE_EXPIRED, "invite token mismatch")
    if current_dt() >= parse_iso_to_dt(inv["expires_at"]):
        raise_err(ERR_INVITE_EXPIRED, "invite has expired")
    # Account must be ACTIVE.
    if not a or a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "owning account is not ACTIVE")
    # Profile cap (priority 17).
    plan = store.subscription_plans[a["plan_id"]]
    if non_archived_profile_count(a["id"]) >= plan["max_profiles"]:
        raise_err(ERR_PROFILE_CAP_REACHED, "profile cap reached")

    # Mint a new ADULT/ACTIVE profile; commit the hold (NOT released).
    new_profile = {
        "account_id": a["id"],
        "display_name": inv["invitee_email"],
        "kind": "ADULT",
        "status": "ACTIVE",
        "max_rating_allowed": rating_ceiling("ADULT", None),
        "daily_watch_minutes_used": 0,
    }
    stamp_common(new_profile)
    store.profiles[new_profile["id"]] = new_profile
    inv["created_profile_id"] = new_profile["id"]
    inv["status"] = "ACCEPTED"
    bump(inv)
    return success_object(invite_view(inv), 200)


@app.route("/invites/<iid>/decline", methods=["POST"])
def decline_invite(iid):
    # Anonymous, token-bearing: no auth headers required.
    inv = get_invite_or_404(iid)
    body = get_json_body()
    require_fields(body, ["token"])
    if inv["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "invite is %s, not PENDING" % inv["status"])
    if body["token"] != inv["token"]:
        raise_err(ERR_INVITE_EXPIRED, "invite token mismatch")
    a = store.accounts.get(inv["account_id"])
    if a:
        release_invite_hold(inv, a)
    inv["status"] = "DECLINED"
    bump(inv)
    return success_object(invite_view(inv), 200)


@app.route("/invites/<iid>/revoke", methods=["POST"])
def revoke_invite(iid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    inv = get_invite_or_404(iid)
    a = store.accounts.get(inv["account_id"])
    owner_owns_account(uid, a if a else {"id": None})
    if inv["status"] != "PENDING":
        raise_err(ERR_INVALID_STATE, "invite is %s, not PENDING" % inv["status"])
    if a:
        release_invite_hold(inv, a)
    inv["status"] = "REVOKED"
    bump(inv)
    return success_object(invite_view(inv), 200)


# ============================================================
# Devices
# ============================================================
DEVICE_PLATFORMS = {"TV", "MOBILE", "WEB", "TABLET"}


@app.route("/devices", methods=["POST"])
def register_device():
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    body = get_json_body()
    require_fields(body, ["account_id", "device_label", "platform"])
    account_id = body["account_id"]
    a = get_account_or_404(account_id)
    owner_owns_account(uid, a)
    # Account must be ACTIVE (state legality, priority 5).
    if a["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "devices may be registered only on an ACTIVE account")
    # Device cap (priority 18).
    plan = store.subscription_plans[a["plan_id"]]
    if int(a["registered_device_count"]) >= plan["max_registered_devices"]:
        raise_err(ERR_DEVICE_CAP_REACHED, "registered_device_count at plan.max_registered_devices")
    label = body["device_label"]
    platform = body["platform"]
    if not isinstance(label, str) or not label:
        raise_err(ERR_INVALID_REQUEST, "device_label must be a non-empty string")
    if platform not in DEVICE_PLATFORMS:
        raise_err(ERR_INVALID_REQUEST, "platform must be one of %s" % sorted(DEVICE_PLATFORMS))
    supports_hd = body.get("supports_hd", True)
    if not isinstance(supports_hd, bool):
        raise_err(ERR_INVALID_REQUEST, "supports_hd must be boolean")

    obj = {
        "account_id": account_id,
        "device_label": label,
        "platform": platform,
        "status": "REGISTERED",
        "supports_hd": supports_hd,
    }
    stamp_common(obj)
    store.devices[obj["id"]] = obj
    a["registered_device_count"] = int(a["registered_device_count"]) + 1
    bump(a)
    return success_object(device_view(obj), 201)


@app.route("/accounts/<aid>/devices", methods=["GET"])
def list_account_devices(aid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "PlatformAdmin"])
    a = get_account_or_404(aid)
    if role == "AccountOwner":
        owner_owns_account(uid, a)
    limit, offset = pagination_params()
    status_filter = request.args.get("status")
    items = [d for d in store.devices.values() if d["account_id"] == aid]
    if status_filter is not None:
        items = [d for d in items if d["status"] == status_filter]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([device_view(d) for d in page], limit, offset, total)


@app.route("/devices/<did>/deregister", methods=["POST"])
def deregister_device(did):
    uid, role = get_auth()
    require_role(role, ["AccountOwner"])
    d = get_device_or_404(did)
    a = store.accounts.get(d["account_id"])
    owner_owns_account(uid, a if a else {"id": None})
    if d["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "deregister requires REGISTERED; device is %s" % d["status"])
    # No ACTIVE StreamSession may reference this device.
    for s in store.stream_sessions.values():
        if s["device_id"] == did and s["status"] == "ACTIVE":
            raise_err(ERR_INVALID_STATE, "device has an ACTIVE stream session")
    d["status"] = "DEREGISTERED"
    bump(d)
    if a:
        a["registered_device_count"] = max(0, int(a["registered_device_count"]) - 1)
        bump(a)
    # Cascade: every {DOWNLOADING, READY} Download licensed to this device -> DELETED.
    for dl in store.downloads.values():
        if dl["device_id"] == did and dl["status"] in ("DOWNLOADING", "READY"):
            delete_download(dl)
    return success_object(device_view(d), 200)


# ============================================================
# Stream sessions — the gauntlet of gates (PRD §3.6 ordered cascade)
# ============================================================
def _session_account_id(session):
    prof = store.profiles.get(session["profile_id"])
    return prof["account_id"] if prof else None


def _in_curfew_window(minute, start, end):
    """Curfew window: open at start inclusive, closed at end exclusive; wraps
    past midnight when end < start (PRD §3.6). When start == end the window is
    empty (no minute is inside)."""
    if start == end:
        return False
    if start < end:
        return start <= minute < end
    # Wrap: [start, 1440) U [0, end)
    return minute >= start or minute < end


@app.route("/stream-sessions", methods=["POST"])
def create_stream_session():
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    body = get_json_body()
    require_fields(body, ["profile_id", "device_id", "title_id"])
    profile_id = body["profile_id"]
    device_id = body["device_id"]
    title_id = body["title_id"]
    # Ownership (priority 3): ProfileUser must own the referenced profile.
    if uid != profile_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Profile")
    # Existence left-to-right (priority 4): profile, device, title.
    profile = get_profile_or_404(profile_id)
    device = get_device_or_404(device_id)
    title = get_title_or_404(title_id)
    account = store.accounts.get(profile["account_id"])

    # State legality (priority 5): account ACTIVE, profile ACTIVE, device REGISTERED.
    if not account or account["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "owning account is not ACTIVE")
    if profile["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "profile is not ACTIVE")
    if device["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "device is not REGISTERED")

    # Cross-account coherence (priority 7): device belongs to profile's account.
    if device["account_id"] != profile["account_id"]:
        raise_err(ERR_CROSS_ACCOUNT_REFERENCE, "device belongs to a different account")

    # Rating gate (priority 8).
    recompute_profile_max_rating(profile)
    if RATING_RANK[title["maturity_rating"]] > RATING_RANK[profile["max_rating_allowed"]]:
        raise_err(ERR_RATING_BLOCKED, "title rating exceeds the profile's ceiling")

    pc = parental_control_for_profile(profile_id)
    now_min = current_minute_of_day()
    # Curfew gate (priority 9): only when a control exists.
    if pc is not None and _in_curfew_window(now_min, pc["curfew_start_min"], pc["curfew_end_min"]):
        raise_err(ERR_CURFEW_BLOCKED, "stream start falls inside the curfew window")
    # Daily-limit gate (priority 10): only when a positive limit is set.
    if pc is not None and int(pc["daily_watch_limit_minutes"]) > 0:
        projected = int(profile["daily_watch_minutes_used"]) + int(title["runtime_minutes"])
        if projected > int(pc["daily_watch_limit_minutes"]):
            raise_err(ERR_DAILY_LIMIT_EXCEEDED, "would exceed the profile's daily limit")

    # Device single-occupancy overlap (priority 11): half-open interval.
    for s in store.stream_sessions.values():
        if s["device_id"] != device_id or s["status"] != "ACTIVE":
            continue
        s_title = store.titles.get(s["title_id"])
        s_runtime = s_title["runtime_minutes"] if s_title else 0
        start = s["started_at_min"]
        end = start + s_runtime  # exclusive
        if start <= now_min < end:
            raise_err(ERR_DEVICE_BUSY, "device hosts an overlapping ACTIVE session")

    # Concurrent cap (priority 15).
    plan = store.subscription_plans[account["plan_id"]]
    if int(account["active_stream_count"]) >= plan["concurrent_stream_cap"]:
        raise_err(ERR_CONCURRENT_CAP_REACHED, "active_stream_count at plan.concurrent_stream_cap")

    obj = {
        "profile_id": profile_id,
        "device_id": device_id,
        "title_id": title_id,
        "status": "ACTIVE",
        "started_at_min": now_min,
        "minutes_watched": 0,
        "ad_breaks_served": ad_break_count(plan["ad_free"], title["runtime_minutes"]),
    }
    stamp_common(obj)
    store.stream_sessions[obj["id"]] = obj
    account["active_stream_count"] = int(account["active_stream_count"]) + 1
    bump(account)
    return success_object(stream_session_view(obj), 201)


@app.route("/stream-sessions/<sid>/stop", methods=["POST"])
def stop_stream_session(sid):
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    s = get_session_or_404(sid)
    if uid != s["profile_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this session's Profile")
    if s["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "session is %s, not ACTIVE" % s["status"])
    end_session(s)
    account = store.accounts.get(_session_account_id(s))
    if account:
        account["active_stream_count"] = max(0, int(account["active_stream_count"]) - 1)
        bump(account)
    return success_object(stream_session_view(s), 200)


@app.route("/stream-sessions/<sid>", methods=["GET"])
def get_stream_session(sid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    s = get_session_or_404(sid)
    if role == "AccountOwner":
        owner_owns_account(uid, store.accounts.get(_session_account_id(s), {"id": None}))
    elif role == "ProfileUser":
        if uid != s["profile_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this session's Profile")
    return success_object(stream_session_view(s), 200)


@app.route("/stream-sessions", methods=["GET"])
def list_stream_sessions():
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    limit, offset = pagination_params()
    items = list(store.stream_sessions.values())
    for key in ("profile_id", "device_id", "title_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [s for s in items if s[key] == val]
    if role == "ProfileUser":
        items = [s for s in items if s["profile_id"] == uid]
    elif role == "AccountOwner":
        items = [s for s in items if _session_account_id(s) == uid]
    items.sort(key=lambda s: (s["created_at"], s["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([stream_session_view(s) for s in page], limit, offset, total)


# ============================================================
# Downloads
# ============================================================
DOWNLOAD_QUALITIES = {"SD", "HD"}


@app.route("/downloads", methods=["POST"])
def create_download():
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    body = get_json_body()
    require_fields(body, ["profile_id", "device_id", "title_id"])
    profile_id = body["profile_id"]
    device_id = body["device_id"]
    title_id = body["title_id"]
    if uid != profile_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Profile")
    profile = get_profile_or_404(profile_id)
    device = get_device_or_404(device_id)
    title = get_title_or_404(title_id)
    account = store.accounts.get(profile["account_id"])

    quality = body.get("quality", "SD")
    if quality not in DOWNLOAD_QUALITIES:
        raise_err(ERR_INVALID_REQUEST, "quality must be SD or HD")

    # State legality (priority 5): account ACTIVE, profile ACTIVE, device REGISTERED.
    if not account or account["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "owning account is not ACTIVE")
    if profile["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "profile is not ACTIVE")
    if device["status"] != "REGISTERED":
        raise_err(ERR_INVALID_STATE, "device is not REGISTERED")

    # Cross-account coherence (priority 7).
    if device["account_id"] != profile["account_id"]:
        raise_err(ERR_CROSS_ACCOUNT_REFERENCE, "device belongs to a different account")

    plan = store.subscription_plans[account["plan_id"]]
    # HD eligibility (priority 12).
    if quality == "HD":
        if not plan["hd_offline_allowed"] or not device["supports_hd"]:
            raise_err(ERR_HD_NOT_ALLOWED, "HD requires plan.hd_offline_allowed and device.supports_hd")
    # Downloadability (priority 13).
    if not title["downloadable"]:
        raise_err(ERR_TITLE_NOT_DOWNLOADABLE, "title is not downloadable")
    # Download quota (priority 16).
    if profile_active_downloads_count(profile_id) >= plan["download_quota_per_profile"]:
        raise_err(ERR_DOWNLOAD_QUOTA_REACHED, "profile at plan.download_quota_per_profile")

    obj = {
        "profile_id": profile_id,
        "device_id": device_id,
        "title_id": title_id,
        "status": "DOWNLOADING",
        "quality": quality,
        "license_expires_at": None,
        "size_mb": download_size(title["license_size_mb"], quality),
    }
    stamp_common(obj)
    store.downloads[obj["id"]] = obj
    return success_object(download_view(obj), 201)


@app.route("/downloads/<did>/complete", methods=["POST"])
def complete_download(did):
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    d = get_download_or_404(did)
    if uid != d["profile_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Download's Profile")
    if d["status"] != "DOWNLOADING":
        raise_err(ERR_INVALID_STATE, "complete requires DOWNLOADING; download is %s" % d["status"])
    expiry = current_dt() + timedelta(hours=DOWNLOAD_LICENSE_HOURS)
    d["license_expires_at"] = expiry.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03dZ" % (expiry.microsecond // 1000))
    d["status"] = "READY"
    bump(d)
    return success_object(download_view(d), 200)


@app.route("/downloads/<did>", methods=["DELETE"])
def delete_download_endpoint(did):
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    d = get_download_or_404(did)
    if uid != d["profile_id"]:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Download's Profile")
    if d["status"] not in ("DOWNLOADING", "READY"):
        raise_err(ERR_INVALID_STATE, "delete requires DOWNLOADING or READY; download is %s" % d["status"])
    d["status"] = "DELETED"
    bump(d)
    return success_object(download_view(d), 200)


@app.route("/downloads/<did>", methods=["GET"])
def get_download(did):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    d = get_download_or_404(did)
    prof = store.profiles.get(d["profile_id"])
    if role == "AccountOwner":
        acc = store.accounts.get(prof["account_id"]) if prof else None
        owner_owns_account(uid, acc if acc else {"id": None})
    elif role == "ProfileUser":
        if uid != d["profile_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Download's Profile")
    return success_object(download_view(d), 200)


@app.route("/downloads", methods=["GET"])
def list_downloads():
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    limit, offset = pagination_params()
    items = list(store.downloads.values())
    for key in ("profile_id", "device_id", "title_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d[key] == val]
    if role == "ProfileUser":
        items = [d for d in items if d["profile_id"] == uid]
    elif role == "AccountOwner":
        def _acc_of(d):
            prof = store.profiles.get(d["profile_id"])
            return prof["account_id"] if prof else None
        items = [d for d in items if _acc_of(d) == uid]
    items.sort(key=lambda d: (d["created_at"], d["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([download_view(d) for d in page], limit, offset, total)


# ============================================================
# Watch progress (cross-device sync)
# ============================================================
@app.route("/watch-progress", methods=["PUT"])
def upsert_watch_progress():
    uid, role = get_auth()
    require_role(role, ["ProfileUser"])
    body = get_json_body()
    require_fields(body, ["profile_id", "title_id", "position_min", "last_device_id"])
    profile_id = body["profile_id"]
    title_id = body["title_id"]
    last_device_id = body["last_device_id"]
    if uid != profile_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this Profile")
    profile = get_profile_or_404(profile_id)
    title = get_title_or_404(title_id)
    device = get_device_or_404(last_device_id)

    position_min = body["position_min"]
    position_min = as_int(position_min, "position_min")
    if position_min < 0:
        raise_err(ERR_INVALID_REQUEST, "position_min must be >= 0")

    # Cross-account coherence (priority 7): last_device_id belongs to the
    # profile's account (title is global).
    if device["account_id"] != profile["account_id"]:
        raise_err(ERR_CROSS_ACCOUNT_REFERENCE, "last_device_id belongs to a different account")

    completed = position_min >= int(title["runtime_minutes"])
    # Upsert: at most one row per (profile, title) — replace in place.
    existing = None
    for w in store.watch_progress.values():
        if w["profile_id"] == profile_id and w["title_id"] == title_id:
            existing = w
            break
    if existing is not None:
        existing["position_min"] = position_min
        existing["last_device_id"] = last_device_id
        existing["completed"] = completed
        bump(existing)
        return success_object(watch_progress_view(existing), 200)

    obj = {
        "profile_id": profile_id,
        "title_id": title_id,
        "position_min": position_min,
        "last_device_id": last_device_id,
        "completed": completed,
    }
    stamp_common(obj)
    store.watch_progress[obj["id"]] = obj
    return success_object(watch_progress_view(obj), 200)


@app.route("/watch-progress/<wid>", methods=["GET"])
def get_watch_progress(wid):
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    w = get_watch_progress_or_404(wid)
    prof = store.profiles.get(w["profile_id"])
    if role == "AccountOwner":
        acc = store.accounts.get(prof["account_id"]) if prof else None
        owner_owns_account(uid, acc if acc else {"id": None})
    elif role == "ProfileUser":
        if uid != w["profile_id"]:
            raise_err(ERR_NOT_RESOURCE_OWNER, "ProfileUser does not own this WatchProgress' Profile")
    return success_object(watch_progress_view(w), 200)


@app.route("/watch-progress", methods=["GET"])
def list_watch_progress():
    uid, role = get_auth()
    require_role(role, ["AccountOwner", "ProfileUser", "PlatformAdmin"])
    limit, offset = pagination_params()
    items = list(store.watch_progress.values())
    for key in ("profile_id", "title_id"):
        val = request.args.get(key)
        if val is not None:
            items = [w for w in items if w[key] == val]
    if role == "ProfileUser":
        items = [w for w in items if w["profile_id"] == uid]
    elif role == "AccountOwner":
        def _acc_of(w):
            prof = store.profiles.get(w["profile_id"])
            return prof["account_id"] if prof else None
        items = [w for w in items if _acc_of(w) == uid]
    items.sort(key=lambda w: (w["created_at"], w["id"]))
    page, total = paginate(items, limit, offset)
    return success_array([watch_progress_view(w) for w in page], limit, offset, total)


# ============================================================
# Test-driving / clock seam
# ============================================================
@app.route("/_clock/advance", methods=["POST"])
def clock_advance():
    _, role = get_auth()
    require_role(role, ["PlatformAdmin"])
    body = get_json_body()
    require_fields(body, ["to_iso8601"])
    to_iso = body["to_iso8601"]
    try:
        new_dt = parse_iso_to_dt(to_iso)
    except Exception:
        raise_err(ERR_INVALID_REQUEST, "to_iso8601 must be ISO 8601")
    run_sweeps = body.get("run_sweeps", False)
    if not isinstance(run_sweeps, bool):
        raise_err(ERR_INVALID_REQUEST, "run_sweeps must be boolean")

    prev_day = utc_day_ordinal(parse_iso_to_dt(store.current_utc))
    store.current_utc = to_iso
    new_day = utc_day_ordinal(new_dt)

    if run_sweeps:
        # PENDING Invites past expires_at -> EXPIRED (release holds).
        for inv in store.invites.values():
            if inv["status"] == "PENDING" and new_dt >= parse_iso_to_dt(inv["expires_at"]):
                a = store.accounts.get(inv["account_id"])
                if a:
                    release_invite_hold(inv, a)
                inv["status"] = "EXPIRED"
                bump(inv)
        # READY Downloads past license_expires_at -> EXPIRED (free quota slot).
        for d in store.downloads.values():
            if d["status"] == "READY" and d["license_expires_at"] is not None:
                if new_dt >= parse_iso_to_dt(d["license_expires_at"]):
                    d["status"] = "EXPIRED"
                    bump(d)
        # Profiles crossing UTC midnight reset daily_watch_minutes_used to 0.
        if new_day != prev_day:
            for p in store.profiles.values():
                if int(p["daily_watch_minutes_used"]) != 0:
                    p["daily_watch_minutes_used"] = 0
                    bump(p)

    return success_object({}, 200)


# ============================================================
# Health
# ============================================================
@app.route("/", methods=["GET"])
def root():
    return success_object({"service": "streaming-family-plan"}, 200)


@app.route("/healthz", methods=["GET"])
def healthz():
    return success_object({"ok": True}, 200)


# ============================================================
# Entry
# ============================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True, debug=False, use_reloader=False)
