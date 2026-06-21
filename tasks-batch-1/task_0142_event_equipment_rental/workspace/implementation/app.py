"""Event & Party Equipment Rental API — Flask entry point.

Implements the PRD for task_0142_event_equipment_rental. In-memory storage
only; the store is reconstructed empty on every process boot (per-test-server
isolation). No seeding.
"""
import os

from flask import Flask, request
from werkzeug.exceptions import HTTPException

from db import store, new_id, utc_now_iso
from errors import (
    ApiError, raise_err,
    ERR_UNAUTHORIZED, ERR_NOT_RESOURCE_OWNER, ERR_NOT_FOUND, ERR_VALIDATION,
    ERR_INVALID_STATE, ERR_ORDER_EMPTY, ERR_COI_REQUIRED, ERR_INVENTORY_UNAVAILABLE,
    ERR_CREW_WINDOW_CONFLICT, ERR_MAX_ATTEMPTS_EXCEEDED, ERR_DELIVERY_NOT_COMPLETED,
    ERR_NOT_RETURNED, ERR_FORFEIT_EXCEEDS_HELD, ERR_NO_WEATHER_EVENT,
    ERR_VENUE_REQUIRED, ERR_INVALID_COVERAGE_WINDOW, ERR_INVALID_EVENT_WINDOW,
    ERR_STALE_VERSION, ERR_LINE_NOT_DRAFT, ERR_INACTIVE_ITEM,
)
from response import success_object, success_array, error_response
from middleware import get_auth, require_role
import calculations as calc
import serializers as ser
from timeutil import parse_dt, rental_days, windows_overlap_inclusive_days, ONE_DAY
from datetime import timedelta

app = Flask(__name__)

CATEGORIES = {"TENT", "TABLE", "CHAIR", "LINEN", "BOUNCE_HOUSE"}
DELIVERY_ZONES = {"LOCAL", "EXTENDED", "REMOTE"}
FULFILLMENTS = {"WILL_CALL", "DELIVERY"}
SEVERITIES = {"ADVISORY", "WARNING"}
LEGS = {"DROP_OFF", "PICK_UP"}
RUN_OUTCOMES = {"SUCCESS", "FAILED"}
DISPOSITIONS = {"RELEASE", "FORFEIT"}


# ---------------------------------------------------------------------------
# Request body / param helpers
# ---------------------------------------------------------------------------

def body():
    """Return the JSON body as a dict, or raise ERR_VALIDATION if malformed.

    Missing body is treated as an empty object (endpoints with no required
    fields accept an empty body)."""
    if request.data is None or request.data == b"":
        return {}
    data = request.get_json(silent=True)
    if data is None:
        raise_err(ERR_VALIDATION, "Request body is not valid JSON")
    if not isinstance(data, dict):
        raise_err(ERR_VALIDATION, "Request body must be a JSON object")
    return data


def require_str(d, key):
    v = d.get(key)
    if not isinstance(v, str) or not v.strip():
        raise_err(ERR_VALIDATION, f"Field {key!r} is required and must be a non-empty string")
    return v


def opt_str(d, key, default=""):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, str):
        raise_err(ERR_VALIDATION, f"Field {key!r} must be a string")
    return v


def require_enum(d, key, allowed):
    v = require_str(d, key)
    if v not in allowed:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be one of {sorted(allowed)}")
    return v


def require_int(d, key, minimum=None):
    if key not in d or d[key] is None:
        raise_err(ERR_VALIDATION, f"Field {key!r} is required")
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"Field {key!r} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be >= {minimum}")
    return v


def opt_int(d, key, default, minimum=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, int):
        raise_err(ERR_VALIDATION, f"Field {key!r} must be an integer")
    if minimum is not None and v < minimum:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be >= {minimum}")
    return v


def opt_number(d, key, default, lo=None, hi=None):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise_err(ERR_VALIDATION, f"Field {key!r} must be a number")
    if lo is not None and v < lo:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be >= {lo}")
    if hi is not None and v > hi:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be <= {hi}")
    return v


def opt_bool(d, key, default):
    if key not in d or d[key] is None:
        return default
    v = d[key]
    if not isinstance(v, bool):
        raise_err(ERR_VALIDATION, f"Field {key!r} must be a boolean")
    return v


def require_dt(d, key):
    raw = d.get(key)
    if not isinstance(raw, str) or not raw.strip():
        raise_err(ERR_VALIDATION, f"Field {key!r} is required and must be an ISO 8601 datetime string")
    dt = parse_dt(raw)
    if dt is None:
        raise_err(ERR_VALIDATION, f"Field {key!r} must be a valid ISO 8601 datetime")
    return raw, dt


def pagination():
    """Parse limit/offset query params per PRD §2.3."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    if limit_raw is None:
        limit = 10
    else:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise_err(ERR_VALIDATION, "limit must be between 1 and 100")
    if offset_raw is None:
        offset = 0
    else:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise_err(ERR_VALIDATION, "offset must be an integer")
        if offset < 0:
            raise_err(ERR_VALIDATION, "offset must be >= 0")
    return limit, offset


def paginate(records, limit, offset):
    """Sort by created_at ASC (insertion seq tie-break) then page (PRD §2.3)."""
    ordered = sorted(records, key=lambda r: r["_seq"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return page, total


def touch(rec):
    """Refresh updated_at and bump version on a mutation (PRD §2.4)."""
    rec["updated_at"] = utc_now_iso()
    if "version" in rec:
        rec["version"] += 1


def stamp_created(rec, with_common=True, with_version=True):
    seq = store.next_seq()
    rec["_seq"] = seq
    rec["created_at"] = utc_now_iso()
    if with_common:
        rec["updated_at"] = rec["created_at"]
        if with_version:
            rec["version"] = 1
    return rec


# ---------------------------------------------------------------------------
# Lookup helpers (existence — priority 3, left-to-right)
# ---------------------------------------------------------------------------

def get_or_404(coll, rid):
    rec = coll.get(rid)
    if rec is None:
        raise_err(ERR_NOT_FOUND, "Resource not found")
    return rec


# ---------------------------------------------------------------------------
# Domain helpers
# ---------------------------------------------------------------------------

def lines_of_order(order_id):
    return [l for l in store.order_lines.values() if l["order_id"] == order_id]


def runs_of_order(order_id):
    return [r for r in store.delivery_runs.values() if r["order_id"] == order_id]


def ledger_of_order(order_id):
    return [e for e in store.ledger_entries.values() if e["order_id"] == order_id]


def append_ledger(order_id, kind, amount_cents, reason=""):
    rec = {
        "id": new_id(),
        "order_id": order_id,
        "kind": kind,
        "amount_cents": int(amount_cents),
        "reason": reason,
    }
    stamp_created(rec, with_common=False)
    # Sort key for chronological replay: created_at then insertion seq, so
    # ties within the same millisecond keep append order WITHOUT using id.
    rec["_created_seq_key"] = (rec["created_at"], rec["_seq"])
    store.ledger_entries[rec["id"]] = rec
    return rec


def held_balance_of(order_id):
    return calc.held_balance(ledger_of_order(order_id))


def recompute_customer_credit(customer_id):
    """Recompute Customer.account_credit_cents (scaffold calc customer_account_credit).

    Sum of every RELEASE ledger entry amount across the customer's orders, plus
    weather refunds credited on the customer's orders. Floored at 0.
    """
    cust = store.customers.get(customer_id)
    if cust is None:
        return
    total = 0
    order_ids = {o["id"] for o in store.orders.values() if o["customer_id"] == customer_id}
    for e in store.ledger_entries.values():
        if e["order_id"] in order_ids and e["kind"] == "RELEASE":
            total += int(e["amount_cents"])
    for o in store.orders.values():
        if o["customer_id"] == customer_id:
            total += int(o.get("_weather_refund_credited", 0))
    cust["account_credit_cents"] = max(total, 0)


def recompute_weather_cancellable(order):
    cancellable = False
    for l in lines_of_order(order["id"]):
        item = store.catalog_items.get(l["item_id"])
        if item and item["category"] in calc.WEATHER_SENSITIVE_CATEGORIES:
            cancellable = True
            break
    order["weather_cancellable"] = cancellable


def recompute_order_totals(order):
    """Recompute the order's monetary fields from its lines (PRD §3.3).

    Mutates each line's computed fields too. Uses order.rental_days.
    """
    days = order["rental_days"]
    subtotal = 0
    cleaning_total = 0
    deposit_total = 0
    total_units = 0
    for l in lines_of_order(order["id"]):
        item = store.catalog_items[l["item_id"]]
        qty = l["quantity"]
        l["line_rental_cents"] = calc.line_rental_charge(item, days, qty)
        l["line_deposit_cents"] = calc.line_deposit_cents(item, qty)
        l["line_cleaning_cents"] = calc.line_cleaning_cents(item, qty)
        subtotal += l["line_rental_cents"]
        cleaning_total += l["line_cleaning_cents"]
        deposit_total += l["line_deposit_cents"]
        total_units += qty
    delivery_zone = None
    if order.get("venue_id"):
        v = store.venues.get(order["venue_id"])
        if v:
            delivery_zone = v["delivery_zone"]
    delivery = calc.delivery_fee_cents(order["fulfillment"], delivery_zone,
                                       total_units, subtotal)
    order["rental_subtotal_cents"] = subtotal
    order["cleaning_fee_total_cents"] = cleaning_total
    order["deposit_total_cents"] = deposit_total
    order["delivery_fee_cents"] = delivery
    order["grand_total_cents"] = subtotal + delivery + cleaning_total


def coi_status_for_window(venue_id, event_start_dt, event_end_dt):
    """Coverage status for a specific event window (scaffold calc venue_coi_status).

    covering = approved certs whose coverage_start <= event_start AND
               coverage_end >= event_end (closed interval, both ends inclusive).
    VALID if any covering; else PENDING if any SUBMITTED; else EXPIRED if any
    APPROVED (non-covering); else NONE.
    """
    certs = [c for c in store.certificates.values() if c["venue_id"] == venue_id]
    approved = [c for c in certs if c["status"] == "APPROVED"]
    covering = [c for c in approved
                if c["_coverage_start_dt"] <= event_start_dt
                and c["_coverage_end_dt"] >= event_end_dt]
    if covering:
        return "VALID"
    if any(c["status"] == "SUBMITTED" for c in certs):
        return "PENDING"
    if approved:
        return "EXPIRED"
    return "NONE"


def venue_coi_status_no_context(venue_id):
    """Venue.coi_status without an order context (scaffold calc venue_coi_status).

    Derived from the venue's latest certificate by coverage_end DESC, tie-break
    created_at ASC; reports VALID/PENDING/EXPIRED with REJECTED treated as NONE.
    """
    certs = [c for c in store.certificates.values() if c["venue_id"] == venue_id]
    if not certs:
        return "NONE"
    # latest by coverage_end DESC, tie-break created_at (insertion seq) ASC
    best = None
    for c in certs:
        if best is None:
            best = c
            continue
        if c["_coverage_end_dt"] > best["_coverage_end_dt"]:
            best = c
        elif c["_coverage_end_dt"] == best["_coverage_end_dt"] and c["_seq"] < best["_seq"]:
            best = c
    status = best["status"]
    if status == "APPROVED":
        return "VALID"
    if status == "SUBMITTED":
        return "PENDING"
    if status == "REVOKED":
        return "EXPIRED"
    # REJECTED -> NONE
    return "NONE"


# Inventory availability ----------------------------------------------------

def reserved_units_over_window(item_id, win_start_dt, win_end_dt, exclude_order_id=None):
    """Units RESERVED on lines of `item_id` whose reserved window overlaps the
    queried window (inclusive day overlap, PRD §2.7)."""
    total = 0
    for l in store.order_lines.values():
        if l["item_id"] != item_id:
            continue
        if l["status"] != "RESERVED":
            continue
        if exclude_order_id is not None and l["order_id"] == exclude_order_id:
            continue
        rs = l.get("_reserved_start_dt")
        re = l.get("_reserved_end_dt")
        if rs is None or re is None:
            continue
        if windows_overlap_inclusive_days(rs, re, win_start_dt, win_end_dt):
            total += l["quantity"]
    return total


# Crew window conflict ------------------------------------------------------

def crew_window_conflict(crew_id, win_start_dt, win_end_dt, turnaround_minutes,
                         exclude_run_id=None):
    """True if [win_start, win_end) collides with any non-CANCELLED run on the
    same crew, including the turnaround buffer (PRD §2.8 / §3.6).

    window_start inclusive, window_end exclusive; two windows conflict if they
    overlap OR sit closer together than the buffer. Equivalent gap test with a
    buffer b: conflict iff a.start < b.end + buffer AND b.start < a.end + buffer.
    """
    buf = timedelta(minutes=turnaround_minutes)
    for r in store.delivery_runs.values():
        if r["crew_id"] != crew_id:
            continue
        if r["status"] == "CANCELLED":
            continue
        if exclude_run_id is not None and r["id"] == exclude_run_id:
            continue
        os_dt = r["_window_start_dt"]
        oe_dt = r["_window_end_dt"]
        # Half-open windows separated by at least `buf` are OK. Conflict when the
        # gap between them is strictly less than the buffer (overlap is a gap < 0).
        if win_start_dt < oe_dt + buf and os_dt < win_end_dt + buf:
            return True
    return False


# Ownership (priority 4) ----------------------------------------------------

def check_order_owner(order, user_id, role):
    if role == "Customer" and order["customer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this order")


def check_venue_owner(venue, user_id, role):
    if role == "Customer" and venue["customer_id"] != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Customer does not own this venue")


# ===========================================================================
# CatalogItem
# ===========================================================================

@app.post("/catalog-items")
def create_catalog_item():
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    d = body()
    sku = require_str(d, "sku")
    name = require_str(d, "name")
    category = require_enum(d, "category", CATEGORIES)
    total_units = require_int(d, "total_units", minimum=1)
    daily_rate = require_int(d, "daily_rate_cents", minimum=0)
    discount = opt_number(d, "multi_day_discount_pct", 0, lo=0, hi=0.90)
    deposit = opt_int(d, "deposit_per_unit_cents", 0, minimum=0)
    requires_cleaning = opt_bool(d, "requires_cleaning", False)
    cleaning_fee = opt_int(d, "cleaning_fee_cents", 0, minimum=0)
    requires_coi = opt_bool(d, "requires_coi", False)
    # sku unique across catalog items
    for it in store.catalog_items.values():
        if it["sku"] == sku:
            raise_err(ERR_VALIDATION, "sku must be unique across catalog items")
    rec = {
        "id": new_id(), "sku": sku, "name": name, "category": category,
        "total_units": total_units, "daily_rate_cents": daily_rate,
        "multi_day_discount_pct": discount, "deposit_per_unit_cents": deposit,
        "requires_cleaning": requires_cleaning, "cleaning_fee_cents": cleaning_fee,
        "requires_coi": requires_coi, "status": "ACTIVE",
    }
    stamp_created(rec)
    store.catalog_items[rec["id"]] = rec
    return success_object(ser.catalog_item_view(rec), 201)


@app.get("/catalog-items")
def list_catalog_items():
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer", "DepositAdjuster"})
    limit, offset = pagination()
    category = request.args.get("category")
    recs = list(store.catalog_items.values())
    if category is not None:
        recs = [r for r in recs if r["category"] == category]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.catalog_item_view(r) for r in page], limit, offset, total)


@app.get("/catalog-items/<item_id>")
def get_catalog_item(item_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer", "DepositAdjuster"})
    rec = get_or_404(store.catalog_items, item_id)
    return success_object(ser.catalog_item_view(rec))


@app.get("/catalog-items/<item_id>/availability")
def catalog_item_availability(item_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer"})
    item = get_or_404(store.catalog_items, item_id)
    ws_raw = request.args.get("window_start")
    we_raw = request.args.get("window_end")
    if not ws_raw or not we_raw:
        raise_err(ERR_VALIDATION, "window_start and window_end are required")
    ws = parse_dt(ws_raw)
    we = parse_dt(we_raw)
    if ws is None or we is None:
        raise_err(ERR_VALIDATION, "window_start and window_end must be ISO 8601 datetimes")
    reserved = reserved_units_over_window(item_id, ws, we)
    available = item["total_units"] - reserved
    return success_object({
        "item_id": item_id,
        "window_start": ws_raw,
        "window_end": we_raw,
        "total_units": item["total_units"],
        "reserved_units": reserved,
        "available_units": available,
    })


@app.get("/catalog-items/<item_id>/reservations")
def catalog_item_reservations(item_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer", "DepositAdjuster"})
    get_or_404(store.catalog_items, item_id)
    limit, offset = pagination()
    status = request.args.get("status")
    recs = [l for l in store.order_lines.values() if l["item_id"] == item_id]
    if status is not None:
        recs = [l for l in recs if l["status"] == status]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.line_view(r) for r in page], limit, offset, total)


@app.post("/catalog-items/<item_id>/retire")
def retire_catalog_item(item_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    item = get_or_404(store.catalog_items, item_id)
    if item["status"] != "ACTIVE":
        raise_err(ERR_INVALID_STATE, "Item is not ACTIVE")
    item["status"] = "RETIRED"
    touch(item)
    return success_object(ser.catalog_item_view(item))


# ===========================================================================
# Customer
# ===========================================================================

@app.post("/customers")
def create_customer():
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer"})
    d = body()
    email = require_str(d, "email")
    full_name = require_str(d, "full_name")
    phone = require_str(d, "phone")
    for c in store.customers.values():
        if c["email"] == email:
            raise_err(ERR_VALIDATION, "email must be unique across customers")
    rec = {
        "id": new_id(), "email": email, "full_name": full_name, "phone": phone,
        "account_credit_cents": 0,
    }
    stamp_created(rec)
    store.customers[rec["id"]] = rec
    return success_object(ser.customer_view(rec), 201)


@app.get("/customers/<customer_id>")
def get_customer(customer_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer", "DepositAdjuster"})
    rec = get_or_404(store.customers, customer_id)
    return success_object(ser.customer_view(rec))


# ===========================================================================
# Venue
# ===========================================================================

@app.post("/venues")
def create_venue():
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    d = body()
    customer_id = require_str(d, "customer_id")
    name = require_str(d, "name")
    address = require_str(d, "address")
    delivery_zone = require_enum(d, "delivery_zone", DELIVERY_ZONES)
    cust = store.customers.get(customer_id)
    if cust is None:
        raise_err(ERR_NOT_FOUND, "Customer not found")
    if role == "Customer" and customer_id != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Customer can only register their own venue")
    rec = {
        "id": new_id(), "customer_id": customer_id, "name": name,
        "address": address, "delivery_zone": delivery_zone,
    }
    stamp_created(rec)
    store.venues[rec["id"]] = rec
    return success_object(ser.venue_view(rec, "NONE"), 201)


@app.get("/venues/<venue_id>")
def get_venue(venue_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    rec = get_or_404(store.venues, venue_id)
    check_venue_owner(rec, user_id, role)
    return success_object(ser.venue_view(rec, venue_coi_status_no_context(venue_id)))


@app.get("/venues")
def list_venues():
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    recs = list(store.venues.values())
    if role == "Customer":
        recs = [v for v in recs if v["customer_id"] == user_id]
    if customer_id is not None:
        recs = [v for v in recs if v["customer_id"] == customer_id]
    page, total = paginate(recs, limit, offset)
    return success_array(
        [ser.venue_view(r, venue_coi_status_no_context(r["id"])) for r in page],
        limit, offset, total)


# ===========================================================================
# InsuranceCertificate
# ===========================================================================

@app.post("/venues/<venue_id>/certificates")
def submit_certificate(venue_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    venue = get_or_404(store.venues, venue_id)
    check_venue_owner(venue, user_id, role)
    d = body()
    carrier = require_str(d, "carrier_name")
    cs_raw, cs_dt = require_dt(d, "coverage_start")
    ce_raw, ce_dt = require_dt(d, "coverage_end")
    amount = require_int(d, "coverage_amount_cents", minimum=0)
    # coverage_end >= coverage_start enforced at submission (PRD §3.2)
    if ce_dt < cs_dt:
        raise_err(ERR_INVALID_COVERAGE_WINDOW, "coverage_end must be >= coverage_start")
    rec = {
        "id": new_id(), "venue_id": venue_id, "carrier_name": carrier,
        "coverage_start": cs_raw, "coverage_end": ce_raw,
        "coverage_amount_cents": amount, "status": "SUBMITTED",
        "_coverage_start_dt": cs_dt, "_coverage_end_dt": ce_dt,
    }
    stamp_created(rec)
    store.certificates[rec["id"]] = rec
    touch(venue)  # recompute Venue.coi_status (reflected via computed read)
    return success_object(ser.certificate_view(rec), 201)


@app.get("/venues/<venue_id>/certificates")
def list_certificates(venue_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    venue = get_or_404(store.venues, venue_id)
    check_venue_owner(venue, user_id, role)
    limit, offset = pagination()
    recs = [c for c in store.certificates.values() if c["venue_id"] == venue_id]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.certificate_view(r) for r in page], limit, offset, total)


def _get_cert_under_venue(venue_id, certificate_id):
    # left-to-right existence: venue first, then certificate
    get_or_404(store.venues, venue_id)
    cert = store.certificates.get(certificate_id)
    if cert is None or cert["venue_id"] != venue_id:
        raise_err(ERR_NOT_FOUND, "Certificate not found")
    return cert


@app.post("/venues/<venue_id>/certificates/<certificate_id>/approve")
def approve_certificate(venue_id, certificate_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    cert = _get_cert_under_venue(venue_id, certificate_id)
    if cert["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Certificate is not SUBMITTED")
    if cert["_coverage_end_dt"] < cert["_coverage_start_dt"]:
        raise_err(ERR_INVALID_COVERAGE_WINDOW, "coverage_end must be >= coverage_start")
    cert["status"] = "APPROVED"
    touch(cert)
    touch(store.venues[venue_id])
    return success_object(ser.certificate_view(cert))


@app.post("/venues/<venue_id>/certificates/<certificate_id>/reject")
def reject_certificate(venue_id, certificate_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    cert = _get_cert_under_venue(venue_id, certificate_id)
    if cert["status"] != "SUBMITTED":
        raise_err(ERR_INVALID_STATE, "Certificate is not SUBMITTED")
    body()  # optional reason; not persisted on the cert per scaffold fields
    cert["status"] = "REJECTED"
    touch(cert)
    touch(store.venues[venue_id])
    return success_object(ser.certificate_view(cert))


@app.post("/venues/<venue_id>/certificates/<certificate_id>/revoke")
def revoke_certificate(venue_id, certificate_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    cert = _get_cert_under_venue(venue_id, certificate_id)
    if cert["status"] != "APPROVED":
        raise_err(ERR_INVALID_STATE, "Certificate is not APPROVED")
    body()  # optional reason
    cert["status"] = "REVOKED"
    touch(cert)
    touch(store.venues[venue_id])
    return success_object(ser.certificate_view(cert))


# ===========================================================================
# RentalOrder
# ===========================================================================

@app.post("/orders")
def create_order():
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    d = body()
    customer_id = require_str(d, "customer_id")
    fulfillment = require_enum(d, "fulfillment", FULFILLMENTS)
    es_raw, es_dt = require_dt(d, "event_start")
    ee_raw, ee_dt = require_dt(d, "event_end")
    venue_id = d.get("venue_id")
    if venue_id is not None and not isinstance(venue_id, str):
        raise_err(ERR_VALIDATION, "venue_id must be a string")
    cust = store.customers.get(customer_id)
    if cust is None:
        raise_err(ERR_NOT_FOUND, "Customer not found")
    if role == "Customer" and customer_id != user_id:
        raise_err(ERR_NOT_RESOURCE_OWNER, "Customer can only create their own order")
    # event window well-formed (priority 17)
    if ee_dt < es_dt:
        raise_err(ERR_INVALID_EVENT_WINDOW, "event_end must be >= event_start")
    # venue existence (if provided) before VENUE_REQUIRED business rule
    venue = None
    if venue_id:
        venue = store.venues.get(venue_id)
        if venue is None:
            raise_err(ERR_NOT_FOUND, "Venue not found")
    # DELIVERY requires a customer-owned venue (priority 15)
    if fulfillment == "DELIVERY":
        if venue is None or venue["customer_id"] != customer_id:
            raise_err(ERR_VENUE_REQUIRED, "DELIVERY order requires a customer-owned venue")
    rec = {
        "id": new_id(), "customer_id": customer_id, "venue_id": venue_id,
        "fulfillment": fulfillment, "event_start": es_raw, "event_end": ee_raw,
        "rental_days": rental_days(es_dt, ee_dt),
        "booking_status": "DRAFT", "settlement_status": "UNSETTLED",
        "rental_subtotal_cents": 0, "delivery_fee_cents": 0,
        "cleaning_fee_total_cents": 0, "deposit_total_cents": 0,
        "grand_total_cents": 0, "weather_cancellable": False,
        "_event_start_dt": es_dt, "_event_end_dt": ee_dt,
        "_weather_refund_credited": 0,
    }
    stamp_created(rec)
    store.orders[rec["id"]] = rec
    return success_object(ser.order_view(rec), 201)


@app.get("/orders/<order_id>")
def get_order(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent", "DepositAdjuster"})
    order = get_or_404(store.orders, order_id)
    if role == "Customer":
        check_order_owner(order, user_id, role)
    return success_object(ser.order_view(order))


@app.get("/orders")
def list_orders():
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent", "DepositAdjuster"})
    limit, offset = pagination()
    customer_id = request.args.get("customer_id")
    venue_id = request.args.get("venue_id")
    recs = list(store.orders.values())
    if role == "Customer":
        recs = [o for o in recs if o["customer_id"] == user_id]
    if customer_id is not None:
        recs = [o for o in recs if o["customer_id"] == customer_id]
    if venue_id is not None:
        recs = [o for o in recs if o.get("venue_id") == venue_id]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.order_view(r) for r in page], limit, offset, total)


@app.post("/orders/<order_id>/lines")
def add_line(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    d = body()
    item_id = require_str(d, "item_id")
    quantity = require_int(d, "quantity", minimum=1)
    item = store.catalog_items.get(item_id)
    if item is None:
        raise_err(ERR_NOT_FOUND, "Catalog item not found")
    # state: add line only on DRAFT (priority 19)
    if order["booking_status"] != "DRAFT":
        raise_err(ERR_LINE_NOT_DRAFT, "Lines can only be added to a DRAFT order")
    # retired item (priority 20)
    if item["status"] != "ACTIVE":
        raise_err(ERR_INACTIVE_ITEM, "Cannot add a line for a RETIRED item")
    rec = {
        "id": new_id(), "order_id": order_id, "item_id": item_id,
        "quantity": quantity, "line_rental_cents": 0, "line_deposit_cents": 0,
        "line_cleaning_cents": 0, "reserved_window_start": None,
        "reserved_window_end": None, "status": "PENDING",
        "_reserved_start_dt": None, "_reserved_end_dt": None,
    }
    stamp_created(rec)
    store.order_lines[rec["id"]] = rec
    recompute_weather_cancellable(order)
    touch(order)
    return success_object(ser.line_view(rec), 201)


@app.get("/orders/<order_id>/lines")
def list_lines(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent", "DepositAdjuster"})
    order = get_or_404(store.orders, order_id)
    if role == "Customer":
        check_order_owner(order, user_id, role)
    limit, offset = pagination()
    recs = lines_of_order(order_id)
    page, total = paginate(recs, limit, offset)
    return success_array([ser.line_view(r) for r in page], limit, offset, total)


@app.delete("/orders/<order_id>/lines/<line_id>")
def remove_line(order_id, line_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    line = store.order_lines.get(line_id)
    if line is None or line["order_id"] != order_id:
        raise_err(ERR_NOT_FOUND, "Line not found")
    if order["booking_status"] != "DRAFT":
        raise_err(ERR_LINE_NOT_DRAFT, "Lines can only be removed from a DRAFT order")
    del store.order_lines[line_id]
    recompute_weather_cancellable(order)
    touch(order)
    return success_object(ser.line_view(line))


@app.get("/orders/<order_id>/quote")
def order_quote(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    # Preview using the same pricing rules without persisting/mutating.
    days = order["rental_days"]
    subtotal = 0
    cleaning_total = 0
    deposit_total = 0
    total_units = 0
    for l in lines_of_order(order_id):
        item = store.catalog_items[l["item_id"]]
        qty = l["quantity"]
        subtotal += calc.line_rental_charge(item, days, qty)
        cleaning_total += calc.line_cleaning_cents(item, qty)
        deposit_total += calc.line_deposit_cents(item, qty)
        total_units += qty
    delivery_zone = None
    if order.get("venue_id"):
        v = store.venues.get(order["venue_id"])
        if v:
            delivery_zone = v["delivery_zone"]
    delivery = calc.delivery_fee_cents(order["fulfillment"], delivery_zone,
                                       total_units, subtotal)
    grand = subtotal + delivery + cleaning_total
    return success_object({
        "order_id": order_id,
        "rental_subtotal_cents": subtotal,
        "delivery_fee_cents": delivery,
        "cleaning_fee_total_cents": cleaning_total,
        "deposit_total_cents": deposit_total,
        "grand_total_cents": grand,
    })


@app.post("/orders/<order_id>/confirm")
def confirm_order(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    d = body()
    expected_version = require_int(d, "expected_order_version")
    # state (priority 5)
    if order["booking_status"] != "DRAFT":
        raise_err(ERR_INVALID_STATE, "Order is not DRAFT")
    lines = lines_of_order(order_id)
    # order empty (priority 6)
    if not lines:
        raise_err(ERR_ORDER_EMPTY, "Order has no lines")
    # DELIVERY venue re-check (priority 15) — applied again at confirm
    if order["fulfillment"] == "DELIVERY":
        v = store.venues.get(order.get("venue_id")) if order.get("venue_id") else None
        if v is None or v["customer_id"] != order["customer_id"]:
            raise_err(ERR_VENUE_REQUIRED, "DELIVERY order requires a customer-owned venue")
    # COI gate (priority 7)
    needs_coi = any(store.catalog_items[l["item_id"]].get("requires_coi") for l in lines)
    if needs_coi:
        venue_id = order.get("venue_id")
        coi = "NONE"
        if venue_id and store.venues.get(venue_id):
            coi = coi_status_for_window(venue_id, order["_event_start_dt"], order["_event_end_dt"])
        if coi != "VALID":
            raise_err(ERR_COI_REQUIRED, "A requires_coi line lacks VALID coverage over the event window")
    # Availability gate (priority 8) — atomic: check all before committing.
    es_dt = order["_event_start_dt"]
    ee_dt = order["_event_end_dt"]
    requested = {}
    for l in lines:
        requested[l["item_id"]] = requested.get(l["item_id"], 0) + l["quantity"]
    for item_id, req_qty in requested.items():
        item = store.catalog_items[item_id]
        reserved = reserved_units_over_window(item_id, es_dt, ee_dt, exclude_order_id=order_id)
        if reserved + req_qty > item["total_units"]:
            raise_err(ERR_INVENTORY_UNAVAILABLE, "Requested quantity exceeds available units")
    # OCC gate (priority 18) — last
    if expected_version != order["version"]:
        raise_err(ERR_STALE_VERSION, "expected_order_version does not match current version")
    # --- commit ---
    for l in lines:
        l["status"] = "RESERVED"
        l["reserved_window_start"] = order["event_start"]
        l["reserved_window_end"] = order["event_end"]
        l["_reserved_start_dt"] = es_dt
        l["_reserved_end_dt"] = ee_dt
        touch(l)
    order["booking_status"] = "CONFIRMED"
    recompute_order_totals(order)
    # cross-dimension cascade: hold deposit
    order["settlement_status"] = "DEPOSIT_HELD"
    append_ledger(order_id, "HOLD", order["deposit_total_cents"], reason="")
    touch(order)
    return success_object(ser.order_view(order))


@app.post("/orders/<order_id>/fulfill")
def fulfill_order(order_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    order = get_or_404(store.orders, order_id)
    if order["booking_status"] != "CONFIRMED":
        raise_err(ERR_INVALID_STATE, "Order is not CONFIRMED")
    if order["fulfillment"] == "DELIVERY":
        drop = [r for r in runs_of_order(order_id)
                if r["leg"] == "DROP_OFF" and r["status"] == "COMPLETED"]
        if not drop:
            raise_err(ERR_DELIVERY_NOT_COMPLETED, "DROP_OFF run is not COMPLETED")
    order["booking_status"] = "FULFILLED"
    touch(order)
    return success_object(ser.order_view(order))


@app.post("/orders/<order_id>/return")
def return_order(order_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    order = get_or_404(store.orders, order_id)
    if order["booking_status"] != "FULFILLED":
        raise_err(ERR_INVALID_STATE, "Order is not FULFILLED")
    if order["fulfillment"] == "DELIVERY":
        pickup = [r for r in runs_of_order(order_id)
                  if r["leg"] == "PICK_UP" and r["status"] == "COMPLETED"]
        if not pickup:
            raise_err(ERR_DELIVERY_NOT_COMPLETED, "PICK_UP run is not COMPLETED")
    for l in lines_of_order(order_id):
        if l["status"] == "RESERVED":
            l["status"] = "RELEASED"
            touch(l)
    order["booking_status"] = "RETURNED"
    touch(order)
    return success_object(ser.order_view(order))


@app.post("/orders/<order_id>/cancel")
def cancel_order(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    d = body()
    expected_version = require_int(d, "expected_order_version")
    if order["booking_status"] not in ("DRAFT", "CONFIRMED"):
        raise_err(ERR_INVALID_STATE, "Order is not DRAFT or CONFIRMED")
    if expected_version != order["version"]:
        raise_err(ERR_STALE_VERSION, "expected_order_version does not match current version")
    # cascade hop 1: release lines + cancel runs
    for l in lines_of_order(order_id):
        if l["status"] != "RELEASED":
            l["status"] = "RELEASED"
            touch(l)
    for r in runs_of_order(order_id):
        if r["status"] in ("SCHEDULED", "ATTEMPTED"):
            r["status"] = "CANCELLED"
            touch(r)
    # cascade hop 2: deposit dimension if held
    if order["settlement_status"] == "DEPOSIT_HELD":
        held = held_balance_of(order_id)
        order["settlement_status"] = "DEPOSIT_RELEASED"
        append_ledger(order_id, "RELEASE", held, reason="")
        recompute_customer_credit(order["customer_id"])
    order["booking_status"] = "CANCELLED"
    touch(order)
    return success_object(ser.order_view(order))


@app.post("/orders/<order_id>/weather-cancel")
def weather_cancel_order(order_id):
    user_id, role = get_auth()
    require_role(role, {"Customer", "RentalAgent"})
    order = get_or_404(store.orders, order_id)
    check_order_owner(order, user_id, role)
    body()
    if order["booking_status"] not in ("CONFIRMED", "FULFILLED"):
        raise_err(ERR_INVALID_STATE, "Order is not CONFIRMED or FULFILLED")
    # matching WARNING WeatherEvent (priority 14): zone matches order's venue
    # zone, effective_date within inclusive event-window days.
    zone = None
    if order.get("venue_id") and store.venues.get(order["venue_id"]):
        zone = store.venues[order["venue_id"]]["delivery_zone"]
    es_dt = order["_event_start_dt"]
    ee_dt = order["_event_end_dt"]
    matched = False
    for w in store.weather_events.values():
        if w["severity"] != "WARNING":
            continue
        if zone is not None and w["delivery_zone"] != zone:
            continue
        wd = w["_effective_date_dt"]
        if es_dt <= wd <= ee_dt:
            matched = True
            break
    if not matched:
        raise_err(ERR_NO_WEATHER_EVENT, "No matching WARNING weather event for this order")
    # refund composition (scaffold calc weather_refund_amount)
    if order["booking_status"] == "CONFIRMED":
        rental_refund = order["rental_subtotal_cents"] + order["cleaning_fee_total_cents"]
        delivery_refund = order["delivery_fee_cents"]
    else:  # FULFILLED
        rental_refund = 0
        delivery_refund = 0
    weather_refund = rental_refund + delivery_refund
    # cascade: release lines + cancel runs (like ordinary cancel)
    for l in lines_of_order(order_id):
        if l["status"] != "RELEASED":
            l["status"] = "RELEASED"
            touch(l)
    for r in runs_of_order(order_id):
        if r["status"] in ("SCHEDULED", "ATTEMPTED"):
            r["status"] = "CANCELLED"
            touch(r)
    # release held deposit in full
    if order["settlement_status"] == "DEPOSIT_HELD":
        held = held_balance_of(order_id)
        order["settlement_status"] = "DEPOSIT_RELEASED"
        append_ledger(order_id, "RELEASE", held, reason="weather cancellation")
    # credit weather refund to customer
    order["_weather_refund_credited"] = order.get("_weather_refund_credited", 0) + weather_refund
    order["booking_status"] = "CANCELLED"
    recompute_customer_credit(order["customer_id"])
    touch(order)
    return success_object(ser.order_view(order))


# ===========================================================================
# Deposit settlement
# ===========================================================================

@app.post("/orders/<order_id>/deposit/settle")
def settle_deposit(order_id):
    _, role = get_auth()
    require_role(role, {"DepositAdjuster"})
    order = get_or_404(store.orders, order_id)
    d = body()
    disposition = require_enum(d, "disposition", DISPOSITIONS)
    expected_version = require_int(d, "expected_order_version")
    # state (priority 5): settlement must be DEPOSIT_HELD
    if order["settlement_status"] != "DEPOSIT_HELD":
        raise_err(ERR_INVALID_STATE, "Settlement status is not DEPOSIT_HELD")
    # not returned (priority 12)
    if order["booking_status"] != "RETURNED":
        raise_err(ERR_NOT_RETURNED, "Order is not RETURNED")
    held = held_balance_of(order_id)
    if disposition == "FORFEIT":
        forfeit_amount = require_int(d, "forfeit_amount_cents", minimum=0)
        # forfeit exceeds held (priority 13) — before OCC
        if forfeit_amount > held:
            raise_err(ERR_FORFEIT_EXCEEDS_HELD, "Forfeit amount exceeds held balance")
    reason = opt_str(d, "reason", "")
    # OCC (priority 18) — last
    if expected_version != order["version"]:
        raise_err(ERR_STALE_VERSION, "expected_order_version does not match current version")
    if disposition == "RELEASE":
        order["settlement_status"] = "DEPOSIT_RELEASED"
        append_ledger(order_id, "RELEASE", held, reason=reason)
        recompute_customer_credit(order["customer_id"])
    else:  # FORFEIT
        order["settlement_status"] = "DEPOSIT_FORFEITED"
        append_ledger(order_id, "FORFEIT", forfeit_amount, reason=reason)
        remainder = held - forfeit_amount
        if remainder > 0:
            append_ledger(order_id, "RELEASE", remainder, reason=reason)
        recompute_customer_credit(order["customer_id"])
    touch(order)
    return success_object(ser.order_view(order))


@app.get("/orders/<order_id>/deposit-ledger")
def list_deposit_ledger(order_id):
    user_id, role = get_auth()
    require_role(role, {"RentalAgent", "DepositAdjuster", "Customer"})
    order = get_or_404(store.orders, order_id)
    if role == "Customer":
        check_order_owner(order, user_id, role)
    limit, offset = pagination()
    recs = ledger_of_order(order_id)
    # created_at ASC, tie-break created_at only (use insertion seq, never id)
    ordered = sorted(recs, key=lambda e: e["_created_seq_key"])
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return success_array([ser.ledger_view(r) for r in page], limit, offset, total)


# ===========================================================================
# Crew & DeliveryRun
# ===========================================================================

@app.post("/crews")
def create_crew():
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    d = body()
    name = require_str(d, "name")
    turnaround = opt_int(d, "turnaround_minutes", 0, minimum=0)
    rec = {"id": new_id(), "name": name, "turnaround_minutes": turnaround}
    stamp_created(rec)
    store.crews[rec["id"]] = rec
    return success_object(ser.crew_view(rec), 201)


@app.get("/crews/<crew_id>")
def get_crew(crew_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    rec = get_or_404(store.crews, crew_id)
    return success_object(ser.crew_view(rec))


@app.post("/delivery-runs")
def create_delivery_run():
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    d = body()
    order_id = require_str(d, "order_id")
    leg = require_enum(d, "leg", LEGS)
    crew_id = require_str(d, "crew_id")
    ws_raw, ws_dt = require_dt(d, "window_start")
    we_raw, we_dt = require_dt(d, "window_end")
    order = store.orders.get(order_id)
    if order is None:
        raise_err(ERR_NOT_FOUND, "Order not found")
    crew = store.crews.get(crew_id)
    if crew is None:
        raise_err(ERR_NOT_FOUND, "Crew not found")
    # crew window conflict (priority 9)
    if crew_window_conflict(crew_id, ws_dt, we_dt, crew["turnaround_minutes"]):
        raise_err(ERR_CREW_WINDOW_CONFLICT, "Run window collides with another crew run")
    rec = {
        "id": new_id(), "order_id": order_id, "leg": leg, "crew_id": crew_id,
        "window_start": ws_raw, "window_end": we_raw,
        "status": "SCHEDULED", "attempt_count": 0,
        "_window_start_dt": ws_dt, "_window_end_dt": we_dt,
    }
    stamp_created(rec)
    store.delivery_runs[rec["id"]] = rec
    return success_object(ser.run_view(rec), 201)


@app.get("/delivery-runs/<run_id>")
def get_delivery_run(run_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    rec = get_or_404(store.delivery_runs, run_id)
    return success_object(ser.run_view(rec))


@app.get("/delivery-runs")
def list_delivery_runs():
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    limit, offset = pagination()
    order_id = request.args.get("order_id")
    crew_id = request.args.get("crew_id")
    recs = list(store.delivery_runs.values())
    if order_id is not None:
        recs = [r for r in recs if r["order_id"] == order_id]
    if crew_id is not None:
        recs = [r for r in recs if r["crew_id"] == crew_id]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.run_view(r) for r in page], limit, offset, total)


@app.post("/delivery-runs/<run_id>/attempt")
def attempt_delivery_run(run_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    run = get_or_404(store.delivery_runs, run_id)
    d = body()
    outcome = require_enum(d, "outcome", RUN_OUTCOMES)
    if run["status"] != "SCHEDULED":
        raise_err(ERR_INVALID_STATE, "Run is not SCHEDULED")
    if outcome == "SUCCESS":
        run["status"] = "COMPLETED"
    else:  # FAILED
        run["status"] = "ATTEMPTED"
        run["attempt_count"] += 1
    touch(run)
    return success_object(ser.run_view(run))


@app.post("/delivery-runs/<run_id>/reschedule")
def reschedule_delivery_run(run_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    run = get_or_404(store.delivery_runs, run_id)
    d = body()
    ws_raw, ws_dt = require_dt(d, "window_start")
    we_raw, we_dt = require_dt(d, "window_end")
    if run["status"] != "ATTEMPTED":
        raise_err(ERR_INVALID_STATE, "Run is not ATTEMPTED")
    # max attempts (priority 10): allowed only while attempt_count <= 2
    if run["attempt_count"] > 2:
        raise_err(ERR_MAX_ATTEMPTS_EXCEEDED, "Reschedule forbidden after 3rd failed attempt")
    crew = store.crews[run["crew_id"]]
    if crew_window_conflict(run["crew_id"], ws_dt, we_dt, crew["turnaround_minutes"],
                            exclude_run_id=run_id):
        raise_err(ERR_CREW_WINDOW_CONFLICT, "New window collides with another crew run")
    run["status"] = "SCHEDULED"
    run["window_start"] = ws_raw
    run["window_end"] = we_raw
    run["_window_start_dt"] = ws_dt
    run["_window_end_dt"] = we_dt
    touch(run)
    return success_object(ser.run_view(run))


@app.post("/delivery-runs/<run_id>/cancel")
def cancel_delivery_run(run_id):
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    run = get_or_404(store.delivery_runs, run_id)
    if run["status"] not in ("SCHEDULED", "ATTEMPTED"):
        raise_err(ERR_INVALID_STATE, "Run is not SCHEDULED or ATTEMPTED")
    run["status"] = "CANCELLED"
    touch(run)
    return success_object(ser.run_view(run))


# ===========================================================================
# WeatherEvent
# ===========================================================================

@app.post("/weather-events")
def create_weather_event():
    _, role = get_auth()
    require_role(role, {"RentalAgent"})
    d = body()
    zone = require_enum(d, "delivery_zone", DELIVERY_ZONES)
    severity = require_enum(d, "severity", SEVERITIES)
    ed_raw, ed_dt = require_dt(d, "effective_date")
    rec = {
        "id": new_id(), "delivery_zone": zone, "severity": severity,
        "effective_date": ed_raw, "_effective_date_dt": ed_dt,
    }
    stamp_created(rec, with_common=False)
    store.weather_events[rec["id"]] = rec
    return success_object(ser.weather_event_view(rec), 201)


@app.get("/weather-events")
def list_weather_events():
    _, role = get_auth()
    require_role(role, {"RentalAgent", "Customer"})
    limit, offset = pagination()
    zone = request.args.get("delivery_zone")
    recs = list(store.weather_events.values())
    if zone is not None:
        recs = [w for w in recs if w["delivery_zone"] == zone]
    page, total = paginate(recs, limit, offset)
    return success_array([ser.weather_event_view(r) for r in page], limit, offset, total)


# ===========================================================================
# Error handlers
# ===========================================================================

@app.errorhandler(ApiError)
def _handle_api_error(e: ApiError):
    return error_response(e.error_id, e.message, e.http_status)


@app.errorhandler(404)
def _handle_404(e):
    return error_response("ERR_NOT_FOUND", "Resource not found", 404)


@app.errorhandler(405)
def _handle_405(e):
    return error_response("ERR_VALIDATION", "Method not allowed", 405)


@app.errorhandler(HTTPException)
def _handle_http(e: HTTPException):
    return error_response("ERR_VALIDATION", e.description or "Bad request", e.code or 400)


@app.errorhandler(Exception)
def _handle_unhandled(e):
    return error_response("ERR_VALIDATION", f"Internal error: {type(e).__name__}", 500)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
