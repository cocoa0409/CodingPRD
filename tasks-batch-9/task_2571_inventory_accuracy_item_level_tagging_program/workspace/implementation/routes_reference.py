"""Reference data: categories, stores, vendors, counting firms, SKUs.

Also hosts the logical-clock surface and the store fulfillment-eligibility
computed read.
"""

from decimal import Decimal

from flask import Blueprint

import calc
from db import clock_now_iso, db, new_id, set_clock
from errors import ApiError
from middleware import require_read, require_roles
from response import created, ok, ok_list, paginate, read_pagination
from validate import (CODE_RE, S, body_json, filter_str, lookup, parse_body, parse_instant)

bp = Blueprint("reference", __name__)

PREFIX = "/inventory-integrity"

READER_MODE_REQUIRED = ("HANDHELD", "OVERHEAD", "EITHER")
READER_CAPABILITY = ("HANDHELD_ONLY", "OVERHEAD_ONLY", "BOTH")
CERTIFICATION_LEVELS = ("TIER_1", "TIER_2")
TAG_ENCODING_SCHEMES = ("SGTIN_96", "SGTIN_198", "NONE")
FULFILLMENT_STATUSES = ("ELIGIBLE", "PROBATION", "SUSPENDED")


def _unique(collection, field, value, error_id):
    for row in getattr(db, collection).values():
        if row.get(field) == value:
            raise ApiError(error_id, "%s '%s' is already registered" % (field, value))


def _list(collection, predicates):
    matched = [r for r in getattr(db, collection).values()
               if all(r.get(key) == value for key, value in predicates)]
    limit, offset = read_pagination()
    page, total = paginate(calc.newest_first(matched), limit, offset)
    return ok_list(page, limit, offset, total)


# --------------------------------------------------------------------------
# Category
# --------------------------------------------------------------------------
CATEGORY_SPECS = [
    S("code", "str", min_len=1, max_len=32, pattern=CODE_RE),
    S("name", "str", min_len=1, max_len=120),
    S("count_cadence_days", "int", min=7, max=365),
    S("variance_tolerance_units", "int", min=0),
    S("variance_tolerance_value_cents", "int", min=1),
    S("min_accuracy_pct", "dec2", min=0, max=100),
    S("landed_cost_uplift_bps", "int", required=False, default=0, min=0, max=5000),
    S("reader_mode_required", "enum", required=False, default="EITHER",
      allowed=READER_MODE_REQUIRED),
    S("auto_correct_negative", "bool", required=False, default=True),
]


@bp.post(PREFIX + "/categories")
def create_category():
    require_roles("SystemAdmin")
    data = parse_body(body_json(), CATEGORY_SPECS)
    _unique("categories", "code", data["code"], "ERR_DUPLICATE_CATEGORY_CODE")
    row = calc.base_row({"id": new_id()})
    record = {"id": row["id"]}
    record.update({k: data[k] for k in ("code", "name", "count_cadence_days",
                                        "variance_tolerance_units",
                                        "variance_tolerance_value_cents",
                                        "landed_cost_uplift_bps",
                                        "reader_mode_required", "min_accuracy_pct",
                                        "auto_correct_negative")})
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.categories[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/categories/<category_id>")
def get_category(category_id):
    require_read()
    return ok(lookup("categories", category_id))


@bp.get(PREFIX + "/categories")
def list_categories():
    require_read()
    return _list("categories", [])


# --------------------------------------------------------------------------
# Store
# --------------------------------------------------------------------------
STORE_SPECS = [
    S("code", "str", min_len=1, max_len=16),
    S("name", "str", min_len=1, max_len=120),
    S("reader_capability", "enum", allowed=READER_CAPABILITY),
    S("overhead_reader_capacity", "int", required=False, default=2, min=0, max=8),
]


@bp.post(PREFIX + "/stores")
def create_store():
    require_roles("SystemAdmin")
    data = parse_body(body_json(), STORE_SPECS)
    _unique("stores", "code", data["code"], "ERR_DUPLICATE_STORE_CODE")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "code": data["code"],
        "name": data["name"],
        "reader_capability": data["reader_capability"],
        "overhead_reader_capacity": data["overhead_reader_capacity"],
        "total_position_count": 0,
        "blocked_position_count": 0,
        "restricted_position_count": 0,
        "accuracy_index_bps": 10000,
        "fulfillment_status": "ELIGIBLE",
        "_blocked_ratio_bps": 0,
        "_restricted_ratio_bps": 0,
        "_demotion_reason": "",
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.stores[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/stores/<store_id>")
def get_store(store_id):
    require_read()
    return ok(lookup("stores", store_id))


@bp.get(PREFIX + "/stores")
def list_stores():
    require_read()
    from validate import filter_enum
    status = filter_enum("fulfillment_status", FULFILLMENT_STATUSES)
    predicates = []
    if status is not None:
        predicates.append(("fulfillment_status", status))
    return _list("stores", predicates)


@bp.get(PREFIX + "/stores/<store_id>/fulfillment-eligibility")
def store_fulfillment_eligibility(store_id):
    require_read()
    store = lookup("stores", store_id)
    figures = calc.store_posture_figures(store_id)
    return ok({
        "store_id": store["id"],
        "total_position_count": figures["total_position_count"],
        "blocked_position_count": figures["blocked_position_count"],
        "restricted_position_count": figures["restricted_position_count"],
        "blocked_ratio_bps": figures["blocked_ratio_bps"],
        "restricted_ratio_bps": figures["restricted_ratio_bps"],
        "accuracy_index_bps": figures["accuracy_index_bps"],
        "fulfillment_status": figures["fulfillment_status"],
        "demotion_reason": figures["demotion_reason"],
    })


# --------------------------------------------------------------------------
# Vendor
# --------------------------------------------------------------------------
VENDOR_SPECS = [
    S("code", "str", min_len=1, max_len=16),
    S("name", "str", min_len=1, max_len=160),
]


@bp.post(PREFIX + "/vendors")
def create_vendor():
    require_roles("SystemAdmin")
    data = parse_body(body_json(), VENDOR_SPECS)
    _unique("vendors", "code", data["code"], "ERR_DUPLICATE_VENDOR_CODE")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "code": data["code"],
        "name": data["name"],
        "tag_compliance_score_bps": 10000,
        "required_verification_sample_pct": 5,
        "shortage_event_count": 0,
        "lifetime_chargeback_gross_cents": 0,
        "credited_cents": 0,
        "chargeback_balance_cents": 0,
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.vendors[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/vendors/<vendor_id>")
def get_vendor(vendor_id):
    require_read()
    return ok(lookup("vendors", vendor_id))


@bp.get(PREFIX + "/vendors")
def list_vendors():
    require_read()
    return _list("vendors", [])


# --------------------------------------------------------------------------
# CounterFirm (immutable: no updated_at, no version)
# --------------------------------------------------------------------------
COUNTER_FIRM_SPECS = [
    S("code", "str", min_len=1, max_len=16),
    S("name", "str", min_len=1, max_len=160),
    S("certification_level", "enum", allowed=CERTIFICATION_LEVELS),
    S("max_lines_per_pass", "int", min=1, max=100000),
]


@bp.post(PREFIX + "/counter-firms")
def create_counter_firm():
    require_roles("SystemAdmin")
    data = parse_body(body_json(), COUNTER_FIRM_SPECS)
    _unique("counter_firms", "code", data["code"], "ERR_DUPLICATE_COUNTER_FIRM_CODE")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "code": data["code"],
        "name": data["name"],
        "certification_level": data["certification_level"],
        "max_lines_per_pass": data["max_lines_per_pass"],
        "created_at": row["created_at"],
        "_seq": row["_seq"],
    }
    db.counter_firms[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/counter-firms/<counter_firm_id>")
def get_counter_firm(counter_firm_id):
    require_read()
    return ok(lookup("counter_firms", counter_firm_id))


@bp.get(PREFIX + "/counter-firms")
def list_counter_firms():
    require_read()
    return _list("counter_firms", [])


# --------------------------------------------------------------------------
# Item
# --------------------------------------------------------------------------
ITEM_SPECS = [
    S("sku", "str", min_len=1, max_len=32),
    S("description", "str", min_len=1, max_len=240),
    S("unit_cost_cents", "int", min=1),
    S("retail_price_cents", "int", min=1),
    S("epc_prefix_length", "int", required=False, default=7, min=6, max=12),
    S("tag_required", "bool", required=False, default=True),
    S("tag_encoding_scheme", "enum", allowed=TAG_ENCODING_SCHEMES),
]


@bp.post(PREFIX + "/items")
def create_item():
    require_roles("SystemAdmin")
    body = body_json()
    # Body foreign keys resolve in declared input order (rejection tier 5).
    category = lookup("categories", body.get("category_id"))
    vendor = lookup("vendors", body.get("primary_vendor_id"))
    data = parse_body(body, ITEM_SPECS)
    _unique("items", "sku", data["sku"], "ERR_DUPLICATE_SKU")
    row = calc.base_row({"id": new_id()})
    record = {
        "id": row["id"],
        "category_id": category["id"],
        "primary_vendor_id": vendor["id"],
        "sku": data["sku"],
        "description": data["description"],
        "unit_cost_cents": data["unit_cost_cents"],
        "retail_price_cents": data["retail_price_cents"],
        "tag_encoding_scheme": data["tag_encoding_scheme"],
        "epc_prefix_length": data["epc_prefix_length"],
        "tag_required": data["tag_required"],
    }
    record.update({k: row[k] for k in ("created_at", "updated_at", "version", "_seq")})
    db.items[record["id"]] = record
    return created(record)


@bp.get(PREFIX + "/items/<item_id>")
def get_item(item_id):
    require_read()
    return ok(lookup("items", item_id))


@bp.get(PREFIX + "/items")
def list_items():
    require_read()
    predicates = []
    for param, key in (("category_id", "category_id"),
                       ("primary_vendor_id", "primary_vendor_id")):
        value = filter_str(param)
        if value is not None:
            predicates.append((key, value))
    return _list("items", predicates)


# --------------------------------------------------------------------------
# logical clock
# --------------------------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_current_utc():
    require_roles("SystemAdmin")
    body = body_json()
    data = parse_body(body, [S("to_iso8601", "str", min_len=1)])
    instant = parse_instant(data["to_iso8601"], "to_iso8601")
    set_clock(instant)
    return ok({"current_utc": clock_now_iso()})
