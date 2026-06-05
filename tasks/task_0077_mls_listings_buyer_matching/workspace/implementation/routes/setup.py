"""Brokerages, Agents, Buyers, clock — the setup surface."""
from datetime import datetime, timezone

from flask import Blueprint

from db import db
from errors import err
from helpers import (body, get_or_404, require_int, require_number, require_str)
from response import ok, created, ok_list, parse_pagination, paginate
from serializers import serialize_brokerage, serialize_agent, serialize_buyer
from services.entities import make_brokerage, make_agent, make_buyer
from services.state import touch

bp = Blueprint("setup", __name__)


# --- Brokerages ---
@bp.post("/brokerages")
def create_brokerage():
    data = body()
    name = require_str(data, "name")
    total_pct = require_number(data, "default_total_commission_pct")
    coop_pct = require_number(data, "default_coop_split_pct")
    if not (0 < total_pct <= 0.10):
        raise err("ERR_VALIDATION", "default_total_commission_pct out of range")
    if not (0 <= coop_pct <= 1):
        raise err("ERR_VALIDATION", "default_coop_split_pct out of range")
    rec = make_brokerage(name, total_pct, coop_pct)
    return created(serialize_brokerage(rec))


@bp.get("/brokerages/<bid>")
def get_brokerage(bid):
    rec = get_or_404(db.brokerages, bid)
    return ok(serialize_brokerage(rec))


@bp.get("/brokerages/<bid>/agents")
def list_brokerage_agents(bid):
    get_or_404(db.brokerages, bid)
    limit, offset = parse_pagination()
    rows = [a for a in db.agents.values() if a["brokerage_id"] == bid]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_agent(a) for a in page], total, limit, offset)


# --- Agents ---
@bp.post("/agents")
def create_agent():
    data = body()
    brokerage_id = require_str(data, "brokerage_id")
    full_name = require_str(data, "full_name")
    license_no = require_str(data, "license_no")
    get_or_404(db.brokerages, brokerage_id)
    # license_no globally unique
    if any(a["license_no"] == license_no for a in db.agents.values()):
        raise err("ERR_DUPLICATE", "license_no already registered")
    rec = make_agent(brokerage_id, full_name, license_no)
    return created(serialize_agent(rec))


@bp.get("/agents/<aid>")
def get_agent(aid):
    rec = get_or_404(db.agents, aid)
    return ok(serialize_agent(rec))


@bp.post("/agents/<aid>/suspend")
def suspend_agent(aid):
    rec = get_or_404(db.agents, aid)
    rec["status"] = "SUSPENDED"
    touch(rec)
    return ok(serialize_agent(rec))


@bp.get("/agents/<aid>/buyers")
def list_agent_buyers(aid):
    get_or_404(db.agents, aid)
    limit, offset = parse_pagination()
    rows = [b for b in db.buyers.values() if b["buyer_agent_id"] == aid]
    page, total = paginate(rows, limit, offset)
    return ok_list([serialize_buyer(b) for b in page], total, limit, offset)


# --- Buyers ---
@bp.post("/buyers")
def create_buyer():
    data = body()
    buyer_agent_id = require_str(data, "buyer_agent_id")
    full_name = require_str(data, "full_name")
    max_budget = require_int(data, "max_budget_cents", min_value=0)
    monthly_income = require_int(data, "monthly_income_cents", min_value=0)
    prequal = require_int(data, "prequalified_amount_cents", required=False, default=0, min_value=0)
    monthly_debt = require_int(data, "monthly_debt_cents", required=False, default=0, min_value=0)
    get_or_404(db.agents, buyer_agent_id)
    rec = make_buyer(buyer_agent_id, full_name, max_budget, prequal, monthly_income, monthly_debt)
    return created(serialize_buyer(rec))


@bp.get("/buyers/<bid>")
def get_buyer(bid):
    rec = get_or_404(db.buyers, bid)
    return ok(serialize_buyer(rec))


# --- Clock (test-driving) ---
@bp.post("/_clock/set")
def set_clock():
    data = body()
    to_iso = data.get("to_iso8601")
    if not isinstance(to_iso, str):
        raise err("ERR_VALIDATION", "to_iso8601 required")
    db.clock = _parse_iso(to_iso)
    return ok({})


def _parse_iso(s):
    raw = s.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        raise err("ERR_VALIDATION", "Invalid ISO 8601 datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)
