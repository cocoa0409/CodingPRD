"""Welfare incidents (PRD 3.7)."""
from flask import Blueprint, g, request

import db
import services as svc
from errors import (
    raise_err, ERR_LOAD_NOT_FOUND, ERR_INCIDENT_NOT_FOUND,
    ERR_OWNERSHIP_MISMATCH, ERR_LOAD_NOT_REPORTABLE, ERR_EVENT_IN_FUTURE,
    ERR_INCIDENT_NOT_REPORTED, ERR_INCIDENT_NOT_UNDER_REVIEW,
)
from middleware import require_role
from response import success
from util import get_body, v_str, v_int, v_enum, v_dt, v_bool, paginate

bp = Blueprint("incidents", __name__)

INCIDENT_TYPES = {"INJURY", "DOWNER", "DEAD_ON_ARRIVAL", "ESCAPE"}
SEVERITIES = {"MINOR", "MAJOR", "CRITICAL"}
REPORTABLE_STATES = {"IN_TRANSIT", "WEATHER_HOLD", "REST_UNLOAD", "ARRIVED", "DELIVERED"}


@bp.post("/haul/incidents")
def report_incident():
    require_role("Driver")
    body = get_body()
    load_id = v_str(body, "load_id")
    incident_type = v_enum(body, "incident_type", INCIDENT_TYPES)
    severity = v_enum(body, "severity", SEVERITIES)
    head = v_int(body, "head_count_affected", min_value=1)
    occurred_at = v_dt(body, "occurred_at")
    description = v_str(body, "description", required=False)
    ld = db.store["loads"].get(load_id)
    if ld is None:
        raise_err(ERR_LOAD_NOT_FOUND)
    if ld["driver_id"] != g.user_id:
        raise_err(ERR_OWNERSHIP_MISMATCH, "drivers report incidents on their own loads")
    if ld["status"] not in REPORTABLE_STATES:
        raise_err(ERR_LOAD_NOT_REPORTABLE, "load is not in a reportable state")
    if occurred_at > db.now():
        raise_err(ERR_EVENT_IN_FUTURE, "occurred_at is after the current time")
    rec = svc.new_common()
    rec.update({
        "load_id": load_id, "driver_id": g.user_id, "incident_type": incident_type,
        "severity": severity, "head_count_affected": head,
        "occurred_at": occurred_at, "description": description,
        "status": "REPORTED", "fine_cents": None, "fine_waived": False,
        "closed_at": None,
    })
    db.store["incidents"][rec["id"]] = rec
    return success(svc.incident_json(rec), status=201)


@bp.get("/haul/incidents")
def list_incidents():
    items = sorted(db.store["incidents"].values(), key=lambda i: i["seq"])
    for param in ("load_id", "driver_id", "status", "severity"):
        val = request.args.get(param)
        if val is not None:
            items = [i for i in items if i[param] == val]
    page, meta = paginate([svc.incident_json(i) for i in items])
    return success(page, response_type="array", pagination=meta)


@bp.get("/haul/incidents/<iid>")
def get_incident(iid):
    inc = db.store["incidents"].get(iid)
    if inc is None:
        raise_err(ERR_INCIDENT_NOT_FOUND)
    return success(svc.incident_json(inc))


@bp.post("/haul/incidents/<iid>/start-review")
def start_review(iid):
    require_role("ComplianceOfficer")
    inc = db.store["incidents"].get(iid)
    if inc is None:
        raise_err(ERR_INCIDENT_NOT_FOUND)
    if inc["status"] != "REPORTED":
        raise_err(ERR_INCIDENT_NOT_REPORTED, "start-review requires REPORTED")
    inc["status"] = "UNDER_REVIEW"
    svc.touch(inc)
    return success(svc.incident_json(inc))


@bp.post("/haul/incidents/<iid>/close")
def close_incident(iid):
    require_role("ComplianceOfficer")
    inc = db.store["incidents"].get(iid)
    if inc is None:
        raise_err(ERR_INCIDENT_NOT_FOUND)
    if inc["status"] != "UNDER_REVIEW":
        raise_err(ERR_INCIDENT_NOT_UNDER_REVIEW, "close requires UNDER_REVIEW")
    body = get_body()
    waived = v_bool(body, "fine_waived", required=False, default=False)
    now = db.now()
    inc["fine_waived"] = waived
    inc["fine_cents"] = 0 if waived else svc.compute_fine_cents(
        inc["incident_type"], inc["severity"], inc["head_count_affected"])
    inc["closed_at"] = now
    inc["status"] = "CLOSED"
    svc.touch(inc)
    # chain link 1: settlement welfare deduction + final (when not PAID)
    st = svc.get_settlement_for_load(inc["load_id"])
    if st is not None and st["status"] != "PAID":
        before = (st["welfare_deduction_cents"], st["final_amount_cents"])
        svc.recompute_settlement_final(st)
        after = (st["welfare_deduction_cents"], st["final_amount_cents"])
        if before != after:
            svc.touch(st)
    # chain link 2/3: possible suspension -> force-unassign cascade
    driver = db.store["drivers"].get(inc["driver_id"])
    if driver is not None:
        svc.maybe_suspend_driver(driver)
    return success(svc.incident_json(inc))
