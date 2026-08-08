"""Routes: logical clock, clients, vaults, artworks, condition reports."""
from flask import Blueprint

import store
from store import db, new_record, touch, serialize
from common import (auth, get_body, require_fields, check_enum, get_or_404,
                    fk_or_404, paginate)
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt
import domain

bp = Blueprint("core", __name__)

CLIENT_TYPES = {"INDIVIDUAL", "INSTITUTION", "DEALER"}
CLIMATE = {"AMBIENT", "COOL", "COLD"}
SIZE = {"SMALL", "MEDIUM", "LARGE"}
FRAGILITY = {"LOW", "MEDIUM", "HIGH"}
REPORT_TYPES = {"INTAKE", "PRE_TRANSIT", "POST_TRANSIT", "PERIODIC", "LOAN_RETURN"}
GRADES = {"A", "B", "C", "D", "F"}


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    auth(["Registrar", "Coordinator", "Approver", "BillingAdmin"])
    body = get_body()
    require_fields(body, ["to_iso8601"])
    store.set_clock(parse_dt(body["to_iso8601"]))
    return object_response({}, 200)


# ---------------------------------------------------------------------------
# Clients
# ---------------------------------------------------------------------------
@bp.route("/clients", methods=["POST"])
def create_client():
    auth(["Registrar"])
    body = get_body()
    require_fields(body, ["name", "client_type", "billing_email"])
    check_enum(body["client_type"], CLIENT_TYPES, "client_type")
    credit = body.get("credit_terms_days", 30)
    if credit is None:
        credit = 30
    rec = new_record({
        "name": body["name"],
        "client_type": body["client_type"],
        "billing_email": body["billing_email"],
        "credit_terms_days": credit,
        "account_status": "ACTIVE",
        "outstanding_balance_cents": 0,
    })
    db["clients"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/clients/<rid>", methods=["GET"])
def get_client(rid):
    uid, role = auth(["Registrar", "Client"])
    if role == "Client" and rid != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "not your client record")
    rec = get_or_404("clients", rid)
    return object_response(serialize(rec))


@bp.route("/clients", methods=["GET"])
def list_clients():
    auth(["Registrar"])
    from flask import request
    ct = request.args.get("client_type")
    recs = [r for r in db["clients"].values() if ct is None or r["client_type"] == ct]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


@bp.route("/clients/<rid>/state", methods=["POST"])
def client_state(rid):
    auth(["Registrar"])
    rec = get_or_404("clients", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, {"ACTIVE", "SUSPENDED"}, "to_status")
    cur = rec["account_status"]
    if (cur, to_status) not in {("ACTIVE", "SUSPENDED"), ("SUSPENDED", "ACTIVE")}:
        raise err("ERR_INVALID_STATE", "cannot move client from %s to %s" % (cur, to_status))
    rec["account_status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# Vaults
# ---------------------------------------------------------------------------
@bp.route("/vaults", methods=["POST"])
def create_vault():
    auth(["Registrar"])
    body = get_body()
    require_fields(body, ["name", "climate_class", "capacity_slots"])
    check_enum(body["climate_class"], CLIMATE, "climate_class")
    cap = body["capacity_slots"]
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        raise err("ERR_VALIDATION", "capacity_slots must be an integer >= 1")
    temp = body.get("temp_setpoint_c", 20)
    hum = body.get("humidity_setpoint_pct", 50)
    rec = new_record({
        "name": body["name"],
        "climate_class": body["climate_class"],
        "capacity_slots": cap,
        "occupied_slots": 0,
        "temp_setpoint_c": temp if temp is not None else 20,
        "humidity_setpoint_pct": hum if hum is not None else 50,
        "status": "OPERATIONAL",
    })
    db["vaults"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/vaults/<rid>", methods=["GET"])
def get_vault(rid):
    auth(["Registrar", "Coordinator", "Approver"])
    rec = get_or_404("vaults", rid)
    return object_response(serialize(rec))


@bp.route("/vaults", methods=["GET"])
def list_vaults():
    auth(["Registrar", "Coordinator", "Approver"])
    from flask import request
    cc = request.args.get("climate_class")
    st = request.args.get("status")
    recs = [r for r in db["vaults"].values()
            if (cc is None or r["climate_class"] == cc) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


@bp.route("/vaults/<rid>/state", methods=["POST"])
def vault_state(rid):
    auth(["Registrar"])
    rec = get_or_404("vaults", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, {"OPERATIONAL", "MAINTENANCE", "DECOMMISSIONED"}, "to_status")
    cur = rec["status"]
    allowed = {
        ("OPERATIONAL", "MAINTENANCE"),
        ("MAINTENANCE", "OPERATIONAL"),
        ("OPERATIONAL", "DECOMMISSIONED"),
    }
    if (cur, to_status) not in allowed:
        raise err("ERR_INVALID_STATE", "cannot move vault from %s to %s" % (cur, to_status))
    if to_status == "DECOMMISSIONED" and rec["occupied_slots"] != 0:
        raise err("ERR_INVALID_STATE", "vault still occupied")
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# Artworks
# ---------------------------------------------------------------------------
@bp.route("/artworks", methods=["POST"])
def create_artwork():
    auth(["Registrar"])
    body = get_body()
    fk_or_404("clients", body.get("client_id"))
    require_fields(body, ["client_id", "title", "artist", "size_class",
                          "fragility_class", "climate_class"])
    check_enum(body["size_class"], SIZE, "size_class")
    check_enum(body["fragility_class"], FRAGILITY, "fragility_class")
    check_enum(body["climate_class"], CLIMATE, "climate_class")
    rec = new_record({
        "client_id": body["client_id"],
        "title": body["title"],
        "artist": body["artist"],
        "medium": body.get("medium"),
        "year": body.get("year"),
        "size_class": body["size_class"],
        "fragility_class": body["fragility_class"],
        "climate_class": body["climate_class"],
        "custody_status": "IN_INTAKE",
        "condition_status": "SOUND",
        "appraised_value_cents": 0,
        "active_policy_id": None,
    })
    db["artworks"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/artworks/<rid>", methods=["GET"])
def get_artwork(rid):
    uid, role = auth(["Registrar", "Coordinator", "Approver", "Client"])
    rec = get_or_404("artworks", rid)
    if role == "Client" and rec["client_id"] != uid:
        raise err("ERR_OWNERSHIP_REQUIRED", "not your artwork")
    return object_response(serialize(rec))


@bp.route("/artworks", methods=["GET"])
def list_artworks():
    uid, role = auth(["Registrar", "Coordinator", "Approver", "Client"])
    from flask import request
    client_id = request.args.get("client_id")
    custody = request.args.get("custody_status")
    condition = request.args.get("condition_status")
    if role == "Client":
        if client_id is not None and client_id != uid:
            raise err("ERR_OWNERSHIP_REQUIRED", "not your client scope")
        client_id = uid
    recs = [r for r in db["artworks"].values()
            if (client_id is None or r["client_id"] == client_id)
            and (custody is None or r["custody_status"] == custody)
            and (condition is None or r["condition_status"] == condition)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


@bp.route("/artworks/<rid>/state", methods=["POST"])
def artwork_state(rid):
    auth(["Registrar"])
    rec = get_or_404("artworks", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    check_enum(to_status, {"IN_INTAKE", "IN_STORAGE", "IN_TRANSIT", "ON_LOAN", "DEACCESSIONED"},
               "to_status")
    # Only the Registrar-driven deaccession is a direct endpoint transition.
    if to_status != "DEACCESSIONED":
        raise err("ERR_INVALID_STATE", "unsupported custody transition via endpoint")
    if rec["custody_status"] != "IN_STORAGE":
        raise err("ERR_INVALID_STATE", "artwork must be IN_STORAGE to deaccession")
    rec["custody_status"] = "DEACCESSIONED"
    touch(rec)
    return object_response(serialize(rec))


# ---------------------------------------------------------------------------
# Condition reports (immutable: only id + created_at)
# ---------------------------------------------------------------------------
@bp.route("/condition-reports", methods=["POST"])
def create_condition_report():
    auth(["Registrar"])
    body = get_body()
    artwork = fk_or_404("artworks", body.get("artwork_id"))
    require_fields(body, ["artwork_id", "report_type", "condition_grade", "damage_noted"])
    check_enum(body["report_type"], REPORT_TYPES, "report_type")
    check_enum(body["condition_grade"], GRADES, "condition_grade")
    if not isinstance(body["damage_noted"], bool):
        raise err("ERR_VALIDATION", "damage_noted must be a boolean")
    rec = new_record({
        "artwork_id": body["artwork_id"],
        "report_type": body["report_type"],
        "condition_grade": body["condition_grade"],
        "damage_noted": body["damage_noted"],
        "notes": body.get("notes"),
    }, common=False)
    db["condition_reports"][rec["id"]] = rec
    _apply_condition_transition(artwork, body["condition_grade"], body["damage_noted"])
    return object_response(serialize(rec), 201)


def _apply_condition_transition(artwork, grade, damage_noted):
    cur = artwork["condition_status"]
    new = None
    if damage_noted and grade in ("C", "D") and cur == "SOUND":
        new = "MINOR_DAMAGE"
    elif damage_noted and grade == "F" and cur in ("SOUND", "MINOR_DAMAGE"):
        new = "MAJOR_DAMAGE"
    elif (not damage_noted) and grade == "A" and cur == "MINOR_DAMAGE":
        new = "SOUND"
    if new is None or new == cur:
        return
    artwork["condition_status"] = new
    touch(artwork)
    if new == "MAJOR_DAMAGE":
        domain.cascade_major_damage(artwork)


@bp.route("/condition-reports/<rid>", methods=["GET"])
def get_condition_report(rid):
    auth(["Registrar", "Coordinator"])
    rec = get_or_404("condition_reports", rid)
    return object_response(serialize(rec))


@bp.route("/condition-reports", methods=["GET"])
def list_condition_reports():
    auth(["Registrar", "Coordinator"])
    from flask import request
    aid = request.args.get("artwork_id")
    rt = request.args.get("report_type")
    recs = [r for r in db["condition_reports"].values()
            if (aid is None or r["artwork_id"] == aid) and (rt is None or r["report_type"] == rt)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
