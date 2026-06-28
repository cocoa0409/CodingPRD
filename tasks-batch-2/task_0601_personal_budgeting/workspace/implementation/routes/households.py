"""Household routes: create, get, freeze, unfreeze, cash-flow-forecast."""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, opt_str, enforce_household_access)
from lookups import get_household
from services.reconcile import recompute_posture
from services.forecast import compute_forecast

bp = Blueprint("households", __name__)

CURRENCIES = {"USD", "EUR", "GBP"}


@bp.route("/households", methods=["POST"])
@require_roles("PlatformAdmin")
def create_household():
    body = get_body()
    name = require_str(body, "name")
    owner_email = require_str(body, "owner_email")
    owner_display_name = require_str(body, "owner_display_name")
    base_currency = opt_str(body, "base_currency", "USD")
    if base_currency not in CURRENCIES:
        raise errors.invalid_request("base_currency must be one of USD, EUR, GBP")

    with lock:
        hid = new_id()
        ts = now_ts()
        member_id = new_id()
        household = {
            "id": hid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "name": name,
            "base_currency": base_currency,
            "owner_member_id": member_id,
            "current_period_id": None,
            "posture": "HEALTHY",
            "net_worth_cents": 0,
            "projected_net_worth_cents": 0,
            "frozen_by_owner": False,
        }
        member = {
            "id": member_id,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": hid,
            "email": owner_email,
            "display_name": owner_display_name,
            "role": "OWNER",
        }
        db.households[hid] = household
        db.members[member_id] = member
    return success(serializers.household(household), status=201)


@bp.route("/households/<household_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_household_route(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    return success(serializers.household(h), status=200)


@bp.route("/households/<household_id>/freeze", methods=["POST"])
@require_roles("HouseholdOwner")
def freeze(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    with lock:
        h["frozen_by_owner"] = True
        h["updated_at"] = now_ts()
        h["version"] += 1
        recompute_posture(h)
    return success(serializers.household(h), status=200)


@bp.route("/households/<household_id>/unfreeze", methods=["POST"])
@require_roles("HouseholdOwner")
def unfreeze(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    with lock:
        h["frozen_by_owner"] = False
        h["updated_at"] = now_ts()
        h["version"] += 1
        recompute_posture(h)
    return success(serializers.household(h), status=200)


@bp.route("/households/<household_id>/cash-flow-forecast", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember")
def cash_flow_forecast(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)

    raw_horizon = request.args.get("horizon_days")
    if raw_horizon is None:
        raise errors.invalid_request("horizon_days is required")
    try:
        horizon = int(raw_horizon)
    except (ValueError, TypeError):
        raise errors.invalid_request("horizon_days must be an integer")
    if horizon < 1 or horizon > 90:
        raise errors.invalid_request("horizon_days must be between 1 and 90")

    include_pending = False
    raw_ip = request.args.get("include_pending")
    if raw_ip is not None:
        if raw_ip.lower() == "true":
            include_pending = True
        elif raw_ip.lower() == "false":
            include_pending = False
        else:
            raise errors.invalid_request("include_pending must be a boolean")

    result = compute_forecast(h, horizon, include_pending)
    return success(result, status=200)
