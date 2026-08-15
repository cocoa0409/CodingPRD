"""Routes: shops, logical clock, clients, design packages, takeoffs, takeoff lines, bids."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB, CLOCK, ALL_ROLES, ApiError, iso, rhu_cents,
    auth, need_role, not_own, body, check_unknown, req, opt_int, opt_str,
    as_int, as_str, as_bool, as_enum, parse_dt, verr, not_found, invalid_state,
    mint, touch, ok, list_response, get_or_404,
    recompute_capacity, recompute_inventory, recompute_client,
    recompute_takeoff_subtotal, stock_refresh,
    price_bid_detailed, price_bid_rom, now,
)

bp = Blueprint("commercial", __name__)


# ---------------------------------------------------------------------------
# Shops
# ---------------------------------------------------------------------------
@bp.post("/scenic/shops")
def create_shop():
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    data = body()
    allowed = {"name", "weekly_crew_hours_capacity", "horizon_weeks", "bay_count",
               "truck_fleet_size", "labor_rate_cents_per_hour", "overtime_multiplier_bp",
               "overhead_pct_bp", "margin_pct_bp"}
    check_unknown(data, allowed)
    name = as_str(req(data, "name"), "name")
    weekly = as_int(req(data, "weekly_crew_hours_capacity"), "weekly_crew_hours_capacity")
    horizon = as_int(req(data, "horizon_weeks"), "horizon_weeks")
    bays = as_int(req(data, "bay_count"), "bay_count")
    fleet = as_int(req(data, "truck_fleet_size"), "truck_fleet_size")
    rate = as_int(req(data, "labor_rate_cents_per_hour"), "labor_rate_cents_per_hour")
    ot_mult = as_int(req(data, "overtime_multiplier_bp"), "overtime_multiplier_bp")
    overhead = as_int(req(data, "overhead_pct_bp"), "overhead_pct_bp")
    margin = as_int(req(data, "margin_pct_bp"), "margin_pct_bp")
    if weekly <= 0:
        raise verr("weekly_crew_hours_capacity must be > 0")
    if horizon <= 0:
        raise verr("horizon_weeks must be > 0")
    if bays <= 0:
        raise verr("bay_count must be > 0")
    if fleet <= 0:
        raise verr("truck_fleet_size must be > 0")
    if rate <= 0:
        raise verr("labor_rate_cents_per_hour must be > 0")
    if ot_mult < 10000:
        raise verr("overtime_multiplier_bp must be >= 10000")
    if overhead < 0:
        raise verr("overhead_pct_bp must be >= 0")
    if margin < 0:
        raise verr("margin_pct_bp must be >= 0")
    shop = mint()
    shop.update({
        "name": name,
        "weekly_crew_hours_capacity": weekly,
        "horizon_weeks": horizon,
        "bay_count": bays,
        "truck_fleet_size": fleet,
        "labor_rate_cents_per_hour": rate,
        "overtime_multiplier_bp": ot_mult,
        "overhead_pct_bp": overhead,
        "margin_pct_bp": margin,
        "committed_crew_hours": 0,
        "capacity_ratio_bp": 0,
        "posture": "OPEN",
        "inventory_value_cents": 0,
        "epoch_index": 0,
    })
    DB["shops"][shop["id"]] = shop
    return ok(shop, 201)


@bp.get("/scenic/shops/<shopId>")
def get_shop(shopId):
    auth()
    return ok(get_or_404("shops", shopId))


@bp.get("/scenic/shops/<shopId>/summary")
def shop_summary(shopId):
    auth()
    shop = get_or_404("shops", shopId)
    active = sum(
        1 for p in DB["productions"].values()
        if p["shop_id"] == shop["id"] and p["status"] in ("SCHEDULED", "IN_BUILD", "ON_HOLD")
    )
    return ok({
        "posture": shop["posture"],
        "committed_crew_hours": shop["committed_crew_hours"],
        "capacity_crew_hours_horizon": shop["weekly_crew_hours_capacity"] * shop["horizon_weeks"],
        "capacity_ratio_bp": shop["capacity_ratio_bp"],
        "active_productions": active,
        "inventory_value_cents": shop["inventory_value_cents"],
        "epoch_index": shop["epoch_index"],
    })


@bp.post("/scenic/shops/<shopId>/run-epoch")
def run_epoch(shopId):
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    shop = get_or_404("shops", shopId)
    shop["epoch_index"] += 1
    touch(shop)
    shop_client_ids = {c["id"] for c in DB["clients"].values() if c["shop_id"] == shop["id"]}
    for bid in DB["bids"].values():
        if (bid["client_id"] in shop_client_ids and bid["status"] == "SUBMITTED"
                and bid["valid_until"] is not None and now() > bid["valid_until"]):
            bid["status"] = "EXPIRED"
            touch(bid)
    recompute_capacity(shop)
    return ok(shop)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/scenic/_clock/set-current-utc")
def set_clock():
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    data = body()
    check_unknown(data, {"to_iso8601"})
    CLOCK["now"] = parse_dt(req(data, "to_iso8601"), "to_iso8601")
    return ok({"current_utc": iso(CLOCK["now"])})


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@bp.post("/scenic/clients")
def create_client():
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    data = body()
    check_unknown(data, {"shop_id", "company_name", "contact_email", "credit_limit_cents"})
    shop_id = as_str(req(data, "shop_id"), "shop_id")
    company = as_str(req(data, "company_name"), "company_name")
    email = as_str(req(data, "contact_email"), "contact_email")
    credit = as_int(req(data, "credit_limit_cents"), "credit_limit_cents")
    get_or_404("shops", shop_id)
    if credit < 0:
        raise verr("credit_limit_cents must be >= 0")
    client = mint()
    client.update({
        "shop_id": shop_id,
        "company_name": company,
        "contact_email": email,
        "credit_limit_cents": credit,
        "outstanding_cents": 0,
    })
    DB["clients"][client["id"]] = client
    return ok(client, 201)


@bp.get("/scenic/clients")
def list_clients():
    auth()
    items = list(DB["clients"].values())
    shop_id = request.args.get("shop_id")
    if shop_id is not None:
        items = [c for c in items if c["shop_id"] == shop_id]
    return list_response(items)


@bp.get("/scenic/clients/<clientId>")
def get_client(clientId):
    auth()
    return ok(get_or_404("clients", clientId))


# ---------------------------------------------------------------------------
# Design packages
# ---------------------------------------------------------------------------
@bp.post("/scenic/design-packages")
def create_design_package():
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    data = body()
    check_unknown(data, {"client_id", "show_title", "venue", "load_in_at", "strike_at"})
    client_id = as_str(req(data, "client_id"), "client_id")
    show_title = as_str(req(data, "show_title"), "show_title")
    venue = as_str(req(data, "venue"), "venue")
    load_in_at = parse_dt(req(data, "load_in_at"), "load_in_at")
    strike_at = parse_dt(req(data, "strike_at"), "strike_at")
    # Ownership (tier 2): ClientPM's X-User-ID is the acting Client's id
    if auth_uid != client_id:
        raise not_own("ClientPM may only upload packages for their own client")
    client = get_or_404("clients", client_id)
    if not strike_at > load_in_at:
        raise verr("strike_at must be strictly later than load_in_at")
    priors = [p for p in DB["design_packages"].values()
              if p["client_id"] == client_id and p["show_title"] == show_title]
    revision = max([p["drawing_revision"] for p in priors], default=0) + 1
    for p in priors:
        if p["status"] == "CURRENT":
            p["status"] = "SUPERSEDED"
            touch(p)
    pkg = mint()
    pkg.update({
        "client_id": client_id,
        "show_title": show_title,
        "venue": venue,
        "load_in_at": load_in_at,
        "strike_at": strike_at,
        "drawing_revision": revision,
        "status": "CURRENT",
    })
    DB["design_packages"][pkg["id"]] = pkg
    return ok(pkg, 201)


@bp.get("/scenic/design-packages")
def list_design_packages():
    auth()
    items = list(DB["design_packages"].values())
    client_id = request.args.get("client_id")
    if client_id is not None:
        items = [p for p in items if p["client_id"] == client_id]
    show_title = request.args.get("show_title")
    if show_title is not None:
        items = [p for p in items if p["show_title"] == show_title]
    status = request.args.get("status")
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return list_response(items)


@bp.get("/scenic/design-packages/<packageId>")
def get_design_package(packageId):
    auth()
    return ok(get_or_404("design_packages", packageId))


# ---------------------------------------------------------------------------
# Takeoffs
# ---------------------------------------------------------------------------
@bp.post("/scenic/takeoffs")
def create_takeoff():
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    data = body()
    check_unknown(data, {"design_package_id", "labor_hours_est", "notes"})
    pkg_id = as_str(req(data, "design_package_id"), "design_package_id")
    labor = as_int(req(data, "labor_hours_est"), "labor_hours_est")
    notes = opt_str(data, "notes")
    pkg = get_or_404("design_packages", pkg_id)
    if labor <= 0:
        raise verr("labor_hours_est must be > 0")
    takeoff = mint()
    takeoff.update({
        "design_package_id": pkg_id,
        "estimator_user_id": auth_uid,
        "labor_hours_est": labor,
        "pinned_package_revision": pkg["drawing_revision"],
        "materials_subtotal_cents": 0,
        "status": "DRAFT",
        "notes": notes,
    })
    DB["takeoffs"][takeoff["id"]] = takeoff
    return ok(takeoff, 201)


@bp.get("/scenic/takeoffs")
def list_takeoffs():
    auth()
    items = list(DB["takeoffs"].values())
    pkg_id = request.args.get("design_package_id")
    if pkg_id is not None:
        items = [t for t in items if t["design_package_id"] == pkg_id]
    status = request.args.get("status")
    if status is not None:
        items = [t for t in items if t["status"] == status]
    return list_response(items)


@bp.get("/scenic/takeoffs/<takeoffId>")
def get_takeoff(takeoffId):
    auth()
    return ok(get_or_404("takeoffs", takeoffId))


# ---------------------------------------------------------------------------
# Takeoff lines
# ---------------------------------------------------------------------------
@bp.post("/scenic/takeoff-lines")
def create_takeoff_line():
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    data = body()
    allowed = {"takeoff_id", "expected_takeoff_version", "material_code", "quantity",
               "source", "unit_cost_cents", "stock_item_id", "waste_pct_bp"}
    check_unknown(data, allowed)
    takeoff_id = as_str(req(data, "takeoff_id"), "takeoff_id")
    expected_version = as_int(req(data, "expected_takeoff_version"), "expected_takeoff_version")
    material_code = as_str(req(data, "material_code"), "material_code")
    quantity = as_int(req(data, "quantity"), "quantity")
    source = as_enum(req(data, "source"), "source", {"PURCHASE", "STOCK"})
    unit_cost = opt_int(data, "unit_cost_cents")
    stock_item_id = opt_str(data, "stock_item_id")
    waste = as_int(data["waste_pct_bp"], "waste_pct_bp") if "waste_pct_bp" in data else 0
    # Existence (tier 3)
    takeoff = get_or_404("takeoffs", takeoff_id)
    item = None
    if stock_item_id is not None:
        item = get_or_404("stock_items", stock_item_id)
    # State (tier 4): takeoff must be DRAFT
    if takeoff["status"] != "DRAFT":
        raise ApiError("ERR_TAKEOFF_LOCKED", 409, "Takeoff is LOCKED; lines cannot be modified")
    # Structural rules (tier 7)
    if quantity <= 0:
        raise verr("quantity must be > 0")
    if waste < 0:
        raise verr("waste_pct_bp must be >= 0")
    if source == "PURCHASE":
        if unit_cost is None:
            raise verr("unit_cost_cents is required when source is PURCHASE")
        if stock_item_id is not None:
            raise verr("stock_item_id must be absent when source is PURCHASE")
    else:  # STOCK
        if stock_item_id is None:
            raise verr("stock_item_id is required when source is STOCK")
        if quantity > item["quantity_on_hand"]:
            raise ApiError("ERR_STOCK_INSUFFICIENT", 409,
                           "Requested quantity exceeds stock on hand")
    # OCC (tier 12)
    if expected_version != takeoff["version"]:
        raise ApiError("ERR_STALE_TAKEOFF_VERSION", 412,
                       "expected_takeoff_version does not match the takeoff's current version")
    if source == "PURCHASE":
        applied = unit_cost
    else:
        applied = item["reuse_unit_cost_cents"]
    line_total = rhu_cents(Decimal(quantity) * applied * (10000 + waste) / 10000)
    line = mint()
    line.update({
        "takeoff_id": takeoff_id,
        "material_code": material_code,
        "quantity": quantity,
        "source": source,
        "unit_cost_cents": unit_cost if source == "PURCHASE" else None,
        "stock_item_id": stock_item_id if source == "STOCK" else None,
        "waste_pct_bp": waste,
        "applied_unit_cost_cents": applied,
        "line_total_cents": line_total,
    })
    DB["takeoff_lines"][line["id"]] = line
    if source == "STOCK":
        item["quantity_on_hand"] -= quantity
        stock_refresh(item)
        touch(item)
        recompute_inventory(DB["shops"][item["shop_id"]])
    recompute_takeoff_subtotal(takeoff)
    touch(takeoff)
    return ok(line, 201)


@bp.get("/scenic/takeoff-lines")
def list_takeoff_lines():
    auth()
    items = list(DB["takeoff_lines"].values())
    takeoff_id = request.args.get("takeoff_id")
    if takeoff_id is not None:
        items = [l for l in items if l["takeoff_id"] == takeoff_id]
    stock_item_id = request.args.get("stock_item_id")
    if stock_item_id is not None:
        items = [l for l in items if l["stock_item_id"] == stock_item_id]
    return list_response(items)


@bp.get("/scenic/takeoff-lines/<lineId>")
def get_takeoff_line(lineId):
    auth()
    return ok(get_or_404("takeoff_lines", lineId))


@bp.delete("/scenic/takeoff-lines/<lineId>")
def delete_takeoff_line(lineId):
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    line = get_or_404("takeoff_lines", lineId)
    takeoff = DB["takeoffs"][line["takeoff_id"]]
    if takeoff["status"] != "DRAFT":
        raise ApiError("ERR_TAKEOFF_LOCKED", 409, "Takeoff is LOCKED; lines cannot be modified")
    if line["source"] == "STOCK" and line["stock_item_id"] is not None:
        item = DB["stock_items"].get(line["stock_item_id"])
        if item is not None:
            item["quantity_on_hand"] += line["quantity"]
            stock_refresh(item)
            touch(item)
            recompute_inventory(DB["shops"][item["shop_id"]])
    del DB["takeoff_lines"][lineId]
    recompute_takeoff_subtotal(takeoff)
    touch(takeoff)
    return ok({}, 204)


# ---------------------------------------------------------------------------
# Bids
# ---------------------------------------------------------------------------
@bp.post("/scenic/bids")
def create_bid():
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    data = body()
    allowed = {"client_id", "design_package_id", "pricing_variant", "takeoff_id",
               "floor_area_sqft", "complexity_class", "has_automation_scope",
               "bays_required", "build_start_at", "estimated_crew_hours", "validity_days"}
    check_unknown(data, allowed)
    client_id = as_str(req(data, "client_id"), "client_id")
    pkg_id = as_str(req(data, "design_package_id"), "design_package_id")
    variant = as_enum(req(data, "pricing_variant"), "pricing_variant", {"DETAILED", "ROM"})
    has_automation = as_bool(req(data, "has_automation_scope"), "has_automation_scope")
    bays_required = as_int(req(data, "bays_required"), "bays_required")
    build_start_at = parse_dt(req(data, "build_start_at"), "build_start_at")
    validity_days = as_int(req(data, "validity_days"), "validity_days")
    takeoff_id = opt_str(data, "takeoff_id")
    floor_area = opt_int(data, "floor_area_sqft")
    complexity = opt_str(data, "complexity_class")
    est_hours = opt_int(data, "estimated_crew_hours")
    # Existence (tier 3), including takeoff<->package consistency
    client = get_or_404("clients", client_id)
    pkg = get_or_404("design_packages", pkg_id)
    takeoff = None
    if takeoff_id is not None:
        takeoff = get_or_404("takeoffs", takeoff_id)
        if takeoff["design_package_id"] != pkg_id:
            raise not_found("takeoff_id does not belong to the referenced design package")
    # Structural / conditional rules (tier 7)
    if bays_required <= 0:
        raise verr("bays_required must be > 0")
    if validity_days <= 0:
        raise verr("validity_days must be > 0")
    if not build_start_at < pkg["load_in_at"]:
        raise verr("build_start_at must be strictly earlier than the package load_in_at")
    if variant == "DETAILED":
        if takeoff is None:
            raise verr("takeoff_id is required when pricing_variant is DETAILED")
        if floor_area is not None or complexity is not None or est_hours is not None:
            raise verr("floor_area_sqft, complexity_class and estimated_crew_hours "
                       "must be absent when pricing_variant is DETAILED")
    else:  # ROM
        if takeoff_id is not None:
            raise verr("takeoff_id must be absent when pricing_variant is ROM")
        if floor_area is None or floor_area <= 0:
            raise verr("floor_area_sqft is required and must be > 0 when pricing_variant is ROM")
        if complexity not in ("A_SIMPLE", "B_STANDARD", "C_COMPLEX"):
            raise verr("complexity_class must be one of A_SIMPLE, B_STANDARD, C_COMPLEX")
        if est_hours is None or est_hours <= 0:
            raise verr("estimated_crew_hours is required and must be > 0 when pricing_variant is ROM")
    shop = DB["shops"][client["shop_id"]]
    if variant == "DETAILED":
        price = price_bid_detailed(shop, takeoff)
    else:
        price = price_bid_rom(pkg, floor_area, complexity)
    bid = mint()
    bid.update({
        "client_id": client_id,
        "design_package_id": pkg_id,
        "pricing_variant": variant,
        "takeoff_id": takeoff_id if variant == "DETAILED" else None,
        "floor_area_sqft": floor_area if variant == "ROM" else None,
        "complexity_class": complexity if variant == "ROM" else None,
        "has_automation_scope": has_automation,
        "bays_required": bays_required,
        "build_start_at": build_start_at,
        "estimated_crew_hours": est_hours if variant == "ROM" else None,
        "validity_days": validity_days,
        "pinned_drawing_revision": pkg["drawing_revision"],
        "price_cents": price,
        "valid_until": None,
        "round_no": 1,
        "production_id": None,
        "status": "DRAFT",
    })
    DB["bids"][bid["id"]] = bid
    return ok(bid, 201)


@bp.get("/scenic/bids")
def list_bids():
    auth()
    items = list(DB["bids"].values())
    for param in ("client_id", "design_package_id", "takeoff_id", "production_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [b for b in items if b.get(param) == value]
    return list_response(items)


@bp.get("/scenic/bids/<bidId>")
def get_bid(bidId):
    auth()
    return ok(get_or_404("bids", bidId))


def _bid_fresh_or_error(bid):
    pkg = DB["design_packages"][bid["design_package_id"]]
    if pkg["status"] != "CURRENT" or bid["pinned_drawing_revision"] != pkg["drawing_revision"]:
        raise ApiError("ERR_STALE_DRAWING_REVISION", 409,
                       "Design package has been superseded since the bid was pinned")


@bp.post("/scenic/bids/<bidId>/submit")
def submit_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    bid = get_or_404("bids", bidId)
    if bid["status"] != "DRAFT":
        raise invalid_state("Only a DRAFT bid can be submitted")
    _bid_fresh_or_error(bid)
    shop = DB["shops"][DB["clients"][bid["client_id"]]["shop_id"]]
    if shop["posture"] == "SATURATED":
        raise ApiError("ERR_SHOP_SATURATED", 409, "Shop is SATURATED; bids cannot be submitted")
    bid["valid_until"] = now() + timedelta(days=bid["validity_days"])
    bid["status"] = "SUBMITTED"
    touch(bid)
    if bid["pricing_variant"] == "DETAILED" and bid["takeoff_id"] is not None:
        takeoff = DB["takeoffs"][bid["takeoff_id"]]
        if takeoff["status"] == "DRAFT":
            takeoff["status"] = "LOCKED"
            touch(takeoff)
    return ok(bid)


@bp.post("/scenic/bids/<bidId>/counter")
def counter_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    bid = get_or_404("bids", bidId)
    if auth_uid != bid["client_id"]:
        raise not_own("ClientPM may only counter bids addressed to their own client")
    if bid["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED bid can be countered")
    data = body()
    check_unknown(data, {"counter_price_cents", "note"})
    as_int(req(data, "counter_price_cents"), "counter_price_cents")
    opt_str(data, "note")
    bid["status"] = "COUNTERED"
    touch(bid)
    return ok(bid)


@bp.post("/scenic/bids/<bidId>/revise")
def revise_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    bid = get_or_404("bids", bidId)
    if bid["status"] != "COUNTERED":
        raise invalid_state("Only a COUNTERED bid can be revised")
    data = body()
    check_unknown(data, {"revised_price_cents"})
    revised = as_int(req(data, "revised_price_cents"), "revised_price_cents")
    bid["price_cents"] = revised
    bid["round_no"] += 1
    bid["valid_until"] = now() + timedelta(days=bid["validity_days"])
    bid["status"] = "SUBMITTED"
    touch(bid)
    return ok(bid)


@bp.post("/scenic/bids/<bidId>/accept")
def accept_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    bid = get_or_404("bids", bidId)
    if auth_uid != bid["client_id"]:
        raise not_own("ClientPM may only accept bids addressed to their own client")
    if bid["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED bid can be accepted")
    _bid_fresh_or_error(bid)
    if now() > bid["valid_until"]:
        raise ApiError("ERR_BID_EXPIRED", 409, "Bid validity has elapsed")
    client = DB["clients"][bid["client_id"]]
    if client["outstanding_cents"] + bid["price_cents"] > client["credit_limit_cents"]:
        raise ApiError("ERR_CREDIT_LIMIT_EXCEEDED", 409,
                       "Acceptance would exceed the client's credit limit")
    shop = DB["shops"][client["shop_id"]]
    if shop["posture"] == "SATURATED":
        raise ApiError("ERR_SHOP_SATURATED", 409, "Shop is SATURATED; bids cannot be accepted")
    pkg = DB["design_packages"][bid["design_package_id"]]
    if bid["pricing_variant"] == "DETAILED":
        committed = DB["takeoffs"][bid["takeoff_id"]]["labor_hours_est"]
    else:
        committed = bid["estimated_crew_hours"]
    scopes = ["STRUCTURAL"] + (["AUTOMATION"] if bid["has_automation_scope"] else [])
    prod = mint()
    prod.update({
        "shop_id": client["shop_id"],
        "bid_id": bid["id"],
        "client_id": bid["client_id"],
        "show_title": pkg["show_title"],
        "build_start_at": bid["build_start_at"],
        "load_in_deadline_at": pkg["load_in_at"],
        "strike_at": pkg["strike_at"],
        "committed_crew_hours": committed,
        "bays_required": bid["bays_required"],
        "required_review_scopes": scopes,
        "applied_drawing_revision": bid["pinned_drawing_revision"],
        "current_price_cents": bid["price_cents"],
        "built_at": None,
        "status": "SCHEDULED",
    })
    DB["productions"][prod["id"]] = prod
    bid["production_id"] = prod["id"]
    bid["status"] = "ACCEPTED"
    touch(bid)
    recompute_capacity(shop)
    recompute_client(client)
    return ok(bid)


@bp.post("/scenic/bids/<bidId>/reject")
def reject_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    bid = get_or_404("bids", bidId)
    if auth_uid != bid["client_id"]:
        raise not_own("ClientPM may only reject bids addressed to their own client")
    if bid["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED bid can be rejected")
    bid["status"] = "REJECTED"
    touch(bid)
    return ok(bid)


@bp.post("/scenic/bids/<bidId>/withdraw")
def withdraw_bid(bidId):
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    bid = get_or_404("bids", bidId)
    if bid["status"] not in ("DRAFT", "SUBMITTED", "COUNTERED"):
        raise invalid_state("Bid cannot be withdrawn from its current state")
    bid["status"] = "WITHDRAWN"
    touch(bid)
    return ok(bid)
