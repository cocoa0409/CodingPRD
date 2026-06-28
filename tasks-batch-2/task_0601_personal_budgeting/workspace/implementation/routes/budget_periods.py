"""BudgetPeriod routes: open, get, list, patch income, close (zero-based + OCC)."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int, opt_int,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_period
from services.reconcile import recompute_posture, recompute_category

bp = Blueprint("budget_periods", __name__)


def _next_month(month):
    """month is 'YYYY-MM'. Returns the following month string."""
    try:
        y, m = month.split("-")
        y = int(y)
        m = int(m)
    except Exception:
        return month  # fallback; well-formed months expected
    m += 1
    if m > 12:
        m = 1
        y += 1
    return "%04d-%02d" % (y, m)


@bp.route("/households/<household_id>/budget-periods", methods=["POST"])
@require_roles("HouseholdOwner")
def open_period(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    month = require_str(body, "month")
    income = opt_int(body, "income_expected_cents", 0)

    with lock:
        # month unique within household.
        for p in db.budget_periods.values():
            if p["household_id"] == household_id and p["month"] == month:
                raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                                      "Period month already exists in household")
        # only one OPEN period per household.
        for p in db.budget_periods.values():
            if p["household_id"] == household_id and p["status"] == "OPEN":
                raise errors.ApiError(errors.ERR_DUPLICATE_RESOURCE, 409,
                                      "Household already has an OPEN period")
        pid = new_id()
        ts = now_ts()
        period = {
            "id": pid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "month": month,
            "status": "OPEN",
            "income_expected_cents": income,
            "total_allocated_cents": 0,
        }
        db.budget_periods[pid] = period
        if h.get("current_period_id") is None:
            h["current_period_id"] = pid
            h["updated_at"] = now_ts()
            h["version"] += 1
    return success(serializers.budget_period(period), status=201)


@bp.route("/households/budget-periods/<period_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_period_route(period_id):
    p = get_period(period_id)
    enforce_household_access(p["household_id"])
    return success(serializers.budget_period(p), status=200)


@bp.route("/households/budget-periods", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_periods():
    household_id = request.args.get("household_id")
    status = request.args.get("status")
    items = list(db.budget_periods.values())
    if household_id is not None:
        items = [p for p in items if p["household_id"] == household_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    return paginate_and_respond(items, serializers.budget_period)


@bp.route("/households/<household_id>/budget-periods/<period_id>", methods=["PATCH"])
@require_roles("HouseholdOwner")
def patch_period(household_id, period_id):
    h = get_household(household_id)
    p = get_period(period_id)
    enforce_household_access(household_id)
    if p["household_id"] != household_id:
        raise errors.not_found("Period not found in household")
    body = get_body()
    income = require_int(body, "income_expected_cents")
    with lock:
        p["income_expected_cents"] = income
        p["updated_at"] = now_ts()
        p["version"] += 1
    return success(serializers.budget_period(p), status=200)


@bp.route("/households/<household_id>/budget-periods/<period_id>/close", methods=["POST"])
@require_roles("HouseholdOwner")
def close_period(household_id, period_id):
    h = get_household(household_id)
    p = get_period(period_id)
    enforce_household_access(household_id)
    if p["household_id"] != household_id:
        raise errors.not_found("Period not found in household")

    body = get_body()
    expected_version = require_int(body, "expected_household_version")

    # State: must be the household's current period (and OPEN).
    if p["status"] != "OPEN" or h.get("current_period_id") != period_id:
        raise errors.invalid_state("Period is not the current OPEN period")

    # Zero-based check (before OCC per §2.7 ordering: zero-based then OCC).
    if p["total_allocated_cents"] != p["income_expected_cents"]:
        raise errors.ApiError(errors.ERR_BUDGET_NOT_ZERO_BASED, 422,
                              "total_allocated_cents must equal income_expected_cents")

    # OCC check.
    if expected_version != h["version"]:
        raise errors.ApiError(errors.ERR_STALE_HOUSEHOLD, 412,
                              "expected_household_version does not match")

    with lock:
        p["status"] = "CLOSED"
        p["updated_at"] = now_ts()
        p["version"] += 1

        # Mint next OPEN period.
        npid = new_id()
        ts = now_ts()
        new_period = {
            "id": npid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "month": _next_month(p["month"]),
            "status": "OPEN",
            "income_expected_cents": 0,
            "total_allocated_cents": 0,
        }
        db.budget_periods[npid] = new_period

        h["current_period_id"] = npid
        h["updated_at"] = now_ts()
        h["version"] += 1

        # Rollover: for each rollover-enabled category with available_cents > 0,
        # create a same-named category in the new period with rollover_in_cents.
        closing_cats = [c for c in db.budget_categories.values()
                        if c["budget_period_id"] == period_id]
        closing_cats.sort(key=lambda c: (c["created_at"], c.get("_seq", 0)))
        for c in closing_cats:
            if c["rollover_enabled"] and c["available_cents"] > 0:
                cid = new_id()
                cts = now_ts()
                rolled = {
                    "id": cid,
                    "created_at": cts, "updated_at": cts, "version": 1,
                    "_seq": db.next_seq(),
                    "budget_period_id": npid,
                    "household_id": household_id,
                    "name": c["name"],
                    "allocated_cents": 0,
                    "rollover_in_cents": c["available_cents"],
                    "spent_cents": 0,
                    "available_cents": 0,
                    "envelope_state": "FUNDED",
                    "rollover_enabled": c["rollover_enabled"],
                }
                db.budget_categories[cid] = rolled
                recompute_category(rolled)

        # Recompute new period total (rolled categories have allocated 0) and posture.
        new_period["total_allocated_cents"] = 0
        recompute_posture(h)
    return success(serializers.budget_period(p), status=200)
