"""Product registration and watch posture (PRD 3.5)."""

from flask import Blueprint

import calc
from response import collection_response, resource_response
from store import create_record, db, touch
from validation import (
    authorize,
    find_carrier,
    find_product_type,
    get_enum,
    get_id,
    get_int,
    get_string,
    guard_terminal,
    guard_transition,
    is_liaison,
    json_body,
    liaison_carrier_id,
    pagination,
    query_enum,
    query_str,
    scope_check,
)

bp = Blueprint("products", __name__)

PRODUCT_STATUSES = ("OPEN", "ON_WATCH", "CLOSED_TO_NEW")
ACCOUNT_TYPES = ("GENERAL", "SEPARATE", "HYBRID")
MEC_STATUSES = ("MEC", "NON_MEC")
READ_ROLES = (
    "PlatformAdmin",
    "BenefitsAnalyst",
    "RiskOfficer",
    "TreasuryController",
    "CarrierLiaison",
)


@bp.post("/product-types")
def register_product_type():
    authorize(("PlatformAdmin",))
    body = json_body()
    carrier_id = get_id(body, "carrier_id")
    product_name = get_string(body, "product_name")
    account_type = get_enum(body, "account_type", ACCOUNT_TYPES)
    mec_status = get_enum(body, "mec_status", MEC_STATUSES)
    disclosed = get_int(body, "disclosed_me_charge_bps", minimum=0)
    guaranteed = get_int(body, "guaranteed_min_crediting_bps", minimum=0)

    find_carrier(carrier_id)
    product = create_record(
        db.product_types,
        {
            "carrier_id": carrier_id,
            "product_name": product_name,
            "account_type": account_type,
            "mec_status": mec_status,
            "disclosed_me_charge_bps": disclosed,
            "guaranteed_min_crediting_bps": guaranteed,
            "status": "OPEN",
            "consecutive_low_yield_count": 0,
            "latest_me_charge_bps": 0,
            "latest_me_drift_bps": 0,
        },
    )
    return resource_response(product, 201)


@bp.get("/product-types")
def list_product_types():
    authorize(READ_ROLES)
    limit, offset = pagination()
    carrier_id = query_str("carrier_id")
    status = query_enum("status", PRODUCT_STATUSES)
    account_type = query_enum("account_type", ACCOUNT_TYPES)
    if is_liaison():
        scope_check(carrier_id)
        carrier_id = liaison_carrier_id()
    rows = []
    for product in db.product_types.values():
        if carrier_id is not None and product["carrier_id"] != carrier_id:
            continue
        if status is not None and product["status"] != status:
            continue
        if account_type is not None and product["account_type"] != account_type:
            continue
        rows.append(product)
    return collection_response(rows, limit, offset)


@bp.get("/product-types/<product_type_id>")
def read_product_type(product_type_id):
    authorize(READ_ROLES)
    product = find_product_type(product_type_id)
    scope_check(product["carrier_id"])
    return resource_response(product)


@bp.post("/product-types/<product_type_id>/clear-watch")
def clear_watch(product_type_id):
    authorize(("RiskOfficer",))
    product = find_product_type(product_type_id)
    guard_terminal(product["status"], ("CLOSED_TO_NEW",))
    guard_transition(product["status"] == "ON_WATCH")
    guard_transition(product["latest_me_drift_bps"] <= calc.ME_DRIFT_TOLERANCE_BPS)
    product["status"] = "OPEN"
    product["consecutive_low_yield_count"] = 0
    touch(product)
    return resource_response(product)
