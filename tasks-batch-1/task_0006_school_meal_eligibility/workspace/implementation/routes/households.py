"""Household routes + nested reads."""
from flask import Blueprint
import db
from response import success_object, success_array
from middleware import require_role
from validation import (
    parse_pagination, get_json_body, enforce_keys, require_str, require_int,
    require_bool,
)
from services import (
    common_fields_init, bump_version, get_or_404, sort_by_created_at, paginate, clean
)
from errors import ERR_INVALID_REQUEST, raise_err

bp = Blueprint("households", __name__)


# ----------------------------- Create -----------------------------

@bp.post("/school-meals/households")
def create_household():
    require_role({"SchoolStaff", "DistrictReviewer"})
    body = get_json_body()
    enforce_keys(
        body,
        required={"primary_parent_name", "family_size", "annual_income_cents", "address_state"},
        optional={"direct_certification_flag"},
    )
    require_str(body["primary_parent_name"], "primary_parent_name")
    require_int(body["family_size"], "family_size", min_val=1, max_val=20)
    require_int(body["annual_income_cents"], "annual_income_cents", min_val=0)
    require_str(body["address_state"], "address_state")
    state = body["address_state"]
    if not (len(state) == 2 and state.isalpha() and state.isupper()):
        raise_err(ERR_INVALID_REQUEST, "address_state must be 2-letter uppercase")
    dcf = body.get("direct_certification_flag", False)
    if "direct_certification_flag" in body:
        require_bool(body["direct_certification_flag"], "direct_certification_flag")

    record = {
        **common_fields_init(),
        "primary_parent_name": body["primary_parent_name"],
        "family_size": body["family_size"],
        "annual_income_cents": body["annual_income_cents"],
        "address_state": state,
        "direct_certification_flag": dcf,
    }
    db.households[record["id"]] = record

    # Always-on side effect: create ParentAccount at zero balance.
    parent_account = {
        **common_fields_init(),
        "household_id": record["id"],
        "balance_cents": 0,
        "daily_topup_total_cents": 0,
        "daily_topup_window_date": None,
    }
    db.parent_accounts[parent_account["id"]] = parent_account

    return success_object(clean(record), status=201)


# ----------------------------- Read -----------------------------

@bp.get("/school-meals/households/<hid>")
def read_household(hid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    record = get_or_404(db.households, hid, "Household")
    # Parents may only read their own household
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    return success_object(clean(record))


# ----------------------------- List -----------------------------

@bp.get("/school-meals/households")
def list_households():
    require_role({"SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    limit, offset = parse_pagination()
    from flask import request
    address_state = request.args.get("address_state")
    items = list(db.households.values())
    if address_state is not None:
        items = [h for h in items if h["address_state"] == address_state]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


# ----------------------------- PATCH -----------------------------

@bp.patch("/school-meals/households/<hid>")
def update_household(hid):
    user_id, role = require_role({"Parent", "SchoolStaff"})
    record = get_or_404(db.households, hid, "Household")
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    body = get_json_body()
    enforce_keys(
        body,
        required=set(),
        optional={
            "primary_parent_name", "family_size", "annual_income_cents",
            "address_state", "direct_certification_flag",
        },
    )
    if "primary_parent_name" in body:
        require_str(body["primary_parent_name"], "primary_parent_name")
        record["primary_parent_name"] = body["primary_parent_name"]
    if "family_size" in body:
        require_int(body["family_size"], "family_size", min_val=1, max_val=20)
        record["family_size"] = body["family_size"]
    if "annual_income_cents" in body:
        require_int(body["annual_income_cents"], "annual_income_cents", min_val=0)
        record["annual_income_cents"] = body["annual_income_cents"]
    if "address_state" in body:
        require_str(body["address_state"], "address_state")
        state = body["address_state"]
        if not (len(state) == 2 and state.isalpha() and state.isupper()):
            raise_err(ERR_INVALID_REQUEST, "address_state must be 2-letter uppercase")
        record["address_state"] = state
    if "direct_certification_flag" in body:
        require_bool(body["direct_certification_flag"], "direct_certification_flag")
        record["direct_certification_flag"] = body["direct_certification_flag"]
    bump_version(record)
    return success_object(clean(record))


# ----------------------------- Nested reads -----------------------------

@bp.get("/school-meals/households/<hid>/students")
def list_household_students(hid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    get_or_404(db.households, hid, "Household")
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    limit, offset = parse_pagination()
    items = [s for s in db.students.values() if s["household_id"] == hid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/school-meals/households/<hid>/applications")
def list_household_applications(hid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    get_or_404(db.households, hid, "Household")
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    limit, offset = parse_pagination()
    from flask import request
    status_filter = request.args.get("status")
    items = [a for a in db.meal_applications.values() if a["household_id"] == hid]
    if status_filter is not None:
        items = [a for a in items if a["status"] == status_filter]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/school-meals/households/<hid>/eligibility-determinations")
def list_household_determinations(hid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer", "USDAAuditor"})
    get_or_404(db.households, hid, "Household")
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    limit, offset = parse_pagination()
    from flask import request
    lifecycle = request.args.get("lifecycle_status")
    items = [d for d in db.eligibility_determinations.values() if d["household_id"] == hid]
    if lifecycle is not None:
        items = [d for d in items if d["lifecycle_status"] == lifecycle]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    return success_array([clean(r) for r in page], limit=limit, offset=offset, total_count=total)


@bp.get("/school-meals/households/<hid>/parent-account")
def get_household_parent_account(hid):
    user_id, role = require_role({"Parent", "SchoolStaff", "DistrictReviewer"})
    get_or_404(db.households, hid, "Household")
    if role == "Parent" and user_id != hid:
        from errors import ERR_NOT_RESOURCE_OWNER
        raise_err(ERR_NOT_RESOURCE_OWNER, "parent does not own this household")
    from services import serialize_parent_account
    limit, offset = parse_pagination()
    items = [a for a in db.parent_accounts.values() if a["household_id"] == hid]
    items = sort_by_created_at(items)
    page, total = paginate(items, limit, offset)
    cleaned = [clean(serialize_parent_account(r)) for r in page]
    return success_array(cleaned, limit=limit, offset=offset, total_count=total)
