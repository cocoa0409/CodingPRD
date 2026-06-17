"""MaterialReservation and BuildJob routes (production)."""
from flask import Blueprint, request

from db import store
from errors import err
from middleware import get_user_context, require_role
from response import success, success_list
from helpers import (get_body, require_str, require_int, parse_datetime,
                     parse_stored_dt, parse_pagination, paginate, sort_by_created)
from models import (_base_record, touch, serialize_reservation, serialize_build_job,
                    material_reserved_sheets)
from lookups import (get_shop, get_project_in_shop, get_reservation_in_project,
                     get_build_job_in_project)

bp = Blueprint("production", __name__)


# --------------------------------------------------------------------------
# MaterialReservation
# --------------------------------------------------------------------------
@bp.route("/shops/<shop_id>/projects/<project_id>/material-reservations", methods=["POST"])
def create_reservation(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    material_id = require_str(body, "material_id")
    sheets = require_int(body, "sheets", minimum=1)

    material = store.materials.get(material_id)
    if material is None or material["shop_id"] != shop_id:
        raise err("ERR_CROSS_SHOP_REFERENCE", "Material belongs to a different shop")

    available = material["on_hand_sheets"] - material_reserved_sheets(material_id)
    if sheets > available:
        raise err("ERR_INSUFFICIENT_STOCK", "Not enough available sheets")

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "material_id": material_id,
        "sheets": sheets,
        "status": "HELD",
    })
    store.reservations[rec["id"]] = rec
    # reserved/available are computed on the material; nothing to write there.
    touch(material)
    return success(serialize_reservation(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/material-reservations/<reservation_id>", methods=["GET"])
def get_reservation(shop_id, project_id, reservation_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    r = get_reservation_in_project(shop_id, project_id, reservation_id)
    return success(serialize_reservation(r), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/material-reservations", methods=["GET"])
def list_reservations(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    items = [r for r in store.reservations.values() if r["project_id"] == project_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_reservation(r) for r in page], limit, offset, total)


@bp.route("/shops/<shop_id>/material-reservations", methods=["GET"])
def list_reservations_by_material(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_shop(shop_id)
    limit, offset = parse_pagination()
    material_id = request.args.get("material_id")
    # Scope to reservations whose project lives in this shop.
    shop_proj_ids = {p["id"] for p in store.projects.values() if p["shop_id"] == shop_id}
    items = [r for r in store.reservations.values() if r["project_id"] in shop_proj_ids]
    if material_id is not None:
        items = [r for r in items if r["material_id"] == material_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_reservation(r) for r in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/material-reservations/<reservation_id>/commit", methods=["POST"])
def commit_reservation(shop_id, project_id, reservation_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    r = get_reservation_in_project(shop_id, project_id, reservation_id)
    if r["status"] != "HELD":
        raise err("ERR_INVALID_STATE", "Reservation is not HELD")
    if p["status"] not in ("IN_PRODUCTION", "CHANGE_PENDING"):
        raise err("ERR_INVALID_STATE", "Project is not in production")
    r["status"] = "COMMITTED"
    touch(r)
    return success(serialize_reservation(r), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/material-reservations/<reservation_id>/release", methods=["POST"])
def release_reservation(shop_id, project_id, reservation_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    r = get_reservation_in_project(shop_id, project_id, reservation_id)
    if r["status"] not in ("HELD", "COMMITTED"):
        raise err("ERR_INVALID_STATE", "Reservation cannot be released from %s" % r["status"])
    if r["status"] == "COMMITTED" and p["status"] == "IN_PRODUCTION":
        raise err("ERR_RESERVATION_LOCKED", "Committed reservation is locked during production")
    r["status"] = "RELEASED"
    touch(r)
    material = store.materials.get(r["material_id"])
    if material is not None:
        touch(material)
    return success(serialize_reservation(r), 200)


# --------------------------------------------------------------------------
# BuildJob
# --------------------------------------------------------------------------
def _intervals_conflict(a_start, a_end, b_start, b_end, buffer_min):
    """Two intervals conflict if they overlap once b is padded by buffer on both
    sides. Padded b = [b_start - buffer, b_end + buffer). Overlap iff
    a_start < padded_end and padded_start < a_end."""
    from datetime import timedelta
    pad = timedelta(minutes=buffer_min)
    padded_start = b_start - pad
    padded_end = b_end + pad
    return a_start < padded_end and padded_start < a_end


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs", methods=["POST"])
def create_build_job(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    p = get_project_in_shop(shop_id, project_id)
    body = get_body()
    machine_id = require_str(body, "machine_id")
    start_utc = parse_datetime(body, "start_utc")
    end_utc = parse_datetime(body, "end_utc")
    if not (end_utc > start_utc):
        raise err("ERR_INVALID_REQUEST", "end_utc must be strictly after start_utc")

    # State: scheduling first build job transitions CONTRACTED -> IN_PRODUCTION.
    # Only CONTRACTED (first job) or IN_PRODUCTION (subsequent jobs) are valid.
    if p["status"] not in ("CONTRACTED", "IN_PRODUCTION"):
        raise err("ERR_INVALID_STATE", "Project is not in a state that allows build jobs")

    # Cross-shop: machine must belong to path shop.
    machine = store.machines.get(machine_id)
    if machine is None or machine["shop_id"] != shop_id:
        raise err("ERR_CROSS_SHOP_REFERENCE", "Machine belongs to a different shop")

    # Time conflict against non-CANCELLED jobs on same machine, with changeover buffer.
    buffer_min = machine["changeover_buffer_min"]
    for b in store.build_jobs.values():
        if b["machine_id"] != machine_id or b["status"] == "CANCELLED":
            continue
        b_start = parse_stored_dt(b["start_utc"])
        b_end = parse_stored_dt(b["end_utc"])
        if _intervals_conflict(start_utc, end_utc, b_start, b_end, buffer_min):
            raise err("ERR_MACHINE_TIME_CONFLICT", "Build job conflicts with another on this machine")

    # Deposit gate: first build job on CONTRACTED project requires deposit fully paid.
    from models import project_paid_to_date
    if p["status"] == "CONTRACTED":
        if project_paid_to_date(project_id) < p["deposit_required_cents"]:
            raise err("ERR_DEPOSIT_UNPAID", "Deposit not fully paid")

    rec = _base_record()
    rec.update({
        "project_id": project_id,
        "machine_id": machine_id,
        "start_utc": body["start_utc"],
        "end_utc": body["end_utc"],
        "status": "SCHEDULED",
    })
    store.build_jobs[rec["id"]] = rec

    if p["status"] == "CONTRACTED":
        p["status"] = "IN_PRODUCTION"
        touch(p)
    return success(serialize_build_job(rec), 201)


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs/<build_job_id>", methods=["GET"])
def get_build_job(shop_id, project_id, build_job_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    b = get_build_job_in_project(shop_id, project_id, build_job_id)
    return success(serialize_build_job(b), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs", methods=["GET"])
def list_build_jobs(shop_id, project_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_project_in_shop(shop_id, project_id)
    limit, offset = parse_pagination()
    items = [b for b in store.build_jobs.values() if b["project_id"] == project_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_build_job(b) for b in page], limit, offset, total)


@bp.route("/shops/<shop_id>/build-jobs", methods=["GET"])
def list_build_jobs_by_machine(shop_id):
    _, role = get_user_context()
    require_role(role, {"ShopAdmin", "ShopManager"})
    get_shop(shop_id)
    limit, offset = parse_pagination()
    machine_id = request.args.get("machine_id")
    shop_proj_ids = {p["id"] for p in store.projects.values() if p["shop_id"] == shop_id}
    items = [b for b in store.build_jobs.values() if b["project_id"] in shop_proj_ids]
    if machine_id is not None:
        items = [b for b in items if b["machine_id"] == machine_id]
    items = sort_by_created(items)
    total = len(items)
    page = paginate(items, limit, offset)
    return success_list([serialize_build_job(b) for b in page], limit, offset, total)


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs/<build_job_id>/start", methods=["POST"])
def start_build_job(shop_id, project_id, build_job_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    b = get_build_job_in_project(shop_id, project_id, build_job_id)
    if b["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Build job is not SCHEDULED")
    machine = store.machines.get(b["machine_id"])
    if machine is None or machine["status"] != "ONLINE":
        raise err("ERR_MACHINE_OFFLINE", "Machine is offline")
    b["status"] = "IN_PROGRESS"
    touch(b)
    return success(serialize_build_job(b), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs/<build_job_id>/complete", methods=["POST"])
def complete_build_job(shop_id, project_id, build_job_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    b = get_build_job_in_project(shop_id, project_id, build_job_id)
    if b["status"] != "IN_PROGRESS":
        raise err("ERR_INVALID_STATE", "Build job is not IN_PROGRESS")
    b["status"] = "COMPLETE"
    touch(b)
    # Consumption cascade: every COMMITTED reservation on the project -> CONSUMED;
    # decrement that material's on_hand_sheets by the reservation's sheets.
    for r in store.reservations.values():
        if r["project_id"] == project_id and r["status"] == "COMMITTED":
            r["status"] = "CONSUMED"
            touch(r)
            material = store.materials.get(r["material_id"])
            if material is not None:
                material["on_hand_sheets"] -= r["sheets"]
                touch(material)
    return success(serialize_build_job(b), 200)


@bp.route("/shops/<shop_id>/projects/<project_id>/build-jobs/<build_job_id>/cancel", methods=["POST"])
def cancel_build_job(shop_id, project_id, build_job_id):
    _, role = get_user_context()
    require_role(role, {"ShopManager", "ShopAdmin"})
    get_project_in_shop(shop_id, project_id)
    b = get_build_job_in_project(shop_id, project_id, build_job_id)
    if b["status"] != "SCHEDULED":
        raise err("ERR_INVALID_STATE", "Build job is not SCHEDULED")
    b["status"] = "CANCELLED"
    touch(b)
    return success(serialize_build_job(b), 200)
