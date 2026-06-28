"""Project endpoints + nested list sub-resources (PRD §3.1, §2.5)."""
from flask import Blueprint, request, g

import errors
import response
from db import db
from middleware import require_roles
from services import common, serialize, calculations
from services.permit_expiry import evaluate_expiry

bp = Blueprint("projects", __name__)

STRUCTURE_TYPES = {"SCREEN_ROOM", "THREE_SEASON", "FOUR_SEASON"}
MATERIALS = {"ALUMINUM", "VINYL", "THERMAL_BREAK_ALUMINUM"}

CANCELLABLE_STATES = {"DRAFT", "MEASURED", "DESIGNED", "QUOTED", "PERMITTING"}


@bp.route("/projects", methods=["POST"])
def create_project():
    require_roles({"SalesDesigner"})
    body = common.get_json()

    homeowner_id = common.require_field(body, "homeowner_id", expected_types=["string"])
    address_line = common.require_field(body, "address_line", expected_types=["string"])
    structure_type = common.require_field(
        body, "structure_type", expected_types=["string"],
        validator=lambda v: v in STRUCTURE_TYPES)
    material = common.require_field(
        body, "material", expected_types=["string"],
        validator=lambda v: v in MATERIALS)

    # existence: FK resolves (priority 4)
    common.get_homeowner(homeowner_id)

    entity = {
        "homeowner_id": homeowner_id,
        "address_line": address_line,
        "structure_type": structure_type,
        "material": material,
        "status": "DRAFT",
        "width_in": 0,
        "depth_in": 0,
        "footprint_sqft": 0,
        "accepted_quote_id": None,
        "requires_hoa": False,
        "requires_engineering": False,
    }
    common.stamp_create(entity)
    db.projects[entity["id"]] = entity
    return response.success(serialize.project(entity), status=201)


@bp.route("/projects", methods=["GET"])
def list_projects():
    require_roles({"SalesDesigner", "Homeowner", "InstallManager"})
    limit, offset = common.parse_pagination()

    homeowner_id = request.args.get("homeowner_id")
    status = request.args.get("status")
    items = list(db.projects.values())
    if homeowner_id is not None:
        items = [p for p in items if p["homeowner_id"] == homeowner_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    page, total = common.paginate(items, limit, offset)
    return response.array([serialize.project(p) for p in page], limit, offset, total)


@bp.route("/projects/<pid>", methods=["GET"])
def get_project(pid):
    require_roles({"SalesDesigner", "Homeowner", "InstallManager",
                   "Manufacturer", "PermitOfficer", "Inspector"})
    project = common.get_project(pid)
    return response.success(serialize.project(project), status=200)


@bp.route("/projects/<pid>/finalize-design", methods=["POST"])
def finalize_design(pid):
    require_roles({"SalesDesigner"})
    common.get_json()
    project = common.get_project(pid)

    # state: MEASURED (priority 5)
    if project["status"] != "MEASURED":
        raise errors.invalid_state("Project must be MEASURED to finalize design.")
    if not project.get("structure_type") or not project.get("material"):
        raise errors.invalid_state("structure_type and material must be set.")

    homeowner = db.homeowners[project["homeowner_id"]]
    project["requires_hoa"] = bool(homeowner["hoa_governed"])
    project["requires_engineering"] = calculations.engineering_requirement(
        project["structure_type"],
        homeowner["ground_snow_load_psf"],
        homeowner["design_wind_speed_mph"],
    )
    project["status"] = "DESIGNED"
    common.touch(project)
    return response.success(serialize.project(project), status=200)


@bp.route("/projects/<pid>/cancel", methods=["POST"])
def cancel_project(pid):
    user_id, role = require_roles({"Homeowner"})
    common.get_json()
    project = common.get_project(pid)

    # ownership (priority 3)
    if project["homeowner_id"] != user_id:
        raise errors.not_resource_owner("You do not own this project.")

    # state (priority 5)
    if project["status"] not in CANCELLABLE_STATES:
        raise errors.invalid_state("Project cannot be cancelled in its current state.")

    # cascade: supersede ISSUED quotes
    for q in db.quotes.values():
        if q["project_id"] == pid and q["status"] == "ISSUED":
            q["status"] = "SUPERSEDED"
            common.touch(q)
    # cascade: expire SUBMITTED/IN_REVIEW permit
    for p in db.permit_applications.values():
        if p["project_id"] == pid and p["status"] in ("SUBMITTED", "IN_REVIEW"):
            p["status"] = "EXPIRED"
            common.touch(p)
    # cascade: cancel QUEUED/IN_PRODUCTION manufacture order
    for mo in db.manufacture_orders.values():
        if mo["project_id"] == pid and mo["status"] in ("QUEUED", "IN_PRODUCTION"):
            mo["status"] = "CANCELLED"
            common.touch(mo)

    project["status"] = "CANCELLED"
    common.touch(project)
    return response.success(serialize.project(project), status=200)


# ----- nested list sub-resources (PRD §2.5) -----
def _list_children(pid, store, serializer, status_filter=None):
    limit, offset = common.parse_pagination()
    common.get_project(pid)  # existence first (priority 4)
    items = [e for e in store.values() if e.get("project_id") == pid]
    if status_filter is not None:
        items = [e for e in items if e.get("status") == status_filter]
    page, total = common.paginate(items, limit, offset)
    return response.array([serializer(e) for e in page], limit, offset, total)


@bp.route("/projects/<pid>/measurements", methods=["GET"])
def list_measurements(pid):
    require_roles({"SalesDesigner", "Homeowner"})
    return _list_children(pid, db.measurements, serialize.measurement)


@bp.route("/projects/<pid>/quotes", methods=["GET"])
def list_quotes(pid):
    require_roles({"SalesDesigner", "Homeowner"})
    status = request.args.get("status")
    return _list_children(pid, db.quotes, serialize.quote, status_filter=status)


@bp.route("/projects/<pid>/permit-applications", methods=["GET"])
def list_permits(pid):
    require_roles({"SalesDesigner", "Homeowner", "PermitOfficer"})
    limit, offset = common.parse_pagination()
    common.get_project(pid)
    items = [evaluate_expiry(e) for e in db.permit_applications.values()
             if e.get("project_id") == pid]
    page, total = common.paginate(items, limit, offset)
    return response.array([serialize.permit(e) for e in page], limit, offset, total)


@bp.route("/projects/<pid>/manufacture-orders", methods=["GET"])
def list_manufacture(pid):
    require_roles({"Manufacturer", "InstallManager", "SalesDesigner"})
    return _list_children(pid, db.manufacture_orders, serialize.manufacture)


@bp.route("/projects/<pid>/install-jobs", methods=["GET"])
def list_install_jobs(pid):
    require_roles({"InstallManager", "SalesDesigner", "Inspector"})
    return _list_children(pid, db.install_jobs, serialize.install_job)


@bp.route("/projects/<pid>/inspections", methods=["GET"])
def list_inspections(pid):
    require_roles({"Inspector", "InstallManager", "SalesDesigner"})
    return _list_children(pid, db.inspections, serialize.inspection)


@bp.route("/projects/<pid>/warranties", methods=["GET"])
def list_warranties(pid):
    require_roles({"Homeowner", "SalesDesigner", "Inspector"})
    return _list_children(pid, db.warranties, serialize.warranty)
