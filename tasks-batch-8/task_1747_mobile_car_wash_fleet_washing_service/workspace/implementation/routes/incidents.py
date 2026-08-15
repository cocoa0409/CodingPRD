"""ComplianceIncident endpoints."""

from flask import Blueprint, request

from db import store
from serialize import ser_incident, customer_of_incident
from services import suspend_site, confirmed_incident_open
from util import (
    caller, require_role, forbid, get_body, respond, paginate, req_str,
    opt_str, req_enum, stamp_new, touch, ApiError,
)
from errors import ERR_NOT_FOUND, ERR_VALIDATION, ERR_INVALID_STATE

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = {"DISCHARGE_TO_STORM_DRAIN", "CONTAINMENT_FAILURE",
                  "RECLAIM_EQUIPMENT_FAILURE", "SPILL"}


@bp.post("/fleet-wash/compliance-incidents")
def create_incident():
    _uid, role = caller()
    require_role(role, {"ComplianceOfficer"})
    body = get_body()
    site_id = req_str(body, "site_id")
    if site_id not in store.sites:
        raise ApiError(ERR_NOT_FOUND, "Site %s not found" % site_id)
    wash_order_id = opt_str(body, "wash_order_id")
    if wash_order_id is not None and wash_order_id not in store.orders:
        raise ApiError(ERR_NOT_FOUND, "WashOrder %s not found" % wash_order_id)
    incident_type = req_enum(body, "incident_type", INCIDENT_TYPES)
    notes = req_str(body, "notes")
    rec = {
        "site_id": site_id,
        "wash_order_id": wash_order_id,
        "incident_type": incident_type,
        "notes": notes,
        "status": "REPORTED",
    }
    stamp_new(rec)
    store.incidents[rec["id"]] = rec
    return respond(ser_incident(rec), 201)


@bp.get("/fleet-wash/compliance-incidents/<iid>")
def get_incident(iid):
    uid, role = caller()
    rec = store.incidents.get(iid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "ComplianceIncident %s not found" % iid)
    if role == "Customer" and customer_of_incident(rec) != uid:
        forbid("Customers may only access incidents at their own sites")
    return respond(ser_incident(rec), 200)


@bp.get("/fleet-wash/compliance-incidents")
def list_incidents():
    uid, role = caller()
    site_id = request.args.get("site_id")
    wash_order_id = request.args.get("wash_order_id")
    status = request.args.get("status")
    recs = list(store.incidents.values())
    if role == "Customer":
        recs = [i for i in recs if customer_of_incident(i) == uid]
    if site_id is not None:
        recs = [i for i in recs if i["site_id"] == site_id]
    if wash_order_id is not None:
        recs = [i for i in recs if i["wash_order_id"] == wash_order_id]
    if status is not None:
        recs = [i for i in recs if i["status"] == status]
    return paginate(recs, ser_incident)


@bp.post("/fleet-wash/compliance-incidents/<iid>/events")
def incident_event(iid):
    _uid, role = caller()
    require_role(role, {"ComplianceOfficer"})
    rec = store.incidents.get(iid)
    if rec is None:
        raise ApiError(ERR_NOT_FOUND, "ComplianceIncident %s not found" % iid)
    body = get_body()
    event = req_str(body, "event_type")
    if event not in ("START_REVIEW", "CONFIRM", "DISMISS", "RESOLVE"):
        raise ApiError(ERR_VALIDATION,
                       "event_type must be START_REVIEW, CONFIRM, DISMISS, or RESOLVE")
    if event == "START_REVIEW":
        if rec["status"] != "REPORTED":
            raise ApiError(ERR_INVALID_STATE, "ComplianceIncident is not REPORTED")
        rec["status"] = "UNDER_REVIEW"
    elif event == "CONFIRM":
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "ComplianceIncident is not UNDER_REVIEW")
        rec["status"] = "CONFIRMED"
        touch(rec)
        site = store.sites.get(rec["site_id"])
        if site is not None and site["status"] == "ACTIVE":
            suspend_site(site, "COMPLIANCE_INCIDENT")
        return respond(ser_incident(rec), 200)
    elif event == "DISMISS":
        if rec["status"] != "UNDER_REVIEW":
            raise ApiError(ERR_INVALID_STATE, "ComplianceIncident is not UNDER_REVIEW")
        rec["status"] = "DISMISSED"
    else:  # RESOLVE
        if rec["status"] != "CONFIRMED":
            raise ApiError(ERR_INVALID_STATE, "ComplianceIncident is not CONFIRMED")
        rec["status"] = "RESOLVED"
        touch(rec)
        if not confirmed_incident_open(rec["site_id"]):
            site = store.sites.get(rec["site_id"])
            if site is not None and site["status"] == "SUSPENDED":
                site["status"] = "ACTIVE"
                site["suspension_reason"] = None
                touch(site)
        return respond(ser_incident(rec), 200)
    touch(rec)
    return respond(ser_incident(rec), 200)
