"""AssetBundle endpoints."""

from flask import Blueprint, request

from db import store
from errors import not_found
from middleware import require_roles
from response import success_object, success_list, parse_pagination
from serializers import bundle_json
from services.domain import sweep_clock

bp = Blueprint("asset_bundles", __name__)


def _get_booking_or_404(booking_id):
    b = store.bookings.get(booking_id)
    if not b:
        raise not_found("ShootBooking not found")
    return b


@bp.route("/shoot-bookings/<booking_id>/asset-bundles", methods=["GET"])
def list_bundles(booking_id):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    limit, offset = parse_pagination(request.args)
    items = sorted(
        (x for x in store.asset_bundles.values() if x["booking_id"] == b["id"]),
        key=lambda x: x["created_at"],
    )
    state = request.args.get("state")
    if state is not None:
        items = [x for x in items if x["state"] == state]
    total = len(items)
    page = items[offset:offset + limit]
    return success_list([bundle_json(x) for x in page], limit, offset, total)


@bp.route("/shoot-bookings/<booking_id>/asset-bundles/<bundleId>", methods=["GET"])
def get_bundle(booking_id, bundleId):
    require_roles("ClientAgent", "Photographer", "Coordinator", "OpsAdmin")
    sweep_clock()
    b = _get_booking_or_404(booking_id)
    x = store.asset_bundles.get(bundleId)
    if not x or x["booking_id"] != b["id"]:
        raise not_found("AssetBundle not found")
    return success_object(bundle_json(x))
