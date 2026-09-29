"""Dropship offers (DropshipItem) and their inventory feed messages."""

from flask import Blueprint, request

import calc
import serialize
import validate as v
from auth import authenticate, require_item_scope
from db import db, new_row, now, touch
from errors import api_error
from response import created, listing, ok, paginate, pagination

bp = Blueprint("items", __name__)

SHIP_METHODS = ("GROUND", "TWO_DAY", "FREIGHT_LTL")
FREIGHT_OWNERS = ("VENDOR", "RETAILER")
RESTOCK_POLICIES = ("VENDOR_RESTOCK", "RETAILER_RESTOCK", "DESTROY")
ITEM_STATUSES = ("DRAFT", "ACTIVE", "SUPPRESSED")
SNAPSHOT_SOURCES = ("VENDOR_FEED", "MANUAL_ADJUST")


def get_item(item_id):
    """Validation rank 4."""
    row = db.items.get(item_id)
    if row is None:
        api_error("ERR_ITEM_NOT_FOUND", "offer %s does not exist" % item_id)
    return row


def _resolve_fallback(body):
    """Rank 4 for the fallback pointer: absent -> None, unknown -> 404."""
    if not v.has_value(body, "fallback_item_id"):
        return None
    raw = body["fallback_item_id"]
    if not isinstance(raw, str):
        api_error("ERR_INVALID_REQUEST", "fallback_item_id must be a string")
    return get_item(raw)


def _check_fallback(item_id, sku, vendor_id, fallback):
    """Validation rank 30."""
    if fallback is None:
        return
    if fallback["id"] == item_id:
        api_error("ERR_FALLBACK_INVALID", "an offer may not fall back to itself")
    if fallback["sku"] != sku:
        api_error("ERR_FALLBACK_INVALID", "the fallback offer must carry the same sku")
    if fallback["vendor_id"] == vendor_id:
        api_error("ERR_FALLBACK_INVALID", "the fallback offer must belong to a different vendor")


# ------------------------------------------------------------- create/read --


@bp.post("/dropship/items")
def create_item():
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    body = v.payload()

    # rank 3: the vendor named in the body
    if not v.has_value(body, "vendor_id") or not isinstance(body["vendor_id"], str):
        api_error("ERR_INVALID_REQUEST", "vendor_id is required")
    vendor = db.vendors.get(body["vendor_id"])
    if vendor is None:
        api_error("ERR_VENDOR_NOT_FOUND", "vendor %s does not exist" % body["vendor_id"])

    # rank 4: the fallback offer, when supplied
    fallback = _resolve_fallback(body)

    # rank 12
    sku = v.req_str(body, "sku", 1, 40)
    unit_retail = v.req_int(body, "unit_retail_cents", 1, None)
    ship_method = v.req_enum(body, "ship_method", SHIP_METHODS)
    lead_days = v.opt_int(body, "lead_time_days", vendor["default_lead_time_days"], 0, 60)
    wholesale_cost = v.opt_int(body, "unit_wholesale_cost_cents", None, 1, None)
    freight_owner = v.opt_enum(body, "reverse_freight_owner", FREIGHT_OWNERS, "RETAILER")
    restock_policy = v.opt_enum(body, "restock_policy", RESTOCK_POLICIES, "VENDOR_RESTOCK")
    defect_window = v.opt_int(body, "defect_window_days", 30, 1, 365)

    # rank 14
    if vendor["cost_model"] == "WHOLESALE":
        if wholesale_cost is None:
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "unit_wholesale_cost_cents is required for a WHOLESALE vendor's offer")
    else:
        if v.has_value(body, "unit_wholesale_cost_cents"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "unit_wholesale_cost_cents must be omitted for a COMMISSION vendor's offer")
        wholesale_cost = None

    # rank 26
    if vendor["onboarding_status"] not in ("CERTIFIED", "ACTIVE"):
        api_error("ERR_VENDOR_NOT_ACTIVE",
                  "offers may only be created for a CERTIFIED or ACTIVE vendor")

    # rank 30
    _check_fallback(None, sku, vendor["id"], fallback)

    row = new_row()
    row.update({
        "vendor_id": vendor["id"],
        "fallback_item_id": fallback["id"] if fallback else None,
        "sku": sku,
        "lead_time_days": lead_days,
        "ship_method": ship_method,
        "unit_retail_cents": unit_retail,
        "unit_wholesale_cost_cents": wholesale_cost,
        "reverse_freight_owner": freight_owner,
        "restock_policy": restock_policy,
        "defect_window_days": defect_window,
        "status": "DRAFT",
        "suppression_reason": None,
        "reserved_units": 0,
        "last_inventory_refresh_at": None,
        "lifetime_reserved_units": 0,
        "lifetime_released_units": 0,
        "lifetime_shipped_units": 0,
        "unit_cost_cents": 0,
    })
    row["unit_cost_cents"] = calc.derive_unit_cost(row)
    db.items[row["id"]] = row
    return created(serialize.item(row))


@bp.get("/dropship/items/<item_id>")
def read_item(item_id):
    caller = authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager",
                           "VendorUser", "CareAgent"))
    row = get_item(item_id)
    require_item_scope(caller, row)
    return ok(serialize.item(row))


@bp.get("/dropship/items")
def list_items():
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "CareAgent"))

    vendor_id = v.filter_str(request.args, "vendor_id")
    fallback_item_id = v.filter_str(request.args, "fallback_item_id")
    status = v.filter_enum(request.args, "status", ITEM_STATUSES)
    sku = v.filter_str(request.args, "sku")
    limit, offset = pagination(request.args)

    rows = list(db.items.values())
    if vendor_id is not None:
        rows = [i for i in rows if i["vendor_id"] == vendor_id]
    if fallback_item_id is not None:
        rows = [i for i in rows if i["fallback_item_id"] == fallback_item_id]
    if status is not None:
        rows = [i for i in rows if i["status"] == status]
    if sku is not None:
        rows = [i for i in rows if i["sku"] == sku]

    rows = sorted(rows, key=lambda i: (i["created_at"], i["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.item(i) for i in page], limit, offset, total)


@bp.patch("/dropship/items/<item_id>")
def patch_item(item_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    item = get_item(item_id)
    body = v.payload()

    fallback = _resolve_fallback(body)
    vendor = calc.vendor_of(item)

    lead_days = v.opt_int(body, "lead_time_days", None, 0, 60)
    unit_retail = v.opt_int(body, "unit_retail_cents", None, 1, None)
    wholesale_cost = v.opt_int(body, "unit_wholesale_cost_cents", None, 1, None)
    ship_method = v.opt_enum(body, "ship_method", SHIP_METHODS)
    freight_owner = v.opt_enum(body, "reverse_freight_owner", FREIGHT_OWNERS)
    restock_policy = v.opt_enum(body, "restock_policy", RESTOCK_POLICIES)
    defect_window = v.opt_int(body, "defect_window_days", None, 1, 365)

    # rank 14
    if vendor is not None and vendor["cost_model"] == "COMMISSION":
        if v.has_value(body, "unit_wholesale_cost_cents"):
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "unit_wholesale_cost_cents must be omitted for a COMMISSION vendor's offer")
    elif vendor is not None:
        if v.has_key(body, "unit_wholesale_cost_cents") and wholesale_cost is None:
            api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                      "unit_wholesale_cost_cents is required for a WHOLESALE vendor's offer")

    # rank 20
    if item["status"] not in ("DRAFT", "SUPPRESSED"):
        api_error("ERR_ITEM_INVALID_STATE", "an ACTIVE offer is immutable")

    # rank 30
    new_sku = item["sku"]
    if fallback is not None:
        _check_fallback(item["id"], new_sku, item["vendor_id"], fallback)

    if lead_days is not None:
        item["lead_time_days"] = lead_days
    if unit_retail is not None:
        item["unit_retail_cents"] = unit_retail
    if wholesale_cost is not None:
        item["unit_wholesale_cost_cents"] = wholesale_cost
    if ship_method is not None:
        item["ship_method"] = ship_method
    if v.has_key(body, "fallback_item_id"):
        item["fallback_item_id"] = fallback["id"] if fallback else None
    if freight_owner is not None:
        item["reverse_freight_owner"] = freight_owner
    if restock_policy is not None:
        item["restock_policy"] = restock_policy
    if defect_window is not None:
        item["defect_window_days"] = defect_window

    item["unit_cost_cents"] = calc.derive_unit_cost(item)
    touch(item)
    return ok(serialize.item(item))


@bp.post("/dropship/items/<item_id>/activate")
def activate_item(item_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    item = get_item(item_id)

    # rank 20
    if item["status"] == "ACTIVE":
        api_error("ERR_ITEM_INVALID_STATE", "the offer is already ACTIVE")
    if item["status"] == "SUPPRESSED" and item["suppression_reason"] == "VENDOR_SUSPENDED":
        api_error("ERR_ITEM_INVALID_STATE",
                  "a VENDOR_SUSPENDED offer is restored only by vendor reinstatement")
    if item["status"] not in ("DRAFT", "SUPPRESSED"):
        api_error("ERR_ITEM_INVALID_STATE",
                  "activate is not allowed from %s" % item["status"])

    vendor = calc.vendor_of(item)
    # rank 26
    if vendor is None or vendor["onboarding_status"] != "ACTIVE":
        api_error("ERR_VENDOR_NOT_ACTIVE", "the owning vendor is not ACTIVE")

    # rank 29
    if not calc.has_active_coverage(item["vendor_id"], item["ship_method"]):
        api_error("ERR_NO_SERVICEABILITY_COVERAGE",
                  "no ACTIVE serviceability rule matches the offer's ship_method")

    # cost-model agreement
    if vendor["cost_model"] == "WHOLESALE" and item["unit_wholesale_cost_cents"] is None:
        api_error("ERR_COST_MODEL_FIELD_MISMATCH",
                  "unit_wholesale_cost_cents is required for a WHOLESALE vendor's offer")

    item["status"] = "ACTIVE"
    item["suppression_reason"] = None
    item["unit_cost_cents"] = calc.derive_unit_cost(item)
    touch(item)
    return ok(serialize.item(item))


@bp.post("/dropship/items/<item_id>/suppress")
def suppress_item(item_id):
    authenticate(("MerchandiseManager", "PlatformAdmin"))
    item = get_item(item_id)

    if item["status"] != "ACTIVE":
        api_error("ERR_ITEM_INVALID_STATE",
                  "suppress is not allowed from %s" % item["status"])

    item["status"] = "SUPPRESSED"
    item["suppression_reason"] = "MANUAL"
    touch(item)
    return ok(serialize.item(item))


# ------------------------------------------------------ inventory feed --


@bp.post("/dropship/items/<item_id>/inventory-snapshots")
def create_snapshot(item_id):
    authenticate(("VendorUser", "VendorOpsAnalyst", "PlatformAdmin"))
    item = get_item(item_id)
    body = v.payload()

    # rank 12
    on_hand = v.req_int(body, "on_hand_units", 0, None)
    effective_from = v.req_datetime(body, "effective_from")
    v.req_int(body, "feed_sequence", 1, None)
    expected_version = v.req_int(body, "expected_item_version", 0, None)
    effective_to = v.opt_datetime(body, "effective_to")
    source = v.opt_enum(body, "source", SNAPSHOT_SOURCES, "VENDOR_FEED")

    # rank 13
    if effective_to is not None and effective_to <= effective_from:
        api_error("ERR_INVALID_INTERVAL",
                  "effective_to must be strictly later than effective_from")

    # rank 17
    if expected_version != item["version"]:
        api_error("ERR_STALE_ITEM_VERSION",
                  "expected_item_version %d does not match the offer's current version %d"
                  % (expected_version, item["version"]))

    # rank 33: half-open overlap against ACTIVE snapshots of the same offer. An ACTIVE
    # open-ended window that starts strictly earlier is the row this feed supersedes, so
    # it counts as virtually closed at the new effective_from.
    superseded = []
    for other in db.snapshots.values():
        if other["item_id"] != item_id or other["status"] != "ACTIVE":
            continue
        other_to = other["effective_to"]
        if other_to is None and other["effective_from"] < effective_from:
            superseded.append(other)
            other_to = effective_from
        if other_to is not None and other_to <= effective_from:
            continue
        if effective_to is not None and effective_to <= other["effective_from"]:
            continue
        api_error("ERR_SNAPSHOT_WINDOW_OVERLAP",
                  "the window overlaps an existing ACTIVE snapshot")

    for other in superseded:
        other["status"] = "SUPERSEDED"
        other["effective_to"] = effective_from
        touch(other)

    sequence = len([s for s in db.snapshots.values() if s["item_id"] == item_id]) + 1

    row = new_row()
    row.update({
        "item_id": item_id,
        "on_hand_units": on_hand,
        "effective_from": effective_from,
        "effective_to": effective_to,
        "source": source,
        "status": "ACTIVE",
        "feed_sequence": sequence,
    })
    db.snapshots[row["id"]] = row

    item["last_inventory_refresh_at"] = now()

    view = calc.availability(item)
    if item["status"] == "ACTIVE":
        if view["atp_raw"] == 0 and view["effective_on_hand_units"] == 0:
            item["status"] = "SUPPRESSED"
            item["suppression_reason"] = "ZERO_AVAILABILITY"
    elif item["status"] == "SUPPRESSED" and item["suppression_reason"] == "ZERO_AVAILABILITY":
        if view["atp_raw"] > 0:
            item["status"] = "ACTIVE"
            item["suppression_reason"] = None
    touch(item)

    return created(serialize.snapshot(row))


@bp.get("/dropship/items/<item_id>/inventory-snapshots")
def list_snapshots(item_id):
    authenticate(("PlatformAdmin", "VendorOpsAnalyst", "MerchandiseManager", "VendorUser"))
    get_item(item_id)

    status = v.filter_enum(request.args, "status", ("ACTIVE", "SUPERSEDED"))
    source = v.filter_enum(request.args, "source", SNAPSHOT_SOURCES)
    limit, offset = pagination(request.args)

    rows = [s for s in db.snapshots.values() if s["item_id"] == item_id]
    if status is not None:
        rows = [s for s in rows if s["status"] == status]
    if source is not None:
        rows = [s for s in rows if s["source"] == source]

    rows = sorted(rows, key=lambda s: (s["created_at"], s["_seq"]))
    page, total = paginate(rows, limit, offset)
    return listing([serialize.snapshot(s) for s in page], limit, offset, total)
