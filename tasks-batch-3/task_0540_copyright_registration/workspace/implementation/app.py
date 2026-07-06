"""Copyright Registration & Licensing API (US Copyright Office model).

Single-file Flask implementation. In-memory store; starts empty on every boot.
All time-sensitive behavior is governed by a logical clock (default 2026-05-01T00:00:00Z).
"""
import os
import re
import uuid
import random
import string
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timezone, timedelta

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (from PRD / scaffold)
# ---------------------------------------------------------------------------
SINGLE_BASE = 4500
STANDARD_BASE = 6500
ADDL_CLAIMANT = 1500
EXPEDITE_SURCHARGE = 80000

BPS_DENOMINATOR = 10000

DEPOSIT_MIN_COPIES_ELECTRONIC = 1
DEPOSIT_MIN_COPIES_PHYSICAL = 2

CORRESPONDENCE_DAYS = 90
RENEWAL_TERM_YEARS = 28
RENEWAL_WINDOW_SPAN_YEARS = 1
RESTORE_MIN_DAYS = 10
RESTORE_MAX_DAYS = 14
TERMINATION_WINDOW_START_YEARS = 35
TERMINATION_WINDOW_SPAN_YEARS = 5

ROLES = {"RightsHolder", "Examiner", "Complainant", "Admin"}
ALL_ROLES = ["RightsHolder", "Examiner", "Complainant", "Admin"]

WORK_TYPES = {"LITERARY", "MUSICAL", "SOUND_RECORDING", "VISUAL_ARTS",
              "DRAMATIC", "ARCHITECTURAL", "MOTION_PICTURE"}
FILING_BASES = {"SINGLE_AUTHOR_SINGLE_WORK", "STANDARD"}
DEPOSIT_TYPES = {"ELECTRONIC", "PHYSICAL"}
LICENSE_TYPES = {"EXCLUSIVE", "NON_EXCLUSIVE"}
RIGHT_TYPES = {"REPRODUCTION", "DISTRIBUTION", "PERFORMANCE", "DERIVATIVE", "PUBLIC_DISPLAY"}
TERRITORIES = {"US", "EU", "WORLD"}
ROYALTY_BASES = {"GROSS", "NET"}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# In-memory state (fresh on every boot)
# ---------------------------------------------------------------------------
class Store:
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self.works = {}
        self.applications = {}
        self.deposits = {}
        self.certificates = {}
        self.recordations = {}
        self.licenses = {}
        self.royalty_statements = {}
        self.dmca_takedowns = {}
        self.counter_notices = {}
        self.terminations = {}
        self.reg_counter = 0


DB = Store()


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=""):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=""):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def now():
    return DB.clock


def fmt_ms(dt):
    """ISO 8601 UTC with 3 fractional digits (timestamps/instants)."""
    ms = int(dt.microsecond / 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms


def fmt_day(dt):
    """ISO 8601 UTC at day granularity, time zeroed (calendar-date fields)."""
    return dt.strftime("%Y-%m-%dT00:00:00Z")


def parse_iso(s):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Returns None on failure.
    """
    if not isinstance(s, str):
        return None
    txt = s.strip()
    if not txt:
        return None
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        # Feb 29 -> Feb 28 in the target (non-leap) year.
        return dt.replace(month=2, day=28, year=dt.year + years)


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def base_meta():
    return {
        "api_request_id": gen_request_id(),
        "api_request_timestamp": fmt_ms(now()),
    }


def success(data, code=200, is_list=False, pagination=None):
    meta = base_meta()
    if pagination is not None:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": "array" if is_list else "object",
        "data": data,
    }
    return jsonify(body), code


def error_response(error_id, http_status, message):
    body = {
        "meta": base_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(e):
    return error_response(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def handle_404(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def require_role(allowed):
    role = request.headers.get("X-User-Role")
    if role is None or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unknown role")
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")
    g.role = role
    g.user_id = request.headers.get("X-User-ID", "")
    return role


# ---------------------------------------------------------------------------
# Body / validation helpers
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        return {}
    if not isinstance(body, dict):
        err("ERR_VALIDATION", 422, "Request body must be a JSON object")
    return body


def require_field(body, key):
    if key not in body or body[key] is None:
        err("ERR_VALIDATION", 422, "Missing required field: %s" % key)
    return body[key]


def require_str(body, key):
    v = require_field(body, key)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 422, "Field %s must be a non-empty string" % key)
    return v


def require_enum(body, key, valid):
    v = require_field(body, key)
    if not isinstance(v, str) or v not in valid:
        err("ERR_VALIDATION", 422, "Field %s has an invalid value" % key)
    return v


def require_nonneg_int(body, key):
    v = require_field(body, key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        err("ERR_VALIDATION", 422, "Field %s must be a non-negative integer" % key)
    return v


def opt_nonneg_int(body, key, default=0):
    if key not in body or body[key] is None:
        return default
    v = body[key]
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        err("ERR_VALIDATION", 422, "Field %s must be a non-negative integer" % key)
    return v


def require_datetime(body, key):
    v = require_field(body, key)
    if not isinstance(v, str) or parse_iso(v) is None:
        err("ERR_VALIDATION", 422, "Field %s must be a valid ISO 8601 datetime" % key)
    return v


def parse_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        try:
            limit = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_PAGINATION", 422, "limit must be an integer")
    if "offset" in args:
        raw = args.get("offset")
        try:
            offset = int(raw)
        except (TypeError, ValueError):
            err("ERR_INVALID_PAGINATION", 422, "offset must be an integer")
    if limit < 1 or limit > 100:
        err("ERR_INVALID_PAGINATION", 422, "limit out of range")
    if offset < 0:
        err("ERR_INVALID_PAGINATION", 422, "offset out of range")
    return limit, offset


def paginate(items):
    limit, offset = parse_pagination()
    items = sorted(items, key=lambda r: r["created_at"])
    total = len(items)
    page = items[offset:offset + limit]
    has_more = (offset + limit) < total
    pag = {"limit": limit, "offset": offset, "total_count": total, "has_more": has_more}
    return page, pag


# ---------------------------------------------------------------------------
# Entity helpers
# ---------------------------------------------------------------------------
def new_common():
    ts = fmt_ms(now())
    return {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = fmt_ms(now())


def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return rec


def clean(rec):
    return {k: v for k, v in rec.items() if not k.startswith("_")}


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def round_half_up(numerator):
    return int((Decimal(numerator) / Decimal(BPS_DENOMINATOR)).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP))


def compute_fee(filing_basis, claimant_count, is_expedited, is_published):
    if filing_basis == "SINGLE_AUTHOR_SINGLE_WORK" and claimant_count == 1 and not is_published:
        base = SINGLE_BASE
    else:
        base = STANDARD_BASE
        base += max(0, claimant_count - 1) * ADDL_CLAIMANT
    if is_expedited:
        base += EXPEDITE_SURCHARGE
    return base


def compute_distribution(accrued, owner_shares):
    n = len(owner_shares)
    base = []
    for owner in owner_shares:
        share = owner.get("share_bps", 0)
        base.append((accrued * share) // BPS_DENOMINATOR)
    remainder = accrued - sum(base)
    # order indices by share_bps DESC, tie-break by original index ASC
    order = sorted(range(n), key=lambda i: (-owner_shares[i].get("share_bps", 0), i))
    for i in range(remainder):
        base[order[i]] += 1
    distribution = [
        {"name": owner_shares[i].get("name"), "amount_cents": base[i]}
        for i in range(n)
    ]
    return distribution, sum(base)


def recompute_work_status(work):
    """(unused hook) — Work.registration_status is set directly by transitions."""
    return work


# ---------------------------------------------------------------------------
# Clock endpoint
# ---------------------------------------------------------------------------
@app.route("/copyright/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_role({"Admin"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        err("ERR_CLOCK_INVALID", 422, "to_iso8601 is required")
    dt = parse_iso(body["to_iso8601"])
    if dt is None:
        err("ERR_CLOCK_INVALID", 422, "Invalid ISO 8601 datetime")
    DB.clock = dt
    return success({"current_utc": fmt_ms(dt)}, 200)


# ---------------------------------------------------------------------------
# Work
# ---------------------------------------------------------------------------
def serialize_work(w):
    return clean(w)


@app.route("/copyright/works", methods=["POST"])
def create_work():
    require_role({"RightsHolder"})
    body = get_body()
    title = require_str(body, "title")
    work_type = require_enum(body, "work_type", WORK_TYPES)
    year = require_nonneg_int(body, "year_of_creation")
    author_name = require_str(body, "author_name")
    owner_shares = require_field(body, "owner_shares")
    if not isinstance(owner_shares, list) or len(owner_shares) == 0:
        err("ERR_VALIDATION", 422, "owner_shares must be a non-empty list")
    total = 0
    norm_shares = []
    for item in owner_shares:
        if not isinstance(item, dict):
            err("ERR_VALIDATION", 422, "owner_shares entries must be objects")
        name = item.get("name")
        share = item.get("share_bps")
        if not isinstance(name, str) or name == "":
            err("ERR_VALIDATION", 422, "owner share requires a name")
        if isinstance(share, bool) or not isinstance(share, int) or share < 0:
            err("ERR_VALIDATION", 422, "share_bps must be a non-negative integer")
        total += share
        norm_shares.append({"name": name, "share_bps": share})
    if total != BPS_DENOMINATOR:
        err("ERR_VALIDATION", 422, "share_bps must sum to exactly 10000")

    is_published = body.get("is_published", False)
    if is_published is None:
        is_published = False
    if not isinstance(is_published, bool):
        err("ERR_VALIDATION", 422, "is_published must be a boolean")
    publication_date = body.get("publication_date")
    if is_published:
        if publication_date is None or not isinstance(publication_date, str) or parse_iso(publication_date) is None:
            err("ERR_VALIDATION", 422, "publication_date required when is_published is true")

    w = new_common()
    w.update({
        "title": title,
        "work_type": work_type,
        "year_of_creation": year,
        "author_name": author_name,
        "is_published": is_published,
        "publication_date": publication_date,
        "owner_shares": norm_shares,
        "owner_user_id": g.user_id,
        "registration_status": "UNREGISTERED",
        "current_owner_name": author_name,
    })
    DB.works[w["id"]] = w
    return success(serialize_work(w), 201)


@app.route("/copyright/works/<rid>", methods=["GET"])
def get_work(rid):
    require_role(set(ALL_ROLES))
    w = get_or_404(DB.works, rid)
    return success(serialize_work(w), 200)


@app.route("/copyright/works", methods=["GET"])
def list_works():
    require_role(set(ALL_ROLES))
    work_type = request.args.get("work_type")
    reg_status = request.args.get("registration_status")
    items = list(DB.works.values())
    if work_type is not None:
        items = [w for w in items if w["work_type"] == work_type]
    if reg_status is not None:
        items = [w for w in items if w["registration_status"] == reg_status]
    page, pag = paginate(items)
    return success([serialize_work(w) for w in page], 200, is_list=True, pagination=pag)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
def serialize_app(a):
    return clean(a)


@app.route("/copyright/applications", methods=["POST"])
def create_application():
    require_role({"RightsHolder"})
    body = get_body()
    work_id = require_str(body, "work_id")
    filing_basis = require_enum(body, "filing_basis", FILING_BASES)
    claimant_count = body.get("claimant_count", 1)
    if claimant_count is None:
        claimant_count = 1
    if isinstance(claimant_count, bool) or not isinstance(claimant_count, int) or claimant_count < 1:
        err("ERR_VALIDATION", 422, "claimant_count must be an integer >= 1")
    is_expedited = body.get("is_expedited", False)
    if is_expedited is None:
        is_expedited = False
    if not isinstance(is_expedited, bool):
        err("ERR_VALIDATION", 422, "is_expedited must be a boolean")

    # existence
    get_or_404(DB.works, work_id)
    # referential: only one non-terminal application per work
    terminal = {"REGISTERED", "REFUSED", "WITHDRAWN"}
    for a in DB.applications.values():
        if a["work_id"] == work_id and a["status"] not in terminal:
            err("ERR_DUPLICATE_ACTIVE_APPLICATION", 409,
                "A non-terminal application already exists for this work")

    a = new_common()
    a.update({
        "work_id": work_id,
        "applicant_user_id": g.user_id,
        "filing_basis": filing_basis,
        "claimant_count": claimant_count,
        "is_expedited": is_expedited,
        "status": "DRAFT",
        "fee_due_cents": 0,
        "fee_paid_cents": 0,
        "fee_refunded_cents": 0,
        "net_fee_cents": 0,
        "correspondence_open": False,
        "correspondence_deadline": None,
        "correspondence_rounds": 0,
        "submitted_at": None,
        "fee_paid_at": None,
        "registered_at": None,
    })
    DB.applications[a["id"]] = a
    return success(serialize_app(a), 201)


@app.route("/copyright/applications/<rid>", methods=["GET"])
def get_application(rid):
    require_role(set(ALL_ROLES))
    a = get_or_404(DB.applications, rid)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications", methods=["GET"])
def list_applications():
    require_role(set(ALL_ROLES))
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    items = list(DB.applications.values())
    if work_id is not None:
        items = [a for a in items if a["work_id"] == work_id]
    if status is not None:
        items = [a for a in items if a["status"] == status]
    page, pag = paginate(items)
    return success([serialize_app(a) for a in page], 200, is_list=True, pagination=pag)


def owner_check(app_rec):
    if g.user_id != app_rec["applicant_user_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Acting user does not own this application")


@app.route("/copyright/applications/<rid>/submit", methods=["POST"])
def submit_application(rid):
    require_role({"RightsHolder"})
    a = get_or_404(DB.applications, rid)
    owner_check(a)
    if a["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Application is not in DRAFT")
    work = DB.works.get(a["work_id"])
    # filing basis validity
    if a["filing_basis"] == "SINGLE_AUTHOR_SINGLE_WORK":
        if a["claimant_count"] != 1 or work["is_published"]:
            err("ERR_FILING_BASIS_INVALID", 409,
                "SINGLE_AUTHOR_SINGLE_WORK requires claimant_count == 1 and an unpublished work")
    if work["is_published"] and not work.get("publication_date"):
        err("ERR_VALIDATION", 422, "publication_date required for a published work")

    a["fee_due_cents"] = compute_fee(
        a["filing_basis"], a["claimant_count"], a["is_expedited"], work["is_published"])
    a["submitted_at"] = fmt_ms(now())
    a["status"] = "SUBMITTED"
    touch(a)
    # Work -> PENDING
    work["registration_status"] = "PENDING"
    touch(work)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications/<rid>/pay-fee", methods=["POST"])
def pay_fee(rid):
    require_role({"RightsHolder"})
    a = get_or_404(DB.applications, rid)
    owner_check(a)
    body = get_body()
    amount = require_nonneg_int(body, "amount_cents")
    if amount != a["fee_due_cents"]:
        err("ERR_FEE_AMOUNT_MISMATCH", 409, "amount_cents must equal fee_due_cents")
    a["fee_paid_cents"] = amount
    a["net_fee_cents"] = a["fee_paid_cents"] - a["fee_refunded_cents"]
    a["fee_paid_at"] = fmt_ms(now())
    touch(a)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications/<rid>/begin-examination", methods=["POST"])
def begin_examination(rid):
    require_role({"Examiner"})
    a = get_or_404(DB.applications, rid)
    if a["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Application is not SUBMITTED")
    accepted = any(d for d in DB.deposits.values()
                   if d["application_id"] == a["id"] and d["status"] == "ACCEPTED")
    if not accepted:
        err("ERR_DEPOSIT_NOT_ACCEPTED", 409, "No accepted deposit for this application")
    if a["fee_paid_cents"] < a["fee_due_cents"]:
        err("ERR_FEE_NOT_PAID", 409, "Fee not fully paid")
    a["status"] = "UNDER_EXAMINATION"
    touch(a)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications/<rid>/issue-correspondence", methods=["POST"])
def issue_correspondence(rid):
    require_role({"Examiner"})
    a = get_or_404(DB.applications, rid)
    body = get_body()
    require_field(body, "issue_code")
    require_field(body, "message")
    if a["status"] != "UNDER_EXAMINATION":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_EXAMINATION")
    a["status"] = "CORRESPONDENCE"
    a["correspondence_open"] = True
    a["correspondence_deadline"] = fmt_ms(now() + timedelta(days=CORRESPONDENCE_DAYS))
    a["correspondence_rounds"] += 1
    touch(a)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications/<rid>/respond-correspondence", methods=["POST"])
def respond_correspondence(rid):
    require_role({"RightsHolder"})
    a = get_or_404(DB.applications, rid)
    owner_check(a)
    body = get_body()
    require_field(body, "message")
    if a["status"] != "CORRESPONDENCE":
        err("ERR_INVALID_STATE", 409, "Application is not in CORRESPONDENCE")
    deadline = parse_iso(a["correspondence_deadline"]) if a["correspondence_deadline"] else None
    if deadline is not None and now() > deadline:
        err("ERR_CORRESPONDENCE_EXPIRED", 409, "Correspondence deadline has passed")
    a["status"] = "UNDER_EXAMINATION"
    a["correspondence_open"] = False
    touch(a)
    return success(serialize_app(a), 200)


def mint_registration_number():
    DB.reg_counter += 1
    return "TX%09d" % DB.reg_counter


@app.route("/copyright/applications/<rid>/register", methods=["POST"])
def register_application(rid):
    require_role({"Examiner"})
    a = get_or_404(DB.applications, rid)
    if a["status"] != "UNDER_EXAMINATION":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_EXAMINATION")

    # receipt-completion effective date: max of submitted / deposit-accepted / fee-paid dates
    dates = []
    if a["submitted_at"]:
        dates.append(parse_iso(a["submitted_at"]).date())
    if a["fee_paid_at"]:
        dates.append(parse_iso(a["fee_paid_at"]).date())
    accepted_dep = None
    for d in DB.deposits.values():
        if d["application_id"] == a["id"] and d["status"] == "ACCEPTED":
            accepted_dep = d
            break
    if accepted_dep and accepted_dep.get("accepted_at"):
        dates.append(parse_iso(accepted_dep["accepted_at"]).date())
    eff_date = max(dates) if dates else now().date()
    eff_dt = datetime(eff_date.year, eff_date.month, eff_date.day, tzinfo=timezone.utc)

    decision_dt = now()
    a["registered_at"] = fmt_ms(decision_dt)
    a["status"] = "REGISTERED"
    touch(a)

    cert = new_common()
    renewal_deadline = add_years(eff_dt, RENEWAL_TERM_YEARS)
    renewal_window_start = add_years(eff_dt, RENEWAL_TERM_YEARS - RENEWAL_WINDOW_SPAN_YEARS)
    cert.update({
        "application_id": a["id"],
        "registration_number": mint_registration_number(),
        "effective_date": fmt_day(eff_dt),
        "decision_date": fmt_day(decision_dt),
        "status": "ISSUED",
        "renewal_window_start": fmt_day(renewal_window_start),
        "renewal_deadline": fmt_day(renewal_deadline),
        "renewed_at": None,
    })
    DB.certificates[cert["id"]] = cert

    work = DB.works.get(a["work_id"])
    work["registration_status"] = "REGISTERED"
    touch(work)
    return success(serialize_app(a), 200)


def refund_and_unregister(a):
    a["fee_refunded_cents"] += a["fee_paid_cents"]
    a["net_fee_cents"] = a["fee_paid_cents"] - a["fee_refunded_cents"]


@app.route("/copyright/applications/<rid>/refuse", methods=["POST"])
def refuse_application(rid):
    require_role({"Examiner"})
    a = get_or_404(DB.applications, rid)
    if a["status"] != "UNDER_EXAMINATION":
        err("ERR_INVALID_STATE", 409, "Application is not UNDER_EXAMINATION")
    refund_and_unregister(a)
    a["status"] = "REFUSED"
    touch(a)
    work = DB.works.get(a["work_id"])
    work["registration_status"] = "UNREGISTERED"
    touch(work)
    return success(serialize_app(a), 200)


@app.route("/copyright/applications/<rid>/withdraw", methods=["POST"])
def withdraw_application(rid):
    require_role({"RightsHolder"})
    a = get_or_404(DB.applications, rid)
    owner_check(a)
    if a["status"] not in ("DRAFT", "SUBMITTED"):
        err("ERR_INVALID_STATE", 409, "Application cannot be withdrawn from its current state")
    refund_and_unregister(a)
    a["status"] = "WITHDRAWN"
    touch(a)
    work = DB.works.get(a["work_id"])
    work["registration_status"] = "UNREGISTERED"
    touch(work)
    return success(serialize_app(a), 200)


# ---------------------------------------------------------------------------
# Deposit
# ---------------------------------------------------------------------------
@app.route("/copyright/deposits", methods=["POST"])
def create_deposit():
    require_role({"RightsHolder"})
    body = get_body()
    application_id = require_str(body, "application_id")
    deposit_type = require_enum(body, "deposit_type", DEPOSIT_TYPES)
    copy_count = require_nonneg_int(body, "copy_count")
    get_or_404(DB.applications, application_id)
    d = new_common()
    d.update({
        "application_id": application_id,
        "deposit_type": deposit_type,
        "copy_count": copy_count,
        "status": "SUBMITTED",
        "accepted_at": None,
    })
    DB.deposits[d["id"]] = d
    return success(clean(d), 201)


@app.route("/copyright/deposits/<rid>", methods=["GET"])
def get_deposit(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.deposits, rid)), 200)


@app.route("/copyright/deposits", methods=["GET"])
def list_deposits():
    require_role(set(ALL_ROLES))
    application_id = request.args.get("application_id")
    status = request.args.get("status")
    items = list(DB.deposits.values())
    if application_id is not None:
        items = [d for d in items if d["application_id"] == application_id]
    if status is not None:
        items = [d for d in items if d["status"] == status]
    page, pag = paginate(items)
    return success([clean(d) for d in page], 200, is_list=True, pagination=pag)


@app.route("/copyright/deposits/<rid>/accept", methods=["POST"])
def accept_deposit(rid):
    require_role({"Examiner"})
    d = get_or_404(DB.deposits, rid)
    if d["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Deposit is not SUBMITTED")
    minimum = (DEPOSIT_MIN_COPIES_ELECTRONIC if d["deposit_type"] == "ELECTRONIC"
               else DEPOSIT_MIN_COPIES_PHYSICAL)
    if d["copy_count"] < minimum:
        err("ERR_DEPOSIT_INSUFFICIENT_COPIES", 409, "Not enough deposit copies")
    d["status"] = "ACCEPTED"
    d["accepted_at"] = fmt_ms(now())
    touch(d)
    return success(clean(d), 200)


@app.route("/copyright/deposits/<rid>/reject", methods=["POST"])
def reject_deposit(rid):
    require_role({"Examiner"})
    d = get_or_404(DB.deposits, rid)
    if d["status"] != "SUBMITTED":
        err("ERR_INVALID_STATE", 409, "Deposit is not SUBMITTED")
    d["status"] = "DEFICIENT"
    touch(d)
    return success(clean(d), 200)


# ---------------------------------------------------------------------------
# Certificate
# ---------------------------------------------------------------------------
@app.route("/copyright/certificates/<rid>", methods=["GET"])
def get_certificate(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.certificates, rid)), 200)


@app.route("/copyright/certificates", methods=["GET"])
def list_certificates():
    require_role(set(ALL_ROLES))
    application_id = request.args.get("application_id")
    items = list(DB.certificates.values())
    if application_id is not None:
        items = [c for c in items if c["application_id"] == application_id]
    page, pag = paginate(items)
    return success([clean(c) for c in page], 200, is_list=True, pagination=pag)


@app.route("/copyright/certificates/<rid>/renew", methods=["POST"])
def renew_certificate(rid):
    require_role({"RightsHolder"})
    c = get_or_404(DB.certificates, rid)
    if c["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "Certificate is not ISSUED")
    start = parse_iso(c["renewal_window_start"]).date()
    deadline = parse_iso(c["renewal_deadline"]).date()
    today = now().date()
    if today < start or today > deadline:
        err("ERR_RENEWAL_WINDOW", 409, "Outside the renewal window")
    c["status"] = "RENEWED"
    c["renewed_at"] = fmt_ms(now())
    touch(c)
    return success(clean(c), 200)


# ---------------------------------------------------------------------------
# Recordation
# ---------------------------------------------------------------------------
@app.route("/copyright/recordations", methods=["POST"])
def create_recordation():
    require_role({"Examiner"})
    body = get_body()
    work_id = require_str(body, "work_id")
    transferor_name = require_str(body, "transferor_name")
    transferee_name = require_str(body, "transferee_name")
    execution_date = require_datetime(body, "execution_date")
    expected_version = require_nonneg_int(body, "expected_work_version")

    work = get_or_404(DB.works, work_id)
    # OCC
    if expected_version != work["version"]:
        err("ERR_STALE_VERSION", 412, "expected_work_version does not match Work.version")

    r = new_common()
    r.update({
        "work_id": work_id,
        "transferor_name": transferor_name,
        "transferee_name": transferee_name,
        "execution_date": execution_date,
        "status": "RECORDED",
        "recorded_at": fmt_ms(now()),
    })
    DB.recordations[r["id"]] = r

    # Link A: supersede prior RECORDED recordations; update owner; bump work
    for other in DB.recordations.values():
        if other["id"] != r["id"] and other["work_id"] == work_id and other["status"] == "RECORDED":
            other["status"] = "SUPERSEDED"
            touch(other)
    work["current_owner_name"] = transferee_name
    touch(work)

    # Link B: ACTIVE licenses on the work -> UNDER_REVIEW
    for lic in DB.licenses.values():
        if lic["work_id"] == work_id and lic["status"] == "ACTIVE":
            lic["status"] = "UNDER_REVIEW"
            touch(lic)
            # Link C: DRAFT royalty statements under this license -> VOIDED
            for rs in DB.royalty_statements.values():
                if rs["license_id"] == lic["id"] and rs["status"] == "DRAFT":
                    rs["status"] = "VOIDED"
                    touch(rs)

    return success(clean(r), 201)


@app.route("/copyright/recordations/<rid>", methods=["GET"])
def get_recordation(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.recordations, rid)), 200)


@app.route("/copyright/recordations", methods=["GET"])
def list_recordations():
    require_role(set(ALL_ROLES))
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    items = list(DB.recordations.values())
    if work_id is not None:
        items = [r for r in items if r["work_id"] == work_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pag = paginate(items)
    return success([clean(r) for r in page], 200, is_list=True, pagination=pag)


# ---------------------------------------------------------------------------
# License
# ---------------------------------------------------------------------------
def intervals_overlap_half_open(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


@app.route("/copyright/licenses", methods=["POST"])
def create_license():
    require_role({"RightsHolder"})
    body = get_body()
    work_id = require_str(body, "work_id")
    licensee_name = require_str(body, "licensee_name")
    license_type = require_enum(body, "license_type", LICENSE_TYPES)
    right_type = require_enum(body, "right_type", RIGHT_TYPES)
    territory = require_enum(body, "territory", TERRITORIES)
    start_date = require_datetime(body, "start_date")
    end_date = require_datetime(body, "end_date")
    grant_date = require_datetime(body, "grant_date")
    royalty_rate_bps = require_nonneg_int(body, "royalty_rate_bps")
    royalty_basis = require_enum(body, "royalty_basis", ROYALTY_BASES)

    work = get_or_404(DB.works, work_id)
    # referential: work must be REGISTERED
    if work["registration_status"] != "REGISTERED":
        err("ERR_WORK_NOT_REGISTERED", 409, "Work is not REGISTERED")
    # temporal: start < end
    s = parse_iso(start_date)
    e = parse_iso(end_date)
    if s >= e:
        err("ERR_INVALID_DATE_RANGE", 422, "start_date must be before end_date")
    # exclusive conflict
    if license_type == "EXCLUSIVE":
        for lic in DB.licenses.values():
            if (lic["work_id"] == work_id and lic["license_type"] == "EXCLUSIVE"
                    and lic["right_type"] == right_type and lic["territory"] == territory
                    and lic["status"] in ("ACTIVE", "UNDER_REVIEW")):
                es = parse_iso(lic["start_date"])
                ee = parse_iso(lic["end_date"])
                if intervals_overlap_half_open(s, e, es, ee):
                    err("ERR_EXCLUSIVE_CONFLICT", 409, "Overlapping exclusive license exists")

    lic = new_common()
    lic.update({
        "work_id": work_id,
        "licensor_user_id": g.user_id,
        "licensee_name": licensee_name,
        "license_type": license_type,
        "right_type": right_type,
        "territory": territory,
        "start_date": start_date,
        "end_date": end_date,
        "grant_date": grant_date,
        "royalty_rate_bps": royalty_rate_bps,
        "royalty_basis": royalty_basis,
        "status": "ACTIVE",
        "escrow_balance_cents": 0,
    })
    DB.licenses[lic["id"]] = lic
    return success(clean(lic), 201)


@app.route("/copyright/licenses/<rid>", methods=["GET"])
def get_license(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.licenses, rid)), 200)


@app.route("/copyright/licenses", methods=["GET"])
def list_licenses():
    require_role(set(ALL_ROLES))
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    items = list(DB.licenses.values())
    if work_id is not None:
        items = [l for l in items if l["work_id"] == work_id]
    if status is not None:
        items = [l for l in items if l["status"] == status]
    page, pag = paginate(items)
    return success([clean(l) for l in page], 200, is_list=True, pagination=pag)


# ---------------------------------------------------------------------------
# RoyaltyStatement
# ---------------------------------------------------------------------------
def intervals_overlap_closed(s1, e1, s2, e2):
    return s1 <= e2 and s2 <= e1


@app.route("/copyright/royalty-statements", methods=["POST"])
def create_royalty_statement():
    require_role({"RightsHolder"})
    body = get_body()
    license_id = require_str(body, "license_id")
    period_start = require_datetime(body, "period_start")
    period_end = require_datetime(body, "period_end")
    gross_revenue = require_nonneg_int(body, "gross_revenue_cents")
    deduction = opt_nonneg_int(body, "deduction_cents", 0)

    get_or_404(DB.licenses, license_id)
    ps = parse_iso(period_start)
    pe = parse_iso(period_end)
    if ps >= pe:
        err("ERR_INVALID_DATE_RANGE", 422, "period_start must be before period_end")
    # period overlap with non-reversed/non-voided statements of same license
    for rs in DB.royalty_statements.values():
        if rs["license_id"] == license_id and rs["status"] not in ("REVERSED", "VOIDED"):
            es = parse_iso(rs["period_start"])
            ee = parse_iso(rs["period_end"])
            if intervals_overlap_closed(ps, pe, es, ee):
                err("ERR_PERIOD_OVERLAP", 409, "Overlapping royalty period exists")

    rs = new_common()
    rs.update({
        "license_id": license_id,
        "period_start": period_start,
        "period_end": period_end,
        "gross_revenue_cents": gross_revenue,
        "deduction_cents": deduction,
        "accrued_cents": 0,
        "distributed_cents": 0,
        "distribution": [],
        "status": "DRAFT",
    })
    DB.royalty_statements[rs["id"]] = rs
    return success(clean(rs), 201)


@app.route("/copyright/royalty-statements/<rid>", methods=["GET"])
def get_royalty_statement(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.royalty_statements, rid)), 200)


@app.route("/copyright/royalty-statements", methods=["GET"])
def list_royalty_statements():
    require_role(set(ALL_ROLES))
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    items = list(DB.royalty_statements.values())
    if license_id is not None:
        items = [r for r in items if r["license_id"] == license_id]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    page, pag = paginate(items)
    return success([clean(r) for r in page], 200, is_list=True, pagination=pag)


@app.route("/copyright/royalty-statements/<rid>/post", methods=["POST"])
def post_royalty_statement(rid):
    require_role({"RightsHolder"})
    rs = get_or_404(DB.royalty_statements, rid)
    if rs["status"] != "DRAFT":
        err("ERR_INVALID_STATE", 409, "Statement is not DRAFT")
    lic = DB.licenses.get(rs["license_id"])
    if lic is None or lic["status"] != "ACTIVE":
        err("ERR_LICENSE_NOT_ACTIVE", 409, "Parent license is not ACTIVE")
    if lic["royalty_basis"] == "GROSS":
        basis_amount = rs["gross_revenue_cents"]
    else:
        basis_amount = rs["gross_revenue_cents"] - rs["deduction_cents"]
    accrued = round_half_up(basis_amount * lic["royalty_rate_bps"])
    rs["accrued_cents"] = accrued
    rs["status"] = "POSTED"
    touch(rs)
    lic["escrow_balance_cents"] += accrued
    touch(lic)
    return success(clean(rs), 200)


@app.route("/copyright/royalty-statements/<rid>/distribute", methods=["POST"])
def distribute_royalty_statement(rid):
    require_role({"RightsHolder"})
    rs = get_or_404(DB.royalty_statements, rid)
    if rs["status"] != "POSTED":
        err("ERR_INVALID_STATE", 409, "Statement is not POSTED")
    lic = DB.licenses.get(rs["license_id"])
    work = DB.works.get(lic["work_id"]) if lic else None
    owner_shares = work["owner_shares"] if work else []
    distribution, distributed = compute_distribution(rs["accrued_cents"], owner_shares)
    rs["distribution"] = distribution
    rs["distributed_cents"] = distributed
    rs["status"] = "DISTRIBUTED"
    touch(rs)
    lic["escrow_balance_cents"] -= rs["accrued_cents"]
    touch(lic)
    return success(clean(rs), 200)


@app.route("/copyright/royalty-statements/<rid>/reverse", methods=["POST"])
def reverse_royalty_statement(rid):
    require_role({"RightsHolder"})
    rs = get_or_404(DB.royalty_statements, rid)
    if rs["status"] != "POSTED":
        err("ERR_INVALID_STATE", 409, "Statement is not POSTED")
    lic = DB.licenses.get(rs["license_id"])
    rs["status"] = "REVERSED"
    touch(rs)
    if lic is not None:
        lic["escrow_balance_cents"] -= rs["accrued_cents"]
        touch(lic)
    return success(clean(rs), 200)


# ---------------------------------------------------------------------------
# DmcaTakedown
# ---------------------------------------------------------------------------
@app.route("/copyright/dmca-takedowns", methods=["POST"])
def create_takedown():
    require_role({"Complainant"})
    body = get_body()
    work_id = require_str(body, "work_id")
    complainant_name = require_str(body, "complainant_name")
    infringing_url = require_str(body, "infringing_url")
    get_or_404(DB.works, work_id)
    t = new_common()
    t.update({
        "work_id": work_id,
        "complainant_user_id": g.user_id,
        "complainant_name": complainant_name,
        "infringing_url": infringing_url,
        "status": "FILED",
        "effective_at": None,
        "countered_at": None,
        "restoration_earliest_date": None,
        "restoration_latest_date": None,
    })
    DB.dmca_takedowns[t["id"]] = t
    return success(clean(t), 201)


@app.route("/copyright/dmca-takedowns/<rid>", methods=["GET"])
def get_takedown(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.dmca_takedowns, rid)), 200)


@app.route("/copyright/dmca-takedowns", methods=["GET"])
def list_takedowns():
    require_role(set(ALL_ROLES))
    work_id = request.args.get("work_id")
    status = request.args.get("status")
    items = list(DB.dmca_takedowns.values())
    if work_id is not None:
        items = [t for t in items if t["work_id"] == work_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pag = paginate(items)
    return success([clean(t) for t in page], 200, is_list=True, pagination=pag)


@app.route("/copyright/dmca-takedowns/<rid>/process", methods=["POST"])
def process_takedown(rid):
    require_role({"Examiner"})
    t = get_or_404(DB.dmca_takedowns, rid)
    if t["status"] != "FILED":
        err("ERR_INVALID_STATE", 409, "Takedown is not FILED")
    t["status"] = "EFFECTIVE"
    t["effective_at"] = fmt_ms(now())
    touch(t)
    return success(clean(t), 200)


@app.route("/copyright/dmca-takedowns/<rid>/restore", methods=["POST"])
def restore_takedown(rid):
    require_role({"Examiner"})
    t = get_or_404(DB.dmca_takedowns, rid)
    if t["status"] != "COUNTERED":
        err("ERR_INVALID_STATE", 409, "Takedown is not COUNTERED")
    earliest = parse_iso(t["restoration_earliest_date"]).date()
    latest = parse_iso(t["restoration_latest_date"]).date()
    today = now().date()
    if today < earliest:
        err("ERR_RESTORE_TOO_EARLY", 409, "Restore before restoration_earliest_date")
    if today > latest:
        err("ERR_RESTORE_WINDOW_EXPIRED", 409, "Restore after restoration_latest_date")
    t["status"] = "RESTORED"
    touch(t)
    for cn in DB.counter_notices.values():
        if cn["takedown_id"] == t["id"] and cn["status"] == "FORWARDED":
            cn["status"] = "COMPLETE"
            touch(cn)
    return success(clean(t), 200)


@app.route("/copyright/dmca-takedowns/<rid>/withdraw", methods=["POST"])
def withdraw_takedown(rid):
    require_role({"Complainant"})
    t = get_or_404(DB.dmca_takedowns, rid)
    if t["status"] not in ("FILED", "EFFECTIVE"):
        err("ERR_INVALID_STATE", 409, "Takedown cannot be withdrawn from its current state")
    t["status"] = "WITHDRAWN"
    touch(t)
    return success(clean(t), 200)


# ---------------------------------------------------------------------------
# CounterNotice
# ---------------------------------------------------------------------------
@app.route("/copyright/counter-notices", methods=["POST"])
def create_counter_notice():
    require_role({"RightsHolder"})
    body = get_body()
    takedown_id = require_str(body, "takedown_id")
    subscriber_name = require_str(body, "subscriber_name")
    statement = require_str(body, "statement")
    t = get_or_404(DB.dmca_takedowns, takedown_id)
    if t["status"] != "EFFECTIVE":
        err("ERR_TAKEDOWN_NOT_EFFECTIVE", 409, "Takedown is not EFFECTIVE")
    for cn in DB.counter_notices.values():
        if cn["takedown_id"] == takedown_id:
            err("ERR_COUNTER_NOTICE_EXISTS", 409, "A counter-notice already exists")

    clock = now()
    cn = new_common()
    cn.update({
        "takedown_id": takedown_id,
        "subscriber_user_id": g.user_id,
        "subscriber_name": subscriber_name,
        "statement": statement,
        "status": "FORWARDED",
        "forwarded_at": fmt_ms(clock),
    })
    DB.counter_notices[cn["id"]] = cn

    # side effect: takedown EFFECTIVE -> COUNTERED
    t["status"] = "COUNTERED"
    t["countered_at"] = fmt_ms(clock)
    t["restoration_earliest_date"] = fmt_day(clock + timedelta(days=RESTORE_MIN_DAYS))
    t["restoration_latest_date"] = fmt_day(clock + timedelta(days=RESTORE_MAX_DAYS))
    touch(t)
    return success(clean(cn), 201)


@app.route("/copyright/counter-notices/<rid>", methods=["GET"])
def get_counter_notice(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.counter_notices, rid)), 200)


@app.route("/copyright/counter-notices", methods=["GET"])
def list_counter_notices():
    require_role(set(ALL_ROLES))
    takedown_id = request.args.get("takedown_id")
    status = request.args.get("status")
    items = list(DB.counter_notices.values())
    if takedown_id is not None:
        items = [c for c in items if c["takedown_id"] == takedown_id]
    if status is not None:
        items = [c for c in items if c["status"] == status]
    page, pag = paginate(items)
    return success([clean(c) for c in page], 200, is_list=True, pagination=pag)


# ---------------------------------------------------------------------------
# Termination
# ---------------------------------------------------------------------------
@app.route("/copyright/terminations", methods=["POST"])
def create_termination():
    require_role({"RightsHolder"})
    body = get_body()
    license_id = require_str(body, "license_id")
    terminating_party_name = require_str(body, "terminating_party_name")
    notice_served_date = require_datetime(body, "notice_served_date")
    effective_date = require_datetime(body, "effective_date")

    lic = get_or_404(DB.licenses, license_id)
    grant = parse_iso(lic["grant_date"])
    earliest = add_years(grant, TERMINATION_WINDOW_START_YEARS)
    latest = add_years(earliest, TERMINATION_WINDOW_SPAN_YEARS)

    term = new_common()
    term.update({
        "license_id": license_id,
        "terminating_party_name": terminating_party_name,
        "notice_served_date": notice_served_date,
        "effective_date": effective_date,
        "window_earliest_date": fmt_day(earliest),
        "window_latest_date": fmt_day(latest),
        "status": "NOTICE_SERVED",
    })
    DB.terminations[term["id"]] = term
    return success(clean(term), 201)


@app.route("/copyright/terminations/<rid>", methods=["GET"])
def get_termination(rid):
    require_role(set(ALL_ROLES))
    return success(clean(get_or_404(DB.terminations, rid)), 200)


@app.route("/copyright/terminations", methods=["GET"])
def list_terminations():
    require_role(set(ALL_ROLES))
    license_id = request.args.get("license_id")
    status = request.args.get("status")
    items = list(DB.terminations.values())
    if license_id is not None:
        items = [t for t in items if t["license_id"] == license_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    page, pag = paginate(items)
    return success([clean(t) for t in page], 200, is_list=True, pagination=pag)


@app.route("/copyright/terminations/<rid>/effectuate", methods=["POST"])
def effectuate_termination(rid):
    require_role({"Examiner"})
    term = get_or_404(DB.terminations, rid)
    if term["status"] != "NOTICE_SERVED":
        err("ERR_INVALID_STATE", 409, "Termination is not NOTICE_SERVED")
    eff = parse_iso(term["effective_date"]).date()
    earliest = parse_iso(term["window_earliest_date"]).date()
    latest = parse_iso(term["window_latest_date"]).date()
    if eff < earliest or eff > latest:
        err("ERR_TERMINATION_WINDOW", 409, "effective_date outside statutory window")
    term["status"] = "EFFECTIVE"
    touch(term)

    lic = DB.licenses.get(term["license_id"])
    if lic is not None:
        # link A: license -> TERMINATED
        lic["status"] = "TERMINATED"
        touch(lic)
        # link B: POSTED statements -> REVERSED
        for rs in DB.royalty_statements.values():
            if rs["license_id"] == lic["id"] and rs["status"] == "POSTED":
                rs["status"] = "REVERSED"
                touch(rs)
        # link C: escrow -> 0
        lic["escrow_balance_cents"] = 0
        touch(lic)
    return success(clean(term), 200)


# ---------------------------------------------------------------------------
# Health / entrypoint
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def health():
    return success({"status": "ok"}, 200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
