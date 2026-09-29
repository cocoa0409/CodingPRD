"""Performance guarantee demonstrations and certification."""
from flask import Blueprint

import auth
import calc
import clock
import constants as C
import db
import domain
import response
import serialize
import validate
from errors import fail
from util import D, format_dt

bp = Blueprint("demos", __name__)


def _parse_readings(body):
    raw = validate.array(body, "readings", min_length=1)
    readings = []
    for item in raw:
        if not isinstance(item, dict):
            fail("ERR_INVALID_REQUEST", "readings entries must be objects")
        parameter = validate.enum(item, "parameter", C.OBJECTIVE_PARAMETERS)
        measured = validate.number(item, "measured_value", minimum=0)
        readings.append({"parameter": parameter, "measured_value": measured})
    return readings


@bp.post("/performance-demos")
def create_demo():
    actor = auth.require("CommissioningEngineer")
    body = validate.body()
    project = validate.catalog_ref(body, "project_id", "projects")
    skid = validate.catalog_ref(body, "skid_id", "skids")
    validate.string(body, "project_id")
    validate.string(body, "skid_id")
    start = validate.instant(body, "window_start_at")
    end = validate.instant(body, "window_end_at")
    readings = _parse_readings(body)
    if end <= start:
        fail("ERR_INVALID_REQUEST",
             "window_end_at must be strictly after window_start_at")

    if calc.conflicting_demos(skid["id"], start, end):
        fail("ERR_DEMO_WINDOW_CONFLICT",
             "the skid already has a pending demonstration in this window")

    closed = [d for d in db.all_rows("performance_demos")
              if d["project_id"] == project["id"]
              and d["result"] in C.DEMO_CLOSED_RESULTS]
    if len(closed) >= C.MAX_DEMO_ROUNDS:
        fail("ERR_MAX_DEMO_ROUNDS_EXCEEDED",
             "the project has exhausted its demonstration rounds")

    package = domain.package_of_skid(skid)
    skid_project = domain.project_of_package(package) if package else None
    if (project["status"] != "COMMISSIONING"
            or package is None
            or package["status"] not in ("FAT_PASSED", "SHIPPED")
            or skid_project is None
            or skid_project["id"] != project["id"]):
        fail("ERR_GUARANTEE_PREREQ_NOT_MET",
             "the project or skid is not ready for a guarantee demonstration")

    row = db.new_row("performance_demos")
    row.update({
        "project_id": project["id"],
        "skid_id": skid["id"],
        "round_no": len(closed) + 1,
        "window_start_at": format_dt(start),
        "window_end_at": format_dt(end),
        "readings": readings,
        "evaluation": [],
        "min_margin_pct": None,
        "result": "PENDING",
        "recorded_by_user_id": actor,
        "certified_by_user_id": None,
    })
    db.insert("performance_demos", row)

    if package["status"] == "FAT_PASSED":
        package["status"] = "SHIPPED"
        db.touch(package)
    if project["guarantee_status"] == "NOT_STARTED":
        project["guarantee_status"] = "DEMONSTRATING"
    db.touch(project)

    return response.created(serialize.row(row))


@bp.get("/performance-demos")
def list_demos():
    auth.require(*auth.ROLES)
    project_id = validate.string_filter("project_id")
    skid_id = validate.string_filter("skid_id")
    result = validate.enum_filter("result", C.DEMO_RESULTS)
    rows = db.all_rows("performance_demos")
    if project_id:
        rows = [r for r in rows if r["project_id"] == project_id]
    if skid_id:
        rows = [r for r in rows if r["skid_id"] == skid_id]
    if result:
        rows = [r for r in rows if r["result"] == result]
    rows = db.sorted_rows(rows, [("round_no", "asc"), ("created_at", "asc")])
    return response.paginate(rows, serialize.row)


@bp.get("/performance-demos/<demo_id>")
def get_demo(demo_id):
    auth.require(*auth.ROLES)
    return response.ok(serialize.row(domain.demo(demo_id)))


@bp.post("/performance-demos/<demo_id>/certify")
def certify_demo(demo_id):
    actor = auth.require("QualityEngineer")
    demo = domain.demo(demo_id)
    body = validate.body()
    certification = validate.enum(body, "certification", C.CERTIFICATIONS)
    validate.string(body, "certification_note", required=False, default=None,
                    max_length=2000, allow_blank=True)

    if demo["result"] != "PENDING":
        fail("ERR_DEMO_ALREADY_CERTIFIED", "the demonstration is already certified")
    domain.forbid_same_user(actor, demo["recorded_by_user_id"],
                            "ERR_SOD_RECORDER_IS_CERTIFIER")

    evaluation, min_margin, all_passed = calc.evaluate_guarantee(
        demo["project_id"], demo["readings"])
    result = calc.demo_result(certification, all_passed, min_margin)

    demo["evaluation"] = evaluation
    demo["min_margin_pct"] = min_margin
    demo["result"] = result
    demo["certified_by_user_id"] = actor
    db.touch(demo)

    project = db.get("projects", demo["project_id"])
    if project is None:
        return response.ok(serialize.row(demo))

    if result == "PASSED":
        project["guarantee_status"] = "MET"
        if project["status"] == "COMMISSIONING":
            project["status"] = "GUARANTEED"
        activated = False
        for agreement in db.all_rows("service_agreements"):
            if (agreement["project_id"] != project["id"]
                    or agreement["status"] != "PENDING_ACTIVATION"):
                continue
            domain.activate_agreement(agreement)
            activated = True
        if project["status"] == "GUARANTEED":
            has_active = any(a["project_id"] == project["id"]
                             and a["status"] == "ACTIVE"
                             for a in db.all_rows("service_agreements"))
            if activated or has_active:
                project["status"] = "SERVICE_ACTIVE"
    elif int(demo["round_no"]) >= C.MAX_DEMO_ROUNDS:
        if project["status"] == "COMMISSIONING":
            project["status"] = "REMEDIATION"
        project["guarantee_status"] = "DEFAULTED"
        project["liquidated_damages_cents"] = calc.liquidated_damages_cents(project)

    domain.recompute_posture(project)
    return response.ok(serialize.row(demo))
