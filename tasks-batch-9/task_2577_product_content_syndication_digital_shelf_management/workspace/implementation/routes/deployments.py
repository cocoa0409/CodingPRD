"""Enhanced-content deployment windows (PRD 3.8)."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (deployment_out, get_change_request, get_deployment, get_listing,
                      get_media_asset)
from errors import ApiError
from store import base_row, db, in_order, now, touch

bp = Blueprint("deployments", __name__)

MODULE_KINDS = ("A_PLUS_PAGE", "COMPARISON_CHART", "VIDEO_BLOCK")
DECISIONS = ("APPROVE", "REJECT")


def _half_open_intersect(a_start, a_end, b_start, b_end):
    """Half-open [start, end): touching endpoints do NOT intersect (PRD 3.8)."""
    return a_start < b_end and b_start < a_end


def _target_version_of(change_request):
    if change_request is None:
        return None
    return db.content_versions.get(change_request.get("target_content_version_id"))


@bp.route("/enhanced-deployments", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_deployment():
    data = validate.body()
    listing_id = validate.req_str(data, "retailer_listing_id", 1)
    change_request_id = validate.req_str(data, "change_request_id", 1)
    media_asset_id = validate.req_str(data, "media_asset_id", 1)
    module_kind = validate.req_enum(data, "module_kind", MODULE_KINDS)
    window_start = validate.window_dt(data, "window_start")
    window_end = validate.window_dt(data, "window_end")
    expected_listing_version = validate.req_int(data, "expected_retailer_listing_version")
    if window_end <= window_start:
        raise ApiError("ERR_WINDOW_INVALID")
    listing = get_listing(listing_id)
    asset = get_media_asset(media_asset_id)
    change_request = get_change_request(change_request_id)
    if expected_listing_version != listing["version"]:
        raise ApiError("ERR_STALE_VERSION")
    retailer = db.retailers.get(listing["retailer_id"])
    if retailer is None:
        raise ApiError("ERR_RETAILER_NOT_FOUND")
    if retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    if listing["shelf_state"] in ("SUSPENDED", "UNAUTHORIZED"):
        raise ApiError("ERR_LISTING_SHELF_BLOCKED")
    if change_request["state"] != "APPROVED":
        raise ApiError("ERR_CHANGE_REQUEST_NOT_APPROVED")
    if (change_request["retailer_id"] != listing["retailer_id"]
            or change_request["product_id"] != listing["product_id"]
            or asset["product_id"] != listing["product_id"]):
        raise ApiError("ERR_DEPLOYMENT_SCOPE_MISMATCH")
    if asset["approval_state"] != "APPROVED":
        raise ApiError("ERR_MEDIA_ASSET_NOT_APPROVED")
    if calc.approved_image_count(listing["product_id"]) < int(retailer["min_image_count"]):
        raise ApiError("ERR_IMAGE_COUNT_BELOW_MINIMUM")
    for other in calc.deployments_of_listing(listing["id"]):
        if other["state"] not in calc.ACTIVE_DEPLOYMENT_STATES:
            continue
        if _half_open_intersect(window_start, window_end,
                                other["window_start"], other["window_end"]):
            raise ApiError("ERR_DEPLOYMENT_WINDOW_OVERLAP")

    live_immediately = not retailer["enhanced_content_requires_approval"]
    deployment = base_row()
    deployment.update({
        "retailer_listing_id": listing["id"],
        "change_request_id": change_request["id"],
        "media_asset_id": asset["id"],
        "module_kind": module_kind,
        "window_start": window_start,
        "window_end": window_end,
        "state": "LIVE" if live_immediately else "PENDING_RETAILER_APPROVAL",
        "retailer_decision_at": None,
        "withdrawn_reason": None,
    })
    db.deployments[deployment["id"]] = deployment
    touch(listing)
    recompute.recompute_pin_count(_target_version_of(change_request))
    if live_immediately:
        recompute.recompute_listing_readiness(listing)
        product = db.products.get(listing["product_id"])
        if product is not None:
            recompute.recompute_product_health(product)
    return envelope.created(deployment_out(deployment))


@bp.route("/enhanced-deployments/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_deployment(row_id):
    return envelope.ok(deployment_out(get_deployment(row_id)))


@bp.route("/enhanced-deployments", methods=["GET"])
@endpoint(ALL_ROLES)
def list_deployments():
    limit, offset = envelope.page_params()
    rows = in_order(list(db.deployments.values()))
    for arg in ("retailer_listing_id", "change_request_id", "media_asset_id", "state"):
        value = request.args.get(arg)
        if value is not None:
            rows = [r for r in rows if r.get(arg) == value]
    return envelope.paged_with(rows, deployment_out, limit, offset)


@bp.route("/enhanced-deployments/<row_id>/retailer-decision", methods=["POST"])
@endpoint(["RetailerIntegration"])
def decide_deployment(row_id):
    deployment = get_deployment(row_id)
    listing = db.listings.get(deployment["retailer_listing_id"])
    if listing is None or listing["retailer_id"] != g.user_id:
        raise ApiError("ERR_RETAILER_SCOPE_VIOLATION")
    data = validate.body()
    decision = validate.req_enum(data, "decision", DECISIONS)
    if deployment["state"] != "PENDING_RETAILER_APPROVAL":
        raise ApiError("ERR_DEPLOYMENT_NOT_ACTIVE")
    deployment["state"] = "LIVE" if decision == "APPROVE" else "REJECTED"
    deployment["retailer_decision_at"] = now()
    touch(deployment)
    touch(listing)
    product = db.products.get(listing["product_id"])
    if decision == "APPROVE":
        recompute.recompute_listing_readiness(listing)
        if product is not None:
            recompute.recompute_product_health(product)
    else:
        # The reference is gone; the placement window is freed for another deployment.
        recompute.recompute_pin_count(
            _target_version_of(db.change_requests.get(deployment["change_request_id"])))
    return envelope.ok(deployment_out(deployment))


@bp.route("/enhanced-deployments/<row_id>/withdraw", methods=["POST"])
@endpoint(["ContentAuthor"])
def withdraw_deployment(row_id):
    data = validate.body()
    reason = validate.opt_str(data, "withdrawn_reason", 1)
    deployment = get_deployment(row_id)
    if deployment["state"] not in calc.ACTIVE_DEPLOYMENT_STATES:
        raise ApiError("ERR_DEPLOYMENT_NOT_ACTIVE")
    deployment["state"] = "WITHDRAWN"
    deployment["withdrawn_reason"] = reason
    touch(deployment)
    listing = db.listings.get(deployment["retailer_listing_id"])
    recompute.recompute_pin_count(
        _target_version_of(db.change_requests.get(deployment["change_request_id"])))
    if listing is not None:
        touch(listing)
        recompute.recompute_listing_readiness(listing)
        product = db.products.get(listing["product_id"])
        if product is not None:
            recompute.recompute_product_health(product)
    return envelope.ok(deployment_out(deployment))
