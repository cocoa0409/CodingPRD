"""Catalog items and the offer window."""

from flask import Blueprint, request

import domain
import fetch
import serializers
import validators
from constants import (ROLE_BUYER, ROLE_COMPLIANCE, ROLE_HUB_ADMIN,
                       ROLE_PRODUCER, STORAGE_CLASSES, UNITS_OF_MEASURE)
from envelope import list_response, ok
from errors import ApiError
from store import base_record, db, sorted_records, touch
from validators import (actor, body, endpoint, opt_int, req_datetime, req_enum,
                        req_int, req_number, req_string)

bp = Blueprint("catalog", __name__)


@bp.post("/products")
@endpoint([ROLE_PRODUCER, ROLE_HUB_ADMIN])
def create_product():
    payload = body()
    producer = fetch.body_fk(payload, "producer_id", "producer")   # rung 5
    # rung 6
    req_string(payload, "producer_id")
    commodity_code = req_string(payload, "commodity_code", min_len=1, max_len=40,
                                pattern=validators.COMMODITY_RE)
    unit_of_measure = req_enum(payload, "unit_of_measure", UNITS_OF_MEASURE)
    storage_class = req_enum(payload, "storage_class", STORAGE_CLASSES)
    pack_weight_lb = req_number(payload, "pack_weight_lb", minimum_exclusive=0)
    units_per_pallet = req_int(payload, "units_per_pallet", minimum=1)
    unit_price = req_int(payload, "producer_unit_price_cents", minimum=1)

    user_id, role = actor()
    if role == ROLE_PRODUCER and user_id != producer["id"]:          # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 13 — only a producer in good standing may hold a catalog
    if not domain.producer_in_good_standing(producer):
        raise ApiError("ERR_PRODUCER_NOT_COMPLIANT")

    product = base_record({
        "producer_id": producer["id"],
        "commodity_code": commodity_code,
        "unit_of_measure": unit_of_measure,
        "storage_class": storage_class,
        "pack_weight_lb": pack_weight_lb,
        "units_per_pallet": units_per_pallet,
        "producer_unit_price_cents": unit_price,
        "status": "DRAFT",
        "quantity_offered": 0,
        "quantity_committed": 0,
        "quantity_available": 0,
        "offer_window_start": None,
        "offer_window_end": None,
    })
    db.products[product["id"]] = product
    return ok(serializers.product_out(product), 201)


@bp.get("/products/<product_id>")
@endpoint([ROLE_HUB_ADMIN, ROLE_COMPLIANCE, ROLE_PRODUCER, ROLE_BUYER])
def read_product(product_id):
    product = fetch.get("product", product_id)
    return ok(serializers.product_out(product))


@bp.get("/products")
@endpoint([ROLE_HUB_ADMIN, ROLE_PRODUCER, ROLE_BUYER])
def list_products():
    records = sorted_records(list(db.products.values()))
    for field in ("producer_id", "commodity_code", "storage_class", "status"):
        value = request.args.get(field)
        if value is not None:
            records = [r for r in records if r[field] == value]
    return list_response(records, serializers.product_out)


@bp.post("/products/<product_id>/offers")
@endpoint([ROLE_PRODUCER, ROLE_HUB_ADMIN])
def publish_offer(product_id):
    product = fetch.get("product", product_id)                     # rung 4
    payload = body()
    # rung 6
    quantity_offered = req_int(payload, "quantity_offered", minimum=0)
    window_start = req_datetime(payload, "offer_window_start")
    window_end = req_datetime(payload, "offer_window_end")
    unit_price = opt_int(payload, "producer_unit_price_cents", minimum=1)
    expected_version = req_int(payload, "expected_product_version")

    user_id, role = actor()
    if role == ROLE_PRODUCER and user_id != product["producer_id"]:  # rung 7
        raise ApiError("ERR_NOT_RESOURCE_OWNER")

    # rung 9 — optimistic concurrency sits above every state and business rule
    if expected_version != product["version"]:
        raise ApiError("ERR_STALE_PRODUCT_VERSION")

    producer = db.producers.get(product["producer_id"])
    # rung 10
    if producer is None or producer["onboarding_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_PRODUCER_STATE")
    # rung 13
    if not domain.compliance_ok(producer):
        raise ApiError("ERR_PRODUCER_NOT_COMPLIANT")
    # rung 18
    if window_end <= window_start:
        raise ApiError("ERR_INVALID_WINDOW")
    # a re-offer may not un-promise cases the hub already reserved
    if quantity_offered < product["quantity_committed"]:
        raise ApiError("ERR_INVALID_REQUEST",
                       "quantity_offered is below the already committed quantity.")

    product["status"] = "LISTED"
    product["quantity_offered"] = quantity_offered
    product["offer_window_start"] = window_start
    product["offer_window_end"] = window_end
    if unit_price is not None:
        product["producer_unit_price_cents"] = unit_price
    domain.recompute_product_available(product)
    touch(product)
    return ok(serializers.product_out(product))
