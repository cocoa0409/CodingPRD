"""Memory Digitization API — Python + Flask, in-memory store.

Every behavior traces to a verbatim sentence in workspace/PRD.md. Storage is
in-memory only (Python dicts keyed by id); the store starts empty on every boot
and nothing is seeded at startup.
"""
import os
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# System constants (SCAFFOLD §system_constants, §1.3 calculations)
# ---------------------------------------------------------------------------
MAX_QC_ATTEMPTS = 3
RETENTION_DAYS = 30
DOWNLOAD_EXPIRY_DAYS = 30
MAX_DOWNLOADS_PER_ARTIFACT = 3
CLAIM_WINDOW_DAYS = 90

RATE = {"TAPE": 1200, "FILM": 1500, "PHOTO": 50, "AUDIO": 1000}
BASE_VALUE = {"TAPE": 4000, "FILM": 6000, "PHOTO": 200, "AUDIO": 3000}
PROTECTION_CAP = 10000
NO_PROTECTION_CAP = 1000

RUSH_PCT = Decimal("0.30")
PROTECTION_BASE = 1500
PROTECTION_PCT = Decimal("0.02")
VOL_TIER_1_MIN, VOL_TIER_1_PCT = 20, Decimal("0.10")
VOL_TIER_2_MIN, VOL_TIER_2_PCT = 40, Decimal("0.20")
SAVE5_CODE = "SAVE5"
PROMO_BAND_HI_MIN, PROMO_BAND_HI_AMT = 13000, 1000
PROMO_BAND_LO_MIN, PROMO_BAND_LO_AMT = 10000, 500

W_APPROVED, W_PENDING, SCORE_CAP = 20, 5, 100

ROLES = {"Customer", "IntakeTech", "LabTech", "ClaimsAdjuster", "Admin"}

PLAN_TIERS = {"STANDARD_KIT", "FAMILY_KIT", "CLOSET_KIT"}
TURNAROUNDS = {"STANDARD", "RUSH"}
OUTPUT_OPTIONS = {"CLOUD", "USB", "DVD"}
MEDIA_TYPES = {"TAPE", "FILM", "PHOTO", "AUDIO"}
MACHINE_KINDS = {"TAPE_DECK", "FILM_SCANNER", "PHOTO_SCANNER", "AUDIO_DECK"}
CLAIM_TYPES = {"LOST", "DAMAGED"}

# ---------------------------------------------------------------------------
# Logical clock (PRD §2.6) — startup default 2026-03-01T00:00:00Z
# ---------------------------------------------------------------------------
CLOCK = {"now": datetime(2026, 3, 1, 0, 0, 0, tzinfo=timezone.utc)}


def now():
    return CLOCK["now"]


# ---------------------------------------------------------------------------
# In-memory data store
# ---------------------------------------------------------------------------
customers = {}
orders = {}
machines = {}
bins = {}
batches = {}
media_items = {}
qc_reviews = {}
artifacts = {}
download_events = {}
claims = {}

_seq_counter = {"n": 0}


def next_seq():
    _seq_counter["n"] += 1
    return _seq_counter["n"]


def new_id():
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Datetime helpers
# ---------------------------------------------------------------------------
def parse_dt(s):
    if not isinstance(s, str) or not s:
        raise ValueError("bad datetime")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (dt.microsecond // 1000)) + "Z"


# ---------------------------------------------------------------------------
# Entity lifecycle helpers (PRD §2.4)
# ---------------------------------------------------------------------------
def make(store, fields, common=True):
    t = now()
    e = {"id": new_id(), "_seq": next_seq(), "_created_dt": t}
    if common:
        e["_updated_dt"] = t
        e["version"] = 1
    e.update(fields)
    store[e["id"]] = e
    return e


def touch(e):
    e["version"] += 1
    e["_updated_dt"] = now()


# ---------------------------------------------------------------------------
# Response envelope (SCAFFOLD §1.0, PRD §2.2)
# ---------------------------------------------------------------------------
def meta_base():
    return {
        "api_request_id": "req_" + uuid.uuid4().hex[:20],
        "api_request_timestamp": fmt_dt(now()),
    }


def ok(data, status=200, response_type="object", pagination=None):
    meta = meta_base()
    if pagination is not None:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), status


def make_error_body(error_id, message):
    return {
        "meta": meta_base(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(make_error_body(err.error_id, err.message)), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    return jsonify(make_error_body("ERR_NOT_FOUND", "Resource not found")), 404


@app.errorhandler(405)
def handle_405(_e):
    return jsonify(make_error_body("ERR_NOT_FOUND", "Method not allowed")), 404


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return jsonify(make_error_body("ERR_VALIDATION", "Unexpected error: %s" % err)), 500


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD §2.1, §2.9)
# ---------------------------------------------------------------------------
def authenticate():
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "Missing or invalid auth headers")
    g.user_id = user_id
    g.role = role


def authorize(allowed_roles):
    if g.role == "Admin":
        return
    if g.role not in allowed_roles:
        raise ApiError("ERR_UNAUTHORIZED", 403, "Role not permitted for this endpoint")


def guard(allowed_roles):
    authenticate()
    authorize(allowed_roles)


def require_owner_order(order):
    """Customer acting on an order/its artifacts must own it (PRD §2.1)."""
    if g.role == "Customer" and order["customer_id"] != g.user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "Customer does not own this order")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def body_json():
    return request.get_json(silent=True) or {}


def err_validation(msg="Invalid or missing field"):
    raise ApiError("ERR_VALIDATION", 400, msg)


def req_str(body, key):
    v = body.get(key)
    if not isinstance(v, str) or v == "":
        err_validation("Missing or invalid field: %s" % key)
    return v


def opt_bool(body, key, default=False):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if not isinstance(v, bool):
        err_validation("Field %s must be a boolean" % key)
    return v


def opt_nonneg_int(body, key, default=0):
    if key not in body or body.get(key) is None:
        return default
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int) or v < 0:
        err_validation("Field %s must be a non-negative integer" % key)
    return v


def opt_int(body, key):
    if key not in body or body.get(key) is None:
        return None
    v = body.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        err_validation("Field %s must be an integer" % key)
    return v


def enum_field(body, key, choices, required=True):
    v = body.get(key)
    if v is None:
        if required:
            err_validation("Missing field: %s" % key)
        return None
    if v not in choices:
        err_validation("Invalid value for %s" % key)
    return v


# ---------------------------------------------------------------------------
# Pagination (PRD §2.3)
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            err_validation("limit must be an integer")
        if limit < 1 or limit > 100:
            err_validation("limit out of range")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            err_validation("offset must be an integer")
        if offset < 0:
            err_validation("offset must be >= 0")
    return limit, offset


def paginate(rows):
    """rows: list of entity dicts. Sorts by created_at asc (PRD §2.3)."""
    limit, offset = parse_pagination()
    rows = sorted(rows, key=lambda e: (e["_created_dt"], e["_seq"]))
    total = len(rows)
    page = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + len(page)) < total,
    }
    return page, pagination


def list_response(rows, serializer):
    page, pagination = paginate(rows)
    return ok([serializer(e) for e in page], 200, "array", pagination)


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_common(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["_created_dt"]),
        "updated_at": fmt_dt(e["_updated_dt"]),
        "version": e["version"],
    }


def ser_customer(e):
    d = ser_common(e)
    d.update(
        email=e["email"],
        full_name=e["full_name"],
        state_code=e["state_code"],
        wallet_credit_cents=e["wallet_credit_cents"],
        risk_score=e["risk_score"],
        approved_claim_count=e["approved_claim_count"],
        pending_claim_count=e["pending_claim_count"],
    )
    return d


def ser_order(e):
    d = ser_common(e)
    d.update(
        customer_id=e["customer_id"],
        plan_tier=e["plan_tier"],
        turnaround=e["turnaround"],
        output_option=e["output_option"],
        lost_damage_protection=e["lost_damage_protection"],
        is_gift=e["is_gift"],
        gift_recipient_email=e["gift_recipient_email"],
        promo_code=e["promo_code"],
        declared_tape_count=e["declared_tape_count"],
        declared_film_count=e["declared_film_count"],
        declared_photo_count=e["declared_photo_count"],
        declared_audio_count=e["declared_audio_count"],
        fulfillment_status=e["fulfillment_status"],
        payment_status=e["payment_status"],
        estimate_total_cents=e["estimate_total_cents"],
        final_total_cents=e["final_total_cents"],
        captured_total_cents=e["captured_total_cents"],
        refunded_total_cents=e["refunded_total_cents"],
        received_item_count=e["received_item_count"],
        written_off_count=e["written_off_count"],
    )
    return d


def ser_machine(e):
    d = ser_common(e)
    d.update(name=e["name"], kind=e["kind"], capacity=e["capacity"])
    return d


def ser_bin(e):
    d = ser_common(e)
    d.update(label=e["label"], capacity=e["capacity"])
    return d


def ser_batch(e):
    d = ser_common(e)
    d.update(
        machine_id=e["machine_id"],
        scheduled_start=e["scheduled_start"],
        scheduled_end=e["scheduled_end"],
        capacity=e["capacity"],
        status=e["status"],
        loaded_count=e["loaded_count"],
    )
    return d


def ser_media(e):
    d = ser_common(e)
    d.update(
        order_id=e["order_id"],
        batch_id=e["batch_id"],
        bin_id=e["bin_id"],
        media_type=e["media_type"],
        barcode=e["barcode"],
        status=e["status"],
        qc_attempts=e["qc_attempts"],
        digitized_minutes=e["digitized_minutes"],
        page_count=e["page_count"],
        stored_at=fmt_dt(e["_stored_dt"]),
        retention_until=fmt_dt(e["_retention_dt"]),
    )
    return d


def ser_qc(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["_created_dt"]),
        "media_item_id": e["media_item_id"],
        "decision": e["decision"],
        "attempt_number": e["attempt_number"],
        "notes": e["notes"],
    }


def ser_artifact(e):
    d = ser_common(e)
    d.update(
        order_id=e["order_id"],
        output_type=e["output_type"],
        status=e["status"],
        download_token=e["download_token"],
        download_count=e["download_count"],
        expires_at=fmt_dt(e["_expires_dt"]),
        item_count_snapshot=e["item_count_snapshot"],
    )
    return d


def ser_download(e):
    return {
        "id": e["id"],
        "created_at": fmt_dt(e["_created_dt"]),
        "output_artifact_id": e["output_artifact_id"],
        "sequence_number": e["sequence_number"],
        "downloaded_at": fmt_dt(e["_downloaded_dt"]),
    }


def ser_claim(e):
    d = ser_common(e)
    d.update(
        order_id=e["order_id"],
        media_item_id=e["media_item_id"],
        claim_type=e["claim_type"],
        declared_value_cents=e["declared_value_cents"],
        status=e["status"],
        payout_cents=e["payout_cents"],
    )
    return d


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(store, _id):
    e = store.get(_id)
    if e is None:
        raise ApiError("ERR_NOT_FOUND", 404, "Resource not found")
    return e


def fk_or_404(store, _id):
    if _id not in store:
        raise ApiError("ERR_NOT_FOUND", 404, "Referenced resource not found")
    return store[_id]


# ---------------------------------------------------------------------------
# Calculations (SCAFFOLD §1.3, PRD §3.1, §3.7)
# ---------------------------------------------------------------------------
def round_half_up(dec):
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def order_subtotal(tape, film, photo, audio):
    raw = RATE["TAPE"] * tape + RATE["FILM"] * film + RATE["PHOTO"] * photo + RATE["AUDIO"] * audio
    count = tape + film + photo + audio
    if count >= VOL_TIER_2_MIN:
        pct = VOL_TIER_2_PCT
    elif count >= VOL_TIER_1_MIN:
        pct = VOL_TIER_1_PCT
    else:
        pct = Decimal("0")
    vol_discount = round_half_up(Decimal(raw) * pct)
    return raw - vol_discount


def order_total(tape, film, photo, audio, turnaround, protection, promo_code):
    sub = order_subtotal(tape, film, photo, audio)
    rush = round_half_up(Decimal(sub) * RUSH_PCT) if turnaround == "RUSH" else 0
    prot = (PROTECTION_BASE + round_half_up(Decimal(sub) * PROTECTION_PCT)) if protection else 0
    pre = sub + rush + prot
    if promo_code == SAVE5_CODE:
        if pre >= PROMO_BAND_HI_MIN:
            promo = PROMO_BAND_HI_AMT
        elif pre >= PROMO_BAND_LO_MIN:
            promo = PROMO_BAND_LO_AMT
        else:
            promo = 0
    else:
        promo = 0
    return pre - promo


def estimate_total_for(order):
    return order_total(
        order["declared_tape_count"], order["declared_film_count"],
        order["declared_photo_count"], order["declared_audio_count"],
        order["turnaround"], order["lost_damage_protection"], order["promo_code"],
    )


def final_total_for(order):
    counts = {"TAPE": 0, "FILM": 0, "PHOTO": 0, "AUDIO": 0}
    for m in media_items.values():
        if m["order_id"] == order["id"] and m["status"] != "WRITTEN_OFF":
            counts[m["media_type"]] += 1
    return order_total(
        counts["TAPE"], counts["FILM"], counts["PHOTO"], counts["AUDIO"],
        order["turnaround"], order["lost_damage_protection"], order["promo_code"],
    )


def damage_payout(media_type, declared_value_cents, protection):
    base = BASE_VALUE[media_type]
    declared = declared_value_cents if declared_value_cents is not None else base
    if protection:
        return min(declared, PROTECTION_CAP)
    return min(base, NO_PROTECTION_CAP)


def recompute_customer(cust):
    approved = 0
    pending = 0
    for c in claims.values():
        o = orders.get(c["order_id"])
        if o is None or o["customer_id"] != cust["id"]:
            continue
        if c["status"] == "APPROVED":
            approved += 1
        elif c["status"] in ("SUBMITTED", "UNDER_REVIEW"):
            pending += 1
    cust["approved_claim_count"] = approved
    cust["pending_claim_count"] = pending
    cust["risk_score"] = min(SCORE_CAP, W_APPROVED * approved + W_PENDING * pending)


# ---------------------------------------------------------------------------
# Bubble-up / cascade helpers (PRD §3.4, §3.5, §3.6)
# ---------------------------------------------------------------------------
def maybe_ready(order):
    if order["fulfillment_status"] != "PROCESSING":
        return
    items = [m for m in media_items.values() if m["order_id"] == order["id"]]
    if not items:
        return
    if all(m["status"] in ("OUTPUT_READY", "WRITTEN_OFF") for m in items) and \
            any(m["status"] == "OUTPUT_READY" for m in items):
        order["fulfillment_status"] = "READY"
        order["_ready_dt"] = now()
        touch(order)


def maybe_complete_batch(batch):
    if batch["status"] != "RUNNING":
        return
    loaded = [m for m in media_items.values() if m["batch_id"] == batch["id"]]
    if loaded and all(m["status"] not in ("LOGGED", "PREPPED", "SCANNING") for m in loaded):
        batch["status"] = "COMPLETED"
        touch(batch)


def bin_would_exceed(bin_row, new_start, new_end):
    windows = [
        (m["_stored_dt"], m["_retention_dt"])
        for m in media_items.values() if m["bin_id"] == bin_row["id"]
    ]
    windows.append((new_start, new_end))
    events = []
    for s, e in windows:
        events.append((s, 1))   # start
        events.append((e, 0))   # end (processed before starts at equal instant)
    events.sort(key=lambda x: (x[0], x[1]))
    cur = 0
    mx = 0
    for _t, typ in events:
        if typ == 1:
            cur += 1
            mx = max(mx, cur)
        else:
            cur -= 1
    return mx > bin_row["capacity"]


# ===========================================================================
# ENDPOINTS
# ===========================================================================

# --- Logical clock (Admin) -------------------------------------------------
@app.post("/_clock/set_current_utc")
def clock_set():
    guard({"Admin"})
    body = body_json()
    raw = body.get("to_iso8601")
    try:
        dt = parse_dt(raw)
    except (ValueError, TypeError):
        err_validation("to_iso8601 must be an ISO 8601 datetime")
    CLOCK["now"] = dt
    return ok({}, 200, "object")


# --- Machines (Admin) ------------------------------------------------------
@app.post("/machines")
def create_machine():
    guard({"Admin"})
    body = body_json()
    name = req_str(body, "name")
    kind = enum_field(body, "kind", MACHINE_KINDS)
    capacity = opt_nonneg_int(body, "capacity", 50)
    e = make(machines, {"name": name, "kind": kind, "capacity": capacity})
    return ok(ser_machine(e), 201, "object")


# --- Storage bins (Admin) --------------------------------------------------
@app.post("/storage-bins")
def create_bin():
    guard({"Admin"})
    body = body_json()
    label = req_str(body, "label")
    cap = body.get("capacity")
    if isinstance(cap, bool) or not isinstance(cap, int) or cap < 1:
        err_validation("capacity must be an integer >= 1")
    e = make(bins, {"label": label, "capacity": cap})
    return ok(ser_bin(e), 201, "object")


# --- Customers -------------------------------------------------------------
@app.post("/customers")
def create_customer():
    guard({"Admin"})
    body = body_json()
    email = req_str(body, "email")
    full_name = req_str(body, "full_name")
    state_code = req_str(body, "state_code")
    for c in customers.values():
        if c["email"] == email:
            err_validation("email must be unique")
    e = make(customers, {
        "email": email, "full_name": full_name, "state_code": state_code,
        "wallet_credit_cents": 0, "risk_score": 0,
        "approved_claim_count": 0, "pending_claim_count": 0,
    })
    return ok(ser_customer(e), 201, "object")


@app.get("/customers/<cid>")
def get_customer(cid):
    guard({"Admin", "Customer"})
    e = get_or_404(customers, cid)
    if g.role == "Customer" and cid != g.user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "Customer may only read their own record")
    return ok(ser_customer(e), 200, "object")


# --- Orders ----------------------------------------------------------------
@app.post("/orders")
def create_order():
    guard({"Customer", "Admin"})
    body = body_json()
    # (4) body FK existence
    cust_id = body.get("customer_id")
    if cust_id is not None:
        fk_or_404(customers, cust_id)
    # (5) ownership: Customer places order as self
    if g.role == "Customer" and cust_id is not None and cust_id != g.user_id:
        raise ApiError("ERR_NOT_OWNER", 403, "Customer may only order for themselves")
    # (7) body validity
    customer_id = req_str(body, "customer_id")
    plan_tier = enum_field(body, "plan_tier", PLAN_TIERS)
    turnaround = enum_field(body, "turnaround", TURNAROUNDS)
    output_option = enum_field(body, "output_option", OUTPUT_OPTIONS)
    lost_damage_protection = opt_bool(body, "lost_damage_protection", False)
    is_gift = opt_bool(body, "is_gift", False)
    gift_recipient_email = body.get("gift_recipient_email")
    if gift_recipient_email is not None and not isinstance(gift_recipient_email, str):
        err_validation("gift_recipient_email must be a string")
    declared_tape = opt_nonneg_int(body, "declared_tape_count", 0)
    declared_film = opt_nonneg_int(body, "declared_film_count", 0)
    declared_photo = opt_nonneg_int(body, "declared_photo_count", 0)
    declared_audio = opt_nonneg_int(body, "declared_audio_count", 0)
    promo_code = body.get("promo_code")
    if promo_code is not None:
        if not isinstance(promo_code, str):
            err_validation("promo_code must be a string")
        if promo_code != SAVE5_CODE:
            raise ApiError("ERR_INVALID_PROMO", 422, "Unrecognized promo_code")

    e = make(orders, {
        "customer_id": customer_id,
        "plan_tier": plan_tier,
        "turnaround": turnaround,
        "output_option": output_option,
        "lost_damage_protection": lost_damage_protection,
        "is_gift": is_gift,
        "gift_recipient_email": gift_recipient_email if is_gift else (gift_recipient_email if gift_recipient_email is not None else None),
        "promo_code": promo_code,
        "declared_tape_count": declared_tape,
        "declared_film_count": declared_film,
        "declared_photo_count": declared_photo,
        "declared_audio_count": declared_audio,
        "fulfillment_status": "QUOTED",
        "payment_status": "UNPAID",
        "estimate_total_cents": 0,
        "final_total_cents": None,
        "captured_total_cents": 0,
        "refunded_total_cents": 0,
        "received_item_count": 0,
        "written_off_count": 0,
        "_ready_dt": None,
    })
    e["estimate_total_cents"] = estimate_total_for(e)
    return ok(ser_order(e), 201, "object")


@app.get("/orders/<oid>")
def get_order(oid):
    guard({"Admin", "Customer"})
    e = get_or_404(orders, oid)
    require_owner_order(e)
    return ok(ser_order(e), 200, "object")


@app.get("/orders")
def list_orders():
    guard({"Admin", "Customer"})
    rows = list(orders.values())
    cust_filter = request.args.get("customer_id")
    ff = request.args.get("fulfillment_status")
    ps = request.args.get("payment_status")
    if g.role == "Customer":
        rows = [o for o in rows if o["customer_id"] == g.user_id]
    if cust_filter is not None:
        rows = [o for o in rows if o["customer_id"] == cust_filter]
    if ff is not None:
        rows = [o for o in rows if o["fulfillment_status"] == ff]
    if ps is not None:
        rows = [o for o in rows if o["payment_status"] == ps]
    return list_response(rows, ser_order)


@app.post("/orders/<oid>/authorize-payment")
def authorize_payment(oid):
    guard({"Customer", "Admin"})
    o = get_or_404(orders, oid)
    require_owner_order(o)
    if o["fulfillment_status"] != "QUOTED" or o["payment_status"] != "UNPAID":
        raise ApiError("ERR_INVALID_STATE", 409, "Order not in QUOTED/UNPAID state")
    o["payment_status"] = "AUTHORIZED"
    o["fulfillment_status"] = "AWAITING_MEDIA"
    touch(o)
    return ok(ser_order(o), 200, "object")


@app.post("/orders/<oid>/capture-payment")
def capture_payment(oid):
    guard({"Admin"})
    o = get_or_404(orders, oid)
    if o["payment_status"] != "AUTHORIZED":
        raise ApiError("ERR_INVALID_STATE", 409, "Order payment not AUTHORIZED")
    o["payment_status"] = "CAPTURED"
    o["captured_total_cents"] = o["estimate_total_cents"]
    touch(o)
    return ok(ser_order(o), 200, "object")


@app.post("/orders/<oid>/receive")
def receive_order(oid):
    guard({"IntakeTech", "Admin"})
    o = get_or_404(orders, oid)
    if o["fulfillment_status"] != "AWAITING_MEDIA" or o["payment_status"] not in ("AUTHORIZED", "CAPTURED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Order not ready to be received")
    o["fulfillment_status"] = "RECEIVED"
    touch(o)
    return ok(ser_order(o), 200, "object")


@app.post("/orders/<oid>/media-items")
def log_media_item(oid):
    guard({"IntakeTech", "Admin"})
    o = get_or_404(orders, oid)
    body = body_json()
    # (4) body FK existence
    bin_id = body.get("bin_id")
    if bin_id is not None:
        bin_row = fk_or_404(bins, bin_id)
    else:
        bin_row = None
    # (6) state: order must be RECEIVED
    if o["fulfillment_status"] != "RECEIVED":
        raise ApiError("ERR_ORDER_NOT_RECEIVED", 409, "Order not in RECEIVED state")
    # (6) business: bin capacity — needs a resolved bin
    if bin_row is None:
        err_validation("Missing field: bin_id")
    new_start = now()
    new_end = new_start + timedelta(days=RETENTION_DAYS)
    if bin_would_exceed(bin_row, new_start, new_end):
        raise ApiError("ERR_BIN_CAPACITY_EXCEEDED", 409, "Bin overlap capacity exceeded")
    # (7) body validity
    media_type = enum_field(body, "media_type", MEDIA_TYPES)
    barcode = body.get("barcode")
    if barcode is not None:
        if not isinstance(barcode, str):
            err_validation("barcode must be a string")
        for m in media_items.values():
            if m["barcode"] == barcode:
                err_validation("barcode must be unique")

    m = make(media_items, {
        "order_id": o["id"],
        "batch_id": None,
        "bin_id": bin_row["id"],
        "media_type": media_type,
        "barcode": barcode,
        "status": "LOGGED",
        "qc_attempts": 0,
        "digitized_minutes": None,
        "page_count": None,
        "_stored_dt": new_start,
        "_retention_dt": new_end,
    })
    o["received_item_count"] += 1
    touch(o)
    return ok(ser_media(m), 201, "object")


# --- Media items -----------------------------------------------------------
@app.get("/media-items/<mid>")
def get_media_item(mid):
    guard({"Admin", "LabTech", "IntakeTech", "Customer"})
    m = get_or_404(media_items, mid)
    return ok(ser_media(m), 200, "object")


@app.get("/media-items")
def list_media_items():
    guard({"Admin", "LabTech", "IntakeTech", "Customer"})
    rows = list(media_items.values())
    order_id = request.args.get("order_id")
    batch_id = request.args.get("batch_id")
    bin_id = request.args.get("bin_id")
    status = request.args.get("status")
    if order_id is not None:
        rows = [m for m in rows if m["order_id"] == order_id]
    if batch_id is not None:
        rows = [m for m in rows if m["batch_id"] == batch_id]
    if bin_id is not None:
        rows = [m for m in rows if m["bin_id"] == bin_id]
    if status is not None:
        rows = [m for m in rows if m["status"] == status]
    return list_response(rows, ser_media)


# --- Batches ---------------------------------------------------------------
@app.post("/batches")
def create_batch():
    guard({"LabTech", "Admin"})
    body = body_json()
    machine_id = body.get("machine_id")
    if machine_id is not None:
        fk_or_404(machines, machine_id)
    # parse window (needed for overlap check, which precedes generic validation)
    start_raw = body.get("scheduled_start")
    end_raw = body.get("scheduled_end")
    start_dt = end_dt = None
    try:
        if start_raw is not None:
            start_dt = parse_dt(start_raw)
        if end_raw is not None:
            end_dt = parse_dt(end_raw)
    except (ValueError, TypeError):
        start_dt = end_dt = None
    # (6) business: machine double-booking (half-open overlap)
    if machine_id is not None and start_dt is not None and end_dt is not None and end_dt > start_dt:
        for b in batches.values():
            if b["machine_id"] != machine_id:
                continue
            if start_dt < b["_end_dt"] and b["_start_dt"] < end_dt:
                raise ApiError("ERR_MACHINE_DOUBLE_BOOKED", 409, "Machine window overlaps")
    # (7) body validity
    if machine_id is None or not isinstance(machine_id, str):
        err_validation("Missing field: machine_id")
    if start_dt is None or end_dt is None:
        err_validation("scheduled_start and scheduled_end must be valid datetimes")
    if not (end_dt > start_dt):
        err_validation("scheduled_end must be strictly after scheduled_start")
    capacity = opt_nonneg_int(body, "capacity", 50)

    e = make(batches, {
        "machine_id": machine_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "capacity": capacity,
        "status": "OPEN",
        "loaded_count": 0,
    })
    return ok(ser_batch(e), 201, "object")


@app.get("/batches/<bid>")
def get_batch(bid):
    guard({"Admin", "LabTech"})
    e = get_or_404(batches, bid)
    return ok(ser_batch(e), 200, "object")


@app.get("/batches")
def list_batches():
    guard({"Admin", "LabTech"})
    rows = list(batches.values())
    machine_id = request.args.get("machine_id")
    status = request.args.get("status")
    if machine_id is not None:
        rows = [b for b in rows if b["machine_id"] == machine_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    return list_response(rows, ser_batch)


@app.post("/batches/<bid>/load")
def load_batch(bid):
    guard({"LabTech", "Admin"})
    batch = get_or_404(batches, bid)
    body = body_json()
    mi_id = body.get("media_item_id")
    if mi_id is not None:
        m = fk_or_404(media_items, mi_id)
    else:
        err_validation("Missing field: media_item_id")
    # (6) state guards (all generic ERR_INVALID_STATE)
    if m["status"] != "LOGGED":
        raise ApiError("ERR_INVALID_STATE", 409, "Media item not in LOGGED state")
    if batch["status"] not in ("OPEN", "LOADED"):
        raise ApiError("ERR_INVALID_STATE", 409, "Batch not OPEN/LOADED")
    if batch["loaded_count"] >= batch["capacity"]:
        raise ApiError("ERR_INVALID_STATE", 409, "Batch at capacity")
    m["status"] = "PREPPED"
    m["batch_id"] = batch["id"]
    touch(m)
    batch["loaded_count"] += 1
    batch["status"] = "LOADED"
    touch(batch)
    return ok(ser_batch(batch), 200, "object")


@app.post("/batches/<bid>/run")
def run_batch(bid):
    guard({"LabTech", "Admin"})
    batch = get_or_404(batches, bid)
    # (6) state
    if batch["status"] != "LOADED" or batch["loaded_count"] < 1:
        raise ApiError("ERR_INVALID_STATE", 409, "Batch not LOADED with items")
    loaded = [m for m in media_items.values() if m["batch_id"] == batch["id"] and m["status"] == "PREPPED"]
    # (6) cross-entity gate — check ALL before applying (atomic)
    for m in loaded:
        o = orders.get(m["order_id"])
        if o is None or o["fulfillment_status"] not in ("RECEIVED", "PROCESSING"):
            raise ApiError("ERR_ORDER_NOT_RECEIVED", 409, "Owning order not RECEIVED/PROCESSING")
    batch["status"] = "RUNNING"
    touch(batch)
    for m in loaded:
        m["status"] = "SCANNING"
        touch(m)
        o = orders[m["order_id"]]
        if o["fulfillment_status"] == "RECEIVED":
            o["fulfillment_status"] = "PROCESSING"
            touch(o)
    return ok(ser_batch(batch), 200, "object")


@app.post("/media-items/<mid>/complete-scan")
def complete_scan(mid):
    guard({"LabTech", "Admin"})
    m = get_or_404(media_items, mid)
    if m["status"] != "SCANNING":
        raise ApiError("ERR_INVALID_STATE", 409, "Media item not SCANNING")
    body = body_json()
    dm = body.get("digitized_minutes")
    if dm is not None:
        if isinstance(dm, bool) or not isinstance(dm, (int, float)):
            err_validation("digitized_minutes must be a number")
        m["digitized_minutes"] = dm
    pc = body.get("page_count")
    if pc is not None:
        if isinstance(pc, bool) or not isinstance(pc, int):
            err_validation("page_count must be an integer")
        m["page_count"] = pc
    m["status"] = "QC_PENDING"
    touch(m)
    if m["batch_id"] is not None:
        b = batches.get(m["batch_id"])
        if b is not None:
            maybe_complete_batch(b)
    return ok(ser_media(m), 200, "object")


@app.post("/media-items/<mid>/qc-review")
def qc_review(mid):
    guard({"LabTech", "Admin"})
    m = get_or_404(media_items, mid)
    if m["status"] != "QC_PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "Media item not QC_PENDING")
    body = body_json()
    decision = enum_field(body, "decision", {"PASS", "FAIL"})
    notes = body.get("notes")
    if notes is not None and not isinstance(notes, str):
        err_validation("notes must be a string")
    m["qc_attempts"] += 1
    make(qc_reviews, {
        "media_item_id": m["id"],
        "decision": decision,
        "attempt_number": m["qc_attempts"],
        "notes": notes,
    }, common=False)
    if decision == "PASS":
        m["status"] = "OUTPUT_READY"
        touch(m)
        o = orders.get(m["order_id"])
        if o is not None:
            maybe_ready(o)
    else:
        m["status"] = "QC_FAIL"
        touch(m)
    return ok(ser_media(m), 201, "object")


@app.get("/media-items/<mid>/qc-reviews")
def list_qc_reviews(mid):
    guard({"Admin", "LabTech"})
    get_or_404(media_items, mid)
    rows = [q for q in qc_reviews.values() if q["media_item_id"] == mid]
    return list_response(rows, ser_qc)


@app.post("/media-items/<mid>/rescan")
def rescan(mid):
    guard({"LabTech", "Admin"})
    m = get_or_404(media_items, mid)
    if m["status"] != "QC_FAIL":
        raise ApiError("ERR_INVALID_STATE", 409, "Media item not QC_FAIL")
    if m["qc_attempts"] >= MAX_QC_ATTEMPTS:
        raise ApiError("ERR_QC_ATTEMPTS_EXCEEDED", 409, "QC attempt cap reached")
    m["status"] = "SCANNING"
    touch(m)
    return ok(ser_media(m), 200, "object")


# --- Output artifacts ------------------------------------------------------
@app.post("/orders/<oid>/output-artifacts")
def generate_artifact(oid):
    guard({"Customer", "LabTech", "Admin"})
    o = get_or_404(orders, oid)
    require_owner_order(o)
    body = body_json()
    # (6) state/business in the PRD-declared order
    if o["fulfillment_status"] != "READY":
        raise ApiError("ERR_ORDER_NOT_READY", 409, "Order not READY")
    if o["payment_status"] != "CAPTURED":
        raise ApiError("ERR_PAYMENT_NOT_CAPTURED", 402, "Order payment not CAPTURED")
    ev = body.get("expected_order_version")
    if ev is not None and ev != o["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION", 412, "Stale order version")
    # (7) body validity
    if ev is None:
        err_validation("Missing field: expected_order_version")
    output_type = enum_field(body, "output_type", OUTPUT_OPTIONS)

    created = now()
    item_count = sum(
        1 for m in media_items.values()
        if m["order_id"] == o["id"] and m["status"] == "OUTPUT_READY"
    )
    art = make(artifacts, {
        "order_id": o["id"],
        "output_type": output_type,
        "status": "AVAILABLE",
        "download_token": "tok_" + uuid.uuid4().hex,
        "download_count": 0,
        "_expires_dt": created + timedelta(days=DOWNLOAD_EXPIRY_DAYS),
        "item_count_snapshot": item_count,
    })
    # supersede prior AVAILABLE artifact of this order
    for other in artifacts.values():
        if other["id"] != art["id"] and other["order_id"] == o["id"] and other["status"] == "AVAILABLE":
            other["status"] = "REVOKED"
            touch(other)
    touch(o)
    return ok(ser_artifact(art), 201, "object")


@app.get("/orders/<oid>/output-artifacts")
def list_order_artifacts(oid):
    guard({"Admin", "Customer", "LabTech"})
    o = get_or_404(orders, oid)
    require_owner_order(o)
    rows = [a for a in artifacts.values() if a["order_id"] == oid]
    return list_response(rows, ser_artifact)


@app.get("/output-artifacts/<aid>")
def get_artifact(aid):
    guard({"Admin", "Customer", "LabTech"})
    a = get_or_404(artifacts, aid)
    require_owner_order(orders[a["order_id"]])
    return ok(ser_artifact(a), 200, "object")


@app.post("/output-artifacts/<aid>/download")
def download_artifact(aid):
    guard({"Customer", "Admin"})
    a = get_or_404(artifacts, aid)
    require_owner_order(orders[a["order_id"]])
    # (6) business, in the PRD-declared order
    if a["output_type"] != "CLOUD":
        raise ApiError("ERR_NOT_DOWNLOADABLE", 409, "Only CLOUD artifacts are downloadable")
    if now() >= a["_expires_dt"]:
        a["status"] = "EXPIRED"
        touch(a)
        raise ApiError("ERR_DOWNLOAD_EXPIRED", 409, "Download window expired")
    if a["download_count"] >= MAX_DOWNLOADS_PER_ARTIFACT:
        raise ApiError("ERR_DOWNLOAD_LIMIT_REACHED", 409, "Download limit reached")
    a["download_count"] += 1
    touch(a)
    ev = make(download_events, {
        "output_artifact_id": a["id"],
        "sequence_number": a["download_count"],
        "_downloaded_dt": now(),
    }, common=False)
    return ok(ser_download(ev), 201, "object")


@app.get("/output-artifacts/<aid>/downloads")
def list_downloads(aid):
    guard({"Admin", "Customer", "LabTech"})
    a = get_or_404(artifacts, aid)
    require_owner_order(orders[a["order_id"]])
    rows = [d for d in download_events.values() if d["output_artifact_id"] == aid]
    return list_response(rows, ser_download)


# --- Damage claims ---------------------------------------------------------
@app.post("/damage-claims")
def create_claim():
    guard({"Customer", "Admin"})
    body = body_json()
    # (4) body FK existence
    order_id = body.get("order_id")
    media_item_id = body.get("media_item_id")
    o = fk_or_404(orders, order_id) if order_id is not None else None
    m = fk_or_404(media_items, media_item_id) if media_item_id is not None else None
    # (5) ownership
    if o is not None:
        require_owner_order(o)
    # need both refs to proceed to business rules
    if o is None:
        err_validation("Missing field: order_id")
    if m is None:
        err_validation("Missing field: media_item_id")
    # (6) referential: media item must belong to order
    if m["order_id"] != o["id"]:
        raise ApiError("ERR_MEDIA_NOT_IN_ORDER", 422, "Media item does not belong to order")
    # (6) temporal: claim within CLAIM_WINDOW_DAYS of order READY
    if o["_ready_dt"] is not None and now() > o["_ready_dt"] + timedelta(days=CLAIM_WINDOW_DAYS):
        raise ApiError("ERR_CLAIM_WINDOW_CLOSED", 422, "Claim window closed")
    # (7) body validity
    claim_type = enum_field(body, "claim_type", CLAIM_TYPES)
    declared_value = opt_int(body, "declared_value_cents")
    if declared_value is not None and declared_value < 0:
        err_validation("declared_value_cents must be non-negative")

    claim = make(claims, {
        "order_id": o["id"],
        "media_item_id": m["id"],
        "claim_type": claim_type,
        "declared_value_cents": declared_value,
        "status": "SUBMITTED",
        "payout_cents": 0,
    })
    cust = customers.get(o["customer_id"])
    if cust is not None:
        recompute_customer(cust)
        touch(cust)
    return ok(ser_claim(claim), 201, "object")


@app.get("/orders/<oid>/damage-claims")
def list_order_claims(oid):
    guard({"Admin", "Customer", "ClaimsAdjuster"})
    o = get_or_404(orders, oid)
    require_owner_order(o)
    rows = [c for c in claims.values() if c["order_id"] == oid]
    return list_response(rows, ser_claim)


@app.get("/media-items/<mid>/damage-claims")
def list_media_claims(mid):
    guard({"Admin", "Customer", "ClaimsAdjuster"})
    m = get_or_404(media_items, mid)
    if g.role == "Customer":
        require_owner_order(orders[m["order_id"]])
    rows = [c for c in claims.values() if c["media_item_id"] == mid]
    return list_response(rows, ser_claim)


@app.post("/damage-claims/<cid>/review")
def review_claim(cid):
    guard({"ClaimsAdjuster", "Admin"})
    claim = get_or_404(claims, cid)
    # (6) state
    if claim["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "Claim not SUBMITTED")
    body = body_json()
    decision = body.get("decision")
    o = orders[claim["order_id"]]
    if decision == "APPROVE":
        # (6) business fiscal
        if o["payment_status"] != "CAPTURED":
            raise ApiError("ERR_PAYMENT_NOT_CAPTURED", 402, "Order payment not CAPTURED")
        m = media_items[claim["media_item_id"]]
        payout = damage_payout(m["media_type"], claim["declared_value_cents"], o["lost_damage_protection"])
        claim["payout_cents"] = payout
        claim["status"] = "APPROVED"
        touch(claim)
        # cascade link 1: write off media item
        m["status"] = "WRITTEN_OFF"
        touch(m)
        # cascade link 2: order refund + partial-refund + final recompute
        o["written_off_count"] += 1
        o["refunded_total_cents"] += payout
        o["payment_status"] = "PARTIALLY_REFUNDED"
        o["final_total_cents"] = final_total_for(o)
        touch(o)
        maybe_ready(o)
        # cascade link 3: customer wallet + counters + risk
        cust = customers.get(o["customer_id"])
        if cust is not None:
            cust["wallet_credit_cents"] += payout
            recompute_customer(cust)
            touch(cust)
        return ok(ser_claim(claim), 200, "object")
    elif decision == "REJECT":
        claim["status"] = "REJECTED"
        touch(claim)
        cust = customers.get(o["customer_id"])
        if cust is not None:
            recompute_customer(cust)
            touch(cust)
        return ok(ser_claim(claim), 200, "object")
    else:
        err_validation("decision must be APPROVE or REJECT")


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
