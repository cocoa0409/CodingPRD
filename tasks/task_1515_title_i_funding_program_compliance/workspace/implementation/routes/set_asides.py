"""SetAside endpoints."""

from flask import Blueprint

import db
import errors
import middleware
import response
import validators as V
from services import calc, serializers

bp = Blueprint("set_asides", __name__)

ALL_ROLES = middleware.ROLES


def get_set_aside_or_404(set_aside_id):
    sa = db.set_asides.get(set_aside_id)
    if sa is None:
        errors.fail(errors.ERR_NOT_FOUND, "Set-aside %s does not exist." % set_aside_id)
    return sa


@bp.get("/set-asides")
def list_set_asides():
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    filters = [
        ("grant_id", V.query_filter("grant_id")),
        ("category", V.query_filter("category")),
    ]
    page, limit, offset, total = V.sorted_page(list(db.set_asides.values()), filters)
    return response.success_list(
        [serializers.set_aside_view(s) for s in page], limit, offset, total
    )


@bp.get("/set-asides/<set_aside_id>")
def get_set_aside(set_aside_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, ALL_ROLES)
    return response.success_object(serializers.set_aside_view(get_set_aside_or_404(set_aside_id)))


@bp.post("/set-asides/<set_aside_id>/adjust")
def adjust_set_aside(set_aside_id):
    _uid, role = middleware.current_user()
    middleware.require_role(role, {"FederalProgramsDirector"})
    sa = get_set_aside_or_404(set_aside_id)
    data = V.json_body()
    V.check_unknown(data, {"reserved_cents"})
    reserved = V.req_int(data, "reserved_cents")
    if reserved < 0:
        errors.fail(errors.ERR_INVALID_REQUEST, "reserved_cents must be >= 0.")
    # Tier 11: the floor.
    if reserved < sa["minimum_cents"]:
        errors.fail(
            errors.ERR_SET_ASIDE_BELOW_MINIMUM,
            "reserved_cents would drop below minimum_cents.",
        )
    sa["reserved_cents"] = reserved
    if sa["category"] == "PARENT_ENGAGEMENT":
        sa["school_distributed_minimum_cents"] = calc.pe_school_distributed_minimum(reserved)
    db.touch(sa)
    grant = db.grants[sa["grant_id"]]
    db.touch(grant)
    return response.success_object(serializers.set_aside_view(sa))
