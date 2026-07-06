"""MSP Managed IT API — Flask implementation.

Fresh-boot friendly (per-test-server isolation): all state lives in module
globals and is created empty at import time. No seeding.
"""
from __future__ import annotations

import os
import re
import secrets
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from functools import wraps
from typing import Any, Callable, Optional

from flask import Flask, g, jsonify, request


# =============================================================================
# Time helpers
# =============================================================================

DEFAULT_CLOCK_ISO = "2026-05-01T00:00:00Z"
_UTC = timezone.utc


def _parse_iso(value: str) -> datetime:
    """Parse ISO-8601 into an aware UTC datetime. Raises ValueError on failure."""
    if not isinstance(value, str) or not value:
        raise ValueError("empty timestamp")
    v = value.strip()
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    # Python's fromisoformat handles fractional seconds
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    return dt.astimezone(_UTC)


def _format_iso(dt: datetime) -> str:
    """Format an aware UTC datetime as ISO-8601 with 3 fractional digits, Z suffix."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_UTC)
    dt = dt.astimezone(_UTC)
    ms = dt.microsecond // 1000
    return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}.{ms:03d}Z"


# =============================================================================
# Logical clock
# =============================================================================

class Clock:
    def __init__(self) -> None:
        self.now: datetime = _parse_iso(DEFAULT_CLOCK_ISO)

    def set(self, iso: str) -> None:
        self.now = _parse_iso(iso)


CLOCK = Clock()


# =============================================================================
# In-memory store
# =============================================================================

class Store:
    def __init__(self) -> None:
        self.clients: dict[str, dict] = {}
        self.sites: dict[str, dict] = {}
        self.technicians: dict[str, dict] = {}
        self.contracts: dict[str, dict] = {}
        self.assets: dict[str, dict] = {}
        self.patch_jobs: dict[str, dict] = {}
        self.tickets: dict[str, dict] = {}
        self.dispatches: dict[str, dict] = {}
        self.quotes: dict[str, dict] = {}
        self.procurement_orders: dict[str, dict] = {}
        self.invoices: dict[str, dict] = {}
        self.seat_adjustments: dict[str, dict] = {}


DB = Store()


def new_id() -> str:
    return str(uuid.uuid4())


def new_request_id() -> str:
    return "req_" + "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(20))


# =============================================================================
# Errors
# =============================================================================

class AppError(Exception):
    def __init__(self, error_id: str, http_status: int, message: str = "") -> None:
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


# =============================================================================
# Envelope
# =============================================================================

def _meta_base() -> dict:
    return {
        "api_request_id": getattr(g, "api_request_id", new_request_id()),
        "api_request_timestamp": _format_iso(CLOCK.now),
    }


def ok(data: Any, code: int = 200, pagination: Optional[dict] = None):
    meta = _meta_base()
    if pagination is not None:
        meta.update(pagination)
    response_type = "array" if isinstance(data, list) else "object"
    body = {"meta": meta, "response_type": response_type, "data": data}
    return jsonify(body), code


def err(error_id: str, http_status: int, message: str = ""):
    body = {
        "meta": _meta_base(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message or error_id,
        },
    }
    return jsonify(body), http_status


# =============================================================================
# Roles / RBAC
# =============================================================================

ROLES = {"ServiceManager", "Dispatcher", "Technician", "AccountManager", "ClientContact"}


def require_auth() -> tuple[str, str]:
    """Extract and validate X-User-ID / X-User-Role. Raises AppError on failure."""
    user_id = request.headers.get("X-User-ID")
    role = request.headers.get("X-User-Role")
    if not user_id or not role or role not in ROLES:
        raise AppError("ERR_MISSING_AUTH_CONTEXT", 401)
    return user_id, role


def require_roles(role: str, allowed: set[str]) -> None:
    if role not in allowed:
        raise AppError("ERR_FORBIDDEN_ROLE", 403)


# =============================================================================
# Common fields
# =============================================================================

def stamp_common(entity: dict, with_version: bool = True) -> None:
    now = _format_iso(CLOCK.now)
    entity["created_at"] = now
    entity["updated_at"] = now
    if with_version:
        entity["version"] = 1


def touch(entity: dict) -> None:
    entity["updated_at"] = _format_iso(CLOCK.now)
    if "version" in entity:
        entity["version"] += 1


# =============================================================================
# Money & rounding
# =============================================================================

def round_half_up_int(x) -> int:
    return int(Decimal(str(x)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def round_half_up_2dp(x) -> float:
    return float(Decimal(str(x)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# =============================================================================
# Input helpers
# =============================================================================

def get_json() -> dict:
    if request.data:
        try:
            data = request.get_json(force=True, silent=False)
        except Exception:
            raise AppError("ERR_VALIDATION", 400, "malformed JSON body")
        if data is None:
            return {}
        if not isinstance(data, dict):
            raise AppError("ERR_VALIDATION", 400, "body must be a JSON object")
        return data
    return {}


def require_field(data: dict, name: str, kind=None):
    if name not in data or data[name] is None:
        raise AppError("ERR_VALIDATION", 400, f"missing required field: {name}")
    v = data[name]
    if kind is not None and not isinstance(v, kind):
        raise AppError("ERR_VALIDATION", 400, f"invalid type for field: {name}")
    return v


def require_enum(data: dict, name: str, allowed: set[str]) -> str:
    v = require_field(data, name, str)
    if v not in allowed:
        raise AppError("ERR_INVALID_ENUM", 400, f"{name} not in {allowed}")
    return v


def optional_enum(data: dict, name: str, allowed: set[str], default=None):
    if name not in data or data[name] is None:
        return default
    v = data[name]
    if not isinstance(v, str) or v not in allowed:
        raise AppError("ERR_INVALID_ENUM", 400, f"{name} not in {allowed}")
    return v


def parse_iso_field(data: dict, name: str, required: bool = True) -> Optional[datetime]:
    if name not in data or data[name] is None:
        if required:
            raise AppError("ERR_VALIDATION", 400, f"missing required field: {name}")
        return None
    v = data[name]
    if not isinstance(v, str):
        raise AppError("ERR_VALIDATION", 400, f"{name} must be a string")
    try:
        return _parse_iso(v)
    except Exception:
        raise AppError("ERR_VALIDATION", 400, f"{name} is not a valid ISO-8601 timestamp")


def parse_int(data: dict, name: str, required: bool = True, default=None, allow_negative: bool = False):
    if name not in data or data[name] is None:
        if required:
            raise AppError("ERR_VALIDATION", 400, f"missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool) or not isinstance(v, int):
        raise AppError("ERR_VALIDATION", 400, f"{name} must be an integer")
    if not allow_negative and v < 0:
        raise AppError("ERR_VALIDATION", 400, f"{name} must be non-negative")
    return v


def parse_bool(data: dict, name: str, default=None, required: bool = False):
    if name not in data or data[name] is None:
        if required:
            raise AppError("ERR_VALIDATION", 400, f"missing required field: {name}")
        return default
    v = data[name]
    if not isinstance(v, bool):
        raise AppError("ERR_VALIDATION", 400, f"{name} must be boolean")
    return v


def parse_number(data: dict, name: str, required: bool = True, default=None):
    if name not in data or data[name] is None:
        if required:
            raise AppError("ERR_VALIDATION", 400, f"missing required field: {name}")
        return default
    v = data[name]
    if isinstance(v, bool):
        raise AppError("ERR_VALIDATION", 400, f"{name} must be numeric")
    if not isinstance(v, (int, float)):
        raise AppError("ERR_VALIDATION", 400, f"{name} must be numeric")
    return v


# =============================================================================
# Existence checks (with left-to-right ordering)
# =============================================================================

def _get_or_404(collection: dict, key: str, err_id: str) -> dict:
    obj = collection.get(key)
    if obj is None:
        raise AppError(err_id, 404)
    return obj


def get_client_404(cid) -> dict:
    if not isinstance(cid, str):
        raise AppError("ERR_CLIENT_NOT_FOUND", 404)
    return _get_or_404(DB.clients, cid, "ERR_CLIENT_NOT_FOUND")


def get_site_404(sid) -> dict:
    if not isinstance(sid, str):
        raise AppError("ERR_SITE_NOT_FOUND", 404)
    return _get_or_404(DB.sites, sid, "ERR_SITE_NOT_FOUND")


def get_technician_404(tid) -> dict:
    if not isinstance(tid, str):
        raise AppError("ERR_TECHNICIAN_NOT_FOUND", 404)
    return _get_or_404(DB.technicians, tid, "ERR_TECHNICIAN_NOT_FOUND")


def get_contract_404(cid) -> dict:
    if not isinstance(cid, str):
        raise AppError("ERR_CONTRACT_NOT_FOUND", 404)
    return _get_or_404(DB.contracts, cid, "ERR_CONTRACT_NOT_FOUND")


def get_asset_404(aid) -> dict:
    if not isinstance(aid, str):
        raise AppError("ERR_ASSET_NOT_FOUND", 404)
    return _get_or_404(DB.assets, aid, "ERR_ASSET_NOT_FOUND")


def get_patch_job_404(pid) -> dict:
    if not isinstance(pid, str):
        raise AppError("ERR_PATCH_JOB_NOT_FOUND", 404)
    return _get_or_404(DB.patch_jobs, pid, "ERR_PATCH_JOB_NOT_FOUND")


def get_ticket_404(tid) -> dict:
    if not isinstance(tid, str):
        raise AppError("ERR_TICKET_NOT_FOUND", 404)
    return _get_or_404(DB.tickets, tid, "ERR_TICKET_NOT_FOUND")


def get_dispatch_404(did) -> dict:
    if not isinstance(did, str):
        raise AppError("ERR_DISPATCH_NOT_FOUND", 404)
    return _get_or_404(DB.dispatches, did, "ERR_DISPATCH_NOT_FOUND")


def get_quote_404(qid) -> dict:
    if not isinstance(qid, str):
        raise AppError("ERR_QUOTE_NOT_FOUND", 404)
    return _get_or_404(DB.quotes, qid, "ERR_QUOTE_NOT_FOUND")


def get_procurement_order_404(oid) -> dict:
    if not isinstance(oid, str):
        raise AppError("ERR_PROCUREMENT_ORDER_NOT_FOUND", 404)
    return _get_or_404(DB.procurement_orders, oid, "ERR_PROCUREMENT_ORDER_NOT_FOUND")


# =============================================================================
# Pagination + listing
# =============================================================================

def parse_pagination() -> tuple[int, int]:
    limit_s = request.args.get("limit")
    offset_s = request.args.get("offset")
    limit = 10
    offset = 0
    if limit_s is not None:
        try:
            limit = int(limit_s)
        except (TypeError, ValueError):
            raise AppError("ERR_VALIDATION", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise AppError("ERR_VALIDATION", 400, "limit out of range")
    if offset_s is not None:
        try:
            offset = int(offset_s)
        except (TypeError, ValueError):
            raise AppError("ERR_VALIDATION", 400, "offset must be an integer")
        if offset < 0:
            raise AppError("ERR_VALIDATION", 400, "offset must be >= 0")
    return limit, offset


def paginate(items: list) -> tuple[list, dict]:
    limit, offset = parse_pagination()
    # sort by created_at asc (stable), fallback: keep insertion order
    items_sorted = sorted(items, key=lambda x: (x.get("created_at") or "", x.get("id") or ""))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total,
    }


# =============================================================================
# ClientContact ownership scoping
# =============================================================================

def contact_owns_client(role: str, user_id: str, client_id: str) -> None:
    if role == "ClientContact" and client_id != user_id:
        raise AppError("ERR_NOT_RESOURCE_OWNER", 403)


def technician_owns_dispatch(role: str, user_id: str, dispatch: dict) -> None:
    if role == "Technician" and dispatch.get("technician_id") != user_id:
        raise AppError("ERR_NOT_RESOURCE_OWNER", 403)


# =============================================================================
# App
# =============================================================================

app = Flask(__name__)


@app.before_request
def _init_request():
    g.api_request_id = new_request_id()


@app.errorhandler(AppError)
def _handle_app_error(e: AppError):
    return err(e.error_id, e.http_status, e.message)


@app.errorhandler(404)
def _handle_404(_e):
    return err("ERR_NOT_FOUND", 404, "route not found")


@app.errorhandler(405)
def _handle_405(_e):
    return err("ERR_METHOD_NOT_ALLOWED", 405, "method not allowed")


@app.errorhandler(Exception)
def _handle_exc(e):
    if isinstance(e, AppError):
        return _handle_app_error(e)
    # Surface programming errors as 500 with envelope
    return err("ERR_INTERNAL", 500, str(e))


# =============================================================================
# Entity computed views
# =============================================================================

def client_view(c: dict) -> dict:
    placed_total = sum(
        o["total_cents"] for o in DB.procurement_orders.values()
        if o["client_id"] == c["id"] and o["status"] == "PLACED"
    )
    return {
        "id": c["id"],
        "company_name": c["company_name"],
        "primary_contact_email": c["primary_contact_email"],
        "credit_limit_cents": c["credit_limit_cents"],
        "credit_available_cents": c["credit_limit_cents"] - placed_total,
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def site_view(s: dict) -> dict:
    return {
        "id": s["id"],
        "client_id": s["client_id"],
        "label": s["label"],
        "address": s["address"],
        "created_at": s["created_at"],
        "updated_at": s["updated_at"],
        "version": s["version"],
    }


def technician_view(t: dict) -> dict:
    return {
        "id": t["id"],
        "full_name": t["full_name"],
        "skill_level": t["skill_level"],
        "hourly_rate_cents": t["hourly_rate_cents"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def _contract_seats_available(c: dict) -> int:
    active = sum(
        1 for a in DB.assets.values()
        if a["contract_id"] == c["id"] and a["monitoring_status"] == "ACTIVE"
    )
    return c["seat_count"] - active


def contract_view(c: dict) -> dict:
    return {
        "id": c["id"],
        "client_id": c["client_id"],
        "service_tier": c["service_tier"],
        "seat_count": c["seat_count"],
        "per_seat_rate_cents": c["per_seat_rate_cents"],
        "backup_addon": c["backup_addon"],
        "security_addon": c["security_addon"],
        "seats_available": _contract_seats_available(c),
        "period_start": _format_iso(c["period_start"]) if c.get("period_start") else None,
        "period_end": _format_iso(c["period_end"]) if c.get("period_end") else None,
        "period_ticket_minutes": c["period_ticket_minutes"],
        "status": c["status"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


def _asset_patch_compliance(a: dict) -> float:
    succeeded = sum(
        1 for p in DB.patch_jobs.values()
        if p["asset_id"] == a["id"] and p["status"] == "SUCCEEDED"
    )
    failed = sum(
        1 for p in DB.patch_jobs.values()
        if p["asset_id"] == a["id"] and p["status"] == "FAILED"
    )
    if succeeded + failed == 0:
        return 100.00
    return round_half_up_2dp(100 * succeeded / (succeeded + failed))


def asset_view(a: dict) -> dict:
    return {
        "id": a["id"],
        "client_id": a["client_id"],
        "site_id": a["site_id"],
        "contract_id": a["contract_id"],
        "asset_type": a["asset_type"],
        "hostname": a["hostname"],
        "monitoring_status": a["monitoring_status"],
        "patch_compliance_pct": _asset_patch_compliance(a),
        "created_at": a["created_at"],
        "updated_at": a["updated_at"],
        "version": a["version"],
    }


def patch_job_view(p: dict) -> dict:
    return {
        "id": p["id"],
        "asset_id": p["asset_id"],
        "window_start": _format_iso(p["window_start"]),
        "window_end": _format_iso(p["window_end"]),
        "patch_count": p["patch_count"],
        "status": p["status"],
        "created_at": p["created_at"],
        "updated_at": p["updated_at"],
        "version": p["version"],
    }


# --- SLA tables ---

SLA_RESPONSE_MINUTES = {
    "GOLD": {"P1": 15, "P2": 30, "P3": 60, "P4": 120},
    "SILVER": {"P1": 30, "P2": 60, "P3": 120, "P4": 240},
    "BRONZE": {"P1": 60, "P2": 120, "P3": 240, "P4": 480},
}
SLA_RESOLVE_MINUTES = {
    "GOLD": {"P1": 240, "P2": 480, "P3": 1440, "P4": 2880},
    "SILVER": {"P1": 480, "P2": 960, "P3": 2880, "P4": 5760},
    "BRONZE": {"P1": 960, "P2": 1920, "P3": 5760, "P4": 11520},
}
PRIORITY_ESTIMATE_MINUTES = {"P1": 240, "P2": 120, "P3": 60, "P4": 30}


def _ticket_billable_minutes(t: dict) -> int:
    completed = [d for d in DB.dispatches.values()
                 if d["ticket_id"] == t["id"] and d["status"] == "COMPLETED"]
    if not completed:
        return PRIORITY_ESTIMATE_MINUTES[t["priority"]]
    return sum(d["logged_minutes"] for d in completed)


def ticket_view(t: dict) -> dict:
    contract = DB.contracts.get(t["contract_id"])
    tier = contract["service_tier"] if contract else "BRONZE"
    priority = t["priority"]
    created_dt = _parse_iso(t["created_at"])
    resp_target = SLA_RESPONSE_MINUTES[tier][priority]
    resolve_target = SLA_RESOLVE_MINUTES[tier][priority]
    sla_response_due_at = created_dt + timedelta(minutes=resp_target)
    sla_resolve_due_at = created_dt + timedelta(minutes=resolve_target)
    now = CLOCK.now
    first_resp = _parse_iso(t["first_response_at"]) if t.get("first_response_at") else None
    resolved = _parse_iso(t["resolved_at"]) if t.get("resolved_at") else None
    sla_response_breached = (
        (first_resp is None and now >= sla_response_due_at)
        or (first_resp is not None and first_resp > sla_response_due_at)
    )
    sla_resolve_breached = (
        (resolved is None and now >= sla_resolve_due_at)
        or (resolved is not None and resolved > sla_resolve_due_at)
    )
    return {
        "id": t["id"],
        "client_id": t["client_id"],
        "contract_id": t["contract_id"],
        "asset_id": t.get("asset_id"),
        "priority": t["priority"],
        "subject": t["subject"],
        "owner_technician_id": t.get("owner_technician_id"),
        "first_response_at": t.get("first_response_at"),
        "resolved_at": t.get("resolved_at"),
        "sla_response_due_at": _format_iso(sla_response_due_at),
        "sla_resolve_due_at": _format_iso(sla_resolve_due_at),
        "sla_response_breached": sla_response_breached,
        "sla_resolve_breached": sla_resolve_breached,
        "billable_minutes": _ticket_billable_minutes(t),
        "status": t["status"],
        "created_at": t["created_at"],
        "updated_at": t["updated_at"],
        "version": t["version"],
    }


def dispatch_view(d: dict) -> dict:
    return {
        "id": d["id"],
        "ticket_id": d["ticket_id"],
        "technician_id": d["technician_id"],
        "mode": d["mode"],
        "scheduled_start": _format_iso(d["scheduled_start"]),
        "scheduled_end": _format_iso(d["scheduled_end"]),
        "travel_buffer_minutes": d["travel_buffer_minutes"],
        "logged_minutes": d["logged_minutes"],
        "resolves_ticket": d["resolves_ticket"],
        "status": d["status"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
        "version": d["version"],
    }


# --- Quote / Order money math ---

def _compute_order_totals(line_items: list, tax_rate: float) -> tuple[int, int]:
    """Returns (subtotal_cents, total_cents). Rounds per line then sums."""
    subtotal = 0
    total = 0
    tax_multiplier = Decimal(str(1.0 + tax_rate))
    for li in line_items:
        upc = li["unit_price_cents"]
        qty = li["qty"]
        subtotal += upc * qty
        line_taxed = Decimal(str(upc)) * Decimal(str(qty)) * tax_multiplier
        total += int(line_taxed.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    return subtotal, total


def _validate_line_items(line_items) -> None:
    if not isinstance(line_items, list):
        raise AppError("ERR_VALIDATION", 400, "line_items must be an array")
    for li in line_items:
        if not isinstance(li, dict):
            raise AppError("ERR_VALIDATION", 400, "line_items entries must be objects")
        if "description" not in li or "unit_price_cents" not in li or "qty" not in li:
            raise AppError("ERR_VALIDATION", 400, "line items require description, unit_price_cents, qty")
        upc = li["unit_price_cents"]
        qty = li["qty"]
        if isinstance(upc, bool) or not isinstance(upc, int):
            raise AppError("ERR_VALIDATION", 400, "unit_price_cents must be an integer")
        if isinstance(qty, bool) or not isinstance(qty, int):
            raise AppError("ERR_VALIDATION", 400, "qty must be an integer")


def quote_view(q: dict) -> dict:
    # auto-expire SENT quotes past valid_until on read
    _maybe_expire_quote(q)
    return {
        "id": q["id"],
        "client_id": q["client_id"],
        "quote_type": q["quote_type"],
        "title": q["title"],
        "line_items": q["line_items"],
        "tax_rate": q["tax_rate"],
        "valid_until": _format_iso(q["valid_until"]),
        "subtotal_cents": q["subtotal_cents"],
        "total_cents": q["total_cents"],
        "status": q["status"],
        "created_at": q["created_at"],
        "updated_at": q["updated_at"],
        "version": q["version"],
    }


def _maybe_expire_quote(q: dict) -> None:
    if q["status"] == "SENT" and CLOCK.now >= q["valid_until"]:
        q["status"] = "EXPIRED"
        touch(q)


def procurement_order_view(o: dict) -> dict:
    return {
        "id": o["id"],
        "client_id": o["client_id"],
        "quote_id": o.get("quote_id"),
        "line_items": o["line_items"],
        "tax_rate": o["tax_rate"],
        "total_cents": o["total_cents"],
        "status": o["status"],
        "created_at": o["created_at"],
        "updated_at": o["updated_at"],
        "version": o["version"],
    }


def invoice_view(inv: dict) -> dict:
    return {
        "id": inv["id"],
        "contract_id": inv["contract_id"],
        "variant": inv["variant"],
        "period_start": _format_iso(inv["period_start"]),
        "period_end": _format_iso(inv["period_end"]),
        "seat_count_snapshot": inv["seat_count_snapshot"],
        "total_seat_days": inv["total_seat_days"],
        "base_seat_charge_cents": inv["base_seat_charge_cents"],
        "volume_discount_cents": inv["volume_discount_cents"],
        "addon_charge_cents": inv["addon_charge_cents"],
        "overage_charge_cents": inv["overage_charge_cents"],
        "total_cents": inv["total_cents"],
        "created_at": inv["created_at"],
    }


def seat_adjustment_view(sa: dict) -> dict:
    return {
        "id": sa["id"],
        "contract_id": sa["contract_id"],
        "delta": sa["delta"],
        "effective_at": _format_iso(sa["effective_at"]),
        "reason": sa.get("reason"),
        "seat_count_after": sa["seat_count_after"],
        "created_at": sa["created_at"],
    }


# =============================================================================
# Cascades
# =============================================================================

def _cascade_asset_retire(asset: dict) -> None:
    """Retire an ACTIVE asset: retire → cancel SCHEDULED patch jobs → cancel open tickets."""
    asset["monitoring_status"] = "RETIRED"
    touch(asset)
    # SCHEDULED patch jobs on this asset → CANCELLED
    for p in DB.patch_jobs.values():
        if p["asset_id"] == asset["id"] and p["status"] == "SCHEDULED":
            p["status"] = "CANCELLED"
            touch(p)
    # Tickets in NEW/IN_PROGRESS referencing this asset → CANCELLED
    for t in DB.tickets.values():
        if t.get("asset_id") == asset["id"] and t["status"] in ("NEW", "IN_PROGRESS"):
            prev = t["status"]
            t["status"] = "CANCELLED"
            touch(t)
            if prev == "IN_PROGRESS":
                # cancel scheduled dispatches
                for d in DB.dispatches.values():
                    if d["ticket_id"] == t["id"] and d["status"] == "SCHEDULED":
                        d["status"] = "CANCELLED"
                        touch(d)


def _cascade_contract_terminate(contract: dict) -> None:
    contract["status"] = "TERMINATED"
    touch(contract)
    # Retire covered ACTIVE assets
    for a in list(DB.assets.values()):
        if a["contract_id"] == contract["id"] and a["monitoring_status"] == "ACTIVE":
            _cascade_asset_retire(a)


# =============================================================================
# Routes: clock
# =============================================================================

@app.post("/_clock/set_current_utc")
def clock_set():
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    data = get_json()
    to_iso = require_field(data, "to_iso8601", str)
    try:
        CLOCK.set(to_iso)
    except Exception:
        raise AppError("ERR_VALIDATION", 400, "invalid to_iso8601")
    return ok({"now": _format_iso(CLOCK.now)})


# =============================================================================
# Routes: Clients
# =============================================================================

@app.post("/clients")
def create_client():
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    data = get_json()
    company_name = require_field(data, "company_name", str)
    primary_contact_email = require_field(data, "primary_contact_email", str)
    credit_limit_cents = parse_int(data, "credit_limit_cents", required=False, default=0)
    cid = new_id()
    obj = {
        "id": cid,
        "company_name": company_name,
        "primary_contact_email": primary_contact_email,
        "credit_limit_cents": credit_limit_cents,
        "status": "ACTIVE",
    }
    stamp_common(obj)
    DB.clients[cid] = obj
    return ok(client_view(obj), 201)


@app.get("/clients/<cid>")
def get_client(cid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    c = get_client_404(cid)
    contact_owns_client(role, user_id, c["id"])
    return ok(client_view(c))


@app.post("/clients/<cid>/offboard")
def offboard_client(cid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    c = get_client_404(cid)
    if c["status"] != "ACTIVE":
        raise AppError("ERR_INVALID_STATE", 409)
    c["status"] = "OFFBOARDED"
    touch(c)
    # Cascade: every ACTIVE contract of this client → TERMINATED
    for k in list(DB.contracts.keys()):
        con = DB.contracts[k]
        if con["client_id"] == c["id"] and con["status"] == "ACTIVE":
            _cascade_contract_terminate(con)
    return ok(client_view(c))


# =============================================================================
# Routes: Sites
# =============================================================================

@app.post("/sites")
def create_site():
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    label = require_field(data, "label", str)
    address = require_field(data, "address", str)
    get_client_404(client_id)
    sid = new_id()
    obj = {"id": sid, "client_id": client_id, "label": label, "address": address}
    stamp_common(obj)
    DB.sites[sid] = obj
    return ok(site_view(obj), 201)


@app.get("/sites/<sid>")
def get_site(sid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    s = get_site_404(sid)
    contact_owns_client(role, user_id, s["client_id"])
    return ok(site_view(s))


@app.get("/sites")
def list_sites():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    items = list(DB.sites.values())
    if client_id:
        items = [s for s in items if s["client_id"] == client_id]
    if role == "ClientContact":
        items = [s for s in items if s["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([site_view(x) for x in page], 200, pag)


# =============================================================================
# Routes: Technicians
# =============================================================================

@app.post("/technicians")
def create_technician():
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    data = get_json()
    full_name = require_field(data, "full_name", str)
    skill_level = optional_enum(data, "skill_level", {"JUNIOR", "SENIOR"}, default="JUNIOR")
    hourly_rate_cents = parse_int(data, "hourly_rate_cents", required=True)
    tid = new_id()
    obj = {
        "id": tid,
        "full_name": full_name,
        "skill_level": skill_level,
        "hourly_rate_cents": hourly_rate_cents,
    }
    stamp_common(obj)
    DB.technicians[tid] = obj
    return ok(technician_view(obj), 201)


# =============================================================================
# Routes: Contracts
# =============================================================================

@app.post("/contracts")
def create_contract():
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    service_tier = require_enum(data, "service_tier", {"BRONZE", "SILVER", "GOLD"})
    seat_count = parse_int(data, "seat_count", required=True)
    per_seat_rate_cents = parse_int(data, "per_seat_rate_cents", required=True)
    backup_addon = parse_bool(data, "backup_addon", default=False)
    security_addon = parse_bool(data, "security_addon", default=False)
    get_client_404(client_id)
    cid = new_id()
    obj = {
        "id": cid,
        "client_id": client_id,
        "service_tier": service_tier,
        "seat_count": seat_count,
        "per_seat_rate_cents": per_seat_rate_cents,
        "backup_addon": backup_addon,
        "security_addon": security_addon,
        "period_start": None,
        "period_end": None,
        "period_ticket_minutes": 0,
        "status": "DRAFT",
    }
    stamp_common(obj)
    DB.contracts[cid] = obj
    return ok(contract_view(obj), 201)


@app.get("/contracts/<cid>")
def get_contract(cid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    c = get_contract_404(cid)
    contact_owns_client(role, user_id, c["client_id"])
    return ok(contract_view(c))


@app.get("/contracts")
def list_contracts():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    items = list(DB.contracts.values())
    if client_id:
        items = [c for c in items if c["client_id"] == client_id]
    if status:
        items = [c for c in items if c["status"] == status]
    if role == "ClientContact":
        items = [c for c in items if c["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([contract_view(x) for x in page], 200, pag)


@app.post("/contracts/<cid>/activate")
def activate_contract(cid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    c = get_contract_404(cid)
    if c["status"] != "DRAFT":
        raise AppError("ERR_INVALID_STATE", 409)
    client = DB.clients.get(c["client_id"])
    if not client or client["status"] != "ACTIVE":
        raise AppError("ERR_CONTRACT_NOT_ACTIVE", 409)
    if c["seat_count"] <= 0:
        raise AppError("ERR_VALIDATION", 400, "seat_count must be > 0")
    c["status"] = "ACTIVE"
    c["period_start"] = CLOCK.now
    c["period_end"] = CLOCK.now + timedelta(days=30)
    c["period_ticket_minutes"] = 0
    touch(c)
    return ok(contract_view(c))


@app.post("/contracts/<cid>/terminate")
def terminate_contract(cid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    c = get_contract_404(cid)
    if c["status"] != "ACTIVE":
        raise AppError("ERR_INVALID_STATE", 409)
    _cascade_contract_terminate(c)
    return ok(contract_view(c))


@app.post("/contracts/<cid>/seat-adjustments")
def create_seat_adjustment(cid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    c = get_contract_404(cid)
    data = get_json()
    # Field validation (ERR_VALIDATION for missing type/format issues)
    delta = parse_int(data, "delta", required=True, allow_negative=True)
    effective_at = parse_iso_field(data, "effective_at", required=True)
    if "expected_contract_version" not in data or data["expected_contract_version"] is None:
        raise AppError("ERR_VALIDATION", 400, "missing required field: expected_contract_version")
    expected_version = data["expected_contract_version"]
    if isinstance(expected_version, bool) or not isinstance(expected_version, int):
        raise AppError("ERR_VALIDATION", 400, "expected_contract_version must be integer")
    reason = data.get("reason")

    # Priority 8: business_constraint
    if delta == 0:
        raise AppError("ERR_INVALID_SEAT_DELTA", 422)
    active_asset_count = sum(
        1 for a in DB.assets.values()
        if a["contract_id"] == c["id"] and a["monitoring_status"] == "ACTIVE"
    )
    new_seat_count = c["seat_count"] + delta
    if new_seat_count < active_asset_count:
        raise AppError("ERR_SEAT_FLOOR_VIOLATION", 422)

    # Priority 10: OCC
    if expected_version != c["version"]:
        raise AppError("ERR_STALE_CONTRACT_VERSION", 412)

    # Apply
    c["seat_count"] = new_seat_count
    touch(c)
    sa_id = new_id()
    sa = {
        "id": sa_id,
        "contract_id": c["id"],
        "delta": delta,
        "effective_at": effective_at,
        "reason": reason,
        "seat_count_after": new_seat_count,
        "created_at": _format_iso(CLOCK.now),
    }
    DB.seat_adjustments[sa_id] = sa
    return ok(seat_adjustment_view(sa), 201)


@app.get("/contracts/<cid>/seat-adjustments")
def list_seat_adjustments(cid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    c = get_contract_404(cid)
    contact_owns_client(role, user_id, c["client_id"])
    items = [sa for sa in DB.seat_adjustments.values() if sa["contract_id"] == cid]
    page, pag = paginate(items)
    return ok([seat_adjustment_view(x) for x in page], 200, pag)


@app.post("/contracts/<cid>/invoices")
def create_invoice(cid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager"})
    c = get_contract_404(cid)
    data = get_json()
    variant = require_enum(data, "variant", {"PROVISIONAL", "FINAL"})
    if c.get("period_start") is None or c.get("period_end") is None:
        raise AppError("ERR_INVALID_STATE", 409, "contract has no active billing period")
    period_start = c["period_start"]
    period_end = c["period_end"]
    per_seat_rate = c["per_seat_rate_cents"]

    if variant == "PROVISIONAL":
        seat_count_snapshot = c["seat_count"]
        total_seat_days = 0
        base_seat_charge_cents = seat_count_snapshot * per_seat_rate
    else:
        # FINAL: walk seat timeline
        # Adjustments in-period: effective_at in [period_start, period_end)
        in_period = [sa for sa in DB.seat_adjustments.values()
                     if sa["contract_id"] == c["id"]
                     and period_start <= sa["effective_at"] < period_end]
        # Starting level = current seat_count - sum(delta for adj with effective_at >= period_start)
        after_start = [sa for sa in DB.seat_adjustments.values()
                       if sa["contract_id"] == c["id"] and sa["effective_at"] >= period_start]
        start_level = c["seat_count"] - sum(sa["delta"] for sa in after_start)
        # sort in_period by effective_at asc, created_at asc
        in_period.sort(key=lambda x: (x["effective_at"], x["created_at"]))

        total_seat_days = 0
        current_level = start_level
        prev_time = period_start
        for sa in in_period:
            t = sa["effective_at"]
            if t > prev_time:
                days = int((t - prev_time).total_seconds() // 86400)
                total_seat_days += current_level * days
            current_level = current_level + sa["delta"]
            prev_time = t
        # tail sub-interval up to period_end
        if period_end > prev_time:
            days = int((period_end - prev_time).total_seconds() // 86400)
            total_seat_days += current_level * days

        seat_count_snapshot = current_level  # level in force at period_end
        base_seat_charge_cents = round_half_up_int(
            Decimal(str(per_seat_rate)) * Decimal(str(total_seat_days)) / Decimal("30")
        )

    # Discount rate by inclusive lower bound
    if seat_count_snapshot >= 50:
        discount_rate = Decimal("0.15")
    elif seat_count_snapshot >= 25:
        discount_rate = Decimal("0.10")
    elif seat_count_snapshot >= 10:
        discount_rate = Decimal("0.05")
    else:
        discount_rate = Decimal("0.00")

    volume_discount_cents = round_half_up_int(Decimal(str(base_seat_charge_cents)) * discount_rate)

    addon_per_seat = 0
    if c["backup_addon"]:
        addon_per_seat += 800
    if c["security_addon"]:
        addon_per_seat += 1500
    addon_charge_cents = addon_per_seat * seat_count_snapshot

    included_map = {"BRONZE": 600, "SILVER": 1200, "GOLD": 3000}
    included = included_map[c["service_tier"]]
    overage_minutes = max(0, c["period_ticket_minutes"] - included)
    overage_charge_cents = overage_minutes * 250

    total_cents = (
        base_seat_charge_cents - volume_discount_cents + addon_charge_cents + overage_charge_cents
    )

    inv_id = new_id()
    inv = {
        "id": inv_id,
        "contract_id": c["id"],
        "variant": variant,
        "period_start": period_start,
        "period_end": period_end,
        "seat_count_snapshot": seat_count_snapshot,
        "total_seat_days": total_seat_days,
        "base_seat_charge_cents": base_seat_charge_cents,
        "volume_discount_cents": volume_discount_cents,
        "addon_charge_cents": addon_charge_cents,
        "overage_charge_cents": overage_charge_cents,
        "total_cents": total_cents,
        "created_at": _format_iso(CLOCK.now),
    }
    DB.invoices[inv_id] = inv
    return ok(invoice_view(inv), 201)


@app.get("/contracts/<cid>/invoices")
def list_invoices(cid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    c = get_contract_404(cid)
    contact_owns_client(role, user_id, c["client_id"])
    items = [inv for inv in DB.invoices.values() if inv["contract_id"] == cid]
    page, pag = paginate(items)
    return ok([invoice_view(x) for x in page], 200, pag)


# =============================================================================
# Routes: Assets
# =============================================================================

@app.post("/assets")
def create_asset():
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    site_id = require_field(data, "site_id", str)
    asset_type = require_enum(data, "asset_type", {"LAPTOP", "DESKTOP", "PHONE", "SERVER"})
    hostname = require_field(data, "hostname", str)
    # Existence left-to-right: client, then site
    get_client_404(client_id)
    site = get_site_404(site_id)
    aid = new_id()
    obj = {
        "id": aid,
        "client_id": client_id,
        "site_id": site_id,
        "contract_id": None,
        "asset_type": asset_type,
        "hostname": hostname,
        "monitoring_status": "UNMONITORED",
    }
    stamp_common(obj)
    DB.assets[aid] = obj
    return ok(asset_view(obj), 201)


@app.get("/assets/<aid>")
def get_asset(aid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    a = get_asset_404(aid)
    contact_owns_client(role, user_id, a["client_id"])
    return ok(asset_view(a))


@app.get("/assets")
def list_assets():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    site_id = request.args.get("site_id")
    contract_id = request.args.get("contract_id")
    monitoring_status = request.args.get("monitoring_status")
    items = list(DB.assets.values())
    if client_id:
        items = [a for a in items if a["client_id"] == client_id]
    if site_id:
        items = [a for a in items if a["site_id"] == site_id]
    if contract_id:
        items = [a for a in items if a["contract_id"] == contract_id]
    if monitoring_status:
        items = [a for a in items if a["monitoring_status"] == monitoring_status]
    if role == "ClientContact":
        items = [a for a in items if a["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([asset_view(x) for x in page], 200, pag)


@app.post("/assets/<aid>/assign-contract")
def assign_asset_contract(aid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    a = get_asset_404(aid)
    data = get_json()
    contract_id = require_field(data, "contract_id", str)
    c = get_contract_404(contract_id)
    # priority 5 state
    if a["monitoring_status"] != "UNMONITORED":
        raise AppError("ERR_INVALID_STATE", 409)
    # priority 6 cross-entity
    if c["status"] != "ACTIVE":
        raise AppError("ERR_CONTRACT_NOT_ACTIVE", 409)
    # priority 8 constraint
    if _contract_seats_available(c) <= 0:
        raise AppError("ERR_NO_SEATS_AVAILABLE", 422)
    a["monitoring_status"] = "ACTIVE"
    a["contract_id"] = c["id"]
    touch(a)
    return ok(asset_view(a))


@app.post("/assets/<aid>/unassign-contract")
def unassign_asset_contract(aid):
    _, role = require_auth()
    require_roles(role, {"ServiceManager", "AccountManager"})
    a = get_asset_404(aid)
    if a["monitoring_status"] != "ACTIVE":
        raise AppError("ERR_INVALID_STATE", 409)
    a["monitoring_status"] = "UNMONITORED"
    a["contract_id"] = None
    touch(a)
    return ok(asset_view(a))


def _windows_overlap(a_start: datetime, a_end: datetime, b_start: datetime, b_end: datetime) -> bool:
    """Half-open [start, end) overlap check. Touching-at-endpoint does not overlap."""
    return a_start < b_end and b_start < a_end


@app.post("/assets/<aid>/patch-jobs")
def create_patch_job(aid):
    _, role = require_auth()
    require_roles(role, {"Dispatcher", "Technician"})
    a = get_asset_404(aid)
    data = get_json()
    window_start = parse_iso_field(data, "window_start", required=True)
    window_end = parse_iso_field(data, "window_end", required=True)
    patch_count = parse_int(data, "patch_count", required=False, default=0)
    # PRD §3.4 order: window shape first, then asset monitored, then overlap
    if window_end <= window_start:
        raise AppError("ERR_INVALID_TIME_WINDOW", 400)
    if a["monitoring_status"] != "ACTIVE":
        raise AppError("ERR_ASSET_NOT_MONITORED", 409)
    for p in DB.patch_jobs.values():
        if p["asset_id"] == a["id"] and p["status"] in ("SCHEDULED", "RUNNING"):
            if _windows_overlap(window_start, window_end, p["window_start"], p["window_end"]):
                raise AppError("ERR_PATCH_WINDOW_CONFLICT", 409)
    pid = new_id()
    obj = {
        "id": pid,
        "asset_id": a["id"],
        "window_start": window_start,
        "window_end": window_end,
        "patch_count": patch_count,
        "status": "SCHEDULED",
    }
    stamp_common(obj)
    DB.patch_jobs[pid] = obj
    return ok(patch_job_view(obj), 201)


@app.get("/assets/<aid>/patch-jobs")
def list_patch_jobs(aid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    a = get_asset_404(aid)
    contact_owns_client(role, user_id, a["client_id"])
    status = request.args.get("status")
    items = [p for p in DB.patch_jobs.values() if p["asset_id"] == a["id"]]
    if status:
        items = [p for p in items if p["status"] == status]
    page, pag = paginate(items)
    return ok([patch_job_view(x) for x in page], 200, pag)


# =============================================================================
# Routes: PatchJobs
# =============================================================================

@app.post("/patch-jobs/<pid>/start")
def start_patch_job(pid):
    _, role = require_auth()
    require_roles(role, {"Technician"})
    p = get_patch_job_404(pid)
    if p["status"] != "SCHEDULED":
        raise AppError("ERR_INVALID_STATE", 409)
    a = DB.assets.get(p["asset_id"])
    if not a or a["monitoring_status"] != "ACTIVE":
        raise AppError("ERR_ASSET_NOT_MONITORED", 409)
    p["status"] = "RUNNING"
    touch(p)
    return ok(patch_job_view(p))


@app.post("/patch-jobs/<pid>/report")
def report_patch_job(pid):
    _, role = require_auth()
    require_roles(role, {"Technician"})
    p = get_patch_job_404(pid)
    data = get_json()
    outcome = require_enum(data, "outcome", {"SUCCEEDED", "FAILED"})
    if "patch_count" in data and data["patch_count"] is not None:
        pc = data["patch_count"]
        if isinstance(pc, bool) or not isinstance(pc, int) or pc < 0:
            raise AppError("ERR_VALIDATION", 400, "patch_count must be non-negative int")
        p["patch_count"] = pc
    if p["status"] != "RUNNING":
        raise AppError("ERR_INVALID_STATE", 409)
    p["status"] = outcome
    touch(p)
    return ok(patch_job_view(p))


# =============================================================================
# Routes: Tickets
# =============================================================================

@app.post("/tickets")
def create_ticket():
    user_id, role = require_auth()
    require_roles(role, {"ServiceManager", "Dispatcher", "ClientContact"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    contract_id = require_field(data, "contract_id", str)
    priority = require_enum(data, "priority", {"P1", "P2", "P3", "P4"})
    subject = require_field(data, "subject", str)
    asset_id = data.get("asset_id")
    # Existence left-to-right
    client = get_client_404(client_id)
    contract = get_contract_404(contract_id)
    if asset_id is not None:
        get_asset_404(asset_id)
    # Ownership: ClientContact only within own client
    contact_owns_client(role, user_id, client_id)
    # Cross-entity: contract must be ACTIVE
    if contract["status"] != "ACTIVE":
        raise AppError("ERR_CONTRACT_NOT_ACTIVE", 409)
    tid = new_id()
    obj = {
        "id": tid,
        "client_id": client_id,
        "contract_id": contract_id,
        "asset_id": asset_id,
        "priority": priority,
        "subject": subject,
        "owner_technician_id": None,
        "first_response_at": None,
        "resolved_at": None,
        "status": "NEW",
        "_accrued_minutes": 0,
    }
    stamp_common(obj)
    DB.tickets[tid] = obj
    return ok(ticket_view(obj), 201)


@app.get("/tickets/<tid>")
def get_ticket(tid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    t = get_ticket_404(tid)
    contact_owns_client(role, user_id, t["client_id"])
    return ok(ticket_view(t))


@app.get("/tickets")
def list_tickets():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    asset_id = request.args.get("asset_id")
    contract_id = request.args.get("contract_id")
    status = request.args.get("status")
    items = list(DB.tickets.values())
    if client_id:
        items = [t for t in items if t["client_id"] == client_id]
    if asset_id:
        items = [t for t in items if t.get("asset_id") == asset_id]
    if contract_id:
        items = [t for t in items if t["contract_id"] == contract_id]
    if status:
        items = [t for t in items if t["status"] == status]
    if role == "ClientContact":
        items = [t for t in items if t["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([ticket_view(x) for x in page], 200, pag)


@app.post("/tickets/<tid>/assign")
def assign_ticket(tid):
    _, role = require_auth()
    require_roles(role, {"Dispatcher"})
    t = get_ticket_404(tid)
    data = get_json()
    technician_id = require_field(data, "technician_id", str)
    get_technician_404(technician_id)
    if t["status"] != "NEW":
        raise AppError("ERR_INVALID_STATE", 409)
    t["owner_technician_id"] = technician_id
    t["status"] = "IN_PROGRESS"
    if t.get("first_response_at") is None:
        t["first_response_at"] = _format_iso(CLOCK.now)
    touch(t)
    return ok(ticket_view(t))


def _resolve_ticket(t: dict) -> None:
    """Move IN_PROGRESS→RESOLVED, stamp resolved_at, accrue to contract."""
    t["status"] = "RESOLVED"
    t["resolved_at"] = _format_iso(CLOCK.now)
    minutes = _ticket_billable_minutes(t)
    t["_accrued_minutes"] = minutes
    contract = DB.contracts.get(t["contract_id"])
    if contract:
        contract["period_ticket_minutes"] = contract.get("period_ticket_minutes", 0) + minutes
        touch(contract)
    touch(t)


@app.post("/tickets/<tid>/resolve")
def resolve_ticket(tid):
    _, role = require_auth()
    require_roles(role, {"Technician", "Dispatcher"})
    t = get_ticket_404(tid)
    if t["status"] != "IN_PROGRESS":
        raise AppError("ERR_INVALID_STATE", 409)
    _resolve_ticket(t)
    return ok(ticket_view(t))


@app.post("/tickets/<tid>/reopen")
def reopen_ticket(tid):
    user_id, role = require_auth()
    require_roles(role, {"Dispatcher", "ClientContact"})
    t = get_ticket_404(tid)
    contact_owns_client(role, user_id, t["client_id"])
    if t["status"] != "RESOLVED":
        raise AppError("ERR_INVALID_STATE", 409)
    t["status"] = "IN_PROGRESS"
    prev_accrued = t.get("_accrued_minutes", 0)
    t["resolved_at"] = None
    contract = DB.contracts.get(t["contract_id"])
    if contract:
        contract["period_ticket_minutes"] = contract.get("period_ticket_minutes", 0) - prev_accrued
        touch(contract)
    t["_accrued_minutes"] = 0
    touch(t)
    return ok(ticket_view(t))


@app.post("/tickets/<tid>/dispatches")
def create_dispatch(tid):
    _, role = require_auth()
    require_roles(role, {"Dispatcher"})
    t = get_ticket_404(tid)
    data = get_json()
    technician_id = require_field(data, "technician_id", str)
    mode = require_enum(data, "mode", {"REMOTE", "ONSITE"})
    scheduled_start = parse_iso_field(data, "scheduled_start", required=True)
    scheduled_end = parse_iso_field(data, "scheduled_end", required=True)
    resolves_ticket = parse_bool(data, "resolves_ticket", default=True)
    # Existence
    get_technician_404(technician_id)
    # PRD §3.6 order: window shape first, then ticket dispatchable
    if scheduled_end <= scheduled_start:
        raise AppError("ERR_INVALID_TIME_WINDOW", 400)
    if t["status"] != "IN_PROGRESS":
        raise AppError("ERR_TICKET_NOT_DISPATCHABLE", 409)
    # Priority 7: technician double-booking; buffered interval [start, end + buffer)
    buffer_new = 30 if mode == "ONSITE" else 0
    new_start = scheduled_start
    new_end = scheduled_end + timedelta(minutes=buffer_new)
    for d in DB.dispatches.values():
        if d["technician_id"] == technician_id and d["status"] != "CANCELLED":
            d_start = d["scheduled_start"]
            d_end = d["scheduled_end"] + timedelta(minutes=d["travel_buffer_minutes"])
            if _windows_overlap(new_start, new_end, d_start, d_end):
                raise AppError("ERR_TECHNICIAN_DOUBLE_BOOKED", 409)
    did = new_id()
    obj = {
        "id": did,
        "ticket_id": t["id"],
        "technician_id": technician_id,
        "mode": mode,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "travel_buffer_minutes": buffer_new,
        "logged_minutes": 0,
        "resolves_ticket": resolves_ticket,
        "status": "SCHEDULED",
    }
    stamp_common(obj)
    DB.dispatches[did] = obj
    return ok(dispatch_view(obj), 201)


# =============================================================================
# Routes: Dispatches
# =============================================================================

@app.get("/dispatches/<did>")
def get_dispatch(did):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    d = get_dispatch_404(did)
    # Scope for ClientContact: dispatch → ticket → client
    if role == "ClientContact":
        t = DB.tickets.get(d["ticket_id"])
        if not t or t["client_id"] != user_id:
            raise AppError("ERR_NOT_RESOURCE_OWNER", 403)
    return ok(dispatch_view(d))


@app.get("/dispatches")
def list_dispatches():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    ticket_id = request.args.get("ticket_id")
    technician_id = request.args.get("technician_id")
    status = request.args.get("status")
    items = list(DB.dispatches.values())
    if ticket_id:
        items = [d for d in items if d["ticket_id"] == ticket_id]
    if technician_id:
        items = [d for d in items if d["technician_id"] == technician_id]
    if status:
        items = [d for d in items if d["status"] == status]
    if role == "ClientContact":
        filtered = []
        for d in items:
            t = DB.tickets.get(d["ticket_id"])
            if t and t["client_id"] == user_id:
                filtered.append(d)
        items = filtered
    page, pag = paginate(items)
    return ok([dispatch_view(x) for x in page], 200, pag)


@app.post("/dispatches/<did>/arrive")
def arrive_dispatch(did):
    user_id, role = require_auth()
    require_roles(role, {"Technician"})
    d = get_dispatch_404(did)
    technician_owns_dispatch(role, user_id, d)
    if d["status"] != "SCHEDULED" or d["mode"] != "ONSITE":
        raise AppError("ERR_INVALID_STATE", 409)
    d["status"] = "ON_SITE"
    touch(d)
    return ok(dispatch_view(d))


@app.post("/dispatches/<did>/complete")
def complete_dispatch(did):
    user_id, role = require_auth()
    require_roles(role, {"Technician"})
    d = get_dispatch_404(did)
    technician_owns_dispatch(role, user_id, d)
    data = get_json()
    logged_minutes = parse_int(data, "logged_minutes", required=True)
    if d["mode"] == "ONSITE":
        if d["status"] != "ON_SITE":
            raise AppError("ERR_INVALID_STATE", 409)
    else:
        # REMOTE
        if d["status"] != "SCHEDULED":
            raise AppError("ERR_INVALID_STATE", 409)
    d["status"] = "COMPLETED"
    d["logged_minutes"] = logged_minutes
    touch(d)
    # Cascade: resolve ticket if flagged
    if d["resolves_ticket"]:
        t = DB.tickets.get(d["ticket_id"])
        if t and t["status"] == "IN_PROGRESS":
            _resolve_ticket(t)
    return ok(dispatch_view(d))


@app.post("/dispatches/<did>/cancel")
def cancel_dispatch(did):
    _, role = require_auth()
    require_roles(role, {"Dispatcher"})
    d = get_dispatch_404(did)
    if d["status"] != "SCHEDULED":
        raise AppError("ERR_INVALID_STATE", 409)
    d["status"] = "CANCELLED"
    touch(d)
    return ok(dispatch_view(d))


# =============================================================================
# Routes: Quotes
# =============================================================================

@app.post("/quotes")
def create_quote():
    _, role = require_auth()
    require_roles(role, {"AccountManager"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    quote_type = require_enum(data, "quote_type", {"PROJECT", "PROCUREMENT"})
    title = require_field(data, "title", str)
    line_items = data.get("line_items")
    _validate_line_items(line_items)
    valid_until = parse_iso_field(data, "valid_until", required=True)
    tax_rate = parse_number(data, "tax_rate", required=False, default=0.08)
    get_client_404(client_id)
    if not line_items:
        raise AppError("ERR_EMPTY_LINE_ITEMS", 422)
    subtotal, total = _compute_order_totals(line_items, tax_rate)
    qid = new_id()
    obj = {
        "id": qid,
        "client_id": client_id,
        "quote_type": quote_type,
        "title": title,
        "line_items": line_items,
        "tax_rate": tax_rate,
        "valid_until": valid_until,
        "subtotal_cents": subtotal,
        "total_cents": total,
        "status": "DRAFT",
    }
    stamp_common(obj)
    DB.quotes[qid] = obj
    return ok(quote_view(obj), 201)


@app.get("/quotes/<qid>")
def get_quote(qid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    q = get_quote_404(qid)
    contact_owns_client(role, user_id, q["client_id"])
    return ok(quote_view(q))


@app.get("/quotes")
def list_quotes():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    status = request.args.get("status")
    # apply auto-expiry on read
    for q in DB.quotes.values():
        _maybe_expire_quote(q)
    items = list(DB.quotes.values())
    if client_id:
        items = [q for q in items if q["client_id"] == client_id]
    if status:
        items = [q for q in items if q["status"] == status]
    if role == "ClientContact":
        items = [q for q in items if q["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([quote_view(x) for x in page], 200, pag)


@app.post("/quotes/<qid>/send")
def send_quote(qid):
    _, role = require_auth()
    require_roles(role, {"AccountManager"})
    q = get_quote_404(qid)
    if q["status"] != "DRAFT":
        raise AppError("ERR_INVALID_STATE", 409)
    if not q["line_items"]:
        raise AppError("ERR_EMPTY_LINE_ITEMS", 422)
    q["status"] = "SENT"
    touch(q)
    return ok(quote_view(q))


@app.post("/quotes/<qid>/accept")
def accept_quote(qid):
    user_id, role = require_auth()
    require_roles(role, {"ClientContact"})
    q = get_quote_404(qid)
    contact_owns_client(role, user_id, q["client_id"])
    # Auto-expire if past valid_until
    _maybe_expire_quote(q)
    if q["status"] == "EXPIRED":
        raise AppError("ERR_QUOTE_EXPIRED", 409)
    if q["status"] != "SENT":
        raise AppError("ERR_INVALID_STATE", 409)
    if CLOCK.now >= q["valid_until"]:
        q["status"] = "EXPIRED"
        touch(q)
        raise AppError("ERR_QUOTE_EXPIRED", 409)
    q["status"] = "ACCEPTED"
    touch(q)
    return ok(quote_view(q))


@app.post("/quotes/<qid>/request-revision")
def request_revision_quote(qid):
    user_id, role = require_auth()
    require_roles(role, {"ClientContact"})
    q = get_quote_404(qid)
    contact_owns_client(role, user_id, q["client_id"])
    _maybe_expire_quote(q)
    if q["status"] != "SENT":
        raise AppError("ERR_INVALID_STATE", 409)
    q["status"] = "DRAFT"
    touch(q)
    return ok(quote_view(q))


# =============================================================================
# Routes: ProcurementOrders
# =============================================================================

@app.post("/procurement-orders")
def create_procurement_order():
    _, role = require_auth()
    require_roles(role, {"AccountManager"})
    data = get_json()
    client_id = require_field(data, "client_id", str)
    line_items = data.get("line_items")
    _validate_line_items(line_items)
    quote_id = data.get("quote_id")
    tax_rate = parse_number(data, "tax_rate", required=False, default=0.08)
    # existence left-to-right: client, quote (if provided)
    get_client_404(client_id)
    if quote_id is not None:
        get_quote_404(quote_id)
    if not line_items:
        raise AppError("ERR_EMPTY_LINE_ITEMS", 422)
    _, total = _compute_order_totals(line_items, tax_rate)
    oid = new_id()
    obj = {
        "id": oid,
        "client_id": client_id,
        "quote_id": quote_id,
        "line_items": line_items,
        "tax_rate": tax_rate,
        "total_cents": total,
        "status": "DRAFT",
    }
    stamp_common(obj)
    DB.procurement_orders[oid] = obj
    return ok(procurement_order_view(obj), 201)


@app.get("/procurement-orders/<oid>")
def get_procurement_order(oid):
    user_id, role = require_auth()
    require_roles(role, ROLES)
    o = get_procurement_order_404(oid)
    contact_owns_client(role, user_id, o["client_id"])
    return ok(procurement_order_view(o))


@app.get("/procurement-orders")
def list_procurement_orders():
    user_id, role = require_auth()
    require_roles(role, ROLES)
    client_id = request.args.get("client_id")
    quote_id = request.args.get("quote_id")
    status = request.args.get("status")
    items = list(DB.procurement_orders.values())
    if client_id:
        items = [o for o in items if o["client_id"] == client_id]
    if quote_id:
        items = [o for o in items if o.get("quote_id") == quote_id]
    if status:
        items = [o for o in items if o["status"] == status]
    if role == "ClientContact":
        items = [o for o in items if o["client_id"] == user_id]
    page, pag = paginate(items)
    return ok([procurement_order_view(x) for x in page], 200, pag)


@app.post("/procurement-orders/<oid>/place")
def place_procurement_order(oid):
    _, role = require_auth()
    require_roles(role, {"AccountManager", "ServiceManager"})
    o = get_procurement_order_404(oid)
    # state
    if o["status"] != "DRAFT":
        raise AppError("ERR_INVALID_STATE", 409)
    # cross-entity: linked quote must be ACCEPTED (if any)
    if o.get("quote_id"):
        q = DB.quotes.get(o["quote_id"])
        if not q or q["status"] != "ACCEPTED":
            raise AppError("ERR_QUOTE_NOT_ACCEPTED", 409)
    # fiscal ceiling
    client = DB.clients.get(o["client_id"])
    if not client:
        raise AppError("ERR_CLIENT_NOT_FOUND", 404)
    placed_total = sum(
        po["total_cents"] for po in DB.procurement_orders.values()
        if po["client_id"] == client["id"] and po["status"] == "PLACED"
    )
    available = client["credit_limit_cents"] - placed_total
    if o["total_cents"] > available:
        raise AppError("ERR_CREDIT_LIMIT_EXCEEDED", 402)
    o["status"] = "PLACED"
    touch(o)
    return ok(procurement_order_view(o))


@app.post("/procurement-orders/<oid>/cancel")
def cancel_procurement_order(oid):
    _, role = require_auth()
    require_roles(role, {"AccountManager", "ServiceManager"})
    o = get_procurement_order_404(oid)
    if o["status"] not in ("DRAFT", "PLACED"):
        raise AppError("ERR_INVALID_STATE", 409)
    o["status"] = "CANCELLED"
    touch(o)
    return ok(procurement_order_view(o))


# =============================================================================
# Health
# =============================================================================

@app.get("/")
def _root():
    return ok({"service": "msp-managed-it", "now": _format_iso(CLOCK.now)})


# =============================================================================
# Main
# =============================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False, threaded=True)
