"""Master-data endpoints: properties, residents, technicians, vendors, parts,
plus the SLA compliance report."""

from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint, request

from db import new_record, store, touch
from domain import clear_assignment, recompute_restock, release_reserved_lines
from errors import duplicate_sku, invalid_state, not_found, validation
from helpers import body, is_int, pagination, sorted_page, TRADES
from middleware import authn, authorize
from response import ok_list, ok_object
from serializers import (
    part_out,
    property_out,
    resident_out,
    technician_out,
    vendor_out,
)
from timeutil import fmt_dt, parse_dt

bp = Blueprint("master", __name__)

ALL_ROLES = ("Resident", "Dispatcher", "Technician", "Vendor", "PropertyManager")

# Policy defaults (PRD 3.1).
PROPERTY_DEFAULTS = {
    "emergency_response_hours": 4,
    "emergency_completion_hours": 24,
    "urgent_response_hours": 24,
    "urgent_completion_hours": 72,
    "routine_response_hours": 72,
    "routine_completion_hours": 168,
    "purchase_auto_approve_threshold_cents": 50000,
    "recall_window_days": 30,
    "vendor_travel_buffer_minutes": 60,
    "entry_notice_min_hours": 24,
}


def _require_property(payload):
    """Existence of a payload FK: present-but-nonexistent -> 404 (priority 4)."""
    pid = payload.get("property_id")
    if isinstance(pid, str) and pid and pid not in store.properties:
        not_found("property")


# --- Property ------------------------------------------------------------------

@bp.post("/properties")
def create_property():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    b = body()
    if not isinstance(b.get("name"), str):
        validation("name is required")
    rec = new_record()
    rec["name"] = b["name"]
    for field, default in PROPERTY_DEFAULTS.items():
        value = b.get(field, default)
        if not is_int(value):
            validation(f"{field} must be an integer")
        rec[field] = value
    store.properties[rec["id"]] = rec
    return ok_object(property_out(rec), 201)


@bp.get("/properties/<prop_id>")
def get_property(prop_id):
    authn_role = authn()[1]
    authorize(authn_role, ALL_ROLES)
    prop = store.properties.get(prop_id)
    if prop is None:
        not_found("property")
    return ok_object(property_out(prop))


@bp.get("/properties/<prop_id>/sla-report")
def sla_report(prop_id):
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "PropertyManager"})
    prop = store.properties.get(prop_id)
    if prop is None:
        not_found("property")
    ws_raw = request.args.get("window_start")
    we_raw = request.args.get("window_end")
    basis = request.args.get("basis", "OPEN_INCLUSIVE")
    ws = parse_dt(ws_raw) if isinstance(ws_raw, str) else None
    we = parse_dt(we_raw) if isinstance(we_raw, str) else None
    if ws is None or we is None:
        validation("window_start and window_end are required ISO 8601 datetimes")
    if basis not in ("CLOSED_ONLY", "OPEN_INCLUSIVE"):
        validation("basis must be CLOSED_ONLY or OPEN_INCLUSIVE")

    now = store.clock
    closed_statuses = ("COMPLETED", "CLOSED")
    open_statuses = ("TRIAGED", "ASSIGNED", "IN_PROGRESS", "REOPENED")
    metrics = []
    for priority in ("EMERGENCY", "URGENT", "ROUTINE"):
        eligible = [
            wo
            for wo in store.work_orders.values()
            if wo["property_id"] == prop["id"]
            and wo["priority"] == priority
            and ws <= wo["created_at"] < we  # half-open creation window
            and (
                wo["status"] in closed_statuses
                or (basis == "OPEN_INCLUSIVE" and wo["status"] in open_statuses)
            )
        ]
        response_ok = 0
        completion_ok = 0
        for wo in eligible:
            if wo["status"] in closed_statuses:
                if not wo["response_sla_breached"]:
                    response_ok += 1
                if not wo["completion_sla_breached"]:
                    completion_ok += 1
            else:
                # Open work orders are judged live against the logical clock.
                first = wo["first_responded_at"]
                if (first is not None and first <= wo["response_due_at"]) or (
                    first is None and now <= wo["response_due_at"]
                ):
                    response_ok += 1
                done = wo["completed_at"]
                if (done is not None and done <= wo["completion_due_at"]) or (
                    done is None and now <= wo["completion_due_at"]
                ):
                    completion_ok += 1
        n = len(eligible)
        if n == 0:
            response_pct = 100.0
            completion_pct = 100.0
        else:
            response_pct = float(
                (Decimal(100 * response_ok) / Decimal(n)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
            completion_pct = float(
                (Decimal(100 * completion_ok) / Decimal(n)).quantize(
                    Decimal("0.01"), rounding=ROUND_HALF_UP
                )
            )
        metrics.append(
            {
                "priority": priority,
                "eligible_count": n,
                "response_compliance_pct": response_pct,
                "completion_compliance_pct": completion_pct,
            }
        )

    return ok_object(
        {
            "property_id": prop["id"],
            "window_start": ws_raw,
            "window_end": we_raw,
            "basis": basis,
            "generated_at": fmt_dt(now),
            "metrics": metrics,
        }
    )


# --- Resident ------------------------------------------------------------------

@bp.post("/residents")
def create_resident():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    b = body()
    _require_property(b)
    if not isinstance(b.get("property_id"), str) or not b.get("property_id"):
        validation("property_id is required")
    for field in ("unit_number", "full_name", "email"):
        if not isinstance(b.get(field), str):
            validation(f"{field} is required")
    rec = new_record()
    rec.update(
        {
            "property_id": b["property_id"],
            "unit_number": b["unit_number"],
            "full_name": b["full_name"],
            "email": b["email"],
            "chargeback_balance_cents": 0,
        }
    )
    store.residents[rec["id"]] = rec
    return ok_object(resident_out(rec), 201)


@bp.get("/residents")
def list_residents():
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "PropertyManager"})
    limit, offset = pagination()
    items = list(store.residents.values())
    prop_filter = request.args.get("property_id")
    if prop_filter is not None:
        items = [r for r in items if r["property_id"] == prop_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([resident_out(r) for r in page], limit, offset, total)


@bp.get("/residents/<res_id>")
def get_resident(res_id):
    authn_role = authn()[1]
    authorize(authn_role, {"Resident", "Dispatcher", "PropertyManager"})
    resident = store.residents.get(res_id)
    if resident is None:
        not_found("resident")
    return ok_object(resident_out(resident))


# --- Technician ----------------------------------------------------------------

@bp.post("/technicians")
def create_technician():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    b = body()
    _require_property(b)
    if not isinstance(b.get("property_id"), str) or not b.get("property_id"):
        validation("property_id is required")
    if not isinstance(b.get("full_name"), str):
        validation("full_name is required")
    if b.get("trade") not in TRADES:
        validation("trade must be a declared trade")
    rec = new_record()
    rec.update(
        {
            "property_id": b["property_id"],
            "full_name": b["full_name"],
            "trade": b["trade"],
        }
    )
    store.technicians[rec["id"]] = rec
    return ok_object(technician_out(rec), 201)


@bp.get("/technicians")
def list_technicians():
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "PropertyManager"})
    limit, offset = pagination()
    items = list(store.technicians.values())
    prop_filter = request.args.get("property_id")
    if prop_filter is not None:
        items = [t for t in items if t["property_id"] == prop_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([technician_out(t) for t in page], limit, offset, total)


@bp.get("/technicians/<tech_id>")
def get_technician(tech_id):
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "Technician", "PropertyManager"})
    tech = store.technicians.get(tech_id)
    if tech is None:
        not_found("technician")
    return ok_object(technician_out(tech))


# --- Vendor --------------------------------------------------------------------

@bp.post("/vendors")
def create_vendor():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    b = body()
    _require_property(b)
    if not isinstance(b.get("property_id"), str) or not b.get("property_id"):
        validation("property_id is required")
    if not isinstance(b.get("company_name"), str):
        validation("company_name is required")
    if b.get("trade") not in TRADES:
        validation("trade must be a declared trade")
    insurance = parse_dt(b.get("insurance_valid_until"))
    if insurance is None:
        validation("insurance_valid_until must be a well-formed ISO 8601 datetime")
    rec = new_record()
    rec.update(
        {
            "property_id": b["property_id"],
            "company_name": b["company_name"],
            "trade": b["trade"],
            "insurance_valid_until": insurance,
            "status": "ACTIVE",
        }
    )
    store.vendors[rec["id"]] = rec
    return ok_object(vendor_out(rec), 201)


@bp.get("/vendors")
def list_vendors():
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "PropertyManager"})
    limit, offset = pagination()
    items = list(store.vendors.values())
    prop_filter = request.args.get("property_id")
    if prop_filter is not None:
        items = [v for v in items if v["property_id"] == prop_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([vendor_out(v) for v in page], limit, offset, total)


@bp.get("/vendors/<vendor_id>")
def get_vendor(vendor_id):
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "Vendor", "PropertyManager"})
    vendor = store.vendors.get(vendor_id)
    if vendor is None:
        not_found("vendor")
    return ok_object(vendor_out(vendor))


@bp.post("/vendors/<vendor_id>/events")
def vendor_event(vendor_id):
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    vendor = store.vendors.get(vendor_id)
    if vendor is None:
        not_found("vendor")
    event_type = body().get("event_type")
    if event_type == "SUSPEND":
        if vendor["status"] != "ACTIVE":
            invalid_state("only an ACTIVE vendor can be suspended")
        vendor["status"] = "SUSPENDED"
        touch(vendor)
        # Cascade: ASSIGNED work orders of this vendor revert to TRIAGED with
        # assignment cleared (first_responded_at retained), and their RESERVED
        # part lines are released, restoring stock. IN_PROGRESS work continues.
        for wo in list(store.work_orders.values()):
            if wo["assigned_vendor_id"] == vendor["id"] and wo["status"] == "ASSIGNED":
                wo["status"] = "TRIAGED"
                clear_assignment(wo)
                release_reserved_lines(wo)
                touch(wo)
    elif event_type == "REINSTATE":
        if vendor["status"] != "SUSPENDED":
            invalid_state("only a SUSPENDED vendor can be reinstated")
        vendor["status"] = "ACTIVE"
        touch(vendor)
    else:
        validation("event_type must be SUSPEND or REINSTATE")
    return ok_object(vendor_out(vendor))


# --- Part ----------------------------------------------------------------------

@bp.post("/parts")
def create_part():
    authn_role = authn()[1]
    authorize(authn_role, {"PropertyManager"})
    b = body()
    _require_property(b)
    sku = b.get("sku")
    if isinstance(sku, str) and isinstance(b.get("property_id"), str):
        for existing in store.parts.values():
            if existing["property_id"] == b["property_id"] and existing["sku"] == sku:
                duplicate_sku()
    if not isinstance(b.get("property_id"), str) or not b.get("property_id"):
        validation("property_id is required")
    if not isinstance(sku, str):
        validation("sku is required")
    if not isinstance(b.get("name"), str):
        validation("name is required")
    if not is_int(b.get("unit_cost_cents")) or b["unit_cost_cents"] < 0:
        validation("unit_cost_cents must be an integer >= 0")
    reorder_level = b.get("reorder_level", 0)
    if not is_int(reorder_level) or reorder_level < 0:
        validation("reorder_level must be an integer >= 0")
    initial_stock = b.get("initial_stock", 0)
    if not is_int(initial_stock) or initial_stock < 0:
        validation("initial_stock must be an integer >= 0")
    rec = new_record()
    rec.update(
        {
            "property_id": b["property_id"],
            "sku": sku,
            "name": b["name"],
            "unit_cost_cents": b["unit_cost_cents"],
            "reorder_level": reorder_level,
            "initial_stock": initial_stock,
            "quantity_on_hand": initial_stock,
            "reserved_quantity": 0,
        }
    )
    recompute_restock(rec)
    store.parts[rec["id"]] = rec
    return ok_object(part_out(rec), 201)


@bp.get("/parts")
def list_parts():
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "Technician", "Vendor", "PropertyManager"})
    limit, offset = pagination()
    items = list(store.parts.values())
    prop_filter = request.args.get("property_id")
    if prop_filter is not None:
        items = [p for p in items if p["property_id"] == prop_filter]
    page, total = sorted_page(items, limit, offset)
    return ok_list([part_out(p) for p in page], limit, offset, total)


@bp.get("/parts/<part_id>")
def get_part(part_id):
    authn_role = authn()[1]
    authorize(authn_role, {"Dispatcher", "Technician", "Vendor", "PropertyManager"})
    part = store.parts.get(part_id)
    if part is None:
        not_found("part")
    return ok_object(part_out(part))
