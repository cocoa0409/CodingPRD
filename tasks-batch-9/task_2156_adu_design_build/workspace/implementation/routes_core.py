"""Clock, jurisdictions, inspectors, properties, projects, feasibility screenings."""
import re

from flask import Blueprint, g

from common import (
    ALL_ROLES, DB, DATE_RE, authorize, body_json, clock_date, fail, fmt_dt, get_inspector,
    get_jurisdiction, get_project, get_property, listing, new_row, ok, parse_iso_dt,
    pagination, ser, touch, v_array, v_bool, v_date, v_enum, v_int, v_num, v_str,
)
import calc
import services

bp = Blueprint("core", __name__)

CODE_RE = re.compile(r"^[A-Z0-9]{2,8}$")
CERTIFICATIONS = ("STRUCTURAL", "ELECTRICAL", "PLUMBING", "ENVELOPE", "FINAL")
UNIT_TYPES = ("DETACHED_NEW", "ATTACHED", "CONVERSION", "JADU")
PATHWAYS = ("STATUTORY_MINISTERIAL", "LOCAL_ORDINANCE")
PROJECT_STATUSES = (
    "INTAKE", "FEASIBILITY_CLEARED", "PERMITTING", "DESIGN_REVISION",
    "PERMITTED", "UNDER_CONSTRUCTION", "FINALED",
)


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.post("/_clock/set_current_utc")
@authorize("PlatformAdmin")
def set_clock():
    body = body_json()
    raw = v_str(body, "to_iso8601")
    dt = parse_iso_dt(raw, "to_iso8601")
    DB.clock = dt
    # Report the new setting exactly as the operator supplied it.
    return ok({"current_utc": raw})


# ---------------------------------------------------------------------------
# Jurisdictions
# ---------------------------------------------------------------------------
@bp.post("/jurisdictions")
@authorize("PlatformAdmin")
def create_jurisdiction():
    body = body_json()
    name = v_str(body, "name")
    code = v_str(body, "code")
    if not CODE_RE.match(code):
        fail("ERR_VALIDATION", "code must be 2-8 uppercase letters or digits.")
    local_max_detached_sqft = v_int(body, "local_max_detached_sqft", minimum=150)
    local_rear_setback_ft = v_num(body, "local_rear_setback_ft", minimum=0)
    local_side_setback_ft = v_num(body, "local_side_setback_ft", minimum=0)
    local_max_height_ft = v_num(body, "local_max_height_ft", exclusive_min=0)
    plan_check_base_fee_cents = v_int(body, "plan_check_base_fee_cents", minimum=0)
    plan_check_rate_per_sqft_cents = v_int(body, "plan_check_rate_per_sqft_cents", minimum=0)
    impact_fee_per_sqft_cents = v_int(body, "impact_fee_per_sqft_cents", minimum=0)
    utility_capacity_fee_cents = v_int(body, "utility_capacity_fee_cents", minimum=0)
    correction_response_days = v_int(body, "correction_response_days", required=False,
                                     default=60, minimum=1)
    separate_meter_required = v_bool(body, "separate_meter_required", required=False,
                                     default=False)
    str_min_lease_days = v_int(body, "str_min_lease_days", required=False, default=30, minimum=1)
    str_prohibited = v_bool(body, "str_prohibited", required=False, default=False)

    for existing in DB.jurisdictions.values():
        if existing["code"] == code:
            fail("ERR_DUPLICATE_JURISDICTION_CODE", "Jurisdiction code already in use.")

    row = new_row()
    row.update(
        name=name,
        code=code,
        local_max_detached_sqft=local_max_detached_sqft,
        local_rear_setback_ft=local_rear_setback_ft,
        local_side_setback_ft=local_side_setback_ft,
        local_max_height_ft=local_max_height_ft,
        correction_response_days=correction_response_days,
        plan_check_base_fee_cents=plan_check_base_fee_cents,
        plan_check_rate_per_sqft_cents=plan_check_rate_per_sqft_cents,
        impact_fee_per_sqft_cents=impact_fee_per_sqft_cents,
        utility_capacity_fee_cents=utility_capacity_fee_cents,
        separate_meter_required=separate_meter_required,
        str_min_lease_days=str_min_lease_days,
        str_prohibited=str_prohibited,
    )
    DB.jurisdictions[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/jurisdictions/<jid>")
@authorize(*ALL_ROLES)
def read_jurisdiction(jid):
    return ok(ser(get_jurisdiction(jid)))


# ---------------------------------------------------------------------------
# Inspectors
# ---------------------------------------------------------------------------
@bp.post("/inspectors")
@authorize("PlatformAdmin")
def create_inspector():
    body = body_json()
    if isinstance(body.get("jurisdiction_id"), str):
        get_jurisdiction(body["jurisdiction_id"])
    jurisdiction_id = v_str(body, "jurisdiction_id")
    get_jurisdiction(jurisdiction_id)
    full_name = v_str(body, "full_name")
    certifications = v_array(body, "certifications", item_type=str, non_empty=True)
    for cert in certifications:
        if cert not in CERTIFICATIONS:
            fail("ERR_VALIDATION", "certifications members must be drawn from %s."
                 % list(CERTIFICATIONS))
    daily_capacity = v_int(body, "daily_capacity", required=False, default=4,
                           minimum=1, maximum=12)
    status = v_enum(body, "status", ("ACTIVE", "INACTIVE"), required=False, default="ACTIVE")

    row = new_row()
    row.update(
        jurisdiction_id=jurisdiction_id,
        full_name=full_name,
        certifications=certifications,
        daily_capacity=daily_capacity,
        status=status,
    )
    DB.inspectors[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/inspectors/<iid>")
@authorize(*ALL_ROLES)
def read_inspector(iid):
    return ok(ser(get_inspector(iid)))


@bp.get("/inspectors")
@authorize(*ALL_ROLES)
def list_inspectors():
    from flask import request
    rows = list(DB.inspectors.values())
    jid = request.args.get("jurisdiction_id")
    if jid:
        rows = [r for r in rows if r["jurisdiction_id"] == jid]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


@bp.get("/inspectors/<iid>/availability")
@authorize(*ALL_ROLES)
def inspector_availability(iid):
    from flask import request
    inspector = get_inspector(iid)
    slot_date = request.args.get("slot_date")
    if slot_date is None or slot_date == "":
        fail("ERR_VALIDATION", "slot_date is required.")
    if not DATE_RE.match(slot_date):
        fail("ERR_VALIDATION", "slot_date must be a YYYY-MM-DD date.")
    booked = [
        a for a in DB.appointments.values()
        if a["inspector_id"] == iid
        and a["slot_date"] == slot_date
        and a["status"] in ("SCHEDULED", "PARTIAL")
    ]
    booked_count = len(booked)
    return ok(
        {
            "inspector_id": iid,
            "slot_date": slot_date,
            "daily_capacity": inspector["daily_capacity"],
            "booked_count": booked_count,
            "remaining_slots": inspector["daily_capacity"] - booked_count,
        }
    )


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------
@bp.post("/properties")
@authorize("PlatformAdmin", "DesignLead")
def create_property():
    body = body_json()
    if isinstance(body.get("jurisdiction_id"), str):
        get_jurisdiction(body["jurisdiction_id"])
    jurisdiction_id = v_str(body, "jurisdiction_id")
    get_jurisdiction(jurisdiction_id)
    address_line = v_str(body, "address_line")
    lot_sqft = v_int(body, "lot_sqft", minimum=1)
    existing_dwelling_sqft = v_int(body, "existing_dwelling_sqft", minimum=1)
    electrical_service_amps = v_int(body, "electrical_service_amps")
    if electrical_service_amps not in (100, 125, 150, 200, 400):
        fail("ERR_VALIDATION", "electrical_service_amps must be one of 100, 125, 150, 200, 400.")
    existing_water_meter_size_in = v_num(body, "existing_water_meter_size_in",
                                         allowed=(0.625, 0.75, 1.0, 1.5))
    pre_adu_value_cents = v_int(body, "pre_adu_value_cents", minimum=1)
    occupied = v_bool(body, "occupied", required=False, default=True)
    in_str_overlay = v_bool(body, "in_str_overlay", required=False, default=False)
    existing_mortgage_balance_cents = v_int(body, "existing_mortgage_balance_cents",
                                            required=False, default=0, minimum=0)

    row = new_row()
    row.update(
        jurisdiction_id=jurisdiction_id,
        address_line=address_line,
        lot_sqft=lot_sqft,
        existing_dwelling_sqft=existing_dwelling_sqft,
        occupied=occupied,
        in_str_overlay=in_str_overlay,
        electrical_service_amps=electrical_service_amps,
        existing_water_meter_size_in=existing_water_meter_size_in,
        pre_adu_value_cents=pre_adu_value_cents,
        existing_mortgage_balance_cents=existing_mortgage_balance_cents,
    )
    DB.properties[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/properties/<pid>")
@authorize(*ALL_ROLES)
def read_property(pid):
    return ok(ser(get_property(pid)))


@bp.get("/properties")
@authorize(*ALL_ROLES)
def list_properties():
    from flask import request
    rows = list(DB.properties.values())
    jid = request.args.get("jurisdiction_id")
    if jid:
        rows = [r for r in rows if r["jurisdiction_id"] == jid]
    return listing(rows)


# ---------------------------------------------------------------------------
# ADU projects
# ---------------------------------------------------------------------------
@bp.post("/adu-projects")
@authorize("DesignLead")
def create_project():
    body = body_json()
    if isinstance(body.get("property_id"), str):
        get_property(body["property_id"])
    property_id = v_str(body, "property_id")
    prop = get_property(property_id)

    expected_property_version = v_int(body, "expected_property_version")
    unit_type = v_enum(body, "unit_type", UNIT_TYPES)
    proposed_sqft = v_int(body, "proposed_sqft", minimum=150, maximum=1200)
    proposed_height_ft = v_num(body, "proposed_height_ft", exclusive_min=0, maximum=35)
    rear_setback_ft = v_num(body, "rear_setback_ft", minimum=0)
    side_setback_ft = v_num(body, "side_setback_ft", minimum=0)
    bedrooms = v_int(body, "bedrooms", minimum=0, maximum=4)
    contract_base_price_cents = v_int(body, "contract_base_price_cents", minimum=1)

    if expected_property_version != prop["version"]:
        fail("ERR_STALE_PROPERTY_VERSION", "Property version has moved on.")

    row = new_row()
    row.update(
        property_id=property_id,
        unit_type=unit_type,
        proposed_sqft=proposed_sqft,
        proposed_height_ft=proposed_height_ft,
        rear_setback_ft=rear_setback_ft,
        side_setback_ft=side_setback_ft,
        bedrooms=bedrooms,
        contract_base_price_cents=contract_base_price_cents,
        status="INTAKE",
        financing_state="UNFUNDED",
        approved_pathway=None,
        max_allowed_sqft=0,
        contract_price_current_cents=contract_base_price_cents,
        approved_change_days=0,
        approved_change_order_count=0,
        total_permit_fee_cents=0,
    )
    DB.projects[row["id"]] = row
    touch(prop)
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>")
@authorize(*ALL_ROLES)
def read_project(pid):
    return ok(ser(get_project(pid)))


@bp.get("/adu-projects")
@authorize(*ALL_ROLES)
def list_projects():
    from flask import request
    rows = list(DB.projects.values())
    prop_id = request.args.get("property_id")
    if prop_id:
        rows = [r for r in rows if r["property_id"] == prop_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return listing(rows)


# ---------------------------------------------------------------------------
# Feasibility screenings
# ---------------------------------------------------------------------------
@bp.post("/adu-projects/<pid>/feasibility-screenings")
@authorize("DesignLead")
def create_screening(pid):
    project = get_project(pid)
    body = body_json()
    pathway = v_enum(body, "pathway", PATHWAYS)
    prop = DB.properties.get(project["property_id"])
    jur = DB.jurisdictions.get(prop["jurisdiction_id"])

    result = calc.feasibility_screening(project, prop, jur, pathway)
    row = new_row(common=False)
    row["adu_project_id"] = project["id"]
    row["pathway"] = pathway
    row.update(result)
    DB.screenings[row["id"]] = row
    return ok(ser(row), 201)


@bp.get("/adu-projects/<pid>/feasibility-screenings")
@authorize(*ALL_ROLES)
def list_screenings(pid):
    from flask import request
    get_project(pid)
    rows = [s for s in DB.screenings.values() if s["adu_project_id"] == pid]
    pathway = request.args.get("pathway")
    if pathway:
        rows = [r for r in rows if r["pathway"] == pathway]
    return listing(rows)


@bp.post("/adu-projects/<pid>/select-pathway")
@authorize("DesignLead")
def select_pathway(pid):
    project = get_project(pid)
    body = body_json()

    raw_screening = body.get("screening_id")
    if isinstance(raw_screening, str):
        screening = DB.screenings.get(raw_screening)
        if screening is None or screening["adu_project_id"] != project["id"]:
            fail("ERR_SCREENING_NOT_FOUND", "Screening not found for this project.")
    screening_id = v_str(body, "screening_id")
    screening = DB.screenings.get(screening_id)
    if screening is None or screening["adu_project_id"] != project["id"]:
        fail("ERR_SCREENING_NOT_FOUND", "Screening not found for this project.")

    if project["status"] != "INTAKE":
        fail("ERR_PROJECT_PHASE_INVALID", "Project has already left intake.")
    if screening["verdict"] not in ("PASS", "PASS_WITH_CONDITIONS"):
        fail("ERR_FEASIBILITY_FAILED", "Screening verdict is FAIL.")

    project["status"] = "FEASIBILITY_CLEARED"
    project["approved_pathway"] = screening["pathway"]
    project["max_allowed_sqft"] = screening["max_allowed_sqft"]
    touch(project)
    return ok(ser(project))
