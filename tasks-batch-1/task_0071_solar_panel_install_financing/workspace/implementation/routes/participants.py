from flask import Blueprint
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, is_int, is_num, VALID_STATES

bp = Blueprint("participants", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


# ---------------- Homeowner ----------------
@bp.route("/solar/homeowners", methods=["POST"])
def create_homeowner():
    authenticate({"Anonymous"})
    body = get_body()
    require_fields(body, ["email", "full_name", "state_code", "annual_kwh_usage"])
    email = body["email"]
    if not isinstance(email, str) or email.strip() == "":
        raise err("ERR_INVALID_REQUEST", "email must be non-empty string.")
    if not isinstance(body["full_name"], str):
        raise err("ERR_INVALID_REQUEST", "full_name must be a string.")
    sc = body["state_code"]
    if not isinstance(sc, str) or sc not in VALID_STATES:
        raise err("ERR_INVALID_REQUEST", "Invalid state_code.")
    usage = body["annual_kwh_usage"]
    if not is_int(usage) or usage < 0:
        raise err("ERR_INVALID_REQUEST", "annual_kwh_usage must be integer >= 0.")
    # unique email
    for h in db.homeowners.values():
        if h["email"] == email:
            raise err("ERR_INVALID_REQUEST", "email already registered.")
    with db.lock:
        hid = new_id()
        rec = {"id": hid, "email": email, "full_name": body["full_name"],
               "state_code": sc, "annual_kwh_usage": usage}
        rec.update(_common_create())
        db.homeowners[hid] = rec
    return ok(rec, 201)


@bp.route("/solar/homeowners/<hid>", methods=["GET"])
def get_homeowner(hid):
    authenticate({"Homeowner", "PlatformAdmin"})
    rec = db.homeowners.get(hid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Homeowner not found.")
    return ok(rec, 200)


# ---------------- SolarInstaller ----------------
@bp.route("/solar/installers", methods=["POST"])
def create_installer():
    authenticate({"Anonymous"})
    body = get_body()
    require_fields(body, ["company_name", "licensed_states"])
    if not isinstance(body["company_name"], str):
        raise err("ERR_INVALID_REQUEST", "company_name must be a string.")
    ls = body["licensed_states"]
    if not isinstance(ls, list) or len(ls) == 0:
        raise err("ERR_INVALID_REQUEST", "licensed_states must be non-empty array.")
    for s in ls:
        if not isinstance(s, str) or s not in VALID_STATES:
            raise err("ERR_INVALID_REQUEST", "Invalid state in licensed_states.")
    with db.lock:
        iid = new_id()
        rec = {"id": iid, "company_name": body["company_name"], "licensed_states": ls}
        rec.update(_common_create())
        db.installers[iid] = rec
    return ok(rec, 201)


@bp.route("/solar/installers/<iid>", methods=["GET"])
def get_installer(iid):
    authenticate({"SolarInstaller", "PlatformAdmin"})
    rec = db.installers.get(iid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Installer not found.")
    return ok(rec, 200)


# ---------------- Utility ----------------
@bp.route("/solar/utilities", methods=["POST"])
def create_utility():
    authenticate({"PlatformAdmin"})
    body = get_body()
    require_fields(body, ["name", "state_code", "feeder_headroom_kw",
                          "net_metering_rate_cents_per_kwh"])
    if not isinstance(body["name"], str):
        raise err("ERR_INVALID_REQUEST", "name must be a string.")
    sc = body["state_code"]
    if not isinstance(sc, str) or sc not in VALID_STATES:
        raise err("ERR_INVALID_REQUEST", "Invalid state_code.")
    fh = body["feeder_headroom_kw"]
    if not is_num(fh) or fh < 0:
        raise err("ERR_INVALID_REQUEST", "feeder_headroom_kw must be >= 0.")
    rate = body["net_metering_rate_cents_per_kwh"]
    if not is_num(rate) or rate < 0:
        raise err("ERR_INVALID_REQUEST", "net_metering_rate_cents_per_kwh must be >= 0.")
    ratio = body.get("export_credit_ratio", 1.0)
    if ratio is None:
        ratio = 1.0
    if not is_num(ratio) or ratio < 0.0 or ratio > 1.0:
        raise err("ERR_INVALID_REQUEST", "export_credit_ratio must be in [0,1].")
    with db.lock:
        uid = new_id()
        rec = {"id": uid, "name": body["name"], "state_code": sc,
               "feeder_headroom_kw": fh,
               "net_metering_rate_cents_per_kwh": rate,
               "export_credit_ratio": ratio}
        rec.update(_common_create())
        db.utilities[uid] = rec
    return ok(rec, 201)


@bp.route("/solar/utilities/<uid>", methods=["GET"])
def get_utility(uid):
    authenticate({"Utility", "PlatformAdmin"})
    rec = db.utilities.get(uid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Utility not found.")
    return ok(rec, 200)


# ---------------- SrecBroker ----------------
@bp.route("/solar/brokers", methods=["POST"])
def create_broker():
    authenticate({"Anonymous"})
    body = get_body()
    require_fields(body, ["firm_name", "broker_fee_pct", "operating_states"])
    if not isinstance(body["firm_name"], str):
        raise err("ERR_INVALID_REQUEST", "firm_name must be a string.")
    fee = body["broker_fee_pct"]
    if not is_num(fee) or fee < 0.0 or fee > 0.25:
        raise err("ERR_INVALID_REQUEST", "broker_fee_pct must be in [0,0.25].")
    os_ = body["operating_states"]
    if not isinstance(os_, list) or len(os_) == 0:
        raise err("ERR_INVALID_REQUEST", "operating_states must be non-empty array.")
    for s in os_:
        if not isinstance(s, str) or s not in VALID_STATES:
            raise err("ERR_INVALID_REQUEST", "Invalid state in operating_states.")
    with db.lock:
        bid = new_id()
        rec = {"id": bid, "firm_name": body["firm_name"], "broker_fee_pct": fee,
               "operating_states": os_}
        rec.update(_common_create())
        db.brokers[bid] = rec
    return ok(rec, 201)


@bp.route("/solar/brokers/<bid>", methods=["GET"])
def get_broker(bid):
    authenticate({"SrecBroker", "PlatformAdmin"})
    rec = db.brokers.get(bid)
    if not rec:
        raise err("ERR_NOT_FOUND", "Broker not found.")
    return ok(rec, 200)
