"""Routes: productions, engineering reviews, finish samples, change orders,
bay reservations, stock items, transport plans."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request

from core import (
    DB, SF_STATIC_MIN, SF_DYNAMIC_MIN, ApiError,
    auth, need_role, not_own, body, check_unknown, req, opt_int, opt_str,
    as_int, as_str, as_enum, as_load, parse_dt, verr, invalid_state,
    mint, touch, ok, list_response, get_or_404,
    recompute_capacity, recompute_inventory, recompute_client, stock_refresh,
    compute_sf, price_change_order, current_package_for, find_stock_item,
    overlaps, now,
)

bp = Blueprint("production", __name__)


# ---------------------------------------------------------------------------
# Productions
# ---------------------------------------------------------------------------
@bp.get("/scenic/productions")
def list_productions():
    auth()
    items = list(DB["productions"].values())
    for param in ("shop_id", "client_id", "bid_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    return list_response(items)


@bp.get("/scenic/productions/<productionId>")
def get_production(productionId):
    auth()
    return ok(get_or_404("productions", productionId))


@bp.post("/scenic/productions/<productionId>/start-build")
def start_build(productionId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    prod = get_or_404("productions", productionId)
    if prod["status"] != "SCHEDULED":
        raise invalid_state("Only a SCHEDULED production can start build")
    reviews = [r for r in DB["engineering_reviews"].values()
               if r["production_id"] == prod["id"]]
    for scope in prod["required_review_scopes"]:
        if not any(r["scope"] == scope and r["status"] == "APPROVED" for r in reviews):
            raise ApiError("ERR_ENGINEERING_NOT_APPROVED", 409,
                           f"No APPROVED engineering review for required scope {scope}")
    reserved = sum(1 for r in DB["bay_reservations"].values()
                   if r["production_id"] == prod["id"] and r["status"] == "ACTIVE")
    if reserved < prod["bays_required"]:
        raise ApiError("ERR_BAY_UNDER_RESERVED", 409,
                       "Active bay reservations do not cover bays_required")
    prod["status"] = "IN_BUILD"
    touch(prod)
    return ok(prod)


@bp.post("/scenic/productions/<productionId>/complete-build")
def complete_build(productionId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    prod = get_or_404("productions", productionId)
    if prod["status"] != "IN_BUILD":
        raise invalid_state("Only an IN_BUILD production can complete build")
    reviews = [r for r in DB["engineering_reviews"].values()
               if r["production_id"] == prod["id"]]
    if any(r["status"] in ("PENDING", "REVISION_REQUIRED") for r in reviews):
        raise ApiError("ERR_ENGINEERING_NOT_APPROVED", 409,
                       "Engineering reviews are still open")
    samples = [s for s in DB["finish_samples"].values()
               if s["production_id"] == prod["id"]]
    if any(s["status"] != "APPROVED" for s in samples):
        raise ApiError("ERR_FINISH_NOT_APPROVED", 409,
                       "Every finish sample must be APPROVED before completing the build")
    if prod["load_in_deadline_at"] - now() < timedelta(days=2):
        raise ApiError("ERR_LOAD_IN_TOO_SOON", 409,
                       "Load-in deadline is less than two days away")
    prod["status"] = "BUILT"
    prod["built_at"] = now()
    touch(prod)
    recompute_capacity(DB["shops"][prod["shop_id"]])
    return ok(prod)


@bp.post("/scenic/productions/<productionId>/load-in")
def load_in(productionId):
    auth_uid, role = auth()
    need_role(role, {"TransportCoordinator"})
    prod = get_or_404("productions", productionId)
    if prod["status"] != "BUILT":
        raise invalid_state("Only a BUILT production can load in")
    plans = [p for p in DB["transport_plans"].values() if p["production_id"] == prod["id"]]
    if not any(p["status"] == "CONFIRMED" for p in plans):
        raise ApiError("ERR_TRANSPORT_NOT_CONFIRMED", 409,
                       "No CONFIRMED transport plan exists for this production")
    prod["status"] = "LOADED_IN"
    touch(prod)
    for plan in plans:
        if plan["status"] == "CONFIRMED":
            plan["status"] = "EXECUTED"
            touch(plan)
    return ok(prod)


@bp.post("/scenic/productions/<productionId>/strike")
def strike(productionId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    prod = get_or_404("productions", productionId)
    if prod["status"] != "LOADED_IN":
        raise invalid_state("Only a LOADED_IN production can be struck")
    data = body()
    check_unknown(data, {"reclaim_lines"})
    lines = req(data, "reclaim_lines")
    if not isinstance(lines, list):
        raise verr("reclaim_lines must be an array")
    parsed = []
    for ln in lines:
        if not isinstance(ln, dict):
            raise verr("each reclaim line must be an object")
        check_unknown(ln, {"material_code", "quantity", "condition_grade",
                           "replacement_cost_cents"})
        mc = as_str(req(ln, "material_code"), "material_code")
        qty = as_int(req(ln, "quantity"), "quantity")
        grade = as_enum(req(ln, "condition_grade"), "condition_grade", {"A", "B", "C"})
        rc = as_int(req(ln, "replacement_cost_cents"), "replacement_cost_cents")
        if qty <= 0:
            raise verr("reclaim line quantity must be > 0")
        if rc <= 0:
            raise verr("reclaim line replacement_cost_cents must be > 0")
        parsed.append((mc, qty, grade, rc))
    shop = DB["shops"][prod["shop_id"]]
    for mc, qty, grade, rc in parsed:
        item = find_stock_item(shop["id"], mc, grade)
        if item is None:
            item = mint()
            item.update({
                "shop_id": shop["id"],
                "material_code": mc,
                "condition_grade": grade,
                "quantity_on_hand": 0,
                "origin": "RECLAIMED",
                "replacement_cost_cents": rc,
            })
            stock_refresh(item)
            DB["stock_items"][item["id"]] = item
        item["quantity_on_hand"] += qty
        stock_refresh(item)
        touch(item)
    recompute_inventory(shop)
    prod["status"] = "STRUCK"
    touch(prod)
    return ok(prod)


@bp.post("/scenic/productions/<productionId>/close")
def close_production(productionId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    prod = get_or_404("productions", productionId)
    if prod["status"] != "STRUCK":
        raise invalid_state("Only a STRUCK production can be closed")
    if any(co["production_id"] == prod["id"] and co["status"] == "PROPOSED"
           for co in DB["change_orders"].values()):
        raise ApiError("ERR_CHANGE_ORDERS_PENDING", 409,
                       "Production still has PROPOSED change orders")
    if any(r["production_id"] == prod["id"] and r["status"] == "ACTIVE"
           for r in DB["bay_reservations"].values()):
        raise ApiError("ERR_RESERVATIONS_OPEN", 409,
                       "Production still has ACTIVE bay reservations")
    prod["status"] = "CLOSED"
    touch(prod)
    recompute_capacity(DB["shops"][prod["shop_id"]])
    recompute_client(DB["clients"][prod["client_id"]])
    return ok(prod)


# ---------------------------------------------------------------------------
# Engineering reviews
# ---------------------------------------------------------------------------
def _review_loads(data, scope):
    load = as_load(req(data, "design_load_lb"), "design_load_lb")
    capacity = as_load(req(data, "member_capacity_lb"), "member_capacity_lb")
    impact = opt_int(data, "impact_factor_bp")
    if scope == "AUTOMATION":
        if impact is None:
            raise verr("impact_factor_bp is required when scope is AUTOMATION")
        if impact < 10000:
            raise verr("impact_factor_bp must be >= 10000")
    else:
        if impact is not None:
            raise verr("impact_factor_bp must be absent when scope is STRUCTURAL")
    return load, capacity, impact


@bp.post("/scenic/engineering-reviews")
def create_review():
    auth_uid, role = auth()
    need_role(role, {"ShopForeman", "StaffEngineer"})
    data = body()
    check_unknown(data, {"production_id", "scope", "design_load_lb",
                         "member_capacity_lb", "impact_factor_bp"})
    prod_id = as_str(req(data, "production_id"), "production_id")
    scope = as_enum(req(data, "scope"), "scope", {"STRUCTURAL", "AUTOMATION"})
    prod = get_or_404("productions", prod_id)
    if prod["status"] in ("STRUCK", "CLOSED"):
        raise invalid_state("Reviews cannot be created for a STRUCK or CLOSED production")
    load, capacity, impact = _review_loads(data, scope)
    sf_static, sf_dynamic = compute_sf(scope, load, capacity, impact)
    review = mint()
    review.update({
        "production_id": prod_id,
        "scope": scope,
        "design_load_lb": load,
        "member_capacity_lb": capacity,
        "prepared_by_user_id": auth_uid,
        "sf_static": sf_static,
        "round_no": 1,
        "revision_note": None,
        "status": "PENDING",
    })
    if scope == "AUTOMATION":
        review["impact_factor_bp"] = impact
        review["sf_dynamic"] = sf_dynamic
    DB["engineering_reviews"][review["id"]] = review
    return ok(review, 201)


@bp.get("/scenic/engineering-reviews")
def list_reviews():
    auth()
    items = list(DB["engineering_reviews"].values())
    for param in ("production_id", "scope", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r.get(param) == value]
    return list_response(items)


@bp.get("/scenic/engineering-reviews/<reviewId>")
def get_review(reviewId):
    auth()
    return ok(get_or_404("engineering_reviews", reviewId))


@bp.post("/scenic/engineering-reviews/<reviewId>/approve")
def approve_review(reviewId):
    auth_uid, role = auth()
    need_role(role, {"StaffEngineer"})
    review = get_or_404("engineering_reviews", reviewId)
    if review["status"] != "PENDING":
        raise invalid_state("Only a PENDING review can be approved")
    if auth_uid == review["prepared_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                       "The approver must differ from the preparer")
    if review["sf_static"] < SF_STATIC_MIN:
        raise ApiError("ERR_SAFETY_FACTOR_INSUFFICIENT", 422,
                       "sf_static is below 1.50")
    if review["scope"] == "AUTOMATION" and review["sf_dynamic"] < SF_DYNAMIC_MIN:
        raise ApiError("ERR_SAFETY_FACTOR_INSUFFICIENT", 422,
                       "sf_dynamic is below 2.00")
    review["status"] = "APPROVED"
    touch(review)
    prod = DB["productions"][review["production_id"]]
    if prod["status"] == "ON_HOLD":
        others = [r for r in DB["engineering_reviews"].values()
                  if r["production_id"] == prod["id"]]
        if all(r["status"] == "APPROVED" for r in others):
            prod["status"] = "IN_BUILD"
            touch(prod)
    return ok(review)


@bp.post("/scenic/engineering-reviews/<reviewId>/request-revision")
def request_revision(reviewId):
    auth_uid, role = auth()
    need_role(role, {"StaffEngineer"})
    review = get_or_404("engineering_reviews", reviewId)
    if review["status"] != "PENDING":
        raise invalid_state("Only a PENDING review can be sent back for revision")
    data = body()
    check_unknown(data, {"revision_note"})
    note = as_str(req(data, "revision_note"), "revision_note")
    review["status"] = "REVISION_REQUIRED"
    review["revision_note"] = note
    touch(review)
    prod = DB["productions"][review["production_id"]]
    if prod["status"] == "IN_BUILD":
        prod["status"] = "ON_HOLD"
        touch(prod)
    return ok(review)


@bp.post("/scenic/engineering-reviews/<reviewId>/resubmit")
def resubmit_review(reviewId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman", "StaffEngineer"})
    review = get_or_404("engineering_reviews", reviewId)
    if auth_uid != review["prepared_by_user_id"]:
        raise not_own("Only the preparer may resubmit this review")
    if review["status"] != "REVISION_REQUIRED":
        raise invalid_state("Only a REVISION_REQUIRED review can be resubmitted")
    data = body()
    check_unknown(data, {"design_load_lb", "member_capacity_lb", "impact_factor_bp"})
    load, capacity, impact = _review_loads(data, review["scope"])
    sf_static, sf_dynamic = compute_sf(review["scope"], load, capacity, impact)
    review["design_load_lb"] = load
    review["member_capacity_lb"] = capacity
    if review["scope"] == "AUTOMATION":
        review["impact_factor_bp"] = impact
        review["sf_dynamic"] = sf_dynamic
    review["sf_static"] = sf_static
    review["round_no"] += 1
    review["status"] = "PENDING"
    touch(review)
    return ok(review)


# ---------------------------------------------------------------------------
# Finish samples
# ---------------------------------------------------------------------------
@bp.post("/scenic/finish-samples")
def create_sample():
    auth_uid, role = auth()
    need_role(role, {"PaintCharge"})
    data = body()
    check_unknown(data, {"production_id", "finish_code", "texture_ref"})
    prod_id = as_str(req(data, "production_id"), "production_id")
    finish_code = as_str(req(data, "finish_code"), "finish_code")
    texture_ref = as_str(req(data, "texture_ref"), "texture_ref")
    prod = get_or_404("productions", prod_id)
    if prod["status"] in ("STRUCK", "CLOSED"):
        raise invalid_state("Samples cannot be created for a STRUCK or CLOSED production")
    sample = mint()
    sample.update({
        "production_id": prod_id,
        "finish_code": finish_code,
        "texture_ref": texture_ref,
        "round_no": 1,
        "rejection_note": None,
        "status": "SUBMITTED",
    })
    DB["finish_samples"][sample["id"]] = sample
    return ok(sample, 201)


@bp.get("/scenic/finish-samples")
def list_samples():
    auth()
    items = list(DB["finish_samples"].values())
    for param in ("production_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [s for s in items if s.get(param) == value]
    return list_response(items)


@bp.get("/scenic/finish-samples/<sampleId>")
def get_sample(sampleId):
    auth()
    return ok(get_or_404("finish_samples", sampleId))


@bp.post("/scenic/finish-samples/<sampleId>/approve")
def approve_sample(sampleId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    sample = get_or_404("finish_samples", sampleId)
    prod = DB["productions"][sample["production_id"]]
    if auth_uid != prod["client_id"]:
        raise not_own("ClientPM may only decide samples of their own client's production")
    if sample["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED sample can be approved")
    sample["status"] = "APPROVED"
    touch(sample)
    return ok(sample)


@bp.post("/scenic/finish-samples/<sampleId>/reject")
def reject_sample(sampleId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    sample = get_or_404("finish_samples", sampleId)
    prod = DB["productions"][sample["production_id"]]
    if auth_uid != prod["client_id"]:
        raise not_own("ClientPM may only decide samples of their own client's production")
    if sample["status"] != "SUBMITTED":
        raise invalid_state("Only a SUBMITTED sample can be rejected")
    data = body()
    check_unknown(data, {"rejection_note"})
    note = as_str(req(data, "rejection_note"), "rejection_note")
    sample["status"] = "REJECTED"
    sample["rejection_note"] = note
    touch(sample)
    return ok(sample)


@bp.post("/scenic/finish-samples/<sampleId>/resubmit")
def resubmit_sample(sampleId):
    auth_uid, role = auth()
    need_role(role, {"PaintCharge"})
    sample = get_or_404("finish_samples", sampleId)
    if sample["status"] != "REJECTED":
        raise invalid_state("Only a REJECTED sample can be resubmitted")
    data = body()
    check_unknown(data, {"texture_ref"})
    texture_ref = as_str(req(data, "texture_ref"), "texture_ref")
    sample["texture_ref"] = texture_ref
    sample["round_no"] += 1
    sample["status"] = "SUBMITTED"
    touch(sample)
    return ok(sample)


# ---------------------------------------------------------------------------
# Change orders
# ---------------------------------------------------------------------------
@bp.post("/scenic/change-orders")
def create_change_order():
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    data = body()
    allowed = {"production_id", "expected_production_version", "new_drawing_revision",
               "delta_materials_cents", "delta_labor_hours", "delta_load_in_days"}
    check_unknown(data, allowed)
    prod_id = as_str(req(data, "production_id"), "production_id")
    expected_version = as_int(req(data, "expected_production_version"),
                              "expected_production_version")
    new_revision = as_int(req(data, "new_drawing_revision"), "new_drawing_revision")
    delta_materials = as_int(req(data, "delta_materials_cents"), "delta_materials_cents")
    delta_hours = as_int(req(data, "delta_labor_hours"), "delta_labor_hours")
    delta_days = as_int(req(data, "delta_load_in_days"), "delta_load_in_days")
    prod = get_or_404("productions", prod_id)
    if prod["status"] not in ("SCHEDULED", "IN_BUILD", "ON_HOLD", "BUILT", "LOADED_IN"):
        raise invalid_state("Change orders cannot be created in the production's current state")
    current_pkg = current_package_for(prod["client_id"], prod["show_title"])
    current_revision = current_pkg["drawing_revision"] if current_pkg else None
    if new_revision != current_revision or new_revision <= prod["applied_drawing_revision"]:
        raise ApiError("ERR_REVISION_NOT_CURRENT", 409,
                       "new_drawing_revision must equal the package's current revision and "
                       "exceed the production's applied revision")
    if abs(delta_materials) > 100000000:
        raise verr("delta_materials_cents absolute value must not exceed 100000000")
    if expected_version != prod["version"]:
        raise ApiError("ERR_STALE_PRODUCTION_VERSION", 412,
                       "expected_production_version does not match the production's version")
    shop = DB["shops"][prod["shop_id"]]
    delta_price = price_change_order(shop, prod, delta_materials, delta_hours, delta_days)
    co_no = sum(1 for co in DB["change_orders"].values()
                if co["production_id"] == prod["id"]) + 1
    co = mint()
    co.update({
        "production_id": prod_id,
        "new_drawing_revision": new_revision,
        "delta_materials_cents": delta_materials,
        "delta_labor_hours": delta_hours,
        "delta_load_in_days": delta_days,
        "priced_posture": shop["posture"],
        "priced_production_status": prod["status"],
        "delta_price_cents": delta_price,
        "co_no": co_no,
        "status": "PROPOSED",
    })
    DB["change_orders"][co["id"]] = co
    touch(prod)
    return ok(co, 201)


@bp.get("/scenic/change-orders")
def list_change_orders():
    auth()
    items = list(DB["change_orders"].values())
    for param in ("production_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [c for c in items if c.get(param) == value]
    return list_response(items)


@bp.get("/scenic/change-orders/<coId>")
def get_change_order(coId):
    auth()
    return ok(get_or_404("change_orders", coId))


@bp.post("/scenic/change-orders/<coId>/approve")
def approve_change_order(coId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    co = get_or_404("change_orders", coId)
    prod = DB["productions"][co["production_id"]]
    if auth_uid != prod["client_id"]:
        raise not_own("ClientPM may only decide change orders of their own client")
    if co["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED change order can be approved")
    # Cascade; the production's version increments for each mutation step.
    prod["current_price_cents"] += co["delta_price_cents"]
    touch(prod)
    prod["load_in_deadline_at"] = (
        prod["load_in_deadline_at"] + timedelta(days=co["delta_load_in_days"]))
    touch(prod)
    prod["committed_crew_hours"] = max(1, prod["committed_crew_hours"] + co["delta_labor_hours"])
    touch(prod)
    prod["applied_drawing_revision"] = co["new_drawing_revision"]
    touch(prod)
    for reservation in DB["bay_reservations"].values():
        if (reservation["production_id"] == prod["id"]
                and reservation["status"] == "ACTIVE"
                and reservation["window_end"] > prod["load_in_deadline_at"]):
            reservation["status"] = "RELEASED"
            touch(reservation)
    recompute_capacity(DB["shops"][prod["shop_id"]])
    recompute_client(DB["clients"][prod["client_id"]])
    co["status"] = "APPROVED"
    touch(co)
    return ok(co)


@bp.post("/scenic/change-orders/<coId>/reject")
def reject_change_order(coId):
    auth_uid, role = auth()
    need_role(role, {"ClientPM"})
    co = get_or_404("change_orders", coId)
    prod = DB["productions"][co["production_id"]]
    if auth_uid != prod["client_id"]:
        raise not_own("ClientPM may only decide change orders of their own client")
    if co["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED change order can be rejected")
    co["status"] = "REJECTED"
    touch(co)
    return ok(co)


@bp.post("/scenic/change-orders/<coId>/withdraw")
def withdraw_change_order(coId):
    auth_uid, role = auth()
    need_role(role, {"Estimator"})
    co = get_or_404("change_orders", coId)
    if co["status"] != "PROPOSED":
        raise invalid_state("Only a PROPOSED change order can be withdrawn")
    co["status"] = "WITHDRAWN"
    touch(co)
    return ok(co)


# ---------------------------------------------------------------------------
# Bay reservations
# ---------------------------------------------------------------------------
@bp.post("/scenic/bay-reservations")
def create_reservation():
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    data = body()
    check_unknown(data, {"production_id", "bay_slot", "window_start", "window_end"})
    prod_id = as_str(req(data, "production_id"), "production_id")
    bay_slot = as_int(req(data, "bay_slot"), "bay_slot")
    window_start = parse_dt(req(data, "window_start"), "window_start")
    window_end = parse_dt(req(data, "window_end"), "window_end")
    prod = get_or_404("productions", prod_id)
    if prod["status"] in ("STRUCK", "CLOSED"):
        raise invalid_state("Reservations cannot be created for a STRUCK or CLOSED production")
    shop = DB["shops"][prod["shop_id"]]
    if bay_slot < 1 or bay_slot > shop["bay_count"]:
        raise ApiError("ERR_BAY_SLOT_INVALID", 422,
                       "bay_slot must lie between 1 and the shop's bay_count")
    if not window_start < window_end:
        raise verr("window_start must be strictly earlier than window_end")
    for existing in DB["bay_reservations"].values():
        if existing["status"] != "ACTIVE":
            continue
        ex_prod = DB["productions"][existing["production_id"]]
        if ex_prod["shop_id"] != shop["id"] or existing["bay_slot"] != bay_slot:
            continue
        if overlaps(window_start, window_end,
                    existing["window_start"], existing["window_end"]):
            raise ApiError("ERR_BAY_OVERLAP", 409,
                           "Window overlaps an ACTIVE reservation on the same bay slot")
    if window_end > prod["load_in_deadline_at"]:
        raise ApiError("ERR_WINDOW_PAST_DEADLINE", 409,
                       "window_end lies after the production's load-in deadline")
    reservation = mint()
    reservation.update({
        "production_id": prod_id,
        "bay_slot": bay_slot,
        "window_start": window_start,
        "window_end": window_end,
        "status": "ACTIVE",
    })
    DB["bay_reservations"][reservation["id"]] = reservation
    return ok(reservation, 201)


@bp.get("/scenic/bay-reservations")
def list_reservations():
    auth()
    items = list(DB["bay_reservations"].values())
    prod_id = request.args.get("production_id")
    if prod_id is not None:
        items = [r for r in items if r["production_id"] == prod_id]
    bay_slot = request.args.get("bay_slot")
    if bay_slot is not None:
        try:
            slot = int(bay_slot)
        except (TypeError, ValueError):
            raise verr("bay_slot filter must be an integer")
        items = [r for r in items if r["bay_slot"] == slot]
    status = request.args.get("status")
    if status is not None:
        items = [r for r in items if r["status"] == status]
    return list_response(items)


@bp.get("/scenic/bay-reservations/<reservationId>")
def get_reservation(reservationId):
    auth()
    return ok(get_or_404("bay_reservations", reservationId))


@bp.delete("/scenic/bay-reservations/<reservationId>")
def release_reservation(reservationId):
    auth_uid, role = auth()
    need_role(role, {"ShopForeman"})
    reservation = get_or_404("bay_reservations", reservationId)
    if reservation["status"] != "ACTIVE":
        raise invalid_state("Only an ACTIVE reservation can be released")
    reservation["status"] = "RELEASED"
    touch(reservation)
    return ok({}, 204)


# ---------------------------------------------------------------------------
# Stock items
# ---------------------------------------------------------------------------
@bp.post("/scenic/stock-items")
def create_stock_item():
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    data = body()
    allowed = {"shop_id", "material_code", "condition_grade", "quantity_on_hand",
               "replacement_cost_cents"}
    check_unknown(data, allowed)
    shop_id = as_str(req(data, "shop_id"), "shop_id")
    material_code = as_str(req(data, "material_code"), "material_code")
    grade = as_enum(req(data, "condition_grade"), "condition_grade", {"A", "B", "C"})
    qty = as_int(req(data, "quantity_on_hand"), "quantity_on_hand")
    rc = as_int(req(data, "replacement_cost_cents"), "replacement_cost_cents")
    shop = get_or_404("shops", shop_id)
    if qty < 0:
        raise verr("quantity_on_hand must be >= 0")
    if rc <= 0:
        raise verr("replacement_cost_cents must be > 0")
    if find_stock_item(shop_id, material_code, grade) is not None:
        raise ApiError("ERR_DUPLICATE_STOCK_ITEM", 409,
                       "A stock item already exists for this shop, material and grade")
    item = mint()
    item.update({
        "shop_id": shop_id,
        "material_code": material_code,
        "condition_grade": grade,
        "quantity_on_hand": qty,
        "origin": "PURCHASED",
        "replacement_cost_cents": rc,
    })
    stock_refresh(item)
    DB["stock_items"][item["id"]] = item
    recompute_inventory(shop)
    return ok(item, 201)


@bp.get("/scenic/stock-items")
def list_stock_items():
    auth()
    items = list(DB["stock_items"].values())
    for param in ("shop_id", "material_code", "condition_grade", "status", "origin"):
        value = request.args.get(param)
        if value is not None:
            items = [i for i in items if i.get(param) == value]
    return list_response(items)


@bp.get("/scenic/stock-items/<itemId>")
def get_stock_item(itemId):
    auth()
    return ok(get_or_404("stock_items", itemId))


@bp.post("/scenic/stock-items/<itemId>/adjust")
def adjust_stock_item(itemId):
    auth_uid, role = auth()
    need_role(role, {"ShopAdmin"})
    item = get_or_404("stock_items", itemId)
    data = body()
    check_unknown(data, {"delta_quantity", "expected_stock_item_version", "reason"})
    delta = as_int(req(data, "delta_quantity"), "delta_quantity")
    expected = as_int(req(data, "expected_stock_item_version"), "expected_stock_item_version")
    opt_str(data, "reason")
    if item["quantity_on_hand"] + delta < 0:
        raise ApiError("ERR_STOCK_NEGATIVE", 409,
                       "Adjustment would drive quantity_on_hand below zero")
    if expected != item["version"]:
        raise ApiError("ERR_STALE_STOCK_VERSION", 412,
                       "expected_stock_item_version does not match the item's current version")
    item["quantity_on_hand"] += delta
    stock_refresh(item)
    touch(item)
    recompute_inventory(DB["shops"][item["shop_id"]])
    return ok(item)


# ---------------------------------------------------------------------------
# Transport plans
# ---------------------------------------------------------------------------
@bp.post("/scenic/transport-plans")
def create_transport_plan():
    auth_uid, role = auth()
    need_role(role, {"TransportCoordinator"})
    data = body()
    allowed = {"production_id", "truck_count", "install_crew_hours", "depart_at", "arrive_at"}
    check_unknown(data, allowed)
    prod_id = as_str(req(data, "production_id"), "production_id")
    truck_count = as_int(req(data, "truck_count"), "truck_count")
    install_hours = as_int(req(data, "install_crew_hours"), "install_crew_hours")
    depart_at = parse_dt(req(data, "depart_at"), "depart_at")
    arrive_at = parse_dt(req(data, "arrive_at"), "arrive_at")
    prod = get_or_404("productions", prod_id)
    if prod["status"] in ("STRUCK", "CLOSED"):
        raise invalid_state("Transport plans cannot be created for a STRUCK or CLOSED production")
    if truck_count < 1:
        raise verr("truck_count must be >= 1")
    if install_hours < 1:
        raise verr("install_crew_hours must be >= 1")
    if not depart_at < arrive_at:
        raise verr("depart_at must be strictly earlier than arrive_at")
    shop = DB["shops"][prod["shop_id"]]
    committed = 0
    for plan in DB["transport_plans"].values():
        if plan["status"] == "CANCELLED":
            continue
        plan_prod = DB["productions"][plan["production_id"]]
        if plan_prod["shop_id"] != shop["id"]:
            continue
        if overlaps(depart_at, arrive_at, plan["depart_at"], plan["arrive_at"]):
            committed += plan["truck_count"]
    if committed + truck_count > shop["truck_fleet_size"]:
        raise ApiError("ERR_FLEET_OVER_COMMITTED", 409,
                       "Truck fleet capacity would be exceeded over the requested window")
    plan = mint()
    plan.update({
        "production_id": prod_id,
        "truck_count": truck_count,
        "install_crew_hours": install_hours,
        "depart_at": depart_at,
        "arrive_at": arrive_at,
        "status": "PLANNED",
    })
    DB["transport_plans"][plan["id"]] = plan
    return ok(plan, 201)


@bp.get("/scenic/transport-plans")
def list_transport_plans():
    auth()
    items = list(DB["transport_plans"].values())
    for param in ("production_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [p for p in items if p.get(param) == value]
    return list_response(items)


@bp.get("/scenic/transport-plans/<planId>")
def get_transport_plan(planId):
    auth()
    return ok(get_or_404("transport_plans", planId))


@bp.post("/scenic/transport-plans/<planId>/confirm")
def confirm_transport_plan(planId):
    auth_uid, role = auth()
    need_role(role, {"TransportCoordinator"})
    plan = get_or_404("transport_plans", planId)
    if plan["status"] != "PLANNED":
        raise invalid_state("Only a PLANNED transport plan can be confirmed")
    prod = DB["productions"][plan["production_id"]]
    if prod["status"] in ("LOADED_IN", "STRUCK", "CLOSED"):
        raise invalid_state("The production is too far along to confirm transport")
    plan["status"] = "CONFIRMED"
    touch(plan)
    return ok(plan)


@bp.post("/scenic/transport-plans/<planId>/cancel")
def cancel_transport_plan(planId):
    auth_uid, role = auth()
    need_role(role, {"TransportCoordinator"})
    plan = get_or_404("transport_plans", planId)
    if plan["status"] != "PLANNED":
        raise invalid_state("Only a PLANNED transport plan can be cancelled")
    plan["status"] = "CANCELLED"
    touch(plan)
    return ok(plan)
