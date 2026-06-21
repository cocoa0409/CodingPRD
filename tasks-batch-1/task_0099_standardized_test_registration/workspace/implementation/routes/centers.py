"""TestCenter routes."""
from flask import Blueprint

from db import store, stamp_create
from errors import err, ERR_INVALID_REQUEST
from middleware import require_roles
from response import object_response
from services import lookups, serializers
from services.common import get_json_body, require_fields

bp = Blueprint("centers", __name__)


@bp.route("/test-centers", methods=["POST"])
@require_roles("TestCenterAdmin")
def create_center():
    body = get_json_body()
    require_fields(body, ["name", "state_code", "room_capacity_standard",
                          "room_capacity_accommodated"])

    name = body["name"]
    state_code = body["state_code"]
    rcs = body["room_capacity_standard"]
    rca = body["room_capacity_accommodated"]

    if not isinstance(name, str) or not isinstance(state_code, str):
        raise err(ERR_INVALID_REQUEST, "name and state_code must be strings")
    if not isinstance(rcs, int) or isinstance(rcs, bool) or rcs < 0:
        raise err(ERR_INVALID_REQUEST, "room_capacity_standard must be a non-negative integer")
    if not isinstance(rca, int) or isinstance(rca, bool) or rca < 0:
        raise err(ERR_INVALID_REQUEST, "room_capacity_accommodated must be a non-negative integer")

    center = {
        "name": name,
        "state_code": state_code,
        "room_capacity_standard": rcs,
        "room_capacity_accommodated": rca,
        "net_revenue_cents": 0,
    }
    stamp_create(center)
    store.test_centers[center["id"]] = center
    return object_response(serializers.test_center(center), 201)


@bp.route("/test-centers/<cid>", methods=["GET"])
@require_roles("TestCenterAdmin", "Candidate", "ScoreOps", "AccommodationReviewer")
def get_center(cid):
    center = lookups.test_center(cid)
    return object_response(serializers.test_center(center), 200)
