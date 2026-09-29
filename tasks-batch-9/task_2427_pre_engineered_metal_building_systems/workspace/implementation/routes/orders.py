"""PRD 3.8 / 3.9 -- order reads, release to fabrication, its compensation, erection sequence."""

from flask import Blueprint, request

import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, now_iso, ordered, touch

bp = Blueprint("orders", __name__)


@bp.route("/orders/<order_id>", methods=["GET"])
@roles_required(ANY)
def read_order(order_id):
    return object_response(S.order_out(domain.get_order(order_id)))


@bp.route("/orders", methods=["GET"])
@roles_required(ANY)
def list_orders():
    filters = (
        ("builder_id", "builder_id"),
        ("quote_id", "quote_id"),
        ("configuration_id", "configuration_id"),
        ("engineering_design_id", "engineering_design_id"),
        ("drawing_package_id", "drawing_package_id"),
        ("production_status", "production_status"),
    )
    supplied = [(field, request.args.get(param)) for param, field in filters]

    def predicate(row):
        for field, value in supplied:
            if value is not None and row[field] != value:
                return False
        return True

    return paginated(ordered(db.orders, predicate), S.order_out)


@bp.route("/orders/<order_id>/release-to-fabrication", methods=["POST"])
@roles_required("ProductionPlanner")
def release_to_fabrication(order_id):
    data = V.body()
    expected_version = V.get_int(data, "expected_order_version")

    order = domain.get_order(order_id)

    # Band 6.
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")

    builder = db.builders.get(order["builder_id"])
    if builder is None:
        raise ApiError("ERR_BUILDER_NOT_FOUND")

    # Band 8.
    if builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_BUILDER_NOT_AUTHORIZED")

    # Band 9.
    if order["production_status"] != "PROD_NOT_RELEASED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Band 10 -- one code guards four separate paperwork facts.
    package = db.drawing_packages.get(order["drawing_package_id"])
    if (
        order["engineering_status"] != "ENG_SEALED"
        or order["drawing_package_id"] is None
        or package is None
        or package["status"] != "SEALED"
        or order["permit_hold"]
        or order["commercial_hold"]
    ):
        raise ApiError("ERR_DRAWINGS_NOT_SEALED")

    config = db.configurations.get(order["configuration_id"])
    quote = db.quotes.get(order["quote_id"])
    design = db.designs.get(order["engineering_design_id"])
    jurisdiction = db.jurisdictions.get(config["jurisdiction_id"]) if config else None
    if config is None or quote is None or design is None or jurisdiction is None:
        raise ApiError("ERR_DRAWINGS_NOT_SEALED")

    kits = domain.kits_of_configuration(config["id"])
    priced = calc.quote_price_pipeline(
        "FINAL",
        config,
        builder,
        jurisdiction,
        kits,
        quote["freight_distance_miles"],
        quote["adjustment_cents"],
        design["frame_weight_lbs"],
    )
    final_price_cents = priced["price_cents"]
    price_delta_cents = final_price_cents - quote["quoted_price_cents"]

    # Band 15 -- a negative or zero delta always passes.
    if price_delta_cents > domain.credit_available(builder):
        raise ApiError("ERR_BUILDER_CREDIT_EXCEEDED")

    order["final_price_cents"] = final_price_cents
    order["price_delta_cents"] = price_delta_cents
    domain.move_credit(builder, price_delta_cents)
    touch(builder)

    total = calc.total_shippable_weight(design["shippable_weight_lbs"], kits)
    order["total_shippable_weight_lbs"] = total
    order["assigned_weight_lbs"] = calc.rhu(0, 2)
    order["unassigned_weight_lbs"] = total
    order["released_at"] = now_iso()
    domain.production_status_rollup(order)
    touch(order)

    return object_response(S.order_out(order))


@bp.route("/orders/<order_id>/cancel-release", methods=["POST"])
@roles_required("ProductionPlanner")
def cancel_release(order_id):
    data = V.body()
    expected_version = V.get_int(data, "expected_order_version")

    order = domain.get_order(order_id)

    # Band 6.
    if expected_version != order["version"]:
        raise ApiError("ERR_STALE_ORDER_VERSION")

    # Band 9 -- the release must still exist.  PRD 3.8 says in the same paragraph
    # both that "the order must be PROD_RELEASED, otherwise
    # ERR_INVALID_STATE_TRANSITION" and, of the active-work refusal, to "note that
    # a COMPLETE lot blocks cancellation just as a SCHEDULED one does".  A
    # SCHEDULED or COMPLETE lot always projects the order to PROD_IN_FABRICATION
    # or PROD_COMPLETE, so that note is reachable only if those two projections
    # satisfy this from-state and fall through to the active-work band below.
    # PROD_NOT_RELEASED (nothing to cancel) and PROD_HOLD do not, so the
    # from-state code stays reachable too.  Cancellation still only ever succeeds
    # on an order with no active work at all.
    if order["production_status"] not in (
        "PROD_RELEASED",
        "PROD_IN_FABRICATION",
        "PROD_COMPLETE",
    ):
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    # Band 10 -- a COMPLETE lot blocks just as a SCHEDULED one does.
    for lot in domain.lots_of_order(order["id"]):
        if lot["status"] in ("SCHEDULED", "COMPLETE"):
            raise ApiError("ERR_ORDER_HAS_ACTIVE_WORK")
    for load in domain.loads_of_order(order["id"]):
        if load["status"] in ("PLANNED", "DISPATCHED"):
            raise ApiError("ERR_ORDER_HAS_ACTIVE_WORK")

    builder = db.builders.get(order["builder_id"])
    if builder is None:
        raise ApiError("ERR_BUILDER_NOT_FOUND")

    delta = order["price_delta_cents"] or 0
    domain.move_credit(builder, -delta)
    touch(builder)

    order["final_price_cents"] = None
    order["price_delta_cents"] = None
    order["total_shippable_weight_lbs"] = 0
    order["assigned_weight_lbs"] = 0
    order["unassigned_weight_lbs"] = 0
    order["released_at"] = None
    domain.production_status_rollup(order)
    touch(order)

    return object_response(S.order_out(order))


@bp.route("/orders/<order_id>/erection-sequence", methods=["GET"])
@roles_required(ANY)
def read_erection_sequence(order_id):
    order = domain.get_order(order_id)
    return object_response(domain.erection_sequence(order))
