"""Entity plumbing: creation, mutation stamps, serialization, list queries.

Common quartet on primary resources (PRD §2.5): id, created_at, updated_at,
version (increments on EVERY mutation, including cascading side effects).
Audit resources (BolEvent, CreditHoldLog) carry id, created_at, occurred_at
and deliberately lack updated_at/version.

Internal bookkeeping fields are prefixed with "_" and never serialized.
"""
from flask import request

from clock import now_iso
from db import next_seq, new_id
from response import page_params


def get_body():
    """JSON request body as a dict; tolerates empty/non-JSON bodies."""
    body = request.get_json(silent=True)
    return body if isinstance(body, dict) else {}


def new_entity(fields):
    """Primary resource with the standard system-managed quartet."""
    ts = now_iso()
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def new_audit(fields):
    """Immutable audit record (BolEvent / CreditHoldLog)."""
    ts = now_iso()
    e = {
        "id": new_id(),
        "created_at": ts,
        "occurred_at": ts,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    """Stamp a mutation: version increments and updated_at refreshes."""
    e["version"] += 1
    e["updated_at"] = now_iso()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------

_BASE = ("id", "created_at", "updated_at", "version")


def _ser(e, fields):
    d = {k: e[k] for k in _BASE}
    for k in fields:
        d[k] = e.get(k)
    return d


def ser_terminal(t):
    return _ser(t, [
        "terminal_code", "legal_name", "state_code", "county_code",
        "city_code", "rack_status", "inventory_gallons",
        "daily_allocation_pool_gallons",
    ])


def ser_product(p):
    return _ser(p, ["product_code", "display_name", "product_family", "is_brandable"])


def ser_customer(c):
    return _ser(c, [
        "customer_code", "legal_name", "credit_limit_cents",
        "open_lifting_exposure_cents", "credit_status", "hold_reason",
    ])


def ser_schedule(s):
    return _ser(s, [
        "terminal_id", "product_id", "effective_date",
        "posted_rack_cents_per_gal", "branded_premium_cents_per_gal",
        "status", "published_at",
    ])


def ser_right(r):
    return _ser(r, [
        "customer_id", "terminal_id", "product_id", "contract_id",
        "daily_ratable_gallons", "lifted_today_gallons", "reserved_gallons",
        "allocated_gallons", "status",
    ])


def ser_contract(c):
    return _ser(c, [
        "customer_id", "start_date", "end_date", "volume_commitment_gallons",
        "lifted_to_date_gallons", "pricing_tier", "status",
    ])


def ser_agreement(a):
    return _ser(a, [
        "delivering_terminal_id", "receiving_supplier_code", "product_id",
        "monthly_exchange_cap_gallons", "delivered_this_month_gallons", "status",
    ])


def ser_notice(n):
    return _ser(n, [
        "terminal_id", "effective_date", "total_pool_gallons",
        "allocation_method", "status", "published_at",
    ])


def ser_ticket(t):
    return _ser(t, [
        "lifting_right_id", "customer_id", "terminal_id", "product_id",
        "requested_gallons", "branded", "additive_package_code",
        "unit_price_cents_per_gal", "additive_cost_cents", "tax_cents",
        "gross_cents", "bol_number", "status",
    ])


def ser_tax_rule(r):
    return _ser(r, [
        "jurisdiction_level", "jurisdiction_code", "product_family",
        "rate_cents_per_gal", "effective_start_date", "effective_end_date",
        "status",
    ])


def ser_bol_event(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "occurred_at": e["occurred_at"],
        "lifting_ticket_id": e["lifting_ticket_id"],
        "event_type": e["event_type"],
        "event_payload": e["event_payload"],
    }


def ser_credit_log(e):
    return {
        "id": e["id"],
        "created_at": e["created_at"],
        "occurred_at": e["occurred_at"],
        "customer_id": e["customer_id"],
        "event_type": e["event_type"],
        "trigger_reason": e["trigger_reason"],
        "open_exposure_cents_at_event": e["open_exposure_cents_at_event"],
    }


# ---------------------------------------------------------------------------
# List queries: exact-match filters, created_at ASC sort, limit/offset paging
# ---------------------------------------------------------------------------

def list_query(items, args, filter_fields):
    out = list(items)
    for f in filter_fields:
        v = args.get(f)
        if v is not None:
            out = [e for e in out if str(e.get(f)) == v]
    out.sort(key=lambda e: (e["created_at"], e["_seq"]))
    limit, offset = page_params(args)
    total = len(out)
    return out[offset:offset + limit], total, limit, offset
