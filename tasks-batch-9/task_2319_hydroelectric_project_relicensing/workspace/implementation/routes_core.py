"""Logical clock, projects, dams and study sites."""
from flask import Blueprint

import auth
import clock
import constants as C
import listing
import payload
import response
import serializers as S
import services as SV
from db import db, sorted_rows
from errors import ApiError
from numeric import q1, q2

bp = Blueprint("core", __name__)


# ---------------------------------------------------------------------------
# logical clock
# ---------------------------------------------------------------------------


@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.authenticate(["Regulator"], clock_endpoint=True)
    data = payload.body()
    raw = payload.req_field(data, "to_iso8601")
    parsed = clock.parse_iso8601_datetime(raw) if isinstance(raw, str) else None
    if parsed is None:
        payload.bad("to_iso8601", "must be an ISO 8601 instant")
    clock.set_now(parsed)
    return response.object_response({"current_utc": clock.now_iso()})


@bp.get("/_clock")
def read_clock():
    auth.authenticate(C.ALL_ROLES, clock_endpoint=True)
    return response.object_response({"current_utc": clock.now_iso()})


# ---------------------------------------------------------------------------
# projects
# ---------------------------------------------------------------------------


@bp.post("/relicensing/projects")
def create_project():
    auth.authenticate(["Regulator"])
    data = payload.body()

    license_number = payload.req_string(data, "license_number")
    project_name = payload.req_string(data, "project_name")
    installed_capacity_mw = payload.req_number(data, "installed_capacity_mw", exclusive_min=0)
    base_generation = payload.req_number(data, "base_annual_generation_mwh", exclusive_min=0)
    expiration = payload.req_date(data, "license_expiration_date")
    waiver = payload.opt_bool(data, "infeasibility_waiver_granted", False)

    if expiration <= clock.today():
        payload.bad("license_expiration_date", "must fall strictly after the current clock date")

    for row in db.projects.values():
        if row["license_number"] == license_number:
            raise ApiError("ERR_DUPLICATE_KEY", "license_number is already registered.")

    project = SV.base_row()
    project.update(
        {
            "license_number": license_number,
            "project_name": project_name,
            "installed_capacity_mw": installed_capacity_mw,
            "base_annual_generation_mwh": base_generation,
            "license_expiration_date": clock.fmt_date(expiration),
            "infeasibility_waiver_granted": waiver,
            "stage": "PRE_FILING",
            "pad_filed_at": None,
            "pad_year": None,
            "application_filed_at": None,
            "timeline_posture": "ON_TRACK",
            "regulatory_posture": "OPEN",
            "total_pme_annual_cost_usd": q2(0),
            "total_generation_loss_mwh": q1(0),
            "administrative_annual_charge_usd": q2(0),
            "total_annual_burden_usd": q2(0),
            "burden_ratio_pct": q2(0),
            "economically_infeasible": False,
            "wqc_status": "NONE",
            "unresolved_mandatory_comment_count": 0,
            "open_deficiency_count": 0,
            "compliance_flag_count": 0,
            "last_sweep_at": None,
        }
    )
    db.projects[project["id"]] = project

    SV.refresh_timeline_posture(project)
    SV.refresh_regulatory_posture(project)
    return response.object_response(S.project(project), 201)


@bp.get("/relicensing/projects")
def list_projects():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(
        sorted_rows(db.projects), S.project, ("stage", "regulatory_posture", "timeline_posture")
    )


@bp.get("/relicensing/projects/<project_id>")
def get_project(project_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.project(SV.fetch("projects", project_id)))


@bp.patch("/relicensing/projects/<project_id>")
def patch_project(project_id):
    auth.authenticate(["Regulator"])
    project = SV.fetch("projects", project_id)
    data = payload.body()

    project_name = payload.opt_string(data, "project_name", None, allow_empty=False)
    base_generation = payload.opt_number(data, "base_annual_generation_mwh", None, exclusive_min=0)
    waiver = payload.opt_bool(data, "infeasibility_waiver_granted", None)

    SV.require_not_frozen(project)

    if project_name is not None:
        project["project_name"] = project_name
    if base_generation is not None:
        project["base_annual_generation_mwh"] = base_generation
    if waiver is not None:
        project["infeasibility_waiver_granted"] = waiver

    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.project(project))


@bp.post("/relicensing/projects/<project_id>/pre-application-document")
def file_pad(project_id):
    auth.authenticate(["Licensee"])
    project = SV.fetch("projects", project_id)
    data = payload.body()
    payload.opt_string(data, "filing_note")

    SV.require_not_frozen(project)
    SV.require_stage(project, ["PRE_FILING"])

    if clock.today() > SV.pad_due_date(project):
        raise ApiError(
            "ERR_FILING_DEADLINE_PASSED",
            "The pre-application document deadline has passed.",
        )

    project["stage"] = "PAD_FILED"
    project["pad_filed_at"] = clock.now_iso()
    project["pad_year"] = clock.now().year

    SV.refresh_timeline_posture(project)
    SV.finalize_project(project)
    SV.touch(project)
    return response.object_response(S.project(project))


@bp.post("/relicensing/projects/<project_id>/run-compliance-sweep")
def run_sweep(project_id):
    auth.authenticate(["Regulator"])
    project = SV.fetch("projects", project_id)
    payload.body()

    today = clock.today()

    orders = [
        order
        for order in sorted_rows(db.orders)
        if SV.project_of_order(order)["id"] == project["id"]
        and order["compliance_state"] != "SUPERSEDED"
    ]
    for order in orders:
        for obligation in SV.order_obligations(order):
            if obligation["status"] not in ("PENDING", "SCHEDULED"):
                continue
            due = clock.parse_iso_date(obligation["due_date"])
            if due is not None and due < today:
                obligation["status"] = "OVERDUE"
                obligation["overdue_marked_at"] = clock.now_iso()
                SV.touch(obligation)
    for order in orders:
        SV.refresh_order_violations(order, flag_on_violation=True)

    for wqc in sorted_rows(db.wqcs, lambda w: w["project_id"] == project["id"]):
        if wqc["status"] != "REQUESTED":
            continue
        waiver_date = clock.parse_iso_date(wqc["statutory_waiver_date"])
        if waiver_date is not None and today >= waiver_date:
            wqc["status"] = "WAIVED"
            wqc["decided_at"] = clock.now_iso()
            SV.touch(wqc)

    SV.refresh_timeline_posture(project)
    SV.finalize_project(project)

    project["last_sweep_at"] = clock.now_iso()
    SV.touch(project)
    return response.object_response(S.project(project))


# ---------------------------------------------------------------------------
# dams
# ---------------------------------------------------------------------------


@bp.post("/relicensing/dams")
def create_dam():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)

    dam_code = payload.req_string(data, "dam_code")
    hazard_class = payload.req_enum(data, "hazard_class", C.HAZARD_CLASSES)
    interval = payload.req_int(data, "inspection_interval_months", minimum=6, maximum=60)
    eap_required = payload.opt_bool(data, "eap_exercise_required", True)
    max_concurrent = payload.opt_int(data, "max_concurrent_field_activities", 1, minimum=1)

    for row in db.dams.values():
        if row["project_id"] == project_id and row["dam_code"] == dam_code:
            raise ApiError("ERR_DUPLICATE_KEY", "dam_code is already registered on this project.")

    SV.require_not_frozen(project)

    dam = SV.base_row()
    dam.update(
        {
            "project_id": project_id,
            "dam_code": dam_code,
            "hazard_class": hazard_class,
            "inspection_interval_months": interval,
            "eap_exercise_required": eap_required,
            "max_concurrent_field_activities": max_concurrent,
        }
    )
    db.dams[dam["id"]] = dam

    SV.finalize_project(project)
    return response.object_response(S.dam(dam), 201)


@bp.get("/relicensing/dams")
def list_dams():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(sorted_rows(db.dams), S.dam, ("project_id", "hazard_class"))


@bp.get("/relicensing/dams/<dam_id>")
def get_dam(dam_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.dam(SV.fetch("dams", dam_id)))


# ---------------------------------------------------------------------------
# study sites
# ---------------------------------------------------------------------------


@bp.post("/relicensing/sites")
def create_site():
    auth.authenticate(["Licensee"])
    data = payload.body()

    project_id = payload.req_string(data, "project_id")
    project = SV.fetch("projects", project_id)

    site_code = payload.req_string(data, "site_code")
    river_mile = payload.req_number(data, "river_mile")
    min_rest = payload.opt_int(data, "min_rest_buffer_days", 0, minimum=0)
    sensitivity = payload.opt_enum(data, "cultural_sensitivity", C.CULTURAL_SENSITIVITIES, "NONE")

    for row in db.sites.values():
        if row["project_id"] == project_id and row["site_code"] == site_code:
            raise ApiError("ERR_DUPLICATE_KEY", "site_code is already registered on this project.")

    SV.require_not_frozen(project)

    site = SV.base_row()
    site.update(
        {
            "project_id": project_id,
            "site_code": site_code,
            "river_mile": river_mile,
            "min_rest_buffer_days": min_rest,
            "cultural_sensitivity": sensitivity,
        }
    )
    db.sites[site["id"]] = site

    SV.finalize_project(project)
    return response.object_response(S.site(site), 201)


@bp.get("/relicensing/sites")
def list_sites():
    auth.authenticate(C.ALL_ROLES)
    return listing.respond(sorted_rows(db.sites), S.site, ("project_id", "cultural_sensitivity"))


@bp.get("/relicensing/sites/<site_id>")
def get_site(site_id):
    auth.authenticate(C.ALL_ROLES)
    return response.object_response(S.site(SV.fetch("sites", site_id)))
