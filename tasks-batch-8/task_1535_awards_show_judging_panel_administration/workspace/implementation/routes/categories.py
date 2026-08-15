"""Category endpoints (get / publish / suspend / retire)."""
from flask import Blueprint, request

import audit
import services
import store
from auth import authenticate, authorize, ALL_ROLES
from errors import raise_err, ERR_INVALID_STATE, ERR_CONSTRAINT_VIOLATION
from util import bump, success_object, get_or_404

bp = Blueprint("categories", __name__)


@bp.get("/awards/categories/<cid>")
def get_category(cid):
    _, role = authenticate()
    authorize(role, ALL_ROLES)
    c = get_or_404(store.categories, cid, "Category")
    return success_object(services.serialize_category(c), 200)


@bp.post("/awards/categories/<cid>/publish")
def publish_category(cid):
    uid, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.categories, cid, "Category")
    services.guard_transition("category", c, {"DRAFT", "SUSPENDED"})
    s = store.seasons.get(c["season_id"])
    if s is None or s["status"] not in ("DRAFT", "OPEN"):
        raise_err(ERR_INVALID_STATE,
                  "parent season must be DRAFT or OPEN to publish a category")
    weight_sum = sum(x["weight_bp"] for x in c["scoring_rubric"])
    if weight_sum != 10000:
        raise_err(ERR_CONSTRAINT_VIOLATION,
                  "scoring_rubric weight_bp values must sum to exactly 10000")
    if c["status"] == "DRAFT":
        if c["panel_size"] < 3:
            raise_err(ERR_CONSTRAINT_VIOLATION, "panel_size must be >= 3")
        if c["finalist_slots"] < 1:
            raise_err(ERR_CONSTRAINT_VIOLATION, "finalist_slots must be >= 1")
        audit.append(c["season_id"], role, uid, "CATEGORY_PUBLISH",
                     "AwardCategory", c["id"],
                     {"before": {"status": "DRAFT"}, "after": {"status": "PUBLISHED"}})
    c["status"] = "PUBLISHED"
    bump(c)
    return success_object(services.serialize_category(c), 200)


@bp.post("/awards/categories/<cid>/suspend")
def suspend_category(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.categories, cid, "Category")
    services.guard_transition("category", c, {"PUBLISHED"})
    s = store.seasons.get(c["season_id"])
    if s is None or s["status"] not in ("DRAFT", "OPEN", "SUBMISSION_CLOSED"):
        raise_err(ERR_INVALID_STATE,
                  "parent season must be DRAFT, OPEN or SUBMISSION_CLOSED to suspend")
    c["status"] = "SUSPENDED"
    bump(c)
    for e in services.entries_of_category(c["id"]):
        if e["status"] == "DRAFT":
            e["status"] = "WITHDRAWN"
            bump(e)
    return success_object(services.serialize_category(c), 200)


@bp.post("/awards/categories/<cid>/retire")
def retire_category(cid):
    _, role = authenticate()
    authorize(role, ["ProgramAdmin"])
    c = get_or_404(store.categories, cid, "Category")
    services.guard_transition("category", c, {"PUBLISHED"})
    s = store.seasons.get(c["season_id"])
    if s is None or s["status"] not in ("PUBLISHED", "ARCHIVED"):
        raise_err(ERR_INVALID_STATE,
                  "parent season must be PUBLISHED or ARCHIVED to retire")
    entry_ids = {e["id"] for e in services.entries_of_category(c["id"])}
    for a in store.appeals.values():
        if a["entry_id"] in entry_ids and a["status"] in ("FILED", "UNDER_REVIEW"):
            raise_err(ERR_INVALID_STATE, "open appeals exist on entries of this category")
    c["status"] = "RETIRED"
    bump(c)
    return success_object(services.serialize_category(c), 200)
