"""Store-scoped filings: inventory lots, selling days, employees, lease
dispositions, and the three store lifecycle transitions."""

from flask import Blueprint

import auth
import calc
import clock
import db
import helpers
import response
import serializers
import shape
from errors import ApiError
from money import ZERO, round4

bp = Blueprint("store", __name__)


# ------------------------------------------------------------ inventory lots

@bp.post("/stores/<store_id>/inventory-lots")
def create_lot(store_id):
    user_id, role = auth.begin(("LiquidationConsultant", "StoreManager"))
    auth.scope_store(user_id, role, store_id)
    body = shape.json_body()
    category = shape.field_enum(body, "category", calc.CATEGORIES)
    source = shape.field_enum(body, "source", calc.SOURCES)
    units_initial = shape.field_int(body, "units_initial", minimum=1)
    unit_cost_cents = shape.field_int(body, "unit_cost_cents", minimum=1)
    unit_retail_cents = shape.field_int(body, "unit_retail_cents", minimum=1)
    if unit_retail_cents < unit_cost_cents:
        shape.bad("Field 'unit_retail_cents' may not be below 'unit_cost_cents'")
    if source == "AUGMENTATION":
        raise ApiError("ERR_AUGMENTATION_SOURCE_FORBIDDEN")

    store = helpers.require("stores", store_id)
    helpers.store_open_for_children(store)

    row = db.insert(
        "lots",
        {
            "store_id": store["id"],
            "consignment_id": None,
            "category": category,
            "source": source,
            "units_initial": units_initial,
            "units_on_hand": units_initial,
            "units_sold": 0,
            "units_returned": 0,
            "unit_cost_cents": unit_cost_cents,
            "unit_retail_cents": unit_retail_cents,
            "cost_value_cents": units_initial * unit_cost_cents,
            "retail_value_cents": units_initial * unit_retail_cents,
            "lot_status": "ON_FLOOR",
            "projected_recovery_cents": 0,
        },
    )
    engagement = helpers.engagement_of_store(store)
    calc.recompute_store(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    # PRD 3.2 names no version increment on the store when a lot is filed; the
    # roll-up refresh alone does not bump a row's version (the same reading the
    # engagement roll-up already follows here).
    db.refresh(store)
    return response.ok(serializers.lot(row), 201)


@bp.get("/stores/<store_id>/inventory-lots")
def list_lots(store_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    auth.scope_store(user_id, role, store_id)
    limit, offset = shape.pagination()
    source = shape.query_enum("source", calc.SOURCES)
    lot_status = shape.query_enum("lot_status", calc.LOT_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.lots_of_store(store["id"])
    if source is not None:
        rows = [r for r in rows if r["source"] == source]
    if lot_status is not None:
        rows = [r for r in rows if r["lot_status"] == lot_status]
    return helpers.paginate(rows, serializers.lot, limit, offset)


@bp.get("/inventory-lots/<row_id>")
def read_lot(row_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    row = db.get("lots", row_id)
    auth.scope_child(user_id, role, row)
    if row is None:
        raise ApiError("ERR_INVENTORY_LOT_NOT_FOUND")
    return response.ok(serializers.lot(row))


# --------------------------------------------------------------- sales days

@bp.post("/stores/<store_id>/sales-days")
def create_sales_day(store_id):
    user_id, role = auth.begin(("StoreManager", "LiquidationConsultant"))
    auth.scope_store(user_id, role, store_id)
    body = shape.json_body()
    business_date = shape.field_date(body, "business_date")
    original_net = shape.field_int(body, "original_net_sales_cents", minimum=0)
    augmentation_net = shape.field_int(body, "augmentation_net_sales_cents", minimum=0)
    original_units = shape.field_int(body, "original_units_sold", minimum=0)
    augmentation_units = shape.field_int(body, "augmentation_units_sold", minimum=0)

    store = helpers.require("stores", store_id)
    helpers.store_open_for_children(store)

    start = calc.as_date(store["selling_start_date"])
    end = calc.as_date(store["selling_end_date"])
    if start is None or business_date < start:
        raise ApiError("ERR_SALES_DAY_OUT_OF_WINDOW")
    if end is not None and business_date > end:
        raise ApiError("ERR_SALES_DAY_OUT_OF_WINDOW")
    if business_date > clock.today():
        raise ApiError("ERR_SALES_DAY_OUT_OF_WINDOW")

    for existing in db.sales_days_of_store(store["id"]):
        if existing["day_status"] == "REJECTED":
            continue
        if calc.as_date(existing["business_date"]) == business_date:
            raise ApiError("ERR_DUPLICATE_SALES_DAY")

    if augmentation_units == 0 and augmentation_net != 0:
        raise ApiError("ERR_SALES_TOTALS_INCONSISTENT")

    row = db.insert(
        "sales_days",
        {
            "store_id": store["id"],
            "business_date": business_date.isoformat(),
            "original_net_sales_cents": original_net,
            "augmentation_net_sales_cents": augmentation_net,
            "original_units_sold": original_units,
            "augmentation_units_sold": augmentation_units,
            "net_sales_cents": original_net + augmentation_net,
            "day_status": "PENDING_REVIEW",
            "posted_at": None,
            "submitted_by_user_id": user_id,
            "reviewed_by_user_id": None,
            "allocation_note": None,
        },
    )
    return response.ok(serializers.sales_day(row), 201)


@bp.get("/stores/<store_id>/sales-days")
def list_sales_days(store_id):
    user_id, role = auth.begin(
        ("StoreManager", "LiquidationConsultant", "RetailerController")
    )
    auth.scope_store(user_id, role, store_id)
    limit, offset = shape.pagination()
    day_status = shape.query_enum("day_status", calc.DAY_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.sales_days_of_store(store["id"])
    if day_status is not None:
        rows = [r for r in rows if r["day_status"] == day_status]
    return helpers.paginate(rows, serializers.sales_day, limit, offset)


# ---------------------------------------------------------------- employees

@bp.post("/stores/<store_id>/employees")
def create_employee(store_id):
    user_id, role = auth.begin(("StoreManager", "LiquidationConsultant"))
    auth.scope_store(user_id, role, store_id)
    body = shape.json_body()
    employee_code = shape.field_str(body, "employee_code")
    bonus_cents = shape.field_int(body, "retention_bonus_cents", minimum=0)
    start = shape.field_date(body, "retention_start_date")
    target = shape.field_date(body, "retention_target_date")
    attendance_rate = shape.field_pct(body, "attendance_rate")
    if target < start:
        raise ApiError("ERR_INVALID_DATE_RANGE")

    store = helpers.require("stores", store_id)
    for existing in db.employees_of_store(store["id"]):
        if existing["employee_code"] == employee_code:
            raise ApiError("ERR_DUPLICATE_EMPLOYEE_CODE")
    helpers.store_open_for_children(store)

    row = db.insert(
        "employees",
        {
            "store_id": store["id"],
            "employee_code": employee_code,
            "employment_status": "ACTIVE",
            "bonus_status": "PENDING",
            "retention_bonus_cents": bonus_cents,
            "retention_start_date": start.isoformat(),
            "retention_target_date": target.isoformat(),
            "attendance_rate": attendance_rate,
            "served_days": 0,
            "earned_bonus_cents": 0,
            "notice_given_date": None,
            "termination_date": None,
            "bonus_paid_at": None,
        },
    )
    return response.ok(serializers.employee(row), 201)


@bp.get("/stores/<store_id>/employees")
def list_employees(store_id):
    user_id, role = auth.begin(
        ("StoreManager", "LiquidationConsultant", "RetailerController")
    )
    auth.scope_store(user_id, role, store_id)
    limit, offset = shape.pagination()
    employment_status = shape.query_enum("employment_status", calc.EMPLOYMENT_STATUSES)
    bonus_status = shape.query_enum("bonus_status", calc.BONUS_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.employees_of_store(store["id"])
    if employment_status is not None:
        rows = [r for r in rows if r["employment_status"] == employment_status]
    if bonus_status is not None:
        rows = [r for r in rows if r["bonus_status"] == bonus_status]
    return helpers.paginate(rows, serializers.employee, limit, offset)


# ------------------------------------------------------- store expense items

@bp.get("/stores/<store_id>/expense-items")
def list_store_expense_items(store_id):
    user_id, role = auth.begin(
        ("LiquidationConsultant", "RetailerController", "StoreManager")
    )
    auth.scope_store(user_id, role, store_id)
    limit, offset = shape.pagination()
    expense_status = shape.query_enum("expense_status", calc.EXPENSE_STATUSES)
    store = helpers.require("stores", store_id)
    rows = db.expense_items_of_store(store["id"])
    if expense_status is not None:
        rows = [r for r in rows if r["expense_status"] == expense_status]
    return helpers.paginate(rows, serializers.expense_item, limit, offset)


# ------------------------------------------------------- lease dispositions

@bp.post("/stores/<store_id>/lease-dispositions")
def create_lease(store_id):
    auth.begin(("LiquidationConsultant",))
    body = shape.json_body()
    landlord_name = shape.field_str(body, "landlord_name")
    deadline = shape.field_date(body, "surrender_deadline_date")
    daily_rate = shape.field_int(body, "daily_holdover_rate_cents", minimum=0)
    rent = shape.field_int(body, "rent_arrears_cents", minimum=0)
    cam = shape.field_int(body, "cam_arrears_cents", minimum=0)
    restoration = shape.field_int(body, "restoration_cost_cents", minimum=0)
    reserve = shape.field_int(body, "fixture_reserve_price_cents", minimum=0)
    credit = shape.field_int(
        body, "surrender_credit_cents", required=False, default=0, minimum=0
    )

    store = helpers.require("stores", store_id)
    helpers.store_open_for_children(store)

    row = db.insert(
        "leases",
        {
            "store_id": store["id"],
            "landlord_name": landlord_name,
            "surrender_deadline_date": deadline.isoformat(),
            "daily_holdover_rate_cents": daily_rate,
            "rent_arrears_cents": rent,
            "cam_arrears_cents": cam,
            "restoration_cost_cents": restoration,
            "fixture_reserve_price_cents": reserve,
            "surrender_credit_cents": credit,
            "disposition_status": "DRAFT",
            "negotiation_round": 0,
            "offered_surrender_payment_cents": None,
            "landlord_counter_amount_cents": None,
            "agreed_surrender_payment_cents": None,
            "landlord_agreed_date": None,
            "fixture_sale_price_cents": None,
            "holdover_days": None,
            "holdover_penalty_cents": None,
            "allocated_rent_cents": None,
            "allocated_cam_cents": None,
            "allocated_restoration_cents": None,
            "allocated_holdover_cents": None,
            "unpaid_landlord_balance_cents": None,
            "residual_to_retailer_cents": None,
            "surrendered_at": None,
        },
    )
    return response.ok(serializers.lease(row), 201)


@bp.get("/stores/<store_id>/lease-dispositions")
def list_leases(store_id):
    auth.begin(("LiquidationConsultant", "RetailerController"))
    limit, offset = shape.pagination()
    disposition_status = shape.query_enum(
        "disposition_status", calc.DISPOSITION_STATUSES
    )
    store = helpers.require("stores", store_id)
    rows = db.leases_of_store(store["id"])
    if disposition_status is not None:
        rows = [r for r in rows if r["disposition_status"] == disposition_status]
    return helpers.paginate(rows, serializers.lease, limit, offset)


# ------------------------------------------------- store lifecycle transitions

def _close_active_stage(store, reason):
    """Shared by licence loss, discretionary suspension and store closure."""
    closed = 0
    for stage in db.stages_of_store(store["id"]):
        if stage["stage_status"] == "ACTIVE":
            stage["stage_status"] = "CLOSED"
            stage["closed_reason"] = reason
            stage["escalation_applied_pct"] = round4(ZERO)
            db.touch(stage)
            closed += 1
    return closed


@bp.post("/stores/<store_id>/close-selling")
def close_selling(store_id):
    auth.begin(("LiquidationConsultant",))
    store = helpers.require("stores", store_id)
    if store["store_status"] not in ("SELLING", "SUSPENDED"):
        raise ApiError("ERR_STORE_STATE_INVALID")
    engagement = helpers.engagement_of_store(store)
    today = clock.today()

    # hop 1
    store["store_status"] = "CLOSED"
    store["selling_end_date"] = today.isoformat()

    # hop 2
    for stage in db.stages_of_store(store["id"]):
        if stage["stage_status"] in calc.PLANNED_STAGE_STATUSES:
            stage["stage_status"] = "CLOSED"
            stage["closed_reason"] = "STORE_CLOSED"
            stage["escalation_applied_pct"] = round4(ZERO)
            db.touch(stage)

    # hop 3
    for employee in db.employees_of_store(store["id"]):
        touched = False
        if employee["bonus_status"] == "PENDING":
            calc.settle_retention_bonus(employee, today)
            touched = True
        if employee["employment_status"] in ("ACTIVE", "NOTICE_GIVEN"):
            employee["employment_status"] = "TERMINATED_INVOLUNTARY"
            employee["termination_date"] = store["selling_end_date"]
            touched = True
        if touched:
            db.touch(employee)

    # hop 4
    if engagement is not None:
        calc.recompute_engagement(engagement)

    # hop 5 and hop 6
    payroll_total = sum(
        e["earned_bonus_cents"] for e in db.employees_of_store(store["id"])
    )
    if engagement is not None and payroll_total > 0:
        item = db.insert(
            "expense_items",
            {
                "engagement_id": engagement["id"],
                "store_id": store["id"],
                "expense_category": "PAYROLL",
                "amount_cents": payroll_total,
                "incurred_date": store["selling_end_date"],
                "expense_status": "APPROVED",
                "liquidator_share_cents": 0,
                "retailer_share_cents": 0,
                "auto_generated": True,
                "submitted_by_user_id": None,
                "decided_by_user_id": None,
            },
        )
        liquidator, retailer = calc.expense_responsibility_split(
            engagement, item["amount_cents"]
        )
        item["liquidator_share_cents"] = liquidator
        item["retailer_share_cents"] = retailer

    calc.recompute_store(store)
    db.touch(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
        db.touch(engagement)
    return response.ok(serializers.store(store))


@bp.post("/stores/<store_id>/suspend")
def suspend_store(store_id):
    auth.begin(("ComplianceOfficer",))
    body = shape.json_body()
    reason = shape.field_enum(
        body,
        "suspension_reason",
        calc.SUSPENSION_REASONS,
        required=False,
        default="COMPLIANCE_HOLD",
    )
    store = helpers.require("stores", store_id)
    if store["store_status"] != "SELLING":
        raise ApiError("ERR_STORE_NOT_SELLING")

    store["store_status"] = "SUSPENDED"
    store["suspension_reason"] = reason
    _close_active_stage(store, "LICENSE_LOST")
    engagement = helpers.engagement_of_store(store)
    calc.recompute_store(store)
    db.touch(store)
    if engagement is not None:
        calc.recompute_engagement(engagement)
    return response.ok(serializers.store(store))


@bp.post("/stores/<store_id>/resume")
def resume_store(store_id):
    auth.begin(("ComplianceOfficer",))
    store = helpers.require("stores", store_id)
    if store["store_status"] != "SUSPENDED":
        raise ApiError("ERR_STORE_STATE_INVALID")
    jurisdiction = helpers.jurisdiction_of_store(store)
    if jurisdiction is not None and jurisdiction["gob_license_required"]:
        if calc.license_covers_date(store, clock.today()) is None:
            raise ApiError("ERR_LICENSE_NOT_ACTIVE")
    store["store_status"] = "SELLING"
    store["suspension_reason"] = "NONE"
    db.touch(store)
    return response.ok(serializers.store(store))
