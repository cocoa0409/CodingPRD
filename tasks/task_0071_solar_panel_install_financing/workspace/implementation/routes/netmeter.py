from flask import Blueprint, request
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, is_int, list_response
from services import calc

bp = Blueprint("netmeter", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def _get_period(pid):
    p = db.net_meter_periods.get(pid)
    if not p:
        raise err("ERR_NOT_FOUND", "Net-meter period not found.")
    return p


def _utility_for_project(project):
    """Find the utility on the project's interconnection application."""
    for app in db.interconnection_applications.values():
        if app["project_id"] == project["id"]:
            u = db.utilities.get(app["utility_id"])
            if u:
                return u
    return None


@bp.route("/solar/net-meter-periods", methods=["POST"])
def create_period():
    authenticate({"Utility"})
    body = get_body()
    require_fields(body, ["project_id", "period_start", "period_end",
                          "kwh_produced", "kwh_consumed"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    ps = body["period_start"]
    pe = body["period_end"]
    if not isinstance(ps, str) or not isinstance(pe, str):
        raise err("ERR_INVALID_REQUEST", "period_start/end must be strings.")
    kp = body["kwh_produced"]
    kc = body["kwh_consumed"]
    if not is_int(kp) or kp < 0:
        raise err("ERR_INVALID_REQUEST", "kwh_produced must be integer >= 0.")
    if not is_int(kc) or kc < 0:
        raise err("ERR_INVALID_REQUEST", "kwh_consumed must be integer >= 0.")
    # interval validity
    if not (pe > ps):
        raise err("ERR_INVALID_INTERVAL", "period_end must be strictly after period_start.")
    # overlap check (half-open [start,end)): conflict if ps < other_end and other_start < pe
    for other in db.net_meter_periods.values():
        if other["project_id"] != project["id"]:
            continue
        if ps < other["period_end"] and other["period_start"] < pe:
            raise err("ERR_PERIOD_OVERLAP", "Period overlaps an existing period.")
    with db.lock:
        nid = new_id()
        rec = {
            "id": nid,
            "project_id": project["id"],
            "period_start": ps,
            "period_end": pe,
            "kwh_produced": kp,
            "kwh_consumed": kc,
            "status": "OPEN",
            "net_kwh": 0,
            "bill_credit_cents": 0,
            "bank_kwh_after": 0,
        }
        rec.update(_common_create())
        db.net_meter_periods[nid] = rec
    return ok(rec, 201)


@bp.route("/solar/net-meter-periods/<nid>", methods=["GET"])
def get_period(nid):
    authenticate({"Utility", "Homeowner", "PlatformAdmin"})
    return ok(_get_period(nid), 200)


@bp.route("/solar/net-meter-periods", methods=["GET"])
def list_periods():
    authenticate({"Utility", "Homeowner", "PlatformAdmin"})
    rows = list(db.net_meter_periods.values())
    proj = request.args.get("project_id")
    status = request.args.get("status")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows)


@bp.route("/solar/net-meter-periods/<nid>/settle", methods=["POST"])
def settle(nid):
    authenticate({"Utility"})
    period = _get_period(nid)
    project = db.projects.get(period["project_id"])
    if period["status"] != "OPEN":
        raise err("ERR_INVALID_STATE", "Period not OPEN.")
    if not project or project["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project not OPERATIONAL.")
    # chronological order: no earlier OPEN period exists on the same project
    for other in db.net_meter_periods.values():
        if other["project_id"] != project["id"]:
            continue
        if other["status"] == "OPEN" and other["period_start"] < period["period_start"]:
            raise err("ERR_OUT_OF_ORDER_SETTLEMENT", "An earlier OPEN period exists.")
    utility = _utility_for_project(project)
    if utility is None:
        raise err("ERR_INVALID_STATE", "No utility associated with project.")
    with db.lock:
        bank_before = db.project_bank.get(project["id"], 0)
        net_kwh, bill_credit, bank_after = calc.net_metering_settlement(
            period["kwh_produced"], period["kwh_consumed"], bank_before, utility)
        period["net_kwh"] = net_kwh
        period["bill_credit_cents"] = bill_credit
        period["bank_kwh_after"] = bank_after
        period["status"] = "SETTLED"
        db.project_bank[project["id"]] = bank_after
        db.touch(period)
    return ok(period, 200)
