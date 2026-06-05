from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import course_out
from util import new_uuid, now_iso
import validate as V

bp = Blueprint("courses", __name__)


@bp.route("/golf/courses", methods=["POST"])
def create_course():
    require_auth({"ProShop"})
    data = V.require_body(request.get_json(silent=True))

    name = V.as_str(V.require_present(data, "name"), "name")
    course_rating = V.as_number(V.require_present(data, "course_rating"), "course_rating")
    V.in_range_num(course_rating, "course_rating", 55.0, 85.0)
    slope_rating = V.as_int(V.require_present(data, "slope_rating"), "slope_rating")
    V.in_range_num(slope_rating, "slope_rating", 55, 155)
    peak_fee = V.as_int(V.require_present(data, "peak_fee_cents"), "peak_fee_cents")
    V.in_range_num(peak_fee, "peak_fee_cents", 0, float("inf"))
    offpeak_fee = V.as_int(V.require_present(data, "offpeak_fee_cents"), "offpeak_fee_cents")
    V.in_range_num(offpeak_fee, "offpeak_fee_cents", 0, float("inf"))

    peak_start = data.get("peak_start_hour", 7)
    peak_start = V.as_int(peak_start, "peak_start_hour")
    V.in_range_num(peak_start, "peak_start_hour", 0, 23)
    peak_end = data.get("peak_end_hour", 15)
    peak_end = V.as_int(peak_end, "peak_end_hour")
    V.in_range_num(peak_end, "peak_end_hour", 0, 23)
    if not (peak_end > peak_start):
        raise errors.validation("peak_end_hour must be strictly greater than peak_start_hour.")

    discount = data.get("member_discount_pct", 0.20)
    discount = V.as_number(discount, "member_discount_pct")
    V.in_range_num(discount, "member_discount_pct", 0.0, 1.0)

    ts = now_iso()
    c = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "name": name,
        "course_rating": course_rating,
        "slope_rating": slope_rating,
        "peak_fee_cents": peak_fee,
        "offpeak_fee_cents": offpeak_fee,
        "peak_start_hour": peak_start,
        "peak_end_hour": peak_end,
        "member_discount_pct": discount,
    }
    db.courses[c["id"]] = c
    return success_object(course_out(c), 201)


@bp.route("/golf/courses/<cid>", methods=["GET"])
def get_course(cid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    c = db.courses.get(cid)
    if not c:
        raise errors.not_found("Course not found.")
    return success_object(course_out(c), 200)


@bp.route("/golf/courses", methods=["GET"])
def list_courses():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    items = sorted(db.courses.values(), key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([course_out(c) for c in page], limit, offset, total, 200)
