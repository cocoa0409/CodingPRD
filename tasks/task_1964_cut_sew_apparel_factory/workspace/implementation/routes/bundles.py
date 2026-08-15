"""Bundle endpoints (PRD §3.6)."""

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_LINE_SUPERVISOR
from response import success_object
from util import get_body
from errors import invalid_state, bundle_not_releasable, trim_hold_active
from services.core import public, get_bundle, get_production_order
from services.core import touch
from routes.common import list_response, active_filters

bp = Blueprint("bundles", __name__)


@bp.route("/bundles", methods=["GET"])
def list_bundles():
    require_roles(ALL_ROLES)
    filters = active_filters([
        ("marker_id", request.args.get("marker_id")),
        ("production_order_id", request.args.get("production_order_id")),
    ])
    return list_response(store.bundles.values(), filters)


@bp.route("/bundles/<bundle_id>", methods=["GET"])
def get_bundle_endpoint(bundle_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_bundle(bundle_id)))


@bp.route("/bundles/<bundle_id>/release", methods=["POST"])
def release_bundle(bundle_id):
    require_roles([ROLE_LINE_SUPERVISOR])
    get_body()
    bundle = get_bundle(bundle_id)
    if bundle["status"] != "TICKETED":
        raise bundle_not_releasable("bundle must be TICKETED to release")
    order = get_production_order(bundle["production_order_id"])
    if order["production_status"] not in ("CUTTING", "SEWING"):
        raise invalid_state(
            "the bundle's order must be CUTTING or SEWING to release")
    if order["trim_hold_status"] != "MATERIALS_OK":
        raise trim_hold_active("order is on TRIM_HOLD")
    bundle["status"] = "RELEASED"
    touch(bundle)
    # First release moves the order CUTTING -> SEWING (PRD §3.6).
    if order["production_status"] == "CUTTING":
        order["production_status"] = "SEWING"
        touch(order)
    return success_object(public(bundle))
