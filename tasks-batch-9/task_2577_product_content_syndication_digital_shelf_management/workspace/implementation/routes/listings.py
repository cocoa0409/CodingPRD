"""Retailer listings, the completeness diagnostic, crawl observations and shelf status."""
from flask import Blueprint, g, request

import calc
import envelope
import recompute
import validate
from auth import ALL_ROLES, endpoint
from entities import (get_listing, get_product, get_retailer, listing_out, observation_out)
from errors import ApiError
from store import base_row, db, event_row, in_order, touch

bp = Blueprint("listings", __name__)

SYNDICATION_STATES = ("NOT_SYNDICATED", "PENDING", "LIVE", "ERROR_HOLD")
SHELF_STATES = ("OK", "OOS_WATCH", "UNAUTHORIZED", "SUSPENDED")
SHELF_STATUS_TARGETS = ("SUSPENDED", "OK")


@bp.route("/retailer-listings", methods=["POST"])
@endpoint(["ContentAuthor"])
def create_listing():
    data = validate.body()
    product_id = validate.req_str(data, "product_id", 1)
    retailer_id = validate.req_str(data, "retailer_id", 1)
    account_team_user_id = validate.opt_str(data, "account_team_user_id", 1)
    retailer = get_retailer(retailer_id)
    product = get_product(product_id)
    if calc.find_listing(product["id"], retailer["id"]) is not None:
        raise ApiError("ERR_DUPLICATE_LISTING")
    if retailer["status"] != "ACTIVE":
        raise ApiError("ERR_RETAILER_NOT_ACTIVE")
    listing = base_row()
    listing.update({
        "product_id": product["id"],
        "retailer_id": retailer["id"],
        "pinned_content_version_id": None,
        "account_team_user_id": account_team_user_id,
        "syndication_state": "NOT_SYNDICATED",
        "shelf_state": "OK",
        "completeness_score_declared": calc.ZERO2,
        "completeness_score_certified": calc.ZERO2,
        "readiness_score": calc.ZERO2,
        "search_rank_latest": None,
        "content_accuracy_pct": None,
        "rating_avg": None,
        "in_stock": True,
        "open_blocking_error_count": 0,
    })
    db.listings[listing["id"]] = listing
    recompute.recompute_listing_completeness(listing)
    return envelope.created(listing_out(listing))


@bp.route("/retailer-listings/<row_id>", methods=["GET"])
@endpoint(ALL_ROLES)
def read_listing(row_id):
    return envelope.ok(listing_out(get_listing(row_id)))


@bp.route("/retailer-listings", methods=["GET"])
@endpoint(ALL_ROLES)
def list_listings():
    limit, offset = envelope.page_params()
    filters = (
        ("product_id", "product_id"),
        ("retailer_id", "retailer_id"),
        ("pinned_content_version_id", "pinned_content_version_id"),
        ("syndication_state", "syndication_state"),
        ("shelf_state", "shelf_state"),
    )
    rows = in_order(list(db.listings.values()))
    for arg, field in filters:
        value = request.args.get(arg)
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    return envelope.paged_with(rows, listing_out, limit, offset)


@bp.route("/retailer-listings/<row_id>/completeness", methods=["GET"])
@endpoint(ALL_ROLES)
def listing_completeness(row_id):
    listing = get_listing(row_id)
    detail = calc.completeness_detail(listing)
    return envelope.ok({
        "retailer_listing_id": listing["id"],
        "declared_score": detail["declared_score"],
        "certified_score": detail["certified_score"],
        "declared_source_content_version_id": detail["declared_source_content_version_id"],
        "certified_source_content_version_id": detail["certified_source_content_version_id"],
        "requirement_weight_total": detail["requirement_weight_total"],
        "missing_required_keys": detail["missing_required_keys"],
        "over_limit_keys": detail["over_limit_keys"],
        "declared_image_component": detail["declared_image_component"],
        "certified_image_component": detail["certified_image_component"],
    })


# --------------------------------------------------------------- observations
@bp.route("/retailer-listings/<row_id>/observations", methods=["POST"])
@endpoint(["ShelfAdmin"])
def ingest_observation(row_id):
    data = validate.body()
    observed_at = validate.req_dt(data, "observed_at")
    in_stock = validate.req_bool(data, "in_stock")
    accuracy = validate.req_num(data, "content_accuracy_pct", 0, 100)
    rating_avg = validate.req_num(data, "rating_avg", 0, 5)
    rating_count = validate.req_int(data, "rating_count", 0)
    unauthorized = validate.req_int(data, "unauthorized_seller_count", 0)
    conversion = validate.req_num(data, "conversion_rate_pct", 0, 100)
    units_sold = validate.req_int(data, "units_sold", 0)
    search_rank = validate.opt_int(data, "search_rank", 1)
    listing = get_listing(row_id)

    observation = event_row()
    observation.update({
        "retailer_listing_id": listing["id"],
        "observed_at": observed_at,
        "search_rank": search_rank,
        "in_stock": in_stock,
        "content_accuracy_pct": accuracy,
        "rating_avg": rating_avg,
        "rating_count": rating_count,
        "unauthorized_seller_count": unauthorized,
        "conversion_rate_pct": conversion,
        "units_sold": units_sold,
    })
    db.observations[observation["id"]] = observation

    # Hop 1 -- re-project the shelf snapshot from the observation log.
    recompute.recompute_listing_projection(listing)

    # Hop 2 -- re-derive shelf_state under SUSPENDED > UNAUTHORIZED > OOS_WATCH > OK
    # and raise the monitoring alerts keyed on the ingested observation.
    current = listing["shelf_state"]
    if current != "SUSPENDED":
        if unauthorized >= 1:
            recompute.set_shelf_state(listing, "UNAUTHORIZED")
            recompute.raise_alert(listing, "UNAUTHORIZED_LISTING", observation["id"])
        elif not in_stock:
            if current == "OK":
                recompute.set_shelf_state(listing, "OOS_WATCH")
                recompute.raise_alert(listing, "OUT_OF_STOCK", observation["id"])
        else:
            if current == "OOS_WATCH":
                recompute.set_shelf_state(listing, "OK")
                recompute.auto_resolve_alerts(listing, "OUT_OF_STOCK",
                                              "AUTO_CLEARED_BY_OBSERVATION")
    if accuracy < calc.CONTENT_DRIFT_THRESHOLD:
        recompute.raise_alert(listing, "CONTENT_DRIFT", observation["id"])

    # Hop 3/4 -- scores, the health-degraded rule and the product roll-up.
    product = db.products.get(listing["product_id"])
    recompute.recompute_listing_readiness(listing)
    if product is not None:
        recompute.recompute_product_health(product)
        recompute.maybe_health_degraded(listing, product)
        recompute.recompute_product_lift(product)
        recompute.recompute_product_alerts(product)
        touch(product)
    return envelope.created(observation_out(observation))


@bp.route("/retailer-listings/<row_id>/observations", methods=["GET"])
@endpoint(ALL_ROLES)
def list_observations(row_id):
    limit, offset = envelope.page_params()
    listing = get_listing(row_id)
    rows = calc.observations_of_listing(listing["id"])
    return envelope.paged_with(rows, observation_out, limit, offset)


# -------------------------------------------------------------- shelf status
@bp.route("/retailer-listings/<row_id>/shelf-status", methods=["POST"])
@endpoint(["AccountTeamLead"])
def shelf_status(row_id):
    data = validate.body()
    target = validate.req_enum(data, "shelf_state", SHELF_STATUS_TARGETS)
    listing = get_listing(row_id)
    product = db.products.get(listing["product_id"])
    if target == "OK":
        recompute.set_shelf_state(listing, "OK")
        recompute.auto_resolve_alerts(listing, "UNAUTHORIZED_LISTING",
                                      "AUTO_CLEARED_BY_ACCOUNT_TEAM")
        recompute.recompute_listing_readiness(listing)
        if product is not None:
            recompute.recompute_product_alerts(product)
            touch(product)
    else:
        recompute.set_shelf_state(listing, "SUSPENDED")
        recompute.recompute_listing_readiness(listing)
    return envelope.ok(listing_out(listing))
