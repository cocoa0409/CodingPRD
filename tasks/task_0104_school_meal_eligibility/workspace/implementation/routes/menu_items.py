"""MenuItem endpoints. PRD §3.3."""

from flask import Blueprint, request

from core.auth import require_roles
from core.clock import CLOCK
from core.envelope import success_object
from core.errors import raise_error
from core.store import STORE, stamp_common, lock, touch, iso_from_dt
from core.validation import (
    require_body, require_field, optional_field, check_version,
)

from services.calculations import high_sodium_flag
from services.constants import ALLERGENS
from services.relationships import (
    get_district_or_404, get_menu_item_in_district,
)
from services.views import menu_item_view


bp = Blueprint("menu_items", __name__)


@bp.post("/districts/<district_id>/menu-items")
@require_roles("CafeteriaManager")
def create_menu_item(district_id):
    with lock():
        get_district_or_404(district_id)
        body = require_body(request)
        name = require_field(body, "name", kind="string")
        allergens = require_field(body, "contains_allergens", kind="array")
        for a in allergens:
            if a not in ALLERGENS:
                raise_error("ERR_VALIDATION",
                            f"contains_allergens contains unknown allergen '{a}'")
        calories = require_field(body, "calories", kind="non_neg_int")
        sodium_mg = require_field(body, "sodium_mg", kind="non_neg_int")
        full_price = require_field(body, "full_price_cents", kind="non_neg_int")
        reimbursable = require_field(body, "reimbursable", kind="bool")
        m = {
            "district_id": district_id,
            "name": name,
            "contains_allergens": list(allergens),
            "calories": calories,
            "sodium_mg": sodium_mg,
            "full_price_cents": full_price,
            "reimbursable": reimbursable,
            "status": "ACTIVE",
        }
        stamp_common(m)
        STORE.menu_items[m["id"]] = m
        return success_object(menu_item_view(m), status=201)


@bp.get("/districts/<district_id>/menu-items/<menu_item_id>/nutrition-label")
@require_roles("Parent", "DistrictReviewer", "CafeteriaManager", "AuditOfficer")
def nutrition_label(district_id, menu_item_id):
    with lock():
        get_district_or_404(district_id)
        m = get_menu_item_in_district(district_id, menu_item_id)
        allergens_sorted = sorted(set(m.get("contains_allergens", [])))
        out = {
            "calories_per_serving": m["calories"],
            "sodium_per_serving_mg": m["sodium_mg"],
            "allergens": allergens_sorted,
            "high_sodium_flag": high_sodium_flag(m["sodium_mg"]),
        }
        return success_object(out)


@bp.post("/districts/<district_id>/menu-items/<menu_item_id>/retire")
@require_roles("CafeteriaManager")
def retire(district_id, menu_item_id):
    with lock():
        get_district_or_404(district_id)
        m = get_menu_item_in_district(district_id, menu_item_id)
        body = require_body(request)
        check_version(body, m)
        if m["status"] != "ACTIVE":
            raise_error("ERR_INVALID_STATE",
                        f"MenuItem is not ACTIVE (current={m['status']})")
        # Refuse retirement if a SERVED MealServingRecord references this item
        # with serving_date >= today.
        today_iso = iso_from_dt(CLOCK.today_midnight())
        for r in STORE.meal_serving_records.values():
            if r["menu_item_id"] != menu_item_id:
                continue
            if r["status"] != "SERVED":
                continue
            if r["serving_date"] >= today_iso:
                raise_error("ERR_MENU_ITEM_IN_USE",
                            "MenuItem cannot be RETIRED while a future-dated SERVED "
                            "MealServingRecord references it")
        m["status"] = "RETIRED"
        touch(m)
        return success_object(menu_item_view(m))
