"""Facilities, the revenue-code reference table and departments (PRD 3.1)."""

from flask import Blueprint

import validate
from auth import ALL_ROLES, SA, require
from derive import find, recompute_facility
from envelope import list_response, ok
from errors import fail
from store import STORE, serialize

bp = Blueprint("routes_facilities", __name__)

ROUNDING_MODES = ("NEAREST_CENT", "NEAREST_DOLLAR", "PSYCHOLOGICAL_99")
DUPLICATE_MODES = ("STRICT_CODE", "FUZZY_DESCRIPTION")
CODE_TYPES = ("CPT", "HCPCS", "REV_ONLY", "CDM_INTERNAL")
PRICING_CLASSES = ("SUPPLY", "PHARMACY", "PROCEDURE", "ROOM_AND_BOARD")
REVENUE_CODE_STATUSES = ("ACTIVE", "RETIRED")


def body_facility(data, required=True):
    """Rank 4 — a body facility_id must resolve before schema checks."""
    if "facility_id" in data and isinstance(data.get("facility_id"), str):
        facility = STORE.facilities.get(data["facility_id"])
        if facility is None:
            fail(
                "ERR_FACILITY_NOT_FOUND",
                "Facility %s does not exist." % data["facility_id"],
            )
        return facility
    if required:
        validate.req_id(data, "facility_id")
    return None


# ---------------------------------------------------------------------------
# Facilities
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/facilities", methods=["POST"])
def create_facility():
    require(SA)
    data = validate.body()
    name = validate.req_string(data, "name")
    ccn = validate.req_string(data, "cms_certification_number")
    rounding_mode = validate.opt_enum(data, "rounding_mode", ROUNDING_MODES, "NEAREST_DOLLAR")
    markup_limit = validate.opt_int(data, "aggregate_markup_limit_bp", 40000)
    volume_growth = validate.opt_int(data, "volume_growth_bp", 10500)
    lookback = validate.opt_int(data, "impact_lookback_days", 90)
    duplicate_mode = validate.opt_enum(
        data, "duplicate_detection_mode", DUPLICATE_MODES, "STRICT_CODE"
    )
    for row in STORE.facilities.values():
        if row["cms_certification_number"] == ccn:
            fail("ERR_DUPLICATE_KEY", "cms_certification_number is already in use.")
    facility = {
        "name": name,
        "cms_certification_number": ccn,
        "rounding_mode": rounding_mode,
        "aggregate_markup_limit_bp": markup_limit,
        "volume_growth_bp": volume_growth,
        "impact_lookback_days": lookback,
        "duplicate_detection_mode": duplicate_mode,
        "chargemaster_posture": "OPEN",
        "active_item_count": 0,
        "aggregate_gross_charge_cents": 0,
        "aggregate_cost_basis_cents": 0,
        "aggregate_markup_ratio_bp": 0,
        "stale_price_item_count": 0,
        "published_transparency_file_id": None,
        "transparency_status": "NEEDS_REFRESH",
    }
    STORE.stamp_new(facility)
    STORE.facilities[facility["id"]] = facility
    return ok(serialize(facility), 201)


@bp.route("/chargemaster/facilities/<facility_id>", methods=["GET"])
def read_facility(facility_id):
    require(ALL_ROLES)
    facility = find(STORE.facilities, facility_id, "ERR_FACILITY_NOT_FOUND", "Facility")
    return ok(serialize(facility))


@bp.route("/chargemaster/facilities/<facility_id>", methods=["PATCH"])
def patch_facility(facility_id):
    require(SA)
    facility = find(STORE.facilities, facility_id, "ERR_FACILITY_NOT_FOUND", "Facility")
    data = validate.body()
    expected = validate.req_int(data, "expected_facility_version", 0)
    rounding_mode = validate.opt_enum(data, "rounding_mode", ROUNDING_MODES)
    markup_limit = validate.opt_int(data, "aggregate_markup_limit_bp")
    volume_growth = validate.opt_int(data, "volume_growth_bp")
    lookback = validate.opt_int(data, "impact_lookback_days")
    duplicate_mode = validate.opt_enum(data, "duplicate_detection_mode", DUPLICATE_MODES)
    if expected != facility["version"]:
        fail(
            "ERR_STALE_FACILITY_VERSION",
            "expected_facility_version %s does not match the live facility version %s."
            % (expected, facility["version"]),
        )
    if rounding_mode is not None:
        facility["rounding_mode"] = rounding_mode
    if markup_limit is not None:
        facility["aggregate_markup_limit_bp"] = markup_limit
    if volume_growth is not None:
        facility["volume_growth_bp"] = volume_growth
    if lookback is not None:
        facility["impact_lookback_days"] = lookback
    if duplicate_mode is not None:
        facility["duplicate_detection_mode"] = duplicate_mode
    recompute_facility(facility, bump=True)
    return ok(serialize(facility))


# ---------------------------------------------------------------------------
# Revenue codes
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/revenue-codes", methods=["POST"])
def create_revenue_code():
    require(SA)
    data = validate.body()
    code = validate.req_string(data, "code")
    description = validate.req_string(data, "description")
    requires_hcpcs = validate.req_bool(data, "requires_hcpcs")
    allowed_code_types = validate.req_str_list(data, "allowed_code_types", CODE_TYPES)
    pricing_class = validate.req_enum(data, "pricing_class", PRICING_CLASSES)
    status = validate.opt_enum(data, "status", REVENUE_CODE_STATUSES, "ACTIVE")
    for row in STORE.revenue_codes.values():
        if row["code"] == code:
            fail("ERR_DUPLICATE_KEY", "Revenue code %s already exists." % code)
    revenue_code = {
        "code": code,
        "description": description,
        "requires_hcpcs": requires_hcpcs,
        "allowed_code_types": allowed_code_types,
        "status": status,
        "pricing_class": pricing_class,
    }
    STORE.stamp_new(revenue_code, versioned=False)
    STORE.revenue_codes[revenue_code["id"]] = revenue_code
    return ok(serialize(revenue_code), 201)


@bp.route("/chargemaster/revenue-codes", methods=["GET"])
def list_revenue_codes():
    require(ALL_ROLES)
    code = validate.query_filter("code")
    status = validate.query_filter("status")
    pricing_class = validate.query_filter("pricing_class")

    def keep(row):
        if code is not None and row["code"] != code:
            return False
        if status is not None and row["status"] != status:
            return False
        if pricing_class is not None and row["pricing_class"] != pricing_class:
            return False
        return True

    rows = STORE.ordered(STORE.revenue_codes, keep)
    return list_response(rows, serialize)


@bp.route("/chargemaster/revenue-codes/<revenue_code_id>", methods=["GET"])
def read_revenue_code(revenue_code_id):
    require(ALL_ROLES)
    row = find(
        STORE.revenue_codes,
        revenue_code_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "RevenueCode",
    )
    return ok(serialize(row))


@bp.route("/chargemaster/revenue-codes/<revenue_code_id>/retire", methods=["POST"])
def retire_revenue_code(revenue_code_id):
    require(SA)
    row = find(
        STORE.revenue_codes,
        revenue_code_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "RevenueCode",
    )
    row["status"] = "RETIRED"
    return ok(serialize(row))


# ---------------------------------------------------------------------------
# Departments
# ---------------------------------------------------------------------------
@bp.route("/chargemaster/departments", methods=["POST"])
def create_department():
    require(SA)
    data = validate.body()
    facility = body_facility(data)
    name = validate.req_string(data, "name")
    cost_center_code = validate.req_string(data, "cost_center_code")
    manager_user_id = validate.req_string(data, "manager_user_id")
    allowed = validate.opt_str_list(data, "allowed_revenue_code_values", [])
    for row in STORE.departments.values():
        if row["facility_id"] == facility["id"] and row["cost_center_code"] == cost_center_code:
            fail("ERR_DUPLICATE_KEY", "cost_center_code is already used in this facility.")
    department = {
        "facility_id": facility["id"],
        "name": name,
        "cost_center_code": cost_center_code,
        "allowed_revenue_code_values": allowed,
        "manager_user_id": manager_user_id,
        "capture_hold": False,
        "unresolved_finding_amount_cents": 0,
        "recovered_charge_cents": 0,
        "open_request_count": 0,
    }
    STORE.stamp_new(department)
    STORE.departments[department["id"]] = department
    return ok(serialize(department), 201)


@bp.route("/chargemaster/departments", methods=["GET"])
def list_departments():
    require(ALL_ROLES)
    facility_id = validate.query_filter("facility_id")
    capture_hold = validate.query_bool("capture_hold")

    def keep(row):
        if facility_id is not None and row["facility_id"] != facility_id:
            return False
        if capture_hold is not None and row["capture_hold"] != capture_hold:
            return False
        return True

    rows = STORE.ordered(STORE.departments, keep)
    return list_response(rows, serialize)


@bp.route("/chargemaster/departments/<department_id>", methods=["GET"])
def read_department(department_id):
    require(ALL_ROLES)
    row = find(
        STORE.departments,
        department_id,
        "ERR_GOVERNANCE_RESOURCE_NOT_FOUND",
        "Department",
    )
    return ok(serialize(row))
