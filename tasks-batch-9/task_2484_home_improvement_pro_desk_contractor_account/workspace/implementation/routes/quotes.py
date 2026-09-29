"""Bulk job quotes, quote lines and the negotiation cycle."""
from decimal import Decimal

from flask import Blueprint, request

import clock
import db
import response
import validate as v
from errors import ApiError
from middleware import auth, check_scope, scope_list
from services import stock as stock_svc
from services import tier as tier_svc
from services.money import round_half_up_places

bp = Blueprint("quotes", __name__)

MAX_QUOTE_ROUNDS = 3
MAX_APPROVABLE_DISCOUNT_DEPTH_PCT = Decimal("0.30")

QUOTE_READ_ROLES = ("ContractorAdmin", "ProDeskAssociate", "CreditManager")


def _require_active_account(quote):
    account = db.get("pro_accounts", quote["pro_account_id"])
    if account is not None and account["status"] != "ACTIVE":
        raise ApiError("ERR_ACCOUNT_ON_HOLD", 409)
    return account


def _lines_of(quote):
    return db.where("quote_lines", job_quote_id=quote["id"])


# ---------------------------------------------------------------- job quotes
@bp.post("/pro/job-quotes")
def create_quote():
    user_id, role = auth("ContractorAdmin")
    data = v.body()
    account = v.resolve_fk(data, "pro_account_id", "pro_accounts", "ERR_PRO_ACCOUNT_NOT_FOUND")
    if account is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'pro_account_id' is required.")
    store = v.resolve_fk(data, "originating_store_id", "stores", "ERR_STORE_NOT_FOUND")
    if store is None:
        raise ApiError("ERR_INVALID_REQUEST", 400, "Field 'originating_store_id' is required.")
    job_name = v.req_str(data, "job_name")
    requested_term_days = v.req_int(data, "requested_term_days", minimum=1)
    check_scope(role, user_id, account["id"])
    rec = db.new_record("job_quotes", {
        "pro_account_id": account["id"],
        "originating_store_id": store["id"],
        "job_name": job_name,
        "requested_term_days": requested_term_days,
        "status": "DRAFT",
        "round_count": 0,
        "revision_count": 0,
        "list_subtotal_cents": None,
        "negotiated_total_cents": None,
        "discount_depth_pct": None,
        "term_days": None,
        "term_start": None,
        "term_end": None,
        "authored_by_user_id": None,
        "approved_by_user_id": None,
        "withdrawn_reason_code": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/job-quotes/<job_quote_id>")
def get_quote(job_quote_id):
    user_id, role = auth(*QUOTE_READ_ROLES)
    quote = db.require("job_quotes", job_quote_id)
    check_scope(role, user_id, quote["pro_account_id"])
    return response.obj(db.public(quote))


@bp.get("/pro/job-quotes")
def list_quotes():
    user_id, role = auth(*QUOTE_READ_ROLES)
    records = db.all_of("job_quotes")
    for key in ("pro_account_id", "originating_store_id", "status"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    records = scope_list(role, user_id, records, lambda r: r["pro_account_id"])
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# ---------------------------------------------------------------- quote lines
@bp.post("/pro/job-quotes/<job_quote_id>/lines")
def create_quote_line(job_quote_id):
    user_id, role = auth("ContractorAdmin")
    quote = db.require("job_quotes", job_quote_id)
    data = v.body()
    sku = v.req_str(data, "sku")
    qty_units = v.req_int(data, "qty_units", minimum=1)
    check_scope(role, user_id, quote["pro_account_id"])
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    if stock_svc.find_stock(quote["originating_store_id"], sku) is None:
        raise ApiError("ERR_SKU_NOT_STOCKED", 422)
    for existing in _lines_of(quote):
        if existing["sku"] == sku:
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "A quote may carry only one line per SKU.")
    rec = db.new_record("quote_lines", {
        "job_quote_id": quote["id"],
        "sku": sku,
        "qty_units": qty_units,
        "list_unit_price_cents": None,
        "negotiated_unit_price_cents": None,
        "line_list_subtotal_cents": None,
        "line_negotiated_subtotal_cents": None,
    })
    return response.obj(db.public(rec), 201)


@bp.get("/pro/job-quotes/<job_quote_id>/lines")
def list_quote_lines_of(job_quote_id):
    user_id, role = auth(*QUOTE_READ_ROLES)
    quote = db.require("job_quotes", job_quote_id)
    check_scope(role, user_id, quote["pro_account_id"])
    items, meta = v.paginate(_lines_of(quote))
    return response.array(items, 200, meta)


@bp.get("/pro/quote-lines/<quote_line_id>")
def get_quote_line(quote_line_id):
    user_id, role = auth(*QUOTE_READ_ROLES)
    line = db.require("quote_lines", quote_line_id)
    quote = db.get("job_quotes", line["job_quote_id"])
    check_scope(role, user_id, quote["pro_account_id"] if quote else None)
    return response.obj(db.public(line))


@bp.get("/pro/quote-lines")
def list_quote_lines():
    user_id, role = auth(*QUOTE_READ_ROLES)
    records = db.all_of("quote_lines")
    for key in ("job_quote_id", "sku"):
        value = request.args.get(key)
        if value is not None:
            records = [r for r in records if r[key] == value]
    if role == "ContractorAdmin":
        def owner(line):
            quote = db.get("job_quotes", line["job_quote_id"])
            return quote["pro_account_id"] if quote else None
        records = scope_list(role, user_id, records, owner)
    items, meta = v.paginate(records)
    return response.array(items, 200, meta)


# ---------------------------------------------------------------- transitions
@bp.post("/pro/job-quotes/<job_quote_id>/submit")
def submit_quote(job_quote_id):
    user_id, role = auth("ContractorAdmin")
    quote = db.require("job_quotes", job_quote_id)
    check_scope(role, user_id, quote["pro_account_id"])
    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", 409)
    _require_active_account(quote)
    lines = _lines_of(quote)
    for line in lines:
        if stock_svc.find_stock(quote["originating_store_id"], line["sku"]) is None:
            raise ApiError("ERR_SKU_NOT_STOCKED", 422)
    if not lines:
        raise ApiError("ERR_NO_QUOTE_LINES", 422)

    list_subtotal = 0
    for line in lines:
        stock = stock_svc.find_stock(quote["originating_store_id"], line["sku"])
        line["list_unit_price_cents"] = stock["list_unit_price_cents"]
        line["line_list_subtotal_cents"] = stock["list_unit_price_cents"] * line["qty_units"]
        list_subtotal += line["line_list_subtotal_cents"]
        db.touch(line)
    quote["list_subtotal_cents"] = list_subtotal
    quote["status"] = "SUBMITTED"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/counter-offers")
def counter_offer(job_quote_id):
    user_id, _role = auth("ProDeskAssociate")
    quote = db.require("job_quotes", job_quote_id)
    data = v.body()
    entries = v.req_array(data, "line_prices")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Each line_prices entry must be an object.")
    # rung 4: every named quote line must resolve, and must belong to this quote
    resolved = []
    for entry in entries:
        line_id = entry.get("quote_line_id")
        line = db.get("quote_lines", line_id) if isinstance(line_id, str) else None
        if line is None or line["job_quote_id"] != quote["id"]:
            raise ApiError("ERR_QUOTE_LINE_NOT_FOUND", 404)
        resolved.append((line, entry))
    for _line, entry in resolved:
        if isinstance(entry.get("negotiated_unit_price_cents"), bool) or \
                not isinstance(entry.get("negotiated_unit_price_cents"), int):
            raise ApiError("ERR_INVALID_REQUEST", 400,
                           "Each line_prices entry needs an integer negotiated_unit_price_cents.")
    term_days = v.req_int(data, "term_days", minimum=1)
    expected_version = v.req_int(data, "expected_job_quote_version")
    if expected_version != quote["version"]:
        raise ApiError("ERR_STALE_VERSION", 412)
    if quote["status"] != "SUBMITTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if quote["round_count"] >= MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUND_LIMIT", 409)
    all_lines = _lines_of(quote)
    named_ids = {line["id"] for line, _entry in resolved}
    if len(named_ids) != len(all_lines) or any(line["id"] not in named_ids for line in all_lines):
        raise ApiError("ERR_INCOMPLETE_COUNTER_OFFER", 422)
    for line, entry in resolved:
        price = entry["negotiated_unit_price_cents"]
        if price < 1 or price > (line["list_unit_price_cents"] or 0):
            raise ApiError("ERR_INVALID_NEGOTIATED_PRICE", 422)

    negotiated_total = 0
    for line, entry in resolved:
        line["negotiated_unit_price_cents"] = entry["negotiated_unit_price_cents"]
        line["line_negotiated_subtotal_cents"] = \
            line["negotiated_unit_price_cents"] * line["qty_units"]
        negotiated_total += line["line_negotiated_subtotal_cents"]
        db.touch(line)
    quote["negotiated_total_cents"] = negotiated_total
    list_subtotal = quote["list_subtotal_cents"] or 0
    if list_subtotal > 0:
        depth = round_half_up_places(
            (Decimal(list_subtotal) - Decimal(negotiated_total)) / Decimal(list_subtotal), 4)
        quote["discount_depth_pct"] = float(depth)
    else:
        quote["discount_depth_pct"] = 0.0
    quote["term_days"] = term_days
    quote["authored_by_user_id"] = user_id
    quote["round_count"] += 1
    quote["status"] = "COUNTERED"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/revise")
def revise_quote(job_quote_id):
    user_id, role = auth("ContractorAdmin")
    quote = db.require("job_quotes", job_quote_id)
    data = v.body()
    v.req_str(data, "revision_note")
    check_scope(role, user_id, quote["pro_account_id"])
    if quote["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", 409)
    _require_active_account(quote)
    if quote["round_count"] >= MAX_QUOTE_ROUNDS:
        raise ApiError("ERR_QUOTE_ROUND_LIMIT", 409)
    quote["revision_count"] += 1
    quote["status"] = "SUBMITTED"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/approve")
def approve_quote(job_quote_id):
    user_id, _role = auth("CreditManager")
    quote = db.require("job_quotes", job_quote_id)
    if quote["status"] != "COUNTERED":
        raise ApiError("ERR_INVALID_STATE", 409)
    _require_active_account(quote)
    if quote.get("authored_by_user_id") == user_id:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403)
    depth = quote.get("discount_depth_pct")
    if depth is not None and Decimal(str(depth)) > MAX_APPROVABLE_DISCOUNT_DEPTH_PCT:
        raise ApiError("ERR_DISCOUNT_DEPTH_EXCEEDED", 422)
    quote["approved_by_user_id"] = user_id
    quote["status"] = "APPROVED"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/accept")
def accept_quote(job_quote_id):
    user_id, role = auth("ContractorAdmin")
    quote = db.require("job_quotes", job_quote_id)
    check_scope(role, user_id, quote["pro_account_id"])
    if quote["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE", 409)
    account = _require_active_account(quote)
    cap = tier_svc.tier_by_code(account.get("tier_code") if account else None)["max_quote_term_days"]
    term_days = min(quote["requested_term_days"], cap)
    term_start = clock.get_now()
    term_end = clock.add_days(term_start, term_days)
    quote["term_days"] = term_days
    quote["term_start"] = clock.fmt(term_start)
    quote["term_end"] = clock.fmt(term_end)
    quote["_term_start"] = term_start
    quote["_term_end"] = term_end
    quote["status"] = "ACCEPTED"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/withdraw")
def withdraw_quote(job_quote_id):
    user_id, role = auth("ContractorAdmin")
    quote = db.require("job_quotes", job_quote_id)
    data = v.body()
    reason_code = v.req_str(data, "reason_code")
    check_scope(role, user_id, quote["pro_account_id"])
    if quote["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED", "APPROVED"):
        raise ApiError("ERR_INVALID_STATE", 409)
    quote["withdrawn_reason_code"] = reason_code
    quote["status"] = "WITHDRAWN"
    db.touch(quote)
    return response.obj(db.public(quote))


@bp.post("/pro/job-quotes/<job_quote_id>/expire")
def expire_quote(job_quote_id):
    auth("ProDeskAssociate")
    quote = db.require("job_quotes", job_quote_id)
    if quote["status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409)
    if quote.get("_term_end") is None or not clock.get_now() > quote["_term_end"]:
        raise ApiError("ERR_QUOTE_TERM_ACTIVE", 409)
    quote["status"] = "EXPIRED"
    db.touch(quote)
    return response.obj(db.public(quote))
