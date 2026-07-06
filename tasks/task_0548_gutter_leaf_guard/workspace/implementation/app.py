"""Gutter Installation & Leaf-Guard platform API (Flask, in-memory).

Boots empty on every start; the test harness restarts this process before
every test under `prd-bench-local-run --isolation per-test-server`.
"""

import os
from datetime import timedelta

from flask import Flask, request, jsonify

import core
from core import (
    ApiError, D, rhu, parse_iso, parse_date, iso_ms, clock_now,
    stamp_common, touch, make_meta,
    price_quote, compute_financing, compute_install_days, compute_deposit,
    compute_referral_payout, compute_remediation,
    NO_SHOW_LIMIT, QUOTE_VALIDITY_DAYS, MIN_FINANCE_AMOUNT_CENTS,
    FINANCE_MAX_CENTS, TRAVEL_BUFFER,
)

app = Flask(__name__)

ALL_ROLES = {"Admin", "SalesRep", "Scheduler", "WarrantyAgent"}

# Status enum sets (for structural to_status validation -> ERR_VALIDATION)
LEAD_STATES = {"NEW", "CONTACTED", "APPOINTMENT_SET", "QUOTED", "WON", "LOST"}
APPT_STATES = {"SCHEDULED", "CONFIRMED", "COMPLETED", "CANCELED", "NO_SHOW"}
QUOTE_STATES = {"DRAFT", "PRESENTED", "ACCEPTED", "DECLINED", "REVISION_REQUESTED", "SUPERSEDED"}
FIN_STATES = {"OFFERED", "ACCEPTED", "CANCELED"}
JOB_STATES = {"PENDING", "SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS", "COMPLETED", "CANCELED"}
CLAIM_STATES = {"SUBMITTED", "UNDER_REVIEW", "APPROVED", "DENIED", "RESOLVED"}
REFERRAL_STATES = {"PENDING", "PAYABLE", "PAID", "CLAWED_BACK"}


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------
def ok(data, response_type="object", pagination=None, status=200):
    body = {"meta": make_meta(pagination), "response_type": response_type, "data": data}
    return jsonify(body), status


@app.errorhandler(ApiError)
def handle_api_error(err):
    body = {
        "meta": make_meta(),
        "response_type": "error",
        "data": {"error_id": err.error_id, "message": err.message},
    }
    return jsonify(body), err.http_status


@app.errorhandler(404)
def handle_404(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "not found"}}
    return jsonify(body), 400


@app.errorhandler(405)
def handle_405(_e):
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": "method not allowed"}}
    return jsonify(body), 400


@app.errorhandler(Exception)
def handle_unexpected(err):
    if isinstance(err, ApiError):
        return handle_api_error(err)
    body = {"meta": make_meta(), "response_type": "error",
            "data": {"error_id": "ERR_VALIDATION", "message": str(err)}}
    return jsonify(body), 400


# ---------------------------------------------------------------------------
# Body / field validation (structural -> ERR_VALIDATION 400, "up front")
# ---------------------------------------------------------------------------
def get_body():
    body = request.get_json(silent=True)
    if body is None:
        body = {}
    if not isinstance(body, dict):
        raise ApiError("ERR_VALIDATION", 400, "malformed body")
    return body


def _present(body, name):
    return name in body and body[name] is not None


def sfield(body, name, required=True, enum=None, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
        return default
    v = body[name]
    if not isinstance(v, str):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a string")
    if enum is not None and v not in enum:
        raise ApiError("ERR_VALIDATION", 400, f"{name} not a recognized value")
    return v


def ifield(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be an integer")
    return v


def nfield(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
        return default
    v = body[name]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a number")
    return v


def bfield(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
        return default
    v = body[name]
    if not isinstance(v, bool):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be a boolean")
    return v


def lfield(body, name, required=True, default=None):
    if not _present(body, name):
        if required:
            raise ApiError("ERR_VALIDATION", 400, f"missing field {name}")
        return default
    v = body[name]
    if not isinstance(v, list):
        raise ApiError("ERR_VALIDATION", 400, f"{name} must be an array")
    return v


# ---------------------------------------------------------------------------
# Auth / RBAC
# ---------------------------------------------------------------------------
def authenticate():
    role = request.headers.get("X-User-Role")
    user_id = request.headers.get("X-User-ID")
    if role is None or role not in ALL_ROLES:
        raise ApiError("ERR_UNAUTHENTICATED", 401, "missing or unrecognized X-User-Role")
    return role, user_id


def require_role(role, allowed):
    if role not in allowed:
        raise ApiError("ERR_UNAUTHORIZED", 403, "role not permitted for this operation")


def check_lead_owned(role, user_id, lead):
    if role == "SalesRep" and lead.get("sales_rep_id") != user_id:
        raise ApiError("ERR_UNAUTHORIZED", 403, "sales rep does not own this lead")


# ---------------------------------------------------------------------------
# Existence helpers
# ---------------------------------------------------------------------------
def get_or_404(store, rid, err_id):
    e = store.get(rid)
    if e is None:
        raise ApiError(err_id, 404, f"{err_id}")
    return e


# ---------------------------------------------------------------------------
# Pagination + listing
# ---------------------------------------------------------------------------
def parse_pagination():
    args = request.args
    limit_raw = args.get("limit", None)
    offset_raw = args.get("offset", None)
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 422, "invalid limit")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (ValueError, TypeError):
            raise ApiError("ERR_PAGINATION_INVALID", 422, "invalid offset")
    if limit < 1 or limit > 100:
        raise ApiError("ERR_PAGINATION_INVALID", 422, "limit out of range")
    if offset < 0:
        raise ApiError("ERR_PAGINATION_INVALID", 422, "offset must be >= 0")
    return limit, offset


def list_response(items):
    limit, offset = parse_pagination()
    ordered = sorted(items, key=lambda e: e["created_at"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    meta = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }
    return ok([dict(e) for e in page], "array", pagination=meta, status=200)


def out(entity, status=200):
    return ok(dict(entity), "object", status=status)


# ---------------------------------------------------------------------------
# Aggregate recompute + cascades
# ---------------------------------------------------------------------------
def recompute_crew_booked_days(crew):
    total = sum(
        j["install_days"] for j in core.jobs.values()
        if j.get("crew_id") == crew["id"] and j["status"] in ("SCHEDULED", "IN_PROGRESS")
    )
    if crew.get("booked_days") != total:
        crew["booked_days"] = total
        touch(crew)


def recompute_no_show_strikes(lead):
    count = sum(
        1 for a in core.appointments.values()
        if a["lead_id"] == lead["id"] and a["status"] == "NO_SHOW"
    )
    if lead.get("no_show_strikes") != count:
        lead["no_show_strikes"] = count
        touch(lead)
    return count


def recompute_credit(lead):
    total = sum(
        r.get("payout_cents", 0) for r in core.referrals.values()
        if r.get("referrer_lead_id") == lead["id"] and r["status"] in ("PAYABLE", "PAID")
    )
    if lead.get("credit_balance_cents") != total:
        lead["credit_balance_cents"] = total
        touch(lead)


def lead_lost_cascade(lead):
    for q in core.quotes.values():
        if q["lead_id"] == lead["id"] and q["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED"):
            q["status"] = "DECLINED"
            touch(q)
    for a in core.appointments.values():
        if a["lead_id"] == lead["id"] and a["status"] in ("SCHEDULED", "CONFIRMED"):
            a["status"] = "CANCELED"
            touch(a)


def set_lead_lost(lead):
    lead["status"] = "LOST"
    touch(lead)
    lead_lost_cascade(lead)


def quote_accept_cascade(quote):
    lead = core.leads[quote["lead_id"]]
    # link 1: create Job PENDING
    job = {
        "quote_id": quote["id"],
        "lead_id": lead["id"],
        "crew_id": None,
        "install_date": None,
        "install_days": compute_install_days(quote["linear_feet"]),
        "deposit_cents": compute_deposit(quote["total_cents"]),
        "status": "PENDING",
    }
    stamp_common(job)
    core.jobs[job["id"]] = job
    # link 2: Lead QUOTED -> WON
    became_won = False
    if lead["status"] == "QUOTED":
        lead["status"] = "WON"
        touch(lead)
        became_won = True
    # link 3: PENDING referrals whose referee == lead -> PAYABLE
    if became_won:
        for r in core.referrals.values():
            if r["referee_lead_id"] == lead["id"] and r["status"] == "PENDING":
                r["status"] = "PAYABLE"
                r["payout_cents"] = compute_referral_payout(quote["total_cents"])
                touch(r)
                referrer = core.leads.get(r["referrer_lead_id"])
                if referrer is not None:
                    recompute_credit(referrer)
    return job


def job_cancel_clawback(job):
    lead_id = job["lead_id"]
    for r in core.referrals.values():
        if r["referee_lead_id"] == lead_id and r["status"] in ("PAYABLE", "PAID"):
            r["status"] = "CLAWED_BACK"
            touch(r)
            referrer = core.leads.get(r["referrer_lead_id"])
            if referrer is not None:
                recompute_credit(referrer)


# ===========================================================================
# Product
# ===========================================================================
@app.post("/api/products")
def create_product():
    body = get_body()
    name = sfield(body, "name")
    category = sfield(body, "category", enum={"GUTTER", "LEAF_GUARD", "DOWNSPOUT"})
    base_rate = ifield(body, "base_rate_cents_per_foot")
    available_colors = lfield(body, "available_colors")
    premium_colors = lfield(body, "premium_colors")
    surcharge = ifield(body, "color_surcharge_cents_per_foot", required=False, default=0)
    is_active = bfield(body, "is_active", required=False, default=True)
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    p = {
        "name": name,
        "category": category,
        "base_rate_cents_per_foot": base_rate,
        "available_colors": available_colors,
        "premium_colors": premium_colors,
        "color_surcharge_cents_per_foot": surcharge,
        "is_active": is_active,
    }
    stamp_common(p)
    core.products[p["id"]] = p
    return out(p, status=201)


@app.get("/api/products/<pid>")
def get_product(pid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.products, pid, "ERR_PRODUCT_NOT_FOUND"))


# ===========================================================================
# SalesRep
# ===========================================================================
@app.post("/api/sales-reps")
def create_sales_rep():
    body = get_body()
    full_name = sfield(body, "full_name")
    region = sfield(body, "region")
    is_active = bfield(body, "is_active", required=False, default=True)
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    r = {"full_name": full_name, "region": region, "is_active": is_active}
    stamp_common(r)
    core.sales_reps[r["id"]] = r
    return out(r, status=201)


@app.get("/api/sales-reps/<rid>")
def get_sales_rep(rid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.sales_reps, rid, "ERR_SALES_REP_NOT_FOUND"))


# ===========================================================================
# Crew
# ===========================================================================
@app.post("/api/crews")
def create_crew():
    body = get_body()
    name = sfield(body, "name")
    region = sfield(body, "region")
    certified = bfield(body, "is_certified_leaf_guard", required=False, default=False)
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    c = {
        "name": name,
        "region": region,
        "is_certified_leaf_guard": certified,
        "booked_days": 0,
    }
    stamp_common(c)
    core.crews[c["id"]] = c
    return out(c, status=201)


@app.get("/api/crews/<cid>")
def get_crew(cid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.crews, cid, "ERR_CREW_NOT_FOUND"))


# ===========================================================================
# Lead
# ===========================================================================
@app.post("/api/leads")
def create_lead():
    body = get_body()
    full_name = sfield(body, "full_name")
    address = sfield(body, "address")
    phone = sfield(body, "phone")
    region = sfield(body, "region")
    sales_rep_id = sfield(body, "sales_rep_id")
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    if role == "SalesRep" and sales_rep_id != uid:
        raise ApiError("ERR_UNAUTHORIZED", 403, "sales rep may only create own leads")
    get_or_404(core.sales_reps, sales_rep_id, "ERR_SALES_REP_NOT_FOUND")
    lead = {
        "full_name": full_name,
        "address": address,
        "phone": phone,
        "region": region,
        "sales_rep_id": sales_rep_id,
        "status": "NEW",
        "no_show_strikes": 0,
        "credit_balance_cents": 0,
    }
    stamp_common(lead)
    core.leads[lead["id"]] = lead
    return out(lead, status=201)


@app.get("/api/leads/<lid>")
def get_lead(lid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.leads, lid, "ERR_LEAD_NOT_FOUND"))


@app.get("/api/leads")
def list_leads():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    rep = request.args.get("sales_rep_id")
    status = request.args.get("status")
    items = [
        l for l in core.leads.values()
        if (rep is None or l["sales_rep_id"] == rep)
        and (status is None or l["status"] == status)
    ]
    return list_response(items)


@app.post("/api/leads/<lid>/transition")
def transition_lead(lid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=LEAD_STATES)
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    lead = get_or_404(core.leads, lid, "ERR_LEAD_NOT_FOUND")
    check_lead_owned(role, uid, lead)
    cur = lead["status"]
    if to_status == "CONTACTED":
        if cur != "NEW":
            raise ApiError("ERR_INVALID_STATE", 409, "cannot mark CONTACTED")
        lead["status"] = "CONTACTED"
        touch(lead)
    elif to_status == "LOST":
        if cur not in ("NEW", "CONTACTED", "APPOINTMENT_SET", "QUOTED"):
            raise ApiError("ERR_INVALID_STATE", 409, "lead not in a lossable state")
        set_lead_lost(lead)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported manual lead transition")
    return out(lead)


# ===========================================================================
# Appointment
# ===========================================================================
def _appt_windows_overlap(new_start, new_end, ex_start, ex_end):
    return (new_start - TRAVEL_BUFFER) < ex_end and ex_start < (new_end + TRAVEL_BUFFER)


@app.post("/api/appointments")
def create_appointment():
    body = get_body()
    lead_id = sfield(body, "lead_id")
    sales_rep_id = sfield(body, "sales_rep_id")
    start_raw = sfield(body, "scheduled_start")
    end_raw = sfield(body, "scheduled_end")
    new_start = parse_iso(start_raw)
    new_end = parse_iso(end_raw)
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    lead = get_or_404(core.leads, lead_id, "ERR_LEAD_NOT_FOUND")
    get_or_404(core.sales_reps, sales_rep_id, "ERR_SALES_REP_NOT_FOUND")
    check_lead_owned(role, uid, lead)
    # temporal overlap for the same rep
    for a in core.appointments.values():
        if a["sales_rep_id"] != sales_rep_id:
            continue
        if a["status"] not in ("SCHEDULED", "CONFIRMED"):
            continue
        ex_start = parse_iso(a["scheduled_start"])
        ex_end = parse_iso(a["scheduled_end"])
        if _appt_windows_overlap(new_start, new_end, ex_start, ex_end):
            raise ApiError("ERR_REP_DOUBLE_BOOKED", 409, "rep window overlaps existing booking")
    appt = {
        "lead_id": lead_id,
        "sales_rep_id": sales_rep_id,
        "scheduled_start": start_raw,
        "scheduled_end": end_raw,
        "status": "SCHEDULED",
        "measured_linear_feet": None,
    }
    stamp_common(appt)
    core.appointments[appt["id"]] = appt
    if lead["status"] in ("NEW", "CONTACTED"):
        lead["status"] = "APPOINTMENT_SET"
        touch(lead)
    return out(appt, status=201)


@app.get("/api/appointments/<aid>")
def get_appointment(aid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND"))


@app.get("/api/appointments")
def list_appointments():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    lead_id = request.args.get("lead_id")
    rep = request.args.get("sales_rep_id")
    status = request.args.get("status")
    items = [
        a for a in core.appointments.values()
        if (lead_id is None or a["lead_id"] == lead_id)
        and (rep is None or a["sales_rep_id"] == rep)
        and (status is None or a["status"] == status)
    ]
    return list_response(items)


@app.post("/api/appointments/<aid>/transition")
def transition_appointment(aid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=APPT_STATES)
    measured = nfield(body, "measured_linear_feet", required=False, default=None)
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    appt = get_or_404(core.appointments, aid, "ERR_APPOINTMENT_NOT_FOUND")
    lead = core.leads.get(appt["lead_id"])
    if lead is not None:
        check_lead_owned(role, uid, lead)
    cur = appt["status"]

    if to_status == "CONFIRMED":
        if cur != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "cannot confirm")
        appt["status"] = "CONFIRMED"
        touch(appt)
    elif to_status == "COMPLETED":
        if cur not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot complete")
        if measured is None or D(measured) <= 0:
            raise ApiError("ERR_INVALID_MEASUREMENT", 422, "measured_linear_feet must be > 0")
        appt["measured_linear_feet"] = measured
        appt["status"] = "COMPLETED"
        touch(appt)
    elif to_status == "CANCELED":
        if cur not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot cancel")
        appt["status"] = "CANCELED"
        touch(appt)
    elif to_status == "NO_SHOW":
        if cur not in ("SCHEDULED", "CONFIRMED"):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot mark no-show")
        appt["status"] = "NO_SHOW"
        touch(appt)
        if lead is not None:
            strikes = recompute_no_show_strikes(lead)
            if strikes >= NO_SHOW_LIMIT and lead["status"] not in ("WON", "LOST"):
                set_lead_lost(lead)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported appointment transition")
    return out(appt)


# ===========================================================================
# Quote
# ===========================================================================
def apply_pricing(quote, product, feet):
    subtotal, discount, total = price_quote(
        product, feet, quote["color"], quote["downspout_count"], quote["discount_pct"]
    )
    quote["subtotal_cents"] = subtotal
    quote["discount_cents"] = discount
    quote["total_cents"] = total


@app.post("/api/quotes")
def create_quote():
    body = get_body()
    lead_id = sfield(body, "lead_id")
    appointment_id = sfield(body, "appointment_id")
    sales_rep_id = sfield(body, "sales_rep_id")
    product_id = sfield(body, "product_id")
    color = sfield(body, "color")
    estimated = nfield(body, "estimated_linear_feet")
    expected_lead_version = ifield(body, "expected_lead_version")
    downspout_count = ifield(body, "downspout_count", required=False, default=0)
    discount_pct = nfield(body, "discount_pct", required=False, default=0)
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    # existence (path none; body FK order: lead, appointment, sales_rep, product)
    lead = get_or_404(core.leads, lead_id, "ERR_LEAD_NOT_FOUND")
    get_or_404(core.appointments, appointment_id, "ERR_APPOINTMENT_NOT_FOUND")
    get_or_404(core.sales_reps, sales_rep_id, "ERR_SALES_REP_NOT_FOUND")
    product = get_or_404(core.products, product_id, "ERR_PRODUCT_NOT_FOUND")
    # ownership
    check_lead_owned(role, uid, lead)
    # business constraints (priority 8): measurement, discount, color
    if D(estimated) <= 0:
        raise ApiError("ERR_INVALID_MEASUREMENT", 422, "estimated_linear_feet must be > 0")
    if D(discount_pct) < 0 or D(discount_pct) > 1:
        raise ApiError("ERR_INVALID_DISCOUNT", 422, "discount_pct must be within [0,1]")
    if color not in (product.get("available_colors") or []):
        raise ApiError("ERR_COLOR_UNAVAILABLE", 422, "color not available for product")
    # OCC (priority 10)
    if expected_lead_version != lead["version"]:
        raise ApiError("ERR_STALE_VERSION", 412, "expected_lead_version does not match lead")
    # supersede prior non-terminal quotes for this lead
    for q in core.quotes.values():
        if q["lead_id"] == lead_id and q["status"] in ("DRAFT", "PRESENTED", "REVISION_REQUESTED"):
            q["status"] = "SUPERSEDED"
            touch(q)
    quote = {
        "lead_id": lead_id,
        "appointment_id": appointment_id,
        "sales_rep_id": sales_rep_id,
        "product_id": product_id,
        "color": color,
        "estimated_linear_feet": estimated,
        "downspout_count": downspout_count,
        "discount_pct": discount_pct,
        "linear_feet": estimated,
        "measured_linear_feet": None,
        "subtotal_cents": 0,
        "discount_cents": 0,
        "total_cents": 0,
        "presented_at": None,
        "status": "DRAFT",
    }
    apply_pricing(quote, product, estimated)
    stamp_common(quote)
    core.quotes[quote["id"]] = quote
    # lead advance + version bump (always mutated on quote create)
    if lead["status"] == "APPOINTMENT_SET":
        lead["status"] = "QUOTED"
    touch(lead)
    return out(quote, status=201)


@app.get("/api/quotes/<qid>")
def get_quote(qid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.quotes, qid, "ERR_QUOTE_NOT_FOUND"))


@app.get("/api/quotes")
def list_quotes():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    lead_id = request.args.get("lead_id")
    appointment_id = request.args.get("appointment_id")
    rep = request.args.get("sales_rep_id")
    product_id = request.args.get("product_id")
    status = request.args.get("status")
    items = [
        q for q in core.quotes.values()
        if (lead_id is None or q["lead_id"] == lead_id)
        and (appointment_id is None or q["appointment_id"] == appointment_id)
        and (rep is None or q["sales_rep_id"] == rep)
        and (product_id is None or q["product_id"] == product_id)
        and (status is None or q["status"] == status)
    ]
    return list_response(items)


@app.post("/api/quotes/<qid>/present")
def present_quote(qid):
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    quote = get_or_404(core.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    lead = core.leads.get(quote["lead_id"])
    if lead is not None:
        check_lead_owned(role, uid, lead)
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409, "only DRAFT quotes may be presented")
    appt = core.appointments.get(quote["appointment_id"])
    if appt is None or appt["status"] != "COMPLETED":
        raise ApiError("ERR_APPOINTMENT_NOT_COMPLETED", 409, "backing appointment not COMPLETED")
    measured = appt["measured_linear_feet"]
    product = core.products.get(quote["product_id"])
    quote["measured_linear_feet"] = measured
    quote["linear_feet"] = measured
    apply_pricing(quote, product, measured)
    quote["presented_at"] = iso_ms(clock_now())
    quote["status"] = "PRESENTED"
    touch(quote)
    return out(quote)


@app.post("/api/quotes/<qid>/transition")
def transition_quote(qid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=QUOTE_STATES)
    role, uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    quote = get_or_404(core.quotes, qid, "ERR_QUOTE_NOT_FOUND")
    lead = core.leads.get(quote["lead_id"])
    if lead is not None:
        check_lead_owned(role, uid, lead)
    cur = quote["status"]

    if to_status == "ACCEPTED":
        if cur != "PRESENTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only PRESENTED quotes may be accepted")
        presented = parse_iso(quote["presented_at"])
        if clock_now() > presented + timedelta(days=QUOTE_VALIDITY_DAYS):
            raise ApiError("ERR_QUOTE_EXPIRED", 409, "quote validity window elapsed")
        quote["status"] = "ACCEPTED"
        touch(quote)
        quote_accept_cascade(quote)
    elif to_status == "DECLINED":
        if cur != "PRESENTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only PRESENTED quotes may be declined")
        quote["status"] = "DECLINED"
        touch(quote)
    elif to_status == "REVISION_REQUESTED":
        if cur != "PRESENTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only PRESENTED quotes may be revised")
        quote["status"] = "REVISION_REQUESTED"
        touch(quote)
    elif to_status == "DRAFT":
        if cur != "REVISION_REQUESTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only REVISION_REQUESTED may return to DRAFT")
        quote["linear_feet"] = quote["estimated_linear_feet"]
        product = core.products.get(quote["product_id"])
        apply_pricing(quote, product, quote["estimated_linear_feet"])
        quote["presented_at"] = None
        quote["status"] = "DRAFT"
        touch(quote)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported quote transition")
    return out(quote)


# ===========================================================================
# FinancingPlan
# ===========================================================================
@app.post("/api/financing-plans")
def create_financing_plan():
    body = get_body()
    quote_id = sfield(body, "quote_id")
    plan_type = sfield(body, "plan_type", enum={"DEFERRED_INTEREST", "AMORTIZED"})
    apr_bps = ifield(body, "apr_bps")
    term_months = ifield(body, "term_months")
    promo_window_days = ifield(body, "promo_window_days", required=False, default=0)
    if term_months < 1:
        raise ApiError("ERR_VALIDATION", 400, "term_months must be >= 1")
    role, _uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    quote = get_or_404(core.quotes, quote_id, "ERR_QUOTE_NOT_FOUND")
    principal = quote["total_cents"]
    if principal < MIN_FINANCE_AMOUNT_CENTS:
        raise ApiError("ERR_FINANCE_BELOW_MIN", 422, "principal below minimum")
    if principal > FINANCE_MAX_CENTS:
        raise ApiError("ERR_FINANCE_LIMIT_EXCEEDED", 422, "principal exceeds maximum")
    monthly, total_cost = compute_financing(plan_type, apr_bps, term_months, principal)
    plan = {
        "quote_id": quote_id,
        "plan_type": plan_type,
        "apr_bps": apr_bps,
        "term_months": term_months,
        "promo_window_days": promo_window_days,
        "principal_cents": principal,
        "monthly_payment_cents": monthly,
        "total_cost_cents": total_cost,
        "status": "OFFERED",
    }
    stamp_common(plan)
    core.financing_plans[plan["id"]] = plan
    return out(plan, status=201)


@app.get("/api/financing-plans/<fid>")
def get_financing_plan(fid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.financing_plans, fid, "ERR_FINANCING_PLAN_NOT_FOUND"))


@app.get("/api/financing-plans")
def list_financing_plans():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    items = [
        f for f in core.financing_plans.values()
        if (quote_id is None or f["quote_id"] == quote_id)
        and (status is None or f["status"] == status)
    ]
    return list_response(items)


@app.post("/api/financing-plans/<fid>/transition")
def transition_financing_plan(fid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=FIN_STATES)
    role, _uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    plan = get_or_404(core.financing_plans, fid, "ERR_FINANCING_PLAN_NOT_FOUND")
    cur = plan["status"]
    if to_status == "ACCEPTED":
        if cur != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", 409, "only OFFERED plans may be accepted")
        quote = core.quotes.get(plan["quote_id"])
        if quote is None or quote["status"] != "ACCEPTED":
            raise ApiError("ERR_QUOTE_NOT_ACCEPTED", 409, "backing quote not ACCEPTED")
        plan["status"] = "ACCEPTED"
        touch(plan)
    elif to_status == "CANCELED":
        if cur != "OFFERED":
            raise ApiError("ERR_INVALID_STATE", 409, "only OFFERED plans may be canceled")
        plan["status"] = "CANCELED"
        touch(plan)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported financing transition")
    return out(plan)


# ===========================================================================
# Job
# ===========================================================================
@app.get("/api/jobs/<jid>")
def get_job(jid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.jobs, jid, "ERR_JOB_NOT_FOUND"))


@app.get("/api/jobs")
def list_jobs():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    quote_id = request.args.get("quote_id")
    lead_id = request.args.get("lead_id")
    crew_id = request.args.get("crew_id")
    status = request.args.get("status")
    items = [
        j for j in core.jobs.values()
        if (quote_id is None or j["quote_id"] == quote_id)
        and (lead_id is None or j["lead_id"] == lead_id)
        and (crew_id is None or j.get("crew_id") == crew_id)
        and (status is None or j["status"] == status)
    ]
    return list_response(items)


def _job_product(job):
    quote = core.quotes.get(job["quote_id"])
    if quote is None:
        return None
    return core.products.get(quote["product_id"])


def _crew_overlap(crew_id, day0, day1, exclude_job_id):
    for j in core.jobs.values():
        if j["id"] == exclude_job_id:
            continue
        if j.get("crew_id") != crew_id:
            continue
        if j["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        if not j.get("install_date"):
            continue
        o0 = parse_date(j["install_date"])
        o1 = o0 + timedelta(days=j["install_days"] - 1)
        if day0 <= o1 and o0 <= day1:
            return True
    return False


@app.post("/api/jobs/<jid>/schedule")
def schedule_job(jid):
    body = get_body()
    crew_id = sfield(body, "crew_id")
    install_date_raw = sfield(body, "install_date")
    install_date = parse_date(install_date_raw)
    role, _uid = authenticate()
    require_role(role, {"Scheduler", "Admin"})
    job = get_or_404(core.jobs, jid, "ERR_JOB_NOT_FOUND")
    crew = get_or_404(core.crews, crew_id, "ERR_CREW_NOT_FOUND")
    if job["status"] not in ("PENDING", "WEATHER_HOLD"):
        raise ApiError("ERR_INVALID_STATE", 409, "job not schedulable from current state")
    # weather safety
    if core.weather.get(install_date_raw, "CLEAR") == "SEVERE":
        raise ApiError("ERR_WEATHER_UNSAFE", 422, "forecast severe on install date")
    # crew certification
    product = _job_product(job)
    if product is not None and product["category"] == "LEAF_GUARD" and not crew["is_certified_leaf_guard"]:
        raise ApiError("ERR_CREW_NOT_CERTIFIED", 422, "crew not certified for leaf-guard")
    # crew temporal overlap
    day0 = install_date
    day1 = install_date + timedelta(days=job["install_days"] - 1)
    if _crew_overlap(crew_id, day0, day1, job["id"]):
        raise ApiError("ERR_CREW_DOUBLE_BOOKED", 409, "crew day span overlaps existing job")
    job["crew_id"] = crew_id
    job["install_date"] = install_date_raw
    job["status"] = "SCHEDULED"
    touch(job)
    recompute_crew_booked_days(crew)
    return out(job)


@app.post("/api/jobs/<jid>/transition")
def transition_job(jid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=JOB_STATES)
    role, _uid = authenticate()
    require_role(role, {"Scheduler", "Admin"})
    job = get_or_404(core.jobs, jid, "ERR_JOB_NOT_FOUND")
    cur = job["status"]
    crew = core.crews.get(job.get("crew_id")) if job.get("crew_id") else None

    if to_status == "WEATHER_HOLD":
        if cur != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "only SCHEDULED jobs may be held")
        job["status"] = "WEATHER_HOLD"
        touch(job)
        if crew is not None:
            recompute_crew_booked_days(crew)
    elif to_status == "IN_PROGRESS":
        if cur != "SCHEDULED":
            raise ApiError("ERR_INVALID_STATE", 409, "only SCHEDULED jobs may start")
        if clock_now().date() < parse_date(job["install_date"]):
            raise ApiError("ERR_INVALID_STATE", 409, "cannot start before install date")
        today = clock_now().date().isoformat()
        if core.weather.get(today, "CLEAR") == "SEVERE":
            raise ApiError("ERR_WEATHER_UNSAFE", 422, "forecast severe today")
        job["status"] = "IN_PROGRESS"
        touch(job)
    elif to_status == "COMPLETED":
        if cur != "IN_PROGRESS":
            raise ApiError("ERR_INVALID_STATE", 409, "only IN_PROGRESS jobs may complete")
        job["status"] = "COMPLETED"
        touch(job)
        if crew is not None:
            recompute_crew_booked_days(crew)
    elif to_status == "CANCELED":
        if cur not in ("SCHEDULED", "WEATHER_HOLD", "IN_PROGRESS"):
            raise ApiError("ERR_INVALID_STATE", 409, "job not cancelable from current state")
        was_reserving = cur in ("SCHEDULED", "IN_PROGRESS")
        job["status"] = "CANCELED"
        touch(job)
        if crew is not None and was_reserving:
            recompute_crew_booked_days(crew)
        job_cancel_clawback(job)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported job transition")
    return out(job)


# ===========================================================================
# WarrantyClaim
# ===========================================================================
@app.post("/api/warranty-claims")
def create_warranty_claim():
    body = get_body()
    job_id = sfield(body, "job_id")
    issue_type = sfield(body, "issue_type", enum={"CLOG", "OVERFLOW", "DETACHMENT"})
    role, _uid = authenticate()
    require_role(role, {"WarrantyAgent", "Admin"})
    job = get_or_404(core.jobs, job_id, "ERR_JOB_NOT_FOUND")
    if job["status"] != "COMPLETED":
        raise ApiError("ERR_JOB_NOT_COMPLETED", 409, "job must be COMPLETED")
    claim = {
        "job_id": job_id,
        "issue_type": issue_type,
        "estimated_remediation_cents": None,
        "actual_remediation_cents": None,
        "status": "SUBMITTED",
    }
    stamp_common(claim)
    core.warranty_claims[claim["id"]] = claim
    return out(claim, status=201)


@app.get("/api/warranty-claims/<wid>")
def get_warranty_claim(wid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND"))


@app.get("/api/warranty-claims")
def list_warranty_claims():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    job_id = request.args.get("job_id")
    status = request.args.get("status")
    items = [
        w for w in core.warranty_claims.values()
        if (job_id is None or w["job_id"] == job_id)
        and (status is None or w["status"] == status)
    ]
    return list_response(items)


@app.post("/api/warranty-claims/<wid>/transition")
def transition_warranty_claim(wid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=CLAIM_STATES)
    actual = ifield(body, "actual_remediation_cents", required=False, default=None)
    role, _uid = authenticate()
    require_role(role, {"WarrantyAgent", "Admin"})
    claim = get_or_404(core.warranty_claims, wid, "ERR_WARRANTY_CLAIM_NOT_FOUND")
    cur = claim["status"]

    if to_status == "UNDER_REVIEW":
        if cur != "SUBMITTED":
            raise ApiError("ERR_INVALID_STATE", 409, "only SUBMITTED claims may go under review")
        job = core.jobs.get(claim["job_id"])
        quote = core.quotes.get(job["quote_id"]) if job else None
        feet = quote["linear_feet"] if quote else 0
        claim["estimated_remediation_cents"] = compute_remediation(claim["issue_type"], feet)
        claim["status"] = "UNDER_REVIEW"
        touch(claim)
    elif to_status == "APPROVED":
        if cur != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "only UNDER_REVIEW claims may be approved")
        claim["status"] = "APPROVED"
        touch(claim)
    elif to_status == "DENIED":
        if cur != "UNDER_REVIEW":
            raise ApiError("ERR_INVALID_STATE", 409, "only UNDER_REVIEW claims may be denied")
        claim["status"] = "DENIED"
        touch(claim)
    elif to_status == "RESOLVED":
        if cur != "APPROVED":
            raise ApiError("ERR_INVALID_STATE", 409, "only APPROVED claims may be resolved")
        if actual is None or actual < 0:
            raise ApiError("ERR_VALIDATION", 400, "actual_remediation_cents must be present and >= 0")
        claim["actual_remediation_cents"] = actual
        claim["status"] = "RESOLVED"
        touch(claim)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported warranty transition")
    return out(claim)


# ===========================================================================
# Referral
# ===========================================================================
@app.post("/api/referrals")
def create_referral():
    body = get_body()
    referrer_lead_id = sfield(body, "referrer_lead_id")
    referee_lead_id = sfield(body, "referee_lead_id")
    role, _uid = authenticate()
    require_role(role, {"SalesRep", "Admin"})
    get_or_404(core.leads, referrer_lead_id, "ERR_LEAD_NOT_FOUND")
    get_or_404(core.leads, referee_lead_id, "ERR_LEAD_NOT_FOUND")
    if referrer_lead_id == referee_lead_id:
        raise ApiError("ERR_SELF_REFERRAL", 422, "referrer and referee must differ")
    ref = {
        "referrer_lead_id": referrer_lead_id,
        "referee_lead_id": referee_lead_id,
        "payout_cents": 0,
        "status": "PENDING",
    }
    stamp_common(ref)
    core.referrals[ref["id"]] = ref
    return out(ref, status=201)


@app.get("/api/referrals/<rid>")
def get_referral(rid):
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    return out(get_or_404(core.referrals, rid, "ERR_REFERRAL_NOT_FOUND"))


@app.get("/api/referrals")
def list_referrals():
    role, _uid = authenticate()
    require_role(role, ALL_ROLES)
    referrer = request.args.get("referrer_lead_id")
    referee = request.args.get("referee_lead_id")
    status = request.args.get("status")
    items = [
        r for r in core.referrals.values()
        if (referrer is None or r["referrer_lead_id"] == referrer)
        and (referee is None or r["referee_lead_id"] == referee)
        and (status is None or r["status"] == status)
    ]
    return list_response(items)


@app.post("/api/referrals/<rid>/transition")
def transition_referral(rid):
    body = get_body()
    to_status = sfield(body, "to_status", enum=REFERRAL_STATES)
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    ref = get_or_404(core.referrals, rid, "ERR_REFERRAL_NOT_FOUND")
    if to_status == "PAID":
        if ref["status"] != "PAYABLE":
            raise ApiError("ERR_INVALID_STATE", 409, "only PAYABLE referrals may be marked paid")
        ref["status"] = "PAID"
        touch(ref)
    else:
        raise ApiError("ERR_INVALID_STATE", 409, "unsupported referral transition")
    return out(ref)


# ===========================================================================
# Test-driving endpoints: clock + weather (Admin only)
# ===========================================================================
@app.post("/_clock/set_current_utc")
def set_clock():
    body = get_body()
    to_iso = sfield(body, "to_iso8601")
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    core.clock["now"] = parse_iso(to_iso)
    return ok({}, "object", status=200)


@app.post("/_weather/set_forecast")
def set_weather():
    body = get_body()
    install_date = sfield(body, "install_date")
    condition = sfield(body, "condition", enum={"CLEAR", "RAIN", "SEVERE"})
    parse_date(install_date)  # validate format -> 400 if bad
    role, _uid = authenticate()
    require_role(role, {"Admin"})
    core.weather[install_date] = condition
    return ok({}, "object", status=200)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
