"""Tray lines: listing, reading and substitution (PRD sections 2.8 and 3.6)."""

from flask import Blueprint

import api
import domain
import serialize
import store
from calcs import LIQUID_ORDINAL, TEXTURE_ORDINAL
from errors import ApiError

bp = Blueprint("meal_order_lines", __name__, url_prefix="/nutrition/meal-order-lines")
sub_bp = Blueprint("line_substitution", __name__, url_prefix="/nutrition/meal-orders")

LINE_STATUSES = ("REQUESTED", "SUBSTITUTED")


@bp.get("")
@api.require(*api.ALL_ROLES)
def list_lines():
    meal_order_id = api.q_str("meal_order_id")
    menu_item_id = api.q_str("menu_item_id")
    substituted_from = api.q_str("substituted_from_menu_item_id")
    line_status = api.q_enum("line_status", LINE_STATUSES)
    rows = api.filtered(list(store.meal_order_lines.values()),
                        [(meal_order_id, "meal_order_id"),
                         (menu_item_id, "menu_item_id"),
                         (substituted_from, "substituted_from_menu_item_id"),
                         (line_status, "line_status")])
    return api.paged(rows, serialize.meal_order_line)


@bp.get("/<line_id>")
@api.require(*api.ALL_ROLES)
def read_line(line_id):
    return api.ok(serialize.meal_order_line(store.get_meal_order_line(line_id)))


@sub_bp.post("/<order_id>/lines/<line_id>/substitute")
@api.require("DietClerk", "Dietitian")
def substitute_line(order_id, line_id):
    # Path identifiers resolve strictly left to right; a line addressed through
    # the wrong parent is treated as not found.
    order = store.get_meal_order(order_id)
    line = store.meal_order_lines.get(line_id)
    if line is None or line["meal_order_id"] != order["id"]:
        raise ApiError("ERR_MEAL_ORDER_LINE_NOT_FOUND")

    body = api.body()
    replacement_id = api.req_id(body, "substitute_menu_item_id")
    reason = api.opt_str(body, "substitution_reason")

    replacement = store.get_menu_item(replacement_id)

    patient = store.patients[order["patient_id"]]
    diet_order = store.diet_orders[order["diet_order_id"]]
    envelope = domain.envelope_of(diet_order)

    if set(patient["allergen_codes"]) & set(replacement["allergen_codes"]):
        raise ApiError("ERR_ALLERGEN_CONFLICT",
                       "The replacement item declares a documented allergen.")
    floor_texture = order["effective_texture_level"] or "REGULAR"
    if TEXTURE_ORDINAL[replacement["texture_level"]] < TEXTURE_ORDINAL[floor_texture]:
        raise ApiError("ERR_TEXTURE_LEVEL_VIOLATION",
                       "The replacement item is coarser than the texture floor.")
    floor_liquid = order["effective_liquid_level"] or "THIN"
    if (replacement["liquid_level"] is not None
            and LIQUID_ORDINAL[replacement["liquid_level"]] < LIQUID_ORDINAL[floor_liquid]):
        raise ApiError("ERR_LIQUID_LEVEL_VIOLATION",
                       "The replacement item is thinner than the thickness floor.")
    forbidden = set(envelope["forbidden_tag_codes_effective"] or [])
    if forbidden & set(replacement["tag_codes"]):
        raise ApiError("ERR_FORBIDDEN_TAG",
                       "The replacement item carries a forbidden dietary tag.")
    if replacement["status"] != "ACTIVE":
        raise ApiError("ERR_MENU_ITEM_DISCONTINUED",
                       "The replacement item is DISCONTINUED.")

    line["substituted_from_menu_item_id"] = line["menu_item_id"]
    line["menu_item_id"] = replacement_id
    line["line_status"] = "SUBSTITUTED"
    line["substitution_reason"] = reason

    domain.recompute_tray(order, order["effective_texture_level"])
    store.touch(line)
    store.touch(order)
    return api.ok(serialize.meal_order_line(line))
