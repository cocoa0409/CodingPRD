"""Routes: items, store zones, markdown runs."""
from decimal import Decimal

from flask import Blueprint, request

import db
from errors import ApiError, err_invalid_request
from response import success_obj, success_list
from services import (
    compute_list_price,
    serialize_item,
    serialize_zone,
    item_days_on_floor,
    zone_current_count,
    zone_restock_recommended,
)
from util import (
    authenticate,
    require_role,
    get_body,
    req_str,
    req_enum,
    req_int,
    req_num,
    req_bool,
    opt_fk,
    opt_int,
    opt_str,
    lookup,
    paginate,
    serialize,
    parse_bool_param,
    D,
    round_cents,
    dec1,
)

bp = Blueprint("store", __name__)

CONDITION_GRADES = {"A", "B", "C", "D"}
MEASURE_UNITS = {"UNIT", "SQFT", "LINEAR_FT"}
DISPOSITIONS = {"DONATE", "RECYCLE", "DISPOSE"}
DISPOSITION_TARGET = {
    "DONATE": "DONATED_OUT",
    "RECYCLE": "RECYCLED",
    "DISPOSE": "DISPOSED",
}

ITEM_ROLES = ["IntakeStaff", "StoreManager", "Cashier", "WarehouseAdmin", "Contractor"]
ZONE_ROLES = ["StoreManager", "IntakeStaff", "Cashier", "WarehouseAdmin"]


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------


@bp.post("/reuse/items")
def create_item():
    data = get_body()
    category_id = req_str(data, "category_id")
    description_text = req_str(data, "description_text")
    condition_grade = req_enum(data, "condition_grade", CONDITION_GRADES)
    measure_qty = req_num(data, "measure_qty", gt=0)
    measure_unit = req_enum(data, "measure_unit", MEASURE_UNITS)
    pre_1978_flag = req_bool(data, "pre_1978_flag")
    estimated_weight_lbs = req_num(data, "estimated_weight_lbs", ge=0)
    offer_id = opt_fk(data, "offer_id")
    batch_id = opt_fk(data, "batch_id")
    screening_id = opt_fk(data, "screening_id")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff"])
    # Body FK existence (priority 5)
    category = lookup(db.categories, "category", category_id)
    offer = None
    if offer_id is not None:
        offer = lookup(db.offers, "offer", offer_id)
    batch = None
    if batch_id is not None:
        batch = lookup(db.batches, "batch", batch_id)
    screening = None
    if screening_id is not None:
        screening = lookup(db.screenings, "screening", screening_id)
    # State (priority 7): batch must be WEIGHED or SORTED
    if batch is not None and batch["status"] not in ("WEIGHED", "SORTED"):
        raise ApiError(
            "ERR_INVALID_BATCH_STATE",
            409,
            "Item intake from a batch requires batch WEIGHED or SORTED",
        )
    # Safety (priority 8): hazmat exposure needs a CLEARED screening unless
    # batch-linked (batch items inherit the job screening)
    exposed = category["hazmat_risk_flag"] or pre_1978_flag
    if exposed and batch_id is None:
        if screening is None or screening["outcome"] != "CLEARED":
            raise ApiError(
                "ERR_HAZMAT_SCREENING_REQUIRED",
                422,
                "Hazmat-exposed item intake requires a screening with outcome CLEARED",
            )
    # Business constraints (priority 9): category must be accepting
    if category["acceptance_status"] != "ACCEPTING":
        raise ApiError(
            "ERR_CATEGORY_NOT_ACCEPTING", 409, "Category is not accepting material"
        )
    # Referential linkage (priority 12)
    if offer is not None:
        if offer["status"] != "RECEIVED":
            raise ApiError(
                "ERR_INVALID_OFFER_STATE",
                409,
                "Item intake from an offer requires offer RECEIVED",
            )
        if offer["category_id"] != category_id:
            raise ApiError(
                "ERR_CATEGORY_MISMATCH",
                422,
                "Item category differs from the linked offer's category",
            )
    if batch is not None and batch["category_id"] != category_id:
        raise ApiError(
            "ERR_CATEGORY_MISMATCH",
            422,
            "Item category differs from the linked batch's category",
        )
    item = {
        **db.base_fields(),
        "category_id": category_id,
        "batch_id": batch_id,
        "offer_id": offer_id,
        "screening_id": screening_id,
        "parent_item_id": None,
        "description_text": description_text,
        "condition_grade": condition_grade,
        "measure_qty": measure_qty,
        "measure_unit": measure_unit,
        "pre_1978_flag": pre_1978_flag,
        "estimated_weight_lbs": estimated_weight_lbs,
        "pricing_status": "UNPRICED",
        "sales_status": "BACKROOM",
        "list_price_cents": 0,
        "current_price_cents": 0,
        "markdown_step": 0,
        "price_override_cents": None,
        "priced_by_user_id": "",
        "zone_id": None,
        "floor_since": None,
        "disposition_recommended": "NONE",
        "sold_via_sale_id": None,
        "_disposed_at": None,
        "_reserved_zone_id": None,
    }
    db.items[item["id"]] = item
    return success_obj(serialize_item(item), 201)


@bp.get("/reuse/items")
def list_items():
    ctx = authenticate()
    require_role(ctx, ITEM_ROLES)
    records = list(db.items.values())
    for param in (
        "category_id",
        "batch_id",
        "offer_id",
        "zone_id",
        "sold_via_sale_id",
        "parent_item_id",
        "screening_id",
        "sales_status",
        "pricing_status",
    ):
        v = request.args.get(param)
        if v is not None:
            records = [i for i in records if i.get(param) == v]
    slow_only = parse_bool_param("slow_only")
    if slow_only:
        records = [
            i
            for i in records
            if item_days_on_floor(i)
            >= db.categories[i["category_id"]]["target_turn_days"]
        ]
    page, meta = paginate(records)
    return success_list([serialize_item(i) for i in page], meta)


@bp.get("/reuse/items/<itemId>")
def get_item(itemId):
    ctx = authenticate()
    require_role(ctx, ITEM_ROLES)
    return success_obj(serialize_item(lookup(db.items, "item", itemId)))


@bp.post("/reuse/items/<itemId>/price")
def price_item(itemId):
    data = get_body()
    price_override_cents = opt_int(data, "price_override_cents")
    ctx = authenticate()
    require_role(ctx, ["StoreManager"])
    item = lookup(db.items, "item", itemId)
    if item["pricing_status"] != "UNPRICED":
        raise ApiError("ERR_ITEM_NOT_UNPRICED", 409, "price requires UNPRICED")
    category = db.categories[item["category_id"]]
    override = (
        price_override_cents
        if (price_override_cents is not None and price_override_cents > 0)
        else None
    )
    list_price = compute_list_price(item, category, override)
    item["pricing_status"] = "PRICED"
    item["list_price_cents"] = list_price
    item["current_price_cents"] = list_price
    item["markdown_step"] = 0
    item["disposition_recommended"] = "NONE"
    item["price_override_cents"] = override
    item["priced_by_user_id"] = ctx.user_id
    db.touch(item)
    return success_obj(serialize_item(item))


@bp.post("/reuse/items/<itemId>/place")
def place_item(itemId):
    data = get_body()
    zone_id = req_str(data, "zone_id")
    ctx = authenticate()
    require_role(ctx, ["StoreManager"])
    item = lookup(db.items, "item", itemId)
    zone = lookup(db.zones, "zone", zone_id)
    if item["sales_status"] != "BACKROOM":
        raise ApiError("ERR_ITEM_NOT_BACKROOM", 409, "place requires BACKROOM")
    if item["pricing_status"] != "PRICED":
        raise ApiError("ERR_ITEM_NOT_PRICED", 409, "place requires PRICED")
    if zone["status"] != "OPEN":
        raise ApiError("ERR_ZONE_NOT_OPEN", 409, "Zone is not OPEN")
    if zone["allowed_category_id"] is not None and zone["allowed_category_id"] != item[
        "category_id"
    ]:
        raise ApiError(
            "ERR_ZONE_CATEGORY_MISMATCH",
            409,
            "Zone is restricted to a different category",
        )
    if zone_current_count(zone) >= zone["capacity"]:
        raise ApiError("ERR_ZONE_AT_CAPACITY", 409, "Zone is at capacity")
    item["sales_status"] = "ON_FLOOR"
    item["zone_id"] = zone["id"]
    item["floor_since"] = db.now()
    db.touch(item)
    db.touch(zone)  # occupancy changed; count/flag recompute on read
    return success_obj(serialize_item(item))


@bp.post("/reuse/items/<itemId>/unplace")
def unplace_item(itemId):
    get_body()
    ctx = authenticate()
    require_role(ctx, ["StoreManager"])
    item = lookup(db.items, "item", itemId)
    if item["sales_status"] != "ON_FLOOR":
        raise ApiError("ERR_ITEM_NOT_ON_FLOOR", 409, "unplace requires ON_FLOOR")
    zone = db.zones.get(item["zone_id"] or "")
    item["sales_status"] = "BACKROOM"
    item["zone_id"] = None
    item["floor_since"] = None
    db.touch(item)
    if zone is not None:
        db.touch(zone)
    return success_obj(serialize_item(item))


@bp.post("/reuse/items/<itemId>/dispose")
def dispose_item(itemId):
    data = get_body()
    disposition = req_enum(data, "disposition", DISPOSITIONS)
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    item = lookup(db.items, "item", itemId)
    if item["sales_status"] == "BACKROOM":
        pass
    elif item["sales_status"] == "ON_FLOOR":
        zone = db.zones.get(item["zone_id"] or "")
        item["zone_id"] = None
        item["floor_since"] = None
        if zone is not None:
            db.touch(zone)
    else:
        raise ApiError(
            "ERR_ITEM_NOT_BACKROOM",
            409,
            "dispose requires BACKROOM or ON_FLOOR",
        )
    item["sales_status"] = DISPOSITION_TARGET[disposition]
    item["_disposed_at"] = db.now()
    db.touch(item)
    return success_obj(serialize_item(item))


@bp.post("/reuse/items/<itemId>/split")
def split_item(itemId):
    data = get_body()
    split_qty = req_num(data, "split_qty")
    ctx = authenticate()
    require_role(ctx, ["IntakeStaff", "StoreManager"])
    item = lookup(db.items, "item", itemId)
    if item["sales_status"] != "BACKROOM":
        raise ApiError("ERR_ITEM_NOT_BACKROOM", 409, "split requires BACKROOM")
    if (
        item["measure_unit"] == "UNIT"
        or D(split_qty) <= 0
        or D(split_qty) >= D(item["measure_qty"])
    ):
        raise ApiError(
            "ERR_SPLIT_INVALID_QUANTITY",
            422,
            "split_qty must be > 0 and < measure_qty, and the item must not be UNIT-measured",
        )
    item["measure_qty"] = float(D(item["measure_qty"]) - D(split_qty))
    item["pricing_status"] = "UNPRICED"
    db.touch(item)
    child = {
        **db.base_fields(),
        "category_id": item["category_id"],
        "batch_id": item["batch_id"],
        "offer_id": item["offer_id"],
        "screening_id": item["screening_id"],
        "parent_item_id": item["id"],
        "description_text": item["description_text"],
        "condition_grade": item["condition_grade"],
        "measure_qty": float(D(split_qty)),
        "measure_unit": item["measure_unit"],
        "pre_1978_flag": item["pre_1978_flag"],
        "estimated_weight_lbs": item["estimated_weight_lbs"],
        "pricing_status": "UNPRICED",
        "sales_status": "BACKROOM",
        "list_price_cents": 0,
        "current_price_cents": 0,
        "markdown_step": 0,
        "price_override_cents": None,
        "priced_by_user_id": "",
        "zone_id": None,
        "floor_since": None,
        "disposition_recommended": "NONE",
        "sold_via_sale_id": None,
        "_disposed_at": None,
        "_reserved_zone_id": None,
    }
    db.items[child["id"]] = child
    return success_obj(serialize_item(child), 201)


# ---------------------------------------------------------------------------
# Store zones
# ---------------------------------------------------------------------------


@bp.post("/reuse/store-zones")
def create_zone():
    data = get_body()
    code = req_str(data, "code")
    display_name = req_str(data, "display_name")
    capacity = req_int(data, "capacity", min_value=1)
    allowed_category_id = opt_fk(data, "allowed_category_id")
    restock_threshold = opt_int(data, "restock_threshold", 0, min_value=0)
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    if allowed_category_id is not None:
        lookup(db.categories, "category", allowed_category_id)
    for z in db.zones.values():
        if z["code"] == code:
            raise ApiError("ERR_DUPLICATE_CODE", 409, "Zone code already exists")
    zone = {
        **db.base_fields(),
        "code": code,
        "display_name": display_name,
        "capacity": capacity,
        "current_count": 0,
        "allowed_category_id": allowed_category_id,
        "restock_threshold": restock_threshold,
        "restock_recommended": True,
        "status": "OPEN",
    }
    db.zones[zone["id"]] = zone
    return success_obj(serialize_zone(zone), 201)


@bp.get("/reuse/store-zones")
def list_zones():
    ctx = authenticate()
    require_role(ctx, ZONE_ROLES)
    records = list(db.zones.values())
    for param in ("status", "allowed_category_id"):
        v = request.args.get(param)
        if v is not None:
            records = [z for z in records if z.get(param) == v]
    page, meta = paginate(records)
    return success_list([serialize_zone(z) for z in page], meta)


@bp.get("/reuse/store-zones/<zoneId>")
def get_zone(zoneId):
    ctx = authenticate()
    require_role(ctx, ZONE_ROLES)
    return success_obj(serialize_zone(lookup(db.zones, "zone", zoneId)))


@bp.patch("/reuse/store-zones/<zoneId>")
def patch_zone(zoneId):
    data = get_body()
    new_status = opt_str(data, "status")
    if new_status is not None and new_status not in ("OPEN", "CLOSED"):
        raise err_invalid_request("status must be OPEN or CLOSED")
    capacity = opt_int(data, "capacity", min_value=1)
    restock_threshold = opt_int(data, "restock_threshold", min_value=0)
    allowed_category_id = opt_fk(data, "allowed_category_id")
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    zone = lookup(db.zones, "zone", zoneId)
    if allowed_category_id is not None:
        lookup(db.categories, "category", allowed_category_id)
    if capacity is not None and capacity < zone_current_count(zone):
        raise ApiError(
            "ERR_CAPACITY_BELOW_OCCUPANCY",
            409,
            "capacity may not be below current occupancy",
        )
    if new_status is not None:
        zone["status"] = new_status
    if capacity is not None:
        zone["capacity"] = capacity
    if restock_threshold is not None:
        zone["restock_threshold"] = restock_threshold
    if "allowed_category_id" in data:
        zone["allowed_category_id"] = allowed_category_id
    db.touch(zone)
    return success_obj(serialize_zone(zone))


# ---------------------------------------------------------------------------
# Markdown runs
# ---------------------------------------------------------------------------


@bp.post("/reuse/markdown-runs")
def create_markdown_run():
    data = get_body()
    notes = opt_str(data, "notes", "")
    ctx = authenticate()
    require_role(ctx, ["StoreManager"])
    now = db.now()
    candidates = [
        i
        for i in db.items.values()
        if i["pricing_status"] == "PRICED" and i["sales_status"] == "ON_FLOOR"
    ]
    # Ascending floor_since, ties broken by created_at (insertion order)
    candidates.sort(key=lambda i: (i["floor_since"] or i["created_at"], i["created_at"]))
    items_evaluated = len(candidates)
    items_marked_down = 0
    items_flagged = 0
    for item in candidates:
        if item["disposition_recommended"] != "NONE":
            continue
        category = db.categories[item["category_id"]]
        threshold = (
            category["markdown_after_days"]
            + item["markdown_step"] * category["markdown_interval_days"]
        )
        if item_days_on_floor(item) < threshold:
            continue  # inclusive >=: exactly on the boundary day IS eligible
        if item["markdown_step"] < category["max_markdown_steps"]:
            item["markdown_step"] += 1
            step_price = round_cents(
                D(item["list_price_cents"])
                * (Decimal("1") - D(category["markdown_step_pct"]))
                ** item["markdown_step"]
            )
            floor_price = round_cents(
                D(item["list_price_cents"]) * D(category["floor_price_pct"])
            )
            item["current_price_cents"] = max(floor_price, step_price)
            items_marked_down += 1
        else:
            item["disposition_recommended"] = category["slow_item_disposition"]
            items_flagged += 1
        db.touch(item)
    run = {
        **db.lean_fields(),
        "as_of_date": now.strftime("%Y-%m-%d"),
        "items_evaluated": items_evaluated,
        "items_marked_down": items_marked_down,
        "items_flagged_disposition": items_flagged,
        "notes": notes,
    }
    db.markdown_runs[run["id"]] = run
    return success_obj(serialize(run), 201)


@bp.get("/reuse/markdown-runs")
def list_markdown_runs():
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    records = list(db.markdown_runs.values())
    page, meta = paginate(records)
    return success_list([serialize(r) for r in page], meta)


@bp.get("/reuse/markdown-runs/<runId>")
def get_markdown_run(runId):
    ctx = authenticate()
    require_role(ctx, ["StoreManager", "WarehouseAdmin"])
    return success_obj(serialize(lookup(db.markdown_runs, "run", runId)))
