"""Work-order scheduling plus the two independent state dimensions."""

from datetime import timedelta

from flask import Blueprint

import calculations as calc
from db import assign, commit, create, db
from errors import ApiError
from middleware import (authenticate, body, filter_arg, opt_id, opt_num, opt_str,
                        pagination, req_datetime, req_enum, resolve)
from response import entity_response, list_response
from services import project as svc

bp = Blueprint("work_orders", __name__)

READ_ROLES = ("ProjectCoordinator", "FieldTechnician", "LicensedSiteProfessional",
              "ComplianceOfficer")


@bp.post("/work-orders")
def create_work_order():
    authenticate(("ProjectCoordinator",))
    payload = body()
    project_id = opt_id(payload, "tank_project_id")
    project = resolve("tank_projects", project_id) if project_id else None
    crew_id = opt_id(payload, "crew_id")
    crew = resolve("crews", crew_id) if crew_id else None
    if project is None:
        raise ApiError("ERR_INVALID_REQUEST", "tank_project_id is required.")
    if crew is None:
        raise ApiError("ERR_INVALID_REQUEST", "crew_id is required.")

    method = req_enum(payload, "method", calc.METHODS)
    start = req_datetime(payload, "scheduled_start_at")
    end = req_datetime(payload, "scheduled_end_at")
    if end <= start:
        raise ApiError("ERR_INVALID_REQUEST",
                       "scheduled_end_at must be strictly later than scheduled_start_at.")
    override_reason = opt_str(payload, "method_override_reason")

    # rule 12 — the override justification precedes the crew calendar check.
    if method != project["recommended_method"] and override_reason is None:
        raise ApiError("ERR_METHOD_OVERRIDE_REASON_REQUIRED")

    # rule 13 — buffered crew calendar.
    buffer = timedelta(minutes=int(crew["mobilization_buffer_minutes"]))
    for candidate in svc.crew_bookings(crew["id"]):
        if (start - buffer) < candidate["scheduled_end_at"] \
                and candidate["scheduled_start_at"] < (end + buffer):
            raise ApiError("ERR_CREW_BOOKING_CONFLICT")

    # rule 15 — at most one live work order per project.
    for existing in svc.children("work_orders", project["id"]):
        if existing["field_status"] in svc.LIVE_FIELD_STATUSES:
            raise ApiError("ERR_WORK_ORDER_ALREADY_OPEN")

    work_order = create("work_orders", {
        "tank_project_id": project["id"],
        "crew_id": crew["id"],
        "method": method,
        "method_override_reason": override_reason,
        "scheduled_start_at": start,
        "scheduled_end_at": end,
        "field_status": "SCHEDULED",
        "billing_status": "UNBILLED",
        "actual_excavated_cubic_yards": None,
        "hauled_tons": None,
        "abort_reason": None,
    })
    return entity_response(work_order, 201)


@bp.get("/work-orders")
def list_work_orders():
    authenticate(READ_ROLES)
    limit, offset = pagination()
    project_id = filter_arg("tank_project_id")
    crew_id = filter_arg("crew_id")
    field_status = filter_arg("field_status")
    billing_status = filter_arg("billing_status")
    rows = list(db.work_orders.values())
    if project_id is not None:
        rows = [r for r in rows if r["tank_project_id"] == project_id]
    if crew_id is not None:
        rows = [r for r in rows if r["crew_id"] == crew_id]
    if field_status is not None:
        rows = [r for r in rows if r["field_status"] == field_status]
    if billing_status is not None:
        rows = [r for r in rows if r["billing_status"] == billing_status]
    return list_response(rows, limit, offset)


@bp.get("/work-orders/<work_order_id>")
def read_work_order(work_order_id):
    authenticate(READ_ROLES)
    return entity_response(resolve("work_orders", work_order_id))


@bp.post("/work-orders/<work_order_id>/field-events")
def field_event(work_order_id):
    authenticate(("FieldTechnician",))
    work_order = resolve("work_orders", work_order_id)
    payload = body()
    event = req_enum(payload, "event", ("MOBILIZE", "START", "COMPLETE", "ABORT"))
    excavated = opt_num(payload, "actual_excavated_cubic_yards", minimum=0)
    hauled = opt_num(payload, "hauled_tons", minimum=0)
    abort_reason = opt_str(payload, "abort_reason")
    if event == "COMPLETE" and (excavated is None or hauled is None):
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "actual_excavated_cubic_yards and hauled_tons are required on COMPLETE.")
    if event == "ABORT" and abort_reason is None:
        raise ApiError("ERR_INVALID_REQUEST", "abort_reason is required on ABORT.")

    project = db.tank_projects.get(work_order["tank_project_id"])

    if event == "MOBILIZE":
        if work_order["field_status"] != "SCHEDULED":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        if project is None or project["status"] != "PERMITTED":
            raise ApiError("ERR_PROJECT_STATE_INVALID")
        _check_mobilization_permits(project)
        assign(work_order, "field_status", "MOBILIZED")
    elif event == "START":
        if work_order["field_status"] != "MOBILIZED":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        if project is None or project["status"] != "PERMITTED":
            raise ApiError("ERR_PROJECT_STATE_INVALID")
        assign(work_order, "field_status", "IN_PROGRESS")
        assign(project, "decommission_method", work_order["method"])
        assign(project, "status", "DECOMMISSIONING")
        svc.recompute_blockers(project)
    elif event == "COMPLETE":
        if work_order["field_status"] != "IN_PROGRESS":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        if project is None or project["status"] != "DECOMMISSIONING":
            raise ApiError("ERR_PROJECT_STATE_INVALID")
        assign(work_order, "actual_excavated_cubic_yards", excavated)
        assign(work_order, "hauled_tons", hauled)
        assign(work_order, "field_status", "FIELD_COMPLETE")
        if work_order["billing_status"] == "UNBILLED":
            assign(work_order, "billing_status", "BILLABLE")
        assign(project, "actual_excavated_cubic_yards", excavated)
        assign(project, "hauled_tons", hauled)
        if project["sampling_round"] == 0:
            assign(project, "sampling_round", 1)
        assign(project, "status", "SAMPLING")
        svc.recompute_blockers(project)
    else:  # ABORT
        if work_order["field_status"] not in svc.LIVE_FIELD_STATUSES:
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        svc.abort_work_order(work_order, abort_reason)
        if project is not None:
            svc.recompute_blockers(project)
    return entity_response(work_order)


def _check_mobilization_permits(project):
    """§3.4 — fire-marshal notice, then the municipal permit (rule 11)."""
    now = db.now()
    permits = svc.children("permits", project["id"])
    effective = [p for p in permits
                 if p["permit_type"] == "FIRE_MARSHAL_NOTIFICATION"
                 and p["status"] == "ISSUED"
                 and p["notice_effective_at"] is not None
                 and p["notice_effective_at"] <= now]
    if not effective:
        raise ApiError("ERR_FIRE_MARSHAL_NOTICE_NOT_EFFECTIVE")

    municipal = [p for p in permits
                 if p["permit_type"] == "MUNICIPAL_DECOMMISSION" and p["status"] == "ISSUED"]
    if not municipal:
        raise ApiError("ERR_PERMIT_NOT_ISSUED")
    lapsed = [p for p in municipal if p["expires_at"] is not None and now > p["expires_at"]]
    for permit in lapsed:
        # Persist-then-reject: the lapse is recorded before the refusal.
        assign(permit, "status", "EXPIRED")
    if lapsed:
        svc.recompute_blockers(project)
    if len(lapsed) == len(municipal):
        commit()
        raise ApiError("ERR_PERMIT_EXPIRED")


@bp.post("/work-orders/<work_order_id>/billing-events")
def billing_event(work_order_id):
    authenticate(("ProjectCoordinator",))
    work_order = resolve("work_orders", work_order_id)
    payload = body()
    event = req_enum(payload, "event", ("INVOICE", "RECONCILE", "WRITE_OFF"))
    project = db.tank_projects.get(work_order["tank_project_id"])

    if event == "INVOICE":
        if work_order["billing_status"] != "BILLABLE":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        assign(work_order, "billing_status", "INVOICED")
    elif event == "RECONCILE":
        if work_order["billing_status"] != "INVOICED":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        if work_order["field_status"] != "FIELD_COMPLETE":
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        if project is None or not project["remediation_started"]:
            raise ApiError("ERR_PROJECT_STATE_INVALID")
        assign(work_order, "billing_status", "RECONCILED")
        svc.set_final_surveyed_volume(project)
    else:  # WRITE_OFF
        if work_order["billing_status"] not in ("UNBILLED", "BILLABLE", "INVOICED"):
            raise ApiError("ERR_WORK_ORDER_STATE_INVALID")
        assign(work_order, "billing_status", "WRITTEN_OFF")
    return entity_response(work_order)
