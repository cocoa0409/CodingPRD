"""Alert incidents: lifecycle, alert-level escalation, nested lists."""
from flask import Blueprint, request

from db import store, base_entity, touch, serialize, fmt_ts, fmt_clock
from errors import (
    ApiError, ERR_INCIDENT_NOT_FOUND, ERR_AIRCRAFT_NOT_FOUND,
    ERR_AGREEMENT_NOT_FOUND, ERR_INCIDENT_NOT_OPEN, ERR_INCIDENT_NOT_RESPONDING,
    ERR_INCIDENT_NOT_CONTROLLED, ERR_OPEN_REQUESTS_EXIST,
    ERR_ALERT_LEVEL_NOT_ESCALATION, ERR_INDEX_INSUFFICIENT_FOR_ALERT,
    ERR_AGREEMENT_NOT_ACTIVE, ERR_ALERT_LEVEL_NOT_COVERED,
)
from middleware import require, json_body, need_str, need_int, need_enum, ALL_ROLES
from response import success, paginated
from services import calc

bp = Blueprint("incidents", __name__)


def get_incident_or_404(iid):
    inc = store.incidents.get(iid)
    if inc is None:
        raise ApiError(ERR_INCIDENT_NOT_FOUND, 404, "Incident id does not exist")
    return inc


@bp.post("/arff/incidents")
def create_incident():
    require(["ArffChief"])
    data = json_body()
    raw_air = data.get("aircraft_id")
    if isinstance(raw_air, str) and raw_air not in store.aircraft:
        raise ApiError(ERR_AIRCRAFT_NOT_FOUND, 404, "Aircraft id does not exist")
    alert = need_enum(data, "alert_level", calc.ALERT_LEVELS)
    location = need_str(data, "location")
    if raw_air is not None and not isinstance(raw_air, str):
        raise ApiError("ERR_VALIDATION_FAILED", 400, "'aircraft_id' must be a string or null")
    inc = base_entity()
    inc.update({
        "alert_level": alert,
        "aircraft_id": raw_air,
        "location": location,
        "reported_at": fmt_clock(store.clock),
        "controlled_at": None,
        "status": "REPORTED",
        "_controlled_dt": None,
    })
    store.incidents[inc["id"]] = inc
    return success(serialize(inc), "object", 201)


@bp.get("/arff/incidents")
def list_incidents():
    require(ALL_ROLES)
    items = list(store.incidents.values())
    status = request.args.get("status")
    if status is not None:
        items = [i for i in items if i["status"] == status]
    alert = request.args.get("alert_level")
    if alert is not None:
        items = [i for i in items if i["alert_level"] == alert]
    return paginated(items)


@bp.get("/arff/incidents/<iid>")
def get_incident(iid):
    require(ALL_ROLES)
    return success(serialize(get_incident_or_404(iid)), "object", 200)


@bp.post("/arff/incidents/<iid>/respond")
def respond_incident(iid):
    require(["ArffChief"])
    inc = get_incident_or_404(iid)
    if inc["status"] != "REPORTED":
        raise ApiError(ERR_INCIDENT_NOT_OPEN, 409, "Incident must be REPORTED to respond")
    effective = store.profile["effective_index"] if store.profile else "NONE"
    req = calc.ALERT_INDEX_REQ[inc["alert_level"]]
    if calc.INDEX_RANK[effective] < calc.INDEX_RANK[req]:
        raise ApiError(ERR_INDEX_INSUFFICIENT_FOR_ALERT, 422,
                       "effective_index is below the alert level's required index")
    inc["status"] = "RESPONDING"
    touch(inc)
    return success(serialize(inc), "object", 200)


@bp.post("/arff/incidents/<iid>/control")
def control_incident(iid):
    require(["ArffChief"])
    inc = get_incident_or_404(iid)
    if inc["status"] != "RESPONDING":
        raise ApiError(ERR_INCIDENT_NOT_RESPONDING, 409,
                       "Incident must be RESPONDING to control")
    inc["status"] = "CONTROLLED"
    inc["controlled_at"] = fmt_clock(store.clock)
    inc["_controlled_dt"] = store.clock
    touch(inc)
    return success(serialize(inc), "object", 200)


@bp.post("/arff/incidents/<iid>/close")
def close_incident(iid):
    require(["ArffChief"])
    inc = get_incident_or_404(iid)
    if inc["status"] != "CONTROLLED":
        raise ApiError(ERR_INCIDENT_NOT_CONTROLLED, 409,
                       "Incident must be CONTROLLED to close")
    open_reqs = [r for r in store.requests.values()
                 if r["incident_id"] == iid and r["status"] in ("REQUESTED", "DEPLOYED")]
    if open_reqs:
        raise ApiError(ERR_OPEN_REQUESTS_EXIST, 409,
                       "Open mutual-aid requests block incident close")
    inc["status"] = "CLOSED"
    touch(inc)
    return success(serialize(inc), "object", 200)


@bp.patch("/arff/incidents/<iid>/alert-level")
def escalate_alert_level(iid):
    require(["ArffChief"])
    inc = get_incident_or_404(iid)
    data = json_body()
    new_level = need_enum(data, "alert_level", calc.ALERT_LEVELS)
    if inc["status"] not in ("REPORTED", "RESPONDING"):
        raise ApiError(ERR_INCIDENT_NOT_OPEN, 409,
                       "Alert level can only change while the incident is open")
    if calc.ALERT_RANK[new_level] <= calc.ALERT_RANK[inc["alert_level"]]:
        raise ApiError(ERR_ALERT_LEVEL_NOT_ESCALATION, 422,
                       "New alert_level must be strictly higher than current")
    inc["alert_level"] = new_level
    touch(inc)
    return success(serialize(inc), "object", 200)


@bp.get("/arff/incidents/<iid>/mutual-aid-requests")
def list_incident_requests(iid):
    require(ALL_ROLES)
    get_incident_or_404(iid)
    items = [r for r in store.requests.values() if r["incident_id"] == iid]
    return paginated(items)


@bp.get("/arff/incidents/<iid>/reports")
def list_incident_reports(iid):
    require(ALL_ROLES)
    get_incident_or_404(iid)
    items = [r for r in store.reports.values() if r["incident_id"] == iid]
    return paginated(items)


@bp.post("/arff/incidents/<iid>/mutual-aid-requests")
def create_mutual_aid_request(iid):
    require(["ArffChief"])
    inc = get_incident_or_404(iid)
    data = json_body()
    raw_ag = data.get("agreement_id")
    if isinstance(raw_ag, str) and raw_ag not in store.agreements:
        raise ApiError(ERR_AGREEMENT_NOT_FOUND, 404, "Mutual-aid agreement id does not exist")
    agid = need_str(data, "agreement_id")
    units = need_int(data, "units_requested", min_value=1)
    if inc["status"] not in ("REPORTED", "RESPONDING"):
        raise ApiError(ERR_INCIDENT_NOT_RESPONDING, 409,
                       "Incident must be REPORTED or RESPONDING for a mutual-aid request")
    ag = store.agreements[agid]
    if ag["status"] != "ACTIVE":
        raise ApiError(ERR_AGREEMENT_NOT_ACTIVE, 409,
                       "Agreement must be ACTIVE for a mutual-aid request")
    if calc.ALERT_RANK[ag["max_alert_level"]] < calc.ALERT_RANK[inc["alert_level"]]:
        raise ApiError(ERR_ALERT_LEVEL_NOT_COVERED, 422,
                       "Agreement max_alert_level does not cover the incident alert_level")
    r = base_entity()
    r.update({
        "incident_id": iid,
        "agreement_id": agid,
        "units_requested": units,
        "status": "REQUESTED",
    })
    store.requests[r["id"]] = r
    return success(serialize(r), "object", 201)
