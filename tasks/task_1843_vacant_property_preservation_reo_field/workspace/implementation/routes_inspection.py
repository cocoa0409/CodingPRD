"""Routes: inspections (occupancy determination), personal property dispositions,
recurring service plans."""

from flask import Blueprint, request

from auth import get_auth, require_role, ANY_ROLE
from db import store, new_entity, bump, bump_if_changed, public, iso3, clock_date
from errors import raise_err
from response import ok, ok_list
from services import (
    recompute_property_score, hold_until_for, suspend_plan_cascade,
    season_window,
)
from util import (
    get_body, req_str, req_amount, req_enum, req_bool,
    req_date, get_or_404, parse_pagination, paginate, sort_created,
    OCCUPANCY_DETERMINATIONS, VERIFIED_OCCUPANCY, SERVICE_TYPES,
)

bp = Blueprint("inspection", __name__)


# ---- Inspection ------------------------------------------------------------------

@bp.post("/preservation/inspections")
def create_inspection():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin", "Servicer"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")
    work_order_id = b.get("work_order_id")
    if work_order_id is not None:
        if not isinstance(work_order_id, str):
            raise_err("ERR_INVALID_REQUEST", "work_order_id must be a string")
        get_or_404(store.work_orders, work_order_id, "WorkOrder")
    due_date = req_date(b, "due_date")

    cycle_index = sum(1 for i in store.inspections.values() if i["property_id"] == prop["id"]) + 1
    ins = new_entity({
        "property_id": prop["id"],
        "work_order_id": work_order_id,
        "cycle_index": cycle_index,
        "due_date": due_date,
        "status": "SCHEDULED",
        "occupancy_determination": None,
        "interior_access": None,
        "personal_property_present": None,
        "personal_property_value_estimate_cents": None,
        "condition_notes": None,
        "recorded_at": None,
        "verified_occupancy": None,
    })
    store.inspections[ins["id"]] = ins
    return ok(public(ins), status=201)


@bp.get("/preservation/inspections/<inspectionId>")
def get_inspection(inspectionId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    ins = get_or_404(store.inspections, inspectionId, "Inspection")
    return ok(public(ins))


@bp.get("/preservation/inspections")
def list_inspections():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.inspections.values())
    for field in ("property_id", "work_order_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [i for i in items if i.get(field) == v]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/inspections/<inspectionId>/record")
def record_inspection(inspectionId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    ins = get_or_404(store.inspections, inspectionId, "Inspection")
    b = get_body()
    occupancy_determination = req_enum(b, "occupancy_determination", OCCUPANCY_DETERMINATIONS)
    interior_access = req_bool(b, "interior_access")
    personal_property_present = req_bool(b, "personal_property_present")
    estimate = b.get("personal_property_value_estimate_cents")
    if personal_property_present is True and estimate is None:
        raise_err(
            "ERR_INVALID_REQUEST",
            "personal_property_value_estimate_cents is required when personal_property_present is true",
        )
    if estimate is not None:
        if isinstance(estimate, bool) or not isinstance(estimate, int) or estimate < 0:
            raise_err("ERR_INVALID_REQUEST", "personal_property_value_estimate_cents must be a non-negative integer")
    condition_notes = b.get("condition_notes")
    if condition_notes is not None and not isinstance(condition_notes, str):
        raise_err("ERR_INVALID_REQUEST", "condition_notes must be a string")

    if ins["status"] != "SCHEDULED":
        raise_err("ERR_INVALID_STATE", "Inspection is not SCHEDULED")

    ins["occupancy_determination"] = occupancy_determination
    ins["interior_access"] = interior_access
    ins["personal_property_present"] = personal_property_present
    ins["personal_property_value_estimate_cents"] = estimate
    ins["condition_notes"] = condition_notes
    ins["recorded_at"] = iso3(store.clock)

    prop = store.properties.get(ins["property_id"])
    if occupancy_determination == "VACANT":
        ins["status"] = "COMPLETED"
        bump(ins)
        if prop is not None:
            prop["occupancy_status"] = "VACANT"
            bump(prop)
            recompute_property_score(prop)
    else:
        ins["status"] = "VERIFICATION_PENDING"
        bump(ins)
        if occupancy_determination == "OCCUPIED" and prop is not None:
            bump_if_changed(prop, {"occupancy_status": "OCCUPIED_PENDING_VERIFICATION"})
    return ok(public(ins))


@bp.post("/preservation/inspections/<inspectionId>/verify")
def verify_inspection(inspectionId):
    user_id, role = get_auth()
    require_role(role, ["FieldCrew"])
    ins = get_or_404(store.inspections, inspectionId, "Inspection")
    b = get_body()
    verified_occupancy = req_enum(b, "verified_occupancy", VERIFIED_OCCUPANCY)
    if ins["status"] != "VERIFICATION_PENDING":
        raise_err("ERR_INVALID_STATE", "Inspection is not VERIFICATION_PENDING")

    ins["verified_occupancy"] = verified_occupancy
    ins["status"] = "COMPLETED"
    bump(ins)

    prop = store.properties.get(ins["property_id"])
    if prop is not None:
        if verified_occupancy == "OCCUPIED":
            prop["occupancy_status"] = "OCCUPIED"
            bump(prop)
            # Cascade link 2: suspend every ACTIVE plan of the property.
            for plan in store.plans.values():
                if plan["property_id"] == prop["id"] and plan["status"] == "ACTIVE":
                    plan["status"] = "SUSPENDED"
                    bump(plan)
                    # Cascade link 3: cancel open generated orders with compensation.
                    suspend_plan_cascade(plan)
        else:
            prop["occupancy_status"] = "VACANT"
            bump(prop)
            recompute_property_score(prop)
    return ok(public(ins))


# ---- PersonalPropertyDisposition --------------------------------------------------

@bp.post("/preservation/personal-property-dispositions")
def create_disposition():
    user_id, role = get_auth()
    require_role(role, ["FieldCrew", "VendorAdmin"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")
    work_order_id = b.get("work_order_id")
    if work_order_id is not None:
        if not isinstance(work_order_id, str):
            raise_err("ERR_INVALID_REQUEST", "work_order_id must be a string")
        get_or_404(store.work_orders, work_order_id, "WorkOrder")
    inspection_id = b.get("inspection_id")
    if inspection_id is not None:
        if not isinstance(inspection_id, str):
            raise_err("ERR_INVALID_REQUEST", "inspection_id must be a string")
        get_or_404(store.inspections, inspection_id, "Inspection")
    description = req_str(b, "description")
    valuation_cents = req_amount(b, "valuation_cents")

    documented = clock_date().isoformat()
    disp = new_entity({
        "property_id": prop["id"],
        "work_order_id": work_order_id,
        "inspection_id": inspection_id,
        "description": description,
        "valuation_cents": valuation_cents,
        "documented_date": documented,
        "hold_until_date": hold_until_for(prop["state_code"], documented),
        "status": "IN_HOLD",
        "authorized_by_user_id": None,
    })
    store.dispositions[disp["id"]] = disp
    return ok(public(disp), status=201)


@bp.get("/preservation/personal-property-dispositions/<dispositionId>")
def get_disposition(dispositionId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    disp = get_or_404(store.dispositions, dispositionId, "PersonalPropertyDisposition")
    return ok(public(disp))


@bp.get("/preservation/personal-property-dispositions")
def list_dispositions():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.dispositions.values())
    for field in ("property_id", "work_order_id", "inspection_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [d for d in items if d.get(field) == v]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/personal-property-dispositions/<dispositionId>/authorize-disposal")
def authorize_disposal(dispositionId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin", "Servicer"])
    disp = get_or_404(store.dispositions, dispositionId, "PersonalPropertyDisposition")
    get_body()
    if disp["status"] == "IN_HOLD":
        raise_err("ERR_HOLD_PERIOD_ACTIVE", "Disposition is still within its hold period")
    if disp["status"] != "RELEASE_ELIGIBLE":
        raise_err("ERR_INVALID_STATE", "Disposition is not RELEASE_ELIGIBLE")
    if disp["valuation_cents"] >= 50000 and role != "Servicer":
        raise_err("ERR_DISPOSAL_AUTHORITY_LIMIT", "Valuation at or above 50000 cents requires a Servicer authorizer")
    disp["status"] = "DISPOSAL_AUTHORIZED"
    disp["authorized_by_user_id"] = user_id
    bump(disp)
    return ok(public(disp))


@bp.post("/preservation/personal-property-dispositions/<dispositionId>/dispose")
def dispose_disposition(dispositionId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    disp = get_or_404(store.dispositions, dispositionId, "PersonalPropertyDisposition")
    b = get_body()
    outcome = req_enum(b, "outcome", {"DISPOSED", "DONATED", "RETURNED"})
    if disp["status"] != "DISPOSAL_AUTHORIZED":
        raise_err("ERR_INVALID_STATE", "Disposition is not DISPOSAL_AUTHORIZED")
    disp["status"] = outcome
    bump(disp)
    return ok(public(disp))


# ---- RecurringServicePlan -----------------------------------------------------------

@bp.post("/preservation/recurring-plans")
def create_plan():
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    b = get_body()
    property_id = b.get("property_id")
    if property_id is None:
        raise_err("ERR_INVALID_REQUEST", "Missing required field: property_id")
    if not isinstance(property_id, str):
        raise_err("ERR_INVALID_REQUEST", "property_id must be a string")
    prop = get_or_404(store.properties, property_id, "Property")

    service_type = req_enum(b, "service_type", SERVICE_TYPES)
    season_start_md = _req_md(b, "season_start_md")
    season_end_md = _req_md(b, "season_end_md")
    interval_days = _req_pos_int(b, "interval_days")
    max_per_season = _req_pos_int(b, "max_per_season")
    if _md_tuple(season_end_md) <= _md_tuple(season_start_md):
        raise_err("ERR_INVALID_REQUEST", "season_end_md must be after season_start_md")

    plan = new_entity({
        "property_id": prop["id"],
        "service_type": service_type,
        "season_start_md": season_start_md,
        "season_end_md": season_end_md,
        "interval_days": interval_days,
        "max_per_season": max_per_season,
        "generated_this_season": 0,
        "last_generated_date": None,
        "status": "ACTIVE",
    })
    store.plans[plan["id"]] = plan
    return ok(public(plan), status=201)


def _req_md(b, name):
    v = req_str(b, name)
    parts = v.split("-")
    if len(parts) != 2 or len(parts[0]) != 2 or len(parts[1]) != 2:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an MM-DD string")
    try:
        month = int(parts[0])
        day = int(parts[1])
        if not (1 <= month <= 12 and 1 <= day <= 31):
            raise ValueError
        from datetime import date as _date
        _date(2000, month, day)
    except (ValueError, TypeError):
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an MM-DD string")
    return v


def _md_tuple(md):
    return (int(md[:2]), int(md[3:5]))


def _req_pos_int(b, name):
    v = b.get(name)
    if v is None:
        raise_err("ERR_INVALID_REQUEST", f"Missing required field: {name}")
    if isinstance(v, bool) or not isinstance(v, int) or v < 1:
        raise_err("ERR_INVALID_REQUEST", f"Field {name} must be an integer of at least 1")
    return v


@bp.get("/preservation/recurring-plans/<planId>")
def get_plan(planId):
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    plan = get_or_404(store.plans, planId, "RecurringServicePlan")
    return ok(public(plan))


@bp.get("/preservation/recurring-plans")
def list_plans():
    user_id, role = get_auth()
    require_role(role, ANY_ROLE)
    limit, offset = parse_pagination()
    items = list(store.plans.values())
    for field in ("property_id", "status"):
        v = request.args.get(field)
        if v is not None:
            items = [p for p in items if p.get(field) == v]
    items = sort_created(items)
    page, total = paginate(items, public, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.post("/preservation/recurring-plans/<planId>/suspend")
def suspend_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    plan = get_or_404(store.plans, planId, "RecurringServicePlan")
    get_body()
    if plan["status"] != "ACTIVE":
        raise_err("ERR_INVALID_STATE", "Plan is not ACTIVE")
    plan["status"] = "SUSPENDED"
    bump(plan)
    suspend_plan_cascade(plan)
    return ok(public(plan))


@bp.post("/preservation/recurring-plans/<planId>/resume")
def resume_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    plan = get_or_404(store.plans, planId, "RecurringServicePlan")
    get_body()
    if plan["status"] != "SUSPENDED":
        raise_err("ERR_INVALID_STATE", "Plan is not SUSPENDED")
    prop = store.properties.get(plan["property_id"])
    if prop is not None and prop["occupancy_status"] == "OCCUPIED":
        raise_err("ERR_PROPERTY_OCCUPIED", "Plan may not resume while the property is OCCUPIED")
    today = clock_date()
    start, end = season_window(plan, today.year)
    if not (start <= today <= end):
        raise_err("ERR_SEASON_WINDOW_CLOSED", "Clock date is outside the plan's season window")
    plan["status"] = "ACTIVE"
    bump(plan)
    return ok(public(plan))


@bp.post("/preservation/recurring-plans/<planId>/end")
def end_plan(planId):
    user_id, role = get_auth()
    require_role(role, ["VendorAdmin"])
    plan = get_or_404(store.plans, planId, "RecurringServicePlan")
    get_body()
    if plan["status"] not in ("ACTIVE", "SUSPENDED"):
        raise_err("ERR_INVALID_STATE", "Plan is not ACTIVE or SUSPENDED")
    plan["status"] = "ENDED"
    bump(plan)
    return ok(public(plan))
