from flask import Blueprint, request

import db
import validate
import response
import errors
from errors import err
from middleware import get_user_context, require_role
from services import lookup, serialize, paginate, recompute, fraud_ops

bp = Blueprint("fraud", __name__)

READ_ROLES = ("PlatformAdmin", "TrustSafety", "Seller")
SUBJECT_TYPES = {"LISTING", "ORDER", "SEAT"}
SIGNALS = {"DUPLICATE_BARCODE", "PRICE_GOUGE", "VELOCITY", "CHARGEBACK"}


@bp.post("/fraud-flags")
def create_flag():
    body = validate.get_json_body()
    subject_type = validate.require_enum(body, "subject_type", SUBJECT_TYPES)
    signal = validate.require_enum(body, "signal", SIGNALS)
    listing_id = validate.require_string(body, "listing_id", required=False)
    order_id = validate.require_string(body, "order_id", required=False)
    seat_id = validate.require_string(body, "seat_id", required=False)

    _, role = get_user_context()
    require_role(role, ("TrustSafety", "PlatformAdmin"))

    # existence of the declared subject; referential mismatch if wrong fk for subject_type
    if subject_type == "LISTING":
        if listing_id is None:
            raise err(errors.ERR_REFERENTIAL_MISMATCH, "listing_id required for LISTING subject")
        lookup.get_listing(listing_id)
    elif subject_type == "ORDER":
        if order_id is None:
            raise err(errors.ERR_REFERENTIAL_MISMATCH, "order_id required for ORDER subject")
        lookup.get_order(order_id)
    elif subject_type == "SEAT":
        if seat_id is None:
            raise err(errors.ERR_REFERENTIAL_MISMATCH, "seat_id required for SEAT subject")
        lookup.get_seat(seat_id)

    flag = {
        "subject_type": subject_type,
        "listing_id": listing_id if subject_type == "LISTING" else None,
        "order_id": order_id if subject_type == "ORDER" else None,
        "seat_id": seat_id if subject_type == "SEAT" else None,
        "signal": signal,
        "severity": "LOW",
        "status": "OPEN",
    }
    db.stamp_create(flag)
    flag["severity"] = fraud_ops.compute_severity(flag)
    db.fraud_flags[flag["id"]] = flag

    # HIGH on listing -> freeze
    fraud_ops.freeze_listing_if_needed(flag)

    # recompute seller open_fraud_flag_count
    seller = fraud_ops._seller_for_flag(flag)
    if seller is not None:
        recompute.recompute_seller(seller)

    return response.object_response(serialize.public(flag), 201)


@bp.get("/fraud-flags/<flag_id>")
def get_flag(flag_id):
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    flag = lookup.get_flag(flag_id)
    return response.object_response(serialize.public(flag), 200)


@bp.get("/fraud-flags")
def list_flags():
    _, role = get_user_context()
    require_role(role, READ_ROLES)
    listing_id = request.args.get("listing_id")
    order_id = request.args.get("order_id")
    seat_id = request.args.get("seat_id")
    records = list(db.fraud_flags.values())
    if listing_id is not None:
        records = [f for f in records if f.get("listing_id") == listing_id]
    if order_id is not None:
        records = [f for f in records if f.get("order_id") == order_id]
    if seat_id is not None:
        records = [f for f in records if f.get("seat_id") == seat_id]
    page, limit, offset, total = paginate.apply_pagination(records)
    return response.array_response(serialize.public_list(page), limit, offset, total)


@bp.post("/fraud-flags/<flag_id>/review")
def review(flag_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    flag = lookup.get_flag(flag_id)
    fraud_ops.review(flag)
    return response.object_response(serialize.public(flag), 200)


@bp.post("/fraud-flags/<flag_id>/confirm")
def confirm(flag_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    flag = lookup.get_flag(flag_id)
    fraud_ops.confirm(flag)
    return response.object_response(serialize.public(flag), 200)


@bp.post("/fraud-flags/<flag_id>/dismiss")
def dismiss(flag_id):
    _, role = get_user_context()
    require_role(role, ("TrustSafety",))
    flag = lookup.get_flag(flag_id)
    fraud_ops.dismiss(flag)
    return response.object_response(serialize.public(flag), 200)
