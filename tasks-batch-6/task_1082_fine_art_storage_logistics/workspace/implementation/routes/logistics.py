"""Routes: crates, rigging crews, transport jobs."""
from datetime import timedelta

from flask import Blueprint, request

from store import db, new_record, touch, serialize
from common import (auth, get_body, require_fields, check_enum, require_int,
                    require_number, require_bool, get_or_404, fk_or_404, paginate)
from envelope import object_response, list_response
from errors import err
from timeutil import parse_dt
import calc

bp = Blueprint("logistics", __name__)

CRATE_TYPES = {"SOFT", "HARD", "CLIMATE"}
CERT_LEVELS = {"STANDARD", "FINE_ART", "MONUMENTAL"}


# ---------------------------------------------------------------------------
# Crates
# ---------------------------------------------------------------------------
@bp.route("/crates", methods=["POST"])
def create_crate():
    auth(["Coordinator"])
    body = get_body()
    fk_or_404("artworks", body.get("artwork_id"))
    require_fields(body, ["artwork_id", "crate_type", "internal_length_cm",
                          "internal_width_cm", "internal_height_cm"])
    check_enum(body["crate_type"], CRATE_TYPES, "crate_type")
    for f in ("internal_length_cm", "internal_width_cm", "internal_height_cm"):
        require_number(body, f)
    rec = new_record({
        "artwork_id": body["artwork_id"],
        "crate_type": body["crate_type"],
        "internal_length_cm": body["internal_length_cm"],
        "internal_width_cm": body["internal_width_cm"],
        "internal_height_cm": body["internal_height_cm"],
        "status": "BUILDING",
    })
    db["crates"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/crates/<rid>/state", methods=["POST"])
def crate_state(rid):
    auth(["Coordinator"])
    rec = get_or_404("crates", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in {"BUILDING", "READY", "IN_USE", "RETIRED"}:
        raise err("ERR_VALIDATION", "invalid to_status")
    cur = rec["status"]
    allowed = {("BUILDING", "READY"), ("READY", "RETIRED")}
    if (cur, to_status) not in allowed:
        raise err("ERR_INVALID_STATE", "cannot move crate from %s to %s" % (cur, to_status))
    rec["status"] = to_status
    touch(rec)
    return object_response(serialize(rec))


@bp.route("/crates/<rid>", methods=["GET"])
def get_crate(rid):
    auth(["Coordinator", "Registrar"])
    rec = get_or_404("crates", rid)
    return object_response(serialize(rec))


@bp.route("/crates", methods=["GET"])
def list_crates():
    auth(["Coordinator", "Registrar"])
    aid = request.args.get("artwork_id")
    st = request.args.get("status")
    recs = [r for r in db["crates"].values()
            if (aid is None or r["artwork_id"] == aid) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Rigging crews
# ---------------------------------------------------------------------------
@bp.route("/crews", methods=["POST"])
def create_crew():
    auth(["Coordinator"])
    body = get_body()
    require_fields(body, ["name", "crew_size", "certification_level"])
    require_int(body, "crew_size")
    check_enum(body["certification_level"], CERT_LEVELS, "certification_level")
    rec = new_record({
        "name": body["name"],
        "crew_size": body["crew_size"],
        "certification_level": body["certification_level"],
        "status": "AVAILABLE",
    })
    db["crews"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/crews/<rid>", methods=["GET"])
def get_crew(rid):
    auth(["Coordinator"])
    rec = get_or_404("crews", rid)
    return object_response(serialize(rec))


@bp.route("/crews", methods=["GET"])
def list_crews():
    auth(["Coordinator"])
    cl = request.args.get("certification_level")
    st = request.args.get("status")
    recs = [r for r in db["crews"].values()
            if (cl is None or r["certification_level"] == cl) and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)


# ---------------------------------------------------------------------------
# Transport jobs
# ---------------------------------------------------------------------------
def _crew_conflict(crew_id, new_start, new_end):
    buffer = timedelta(minutes=calc.SETUP_BUFFER_MINUTES)
    for j in db["transport_jobs"].values():
        if j["crew_id"] != crew_id or j["status"] not in ("SCHEDULED", "IN_PROGRESS"):
            continue
        es = parse_dt(j["scheduled_start"])
        ee = parse_dt(j["scheduled_end"])
        if new_start < ee + buffer and new_end + buffer > es:
            return True
    return False


@bp.route("/transport-jobs", methods=["POST"])
def create_transport_job():
    auth(["Coordinator"])
    body = get_body()
    fk_or_404("artworks", body.get("artwork_id"))
    fk_or_404("crates", body.get("crate_id"))
    fk_or_404("crews", body.get("crew_id"))
    require_fields(body, ["artwork_id", "crate_id", "crew_id", "origin_location",
                          "destination_location", "scheduled_start", "scheduled_end",
                          "requires_rigging", "estimated_hours"])
    require_bool(body, "requires_rigging")
    require_number(body, "estimated_hours")
    start = parse_dt(body["scheduled_start"])
    end = parse_dt(body["scheduled_end"])
    if not end > start:
        raise err("ERR_TIME_WINDOW_INVALID", "scheduled_end must be after scheduled_start")
    if _crew_conflict(body["crew_id"], start, end):
        raise err("ERR_CREW_UNAVAILABLE", "crew already committed in an overlapping window")
    charge = calc.transport_charge(body["estimated_hours"], body["requires_rigging"])
    rec = new_record({
        "artwork_id": body["artwork_id"],
        "crate_id": body["crate_id"],
        "crew_id": body["crew_id"],
        "origin_location": body["origin_location"],
        "destination_location": body["destination_location"],
        "scheduled_start": body["scheduled_start"],
        "scheduled_end": body["scheduled_end"],
        "requires_rigging": body["requires_rigging"],
        "estimated_hours": body["estimated_hours"],
        "actual_hours": None,
        "transport_charge_cents": charge,
        "status": "SCHEDULED",
    })
    db["transport_jobs"][rec["id"]] = rec
    return object_response(serialize(rec), 201)


@bp.route("/transport-jobs/<rid>/state", methods=["POST"])
def transport_job_state(rid):
    auth(["Coordinator"])
    rec = get_or_404("transport_jobs", rid)
    body = get_body()
    require_fields(body, ["to_status"])
    to_status = body["to_status"]
    if to_status not in {"SCHEDULED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}:
        raise err("ERR_VALIDATION", "invalid to_status")
    cur = rec["status"]
    valid = {("SCHEDULED", "IN_PROGRESS"), ("IN_PROGRESS", "COMPLETED"),
             ("SCHEDULED", "CANCELLED")}
    if (cur, to_status) not in valid:
        raise err("ERR_INVALID_STATE", "cannot move job from %s to %s" % (cur, to_status))

    artwork = db["artworks"].get(rec["artwork_id"])
    crate = db["crates"].get(rec["crate_id"])

    if to_status == "IN_PROGRESS":
        if artwork["condition_status"] == "MAJOR_DAMAGE":
            raise err("ERR_ARTWORK_CONDITION_UNSAFE", "artwork condition unsafe")
        if artwork["custody_status"] != "IN_STORAGE":
            raise err("ERR_ARTWORK_NOT_AVAILABLE", "artwork not available for transport")
        if crate is None or crate["status"] != "READY" or crate["artwork_id"] != rec["artwork_id"]:
            raise err("ERR_CRATE_NOT_READY", "crate not ready for this artwork")
        rec["status"] = "IN_PROGRESS"
        touch(rec)
        artwork["custody_status"] = "IN_TRANSIT"
        touch(artwork)
        crate["status"] = "IN_USE"
        touch(crate)
    elif to_status == "COMPLETED":
        if body.get("actual_hours") is None:
            raise err("ERR_VALIDATION", "actual_hours is required to complete a job")
        require_number(body, "actual_hours")
        rec["actual_hours"] = body["actual_hours"]
        rec["transport_charge_cents"] = calc.transport_charge(
            body["actual_hours"], rec["requires_rigging"])
        rec["status"] = "COMPLETED"
        touch(rec)
        if artwork is not None:
            artwork["custody_status"] = "IN_STORAGE"
            touch(artwork)
        if crate is not None:
            crate["status"] = "READY"
            touch(crate)
    else:  # CANCELLED
        rec["status"] = "CANCELLED"
        touch(rec)
    return object_response(serialize(rec))


@bp.route("/transport-jobs/<rid>", methods=["GET"])
def get_transport_job(rid):
    auth(["Coordinator", "Registrar"])
    rec = get_or_404("transport_jobs", rid)
    return object_response(serialize(rec))


@bp.route("/transport-jobs", methods=["GET"])
def list_transport_jobs():
    auth(["Coordinator", "Registrar"])
    aid = request.args.get("artwork_id")
    cid = request.args.get("crate_id")
    crid = request.args.get("crew_id")
    st = request.args.get("status")
    recs = [r for r in db["transport_jobs"].values()
            if (aid is None or r["artwork_id"] == aid)
            and (cid is None or r["crate_id"] == cid)
            and (crid is None or r["crew_id"] == crid)
            and (st is None or r["status"] == st)]
    items, limit, offset, total = paginate(recs)
    return list_response(items, limit, offset, total)
