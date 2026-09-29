"""Jurisdiction permits: draft, submit and the officer's decision."""

import math

from flask import Blueprint, request

import calc
import db
import errors
import serializers as ser
import validators as v
from errors import fail, invalid
from middleware import (ROLE_COMPLIANCE_CLERK, ROLE_GENERAL_MANAGER,
                        ROLE_JURISDICTION_OFFICER, ROLE_PLATFORM_ADMIN,
                        ROLE_ROUTE_MANAGER, ROLE_TICKETING_AUDITOR, require_role)
from response import created, ok, paginate

bp = Blueprint("permits", __name__)

PERMIT_TYPES = ("EVENT", "TRANSPORT", "ELECTRICAL", "HOUSING")
DECISIONS = ("APPROVE", "DENY")
READ_ROLES = (ROLE_PLATFORM_ADMIN, ROLE_ROUTE_MANAGER, ROLE_GENERAL_MANAGER,
              ROLE_TICKETING_AUDITOR, ROLE_COMPLIANCE_CLERK,
              ROLE_JURISDICTION_OFFICER)


@bp.post("/permit-applications")
def create_permit():
    require_role(ROLE_COMPLIANCE_CLERK)
    body = v.get_body()
    stop = v.body_ref(body, "route_stop_id", "route_stops")
    if stop is None:
        v.req_str(body, "route_stop_id")
    permit_type = v.req_enum(body, "permit_type", PERMIT_TYPES)
    valid_from_raw, valid_from = v.req_dt(body, "valid_from")
    valid_until_raw, valid_until = v.req_dt(body, "valid_until")
    axles = v.opt_int(body, "axles_declared", 0, minimum=0)
    if valid_until <= valid_from:
        invalid("valid_until must be after valid_from.")

    jurisdiction = calc.jurisdiction_of(stop)
    fee = int(jurisdiction["permit_fee_cents"]) if jurisdiction else 0
    if permit_type == "TRANSPORT":
        fee += axles * calc.TRANSPORT_AXLE_SURCHARGE_CENTS

    row = db.create(db.store.permit_applications, {
        "route_stop_id": stop["id"],
        "permit_type": permit_type,
        "valid_from": valid_from_raw,
        "valid_until": valid_until_raw,
        "axles_declared": axles,
        "fee_cents": fee,
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "denial_reason": None,
    })
    return created(ser.permit_application(row))


@bp.get("/route-stops/<stop_id>/permit-applications")
def list_permits(stop_id):
    require_role(*READ_ROLES)
    stop = v.path_row("route_stops", stop_id)
    rows = [r for r in db.all_of(db.store.permit_applications)
            if r["route_stop_id"] == stop["id"]]
    permit_type = request.args.get("permit_type")
    status = request.args.get("status")
    if permit_type:
        rows = [r for r in rows if r["permit_type"] == permit_type]
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, ser.permit_application)


@bp.post("/permit-applications/<permit_id>/submit")
def submit_permit(permit_id):
    require_role(ROLE_COMPLIANCE_CLERK)
    permit = v.path_row("permit_applications", permit_id)
    stop = db.store.route_stops.get(permit["route_stop_id"])
    if stop is None or stop["status"] not in ("PLANNED", "CONFIRMED", "SETUP"):
        fail(errors.ERR_STOP_STATE_INVALID,
             "Permits may only be filed while the lot is PLANNED, CONFIRMED or "
             "SETUP.")
    if permit["status"] != "DRAFT":
        fail(errors.ERR_PERMIT_STATE_INVALID,
             "Only a DRAFT permit may be filed.")
    jurisdiction = calc.jurisdiction_of(stop)
    lead_days = int(jurisdiction["permit_lead_days"]) if jurisdiction else 0
    delta = calc.dt(stop, "open_date") - db.now()
    whole_days = math.floor(delta.total_seconds() / 86400.0)
    if whole_days < lead_days:
        fail(errors.ERR_PERMIT_LEAD_TIME_VIOLATION,
             "The jurisdiction's filing lead time has not been met.")
    permit["status"] = "SUBMITTED"
    permit["submitted_at"] = db.now_iso()
    db.touch(permit)
    return ok(ser.permit_application(permit))


@bp.post("/permit-applications/<permit_id>/decision")
def decide_permit(permit_id):
    require_role(ROLE_JURISDICTION_OFFICER)
    permit = v.path_row("permit_applications", permit_id)
    body = v.get_body()
    decision = v.req_enum(body, "decision", DECISIONS)
    denial_reason = v.opt_str(body, "denial_reason", None)
    if permit["status"] != "SUBMITTED":
        fail(errors.ERR_PERMIT_STATE_INVALID,
             "Only a SUBMITTED permit may be decided.")
    if decision == "DENY" and not denial_reason:
        invalid("denial_reason is required when the decision is DENY.")

    permit["status"] = "APPROVED" if decision == "APPROVE" else "DENIED"
    permit["decided_at"] = db.now_iso()
    if decision == "DENY":
        permit["denial_reason"] = denial_reason
    db.touch(permit)
    stop = db.store.route_stops.get(permit["route_stop_id"])
    if stop is not None:
        db.touch(stop)
    return ok(ser.permit_application(permit))
