"""RecurringBill routes: create, get, list, pause, resume.

Slot conflict (PRD §3.7): a new/resumed SCHEDULED bill conflicts with an existing
SCHEDULED bill of the same payee whose day_of_month is within +/-2 days of the new
bill's day_of_month, with the day window cyclically clamped to the 1..28 domain.
"""

from flask import Blueprint, request

import errors
import serializers
from db import db, lock, new_id, now_ts
from middleware import require_roles
from response import success
from helpers import (get_body, require_str, require_int,
                     enforce_household_access, paginate_and_respond)
from lookups import get_household, get_bill

bp = Blueprint("recurring_bills", __name__)

DOMAIN = 28  # day_of_month domain is 1..28


def _cyclic_window(day):
    """Return the set of day-of-month slots within +/-2 of `day`, cyclically
    clamped to the 1..28 domain."""
    slots = set()
    for delta in range(-2, 3):
        v = day + delta
        # Cyclic clamp into 1..28.
        v = ((v - 1) % DOMAIN) + 1
        slots.add(v)
    return slots


def _has_slot_conflict(household_id, payee, day_of_month, exclude_id=None):
    window = _cyclic_window(day_of_month)
    for b in db.recurring_bills.values():
        if b["id"] == exclude_id:
            continue
        if b["household_id"] != household_id:
            continue
        if b["status"] != "SCHEDULED":
            continue
        if b["payee"] != payee:
            continue
        if b["day_of_month"] in window:
            return True
    return False


@bp.route("/households/<household_id>/recurring-bills", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def create_bill(household_id):
    h = get_household(household_id)
    enforce_household_access(household_id)
    body = get_body()
    payee = require_str(body, "payee")
    amount = require_int(body, "amount_cents")
    day_of_month = require_int(body, "day_of_month")
    funding_category_id = require_str(body, "funding_category_id")

    if day_of_month < 1 or day_of_month > 28:
        raise errors.invalid_request("day_of_month must be between 1 and 28")
    if amount <= 0:
        raise errors.invalid_request("amount_cents must be positive")

    # Reference: funding category exists and belongs to household.
    cat = db.budget_categories.get(funding_category_id)
    if cat is None or cat["household_id"] != household_id:
        raise errors.reference_not_found("funding_category_id not found in household")

    with lock:
        if _has_slot_conflict(household_id, payee, day_of_month):
            raise errors.ApiError(errors.ERR_BILL_SLOT_CONFLICT, 409,
                                  "Bill collides with an existing SCHEDULED bill slot")
        bid = new_id()
        ts = now_ts()
        bill = {
            "id": bid,
            "created_at": ts, "updated_at": ts, "version": 1,
            "_seq": db.next_seq(),
            "household_id": household_id,
            "payee": payee,
            "amount_cents": amount,
            "day_of_month": day_of_month,
            "funding_category_id": funding_category_id,
            "status": "SCHEDULED",
        }
        db.recurring_bills[bid] = bill
    return success(serializers.recurring_bill(bill), status=201)


@bp.route("/households/recurring-bills/<bill_id>", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def get_bill_route(bill_id):
    b = get_bill(bill_id)
    enforce_household_access(b["household_id"])
    return success(serializers.recurring_bill(b), status=200)


@bp.route("/households/recurring-bills", methods=["GET"])
@require_roles("HouseholdOwner", "HouseholdMember", "PlatformAdmin")
def list_bills():
    household_id = request.args.get("household_id")
    status = request.args.get("status")
    funding_category_id = request.args.get("funding_category_id")
    items = list(db.recurring_bills.values())
    if household_id is not None:
        items = [b for b in items if b["household_id"] == household_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    if funding_category_id is not None:
        items = [b for b in items if b["funding_category_id"] == funding_category_id]
    return paginate_and_respond(items, serializers.recurring_bill)


@bp.route("/households/<household_id>/recurring-bills/<bill_id>/pause", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def pause_bill(household_id, bill_id):
    h = get_household(household_id)
    b = get_bill(bill_id)
    enforce_household_access(household_id)
    if b["household_id"] != household_id:
        raise errors.not_found("Bill not found in household")
    if b["status"] != "SCHEDULED":
        raise errors.invalid_state("Bill is not SCHEDULED")
    with lock:
        b["status"] = "PAUSED"
        b["updated_at"] = now_ts()
        b["version"] += 1
    return success(serializers.recurring_bill(b), status=200)


@bp.route("/households/<household_id>/recurring-bills/<bill_id>/resume", methods=["POST"])
@require_roles("HouseholdOwner", "HouseholdMember")
def resume_bill(household_id, bill_id):
    h = get_household(household_id)
    b = get_bill(bill_id)
    enforce_household_access(household_id)
    if b["household_id"] != household_id:
        raise errors.not_found("Bill not found in household")
    if b["status"] != "PAUSED":
        raise errors.invalid_state("Bill is not PAUSED")
    with lock:
        if _has_slot_conflict(household_id, b["payee"], b["day_of_month"],
                              exclude_id=bill_id):
            raise errors.ApiError(errors.ERR_BILL_SLOT_CONFLICT, 409,
                                  "Bill collides with an existing SCHEDULED bill slot")
        b["status"] = "SCHEDULED"
        b["updated_at"] = now_ts()
        b["version"] += 1
    return success(serializers.recurring_bill(b), status=200)
