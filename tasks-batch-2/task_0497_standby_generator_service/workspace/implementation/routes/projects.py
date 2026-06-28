"""GeneratorProject + LoadAssessment routes (install pipeline)."""
from flask import Blueprint, request

import calc
import db
import posture
from auth import get_principal, require_roles
from clock import get_now, to_iso8601
from errors import err
from response import success
from serialize import out
from validate import (
    get_body, opt_bool, opt_int, opt_str, require_enum, require_int,
    require_str,
)
from routes.common import (
    customer_owns, find_or_404, ref_or_404, render_list,
)

bp = Blueprint("projects", __name__)

FUELS = {"NG", "PROPANE"}
METHODS = {"STAGGERED", "FULL_LOAD"}


# ---- Create / list / get ---------------------------------------------------
@bp.route("/projects", methods=["POST"])
def create_project():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    body = get_body()
    customer_id = require_str(body, "customer_id")
    fuel_type = require_enum(body, "fuel_type", FUELS)
    model_id = opt_str(body, "model_id", default=None)

    # FK references (priority 4)
    customer = ref_or_404(db.customers, customer_id)
    if model_id is not None:
        ref_or_404(db.models, model_id)

    # Ownership: a Customer may only create for their own customer_id
    if principal.role == "Customer" and principal.user_id != customer_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Customer may only create projects for themselves")

    rec = db.base_record(full_common=True)
    rec.update({
        "customer_id": customer_id,
        "model_id": model_id,
        "fuel_type": fuel_type,
        "status": "DRAFT",
        "required_kw": None,
        "sizing_method": "STAGGERED",
        "permit_number": None,
        "permit_status": "NONE",
        "fuel_hookup_verified": False,
        "ats_amps": None,
        "install_tech_id": None,
        "unit_id": None,
        "cancellation_reason": None,
    })
    db.projects[rec["id"]] = rec
    _ = customer
    return success(out(rec), status=201)


@bp.route("/projects", methods=["GET"])
def list_projects():
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    records = list(db.projects.values())
    for f in ("customer_id", "model_id", "install_tech_id", "unit_id"):
        if f in request.args:
            val = request.args.get(f)
            records = [r for r in records if r.get(f) == val]
    return render_list(records)


@bp.route("/projects/<project_id>", methods=["GET"])
def get_project(project_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "Technician", "ServiceManager", "ComplianceOfficer"})
    rec = find_or_404(db.projects, project_id)
    return success(out(rec), status=200)


# ---- Load assessments ------------------------------------------------------
@bp.route("/projects/<project_id>/load-assessments", methods=["POST"])
def create_assessment(project_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()

    appliances = body.get("appliances")
    if not isinstance(appliances, list) or len(appliances) == 0:
        raise err("ERR_INVALID_REQUEST", "appliances must be a non-empty array")
    method = require_enum_default(body, "method", METHODS, "STAGGERED")

    parsed = []
    for a in appliances:
        if not isinstance(a, dict):
            raise err("ERR_INVALID_REQUEST", "each appliance must be an object")
        name = a.get("name")
        rw = a.get("running_watts")
        sw = a.get("starting_watts")
        if not isinstance(name, str) or name == "":
            raise err("ERR_INVALID_REQUEST", "appliance name must be a non-empty string")
        if isinstance(rw, bool) or not isinstance(rw, (int, float)):
            raise err("ERR_INVALID_REQUEST", "running_watts must be a number")
        if isinstance(sw, bool) or not isinstance(sw, (int, float)):
            raise err("ERR_INVALID_REQUEST", "starting_watts must be a number")
        if rw < 0:
            raise err("ERR_INVALID_REQUEST", "running_watts must be >= 0")
        # semantic field violation: starting < running -> ERR_VALIDATION
        if sw < rw:
            raise err("ERR_VALIDATION", "starting_watts must be >= running_watts")
        parsed.append({"name": name, "running_watts": rw, "starting_watts": sw})

    # Ownership (priority 6) after body well-formedness (priority 5).
    customer_owns(principal, project["customer_id"])

    peak, required_kw = calc.run_load_sizing(parsed, method)

    rec = db.base_record(full_common=False)
    rec.update({
        "project_id": project_id,
        "appliances": parsed,
        "method": method,
        "computed_required_kw": required_kw,
        "peak_demand_w": peak,
    })
    db.load_assessments[rec["id"]] = rec
    return success(out(rec), status=201)


@bp.route("/projects/<project_id>/load-assessments", methods=["GET"])
def list_assessments(project_id):
    principal = get_principal()
    require_roles(principal, {"Customer", "ServiceManager", "ComplianceOfficer"})
    find_or_404(db.projects, project_id)
    records = [a for a in db.load_assessments.values() if a["project_id"] == project_id]
    return render_list(records)


# ---- Size: DRAFT -> SIZED --------------------------------------------------
@bp.route("/projects/<project_id>/size", methods=["POST"])
def size_project(project_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()
    assessment_id = require_str(body, "assessment_id")
    model_id = require_str(body, "model_id")

    # FK reference resolution (priority 4)
    model = ref_or_404(db.models, model_id)
    assessment = db.load_assessments.get(assessment_id)

    # state legality (priority 8)
    if project["status"] != "DRAFT":
        raise err("ERR_INVALID_STATE", "Project must be DRAFT to size")

    # assessment must belong to project (priority: business)
    if assessment is None or assessment["project_id"] != project_id:
        raise err("ERR_NO_ASSESSMENT", "Assessment not found on this project")

    # model active
    if not model["active"]:
        raise err("ERR_MODEL_INACTIVE", "Chosen model is inactive")

    # sizing adequacy
    required = assessment["computed_required_kw"]
    if model["rated_kw"] < required or project["fuel_type"] not in model["fuel_types"]:
        raise err("ERR_MODEL_UNDERSIZED", "Model undersized or fuel-incompatible")

    project["required_kw"] = required
    project["sizing_method"] = assessment["method"]
    project["model_id"] = model_id
    project["status"] = "SIZED"
    db.touch(project)
    return success(out(project), status=200)


# ---- Permit: SIZED -> PERMITTED -------------------------------------------
@bp.route("/projects/<project_id>/permit", methods=["POST"])
def permit_project(project_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()
    permit_number = require_str(body, "permit_number")
    permit_decision = require_enum(body, "permit_decision", {"APPROVE", "REJECT"})
    fuel_supply = require_int(body, "fuel_supply_btu_per_hr", minimum=0)
    existing_load = opt_int(body, "existing_load_btu_per_hr", default=0, minimum=0)

    if project["status"] != "SIZED":
        raise err("ERR_INVALID_STATE", "Project must be SIZED to permit")

    if permit_decision == "REJECT":
        project["permit_status"] = "REJECTED"
        project["permit_number"] = permit_number
        db.touch(project)
        return success(out(project), status=200)

    # APPROVE: run fuel adequacy
    if not calc.run_fuel_adequacy(project["required_kw"], fuel_supply, existing_load):
        raise err("ERR_FUEL_INADEQUATE", "Fuel BTU supply does not cover the sized unit")

    project["permit_number"] = permit_number
    project["permit_status"] = "APPROVED"
    project["fuel_hookup_verified"] = True
    project["status"] = "PERMITTED"
    db.touch(project)
    return success(out(project), status=200)


# ---- Install: PERMITTED -> INSTALLED --------------------------------------
@bp.route("/projects/<project_id>/install", methods=["POST"])
def install_project(project_id):
    principal = get_principal()
    require_roles(principal, {"Technician", "ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()
    install_tech_id = require_str(body, "install_tech_id")
    ats_amps = require_int(body, "ats_amps")

    # FK reference (priority 4)
    tech = ref_or_404(db.technicians, install_tech_id)

    # Technician acting must be the named install tech (ownership)
    if principal.role == "Technician" and principal.user_id != install_tech_id:
        raise err("ERR_NOT_ASSIGNED_TECH", "Acting technician is not the install tech")

    # body semantic: ats_amps > 0
    if ats_amps <= 0:
        raise err("ERR_INVALID_REQUEST", "ats_amps must be > 0")

    if project["status"] != "PERMITTED":
        raise err("ERR_INVALID_STATE", "Project must be PERMITTED to install")

    # tech qualified
    if tech["status"] != "ACTIVE" or not tech["gas_certified"]:
        raise err("ERR_TECH_NOT_QUALIFIED", "Install tech must be ACTIVE and gas_certified")

    project["install_tech_id"] = install_tech_id
    project["ats_amps"] = ats_amps
    project["status"] = "INSTALLED"
    db.touch(project)
    return success(out(project), status=200)


# ---- Activate: INSTALLED -> ACTIVATED (mints Unit) ------------------------
@bp.route("/projects/<project_id>/activate", methods=["POST"])
def activate_project(project_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()
    serial_no = require_str(body, "serial_no")
    monitoring_enabled = opt_bool(body, "monitoring_enabled", default=False)

    if project["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project must be INSTALLED to activate")

    # permit gate
    if project["permit_status"] != "APPROVED" or not project["fuel_hookup_verified"]:
        raise err("ERR_PERMIT_NOT_APPROVED", "Permit not approved / fuel not verified")

    # serial uniqueness
    for u in db.units.values():
        if u["serial_no"] == serial_no:
            raise err("ERR_DUPLICATE_SERIAL", "Serial number already used")

    model = db.models[project["model_id"]]
    unit = db.base_record(full_common=True)
    unit.update({
        "project_id": project_id,
        "customer_id": project["customer_id"],
        "model_id": project["model_id"],
        "serial_no": serial_no,
        "rated_kw": model["rated_kw"],
        "fuel_type": project["fuel_type"],
        "registration_status": "UNREGISTERED",
        "warranty_start": db.now_iso(),
        "warranty_total_months": model["warranty_months"],
        "warranty_status": "ACTIVE",
        "monitoring_enabled": monitoring_enabled,
        "monitoring_health": "OFFLINE",
        "compliance_score": 0,
        "operating_status": "OPERATIONAL",
        "last_exercise_at": None,
        "runtime_hours": 0,
    })
    db.units[unit["id"]] = unit

    project["unit_id"] = unit["id"]
    project["status"] = "ACTIVATED"
    db.touch(project)
    return success(out(project), status=200)


# ---- Cancel ----------------------------------------------------------------
@bp.route("/projects/<project_id>/cancel", methods=["POST"])
def cancel_project(project_id):
    principal = get_principal()
    require_roles(principal, {"ServiceManager"})
    project = find_or_404(db.projects, project_id)
    body = get_body()
    cancellation_reason = require_str(body, "cancellation_reason")

    if project["status"] in ("ACTIVATED", "CANCELLED"):
        raise err("ERR_INVALID_STATE", "Cannot cancel an activated or cancelled project")

    project["cancellation_reason"] = cancellation_reason
    project["status"] = "CANCELLED"
    db.touch(project)
    return success(out(project), status=200)


# ---- local helper ----------------------------------------------------------
def require_enum_default(body, field, allowed, default):
    if field not in body or body[field] is None:
        return default
    val = body[field]
    if val not in allowed:
        raise err("ERR_INVALID_REQUEST", f"{field} must be one of {sorted(allowed)}")
    return val
