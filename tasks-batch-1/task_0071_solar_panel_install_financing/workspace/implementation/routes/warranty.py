from flask import Blueprint, request
from db import db, new_id, now_iso
from errors import err
from response import ok
from middleware import authenticate
from services.common import get_body, require_fields, list_response
from services import calc

bp = Blueprint("warranty", __name__)


def _common_create():
    ts = now_iso()
    return {"created_at": ts, "updated_at": ts, "version": 1}


# ---------------- WarrantyPolicy (read only) ----------------
@bp.route("/solar/warranty-policies/<wid>", methods=["GET"])
def get_policy(wid):
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin"})
    p = db.warranty_policies.get(wid)
    if not p:
        raise err("ERR_NOT_FOUND", "Warranty policy not found.")
    return ok(p, 200)


@bp.route("/solar/warranty-policies", methods=["GET"])
def list_policies():
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin"})
    rows = list(db.warranty_policies.values())
    proj = request.args.get("project_id")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    return list_response(rows)


# ---------------- WarrantyClaim ----------------
def _get_claim(cid):
    c = db.warranty_claims.get(cid)
    if not c:
        raise err("ERR_NOT_FOUND", "Warranty claim not found.")
    return c


@bp.route("/solar/warranty-claims", methods=["POST"])
def file_claim():
    user_id, role = authenticate({"Homeowner"})
    body = get_body()
    require_fields(body, ["project_id", "claim_type"])
    project = db.projects.get(body["project_id"])
    if not project:
        raise err("ERR_NOT_FOUND", "Project not found.")
    if project["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    ct = body["claim_type"]
    if ct not in ("PRODUCTION_SHORTFALL", "EQUIPMENT_DEFECT"):
        raise err("ERR_INVALID_REQUEST", "Invalid claim_type.")
    if project["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project not OPERATIONAL.")

    ws = body.get("claimed_window_start")
    we = body.get("claimed_window_end")
    if ct == "PRODUCTION_SHORTFALL":
        if ws is None or we is None:
            raise err("ERR_INVALID_REQUEST", "Production shortfall requires window.")
        if not isinstance(ws, str) or not isinstance(we, str):
            raise err("ERR_INVALID_REQUEST", "window must be strings.")
        if not (we > ws):
            raise err("ERR_INVALID_INTERVAL", "claimed_window_end must be after start.")
        # closed-interval overlap vs non-DENIED PRODUCTION_SHORTFALL claims on same project
        for other in db.warranty_claims.values():
            if other["project_id"] != project["id"]:
                continue
            if other["claim_type"] != "PRODUCTION_SHORTFALL":
                continue
            if other["status"] == "DENIED":
                continue
            ows = other.get("claimed_window_start")
            owe = other.get("claimed_window_end")
            if ows is None or owe is None:
                continue
            if ws <= owe and ows <= we:
                raise err("ERR_CLAIM_WINDOW_OVERLAP", "Claim window overlaps existing claim.")
    else:
        ws = None
        we = None

    with db.lock:
        cid = new_id()
        rec = {
            "id": cid,
            "project_id": project["id"],
            "claim_type": ct,
            "claimed_window_start": ws,
            "claimed_window_end": we,
            "status": "SUBMITTED",
            "measured_production_kwh": 0,
            "shortfall_kwh": 0,
            "payout_cents": 0,
        }
        rec.update(_common_create())
        db.warranty_claims[cid] = rec
    return ok(rec, 201)


@bp.route("/solar/warranty-claims/<cid>", methods=["GET"])
def get_claim(cid):
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin"})
    return ok(_get_claim(cid), 200)


@bp.route("/solar/warranty-claims", methods=["GET"])
def list_claims():
    authenticate({"Homeowner", "SolarInstaller", "PlatformAdmin"})
    rows = list(db.warranty_claims.values())
    proj = request.args.get("project_id")
    status = request.args.get("status")
    if proj is not None:
        rows = [r for r in rows if r["project_id"] == proj]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows)


@bp.route("/solar/warranty-claims/<cid>/request-info", methods=["POST"])
def request_info(cid):
    authenticate({"SolarInstaller"})
    c = _get_claim(cid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim not SUBMITTED.")
    with db.lock:
        c["status"] = "INFO_REQUESTED"
        db.touch(c)
    return ok(c, 200)


@bp.route("/solar/warranty-claims/<cid>/resubmit", methods=["POST"])
def resubmit(cid):
    user_id, role = authenticate({"Homeowner"})
    c = _get_claim(cid)
    project = db.projects.get(c["project_id"])
    if project and project["homeowner_id"] != user_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Acting homeowner does not own the project.")
    if c["status"] != "INFO_REQUESTED":
        raise err("ERR_INVALID_STATE", "Claim not INFO_REQUESTED.")
    with db.lock:
        c["status"] = "SUBMITTED"
        db.touch(c)
    return ok(c, 200)


@bp.route("/solar/warranty-claims/<cid>/approve", methods=["POST"])
def approve_claim(cid):
    authenticate({"SolarInstaller"})
    c = _get_claim(cid)
    project = db.projects.get(c["project_id"])
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim not SUBMITTED.")
    if not project or project["status"] != "OPERATIONAL":
        raise err("ERR_INVALID_STATE", "Project not OPERATIONAL.")

    # evaluate
    policy = None
    for pol in db.warranty_policies.values():
        if pol["project_id"] == project["id"]:
            policy = pol
            break
    # utility on the project's interconnection
    utility = None
    for app in db.interconnection_applications.values():
        if app["project_id"] == project["id"]:
            u = db.utilities.get(app["utility_id"])
            if u:
                utility = u
                break

    measured, shortfall, payout = calc.production_shortfall_eval(
        c, project, list(db.net_meter_periods.values()),
        policy if policy else {"production_guarantee_pct": 0.85},
        utility if utility else {"net_metering_rate_cents_per_kwh": 0})

    if c["claim_type"] == "PRODUCTION_SHORTFALL":
        if shortfall <= 0:
            raise err("ERR_NO_SHORTFALL", "No shortfall to approve.")

    with db.lock:
        c["measured_production_kwh"] = measured
        c["shortfall_kwh"] = shortfall
        c["payout_cents"] = payout
        c["status"] = "APPROVED"
        db.touch(c)
    return ok(c, 200)


@bp.route("/solar/warranty-claims/<cid>/deny", methods=["POST"])
def deny_claim(cid):
    authenticate({"SolarInstaller"})
    c = _get_claim(cid)
    if c["status"] != "SUBMITTED":
        raise err("ERR_INVALID_STATE", "Claim not SUBMITTED.")
    with db.lock:
        c["status"] = "DENIED"
        db.touch(c)
    return ok(c, 200)


@bp.route("/solar/warranty-claims/<cid>/remediate", methods=["POST"])
def remediate_claim(cid):
    authenticate({"SolarInstaller"})
    c = _get_claim(cid)
    if c["status"] != "APPROVED":
        raise err("ERR_INVALID_STATE", "Claim not APPROVED.")
    with db.lock:
        c["status"] = "REMEDIATED"
        db.touch(c)
    return ok(c, 200)
