"""Ingredient monograph and eligibility determination (PRD 3.1)."""

from flask import Blueprint

import auth
import calc
import cascade
import db
import errors
import response
import serialize
import validate
from errors import fail
from routes.helpers import PREFIX, fk_row, listing, path_row

bp = Blueprint("ingredients", __name__)

READ_ROLES = (
    auth.ROLE_SPECIALIST,
    auth.ROLE_REVIEWER,
    auth.ROLE_APPROVAL,
    auth.ROLE_QA,
    auth.ROLE_SUPPLIER_REP,
    auth.ROLE_AUDITOR,
)

AMENDABLE_STATES = ("DRAFT_ASSESSMENT", "NDI_REQUIRED")


@bp.route(PREFIX + "/ingredients", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def create_ingredient():
    body = validate.body()
    name = validate.req_str(body, "ingredient_name")
    ingredient_class = validate.req_enum(body, "ingredient_class", calc.INGREDIENT_CLASSES)
    pre_dshea = validate.req_bool(body, "pre_dshea_marketed")
    altered = validate.req_bool(body, "chemical_alteration")
    daily_intake = validate.req_number(body, "daily_intake_mg", ge=0)
    rdi = validate.opt_number(body, "rdi_mg", gt=0)
    allergen = validate.opt_enum(body, "allergen_code", calc.ALLERGEN_CODES)
    contraindication = validate.opt_enum(
        body, "contraindication_code", calc.CONTRAINDICATION_CODES
    )
    predecessor_id = validate.opt_str(body, "predecessor_ingredient_id")

    if predecessor_id is not None:
        fk_row("ingredients", predecessor_id, errors.ERR_INGREDIENT_NOT_FOUND)

    row = db.base_fields()
    row.update(
        {
            "ingredient_name": name,
            "ingredient_class": ingredient_class,
            "pre_dshea_marketed": pre_dshea,
            "chemical_alteration": altered,
            "daily_intake_mg": daily_intake,
            "rdi_mg": rdi,
            "allergen_code": allergen,
            "contraindication_code": contraindication,
            "predecessor_ingredient_id": predecessor_id,
            "eligibility_status": "DRAFT_ASSESSMENT",
            "ndi_notification_required": False,
            "determined_at": None,
        }
    )
    db.insert("ingredients", row)
    return response.object_response(serialize.ingredient(row), 201)


@bp.route(PREFIX + "/ingredients/<row_id>", methods=["GET"])
@auth.endpoint(READ_ROLES)
def get_ingredient(row_id):
    row = path_row("ingredients", row_id, errors.ERR_INGREDIENT_NOT_FOUND)
    return response.object_response(serialize.ingredient(row))


@bp.route(PREFIX + "/ingredients", methods=["GET"])
@auth.endpoint(READ_ROLES)
def list_ingredients():
    return listing(
        "ingredients",
        serialize.ingredient,
        filters=("eligibility_status", "ingredient_class", "predecessor_ingredient_id"),
    )


@bp.route(PREFIX + "/ingredients/<row_id>", methods=["PATCH"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def amend_ingredient(row_id):
    row = path_row("ingredients", row_id, errors.ERR_INGREDIENT_NOT_FOUND)
    body = validate.body()

    sentinel = object()
    rdi = validate.opt_number(body, "rdi_mg", default=sentinel, gt=0)
    allergen = validate.opt_enum(body, "allergen_code", calc.ALLERGEN_CODES, default=sentinel)
    contraindication = validate.opt_enum(
        body, "contraindication_code", calc.CONTRAINDICATION_CODES, default=sentinel
    )
    daily_intake = validate.opt_number(body, "daily_intake_mg", default=sentinel, ge=0)
    predecessor_id = validate.opt_str(body, "predecessor_ingredient_id", default=sentinel)

    if predecessor_id is not sentinel and predecessor_id is not None:
        fk_row("ingredients", predecessor_id, errors.ERR_INGREDIENT_NOT_FOUND)

    if row["eligibility_status"] not in AMENDABLE_STATES:
        fail(
            errors.ERR_INGREDIENT_STATE_INVALID,
            "An ingredient in %s may not be amended." % row["eligibility_status"],
        )

    if rdi is not sentinel:
        row["rdi_mg"] = rdi
    if allergen is not sentinel:
        row["allergen_code"] = allergen
    if contraindication is not sentinel:
        row["contraindication_code"] = contraindication
    if daily_intake is not sentinel:
        row["daily_intake_mg"] = daily_intake
    if predecessor_id is not sentinel:
        row["predecessor_ingredient_id"] = predecessor_id
    db.touch(row)

    # A corrected reference daily intake re-prices every panel line that depends on it.
    for line in db.all_rows("product_ingredients"):
        if line["ingredient_id"] != row["id"] or line["line_status"] != "ACTIVE":
            continue
        cascade.recompute_line_dv(line)
        db.touch(line)

    return response.object_response(serialize.ingredient(row))


@bp.route(PREFIX + "/ingredients/<row_id>/eligibility-determination", methods=["POST"])
@auth.endpoint([auth.ROLE_SPECIALIST])
def determine_eligibility(row_id):
    row = path_row("ingredients", row_id, errors.ERR_INGREDIENT_NOT_FOUND)
    if row["eligibility_status"] != "DRAFT_ASSESSMENT":
        fail(
            errors.ERR_INGREDIENT_STATE_INVALID,
            "The eligibility determination has already settled this ingredient.",
        )

    if row["ingredient_class"] == "EXCLUDED_SUBSTANCE":
        row["eligibility_status"] = "INELIGIBLE"
        row["ndi_notification_required"] = False
    elif (
        row["pre_dshea_marketed"] is True
        and row["chemical_alteration"] is False
        and calc.dec(row["daily_intake_mg"]) <= calc.GRANDFATHER_INTAKE_LIMIT
    ):
        row["eligibility_status"] = "GRANDFATHERED"
        row["ndi_notification_required"] = False
    else:
        row["eligibility_status"] = "NDI_REQUIRED"
        row["ndi_notification_required"] = True

    row["determined_at"] = db.now()
    db.touch(row)
    return response.object_response(serialize.ingredient(row))
