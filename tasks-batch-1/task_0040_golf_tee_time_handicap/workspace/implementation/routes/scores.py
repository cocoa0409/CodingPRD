from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import score_out
from util import new_uuid, now_iso, round_half_up
from services.handicap import compute_provisional
import validate as V
from decimal import Decimal
import re

bp = Blueprint("scores", __name__)

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


@bp.route("/golf/scores", methods=["POST"])
def create_score():
    require_auth({"ProShop", "Golfer"})
    data = V.require_body(request.get_json(silent=True))

    golfer_id = V.require_present(data, "golfer_id")
    course_id = V.require_present(data, "course_id")
    played_on = V.require_present(data, "played_on")
    ags = V.require_present(data, "adjusted_gross_score")

    # existence (priority 3) before field range validation (priority 13)
    golfer = db.golfers.get(golfer_id)
    if not golfer:
        raise errors.not_found("Golfer not found.")
    course = db.courses.get(course_id)
    if not course:
        raise errors.not_found("Course not found.")

    # field validation
    played_on = V.as_str(played_on, "played_on")
    if not DATE_RE.match(played_on):
        raise errors.validation("played_on must be YYYY-MM-DD.")
    ags = V.as_int(ags, "adjusted_gross_score")
    V.in_range_num(ags, "adjusted_gross_score", 50, 150)

    # compute score_differential = round_half_up((113/slope)*(ags - rating), 1)
    slope = Decimal(str(course["slope_rating"]))
    rating = Decimal(str(course["course_rating"]))
    diff = round_half_up((Decimal(113) / slope) * (Decimal(ags) - rating), 1)

    ts = now_iso()
    s = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "golfer_id": golfer_id,
        "course_id": course_id,
        "played_on": played_on,
        "adjusted_gross_score": ags,
        "score_differential": float(diff),
        "status": "POSTED",
        "counted_in_revision": 0,
    }
    db.scores[s["id"]] = s

    # recompute provisional handicap index for the golfer
    golfer["provisional_handicap_index"] = compute_provisional(golfer_id, db)
    golfer["version"] += 1
    golfer["updated_at"] = ts

    return success_object(score_out(s), 201)


@bp.route("/golf/scores/<sid>", methods=["GET"])
def get_score(sid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    s = db.scores.get(sid)
    if not s:
        raise errors.not_found("Score not found.")
    return success_object(score_out(s), 200)


@bp.route("/golf/scores", methods=["GET"])
def list_scores():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    golfer_id = request.args.get("golfer_id")
    course_id = request.args.get("course_id")
    items = list(db.scores.values())
    if golfer_id is not None:
        items = [s for s in items if s["golfer_id"] == golfer_id]
    if course_id is not None:
        items = [s for s in items if s["course_id"] == course_id]
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([score_out(s) for s in page], limit, offset, total, 200)


@bp.route("/golf/scores/<sid>/void", methods=["POST"])
def void_score(sid):
    require_auth({"ProShop"})
    s = db.scores.get(sid)
    if not s:
        raise errors.not_found("Score not found.")
    if s["status"] != "POSTED":
        raise errors.invalid_state("Score is not in POSTED status.")

    ts = now_iso()
    s["status"] = "VOID"
    s["updated_at"] = ts
    s["version"] += 1

    golfer = db.golfers.get(s["golfer_id"])
    if golfer:
        golfer["provisional_handicap_index"] = compute_provisional(s["golfer_id"], db)
        golfer["version"] += 1
        golfer["updated_at"] = ts

    return success_object(score_out(s), 200)
