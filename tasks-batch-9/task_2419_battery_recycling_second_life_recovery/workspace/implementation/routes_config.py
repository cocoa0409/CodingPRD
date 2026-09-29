"""Network configuration surfaces: clock, facilities, suppliers, index quotes,
processing lines and permit allotments."""

import re
from decimal import Decimal as D

from flask import Blueprint, g

import calc
import services
from core import (
    ApiError,
    db,
    f_dt,
    f_enum,
    f_int,
    f_num,
    f_str,
    endpoint,
    filter_eq,
    new_row,
    paginate,
    payload,
    sort_rows,
    touch,
)

bp = Blueprint("config", __name__)

STATE_CODE_RE = re.compile(r"^[A-Z]{2}$")

READ_ALL_ROLES = [
    "PlatformAdmin",
    "PlantOperator",
    "ComplianceOfficer",
    "IntakeClerk",
    "AssayTechnician",
    "SettlementAccountant",
    "CertificationOfficer",
    "TriageEngineer",
    "MarketAnalyst",
]


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/_clock/set_current_utc", ["POST"], ["PlatformAdmin"], 200)
def set_current_utc():
    data = payload()
    target = f_dt(data, "to_iso8601")
    db.clock = target
    return {"current_utc": target}


# ---------------------------------------------------------------------------
# facilities
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/facilities", ["POST"], ["PlatformAdmin"], 201)
def create_facility():
    data = payload()
    name = f_str(data, "name")
    state_code = f_str(data, "state_code")
    if not STATE_CODE_RE.match(state_code):
        raise ApiError(
            "ERR_INVALID_REQUEST", "'state_code' must be exactly 2 uppercase letters."
        )
    mech = f_num(data, "mech_capacity_kg_per_day", gt=0)
    hydro = f_num(data, "hydro_capacity_kg_per_day", gt=0)
    status = f_enum(
        data, "status", ("ACTIVE", "SUSPENDED"), required=False, default="ACTIVE"
    )
    row = new_row(
        {
            "name": name,
            "state_code": state_code,
            "status": status,
            "mech_capacity_kg_per_day": mech,
            "hydro_capacity_kg_per_day": hydro,
        }
    )
    db.facilities[row["id"]] = row
    return row


@endpoint(bp, "/recycling/facilities/<facility_id>", ["GET"], READ_ALL_ROLES, 200)
def get_facility(facility_id):
    return services.facility_or_404(facility_id)


@endpoint(
    bp,
    "/recycling/facilities/<facility_id>/capacity-projection",
    ["GET"],
    ["PlatformAdmin", "PlantOperator", "ComplianceOfficer"],
    200,
)
def get_capacity_projection(facility_id):
    data = payload()
    horizon_days = f_int(data, "horizon_days", ge=1)
    facility = services.facility_or_404(facility_id)
    return calc.facility_capacity_projection(facility, horizon_days)


# ---------------------------------------------------------------------------
# suppliers
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/suppliers", ["POST"], ["PlatformAdmin"], 201)
def create_supplier():
    data = payload()
    legal_name = f_str(data, "legal_name")
    channel = f_enum(data, "channel", ("AUTOMAKER", "DISMANTLER", "CONSUMER_COLLECTION"))
    credit_limit_cents = f_int(data, "credit_limit_cents", ge=0)
    contact_email = f_str(data, "contact_email", required=False, default=None)
    row = new_row(
        {
            "legal_name": legal_name,
            "channel": channel,
            "credit_limit_cents": credit_limit_cents,
            "contact_email": contact_email,
            "payable_balance_cents": 0,
            "paid_to_date_cents": 0,
            "credit_hold": False,
            "quality_strike_count": 0,
        }
    )
    db.suppliers[row["id"]] = row
    return row


@endpoint(
    bp,
    "/recycling/suppliers/<supplier_id>",
    ["GET"],
    [
        "PlatformAdmin",
        "SettlementAccountant",
        "ComplianceOfficer",
        "IntakeClerk",
        "PlantOperator",
        "SupplierRep",
    ],
    200,
)
def get_supplier(supplier_id):
    return services.supplier_or_404(supplier_id)


@endpoint(
    bp,
    "/recycling/suppliers/<supplier_id>/quality-strikes",
    ["POST"],
    ["ComplianceOfficer"],
    200,
)
def log_quality_strike(supplier_id):
    data = payload()
    f_str(data, "incident_code")
    supplier = services.supplier_or_404(supplier_id)
    supplier["quality_strike_count"] += 1
    touch(supplier)
    return supplier


# ---------------------------------------------------------------------------
# metal index prices
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/metal-index-prices", ["POST"], ["MarketAnalyst"], 201)
def create_index_price():
    data = payload()
    metal = f_enum(data, "metal", calc.METALS)
    effective_date = f_dt(data, "effective_date")
    price = f_int(data, "price_cents_per_kg", gt=0)
    source_index = f_str(data, "source_index", required=False, default="LME")
    for existing in db.prices.values():
        if existing["metal"] == metal and existing["effective_date"] == effective_date:
            raise ApiError("ERR_DUPLICATE_INDEX_PRICE")
    row = new_row(
        {
            "metal": metal,
            "effective_date": effective_date,
            "price_cents_per_kg": price,
            "source_index": source_index,
        },
        common_fields=False,
    )
    db.prices[row["id"]] = row
    return row


@endpoint(
    bp,
    "/recycling/metal-index-prices",
    ["GET"],
    ["PlatformAdmin", "MarketAnalyst", "SettlementAccountant", "AssayTechnician"],
    200,
)
def list_index_prices():
    data = payload()
    rows = list(db.prices.values())
    metal = data.get("metal")
    if metal is not None:
        rows = [r for r in rows if r["metal"] == metal]
    if data.get("effective_on_or_before") is not None:
        cutoff = f_dt(data, "effective_on_or_before")
        rows = [r for r in rows if r["effective_date"] <= cutoff]
    rows.sort(key=lambda r: (r["effective_date"], r["created_at"], r["_seq"]), reverse=True)
    return paginate(rows, data)


# ---------------------------------------------------------------------------
# permit allotments
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/permit-allotments", ["POST"], ["ComplianceOfficer"], 201)
def create_allotment():
    data = payload()
    facility_id = f_str(data, "facility_id")
    medium = f_enum(data, "medium", ("AIR", "WATER"))
    permit_no = f_str(data, "permit_no")
    valid_from = f_dt(data, "valid_from")
    valid_to = f_dt(data, "valid_to")
    if not valid_to > valid_from:
        raise ApiError("ERR_INVALID_REQUEST", "'valid_to' must be after 'valid_from'.")
    daily_cap = f_num(data, "daily_cap_kg", gt=0)
    services.facility_or_404(facility_id)
    row = new_row(
        {
            "facility_id": facility_id,
            "medium": medium,
            "permit_no": permit_no,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "daily_cap_kg": daily_cap,
            "consumed_kg": D("0.0"),
            "status": "ACTIVE",
            "suspend_reason": None,
        }
    )
    db.allotments[row["id"]] = row
    return row


@endpoint(
    bp,
    "/recycling/permit-allotments",
    ["GET"],
    ["PlatformAdmin", "ComplianceOfficer", "PlantOperator"],
    200,
)
def list_allotments():
    data = payload()
    rows = sort_rows(db.allotments.values())
    rows = filter_eq(rows, data, "facility_id")
    rows = filter_eq(rows, data, "medium")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(
    bp,
    "/recycling/permit-allotments/<allotment_id>",
    ["GET"],
    ["PlatformAdmin", "ComplianceOfficer", "PlantOperator"],
    200,
)
def get_allotment(allotment_id):
    return services.allotment_or_404(allotment_id)


@endpoint(
    bp,
    "/recycling/permit-allotments/<allotment_id>/suspend",
    ["POST"],
    ["ComplianceOfficer"],
    200,
)
def suspend_allotment(allotment_id):
    data = payload()
    reason = f_str(data, "suspend_reason")
    allotment = services.allotment_or_404(allotment_id)
    if allotment["status"] != "ACTIVE":
        raise ApiError("ERR_PERMIT_NOT_ACTIVE")
    allotment["status"] = "SUSPENDED"
    allotment["suspend_reason"] = reason
    touch(allotment)
    return allotment


# ---------------------------------------------------------------------------
# processing lines
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/processing-lines", ["POST"], ["PlatformAdmin"], 201)
def create_line():
    data = payload()
    facility_id = f_str(data, "facility_id")
    line_code = f_str(data, "line_code")
    line_type = f_enum(data, "line_type", ("MECHANICAL", "HYDROMET"))
    chemistry_family = f_enum(data, "chemistry_family", calc.FAMILIES)
    throughput = f_num(data, "throughput_kg_per_hour", gt=0)
    buffer_hours = f_int(
        data,
        "changeover_buffer_hours",
        required=False,
        default=calc.DEFAULT_CHANGEOVER_BUFFER_HOURS,
        ge=0,
    )
    status = f_enum(
        data, "status", ("AVAILABLE", "MAINTENANCE"), required=False, default="AVAILABLE"
    )
    services.facility_or_404(facility_id)
    row = new_row(
        {
            "facility_id": facility_id,
            "line_code": line_code,
            "line_type": line_type,
            "chemistry_family": chemistry_family,
            "throughput_kg_per_hour": throughput,
            "changeover_buffer_hours": buffer_hours,
            "status": status,
        }
    )
    db.lines[row["id"]] = row
    return row


@endpoint(
    bp,
    "/recycling/processing-lines",
    ["GET"],
    ["PlatformAdmin", "PlantOperator", "AssayTechnician", "ComplianceOfficer"],
    200,
)
def list_lines():
    data = payload()
    rows = sort_rows(db.lines.values())
    rows = filter_eq(rows, data, "facility_id")
    rows = filter_eq(rows, data, "line_type")
    return paginate(rows, data)


@endpoint(
    bp,
    "/recycling/processing-lines/<line_id>",
    ["GET"],
    ["PlatformAdmin", "PlantOperator", "AssayTechnician", "ComplianceOfficer"],
    200,
)
def get_line(line_id):
    return services.line_or_404(line_id)


@endpoint(
    bp, "/recycling/processing-lines/<line_id>/replumb", ["POST"], ["PlatformAdmin"], 200
)
def replumb_line(line_id):
    data = payload()
    family = f_enum(data, "chemistry_family", calc.FAMILIES)
    line = services.line_or_404(line_id)
    for campaign in services.campaigns_of_line(line["id"]):
        if campaign["status"] == "RUNNING":
            raise ApiError("ERR_LINE_HAS_RUNNING_CAMPAIGN")
    line["chemistry_family"] = family
    touch(line)
    return line
