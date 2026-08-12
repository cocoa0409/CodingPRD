"""Index downgrade notifications."""
from flask import Blueprint, request

from db import store, touch, serialize
from errors import (
    ApiError, ERR_NOTIFICATION_NOT_FOUND, ERR_NOTIFICATION_NOT_ACKNOWLEDGEABLE,
)
from middleware import require, ALL_ROLES
from response import success, paginated

bp = Blueprint("notifications", __name__)


def get_notification_or_404(nid):
    n = store.notifications.get(nid)
    if n is None:
        raise ApiError(ERR_NOTIFICATION_NOT_FOUND, 404,
                       "Index downgrade notification id does not exist")
    return n


@bp.get("/arff/index-downgrade-notifications")
def list_notifications():
    require(ALL_ROLES)
    items = list(store.notifications.values())
    status = request.args.get("status")
    if status is not None:
        items = [n for n in items if n["status"] == status]
    return paginated(items)


@bp.get("/arff/index-downgrade-notifications/<nid>")
def get_notification(nid):
    require(ALL_ROLES)
    return success(serialize(get_notification_or_404(nid)), "object", 200)


@bp.post("/arff/index-downgrade-notifications/<nid>/acknowledge")
def acknowledge_notification(nid):
    require(["FaaInspector"])
    n = get_notification_or_404(nid)
    if n["status"] not in ("PENDING", "OVERDUE"):
        raise ApiError(ERR_NOTIFICATION_NOT_ACKNOWLEDGEABLE, 409,
                       "Notification must be PENDING or OVERDUE to acknowledge")
    n["status"] = "ACKNOWLEDGED"
    touch(n)
    return success(serialize(n), "object", 200)
