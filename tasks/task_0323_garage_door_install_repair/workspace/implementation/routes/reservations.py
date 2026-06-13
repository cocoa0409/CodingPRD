"""PartReservation routes (PRD §3.9). OCC on job version (PRD §2.6)."""
from flask import Blueprint, request

import db
import errors
import lookup
import serialize
import services.calc as calc
import util
from middleware import authenticate, require_role
from response import success

bp = Blueprint("reservations", __name__)


@bp.route("/part-reservations", methods=["POST"])
def create_reservation():
    _, role = authenticate()
    require_role(role, ["Dispatcher", "ServiceManager"])
    body = util.get_body()
    util.require_fields(body, ["job_id", "part_id", "qty", "expected_job_version"])
    job_id = body.get("job_id")
    part_id = body.get("part_id")
    if not isinstance(job_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "job_id must be a string")
    if not isinstance(part_id, str):
        raise errors.err(errors.ERR_INVALID_REQUEST, "part_id must be a string")
    qty = util.require_qty(body, "qty")
    expected = util.require_int(body, "expected_job_version")

    # Existence (left-to-right)
    job = lookup.job(job_id)
    part = lookup.part(part_id)

    # OCC (priority 17)
    if expected != job["version"]:
        raise errors.err(errors.ERR_STALE_VERSION, "Stale job version")

    # Business: stock sufficiency (priority 12)
    available = part["on_hand_qty"] - calc.reserved_qty(part_id)
    if qty > available:
        raise errors.err(errors.ERR_INSUFFICIENT_STOCK, "Insufficient stock")

    res = {"job_id": job_id, "part_id": part_id, "qty": qty, "status": "HELD"}
    db.stamp_create(res, common_fields=True, versioned=True)
    db.part_reservations[res["id"]] = res
    db.touch(part)  # reserved_qty/available_qty derive live
    db.touch(job)   # advances job version
    return success(serialize.part_reservation(res), status=201)


@bp.route("/part-reservations", methods=["GET"])
def list_reservations():
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician"])
    limit, offset = util.parse_pagination()
    job_id = request.args.get("job_id")
    part_id = request.args.get("part_id")
    status = request.args.get("status")
    rows = []
    for r in db.part_reservations.values():
        if job_id is not None and r["job_id"] != job_id:
            continue
        if part_id is not None and r["part_id"] != part_id:
            continue
        if status is not None and r["status"] != status:
            continue
        rows.append(r)
    page, pagination = util.paginate(rows, limit, offset)
    return success([serialize.part_reservation(r) for r in page], pagination=pagination)


@bp.route("/part-reservations/<id>", methods=["GET"])
def get_reservation(id):
    _, role = authenticate()
    require_role(role, ["ServiceManager", "Dispatcher", "Technician"])
    r = lookup.part_reservation(id)
    return success(serialize.part_reservation(r))


@bp.route("/part-reservations/<id>/consume", methods=["POST"])
def consume_reservation(id):
    user_id, role = authenticate()
    require_role(role, ["Technician"])
    r = lookup.part_reservation(id)
    job = db.jobs[r["job_id"]]
    if r["status"] != "HELD":
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation must be HELD to consume")
    if job["dispatch_status"] != "ON_SITE":
        raise errors.err(errors.ERR_INVALID_STATE, "Parent job must be ON_SITE to consume")
    r["status"] = "CONSUMED"
    part = db.parts.get(r["part_id"])
    if part is not None:
        # consumed stock leaves both pools; reserved_qty derives live from HELD set
        part["on_hand_qty"] -= r["qty"]
        db.touch(part)
    db.touch(r)
    return success(serialize.part_reservation(r))


@bp.route("/part-reservations/<id>/release", methods=["POST"])
def release_reservation(id):
    _, role = authenticate()
    require_role(role, ["Dispatcher", "ServiceManager"])
    r = lookup.part_reservation(id)
    if r["status"] != "HELD":
        raise errors.err(errors.ERR_INVALID_STATE, "Reservation must be HELD to release")
    r["status"] = "RELEASED"
    part = db.parts.get(r["part_id"])
    if part is not None:
        db.touch(part)  # reserved_qty/available_qty derive live
    db.touch(r)
    return success(serialize.part_reservation(r))
