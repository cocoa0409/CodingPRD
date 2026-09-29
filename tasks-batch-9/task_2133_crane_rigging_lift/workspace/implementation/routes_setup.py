"""Customers, sites, cranes, load-chart rows and personnel."""
from flask import Blueprint

import cascades
import derive
from core import fail, new_record, ordered, parse_dt, respond_list, respond_object, store, touch
from guards import (Body, auth, body, fk, must_exist, pagination, paginate,
                    q_bool, q_enum, q_int, q_str)

bp = Blueprint("setup", __name__)

BILLING_TERMS = ["NET_15", "NET_30", "NET_45"]
CONFIGURATIONS = ["MAIN_BOOM", "LUFFING_JIB", "FIXED_JIB"]
ROLE_TYPES = ["OPERATOR", "RIGGER", "ENGINEER"]
RIGGER_LEVELS = ["NONE", "BASIC", "INTERMEDIATE", "ADVANCED", "MASTER"]
CRANE_STATUSES = ["AVAILABLE", "RESERVED", "IN_SERVICE", "OUT_OF_SERVICE"]
PERSON_STATUSES = ["ACTIVE", "EXPIRED"]
SURVEY_STATUSES = ["NOT_SURVEYED", "SURVEYED"]


# -------------------------------------------------------------- customers ---
@bp.post("/customers")
def create_customer():
    auth(["Dispatcher"])
    b = Body(body())
    account_name = b.string("account_name")
    billing_terms = b.enum("billing_terms", BILLING_TERMS, required=False, default="NET_30")
    rec = new_record({
        "account_name": account_name,
        "billing_terms": billing_terms,
        "credit_hold": False,
        "credit_hold_reason": None,
    })
    store.customers[rec["id"]] = rec
    return respond_object(derive.customer_json(rec), 201)


@bp.get("/customers/<cid>")
def read_customer(cid):
    user_id, role = auth(["Dispatcher", "LiftDirector", "BillingClerk", "Customer"])
    rec = must_exist("customers", cid)
    if role == "Customer" and user_id != rec["id"]:
        fail("ERR_CUSTOMER_SCOPE_VIOLATION", "A customer may only read its own account.")
    return respond_object(derive.customer_json(rec))


@bp.get("/customers")
def list_customers():
    auth(["Dispatcher", "LiftDirector", "BillingClerk"])
    limit, offset = pagination()
    credit_hold = q_bool("credit_hold")
    rows = ordered(store.customers)
    if credit_hold is not None:
        rows = [r for r in rows if r["credit_hold"] == credit_hold]
    items, limit, offset, total = paginate(rows, limit, offset, derive.customer_json)
    return respond_list(items, limit, offset, total)


@bp.post("/customers/<cid>/credit-status")
def set_credit_status(cid):
    auth(["BillingClerk"])
    rec = must_exist("customers", cid)
    b = Body(body())
    credit_hold = b.boolean("credit_hold")
    reason = b.string("reason", required=False, default=None, allow_empty=True)
    rec["credit_hold"] = credit_hold
    rec["credit_hold_reason"] = reason if credit_hold else None
    touch(rec)
    return respond_object(derive.customer_json(rec))


# ------------------------------------------------------------------ sites ---
@bp.post("/sites")
def create_site():
    auth(["Dispatcher"])
    b = Body(body())
    customer_id = b.string("customer_id")
    address_label = b.string("address_label")
    jurisdiction_code = b.string("jurisdiction_code")
    soil = b.integer("soil_bearing_capacity_psf", exclusive_min=0)
    proximity = b.integer("proximity_to_energized_lines_ft", required=False, default=999, minimum=0)
    over_water = b.boolean("over_water", required=False, default=False)
    fk("customers", customer_id)
    rec = new_record({
        "customer_id": customer_id,
        "address_label": address_label,
        "jurisdiction_code": jurisdiction_code,
        "soil_bearing_capacity_psf": soil,
        "proximity_to_energized_lines_ft": proximity,
        "over_water": over_water,
        "survey_status": "NOT_SURVEYED",
        "last_surveyed_at": None,
        "access_notes": None,
        "mat_inventory_available": False,
    })
    store.sites[rec["id"]] = rec
    return respond_object(derive.site_json(rec), 201)


@bp.get("/sites/<sid>")
def read_site(sid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager", "Customer"])
    rec = must_exist("sites", sid)
    return respond_object(derive.site_json(rec))


@bp.get("/sites")
def list_sites():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    limit, offset = pagination()
    customer_id = q_str("customer_id")
    survey_status = q_enum("survey_status", SURVEY_STATUSES)
    rows = ordered(store.sites)
    if customer_id:
        rows = [r for r in rows if r["customer_id"] == customer_id]
    if survey_status:
        rows = [r for r in rows if r["survey_status"] == survey_status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.site_json)
    return respond_list(items, limit, offset, total)


# ----------------------------------------------------------------- cranes ---
@bp.post("/cranes")
def create_crane():
    auth(["Dispatcher"])
    b = Body(body())
    model_code = b.string("model_code")
    class_tons = b.integer("class_tons", exclusive_min=0)
    gross_weight_lb = b.integer("gross_weight_lb", exclusive_min=0)
    counterweight_lb = b.integer("counterweight_lb", minimum=0)
    pad_area = b.number("outrigger_pad_area_sqft", exclusive_min=0)
    max_line_pull_lb = b.integer("max_line_pull_lb", exclusive_min=0)
    rated_max_wind_mph = b.integer("rated_max_wind_mph", exclusive_min=0)
    expires_raw, _expires = b.datetime("annual_inspection_expires_on")
    mob_demob_cents = b.integer("mob_demob_cents", minimum=0)
    hourly_rate_cents = b.integer("hourly_rate_cents", exclusive_min=0)
    rec = new_record({
        "model_code": model_code,
        "class_tons": class_tons,
        "gross_weight_lb": gross_weight_lb,
        "counterweight_lb": counterweight_lb,
        "outrigger_pad_area_sqft": pad_area,
        "max_line_pull_lb": max_line_pull_lb,
        "rated_max_wind_mph": rated_max_wind_mph,
        "annual_inspection_expires_on": expires_raw,
        "mob_demob_cents": mob_demob_cents,
        "hourly_rate_cents": hourly_rate_cents,
        "out_of_service_flag": False,
    })
    store.cranes[rec["id"]] = rec
    return respond_object(derive.crane_json(rec), 201)


@bp.get("/cranes/<cid>")
def read_crane(cid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager", "BillingClerk"])
    rec = must_exist("cranes", cid)
    return respond_object(derive.crane_json(rec))


@bp.get("/cranes")
def list_cranes():
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager"])
    limit, offset = pagination()
    status = q_enum("status", CRANE_STATUSES)
    rows = ordered(store.cranes)
    if status:
        rows = [r for r in rows if derive.crane_status(r) == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.crane_json)
    return respond_list(items, limit, offset, total)


@bp.post("/cranes/<cid>/out-of-service")
def crane_out_of_service(cid):
    auth(["SafetyManager"])
    rec = must_exist("cranes", cid)
    b = Body(body())
    b.string("reason")
    if derive.crane_status(rec) == "OUT_OF_SERVICE":
        fail("ERR_CRANE_OUT_OF_SERVICE", "The crane is already out of service.")
    rec["out_of_service_flag"] = True
    touch(rec)
    cascades.crane_out_of_service_cascade(rec)
    return respond_object(derive.crane_json(rec))


@bp.post("/cranes/<cid>/return-to-service")
def crane_return_to_service(cid):
    auth(["SafetyManager"])
    rec = must_exist("cranes", cid)
    b = Body(body())
    raw, parsed = b.datetime("new_annual_inspection_expires_on")
    if parsed is None or parsed <= store.now:
        fail("ERR_INVALID_REQUEST",
             "new_annual_inspection_expires_on must be strictly after the logical clock.")
    rec["out_of_service_flag"] = False
    rec["annual_inspection_expires_on"] = raw
    touch(rec)
    return respond_object(derive.crane_json(rec))


# ------------------------------------------------------- load chart rows ----
@bp.post("/load-chart-entries")
def create_chart_entry():
    auth(["Dispatcher"])
    b = Body(body())
    crane_id = b.string("crane_id")
    configuration = b.enum("configuration", CONFIGURATIONS)
    boom_length_ft = b.integer("boom_length_ft", exclusive_min=0)
    radius_ft = b.integer("radius_ft", exclusive_min=0)
    gross_capacity_lb = b.integer("gross_capacity_lb", exclusive_min=0)
    fk("cranes", crane_id)
    for row in store.load_chart_entries.values():
        if (row["crane_id"] == crane_id and row["configuration"] == configuration
                and row["boom_length_ft"] == boom_length_ft and row["radius_ft"] == radius_ft):
            fail("ERR_DUPLICATE_CHART_ROW", "That chart row already exists for this crane.")
    rec = new_record({
        "crane_id": crane_id,
        "configuration": configuration,
        "boom_length_ft": boom_length_ft,
        "radius_ft": radius_ft,
        "gross_capacity_lb": gross_capacity_lb,
    }, common=False)
    store.load_chart_entries[rec["id"]] = rec
    return respond_object(derive.chart_json(rec), 201)


@bp.get("/cranes/<cid>/load-chart-entries")
def list_chart_entries(cid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    must_exist("cranes", cid)
    limit, offset = pagination()
    configuration = q_enum("configuration", CONFIGURATIONS)
    boom_length_ft = q_int("boom_length_ft")
    rows = [r for r in ordered(store.load_chart_entries) if r["crane_id"] == cid]
    if configuration:
        rows = [r for r in rows if r["configuration"] == configuration]
    if boom_length_ft is not None:
        rows = [r for r in rows if r["boom_length_ft"] == boom_length_ft]
    items, limit, offset, total = paginate(rows, limit, offset, derive.chart_json)
    return respond_list(items, limit, offset, total)


# -------------------------------------------------------------- personnel ---
@bp.post("/personnel")
def create_personnel():
    auth(["Dispatcher"])
    b = Body(body())
    full_name = b.string("full_name")
    role_type = b.enum("role_type", ROLE_TYPES)
    certification_number = b.string("certification_number")
    expires_raw, _expires = b.datetime("certification_expires_on")
    endorsement = b.integer("endorsement_class_tons", required=False, default=0, minimum=0)
    rigger_level = b.enum("rigger_level", RIGGER_LEVELS, required=False, default="NONE")
    pe_license_state = b.string("pe_license_state", required=False, default=None)
    rec = new_record({
        "full_name": full_name,
        "role_type": role_type,
        "certification_number": certification_number,
        "certification_expires_on": expires_raw,
        "endorsement_class_tons": endorsement,
        "rigger_level": rigger_level,
        "pe_license_state": pe_license_state,
    })
    store.personnel[rec["id"]] = rec
    return respond_object(derive.personnel_json(rec), 201)


@bp.get("/personnel/<pid>")
def read_personnel(pid):
    auth(["Dispatcher", "LiftDirector", "Engineer", "Operator", "SafetyManager"])
    rec = must_exist("personnel", pid)
    return respond_object(derive.personnel_json(rec))


@bp.get("/personnel")
def list_personnel():
    auth(["Dispatcher", "LiftDirector", "Engineer", "SafetyManager"])
    limit, offset = pagination()
    role_type = q_enum("role_type", ROLE_TYPES)
    status = q_enum("status", PERSON_STATUSES)
    rows = ordered(store.personnel)
    if role_type:
        rows = [r for r in rows if r["role_type"] == role_type]
    if status:
        rows = [r for r in rows if derive.person_status(r) == status]
    items, limit, offset, total = paginate(rows, limit, offset, derive.personnel_json)
    return respond_list(items, limit, offset, total)


@bp.post("/personnel/<pid>/certifications")
def recertify(pid):
    auth(["Dispatcher"])
    rec = must_exist("personnel", pid)
    b = Body(body())
    certification_number = b.string("certification_number")
    expires_raw, _expires = b.datetime("certification_expires_on")
    endorsement = b.integer("endorsement_class_tons", required=False, default=None, minimum=0)
    rigger_level = b.enum("rigger_level", RIGGER_LEVELS, required=False, default=None)
    rec["certification_number"] = certification_number
    rec["certification_expires_on"] = expires_raw
    if endorsement is not None:
        rec["endorsement_class_tons"] = endorsement
    if rigger_level is not None:
        rec["rigger_level"] = rigger_level
    touch(rec)
    return respond_object(derive.personnel_json(rec))
