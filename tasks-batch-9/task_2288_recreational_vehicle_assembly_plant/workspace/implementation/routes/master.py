"""Master data: suppliers, floor plans, options, dealers, lines, booths."""
from decimal import Decimal

import constants as C
import db
import response
import validation as V
from db import store
from errors import ApiError, bad_request
from flask import Blueprint
from middleware import authorize
from routes.common import insert, list_out, must_find, object_out
from services import calc, derive

bp = Blueprint("master", __name__)


# ---------------------------------------------------------------------------
# suppliers
# ---------------------------------------------------------------------------
@bp.post("/suppliers")
@authorize("PlantAdmin")
def create_supplier():
    body = V.body_dict()
    code = V.field_string(body, "supplier_code", required=True, min_len=3, max_len=16)
    name = V.field_string(body, "name", required=True, min_len=1)
    categories = V.field_enum_array(
        body, "component_categories", C.COMPONENT_CATEGORIES, required=True, allow_empty=False
    )
    V.unique_or_400(store.suppliers, "supplier_code", code, "supplier_code")
    row = db.new_row(
        {
            "supplier_code": code,
            "name": name,
            "component_categories": categories,
            "quality_score": Decimal("100.00"),
            "supplier_status": "ACTIVE",
            "open_recall_count": 0,
            "penalty_event_count": 0,
        }
    )
    insert("suppliers", row)
    return object_out("suppliers", row, 201)


@bp.get("/suppliers/<row_id>")
@authorize("PlantAdmin", "ProductionScheduler", "WarrantyAdministrator", "RecallCoordinator")
def get_supplier(row_id):
    return object_out("suppliers", must_find("suppliers", row_id))


@bp.get("/suppliers/<row_id>/scorecard")
@authorize("PlantAdmin", "ProductionScheduler", "WarrantyAdministrator", "RecallCoordinator")
def supplier_scorecard(row_id):
    supplier = must_find("suppliers", row_id)
    rolling, lifetime = derive.supplier_scores(supplier["id"])
    supplier["quality_score"] = rolling
    supplier["supplier_status"] = calc.supplier_status_for(rolling)
    return response.object_response(
        {
            "supplier_id": supplier["id"],
            "rolling_quality_score": float(rolling),
            "lifetime_quality_score": float(lifetime),
            "supplier_status": supplier["supplier_status"],
            "open_recall_count": supplier["open_recall_count"],
            "penalty_event_count": supplier["penalty_event_count"],
            "evaluated_at": db.iso_instant(db.now()),
        }
    )


# ---------------------------------------------------------------------------
# floor plans
# ---------------------------------------------------------------------------
@bp.post("/floor-plans")
@authorize("PlantAdmin")
def create_floor_plan():
    body = V.body_dict()
    model_code = V.field_string(body, "model_code", required=True, min_len=1)
    chassis_class = V.field_enum(body, "chassis_class", C.CHASSIS_CLASSES, required=True)
    length_ft = V.field_int(body, "length_ft", required=True, minimum=18, maximum=45)
    base_msrp = V.field_int(body, "base_msrp_cents", required=True, minimum=1)
    base_hours = V.field_number(body, "base_station_hours", required=True, exclusive_minimum=0)
    dry_weight = V.field_int(body, "base_dry_weight_lbs", required=True, minimum=1)
    gvwr = V.field_int(body, "gvwr_lbs", required=True, minimum=1)
    wheelbase = V.field_int(body, "required_wheelbase_in", required=True, minimum=1)
    amps = V.field_int(body, "electrical_service_amps", required=True, allowed=[30, 50])
    water = V.field_int(body, "fresh_water_capacity_gal", required=True, minimum=1)
    status = V.field_enum(body, "status", ["ACTIVE", "RETIRED"], default="ACTIVE")
    if gvwr <= dry_weight:
        raise bad_request("Field 'gvwr_lbs' must be greater than 'base_dry_weight_lbs'.")
    V.unique_or_400(store.floor_plans, "model_code", model_code, "model_code")
    row = db.new_row(
        {
            "model_code": model_code,
            "chassis_class": chassis_class,
            "length_ft": length_ft,
            "base_msrp_cents": base_msrp,
            "base_station_hours": calc.rhu2(base_hours),
            "base_dry_weight_lbs": dry_weight,
            "gvwr_lbs": gvwr,
            "required_wheelbase_in": wheelbase,
            "electrical_service_amps": amps,
            "fresh_water_capacity_gal": water,
            "max_payload_lbs": gvwr - dry_weight,
            "status": status,
        }
    )
    insert("floor_plans", row)
    return object_out("floor_plans", row, 201)


@bp.get("/floor-plans/<row_id>")
@authorize("PlantAdmin", "DealerPrincipal", "ProductionScheduler")
def get_floor_plan(row_id):
    return object_out("floor_plans", must_find("floor_plans", row_id))


@bp.patch("/floor-plans/<row_id>")
@authorize("PlantAdmin")
def patch_floor_plan(row_id):
    body = V.body_dict()
    base_msrp = V.field_int(body, "base_msrp_cents", minimum=1)
    status = V.field_enum(body, "status", ["ACTIVE", "RETIRED"])
    row = must_find("floor_plans", row_id)
    if base_msrp is not None:
        row["base_msrp_cents"] = base_msrp
    if status is not None:
        row["status"] = status
    row["max_payload_lbs"] = int(row["gvwr_lbs"]) - int(row["base_dry_weight_lbs"])
    db.touch(row)
    return object_out("floor_plans", row)


# ---------------------------------------------------------------------------
# option items
# ---------------------------------------------------------------------------
@bp.post("/option-items")
@authorize("PlantAdmin")
def create_option_item():
    body = V.body_dict()
    option_code = V.field_string(body, "option_code", required=True, min_len=1)
    category = V.field_enum(body, "category", C.OPTION_CATEGORIES, required=True)
    install_station = V.field_enum(body, "install_station", C.INSTALL_STATIONS, required=True)
    price = V.field_int(body, "price_cents", required=True, minimum=0)
    weight = V.field_int(body, "weight_lbs", required=True, minimum=0)
    hours = V.field_number(body, "added_station_hours", required=True, minimum=0)
    amp_draw = V.field_int(body, "amp_draw", default=0, minimum=0)
    water = V.field_int(body, "water_demand_gal", default=0, minimum=0)
    requires = V.field_str_array(body, "requires_option_codes", default=[])
    excludes = V.field_str_array(body, "excludes_option_codes", default=[])
    status = V.field_enum(body, "status", ["ACTIVE", "DISCONTINUED"], default="ACTIVE")
    V.unique_or_400(store.option_items, "option_code", option_code, "option_code")
    row = db.new_row(
        {
            "option_code": option_code,
            "category": category,
            "install_station": install_station,
            "price_cents": price,
            "weight_lbs": weight,
            "added_station_hours": calc.rhu2(hours),
            "amp_draw": amp_draw,
            "water_demand_gal": water,
            "requires_option_codes": requires,
            "excludes_option_codes": excludes,
            "status": status,
        }
    )
    insert("option_items", row)
    return object_out("option_items", row, 201)


@bp.get("/option-items/<row_id>")
@authorize("PlantAdmin", "DealerPrincipal", "ProductionScheduler")
def get_option_item(row_id):
    return object_out("option_items", must_find("option_items", row_id))


@bp.patch("/option-items/<row_id>")
@authorize("PlantAdmin")
def patch_option_item(row_id):
    body = V.body_dict()
    price = V.field_int(body, "price_cents", minimum=0)
    status = V.field_enum(body, "status", ["ACTIVE", "DISCONTINUED"])
    row = must_find("option_items", row_id)
    if price is not None:
        row["price_cents"] = price
    if status is not None:
        row["status"] = status
    db.touch(row)
    return object_out("option_items", row)


# ---------------------------------------------------------------------------
# dealers
# ---------------------------------------------------------------------------
@bp.post("/dealers")
@authorize("PlantAdmin")
def create_dealer():
    body = V.body_dict()
    dealer_code = V.field_string(body, "dealer_code", required=True, min_len=1)
    region = V.field_enum(body, "region", C.REGIONS, required=True)
    share = V.field_int(body, "allocation_share_bp", required=True, minimum=1, maximum=10000)
    limit = V.field_int(body, "floor_plan_credit_limit_cents", required=True, minimum=1)
    goodwill = V.field_int(body, "goodwill_budget_cents", required=True, minimum=0)
    status = V.field_enum(body, "status", ["ACTIVE", "SUSPENDED"], default="ACTIVE")
    V.unique_or_400(store.dealers, "dealer_code", dealer_code, "dealer_code")
    row = db.new_row(
        {
            "dealer_code": dealer_code,
            "region": region,
            "allocation_share_bp": share,
            "floor_plan_credit_limit_cents": limit,
            "goodwill_budget_cents": goodwill,
            "status": status,
        }
    )
    insert("dealers", row)
    return object_out("dealers", row, 201)


@bp.get("/dealers/<row_id>")
@authorize("PlantAdmin", "DealerPrincipal", "ProductionScheduler", "WarrantyAdministrator")
def get_dealer(row_id):
    return object_out("dealers", must_find("dealers", row_id))


@bp.post("/dealers/<row_id>/status")
@authorize("PlantAdmin")
def set_dealer_status(row_id):
    body = V.body_dict()
    status = V.field_enum(body, "status", ["ACTIVE", "SUSPENDED"], required=True)
    row = must_find("dealers", row_id)
    if row["status"] != status:
        row["status"] = status
        db.touch(row)
    return object_out("dealers", row)


# ---------------------------------------------------------------------------
# production lines
# ---------------------------------------------------------------------------
@bp.post("/production-lines")
@authorize("PlantAdmin")
def create_production_line():
    body = V.body_dict()
    line_code = V.field_string(body, "line_code", required=True, min_len=1)
    chassis_class = V.field_enum(body, "chassis_class_supported", C.CHASSIS_CLASSES, required=True)
    capacity = V.field_number(body, "daily_station_hour_capacity", required=True, exclusive_minimum=0)
    max_units = V.field_int(body, "max_units_per_day", required=True, minimum=1)
    status = V.field_enum(body, "status", ["RUNNING", "PAUSED"], default="RUNNING")
    V.unique_or_400(store.production_lines, "line_code", line_code, "line_code")
    row = db.new_row(
        {
            "line_code": line_code,
            "chassis_class_supported": chassis_class,
            "daily_station_hour_capacity": calc.rhu2(capacity),
            "max_units_per_day": max_units,
            "status": status,
        }
    )
    insert("production_lines", row)
    return object_out("production_lines", row, 201)


@bp.get("/production-lines/<row_id>")
@authorize("PlantAdmin", "ProductionScheduler", "LineSupervisor")
def get_production_line(row_id):
    return object_out("production_lines", must_find("production_lines", row_id))


@bp.post("/production-lines/<row_id>/status")
@authorize("PlantAdmin", "ProductionScheduler")
def set_line_status(row_id):
    body = V.body_dict()
    status = V.field_enum(body, "status", ["RUNNING", "PAUSED"], required=True)
    row = must_find("production_lines", row_id)
    if row["status"] != status:
        row["status"] = status
        db.touch(row)
    return object_out("production_lines", row)


# ---------------------------------------------------------------------------
# test booths
# ---------------------------------------------------------------------------
@bp.post("/test-booths")
@authorize("PlantAdmin")
def create_test_booth():
    body = V.body_dict()
    booth_code = V.field_string(body, "booth_code", required=True, min_len=1)
    booth_type = V.field_enum(body, "booth_type", C.BOOTH_TYPES, required=True)
    bay_count = V.field_int(body, "bay_count", required=True, minimum=1)
    turnaround = V.field_int(body, "turnaround_minutes", default=30, minimum=0)
    status = V.field_enum(body, "status", ["OPEN", "DOWN"], default="OPEN")
    V.unique_or_400(store.test_booths, "booth_code", booth_code, "booth_code")
    row = db.new_row(
        {
            "booth_code": booth_code,
            "booth_type": booth_type,
            "bay_count": bay_count,
            "turnaround_minutes": turnaround,
            "status": status,
        }
    )
    insert("test_booths", row)
    return object_out("test_booths", row, 201)


@bp.get("/test-booths/<row_id>")
@authorize("PlantAdmin", "QualityInspector")
def get_test_booth(row_id):
    return object_out("test_booths", must_find("test_booths", row_id))


@bp.post("/test-booths/<row_id>/status")
@authorize("PlantAdmin")
def set_booth_status(row_id):
    body = V.body_dict()
    status = V.field_enum(body, "status", ["OPEN", "DOWN"], required=True)
    row = must_find("test_booths", row_id)
    if row["status"] != status:
        row["status"] = status
        db.touch(row)
    return object_out("test_booths", row)
