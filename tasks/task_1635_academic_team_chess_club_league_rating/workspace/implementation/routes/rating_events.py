from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES
from response import success_object, success_array, paginate
from services.common import get_or_404
from services.serializers import rating_event_json

bp = Blueprint("rating_events", __name__)

READ = ALL_ROLES


@bp.route("/api/rating-events", methods=["GET"])
@require_roles(*READ)
def list_rating_events():
    items = list(store.rating_events.values())
    for param, field in (("player_id", "player_id"),
                         ("pairing_id", "pairing_id"),
                         ("season_id", "season_id"), ("status", "status")):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[field] == v]
    page, limit, offset, total = paginate(items, request.args)
    return success_array([rating_event_json(e) for e in page], 200,
                         paginated=True, limit=limit, offset=offset,
                         total_count=total)


@bp.route("/api/rating-events/<ratingEventId>", methods=["GET"])
@require_roles(*READ)
def get_rating_event(ratingEventId):
    e = get_or_404(store.rating_events, ratingEventId, "rating event")
    return success_object(rating_event_json(e), 200)
