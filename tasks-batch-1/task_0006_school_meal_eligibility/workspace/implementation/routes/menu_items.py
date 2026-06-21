"""MenuItem routes."""
from flask import Blueprint, request
import db
from response import success_object, success_array
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
)
from services import (
    common_fields_init, get_or_404, sort_by_created_at, paginate, clean,
)
from errors import ERR_INVALID_REQUEST, raise_err

bp = Blueprint("menu_items", __name__)

ALLERGEN_ENUM = {"PEANUT", "TREE_NUT", "MILK", "EGG", "SOY", "WHEAT", "FISH", "SHELLFISH"}


@bp.post("/school-meals/menu-items")
def create_menu_item():
    require_role({"SchoolStaff"})
    body = get_json_body()
    enforce_keys(
        body,
        required={
            "school_code", "name", "list_price_cents",
            "federal_reimbursement_free_cents",
            "federal_reimbursement_reduced_cents",
            "federal_reimbursement_paid_cents",
            "calories",
        },
        optional={"allergens_present"},
    )
    require_str(body["school_code"], "school_code")
    require_str(body["name"], "name")
    require_int(body["list_price_cents"], "list_price_cents", min_val=0)
    require_int(body["federal_reimbursement_free_cents"], "federal_reimbursement_free_cents", min_val=0)
    require_int(body["federal_reimbursement_reduced_cents"], "federal_reimbursement_reduced_cents", min_val=0)
    require_int(body["federal_reimbursement_paid_cents"], "federal_reimbursement_paid_cents", min_val=0)
    require_int(body["calories"], "calories", min_val=0)
    allergens = body.get("allergens_present", [])
    if not isinstance(allergens, list):
        raise_err(ERR_INVALID_REQUEST, "allergens_present must be array")
    for a in allergens:
        if a not in ALLERGEN_ENUM:
            raise_err(ERR_INVALID_REQUEST, f"invalid allergen: {a}")
    rec = {
        **common_fields_init(),
        "school_code": body["school_code"],
        "name": body["name"],
        "list_price_cents": body["list_price_cents"],
        "federal_reimbursement_free_cents": body["federal_reimbursement_free_cents"],
        "federal_reimbursement_reduced_cents": body["federal_reimbursement_reduced_cents"],
        "federal_reimbursement_paid_cents": body["federal_reimbursement_paid_cents"],
        "allergens_present": list(allergens),
        "calories": body["calories"],
    }
    db.menu_items[rec["id"]] = rec
    return success_object(clean(rec), status=201)


@bp.get("/school-meals/menu-items/<mid>")
def read_menu_item(mid):
    require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    rec = get_or_404(db.menu_items, mid, "MenuItem")
    return success_object(clean(rec))


@bp.get("/school-meals/menu-items")
def list_menu_items():
    require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    school_code = request.args.get("school_code")
    items = list(db.menu_items.values())
    if school_code is not None:
        items = [m for m in items if m["school_code"] == school_code]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)
