"""RiggingInspection endpoints."""

from datetime import timezone

from flask import Blueprint, request

import db
import errors
import util
from middleware import require_roles
from response import success_object, success_list, now_iso
from services import domain, calculations as calc

bp = Blueprint("rigging_inspections", __name__)

READ_ROLES = ("LoftManager", "Sailmaker", "Measurer", "Rigger", "Customer")
SCOPES = ("STANDING", "RUNNING", "FULL")
VERDICTS = ("PASS", "ADVISORY", "FAIL")


@bp.post("/lofts/boats/<boatId>/rigging-inspections")
def create_inspection(boatId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    body = util.get_body()
    rigging_scope = util.as_enum(util.require_field(body, "rigging_scope"), "rigging_scope", SCOPES)
    expected_boat_version = util.as_int(util.require_field(body, "expected_boat_version"), "expected_boat_version")
    # OCC check — last gate.
    if expected_boat_version != boat["version"]:
        raise errors.stale_boat_version()
    insp = util.stamp_new({
        "boat_id": boat["id"],
        "rigging_scope": rigging_scope,
        "inspected_at": None,
        "standing_months_at_inspection": None,
        "standing_replacement_due_date": None,
        "running_replacement_due_hours": None,
        "verdict": None,
        "inspection_status": "SCHEDULED",
    })
    db.rigging_inspections[insp["id"]] = insp
    # Successful scheduling increments Boat.version by 1.
    util.touch(boat)
    return success_object(domain.serialize(insp), 201)


@bp.get("/lofts/boats/<boatId>/rigging-inspections")
def list_boat_inspections(boatId):
    require_roles(*READ_ROLES)
    domain.get_boat_or_404(boatId)
    limit, offset = util.pagination_params()
    items = [i for i in db.rigging_inspections.values() if i["boat_id"] == boatId]
    items = util.filter_exact(items, "inspection_status", request.args.get("inspection_status"))
    items = util.sort_by_created(items)
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(i) for i in page], limit, offset, total)


@bp.get("/lofts/rigging-inspections")
def list_inspections():
    require_roles(*READ_ROLES)
    limit, offset = util.pagination_params()
    items = util.sort_by_created(list(db.rigging_inspections.values()))
    items = util.filter_exact(items, "boat_id", request.args.get("boat_id"))
    items = util.filter_exact(items, "inspection_status", request.args.get("inspection_status"))
    items = util.filter_exact(items, "rigging_scope", request.args.get("rigging_scope"))
    page, total = util.paginate(items, limit, offset)
    return success_list([domain.serialize(i) for i in page], limit, offset, total)


@bp.get("/lofts/rigging-inspections/<inspectionId>")
def get_inspection(inspectionId):
    require_roles(*READ_ROLES)
    insp = domain.get_inspection_or_404(inspectionId)
    return success_object(domain.serialize(insp))


@bp.post("/lofts/boats/<boatId>/rigging-inspections/<inspectionId>/report")
def report_inspection(boatId, inspectionId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    insp = domain.get_inspection_or_404(inspectionId)
    domain.check_child_of(insp, "boat_id", boat["id"])
    if insp["inspection_status"] != "SCHEDULED":
        raise errors.invalid_state(f"Inspection must be SCHEDULED to report (is {insp['inspection_status']})")
    body = util.get_body()
    verdict = util.as_enum(util.require_field(body, "verdict"), "verdict", VERDICTS)
    inspected_at_dt = __import__("datetime").datetime.now(timezone.utc)
    install_dt = util.parse_iso_datetime(boat["standing_rigging_install_date"], "standing_rigging_install_date")
    standing_months = calc.whole_months_between(install_dt, inspected_at_dt)
    due_dt = calc.add_months(install_dt, calc.MANDATORY_REPLACEMENT_MONTHS)
    # Verdict floor: PASS overridden to ADVISORY when either clock trips.
    if standing_months >= calc.MANDATORY_REPLACEMENT_MONTHS or (
        boat.get("running_rigging_hours_accumulated", 0) >= calc.RUNNING_REPLACEMENT_HOURS
    ):
        if verdict == "PASS":
            verdict = "ADVISORY"
    insp["verdict"] = verdict
    insp["inspected_at"] = now_iso()
    insp["standing_months_at_inspection"] = standing_months
    insp["standing_replacement_due_date"] = due_dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{due_dt.microsecond // 1000:03d}Z"
    insp["running_replacement_due_hours"] = calc.RUNNING_REPLACEMENT_HOURS
    insp["inspection_status"] = "REPORTED"
    util.touch(insp)
    if verdict == "FAIL":
        domain.fail_inspection_cascade(boat)
    return success_object(domain.serialize(insp))


@bp.post("/lofts/boats/<boatId>/rigging-inspections/<inspectionId>/close")
def close_inspection(boatId, inspectionId):
    require_roles("Rigger")
    boat = domain.get_boat_or_404(boatId)
    insp = domain.get_inspection_or_404(inspectionId)
    domain.check_child_of(insp, "boat_id", boat["id"])
    if insp["inspection_status"] != "REPORTED":
        raise errors.invalid_state(f"Inspection must be REPORTED to close (is {insp['inspection_status']})")
    if insp["verdict"] == "FAIL":
        replacement_exists = any(
            o for o in db.rigging_inspections.values()
            if o["boat_id"] == boat["id"]
            and o["id"] != insp["id"]
            and o["rigging_scope"] == insp["rigging_scope"]
            and o["inspection_status"] == "REPORTED"
            and o["verdict"] is not None and o["verdict"] != "FAIL"
        )
        if not replacement_exists:
            raise errors.fail_not_superseded()
        insp["inspection_status"] = "CLOSED"
        util.touch(insp)
        domain.close_fail_inspection_release(boat)
    else:
        insp["inspection_status"] = "CLOSED"
        util.touch(insp)
    return success_object(domain.serialize(insp))
