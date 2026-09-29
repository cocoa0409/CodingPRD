"""Inspection scheduling, results, cancellation (PRD sections 3.8, 3.9)."""
from flask import Blueprint, request

import clock
import domain
import envelope
import errors
import fields
import guards
import store
from errors import ApiError
from guards import (CONTRACTOR, FIELD_INSPECTOR, PROGRAM_ADMIN,
                    PROGRAM_REVIEWER, authorize)

bp = Blueprint("inspections", __name__)

DEAD_PROJECT_STATES = ("REJECTED", "EXPIRED", "FAILED_FINAL", "CLAWED_BACK")


@bp.post("/inspections")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def schedule_inspection():
    payload = guards.body()
    project_id = fields.req_str(payload, "project_id", allow_empty=False)
    inspector_id = fields.req_str(payload, "inspector_id", allow_empty=False)
    inspection_type = fields.req_enum(payload, "inspection_type", ("SPOT", "POST_INSTALL"))
    start = fields.req_datetime(payload, "scheduled_start")
    end = fields.req_datetime(payload, "scheduled_end")
    if end < start:
        raise ApiError(
            errors.ERR_INVALID_REQUEST,
            message="scheduled_end must not be earlier than scheduled_start.",
        )

    project = domain.get_project(project_id)
    inspector = domain.get_inspector(inspector_id)
    program = domain.program_of_project(project)
    if program is None or inspector["program_id"] != program["id"]:
        raise ApiError(errors.ERR_INSPECTOR_NOT_FOUND)

    if project["status"] in DEAD_PROJECT_STATES:
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if inspection_type == "POST_INSTALL":
        if project["status"] == "PAID":
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
        if project["status"] == "REMEDIATION" and domain.project_has_scheduled_inspection(
                project["id"]):
            raise ApiError(errors.ERR_OPEN_INSPECTION_PENDING)

    if domain.inspector_window_conflict(inspector["id"], start, end):
        raise ApiError(errors.ERR_INSPECTOR_WINDOW_CONFLICT)

    inspection = store.new_record({
        "project_id": project["id"],
        "inspector_id": inspector["id"],
        "inspection_type": inspection_type,
        "scheduled_start": clock.iso(start),
        "scheduled_end": clock.iso(end),
        "status": "SCHEDULED",
        "result_recorded_at": None,
        "deficiency_count": 0,
        "deficiency_severity_max": 0,
        "rejected_measure_codes": [],
        "notes": None,
        "scheduled_by_user_id": guards.actor_id(),
        "recorded_by_user_id": None,
    })
    store.inspections[inspection["id"]] = inspection

    if inspection_type == "POST_INSTALL" and project["status"] == "REMEDIATION":
        project["status"] = "INSTALLED"
        store.touch(project)

    return envelope.object_response(store.public(inspection), 201)


@bp.get("/inspections/<inspection_id>")
@authorize(CONTRACTOR, FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def read_inspection(inspection_id):
    inspection = domain.get_inspection(inspection_id)
    return envelope.object_response(store.public(inspection))


@bp.get("/inspections")
@authorize(FIELD_INSPECTOR, PROGRAM_REVIEWER, PROGRAM_ADMIN)
def list_inspections():
    limit, offset = guards.pagination()
    project_id = request.args.get("project_id")
    inspector_id = request.args.get("inspector_id")
    inspection_type = request.args.get("inspection_type")
    status = request.args.get("status")
    records = store.ordered(
        store.inspections,
        lambda i: (project_id is None or i["project_id"] == project_id)
        and (inspector_id is None or i["inspector_id"] == inspector_id)
        and (inspection_type is None or i["inspection_type"] == inspection_type)
        and (status is None or i["status"] == status),
    )
    page = [store.public(r) for r in guards.paginate(records, limit, offset)]
    return envelope.list_response(page, limit, offset, len(records))


@bp.post("/inspections/<inspection_id>/result")
@authorize(FIELD_INSPECTOR)
def record_inspection_result(inspection_id):
    payload = guards.body()
    result = fields.req_enum(payload, "result", ("PASS", "CONDITIONAL_PASS", "FAIL"))
    deficiency_count = fields.opt_int(payload, "deficiency_count", default=0, minimum=0)
    severity_max = fields.opt_int(
        payload, "deficiency_severity_max", default=0, minimum=0, maximum=5)
    rejected_codes = fields.str_list(payload, "rejected_measure_codes", default=[])
    notes = fields.opt_str(payload, "notes")

    inspection = domain.get_inspection(inspection_id)
    if guards.actor_id() != inspection["inspector_id"]:
        raise ApiError(errors.ERR_NOT_RESOURCE_OWNER)

    if inspection["status"] in ("PASSED", "CONDITIONAL_PASS", "FAILED"):
        raise ApiError(errors.ERR_INSPECTION_ALREADY_RECORDED)
    if inspection["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    if result == "CONDITIONAL_PASS" and severity_max > 2:
        raise ApiError(
            errors.ERR_INVALID_STATE_TRANSITION,
            message="A conditional pass requires deficiency_severity_max of 2 or less.",
        )

    project = store.projects.get(inspection["project_id"])
    if project is None:
        raise ApiError(errors.ERR_PROJECT_NOT_FOUND)
    lines = domain.project_measures(project["id"])

    if inspection["inspection_type"] == "POST_INSTALL":
        if project["status"] != "INSTALLED":
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
        for line in lines:
            if (line["install_status"] != "INSTALLED"
                    or line["verified_quantity"] is None
                    or line["actual_cost_cents"] is None):
                raise ApiError(
                    errors.ERR_INVALID_STATE_TRANSITION,
                    message="Every measure line must be INSTALLED with verified figures.",
                )
        for other in store.ordered(store.inspections):
            if (other["project_id"] == project["id"]
                    and other["id"] != inspection["id"]
                    and other["inspection_type"] == "SPOT"
                    and other["recorded_by_user_id"] == guards.actor_id()):
                raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES)

    known = {line["measure_code"] for line in lines}
    for code in rejected_codes:
        if code not in known:
            raise ApiError(errors.ERR_MEASURE_NOT_ON_PROJECT)

    inspection["status"] = {
        "PASS": "PASSED", "CONDITIONAL_PASS": "CONDITIONAL_PASS", "FAIL": "FAILED",
    }[result]
    inspection["result_recorded_at"] = clock.now_iso()
    inspection["recorded_by_user_id"] = guards.actor_id()
    inspection["deficiency_count"] = deficiency_count
    inspection["deficiency_severity_max"] = severity_max
    inspection["rejected_measure_codes"] = list(rejected_codes)
    if notes is not None:
        inspection["notes"] = notes
    store.touch(inspection)

    program = domain.program_of_project(project)
    contractor = domain.contractor_of_project(project)

    if inspection["inspection_type"] == "POST_INSTALL" and result in ("PASS", "CONDITIONAL_PASS"):
        if result == "CONDITIONAL_PASS":
            project["conditional_pass_flag"] = True
        for line in lines:
            if line["verification_status"] == "PENDING":
                line["verification_status"] = "VERIFIED"
                store.touch(line)
        project["status"] = "VERIFIED"
        allocation = domain.run_allocation(project, "final")
        domain.persist_allocation(project, "final", allocation)
        domain.recompute_stacking(project)
        store.touch(project)
    elif inspection["inspection_type"] == "POST_INSTALL" and result == "FAIL":
        if project["remediation_count"] < program["max_remediations_per_project"]:
            project["status"] = "INSPECTION_FAILED"
            domain.inspection_failure_cascade(project, rejected_codes)
            store.touch(project)
        else:
            domain.fail_final(project, inspection, guards.actor_id())
    elif result == "FAIL" and project["status"] == "PAID":
        domain.post_payment_clawback(project, inspection, guards.actor_id())

    domain.recompute_quality(contractor)
    return envelope.object_response(store.public(inspection))


@bp.post("/inspections/<inspection_id>/cancellation")
@authorize(PROGRAM_REVIEWER, PROGRAM_ADMIN)
def cancel_inspection(inspection_id):
    payload = guards.body()
    fields.opt_str(payload, "cancellation_reason")
    inspection = domain.get_inspection(inspection_id)
    if inspection["status"] in ("PASSED", "CONDITIONAL_PASS", "FAILED"):
        raise ApiError(errors.ERR_INSPECTION_ALREADY_RECORDED)
    if inspection["status"] != "SCHEDULED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION)
    inspection["status"] = "CANCELLED"
    store.touch(inspection)
    return envelope.object_response(store.public(inspection))
