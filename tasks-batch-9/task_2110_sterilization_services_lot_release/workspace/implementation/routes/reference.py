"""Reference data: customers, products, emission permits, chambers, recipes,
qualifications and dose audits."""

from decimal import Decimal

from flask import Blueprint

import response
import validation as V
from db import db
from errors import ApiError
from middleware import authenticate, customer_scope
from routes.common import fetch, paginate
from services import calc
from services.domain import (by_seq, new_record, touch)

bp = Blueprint("reference", __name__)

MODALITIES = ("ETO", "GAMMA", "EBEAM")


# =====================================================================
# Customer
# =====================================================================
@bp.post("/sterilization/customers")
def create_customer():
    authenticate("RegulatoryAdmin")
    body = V.body()
    name = V.req_string(body, "name", 1, None)
    account_code = V.req_string(body, "account_code", 1, 32)
    contracted = V.req_string_list(body, "contracted_modalities", MODALITIES)
    status = V.opt_enum(body, "status", ("ACTIVE", "SUSPENDED"), "ACTIVE")

    for existing in db.customers.values():
        if existing["account_code"] == account_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "account_code '%s' is already registered." % account_code)

    customer = new_record({
        "name": name,
        "account_code": account_code,
        "contracted_modalities": contracted,
        "status": status,
        "open_lot_count": 0,
    })
    db.customers[customer["id"]] = customer
    return response.object_response(customer, 201)


@bp.get("/sterilization/customers/<customer_id>")
def read_customer(customer_id):
    authenticate("RegulatoryAdmin", "CustomerRep", "QualityReleaseOfficer")
    customer = fetch("customers", customer_id)
    customer_scope(customer["id"])
    return response.object_response(customer)


@bp.get("/sterilization/customers")
def list_customers():
    authenticate("RegulatoryAdmin")
    limit, offset = V.pagination()
    from flask import request
    status = request.args.get("status")
    rows = [c for c in db.customers.values()
            if status is None or c["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/sterilization/customers/<customer_id>/status")
def set_customer_status(customer_id):
    authenticate("RegulatoryAdmin")
    body = V.body()
    status = V.req_enum(body, "status", ("ACTIVE", "SUSPENDED"))
    customer = fetch("customers", customer_id)
    if customer["status"] != status:
        customer["status"] = status
        touch(customer)
    return response.object_response(customer)


@bp.get("/sterilization/customers/<customer_id>/products")
def list_customer_products(customer_id):
    authenticate("RegulatoryAdmin", "CustomerRep")
    limit, offset = V.pagination()
    customer = fetch("customers", customer_id)
    customer_scope(customer["id"])
    rows = [p for p in db.products.values() if p["customer_id"] == customer_id]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# =====================================================================
# Product
# =====================================================================
@bp.post("/sterilization/products")
def create_product():
    authenticate("RegulatoryAdmin")
    body = V.body()
    customer_id = V.req_id(body, "customer_id")
    product_code = V.req_string(body, "product_code", 1, 32)
    pallet_mass_kg = V.req_number(body, "pallet_mass_kg", gt=0)
    pallet_volume_m3 = V.req_number(body, "pallet_volume_m3", gt=0)
    max_allowed_dose_kgy = V.req_number(body, "max_allowed_dose_kgy", gt=0)
    max_cumulative_dose_kgy = V.req_number(body, "max_cumulative_dose_kgy", gt=0)
    eto_limit = V.req_number(body, "eto_residual_limit_ppm", ge=0)
    ech_limit = V.req_number(body, "ech_residual_limit_ppm", ge=0)
    requires_aeration = V.opt_bool(body, "requires_aeration", True)
    status = V.opt_enum(body, "status", ("ACTIVE", "DISCONTINUED"), "ACTIVE")

    customer = fetch("customers", customer_id)

    for existing in db.products.values():
        if existing["customer_id"] == customer_id and existing["product_code"] == product_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "product_code '%s' already exists for this customer." % product_code)

    product = new_record({
        "customer_id": customer["id"],
        "product_code": product_code,
        "pallet_mass_kg": pallet_mass_kg,
        "pallet_volume_m3": pallet_volume_m3,
        "max_allowed_dose_kgy": max_allowed_dose_kgy,
        "max_cumulative_dose_kgy": max_cumulative_dose_kgy,
        "eto_residual_limit_ppm": eto_limit,
        "ech_residual_limit_ppm": ech_limit,
        "requires_aeration": requires_aeration,
        "status": status,
    })
    db.products[product["id"]] = product
    return response.object_response(product, 201)


@bp.get("/sterilization/products/<product_id>")
def read_product(product_id):
    authenticate("RegulatoryAdmin", "CustomerRep", "CycleOperator", "QualityReleaseOfficer")
    product = fetch("products", product_id)
    customer_scope(product["customer_id"])
    return response.object_response(product)


# =====================================================================
# EmissionPermit
# =====================================================================
@bp.post("/sterilization/emission-permits")
def create_permit():
    authenticate("RegulatoryAdmin")
    body = V.body()
    permit_code = V.req_string(body, "permit_code", 1, 32)
    permit_year = V.req_int(body, "permit_year", minimum=2000)
    allowance = V.req_number(body, "annual_allowance_kg", gt=0)
    max_concurrent = V.req_int(body, "max_concurrent_eto_cycles", minimum=1)

    for existing in db.permits.values():
        if existing["permit_code"] == permit_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "permit_code '%s' is already registered." % permit_code)

    permit = new_record({
        "permit_code": permit_code,
        "permit_year": permit_year,
        "annual_allowance_kg": allowance,
        "consumed_kg_ytd": Decimal("0.000"),
        "total_emission_fee_usd": Decimal("0.00"),
        "max_concurrent_eto_cycles": max_concurrent,
        "status": "ACTIVE",
    })
    db.permits[permit["id"]] = permit
    return response.object_response(permit, 201)


@bp.get("/sterilization/emission-permits/<permit_id>")
def read_permit(permit_id):
    authenticate("RegulatoryAdmin", "CycleOperator")
    return response.object_response(fetch("permits", permit_id))


PERMIT_TRANSITIONS = {
    ("ACTIVE", "SUSPENDED"),
    ("SUSPENDED", "ACTIVE"),
    ("ACTIVE", "EXPIRED"),
    ("SUSPENDED", "EXPIRED"),
}


@bp.post("/sterilization/emission-permits/<permit_id>/status")
def set_permit_status(permit_id):
    authenticate("RegulatoryAdmin")
    body = V.body()
    status = V.req_enum(body, "status", ("ACTIVE", "SUSPENDED", "EXPIRED"))
    permit = fetch("permits", permit_id)
    if (permit["status"], status) not in PERMIT_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE",
                       "Permit cannot move %s -> %s." % (permit["status"], status))
    permit["status"] = status
    touch(permit)
    return response.object_response(permit)


@bp.get("/sterilization/emission-permits/<permit_id>/chambers")
def list_permit_chambers(permit_id):
    authenticate("RegulatoryAdmin", "CycleOperator")
    limit, offset = V.pagination()
    fetch("permits", permit_id)
    rows = [c for c in db.chambers.values() if c["permit_id"] == permit_id]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


# =====================================================================
# Chamber
# =====================================================================
@bp.post("/sterilization/chambers")
def create_chamber():
    authenticate("RegulatoryAdmin")
    body = V.body()
    permit_id = V.req_id(body, "permit_id")
    chamber_code = V.req_string(body, "chamber_code", 1, 32)
    modality = V.req_enum(body, "modality", MODALITIES)
    pallet_capacity = V.req_int(body, "pallet_capacity", minimum=1)
    turnaround_minutes = V.req_int(body, "turnaround_minutes", minimum=0)
    abatement = V.req_number(body, "abatement_efficiency_pct", ge=0, le=100)

    permit = fetch("permits", permit_id)

    for existing in db.chambers.values():
        if existing["chamber_code"] == chamber_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "chamber_code '%s' is already registered." % chamber_code)

    chamber = new_record({
        "permit_id": permit["id"],
        "chamber_code": chamber_code,
        "modality": modality,
        "pallet_capacity": pallet_capacity,
        "turnaround_minutes": turnaround_minutes,
        "abatement_efficiency_pct": abatement,
        "status": "AVAILABLE",
    })
    db.chambers[chamber["id"]] = chamber
    return response.object_response(chamber, 201)


@bp.get("/sterilization/chambers/<chamber_id>")
def read_chamber(chamber_id):
    authenticate("RegulatoryAdmin", "CycleOperator")
    return response.object_response(fetch("chambers", chamber_id))


CHAMBER_TRANSITIONS = {
    ("AVAILABLE", "MAINTENANCE"),
    ("MAINTENANCE", "AVAILABLE"),
    ("AVAILABLE", "DECOMMISSIONED"),
    ("MAINTENANCE", "DECOMMISSIONED"),
}


@bp.post("/sterilization/chambers/<chamber_id>/status")
def set_chamber_status(chamber_id):
    authenticate("RegulatoryAdmin")
    body = V.body()
    status = V.req_enum(body, "status", ("AVAILABLE", "MAINTENANCE", "DECOMMISSIONED"))
    chamber = fetch("chambers", chamber_id)
    if (chamber["status"], status) not in CHAMBER_TRANSITIONS:
        raise ApiError("ERR_INVALID_STATE",
                       "Chamber cannot move %s -> %s." % (chamber["status"], status))
    chamber["status"] = status
    touch(chamber)
    return response.object_response(chamber)


# =====================================================================
# CycleRecipe
# =====================================================================
@bp.post("/sterilization/cycle-recipes")
def create_recipe():
    authenticate("RegulatoryAdmin")
    body = V.body()
    recipe_code = V.req_string(body, "recipe_code", 1, 32)
    modality = V.req_enum(body, "modality", MODALITIES)
    density_min = V.req_number(body, "density_min_g_per_cm3", gt=0)
    density_max = V.req_number(body, "density_max_g_per_cm3", gt=density_min)
    target_dose = V.req_number(body, "target_dose_kgy", gt=0)
    min_dose = V.req_number(body, "min_dose_kgy", gt=0)
    max_dose = V.req_number(body, "max_dose_kgy", gt=min_dose)
    dose_basis = V.req_enum(body, "dose_basis", ("ROUTINE_MEAN", "MIN_ZONE"))
    aeration_base_hours = V.req_int(body, "aeration_base_hours", minimum=0)
    required_min_zone = V.req_int(body, "required_min_zone_dosimeters", minimum=0)
    required_routine = V.req_int(body, "required_routine_dosimeters", minimum=0)
    required_bi = V.req_int(body, "required_biological_indicators", minimum=0)

    for existing in db.recipes.values():
        if existing["recipe_code"] == recipe_code:
            raise ApiError("ERR_DUPLICATE_CODE",
                           "recipe_code '%s' is already registered." % recipe_code)

    recipe = new_record({
        "recipe_code": recipe_code,
        "modality": modality,
        "density_min_g_per_cm3": density_min,
        "density_max_g_per_cm3": density_max,
        "target_dose_kgy": target_dose,
        "min_dose_kgy": min_dose,
        "max_dose_kgy": max_dose,
        "dose_basis": dose_basis,
        "aeration_base_hours": aeration_base_hours,
        "required_min_zone_dosimeters": required_min_zone,
        "required_routine_dosimeters": required_routine,
        "required_biological_indicators": required_bi,
        "status": "DRAFT",
    })
    db.recipes[recipe["id"]] = recipe
    return response.object_response(recipe, 201)


@bp.get("/sterilization/cycle-recipes/<recipe_id>")
def read_recipe(recipe_id):
    authenticate("RegulatoryAdmin", "CycleOperator", "DosimetryAnalyst", "QualityReleaseOfficer")
    return response.object_response(fetch("recipes", recipe_id))


@bp.post("/sterilization/cycle-recipes/<recipe_id>/approve")
def approve_recipe(recipe_id):
    authenticate("RegulatoryAdmin")
    recipe = fetch("recipes", recipe_id)
    if recipe["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE", "Only a DRAFT recipe may be approved.")
    recipe["status"] = "APPROVED"
    touch(recipe)
    return response.object_response(recipe)


# =====================================================================
# ProductQualification and DoseAudit
# =====================================================================
@bp.post("/sterilization/qualifications")
def create_qualification():
    authenticate("RegulatoryAdmin")
    body = V.body()
    product_id = V.req_id(body, "product_id")
    recipe_id = V.req_id(body, "recipe_id")
    method = V.req_enum(body, "method", ("VDMAX_15", "VDMAX_25", "METHOD_1"))
    verification_dose = V.req_number(body, "verification_dose_kgy", gt=0)
    sal_exponent = V.req_int(body, "sal_exponent", minimum=1)

    product = fetch("products", product_id)
    recipe = fetch("recipes", recipe_id)

    qualification = new_record({
        "product_id": product["id"],
        "recipe_id": recipe["id"],
        "method": method,
        "verification_dose_kgy": verification_dose,
        "sal_exponent": sal_exponent,
        "audit_interval_days": 90,
        "last_audit_at": None,
        "next_audit_due_at": None,
        "consecutive_conditional_count": 0,
        "status": "PENDING",
    })
    db.qualifications[qualification["id"]] = qualification
    return response.object_response(qualification, 201)


@bp.get("/sterilization/qualifications/<qualification_id>")
def read_qualification(qualification_id):
    authenticate("RegulatoryAdmin", "CycleOperator", "QualityReleaseOfficer")
    return response.object_response(fetch("qualifications", qualification_id))


@bp.get("/sterilization/qualifications")
def list_qualifications():
    authenticate("RegulatoryAdmin", "CycleOperator", "QualityReleaseOfficer")
    limit, offset = V.pagination()
    from flask import request
    product_id = request.args.get("product_id")
    recipe_id = request.args.get("recipe_id")
    status = request.args.get("status")
    rows = [
        q for q in db.qualifications.values()
        if (product_id is None or q["product_id"] == product_id)
        and (recipe_id is None or q["recipe_id"] == recipe_id)
        and (status is None or q["status"] == status)
    ]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


@bp.post("/sterilization/qualifications/<qualification_id>/dose-audits")
def create_dose_audit(qualification_id):
    authenticate("RegulatoryAdmin")
    body = V.body()
    performed_at = V.req_datetime(body, "performed_at")
    samples_tested = V.req_int(body, "samples_tested")
    if samples_tested != calc.VDMAX_SAMPLE_SIZE:
        raise ApiError("ERR_VALIDATION", "samples_tested must be exactly 100.")
    positives = V.req_int(body, "positives", minimum=0, maximum=samples_tested)
    applied = V.req_number(body, "verification_dose_kgy_applied", gt=0)

    qualification = fetch("qualifications", qualification_id)
    if qualification["status"] == "REVOKED":
        raise ApiError("ERR_INVALID_STATE", "A REVOKED qualification is terminal.")

    outcome, interval_days = calc.vdmax_outcome(positives)
    audit_due = None
    if outcome != "FAIL":
        audit_due = performed_at + _days(interval_days)

    if outcome == "PASS":
        qualification["consecutive_conditional_count"] = 0
        qualification["status"] = "QUALIFIED"
        qualification_due = audit_due
    elif outcome == "CONDITIONAL_PASS":
        new_count = qualification["consecutive_conditional_count"] + 1
        qualification["consecutive_conditional_count"] = new_count
        if new_count >= calc.MAX_CONSECUTIVE_CONDITIONAL:
            qualification["status"] = "REVOKED"
            qualification_due = None
        else:
            qualification["status"] = "CONDITIONAL"
            qualification_due = audit_due
    else:
        qualification["consecutive_conditional_count"] = 0
        qualification["status"] = "SUSPENDED"
        qualification_due = None

    qualification["audit_interval_days"] = interval_days
    qualification["last_audit_at"] = performed_at
    qualification["next_audit_due_at"] = qualification_due
    touch(qualification)

    if qualification["status"] == "REVOKED":
        for lot in by_seq(list(db.lots.values())):
            if lot["product_id"] == qualification["product_id"] \
                    and lot["status"] in ("RECEIVED", "STAGED") \
                    and lot["schedulable"]:
                lot["schedulable"] = False
                touch(lot)

    audit = new_record({
        "qualification_id": qualification["id"],
        "performed_at": performed_at,
        "samples_tested": samples_tested,
        "positives": positives,
        "verification_dose_kgy_applied": applied,
        "outcome": outcome,
        "next_audit_due_at": audit_due,
        "qualification_status_after": qualification["status"],
    }, common_fields=False)
    db.dose_audits[audit["id"]] = audit
    return response.object_response(audit, 201)


@bp.get("/sterilization/qualifications/<qualification_id>/dose-audits")
def list_dose_audits(qualification_id):
    authenticate("RegulatoryAdmin", "QualityReleaseOfficer")
    limit, offset = V.pagination()
    fetch("qualifications", qualification_id)
    rows = [a for a in db.dose_audits.values()
            if a["qualification_id"] == qualification_id]
    page, total = paginate(rows, limit, offset)
    return response.list_response(page, limit, offset, total)


def _days(count):
    from datetime import timedelta
    return timedelta(days=count)
