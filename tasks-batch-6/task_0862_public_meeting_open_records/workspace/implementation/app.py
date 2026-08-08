import os
import math
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

# =============================================================================
# Constants
# =============================================================================
ROLES = {"Clerk", "BodyMember", "RecordsOfficer", "AppealsOfficer", "Requester"}

NOTICE_LEAD_HOURS = {"REGULAR": 72, "SPECIAL": 24, "EMERGENCY": 1}
FREE_PAGE_ALLOWANCE = 50
COPY_TIER1_LIMIT = 500
COPY_TIER1_RATE_CENTS = 15
COPY_TIER2_RATE_CENTS = 10
LABOR_INCREMENT_MINUTES = 15
LABOR_FREE_MINUTES = 30
LABOR_RATE_CENTS_PER_HOUR = 2500
RESPONSE_DEADLINE_BUSINESS_DAYS = 10
ITEM_COMMENT_CAP_SECONDS = 1800
SETUP_BUFFER_MINUTES = 30
APPEAL_WINDOW_DAYS = 30
DAYS_PER_YEAR = 365
RETENTION_YEARS = {"PERMANENT": 9999, "FISCAL": 7, "ADMIN": 3, "TRANSITORY": 1}

MEETING_TYPES = {"REGULAR", "SPECIAL", "EMERGENCY"}
NOTICE_CHANNELS = {"WEBSITE", "BULLETIN", "NEWSPAPER"}
ITEM_TYPES = {"ACTION", "DISCUSSION", "CONSENT"}
EXEMPTION_CODES = {"NONE", "PRIVACY", "DELIBERATIVE", "SECURITY", "MEDICAL"}
RETENTION_SERIES = {"PERMANENT", "FISCAL", "ADMIN", "TRANSITORY"}
VOTE_THRESHOLDS = {"SIMPLE", "ABSOLUTE"}
BALLOT_VALUES = {"YEA", "NAY", "ABSTAIN", "RECUSED"}
DECISIONS = {"GRANTED", "PARTIALLY_GRANTED", "DENIED"}

DEFAULT_CLOCK = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)

# =============================================================================
# In-memory store (wiped on every process boot)
# =============================================================================
DB = {
    "public_bodies": {},
    "requesters": {},
    "body_members": {},
    "venues": {},
    "meetings": {},
    "agenda_items": {},
    "speaker_slips": {},
    "motions": {},
    "records_requests": {},
    "documents": {},
    "appeals": {},
}
CLOCK = {"now": DEFAULT_CLOCK}
_SEQ = {"n": 0}


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


# =============================================================================
# Errors
# =============================================================================
class APIError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise APIError(error_id, http_status, message)


# =============================================================================
# Time helpers
# =============================================================================
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def render_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_dt():
    return CLOCK["now"]


def now_str():
    return render_ts(CLOCK["now"])


# =============================================================================
# Response envelope
# =============================================================================
def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def make_meta(pagination=None):
    meta = {"api_request_id": gen_request_id(), "api_request_timestamp": now_str()}
    if pagination:
        meta.update(pagination)
    return meta


def success(data, response_type="object", code=200, pagination=None):
    body = {
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), code


@app.after_request
def add_conn_close(resp):
    resp.headers["Connection"] = "close"
    return resp


@app.errorhandler(APIError)
def handle_api_error(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": e.error_id, "message": e.message},
    }
    return jsonify(body), e.http_status


@app.errorhandler(404)
def handle_404(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found."},
    }
    return jsonify(body), 404


@app.errorhandler(405)
def handle_405(e):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": "ERR_NOT_FOUND", "message": "Method not allowed."},
    }
    return jsonify(body), 405


# =============================================================================
# Auth
# =============================================================================
def authenticate(allowed_roles):
    """Return (effective_role, uid). Enforces authn (401) and coarse authz (403)."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    anon_ok = "Anonymous" in allowed_roles

    if role in ROLES and uid:
        # authenticated principal
        if role in allowed_roles:
            return role, uid
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this operation.")
    # unauthenticated / anonymous / invalid header pair
    if anon_ok:
        return "Anonymous", uid
    err("ERR_UNAUTHENTICATED", 401, "Missing or invalid authentication headers.")


def fine_authz(role, to_status, role_map):
    """Enforce role-per-target-status (priority 2). Only when to_status is known."""
    if to_status in role_map and role not in role_map[to_status]:
        err("ERR_UNAUTHORIZED", 403, "Role not permitted for this transition.")


# =============================================================================
# Body / field helpers
# =============================================================================
def get_body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        err("ERR_VALIDATION", 422, "Request body must be a JSON object.")
    return data


def req_str(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 422, f"Field '{name}' is required and must be a non-empty string.")
    return v


def opt_str(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, str):
        err("ERR_VALIDATION", 422, f"Field '{name}' must be a string.")
    return v


def req_int(body, name, minimum=None, maximum=None):
    v = body.get(name)
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 422, f"Field '{name}' is required and must be an integer.")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be <= {maximum}.")
    return v


def opt_int(body, name, default, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        err("ERR_VALIDATION", 422, f"Field '{name}' must be an integer.")
    if minimum is not None and v < minimum:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be >= {minimum}.")
    if maximum is not None and v > maximum:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be <= {maximum}.")
    return v


def req_enum(body, name, choices):
    v = body.get(name)
    if v not in choices:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be one of {sorted(choices)}.")
    return v


def opt_enum(body, name, choices, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if v not in choices:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be one of {sorted(choices)}.")
    return v


def opt_bool(body, name, default):
    if name not in body or body[name] is None:
        return default
    v = body[name]
    if not isinstance(v, bool):
        err("ERR_VALIDATION", 422, f"Field '{name}' must be a boolean.")
    return v


def req_datetime(body, name):
    v = body.get(name)
    if not isinstance(v, str) or v == "":
        err("ERR_VALIDATION", 422, f"Field '{name}' is required and must be an ISO8601 datetime string.")
    try:
        parse_iso(v)
    except Exception:
        err("ERR_VALIDATION", 422, f"Field '{name}' must be a valid ISO8601 datetime.")
    return v


# =============================================================================
# Record base / mutation helpers
# =============================================================================
def base_record():
    ts = now_str()
    return {
        "id": str(uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(rec):
    rec["version"] += 1
    rec["updated_at"] = now_str()


def get_or_404(collection, rid):
    rec = DB[collection].get(rid)
    if rec is None:
        err("ERR_NOT_FOUND", 404, "Resource not found.")
    return rec


# =============================================================================
# Calculations
# =============================================================================
def copy_fee(pages):
    billable = max(0, pages - FREE_PAGE_ALLOWANCE)
    tier1 = min(billable, COPY_TIER1_LIMIT - FREE_PAGE_ALLOWANCE)  # up to 450
    tier2 = max(0, billable - (COPY_TIER1_LIMIT - FREE_PAGE_ALLOWANCE))
    return tier1 * COPY_TIER1_RATE_CENTS + tier2 * COPY_TIER2_RATE_CENTS


def labor_fee(docs):
    total = 0
    for d in docs:
        rm = d["review_minutes"]
        total += math.ceil(rm / LABOR_INCREMENT_MINUTES) * LABOR_INCREMENT_MINUTES
    chargeable = max(0, total - LABOR_FREE_MINUTES)
    cents = (Decimal(chargeable) / Decimal(60)) * Decimal(LABOR_RATE_CENTS_PER_HOUR)
    return int(cents.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def compute_assessed(request_id):
    docs = [d for d in DB["documents"].values() if d["request_id"] == request_id]
    copy_pages = sum(d["page_count"] for d in docs if d["status"] in ("RELEASED", "REDACTED"))
    labor_docs = [d for d in docs if d["status"] in ("RELEASED", "REDACTED", "EXEMPT")]
    return copy_fee(copy_pages) + labor_fee(labor_docs)


def response_deadline_for(submitted_dt):
    d = submitted_dt.date()
    remaining = RESPONSE_DEADLINE_BUSINESS_DAYS
    while remaining > 0:
        d = d + timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            remaining -= 1
    return f"{d.isoformat()}T23:59:59Z"


# =============================================================================
# Serializers
# =============================================================================
def common_out(rec):
    return {
        "id": rec["id"],
        "created_at": rec["created_at"],
        "updated_at": rec["updated_at"],
        "version": rec["version"],
    }


def ser_body(r):
    o = common_out(r)
    o.update({
        "name": r["name"],
        "jurisdiction_state": r["jurisdiction_state"],
        "seat_count": r["seat_count"],
        "quorum_size": r["quorum_size"],
    })
    return o


def ser_requester(r):
    o = common_out(r)
    o.update({
        "full_name": r["full_name"],
        "email": r["email"],
        "organization": r["organization"],
    })
    return o


def ser_member(r):
    o = common_out(r)
    o.update({
        "body_id": r["body_id"],
        "full_name": r["full_name"],
        "seat_number": r["seat_number"],
        "status": r["status"],
    })
    return o


def ser_venue(r):
    o = common_out(r)
    o.update({
        "body_id": r["body_id"],
        "name": r["name"],
        "capacity": r["capacity"],
    })
    return o


def ser_meeting(r):
    body = DB["public_bodies"].get(r["body_id"])
    quorum_size = body["quorum_size"] if body else 0
    quorum_met = len(r["present_member_ids"]) >= quorum_size and len(r["present_member_ids"]) > 0
    o = common_out(r)
    o.update({
        "body_id": r["body_id"],
        "venue_id": r["venue_id"],
        "presiding_member_id": r["presiding_member_id"],
        "title": r["title"],
        "meeting_type": r["meeting_type"],
        "scheduled_start": r["scheduled_start"],
        "scheduled_end": r["scheduled_end"],
        "status": r["status"],
        "minutes_status": r["minutes_status"],
        "notice_channel": r["notice_channel"],
        "notice_posted_at": r["notice_posted_at"],
        "notice_lead_hours": r["notice_lead_hours"],
        "present_member_ids": list(r["present_member_ids"]),
        "quorum_met": quorum_met,
        "minutes_text": r["minutes_text"],
        "minutes_approved_at": r["minutes_approved_at"],
    })
    return o


def ser_item(r):
    o = common_out(r)
    o.update({
        "meeting_id": r["meeting_id"],
        "title": r["title"],
        "sequence": r["sequence"],
        "item_type": r["item_type"],
        "public_comment_enabled": r["public_comment_enabled"],
        "status": r["status"],
    })
    return o


def ser_slip(r):
    item_id = r["agenda_item_id"]
    siblings = [s for s in DB["speaker_slips"].values()
                if s["agenda_item_id"] == item_id and s["status"] != "WITHDRAWN"]
    siblings.sort(key=lambda s: (s["created_at"], s["_seq"]))
    position = None
    for i, s in enumerate(siblings):
        if s["id"] == r["id"]:
            position = i + 1
            break
    o = common_out(r)
    o.update({
        "agenda_item_id": r["agenda_item_id"],
        "requester_id": r["requester_id"],
        "speaker_name": r["speaker_name"],
        "allotted_seconds": r["allotted_seconds"],
        "position": position,
        "called_at": r["called_at"],
        "status": r["status"],
    })
    return o


def ser_motion(r):
    ballots = r["ballots"]
    yea = sum(1 for b in ballots if b["value"] == "YEA")
    nay = sum(1 for b in ballots if b["value"] == "NAY")
    abstain = sum(1 for b in ballots if b["value"] == "ABSTAIN")
    recused = sum(1 for b in ballots if b["value"] == "RECUSED")
    ballot_count = yea + nay + abstain + recused
    outcome = r["status"] if r["status"] in ("CARRIED", "FAILED") else "PENDING"
    o = common_out(r)
    o.update({
        "agenda_item_id": r["agenda_item_id"],
        "text": r["text"],
        "moved_by_member_id": r["moved_by_member_id"],
        "seconded_by_member_id": r["seconded_by_member_id"],
        "vote_threshold": r["vote_threshold"],
        "ballots": [dict(b) for b in ballots],
        "yea_count": yea,
        "nay_count": nay,
        "abstain_count": abstain,
        "recused_count": recused,
        "ballot_count": ballot_count,
        "outcome": outcome,
        "status": r["status"],
    })
    return o


def ser_request(r):
    assessed = r["assessed_fee_cents"]
    balance = assessed - r["amount_waived_cents"] - r["amount_paid_cents"]
    o = common_out(r)
    o.update({
        "requester_id": r["requester_id"],
        "body_id": r["body_id"],
        "subject": r["subject"],
        "description": r["description"],
        "estimated_page_count": r["estimated_page_count"],
        "submitted_at": r["submitted_at"],
        "response_deadline": r["response_deadline"],
        "estimated_fee_cents": r["estimated_fee_cents"],
        "assessed_fee_cents": assessed,
        "amount_waived_cents": r["amount_waived_cents"],
        "amount_paid_cents": r["amount_paid_cents"],
        "fee_balance_cents": balance,
        "decision": r["decision"],
        "determined_by_user_id": r["determined_by_user_id"],
        "determined_at": r["determined_at"],
        "status": r["status"],
    })
    return o


def ser_document(r):
    billable = r["page_count"] if r["status"] in ("RELEASED", "REDACTED") else 0
    o = common_out(r)
    o.update({
        "request_id": r["request_id"],
        "title": r["title"],
        "page_count": r["page_count"],
        "review_minutes": r["review_minutes"],
        "exemption_code": r["exemption_code"],
        "retention_series": r["retention_series"],
        "billable_pages": billable,
        "status": r["status"],
    })
    return o


def ser_appeal(r):
    o = common_out(r)
    o.update({
        "request_id": r["request_id"],
        "grounds": r["grounds"],
        "filed_at": r["filed_at"],
        "decided_by_user_id": r["decided_by_user_id"],
        "decision": r["decision"],
        "status": r["status"],
    })
    return o


# =============================================================================
# Pagination helpers
# =============================================================================
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 422, "limit must be an integer.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 422, "offset must be an integer.")
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    return limit, offset


def paginate_list(items, serializer):
    items = sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
    limit, offset = parse_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return success([serializer(x) for x in page], response_type="array", code=200, pagination=pagination)


# =============================================================================
# Presiding / ownership helpers
# =============================================================================
def meeting_of_item(item):
    return DB["meetings"].get(item["meeting_id"])


def require_presiding(uid, meeting):
    if meeting is None or uid != meeting["presiding_member_id"]:
        err("ERR_NOT_PRESIDING_OFFICER", 403, "Acting member is not the presiding officer.")


# =============================================================================
# Endpoints: logical clock
# =============================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate(["Clerk"])
    body = get_body()
    iso = body.get("to_iso8601")
    if not isinstance(iso, str) or iso == "":
        err("ERR_VALIDATION", 422, "to_iso8601 is required.")
    try:
        CLOCK["now"] = parse_iso(iso)
    except Exception:
        err("ERR_VALIDATION", 422, "to_iso8601 must be a valid ISO8601 instant.")
    return success({}, response_type="object", code=200)


# =============================================================================
# Endpoints: PublicBody
# =============================================================================
@app.route("/public-bodies", methods=["POST"])
def create_body():
    authenticate(["Clerk"])
    body = get_body()
    name = req_str(body, "name")
    jurisdiction = req_str(body, "jurisdiction_state")
    seat_count = req_int(body, "seat_count", minimum=1)
    quorum_size = req_int(body, "quorum_size", minimum=1)
    if quorum_size > seat_count:
        err("ERR_VALIDATION", 422, "quorum_size must not exceed seat_count.")
    rec = base_record()
    rec.update({
        "name": name,
        "jurisdiction_state": jurisdiction,
        "seat_count": seat_count,
        "quorum_size": quorum_size,
    })
    DB["public_bodies"][rec["id"]] = rec
    return success(ser_body(rec), code=201)


@app.route("/public-bodies/<bid>", methods=["GET"])
def get_body_ep(bid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester"])
    rec = get_or_404("public_bodies", bid)
    return success(ser_body(rec))


# =============================================================================
# Endpoints: BodyMember
# =============================================================================
@app.route("/public-bodies/<bid>/members", methods=["POST"])
def create_member(bid):
    authenticate(["Clerk"])
    body_rec = get_or_404("public_bodies", bid)
    body = get_body()
    full_name = req_str(body, "full_name")
    seat_number = req_int(body, "seat_number", minimum=1, maximum=body_rec["seat_count"])
    rec = base_record()
    rec.update({
        "body_id": bid,
        "full_name": full_name,
        "seat_number": seat_number,
        "status": "ACTIVE",
    })
    DB["body_members"][rec["id"]] = rec
    return success(ser_member(rec), code=201)


@app.route("/public-bodies/<bid>/members", methods=["GET"])
def list_members(bid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester"])
    get_or_404("public_bodies", bid)
    status_f = request.args.get("status")
    items = [m for m in DB["body_members"].values() if m["body_id"] == bid]
    if status_f is not None:
        items = [m for m in items if m["status"] == status_f]
    return paginate_list(items, ser_member)


# =============================================================================
# Endpoints: Venue
# =============================================================================
@app.route("/public-bodies/<bid>/venues", methods=["POST"])
def create_venue(bid):
    authenticate(["Clerk"])
    get_or_404("public_bodies", bid)
    body = get_body()
    name = req_str(body, "name")
    capacity = opt_int(body, "capacity", 50)
    rec = base_record()
    rec.update({"body_id": bid, "name": name, "capacity": capacity})
    DB["venues"][rec["id"]] = rec
    return success(ser_venue(rec), code=201)


@app.route("/public-bodies/<bid>/venues", methods=["GET"])
def list_venues(bid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester"])
    get_or_404("public_bodies", bid)
    items = [v for v in DB["venues"].values() if v["body_id"] == bid]
    return paginate_list(items, ser_venue)


# =============================================================================
# Endpoints: Meeting
# =============================================================================
def occ_interval_venue(start, end):
    return (start - timedelta(minutes=SETUP_BUFFER_MINUTES), end)


@app.route("/public-bodies/<bid>/meetings", methods=["POST"])
def create_meeting(bid):
    authenticate(["Clerk"])
    body_rec = get_or_404("public_bodies", bid)
    body = get_body()
    venue_id = req_str(body, "venue_id")
    presiding_member_id = req_str(body, "presiding_member_id")
    title = req_str(body, "title")
    meeting_type = req_enum(body, "meeting_type", MEETING_TYPES)
    scheduled_start = req_datetime(body, "scheduled_start")
    scheduled_end = req_datetime(body, "scheduled_end")

    start_dt = parse_iso(scheduled_start)
    end_dt = parse_iso(scheduled_end)
    if not (end_dt > start_dt):
        err("ERR_VALIDATION", 422, "scheduled_end must be strictly after scheduled_start.")

    venue = DB["venues"].get(venue_id)
    if venue is None or venue["body_id"] != bid:
        err("ERR_VALIDATION", 422, "venue_id must reference a venue of this body.")
    member = DB["body_members"].get(presiding_member_id)
    if member is None or member["body_id"] != bid:
        err("ERR_VALIDATION", 422, "presiding_member_id must reference a member of this body.")

    # Priority 11 conflict checks — venue first (buffered, half-open), then presiding (closed).
    new_v_start, new_v_end = occ_interval_venue(start_dt, end_dt)
    for m in DB["meetings"].values():
        if m["body_id"] != bid or m["status"] == "CANCELLED":
            continue
        if m["venue_id"] != venue_id:
            continue
        o_start, o_end = occ_interval_venue(parse_iso(m["scheduled_start"]), parse_iso(m["scheduled_end"]))
        if new_v_start < o_end and o_start < new_v_end:
            err("ERR_VENUE_CONFLICT", 409, "Meeting conflicts with another meeting in the same venue.")

    for m in DB["meetings"].values():
        if m["body_id"] != bid or m["status"] == "CANCELLED":
            continue
        if m["presiding_member_id"] != presiding_member_id:
            continue
        o_start = parse_iso(m["scheduled_start"])
        o_end = parse_iso(m["scheduled_end"])
        if start_dt <= o_end and o_start <= end_dt:
            err("ERR_PRESIDING_CONFLICT", 409, "Presiding member already presides an overlapping meeting.")

    rec = base_record()
    rec.update({
        "body_id": bid,
        "venue_id": venue_id,
        "presiding_member_id": presiding_member_id,
        "title": title,
        "meeting_type": meeting_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "status": "SCHEDULED",
        "minutes_status": "NONE",
        "notice_channel": None,
        "notice_posted_at": None,
        "notice_lead_hours": None,
        "present_member_ids": [],
        "minutes_text": None,
        "minutes_approved_at": None,
    })
    DB["meetings"][rec["id"]] = rec
    return success(ser_meeting(rec), code=201)


@app.route("/meetings/<mid>", methods=["GET"])
def get_meeting(mid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester", "Anonymous"])
    rec = get_or_404("meetings", mid)
    return success(ser_meeting(rec))


@app.route("/public-bodies/<bid>/meetings", methods=["GET"])
def list_meetings(bid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester", "Anonymous"])
    get_or_404("public_bodies", bid)
    status_f = request.args.get("status")
    items = [m for m in DB["meetings"].values() if m["body_id"] == bid]
    if status_f is not None:
        items = [m for m in items if m["status"] == status_f]
    return paginate_list(items, ser_meeting)


MEETING_TRANSITION_ROLE = {
    "NOTICED": ["Clerk"],
    "CANCELLED": ["Clerk"],
    "IN_SESSION": ["BodyMember"],
    "ADJOURNED": ["BodyMember"],
}


def cancel_item_cascade(item):
    """AgendaItem -> CANCELLED with motion void + slip withdraw cascade."""
    item["status"] = "CANCELLED"
    touch(item)
    for mo in DB["motions"].values():
        if mo["agenda_item_id"] == item["id"] and mo["status"] in ("DRAFT", "OPEN", "TABLED"):
            mo["status"] = "VOIDED"
            mo["ballots"] = []
            touch(mo)
    for sl in DB["speaker_slips"].values():
        if sl["agenda_item_id"] == item["id"] and sl["status"] in ("QUEUED", "CALLED"):
            sl["status"] = "WITHDRAWN"
            touch(sl)


@app.route("/meetings/<mid>/transition", methods=["POST"])
def meeting_transition(mid):
    role, uid = authenticate(["Clerk", "BodyMember"])
    body = get_body()
    to_status = body.get("to_status")
    fine_authz(role, to_status, MEETING_TRANSITION_ROLE)

    m = get_or_404("meetings", mid)

    if to_status == "NOTICED":
        # Clerk; notice_channel required; from SCHEDULED or NOTICED
        notice_channel = body.get("notice_channel")
        if notice_channel not in NOTICE_CHANNELS:
            err("ERR_VALIDATION", 422, "notice_channel is required and must be a valid channel.")
        if m["status"] not in ("SCHEDULED", "NOTICED"):
            err("ERR_INVALID_STATE", 409, "Meeting cannot be noticed from its current state.")
        lead = (parse_iso(m["scheduled_start"]) - now_dt()).total_seconds() / 3600.0
        m["notice_channel"] = notice_channel
        m["notice_posted_at"] = now_str()
        m["notice_lead_hours"] = lead
        m["status"] = "NOTICED"
        touch(m)
        return success(ser_meeting(m))

    if to_status == "IN_SESSION":
        require_presiding(uid, m)
        present = body.get("present_member_ids")
        if not isinstance(present, list) or any(not isinstance(x, str) for x in present):
            err("ERR_VALIDATION", 422, "present_member_ids is required and must be a list of ids.")
        if m["status"] != "NOTICED":
            err("ERR_INVALID_STATE", 409, "Meeting must be NOTICED to convene.")
        minimum = NOTICE_LEAD_HOURS[m["meeting_type"]]
        if m["notice_lead_hours"] is None or m["notice_lead_hours"] < minimum:
            err("ERR_NOTICE_NONCOMPLIANT", 409, "Notice lead time is below the statutory minimum.")
        body_rec = DB["public_bodies"].get(m["body_id"])
        if len(present) < body_rec["quorum_size"]:
            err("ERR_QUORUM_NOT_MET", 409, "Quorum not met.")
        m["present_member_ids"] = list(present)
        m["status"] = "IN_SESSION"
        touch(m)
        return success(ser_meeting(m))

    if to_status == "ADJOURNED":
        require_presiding(uid, m)
        if m["status"] != "IN_SESSION":
            err("ERR_INVALID_STATE", 409, "Meeting must be IN_SESSION to adjourn.")
        item_ids = {it["id"] for it in DB["agenda_items"].values() if it["meeting_id"] == mid}
        for mo in DB["motions"].values():
            if mo["agenda_item_id"] in item_ids and mo["status"] == "OPEN":
                err("ERR_OPEN_MOTIONS_EXIST", 409, "Cannot adjourn while a motion is OPEN.")
        # cascade
        for it in DB["agenda_items"].values():
            if it["meeting_id"] == mid and it["status"] == "OPEN":
                it["status"] = "CLOSED"
                touch(it)
        for sl in DB["speaker_slips"].values():
            if sl["agenda_item_id"] in item_ids and sl["status"] in ("QUEUED", "CALLED"):
                sl["status"] = "EXPIRED"
                touch(sl)
        m["status"] = "ADJOURNED"
        touch(m)
        return success(ser_meeting(m))

    if to_status == "CANCELLED":
        if m["status"] not in ("SCHEDULED", "NOTICED", "IN_SESSION"):
            err("ERR_INVALID_STATE", 409, "Meeting cannot be cancelled from its current state.")
        for it in DB["agenda_items"].values():
            if it["meeting_id"] == mid and it["status"] in ("PENDING", "OPEN"):
                cancel_item_cascade(it)
        m["status"] = "CANCELLED"
        touch(m)
        return success(ser_meeting(m))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for meeting transition.")


MINUTES_ROLE = {"DRAFT": ["Clerk"], "AMENDED": ["Clerk"], "APPROVED": ["BodyMember"]}


@app.route("/meetings/<mid>/minutes", methods=["POST"])
def meeting_minutes(mid):
    role, uid = authenticate(["Clerk", "BodyMember"])
    body = get_body()
    to_status = body.get("to_status")
    fine_authz(role, to_status, MINUTES_ROLE)

    m = get_or_404("meetings", mid)

    if to_status == "DRAFT":
        minutes_text = req_str(body, "minutes_text")
        if m["minutes_status"] != "NONE":
            err("ERR_INVALID_STATE", 409, "Minutes already drafted.")
        if m["status"] != "ADJOURNED":
            err("ERR_INVALID_STATE", 409, "Minutes may only be drafted after adjournment.")
        m["minutes_text"] = minutes_text
        m["minutes_status"] = "DRAFT"
        touch(m)
        return success(ser_meeting(m))

    if to_status == "APPROVED":
        require_presiding(uid, m)
        if m["minutes_status"] not in ("DRAFT", "AMENDED"):
            err("ERR_INVALID_STATE", 409, "Minutes must be DRAFT or AMENDED to approve.")
        m["minutes_status"] = "APPROVED"
        m["minutes_approved_at"] = now_str()
        touch(m)
        return success(ser_meeting(m))

    if to_status == "AMENDED":
        minutes_text = req_str(body, "minutes_text")
        if m["minutes_status"] != "APPROVED":
            err("ERR_INVALID_STATE", 409, "Only APPROVED minutes may be amended.")
        m["minutes_text"] = minutes_text
        m["minutes_approved_at"] = None
        m["minutes_status"] = "AMENDED"
        touch(m)
        return success(ser_meeting(m))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for minutes transition.")


# =============================================================================
# Endpoints: AgendaItem
# =============================================================================
@app.route("/meetings/<mid>/agenda-items", methods=["POST"])
def create_item(mid):
    authenticate(["Clerk"])
    get_or_404("meetings", mid)
    body = get_body()
    title = req_str(body, "title")
    sequence = req_int(body, "sequence", minimum=1)
    item_type = opt_enum(body, "item_type", ITEM_TYPES, "DISCUSSION")
    public_comment_enabled = opt_bool(body, "public_comment_enabled", True)
    rec = base_record()
    rec.update({
        "meeting_id": mid,
        "title": title,
        "sequence": sequence,
        "item_type": item_type,
        "public_comment_enabled": public_comment_enabled,
        "status": "PENDING",
    })
    DB["agenda_items"][rec["id"]] = rec
    return success(ser_item(rec), code=201)


@app.route("/agenda-items/<iid>", methods=["GET"])
def get_item(iid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester", "Anonymous"])
    rec = get_or_404("agenda_items", iid)
    return success(ser_item(rec))


@app.route("/meetings/<mid>/agenda-items", methods=["GET"])
def list_items(mid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester", "Anonymous"])
    get_or_404("meetings", mid)
    items = [i for i in DB["agenda_items"].values() if i["meeting_id"] == mid]
    return paginate_list(items, ser_item)


@app.route("/agenda-items/<iid>/transition", methods=["POST"])
def item_transition(iid):
    role, uid = authenticate(["BodyMember"])
    body = get_body()
    to_status = body.get("to_status")

    item = get_or_404("agenda_items", iid)
    meeting = meeting_of_item(item)
    require_presiding(uid, meeting)

    if to_status == "OPEN":
        if item["status"] != "PENDING":
            err("ERR_INVALID_STATE", 409, "Agenda item must be PENDING to open.")
        if meeting["status"] != "IN_SESSION":
            err("ERR_MEETING_NOT_IN_SESSION", 409, "Parent meeting must be IN_SESSION.")
        item["status"] = "OPEN"
        touch(item)
        return success(ser_item(item))

    if to_status == "CLOSED":
        if item["status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "Agenda item must be OPEN to close.")
        for mo in DB["motions"].values():
            if mo["agenda_item_id"] == iid and mo["status"] == "OPEN":
                err("ERR_OPEN_MOTIONS_EXIST", 409, "Cannot close item while a motion is OPEN.")
        for sl in DB["speaker_slips"].values():
            if sl["agenda_item_id"] == iid and sl["status"] in ("QUEUED", "CALLED"):
                sl["status"] = "EXPIRED"
                touch(sl)
        item["status"] = "CLOSED"
        touch(item)
        return success(ser_item(item))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for agenda-item transition.")


# =============================================================================
# Endpoints: SpeakerSlip
# =============================================================================
@app.route("/agenda-items/<iid>/speaker-slips", methods=["POST"])
def create_slip(iid):
    role, uid = authenticate(["Requester"])
    item = get_or_404("agenda_items", iid)
    body = get_body()
    requester_id = req_str(body, "requester_id")
    speaker_name = req_str(body, "speaker_name")
    allotted_seconds = opt_int(body, "allotted_seconds", 180, minimum=0)
    # ownership: requester_id must equal acting X-User-ID
    if requester_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "requester_id must match the acting requester.")
    if not item["public_comment_enabled"]:
        err("ERR_PUBLIC_COMMENT_DISABLED", 409, "Public comment is disabled for this item.")
    active = sum(s["allotted_seconds"] for s in DB["speaker_slips"].values()
                 if s["agenda_item_id"] == iid and s["status"] in ("QUEUED", "CALLED", "SPOKEN"))
    if active + allotted_seconds > ITEM_COMMENT_CAP_SECONDS:
        err("ERR_COMMENT_CAP_EXCEEDED", 409, "Aggregate comment cap exceeded for this item.")
    rec = base_record()
    rec.update({
        "agenda_item_id": iid,
        "requester_id": requester_id,
        "speaker_name": speaker_name,
        "allotted_seconds": allotted_seconds,
        "called_at": None,
        "status": "QUEUED",
    })
    DB["speaker_slips"][rec["id"]] = rec
    return success(ser_slip(rec), code=201)


@app.route("/agenda-items/<iid>/speaker-slips", methods=["GET"])
def list_slips(iid):
    authenticate(["Clerk", "BodyMember", "Requester", "Anonymous"])
    get_or_404("agenda_items", iid)
    status_f = request.args.get("status")
    items = [s for s in DB["speaker_slips"].values() if s["agenda_item_id"] == iid]
    if status_f is not None:
        items = [s for s in items if s["status"] == status_f]
    return paginate_list(items, ser_slip)


SLIP_TRANSITION_ROLE = {
    "CALLED": ["BodyMember"],
    "SPOKEN": ["BodyMember"],
    "YIELDED": ["BodyMember"],
    "WITHDRAWN": ["Requester"],
}


@app.route("/speaker-slips/<sid>/transition", methods=["POST"])
def slip_transition(sid):
    role, uid = authenticate(["BodyMember", "Requester"])
    body = get_body()
    to_status = body.get("to_status")
    fine_authz(role, to_status, SLIP_TRANSITION_ROLE)

    slip = get_or_404("speaker_slips", sid)
    item = DB["agenda_items"].get(slip["agenda_item_id"])
    meeting = meeting_of_item(item) if item else None

    if to_status == "WITHDRAWN":
        if uid != slip["requester_id"]:
            err("ERR_NOT_RESOURCE_OWNER", 403, "Only the slip owner may withdraw it.")
        if slip["status"] != "QUEUED":
            err("ERR_INVALID_STATE", 409, "Only a QUEUED slip may be withdrawn.")
        slip["status"] = "WITHDRAWN"
        touch(slip)
        return success(ser_slip(slip))

    # BodyMember / presiding actions
    require_presiding(uid, meeting)

    if to_status == "CALLED":
        if slip["status"] != "QUEUED":
            err("ERR_INVALID_STATE", 409, "Only a QUEUED slip may be called.")
        if item["status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "Parent agenda item must be OPEN.")
        for other in DB["speaker_slips"].values():
            if other["agenda_item_id"] == slip["agenda_item_id"] and other["status"] == "CALLED":
                err("ERR_SPEAKER_ALREADY_ACTIVE", 409, "Another speaker is currently called.")
        slip["called_at"] = now_str()
        slip["status"] = "CALLED"
        touch(slip)
        return success(ser_slip(slip))

    if to_status == "SPOKEN":
        if slip["status"] != "CALLED":
            err("ERR_INVALID_STATE", 409, "Only a CALLED slip may be marked spoken.")
        slip["status"] = "SPOKEN"
        touch(slip)
        return success(ser_slip(slip))

    if to_status == "YIELDED":
        if slip["status"] != "CALLED":
            err("ERR_INVALID_STATE", 409, "Only a CALLED slip may yield.")
        slip["status"] = "YIELDED"
        touch(slip)
        return success(ser_slip(slip))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for speaker-slip transition.")


# =============================================================================
# Endpoints: Motion
# =============================================================================
@app.route("/agenda-items/<iid>/motions", methods=["POST"])
def create_motion(iid):
    role, uid = authenticate(["BodyMember"])
    item = get_or_404("agenda_items", iid)
    body = get_body()
    text = req_str(body, "text")
    moved_by = req_str(body, "moved_by_member_id")
    seconded_by = req_str(body, "seconded_by_member_id")
    vote_threshold = opt_enum(body, "vote_threshold", VOTE_THRESHOLDS, "SIMPLE")

    # validation (422): mover distinct from seconder
    if moved_by == seconded_by:
        err("ERR_MOVER_SECONDER_SAME", 422, "Mover and seconder must be distinct.")
    # state (409): item actionable, members present
    if item["item_type"] != "ACTION":
        err("ERR_ITEM_NOT_ACTIONABLE", 409, "Motions may only be moved on ACTION items.")
    meeting = meeting_of_item(item)
    present = set(meeting["present_member_ids"]) if meeting else set()
    if moved_by not in present or seconded_by not in present:
        err("ERR_MEMBER_NOT_PRESENT", 409, "Mover and seconder must be present members.")

    rec = base_record()
    rec.update({
        "agenda_item_id": iid,
        "text": text,
        "moved_by_member_id": moved_by,
        "seconded_by_member_id": seconded_by,
        "vote_threshold": vote_threshold,
        "ballots": [],
        "status": "DRAFT",
    })
    DB["motions"][rec["id"]] = rec
    return success(ser_motion(rec), code=201)


@app.route("/agenda-items/<iid>/motions", methods=["GET"])
def list_motions(iid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "BodyMember", "Requester", "Anonymous"])
    get_or_404("agenda_items", iid)
    status_f = request.args.get("status")
    items = [mo for mo in DB["motions"].values() if mo["agenda_item_id"] == iid]
    if status_f is not None:
        items = [mo for mo in items if mo["status"] == status_f]
    return paginate_list(items, ser_motion)


def motion_outcome(motion, meeting):
    ballots = motion["ballots"]
    yea = sum(1 for b in ballots if b["value"] == "YEA")
    nay = sum(1 for b in ballots if b["value"] == "NAY")
    if motion["vote_threshold"] == "SIMPLE":
        return "CARRIED" if yea > nay else "FAILED"
    body_rec = DB["public_bodies"].get(meeting["body_id"])
    seat_count = body_rec["seat_count"] if body_rec else 0
    return "CARRIED" if (yea * 2) > seat_count else "FAILED"


@app.route("/motions/<moid>/transition", methods=["POST"])
def motion_transition(moid):
    role, uid = authenticate(["BodyMember"])
    body = get_body()
    to_status = body.get("to_status")

    motion = get_or_404("motions", moid)
    item = DB["agenda_items"].get(motion["agenda_item_id"])
    meeting = meeting_of_item(item) if item else None
    require_presiding(uid, meeting)

    if to_status == "OPEN":
        if motion["status"] not in ("DRAFT", "TABLED"):
            err("ERR_INVALID_STATE", 409, "Motion must be DRAFT or TABLED to open.")
        if item["status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "Parent agenda item must be OPEN.")
        if meeting["status"] != "IN_SESSION":
            err("ERR_MEETING_NOT_IN_SESSION", 409, "Parent meeting must be IN_SESSION.")
        motion["status"] = "OPEN"
        touch(motion)
        return success(ser_motion(motion))

    if to_status == "TABLED":
        if motion["status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "Only an OPEN motion may be tabled.")
        motion["status"] = "TABLED"
        touch(motion)
        return success(ser_motion(motion))

    if to_status == "CLOSED":
        if motion["status"] != "OPEN":
            err("ERR_INVALID_STATE", 409, "Only an OPEN motion may be closed.")
        motion["status"] = motion_outcome(motion, meeting)
        touch(motion)
        return success(ser_motion(motion))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for motion transition.")


@app.route("/motions/<moid>/votes", methods=["POST"])
def cast_vote(moid):
    role, uid = authenticate(["BodyMember"])
    motion = get_or_404("motions", moid)
    body = get_body()
    member_id = req_str(body, "member_id")
    value = req_enum(body, "value", BALLOT_VALUES)

    if motion["status"] != "OPEN":
        err("ERR_INVALID_STATE", 409, "Ballots may only be cast on an OPEN motion.")
    item = DB["agenda_items"].get(motion["agenda_item_id"])
    meeting = meeting_of_item(item) if item else None
    present = set(meeting["present_member_ids"]) if meeting else set()
    if member_id not in present:
        err("ERR_MEMBER_NOT_PRESENT", 409, "Voter must be a present member.")

    # upsert one ballot per member
    found = False
    for b in motion["ballots"]:
        if b["member_id"] == member_id:
            b["value"] = value
            found = True
            break
    if not found:
        motion["ballots"].append({"member_id": member_id, "value": value})
    touch(motion)
    return success(ser_motion(motion))


# =============================================================================
# Endpoints: Requester
# =============================================================================
@app.route("/requesters", methods=["POST"])
def create_requester():
    authenticate(["Anonymous"])
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    organization = opt_str(body, "organization", None)
    rec = base_record()
    rec.update({"full_name": full_name, "email": email, "organization": organization})
    DB["requesters"][rec["id"]] = rec
    return success(ser_requester(rec), code=201)


# =============================================================================
# Endpoints: RecordsRequest
# =============================================================================
@app.route("/records-requests", methods=["POST"])
def create_request():
    role, uid = authenticate(["Requester"])
    body = get_body()
    requester_id = req_str(body, "requester_id")
    body_id = req_str(body, "body_id")
    subject = req_str(body, "subject")
    description = req_str(body, "description")
    estimated_page_count = req_int(body, "estimated_page_count", minimum=0)

    if requester_id != uid:
        err("ERR_NOT_RESOURCE_OWNER", 403, "requester_id must match the acting requester.")
    # body_id well-formedness (not a path resource)
    if body_id not in DB["public_bodies"]:
        err("ERR_VALIDATION", 422, "body_id must reference an existing public body.")

    submitted = now_dt()
    rec = base_record()
    rec.update({
        "requester_id": requester_id,
        "body_id": body_id,
        "subject": subject,
        "description": description,
        "estimated_page_count": estimated_page_count,
        "submitted_at": now_str(),
        "response_deadline": response_deadline_for(submitted),
        "estimated_fee_cents": copy_fee(estimated_page_count),
        "assessed_fee_cents": 0,
        "amount_waived_cents": 0,
        "amount_paid_cents": 0,
        "decision": "NONE",
        "determined_by_user_id": None,
        "determined_at": None,
        "status": "RECEIVED",
    })
    DB["records_requests"][rec["id"]] = rec
    return success(ser_request(rec), code=201)


@app.route("/records-requests/<rid>", methods=["GET"])
def get_request(rid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "Requester"])
    rec = get_or_404("records_requests", rid)
    return success(ser_request(rec))


@app.route("/records-requests", methods=["GET"])
def list_requests():
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "Requester"])
    requester_f = request.args.get("requester_id")
    body_f = request.args.get("body_id")
    status_f = request.args.get("status")
    items = list(DB["records_requests"].values())
    if requester_f is not None:
        items = [r for r in items if r["requester_id"] == requester_f]
    if body_f is not None:
        items = [r for r in items if r["body_id"] == body_f]
    if status_f is not None:
        items = [r for r in items if r["status"] == status_f]
    return paginate_list(items, ser_request)


RR_TRANSITION_ROLE = {
    "UNDER_REVIEW": ["RecordsOfficer"],
    "CLOSED": ["RecordsOfficer"],
    "WITHDRAWN": ["Requester"],
}


def cancel_request_documents(rid):
    for d in DB["documents"].values():
        if d["request_id"] == rid and d["status"] != "DISPOSED":
            d["status"] = "CANCELLED"
            touch(d)


@app.route("/records-requests/<rid>/transition", methods=["POST"])
def request_transition(rid):
    role, uid = authenticate(["RecordsOfficer", "Requester"])
    body = get_body()
    to_status = body.get("to_status")
    fine_authz(role, to_status, RR_TRANSITION_ROLE)

    r = get_or_404("records_requests", rid)

    if to_status == "WITHDRAWN":
        if uid != r["requester_id"]:
            err("ERR_NOT_RESOURCE_OWNER", 403, "Only the request owner may withdraw it.")
        if r["status"] not in ("RECEIVED", "UNDER_REVIEW"):
            err("ERR_INVALID_STATE", 409, "Request cannot be withdrawn from its current state.")
        was_under_review = r["status"] == "UNDER_REVIEW"
        cancel_request_documents(rid)
        if was_under_review:
            r["assessed_fee_cents"] = 0
        r["status"] = "WITHDRAWN"
        touch(r)
        return success(ser_request(r))

    if to_status == "UNDER_REVIEW":
        if r["status"] != "RECEIVED":
            err("ERR_INVALID_STATE", 409, "Request must be RECEIVED to open review.")
        r["status"] = "UNDER_REVIEW"
        touch(r)
        return success(ser_request(r))

    if to_status == "CLOSED":
        if r["status"] not in ("GRANTED", "PARTIALLY_GRANTED", "DENIED"):
            err("ERR_INVALID_STATE", 409, "Request cannot be closed from its current state.")
        if r["status"] in ("GRANTED", "PARTIALLY_GRANTED"):
            balance = r["assessed_fee_cents"] - r["amount_waived_cents"] - r["amount_paid_cents"]
            if balance != 0:
                err("ERR_FEE_OUTSTANDING", 409, "Outstanding fee balance blocks closing.")
        r["status"] = "CLOSED"
        touch(r)
        return success(ser_request(r))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for request transition.")


@app.route("/records-requests/<rid>/determination", methods=["POST"])
def determination(rid):
    role, uid = authenticate(["RecordsOfficer"])
    r = get_or_404("records_requests", rid)
    body = get_body()

    decision = body.get("decision")
    if decision not in DECISIONS:
        err("ERR_VALIDATION", 422, "decision must be GRANTED, PARTIALLY_GRANTED, or DENIED.")
    if "expected_records_request_version" not in body or body["expected_records_request_version"] is None:
        err("ERR_VALIDATION", 422, "expected_records_request_version is required.")
    expected = body["expected_records_request_version"]
    if isinstance(expected, bool) or not isinstance(expected, int):
        err("ERR_VALIDATION", 422, "expected_records_request_version must be an integer.")
    waive = opt_int(body, "waive_fee_cents", 0, minimum=0)

    assessed = compute_assessed(rid)
    if waive > assessed:
        err("ERR_WAIVER_EXCEEDS_FEE", 422, "Waiver may not exceed the assessed fee.")
    if expected != r["version"]:
        err("ERR_STALE_VERSION", 412, "Request version is stale.")
    if r["status"] != "UNDER_REVIEW":
        err("ERR_INVALID_STATE", 409, "Determination requires the request to be UNDER_REVIEW.")

    r["assessed_fee_cents"] = assessed
    r["amount_waived_cents"] = waive
    r["decision"] = decision
    r["status"] = decision
    r["determined_by_user_id"] = uid
    r["determined_at"] = now_str()
    touch(r)
    return success(ser_request(r))


@app.route("/records-requests/<rid>/payments", methods=["POST"])
def record_payment(rid):
    role, uid = authenticate(["Requester"])
    r = get_or_404("records_requests", rid)
    body = get_body()
    amount = req_int(body, "amount_cents", minimum=0)
    if uid != r["requester_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Only the request owner may pay.")
    r["amount_paid_cents"] += amount
    touch(r)
    return success(ser_request(r))


# =============================================================================
# Endpoints: ResponsiveDocument
# =============================================================================
@app.route("/records-requests/<rid>/documents", methods=["POST"])
def create_document(rid):
    authenticate(["RecordsOfficer"])
    r = get_or_404("records_requests", rid)
    body = get_body()
    title = req_str(body, "title")
    page_count = req_int(body, "page_count", minimum=0)
    review_minutes = req_int(body, "review_minutes", minimum=0)
    exemption_code = opt_enum(body, "exemption_code", EXEMPTION_CODES, "NONE")
    retention_series = opt_enum(body, "retention_series", RETENTION_SERIES, "ADMIN")

    if r["status"] != "UNDER_REVIEW":
        err("ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW", 409, "Documents may only be attached while UNDER_REVIEW.")

    rec = base_record()
    rec.update({
        "request_id": rid,
        "title": title,
        "page_count": page_count,
        "review_minutes": review_minutes,
        "exemption_code": exemption_code,
        "retention_series": retention_series,
        "status": "IDENTIFIED",
    })
    DB["documents"][rec["id"]] = rec
    # attaching a document bumps the parent request version (OCC-relevant)
    touch(r)
    return success(ser_document(rec), code=201)


@app.route("/records-requests/<rid>/documents", methods=["GET"])
def list_documents(rid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "Requester"])
    get_or_404("records_requests", rid)
    status_f = request.args.get("status")
    items = [d for d in DB["documents"].values() if d["request_id"] == rid]
    if status_f is not None:
        items = [d for d in items if d["status"] == status_f]
    return paginate_list(items, ser_document)


DOC_TRANSITION_ROLE = {
    "REVIEWED": ["RecordsOfficer"],
    "RELEASED": ["RecordsOfficer"],
    "REDACTED": ["RecordsOfficer"],
    "EXEMPT": ["RecordsOfficer"],
    "DISPOSED": ["RecordsOfficer", "Clerk"],
}


@app.route("/records-requests/<rid>/documents/<did>/transition", methods=["POST"])
def document_transition(rid, did):
    role, uid = authenticate(["RecordsOfficer", "Clerk"])
    body = get_body()
    to_status = body.get("to_status")
    fine_authz(role, to_status, DOC_TRANSITION_ROLE)

    r = get_or_404("records_requests", rid)
    d = DB["documents"].get(did)
    if d is None or d["request_id"] != rid:
        err("ERR_NOT_FOUND", 404, "Document not found.")

    if to_status == "REVIEWED":
        if d["status"] != "IDENTIFIED":
            err("ERR_INVALID_STATE", 409, "Document must be IDENTIFIED to review.")
        if r["status"] != "UNDER_REVIEW":
            err("ERR_DOCUMENT_REQUEST_NOT_UNDER_REVIEW", 409, "Parent request must be UNDER_REVIEW.")
        d["status"] = "REVIEWED"
        touch(d)
        return success(ser_document(d))

    if to_status == "RELEASED":
        if d["status"] != "REVIEWED":
            err("ERR_INVALID_STATE", 409, "Document must be REVIEWED to release.")
        d["status"] = "RELEASED"
        touch(d)
        return success(ser_document(d))

    if to_status == "REDACTED":
        if d["status"] != "REVIEWED":
            err("ERR_INVALID_STATE", 409, "Document must be REVIEWED to redact.")
        if d["exemption_code"] == "NONE":
            err("ERR_VALIDATION", 422, "A redaction requires an exemption basis.")
        d["status"] = "REDACTED"
        touch(d)
        return success(ser_document(d))

    if to_status == "EXEMPT":
        if d["status"] != "REVIEWED":
            err("ERR_INVALID_STATE", 409, "Document must be REVIEWED to withhold.")
        if d["exemption_code"] == "NONE":
            err("ERR_VALIDATION", 422, "A full withholding requires an exemption basis.")
        d["status"] = "EXEMPT"
        touch(d)
        return success(ser_document(d))

    if to_status == "DISPOSED":
        if d["status"] not in ("RELEASED", "REDACTED", "EXEMPT"):
            err("ERR_INVALID_STATE", 409, "Only a RELEASED/REDACTED/EXEMPT document may be disposed.")
        years = RETENTION_YEARS[d["retention_series"]]
        threshold = parse_iso(d["created_at"]) + timedelta(days=years * DAYS_PER_YEAR)
        if now_dt() < threshold:
            err("ERR_RETENTION_NOT_ELAPSED", 409, "Retention period has not elapsed.")
        d["status"] = "DISPOSED"
        touch(d)
        return success(ser_document(d))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for document transition.")


# =============================================================================
# Endpoints: Appeal
# =============================================================================
@app.route("/records-requests/<rid>/appeals", methods=["POST"])
def file_appeal(rid):
    role, uid = authenticate(["Requester"])
    r = get_or_404("records_requests", rid)
    body = get_body()
    grounds = req_str(body, "grounds")

    if uid != r["requester_id"]:
        err("ERR_NOT_RESOURCE_OWNER", 403, "Only the request owner may file an appeal.")
    if r["status"] not in ("DENIED", "PARTIALLY_GRANTED"):
        err("ERR_REQUEST_NOT_DENIED", 409, "Appeals require a DENIED or PARTIALLY_GRANTED request.")
    if r["determined_at"] is not None:
        window_end = parse_iso(r["determined_at"]) + timedelta(days=APPEAL_WINDOW_DAYS)
        if now_dt() > window_end:
            err("ERR_APPEAL_WINDOW_CLOSED", 409, "Appeal window has closed.")

    rec = base_record()
    rec.update({
        "request_id": rid,
        "grounds": grounds,
        "filed_at": now_str(),
        "decided_by_user_id": None,
        "decision": "NONE",
        "status": "FILED",
    })
    DB["appeals"][rec["id"]] = rec
    return success(ser_appeal(rec), code=201)


@app.route("/records-requests/<rid>/appeals", methods=["GET"])
def list_appeals(rid):
    authenticate(["Clerk", "RecordsOfficer", "AppealsOfficer", "Requester"])
    get_or_404("records_requests", rid)
    items = [a for a in DB["appeals"].values() if a["request_id"] == rid]
    return paginate_list(items, ser_appeal)


def reopen_request_on_remand(r):
    if r["status"] in ("DENIED", "PARTIALLY_GRANTED"):
        r["status"] = "UNDER_REVIEW"
        r["decision"] = "NONE"
        r["determined_by_user_id"] = None
        r["determined_at"] = None
        for d in DB["documents"].values():
            if d["request_id"] == r["id"] and d["status"] == "EXEMPT":
                d["status"] = "REVIEWED"
                touch(d)
        touch(r)


def overturn_request(r):
    r["status"] = "GRANTED"
    r["decision"] = "GRANTED"
    r["assessed_fee_cents"] = compute_assessed(r["id"])
    touch(r)


@app.route("/records-requests/<rid>/appeals/<aid>/transition", methods=["POST"])
def appeal_transition(rid, aid):
    role, uid = authenticate(["AppealsOfficer"])
    body = get_body()
    to_status = body.get("to_status")

    r = get_or_404("records_requests", rid)
    a = DB["appeals"].get(aid)
    if a is None or a["request_id"] != rid:
        err("ERR_NOT_FOUND", 404, "Appeal not found.")

    if to_status == "UNDER_REVIEW":
        if uid == r["determined_by_user_id"]:
            err("ERR_SEGREGATION_OF_DUTIES", 403, "Appeals officer may not review their own determination.")
        if a["status"] != "FILED":
            err("ERR_INVALID_STATE", 409, "Appeal must be FILED to take up.")
        a["decided_by_user_id"] = uid
        a["status"] = "UNDER_REVIEW"
        touch(a)
        return success(ser_appeal(a))

    if to_status == "UPHELD":
        if a["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", 409, "Appeal must be UNDER_REVIEW to decide.")
        a["decision"] = "UPHELD"
        a["status"] = "UPHELD"
        touch(a)
        return success(ser_appeal(a))

    if to_status == "OVERTURNED":
        if a["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", 409, "Appeal must be UNDER_REVIEW to decide.")
        a["decision"] = "OVERTURNED"
        a["status"] = "OVERTURNED"
        overturn_request(r)
        touch(a)
        return success(ser_appeal(a))

    if to_status == "REMANDED":
        if a["status"] != "UNDER_REVIEW":
            err("ERR_INVALID_STATE", 409, "Appeal must be UNDER_REVIEW to decide.")
        a["decision"] = "REMANDED"
        a["status"] = "REMANDED"
        reopen_request_on_remand(r)
        touch(a)
        return success(ser_appeal(a))

    err("ERR_VALIDATION", 422, "Unknown or missing to_status for appeal transition.")


# =============================================================================
# Boot
# =============================================================================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
