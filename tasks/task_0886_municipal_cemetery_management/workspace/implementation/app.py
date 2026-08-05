"""Municipal Cemetery Management API — Python + Flask, in-memory store."""
import os
import random
import string
import threading
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify

from db import db, new_id, next_seq

app = Flask(__name__)

# ---------------------------------------------------------------------------
# Constants (PRD §2.6, §3)
# ---------------------------------------------------------------------------
PREFIX = "/cemetery-mgmt"

ROLES = {"Registrar", "GroundsForeman", "FinanceOfficer",
         "HealthOfficer", "CemeteryDirector", "RightHolder"}
ALL_ROLES = ROLES

CARE_PCT = Decimal("0.15")
CARE_MIN_CENTS = 25000
RESALE_CARE_PCT = Decimal("0.10")

BASE_FEE_BY_PLOT_TYPE = {"GRAVE": 90000, "LAWN_CRYPT": 120000,
                         "NICHE": 45000, "MAUSOLEUM": 150000}
DEPTH_TIER_2 = 15000
DEPTH_TIER_3PLUS = 30000
WEEKEND_SURCHARGE = 20000
HOLIDAY_SURCHARGE = 35000
SHORT_NOTICE_SURCHARGE = 25000
SHORT_NOTICE_DAYS = 3
HOLIDAYS = {"2026-01-01", "2026-07-04", "2026-11-26", "2026-12-25"}

TAX_RATE = Decimal("0.0725")

DISINTERMENT_FEE_CENTS = 200000
RELOC_CREDIT_PCT = Decimal("0.50")
REMOVAL_REFUND_PCT = Decimal("0.25")

MARKER_FEE_BY_TYPE = {"FLAT": 15000, "UPRIGHT": 30000, "MONUMENT": 60000}

CREW_BUFFER = timedelta(minutes=60)

PLOT_TYPES = set(BASE_FEE_BY_PLOT_TYPE.keys())
SALE_TYPES = {"NEW_SALE", "RESALE"}
INTERMENT_TYPES = {"BURIAL", "ENTOMBMENT", "INURNMENT"}
DISINTERMENT_TYPES = {"RELOCATION", "REMOVAL"}
MARKER_TYPES = set(MARKER_FEE_BY_TYPE.keys())
ENTRY_TYPES = {"CONTRIBUTION", "DISBURSEMENT", "INTEREST"}
PAYMENT_METHODS = {"CARD", "CHECK", "CASH", "ACH"}
SEX_VALUES = {"M", "F", "X", "UNKNOWN"}

ACTIVE_OP = {"SCHEDULED", "OPENED", "COMPLETED"}


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------
class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def err(error_id, http_status, message=None):
    raise ApiError(error_id, http_status, message)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------
def format_ts(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def now_ts():
    return format_ts(db.clock)


def clock_date():
    return db.clock.astimezone(timezone.utc).date()


def round_half_up(dec):
    return int(Decimal(dec).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# Response envelope
# ---------------------------------------------------------------------------
def req_id():
    return "req_" + "".join(random.choices(string.ascii_letters + string.digits, k=20))


def _meta(extra=None):
    m = {"api_request_id": req_id(), "api_request_timestamp": now_ts()}
    if extra:
        m.update(extra)
    return m


def envelope(data, rtype, status, extra_meta=None):
    body = {"meta": _meta(extra_meta), "response_type": rtype, "data": data}
    return jsonify(body), status


def ok_obj(data, status=200):
    return envelope(data, "object", status)


def ok_list(items, ser_fn):
    limit, offset = get_pagination()
    total = len(items)
    page = items[offset:offset + limit]
    data = [ser_fn(x) for x in page]
    extra = {"limit": limit, "offset": offset, "total_count": total,
             "has_more": offset + len(page) < total}
    return envelope(data, "array", 200, extra)


@app.errorhandler(ApiError)
def _handle_api_error(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": e.error_id, "message": e.message}}
    return jsonify(body), e.http_status


@app.errorhandler(404)
def _handle_404(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_NOT_FOUND", "message": "Resource not found"}}
    return jsonify(body), 404


@app.errorhandler(405)
def _handle_405(e):
    body = {"meta": _meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "Method not allowed"}}
    return jsonify(body), 405


# ---------------------------------------------------------------------------
# Global request serialization (deterministic under concurrent race tests)
# ---------------------------------------------------------------------------
_LOCK = threading.RLock()


@app.before_request
def _acquire_lock():
    _LOCK.acquire()


@app.teardown_request
def _release_lock(exc):
    try:
        _LOCK.release()
    except RuntimeError:
        pass


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    if not role or role not in ROLES:
        err("ERR_UNAUTHENTICATED", 401, "Missing or unrecognized X-User-Role")
    user_id = request.headers.get("X-User-ID")
    return user_id, role


def require(role, allowed):
    if role not in allowed:
        err("ERR_FORBIDDEN", 403, "Role not permitted for this operation")


# ---------------------------------------------------------------------------
# Body / field validation helpers
# ---------------------------------------------------------------------------
def get_body():
    if request.method in ("POST", "PUT", "PATCH"):
        data = request.get_json(silent=True)
        if data is None:
            return {}
        if not isinstance(data, dict):
            err("ERR_VALIDATION", 400, "Request body must be a JSON object")
        return data
    return {}


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str) or v.strip() == "":
        err("ERR_VALIDATION", 400, f"Missing or invalid field: {field}")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        err("ERR_VALIDATION", 400, f"Invalid field: {field}")
    return v


def req_enum(body, field, allowed):
    v = req_str(body, field)
    if v not in allowed:
        err("ERR_VALIDATION", 400, f"Invalid enum for {field}")
    return v


def opt_enum(body, field, allowed):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str) or v not in allowed:
        err("ERR_VALIDATION", 400, f"Invalid enum for {field}")
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(body, field, min_val=None):
    v = body.get(field)
    if not _is_int(v):
        err("ERR_VALIDATION", 400, f"Missing or invalid integer: {field}")
    if min_val is not None and v < min_val:
        err("ERR_VALIDATION", 400, f"{field} must be >= {min_val}")
    return v


def req_num(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err("ERR_VALIDATION", 400, f"Missing or invalid number: {field}")
    return v


def get_pagination():
    args = request.args
    limit = 10
    offset = 0
    if "limit" in args and args.get("limit") != "":
        try:
            limit = int(args.get("limit"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1:
            limit = 1
        if limit > 100:
            limit = 100
    if "offset" in args and args.get("offset") != "":
        try:
            offset = int(args.get("offset"))
        except (TypeError, ValueError):
            err("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            offset = 0
    return limit, offset


# ---------------------------------------------------------------------------
# Store helpers
# ---------------------------------------------------------------------------
def base_common():
    ts = now_ts()
    return {"id": new_id(), "created_at": ts, "updated_at": ts,
            "version": 1, "_seq": next_seq()}


def base_light():
    return {"id": new_id(), "created_at": now_ts(), "_seq": next_seq()}


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = now_ts()


def must_get(coll, ident):
    ent = coll.get(ident)
    if ent is None:
        err("ERR_NOT_FOUND", 404, "Resource not found")
    return ent


def sorted_vals(coll):
    return sorted(coll.values(), key=lambda e: (e["created_at"], e["_seq"]))


# ---------------------------------------------------------------------------
# Computed fields
# ---------------------------------------------------------------------------
def interments_used(plot_id):
    return sum(1 for i in db.interments.values()
               if i["plot_id"] == plot_id and i["operational_status"] in ACTIVE_OP)


def fund_balance(cemetery_id):
    bal = 0
    for e in db.care_entries.values():
        if e["cemetery_id"] != cemetery_id:
            continue
        if e["entry_type"] in ("CONTRIBUTION", "INTEREST"):
            bal += e["amount_cents"]
        elif e["entry_type"] == "DISBURSEMENT":
            bal -= e["amount_cents"]
    return bal


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def _strip(ent):
    return {k: v for k, v in ent.items() if k != "_seq"}


def ser_cemetery(c):
    d = _strip(c)
    d["perpetual_care_fund_balance_cents"] = fund_balance(c["id"])
    return d


def ser_plot(p):
    d = _strip(p)
    d["interments_used"] = interments_used(p["id"])
    return d


def ser_plain(e):
    return _strip(e)


# ---------------------------------------------------------------------------
# Calculations
# ---------------------------------------------------------------------------
def care_fund_contribution(purchase_price_cents, sale_type):
    if sale_type == "NEW_SALE":
        pct = round_half_up(Decimal(purchase_price_cents) * CARE_PCT)
        return max(pct, CARE_MIN_CENTS)
    return round_half_up(Decimal(purchase_price_cents) * RESALE_CARE_PCT)


def compute_day_type(scheduled_date_str):
    if scheduled_date_str in HOLIDAYS:
        return "HOLIDAY"
    d = date.fromisoformat(scheduled_date_str)
    if d.weekday() >= 5:
        return "WEEKEND"
    return "WEEKDAY"


def service_fee_components(plot_type, depth_position, day_type, scheduled_date_str):
    base = BASE_FEE_BY_PLOT_TYPE[plot_type]
    if depth_position == 1:
        depth = 0
    elif depth_position == 2:
        depth = DEPTH_TIER_2
    else:
        depth = DEPTH_TIER_3PLUS
    if day_type == "HOLIDAY":
        day = HOLIDAY_SURCHARGE
    elif day_type == "WEEKEND":
        day = WEEKEND_SURCHARGE
    else:
        day = 0
    days_out = (date.fromisoformat(scheduled_date_str) - clock_date()).days
    notice = SHORT_NOTICE_SURCHARGE if days_out < SHORT_NOTICE_DAYS else 0
    return base, depth, day, notice


def compute_tax(lines):
    tax = 0
    for ln in lines:
        if ln["taxable"]:
            tax += round_half_up(Decimal(ln["amount_cents"]) * TAX_RATE)
    return tax


# ---------------------------------------------------------------------------
# Invoice / CareFund helpers
# ---------------------------------------------------------------------------
def create_invoice(holder_id, subject_type, subject_id, lines, issued_by):
    inv = base_common()
    inv["holder_id"] = holder_id
    inv["subject_type"] = subject_type
    inv["subject_id"] = subject_id
    inv["lines"] = lines
    inv["subtotal_cents"] = sum(ln["amount_cents"] for ln in lines)
    inv["tax_cents"] = compute_tax(lines)
    inv["total_cents"] = inv["subtotal_cents"] + inv["tax_cents"]
    inv["issued_by_user_id"] = issued_by
    inv["status"] = "ISSUED"
    db.invoices[inv["id"]] = inv
    return inv


def post_care_entry(cemetery_id, entry_type, amount_cents, source_deed_id=None, note=None):
    e = base_light()
    e["cemetery_id"] = cemetery_id
    e["entry_type"] = entry_type
    e["amount_cents"] = amount_cents
    e["source_deed_id"] = source_deed_id
    e["note"] = note
    db.care_entries[e["id"]] = e
    return e


def plot_cemetery_id(plot_id):
    p = db.plots.get(plot_id)
    return p["cemetery_id"] if p else None


# ===========================================================================
# CEMETERY
# ===========================================================================
@app.post(f"{PREFIX}/cemeteries")
def create_cemetery():
    _, role = authenticate()
    require(role, {"CemeteryDirector"})
    body = get_body()
    name = req_str(body, "name")
    timezone_val = opt_str(body, "timezone") or "UTC"
    crew = body.get("crew_team_count")
    if crew is None:
        crew = 1
    else:
        crew = req_int(body, "crew_team_count", min_val=1)
    c = base_common()
    c["name"] = name
    c["timezone"] = timezone_val
    c["crew_team_count"] = crew
    db.cemeteries[c["id"]] = c
    return ok_obj(ser_cemetery(c), 201)


@app.get(f"{PREFIX}/cemeteries/<cemetery_id>")
def get_cemetery(cemetery_id):
    _, role = authenticate()
    require(role, ALL_ROLES)
    c = must_get(db.cemeteries, cemetery_id)
    return ok_obj(ser_cemetery(c))


# ===========================================================================
# PLOT
# ===========================================================================
@app.post(f"{PREFIX}/plots")
def create_plot():
    _, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    cemetery_id = req_str(body, "cemetery_id")
    section_code = req_str(body, "section_code")
    row = req_str(body, "row")
    plot_number = req_str(body, "plot_number")
    gis_lat = req_num(body, "gis_lat")
    gis_lng = req_num(body, "gis_lng")
    plot_type = req_enum(body, "plot_type", PLOT_TYPES)
    capacity = req_int(body, "interment_capacity", min_val=1)
    must_get(db.cemeteries, cemetery_id)
    p = base_common()
    p.update({"cemetery_id": cemetery_id, "section_code": section_code,
              "row": row, "plot_number": plot_number, "gis_lat": gis_lat,
              "gis_lng": gis_lng, "plot_type": plot_type,
              "interment_capacity": capacity, "status": "AVAILABLE"})
    db.plots[p["id"]] = p
    return ok_obj(ser_plot(p), 201)


@app.get(f"{PREFIX}/plots/<plot_id>")
def get_plot(plot_id):
    _, role = authenticate()
    require(role, ALL_ROLES)
    p = must_get(db.plots, plot_id)
    return ok_obj(ser_plot(p))


@app.get(f"{PREFIX}/plots")
def list_plots():
    _, role = authenticate()
    require(role, ALL_ROLES)
    items = sorted_vals(db.plots)
    cemetery_id = request.args.get("cemetery_id")
    status = request.args.get("status")
    section_code = request.args.get("section_code")
    if cemetery_id is not None:
        items = [p for p in items if p["cemetery_id"] == cemetery_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if section_code is not None:
        items = [p for p in items if p["section_code"] == section_code]
    return ok_list(items, ser_plot)


@app.post(f"{PREFIX}/plots/<plot_id>/retire")
def retire_plot(plot_id):
    _, role = authenticate()
    require(role, {"CemeteryDirector"})
    p = must_get(db.plots, plot_id)
    if p["status"] != "AVAILABLE":
        err("ERR_PLOT_NOT_AVAILABLE", 409, "Plot is not AVAILABLE")
    if interments_used(plot_id) != 0:
        err("ERR_PLOT_NOT_AVAILABLE", 409, "Plot has active interments")
    p["status"] = "RETIRED"
    touch(p)
    return ok_obj(ser_plot(p))


# ===========================================================================
# RIGHTHOLDER
# ===========================================================================
@app.post(f"{PREFIX}/holders")
def create_holder():
    _, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    full_name = req_str(body, "full_name")
    email = req_str(body, "email")
    phone = opt_str(body, "phone")
    h = base_common()
    h.update({"full_name": full_name, "email": email, "phone": phone})
    db.holders[h["id"]] = h
    return ok_obj(ser_plain(h), 201)


@app.get(f"{PREFIX}/holders/<holder_id>")
def get_holder(holder_id):
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector", "RightHolder"})
    h = must_get(db.holders, holder_id)
    return ok_obj(ser_plain(h))


# ===========================================================================
# DECEDENT / GENEALOGY
# ===========================================================================
@app.post(f"{PREFIX}/decedents")
def create_decedent():
    _, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    full_name = req_str(body, "full_name")
    date_of_death = req_str(body, "date_of_death")
    try:
        dod = date.fromisoformat(date_of_death)
    except ValueError:
        err("ERR_VALIDATION", 400, "date_of_death must be YYYY-MM-DD")
    date_of_birth = opt_str(body, "date_of_birth")
    if date_of_birth is not None:
        try:
            date.fromisoformat(date_of_birth)
        except ValueError:
            err("ERR_VALIDATION", 400, "date_of_birth must be YYYY-MM-DD")
    sex = opt_enum(body, "sex", SEX_VALUES)
    d = base_light()
    d.update({"full_name": full_name, "date_of_birth": date_of_birth,
              "date_of_death": date_of_death, "sex": sex,
              "death_year": dod.year})
    db.decedents[d["id"]] = d
    return ok_obj(ser_plain(d), 201)


@app.get(f"{PREFIX}/decedents/<decedent_id>")
def get_decedent(decedent_id):
    _, role = authenticate()
    require(role, ALL_ROLES)
    d = must_get(db.decedents, decedent_id)
    return ok_obj(ser_plain(d))


@app.get(f"{PREFIX}/decedents")
def list_decedents():
    _, role = authenticate()
    require(role, ALL_ROLES)
    items = sorted_vals(db.decedents)
    full_name = request.args.get("full_name")
    death_year = request.args.get("death_year")
    if full_name is not None:
        items = [d for d in items if d["full_name"] == full_name]
    if death_year is not None:
        try:
            dy = int(death_year)
        except ValueError:
            err("ERR_VALIDATION", 400, "death_year must be an integer")
        items = [d for d in items if d["death_year"] == dy]
    return ok_list(items, ser_plain)


# ===========================================================================
# DEED
# ===========================================================================
@app.post(f"{PREFIX}/deeds")
def create_deed():
    user_id, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    plot_id = req_str(body, "plot_id")
    holder_id = req_str(body, "holder_id")
    purchase_price = req_int(body, "purchase_price_cents", min_val=0)
    sale_type = req_enum(body, "sale_type", SALE_TYPES)
    expected_version = req_int(body, "expected_plot_version")
    # existence
    plot = must_get(db.plots, plot_id)
    holder = must_get(db.holders, holder_id)
    # concurrency (before state per PRD §2.5)
    if expected_version != plot["version"]:
        err("ERR_STALE_VERSION", 412, "expected_plot_version does not match current Plot.version")
    # state
    if plot["status"] != "AVAILABLE":
        err("ERR_PLOT_NOT_AVAILABLE", 409, "Plot is not AVAILABLE for sale")
    contribution = care_fund_contribution(purchase_price, sale_type)
    deed = base_common()
    deed.update({"plot_id": plot_id, "holder_id": holder_id,
                 "purchase_price_cents": purchase_price, "sale_type": sale_type,
                 "care_fund_contribution_cents": contribution,
                 "status": "PENDING_PAYMENT", "pending_new_holder_id": None})
    # DEED_SALE invoice
    lines = [
        {"label": "purchase_price", "amount_cents": purchase_price, "taxable": True},
        {"label": "perpetual_care", "amount_cents": contribution, "taxable": False},
    ]
    inv = create_invoice(holder_id, "DEED_SALE", deed["id"], lines, user_id)
    deed["sale_invoice_id"] = inv["id"]
    db.deeds[deed["id"]] = deed
    # plot AVAILABLE -> RESERVED
    plot["status"] = "RESERVED"
    touch(plot)
    return ok_obj(ser_plain(deed), 201)


@app.get(f"{PREFIX}/deeds/<deed_id>")
def get_deed(deed_id):
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector", "RightHolder"})
    d = must_get(db.deeds, deed_id)
    return ok_obj(ser_plain(d))


@app.get(f"{PREFIX}/deeds")
def list_deeds():
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector", "RightHolder"})
    items = sorted_vals(db.deeds)
    for key in ("plot_id", "holder_id", "pending_new_holder_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [d for d in items if d.get(key) == val]
    return ok_list(items, ser_plain)


@app.post(f"{PREFIX}/deeds/<deed_id>/transfer")
def transfer_deed(deed_id):
    _, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    new_holder_id = req_str(body, "new_holder_id")
    deed = must_get(db.deeds, deed_id)
    # new holder existence (existence stage)
    if new_holder_id not in db.holders:
        err("ERR_HOLDER_NOT_FOUND", 404, "Transfer target holder does not exist")
    # state
    if deed["status"] != "ISSUED":
        err("ERR_INVALID_STATE", 409, "Deed is not ISSUED")
    if new_holder_id == deed["holder_id"]:
        err("ERR_VALIDATION", 400, "new_holder_id must differ from current holder")
    deed["status"] = "TRANSFER_PENDING"
    deed["pending_new_holder_id"] = new_holder_id
    touch(deed)
    return ok_obj(ser_plain(deed))


@app.post(f"{PREFIX}/deeds/<deed_id>/accept-transfer")
def accept_transfer(deed_id):
    user_id, role = authenticate()
    require(role, {"RightHolder"})
    deed = must_get(db.deeds, deed_id)
    if deed["status"] != "TRANSFER_PENDING":
        err("ERR_INVALID_STATE", 409, "Deed is not TRANSFER_PENDING")
    if user_id != deed.get("pending_new_holder_id"):
        err("ERR_NOT_PENDING_HOLDER", 403, "Acting holder is not the pending recipient")
    deed["holder_id"] = deed["pending_new_holder_id"]
    deed["pending_new_holder_id"] = None
    deed["status"] = "ISSUED"
    touch(deed)
    return ok_obj(ser_plain(deed))


@app.post(f"{PREFIX}/deeds/<deed_id>/surrender")
def surrender_deed(deed_id):
    user_id, role = authenticate()
    require(role, {"Registrar"})
    deed = must_get(db.deeds, deed_id)
    if deed["status"] not in ("ISSUED", "PENDING_PAYMENT"):
        err("ERR_INVALID_STATE", 409, "Deed cannot be surrendered from its current state")
    plot = db.plots.get(deed["plot_id"])
    # no active interment on plot
    if any(i["plot_id"] == deed["plot_id"] and i["operational_status"] in ACTIVE_OP
           for i in db.interments.values()):
        err("ERR_PLOT_OCCUPIED", 409, "Plot has an active interment")
    was_issued = deed["status"] == "ISSUED"
    deed["status"] = "SURRENDERED"
    deed["pending_new_holder_id"] = None
    touch(deed)
    # plot -> AVAILABLE
    if plot is not None:
        plot["status"] = "AVAILABLE"
        touch(plot)
    # cancel non-terminal marker permits on plot
    for m in db.markers.values():
        if m["plot_id"] == deed["plot_id"] and m["status"] in ("APPLIED", "APPROVED"):
            m["status"] = "CANCELLED"
            touch(m)
            inv = db.invoices.get(m["foundation_invoice_id"])
            if inv is not None and inv["status"] == "ISSUED":
                inv["status"] = "VOID"
                touch(inv)
    # care-fund reversal + refund invoice (only when the contribution was posted)
    if was_issued:
        contribution = deed["care_fund_contribution_cents"]
        cem_id = plot["cemetery_id"] if plot is not None else None
        if cem_id is not None:
            post_care_entry(cem_id, "DISBURSEMENT", contribution,
                            source_deed_id=deed["id"], note="deed surrender reversal")
        refund_lines = [{"label": "refund", "amount_cents": -contribution, "taxable": False}]
        create_invoice(deed["holder_id"], "DEED_SALE", deed["id"], refund_lines, user_id)
    return ok_obj(ser_plain(deed))


# ===========================================================================
# INTERMENT
# ===========================================================================
def _parse_dt(s):
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        err("ERR_VALIDATION", 400, "Invalid datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


@app.post(f"{PREFIX}/interments")
def create_interment():
    user_id, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    plot_id = req_str(body, "plot_id")
    decedent_id = req_str(body, "decedent_id")
    deed_id = req_str(body, "deed_id")
    interment_type = req_enum(body, "interment_type", INTERMENT_TYPES)
    depth_position = req_int(body, "depth_position", min_val=1)
    scheduled_date = req_str(body, "scheduled_date")
    scheduled_start = req_str(body, "scheduled_start")
    scheduled_end = req_str(body, "scheduled_end")
    try:
        sched_date = date.fromisoformat(scheduled_date)
    except ValueError:
        err("ERR_VALIDATION", 400, "scheduled_date must be YYYY-MM-DD")
    start_dt = _parse_dt(scheduled_start)
    end_dt = _parse_dt(scheduled_end)
    if not (end_dt > start_dt):
        err("ERR_VALIDATION", 400, "scheduled_end must be strictly after scheduled_start")
    # existence
    plot = must_get(db.plots, plot_id)
    must_get(db.decedents, decedent_id)
    deed = must_get(db.deeds, deed_id)
    # referential: deed ISSUED
    if deed["status"] != "ISSUED":
        err("ERR_DEED_NOT_ISSUED", 409, "Deed must be ISSUED to schedule an interment")
    # temporal: scheduled_date not in past
    if sched_date < clock_date():
        err("ERR_DATE_IN_PAST", 422, "scheduled_date is in the past")
    # capacity
    if interments_used(plot_id) >= plot["interment_capacity"]:
        err("ERR_PLOT_CAPACITY", 409, "Plot capacity reached")
    # single booking per day (this plot)
    for i in db.interments.values():
        if (i["plot_id"] == plot_id and i["scheduled_date"] == scheduled_date
                and i["operational_status"] in ACTIVE_OP):
            err("ERR_PLOT_DOUBLE_BOOKED", 409, "Plot already booked on this date")
    # crew window overlap (cemetery-wide, same date)
    cem = db.cemeteries.get(plot["cemetery_id"])
    crew_count = cem["crew_team_count"] if cem else 1
    overlaps = 0
    for i in db.interments.values():
        if i["operational_status"] not in ACTIVE_OP:
            continue
        if i["scheduled_date"] != scheduled_date:
            continue
        ip = db.plots.get(i["plot_id"])
        if ip is None or ip["cemetery_id"] != plot["cemetery_id"]:
            continue
        e_start = _parse_dt(i["scheduled_start"])
        e_end = _parse_dt(i["scheduled_end"])
        if start_dt < e_end + CREW_BUFFER and e_start < end_dt + CREW_BUFFER:
            overlaps += 1
    if overlaps >= crew_count:
        err("ERR_CREW_UNAVAILABLE", 409, "No crew available for this time window")
    # compute fee
    day_type = compute_day_type(scheduled_date)
    base, depth, day, notice = service_fee_components(
        plot["plot_type"], depth_position, day_type, scheduled_date)
    service_fee = base + depth + day + notice
    inter = base_common()
    inter.update({"plot_id": plot_id, "decedent_id": decedent_id, "deed_id": deed_id,
                  "interment_type": interment_type, "depth_position": depth_position,
                  "scheduled_date": scheduled_date, "scheduled_start": scheduled_start,
                  "scheduled_end": scheduled_end, "day_type": day_type,
                  "service_fee_cents": service_fee, "operational_status": "SCHEDULED",
                  "billing_status": "INVOICED"})
    # INTERMENT_SERVICE invoice: one taxable line per non-zero component
    lines = []
    for label, amount in (("base", base), ("depth_surcharge", depth),
                          ("day_surcharge", day), ("short_notice_surcharge", notice)):
        if amount != 0:
            lines.append({"label": label, "amount_cents": amount, "taxable": True})
    inv = create_invoice(deed["holder_id"], "INTERMENT_SERVICE", inter["id"], lines, user_id)
    inter["service_invoice_id"] = inv["id"]
    db.interments[inter["id"]] = inter
    return ok_obj(ser_plain(inter), 201)


@app.get(f"{PREFIX}/interments/<interment_id>")
def get_interment(interment_id):
    _, role = authenticate()
    require(role, ALL_ROLES)
    i = must_get(db.interments, interment_id)
    return ok_obj(ser_plain(i))


@app.get(f"{PREFIX}/interments")
def list_interments():
    _, role = authenticate()
    require(role, ALL_ROLES)
    items = sorted_vals(db.interments)
    for key in ("plot_id", "decedent_id", "deed_id", "scheduled_date", "operational_status"):
        val = request.args.get(key)
        if val is not None:
            items = [i for i in items if i.get(key) == val]
    return ok_list(items, ser_plain)


@app.post(f"{PREFIX}/interments/<interment_id>/open")
def open_interment(interment_id):
    _, role = authenticate()
    require(role, {"GroundsForeman"})
    i = must_get(db.interments, interment_id)
    if i["operational_status"] != "SCHEDULED":
        err("ERR_INVALID_STATE", 409, "Interment is not SCHEDULED")
    # temporal before fiscal (PRD §2.5)
    if clock_date() < date.fromisoformat(i["scheduled_date"]):
        err("ERR_TOO_EARLY_TO_OPEN", 422, "Cannot open before scheduled_date")
    if i["billing_status"] != "PAID":
        err("ERR_INVOICE_UNPAID", 409, "Service invoice is not PAID")
    i["operational_status"] = "OPENED"
    touch(i)
    return ok_obj(ser_plain(i))


@app.post(f"{PREFIX}/interments/<interment_id>/complete")
def complete_interment(interment_id):
    _, role = authenticate()
    require(role, {"GroundsForeman"})
    i = must_get(db.interments, interment_id)
    if i["operational_status"] != "OPENED":
        err("ERR_INVALID_STATE", 409, "Interment is not OPENED")
    i["operational_status"] = "COMPLETED"
    touch(i)
    return ok_obj(ser_plain(i))


@app.post(f"{PREFIX}/interments/<interment_id>/cancel")
def cancel_interment(interment_id):
    _, role = authenticate()
    require(role, {"Registrar"})
    i = must_get(db.interments, interment_id)
    if i["operational_status"] not in ("SCHEDULED", "OPENED"):
        err("ERR_INVALID_STATE", 409, "Interment cannot be cancelled from its current state")
    inv = db.invoices.get(i["service_invoice_id"])
    if inv is not None and inv["status"] == "ISSUED":
        inv["status"] = "VOID"
        touch(inv)
    i["billing_status"] = "VOIDED"
    i["operational_status"] = "CANCELLED"
    touch(i)
    return ok_obj(ser_plain(i))


# ===========================================================================
# DISINTERMENT AUTHORIZATION
# ===========================================================================
@app.post(f"{PREFIX}/disinterment-authorizations")
def create_disinterment():
    user_id, role = authenticate()
    require(role, {"Registrar"})
    body = get_body()
    interment_id = req_str(body, "interment_id")
    reason = req_str(body, "reason")
    disinterment_type = req_enum(body, "disinterment_type", DISINTERMENT_TYPES)
    target_plot_id = opt_str(body, "target_plot_id")
    inter = must_get(db.interments, interment_id)
    if target_plot_id is not None:
        must_get(db.plots, target_plot_id)
    # referential: interment must be COMPLETED
    if inter["operational_status"] != "COMPLETED":
        err("ERR_INVALID_STATE", 409, "Interment must be COMPLETED for disinterment")
    deed = db.deeds.get(inter["deed_id"])
    holder_id = deed["holder_id"] if deed else None
    auth = base_common()
    auth.update({"interment_id": interment_id, "reason": reason,
                 "disinterment_type": disinterment_type,
                 "target_plot_id": target_plot_id,
                 "health_cleared": False, "nok_consented": False,
                 "settlement_cents": None, "approved_by_user_id": None,
                 "status": "REQUESTED"})
    lines = [{"label": "disinterment", "amount_cents": DISINTERMENT_FEE_CENTS, "taxable": True}]
    inv = create_invoice(holder_id, "DISINTERMENT", auth["id"], lines, user_id)
    auth["disinterment_invoice_id"] = inv["id"]
    db.disinterments[auth["id"]] = auth
    return ok_obj(ser_plain(auth), 201)


@app.get(f"{PREFIX}/disinterment-authorizations/<auth_id>")
def get_disinterment(auth_id):
    _, role = authenticate()
    require(role, {"Registrar", "HealthOfficer", "CemeteryDirector", "RightHolder"})
    a = must_get(db.disinterments, auth_id)
    return ok_obj(ser_plain(a))


@app.get(f"{PREFIX}/disinterment-authorizations")
def list_disinterments():
    _, role = authenticate()
    require(role, {"Registrar", "HealthOfficer", "CemeteryDirector", "RightHolder"})
    items = sorted_vals(db.disinterments)
    for key in ("interment_id", "target_plot_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [a for a in items if a.get(key) == val]
    return ok_list(items, ser_plain)


@app.post(f"{PREFIX}/disinterment-authorizations/<auth_id>/record-clearance")
def record_clearance(auth_id):
    _, role = authenticate()
    require(role, {"HealthOfficer"})
    a = must_get(db.disinterments, auth_id)
    if a["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Authorization is not REQUESTED")
    if a["health_cleared"]:
        err("ERR_ALREADY_RECORDED", 409, "Health clearance already recorded")
    a["health_cleared"] = True
    touch(a)
    return ok_obj(ser_plain(a))


@app.post(f"{PREFIX}/disinterment-authorizations/<auth_id>/record-consent")
def record_consent(auth_id):
    user_id, role = authenticate()
    require(role, {"RightHolder"})
    a = must_get(db.disinterments, auth_id)
    # ownership: acting holder must hold the interment's deed
    inter = db.interments.get(a["interment_id"])
    deed = db.deeds.get(inter["deed_id"]) if inter else None
    if deed is None or user_id != deed["holder_id"]:
        err("ERR_FORBIDDEN", 403, "Only the interment's deed holder may consent")
    if a["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Authorization is not REQUESTED")
    if a["nok_consented"]:
        err("ERR_ALREADY_RECORDED", 409, "Consent already recorded")
    a["nok_consented"] = True
    touch(a)
    return ok_obj(ser_plain(a))


@app.post(f"{PREFIX}/disinterment-authorizations/<auth_id>/approve")
def approve_disinterment(auth_id):
    user_id, role = authenticate()
    require(role, {"CemeteryDirector"})
    a = must_get(db.disinterments, auth_id)
    if a["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Authorization is not REQUESTED")
    if not (a["health_cleared"] and a["nok_consented"]):
        err("ERR_CONSENT_INCOMPLETE", 409, "Both clearance and consent are required")
    a["status"] = "APPROVED"
    a["approved_by_user_id"] = user_id
    touch(a)
    return ok_obj(ser_plain(a))


@app.post(f"{PREFIX}/disinterment-authorizations/<auth_id>/deny")
def deny_disinterment(auth_id):
    _, role = authenticate()
    require(role, {"CemeteryDirector"})
    get_body()
    a = must_get(db.disinterments, auth_id)
    if a["status"] != "REQUESTED":
        err("ERR_INVALID_STATE", 409, "Authorization is not REQUESTED")
    a["status"] = "DENIED"
    touch(a)
    inv = db.invoices.get(a["disinterment_invoice_id"])
    if inv is not None and inv["status"] == "ISSUED":
        inv["status"] = "VOID"
        touch(inv)
    return ok_obj(ser_plain(a))


@app.post(f"{PREFIX}/disinterment-authorizations/<auth_id>/execute")
def execute_disinterment(auth_id):
    user_id, role = authenticate()
    require(role, {"Registrar"})
    a = must_get(db.disinterments, auth_id)
    if a["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Authorization is not APPROVED")
    # segregation of duties (before fiscal per PRD §2.5)
    if user_id == a.get("approved_by_user_id"):
        err("ERR_SEGREGATION_OF_DUTIES", 409, "Approver may not execute")
    inv = db.invoices.get(a["disinterment_invoice_id"])
    if inv is None or inv["status"] != "PAID":
        err("ERR_INVOICE_UNPAID", 409, "DISINTERMENT invoice is not PAID")
    inter = db.interments.get(a["interment_id"])
    deed = db.deeds.get(inter["deed_id"]) if inter else None
    contribution = deed["care_fund_contribution_cents"] if deed else 0
    pct = RELOC_CREDIT_PCT if a["disinterment_type"] == "RELOCATION" else REMOVAL_REFUND_PCT
    settlement = round_half_up(Decimal(contribution) * pct)
    a["settlement_cents"] = settlement
    a["status"] = "EXECUTED"
    touch(a)
    # cascade: interment -> DISINTERRED
    if inter is not None:
        inter["operational_status"] = "DISINTERRED"
        touch(inter)
        # INSTALLED marker permit on plot -> DECOMMISSIONED
        for m in db.markers.values():
            if m["plot_id"] == inter["plot_id"] and m["status"] == "INSTALLED":
                m["status"] = "DECOMMISSIONED"
                touch(m)
        # settlement disbursement
        plot = db.plots.get(inter["plot_id"])
        cem_id = plot["cemetery_id"] if plot else None
        if cem_id is not None:
            post_care_entry(cem_id, "DISBURSEMENT", settlement,
                            source_deed_id=(deed["id"] if deed else None),
                            note="disinterment settlement")
    return ok_obj(ser_plain(a))


# ===========================================================================
# MARKER PERMIT
# ===========================================================================
@app.post(f"{PREFIX}/marker-permits")
def create_marker_permit():
    user_id, role = authenticate()
    require(role, {"Registrar", "RightHolder"})
    body = get_body()
    plot_id = req_str(body, "plot_id")
    deed_id = req_str(body, "deed_id")
    marker_type = req_enum(body, "marker_type", MARKER_TYPES)
    length_in = req_int(body, "foundation_length_in", min_val=1)
    width_in = req_int(body, "foundation_width_in", min_val=1)
    must_get(db.plots, plot_id)
    deed = must_get(db.deeds, deed_id)
    # RightHolder ownership: must own the referenced deed
    if role == "RightHolder" and user_id != deed["holder_id"]:
        err("ERR_FORBIDDEN", 403, "RightHolder must own the referenced deed")
    fee = MARKER_FEE_BY_TYPE[marker_type]
    permit = base_common()
    permit.update({"plot_id": plot_id, "deed_id": deed_id, "marker_type": marker_type,
                   "foundation_length_in": length_in, "foundation_width_in": width_in,
                   "foundation_fee_cents": fee, "status": "APPLIED"})
    lines = [{"label": "foundation", "amount_cents": fee, "taxable": True}]
    inv = create_invoice(deed["holder_id"], "MARKER_FOUNDATION", permit["id"], lines, user_id)
    permit["foundation_invoice_id"] = inv["id"]
    db.markers[permit["id"]] = permit
    return ok_obj(ser_plain(permit), 201)


@app.get(f"{PREFIX}/marker-permits/<permit_id>")
def get_marker_permit(permit_id):
    _, role = authenticate()
    require(role, {"Registrar", "GroundsForeman", "FinanceOfficer",
                   "CemeteryDirector", "RightHolder"})
    m = must_get(db.markers, permit_id)
    return ok_obj(ser_plain(m))


@app.get(f"{PREFIX}/marker-permits")
def list_marker_permits():
    _, role = authenticate()
    require(role, {"Registrar", "GroundsForeman", "FinanceOfficer",
                   "CemeteryDirector", "RightHolder"})
    items = sorted_vals(db.markers)
    for key in ("plot_id", "deed_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [m for m in items if m.get(key) == val]
    return ok_list(items, ser_plain)


@app.post(f"{PREFIX}/marker-permits/<permit_id>/approve")
def approve_marker_permit(permit_id):
    _, role = authenticate()
    require(role, {"CemeteryDirector"})
    m = must_get(db.markers, permit_id)
    if m["status"] != "APPLIED":
        err("ERR_INVALID_STATE", 409, "Permit is not APPLIED")
    deed = db.deeds.get(m["deed_id"])
    if deed is None or deed["status"] != "ISSUED":
        err("ERR_DEED_NOT_ISSUED", 409, "Referenced deed must be ISSUED")
    m["status"] = "APPROVED"
    touch(m)
    return ok_obj(ser_plain(m))


@app.post(f"{PREFIX}/marker-permits/<permit_id>/install")
def install_marker_permit(permit_id):
    _, role = authenticate()
    require(role, {"GroundsForeman"})
    m = must_get(db.markers, permit_id)
    if m["status"] != "APPROVED":
        err("ERR_INVALID_STATE", 409, "Permit is not APPROVED")
    # plot must have a COMPLETED interment (referential, before fiscal)
    has_completed = any(i["plot_id"] == m["plot_id"] and i["operational_status"] == "COMPLETED"
                        for i in db.interments.values())
    if not has_completed:
        err("ERR_NO_COMPLETED_INTERMENT", 409, "Plot has no COMPLETED interment")
    inv = db.invoices.get(m["foundation_invoice_id"])
    if inv is None or inv["status"] != "PAID":
        err("ERR_INVOICE_UNPAID", 409, "MARKER_FOUNDATION invoice is not PAID")
    m["status"] = "INSTALLED"
    touch(m)
    return ok_obj(ser_plain(m))


@app.post(f"{PREFIX}/marker-permits/<permit_id>/reject")
def reject_marker_permit(permit_id):
    _, role = authenticate()
    require(role, {"CemeteryDirector"})
    get_body()
    m = must_get(db.markers, permit_id)
    if m["status"] != "APPLIED":
        err("ERR_INVALID_STATE", 409, "Permit is not APPLIED")
    m["status"] = "REJECTED"
    touch(m)
    inv = db.invoices.get(m["foundation_invoice_id"])
    if inv is not None and inv["status"] == "ISSUED":
        inv["status"] = "VOID"
        touch(inv)
    return ok_obj(ser_plain(m))


# ===========================================================================
# INVOICE
# ===========================================================================
@app.get(f"{PREFIX}/invoices/<invoice_id>")
def get_invoice(invoice_id):
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector", "RightHolder"})
    inv = must_get(db.invoices, invoice_id)
    return ok_obj(ser_plain(inv))


@app.get(f"{PREFIX}/invoices")
def list_invoices():
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector", "RightHolder"})
    items = sorted_vals(db.invoices)
    for key in ("holder_id", "subject_id", "status"):
        val = request.args.get(key)
        if val is not None:
            items = [inv for inv in items if inv.get(key) == val]
    return ok_list(items, ser_plain)


@app.post(f"{PREFIX}/invoices/<invoice_id>/void")
def void_invoice(invoice_id):
    user_id, role = authenticate()
    require(role, {"FinanceOfficer"})
    inv = must_get(db.invoices, invoice_id)
    if inv["status"] != "ISSUED":
        err("ERR_INVOICE_NOT_OPEN", 409, "Invoice is not ISSUED")
    if user_id == inv["issued_by_user_id"]:
        err("ERR_SEGREGATION_OF_DUTIES", 409, "May not void an invoice you issued")
    inv["status"] = "VOID"
    touch(inv)
    return ok_obj(ser_plain(inv))


# ===========================================================================
# PAYMENT
# ===========================================================================
def _apply_payment_cascade(inv, actor_id):
    st = inv["subject_type"]
    if st == "DEED_SALE":
        deed = db.deeds.get(inv["subject_id"])
        if deed is not None and deed["status"] == "PENDING_PAYMENT":
            deed["status"] = "ISSUED"
            touch(deed)
            plot = db.plots.get(deed["plot_id"])
            if plot is not None and plot["status"] == "RESERVED":
                plot["status"] = "SOLD"
                touch(plot)
            post_care_entry(plot["cemetery_id"] if plot else None,
                            "CONTRIBUTION", deed["care_fund_contribution_cents"],
                            source_deed_id=deed["id"], note="deed sale contribution")
    elif st == "INTERMENT_SERVICE":
        inter = db.interments.get(inv["subject_id"])
        if inter is not None:
            inter["billing_status"] = "PAID"
            touch(inter)


@app.post(f"{PREFIX}/payments")
def create_payment():
    user_id, role = authenticate()
    require(role, {"FinanceOfficer"})
    body = get_body()
    invoice_id = req_str(body, "invoice_id")
    amount_cents = req_int(body, "amount_cents", min_val=0)
    method = req_enum(body, "method", PAYMENT_METHODS)
    inv = must_get(db.invoices, invoice_id)
    if inv["status"] != "ISSUED":
        err("ERR_INVOICE_NOT_OPEN", 409, "Invoice is not ISSUED")
    if amount_cents != inv["total_cents"]:
        err("ERR_PAYMENT_AMOUNT_MISMATCH", 409, "Payment must equal invoice total")
    inv["status"] = "PAID"
    touch(inv)
    pay = base_light()
    pay.update({"invoice_id": invoice_id, "amount_cents": amount_cents, "method": method})
    db.payments[pay["id"]] = pay
    _apply_payment_cascade(inv, user_id)
    return ok_obj(ser_plain(pay), 201)


@app.get(f"{PREFIX}/payments/<payment_id>")
def get_payment(payment_id):
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector"})
    p = must_get(db.payments, payment_id)
    return ok_obj(ser_plain(p))


@app.get(f"{PREFIX}/payments")
def list_payments():
    _, role = authenticate()
    require(role, {"Registrar", "FinanceOfficer", "CemeteryDirector"})
    items = sorted_vals(db.payments)
    invoice_id = request.args.get("invoice_id")
    if invoice_id is not None:
        items = [p for p in items if p["invoice_id"] == invoice_id]
    return ok_list(items, ser_plain)


# ===========================================================================
# CARE FUND ENTRY
# ===========================================================================
@app.post(f"{PREFIX}/care-fund-entries")
def create_care_fund_entry():
    _, role = authenticate()
    require(role, {"FinanceOfficer"})
    body = get_body()
    cemetery_id = req_str(body, "cemetery_id")
    entry_type = req_enum(body, "entry_type", ENTRY_TYPES)
    amount_cents = req_int(body, "amount_cents", min_val=0)
    source_deed_id = opt_str(body, "source_deed_id")
    note = opt_str(body, "note")
    must_get(db.cemeteries, cemetery_id)
    if source_deed_id is not None:
        must_get(db.deeds, source_deed_id)
    if entry_type == "DISBURSEMENT":
        if fund_balance(cemetery_id) - amount_cents < 0:
            err("ERR_CARE_FUND_INSUFFICIENT", 409, "Disbursement would drive balance below zero")
    e = post_care_entry(cemetery_id, entry_type, amount_cents, source_deed_id, note)
    return ok_obj(ser_plain(e), 201)


@app.get(f"{PREFIX}/care-fund-entries/<entry_id>")
def get_care_fund_entry(entry_id):
    _, role = authenticate()
    require(role, {"FinanceOfficer", "CemeteryDirector"})
    e = must_get(db.care_entries, entry_id)
    return ok_obj(ser_plain(e))


@app.get(f"{PREFIX}/care-fund-entries")
def list_care_fund_entries():
    _, role = authenticate()
    require(role, {"FinanceOfficer", "CemeteryDirector"})
    items = sorted_vals(db.care_entries)
    for key in ("cemetery_id", "source_deed_id", "entry_type"):
        val = request.args.get(key)
        if val is not None:
            items = [e for e in items if e.get(key) == val]
    return ok_list(items, ser_plain)


# ===========================================================================
# LOGICAL CLOCK (test-driving)
# ===========================================================================
@app.post(f"{PREFIX}/_clock/set_current_utc")
def set_clock():
    _, role = authenticate()
    require(role, {"Registrar", "GroundsForeman", "FinanceOfficer",
                   "HealthOfficer", "CemeteryDirector"})
    body = get_body()
    to_iso = req_str(body, "to_iso8601")
    try:
        dt = datetime.fromisoformat(to_iso.replace("Z", "+00:00"))
    except ValueError:
        err("ERR_VALIDATION", 400, "to_iso8601 must be an ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    db.clock = dt.astimezone(timezone.utc)
    return ok_obj({})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
