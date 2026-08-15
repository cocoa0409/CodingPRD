"""RelocationCase endpoints."""

from flask import Blueprint, request

from db import store, clock
from errors import (
    ApiError,
    ERR_RELOCATION_CASE_NOT_FOUND,
    ERR_RELOCATION_CASE_INVALID_STATE,
    ERR_RELOCATION_OVERLAP,
    ERR_BEFORE_START_DATE,
    ERR_UNIT_NOT_FOUND,
    ERR_CALL_TICKET_NOT_FOUND,
    ERR_UNIT_NOT_UNINHABITABLE,
    ERR_REFERENTIAL_MISMATCH,
    ERR_SEGREGATION_OF_DUTIES,
    ERR_WORK_ORDER_INVALID_STATE,
    ERR_INVALID_REQUEST,
)
from helpers import (
    body,
    req_string,
    req_int,
    req_dt,
    new_id,
    serialize_relocation_case,
    touch,
    pagination_params,
)
from middleware import get_actor, require_role, require_supervisor_capable
from response import success_object, success_list
from services.calculations import relocation_estimate, relocation_actual

bp = Blueprint("relocation_cases", __name__)

READ_ROLES = {"PropertyAdmin", "Dispatcher", "OnCallTechnician", "MaintenanceSupervisor"}


def _closed_overlap(a_start, a_end, b_start, b_end):
    """Closed-interval overlap: [a_start, a_end] vs [b_start, b_end]."""
    return a_start <= b_end and b_start <= a_end


def _check_relocation_overlap(unit_id, start_date, end_date, exclude_id=None):
    for c in store.relocation_cases.values():
        if c["unit_id"] != unit_id:
            continue
        if c["status"] not in ("APPROVED", "ACTIVE"):
            continue
        if exclude_id is not None and c["id"] == exclude_id:
            continue
        if _closed_overlap(start_date, end_date, c["start_date"], c["end_date"]):
            raise ApiError(
                ERR_RELOCATION_OVERLAP,
                "Stay overlaps an APPROVED/ACTIVE relocation case for the unit",
                409,
            )


@bp.route("/v1/relocation-cases", methods=["POST"])
def create_case():
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    data = body()
    unit_id = data.get("unit_id")
    if not isinstance(unit_id, str) or not unit_id:
        raise ApiError(ERR_INVALID_REQUEST, "unit_id is required", 400)
    call_ticket_id = data.get("call_ticket_id")
    if not isinstance(call_ticket_id, str) or not call_ticket_id:
        raise ApiError(ERR_INVALID_REQUEST, "call_ticket_id is required", 400)
    start_date = req_dt(data, "start_date")
    end_date = req_dt(data, "end_date")
    if end_date <= start_date:
        raise ApiError(ERR_INVALID_REQUEST, "end_date must be strictly after start_date", 400)
    nightly_rate = req_int(data, "nightly_rate_cents", minimum=1)
    # Body FK existence, left to right
    unit = store.units.get(unit_id)
    if unit is None:
        raise ApiError(ERR_UNIT_NOT_FOUND, "Unit not found", 404)
    ticket = store.call_tickets.get(call_ticket_id)
    if ticket is None:
        raise ApiError(ERR_CALL_TICKET_NOT_FOUND, "Call ticket not found", 404)
    # Referential (priority 7)
    if not ticket["unit_declared_uninhabitable"]:
        raise ApiError(ERR_UNIT_NOT_UNINHABITABLE, "Ticket's unit was not declared uninhabitable", 409)
    if ticket["unit_id"] != unit_id:
        raise ApiError(ERR_REFERENTIAL_MISMATCH, "Case unit does not match ticket unit", 422)
    # Temporal (priority 8)
    _check_relocation_overlap(unit_id, start_date, end_date)
    planned_nights, est_cost = relocation_estimate(start_date, end_date, nightly_rate)
    now = clock.now()
    rec = {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 0,
        "unit_id": unit_id,
        "call_ticket_id": call_ticket_id,
        "proposed_by_technician_id": actor.user_id,
        "approved_by_technician_id": None,
        "start_date": start_date,
        "end_date": end_date,
        "nightly_rate_cents": nightly_rate,
        "planned_nights": planned_nights,
        "est_cost_cents": est_cost,
        "actual_cost_cents": None,
        "status": "PROPOSED",
        "reject_reason": None,
        "_seq": store.next_seq(),
    }
    store.relocation_cases[rec["id"]] = rec
    return success_object(serialize_relocation_case(rec), 201)


@bp.route("/v1/relocation-cases", methods=["GET"])
def list_cases():
    actor = get_actor()
    require_role(actor, READ_ROLES)
    limit, offset = pagination_params()
    items = list(store.relocation_cases.values())
    for key in (
        "unit_id",
        "call_ticket_id",
        "proposed_by_technician_id",
        "approved_by_technician_id",
        "status",
    ):
        v = request.args.get(key)
        if v is not None:
            items = [c for c in items if c[key] == v]
    items.sort(key=lambda c: (c["created_at"], c["_seq"]))
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([serialize_relocation_case(c) for c in page], limit, offset, total)


def _get_case_or_404(case_id):
    rec = store.relocation_cases.get(case_id)
    if rec is None:
        raise ApiError(ERR_RELOCATION_CASE_NOT_FOUND, "Relocation case not found", 404)
    return rec


@bp.route("/v1/relocation-cases/<relocationCaseId>", methods=["GET"])
def get_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, READ_ROLES)
    rec = _get_case_or_404(relocationCaseId)
    return success_object(serialize_relocation_case(rec))


@bp.route("/v1/relocation-cases/<relocationCaseId>/approve", methods=["POST"])
def approve_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_case_or_404(relocationCaseId)
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_RELOCATION_CASE_INVALID_STATE, "Case is not PROPOSED", 409)
    if actor.is_technician_backed and actor.user_id == rec["proposed_by_technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Proposer cannot approve their own case", 403)
    _, est_cost = relocation_estimate(rec["start_date"], rec["end_date"], rec["nightly_rate_cents"])
    rec["est_cost_cents"] = est_cost
    rec["approved_by_technician_id"] = actor.user_id if actor.is_technician_backed else None
    rec["status"] = "APPROVED"
    touch(rec)
    # CASCADE A link 1: unit -> UNINHABITABLE
    unit = store.units.get(rec["unit_id"])
    if unit is not None:
        unit["habitability_status"] = "UNINHABITABLE"
        touch(unit)
    # CASCADE A link 2: non-emergency OPEN/ASSIGNED work orders -> ON_HOLD
    for wo in store.work_orders.values():
        if (
            wo["unit_id"] == rec["unit_id"]
            and wo["status"] in ("OPEN", "ASSIGNED")
            and wo["priority"] != "EMERGENCY_FOLLOWUP"
        ):
            wo["status"] = "ON_HOLD"
            touch(wo)
            # CASCADE A link 3: held order's PROPOSED vendor authorizations -> VOIDED
            for a in store.vendor_authorizations.values():
                if a["work_order_id"] == wo["id"] and a["status"] == "PROPOSED":
                    a["status"] = "VOIDED"
                    touch(a)
    return success_object(serialize_relocation_case(rec))


@bp.route("/v1/relocation-cases/<relocationCaseId>/reject", methods=["POST"])
def reject_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor", "PropertyAdmin"})
    require_supervisor_capable(actor)
    rec = _get_case_or_404(relocationCaseId)
    data = body()
    reason = req_string(data, "reason")
    if rec["status"] != "PROPOSED":
        raise ApiError(ERR_RELOCATION_CASE_INVALID_STATE, "Case is not PROPOSED", 409)
    if actor.user_id == rec["proposed_by_technician_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, "Proposer cannot reject their own case", 403)
    rec["status"] = "REJECTED"
    rec["reject_reason"] = reason
    touch(rec)
    return success_object(serialize_relocation_case(rec))


@bp.route("/v1/relocation-cases/<relocationCaseId>/resubmit", methods=["POST"])
def resubmit_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, {"OnCallTechnician", "MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_case_or_404(relocationCaseId)
    data = body()
    start_date = req_dt(data, "start_date")
    end_date = req_dt(data, "end_date")
    if end_date <= start_date:
        raise ApiError(ERR_INVALID_REQUEST, "end_date must be strictly after start_date", 400)
    nightly_rate = req_int(data, "nightly_rate_cents", minimum=1)
    if rec["status"] != "REJECTED":
        raise ApiError(ERR_RELOCATION_CASE_INVALID_STATE, "Case is not REJECTED", 409)
    _check_relocation_overlap(rec["unit_id"], start_date, end_date, exclude_id=rec["id"])
    planned_nights, est_cost = relocation_estimate(start_date, end_date, nightly_rate)
    rec["start_date"] = start_date
    rec["end_date"] = end_date
    rec["nightly_rate_cents"] = nightly_rate
    rec["planned_nights"] = planned_nights
    rec["est_cost_cents"] = est_cost
    rec["proposed_by_technician_id"] = actor.user_id
    rec["status"] = "PROPOSED"
    touch(rec)
    return success_object(serialize_relocation_case(rec))


@bp.route("/v1/relocation-cases/<relocationCaseId>/activate", methods=["POST"])
def activate_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_case_or_404(relocationCaseId)
    if rec["status"] != "APPROVED":
        raise ApiError(ERR_RELOCATION_CASE_INVALID_STATE, "Case is not APPROVED", 409)
    now = clock.now()
    if now < rec["start_date"]:
        raise ApiError(ERR_BEFORE_START_DATE, "Activation before start_date", 409)
    rec["status"] = "ACTIVE"
    touch(rec)
    return success_object(serialize_relocation_case(rec))


@bp.route("/v1/relocation-cases/<relocationCaseId>/end", methods=["POST"])
def end_case(relocationCaseId):
    actor = get_actor()
    require_role(actor, {"MaintenanceSupervisor"})
    require_supervisor_capable(actor)
    rec = _get_case_or_404(relocationCaseId)
    data = body()
    actual_end_date = req_dt(data, "actual_end_date")
    if (actual_end_date - rec["start_date"]).total_seconds() < 86400:
        raise ApiError(ERR_INVALID_REQUEST, "actual_end_date must give at least one night", 400)
    if rec["status"] != "ACTIVE":
        raise ApiError(ERR_RELOCATION_CASE_INVALID_STATE, "Case is not ACTIVE", 409)
    # Blocked while any unit work order is OPEN/ASSIGNED/IN_PROGRESS/REOPENED
    for wo in store.work_orders.values():
        if wo["unit_id"] == rec["unit_id"] and wo["status"] in (
            "OPEN", "ASSIGNED", "IN_PROGRESS", "REOPENED",
        ):
            raise ApiError(
                ERR_WORK_ORDER_INVALID_STATE,
                "Unit has work orders blocking relocation end",
                409,
            )
    rec["actual_cost_cents"] = relocation_actual(
        rec["start_date"], actual_end_date, rec["planned_nights"], rec["nightly_rate_cents"]
    )
    rec["status"] = "ENDED"
    touch(rec)
    # Restore unit and release held work orders
    unit = store.units.get(rec["unit_id"])
    if unit is not None:
        unit["habitability_status"] = "HABITABLE"
        touch(unit)
    for wo in store.work_orders.values():
        if wo["unit_id"] == rec["unit_id"] and wo["status"] == "ON_HOLD":
            wo["status"] = "OPEN"
            wo["assigned_technician_id"] = None
            touch(wo)
    return success_object(serialize_relocation_case(rec))
