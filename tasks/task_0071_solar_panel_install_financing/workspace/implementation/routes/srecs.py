from flask import Blueprint, request
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, is_int, is_num, list_response
from services import calc

bp = Blueprint("srecs", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


def _get_srec(sid):
    s = db.srecs.get(sid)
    if not s:
        raise err("ERR_NOT_FOUND", "SREC not found.")
    return s


@bp.route("/solar/srecs", methods=["POST"])
def mint_srec():
    authenticate({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["project_id", "vintage_year"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    vy = body["vintage_year"]
    if not is_int(vy) or vy < 2020:
        raise err("ERR_INVALID_REQUEST", "vintage_year must be integer >= 2020.")
    if project["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project not OPERATIONAL.")
    fpid = project["financing_plan_id"]
    plan = db.financing_plans.get(fpid) if fpid else None
    owner_type = plan["srec_owner"] if plan else "HOMEOWNER"
    with db.lock:
        sid = new_id()
        rec = {
            "id": sid,
            "project_id": project["id"],
            "vintage_year": vy,
            "status": "MINTED",
            "owner_type": owner_type,
            "srec_sale_id": None,
        }
        rec.update(_common_create())
        db.srecs[sid] = rec
        project["lifetime_srec_count"] = project["lifetime_srec_count"] + 1
        db.touch(project)
    return ok(rec, 201)


@bp.route("/solar/srecs/<sid>", methods=["GET"])
def get_srec(sid):
    authenticate({"Homeowner", "SrecBroker", "PlatformAdmin"})
    return ok(_get_srec(sid), 200)


@bp.route("/solar/srecs", methods=["GET"])
def list_srecs():
    authenticate({"Homeowner", "SrecBroker", "PlatformAdmin"})
    rows = list(db.srecs.values())
    proj = request.args.get("project_id")
    sale = request.args.get("srec_sale_id")
    status = request.args.get("status")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    if sale is not None:
        rows = [r for r in rows if r["srec_sale_id"] == sale]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows)


@bp.route("/solar/srecs/<sid>/list", methods=["POST"])
def list_srec_for_sale(sid):
    user_id, role = authenticate({"Homeowner"})
    s = _get_srec(sid)
    project = db.projects.get(s["project_id"])
    if project and project["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    if s["status"] != "MINTED":
        raise err("ERR_INVALID_STATE", "SREC not in MINTED.")
    if not project or project["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project not OPERATIONAL.")
    with db.lock:
        s["status"] = "LISTED"
        db.touch(s)
    return ok(s, 200)


@bp.route("/solar/srecs/<sid>/retire", methods=["POST"])
def retire_srec(sid):
    authenticate({"SrecBroker"})
    s = _get_srec(sid)
    if s["status"] != "SOLD":
        raise err("ERR_INVALID_STATE", "SREC not in SOLD.")
    with db.lock:
        s["status"] = "RETIRED"
        db.touch(s)
    return ok(s, 200)


# ---------------- SrecSale ----------------
def _get_sale(saleid):
    sale = db.srec_sales.get(saleid)
    if not sale:
        raise err("ERR_NOT_FOUND", "SREC sale not found.")
    return sale


@bp.route("/solar/srec-sales", methods=["POST"])
def create_sale():
    authenticate({"SrecBroker"})
    body = get_body()
    require_fields(body, ["project_id", "broker_id", "vintage_year",
                          "price_cents_per_srec", "expected_project_version"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    broker = db.brokers.get(body["broker_id"])
    if not broker:
        raise err("ERR_NOT_FOUND", "Broker not found.")
    vy = body["vintage_year"]
    if not is_int(vy) or vy < 2020:
        raise err("ERR_INVALID_REQUEST", "vintage_year must be integer >= 2020.")
    price = body["price_cents_per_srec"]
    if not is_int(price) or price < 0:
        raise err("ERR_INVALID_REQUEST", "price_cents_per_srec must be integer >= 0.")
    epv = body["expected_project_version"]
    if not is_int(epv):
        raise err("ERR_INVALID_REQUEST", "expected_project_version must be integer.")

    # broker market: homeowner's state must be in broker.operating_states
    homeowner = db.homeowners.get(project["homeowner_id"])
    if homeowner["state_code"] not in broker["operating_states"]:
        raise err("ERR_BROKER_MARKET_MISMATCH", "Broker does not trade homeowner's market.")

    # sweep LISTED SRECs of project + vintage
    swept = [s for s in db.srecs.values()
             if s["project_id"] == project["id"]
             and s["vintage_year"] == vy
             and s["status"] == "LISTED"]
    if len(swept) == 0:
        raise err("ERR_NO_LISTED_SRECS", "No LISTED SRECs to sweep.")

    # OCC last among business checks per priority (17 after 14,15)
    if epv != project["version"]:
        raise err("ERR_STALE_PROJECT_VERSION", "expected_project_version mismatch.")

    swept.sort(key=lambda s: (s["created_at"], s["id"]))
    count = len(swept)
    gross, net = calc.srec_sale_settlement(count, price, broker["broker_fee_pct"])

    with db.lock:
        saleid = new_id()
        rec = {
            "id": saleid,
            "project_id": project["id"],
            "broker_id": broker["id"],
            "vintage_year": vy,
            "price_cents_per_srec": price,
            "srec_count": count,
            "gross_proceeds_cents": gross,
            "net_proceeds_cents": net,
        }
        rec.update(_common_create())
        db.srec_sales[saleid] = rec
        for s in swept:
            s["status"] = "SOLD"
            s["srec_sale_id"] = saleid
            db.touch(s)
        db.touch(project)
    return ok(rec, 201)


@bp.route("/solar/srec-sales/<saleid>", methods=["GET"])
def get_sale(saleid):
    authenticate({"SrecBroker", "Homeowner", "PlatformAdmin"})
    return ok(_get_sale(saleid), 200)


@bp.route("/solar/srec-sales", methods=["GET"])
def list_sales():
    authenticate({"SrecBroker", "Homeowner", "PlatformAdmin"})
    rows = list(db.srec_sales.values())
    proj = request.args.get("project_id")
    brk = request.args.get("broker_id")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    if brk is not None:
        rows = [r for r in rows if r["broker_id"] == brk]
    return list_response(rows)
