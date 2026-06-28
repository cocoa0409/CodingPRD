"""CategoryRule routes: create, get, list."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int, opt_bool,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_rule

bp = Blueprint("category_rules", __name__)


@bp.route("/households/<household_id>/category-rules", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def create_rule(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    match_substring = require_str(body, "match_substring")
    budget_category_id = require_str(body, "budget_category_id")
    priority = require_int(body, "priority")
    enabled = opt_bool(body, "enabled", True)

    # Reference: budget_category_id must exist and belong to same household.
    cat = db.budget_categories.get(budget_category_id)
    if cat is None or cat["household_id"] != household_id:
        raise errors.reference_not_found("budget_category_id not found in household")

    with lock:
        rid = new_id()
        ts = now_ts()
        rule = {
            "id": rid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "match_substring": match_substring,
            "budget_category_id": budget_category_id,
            "priority": priority,
            "enabled": enabled,
        }
        db.category_rules[rid] = rule
    return success(serializers.category_rule(rule), status=201)


@bp.route("/households/category-rules/<rule_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember")
def get_rule_route(rule_id):
    r = get_rule(rule_id)
    enforce_household_access(r["household_id"])
    return success(serializers.category_rule(r), status=200)


@bp.route("/households/category-rules", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember")
def list_rules():
    household_id = request.args.get("household_id")
    budget_category_id = request.args.get("budget_category_id")
    items = list(db.category_rules.values())
    if household_id is not None:
        items = [r for r in items if r["household_id"] == household_id]
    if budget_category_id is not None:
        items = [r for r in items if r["budget_category_id"] == budget_category_id]
    return paginate_and_respond(items, serializers.category_rule)
