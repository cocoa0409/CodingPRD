from flask import Blueprint
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate, entity_for_role
from services.common import get_body, require_fields, is_int, is_num, list_response
from services import calc

bp = Blueprint("projects", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def _get_project(pid):
    p = db.projects.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Project not found.")
    return p


@bp.route("/solar/projects", methods=["POST"])
def create_project():
    user_id, role = authenticate({"Homeowner"})
    body = get_body()
    require_fields(body, ["homeowner_id", "roof_area_sqft"])
    hid = body["homeowner_id"]
    roof = body["roof_area_sqft"]
    if not is_int(roof) or roof < 0:
        raise err("ERR_INVALID_REQUEST", "roof_area_sqft must be integer >= 0.")
    homeowner = db.homeowners.get(hid)
    if not homeowner:
        raise err("ERR_NOT_FOUND", "Homeowner not found.")
    # ownership: acting homeowner must be the homeowner_id
    if user_id != hid:
        raise err("ERR_NOT_RESOURCE_OWNER", "Cannot create project for another homeowner.")
    with db.lock:
        pid = new_id()
        rec = {
            "id": pid,
            "homeowner_id": hid,
            "installer_id": None,
            "status": "REQUESTED",
            "roof_area_sqft": roof,
            "shading_factor": 0.0,
            "peak_sun_hours": 0.0,
            "system_size_kw": 0.0,
            "estimated_annual_production_kwh": 0.0,
            "gross_system_cost_cents": 0,
            "itc_credit_cents": 0,
            "financing_plan_id": None,
            "lifetime_srec_count": 0,
        }
        rec.update(_common_create())
        db.projects[pid] = rec
        db.project_bank[pid] = 0
    return ok(rec, 201)


@bp.route("/solar/projects/<pid>", methods=["GET"])
def get_project(pid):
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin", "Utility"})
    return ok(_get_project(pid), 200)


@bp.route("/solar/projects", methods=["GET"])
def list_projects():
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin"})
    from flask import request
    rows = list(db.projects.values())
    ho = request.args.get("homeowner_id")
    inst = request.args.get("installer_id")
    fp = request.args.get("financing_plan_id")
    if ho is not None:
        rows = [r for r in rows if r["homeowner_id"] == ho]
    if inst is not None:
        rows = [r for r in rows if r["installer_id"] == inst]
    if fp is not None:
        rows = [r for r in rows if r["financing_plan_id"] == fp]
    return list_response(rows)


# ---------------- State transitions ----------------
@bp.route("/solar/projects/<pid>/assess", methods=["POST"])
def assess(pid):
    user_id, role = authenticate({"SolarInstaller"})
    p = _get_project(pid)
    if p["status"] != "REQUESTED":
        raise err("ERR_INVALID_STATE", "Project not in REQUESTED.")
    body = get_body()
    require_fields(body, ["shading_factor", "peak_sun_hours"])
    sf = body["shading_factor"]
    psh = body["peak_sun_hours"]
    if not is_num(sf) or sf < 0.0 or sf > 1.0:
        raise err("ERR_INVALID_REQUEST", "shading_factor must be in [0,1].")
    if not is_num(psh) or psh < 0:
        raise err("ERR_INVALID_REQUEST", "peak_sun_hours must be >= 0.")
    with db.lock:
        p["shading_factor"] = sf
        p["peak_sun_hours"] = psh
        p["status"] = "ASSESSED"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/design", methods=["POST"])
def design(pid):
    user_id, role = authenticate({"SolarInstaller"})
    p = _get_project(pid)
    # installer (acting) must exist
    installer = entity_for_role(user_id, role)
    if installer is None:
        raise err("ERR_NOT_FOUND", "Installer not found.")
    if p["status"] != "ASSESSED":
        raise err("ERR_INVALID_STATE", "Project not in ASSESSED.")
    homeowner = db.homeowners.get(p["homeowner_id"])
    state_code = homeowner["state_code"]
    # business: installer licensed
    if state_code not in installer["licensed_states"]:
        raise err("ERR_INSTALLER_NOT_LICENSED", "Installer not licensed in homeowner's state.")
    # business: roof area > 0
    if p["roof_area_sqft"] <= 0:
        raise err("ERR_DESIGN_INFEASIBLE", "roof_area_sqft must be > 0.")
    # business: design feasible
    if not calc.design_feasible(p["peak_sun_hours"], p["shading_factor"]):
        raise err("ERR_DESIGN_INFEASIBLE", "System size undefined for this assessment.")
    body = get_body()
    require_fields(body, ["installer_id", "gross_system_cost_cents"])
    gsc = body["gross_system_cost_cents"]
    if not is_int(gsc) or gsc < 0:
        raise err("ERR_INVALID_REQUEST", "gross_system_cost_cents must be integer >= 0.")
    # body installer_id should be the acting installer
    body_iid = body["installer_id"]
    with db.lock:
        p["installer_id"] = body_iid
        p["gross_system_cost_cents"] = gsc
        homeowner2 = db.homeowners.get(p["homeowner_id"])
        usage = homeowner2["annual_kwh_usage"]
        p["system_size_kw"] = calc.size_system(
            p["roof_area_sqft"], usage, p["peak_sun_hours"], p["shading_factor"])
        p["estimated_annual_production_kwh"] = calc.estimate_production(
            p["system_size_kw"], p["peak_sun_hours"], p["shading_factor"])
        p["itc_credit_cents"] = calc.itc_credit(gsc, state_code)
        p["status"] = "DESIGNED"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/submit-permit", methods=["POST"])
def submit_permit(pid):
    authenticate({"SolarInstaller"})
    p = _get_project(pid)
    if p["status"] != "DESIGNED":
        raise err("ERR_INVALID_STATE", "Project not in DESIGNED.")
    fpid = p["financing_plan_id"]
    plan = db.financing_plans.get(fpid) if fpid else None
    if not fpid or plan is None or plan["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Project has no ACTIVE financing plan.")
    with db.lock:
        p["status"] = "PERMIT_PENDING"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/approve-permit", methods=["POST"])
def approve_permit(pid):
    authenticate({"PlatformAdmin"})
    p = _get_project(pid)
    if p["status"] != "PERMIT_PENDING":
        raise err("ERR_INVALID_STATE", "Project not in PERMIT_PENDING.")
    with db.lock:
        p["status"] = "PERMIT_APPROVED"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/complete-install", methods=["POST"])
def complete_install(pid):
    user_id, role = authenticate({"SolarInstaller"})
    p = _get_project(pid)
    if p["status"] not in ("PERMIT_APPROVED", "REMEDIATION"):
        raise err("ERR_INVALID_STATE", "Project not in PERMIT_APPROVED or REMEDIATION.")
    if p["installer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting installer is not the project's installer.")
    with db.lock:
        p["status"] = "INSTALLED"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/inspect", methods=["POST"])
def inspect(pid):
    authenticate({"PlatformAdmin"})
    p = _get_project(pid)
    if p["status"] != "INSTALLED":
        raise err("ERR_INVALID_STATE", "Project not in INSTALLED.")
    body = get_body()
    require_fields(body, ["result"])
    result = body["result"]
    if result not in ("PASS", "FAIL"):
        raise err("ERR_INVALID_REQUEST", "result must be PASS or FAIL.")
    with db.lock:
        p["status"] = "PTO_PENDING" if result == "PASS" else "FAILED_INSPECTION"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/start-remediation", methods=["POST"])
def start_remediation(pid):
    user_id, role = authenticate({"SolarInstaller"})
    p = _get_project(pid)
    if p["status"] != "FAILED_INSPECTION":
        raise err("ERR_INVALID_STATE", "Project not in FAILED_INSPECTION.")
    if p["installer_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting installer is not the project's installer.")
    with db.lock:
        p["status"] = "REMEDIATION"
        db.touch(p)
    return ok(p, 200)


@bp.route("/solar/projects/<pid>/cancel", methods=["POST"])
def cancel(pid):
    user_id, role = authenticate({"Homeowner"})
    p = _get_project(pid)
    if p["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    if p["status"] not in ("REQUESTED", "ASSESSED", "DESIGNED"):
        raise err("ERR_INVALID_STATE", "Project not cancellable.")
    with db.lock:
        p["status"] = "CANCELLED"
        fpid = p["financing_plan_id"]
        if fpid:
            plan = db.financing_plans.get(fpid)
            if plan and plan["status"] != "TERMINATED":
                plan["status"] = "TERMINATED"
                db.touch(plan)
        db.touch(p)
    return ok(p, 200)
