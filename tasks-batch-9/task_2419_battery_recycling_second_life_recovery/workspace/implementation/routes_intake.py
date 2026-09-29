"""Custody, hazmat documentation, dismantling and triage (PRD 3.2 - 3.5)."""

from decimal import Decimal as D

from flask import Blueprint, g

import calc
import services
from core import (
    ApiError,
    db,
    endpoint,
    f_enum,
    f_int,
    f_num,
    f_str,
    filter_eq,
    new_row,
    paginate,
    payload,
    q3,
    sort_rows,
    touch,
)

bp = Blueprint("intake", __name__)

INTAKE_READ_ROLES = [
    "PlatformAdmin",
    "IntakeClerk",
    "PlantOperator",
    "ComplianceOfficer",
    "SettlementAccountant",
    "TriageEngineer",
    "AssayTechnician",
    "SupplierRep",
]
MODULE_READ_ROLES = [
    "PlatformAdmin",
    "IntakeClerk",
    "TriageEngineer",
    "PlantOperator",
    "AssayTechnician",
    "ComplianceOfficer",
]


# ---------------------------------------------------------------------------
# intake booking and custody steps
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/intakes", ["POST"], ["IntakeClerk"], 201)
def create_intake():
    data = payload()
    supplier_id = f_str(data, "supplier_id")
    facility_id = f_str(data, "facility_id")
    declared_chemistry = f_enum(data, "declared_chemistry", calc.CHEMISTRIES)
    gross = f_num(data, "gross_mass_kg", gt=0)
    tare = f_num(data, "packaging_tare_kg", ge=0)
    if tare >= gross:
        raise ApiError(
            "ERR_INVALID_REQUEST", "'packaging_tare_kg' must be less than 'gross_mass_kg'."
        )
    pcts = {}
    for field in (
        "declared_ni_pct",
        "declared_co_pct",
        "declared_li_pct",
        "declared_cu_pct",
        "moisture_pct",
        "foreign_material_pct",
    ):
        pcts[field] = f_num(data, field, required=False, default=D("0.0"), ge=0, le=100)

    supplier = services.supplier_or_404(supplier_id)
    facility = services.facility_or_404(facility_id)

    if facility["status"] != "ACTIVE":
        raise ApiError("ERR_FACILITY_SUSPENDED")
    if supplier["credit_hold"]:
        raise ApiError("ERR_SUPPLIER_CREDIT_HOLD")

    row = new_row(
        {
            "supplier_id": supplier_id,
            "facility_id": facility_id,
            "received_at": db.now(),
            "declared_chemistry": declared_chemistry,
            "identified_chemistry": None,
            "gross_mass_kg": gross,
            "packaging_tare_kg": tare,
            "net_mass_kg": q3(gross - tare),
            "declared_ni_pct": pcts["declared_ni_pct"],
            "declared_co_pct": pcts["declared_co_pct"],
            "declared_li_pct": pcts["declared_li_pct"],
            "declared_cu_pct": pcts["declared_cu_pct"],
            "moisture_pct": pcts["moisture_pct"],
            "foreign_material_pct": pcts["foreign_material_pct"],
            "soc_pct": None,
            "packaging_type": None,
            "custody_state": "RECEIVED",
            "compliance_state": "MANIFEST_DRAFT",
            "hold_reason": None,
            "module_mass_total_kg": D("0.0"),
            "assigned_mass_kg": D("0.0"),
            "unassigned_mass_kg": D("0.0"),
            "released_at": None,
        }
    )
    db.intakes[row["id"]] = row
    return row


@endpoint(
    bp,
    "/recycling/intakes",
    ["GET"],
    [
        "PlatformAdmin",
        "IntakeClerk",
        "PlantOperator",
        "ComplianceOfficer",
        "SettlementAccountant",
        "TriageEngineer",
        "SupplierRep",
    ],
    200,
)
def list_intakes():
    data = payload()
    rows = sort_rows(db.intakes.values())
    rows = filter_eq(rows, data, "supplier_id")
    rows = filter_eq(rows, data, "facility_id")
    rows = filter_eq(rows, data, "custody_state")
    rows = filter_eq(rows, data, "compliance_state")
    return paginate(rows, data)


@endpoint(bp, "/recycling/intakes/<intake_id>", ["GET"], INTAKE_READ_ROLES, 200)
def get_intake(intake_id):
    return services.intake_or_404(intake_id)


@endpoint(
    bp,
    "/recycling/intakes/<intake_id>/identify-chemistry",
    ["POST"],
    ["IntakeClerk"],
    200,
)
def identify_chemistry(intake_id):
    data = payload()
    chemistry = f_enum(data, "identified_chemistry", calc.CHEMISTRIES)
    intake = services.intake_or_404(intake_id)
    if intake["custody_state"] != "RECEIVED":
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    intake["identified_chemistry"] = chemistry
    intake["custody_state"] = "IDENTIFIED"
    touch(intake)
    return intake


@endpoint(bp, "/recycling/intakes/<intake_id>/discharge", ["POST"], ["PlantOperator"], 200)
def discharge_intake(intake_id):
    data = payload()
    soc = f_num(data, "soc_pct")
    intake = services.intake_or_404(intake_id)
    if intake["custody_state"] not in ("IDENTIFIED", "DISCHARGED"):
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    if intake["identified_chemistry"] is None:
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    intake["soc_pct"] = soc
    intake["custody_state"] = "DISCHARGED"
    touch(intake)
    return intake


@endpoint(bp, "/recycling/intakes/<intake_id>/package", ["POST"], ["PlantOperator"], 200)
def package_intake(intake_id):
    data = payload()
    packaging_type = f_str(data, "packaging_type")
    intake = services.intake_or_404(intake_id)
    if intake["custody_state"] != "DISCHARGED":
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    soc = intake["soc_pct"]
    if soc is None or soc > calc.SOC_PACKAGING_LIMIT_PCT:
        raise ApiError("ERR_SOC_ABOVE_PACKAGING_LIMIT")
    intake["packaging_type"] = packaging_type
    intake["custody_state"] = "PACKAGED"
    touch(intake)
    return intake


@endpoint(bp, "/recycling/intakes/<intake_id>/release", ["POST"], ["PlantOperator"], 200)
def release_intake(intake_id):
    intake = services.intake_or_404(intake_id)
    if intake["custody_state"] != "PACKAGED":
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    if intake["compliance_state"] != "MANIFEST_CLOSED":
        raise ApiError("ERR_INVALID_COMPLIANCE_STATE")
    supplier = services.supplier_or_404(intake["supplier_id"])
    if supplier["credit_hold"]:
        raise ApiError("ERR_SUPPLIER_CREDIT_HOLD")
    # Prices the cascade child first: a missing quote must leave no state behind.
    services.create_provisional_settlement(intake, supplier)
    intake["custody_state"] = "RELEASED"
    intake["released_at"] = db.now()
    touch(intake)
    return intake


# ---------------------------------------------------------------------------
# hazmat manifests
# ---------------------------------------------------------------------------


@endpoint(
    bp, "/recycling/intakes/<intake_id>/manifests", ["POST"], ["ComplianceOfficer"], 201
)
def submit_manifest(intake_id):
    data = payload()
    un_number = f_enum(data, "un_number", ("UN3480", "UN3481", "UN3536"))
    packing_group = f_enum(data, "packing_group", ("I", "II", "III"))
    transporter_name = f_str(data, "transporter_name")
    intake = services.intake_or_404(intake_id)

    compliance = intake["compliance_state"]
    if compliance == "MANIFEST_DRAFT":
        if intake["custody_state"] not in ("DISCHARGED", "PACKAGED"):
            raise ApiError("ERR_INVALID_CUSTODY_STATE")
        resubmission = False
    elif compliance == "MANIFEST_REJECTED":
        if (
            intake["custody_state"] != "QUARANTINED"
            or intake["hold_reason"] != "MANIFEST_REJECTED"
        ):
            raise ApiError("ERR_INVALID_CUSTODY_STATE")
        resubmission = True
    else:
        raise ApiError("ERR_INVALID_COMPLIANCE_STATE")

    existing = services.manifests_of_intake(intake["id"])
    revision = max([m["revision"] for m in existing], default=0) + 1
    manifest = new_row(
        {
            "intake_id": intake["id"],
            "un_number": un_number,
            "packing_group": packing_group,
            "transporter_name": transporter_name,
            "revision": revision,
            "status": "SUBMITTED",
            "submitted_by_user_id": g.user_id,
            "closed_by_user_id": None,
            "rejection_reason": None,
        }
    )
    db.manifests[manifest["id"]] = manifest

    intake["compliance_state"] = "MANIFEST_SUBMITTED"
    if resubmission:
        intake["custody_state"] = "IDENTIFIED"
        intake["hold_reason"] = None
    touch(intake)
    return manifest


@endpoint(
    bp,
    "/recycling/intakes/<intake_id>/manifests",
    ["GET"],
    ["PlatformAdmin", "ComplianceOfficer", "PlantOperator", "IntakeClerk"],
    200,
)
def list_manifests(intake_id):
    data = payload()
    intake = services.intake_or_404(intake_id)
    rows = services.manifests_of_intake(intake["id"])
    rows = sorted(rows, key=lambda r: (r["revision"], r["created_at"], r["_seq"]))
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(
    bp,
    "/recycling/intakes/<intake_id>/manifests/<manifest_id>/close",
    ["POST"],
    ["ComplianceOfficer"],
    200,
)
def close_manifest(intake_id, manifest_id):
    intake = services.intake_or_404(intake_id)
    manifest = services.manifest_under_intake_or_404(intake, manifest_id)
    if g.user_id == manifest["submitted_by_user_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_MANIFEST_NOT_SUBMITTED")
    if intake["custody_state"] != "PACKAGED":
        raise ApiError("ERR_INVALID_CUSTODY_STATE")
    manifest["status"] = "CLOSED"
    manifest["closed_by_user_id"] = g.user_id
    touch(manifest)
    intake["compliance_state"] = "MANIFEST_CLOSED"
    touch(intake)
    return manifest


@endpoint(
    bp,
    "/recycling/intakes/<intake_id>/manifests/<manifest_id>/reject",
    ["POST"],
    ["ComplianceOfficer"],
    200,
)
def reject_manifest(intake_id, manifest_id):
    data = payload()
    reason = f_str(data, "rejection_reason")
    intake = services.intake_or_404(intake_id)
    manifest = services.manifest_under_intake_or_404(intake, manifest_id)
    if manifest["status"] != "SUBMITTED":
        raise ApiError("ERR_MANIFEST_NOT_SUBMITTED")
    modules = services.modules_of_intake(intake["id"])
    if any(m["status"] in ("CHARGED", "CONSUMED") for m in modules):
        raise ApiError("ERR_MODULES_ALREADY_COMMITTED")

    # link 1
    manifest["status"] = "REJECTED"
    manifest["rejection_reason"] = reason
    touch(manifest)
    intake["compliance_state"] = "MANIFEST_REJECTED"
    # link 2
    intake["custody_state"] = "QUARANTINED"
    intake["hold_reason"] = "MANIFEST_REJECTED"
    touch(intake)
    # link 3
    for module in modules:
        decisions = [
            d for d in services.decisions_of_module(module["id"]) if d["status"] == "ACTIVE"
        ]
        if not decisions:
            continue
        for decision in decisions:
            decision["status"] = "VOIDED"
            touch(decision)
        module["status"] = "PENDING_TRIAGE"
        module["second_life_score"] = None
        module["grade"] = None
        touch(module)
    return manifest


# ---------------------------------------------------------------------------
# modules
# ---------------------------------------------------------------------------


@endpoint(bp, "/recycling/intakes/<intake_id>/modules", ["POST"], ["IntakeClerk"], 201)
def create_module(intake_id):
    data = payload()
    serial_code = f_str(data, "serial_code")
    mass = f_num(data, "mass_kg", gt=0)
    min_cap = f_num(data, "min_cell_capacity_pct", ge=0, le=100)
    mean_cap = f_num(data, "mean_cell_capacity_pct", ge=0, le=100)
    if mean_cap < min_cap:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "'mean_cell_capacity_pct' must be at least 'min_cell_capacity_pct'.",
        )
    expected_version = f_int(data, "expected_intake_version")
    cycle_count = f_int(data, "cycle_count", required=False, default=0, ge=0)

    intake = services.intake_or_404(intake_id)

    for existing in services.modules_of_intake(intake["id"]):
        if existing["serial_code"] == serial_code:
            raise ApiError(
                "ERR_INVALID_REQUEST", "'serial_code' must be unique within the shipment."
            )

    if expected_version != intake["version"]:
        raise ApiError("ERR_STALE_INTAKE_VERSION")

    module = new_row(
        {
            "intake_id": intake["id"],
            "lot_id": None,
            "serial_code": serial_code,
            "chemistry": intake["identified_chemistry"],
            "mass_kg": mass,
            "min_cell_capacity_pct": min_cap,
            "mean_cell_capacity_pct": mean_cap,
            "cycle_count": cycle_count,
            "second_life_score": None,
            "grade": None,
            "status": "PENDING_TRIAGE",
            "shipped_to": None,
        }
    )
    db.modules[module["id"]] = module
    services.recompute_intake_masses(intake)
    touch(intake)
    return module


@endpoint(bp, "/recycling/modules", ["GET"], MODULE_READ_ROLES, 200)
def list_modules():
    data = payload()
    rows = sort_rows(db.modules.values())
    rows = filter_eq(rows, data, "intake_id")
    rows = filter_eq(rows, data, "lot_id")
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/modules/<module_id>", ["GET"], MODULE_READ_ROLES, 200)
def get_module(module_id):
    return services.module_or_404(module_id)


@endpoint(
    bp, "/recycling/modules/<module_id>/triage-decisions", ["POST"], ["TriageEngineer"], 201
)
def create_triage_decision(module_id):
    data = payload()
    variant = f_enum(data, "scoring_variant", ("CONSERVATIVE", "FLEET_AVERAGE"))
    override = f_enum(
        data,
        "override_disposition",
        ("REFURBISH", "SECOND_LIFE", "MATERIAL_RECOVERY"),
        required=False,
        default=None,
    )
    module = services.module_or_404(module_id)
    intake = db.intakes.get(module["intake_id"])
    if module["status"] != "PENDING_TRIAGE" or (
        intake is None or intake["custody_state"] not in ("PACKAGED", "RELEASED")
    ):
        raise ApiError("ERR_MODULE_NOT_TRIAGEABLE")

    score = calc.module_second_life_score(module, variant)
    grade = calc.grade_for_score(score)
    derived = calc.DERIVED_DISPOSITION[grade]
    if override is not None and grade not in calc.OVERRIDE_ALLOWED_GRADES[override]:
        raise ApiError("ERR_DISPOSITION_OVERRIDE_NOT_PERMITTED")
    disposition = override or derived

    decision = new_row(
        {
            "module_id": module["id"],
            "scoring_variant": variant,
            "override_disposition": override,
            "score": score,
            "grade": grade,
            "derived_disposition": derived,
            "disposition": disposition,
            "status": "ACTIVE",
            "decided_by_user_id": g.user_id,
        }
    )
    db.decisions[decision["id"]] = decision

    module["second_life_score"] = score
    module["grade"] = grade
    module["status"] = {
        "REFURBISH": "REFURB_QUEUE",
        "SECOND_LIFE": "SECOND_LIFE_QUEUE",
        "MATERIAL_RECOVERY": "RECOVERY_QUEUE",
    }[disposition]
    touch(module)
    return decision


@endpoint(
    bp,
    "/recycling/modules/<module_id>/triage-decisions",
    ["GET"],
    ["PlatformAdmin", "TriageEngineer", "PlantOperator", "ComplianceOfficer"],
    200,
)
def list_triage_decisions(module_id):
    data = payload()
    module = services.module_or_404(module_id)
    rows = services.decisions_of_module(module["id"])
    rows = filter_eq(rows, data, "status")
    return paginate(rows, data)


@endpoint(bp, "/recycling/modules/<module_id>/ship", ["POST"], ["PlantOperator"], 200)
def ship_module(module_id):
    data = payload()
    customer_name = f_str(data, "customer_name")
    module = services.module_or_404(module_id)
    if module["status"] not in ("REFURB_QUEUE", "SECOND_LIFE_QUEUE"):
        raise ApiError("ERR_MODULE_NOT_SHIPPABLE")
    intake = db.intakes.get(module["intake_id"])
    if intake is None or intake["custody_state"] != "RELEASED":
        raise ApiError("ERR_INTAKE_NOT_RELEASED")
    module["shipped_to"] = customer_name
    module["status"] = "SHIPPED"
    touch(module)
    return module
