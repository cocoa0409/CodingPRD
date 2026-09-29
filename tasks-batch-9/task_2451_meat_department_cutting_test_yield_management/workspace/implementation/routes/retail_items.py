"""Retail item catalogue and the two-stage shelf pricing workflow (PRD §3.1, §3.4)."""

from decimal import Decimal

from flask import Blueprint

import errors
import middleware as mw
import validation as v
from calc import rhu
from db import db, make, mark, sort_rows
from errors import ApiError
from response import list_response, object_response
from services import pricing

bp = Blueprint("retail_items", __name__)

PRODUCT_CLASSES = ("GROUND", "WHOLE_MUSCLE", "VAC_PACKED")
ITEM_ACTION_ROLES = {
    "SUSPEND": (mw.MEAT_MANAGER,),
    "REINSTATE": (mw.MEAT_MANAGER,),
}


@bp.route("/meat-ops/retail-items", methods=["POST"])
def create_retail_item():
    mw.authenticate((mw.STORE_ADMIN, mw.MEAT_MANAGER))
    payload = v.body()

    department_id = v.field_id(payload, "department_id", required=True)
    item_code = v.field_str(payload, "item_code", required=True, min_len=2, max_len=24)
    subprimal_code = v.field_str(payload, "subprimal_code", required=True,
                                 min_len=1, max_len=60)
    product_class = v.field_enum(payload, "product_class", PRODUCT_CLASSES,
                                 required=True)
    target_margin_pct = v.field_num(payload, "target_margin_pct", minimum=0,
                                    maximum=Decimal("0.60"), places=4)

    v.resolve("department", department_id)

    for existing in db.retail_items.values():
        if (existing["department_id"] == department_id
                and existing["item_code"] == item_code):
            raise ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                           "item_code is already in use in this department")

    cost_basis_source = "GRIND_BLEND" if product_class == "GROUND" else "CUT_TEST_LINE"

    item = make("RetailItem", {
        "department_id": department_id,
        "item_code": item_code,
        "subprimal_code": subprimal_code,
        "product_class": product_class,
        "target_margin_pct": target_margin_pct,
        "cost_basis_source": cost_basis_source,
        "pricing_yield_pct_snapshot": rhu(0, 4),
        "yield_adjusted_cost_per_lb_cents": rhu(0, 4),
        "provisional_price_per_lb_cents": 0,
        "final_price_per_lb_cents": 0,
        "active_price_per_lb_cents": 0,
        "price_variance_pct": rhu(0, 4),
        "country_of_origin_label": "PENDING",
        "shelf_life_days": 0,
        "price_status": "UNPRICED",
    })
    db.retail_items[item["id"]] = item
    return object_response(item, 201)


@bp.route("/meat-ops/retail-items/<item_id>", methods=["GET"])
def get_retail_item(item_id):
    mw.authenticate(mw.ALL_ROLES)
    return object_response(v.resolve("retail_item", item_id))


@bp.route("/meat-ops/departments/<department_id>/retail-items", methods=["GET"])
def list_department_items(department_id):
    mw.authenticate(mw.ALL_ROLES)
    v.resolve("department", department_id)
    limit, offset = v.pagination()
    price_status = v.query_filter("price_status")
    rows = [row for row in db.retail_items.values()
            if row["department_id"] == department_id
            and (price_status is None or row["price_status"] == price_status)]
    return list_response(sort_rows(rows), limit, offset)


# --------------------------------------------------------------------------
# stage one — provisional proposal
# --------------------------------------------------------------------------

@bp.route("/meat-ops/retail-items/<item_id>/price-proposals", methods=["POST"])
def propose_price(item_id):
    mw.authenticate((mw.PRICING_ANALYST,))
    item = v.resolve("retail_item", item_id)
    payload = v.body()
    purchase_id = v.field_id(payload, "primal_purchase_id", required=True)
    purchase = v.resolve("primal_purchase", purchase_id)

    if item["price_status"] != "UNPRICED":
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Only an UNPRICED item may take a provisional proposal")

    if purchase["department_id"] != item["department_id"]:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The cited primal purchase belongs to another department")

    if item["cost_basis_source"] == "CUT_TEST_LINE":
        if purchase["product_class"] != item["product_class"]:
            raise ApiError(errors.ERR_PRODUCT_CLASS_MISMATCH, 422,
                           "The cited purchase's product_class must match the item's")

    department = db.departments[item["department_id"]]
    pricing.apply_provisional(item, department, purchase)
    return object_response(item, 201)


# --------------------------------------------------------------------------
# stage two — final activation
# --------------------------------------------------------------------------

def _completed_run_for(item_id):
    rows = [row for row in db.grind_runs.values()
            if row["target_retail_item_id"] == item_id
            and row["status"] == "COMPLETED"]
    rows = sort_rows(rows)
    return rows[-1] if rows else None


@bp.route("/meat-ops/retail-items/<item_id>/price-activations", methods=["POST"])
def activate_price(item_id):
    mw.authenticate((mw.MEAT_MANAGER,))
    item = v.resolve("retail_item", item_id)
    payload = v.body()

    expected_version = v.field_int(payload, "expected_retail_item_version",
                                   required=True)
    cutting_test_id = v.field_id(payload, "cutting_test_id")
    grind_run_id = v.field_id(payload, "grind_run_id")

    cutting_test = v.resolve_optional("cutting_test", cutting_test_id)
    grind_run = v.resolve_optional("grind_run", grind_run_id)

    if expected_version != item["version"]:
        raise ApiError(errors.ERR_STALE_PARENT_VERSION, 412,
                       "expected_retail_item_version does not match the item")

    if item["price_status"] not in ("PROPOSED", "REPRICE_REQUIRED"):
        raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                       "Only a PROPOSED or REPRICE_REQUIRED item may be activated")

    repair = item["price_status"] == "REPRICE_REQUIRED"

    if item["cost_basis_source"] == "CUT_TEST_LINE":
        if cutting_test is not None:
            if cutting_test["status"] != "APPROVED":
                raise ApiError(errors.ERR_SOURCE_TEST_NOT_APPROVED, 409,
                               "The named cutting test is not APPROVED")
        elif not repair:
            raise ApiError(errors.ERR_SOURCE_TEST_NOT_APPROVED, 409,
                           "An APPROVED cutting test must be named")
    else:
        if grind_run is not None:
            if (grind_run["status"] != "COMPLETED"
                    or grind_run["target_retail_item_id"] != item["id"]):
                raise ApiError(errors.ERR_COST_BASIS_UNAVAILABLE, 409,
                               "A COMPLETED grind run for this item is required")
        else:
            grind_run = _completed_run_for(item["id"])
            if grind_run is None and not repair:
                raise ApiError(errors.ERR_COST_BASIS_UNAVAILABLE, 409,
                               "No COMPLETED grind run exists for this item")

    source_purchase = None
    if cutting_test is not None:
        source_purchase = db.primal_purchases.get(cutting_test["primal_purchase_id"])
        if (source_purchase is not None
                and source_purchase["department_id"] != item["department_id"]):
            raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                           "The cited cutting test belongs to another department")
    if grind_run is not None and grind_run["department_id"] != item["department_id"]:
        raise ApiError(errors.ERR_DEPARTMENT_MISMATCH, 422,
                       "The cited grind run belongs to another department")

    if (item["cost_basis_source"] == "CUT_TEST_LINE" and source_purchase is not None
            and source_purchase["product_class"] != item["product_class"]):
        raise ApiError(errors.ERR_PRODUCT_CLASS_MISMATCH, 422,
                       "The cited purchase's product_class must match the item's")

    department = db.departments[item["department_id"]]

    if repair:
        item["active_price_per_lb_cents"] = item["final_price_per_lb_cents"]
        item["price_status"] = "PRICED"
        mark(item)
    else:
        snapshot = None
        coo_label = None
        if item["cost_basis_source"] == "CUT_TEST_LINE":
            if cutting_test is not None:
                snapshot = cutting_test["salable_yield_pct"]
            if source_purchase is not None:
                coo_label = source_purchase["country_of_origin"]
        else:
            if grind_run is not None:
                coo_label = grind_run["coo_label"]
        pricing.apply_final(item, department, snapshot, coo_label)

    pricing.clear_stale_lines(item)
    return object_response(item, 201)


# --------------------------------------------------------------------------
# suspend / reinstate
# --------------------------------------------------------------------------

@bp.route("/meat-ops/retail-items/<item_id>/transitions", methods=["POST"])
def item_transition(item_id):
    _, role = mw.authenticate((mw.MEAT_MANAGER,))
    item = v.resolve("retail_item", item_id)
    payload = v.body()
    action = v.field_enum(payload, "action", tuple(ITEM_ACTION_ROLES), required=True)
    mw.check_action_role(role, action, ITEM_ACTION_ROLES)

    if action == "SUSPEND":
        if item["price_status"] not in ("PROPOSED", "PRICED"):
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "Only a PROPOSED or PRICED item may be suspended")
        for order in db.pre_orders.values():
            if order["retail_item_id"] == item["id"] and order["status"] == "STAGED":
                raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                               "A pre-order on this item is still STAGED")
        item["price_status"] = "SUSPENDED"
        mark(item)
    else:
        if item["price_status"] != "SUSPENDED":
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "Only a SUSPENDED item may be reinstated")
        if item["final_price_per_lb_cents"] <= 0:
            raise ApiError(errors.ERR_INVALID_STATE_TRANSITION, 409,
                           "final_price_per_lb_cents must be greater than 0")
        item["active_price_per_lb_cents"] = item["final_price_per_lb_cents"]
        item["price_status"] = "PRICED"
        mark(item)

    return object_response(item)
