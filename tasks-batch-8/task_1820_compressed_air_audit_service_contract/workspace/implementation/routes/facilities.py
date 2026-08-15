"""Facility lifecycle: create/list/get + activate/suspend/reinstate/offboard."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import recompute_facility_chain
from envelope import ok_object, ok_list
from errors import (
    conflict,
    invalid_state,
    not_found,
    ERR_FACILITY_HAS_OPEN_OBLIGATIONS,
)
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_int, req_str, sort_and_page

bp = Blueprint("facilities", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_facility_or_404(facility_id):
    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")
    return fac


@bp.route("/facilities", methods=["POST"])
def create_facility():
    require_roles(["DealerAdmin"])
    body = body_or_empty()
    name = req_str(body, "name")
    rate = req_int(body, "utility_rate_cents_per_kwh")
    hours = req_int(body, "operating_hours_per_year")
    budget = req_int(body, "repair_budget_cents")

    fac = new_resource()
    fac.update(
        {
            "name": name,
            "utility_rate_cents_per_kwh": rate,
            "operating_hours_per_year": hours,
            "repair_budget_cents": budget,
            "status": "ONBOARDING",
            "posture": "NORMAL",
            "repair_committed_cents": 0,
            "rental_escrow_cents": 0,
        }
    )
    store.facilities[fac["id"]] = fac
    return ok_object(public(fac), 201)


@bp.route("/facilities", methods=["GET"])
def list_facilities():
    require_roles(ALL_ROLES)
    items = list(store.facilities.values())
    status = request.args.get("status")
    posture = request.args.get("posture")
    if status is not None:
        items = [f for f in items if f["status"] == status]
    if posture is not None:
        items = [f for f in items if f["posture"] == posture]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(f) for f in page], limit, offset, total)


@bp.route("/facilities/<facilityId>", methods=["GET"])
def get_facility(facilityId):
    user_id, role = require_roles(ALL_ROLES)
    fac = _get_facility_or_404(facilityId)
    check_ownership(user_id, role, fac["id"])
    return ok_object(public(fac), 200)


@bp.route("/facilities/<facilityId>/activate", methods=["POST"])
def activate_facility(facilityId):
    require_roles(["DealerAdmin"])
    fac = _get_facility_or_404(facilityId)
    if fac["status"] != "ONBOARDING":
        raise invalid_state("Facility must be ONBOARDING to activate")
    fac["status"] = "ACTIVE"
    touch(fac)
    return ok_object(public(fac), 200)


@bp.route("/facilities/<facilityId>/suspend", methods=["POST"])
def suspend_facility(facilityId):
    require_roles(["DealerAdmin"])
    fac = _get_facility_or_404(facilityId)
    if fac["status"] != "ACTIVE":
        raise invalid_state("Facility must be ACTIVE to suspend")
    fac["status"] = "SUSPENDED"
    touch(fac)
    recompute_facility_chain(fac["id"])
    return ok_object(public(fac), 200)


@bp.route("/facilities/<facilityId>/reinstate", methods=["POST"])
def reinstate_facility(facilityId):
    require_roles(["DealerAdmin"])
    fac = _get_facility_or_404(facilityId)
    if fac["status"] != "SUSPENDED":
        raise invalid_state("Facility must be SUSPENDED to reinstate")
    fac["status"] = "ACTIVE"
    touch(fac)
    recompute_facility_chain(fac["id"])
    return ok_object(public(fac), 200)


@bp.route("/facilities/<facilityId>/offboard", methods=["POST"])
def offboard_facility(facilityId):
    require_roles(["DealerAdmin"])
    fac = _get_facility_or_404(facilityId)
    if fac["status"] not in ("ACTIVE", "SUSPENDED"):
        raise invalid_state("Facility must be ACTIVE or SUSPENDED to offboard")
    fid = fac["id"]
    # open-obligations sweep in fixed order: contracts, then rentals, then guarantees
    if any(
        c["facility_id"] == fid and c["status"] in ("DRAFT", "ACTIVE", "SUSPENDED")
        for c in store.service_contracts.values()
    ):
        raise conflict(ERR_FACILITY_HAS_OPEN_OBLIGATIONS, "Facility has non-terminal service contracts")
    if any(
        r["facility_id"] == fid and r["status"] in ("RESERVED", "ON_RENT")
        for r in store.rental_reservations.values()
    ):
        raise conflict(ERR_FACILITY_HAS_OPEN_OBLIGATIONS, "Facility has active rental reservations")
    if any(
        c["facility_id"] == fid and c["settlement_status"] in ("AWAITING_MEASUREMENT", "SETTLED_PAYOUT_DUE")
        for c in store.guarantee_certificates.values()
    ):
        raise conflict(ERR_FACILITY_HAS_OPEN_OBLIGATIONS, "Facility has unsettled guarantee certificates")
    fac["status"] = "OFFBOARDED"
    touch(fac)
    return ok_object(public(fac), 200)
