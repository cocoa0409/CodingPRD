"""Product catalogue endpoints (PRD §3.2) and the computed floor read (§3.6)."""

from flask import Blueprint

import lookup
from auth import ALL_ROLES, ROLE_BRAND_CHANNEL_MANAGER, authenticate
from calc import resolve_floor
from envelope import created, ok, ok_list
from errors import fail
from store import new_row, now_iso, now_dt, parse_iso, serialize, sort_rows, store, touch
from validate import (
    CHANNELS, LIFECYCLE_STATUSES, body, opt_bool, opt_enum, opt_fraction, opt_int,
    query_bool, query_dt, query_enum, req_int, req_str,
)

bp = Blueprint("products", __name__)


@bp.post("/products")
def register_product():
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    sku = req_str(b, "sku", 1, 40)
    name = req_str(b, "name", 1, None)
    msrp_cents = req_int(b, "msrp_cents", 1, None)
    floor_cents = req_int(b, "standard_map_floor_cents", 1, None)
    if floor_cents > msrp_cents:
        fail("ERR_VALIDATION", "standard_map_floor_cents must not exceed msrp_cents.")
    governing_policy_id = req_str(b, "governing_policy_id")
    lifecycle_status = opt_enum(b, "lifecycle_status", LIFECYCLE_STATUSES, "ACTIVE")
    clearance_pct = opt_fraction(b, "clearance_discount_pct", 0.00, 0.60, 0.20)
    serialization_enabled = opt_bool(b, "serialization_enabled", True)

    policy = lookup.policy(governing_policy_id)
    if policy["status"] != "PUBLISHED":
        fail("ERR_POLICY_NOT_PUBLISHED", "The governing policy must be PUBLISHED at registration.")
    for existing in store.products.values():
        if existing["sku"] == sku:
            fail("ERR_DUPLICATE_SKU", "sku must be unique across the catalogue.")

    row = new_row({
        "sku": sku,
        "name": name,
        "msrp_cents": msrp_cents,
        "standard_map_floor_cents": floor_cents,
        "lifecycle_status": lifecycle_status,
        "clearance_discount_pct": clearance_pct,
        "serialization_enabled": serialization_enabled,
        "governing_policy_id": governing_policy_id,
        "open_exception_count": 0,
    })
    store.products[row["id"]] = row
    return created(serialize(row))


@bp.patch("/products/<product_id>")
def adjust_product(product_id):
    authenticate([ROLE_BRAND_CHANNEL_MANAGER])
    b = body()
    lifecycle_status = opt_enum(b, "lifecycle_status", LIFECYCLE_STATUSES)
    clearance_pct = opt_fraction(b, "clearance_discount_pct", 0.00, 0.60)
    floor_cents = opt_int(b, "standard_map_floor_cents", 1, None)
    product = lookup.product(product_id)
    if floor_cents is not None and floor_cents > product["msrp_cents"]:
        fail("ERR_VALIDATION", "standard_map_floor_cents must not exceed msrp_cents.")

    if lifecycle_status is not None:
        product["lifecycle_status"] = lifecycle_status
    if clearance_pct is not None:
        product["clearance_discount_pct"] = clearance_pct
    if floor_cents is not None:
        product["standard_map_floor_cents"] = floor_cents
    touch(product)

    if lifecycle_status == "DISCONTINUED":
        rows = sort_rows([e for e in store.exceptions.values()
                          if e["product_id"] == product["id"]
                          and e["status"] in ("REQUESTED", "APPROVED")])
        for exc in rows:
            was_approved = exc["status"] == "APPROVED"
            exc["status"] = "VOIDED"
            exc["decision_reason"] = "PRODUCT_DISCONTINUED"
            touch(exc)
            if was_approved:
                product["open_exception_count"] = max(0, product["open_exception_count"] - 1)
                touch(product)
    return ok(serialize(product))


@bp.get("/products/<product_id>")
def read_product(product_id):
    authenticate(ALL_ROLES)
    return ok(serialize(lookup.product(product_id)))


@bp.get("/products")
def list_products():
    authenticate(ALL_ROLES)
    rows = lookup.filtered("products", {
        "governing_policy_id": "governing_policy_id",
        "lifecycle_status": "lifecycle_status",
        "sku": "sku",
    })
    return ok_list(rows)


@bp.get("/products/<product_id>/effective-floor")
def effective_floor(product_id):
    authenticate(ALL_ROLES)
    channel = query_enum("channel", CHANNELS, required=True)
    as_of_raw = query_dt("as_of")
    is_bundle = query_bool("is_bundle", False)
    product = lookup.product(product_id)
    if as_of_raw is None:
        as_of_raw = now_iso()
        as_of = now_dt()
    else:
        as_of = parse_iso(as_of_raw)
    floor_cents, source, exception_id = resolve_floor(product, channel, as_of, is_bundle)
    return ok({
        "product_id": product["id"],
        "channel": channel,
        "as_of": as_of_raw,
        "effective_map_floor_cents": floor_cents,
        "floor_source": source,
        "applied_exception_id": exception_id,
        "standard_map_floor_cents": product["standard_map_floor_cents"],
    })
