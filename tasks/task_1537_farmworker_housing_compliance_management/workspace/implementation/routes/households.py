"""Households, household members, and eligibility."""

from flask import Blueprint

import clock
import db
from errors import err
from middleware import require_roles, get_auth
from response import success_object, success_list
from services import core
from validate import (
    get_body, require_string, require_int, require_enum, optional_string,
    parse_pagination, get_filter, sort_and_paginate, parse_date_strict,
)

bp = Blueprint("households", __name__)

RELATIONSHIPS = {"HEAD", "SPOUSE", "CHILD", "OTHER"}
ELIGIBILITY_STATUSES = {"PENDING_ELIGIBILITY", "ELIGIBLE", "INELIGIBLE"}


def _view_hh(h):
    return {
        "id": h["id"],
        "head_of_household_name": h["head_of_household_name"],
        "annual_family_income_cents": h["annual_family_income_cents"],
        "ag_work_verified": h["ag_work_verified"],
        "eligibility_status": h["eligibility_status"],
        "eligibility_notes": h["eligibility_notes"],
        "member_count": h["member_count"],
        "minor_count": h["minor_count"],
        "rehousing_priority": h["rehousing_priority"],
        "created_at": h["created_at"],
        "updated_at": h["updated_at"],
        "version": h["version"],
    }


def _view_member(m):
    return {
        "id": m["id"],
        "household_id": m["household_id"],
        "full_name": m["full_name"],
        "date_of_birth": m["date_of_birth"],
        "relationship": m["relationship"],
        "is_minor": m["is_minor"],
        "created_at": m["created_at"],
        "updated_at": m["updated_at"],
        "version": m["version"],
    }


@bp.route("/households", methods=["POST"])
def create_household():
    require_roles("IntakeCoordinator")
    body = get_body()
    name = require_string(body, "head_of_household_name")
    income = require_int(body, "annual_family_income_cents", min_value=0)
    ag = body.get("ag_work_verified", False)
    if not isinstance(ag, bool):
        raise err("ERR_INVALID_REQUEST", "ag_work_verified must be a boolean")
    now = db.now_ts()
    h = {
        "id": db.new_id(),
        "head_of_household_name": name,
        "annual_family_income_cents": income,
        "ag_work_verified": ag,
        "eligibility_status": "PENDING_ELIGIBILITY",
        "eligibility_notes": None,
        "member_count": 0,
        "minor_count": 0,
        "rehousing_priority": False,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.households[h["id"]] = h
    return success_object(_view_hh(h), status=201)


@bp.route("/households", methods=["GET"])
def list_households():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.households.values())
    elig_f = get_filter("eligibility_status")
    if elig_f is not None:
        items = [h for h in items if h["eligibility_status"] == elig_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view_hh(h) for h in page], total, limit, offset)


@bp.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    get_auth()
    h = db.households.get(hid)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")
    return success_object(_view_hh(h))


@bp.route("/households/<hid>", methods=["PUT"])
def drive_household(hid):
    require_roles("IntakeCoordinator")
    body = get_body()
    target = require_enum(body, "eligibility_status", ELIGIBILITY_STATUSES)
    h = db.households.get(hid)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")
    current = h["eligibility_status"]

    allowed = {
        "PENDING_ELIGIBILITY": {"ELIGIBLE", "INELIGIBLE"},
        "INELIGIBLE": {"PENDING_ELIGIBILITY"},
        "ELIGIBLE": {"INELIGIBLE"},
    }
    if target not in allowed.get(current, set()):
        raise err("ERR_INVALID_STATE", f"Cannot move household from {current} to {target}")

    if target == "ELIGIBLE" and not h["ag_work_verified"]:
        raise err("ERR_AG_WORK_NOT_VERIFIED")

    h["eligibility_status"] = target
    if "eligibility_notes" in body:
        h["eligibility_notes"] = optional_string(body, "eligibility_notes")
    h["updated_at"] = db.now_ts()
    h["version"] += 1
    return success_object(_view_hh(h))


@bp.route("/household-members", methods=["POST"])
def create_member():
    require_roles("IntakeCoordinator")
    body = get_body()
    household_id = require_string(body, "household_id")
    full_name = require_string(body, "full_name")
    dob = parse_date_strict(body.get("date_of_birth"), "date_of_birth")
    relationship = require_enum(body, "relationship", RELATIONSHIPS)

    h = db.households.get(household_id)
    if h is None:
        raise err("ERR_HOUSEHOLD_NOT_FOUND")

    # Occupancy re-check: if household holds ACTIVE/NOTICE tenancy, projected
    # occupancy must not exceed the unit cap.
    for t in db.tenancies.values():
        if t["household_id"] == household_id and t["status"] in ("ACTIVE", "NOTICE"):
            unit = db.units.get(t["unit_id"])
            if unit is not None:
                projected = unit["current_occupancy"] + 1
                if projected > unit["max_occupancy"]:
                    raise err("ERR_OCCUPANCY_LIMIT_EXCEEDED")

    today = clock.current_date()
    age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
    now = db.now_ts()
    m = {
        "id": db.new_id(),
        "household_id": household_id,
        "full_name": full_name,
        "date_of_birth": dob.isoformat(),
        "relationship": relationship,
        "is_minor": age < 18,
        "created_at": now,
        "updated_at": now,
        "version": 1,
    }
    db.household_members[m["id"]] = m
    core.recompute_household_counts(household_id)
    # Occupancy recompute for the housed unit.
    for t in db.tenancies.values():
        if t["household_id"] == household_id and t["status"] in ("ACTIVE", "NOTICE"):
            core.recompute_unit_occupancy(t["unit_id"])
    h["updated_at"] = db.now_ts()
    h["version"] += 1
    return success_object(_view_member(m), status=201)


@bp.route("/household-members", methods=["GET"])
def list_members():
    get_auth()
    limit, offset = parse_pagination()
    items = list(db.household_members.values())
    hh_f = get_filter("household_id")
    if hh_f is not None:
        items = [m for m in items if m["household_id"] == hh_f]
    page, total = sort_and_paginate(items, limit, offset)
    return success_list([_view_member(m) for m in page], total, limit, offset)


@bp.route("/household-members/<mid>", methods=["GET"])
def get_member(mid):
    get_auth()
    m = db.household_members.get(mid)
    if m is None:
        raise err("ERR_NOT_FOUND")
    return success_object(_view_member(m))
