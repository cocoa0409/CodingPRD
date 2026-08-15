"""Rental fleet assets and reservations with overlap buffer + selector."""

from datetime import timedelta

from flask import Blueprint, request

from auth import require_roles, check_ownership
from domain import (
    active_contract_of,
    asset_has_buffered_overlap,
    latest_nonterminal_contract_of,
    rental_actual_bill,
    select_rental_asset,
)
from envelope import ok_object, ok_list
from errors import (
    conflict,
    invalid_request,
    invalid_state,
    not_found,
    unprocessable,
    ERR_COMPRESSOR_NOT_DOWN,
    ERR_CONTRACT_SUSPENDED,
    ERR_CONTRACT_TIER_INELIGIBLE,
    ERR_DUPLICATE_FLEET_TAG,
    ERR_FACILITY_MISMATCH,
    ERR_FACILITY_NOT_ACTIVE,
    ERR_NO_ACTIVE_CONTRACT,
    ERR_NO_RENTAL_ASSET_AVAILABLE,
    ERR_RENTAL_ASSET_UNAVAILABLE,
    ERR_RENTAL_DATE_RANGE_INVALID,
)
import store
from store import new_resource, touch
from util import body_or_empty, parse_pagination, public, req_bool, req_date, req_int, req_str, sort_and_page

bp = Blueprint("rentals", __name__)

ALL_ROLES = ["DealerAdmin", "EnergyEngineer", "ServiceTech", "ContractManager", "FacilityManager"]


def _get_asset_or_404(asset_id):
    asset = store.rental_assets.get(asset_id)
    if asset is None:
        raise not_found("RentalAsset not found")
    return asset


def _get_reservation_or_404(reservation_id):
    res = store.rental_reservations.get(reservation_id)
    if res is None:
        raise not_found("RentalReservation not found")
    return res


# ---------------------------------------------------------------------------
# RentalAsset
# ---------------------------------------------------------------------------

@bp.route("/rental-assets", methods=["POST"])
def create_asset():
    require_roles(["DealerAdmin"])
    body = body_or_empty()
    fleet_tag = req_str(body, "fleet_tag")
    rated_cfm = req_int(body, "rated_cfm")
    daily_rate = req_int(body, "daily_rate_cents")
    deposit = req_int(body, "deposit_cents")

    if any(a["fleet_tag"] == fleet_tag for a in store.rental_assets.values()):
        raise conflict(ERR_DUPLICATE_FLEET_TAG, "fleet_tag already in use")

    asset = new_resource()
    asset.update(
        {
            "fleet_tag": fleet_tag,
            "rated_cfm": rated_cfm,
            "daily_rate_cents": daily_rate,
            "deposit_cents": deposit,
            "status": "AVAILABLE",
            "next_available_date": None,
        }
    )
    store.rental_assets[asset["id"]] = asset
    return ok_object(public(asset), 201)


@bp.route("/rental-assets", methods=["GET"])
def list_assets():
    require_roles(ALL_ROLES)
    items = list(store.rental_assets.values())
    status = request.args.get("status")
    min_rated_cfm = request.args.get("min_rated_cfm")
    if status is not None:
        items = [a for a in items if a["status"] == status]
    if min_rated_cfm is not None:
        try:
            threshold = int(min_rated_cfm)
        except (TypeError, ValueError):
            raise invalid_request("Query parameter min_rated_cfm must be an integer")
        items = [a for a in items if a["rated_cfm"] >= threshold]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(a) for a in page], limit, offset, total)


@bp.route("/rental-assets/<rentalAssetId>", methods=["GET"])
def get_asset(rentalAssetId):
    require_roles(ALL_ROLES)
    asset = _get_asset_or_404(rentalAssetId)
    return ok_object(public(asset), 200)


@bp.route("/rental-assets/<rentalAssetId>/set-maintenance", methods=["POST"])
def set_maintenance(rentalAssetId):
    require_roles(["ServiceTech", "DealerAdmin"])
    asset = _get_asset_or_404(rentalAssetId)
    body = body_or_empty()
    in_maintenance = req_bool(body, "in_maintenance")

    if in_maintenance:
        if asset["status"] != "AVAILABLE":
            raise invalid_state("RentalAsset must be AVAILABLE to enter maintenance")
        if any(
            r["rental_asset_id"] == asset["id"] and r["status"] in ("RESERVED", "ON_RENT")
            for r in store.rental_reservations.values()
        ):
            raise conflict(ERR_RENTAL_ASSET_UNAVAILABLE, "Asset has an active reservation")
        asset["status"] = "IN_MAINTENANCE"
        asset["next_available_date"] = None
    else:
        if asset["status"] != "IN_MAINTENANCE":
            raise invalid_state("RentalAsset must be IN_MAINTENANCE to leave maintenance")
        asset["status"] = "AVAILABLE"
    touch(asset)
    return ok_object(public(asset), 200)


# ---------------------------------------------------------------------------
# RentalReservation
# ---------------------------------------------------------------------------

@bp.route("/rental-reservations", methods=["POST"])
def create_reservation():
    user_id, role = require_roles(["FacilityManager"])
    body = body_or_empty()
    facility_id = req_str(body, "facility_id")
    down_compressor_id = req_str(body, "down_compressor_id")
    start = req_date(body, "start_date")
    end = req_date(body, "end_date")
    explicit_asset_id = None
    if "rental_asset_id" in body and body["rental_asset_id"] is not None:
        explicit_asset_id = body["rental_asset_id"]
        if not isinstance(explicit_asset_id, str):
            raise invalid_request("Field rental_asset_id must be a string")

    fac = store.facilities.get(facility_id)
    if fac is None:
        raise not_found("Facility not found")
    check_ownership(user_id, role, facility_id)

    # tier 6 state gates, in order
    if fac["status"] != "ACTIVE":
        raise conflict(ERR_FACILITY_NOT_ACTIVE, "Facility must be ACTIVE to reserve a rental")

    contract = active_contract_of(facility_id)
    if contract is None:
        latest = latest_nonterminal_contract_of(facility_id)
        if latest is not None and latest["status"] == "SUSPENDED":
            raise conflict(ERR_CONTRACT_SUSPENDED, "Facility's latest non-terminal contract is SUSPENDED")
        raise conflict(ERR_NO_ACTIVE_CONTRACT, "Facility has no ACTIVE service contract")

    comp = store.compressors.get(down_compressor_id)
    if comp is None or comp["status"] != "DOWN":
        raise conflict(ERR_COMPRESSOR_NOT_DOWN, "down_compressor_id must reference a DOWN compressor")

    # tier 7 referential integrity
    if comp["facility_id"] != facility_id:
        raise conflict(ERR_FACILITY_MISMATCH, "down_compressor_id must belong to the calling facility")

    # tier 8 temporal: explicit-choice gates + buffered overlap, then date range
    asset = None
    if explicit_asset_id is not None:
        asset = store.rental_assets.get(explicit_asset_id)
        if (
            asset is None
            or asset["status"] != "AVAILABLE"
            or asset["rated_cfm"] < comp["rated_cfm"]
        ):
            raise conflict(
                ERR_RENTAL_ASSET_UNAVAILABLE,
                "Explicit rental asset must exist, be AVAILABLE, and be sufficiently sized",
            )
        if asset_has_buffered_overlap(asset["id"], start, end):
            raise conflict(ERR_RENTAL_ASSET_UNAVAILABLE, "Rental asset has a buffered overlap conflict")

    if end < start:
        raise unprocessable(ERR_RENTAL_DATE_RANGE_INVALID, "end_date may not precede start_date")

    # tier 9 selector (only when no asset was named)
    if asset is None:
        asset = select_rental_asset(comp, start, end)
        if asset is None:
            raise conflict(ERR_NO_RENTAL_ASSET_AVAILABLE, "No eligible rental asset is available")

    # tier 10 fiscal: ACTIVE contract must be STANDARD or PREMIUM
    if contract["tier"] not in ("STANDARD", "PREMIUM"):
        raise conflict(ERR_CONTRACT_TIER_INELIGIBLE, "Rental requires an ACTIVE STANDARD or PREMIUM contract")

    planned_days = (end - start).days + 1
    res = new_resource()
    res.update(
        {
            "facility_id": facility_id,
            "rental_asset_id": asset["id"],
            "down_compressor_id": down_compressor_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "planned_days": planned_days,
            "quoted_cents": planned_days * asset["daily_rate_cents"],
            "deposit_cents": asset["deposit_cents"],
            "actual_return_date": None,
            "actual_bill_cents": None,
            "final_bill_cents": None,
            "status": "RESERVED",
        }
    )
    store.rental_reservations[res["id"]] = res
    fac["rental_escrow_cents"] += res["deposit_cents"]
    touch(fac)
    return ok_object(public(res), 201)


@bp.route("/rental-reservations", methods=["GET"])
def list_reservations():
    require_roles(ALL_ROLES)
    items = list(store.rental_reservations.values())
    for param in ("facility_id", "rental_asset_id", "down_compressor_id", "status"):
        value = request.args.get(param)
        if value is not None:
            items = [r for r in items if r[param] == value]
    limit, offset = parse_pagination()
    page, total = sort_and_page(items, limit, offset)
    return ok_list([public(r) for r in page], limit, offset, total)


@bp.route("/rental-reservations/<rentalReservationId>", methods=["GET"])
def get_reservation(rentalReservationId):
    user_id, role = require_roles(ALL_ROLES)
    res = _get_reservation_or_404(rentalReservationId)
    check_ownership(user_id, role, res["facility_id"])
    return ok_object(public(res), 200)


@bp.route("/rental-reservations/<rentalReservationId>/deliver", methods=["POST"])
def deliver(rentalReservationId):
    require_roles(["ServiceTech"])
    res = _get_reservation_or_404(rentalReservationId)
    if res["status"] != "RESERVED":
        raise invalid_state("RentalReservation must be RESERVED to deliver")
    res["status"] = "ON_RENT"
    touch(res)
    asset = store.rental_assets.get(res["rental_asset_id"])
    if asset is not None:
        asset["status"] = "ON_RENT"
        asset["next_available_date"] = None
        touch(asset)
    return ok_object(public(res), 200)


@bp.route("/rental-reservations/<rentalReservationId>/return", methods=["POST"])
def return_rental(rentalReservationId):
    require_roles(["ServiceTech"])
    res = _get_reservation_or_404(rentalReservationId)
    body = body_or_empty()
    actual_return = req_date(body, "actual_return_date")
    if res["status"] != "ON_RENT":
        raise invalid_state("RentalReservation must be ON_RENT to return")
    start = store_date(res["start_date"])
    if actual_return < start:
        raise unprocessable(ERR_RENTAL_DATE_RANGE_INVALID, "actual_return_date may not precede start_date")

    asset = store.rental_assets.get(res["rental_asset_id"])
    res["actual_return_date"] = actual_return.isoformat()
    res["actual_bill_cents"] = rental_actual_bill(asset["daily_rate_cents"], start, actual_return)
    res["status"] = "RETURNED"
    touch(res)

    if asset is not None:
        asset["status"] = "AVAILABLE"
        asset["next_available_date"] = (actual_return + timedelta(days=1)).isoformat()
        touch(asset)

    fac = store.facilities.get(res["facility_id"])
    if fac is not None:
        fac["rental_escrow_cents"] -= res["deposit_cents"]
        touch(fac)
    return ok_object(public(res), 200)


def store_date(s):
    from datetime import date as _date

    return _date.fromisoformat(s)


@bp.route("/rental-reservations/<rentalReservationId>/cancel", methods=["POST"])
def cancel_reservation(rentalReservationId):
    user_id, role = require_roles(["FacilityManager"])
    res = _get_reservation_or_404(rentalReservationId)
    check_ownership(user_id, role, res["facility_id"])
    if res["status"] != "RESERVED":
        raise invalid_state("RentalReservation must be RESERVED to cancel")
    res["status"] = "CANCELLED"
    touch(res)
    fac = store.facilities.get(res["facility_id"])
    if fac is not None:
        fac["rental_escrow_cents"] -= res["deposit_cents"]
        touch(fac)
    return ok_object(public(res), 200)


@bp.route("/rental-reservations/<rentalReservationId>/invoice", methods=["POST"])
def invoice(rentalReservationId):
    require_roles(["ContractManager"])
    res = _get_reservation_or_404(rentalReservationId)
    if res["status"] != "RETURNED":
        raise invalid_state("RentalReservation must be RETURNED to invoice")
    res["status"] = "INVOICED"
    res["final_bill_cents"] = res["actual_bill_cents"]
    touch(res)
    return ok_object(public(res), 200)
