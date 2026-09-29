"""Role sets, ownership guards and shared body validators."""
import calc
from core import (actor, actor_role, bad_request, db, fail, opt_str, req_bool,
                  req_enum, req_int, req_str)

# --- role sets -------------------------------------------------------------
ALL_READ = ("FnsAdmin", "FnsAnalyst", "AdminReviewOfficer", "RetailerOwner")
ADMIN = ("FnsAdmin",)
ADMIN_OWNER = ("FnsAdmin", "RetailerOwner")
ADMIN_ANALYST = ("FnsAdmin", "FnsAnalyst")
ANALYST_ADMIN = ("FnsAnalyst", "FnsAdmin")
OWNER_ADMIN = ("RetailerOwner", "FnsAdmin")
CLERK_ADMIN = ("StoreClerk", "FnsAdmin")
INSPECTOR_ADMIN = ("Inspector", "FnsAdmin")


# --- ownership (validation precedence rule 5) ------------------------------
def check_store_scope(store):
    role = actor_role()
    if role == "RetailerOwner" and store["owner_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER")
    if role == "StoreClerk" and store["id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER")


def check_visit_scope(visit):
    if actor_role() == "Inspector" and visit["inspector_id"] != actor():
        fail("ERR_NOT_RESOURCE_OWNER")


def store_of_case(case):
    return db.stores.get(case["store_id"])


# --- shared array validators ----------------------------------------------
def validate_inventory_lines(body, field):
    raw = body.get(field)
    if not isinstance(raw, list):
        bad_request("Field '%s' must be an array." % field)
    if not raw:
        bad_request("Field '%s' must not be empty." % field)
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Every element of '%s' must be an object." % field)
        lines.append({
            "category": req_enum(item, "category", calc.STAPLE_CATEGORIES),
            "variety_key": req_str(item, "variety_key"),
            "unit_count": req_int(item, "unit_count", minimum=0),
            "is_perishable": req_bool(item, "is_perishable"),
        })
    return lines


def validate_line_items(body, field="line_items"):
    raw = body.get(field)
    if not isinstance(raw, list):
        bad_request("Field '%s' must be an array." % field)
    if not raw:
        bad_request("Field '%s' must not be empty." % field)
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Every element of '%s' must be an object." % field)
        lines.append({
            "sku": req_str(item, "sku"),
            "item_class": req_enum(item, "item_class", calc.ITEM_CLASSES),
            "unit_price_cents": req_int(item, "unit_price_cents", minimum=0),
            "qty": req_int(item, "qty", minimum=0),
        })
    return lines


def validate_order_lines(body, field="lines"):
    raw = body.get(field)
    if not isinstance(raw, list):
        bad_request("Field '%s' must be an array." % field)
    if not raw:
        bad_request("Field '%s' must not be empty." % field)
    lines = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Every element of '%s' must be an object." % field)
        lines.append({
            "item_code": req_enum(item, "item_code", calc.ITEM_CODES),
            "qty": req_int(item, "qty", minimum=0),
        })
    return lines


def validate_evidence_items(body, field="evidence_items"):
    from core import req_dt
    raw = body.get(field)
    if raw is None:
        return None
    if not isinstance(raw, list):
        bad_request("Field '%s' must be an array." % field)
    items = []
    for item in raw:
        if not isinstance(item, dict):
            bad_request("Every element of '%s' must be an object." % field)
        items.append({
            "evidence_type": req_enum(item, "evidence_type", calc.EVIDENCE_TYPES),
            "observed_at": req_dt(item, "observed_at"),
            "note": opt_str(item, "note"),
        })
    return items


def check_state_code(value, field="state_code"):
    if len(value) != 2 or not value.isupper() or not value.isalpha():
        bad_request("Field '%s' must be exactly two uppercase letters." % field)
    return value
