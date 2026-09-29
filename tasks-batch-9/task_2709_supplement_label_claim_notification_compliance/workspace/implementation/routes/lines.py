"""Supplement-facts lines: composition, %DV and soft deletion (PRD 3.3)."""

from flask import Blueprint

import auth
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("product_ingredients", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_AUDITOR,
)

LABEL_BLOCKED_ELIGIBILITY = ("INELIGIBLE", "NDI_OBJECTED")


def _position_taken(product_id, position, exclude_id=None):
    for line in db.all_rows("product_ingredients"):
        if line["product_id"] != product_id or line["line_status"] != "ACTIVE":
            continue
        if exclude_id is not None and line["id"] == exclude_id:
            continue
        if line["panel_position"] == position:
            return True
    return False


@bp.route(PREFIX + "/product-ingredients", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_line():
    body = validate.body()
    product_id = validate.req_str(body, "product_id")
    ingredient_id = validate.req_str(body, "ingredient_id")
    amount = validate.req_number(body, "amount_per_serving_mg", gt=0)
    position = validate.req_int(body, "panel_position", ge=1)

    product = fk_row("products", product_id, errors.ERR_PRODUCT_NOT_FOUND)
    ingredient = fk_row("ingredients", ingredient_id, errors.ERR_INGREDIENT_NOT_FOUND)

    if product["lifecycle_status"] != "DRAFT":
        fail(
            errors.ERR_PRODUCT_STATE_INVALID,
            "Lines may only be added to a product in DRAFT.",
        )
    if _position_taken(product_id, position):
        fail(
            errors.ERR_PANEL_POSITION_TAKEN,
            "Panel position %s is already taken by an ACTIVE line." % position,
        )
    if ingredient["eligibility_status"] in LABEL_BLOCKED_ELIGIBILITY:
        fail(
            errors.ERR_INGREDIENT_INELIGIBLE_FOR_LABEL,
            "An ingredient in %s may not be printed on a panel."
            % ingredient["eligibility_status"],
        )

    row = db.base_fields()
    row.update(
        {
            "product_id": product_id,
            "ingredient_id": ingredient_id,
            "amount_per_serving_mg": amount,
            "panel_position": position,
            "line_status": "ACTIVE",
            "percent_dv_declared": None,
            "dv_established": False,
        }
    )
    cascade.recompute_line_dv(row)
    db.insert("product_ingredients", row)
    return response.object_response(serialize.product_ingredient(row), 201)


@bp.route(PREFIX + "/product-ingredients/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_line(row_id):
    row = path_row("product_ingredients", row_id, errors.ERR_PRODUCT_INGREDIENT_NOT_FOUND)
    return response.object_response(serialize.product_ingredient(row))


@bp.route(PREFIX + "/product-ingredients", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_lines():
    return listing(
        "product_ingredients",
        serialize.product_ingredient,
        filters=("product_id", "ingredient_id", "line_status"),
    )


@bp.route(PREFIX + "/product-ingredients/<row_id>", methods=["PATCH"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def amend_line(row_id):
    row = path_row("product_ingredients", row_id, errors.ERR_PRODUCT_INGREDIENT_NOT_FOUND)
    body = validate.body()

    sentinel = object()
    amount = validate.opt_number(
        body, "amount_per_serving_mg", default=sentinel, gt=0, allow_null=False
    )
    position = validate.opt_int(
        body, "panel_position", default=sentinel, ge=1, allow_null=False
    )

    product = db.get("products", row["product_id"])
    if product is not None and product["lifecycle_status"] != "DRAFT":
        fail(
            errors.ERR_PRODUCT_STATE_INVALID,
            "Lines may only be amended on a product in DRAFT.",
        )
    if row["line_status"] != "ACTIVE":
        fail(
            errors.ERR_PRODUCT_INGREDIENT_STATE_INVALID,
            "Only an ACTIVE line may be amended.",
        )
    if position is not sentinel and _position_taken(
        row["product_id"], position, exclude_id=row["id"]
    ):
        fail(
            errors.ERR_PANEL_POSITION_TAKEN,
            "Panel position %s is already taken by an ACTIVE line." % position,
        )

    if amount is not sentinel:
        row["amount_per_serving_mg"] = amount
    if position is not sentinel:
        row["panel_position"] = position
    cascade.recompute_line_dv(row)
    db.touch(row)
    return response.object_response(serialize.product_ingredient(row))


@bp.route(PREFIX + "/product-ingredients/<row_id>", methods=["DELETE"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def remove_line(row_id):
    row = path_row("product_ingredients", row_id, errors.ERR_PRODUCT_INGREDIENT_NOT_FOUND)

    product = db.get("products", row["product_id"])
    if product is not None and product["lifecycle_status"] != "DRAFT":
        fail(
            errors.ERR_PRODUCT_STATE_INVALID,
            "Lines may only be removed from a product in DRAFT.",
        )
    if row["line_status"] != "ACTIVE":
        fail(
            errors.ERR_PRODUCT_INGREDIENT_STATE_INVALID,
            "Only an ACTIVE line may be removed.",
        )

    # Soft delete: the row stays fully queryable so superseded panels remain auditable.
    row["line_status"] = "REMOVED"
    row["percent_dv_declared"] = None
    row["dv_established"] = False
    db.touch(row)
    return response.object_response(serialize.product_ingredient(row))
