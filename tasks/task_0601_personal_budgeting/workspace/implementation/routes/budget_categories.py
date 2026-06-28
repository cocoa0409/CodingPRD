"""BudgetCategory routes: create in period, get, list, allocate."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, opt_int, opt_bool, require_int,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_period, get_category
from services.reconcile import (recompute_category, recompute_period_total,
                                recompute_posture)

bp = Blueprint("budget_categories", __name__)


@bp.route("/households/<household_id>/budget-periods/<period_id>/categories",
          methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def create_category(household_id, period_id):
    h = get_household(household_id)
    p = get_period(period_id)
    enforce_household_access(household_id)
    if p["household_id"] != household_id:
        raise errors.not_found("Period not found in household")

    body = get_body()
    name = require_str(body, "name")
    allocated = opt_int(body, "allocated_cents", 0)
    rollover_enabled = opt_bool(body, "rollover_enabled", True)

    with lock:
        # name unique within period.
        for c in db.budget_categories.values():
            if c["budget_period_id"] == period_id and c["name"] == name:
                raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                                      "Category name already exists in period")
        cid = new_id()
        ts = now_ts()
        cat = {
            "id": cid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "budget_period_id": period_id,
            "household_id": household_id,
            "name": name,
            "allocated_cents": allocated,
            "rollover_in_cents": 0,
            "spent_cents": 0,
            "available_cents": 0,
            "envelope_state": "FUNDED",
            "rollover_enabled": rollover_enabled,
        }
        db.budget_categories[cid] = cat
        recompute_category(cat)
        recompute_period_total(p)
    return success(serializers.budget_category(cat), status=201)


@bp.route("/households/budget-categories/<cat_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_category_route(cat_id):
    c = get_category(cat_id)
    enforce_household_access(c["household_id"])
    return success(serializers.budget_category(c), status=200)


@bp.route("/households/budget-categories", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_categories():
    household_id = request.args.get("household_id")
    budget_period_id = request.args.get("budget_period_id")
    envelope_state = request.args.get("envelope_state")
    items = list(db.budget_categories.values())
    if household_id is not None:
        items = [c for c in items if c["household_id"] == household_id]
    if budget_period_id is not None:
        items = [c for c in items if c["budget_period_id"] == budget_period_id]
    if envelope_state is not None:
        items = [c for c in items if c["envelope_state"] == envelope_state]
    return paginate_and_respond(items, serializers.budget_category)


@bp.route("/households/<household_id>/budget-categories/<cat_id>/allocate",
          methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def allocate(household_id, cat_id):
    h = get_household(household_id)
    c = get_category(cat_id)
    enforce_household_access(household_id)
    if c["household_id"] != household_id:
        raise errors.not_found("Category not found in household")

    body = get_body()
    allocated = require_int(body, "allocated_cents")

    # Frozen guard (spend-affecting write).
    if h["posture"] == "FROZEN":
        raise errors.ApiError(errors.ERR_HOUSEHOLD_FROZEN, 409, "Household is frozen")

    with lock:
        c["allocated_cents"] = allocated
        c["updated_at"] = now_ts()
        c["version"] += 1
        recompute_category(c)
        period = db.budget_periods.get(c["budget_period_id"])
        if period is not None:
            recompute_period_total(period)
        recompute_posture(h)
    return success(serializers.budget_category(c), status=200)
