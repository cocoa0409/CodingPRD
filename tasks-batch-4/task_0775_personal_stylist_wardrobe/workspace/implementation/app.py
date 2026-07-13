import os
import uuid
import math
import random
import string
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Error catalog (error_id -> http status)
# ---------------------------------------------------------------------------
ERROR_STATUS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_UNAUTHORIZED": 403,
    "ERR_VALIDATION": 422,
    "ERR_INVALID_TIME_RANGE": 422,
    "ERR_CLIENT_NOT_FOUND": 404,
    "ERR_STYLIST_NOT_FOUND": 404,
    "ERR_ASSESSMENT_NOT_FOUND": 404,
    "ERR_ENGAGEMENT_NOT_FOUND": 404,
    "ERR_SESSION_NOT_FOUND": 404,
    "ERR_PURCHASE_ITEM_NOT_FOUND": 404,
    "ERR_LOOKBOOK_NOT_FOUND": 404,
    "ERR_SUBSCRIPTION_NOT_FOUND": 404,
    "ERR_REFERRAL_NOT_FOUND": 404,
    "ERR_INVOICE_NOT_FOUND": 404,
    "ERR_INVALID_ASSESSMENT_STATE": 409,
    "ERR_INVALID_ENGAGEMENT_STATE": 409,
    "ERR_INVALID_SESSION_STATE": 409,
    "ERR_INVALID_PURCHASE_ITEM_STATE": 409,
    "ERR_INVALID_LOOKBOOK_STATE": 409,
    "ERR_INVALID_SUBSCRIPTION_STATE": 409,
    "ERR_INVALID_INVOICE_STATE": 409,
    "ERR_INVALID_REFERRAL_STATE": 409,
    "ERR_ASSESSMENT_NOT_COMPLETED": 409,
    "ERR_ENGAGEMENT_NOT_ACTIVE": 409,
    "ERR_LOOKBOOK_EMPTY": 422,
    "ERR_STYLIST_TIME_CONFLICT": 409,
    "ERR_CLIENT_TIME_CONFLICT": 409,
    "ERR_INSUFFICIENT_PACKAGE_HOURS": 409,
    "ERR_INSUFFICIENT_WALLET": 409,
    "ERR_NO_REFRESH_CREDITS": 409,
    "ERR_SELF_REFERRAL": 422,
    "ERR_REFERRAL_EXPIRED": 409,
    "ERR_STALE_ENGAGEMENT_VERSION": 412,
}


class ApiError(Exception):
    def __init__(self, error_id, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = ERROR_STATUS.get(error_id, 400)
        self.message = message or error_id


# ---------------------------------------------------------------------------
# In-memory stores (wiped on every process start)
# ---------------------------------------------------------------------------
clients = {}
stylists = {}
assessments = {}
engagements = {}
sessions = {}
purchase_items = {}
lookbooks = {}
subscriptions = {}
referrals = {}
invoices = {}

_seq_counter = {"n": 0}
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def fmt_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return fmt_dt(datetime.now(timezone.utc))


def parse_dt(s):
    if not isinstance(s, str) or not s:
        raise ValueError("bad datetime")
    dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


# ---------------------------------------------------------------------------
# Entity / response helpers
# ---------------------------------------------------------------------------
def add_common(e):
    now = now_ts()
    e["id"] = str(uuid.uuid4())
    e["created_at"] = now
    e["updated_at"] = now
    e["version"] = 1
    e["_seq"] = next_seq()
    return e


def touch(e):
    e["version"] += 1
    e["updated_at"] = now_ts()


def ser(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}


def make_meta(pagination=None):
    m = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)
        ),
        "api_request_timestamp": now_ts(),
    }
    if pagination:
        m.update(pagination)
    return m


def success(data, response_type="object", status=200, pagination=None):
    return jsonify({
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify({
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }), err.http_status


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
VALID_ROLES = {"Anonymous", "Client", "Stylist", "PlatformAdmin"}


def require(allowed, exempt=False):
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if exempt:
        if role is not None and role not in allowed:
            raise ApiError("ERR_UNAUTHORIZED")
        return role, uid
    if not role or role not in VALID_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED")
    if role != "Anonymous" and (uid is None or uid == ""):
        raise ApiError("ERR_UNAUTHENTICATED")
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED")
    return role, uid


def forbid():
    raise ApiError("ERR_UNAUTHORIZED")


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------
def get_or_404(store, _id, errid):
    e = store.get(_id)
    if e is None:
        raise ApiError(errid)
    return e


def body_json():
    b = request.get_json(silent=True)
    return b if isinstance(b, dict) else {}


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v == "":
        raise ApiError("ERR_VALIDATION", f"missing or invalid '{field}'")
    return v


def req_int(body, field, positive=False, nonneg=False):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", f"missing or invalid '{field}'")
    if positive and v <= 0:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be > 0")
    if nonneg and v < 0:
        raise ApiError("ERR_VALIDATION", f"'{field}' must be >= 0")
    return v


def enum_field(body, field, choices):
    v = body.get(field)
    if v not in choices:
        raise ApiError("ERR_VALIDATION", f"invalid '{field}'")
    return v


# ---------------------------------------------------------------------------
# Calculation helpers
# ---------------------------------------------------------------------------
def rhu(dec):
    return int(Decimal(dec).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def blocks_from_minutes(minutes):
    return max(4, math.ceil(minutes / 15.0))


def window_minutes(start_dt, end_dt):
    return (end_dt - start_dt).total_seconds() / 60.0


def markup_pct_for(retail):
    if retail < 5000:
        return Decimal("0.30")
    if retail < 20000:
        return Decimal("0.20")
    return Decimal("0.10")


def paginate(items):
    def to_int(v, default):
        try:
            return int(v)
        except (TypeError, ValueError):
            return default

    limit = to_int(request.args.get("limit"), 10)
    offset = to_int(request.args.get("offset"), 0)
    if limit < 1:
        limit = 1
    if limit > 100:
        limit = 100
    if offset < 0:
        offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pag = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return page, pag


def list_response(items, extra_filters=None):
    items = sorted(items, key=lambda e: e["_seq"])
    status_f = request.args.get("status")
    if status_f is not None:
        items = [e for e in items if e.get("status") == status_f]
    if extra_filters:
        for field, val in extra_filters.items():
            if val is not None:
                items = [e for e in items if e.get(field) == val]
    page, pag = paginate(items)
    return success([ser(e) for e in page], response_type="array",
                   status=200, pagination=pag)


# ---------------------------------------------------------------------------
# Overlap checks
# ---------------------------------------------------------------------------
def check_stylist_overlap(engagement, start_dt, end_dt, exclude_id=None):
    stylist_id = engagement["stylist_id"]
    for other in sessions.values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        oeng = engagements[other["engagement_id"]]
        if oeng["stylist_id"] != stylist_id:
            continue
        if start_dt < other["_end"] and other["_start"] < end_dt:
            raise ApiError("ERR_STYLIST_TIME_CONFLICT")


def check_client_buffer(engagement, start_dt, end_dt, modality, exclude_id=None):
    if modality != "IN_PERSON":
        return
    client_id = engagement["client_id"]
    exp_start = start_dt - timedelta(minutes=60)
    exp_end = end_dt + timedelta(minutes=60)
    for other in sessions.values():
        if other["id"] == exclude_id:
            continue
        if other["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        if other["modality"] != "IN_PERSON":
            continue
        oeng = engagements[other["engagement_id"]]
        if oeng["client_id"] != client_id:
            continue
        if exp_start < other["_end"] and other["_start"] < exp_end:
            raise ApiError("ERR_CLIENT_TIME_CONFLICT")


# ===========================================================================
# Provisioning / identity
# ===========================================================================
@app.route("/styling/stylists", methods=["POST"])
def create_stylist():
    require({"PlatformAdmin"})
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    commission_pct = body.get("commission_pct")
    if isinstance(commission_pct, bool) or not isinstance(commission_pct, (int, float)):
        raise ApiError("ERR_VALIDATION", "invalid commission_pct")
    if commission_pct < 0 or commission_pct > 1:
        raise ApiError("ERR_VALIDATION", "commission_pct must be within 0..1")
    tier = enum_field(body, "tier", {"JUNIOR", "SENIOR", "LEAD"})
    if any(s["email"] == email for s in stylists.values()):
        raise ApiError("ERR_VALIDATION", "stylist email must be unique")
    s = add_common({
        "full_name": full_name,
        "email": email,
        "commission_pct": commission_pct,
        "tier": tier,
        "earned_commission_cents": 0,
        "status": "ACTIVE",
    })
    stylists[s["id"]] = s
    return success(ser(s), status=201)


@app.route("/styling/stylists/<sid>", methods=["GET"])
def get_stylist(sid):
    require({"PlatformAdmin", "Stylist", "Client"})
    s = get_or_404(stylists, sid, "ERR_STYLIST_NOT_FOUND")
    return success(ser(s))


@app.route("/styling/clients/register", methods=["POST"])
def register_client():
    require({"Anonymous"}, exempt=True)
    body = body_json()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    if any(c["email"] == email for c in clients.values()):
        raise ApiError("ERR_VALIDATION", "client email must be unique")
    c = add_common({
        "full_name": full_name,
        "email": email,
        "wallet_credit_cents": 0,
        "has_paid_invoice": False,
        "status": "ACTIVE",
    })
    clients[c["id"]] = c
    return success(ser(c), status=201)


@app.route("/styling/clients/<cid>", methods=["GET"])
def get_client(cid):
    require({"PlatformAdmin", "Stylist", "Client"})
    c = get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    return success(ser(c))


# ===========================================================================
# Style assessments
# ===========================================================================
@app.route("/styling/clients/<cid>/assessments", methods=["POST"])
def create_assessment(cid):
    role, uid = require({"Client"})
    c = get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    if cid != uid:
        forbid()
    body = body_json()
    body_type = req_str(body, "body_type")
    color_palette = enum_field(body, "color_palette", {"WARM", "COOL", "NEUTRAL"})
    budget_band = enum_field(body, "budget_band", {"ECONOMY", "MID", "PREMIUM", "LUXURY"})
    lifestyle = req_str(body, "lifestyle")
    a = add_common({
        "client_id": cid,
        "body_type": body_type,
        "color_palette": color_palette,
        "budget_band": budget_band,
        "lifestyle": lifestyle,
        "status": "DRAFT",
    })
    assessments[a["id"]] = a
    return success(ser(a), status=201)


@app.route("/styling/clients/<cid>/assessments", methods=["GET"])
def list_assessments(cid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    items = [a for a in assessments.values() if a["client_id"] == cid]
    return list_response(items)


@app.route("/styling/assessments/<aid>/complete", methods=["POST"])
def complete_assessment(aid):
    require({"Stylist"})
    a = get_or_404(assessments, aid, "ERR_ASSESSMENT_NOT_FOUND")
    if a["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ASSESSMENT_STATE")
    a["status"] = "COMPLETED"
    touch(a)
    return success(ser(a))


# ===========================================================================
# Engagements
# ===========================================================================
@app.route("/styling/engagements", methods=["POST"])
def create_engagement():
    role, uid = require({"Client"})
    body = body_json()

    client_id = body.get("client_id")
    if not isinstance(client_id, str) or client_id == "":
        raise ApiError("ERR_VALIDATION", "missing client_id")
    if client_id not in clients:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    stylist_id = body.get("stylist_id")
    if not isinstance(stylist_id, str) or stylist_id == "":
        raise ApiError("ERR_VALIDATION", "missing stylist_id")
    if stylist_id not in stylists:
        raise ApiError("ERR_STYLIST_NOT_FOUND")

    if client_id != uid:
        forbid()

    mode = enum_field(body, "mode", {"HOURLY", "PACKAGE"})
    block_rate_cents = req_int(body, "block_rate_cents", positive=True)
    package_blocks = body.get("package_blocks")
    package_price_cents = body.get("package_price_cents")

    if mode == "PACKAGE":
        if isinstance(package_blocks, bool) or not isinstance(package_blocks, int):
            raise ApiError("ERR_VALIDATION", "package_blocks required for PACKAGE")
        if package_blocks < 4:
            raise ApiError("ERR_VALIDATION", "package_blocks must be >= 4")
        if package_price_cents is not None:
            if isinstance(package_price_cents, bool) or not isinstance(package_price_cents, int):
                raise ApiError("ERR_VALIDATION", "invalid package_price_cents")
        avail = package_blocks
    else:  # HOURLY
        if package_blocks is not None:
            raise ApiError("ERR_VALIDATION", "package_blocks forbidden for HOURLY")
        package_blocks = None
        package_price_cents = None
        avail = 0

    e = add_common({
        "client_id": client_id,
        "stylist_id": stylist_id,
        "mode": mode,
        "block_rate_cents": block_rate_cents,
        "package_blocks": package_blocks,
        "package_price_cents": package_price_cents,
        "hours_reserved_blocks": 0,
        "hours_consumed_blocks": 0,
        "hours_available_blocks": avail,
        "retail_spend_cents": 0,
        "status": "DRAFT",
    })
    engagements[e["id"]] = e
    return success(ser(e), status=201)


@app.route("/styling/engagements/<eid>", methods=["GET"])
def get_engagement(eid):
    require({"PlatformAdmin", "Stylist", "Client"})
    e = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    return success(ser(e))


@app.route("/styling/engagements", methods=["GET"])
def list_engagements():
    require({"PlatformAdmin", "Stylist", "Client"})
    items = list(engagements.values())
    return list_response(items, extra_filters={
        "client_id": request.args.get("client_id"),
        "stylist_id": request.args.get("stylist_id"),
    })


@app.route("/styling/engagements/<eid>/activate", methods=["POST"])
def activate_engagement(eid):
    role, uid = require({"Client"})
    e = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if e["client_id"] != uid:
        forbid()
    if e["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")
    e["status"] = "ACTIVE"
    touch(e)
    return success(ser(e))


@app.route("/styling/engagements/<eid>/cancel", methods=["POST"])
def cancel_engagement(eid):
    role, uid = require({"Client"})
    e = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if e["client_id"] != uid:
        forbid()
    if e["status"] not in ("DRAFT", "ACTIVE"):
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")
    is_package = e["mode"] == "PACKAGE"
    for s in sessions.values():
        if s["engagement_id"] != eid:
            continue
        if s["status"] in ("SCHEDULED", "CONFIRMED"):
            s["status"] = "CANCELLED"
            touch(s)
            if is_package:
                e["hours_reserved_blocks"] -= s["estimated_blocks"]
                e["hours_available_blocks"] += s["estimated_blocks"]
    e["status"] = "CANCELLED"
    touch(e)
    return success(ser(e))


# ===========================================================================
# Sessions
# ===========================================================================
@app.route("/styling/engagements/<eid>/sessions", methods=["POST"])
def schedule_session(eid):
    role, uid = require({"Client"})
    e = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if e["client_id"] != uid:
        forbid()

    body = body_json()
    session_type = enum_field(body, "session_type",
                              {"CLOSET_AUDIT", "SHOPPING", "VIRTUAL", "EVENT"})
    modality = body.get("modality", "IN_PERSON")
    if modality is None:
        modality = "IN_PERSON"
    if modality not in ("IN_PERSON", "VIRTUAL"):
        raise ApiError("ERR_VALIDATION", "invalid modality")
    exp_ver = body.get("expected_engagement_version")
    if isinstance(exp_ver, bool) or not isinstance(exp_ver, int):
        raise ApiError("ERR_VALIDATION", "expected_engagement_version required")
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str) \
            or not start_raw or not end_raw:
        raise ApiError("ERR_VALIDATION", "scheduled_start/scheduled_end required")
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE")

    if e["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    est_blocks = blocks_from_minutes(window_minutes(start_dt, end_dt))

    # Business checks in the pinned order for this endpoint.
    check_stylist_overlap(e, start_dt, end_dt)
    check_client_buffer(e, start_dt, end_dt, modality)

    if e["mode"] == "PACKAGE" and e["hours_available_blocks"] < est_blocks:
        raise ApiError("ERR_INSUFFICIENT_PACKAGE_HOURS")

    # OCC last of all.
    if exp_ver != e["version"]:
        raise ApiError("ERR_STALE_ENGAGEMENT_VERSION")

    charge = est_blocks * e["block_rate_cents"]
    s = add_common({
        "engagement_id": eid,
        "session_type": session_type,
        "modality": modality,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "estimated_blocks": est_blocks,
        "actual_minutes": None,
        "charge_cents": charge,
        "charge_variant": "PROVISIONAL",
        "status": "SCHEDULED",
        "_start": start_dt,
        "_end": end_dt,
    })
    sessions[s["id"]] = s

    if e["mode"] == "PACKAGE":
        e["hours_reserved_blocks"] += est_blocks
        e["hours_available_blocks"] -= est_blocks
        touch(e)

    return success(ser(s), status=201)


@app.route("/styling/sessions/<sid>", methods=["GET"])
def get_session(sid):
    require({"PlatformAdmin", "Stylist", "Client"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    return success(ser(s))


@app.route("/styling/engagements/<eid>/sessions", methods=["GET"])
def list_sessions(eid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    items = [s for s in sessions.values() if s["engagement_id"] == eid]
    return list_response(items)


def _session_owner_check(session, role, uid):
    eng = engagements[session["engagement_id"]]
    if role == "Client" and eng["client_id"] != uid:
        forbid()
    if role == "Stylist" and eng["stylist_id"] != uid:
        forbid()


@app.route("/styling/sessions/<sid>/confirm", methods=["POST"])
def confirm_session(sid):
    role, uid = require({"Stylist"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    eng = engagements[s["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    if s["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_SESSION_STATE")
    has_completed = any(
        a["client_id"] == eng["client_id"] and a["status"] == "COMPLETED"
        for a in assessments.values()
    )
    if not has_completed:
        raise ApiError("ERR_ASSESSMENT_NOT_COMPLETED")
    s["status"] = "CONFIRMED"
    touch(s)
    return success(ser(s))


@app.route("/styling/sessions/<sid>/reschedule", methods=["POST"])
def reschedule_session(sid):
    role, uid = require({"Client", "Stylist"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    _session_owner_check(s, role, uid)
    eng = engagements[s["engagement_id"]]

    body = body_json()
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    if not isinstance(start_raw, str) or not isinstance(end_raw, str) \
            or not start_raw or not end_raw:
        raise ApiError("ERR_VALIDATION", "scheduled_start/scheduled_end required")
    try:
        start_dt = parse_dt(start_raw)
        end_dt = parse_dt(end_raw)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid datetime")
    if not (end_dt > start_dt):
        raise ApiError("ERR_INVALID_TIME_RANGE")

    if s["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_SESSION_STATE")

    new_est = blocks_from_minutes(window_minutes(start_dt, end_dt))

    check_stylist_overlap(eng, start_dt, end_dt, exclude_id=sid)
    check_client_buffer(eng, start_dt, end_dt, s["modality"], exclude_id=sid)

    old_est = s["estimated_blocks"]
    if eng["mode"] == "PACKAGE":
        # available after re-reservation = available + old - new
        if eng["hours_available_blocks"] + old_est - new_est < 0:
            raise ApiError("ERR_INSUFFICIENT_PACKAGE_HOURS")

    s["scheduled_start"] = start_raw
    s["scheduled_end"] = end_raw
    s["_start"] = start_dt
    s["_end"] = end_dt
    s["estimated_blocks"] = new_est
    s["charge_cents"] = new_est * eng["block_rate_cents"]
    s["charge_variant"] = "PROVISIONAL"
    s["status"] = "SCHEDULED"
    touch(s)

    if eng["mode"] == "PACKAGE" and new_est != old_est:
        eng["hours_reserved_blocks"] += (new_est - old_est)
        eng["hours_available_blocks"] = (
            eng["package_blocks"] - eng["hours_reserved_blocks"]
            - eng["hours_consumed_blocks"]
        )
        touch(eng)

    return success(ser(s))


@app.route("/styling/sessions/<sid>/complete", methods=["POST"])
def complete_session(sid):
    role, uid = require({"Stylist"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    eng = engagements[s["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    if s["status"] != "CONFIRMED":
        raise ApiError("ERR_INVALID_SESSION_STATE")
    body = body_json()
    actual = body.get("actual_minutes")
    if isinstance(actual, bool) or not isinstance(actual, int) or actual <= 0:
        raise ApiError("ERR_INVALID_SESSION_STATE")

    billable = blocks_from_minutes(actual)
    s["actual_minutes"] = actual
    s["charge_cents"] = billable * eng["block_rate_cents"]
    s["charge_variant"] = "FINAL"
    s["status"] = "COMPLETED"
    touch(s)

    if eng["mode"] == "PACKAGE":
        eng["hours_reserved_blocks"] -= s["estimated_blocks"]
        eng["hours_consumed_blocks"] += billable
        eng["hours_available_blocks"] = (
            eng["package_blocks"] - eng["hours_reserved_blocks"]
            - eng["hours_consumed_blocks"]
        )
        touch(eng)

        remaining = any(
            o["engagement_id"] == eng["id"]
            and o["status"] in ("SCHEDULED", "CONFIRMED")
            for o in sessions.values()
        )
        if eng["status"] == "ACTIVE" and eng["hours_available_blocks"] == 0 \
                and not remaining:
            eng["status"] = "FULFILLED"
            touch(eng)
            lb = add_common({
                "engagement_id": eng["id"],
                "title": "Final Lookbook",
                "outfits": [],
                "outfit_count": 0,
                "revision_round": 0,
                "status": "DRAFT",
            })
            lookbooks[lb["id"]] = lb

    return success(ser(s))


@app.route("/styling/sessions/<sid>/cancel", methods=["POST"])
def cancel_session(sid):
    role, uid = require({"Client", "Stylist"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    _session_owner_check(s, role, uid)
    eng = engagements[s["engagement_id"]]
    if s["status"] not in ("SCHEDULED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_SESSION_STATE")
    s["status"] = "CANCELLED"
    touch(s)
    if eng["mode"] == "PACKAGE":
        eng["hours_reserved_blocks"] -= s["estimated_blocks"]
        eng["hours_available_blocks"] += s["estimated_blocks"]
        touch(eng)
    return success(ser(s))


# ===========================================================================
# Purchases
# ===========================================================================
@app.route("/styling/sessions/<sid>/items", methods=["POST"])
def create_item(sid):
    role, uid = require({"Stylist"})
    s = get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    eng = engagements[s["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    body = body_json()
    description = req_str(body, "description")
    retail = req_int(body, "retail_cost_cents", positive=True)
    if s["status"] != "CONFIRMED" or s["session_type"] != "SHOPPING":
        raise ApiError("ERR_INVALID_SESSION_STATE")

    stylist = stylists[eng["stylist_id"]]
    mp = markup_pct_for(retail)
    marked = rhu(Decimal(retail) * (Decimal(1) + mp))
    commission = rhu((Decimal(marked) - Decimal(retail)) * Decimal(str(stylist["commission_pct"])))

    item = add_common({
        "session_id": sid,
        "description": description,
        "retail_cost_cents": retail,
        "markup_pct": float(mp),
        "marked_up_price_cents": marked,
        "commission_cents": commission,
        "status": "PURCHASED",
    })
    purchase_items[item["id"]] = item

    eng["retail_spend_cents"] += marked
    touch(eng)
    stylist["earned_commission_cents"] += commission
    touch(stylist)

    return success(ser(item), status=201)


@app.route("/styling/sessions/<sid>/items", methods=["GET"])
def list_items(sid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(sessions, sid, "ERR_SESSION_NOT_FOUND")
    items = [i for i in purchase_items.values() if i["session_id"] == sid]
    return list_response(items)


@app.route("/styling/purchase-items/<iid>/return", methods=["POST"])
def return_item(iid):
    role, uid = require({"Stylist"})
    item = get_or_404(purchase_items, iid, "ERR_PURCHASE_ITEM_NOT_FOUND")
    s = sessions[item["session_id"]]
    eng = engagements[s["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    if item["status"] != "PURCHASED":
        raise ApiError("ERR_INVALID_PURCHASE_ITEM_STATE")
    item["status"] = "RETURNED"
    touch(item)
    eng["retail_spend_cents"] -= item["marked_up_price_cents"]
    touch(eng)
    stylist = stylists[eng["stylist_id"]]
    stylist["earned_commission_cents"] -= item["commission_cents"]
    touch(stylist)
    return success(ser(item))


# ===========================================================================
# Lookbooks
# ===========================================================================
@app.route("/styling/engagements/<eid>/lookbooks", methods=["POST"])
def create_lookbook(eid):
    role, uid = require({"Stylist"})
    eng = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["stylist_id"] != uid:
        forbid()
    body = body_json()
    title = req_str(body, "title")
    if eng["status"] not in ("ACTIVE", "FULFILLED"):
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")
    lb = add_common({
        "engagement_id": eid,
        "title": title,
        "outfits": [],
        "outfit_count": 0,
        "revision_round": 0,
        "status": "DRAFT",
    })
    lookbooks[lb["id"]] = lb
    return success(ser(lb), status=201)


@app.route("/styling/lookbooks/<lid>", methods=["GET"])
def get_lookbook(lid):
    require({"PlatformAdmin", "Stylist", "Client"})
    lb = get_or_404(lookbooks, lid, "ERR_LOOKBOOK_NOT_FOUND")
    return success(ser(lb))


@app.route("/styling/engagements/<eid>/lookbooks", methods=["GET"])
def list_lookbooks(eid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    items = [l for l in lookbooks.values() if l["engagement_id"] == eid]
    return list_response(items)


@app.route("/styling/lookbooks/<lid>/outfits", methods=["POST"])
def add_outfit(lid):
    role, uid = require({"Stylist"})
    lb = get_or_404(lookbooks, lid, "ERR_LOOKBOOK_NOT_FOUND")
    eng = engagements[lb["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    body = body_json()
    name = req_str(body, "name")
    item_refs = body.get("item_refs")
    if item_refs is not None and not isinstance(item_refs, list):
        raise ApiError("ERR_VALIDATION", "invalid item_refs")
    if lb["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LOOKBOOK_STATE")
    lb["outfits"].append({"name": name, "item_refs": item_refs or []})
    lb["outfit_count"] += 1
    touch(lb)
    return success(ser(lb), status=201)


@app.route("/styling/lookbooks/<lid>/deliver", methods=["POST"])
def deliver_lookbook(lid):
    role, uid = require({"Stylist"})
    lb = get_or_404(lookbooks, lid, "ERR_LOOKBOOK_NOT_FOUND")
    eng = engagements[lb["engagement_id"]]
    if eng["stylist_id"] != uid:
        forbid()
    if lb["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_LOOKBOOK_STATE")
    if eng["status"] not in ("ACTIVE", "FULFILLED"):
        raise ApiError("ERR_ENGAGEMENT_NOT_ACTIVE")
    if lb["outfit_count"] < 1:
        raise ApiError("ERR_LOOKBOOK_EMPTY")
    lb["status"] = "DELIVERED"
    touch(lb)
    return success(ser(lb))


@app.route("/styling/lookbooks/<lid>/accept", methods=["POST"])
def accept_lookbook(lid):
    role, uid = require({"Client"})
    lb = get_or_404(lookbooks, lid, "ERR_LOOKBOOK_NOT_FOUND")
    eng = engagements[lb["engagement_id"]]
    if eng["client_id"] != uid:
        forbid()
    if lb["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_LOOKBOOK_STATE")
    lb["status"] = "ACCEPTED"
    touch(lb)
    return success(ser(lb))


@app.route("/styling/lookbooks/<lid>/request-revision", methods=["POST"])
def request_revision(lid):
    role, uid = require({"Client"})
    lb = get_or_404(lookbooks, lid, "ERR_LOOKBOOK_NOT_FOUND")
    eng = engagements[lb["engagement_id"]]
    if eng["client_id"] != uid:
        forbid()
    if lb["status"] != "DELIVERED":
        raise ApiError("ERR_INVALID_LOOKBOOK_STATE")
    lb["status"] = "DRAFT"
    lb["revision_round"] += 1
    touch(lb)
    return success(ser(lb))


# ===========================================================================
# Subscriptions
# ===========================================================================
@app.route("/styling/clients/<cid>/subscriptions", methods=["POST"])
def create_subscription(cid):
    role, uid = require({"Client"})
    get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    if cid != uid:
        forbid()
    body = body_json()
    tier = enum_field(body, "tier", {"SILVER", "GOLD"})
    monthly_fee = req_int(body, "monthly_fee_cents", positive=True)
    sub = add_common({
        "client_id": cid,
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "refresh_credits_total": 0,
        "refresh_credits_remaining": 0,
        "current_period_start": None,
        "current_period_end": None,
        "status": "PENDING",
    })
    subscriptions[sub["id"]] = sub
    return success(ser(sub), status=201)


@app.route("/styling/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    require({"PlatformAdmin", "Stylist", "Client"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    return success(ser(sub))


@app.route("/styling/clients/<cid>/subscriptions", methods=["GET"])
def list_subscriptions(cid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    items = [s for s in subscriptions.values() if s["client_id"] == cid]
    return list_response(items)


@app.route("/styling/subscriptions/<sid>/activate", methods=["POST"])
def activate_subscription(sid):
    require({"PlatformAdmin"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if sub["status"] != "PENDING":
        raise ApiError("ERR_INVALID_SUBSCRIPTION_STATE")
    client = clients[sub["client_id"]]
    if client["wallet_credit_cents"] < sub["monthly_fee_cents"]:
        raise ApiError("ERR_INSUFFICIENT_WALLET")
    credits = 4 if sub["tier"] == "GOLD" else 2
    sub["status"] = "ACTIVE"
    sub["refresh_credits_total"] = credits
    sub["refresh_credits_remaining"] = credits
    sub["current_period_start"] = fmt_dt(CLOCK["now"])
    sub["current_period_end"] = fmt_dt(CLOCK["now"] + timedelta(days=90))
    touch(sub)
    client["wallet_credit_cents"] -= sub["monthly_fee_cents"]
    touch(client)
    return success(ser(sub))


@app.route("/styling/subscriptions/<sid>/redeem-refresh", methods=["POST"])
def redeem_refresh(sid):
    role, uid = require({"Client"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if sub["client_id"] != uid:
        forbid()
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_SUBSCRIPTION_STATE")
    if sub["refresh_credits_remaining"] < 1:
        raise ApiError("ERR_NO_REFRESH_CREDITS")
    sub["refresh_credits_remaining"] -= 1
    touch(sub)
    return success(ser(sub))


@app.route("/styling/subscriptions/<sid>/cancel", methods=["POST"])
def cancel_subscription(sid):
    role, uid = require({"Client"})
    sub = get_or_404(subscriptions, sid, "ERR_SUBSCRIPTION_NOT_FOUND")
    if sub["client_id"] != uid:
        forbid()
    if sub["status"] not in ("PENDING", "ACTIVE"):
        raise ApiError("ERR_INVALID_SUBSCRIPTION_STATE")
    sub["status"] = "CANCELLED"
    touch(sub)
    return success(ser(sub))


# ===========================================================================
# Referrals
# ===========================================================================
@app.route("/styling/referrals", methods=["POST"])
def create_referral():
    role, uid = require({"Client"})
    body = body_json()
    referrer_id = body.get("referrer_client_id")
    if not isinstance(referrer_id, str) or referrer_id == "":
        raise ApiError("ERR_VALIDATION", "missing referrer_client_id")
    if referrer_id not in clients:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    if referrer_id != uid:
        forbid()
    referee_email = req_str(body, "referee_email")
    referrer = clients[referrer_id]
    if referee_email == referrer["email"]:
        raise ApiError("ERR_SELF_REFERRAL")
    expires_dt = CLOCK["now"] + timedelta(days=90)
    ref = add_common({
        "referrer_client_id": referrer_id,
        "referee_email": referee_email,
        "referee_client_id": None,
        "qualifying_invoice_id": None,
        "estimated_credit_cents": 5000,
        "realized_credit_cents": 0,
        "expires_at": fmt_dt(expires_dt),
        "status": "PENDING",
        "_expires_dt": expires_dt,
    })
    referrals[ref["id"]] = ref
    return success(ser(ref), status=201)


@app.route("/styling/referrals/<rid>", methods=["GET"])
def get_referral(rid):
    require({"PlatformAdmin", "Stylist", "Client"})
    ref = get_or_404(referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    return success(ser(ref))


@app.route("/styling/referrals", methods=["GET"])
def list_referrals():
    require({"PlatformAdmin", "Stylist", "Client"})
    items = list(referrals.values())
    return list_response(items, extra_filters={
        "referrer_client_id": request.args.get("referrer_client_id"),
        "referee_client_id": request.args.get("referee_client_id"),
        "qualifying_invoice_id": request.args.get("qualifying_invoice_id"),
    })


@app.route("/styling/referrals/<rid>/signup", methods=["POST"])
def signup_referral(rid):
    require({"PlatformAdmin"})
    ref = get_or_404(referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    body = body_json()
    referee_id = body.get("referee_client_id")
    if not isinstance(referee_id, str) or referee_id == "":
        raise ApiError("ERR_VALIDATION", "missing referee_client_id")
    if referee_id not in clients:
        raise ApiError("ERR_CLIENT_NOT_FOUND")
    if ref["status"] != "PENDING":
        raise ApiError("ERR_INVALID_REFERRAL_STATE")
    if CLOCK["now"] > ref["_expires_dt"]:
        raise ApiError("ERR_REFERRAL_EXPIRED")
    if referee_id == ref["referrer_client_id"]:
        raise ApiError("ERR_SELF_REFERRAL")
    ref["status"] = "SIGNED_UP"
    ref["referee_client_id"] = referee_id
    touch(ref)
    return success(ser(ref))


# ===========================================================================
# Invoices
# ===========================================================================
@app.route("/styling/engagements/<eid>/invoices", methods=["POST"])
def issue_invoice(eid):
    require({"PlatformAdmin"})
    eng = get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    if eng["status"] not in ("ACTIVE", "FULFILLED"):
        raise ApiError("ERR_INVALID_ENGAGEMENT_STATE")

    line_items = []
    eng_sessions = [s for s in sessions.values()
                    if s["engagement_id"] == eid and s["status"] == "COMPLETED"]
    eng_sessions.sort(key=lambda x: x["_seq"])
    for s in eng_sessions:
        line_items.append({"type": "session", "ref_id": s["id"],
                           "amount_cents": s["charge_cents"]})

    eng_items = []
    for it in purchase_items.values():
        if it["status"] != "PURCHASED":
            continue
        s = sessions.get(it["session_id"])
        if s and s["engagement_id"] == eid:
            eng_items.append(it)
    eng_items.sort(key=lambda x: x["_seq"])
    for it in eng_items:
        line_items.append({"type": "item", "ref_id": it["id"],
                           "amount_cents": it["marked_up_price_cents"]})

    lines = [li["amount_cents"] for li in line_items]
    subtotal = sum(lines)
    styling_fee = sum(rhu(Decimal(line) * Decimal("0.10")) for line in lines)

    if subtotal >= 100000:
        vpct = Decimal("0.10")
    elif subtotal >= 50000:
        vpct = Decimal("0.05")
    else:
        vpct = Decimal("0.00")
    volume_discount = rhu(Decimal(subtotal) * vpct)

    pre_credit = subtotal + styling_fee - volume_discount
    client = clients[eng["client_id"]]
    wallet_applied = min(client["wallet_credit_cents"], pre_credit)
    if wallet_applied < 0:
        wallet_applied = 0
    total = pre_credit - wallet_applied

    inv = add_common({
        "engagement_id": eid,
        "line_items": line_items,
        "subtotal_cents": subtotal,
        "styling_fee_cents": styling_fee,
        "volume_discount_cents": volume_discount,
        "wallet_credit_applied_cents": wallet_applied,
        "total_cents": total,
        "paid_at": None,
        "status": "ISSUED",
    })
    invoices[inv["id"]] = inv

    if wallet_applied:
        client["wallet_credit_cents"] -= wallet_applied
        touch(client)

    return success(ser(inv), status=201)


@app.route("/styling/invoices/<iid>", methods=["GET"])
def get_invoice(iid):
    require({"PlatformAdmin", "Stylist", "Client"})
    inv = get_or_404(invoices, iid, "ERR_INVOICE_NOT_FOUND")
    return success(ser(inv))


@app.route("/styling/engagements/<eid>/invoices", methods=["GET"])
def list_invoices(eid):
    require({"PlatformAdmin", "Stylist", "Client"})
    get_or_404(engagements, eid, "ERR_ENGAGEMENT_NOT_FOUND")
    items = [i for i in invoices.values() if i["engagement_id"] == eid]
    return list_response(items)


@app.route("/styling/invoices/<iid>/pay", methods=["POST"])
def pay_invoice(iid):
    role, uid = require({"Client", "PlatformAdmin"})
    inv = get_or_404(invoices, iid, "ERR_INVOICE_NOT_FOUND")
    eng = engagements[inv["engagement_id"]]
    if role == "Client" and eng["client_id"] != uid:
        forbid()
    if inv["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_INVOICE_STATE")
    inv["status"] = "PAID"
    inv["paid_at"] = fmt_dt(CLOCK["now"])
    touch(inv)

    client = clients[eng["client_id"]]
    if not client["has_paid_invoice"]:
        client["has_paid_invoice"] = True
        touch(client)
        # Referral qualification cascade.
        for ref in referrals.values():
            if ref["status"] == "SIGNED_UP" \
                    and ref["referee_client_id"] == client["id"]:
                realized = min(10000, rhu(Decimal("0.10") * Decimal(inv["total_cents"])))
                ref["status"] = "CREDITED"
                ref["qualifying_invoice_id"] = inv["id"]
                ref["realized_credit_cents"] = realized
                touch(ref)
                referrer = clients.get(ref["referrer_client_id"])
                if referrer is not None:
                    referrer["wallet_credit_cents"] += realized
                    touch(referrer)

    return success(ser(inv))


# ===========================================================================
# Wallet adjustments / clock
# ===========================================================================
@app.route("/styling/clients/<cid>/wallet/adjustments", methods=["POST"])
def adjust_wallet(cid):
    require({"PlatformAdmin"})
    client = get_or_404(clients, cid, "ERR_CLIENT_NOT_FOUND")
    body = body_json()
    amount = body.get("amount_cents")
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise ApiError("ERR_VALIDATION", "invalid amount_cents")
    new_balance = client["wallet_credit_cents"] + amount
    if new_balance < 0:
        raise ApiError("ERR_VALIDATION", "wallet balance cannot be negative")
    client["wallet_credit_cents"] = new_balance
    touch(client)
    return success(ser(client))


@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require({"PlatformAdmin"}, exempt=True)
    body = body_json()
    to_iso = body.get("to_iso8601")
    try:
        dt = parse_dt(to_iso)
    except ValueError:
        raise ApiError("ERR_VALIDATION", "invalid to_iso8601")
    CLOCK["now"] = dt
    return success({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
