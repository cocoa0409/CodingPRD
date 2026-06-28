from flask import Blueprint

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_int, opt_int, check_range,
    get_or_404, make_entity,
)
from response import success

bp = Blueprint("counselors", __name__)


def _serialize(c):
    return {
        "id": c["id"],
        "full_name": c["full_name"],
        "email": c["email"],
        "hourly_rate_cents": c["hourly_rate_cents"],
        "weekly_review_capacity": c["weekly_review_capacity"],
        "created_at": c["created_at"],
        "updated_at": c["updated_at"],
        "version": c["version"],
    }


@bp.route("/counselors", methods=["POST"])
def create_counselor():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Counselor"})
    body = get_json_body()
    full_name = require_string(body, "full_name")
    email = require_string(body, "email")
    hourly_rate_cents = require_int(body, "hourly_rate_cents")
    check_range(hourly_rate_cents, "hourly_rate_cents", lo=0, lo_inclusive=False)
    weekly_review_capacity = opt_int(body, "weekly_review_capacity", 10)
    check_range(weekly_review_capacity, "weekly_review_capacity", lo=0)

    with store.lock:
        c = make_entity()
        c.update({
            "full_name": full_name,
            "email": email,
            "hourly_rate_cents": hourly_rate_cents,
            "weekly_review_capacity": weekly_review_capacity,
        })
        store.counselors[c["id"]] = c
        return success(_serialize(c), 201)


@bp.route("/counselors/<counselor_id>", methods=["GET"])
def get_counselor(counselor_id):
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin", "Counselor"})
    with store.lock:
        c = get_or_404(store.counselors, counselor_id)
        return success(_serialize(c))
