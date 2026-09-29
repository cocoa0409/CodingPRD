"""Properties, par-level supply lines and the append-only stock ledger."""

from flask import Blueprint

import errors
import validation as v
from db import base_fields, db, touch
from errors import fail
from middleware import authenticate
from response import created, ok, ok_list
from services import lookup
from services.listing import sort_stock_movements, sort_supply_lines
from services.serialize import (
    property_view,
    stock_movement_view,
    supply_line_view,
)
from services.stock import append_movement, project_line

bp = Blueprint("properties", __name__)

SIZE_TIERS = ("STUDIO", "ONE_BR", "TWO_BR", "THREE_BR_PLUS")
PROPERTY_STATUSES = ("ACTIVE", "PAUSED", "OFFBOARDED")
SUPPLY_CATEGORIES = ("LINEN", "CONSUMABLE", "WELCOME")
SUPPLY_STATUSES = ("ACTIVE", "DISCONTINUED")
MOVEMENT_REASONS = ("SEED", "REPLENISH", "RESTOCK_USE", "REVERSAL")


def _zone_code(body, name):
    value = v.req_string(body, name, allow_empty=False)
    if len(value) > 16 or value != value.upper():
        fail(errors.ERR_INVALID_REQUEST,
             "Field '%s' must be an uppercase token of 1-16 characters." % name)
    return value


@bp.post("/properties")
def create_property():
    authenticate(("PlatformAdmin",))
    body = v.json_body()
    code = v.req_string(body, "code", allow_empty=False)
    name = v.req_string(body, "name", allow_empty=False)
    zone_code = _zone_code(body, "zone_code")
    size_tier = v.req_enum(body, "size_tier", SIZE_TIERS)
    owner_contact_email = v.req_string(body, "owner_contact_email", allow_empty=False)
    bedroom_count = v.opt_int(body, "bedroom_count", 1, minimum=0, maximum=12)
    bathroom_count = v.opt_int(body, "bathroom_count", 1, minimum=0, maximum=12)
    bed_count = v.opt_int(body, "bed_count", 1, minimum=0, maximum=24)
    local_utc_offset_minutes = v.opt_int(body, "local_utc_offset_minutes", 0,
                                        minimum=-720, maximum=840)
    min_clean_minutes = v.opt_int(body, "min_clean_minutes", 60, minimum=0, maximum=600)
    min_skill_level = v.opt_int(body, "min_skill_level", 1, minimum=1, maximum=5)
    owner_notify_min_cost_cents = v.opt_int(body, "owner_notify_min_cost_cents", 5000,
                                           minimum=0)
    status = v.opt_enum(body, "status", PROPERTY_STATUSES, "ACTIVE")

    for existing in db.properties.values():
        if existing["code"] == code:
            fail(errors.ERR_DUPLICATE_RESOURCE_KEY,
                 "Property code '%s' is already registered." % code)

    record = base_fields()
    record.update({
        "code": code,
        "name": name,
        "zone_code": zone_code,
        "size_tier": size_tier,
        "bedroom_count": bedroom_count,
        "bathroom_count": bathroom_count,
        "bed_count": bed_count,
        "local_utc_offset_minutes": local_utc_offset_minutes,
        "min_clean_minutes": min_clean_minutes,
        "min_skill_level": min_skill_level,
        "owner_contact_email": owner_contact_email,
        "owner_notify_min_cost_cents": owner_notify_min_cost_cents,
        "status": status,
        "open_issue_count": 0,
        "last_turnover_completed_at": None,
    })
    db.properties[record["id"]] = record
    return created(property_view(record))


@bp.get("/properties/<property_id>")
def read_property(property_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "QualityAuditor", "PropertyOwner"))
    record = lookup.get_property(property_id)
    lookup.owner_scope_resource(actor, record["id"])
    return ok(property_view(record))


@bp.post("/properties/<property_id>/supply-lines")
def create_supply_line(property_id):
    authenticate(("PlatformAdmin", "Coordinator"))
    body = v.json_body()
    sku = v.req_string(body, "sku", allow_empty=False)
    name = v.req_string(body, "name", allow_empty=False)
    category = v.req_enum(body, "category", SUPPLY_CATEGORIES)
    unit_cost_cents = v.req_int(body, "unit_cost_cents", minimum=0)
    par_qty = v.req_int(body, "par_qty", minimum=0)
    unit = v.opt_string(body, "unit", "each", allow_empty=False)
    reorder_point = v.opt_int(body, "reorder_point", 0, minimum=0)
    initial_on_hand_qty = v.opt_int(body, "initial_on_hand_qty", 0, minimum=0)
    status = v.opt_enum(body, "status", SUPPLY_STATUSES, "ACTIVE")

    prop = lookup.get_property(property_id)

    for existing in db.supply_lines.values():
        if existing["property_id"] == prop["id"] and existing["sku"] == sku:
            fail(errors.ERR_DUPLICATE_RESOURCE_KEY,
                 "SKU '%s' already exists on this property." % sku)

    line = base_fields()
    line.update({
        "property_id": prop["id"],
        "sku": sku,
        "name": name,
        "category": category,
        "unit": unit,
        "unit_cost_cents": unit_cost_cents,
        "par_qty": par_qty,
        "reorder_point": reorder_point,
        "on_hand_qty": 0,
        "below_par": True,
        "status": status,
    })
    db.supply_lines[line["id"]] = line
    # Exactly one SEED movement, sequence_no 1, delta_qty = initial_on_hand_qty.
    append_movement(line, reason="SEED", delta_qty=initial_on_hand_qty)
    project_line(line)
    return created(supply_line_view(line))


@bp.get("/properties/<property_id>/supply-lines")
def list_property_supply_lines(property_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "PropertyOwner"))
    limit, offset = v.pagination()
    category = v.query_enum("category", SUPPLY_CATEGORIES)
    status = v.query_enum("status", SUPPLY_STATUSES)
    below_par = v.query_bool("below_par")

    prop = lookup.get_property(property_id)
    lookup.owner_scope_resource(actor, prop["id"])

    rows = [l for l in db.supply_lines.values() if l["property_id"] == prop["id"]]
    if category is not None:
        rows = [l for l in rows if l["category"] == category]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    if below_par is not None:
        rows = [l for l in rows if l["below_par"] is below_par]
    rows = sort_supply_lines(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([supply_line_view(r) for r in page], limit, offset, total)


@bp.get("/supply-lines/<supply_line_id>")
def read_supply_line(supply_line_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "Cleaner", "PropertyOwner"))
    line = lookup.get_supply_line(supply_line_id)
    lookup.owner_scope_resource(actor, line["property_id"])
    return ok(supply_line_view(line))


@bp.post("/supply-lines/<supply_line_id>/replenish")
def replenish_supply_line(supply_line_id):
    authenticate(("PlatformAdmin", "Coordinator"))
    body = v.json_body()
    qty = v.req_int(body, "qty")
    expected_version = v.req_int(body, "expected_supply_line_version")
    note = v.opt_string(body, "note")

    line = lookup.get_supply_line(supply_line_id)

    if expected_version != line["version"]:
        fail(errors.ERR_STALE_SUPPLY_LINE_VERSION,
             "Expected supply line version %s but the line is at %s."
             % (expected_version, line["version"]))
    if qty < 1:
        fail(errors.ERR_INSUFFICIENT_ON_HAND, "A replenishment quantity must be at least 1.")

    append_movement(line, reason="REPLENISH", delta_qty=qty, note=note)
    project_line(line)
    touch(line)
    return ok(supply_line_view(line))


@bp.get("/stock-movements")
def list_stock_movements():
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    limit, offset = v.pagination()
    supply_line_id = v.query_string("supply_line_id")
    turnover_id = v.query_string("turnover_id")
    checklist_task_id = v.query_string("checklist_task_id")
    property_id = v.query_string("property_id")
    reason = v.query_enum("reason", MOVEMENT_REASONS)

    lookup.owner_scope_list(actor, property_id)

    rows = list(db.stock_movements.values())
    if supply_line_id is not None:
        rows = [m for m in rows if m["supply_line_id"] == supply_line_id]
    if turnover_id is not None:
        rows = [m for m in rows if m["turnover_id"] == turnover_id]
    if checklist_task_id is not None:
        rows = [m for m in rows if m["checklist_task_id"] == checklist_task_id]
    if reason is not None:
        rows = [m for m in rows if m["reason"] == reason]
    if property_id is not None:
        rows = [m for m in rows
                if _movement_property_id(m) == property_id]
    rows = sort_stock_movements(rows)
    page, total = v.paginate(rows, limit, offset)
    return ok_list([stock_movement_view(r) for r in page], limit, offset, total)


def _movement_property_id(movement):
    line = db.supply_lines.get(movement["supply_line_id"])
    return line["property_id"] if line is not None else None


@bp.get("/stock-movements/<movement_id>")
def read_stock_movement(movement_id):
    actor = authenticate(("PlatformAdmin", "Coordinator", "PropertyOwner"))
    movement = lookup.get_stock_movement(movement_id)
    lookup.owner_scope_resource(actor, _movement_property_id(movement))
    return ok(stock_movement_view(movement))
