"""Onboarding and continuing-education items."""

from flask import Blueprint

from authz import (
    COMMITTEE_CHAIR,
    COMMITTEE_MEMBER,
    CORPORATE_SECRETARY,
    GOVERNANCE_STAFF,
    SEATED_DIRECTOR,
    require,
    require_director_owner,
)
from derive import recompute_compliance, recompute_education_hours, recompute_onboarding
from errors import fail
from payload import body, check_enum, check_min, optional, parse_date, required
from store import clock_instant, db, new_row, touch
from vocab import ONBOARDING_CATEGORY

from routes.common import apply_filters, by_created_desc, emit, emit_list, need

bp = Blueprint("onboarding", __name__)

READ_ROLES = (GOVERNANCE_STAFF, CORPORATE_SECRETARY, COMMITTEE_CHAIR, COMMITTEE_MEMBER,
              SEATED_DIRECTOR)
STAFF = (GOVERNANCE_STAFF, CORPORATE_SECRETARY)


@bp.post("/directors/<director_id>/onboarding-items")
def add_item(director_id):
    require(*STAFF)
    b = body()
    module_code = required(b, "module_code", "string")
    category = required(b, "category", "string")
    is_required = optional(b, "is_required", "boolean", True)
    credit_hours = optional(b, "credit_hours", "number", 0.0)
    due_on = optional(b, "due_on", "string")
    check_enum("category", category, ONBOARDING_CATEGORY)
    check_min("credit_hours", credit_hours, 0.0)
    if due_on is not None:
        parse_date(due_on, "due_on")
    director = need("director", director_id)
    for other in db.onboarding_items.values():
        if other["director_id"] == director_id and other["status"] != "WAIVED" \
                and other["module_code"] == module_code:
            fail("ERR_DUPLICATE_RESOURCE",
                 "Module %s already exists in this director's programme." % module_code)
    row = new_row({
        "director_id": director_id,
        "module_code": module_code,
        "category": category,
        "is_required": is_required,
        "credit_hours": credit_hours,
        "due_on": due_on,
        "status": "PENDING",
        "completed_at": None,
        "waiver_reason": None,
    })
    db.onboarding_items[row["id"]] = row
    recompute_onboarding(director)
    return emit(row, 201)


@bp.get("/directors/<director_id>/onboarding-items")
def list_director_items(director_id):
    require(*READ_ROLES)
    need("director", director_id)
    rows = [i for i in db.onboarding_items.values() if i["director_id"] == director_id]
    rows = apply_filters(rows, {"status": ("status", "str"), "category": ("category", "str")})
    return emit_list(by_created_desc(rows))


@bp.get("/onboarding-items/<item_id>")
def read_item(item_id):
    require(*READ_ROLES)
    return emit(need("onboarding_item", item_id))


@bp.get("/onboarding-items")
def list_items():
    require(*READ_ROLES)
    rows = apply_filters(list(db.onboarding_items.values()), {
        "director_id": ("director_id", "str"),
        "status": ("status", "str"),
        "category": ("category", "str"),
    })
    return emit_list(by_created_desc(rows))


@bp.post("/onboarding-items/<item_id>/complete")
def complete_item(item_id):
    actor = require(GOVERNANCE_STAFF, CORPORATE_SECRETARY, SEATED_DIRECTOR)
    item = need("onboarding_item", item_id)
    require_director_owner(actor, item["director_id"])
    if item["status"] != "PENDING":
        fail("ERR_ONBOARDING_ITEM_STATE_INVALID",
             "Only a PENDING item may be completed; this one is %s." % item["status"])
    item["status"] = "COMPLETED"
    item["completed_at"] = clock_instant()
    touch(item)
    director = db.directors.get(item["director_id"])
    if director is not None:
        recompute_onboarding(director)
        recompute_education_hours(director)
        recompute_compliance(director)
    return emit(item)


@bp.post("/onboarding-items/<item_id>/waive")
def waive_item(item_id):
    require(CORPORATE_SECRETARY)
    b = body()
    reason = required(b, "waiver_reason", "string")
    if reason.strip() == "":
        fail("ERR_INVALID_REQUEST", "Field 'waiver_reason' must be non-empty.")
    item = need("onboarding_item", item_id)
    if item["status"] != "PENDING":
        fail("ERR_ONBOARDING_ITEM_STATE_INVALID",
             "Only a PENDING item may be waived; this one is %s." % item["status"])
    item["status"] = "WAIVED"
    item["waiver_reason"] = reason
    touch(item)
    director = db.directors.get(item["director_id"])
    if director is not None:
        recompute_onboarding(director)
        recompute_education_hours(director)
    return emit(item)
