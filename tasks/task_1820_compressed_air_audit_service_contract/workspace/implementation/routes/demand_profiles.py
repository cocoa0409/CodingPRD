"""Demand profiles: create/list/get + OCC-guarded lock with supersede cascade."""

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import annualized_kwh, window_days
from envelope import ok_object, ok_list
from errors import (
    ApiError,
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_MEASUREMENT_WINDOW_OVERLAP,
    ERR_STALE_VERSION,
)
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_date, req_int, req_num, req_str, sort_and_page

bp = Blueprint("demand_profiles", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_or_404(profile_id):
    prof = store.demand_profiles.get(profile_id)
    if prof is None:
        raise not_found("DemandProfile not found")
    return prof


@bp.route("/demand-profiles", methods=["POST"])
def create_profile():
    require_roles(["EnergyEngineer"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    start = req_date(body, "window_start_date")
    end = req_date(body, "window_end_date")
    measured_kwh = req_int(body, "measured_kwh")
    avg_cfm = req_num(body, "measured_avg_cfm")
    peak_cfm = req_num(body, "measured_peak_cfm")

    if end < start:
        raise invalid_request("window_end_date may not precede window_start_date")

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")

    # closed-closed window overlap vs COLLECTING/LOCKED profiles of this facility
    for other in store.demand_profiles.values():
        if other["facility_id"] != facility_id:
            continue
        if other["status"] not in ("COLLECTING", "LOCKED"):
            continue
        o_start = store_date(other["window_start_date"])
        o_end = store_date(other["window_end_date"])
        if start <= o_end and o_start <= end:
            raise conflict(
                ERR_MEASUREMENT_WINDOW_OVERLAP,
                "Measurement window intersects another COLLECTING/LOCKED profile of this facility",
            )

    days = window_days(start, end)
    prof = new_resource()
    prof.update(
        {
            "facility_id": facility_id,
            "window_start_date": start.isoformat(),
            "window_end_date": end.isoformat(),
            "measured_kwh": measured_kwh,
            "measured_avg_cfm": float(avg_cfm) if isinstance(avg_cfm, int) else avg_cfm,
            "measured_peak_cfm": float(peak_cfm) if isinstance(peak_cfm, int) else peak_cfm,
            "baseline_annual_kwh": annualized_kwh(measured_kwh, days),
            "status": "COLLECTING",
            "locked_by_user_id": None,
            "superseded_by_id": None,
        }
    )
    store.demand_profiles[prof["id"]] = prof
    return ok_object(public(prof), 201)


def store_date(s):
    from datetime import date as _date

    return _date.fromisoformat(s)


@bp.route("/demand-profiles", methods=["GET"])
def list_profiles():
    require_roles(ALL_ROLES)
    items = list(store.demand_profiles.values())
    facility_id = request.args.get("facility_id")
    status = request.args.get("status")
    superseded_by_id = request.args.get("superseded_by_id")
    if facility_id is not None:
        items = [p for p in items if p["facility_id"] == facility_id]
    if status is not None:
        items = [p for p in items if p["status"] == status]
    if superseded_by_id is not None:
        items = [p for p in items if p["superseded_by_id"] == superseded_by_id]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(p) for p in page], limit, offset, total)


@bp.route("/demand-profiles/<demandProfileId>", methods=["GET"])
def get_profile(demandProfileId):
    user_id, role = require_roles(ALL_ROLES)
    prof = _get_or_404(demandProfileId)
    check_ownership(user_id, role, prof["facility_id"])
    return ok_object(public(prof), 200)


@bp.route("/demand-profiles/<demandProfileId>/lock", methods=["POST"])
def lock_profile(demandProfileId):
    user_id, _role = require_roles(["EnergyEngineer"])
    prof = _get_or_404(demandProfileId)
    body = body_or_empty()
    if "expected_facility_version" not in body or body["expected_facility_version"] is None:
        raise invalid_request("Missing required field: expected_facility_version")
    expected = body["expected_facility_version"]
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise invalid_request("Field expected_facility_version must be an integer")

    if prof["status"] != "COLLECTING":
        raise invalid_state("DemandProfile must be COLLECTING to lock")

    fac = store.facilities.get(prof["facility_id"])
    if fac is None or fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to lock a profile")

    if expected != fac["version"]:
        raise ApiError(ERR_STALE_VERSION, 412, "expected_facility_version does not match Facility.version")

    # Lock this profile
    prof["status"] = "LOCKED"
    prof["locked_by_user_id"] = user_id
    touch(prof)

    # Supersede the facility's previously LOCKED profile, flag stale savings cases
    for other in store.demand_profiles.values():
        if other["facility_id"] == fac["id"] and other["status"] == "LOCKED" and other["id"] != prof["id"]:
            other["status"] = "SUPERSEDED"
            other["superseded_by_id"] = prof["id"]
            touch(other)
            for case in store.savings_cases.values():
                if (
                    case["baseline_profile_id"] == other["id"]
                    and case["savings_status"] in ("DRAFT", "MODELED")
                    and not case["baseline_stale"]
                ):
                    case["baseline_stale"] = True
                    touch(case)

    # OCC: the lock advances Facility.version by 1
    touch(fac)
    return ok_object(public(prof), 200)
