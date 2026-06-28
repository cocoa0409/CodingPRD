"""Unit endpoints incl. lease and disqualify (PRD §3.1, §3.4, §3.9)."""

from flask import Blueprint, g, request

import errors
import middleware
import response
import serializers
import validate
from clock import clock
from db import db, new_id, stamp_create, touch
from services import calc, domain

bp = Blueprint("units", __name__)

AMI_DESIGNATIONS = {"AMI_40", "AMI_50", "AMI_60", "AMI_80", "MARKET"}


@bp.route("/units", methods=["POST"])
def create_unit():
    middleware.require_role("OwnerAgent")
    body = validate.get_json_body()
    building_id = validate.as_str(body, "building_id")
    unit_number = validate.as_str(body, "unit_number")
    bedroom_count = validate.as_int(body, "bedroom_count", minimum=0, maximum=3)
    sqft = validate.as_int(body, "sqft", minimum=1)
    utility_allowance = validate.as_int(body, "utility_allowance_cents", minimum=0)
    ami_designation = validate.as_enum(body, "ami_designation", AMI_DESIGNATIONS)

    building = db.buildings.get(building_id)
    if building is None:
        raise errors.not_found("Building not found")
    project = db.projects.get(building["project_id"])

    unit = {
        "id": new_id(),
        "building_id": building_id,
        "unit_number": unit_number,
        "bedroom_count": bedroom_count,
        "sqft": sqft,
        "utility_allowance_cents": utility_allowance,
        "ami_designation": ami_designation,
        "income_limit_cents": None,
        "gross_rent_ceiling_cents": None,
        "net_max_rent_cents": None,
        "li_status": "VACANT_NEVER_OCCUPIED",
        "is_low_income_counted": False,
    }
    if ami_designation != "MARKET" and project is not None:
        il, grc, nmr = calc.unit_income_and_rent_limits(
            project["area_median_income_cents"], ami_designation, bedroom_count, utility_allowance
        )
        unit["income_limit_cents"] = il
        unit["gross_rent_ceiling_cents"] = grc
        unit["net_max_rent_cents"] = nmr

    stamp_create(unit)
    db.units[unit["id"]] = unit
    return response.success(serializers.public(unit), status=201)


@bp.route("/units", methods=["GET"])
def list_units():
    middleware.require_role("OwnerAgent", "StateHFA")
    limit, offset = validate.parse_pagination()
    building_id = request.args.get("building_id")
    items = list(db.units.values())
    if building_id is not None:
        items = [u for u in items if u["building_id"] == building_id]
    items = serializers.sort_by_created(items)
    page, meta = validate.paginate(items, limit, offset)
    return response.success(serializers.public_list(page), status=200, pagination=meta)


@bp.route("/units/<uid>", methods=["GET"])
def get_unit(uid):
    middleware.require_role("OwnerAgent", "StateHFA")
    unit = db.units.get(uid)
    if unit is None:
        raise errors.not_found("Unit not found")
    return response.success(serializers.public(unit), status=200)


@bp.route("/units/<uid>/lease", methods=["POST"])
def lease_unit(uid):
    middleware.require_role("OwnerAgent")
    unit = db.units.get(uid)
    if unit is None:
        raise errors.not_found("Unit not found")
    body = validate.get_json_body()
    household_id = validate.as_str(body, "household_id")
    monthly_rent = validate.as_int(body, "monthly_rent_cents", minimum=0)
    rent_start = validate.as_datetime(body, "rent_start_date")
    rent_end = validate.as_datetime(body, "rent_end_date")

    household = db.households.get(household_id)
    if household is None:
        raise errors.not_found("Household not found")

    new_start = domain.parse_dt(rent_start)
    new_end = domain.parse_dt(rent_end)

    # Priority 8.5: occupancy interval overlap (half-open, zero-buffer).
    for lease in db.leases.values():
        if lease["unit_id"] != uid or lease["status"] != "ACTIVE":
            continue
        e_start = domain.parse_dt(lease["rent_start_date"])
        e_end = domain.parse_dt(lease["rent_end_date"])
        if domain.lease_overlaps(new_start, new_end, e_start, e_end):
            raise errors.ApiError(errors.ERR_LEASE_OVERLAP, 409, "Lease occupancy interval overlaps")

    # Priority 9: rent must not exceed unit.net_max_rent_cents (non-MARKET units only).
    net_max = unit.get("net_max_rent_cents")
    if net_max is not None and monthly_rent > net_max:
        raise errors.ApiError(errors.ERR_RENT_OVER_LIMIT, 422, "Rent exceeds the net rent ceiling")

    # Priority 10: available-unit rule. While any unit in the building is OVER_INCOME,
    # a comparable-or-smaller unit may not be leased to a non-qualified household.
    if _available_unit_rule_violated(unit, household):
        raise errors.ApiError(
            errors.ERR_AVAILABLE_UNIT_RULE, 409,
            "Available-unit rule blocks this lease while an over-income unit exists",
        )

    lease = {
        "id": new_id(),
        "household_id": household_id,
        "unit_id": uid,
        "monthly_rent_cents": monthly_rent,
        "rent_start_date": rent_start,
        "rent_end_date": rent_end,
        "status": "ACTIVE",
    }
    stamp_create(lease)
    db.leases[lease["id"]] = lease

    # MARKET unit -> li_status MARKET_RENTED.
    if unit["ami_designation"] == "MARKET" and unit["li_status"] == "VACANT_NEVER_OCCUPIED":
        unit["li_status"] = "MARKET_RENTED"
        touch(unit)

    return response.success(serializers.public(lease), status=201)


def _household_qualified(household):
    """A household is non-qualified if it is student-ineligible. (A MARKET unit is the
    other non-qualified trigger, handled separately on the unit side.)"""
    return household.get("student_eligible", True)


def _available_unit_rule_violated(unit, household):
    building_units = domain.units_for_building(unit["building_id"])
    over_income = [u for u in building_units if u["li_status"] == "OVER_INCOME"]
    if not over_income:
        return False
    # Non-qualified household = MARKET unit (the targeted unit is MARKET) OR a
    # student-ineligible household.
    is_market_unit = unit["ami_designation"] == "MARKET"
    non_qualified = is_market_unit or (not _household_qualified(household))
    if not non_qualified:
        return False
    # Comparable-or-smaller: target unit bedroom_count <= some over-income unit's.
    for oi in over_income:
        if unit["bedroom_count"] <= oi["bedroom_count"]:
            return True
    return False


@bp.route("/units/<uid>/disqualify", methods=["POST"])
def disqualify_unit(uid):
    middleware.require_role("StateHFA")
    unit = db.units.get(uid)
    if unit is None:
        raise errors.not_found("Unit not found")
    body = validate.get_json_body()
    if unit["li_status"] not in ("QUALIFIED", "OVER_INCOME"):
        raise errors.invalid_state("Unit must be QUALIFIED or OVER_INCOME to disqualify")
    discovered_on = validate.as_datetime(body, "discovered_on")

    unit["li_status"] = "DISQUALIFIED"
    unit["is_low_income_counted"] = False
    touch(unit)

    building = db.buildings.get(unit["building_id"])
    if building is not None:
        domain.reconcile_building(building)
        domain.create_finding(
            project_id=building["project_id"],
            building_id=building["id"],
            inspection_id=None,
            category="AVAILABLE_UNIT_VIOLATION",
            discovered_on=discovered_on,
            origin_agent_id=g.user_id,
        )
    return response.success(serializers.public(unit), status=200)
