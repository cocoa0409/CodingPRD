"""Feed call endpoints."""
from flask import Blueprint

import store
from auth import authenticate, authorize
from errors import ERR_PEN_NOT_FOUND, ERR_INVALID_REQUEST, raise_err
from serializers import feed_call_out
from services import feed_service
from util import body_json, get_or_404, req_str, req_date, opt_int, opt_number, \
    success_object

bp = Blueprint("feed_calls", __name__)


@bp.route("/feedlot/feed-calls", methods=["POST"])
def create_feed_call():
    _, role = authenticate()
    authorize(role, ["FeedManager"])
    body = body_json()

    pen_id = req_str(body, "pen_id")
    call_date = req_date(body, "call_date")
    bunk_score = opt_int(body, "bunk_score")
    base_qty_lbs_per_head = opt_number(body, "base_qty_lbs_per_head")

    # Validate pen exists
    pen = store.pens.get(pen_id)
    if pen is None:
        raise_err(ERR_PEN_NOT_FOUND, "Pen not found: %s" % pen_id)

    # Create feed call (service handles all business logic)
    rec = feed_service.create_feed_call(
        pen_id, call_date, bunk_score, base_qty_lbs_per_head
    )
    return success_object(feed_call_out(rec), 201)
