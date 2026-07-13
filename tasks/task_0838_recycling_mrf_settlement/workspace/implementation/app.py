"""Recycling MRF & Commodity Settlement API.

A single-file Flask implementation. Storage is entirely in-memory (module-level
dicts). Every boot starts with an empty store and a logical clock pinned to
2026-03-01T00:00:00Z. No entities are seeded.
"""

import os
import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
ROLES = {"ScaleOperator", "SortManager", "CommodityTrader", "SettlementClerk", "Municipality"}
ALL_READ_ROLES = ["ScaleOperator", "SortManager", "CommodityTrader", "SettlementClerk", "Municipality"]

COMMODITIES = {"OCC", "MIXED_PAPER", "PET", "HDPE", "ALUMINUM", "STEEL", "GLASS"}
GRADES = {"A", "B", "C"}
GRADE_MULT = {"A": Decimal("1.00"), "B": Decimal("0.90"), "C": Decimal("0.75")}

CLEAN_THRESHOLD_PCT = Decimal("5.0")
PENALTY_THRESHOLD_PCT = Decimal("12.0")
REJECT_THRESHOLD_PCT = Decimal("40.0")
CLEAN_REBATE_CENTS_PER_TON = Decimal("300")
PENALTY_CENTS_PER_TON_PER_POINT = Decimal("150")

DEFAULT_CLOCK = "2026-03-01T00:00:00Z"

# ---------------------------------------------------------------------------
# In-memory store (wiped on every process start)
# ---------------------------------------------------------------------------
municipalities = {}
mills = {}
indices = {}
sortlines = {}
downtimes = {}
loads = {}
bales = {}
shipments = {}
statements = {}
postings = {}

_seq_counter = [0]
CLOCK = {"now": None}  # datetime aware UTC


def _reset_state():
    for d in (municipalities, mills, indices, sortlines, downtimes, loads,
              bales, shipments, statements, postings):
        d.clear()
    _seq_counter[0] = 0
    CLOCK["now"] = parse_iso(DEFAULT_CLOCK)


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
# Time helpers
# ---------------------------------------------------------------------------
def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z") or t.endswith("z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}" + "Z"


def clock_now_str():
    return fmt_iso(CLOCK["now"])


def real_now_str():
    return fmt_iso(datetime.now(timezone.utc))


# ---------------------------------------------------------------------------
# Numeric helpers
# ---------------------------------------------------------------------------
def D(x):
    return Decimal(str(x))


def rhu(dec_value):
    """Round-half-up a Decimal to an integer number of cents."""
    return int(dec_value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q3(x):
    return float(D(x).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def q2(x):
    return float(D(x).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Identity / sequence helpers
# ---------------------------------------------------------------------------
def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def new_id():
    return str(uuid.uuid4())


def gen_request_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def common_fields():
    ts = clock_now_str()
    return {"id": new_id(), "created_at": ts, "updated_at": ts, "version": 1, "_seq": next_seq()}


def event_fields():
    return {"id": new_id(), "created_at": clock_now_str(), "_seq": next_seq()}


def touch(entity):
    entity["updated_at"] = clock_now_str()
    entity["version"] = entity.get("version", 1) + 1


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def meta_base():
    return {"api_request_id": gen_request_id(), "api_request_timestamp": real_now_str()}


def serialize(entity):
    return {k: v for k, v in entity.items() if not k.startswith("_")}


def success(data, response_type="object", code=200, pagination=None):
    meta = meta_base()
    if pagination:
        meta.update(pagination)
    return jsonify({"meta": meta, "response_type": response_type, "data": data}), code


def error_response(error_id, http_status, message):
    meta = meta_base()
    body = {"meta": meta, "response_type": "error",
            "data": {"error_id": error_id, "message": message}}
    return jsonify(body), http_status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err.error_id, err.http_status, err.message)


@app.errorhandler(404)
def handle_404(_e):
    return error_response("ERR_NOT_FOUND", 404, "Resource not found")


@app.errorhandler(405)
def handle_405(_e):
    return error_response("ERR_NOT_FOUND", 404, "Method not allowed")


@app.errorhandler(Exception)
def handle_uncaught(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    return error_response("ERR_INTERNAL", 500, str(err))


# ---------------------------------------------------------------------------
# Auth / body helpers
# ---------------------------------------------------------------------------
def require_auth(allowed_roles):
    uid = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not uid or role not in ROLES:
        raise ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                       "Missing or invalid X-User-ID / X-User-Role headers")
    if role not in allowed_roles:
        raise ApiError("ERR_INSUFFICIENT_PERMISSIONS", 403,
                       "Role not permitted for this operation")
    return uid, role


def get_body():
    if request.data and len(request.data) > 0:
        data = request.get_json(silent=True)
        if data is None or not isinstance(data, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Malformed request body")
        return data
    return {}


def req_str(b, k):
    v = b.get(k)
    if k not in b or not isinstance(v, str) or v == "":
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid field: {k}")
    return v


def opt_str(b, k):
    if k not in b or b[k] is None:
        return None
    v = b[k]
    if not isinstance(v, str):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid field: {k}")
    return v


def req_num(b, k):
    v = b.get(k)
    if k not in b or isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid numeric field: {k}")
    return v


def req_int(b, k):
    v = b.get(k)
    if k not in b or isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Missing or invalid integer field: {k}")
    return v


def opt_int(b, k, default):
    if k not in b or b[k] is None:
        return default
    v = b[k]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid integer field: {k}")
    return v


def req_dt(b, k):
    s = req_str(b, k)
    try:
        parse_iso(s)
    except Exception:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid datetime field: {k}")
    return s


def req_enum(b, k, allowed):
    v = req_str(b, k)
    if v not in allowed:
        raise ApiError("ERR_INVALID_REQUEST", 400, f"Invalid enum value for {k}")
    return v


def paginate(items):
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = 10
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid limit")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    offset = 0
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid offset")
        if offset < 0:
            offset = 0
    total = len(items)
    page = items[offset:offset + limit]
    pagination = {"limit": limit, "offset": offset, "total_count": total,
                  "has_more": offset + len(page) < total}
    return page, pagination


def sorted_by_creation(items):
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(store, rid, err_id):
    ent = store.get(rid)
    if ent is None:
        raise ApiError(err_id, 404, "Resource not found")
    return ent


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def contamination_adjustment(net_tons, contamination_pct):
    """Returns signed integer cents: positive rebate, negative penalty, 0 otherwise."""
    net = D(net_tons)
    c = D(contamination_pct)
    if c <= CLEAN_THRESHOLD_PCT:
        return rhu(net * CLEAN_REBATE_CENTS_PER_TON)
    if c >= PENALTY_THRESHOLD_PCT:
        points_over = c - PENALTY_THRESHOLD_PCT
        return -rhu(net * points_over * PENALTY_CENTS_PER_TON_PER_POINT)
    return 0


def bale_gross_value(net_tons, moisture_pct, grade, index_price):
    effective = D(net_tons) * (Decimal(1) - D(moisture_pct) / Decimal(100))
    return rhu(effective * D(index_price) * GRADE_MULT[grade])


def index_in_force(commodity, at_dt):
    for idx in indices.values():
        if idx["status"] != "PUBLISHED" or idx["commodity"] != commodity:
            continue
        start = parse_iso(idx["effective_start"])
        end = parse_iso(idx["effective_end"])
        if start <= at_dt < end:
            return idx
    return None


# ---------------------------------------------------------------------------
# Municipal ledger helpers
# ---------------------------------------------------------------------------
def recompute_balance(muni):
    muni["balance_cents"] = (muni["revenue_share_accrued_cents"]
                             + muni["lifetime_rebate_cents"]
                             - muni["lifetime_penalty_cents"])


def create_posting(muni, posting_type, amount_cents, related_bale_id=None, related_load_id=None):
    posting = event_fields()
    posting.update({
        "municipality_id": muni["id"],
        "posting_type": posting_type,
        "amount_cents": amount_cents,
        "related_bale_id": related_bale_id,
        "related_load_id": related_load_id,
        "reversed": False,
    })
    postings[posting["id"]] = posting

    if posting_type in ("REVENUE_SHARE", "REVERSAL"):
        muni["revenue_share_accrued_cents"] += amount_cents
    elif posting_type == "REBATE":
        muni["lifetime_rebate_cents"] += amount_cents
    elif posting_type == "PENALTY":
        muni["lifetime_penalty_cents"] += -amount_cents  # stored magnitude (positive)
    recompute_balance(muni)
    touch(muni)
    return posting


# ---------------------------------------------------------------------------
# Derived-field recomputation
# ---------------------------------------------------------------------------
def recompute_sortline(line):
    processed = Decimal(0)
    for ld in loads.values():
        if ld["sort_line_id"] == line["id"] and ld["status"] == "CLOSED":
            processed += D(ld["net_tons"])
    downtime = 0
    for ev in downtimes.values():
        if ev["sort_line_id"] == line["id"]:
            downtime += ev["downtime_minutes"]
    line["total_processed_tons"] = float(processed.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    line["total_downtime_minutes"] = downtime
    uptime_hours = (D(line["scheduled_shift_minutes"]) - D(downtime)) / Decimal(60)
    if uptime_hours > 0:
        line["throughput_tph"] = q2(processed / uptime_hours)
    else:
        line["throughput_tph"] = 0


def recompute_load_mass(load):
    baled = Decimal(0)
    for b in bales.values():
        if b["source_load_id"] == load["id"] and b["status"] != "VOIDED":
            baled += D(b["net_tons"])
    load["baled_tons"] = float(baled.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))
    remaining = D(load["net_tons"]) - baled - D(load["residual_tons"])
    load["unbaled_remaining_tons"] = float(remaining.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


def recompute_shipment_tons(sh):
    total = Decimal(0)
    for b in bales.values():
        if b["shipment_id"] == sh["id"] and b["status"] != "VOIDED":
            total += D(b["net_tons"])
    sh["total_net_tons"] = float(total.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP))


# ===========================================================================
# Logical clock
# ===========================================================================
@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth(["ScaleOperator", "SortManager", "CommodityTrader", "SettlementClerk"])
    body = get_body()
    to_iso = req_dt(body, "to_iso8601")
    CLOCK["now"] = parse_iso(to_iso)
    return success({}, response_type="object", code=200)


# ===========================================================================
# Municipality
# ===========================================================================
@app.route("/mrf/municipalities", methods=["POST"])
def create_municipality():
    require_auth(["SettlementClerk"])
    body = get_body()
    name = req_str(body, "name")
    contact_email = opt_str(body, "contact_email")
    revenue_share_pct = req_num(body, "revenue_share_pct")
    # fiscal range (priority 10)
    if not (0 <= revenue_share_pct <= 1):
        raise ApiError("ERR_REVENUE_SHARE_PCT_OUT_OF_RANGE", 422, "revenue_share_pct outside [0,1]")
    m = common_fields()
    m.update({
        "name": name,
        "contact_email": contact_email,
        "revenue_share_pct": revenue_share_pct,
        "status": "ACTIVE",
        "revenue_share_accrued_cents": 0,
        "lifetime_rebate_cents": 0,
        "lifetime_penalty_cents": 0,
        "balance_cents": 0,
    })
    municipalities[m["id"]] = m
    return success(serialize(m), response_type="object", code=201)


@app.route("/mrf/municipalities/<municipality_id>", methods=["GET"])
def get_municipality(municipality_id):
    require_auth(ALL_READ_ROLES)
    m = get_or_404(municipalities, municipality_id, "ERR_MUNICIPALITY_NOT_FOUND")
    return success(serialize(m), response_type="object", code=200)


# ===========================================================================
# Mill
# ===========================================================================
@app.route("/mrf/mills", methods=["POST"])
def create_mill():
    require_auth(["CommodityTrader"])
    body = get_body()
    name = req_str(body, "name")
    commodity_focus = req_enum(body, "commodity_focus", COMMODITIES)
    freight_rate = req_int(body, "freight_rate_cents_per_ton")
    m = common_fields()
    m.update({
        "name": name,
        "commodity_focus": commodity_focus,
        "freight_rate_cents_per_ton": freight_rate,
        "status": "ACTIVE",
    })
    mills[m["id"]] = m
    return success(serialize(m), response_type="object", code=201)


@app.route("/mrf/mills/<mill_id>", methods=["GET"])
def get_mill(mill_id):
    require_auth(ALL_READ_ROLES)
    m = get_or_404(mills, mill_id, "ERR_MILL_NOT_FOUND")
    return success(serialize(m), response_type="object", code=200)


# ===========================================================================
# CommodityIndex
# ===========================================================================
@app.route("/mrf/commodity-indices", methods=["POST"])
def create_index():
    require_auth(["CommodityTrader"])
    body = get_body()
    commodity = req_enum(body, "commodity", COMMODITIES)
    price = req_int(body, "price_cents_per_ton")
    effective_start = req_dt(body, "effective_start")
    effective_end = req_dt(body, "effective_end")
    idx = common_fields()
    idx.update({
        "commodity": commodity,
        "price_cents_per_ton": price,
        "effective_start": effective_start,
        "effective_end": effective_end,
        "status": "DRAFT",
    })
    indices[idx["id"]] = idx
    return success(serialize(idx), response_type="object", code=201)


@app.route("/mrf/commodity-indices", methods=["GET"])
def list_indices():
    require_auth(ALL_READ_ROLES)
    commodity = request.args.get("commodity")
    status = request.args.get("status")
    items = [i for i in indices.values()
             if (commodity is None or i["commodity"] == commodity)
             and (status is None or i["status"] == status)]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(i) for i in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/commodity-indices/<index_id>", methods=["GET"])
def get_index(index_id):
    require_auth(ALL_READ_ROLES)
    idx = get_or_404(indices, index_id, "ERR_INDEX_NOT_FOUND")
    return success(serialize(idx), response_type="object", code=200)


@app.route("/mrf/commodity-indices/<index_id>/publish", methods=["POST"])
def publish_index(index_id):
    require_auth(["CommodityTrader"])
    idx = get_or_404(indices, index_id, "ERR_INDEX_NOT_FOUND")
    # state (priority 5)
    if idx["status"] != "DRAFT":
        raise ApiError("ERR_INDEX_NOT_DRAFT", 409, "Index not in DRAFT")
    start = parse_iso(idx["effective_start"])
    end = parse_iso(idx["effective_end"])
    # interval feasibility
    if not (start < end):
        raise ApiError("ERR_INVALID_INTERVAL", 422, "effective_start must be < effective_end")
    # overlap with existing PUBLISHED for same commodity (half-open, adjacency allowed)
    for other in indices.values():
        if other["id"] == idx["id"] or other["status"] != "PUBLISHED" or other["commodity"] != idx["commodity"]:
            continue
        o_start = parse_iso(other["effective_start"])
        o_end = parse_iso(other["effective_end"])
        if start < o_end and o_start < end:
            raise ApiError("ERR_INDEX_WINDOW_OVERLAP", 409, "PUBLISHED index window overlap")
    idx["status"] = "PUBLISHED"
    touch(idx)
    # supersede the most recent adjacent prior PUBLISHED index for the same commodity
    priors = [o for o in indices.values()
              if o["id"] != idx["id"] and o["status"] == "PUBLISHED" and o["commodity"] == idx["commodity"]
              and parse_iso(o["effective_start"]) < start]
    if priors:
        prior = max(priors, key=lambda o: parse_iso(o["effective_start"]))
        if parse_iso(prior["effective_end"]) == start:
            prior["status"] = "SUPERSEDED"
            touch(prior)
    return success(serialize(idx), response_type="object", code=200)


# ===========================================================================
# SortLine
# ===========================================================================
@app.route("/mrf/sort-lines", methods=["POST"])
def create_sort_line():
    require_auth(["SortManager"])
    body = get_body()
    name = req_str(body, "name")
    rated_tph = req_num(body, "rated_tph")
    scheduled_shift_minutes = opt_int(body, "scheduled_shift_minutes", 480)
    line = common_fields()
    line.update({
        "name": name,
        "rated_tph": rated_tph,
        "scheduled_shift_minutes": scheduled_shift_minutes,
        "status": "IDLE",
        "total_processed_tons": 0,
        "total_downtime_minutes": 0,
        "throughput_tph": 0,
    })
    sortlines[line["id"]] = line
    return success(serialize(line), response_type="object", code=201)


@app.route("/mrf/sort-lines/<sort_line_id>", methods=["GET"])
def get_sort_line(sort_line_id):
    require_auth(ALL_READ_ROLES)
    line = get_or_404(sortlines, sort_line_id, "ERR_SORT_LINE_NOT_FOUND")
    return success(serialize(line), response_type="object", code=200)


# ===========================================================================
# DowntimeEvent
# ===========================================================================
@app.route("/mrf/downtime-events", methods=["POST"])
def create_downtime():
    require_auth(["SortManager"])
    body = get_body()
    sort_line_id = req_str(body, "sort_line_id")
    start_at = req_dt(body, "start_at")
    end_at = req_dt(body, "end_at")
    reason = req_str(body, "reason")
    line = get_or_404(sortlines, sort_line_id, "ERR_SORT_LINE_NOT_FOUND")
    s = parse_iso(start_at)
    e = parse_iso(end_at)
    # interval feasibility
    if not (e > s):
        raise ApiError("ERR_INVALID_INTERVAL", 422, "end_at must be after start_at")
    # overlap with existing events on same line (closed intervals; adjacency conflicts)
    for ev in downtimes.values():
        if ev["sort_line_id"] != sort_line_id:
            continue
        es = parse_iso(ev["start_at"])
        ee = parse_iso(ev["end_at"])
        if s <= ee and es <= e:
            raise ApiError("ERR_DOWNTIME_OVERLAP", 409, "Downtime window overlaps an existing event")
    downtime_minutes = int((e - s).total_seconds() // 60)
    ev = common_fields()
    ev.update({
        "sort_line_id": sort_line_id,
        "start_at": start_at,
        "end_at": end_at,
        "reason": reason,
        "downtime_minutes": downtime_minutes,
    })
    downtimes[ev["id"]] = ev
    recompute_sortline(line)
    touch(line)
    return success(serialize(ev), response_type="object", code=201)


@app.route("/mrf/downtime-events", methods=["GET"])
def list_downtimes():
    require_auth(ALL_READ_ROLES)
    sort_line_id = request.args.get("sort_line_id")
    items = [e for e in downtimes.values()
             if sort_line_id is None or e["sort_line_id"] == sort_line_id]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(e) for e in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/downtime-events/<downtime_event_id>", methods=["GET"])
def get_downtime(downtime_event_id):
    require_auth(ALL_READ_ROLES)
    ev = get_or_404(downtimes, downtime_event_id, "ERR_NOT_FOUND")
    return success(serialize(ev), response_type="object", code=200)


# ===========================================================================
# InboundLoad
# ===========================================================================
@app.route("/mrf/inbound-loads", methods=["POST"])
def create_inbound_load():
    require_auth(["ScaleOperator"])
    body = get_body()
    source_municipality_id = req_str(body, "source_municipality_id")
    sort_line_id = req_str(body, "sort_line_id")
    hauler = req_str(body, "hauler")
    gross_tons = req_num(body, "gross_tons")
    tare_tons = req_num(body, "tare_tons")
    # existence left-to-right
    get_or_404(municipalities, source_municipality_id, "ERR_MUNICIPALITY_NOT_FOUND")
    get_or_404(sortlines, sort_line_id, "ERR_SORT_LINE_NOT_FOUND")
    net_tons = q3(D(gross_tons) - D(tare_tons))
    load = common_fields()
    load.update({
        "source_municipality_id": source_municipality_id,
        "sort_line_id": sort_line_id,
        "hauler": hauler,
        "gross_tons": gross_tons,
        "tare_tons": tare_tons,
        "net_tons": net_tons,
        "sampled_contamination_pct": None,
        "audited_composition": None,
        "provisional_adjustment_cents": 0,
        "residual_tons": 0,
        "final_adjustment_cents": 0,
        "baled_tons": 0,
        "unbaled_remaining_tons": net_tons,
        "status": "RECEIVED",
    })
    loads[load["id"]] = load
    return success(serialize(load), response_type="object", code=201)


@app.route("/mrf/inbound-loads", methods=["GET"])
def list_inbound_loads():
    require_auth(ALL_READ_ROLES)
    smid = request.args.get("source_municipality_id")
    slid = request.args.get("sort_line_id")
    status = request.args.get("status")
    items = [l for l in loads.values()
             if (smid is None or l["source_municipality_id"] == smid)
             and (slid is None or l["sort_line_id"] == slid)
             and (status is None or l["status"] == status)]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(l) for l in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/inbound-loads/<load_id>", methods=["GET"])
def get_inbound_load(load_id):
    require_auth(ALL_READ_ROLES)
    load = get_or_404(loads, load_id, "ERR_LOAD_NOT_FOUND")
    return success(serialize(load), response_type="object", code=200)


@app.route("/mrf/inbound-loads/<load_id>/audit", methods=["POST"])
def audit_load(load_id):
    require_auth(["ScaleOperator"])
    body = get_body()
    load = get_or_404(loads, load_id, "ERR_LOAD_NOT_FOUND")
    # structural
    sampled = req_num(body, "sampled_contamination_pct")
    composition_raw = body.get("audited_composition")
    if not isinstance(composition_raw, list) or len(composition_raw) == 0:
        raise ApiError("ERR_INVALID_REQUEST", 400, "audited_composition must be a non-empty list")
    composition = []
    for entry in composition_raw:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400, "Invalid composition entry")
        c_commodity = req_enum(entry, "commodity", COMMODITIES)
        c_pct = req_num(entry, "pct")
        composition.append({"commodity": c_commodity, "pct": c_pct})
    # state (priority 5)
    if load["status"] not in ("RECEIVED", "PENDING_REAUDIT"):
        raise ApiError("ERR_LOAD_NOT_AUDITABLE", 409, "Load not in RECEIVED or PENDING_REAUDIT")
    # safety (priority 7): contamination processable
    if D(sampled) >= REJECT_THRESHOLD_PCT:
        raise ApiError("ERR_CONTAMINATION_UNPROCESSABLE", 422, "Contamination at or above reject threshold")
    # fiscal range (priority 10): percentages in [0,100]
    if not (0 <= sampled <= 100):
        raise ApiError("ERR_INVALID_REQUEST", 400, "sampled_contamination_pct out of range")
    for entry in composition:
        if not (0 <= entry["pct"] <= 100):
            raise ApiError("ERR_INVALID_REQUEST", 400, "composition pct out of range")
    load["sampled_contamination_pct"] = sampled
    load["audited_composition"] = composition
    load["provisional_adjustment_cents"] = contamination_adjustment(load["net_tons"], sampled)
    load["status"] = "AUDITED"
    touch(load)
    return success(serialize(load), response_type="object", code=200)


@app.route("/mrf/inbound-loads/<load_id>/request-reaudit", methods=["POST"])
def request_reaudit(load_id):
    require_auth(["SortManager"])
    body = get_body()
    load = get_or_404(loads, load_id, "ERR_LOAD_NOT_FOUND")
    req_str(body, "reason")
    if load["status"] != "AUDITED":
        raise ApiError("ERR_LOAD_INVALID_STATE", 409, "Load not in AUDITED")
    for b in bales.values():
        if b["source_load_id"] == load_id and b["status"] != "VOIDED":
            raise ApiError("ERR_LOAD_INVALID_STATE", 409, "Load has non-VOIDED bales")
    load["status"] = "PENDING_REAUDIT"
    touch(load)
    return success(serialize(load), response_type="object", code=200)


@app.route("/mrf/inbound-loads/<load_id>/close", methods=["POST"])
def close_load(load_id):
    require_auth(["SortManager"])
    body = get_body()
    load = get_or_404(loads, load_id, "ERR_LOAD_NOT_FOUND")
    residual_tons = req_num(body, "residual_tons")
    # state (priority 5)
    if load["status"] != "AUDITED":
        raise ApiError("ERR_LOAD_NOT_AUDITED", 409, "Load not in AUDITED")
    # quantity feasibility (priority 9)
    if D(residual_tons) + D(load["baled_tons"]) > D(load["net_tons"]):
        raise ApiError("ERR_RESIDUAL_EXCEEDS_NET", 422, "residual_tons + baled_tons exceeds net_tons")
    load["residual_tons"] = q3(residual_tons)
    recompute_load_mass(load)
    # final contamination (residual-derived), rounded to 4 decimals
    net = D(load["net_tons"])
    if net == 0:
        contamination = Decimal(0)
    else:
        contamination = (D(residual_tons) / net * Decimal(100)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    adj = contamination_adjustment(load["net_tons"], contamination)
    load["final_adjustment_cents"] = adj
    muni = municipalities[load["source_municipality_id"]]
    if adj > 0:
        create_posting(muni, "REBATE", adj, related_load_id=load["id"])
    elif adj < 0:
        create_posting(muni, "PENALTY", adj, related_load_id=load["id"])
    # sortline throughput recompute (after status flips to CLOSED so it counts this load)
    load["status"] = "CLOSED"
    line = sortlines.get(load["sort_line_id"])
    if line is not None:
        recompute_sortline(line)
        touch(line)
    touch(load)
    return success(serialize(load), response_type="object", code=200)


# ===========================================================================
# Bale
# ===========================================================================
@app.route("/mrf/bales", methods=["POST"])
def create_bale():
    require_auth(["SortManager"])
    body = get_body()
    source_load_id = req_str(body, "source_load_id")
    commodity = req_enum(body, "commodity", COMMODITIES)
    net_tons = req_num(body, "net_tons")
    moisture_pct = req_num(body, "moisture_pct")
    quality_grade = req_enum(body, "quality_grade", GRADES)
    load = get_or_404(loads, source_load_id, "ERR_LOAD_NOT_FOUND")
    # state (priority 5): load must be AUDITED
    if load["status"] != "AUDITED":
        raise ApiError("ERR_LOAD_NOT_AUDITED", 409, "Source load not in AUDITED")
    # safety (priority 7): commodity present in audited_composition
    comp_commodities = {c["commodity"] for c in (load["audited_composition"] or [])}
    if commodity not in comp_commodities:
        raise ApiError("ERR_COMMODITY_NOT_IN_LOAD", 422, "Bale commodity not present in load composition")
    # quantity (priority 9): net_tons <= unbaled_remaining_tons
    if D(net_tons) > D(load["unbaled_remaining_tons"]):
        raise ApiError("ERR_BALE_TONS_EXCEED_REMAINING", 422, "Bale tonnage exceeds remaining")
    # provisional value from index snapshot at bale creation clock
    idx = index_in_force(commodity, CLOCK["now"])
    snapshot = idx["price_cents_per_ton"] if idx else 0
    provisional = bale_gross_value(net_tons, moisture_pct, quality_grade, snapshot) if idx else 0
    bale = common_fields()
    bale.update({
        "source_load_id": source_load_id,
        "shipment_id": None,
        "commodity": commodity,
        "net_tons": net_tons,
        "moisture_pct": moisture_pct,
        "quality_grade": quality_grade,
        "index_price_snapshot_cents": snapshot,
        "provisional_value_cents": provisional,
        "final_value_cents": 0,
        "freight_share_cents": 0,
        "status": "BALED",
    })
    bales[bale["id"]] = bale
    recompute_load_mass(load)
    touch(load)
    return success(serialize(bale), response_type="object", code=201)


@app.route("/mrf/bales", methods=["GET"])
def list_bales():
    require_auth(ALL_READ_ROLES)
    source_load_id = request.args.get("source_load_id")
    shipment_id = request.args.get("shipment_id")
    status = request.args.get("status")
    commodity = request.args.get("commodity")
    items = [b for b in bales.values()
             if (source_load_id is None or b["source_load_id"] == source_load_id)
             and (shipment_id is None or b["shipment_id"] == shipment_id)
             and (status is None or b["status"] == status)
             and (commodity is None or b["commodity"] == commodity)]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(b) for b in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/bales/<bale_id>", methods=["GET"])
def get_bale(bale_id):
    require_auth(ALL_READ_ROLES)
    bale = get_or_404(bales, bale_id, "ERR_BALE_NOT_FOUND")
    return success(serialize(bale), response_type="object", code=200)


@app.route("/mrf/bales/<bale_id>/void", methods=["POST"])
def void_bale(bale_id):
    require_auth(["SortManager"])
    bale = get_or_404(bales, bale_id, "ERR_BALE_NOT_FOUND")
    if bale["status"] not in ("BALED", "STAGED"):
        raise ApiError("ERR_BALE_NOT_VOIDABLE", 409, "Bale not in BALED or STAGED")
    was_staged = bale["status"] == "STAGED"
    prior_shipment_id = bale["shipment_id"]
    bale["status"] = "VOIDED"
    bale["shipment_id"] = None
    touch(bale)
    load = loads.get(bale["source_load_id"])
    if load is not None:
        recompute_load_mass(load)
        touch(load)
    if was_staged and prior_shipment_id:
        sh = shipments.get(prior_shipment_id)
        if sh is not None:
            recompute_shipment_tons(sh)
            touch(sh)
    return success(serialize(bale), response_type="object", code=200)


# ===========================================================================
# MillShipment
# ===========================================================================
@app.route("/mrf/mill-shipments", methods=["POST"])
def create_shipment():
    require_auth(["CommodityTrader"])
    body = get_body()
    mill_id = req_str(body, "mill_id")
    commodity = req_enum(body, "commodity", COMMODITIES)
    freight_cost_cents = req_int(body, "freight_cost_cents")
    get_or_404(mills, mill_id, "ERR_MILL_NOT_FOUND")
    sh = common_fields()
    sh.update({
        "mill_id": mill_id,
        "commodity": commodity,
        "freight_cost_cents": freight_cost_cents,
        "total_net_tons": 0,
        "gross_settlement_cents": 0,
        "status": "BUILDING",
    })
    shipments[sh["id"]] = sh
    return success(serialize(sh), response_type="object", code=201)


@app.route("/mrf/mill-shipments", methods=["GET"])
def list_shipments():
    require_auth(ALL_READ_ROLES)
    mill_id = request.args.get("mill_id")
    status = request.args.get("status")
    items = [s for s in shipments.values()
             if (mill_id is None or s["mill_id"] == mill_id)
             and (status is None or s["status"] == status)]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(s) for s in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/mill-shipments/<shipment_id>", methods=["GET"])
def get_shipment(shipment_id):
    require_auth(ALL_READ_ROLES)
    sh = get_or_404(shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    return success(serialize(sh), response_type="object", code=200)


@app.route("/mrf/mill-shipments/<shipment_id>/bales", methods=["POST"])
def assign_bale(shipment_id):
    require_auth(["CommodityTrader"])
    body = get_body()
    bale_id = req_str(body, "bale_id")
    # existence left-to-right: path shipment then body bale
    sh = get_or_404(shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    bale = get_or_404(bales, bale_id, "ERR_BALE_NOT_FOUND")
    # state (priority 5)
    if sh["status"] != "BUILDING":
        raise ApiError("ERR_SHIPMENT_NOT_BUILDING", 409, "Shipment not in BUILDING")
    if bale["status"] != "BALED":
        raise ApiError("ERR_BALE_NOT_STAGEABLE", 409, "Bale not in BALED")
    # referential (priority 6): source load CLOSED
    load = loads.get(bale["source_load_id"])
    if load is None or load["status"] != "CLOSED":
        raise ApiError("ERR_BALE_LOAD_NOT_CLOSED", 422, "Bale source load not CLOSED")
    # safety (priority 7): commodity match
    if bale["commodity"] != sh["commodity"]:
        raise ApiError("ERR_COMMODITY_MISMATCH", 422, "Bale commodity differs from shipment commodity")
    bale["shipment_id"] = sh["id"]
    bale["status"] = "STAGED"
    touch(bale)
    recompute_shipment_tons(sh)
    touch(sh)
    return success(serialize(sh), response_type="object", code=200)


@app.route("/mrf/mill-shipments/<shipment_id>/ship", methods=["POST"])
def ship_shipment(shipment_id):
    require_auth(["CommodityTrader"])
    sh = get_or_404(shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    if sh["status"] != "BUILDING":
        raise ApiError("ERR_SHIPMENT_NOT_BUILDING", 409, "Shipment not in BUILDING")
    staged = [b for b in bales.values() if b["shipment_id"] == sh["id"] and b["status"] == "STAGED"]
    if len(staged) == 0:
        raise ApiError("ERR_SHIPMENT_EMPTY", 422, "Shipment has no STAGED bales")
    sh["status"] = "SHIPPED"
    for b in staged:
        b["status"] = "SHIPPED"
        touch(b)
    touch(sh)
    return success(serialize(sh), response_type="object", code=200)


@app.route("/mrf/mill-shipments/<shipment_id>/settle", methods=["POST"])
def settle_shipment(shipment_id):
    require_auth(["CommodityTrader"])
    sh = get_or_404(shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    # state (priority 5)
    if sh["status"] not in ("SHIPPED", "DISPUTED"):
        raise ApiError("ERR_SHIPMENT_NOT_SHIPPED", 409, "Shipment not in SHIPPED or DISPUTED")
    # referential (priority 6): published index in force at current clock
    idx = index_in_force(sh["commodity"], CLOCK["now"])
    if idx is None:
        raise ApiError("ERR_NO_PUBLISHED_INDEX", 422, "No PUBLISHED index for commodity at clock")
    settling = [b for b in bales.values() if b["shipment_id"] == sh["id"] and b["status"] == "SHIPPED"]
    settling = sorted_by_creation(settling)
    total_net = D(sh["total_net_tons"])
    price = idx["price_cents_per_ton"]
    for b in settling:
        if total_net > 0:
            freight_share = rhu(D(sh["freight_cost_cents"]) * D(b["net_tons"]) / total_net)
        else:
            freight_share = 0
        gross = bale_gross_value(b["net_tons"], b["moisture_pct"], b["quality_grade"], price)
        b["freight_share_cents"] = freight_share
        b["final_value_cents"] = gross - freight_share
        b["status"] = "SETTLED"
        touch(b)
    sh["gross_settlement_cents"] = sum(b["final_value_cents"] for b in settling)
    for b in settling:
        load = loads[b["source_load_id"]]
        muni = municipalities[load["source_municipality_id"]]
        share = rhu(D(b["final_value_cents"]) * D(muni["revenue_share_pct"]))
        create_posting(muni, "REVENUE_SHARE", share, related_bale_id=b["id"], related_load_id=load["id"])
    sh["status"] = "SETTLED"
    touch(sh)
    return success(serialize(sh), response_type="object", code=200)


@app.route("/mrf/mill-shipments/<shipment_id>/dispute", methods=["POST"])
def dispute_shipment(shipment_id):
    require_auth(["CommodityTrader"])
    body = get_body()
    sh = get_or_404(shipments, shipment_id, "ERR_SHIPMENT_NOT_FOUND")
    req_str(body, "reason")
    if sh["status"] != "SETTLED":
        raise ApiError("ERR_SHIPMENT_NOT_SETTLED", 409, "Shipment not in SETTLED")
    settled_bales = [b for b in bales.values() if b["shipment_id"] == sh["id"] and b["status"] == "SETTLED"]
    settled_bales = sorted_by_creation(settled_bales)
    existing_postings = list(postings.values())
    for b in settled_bales:
        for p in existing_postings:
            if (p["posting_type"] == "REVENUE_SHARE" and p["related_bale_id"] == b["id"]
                    and not p["reversed"]):
                muni = municipalities[p["municipality_id"]]
                create_posting(muni, "REVERSAL", -p["amount_cents"],
                               related_bale_id=b["id"], related_load_id=p["related_load_id"])
                p["reversed"] = True
        b["final_value_cents"] = 0
        b["status"] = "SHIPPED"
        touch(b)
    sh["gross_settlement_cents"] = 0
    sh["status"] = "DISPUTED"
    touch(sh)
    return success(serialize(sh), response_type="object", code=200)


# ===========================================================================
# MunicipalStatement
# ===========================================================================
@app.route("/mrf/municipal-statements", methods=["POST"])
def create_statement():
    require_auth(["SettlementClerk"])
    body = get_body()
    municipality_id = req_str(body, "municipality_id")
    period_start = req_dt(body, "period_start")
    period_end = req_dt(body, "period_end")
    expected_version = req_int(body, "expected_municipality_version")
    # existence (priority 3)
    muni = get_or_404(municipalities, municipality_id, "ERR_MUNICIPALITY_NOT_FOUND")
    # OCC (priority 4)
    if expected_version != muni["version"]:
        raise ApiError("ERR_STALE_MUNICIPALITY_VERSION", 412, "Stale municipality version")
    # supersede prior OPEN statement for this municipality
    for st in statements.values():
        if st["municipality_id"] == municipality_id and st["status"] == "OPEN":
            st["status"] = "SUPERSEDED"
            touch(st)
    stmt = common_fields()
    stmt.update({
        "municipality_id": municipality_id,
        "period_start": period_start,
        "period_end": period_end,
        "total_revenue_share_cents": 0,
        "total_rebate_cents": 0,
        "total_penalty_cents": 0,
        "net_payable_cents": 0,
        "status": "OPEN",
    })
    statements[stmt["id"]] = stmt
    # advance municipality version by one
    touch(muni)
    return success(serialize(stmt), response_type="object", code=201)


@app.route("/mrf/municipal-statements", methods=["GET"])
def list_statements():
    require_auth(ALL_READ_ROLES)
    municipality_id = request.args.get("municipality_id")
    status = request.args.get("status")
    items = [s for s in statements.values()
             if (municipality_id is None or s["municipality_id"] == municipality_id)
             and (status is None or s["status"] == status)]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(s) for s in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/municipal-statements/<statement_id>", methods=["GET"])
def get_statement(statement_id):
    require_auth(ALL_READ_ROLES)
    stmt = get_or_404(statements, statement_id, "ERR_STATEMENT_NOT_FOUND")
    return success(serialize(stmt), response_type="object", code=200)


@app.route("/mrf/municipal-statements/<statement_id>/finalize", methods=["POST"])
def finalize_statement(statement_id):
    require_auth(["SettlementClerk"])
    stmt = get_or_404(statements, statement_id, "ERR_STATEMENT_NOT_FOUND")
    if stmt["status"] != "OPEN":
        raise ApiError("ERR_STATEMENT_NOT_OPEN", 409, "Statement not in OPEN")
    period_start = parse_iso(stmt["period_start"])
    period_end = parse_iso(stmt["period_end"])
    relevant = []
    for p in postings.values():
        if p["municipality_id"] != stmt["municipality_id"]:
            continue
        created = parse_iso(p["created_at"])
        if period_start <= created < period_end:
            relevant.append(p)
    relevant = sorted_by_creation(relevant)
    total_revenue = 0
    total_rebate = 0
    total_penalty = 0
    for p in relevant:
        if p["posting_type"] == "REVENUE_SHARE":
            total_revenue += p["amount_cents"]
        elif p["posting_type"] == "REVERSAL":
            total_revenue += p["amount_cents"]  # negative
        elif p["posting_type"] == "REBATE":
            total_rebate += p["amount_cents"]
        elif p["posting_type"] == "PENALTY":
            total_penalty += -p["amount_cents"]  # magnitude
    stmt["total_revenue_share_cents"] = total_revenue
    stmt["total_rebate_cents"] = total_rebate
    stmt["total_penalty_cents"] = total_penalty
    stmt["net_payable_cents"] = total_revenue + total_rebate - total_penalty
    stmt["status"] = "FINALIZED"
    touch(stmt)
    return success(serialize(stmt), response_type="object", code=200)


# ===========================================================================
# RevenueSharePosting (read only)
# ===========================================================================
@app.route("/mrf/revenue-postings", methods=["GET"])
def list_postings():
    require_auth(ALL_READ_ROLES)
    municipality_id = request.args.get("municipality_id")
    items = [p for p in postings.values()
             if municipality_id is None or p["municipality_id"] == municipality_id]
    items = sorted_by_creation(items)
    page, pg = paginate(items)
    return success([serialize(p) for p in page], response_type="array", code=200, pagination=pg)


@app.route("/mrf/revenue-postings/<posting_id>", methods=["GET"])
def get_posting(posting_id):
    require_auth(ALL_READ_ROLES)
    p = get_or_404(postings, posting_id, "ERR_NOT_FOUND")
    return success(serialize(p), response_type="object", code=200)


# ---------------------------------------------------------------------------
# Boot
# ---------------------------------------------------------------------------
_reset_state()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
