"""Configuration and resource registries: prescribers, plans, patients, lens
designs, tolerance standards, blank lots, machines and bays."""

from flask import Blueprint, request

import calc
import serializers as S
import services
from auth import require_roles
from envelope import created, listing, ok
from errors import ApiError
from store import db, sorted_rows, stamp_common, touch
from validate import F, json_body, validate_body

bp = Blueprint("registry", __name__)

DESIGN_TYPES = ("SINGLE_VISION", "PROGRESSIVE", "SPECIALTY")
MATERIALS = ("CR39", "POLYCARBONATE", "TRIVEX", "HIGH_INDEX_167")
PRODUCT_TIERS = ("ECONOMY", "STANDARD", "PREMIUM")


def _filtered(rows, filters):
    out = rows
    for arg, field in filters:
        value = request.args.get(arg)
        if value is None or value == "":
            continue
        out = [r for r in out if r.get(field) == value]
    return out


# --- Prescriber ------------------------------------------------------------

@bp.post("/prescribers")
def create_prescriber():
    body = json_body()
    data = validate_body(
        body,
        [
            F("npi", "string", pattern=r"^\d{10}$"),
            F("full_name", "string", min_len=1, max_len=120),
            F("license_state", "string", pattern=r"^[A-Z]{2}$"),
            F("max_rx_validity_months", "int", required=False, minimum=1, maximum=36, default=12),
        ],
    )
    require_roles("StoreOptician", "LabManager")
    for row in db.prescribers.values():
        if row["npi"] == data["npi"]:
            raise ApiError("ERR_DUPLICATE_NPI")
    row = stamp_common(
        {
            "npi": data["npi"],
            "full_name": data["full_name"],
            "license_state": data["license_state"],
            "max_rx_validity_months": data["max_rx_validity_months"],
            "status": "ACTIVE",
        }
    )
    db.prescribers[row["id"]] = row
    return created(S.prescriber(row))


@bp.get("/prescribers/<rid>")
def get_prescriber(rid):
    row = services.get_or_404(db.prescribers, rid, "ERR_PRESCRIBER_NOT_FOUND")
    require_roles()
    return ok(S.prescriber(row))


@bp.get("/prescribers")
def list_prescribers():
    require_roles()
    rows = _filtered(sorted_rows(db.prescribers), [("status", "status"), ("license_state", "license_state")])
    return listing(rows, S.prescriber)


@bp.patch("/prescribers/<rid>/status")
def set_prescriber_status(rid):
    body = json_body()
    data = validate_body(body, [F("status", "enum", enum=("ACTIVE", "SUSPENDED", "RETIRED"))])
    row = services.get_or_404(db.prescribers, rid, "ERR_PRESCRIBER_NOT_FOUND")
    require_roles("LabManager")
    row["status"] = data["status"]
    touch(row)
    if data["status"] in ("SUSPENDED", "RETIRED"):
        services.prescriber_standing_cascade(row)
    return ok(S.prescriber(row))


# --- InsurancePlan ---------------------------------------------------------

@bp.post("/insurance-plans")
def create_insurance_plan():
    body = json_body()
    data = validate_body(
        body,
        [
            F("plan_code", "string", min_len=1),
            F("frame_allowance_cents", "int", minimum=0),
            F("lens_base_allowance_cents", "int", minimum=0),
            F("coating_allowance_cents", "int", minimum=0),
            F("progressive_copay_cents", "int", minimum=0),
            F("coinsurance_pct", "number", minimum=0, maximum=1),
            F("annual_benefit_cap_cents", "int", minimum=0),
            F("expedite_covered", "bool", required=False, default=False),
            F("specialty_requires_prior_auth", "bool", required=False, default=True),
        ],
    )
    require_roles("BenefitsAdministrator")
    for row in db.insurance_plans.values():
        if row["plan_code"] == data["plan_code"]:
            raise ApiError("ERR_DUPLICATE_PLAN_CODE")
    row = stamp_common(dict(data))
    db.insurance_plans[row["id"]] = row
    return created(S.insurance_plan(row))


@bp.get("/insurance-plans/<rid>")
def get_insurance_plan(rid):
    row = services.get_or_404(db.insurance_plans, rid, "ERR_INSURANCE_PLAN_NOT_FOUND")
    require_roles("StoreOptician", "LabManager", "BenefitsAdministrator")
    return ok(S.insurance_plan(row))


# --- Patient ---------------------------------------------------------------

@bp.post("/patients")
def create_patient():
    body = json_body()
    data = validate_body(
        body,
        [
            F("full_name", "string", min_len=1),
            F("date_of_birth", "date"),
            F("insurance_plan_id", "string", required=False),
            F("member_number", "string", required=False),
            F("benefit_period_start", "date", required=False, default="2026-01-01"),
        ],
    )
    plan_id = data["insurance_plan_id"]
    if plan_id is not None:
        services.get_or_404(db.insurance_plans, plan_id, "ERR_INSURANCE_PLAN_NOT_FOUND")
    require_roles("StoreOptician", "BenefitsAdministrator")
    member = data["member_number"]
    if plan_id is not None:
        if member is None or member == "":
            raise ApiError("ERR_MEMBER_NUMBER_REQUIRED")
    else:
        member = None
    row = stamp_common(
        {
            "full_name": data["full_name"],
            "date_of_birth": data["date_of_birth"],
            "insurance_plan_id": plan_id,
            "member_number": member,
            "benefit_period_start": data["benefit_period_start"],
            "status": "ACTIVE",
        }
    )
    db.patients[row["id"]] = row
    return created(S.patient(row))


@bp.get("/patients/<rid>")
def get_patient(rid):
    row = services.get_or_404(db.patients, rid, "ERR_PATIENT_NOT_FOUND")
    require_roles("StoreOptician", "LabManager", "BenefitsAdministrator")
    return ok(S.patient(row))


@bp.get("/patients")
def list_patients():
    require_roles("StoreOptician", "LabManager", "BenefitsAdministrator")
    rows = _filtered(
        sorted_rows(db.patients), [("insurance_plan_id", "insurance_plan_id"), ("status", "status")]
    )
    return listing(rows, S.patient)


# --- LensDesign ------------------------------------------------------------

@bp.post("/lens-designs")
def create_lens_design():
    body = json_body()
    data = validate_body(
        body,
        [
            F("design_code", "string", min_len=1),
            F("design_type", "enum", enum=DESIGN_TYPES),
            F("material", "enum", enum=MATERIALS),
            F("allowed_coatings", "array", item_kind="string", item_enum=calc.COATING_CODES, min_items=1),
            F("retail_price_cents", "int", minimum=1),
            F("min_fitting_height_mm", "number", minimum=8.0, maximum=30.0),
            F("min_blank_diameter_mm", "number", minimum=50.0, maximum=85.0),
            F("product_tier", "enum", enum=PRODUCT_TIERS),
            F("stock_sku_available", "bool", required=False, default=False),
            F("base_curve", "number", required=False, minimum=0.5, maximum=10.0),
        ],
    )
    require_roles("LabManager")
    for row in db.lens_designs.values():
        if row["design_code"] == data["design_code"]:
            raise ApiError("ERR_DUPLICATE_DESIGN_CODE")
    row = stamp_common(dict(data))
    db.lens_designs[row["id"]] = row
    return created(S.lens_design(row))


@bp.get("/lens-designs/<rid>")
def get_lens_design(rid):
    row = services.get_or_404(db.lens_designs, rid, "ERR_LENS_DESIGN_NOT_FOUND")
    require_roles("StoreOptician", "LabTechnician", "QualityInspector", "LabManager",
                  "BenefitsAdministrator")
    return ok(S.lens_design(row))


# --- ToleranceStandard -----------------------------------------------------

@bp.post("/tolerance-standards")
def create_tolerance_standard():
    body = json_body()
    data = validate_body(
        body,
        [
            F("design_type", "enum", enum=DESIGN_TYPES),
            F("power_band_min_abs", "number", minimum=0),
            F("power_band_max_abs", "number"),
            F("sphere_tolerance_diopters", "number"),
            F("cylinder_tolerance_diopters", "number"),
            F("axis_tolerance_degrees", "int"),
            F("prism_tolerance_pd", "number"),
            F("allowed_cosmetic_defect_codes", "array", item_kind="string"),
            F("effective_from", "date"),
        ],
    )
    if calc.D(data["power_band_max_abs"]) <= calc.D(data["power_band_min_abs"]):
        raise ApiError("ERR_VALIDATION")
    for field in ("sphere_tolerance_diopters", "cylinder_tolerance_diopters",
                  "axis_tolerance_degrees", "prism_tolerance_pd"):
        if calc.D(data[field]) <= 0:
            raise ApiError("ERR_VALIDATION")
    require_roles("LabManager")
    row = stamp_common(dict(data))
    db.tolerance_standards[row["id"]] = row
    return created(S.tolerance_standard(row))


@bp.get("/tolerance-standards/<rid>")
def get_tolerance_standard(rid):
    row = services.get_or_404(db.tolerance_standards, rid, "ERR_TOLERANCE_STANDARD_NOT_FOUND")
    require_roles("LabTechnician", "QualityInspector", "LabManager")
    return ok(S.tolerance_standard(row))


# --- LensBlankLot ----------------------------------------------------------

@bp.post("/lens-blank-lots")
def create_lens_blank_lot():
    body = json_body()
    data = validate_body(
        body,
        [
            F("lens_design_id", "string"),
            F("blank_sku", "string", min_len=1),
            F("diameter_mm", "number", minimum=50.0, maximum=85.0),
            F("received_qty", "int", minimum=1),
            F("received_on", "date"),
        ],
    )
    services.get_or_404(db.lens_designs, data["lens_design_id"], "ERR_LENS_DESIGN_NOT_FOUND")
    require_roles("LabManager")
    row = stamp_common(
        {
            "lens_design_id": data["lens_design_id"],
            "blank_sku": data["blank_sku"],
            "diameter_mm": data["diameter_mm"],
            "received_qty": data["received_qty"],
            "on_hand_qty": data["received_qty"],
            "allocated_qty": 0,
            "consumed_qty": 0,
            "scrapped_qty": 0,
            "status": "AVAILABLE",
            "received_on": data["received_on"],
        }
    )
    db.lens_blank_lots[row["id"]] = row
    return created(S.lens_blank_lot(row))


@bp.get("/lens-blank-lots/<rid>")
def get_lens_blank_lot(rid):
    row = services.get_or_404(db.lens_blank_lots, rid, "ERR_LENS_BLANK_LOT_NOT_FOUND")
    require_roles("LabTechnician", "QualityInspector", "LabManager")
    return ok(S.lens_blank_lot(row))


@bp.get("/lens-blank-lots")
def list_lens_blank_lots():
    require_roles("LabTechnician", "QualityInspector", "LabManager")
    rows = _filtered(
        sorted_rows(db.lens_blank_lots), [("lens_design_id", "lens_design_id"), ("status", "status")]
    )
    return listing(rows, S.lens_blank_lot)


@bp.post("/lens-blank-lots/<rid>/replenish")
def replenish_lens_blank_lot(rid):
    body = json_body()
    if "added_qty" not in body:
        raise ApiError("ERR_VALIDATION")
    lot = services.get_or_404(db.lens_blank_lots, rid, "ERR_LENS_BLANK_LOT_NOT_FOUND")
    require_roles("LabManager")
    added = body["added_qty"]
    if not isinstance(added, int) or isinstance(added, bool) or added <= 0:
        raise ApiError("ERR_VALIDATION")
    lot["received_qty"] += added
    lot["on_hand_qty"] += added
    if lot["status"] == "DEPLETED" and lot["on_hand_qty"] > 0:
        lot["status"] = "AVAILABLE"
    touch(lot)
    services.promote_backordered_jobs(lot)
    return ok(S.lens_blank_lot(lot))


# --- LabMachine ------------------------------------------------------------

@bp.post("/lab-machines")
def create_lab_machine():
    body = json_body()
    data = validate_body(
        body,
        [
            F("machine_code", "string", min_len=1),
            F("machine_type", "enum", enum=("GENERATOR", "POLISHER")),
            F("calibration_buffer_minutes", "int", required=False, minimum=0, maximum=120, default=15),
        ],
    )
    require_roles("LabManager")
    row = stamp_common(dict(data, status="AVAILABLE"))
    db.lab_machines[row["id"]] = row
    return created(S.lab_machine(row))


@bp.get("/lab-machines/<rid>")
def get_lab_machine(rid):
    row = services.get_or_404(db.lab_machines, rid, "ERR_LAB_MACHINE_NOT_FOUND")
    require_roles("LabTechnician", "QualityInspector", "LabManager")
    return ok(S.lab_machine(row))


@bp.patch("/lab-machines/<rid>/status")
def set_lab_machine_status(rid):
    body = json_body()
    data = validate_body(
        body, [F("status", "enum", enum=("AVAILABLE", "CALIBRATION_HOLD", "DOWN"))]
    )
    row = services.get_or_404(db.lab_machines, rid, "ERR_LAB_MACHINE_NOT_FOUND")
    require_roles("LabManager")
    row["status"] = data["status"]
    touch(row)
    return ok(S.lab_machine(row))


# --- FinishingBay ----------------------------------------------------------

@bp.post("/finishing-bays")
def create_finishing_bay():
    body = json_body()
    data = validate_body(
        body,
        [
            F("bay_code", "string", min_len=1),
            F("concurrent_capacity", "int", minimum=1, maximum=4),
        ],
    )
    require_roles("LabManager")
    row = stamp_common(dict(data, status="OPEN"))
    db.finishing_bays[row["id"]] = row
    return created(S.finishing_bay(row))


@bp.get("/finishing-bays/<rid>")
def get_finishing_bay(rid):
    row = services.get_or_404(db.finishing_bays, rid, "ERR_FINISHING_BAY_NOT_FOUND")
    require_roles("LabTechnician", "QualityInspector", "LabManager")
    return ok(S.finishing_bay(row))


@bp.patch("/finishing-bays/<rid>/status")
def set_finishing_bay_status(rid):
    body = json_body()
    data = validate_body(body, [F("status", "enum", enum=("OPEN", "CLOSED"))])
    row = services.get_or_404(db.finishing_bays, rid, "ERR_FINISHING_BAY_NOT_FOUND")
    require_roles("LabManager")
    row["status"] = data["status"]
    touch(row)
    return ok(S.finishing_bay(row))
