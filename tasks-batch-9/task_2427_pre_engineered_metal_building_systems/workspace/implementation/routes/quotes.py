"""PRD 3.4 / 3.5 -- pricing a configuration, issuing, accepting and minting the order."""

from flask import Blueprint, request

import constants as C
import serializers as S
import validation as V
from errors import ApiError
from middleware import ANY, actor, roles_required
from response import object_response, paginated
from services import calc, domain
from store import db, fmt_dt, new_row, now, now_iso, ordered, plus_days, touch

bp = Blueprint("quotes", __name__)


@bp.route("/quotes", methods=["POST"])
@roles_required("SalesEngineer")
def create_quote():
    data = V.body()
    builder_id = V.get_string(data, "builder_id")
    configuration_id = V.get_string(data, "configuration_id")
    freight_distance_miles = V.get_number(data, "freight_distance_miles", exclusive_minimum=0)
    adjustment_cents = V.get_int(data, "adjustment_cents", required=False, default=0)

    builder = domain.get_builder(builder_id)
    config = domain.get_configuration(configuration_id)

    # Band 8 then band 10.
    if builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_BUILDER_NOT_AUTHORIZED")
    if config["status"] != "LOCKED":
        raise ApiError("ERR_CONFIGURATION_NOT_LOCKED")

    jurisdiction = db.jurisdictions.get(config["jurisdiction_id"])
    if jurisdiction is None:
        raise ApiError("ERR_JURISDICTION_NOT_FOUND")

    kits = domain.kits_of_configuration(config["id"])
    priced = calc.quote_price_pipeline(
        "PRELIMINARY",
        config,
        builder,
        jurisdiction,
        kits,
        freight_distance_miles,
        adjustment_cents,
        config["estimated_frame_weight_lbs"],
    )

    # Band 15: the adjustment floor is twenty percent of the parts subtotal.
    if adjustment_cents < calc.adjustment_floor_cents(priced["subtotal_cents"]):
        raise ApiError("ERR_ADJUSTMENT_LIMIT_EXCEEDED")

    fields = {
        "builder_id": builder["id"],
        "configuration_id": config["id"],
        "freight_distance_miles": freight_distance_miles,
        "adjustment_cents": adjustment_cents,
        "quoted_price_cents": priced.pop("price_cents"),
        "valid_until": None,
        "_valid_until_dt": None,
        "issued_at": None,
        "status": "DRAFT",
    }
    fields.update(priced)
    row = new_row(fields)
    db.quotes[row["id"]] = row
    return object_response(S.quote_out(row), 201)


@bp.route("/quotes/<quote_id>", methods=["GET"])
@roles_required(ANY)
def read_quote(quote_id):
    return object_response(S.quote_out(domain.get_quote(quote_id)))


@bp.route("/quotes", methods=["GET"])
@roles_required(ANY)
def list_quotes():
    builder_id = request.args.get("builder_id")
    configuration_id = request.args.get("configuration_id")
    status = request.args.get("status")

    def predicate(row):
        if builder_id is not None and row["builder_id"] != builder_id:
            return False
        if configuration_id is not None and row["configuration_id"] != configuration_id:
            return False
        if status is not None and row["status"] != status:
            return False
        return True

    return paginated(ordered(db.quotes, predicate), S.quote_out)


@bp.route("/quotes/<quote_id>/issue", methods=["POST"])
@roles_required("SalesEngineer")
def issue_quote(quote_id):
    quote = domain.get_quote(quote_id)

    if quote["status"] != "DRAFT":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")

    config = db.configurations.get(quote["configuration_id"])
    if config is None or config["status"] != "LOCKED":
        raise ApiError("ERR_CONFIGURATION_NOT_LOCKED")

    issued_at = now()
    valid_until = plus_days(issued_at, C.QUOTE_VALID_DAYS)
    quote["issued_at"] = fmt_dt(issued_at)
    quote["valid_until"] = fmt_dt(valid_until)
    quote["_valid_until_dt"] = valid_until
    quote["status"] = "ISSUED"
    touch(quote)
    return object_response(S.quote_out(quote))


@bp.route("/quotes/<quote_id>/accept", methods=["POST"])
@roles_required("Builder")
def accept_quote(quote_id):
    data = V.body()
    job_site_code = V.get_string(data, "job_site_code", min_len=3, max_len=16)
    requested_start_dt, requested_start_raw = V.get_datetime(
        data, "requested_erection_start_date"
    )
    site_delivery_capacity = V.get_int(
        data,
        "site_delivery_capacity",
        required=False,
        default=C.DEFAULT_SITE_DELIVERY_CAPACITY,
        minimum=1,
    )

    quote = domain.get_quote(quote_id)

    # Band 5: the acting Builder's X-User-ID IS its row id.
    if quote["builder_id"] != actor():
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    builder = domain.get_builder(quote["builder_id"])

    # Band 8, then band 9, then band 13, then band 15.
    if builder["status"] != "AUTHORIZED":
        raise ApiError("ERR_BUILDER_NOT_AUTHORIZED")
    if quote["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_STATE_TRANSITION")
    valid_until = quote.get("_valid_until_dt")
    if valid_until is None or now() > valid_until:
        raise ApiError("ERR_QUOTE_EXPIRED")
    if quote["quoted_price_cents"] > domain.credit_available(builder):
        raise ApiError("ERR_BUILDER_CREDIT_EXCEEDED")

    order = new_row(
        {
            "quote_id": quote["id"],
            "builder_id": builder["id"],
            "configuration_id": quote["configuration_id"],
            "engineering_design_id": None,
            "drawing_package_id": None,
            "job_site_code": job_site_code,
            "requested_erection_start_date": requested_start_raw,
            "_requested_erection_start_dt": requested_start_dt,
            "site_delivery_capacity": site_delivery_capacity,
            "engineering_status": "ENG_PENDING",
            "production_status": "PROD_NOT_RELEASED",
            "permit_hold": False,
            "commercial_hold": False,
            "final_price_cents": None,
            "price_delta_cents": None,
            "total_shippable_weight_lbs": 0,
            "assigned_weight_lbs": 0,
            "unassigned_weight_lbs": 0,
            "released_at": None,
        }
    )
    db.orders[order["id"]] = order

    domain.move_credit(builder, quote["quoted_price_cents"])
    touch(builder)
    quote["status"] = "ACCEPTED"
    touch(quote)

    return object_response(S.order_out(order), 201)
