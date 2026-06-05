"""Household, HouseholdMember, IncomeSource, Asset endpoints (PRD §3.2)."""
from __future__ import annotations

from flask import Blueprint

import db
import services
from common import (
    stamp_create, touch, serialize, serialize_list, sort_by_created,
    require_str, require_int, require_enum, optional_bool, optional_int,
    get_or_404,
)
from errors import APIError, ERR_NOT_FOUND
from middleware import authenticate, get_json_body, parse_pagination, paginate
from response import ok_object, ok_array

bp = Blueprint("households", __name__)

RELATIONSHIPS = {"SELF", "SPOUSE", "CHILD", "DEPENDENT", "OTHER"}
INCOME_TYPES = {"WAGES", "SELF_EMPLOYMENT", "SOCIAL_SECURITY", "CHILD_SUPPORT", "TANF", "GIFT"}
ASSET_TYPES = {"CASH", "BANK_ACCOUNT", "VEHICLE", "HOME", "RETIREMENT", "BURIAL_FUND"}


# --- Household --------------------------------------------------------------

@bp.post("/households")
def create_household():
    authenticate(["Applicant", "CaseWorker"])
    body = get_json_body()

    state_code = require_str(body, "state_code")
    fpl_year = require_int(body, "fpl_year")
    primary_applicant_name = require_str(body, "primary_applicant_name")

    # Existence (priority 3): FK -> StateRule.state_code, FplSchedule.year.
    if state_code not in db.state_rules:
        raise APIError(ERR_NOT_FOUND, 404, "StateRule not found")
    if fpl_year not in db.fpl_by_year:
        raise APIError(ERR_NOT_FOUND, 404, "FplSchedule not found")

    rec = {
        "state_code": state_code,
        "fpl_year": fpl_year,
        "household_size": 0,
        "primary_applicant_name": primary_applicant_name,
        "covered_member_months": 0,
        "active_enrollment_count": 0,
    }
    stamp_create(rec)
    db.households[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/households/<hid>")
def get_household(hid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    rec = get_or_404(db.households, hid, "Household")
    return ok_object(serialize(rec), 200)


# --- HouseholdMember --------------------------------------------------------

@bp.post("/households/<hid>/members")
def add_member(hid):
    authenticate(["Applicant", "CaseWorker"])
    hh = get_or_404(db.households, hid, "Household")
    body = get_json_body()

    rec = {
        "household_id": hid,
        "full_name": require_str(body, "full_name"),
        "age": require_int(body, "age", non_negative=True),
        "relationship": require_enum(body, "relationship", RELATIONSHIPS),
        "is_disabled": optional_bool(body, "is_disabled", False),
        "member_status": "COUNTED",
    }
    stamp_create(rec)
    db.members[rec["id"]] = rec
    services.recompute_household_size(hid)
    return ok_object(serialize(rec), 201)


@bp.get("/members/<mid>")
def get_member(mid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    rec = get_or_404(db.members, mid, "HouseholdMember")
    return ok_object(serialize(rec), 200)


@bp.get("/households/<hid>/members")
def list_members(hid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    get_or_404(db.households, hid, "Household")
    limit, offset = parse_pagination()
    items = sort_by_created([m for m in db.members.values() if m["household_id"] == hid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


@bp.post("/members/<mid>/exclude")
def exclude_member(mid):
    authenticate(["CaseWorker"])
    rec = get_or_404(db.members, mid, "HouseholdMember")
    rec["member_status"] = "EXCLUDED"
    touch(rec)
    services.recompute_household_size(rec["household_id"])
    return ok_object(serialize(rec), 200)


# --- IncomeSource -----------------------------------------------------------

@bp.post("/members/<mid>/income-sources")
def add_income_source(mid):
    authenticate(["Applicant", "CaseWorker"])
    member = get_or_404(db.members, mid, "HouseholdMember")
    body = get_json_body()

    income_type = require_enum(body, "income_type", INCOME_TYPES)
    monthly = require_int(body, "monthly_amount_cents", non_negative=True)
    projected = optional_int(body, "projected_annual_cents", None, non_negative=True)
    if projected is None:
        projected = monthly * 12

    rec = {
        "member_id": mid,
        "income_type": income_type,
        "monthly_amount_cents": monthly,
        "is_magi_countable": services.is_income_countable(income_type),
        "projected_annual_cents": projected,
    }
    stamp_create(rec)
    db.income_sources[rec["id"]] = rec
    return ok_object(serialize(rec), 201)


@bp.get("/members/<mid>/income-sources")
def list_income_sources(mid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    get_or_404(db.members, mid, "HouseholdMember")
    limit, offset = parse_pagination()
    items = sort_by_created([s for s in db.income_sources.values() if s["member_id"] == mid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)


# --- Asset ------------------------------------------------------------------

@bp.post("/households/<hid>/assets")
def add_asset(hid):
    authenticate(["Applicant", "CaseWorker"])
    get_or_404(db.households, hid, "Household")
    body = get_json_body()

    rec = {
        "household_id": hid,
        "asset_type": require_enum(body, "asset_type", ASSET_TYPES),
        "value_cents": require_int(body, "value_cents", non_negative=True),
    }
    stamp_create(rec)
    db.assets[rec["id"]] = rec
    # Derive is_exempt + countable_value_cents now; adding a vehicle may flip
    # which vehicle is the exempt highest-value one, so recompute the whole set.
    services.refresh_household_assets_derived(hid)
    return ok_object(serialize(rec), 201)


@bp.get("/households/<hid>/assets")
def list_assets(hid):
    authenticate(["Applicant", "CaseWorker", "HearingOfficer"])
    get_or_404(db.households, hid, "Household")
    limit, offset = parse_pagination()
    items = sort_by_created([a for a in db.assets.values() if a["household_id"] == hid])
    page, total = paginate(items, limit, offset)
    return ok_array(serialize_list(page), limit, offset, total)
