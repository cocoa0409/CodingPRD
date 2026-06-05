from flask import Blueprint, request
import errors
from db import db
from middleware import require_auth
from response import success_object, success_array
from pagination import parse_pagination, paginate
from serializers import golfer_out
from util import new_uuid, now_iso
import validate as V

bp = Blueprint("golfers", __name__)


@bp.route("/golf/golfers", methods=["POST"])
def create_golfer():
    require_auth({"ProShop", "Anonymous"})
    data = V.require_body(request.get_json(silent=True))

    full_name = V.as_str(V.require_present(data, "full_name"), "full_name")
    tier = data.get("membership_tier", "PUBLIC")
    if tier is None:
        tier = "PUBLIC"
    if tier not in ("MEMBER", "PUBLIC"):
        raise errors.validation("membership_tier must be MEMBER or PUBLIC.")

    ts = now_iso()
    g = {
        "id": new_uuid(),
        "_seq": db.next_seq(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "full_name": full_name,
        "membership_tier": tier,
        "handicap_index": None,
        "provisional_handicap_index": None,
        "handicap_revision": 0,
        "low_handicap_index": None,
        "_index_history": [],  # list of (effective_iso, official_index) for trailing-365 low
    }
    db.golfers[g["id"]] = g
    return success_object(golfer_out(g), 201)


@bp.route("/golf/golfers/<gid>", methods=["GET"])
def get_golfer(gid):
    require_auth({"ProShop", "Golfer", "Anonymous"})
    g = db.golfers.get(gid)
    if not g:
        raise errors.not_found("Golfer not found.")
    return success_object(golfer_out(g), 200)


@bp.route("/golf/golfers", methods=["GET"])
def list_golfers():
    require_auth({"ProShop", "Golfer", "Anonymous"})
    limit, offset = parse_pagination()
    tier = request.args.get("membership_tier")
    items = list(db.golfers.values())
    if tier is not None:
        items = [g for g in items if g["membership_tier"] == tier]
    items = sorted(items, key=lambda x: (x["created_at"], x["_seq"]))
    total = len(items)
    page = paginate(items, limit, offset)
    return success_array([golfer_out(g) for g in page], limit, offset, total, 200)
