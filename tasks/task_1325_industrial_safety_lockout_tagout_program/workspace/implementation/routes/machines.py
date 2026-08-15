"""Machine registry, modifications (OCC-guarded), and service posture (PRD 3.1/3.3)."""

from flask import Blueprint, request

import db
from clock import CLOCK, parse_iso, fmt
from errors import ApiError
from middleware import auth, paginate, ALL_ROLES
from response import ok, ok_list
from services import core

bp = Blueprint("machines", __name__)


@bp.route("/machines", methods=["POST"])
def create_machine():
    auth(["EHSManager"])
    body = core.body_json()
    asset_tag = core.req_str(body, "asset_tag")
    name = core.req_str(body, "name")
    area = core.req_str(body, "area")
    policy = core.req_enum(body, "risk_window_policy",
                           ("ROLLING_12MO", "SINCE_PROCEDURE_ACTIVATION"))
    # Uniqueness (PRD 2.8 stage 11): duplicate asset_tag reports as ERR_VALIDATION.
    for m in db.DB["machines"].values():
        if m["asset_tag"] == asset_tag:
            raise ApiError("ERR_VALIDATION", 400, "asset_tag must be unique across all machines")
    m = core.stamp_new({
        "id": core.new_id(),
        "asset_tag": asset_tag,
        "name": name,
        "area": area,
        "risk_window_policy": policy,
        "status": "IN_SERVICE",
    })
    db.DB["machines"][m["id"]] = m
    return ok(core.machine_view(m), 201)


@bp.route("/machines", methods=["GET"])
def list_machines():
    auth(ALL_ROLES)
    status = request.args.get("status")
    tier = request.args.get("risk_tier")
    items = list(db.DB["machines"].values())
    if status is not None:
        items = [m for m in items if m["status"] == status]
    if tier is not None:
        items = [m for m in items if core.risk_tier(m) == tier]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.machine_view(m) for m in page], total, limit, offset)


@bp.route("/machines/<mid>", methods=["GET"])
def get_machine(mid):
    auth(ALL_ROLES)
    m = core.get_or_404("machines", mid, "Machine")
    return ok(core.machine_view(m))


@bp.route("/machines/<mid>/modifications", methods=["POST"])
def create_modification(mid):
    auth(["EHSManager"])
    body = core.body_json()
    description = core.req_str(body, "description")
    expected = core.req_int(body, "expected_machine_version")
    m = core.get_or_404("machines", mid, "Machine")
    # Optimistic concurrency (PRD 2.7): the only OCC-guarded write in the API.
    if expected != m["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "Machine version has advanced past expected_machine_version")
    mod = core.stamp_new({
        "id": core.new_id(),
        "machine_id": m["id"],
        "description": description,
        "review_status": "UNREVIEWED",
    }, with_version=False)
    db.DB["modifications"][mod["id"]] = mod
    # Successful registration advances the machine version by exactly one.
    m["version"] += 1
    m["updated_at"] = fmt(CLOCK.now())
    # Cascade: the machine's ACTIVE procedure goes UNDER_REVISION, taking its
    # SETUP sessions (and their ISSUED locks) down with it (PRD 3.3).
    proc = next((p for p in db.DB["lockout_procedures"].values()
                 if p["machine_id"] == m["id"] and p["status"] == "ACTIVE"), None)
    if proc is not None:
        core.procedure_into_revision_on_modification(proc)
    return ok(core.modification_view(mod), 201)


@bp.route("/machines/<mid>/modifications", methods=["GET"])
def list_modifications(mid):
    auth(ALL_ROLES)
    core.get_or_404("machines", mid, "Machine")
    items = [mod for mod in db.DB["modifications"].values() if mod["machine_id"] == mid]
    items = core.sorted_by_created(items)
    page, total, limit, offset = paginate(items)
    return ok_list([core.modification_view(mod) for mod in page], total, limit, offset)


@bp.route("/machines/<mid>/out-of-service", methods=["POST"])
def out_of_service(mid):
    auth(["EHSManager"])
    m = core.get_or_404("machines", mid, "Machine")
    if m["status"] != "IN_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Machine must be IN_SERVICE to go out of service")
    # Active work under lock is never interrupted administratively (PRD 3.1).
    for s in db.DB["lockout_sessions"].values():
        if s["machine_id"] == mid and s["status"] == "LOCKED":
            raise ApiError("ERR_MACHINE_HAS_OPEN_SESSIONS", 409,
                           "Machine has a LOCKED session")
    core.machine_out_of_service(m)
    return ok(core.machine_view(m))


@bp.route("/machines/<mid>/return-to-service", methods=["POST"])
def return_to_service(mid):
    auth(["EHSManager"])
    m = core.get_or_404("machines", mid, "Machine")
    if m["status"] != "OUT_OF_SERVICE":
        raise ApiError("ERR_INVALID_STATE", 409,
                       "Machine must be OUT_OF_SERVICE to return to service")
    # Guards run in the PRD 3.1 fixed order: ACTIVE procedure, audit currency,
    # then open sessions.
    proc = next((p for p in db.DB["lockout_procedures"].values()
                 if p["machine_id"] == mid and p["status"] == "ACTIVE"), None)
    if proc is None:
        raise ApiError("ERR_PROCEDURE_NOT_ACTIVE", 409,
                       "Machine has no ACTIVE lockout procedure")
    if CLOCK.now() > parse_iso(proc["audit_due_at"]):
        raise ApiError("ERR_AUDIT_OVERDUE", 409, "The ACTIVE procedure's audit is overdue")
    if core.open_session_count(mid) != 0:
        raise ApiError("ERR_MACHINE_HAS_OPEN_SESSIONS", 409,
                       "Machine still has open lockout sessions")
    m["status"] = "IN_SERVICE"
    core.touch(m)
    return ok(core.machine_view(m))
