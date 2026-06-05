from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import tee_time_out
from util import new_uuid, now_iso, parse_iso
import validate as V

bp = Blueprint("tee_times", __name__)

TEE_INTERVAL_MINUTES = 8


@bp.route("/golf/tee-times", methods=["POST"])
def create_tee_time():
    require_auth({"ProShop"})
    data = V.require_body(request.get_json(silent=True))

    course_id = V.require_present(data, "course_id")
    start_utc = V.require_present(data, "start_utc")
    local_hour = V.require_present(data, "local_hour")
    group_type = V.require_present(data, "group_type")

    # existence before field validation
    course = db.courses.get(course_id)
    if not course:
        raise errors.not_found("Course not found.")

    start_utc = V.as_str(start_utc, "start_utc")
    try:
        start_dt = parse_iso(start_utc)
    except Exception:
        raise errors.validation("start_utc must be ISO 8601.")
    local_hour = V.as_int(local_hour, "local_hour")
    V.in_range_num(local_hour, "local_hour", 0, 23)
    if group_type not in ("TWOSOME", "FOURSOME"):
        raise errors.validation("group_type must be TWOSOME or FOURSOME.")

    # tee-sheet spacing: at least TEE_INTERVAL_MINUTES from every non-CLOSED tee time
    # on the same course (symmetric buffer; exactly 8 min apart allowed).
    for existing in db.tee_times.values():
        if existing["course_id"] != course_id:
            continue
        if existing["status"] == "CLOSED":
            continue
        ex_dt = parse_iso(existing["start_utc"])
        delta_min = abs((start_dt - ex_dt).total_seconds()) / 60.0
        if delta_min < TEE_INTERVAL_MINUTES:
            raise errors.ApiError(
                errors.ERR_TEE_INTERVAL_CONFLICT, 409,
                "Tee time too close to an existing tee time on this course.")

    capacity = 2 if group_type == "TWOSOME" else 4
    ts = now_iso()
    t = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "course_id": course_id,
        "start_utc": start_utc,
        "local_hour": local_hour,
        "group_type": group_type,
        "capacity": capacity,
        "confirmed_count": 0,
        "status": "OPEN",
    }
    db.tee_times[t["id"]] = t
    return success_object(tee_time_out(t), 201)


@bp.route("/golf/tee-times/<tid>", methods=["GET"])
def get_tee_time(tid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    t = db.tee_times.get(tid)
    if not t:
        raise errors.not_found("Tee time not found.")
    return success_object(tee_time_out(t), 200)


@bp.route("/golf/tee-times", methods=["GET"])
def list_tee_times():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    course_id = request.args.get("course_id")
    status = request.args.get("status")
    items = list(db.tee_times.values())
    if course_id is not None:
        items = [t for t in items if t["course_id"] == course_id]
    if status is not None:
        items = [t for t in items if t["status"] == status]
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([tee_time_out(t) for t in page], limit, offset, total, 200)


@bp.route("/golf/tee-times/<tid>/close", methods=["POST"])
def close_tee_time(tid):
    require_auth({"ProShop"})
    t = db.tee_times.get(tid)
    if not t:
        raise errors.not_found("Tee time not found.")
    if t["status"] != "OPEN":
        raise errors.invalid_state("Tee time must be OPEN to close.")
    t["status"] = "CLOSED"
    t["updated_at"] = now_iso()
    t["version"] += 1
    return success_object(tee_time_out(t), 200)
