"""Accounts, kitchens, the two catalogs, the roster and the computed reads."""

from decimal import Decimal

from flask import Blueprint, request

import db
import middleware
import response
from errors import ApiError
from middleware import (
    ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_PLATFORM_ADMIN,
    ROLE_QUALITY_AUDITOR, ROLE_SERVICE_TECHNICIAN,
)
from routes import common
from services import reports
from util import parse_dt

bp = Blueprint("catalog", __name__)

BILLING_STATUSES = ("CURRENT", "CREDIT_HOLD")
PRIORITY_TIERS = ("STANDARD", "PREMIUM")
SITE_STATUSES = ("ACTIVE", "SUSPENDED", "CLOSED")
PRODUCT_TYPES = ("DETERGENT", "RINSE_AID", "SANITIZER")
MACHINE_CLASSES = ("UNDERCOUNTER", "DOOR_TYPE", "CONVEYOR")
CERT_LEVELS = ("L1", "L2", "SANITATION_CERTIFIED")
TECH_STATUSES = ("AVAILABLE", "OFF_DUTY", "SUSPENDED")


def _unique(table, field, value, label):
    for row in db.rows(table):
        if row[field] == value:
            raise ApiError(
                "ERR_INVALID_REQUEST", "%s is already in use" % label
            )


# --------------------------------------------------------------------------
# customers
# --------------------------------------------------------------------------

@bp.route("/customers", methods=["POST"])
def create_customer():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    name = middleware.f_str(body, "name", required=True, min_len=1, max_len=120)
    goal = middleware.f_int(
        body, "sustainability_goal_water_l", required=True, minimum=1
    )
    billing = middleware.f_enum(body, "billing_status", BILLING_STATUSES)
    row = db.insert("customers", {
        "name": name,
        "sustainability_goal_water_l": goal,
        "billing_status": billing or "CURRENT",
        "equipment_on_placement_value_cents": 0,
        "active_agreement_count": 0,
    })
    return response.created(response.serialize(row))


@bp.route("/customers/<customer_id>", methods=["GET"])
def read_customer(customer_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT
    )
    middleware.scope_customer(role, user_id, customer_id)
    row = middleware.must_exist("customers", customer_id, "Customer")
    return response.ok(response.serialize(row))


# --------------------------------------------------------------------------
# sites
# --------------------------------------------------------------------------

@bp.route("/sites", methods=["POST"])
def create_site():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER)
    body = middleware.body_object()
    customer_id = middleware.f_str(body, "customer_id", required=True)
    name = middleware.f_str(body, "name", required=True, min_len=1, max_len=120)
    region = middleware.f_str(
        body, "region_code", required=True, min_len=2, max_len=4, upper=True
    )
    tier = middleware.f_enum(body, "priority_tier", PRIORITY_TIERS)
    start_minute = middleware.f_int(
        body, "operating_window_start_minute_utc", required=True,
        minimum=0, maximum=1439,
    )
    end_minute = middleware.f_int(
        body, "operating_window_end_minute_utc", required=True,
        minimum=0, maximum=1439,
    )
    water_baseline = middleware.f_num(
        body, "baseline_water_l_per_rack", required=True, gt=0
    )
    energy_baseline = middleware.f_num(
        body, "baseline_kwh_per_rack", required=True, gt=0
    )
    water_cost = middleware.f_int(
        body, "water_cost_cents_per_1000l", required=True, minimum=0
    )
    energy_cost = middleware.f_int(
        body, "energy_cost_cents_per_kwh", required=True, minimum=0
    )
    status = middleware.f_enum(body, "status", SITE_STATUSES)

    middleware.must_reference("customers", customer_id, "customer_id")

    row = db.insert("sites", {
        "customer_id": customer_id,
        "name": name,
        "region_code": region,
        "priority_tier": tier or "STANDARD",
        "operating_window_start_minute_utc": start_minute,
        "operating_window_end_minute_utc": end_minute,
        "baseline_water_l_per_rack": water_baseline,
        "baseline_kwh_per_rack": energy_baseline,
        "water_cost_cents_per_1000l": water_cost,
        "energy_cost_cents_per_kwh": energy_cost,
        "status": status or "ACTIVE",
        "open_ticket_count": 0,
        "service_posture": "NORMAL",
    })
    return response.created(response.serialize(row))


@bp.route("/sites/<site_id>", methods=["GET"])
def read_site(site_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_SERVICE_TECHNICIAN,
        ROLE_QUALITY_AUDITOR,
    )
    middleware.scope_customer(role, user_id, common.owner_of_site(site_id))
    row = middleware.must_exist("sites", site_id, "Site")
    return response.ok(response.serialize(row))


@bp.route("/sites", methods=["GET"])
def list_sites():
    middleware.require_roles(ROLE_ACCOUNT_MANAGER, ROLE_QUALITY_AUDITOR)
    limit, offset = middleware.pagination()
    rows = common.apply_filters(db.rows("sites"), (
        ("customer_id", "customer_id"),
        ("region_code", "region_code"),
        ("service_posture", "service_posture"),
        ("priority_tier", "priority_tier"),
        ("status", "status"),
    ))
    return common.listing(rows, limit, offset)


# --------------------------------------------------------------------------
# chemical catalog
# --------------------------------------------------------------------------

def _sanitizer_fields(body, product_type):
    """The three sanitizer-only fields are required on a sanitizer and
    forbidden on anything else (PRD 3.1)."""
    names = ("sanitizer_min_ppm", "sanitizer_max_ppm", "min_contact_seconds")
    if product_type != "SANITIZER":
        for name in names:
            if name in body and body[name] is not None:
                middleware.bad("%s applies only to a SANITIZER" % name)
        return None, None, None
    low = middleware.f_num(body, "sanitizer_min_ppm", required=True, gt=0)
    high = middleware.f_num(body, "sanitizer_max_ppm", required=True, gt=0)
    contact = middleware.f_int(body, "min_contact_seconds", minimum=1)
    if contact is None:
        if "min_contact_seconds" in body and body["min_contact_seconds"] is None:
            middleware.bad("min_contact_seconds is required")
        contact = 7
    return low, high, contact


@bp.route("/chemical-products", methods=["POST"])
def create_product():
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    sku = middleware.f_str(body, "sku", required=True, min_len=1, max_len=64)
    product_type = middleware.f_enum(
        body, "product_type", PRODUCT_TYPES, required=True
    )
    target = middleware.f_num(
        body, "concentration_target_ppm", required=True, gt=0
    )
    tolerance = middleware.f_num(body, "concentration_tolerance_pct", gt=0)
    spec_dose = middleware.f_num(
        body, "spec_dose_ml_per_rack", required=True, gt=0
    )
    unit_size = middleware.f_int(body, "unit_size_ml", required=True, minimum=0)
    unit_price = middleware.f_int(
        body, "unit_price_cents", required=True, minimum=0
    )
    low, high, contact = _sanitizer_fields(body, product_type)
    if product_type == "SANITIZER":
        if low > target or target > high or high <= low:
            middleware.bad(
                "sanitizer_min_ppm <= concentration_target_ppm <= "
                "sanitizer_max_ppm is required"
            )
    _unique("chemical_products", "sku", sku, "sku")

    row = db.insert("chemical_products", {
        "sku": sku,
        "product_type": product_type,
        "concentration_target_ppm": target,
        "concentration_tolerance_pct": (
            tolerance if tolerance is not None else Decimal("10.00")
        ),
        "spec_dose_ml_per_rack": spec_dose,
        "unit_size_ml": unit_size,
        "unit_price_cents": unit_price,
        "sanitizer_min_ppm": low,
        "sanitizer_max_ppm": high,
        "min_contact_seconds": contact,
    })
    return response.created(response.serialize(row))


@bp.route("/chemical-products/<product_id>", methods=["GET"])
def read_product(product_id):
    middleware.require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN,
        ROLE_QUALITY_AUDITOR,
    )
    row = middleware.must_exist("chemical_products", product_id, "ChemicalProduct")
    return response.ok(response.serialize(row))


# --------------------------------------------------------------------------
# machine catalog
# --------------------------------------------------------------------------

@bp.route("/machine-models", methods=["POST"])
def create_model():
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    model_code = middleware.f_str(
        body, "model_code", required=True, min_len=1, max_len=64
    )
    machine_class = middleware.f_enum(
        body, "machine_class", MACHINE_CLASSES, required=True
    )
    racks_per_hour = middleware.f_int(
        body, "racks_per_hour", required=True, minimum=0
    )
    rated_water = middleware.f_num(
        body, "rated_water_l_per_rack", required=True, gt=0
    )
    rated_kwh = middleware.f_num(
        body, "rated_kwh_per_rack", required=True, gt=0
    )
    min_rinse_temp = middleware.f_int(
        body, "min_final_rinse_temp_f", required=True, minimum=0
    )
    min_wash_temp = middleware.f_int(
        body, "min_wash_temp_f", required=True, minimum=0
    )
    min_pressure = middleware.f_int(
        body, "min_rinse_pressure_psi", required=True, minimum=0
    )
    max_pressure = middleware.f_int(
        body, "max_rinse_pressure_psi", required=True, minimum=0
    )
    equipment_value = middleware.f_int(
        body, "equipment_value_cents", required=True, minimum=1
    )
    max_cycles = middleware.f_int(
        body, "max_cycles_between_calibrations", required=True, minimum=0
    )
    if max_pressure <= min_pressure:
        middleware.bad(
            "max_rinse_pressure_psi must be greater than min_rinse_pressure_psi"
        )
    _unique("machine_models", "model_code", model_code, "model_code")

    row = db.insert("machine_models", {
        "model_code": model_code,
        "machine_class": machine_class,
        "racks_per_hour": racks_per_hour,
        "rated_water_l_per_rack": rated_water,
        "rated_kwh_per_rack": rated_kwh,
        "min_final_rinse_temp_f": min_rinse_temp,
        "min_wash_temp_f": min_wash_temp,
        "min_rinse_pressure_psi": min_pressure,
        "max_rinse_pressure_psi": max_pressure,
        "equipment_value_cents": equipment_value,
        "max_cycles_between_calibrations": max_cycles,
    })
    return response.created(response.serialize(row))


@bp.route("/machine-models/<model_id>", methods=["GET"])
def read_model(model_id):
    middleware.require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN,
        ROLE_QUALITY_AUDITOR,
    )
    row = middleware.must_exist("machine_models", model_id, "MachineModel")
    return response.ok(response.serialize(row))


# --------------------------------------------------------------------------
# technician roster
# --------------------------------------------------------------------------

@bp.route("/technicians", methods=["POST"])
def create_technician():
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    name = middleware.f_str(body, "name", required=True, min_len=1, max_len=120)
    region = middleware.f_str(
        body, "region_code", required=True, min_len=2, max_len=4, upper=True
    )
    cert = middleware.f_enum(
        body, "certification_level", CERT_LEVELS, required=True
    )
    status = middleware.f_enum(body, "status", TECH_STATUSES)
    row = db.insert("technicians", {
        "name": name,
        "region_code": region,
        "certification_level": cert,
        "status": status or "AVAILABLE",
        "open_ticket_count": 0,
        "quality_flag_count": 0,
    })
    return response.created(response.serialize(row))


@bp.route("/technicians/<technician_id>", methods=["GET"])
def read_technician(technician_id):
    middleware.require_roles(
        ROLE_PLATFORM_ADMIN, ROLE_ACCOUNT_MANAGER, ROLE_SERVICE_TECHNICIAN,
        ROLE_QUALITY_AUDITOR,
    )
    row = middleware.must_exist("technicians", technician_id, "Technician")
    return response.ok(response.serialize(row))


@bp.route("/technicians/<technician_id>", methods=["PATCH"])
def update_technician(technician_id):
    middleware.require_roles(ROLE_PLATFORM_ADMIN)
    body = middleware.body_object()
    status = middleware.f_enum(body, "status", TECH_STATUSES)
    cert = middleware.f_enum(body, "certification_level", CERT_LEVELS)
    row = middleware.must_exist("technicians", technician_id, "Technician")
    changed = False
    if status is not None and row["status"] != status:
        row["status"] = status
        changed = True
    if cert is not None and row["certification_level"] != cert:
        row["certification_level"] = cert
        changed = True
    if changed:
        db.mark(row)
    return response.ok(response.serialize(row))


# --------------------------------------------------------------------------
# the two computed reads (PRD 3.9)
# --------------------------------------------------------------------------

def _window_args():
    start_raw = request.args.get("period_start")
    end_raw = request.args.get("period_end")
    if start_raw is None or not start_raw.strip():
        middleware.bad("period_start is required")
    if end_raw is None or not end_raw.strip():
        middleware.bad("period_end is required")
    start = parse_dt(start_raw)
    end = parse_dt(end_raw)
    if start is None:
        middleware.bad("period_start must be an ISO 8601 UTC timestamp")
    if end is None:
        middleware.bad("period_end must be an ISO 8601 UTC timestamp")
    if not start < end:
        middleware.bad("period_start must be earlier than period_end")
    return start, end


@bp.route("/sites/<site_id>/sustainability-report", methods=["GET"])
def sustainability_report(site_id):
    user_id, role = middleware.require_roles(
        ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT, ROLE_QUALITY_AUDITOR
    )
    middleware.scope_customer(role, user_id, common.owner_of_site(site_id))
    start, end = _window_args()
    basis_raw = request.args.get("basis")
    if basis_raw is None or not basis_raw.strip():
        middleware.bad("basis is required")
    if basis_raw not in ("RATED", "TELEMETRY_MEASURED"):
        middleware.bad("basis must be RATED or TELEMETRY_MEASURED")
    site = middleware.must_exist("sites", site_id, "Site")
    data = reports.sustainability_report(site, basis_raw, start, end)
    return response.ok(response.payload(data))


@bp.route("/sites/<site_id>/inspection-dossier", methods=["GET"])
def inspection_dossier(site_id):
    user_id, role = middleware.require_roles(
        ROLE_QUALITY_AUDITOR, ROLE_ACCOUNT_MANAGER, ROLE_CUSTOMER_CONTACT
    )
    middleware.scope_customer(role, user_id, common.owner_of_site(site_id))
    start, end = _window_args()
    site = middleware.must_exist("sites", site_id, "Site")
    data = reports.dossier(site, start, end)
    return response.ok(response.payload(data))
