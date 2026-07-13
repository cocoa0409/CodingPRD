"""Distillery & Spirits Production (DSP/TTB) REST API.

In-memory only. The store starts empty on every boot; no seeding.
"""
import os
import re
import uuid
import random
import string
import calendar
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify, g

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ProductionManager", "ComplianceOfficer", "SalesManager",
         "TastingRoomStaff", "Customer"}

SPIRIT_TYPES = {"WHISKEY", "GIN", "VODKA", "RUM", "BRANDY"}
CHAR_LEVELS = {"CHAR_1", "CHAR_2", "CHAR_3", "CHAR_4"}
GAUGE_METHODS = {"VOLUME", "WEIGHT"}
LINE_IDS = {"LINE_A", "LINE_B"}
REMOVAL_REASONS = {"TAXPAID", "TRANSFER_IN_BOND", "EXPORT"}
CHANNELS = {"THREE_TIER", "SELF_DISTRIBUTION", "TASTING_ROOM", "CLUB"}
CLUB_TIERS = {"NONE", "SILVER", "GOLD", "RESERVE"}

SPECIFIC_WEIGHT_LBS_PER_GALLON = Decimal("7.28")
ML_PER_GALLON = Decimal("3785.411784")
ANGEL_SHARE_ANNUAL_RATE = Decimal("0.05")
CBMA_TIER_LIMIT_PG = Decimal("100000")
CBMA_REDUCED_RATE_CENTS = Decimal("270")
STANDARD_RATE_CENTS = Decimal("1350")
COCKTAIL_SURCHARGE_CENTS = 1200
TOUR_BUFFER_MINUTES = 30
TASTING_ROOM_CAPACITY = 20

DEFAULT_CLOCK = "2026-05-01T00:00:00Z"

PG_ACCOUNTS = [
    "total_gauged_pg", "production_account_pg", "storage_account_pg",
    "processing_account_pg", "removed_pg", "angel_share_losses_pg",
    "bottling_losses_pg", "destroyed_losses_pg", "bonded_total_pg",
    "cbma_pg_removed_ytd",
]

# ---------------------------------------------------------------------------
# In-memory store (reset on every process boot; NO seeding)
# ---------------------------------------------------------------------------
DB = {}
_SEQ = {"n": 0}
_CLOCK = {"dt": None}


def reset_state():
    DB.clear()
    for coll in ["distilleries", "mash_batches", "distillation_runs", "barrels",
                 "label_applications", "bottling_runs", "tax_removals",
                 "excise_reports", "customers", "sales_orders", "tour_bookings"]:
        DB[coll] = {}
    _SEQ["n"] = 0
    _CLOCK["dt"] = parse_iso(DEFAULT_CLOCK)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ApiError("ERR_VALIDATION", 422, "invalid timestamp")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        raise ApiError("ERR_VALIDATION", 422, "invalid ISO 8601 timestamp: %s" % s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_now():
    return _CLOCK["dt"]


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)


def now_iso():
    return fmt_iso(clock_now())


def add_months(dt, n):
    m = dt.month - 1 + n
    y = dt.year + m // 12
    m = m % 12 + 1
    d = min(dt.day, calendar.monthrange(y, m)[1])
    return dt.replace(year=y, month=m, day=d)


def months_between(fill, now):
    if now <= fill:
        return 0
    months = (now.year - fill.year) * 12 + (now.month - fill.month)
    if add_months(fill, months) > now:
        months -= 1
    return max(0, months)


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def dec(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def round_pg(x):
    return dec(x).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def round_cents(x):
    return int(dec(x).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def conv(v):
    if isinstance(v, Decimal):
        f = float(v)
        return f
    return v


# ---------------------------------------------------------------------------
# Identity / common fields
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["n"] += 1
    return _SEQ["n"]


def new_entity(extra):
    ent = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
        "_seq": next_seq(),
    }
    ent.update(extra)
    return ent


def touch(ent):
    ent["updated_at"] = now_iso()
    ent["version"] += 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def make_meta(pagination=None):
    meta = {
        "api_request_id": "req_" + "".join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        "api_request_timestamp": now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return meta


def success(data, response_type="object", status=200, pagination=None):
    body = {
        "meta": make_meta(pagination),
        "response_type": response_type,
        "data": data,
    }
    return jsonify(body), status


def error_response(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


@app.errorhandler(404)
def handle_404(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "resource not found"))


@app.errorhandler(405)
def handle_405(_e):
    return error_response(ApiError("ERR_NOT_FOUND", 404, "method not allowed"))


@app.errorhandler(Exception)
def handle_uncaught(e):
    if isinstance(e, ApiError):
        return error_response(e)
    return error_response(ApiError("ERR_INTERNAL", 500, str(e)))


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate(allowed_roles):
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if not role or role not in ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unrecognized role")
    if role not in allowed_roles:
        raise ApiError("ERR_FORBIDDEN", 403, "role not permitted for this operation")
    g.role = role
    g.user_id = user_id
    return role, user_id


def is_customer():
    return g.get("role") == "Customer"


def check_owner(customer_id):
    """For Customer role: the acting user must own the row."""
    if is_customer() and customer_id != g.get("user_id"):
        raise ApiError("ERR_FORBIDDEN", 403, "customer may only act on its own rows")


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def get_or_404(coll, _id):
    ent = DB[coll].get(_id)
    if ent is None:
        raise ApiError("ERR_NOT_FOUND", 404, "%s not found" % coll)
    return ent


def get_body():
    if request.is_json:
        data = request.get_json(silent=True)
    else:
        data = request.get_json(silent=True)
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ApiError("ERR_VALIDATION", 422, "request body must be an object")
    return data


# ---------------------------------------------------------------------------
# Field validation helpers (ERR_VALIDATION on failure)
# ---------------------------------------------------------------------------
def v_error(msg):
    raise ApiError("ERR_VALIDATION", 422, msg)


def req_str(body, key):
    if key not in body or body[key] is None:
        v_error("missing field: %s" % key)
    val = body[key]
    if not isinstance(val, str) or val == "":
        v_error("field %s must be a non-empty string" % key)
    return val


def req_enum(body, key, allowed):
    val = req_str(body, key)
    if val not in allowed:
        v_error("field %s must be one of %s" % (key, sorted(allowed)))
    return val


def opt_enum(body, key, allowed, default):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, str) or val not in allowed:
        v_error("field %s must be one of %s" % (key, sorted(allowed)))
    return val


def _is_number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def req_number(body, key, positive=True, allow_zero=False):
    if key not in body or body[key] is None:
        v_error("missing field: %s" % key)
    val = body[key]
    if not _is_number(val):
        v_error("field %s must be a number" % key)
    if positive:
        if allow_zero:
            if val < 0:
                v_error("field %s must be >= 0" % key)
        elif val <= 0:
            v_error("field %s must be > 0" % key)
    return val


def req_int(body, key, positive=True, allow_zero=False):
    if key not in body or body[key] is None:
        v_error("missing field: %s" % key)
    val = body[key]
    if isinstance(val, bool) or not isinstance(val, int):
        v_error("field %s must be an integer" % key)
    if positive:
        if allow_zero:
            if val < 0:
                v_error("field %s must be >= 0" % key)
        elif val <= 0:
            v_error("field %s must be > 0" % key)
    return val


def opt_bool(body, key, default=False):
    if key not in body or body[key] is None:
        return default
    val = body[key]
    if not isinstance(val, bool):
        v_error("field %s must be a boolean" % key)
    return val


def req_bool(body, key):
    if key not in body or body[key] is None:
        v_error("missing field: %s" % key)
    val = body[key]
    if not isinstance(val, bool):
        v_error("field %s must be a boolean" % key)
    return val


# ---------------------------------------------------------------------------
# Pagination / listing
# ---------------------------------------------------------------------------
def parse_pagination():
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            v_error("limit must be an integer")
        if limit < 1 or limit > 100:
            v_error("limit must be between 1 and 100")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            v_error("offset must be an integer")
        if offset < 0:
            v_error("offset must be >= 0")
    return limit, offset


def paginate(rows, serialize):
    limit, offset = parse_pagination()
    rows = sorted(rows, key=lambda e: (e["created_at"], e["_seq"]))
    total = len(rows)
    window = rows[offset:offset + limit]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    data = [serialize(e) for e in window]
    return success(data, response_type="array", status=200, pagination=pagination)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
COMMON = ["id", "created_at", "updated_at", "version"]


def _serialize(ent, fields):
    out = {}
    for f in COMMON:
        out[f] = ent[f]
    for f in fields:
        out[f] = conv(ent.get(f))
    return out


def ser_distillery(e):
    return _serialize(e, [
        "name", "dsp_permit_number", "state_code",
        "total_gauged_pg", "production_account_pg", "storage_account_pg",
        "processing_account_pg", "removed_pg", "angel_share_losses_pg",
        "bottling_losses_pg", "destroyed_losses_pg", "bonded_total_pg",
        "cbma_pg_removed_ytd", "cbma_rate_tier", "club_release_active",
    ])


def ser_mash(e):
    return _serialize(e, ["distillery_id", "grain_bill", "volume_gallons", "status"])


def ser_run(e):
    return _serialize(e, [
        "distillery_id", "mash_batch_id", "spirit_type", "gauge_method",
        "collected_wine_gallons", "collected_proof", "collected_weight_lbs",
        "proof_gallons", "remaining_proof_gallons", "open_barrel_count", "status",
    ])


def barrel_angel_and_current(e):
    fill_pg = dec(e["fill_proof_gallons"])
    if e.get("_frozen"):
        return e["angel_share_pg"], e["current_proof_gallons"]
    fill_dt = e["_fill_dt"]
    months = months_between(fill_dt, clock_now())
    angel = round_pg(fill_pg * ANGEL_SHARE_ANNUAL_RATE * (Decimal(months) / Decimal("12")))
    current = fill_pg - angel
    if current < 0:
        current = Decimal("0")
    return angel, current


def ser_barrel(e):
    angel, current = barrel_angel_and_current(e)
    out = _serialize(e, [
        "distillation_run_id", "distillery_id", "char_level",
        "rickhouse_position", "fill_proof_gallons", "fill_date", "status",
    ])
    out["angel_share_pg"] = conv(angel)
    out["current_proof_gallons"] = conv(current)
    return out


def ser_label(e):
    return _serialize(e, [
        "distillery_id", "brand_name", "spirit_type", "label_proof",
        "net_contents_ml", "ttb_id", "correction_notes", "status",
    ])


def ser_bottling(e):
    return _serialize(e, [
        "barrel_id", "label_application_id", "distillery_id", "line_id",
        "scheduled_start", "scheduled_end", "bottle_size_ml", "bottles_per_case",
        "planned_cases", "draw_proof_gallons", "bottled_proof_gallons",
        "bottling_loss_pg", "cases_bottled", "cases_available", "cases_reserved",
        "cases_shipped", "cases_removed", "tax_status", "inventory_status", "status",
    ])


def ser_tax(e):
    return _serialize(e, [
        "bottling_run_id", "distillery_id", "removal_reason", "removed_cases",
        "removed_proof_gallons", "reduced_rate_pg", "standard_rate_pg",
        "excise_tax_due_cents", "removal_date", "status",
    ])


def ser_excise(e):
    return _serialize(e, [
        "distillery_id", "period_month", "expected_distillery_version",
        "total_removed_pg", "total_excise_due_cents", "supersedes_report_id",
        "status",
    ])


def ser_customer(e):
    return _serialize(e, ["name", "email", "state_code", "club_tier", "age_verified"])


def ser_order(e):
    return _serialize(e, [
        "customer_id", "bottling_run_id", "distillery_id", "channel", "cases",
        "unit_price_cents", "includes_cocktail", "subtotal_cents", "total_cents",
        "payment_status", "fulfillment_status",
    ])


def ser_tour(e):
    return _serialize(e, [
        "customer_id", "distillery_id", "start_time", "end_time", "party_size",
        "includes_tasting", "status",
    ])


# ---------------------------------------------------------------------------
# Ledger helpers
# ---------------------------------------------------------------------------
def recompute_bonded(dist):
    dist["bonded_total_pg"] = (dist["production_account_pg"]
                              + dist["storage_account_pg"]
                              + dist["processing_account_pg"])


def recompute_cbma_tier(dist):
    if dist["cbma_pg_removed_ytd"] >= CBMA_TIER_LIMIT_PG:
        dist["cbma_rate_tier"] = "STANDARD"
    else:
        dist["cbma_rate_tier"] = "REDUCED"


def recompute_inventory_status(run):
    if run["cases_available"] > 0:
        run["inventory_status"] = "IN_STOCK"
    else:
        run["inventory_status"] = "SOLD_OUT"


# ===========================================================================
# Test-driving endpoints
# ===========================================================================
@app.route("/dsp/_clock/set_current_utc", methods=["POST"])
def set_clock():
    authenticate({"ProductionManager", "ComplianceOfficer",
                  "SalesManager", "TastingRoomStaff"})
    body = get_body()
    if "to_iso8601" not in body or body["to_iso8601"] is None:
        v_error("missing field: to_iso8601")
    _CLOCK["dt"] = parse_iso(body["to_iso8601"])
    return success({}, response_type="object", status=200)


@app.route("/dsp/_ledger/set_cbma_ytd", methods=["POST"])
def set_cbma_ytd():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    dist_id = req_str(body, "distillery_id")
    dist = get_or_404("distilleries", dist_id)
    val = req_number(body, "cbma_pg_removed_ytd", positive=True, allow_zero=True)
    dist["cbma_pg_removed_ytd"] = round_pg(val)
    recompute_cbma_tier(dist)
    touch(dist)
    return success(ser_distillery(dist), status=200)


# ===========================================================================
# Distillery
# ===========================================================================
@app.route("/dsp/distilleries", methods=["POST"])
def create_distillery():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    name = req_str(body, "name")
    permit = req_str(body, "dsp_permit_number")
    state_code = req_str(body, "state_code")
    ent = new_entity({
        "name": name,
        "dsp_permit_number": permit,
        "state_code": state_code,
        "total_gauged_pg": Decimal("0"),
        "production_account_pg": Decimal("0"),
        "storage_account_pg": Decimal("0"),
        "processing_account_pg": Decimal("0"),
        "removed_pg": Decimal("0"),
        "angel_share_losses_pg": Decimal("0"),
        "bottling_losses_pg": Decimal("0"),
        "destroyed_losses_pg": Decimal("0"),
        "bonded_total_pg": Decimal("0"),
        "cbma_pg_removed_ytd": Decimal("0"),
        "cbma_rate_tier": "REDUCED",
        "club_release_active": False,
    })
    DB["distilleries"][ent["id"]] = ent
    return success(ser_distillery(ent), status=201)


@app.route("/dsp/distilleries/<_id>", methods=["GET"])
def get_distillery(_id):
    authenticate({"ProductionManager", "ComplianceOfficer",
                  "SalesManager", "TastingRoomStaff"})
    ent = get_or_404("distilleries", _id)
    return success(ser_distillery(ent), status=200)


@app.route("/dsp/distilleries", methods=["GET"])
def list_distilleries():
    authenticate({"ProductionManager", "ComplianceOfficer",
                  "SalesManager", "TastingRoomStaff"})
    return paginate(list(DB["distilleries"].values()), ser_distillery)


@app.route("/dsp/distilleries/<_id>/club-release", methods=["POST"])
def club_release(_id):
    authenticate({"SalesManager"})
    dist = get_or_404("distilleries", _id)
    body = get_body()
    active = req_bool(body, "active")
    dist["club_release_active"] = active
    touch(dist)
    return success(ser_distillery(dist), status=200)


# ===========================================================================
# MashBatch
# ===========================================================================
@app.route("/dsp/mash-batches", methods=["POST"])
def create_mash():
    authenticate({"ProductionManager"})
    body = get_body()
    dist_id = req_str(body, "distillery_id")
    get_or_404("distilleries", dist_id)
    grain_bill = req_str(body, "grain_bill")
    volume = req_number(body, "volume_gallons", positive=True)
    ent = new_entity({
        "distillery_id": dist_id,
        "grain_bill": grain_bill,
        "volume_gallons": volume,
        "status": "FERMENTING",
    })
    DB["mash_batches"][ent["id"]] = ent
    return success(ser_mash(ent), status=201)


@app.route("/dsp/mash-batches/<_id>", methods=["GET"])
def get_mash(_id):
    authenticate({"ProductionManager", "ComplianceOfficer"})
    return success(ser_mash(get_or_404("mash_batches", _id)), status=200)


@app.route("/dsp/mash-batches", methods=["GET"])
def list_mash():
    authenticate({"ProductionManager", "ComplianceOfficer"})
    rows = list(DB["mash_batches"].values())
    dist_id = request.args.get("distillery_id")
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_mash)


@app.route("/dsp/mash-batches/<_id>/dump", methods=["POST"])
def dump_mash(_id):
    authenticate({"ProductionManager"})
    ent = get_or_404("mash_batches", _id)
    if ent["status"] != "FERMENTING":
        raise ApiError("ERR_INVALID_STATE", 409, "mash batch not FERMENTING")
    ent["status"] = "DUMPED"
    touch(ent)
    return success(ser_mash(ent), status=200)


# ===========================================================================
# DistillationRun
# ===========================================================================
@app.route("/dsp/distillation-runs", methods=["POST"])
def create_run():
    authenticate({"ProductionManager"})
    body = get_body()
    dist_id = req_str(body, "distillery_id")
    get_or_404("distilleries", dist_id)
    mash_id = req_str(body, "mash_batch_id")
    get_or_404("mash_batches", mash_id)
    spirit = req_enum(body, "spirit_type", SPIRIT_TYPES)
    gauge_method = req_enum(body, "gauge_method", GAUGE_METHODS)
    wine_gallons = req_number(body, "collected_wine_gallons", positive=True)
    proof = req_number(body, "collected_proof", positive=True)
    weight = None
    if "collected_weight_lbs" in body and body["collected_weight_lbs"] is not None:
        weight = req_number(body, "collected_weight_lbs", positive=False)
    ent = new_entity({
        "distillery_id": dist_id,
        "mash_batch_id": mash_id,
        "spirit_type": spirit,
        "gauge_method": gauge_method,
        "collected_wine_gallons": wine_gallons,
        "collected_proof": proof,
        "collected_weight_lbs": weight,
        "proof_gallons": Decimal("0"),
        "remaining_proof_gallons": Decimal("0"),
        "open_barrel_count": 0,
        "status": "DISTILLING",
    })
    DB["distillation_runs"][ent["id"]] = ent
    return success(ser_run(ent), status=201)


@app.route("/dsp/distillation-runs/<_id>", methods=["GET"])
def get_run(_id):
    authenticate({"ProductionManager", "ComplianceOfficer"})
    return success(ser_run(get_or_404("distillation_runs", _id)), status=200)


@app.route("/dsp/distillation-runs", methods=["GET"])
def list_runs():
    authenticate({"ProductionManager", "ComplianceOfficer"})
    rows = list(DB["distillation_runs"].values())
    mash_id = request.args.get("mash_batch_id")
    dist_id = request.args.get("distillery_id")
    if mash_id is not None:
        rows = [r for r in rows if r["mash_batch_id"] == mash_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_run)


@app.route("/dsp/distillation-runs/<_id>/gauge", methods=["POST"])
def gauge_run(_id):
    authenticate({"ProductionManager"})
    run = get_or_404("distillation_runs", _id)
    # state
    if run["status"] != "DISTILLING":
        raise ApiError("ERR_INVALID_STATE", 409, "run not DISTILLING")
    mash = DB["mash_batches"].get(run["mash_batch_id"])
    if mash is None or mash["status"] != "FERMENTING":
        raise ApiError("ERR_MASH_NOT_AVAILABLE", 409, "mash batch not FERMENTING")
    # compute proof gallons
    if run["gauge_method"] == "WEIGHT":
        if run["collected_weight_lbs"] is None or run["collected_weight_lbs"] <= 0:
            v_error("collected_weight_lbs must be > 0 for WEIGHT gauge")
        wine_gallons = dec(run["collected_weight_lbs"]) / SPECIFIC_WEIGHT_LBS_PER_GALLON
    else:
        wine_gallons = dec(run["collected_wine_gallons"])
    proof_gallons = round_pg(wine_gallons * dec(run["collected_proof"]) / Decimal("100"))
    run["proof_gallons"] = proof_gallons
    run["remaining_proof_gallons"] = proof_gallons
    run["status"] = "GAUGED"
    touch(run)
    # ledger
    dist = DB["distilleries"][run["distillery_id"]]
    dist["total_gauged_pg"] += proof_gallons
    dist["production_account_pg"] += proof_gallons
    recompute_bonded(dist)
    touch(dist)
    # mash bubble
    mash["status"] = "DISTILLED"
    touch(mash)
    return success(ser_run(run), status=200)


# ===========================================================================
# Barrel
# ===========================================================================
@app.route("/dsp/barrels", methods=["POST"])
def create_barrel():
    authenticate({"ProductionManager"})
    body = get_body()
    run_id = req_str(body, "distillation_run_id")
    run = get_or_404("distillation_runs", run_id)
    char_level = req_enum(body, "char_level", CHAR_LEVELS)
    rick = req_str(body, "rickhouse_position")
    fill = req_number(body, "fill_proof_gallons", positive=True)
    fill_dec = dec(fill)
    dist = DB["distilleries"][run["distillery_id"]]
    clk = clock_now()
    ent = new_entity({
        "distillation_run_id": run_id,
        "distillery_id": run["distillery_id"],
        "char_level": char_level,
        "rickhouse_position": rick,
        "fill_proof_gallons": fill,
        "fill_date": fmt_iso(clk),
        "_fill_dt": clk,
        "status": "AGING",
        "_frozen": False,
        "angel_share_pg": Decimal("0"),
        "current_proof_gallons": fill_dec,
    })
    DB["barrels"][ent["id"]] = ent
    # ledger transfer
    run["remaining_proof_gallons"] = run["remaining_proof_gallons"] - fill_dec
    run["open_barrel_count"] += 1
    touch(run)
    dist["production_account_pg"] -= fill_dec
    dist["storage_account_pg"] += fill_dec
    recompute_bonded(dist)
    touch(dist)
    return success(ser_barrel(ent), status=201)


@app.route("/dsp/barrels/<_id>", methods=["GET"])
def get_barrel(_id):
    authenticate({"ProductionManager", "ComplianceOfficer"})
    return success(ser_barrel(get_or_404("barrels", _id)), status=200)


@app.route("/dsp/barrels", methods=["GET"])
def list_barrels():
    authenticate({"ProductionManager", "ComplianceOfficer"})
    rows = list(DB["barrels"].values())
    run_id = request.args.get("distillation_run_id")
    dist_id = request.args.get("distillery_id")
    if run_id is not None:
        rows = [r for r in rows if r["distillation_run_id"] == run_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_barrel)


def close_run_cascade(run):
    """When a run's open_barrel_count reaches 0 while GAUGED, close it and
    archive its mash batch."""
    if run["open_barrel_count"] == 0 and run["status"] == "GAUGED":
        run["status"] = "CLOSED"
        touch(run)
        mash = DB["mash_batches"].get(run["mash_batch_id"])
        if mash is not None and mash["status"] == "DISTILLED":
            mash["status"] = "ARCHIVED"
            touch(mash)


@app.route("/dsp/barrels/<_id>/dump", methods=["POST"])
def dump_barrel(_id):
    authenticate({"ProductionManager"})
    barrel = get_or_404("barrels", _id)
    if barrel["status"] != "AGING":
        raise ApiError("ERR_INVALID_STATE", 409, "barrel not AGING")
    angel, current = barrel_angel_and_current(barrel)
    dist = DB["distilleries"][barrel["distillery_id"]]
    dist["angel_share_losses_pg"] += angel
    dist["storage_account_pg"] -= (current + angel)
    dist["destroyed_losses_pg"] += current
    recompute_bonded(dist)
    touch(dist)
    barrel["angel_share_pg"] = angel
    barrel["current_proof_gallons"] = Decimal("0")
    barrel["_frozen"] = True
    barrel["status"] = "DESTROYED"
    touch(barrel)
    run = DB["distillation_runs"].get(barrel["distillation_run_id"])
    if run is not None:
        run["open_barrel_count"] -= 1
        touch(run)
        close_run_cascade(run)
    return success(ser_barrel(barrel), status=200)


# ===========================================================================
# LabelApplication
# ===========================================================================
@app.route("/dsp/label-applications", methods=["POST"])
def create_label():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    dist_id = req_str(body, "distillery_id")
    get_or_404("distilleries", dist_id)
    brand = req_str(body, "brand_name")
    spirit = req_enum(body, "spirit_type", SPIRIT_TYPES)
    label_proof = req_number(body, "label_proof", positive=True)
    net_ml = req_number(body, "net_contents_ml", positive=True)
    ent = new_entity({
        "distillery_id": dist_id,
        "brand_name": brand,
        "spirit_type": spirit,
        "label_proof": label_proof,
        "net_contents_ml": net_ml,
        "ttb_id": None,
        "correction_notes": None,
        "status": "DRAFT",
    })
    DB["label_applications"][ent["id"]] = ent
    return success(ser_label(ent), status=201)


@app.route("/dsp/label-applications/<_id>", methods=["GET"])
def get_label(_id):
    authenticate({"ProductionManager", "ComplianceOfficer"})
    return success(ser_label(get_or_404("label_applications", _id)), status=200)


@app.route("/dsp/label-applications", methods=["GET"])
def list_labels():
    authenticate({"ProductionManager", "ComplianceOfficer"})
    rows = list(DB["label_applications"].values())
    dist_id = request.args.get("distillery_id")
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_label)


@app.route("/dsp/label-applications/<_id>/submit", methods=["POST"])
def submit_label(_id):
    authenticate({"ComplianceOfficer"})
    ent = get_or_404("label_applications", _id)
    if ent["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "label not DRAFT")
    ent["status"] = "SUBMITTED"
    touch(ent)
    return success(ser_label(ent), status=200)


@app.route("/dsp/label-applications/<_id>/decide", methods=["POST"])
def decide_label(_id):
    authenticate({"ComplianceOfficer"})
    ent = get_or_404("label_applications", _id)
    body = get_body()
    outcome = req_enum(body, "outcome", {"APPROVE", "RETURN"})
    if ent["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409, "label not SUBMITTED")
    if outcome == "APPROVE":
        ent["status"] = "APPROVED"
        ent["ttb_id"] = "TTB-" + uuid.uuid4().hex[:12].upper()
    else:
        ent["status"] = "NEEDS_CORRECTION"
        notes = None
        if "correction_notes" in body and body["correction_notes"] is not None:
            notes = body["correction_notes"]
            if not isinstance(notes, str):
                v_error("correction_notes must be a string")
        ent["correction_notes"] = notes
    touch(ent)
    return success(ser_label(ent), status=200)


@app.route("/dsp/label-applications/<_id>/resubmit", methods=["POST"])
def resubmit_label(_id):
    authenticate({"ComplianceOfficer"})
    ent = get_or_404("label_applications", _id)
    if ent["status"] != "NEEDS_CORRECTION":
        raise ApiError("ERR_INVALID_STATE", 409, "label not NEEDS_CORRECTION")
    ent["status"] = "SUBMITTED"
    ent["correction_notes"] = None
    touch(ent)
    return success(ser_label(ent), status=200)


# ===========================================================================
# BottlingRun
# ===========================================================================
def intervals_overlap(a_start, a_end, b_start, b_end):
    # half-open [start, end); touching (a_end == b_start) does not overlap
    return a_start < b_end and b_start < a_end


@app.route("/dsp/bottling-runs", methods=["POST"])
def create_bottling():
    authenticate({"ProductionManager"})
    body = get_body()
    barrel_id = req_str(body, "barrel_id")
    barrel = get_or_404("barrels", barrel_id)
    label_id = req_str(body, "label_application_id")
    get_or_404("label_applications", label_id)
    line_id = req_enum(body, "line_id", LINE_IDS)
    start_raw = req_str(body, "scheduled_start")
    end_raw = req_str(body, "scheduled_end")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if end_dt <= start_dt:
        v_error("scheduled_end must be after scheduled_start")
    bottle_size = req_number(body, "bottle_size_ml", positive=True)
    bottles_per_case = req_int(body, "bottles_per_case", positive=True)
    planned_cases = req_int(body, "planned_cases", positive=True)
    # line contention
    for other in DB["bottling_runs"].values():
        if other["line_id"] != line_id:
            continue
        if other["status"] not in ("SCHEDULED", "BOTTLING"):
            continue
        if intervals_overlap(start_dt, end_dt, other["_start_dt"], other["_end_dt"]):
            raise ApiError("ERR_LINE_CONFLICT", 409, "bottling line interval overlaps")
    run = DB["distillation_runs"].get(barrel["distillation_run_id"])
    dist_id = run["distillery_id"] if run else barrel.get("distillery_id")
    ent = new_entity({
        "barrel_id": barrel_id,
        "label_application_id": label_id,
        "distillery_id": dist_id,
        "line_id": line_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "bottle_size_ml": bottle_size,
        "bottles_per_case": bottles_per_case,
        "planned_cases": planned_cases,
        "draw_proof_gallons": Decimal("0"),
        "bottled_proof_gallons": Decimal("0"),
        "bottling_loss_pg": Decimal("0"),
        "cases_bottled": 0,
        "cases_available": 0,
        "cases_reserved": 0,
        "cases_shipped": 0,
        "cases_removed": 0,
        "tax_status": "IN_BOND",
        "inventory_status": "IN_STOCK",
        "status": "SCHEDULED",
    })
    DB["bottling_runs"][ent["id"]] = ent
    return success(ser_bottling(ent), status=201)


@app.route("/dsp/bottling-runs/<_id>", methods=["GET"])
def get_bottling(_id):
    authenticate({"ProductionManager", "ComplianceOfficer", "SalesManager"})
    return success(ser_bottling(get_or_404("bottling_runs", _id)), status=200)


@app.route("/dsp/bottling-runs", methods=["GET"])
def list_bottling():
    authenticate({"ProductionManager", "ComplianceOfficer", "SalesManager"})
    rows = list(DB["bottling_runs"].values())
    barrel_id = request.args.get("barrel_id")
    label_id = request.args.get("label_application_id")
    dist_id = request.args.get("distillery_id")
    if barrel_id is not None:
        rows = [r for r in rows if r["barrel_id"] == barrel_id]
    if label_id is not None:
        rows = [r for r in rows if r["label_application_id"] == label_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_bottling)


@app.route("/dsp/bottling-runs/<_id>/start", methods=["POST"])
def start_bottling(_id):
    authenticate({"ProductionManager"})
    run = get_or_404("bottling_runs", _id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "bottling run not SCHEDULED")
    label = DB["label_applications"].get(run["label_application_id"])
    if label is None or label["status"] != "APPROVED":
        raise ApiError("ERR_LABEL_NOT_APPROVED", 409, "label not APPROVED")
    barrel = DB["barrels"].get(run["barrel_id"])
    if barrel is None or barrel["status"] != "AGING":
        raise ApiError("ERR_BARREL_NOT_AGING", 409, "barrel not AGING")
    run["status"] = "BOTTLING"
    touch(run)
    return success(ser_bottling(run), status=200)


@app.route("/dsp/bottling-runs/<_id>/complete", methods=["POST"])
def complete_bottling(_id):
    authenticate({"ProductionManager"})
    run = get_or_404("bottling_runs", _id)
    if run["status"] != "BOTTLING":
        raise ApiError("ERR_INVALID_STATE", 409, "bottling run not BOTTLING")
    label = DB["label_applications"][run["label_application_id"]]
    barrel = DB["barrels"][run["barrel_id"]]
    # bottled proof gallons: sum-then-round
    cases_bottled = run["planned_cases"]
    total_ml = dec(cases_bottled) * dec(run["bottles_per_case"]) * dec(run["bottle_size_ml"])
    wine_gallons = total_ml / ML_PER_GALLON
    bottled_pg = round_pg(wine_gallons * dec(label["label_proof"]) / Decimal("100"))
    # barrel current pg at completion clock
    angel, current = barrel_angel_and_current(barrel)
    if current < bottled_pg:
        raise ApiError("ERR_INSUFFICIENT_PROOF_GALLONS", 409,
                       "barrel current proof gallons cannot cover bottled")
    draw_pg = current
    loss_pg = draw_pg - bottled_pg
    if loss_pg < 0:
        loss_pg = Decimal("0")
    run["draw_proof_gallons"] = draw_pg
    run["bottled_proof_gallons"] = bottled_pg
    run["bottling_loss_pg"] = loss_pg
    run["cases_bottled"] = cases_bottled
    run["cases_available"] = cases_bottled
    run["cases_reserved"] = 0
    run["cases_shipped"] = 0
    run["cases_removed"] = 0
    run["inventory_status"] = "IN_STOCK"
    run["tax_status"] = "IN_BOND"
    run["status"] = "COMPLETED"
    touch(run)
    # ledger
    dist = DB["distilleries"][run["distillery_id"]]
    dist["storage_account_pg"] -= draw_pg
    dist["processing_account_pg"] += bottled_pg
    dist["bottling_losses_pg"] += loss_pg
    # barrel emptied (cascade hop 2)
    dist["angel_share_losses_pg"] += angel
    dist["storage_account_pg"] -= angel
    recompute_bonded(dist)
    touch(dist)
    barrel["angel_share_pg"] = angel
    barrel["current_proof_gallons"] = Decimal("0")
    barrel["_frozen"] = True
    barrel["status"] = "EMPTIED"
    touch(barrel)
    # cascade hop 3/4
    drun = DB["distillation_runs"].get(barrel["distillation_run_id"])
    if drun is not None:
        drun["open_barrel_count"] -= 1
        touch(drun)
        close_run_cascade(drun)
    return success(ser_bottling(run), status=200)


@app.route("/dsp/bottling-runs/<_id>/cancel", methods=["POST"])
def cancel_bottling(_id):
    authenticate({"ProductionManager"})
    run = get_or_404("bottling_runs", _id)
    if run["status"] != "SCHEDULED":
        raise ApiError("ERR_INVALID_STATE", 409, "bottling run not SCHEDULED")
    run["status"] = "CANCELLED"
    touch(run)
    return success(ser_bottling(run), status=200)


# ===========================================================================
# TaxRemoval
# ===========================================================================
@app.route("/dsp/tax-removals", methods=["POST"])
def create_tax_removal():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    run_id = req_str(body, "bottling_run_id")
    run = get_or_404("bottling_runs", run_id)
    reason = req_enum(body, "removal_reason", REMOVAL_REASONS)
    removed_cases = req_int(body, "removed_cases", positive=True)
    if run["status"] != "COMPLETED":
        raise ApiError("ERR_INVALID_STATE", 409, "bottling run not COMPLETED")
    if run["cases_available"] < removed_cases:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409, "not enough cases available")
    # pro-rated proof gallons
    ratio = dec(removed_cases) / dec(run["cases_bottled"])
    removed_pg = round_pg(dec(run["bottled_proof_gallons"]) * ratio)
    dist = DB["distilleries"][run["distillery_id"]]
    if reason == "TAXPAID":
        if dist["bonded_total_pg"] < removed_pg:
            raise ApiError("ERR_INSUFFICIENT_BONDED_PG", 409,
                           "removal exceeds bonded proof gallons")
        y = dist["cbma_pg_removed_ytd"]
        reduced = max(Decimal("0"), min(removed_pg, CBMA_TIER_LIMIT_PG - y))
        standard = removed_pg - reduced
        cents = round_cents(reduced * CBMA_REDUCED_RATE_CENTS + standard * STANDARD_RATE_CENTS)
    else:
        reduced = Decimal("0")
        standard = Decimal("0")
        cents = 0
    clk = clock_now()
    ent = new_entity({
        "bottling_run_id": run_id,
        "distillery_id": run["distillery_id"],
        "removal_reason": reason,
        "removed_cases": removed_cases,
        "removed_proof_gallons": removed_pg,
        "reduced_rate_pg": reduced,
        "standard_rate_pg": standard,
        "excise_tax_due_cents": cents,
        "removal_date": fmt_iso(clk),
        "_removal_dt": clk,
        "status": "DETERMINED",
    })
    DB["tax_removals"][ent["id"]] = ent
    # inventory
    run["cases_available"] -= removed_cases
    run["cases_removed"] += removed_cases
    recompute_inventory_status(run)
    if reason == "TAXPAID":
        run["tax_status"] = "TAX_DETERMINED"
    touch(run)
    # ledger for TAXPAID
    if reason == "TAXPAID":
        dist["processing_account_pg"] -= removed_pg
        dist["removed_pg"] += removed_pg
        dist["cbma_pg_removed_ytd"] += removed_pg
        recompute_cbma_tier(dist)
        recompute_bonded(dist)
        touch(dist)
    # cascade B: auto-cancel PENDING orders when SOLD_OUT
    if run["inventory_status"] == "SOLD_OUT":
        for order in DB["sales_orders"].values():
            if order["bottling_run_id"] == run_id and order["fulfillment_status"] == "PENDING":
                order["fulfillment_status"] = "CANCELLED"
                touch(order)
    return success(ser_tax(ent), status=201)


@app.route("/dsp/tax-removals/<_id>", methods=["GET"])
def get_tax_removal(_id):
    authenticate({"ComplianceOfficer"})
    return success(ser_tax(get_or_404("tax_removals", _id)), status=200)


@app.route("/dsp/tax-removals", methods=["GET"])
def list_tax_removals():
    authenticate({"ComplianceOfficer"})
    rows = list(DB["tax_removals"].values())
    run_id = request.args.get("bottling_run_id")
    dist_id = request.args.get("distillery_id")
    if run_id is not None:
        rows = [r for r in rows if r["bottling_run_id"] == run_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_tax)


# ===========================================================================
# ExciseReport
# ===========================================================================
MONTH_RE = re.compile(r"^\d{4}-\d{2}$")


@app.route("/dsp/excise-reports", methods=["POST"])
def create_excise():
    authenticate({"ComplianceOfficer"})
    body = get_body()
    dist_id = req_str(body, "distillery_id")
    dist = get_or_404("distilleries", dist_id)
    period = req_str(body, "period_month")
    if not MONTH_RE.match(period):
        v_error("period_month must be YYYY-MM")
    expected = req_int(body, "expected_distillery_version", positive=False)
    # OCC
    if expected != dist["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "stale distillery version")
    # totals from TAXPAID removals in period
    total_pg = Decimal("0")
    total_cents = 0
    for rem in DB["tax_removals"].values():
        if rem["distillery_id"] != dist_id:
            continue
        if rem["removal_reason"] != "TAXPAID":
            continue
        rd = rem["_removal_dt"]
        if "%04d-%02d" % (rd.year, rd.month) == period:
            total_pg += dec(rem["removed_proof_gallons"])
            total_cents += rem["excise_tax_due_cents"]
    # supersede prior FILED report for same period
    supersedes = None
    for rep in DB["excise_reports"].values():
        if (rep["distillery_id"] == dist_id and rep["period_month"] == period
                and rep["status"] == "FILED"):
            rep["status"] = "SUPERSEDED"
            touch(rep)
            supersedes = rep["id"]
            break
    ent = new_entity({
        "distillery_id": dist_id,
        "period_month": period,
        "expected_distillery_version": expected,
        "total_removed_pg": total_pg,
        "total_excise_due_cents": total_cents,
        "supersedes_report_id": supersedes,
        "status": "FILED",
    })
    DB["excise_reports"][ent["id"]] = ent
    # filing advances distillery version
    touch(dist)
    return success(ser_excise(ent), status=201)


@app.route("/dsp/excise-reports/<_id>", methods=["GET"])
def get_excise(_id):
    authenticate({"ComplianceOfficer"})
    return success(ser_excise(get_or_404("excise_reports", _id)), status=200)


@app.route("/dsp/excise-reports", methods=["GET"])
def list_excise():
    authenticate({"ComplianceOfficer"})
    rows = list(DB["excise_reports"].values())
    dist_id = request.args.get("distillery_id")
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_excise)


# ===========================================================================
# Customer
# ===========================================================================
@app.route("/dsp/customers", methods=["POST"])
def create_customer():
    authenticate({"SalesManager", "TastingRoomStaff"})
    body = get_body()
    name = req_str(body, "name")
    email = req_str(body, "email")
    state_code = req_str(body, "state_code")
    club_tier = opt_enum(body, "club_tier", CLUB_TIERS, "NONE")
    age_verified = opt_bool(body, "age_verified", False)
    ent = new_entity({
        "name": name,
        "email": email,
        "state_code": state_code,
        "club_tier": club_tier,
        "age_verified": age_verified,
    })
    DB["customers"][ent["id"]] = ent
    return success(ser_customer(ent), status=201)


@app.route("/dsp/customers/<_id>", methods=["GET"])
def get_customer(_id):
    authenticate({"SalesManager", "TastingRoomStaff", "Customer"})
    ent = get_or_404("customers", _id)
    if is_customer() and _id != g.get("user_id"):
        raise ApiError("ERR_FORBIDDEN", 403, "customer may only read its own record")
    return success(ser_customer(ent), status=200)


@app.route("/dsp/customers", methods=["GET"])
def list_customers():
    authenticate({"SalesManager", "TastingRoomStaff"})
    return paginate(list(DB["customers"].values()), ser_customer)


# ===========================================================================
# SalesOrder
# ===========================================================================
@app.route("/dsp/sales-orders", methods=["POST"])
def create_order():
    authenticate({"SalesManager", "TastingRoomStaff", "Customer"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    customer = get_or_404("customers", customer_id)
    run_id = req_str(body, "bottling_run_id")
    run = get_or_404("bottling_runs", run_id)
    check_owner(customer_id)
    channel = req_enum(body, "channel", CHANNELS)
    cases = req_int(body, "cases", positive=True)
    unit_price = req_int(body, "unit_price_cents", positive=True, allow_zero=True)
    includes_cocktail = opt_bool(body, "includes_cocktail", False)
    subtotal = unit_price * cases
    total = subtotal + (COCKTAIL_SURCHARGE_CENTS if includes_cocktail else 0)
    ent = new_entity({
        "customer_id": customer_id,
        "bottling_run_id": run_id,
        "distillery_id": run["distillery_id"],
        "channel": channel,
        "cases": cases,
        "unit_price_cents": unit_price,
        "includes_cocktail": includes_cocktail,
        "subtotal_cents": subtotal,
        "total_cents": total,
        "payment_status": "UNPAID",
        "fulfillment_status": "PENDING",
    })
    DB["sales_orders"][ent["id"]] = ent
    return success(ser_order(ent), status=201)


@app.route("/dsp/sales-orders/<_id>", methods=["GET"])
def get_order(_id):
    authenticate({"SalesManager", "TastingRoomStaff", "Customer"})
    ent = get_or_404("sales_orders", _id)
    check_owner(ent["customer_id"])
    return success(ser_order(ent), status=200)


@app.route("/dsp/sales-orders", methods=["GET"])
def list_orders():
    authenticate({"SalesManager", "TastingRoomStaff", "Customer"})
    rows = list(DB["sales_orders"].values())
    if is_customer():
        rows = [r for r in rows if r["customer_id"] == g.get("user_id")]
    customer_id = request.args.get("customer_id")
    run_id = request.args.get("bottling_run_id")
    dist_id = request.args.get("distillery_id")
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if run_id is not None:
        rows = [r for r in rows if r["bottling_run_id"] == run_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_order)


@app.route("/dsp/sales-orders/<_id>/pay", methods=["POST"])
def pay_order(_id):
    authenticate({"SalesManager", "Customer"})
    order = get_or_404("sales_orders", _id)
    check_owner(order["customer_id"])
    if order["payment_status"] != "UNPAID" or order["fulfillment_status"] != "PENDING":
        raise ApiError("ERR_INVALID_STATE", 409, "order not UNPAID/PENDING")
    customer = DB["customers"][order["customer_id"]]
    if not customer["age_verified"]:
        raise ApiError("ERR_AGE_NOT_VERIFIED", 403, "customer age not verified")
    run = DB["bottling_runs"][order["bottling_run_id"]]
    if order["channel"] == "CLUB":
        dist = DB["distilleries"][order["distillery_id"]]
        if not dist["club_release_active"] or customer["club_tier"] == "NONE":
            raise ApiError("ERR_CLUB_NOT_ELIGIBLE", 409, "club order not eligible")
    if run["cases_available"] < order["cases"]:
        raise ApiError("ERR_INSUFFICIENT_INVENTORY", 409, "not enough cases available")
    order["payment_status"] = "PAID"
    order["fulfillment_status"] = "ALLOCATED"
    touch(order)
    run["cases_available"] -= order["cases"]
    run["cases_reserved"] += order["cases"]
    recompute_inventory_status(run)
    touch(run)
    return success(ser_order(order), status=200)


@app.route("/dsp/sales-orders/<_id>/ship", methods=["POST"])
def ship_order(_id):
    authenticate({"SalesManager"})
    order = get_or_404("sales_orders", _id)
    if order["fulfillment_status"] != "ALLOCATED" or order["payment_status"] != "PAID":
        raise ApiError("ERR_INVALID_STATE", 409, "order not ALLOCATED/PAID")
    run = DB["bottling_runs"][order["bottling_run_id"]]
    if order["channel"] == "THREE_TIER" and run["tax_status"] != "TAX_DETERMINED":
        raise ApiError("ERR_NOT_TAX_DETERMINED", 409, "goods not tax-determined")
    order["fulfillment_status"] = "SHIPPED"
    touch(order)
    run["cases_reserved"] -= order["cases"]
    run["cases_shipped"] += order["cases"]
    touch(run)
    return success(ser_order(order), status=200)


@app.route("/dsp/sales-orders/<_id>/cancel", methods=["POST"])
def cancel_order(_id):
    authenticate({"SalesManager", "Customer"})
    order = get_or_404("sales_orders", _id)
    check_owner(order["customer_id"])
    if order["fulfillment_status"] not in ("PENDING", "ALLOCATED"):
        raise ApiError("ERR_INVALID_STATE", 409, "order not PENDING/ALLOCATED")
    was_allocated = order["fulfillment_status"] == "ALLOCATED"
    order["fulfillment_status"] = "CANCELLED"
    touch(order)
    if was_allocated:
        run = DB["bottling_runs"][order["bottling_run_id"]]
        run["cases_reserved"] -= order["cases"]
        run["cases_available"] += order["cases"]
        recompute_inventory_status(run)
        touch(run)
    return success(ser_order(order), status=200)


@app.route("/dsp/sales-orders/<_id>/refund", methods=["POST"])
def refund_order(_id):
    authenticate({"SalesManager"})
    order = get_or_404("sales_orders", _id)
    if order["payment_status"] != "PAID" or order["fulfillment_status"] != "CANCELLED":
        raise ApiError("ERR_INVALID_STATE", 409, "order not PAID/CANCELLED")
    order["payment_status"] = "REFUNDED"
    touch(order)
    return success(ser_order(order), status=200)


# ===========================================================================
# TourBooking
# ===========================================================================
@app.route("/dsp/tour-bookings", methods=["POST"])
def create_tour():
    authenticate({"TastingRoomStaff", "Customer"})
    body = get_body()
    customer_id = req_str(body, "customer_id")
    get_or_404("customers", customer_id)
    dist_id = req_str(body, "distillery_id")
    get_or_404("distilleries", dist_id)
    check_owner(customer_id)
    start_raw = req_str(body, "start_time")
    end_raw = req_str(body, "end_time")
    start_dt = parse_iso(start_raw)
    end_dt = parse_iso(end_raw)
    if end_dt <= start_dt:
        v_error("end_time must be after start_time")
    party_size = req_int(body, "party_size", positive=True)
    includes_tasting = opt_bool(body, "includes_tasting", False)
    ent = new_entity({
        "customer_id": customer_id,
        "distillery_id": dist_id,
        "start_time": start_raw,
        "end_time": end_raw,
        "_start_dt": start_dt,
        "_end_dt": end_dt,
        "party_size": party_size,
        "includes_tasting": includes_tasting,
        "status": "REQUESTED",
    })
    DB["tour_bookings"][ent["id"]] = ent
    return success(ser_tour(ent), status=201)


@app.route("/dsp/tour-bookings/<_id>", methods=["GET"])
def get_tour(_id):
    authenticate({"TastingRoomStaff", "Customer"})
    ent = get_or_404("tour_bookings", _id)
    check_owner(ent["customer_id"])
    return success(ser_tour(ent), status=200)


@app.route("/dsp/tour-bookings", methods=["GET"])
def list_tours():
    authenticate({"TastingRoomStaff", "Customer"})
    rows = list(DB["tour_bookings"].values())
    if is_customer():
        rows = [r for r in rows if r["customer_id"] == g.get("user_id")]
    customer_id = request.args.get("customer_id")
    dist_id = request.args.get("distillery_id")
    if customer_id is not None:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if dist_id is not None:
        rows = [r for r in rows if r["distillery_id"] == dist_id]
    return paginate(rows, ser_tour)


@app.route("/dsp/tour-bookings/<_id>/confirm", methods=["POST"])
def confirm_tour(_id):
    authenticate({"TastingRoomStaff"})
    tour = get_or_404("tour_bookings", _id)
    if tour["status"] != "REQUESTED":
        raise ApiError("ERR_INVALID_STATE", 409, "tour not REQUESTED")
    buffer = timedelta(minutes=TOUR_BUFFER_MINUTES)
    # overlap (buffer) check
    for other in DB["tour_bookings"].values():
        if other["id"] == tour["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if other["distillery_id"] != tour["distillery_id"]:
            continue
        if abs(other["_start_dt"] - tour["_start_dt"]) < buffer:
            raise ApiError("ERR_TOUR_OVERLAP", 409, "confirmed tour within buffer")
    # capacity check
    total = tour["party_size"]
    for other in DB["tour_bookings"].values():
        if other["id"] == tour["id"]:
            continue
        if other["status"] != "CONFIRMED":
            continue
        if other["distillery_id"] != tour["distillery_id"]:
            continue
        if intervals_overlap(tour["_start_dt"], tour["_end_dt"],
                             other["_start_dt"], other["_end_dt"]):
            total += other["party_size"]
    if total > TASTING_ROOM_CAPACITY:
        raise ApiError("ERR_TOUR_CAPACITY", 409, "exceeds tasting-room capacity")
    tour["status"] = "CONFIRMED"
    touch(tour)
    return success(ser_tour(tour), status=200)


@app.route("/dsp/tour-bookings/<_id>/cancel", methods=["POST"])
def cancel_tour(_id):
    authenticate({"TastingRoomStaff", "Customer"})
    tour = get_or_404("tour_bookings", _id)
    check_owner(tour["customer_id"])
    if tour["status"] not in ("REQUESTED", "CONFIRMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "tour not REQUESTED/CONFIRMED")
    tour["status"] = "CANCELLED"
    touch(tour)
    return success(ser_tour(tour), status=200)


# ---------------------------------------------------------------------------
reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
