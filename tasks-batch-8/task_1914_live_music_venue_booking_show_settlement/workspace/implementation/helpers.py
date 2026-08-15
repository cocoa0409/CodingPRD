"""Shared request helpers: auth, RBAC, body validation, lookups, pagination,
and entity serializers. All structural names come from PRD/SCAFFOLD."""

import math
import re
from datetime import datetime, timezone

from flask import g, request

import store
from errors import (ApiError, forbidden, invalid_request, not_found,
                    unauthenticated)
from envelope import ok_list

ROLES = {"VenueManager", "BookingAgent", "Promoter", "ProductionManager", "Accountant"}

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


# ---------------------------------------------------------------------------
# Auth / RBAC (PRD 2.1)
# ---------------------------------------------------------------------------
def authenticate():
    """Populate g.user_id / g.user_role or raise ERR_UNAUTHENTICATED."""
    role = request.headers.get("X-User-Role")
    uid = request.headers.get("X-User-ID")
    if not role or not isinstance(role, str) or role not in ROLES:
        raise unauthenticated()
    if not uid or not isinstance(uid, str):
        raise unauthenticated()
    g.user_role = role
    g.user_id = uid


def require_roles(*roles):
    if g.user_role not in roles:
        raise forbidden()


def caller_offer_side():
    """Map the caller's role onto the Offer.proposed_by_role enum."""
    if g.user_role == "BookingAgent":
        return "BOOKING_AGENT"
    if g.user_role == "VenueManager":
        return "VENUE_MANAGER"
    return None


# ---------------------------------------------------------------------------
# Body validation
# ---------------------------------------------------------------------------
def body():
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise invalid_request("JSON body must be an object")
    return data


def req_present(b, name):
    if name not in b or b[name] is None:
        raise invalid_request("Missing required field: %s" % name)
    return b[name]


def req_str(b, name):
    v = req_present(b, name)
    if not isinstance(v, str) or v == "":
        raise invalid_request("Field %s must be a non-empty string" % name)
    return v


def opt_str(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not isinstance(v, str):
        raise invalid_request("Field %s must be a string" % name)
    return v


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_int(b, name, minimum=None):
    v = req_present(b, name)
    if not _is_int(v):
        raise invalid_request("Field %s must be an integer" % name)
    if minimum is not None and v < minimum:
        raise invalid_request("Field %s is out of range" % name)
    return v


def opt_int(b, name):
    v = b.get(name)
    if v is None:
        return None
    if not _is_int(v):
        raise invalid_request("Field %s must be an integer" % name)
    return v


def req_num(b, name):
    v = req_present(b, name)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("Field %s must be a number" % name)
    return v


def opt_num(b, name):
    v = b.get(name)
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise invalid_request("Field %s must be a number" % name)
    return v


def opt_bool(b, name, default=None):
    v = b.get(name, default)
    if v is None:
        return None
    if not isinstance(v, bool):
        raise invalid_request("Field %s must be a boolean" % name)
    return v


def req_enum(b, name, allowed):
    v = req_str(b, name)
    if v not in allowed:
        raise invalid_request("Field %s must be one of %s" % (name, ", ".join(allowed)))
    return v


def parse_dt(value, field):
    """Parse an ISO-8601 datetime into an aware UTC datetime."""
    if not isinstance(value, str):
        raise invalid_request("Field %s must be an ISO-8601 datetime string" % field)
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        raise invalid_request("Field %s is not a valid ISO-8601 datetime" % field)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def req_dt(b, name):
    return parse_dt(req_present(b, name), name)


def parse_date(value, field):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise invalid_request("Field %s must be a YYYY-MM-DD date string" % field)
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise invalid_request("Field %s is not a valid calendar date" % field)


def req_date(b, name):
    return parse_date(req_present(b, name), name)


def req_expected_show_version(b):
    v = req_present(b, "expected_show_version")
    if not _is_int(v):
        raise invalid_request("Field expected_show_version must be an integer")
    return v


# ---------------------------------------------------------------------------
# Lookups (path existence, left-to-right; nested children must belong to show)
# ---------------------------------------------------------------------------
def lookup(table, rid, what="Resource"):
    ent = table.get(rid)
    if ent is None:
        raise not_found("%s not found" % what)
    return ent


def get_show(show_id):
    return lookup(store.shows, show_id, "Show")


def get_child(table, show, rid, what="Resource"):
    ent = table.get(rid)
    if ent is None or ent.get("show_id") != show["id"]:
        raise not_found("%s not found" % what)
    return ent


# ---------------------------------------------------------------------------
# Pagination (PRD 2.3): limit default 10, min 1, max 100; offset default 0.
# Sort: created_at ascending (insertion sequence as the stable tie-break).
# ---------------------------------------------------------------------------
def paginate(items):
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter limit must be an integer")
        limit = max(1, min(100, limit))
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter offset must be an integer")
        offset = max(0, offset)
    ordered = sorted(items, key=lambda e: (e["created_at"], e.get("_seq", 0)))
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, limit, offset, total


def list_response(items, serializer):
    page, limit, offset, total = paginate(items)
    return ok_list([serializer(e) for e in page], limit, offset, total)


def filter_eq(items, field, value):
    if value is None:
        return items
    return [e for e in items if e.get(field) == value]


# ---------------------------------------------------------------------------
# Serializers (exact scaffold field sets; private "_"-keys never leak)
# ---------------------------------------------------------------------------
def ser_artist(a):
    return {
        "id": a["id"],
        "legal_name": a["legal_name"],
        "agency": a["agency"],
        "guarantee_floor_cents": a["guarantee_floor_cents"],
        "deposit_pct": a["deposit_pct"],
        "status": a["status"],
        "total_settled_shows": sum(
            1 for s in store.shows.values()
            if s["artist_id"] == a["id"] and s["status"] == "SETTLED"),
        "created_at": store.fmt_dt(a["created_at"]),
        "updated_at": store.fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_agent(a):
    return {
        "id": a["id"],
        "display_name": a["display_name"],
        "agency_name": a["agency_name"],
        "status": a["status"],
        "created_at": store.fmt_dt(a["created_at"]),
        "updated_at": store.fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_show(s):
    return {
        "id": s["id"],
        "artist_id": s["artist_id"],
        "room": s["room"],
        "show_date": s["show_date"],
        "doors_at_utc": store.fmt_dt(s["doors_at_utc"]),
        "curfew_at_utc": store.fmt_dt(s["curfew_at_utc"]),
        "status": s["status"],
        "hold_priority": s["hold_priority"],
        "deal_id": s["deal_id"],
        "deposit_required_cents": s["deposit_required_cents"],
        "deposit_paid_cents": s["deposit_paid_cents"],
        "deposit_due_by_utc": store.fmt_dt(s["deposit_due_by_utc"]),
        "total_capacity": s["total_capacity"],
        "tickets_sold": s["tickets_sold"],
        "gross_ticket_revenue_cents": s["gross_ticket_revenue_cents"],
        "on_sale_at_utc": store.fmt_dt(s["on_sale_at_utc"]),
        "weather_or_emergency_flag": s["weather_or_emergency_flag"],
        "cancellation_reason": s["cancellation_reason"],
        "created_at": store.fmt_dt(s["created_at"]),
        "updated_at": store.fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_hold(h):
    return {
        "id": h["id"],
        "show_id": h["show_id"],
        "priority": h["priority"],
        "status": h["status"],
        "hold_expires_at_utc": store.fmt_dt(h["hold_expires_at_utc"]),
        "challenge_window_ends_at_utc": store.fmt_dt(h.get("challenge_window_ends_at_utc")),
        "booked_by_agent_id": h["booked_by_agent_id"],
        "created_at": store.fmt_dt(h["created_at"]),
        "updated_at": store.fmt_dt(h["updated_at"]),
        "version": h["version"],
    }


def ser_offer(o):
    return {
        "id": o["id"],
        "show_id": o["show_id"],
        "round_number": o["round_number"],
        "proposed_by_role": o["proposed_by_role"],
        "deal_kind": o["deal_kind"],
        "guarantee_cents": o.get("guarantee_cents"),
        "artist_split_pct": o.get("artist_split_pct"),
        "versus_threshold_cents": o.get("versus_threshold_cents"),
        "status": o["status"],
        "expense_budget_cents": o.get("expense_budget_cents"),
        "support_budget_cents": o.get("support_budget_cents"),
        "bar_split_pct": o.get("bar_split_pct"),
        "merch_split_pct": o.get("merch_split_pct"),
        "supersedes_offer_id": o.get("supersedes_offer_id"),
        "created_at": store.fmt_dt(o["created_at"]),
        "updated_at": store.fmt_dt(o["updated_at"]),
        "version": o["version"],
    }


def ser_deal(d):
    return {
        "id": d["id"],
        "show_id": d["show_id"],
        "offer_id": d["offer_id"],
        "deal_kind": d["deal_kind"],
        "guarantee_cents": d.get("guarantee_cents"),
        "artist_split_pct": d.get("artist_split_pct"),
        "versus_threshold_cents": d.get("versus_threshold_cents"),
        "expense_budget_cents": d.get("expense_budget_cents"),
        "support_budget_cents": d.get("support_budget_cents"),
        "bar_split_pct": d.get("bar_split_pct"),
        "merch_split_pct": d.get("merch_split_pct"),
        "status": d["status"],
        "created_at": store.fmt_dt(d["created_at"]),
        "updated_at": store.fmt_dt(d["updated_at"]),
        "version": d["version"],
    }


def ser_tier(t):
    return {
        "id": t["id"],
        "show_id": t["show_id"],
        "tier_name": t["tier_name"],
        "face_price_cents": t["face_price_cents"],
        "capacity": t["capacity"],
        "sold_count": t["sold_count"],
        "refund_count": t["refund_count"],
        "tier_order": t["tier_order"],
        "created_at": store.fmt_dt(t["created_at"]),
        "updated_at": store.fmt_dt(t["updated_at"]),
        "version": t["version"],
    }


def ser_sale(s):
    return {
        "id": s["id"],
        "show_id": s["show_id"],
        "tier_id": s["tier_id"],
        "quantity": s["quantity"],
        "gross_amount_cents": s["gross_amount_cents"],
        "sold_at_utc": store.fmt_dt(s["sold_at_utc"]),
        "refund_status": s["refund_status"],
        "created_at": store.fmt_dt(s["created_at"]),
    }


def ser_checklist(c):
    return {
        "id": c["id"],
        "show_id": c["show_id"],
        "hospitality_done": c["hospitality_done"],
        "tech_done": c["tech_done"],
        "backline_done": c["backline_done"],
        "production_requirements_done": c["production_requirements_done"],
        "insurance_cert_received": c["insurance_cert_received"],
        "w9_received": c["w9_received"],
        "all_complete": c["all_complete"],
        "created_at": store.fmt_dt(c["created_at"]),
        "updated_at": store.fmt_dt(c["updated_at"]),
        "version": c["version"],
    }


def ser_support(a):
    return {
        "id": a["id"],
        "show_id": a["show_id"],
        "artist_name": a["artist_name"],
        "agreed_fee_cents": a["agreed_fee_cents"],
        "buyout_fee_cents": a["buyout_fee_cents"],
        "status": a["status"],
        "paid_cents": a["paid_cents"],
        "created_at": store.fmt_dt(a["created_at"]),
        "updated_at": store.fmt_dt(a["updated_at"]),
        "version": a["version"],
    }


def ser_receipt(r):
    return {
        "id": r["id"],
        "show_id": r["show_id"],
        "category": r["category"],
        "amount_cents": r["amount_cents"],
        "receipt_reference": r["receipt_reference"],
        "submitted_by_role": r["submitted_by_role"],
        "status": r["status"],
        "rejection_reason": r.get("rejection_reason"),
        "is_recoupable": r["is_recoupable"],
        "created_at": store.fmt_dt(r["created_at"]),
        "updated_at": store.fmt_dt(r["updated_at"]),
        "version": r["version"],
    }


def ser_ancillary(a):
    return {
        "id": a["id"],
        "show_id": a["show_id"],
        "kind": a["kind"],
        "gross_cents": a["gross_cents"],
        "cost_cents": a["cost_cents"],
        "recorded_by_role": a["recorded_by_role"],
        "recorded_at_utc": store.fmt_dt(a["recorded_at_utc"]),
        "created_at": store.fmt_dt(a["created_at"]),
    }


def ser_settlement(s):
    return {
        "id": s["id"],
        "show_id": s["show_id"],
        "status": s["status"],
        "gross_ticket_revenue_cents": s["gross_ticket_revenue_cents"],
        "recoupable_expenses_cents": s["recoupable_expenses_cents"],
        "net_door_cents": s["net_door_cents"],
        "artist_door_share_cents": s["artist_door_share_cents"],
        "guarantee_paid_cents": s["guarantee_paid_cents"],
        "bonus_cents": s["bonus_cents"],
        "bar_artist_share_cents": s["bar_artist_share_cents"],
        "merch_venue_share_cents": s["merch_venue_share_cents"],
        "support_payouts_cents": s["support_payouts_cents"],
        "deposit_credit_cents": s["deposit_credit_cents"],
        "artist_total_due_cents": s["artist_total_due_cents"],
        "venue_net_cents": s["venue_net_cents"],
        "submitted_at_utc": store.fmt_dt(s.get("submitted_at_utc")),
        "approved_by_user_id": s.get("approved_by_user_id"),
        "submitted_by_user_id": s.get("submitted_by_user_id"),
        "created_at": store.fmt_dt(s["created_at"]),
        "updated_at": store.fmt_dt(s["updated_at"]),
        "version": s["version"],
    }


def ser_wire(w):
    return {
        "id": w["id"],
        "show_id": w["show_id"],
        "purpose": w["purpose"],
        "amount_cents": w["amount_cents"],
        "recipient_artist_id": w.get("recipient_artist_id"),
        "support_act_id": w.get("support_act_id"),
        "status": w["status"],
        "initiated_by_role": w["initiated_by_role"],
        "initiated_at_utc": store.fmt_dt(w["initiated_at_utc"]),
        "completed_at_utc": store.fmt_dt(w.get("completed_at_utc")),
        "failure_reason": w.get("failure_reason"),
        "settlement_id": w.get("settlement_id"),
        "created_at": store.fmt_dt(w["created_at"]),
        "updated_at": store.fmt_dt(w["updated_at"]),
        "version": w["version"],
    }


def ser_cancellation(c):
    return {
        "id": c["id"],
        "show_id": c["show_id"],
        "reason": c["reason"],
        "declared_by_role": c["declared_by_role"],
        "declared_at_utc": store.fmt_dt(c["declared_at_utc"]),
        "days_before_show": c["days_before_show"],
        "artist_penalty_pct": c["artist_penalty_pct"],
        "artist_penalty_cents": c["artist_penalty_cents"],
        "deposit_refundable_cents": c["deposit_refundable_cents"],
        "support_kill_fee_cents": c["support_kill_fee_cents"],
        "created_at": store.fmt_dt(c["created_at"]),
    }
