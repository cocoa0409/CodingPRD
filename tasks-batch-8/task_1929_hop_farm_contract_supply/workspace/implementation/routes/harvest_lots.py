"""Harvest lot endpoints — the kiln pipeline (PRD §3.2)."""

from decimal import Decimal

from flask import Blueprint, request

from db import store
from middleware import require_roles, ALL_ROLES, ROLE_FARM_MANAGER
from response import success_object, success_list, parse_pagination
from util import (
    get_body, check_unknown_fields, req_str, req_int, req_datetime,
)
from errors import (
    invalid_state, invalid_request, ApiError,
    ERR_KILN_WINDOW_OVERLAP, ERR_MOISTURE_UNSAFE, ERR_WEIGHT_IMPOSSIBLE,
)
from services.core import (
    base_record, touch, public, get_harvest_lot, get_kiln, get_plan,
    dried_lbs_floor, compute_moisture_pct, kiln_window_conflict,
    filtered_sorted, LOT_STATUSES, MOISTURE_RELEASE_MAX_PCT,
)

bp = Blueprint("harvest_lots", __name__)

FM = [ROLE_FARM_MANAGER]


def _check_window(kiln_id, start, end, exclude_lot_id=None):
    if end <= start:
        raise invalid_request("kiln_window_end must be strictly after kiln_window_start")
    if kiln_window_conflict(kiln_id, start, end, exclude_lot_id=exclude_lot_id):
        raise ApiError(ERR_KILN_WINDOW_OVERLAP, 409,
                       "Kiln window violates the 30-minute buffer rule")


@bp.route("/api/harvest-lots", methods=["POST"])
def create_harvest_lot():
    require_roles(FM)
    body = get_body()
    check_unknown_fields(body, {"planting_plan_id", "wet_lbs"})
    planting_plan_id = req_str(body, "planting_plan_id")
    wet_lbs = req_int(body, "wet_lbs", min_v=1)

    plan = get_plan(planting_plan_id)
    if plan["status"] != "HARVESTING":
        raise invalid_state("Planting plan is not HARVESTING")

    rec = base_record()
    rec.update({
        "planting_plan_id": planting_plan_id,
        "kiln_id": None,
        "variety": plan["variety"],
        "crop_year": plan["crop_year"],
        "wet_lbs": wet_lbs,
        "dried_lbs": None,
        "moisture_pct": None,
        "alpha_pct_provisional": None,
        "alpha_pct_final": None,
        "kiln_window_start": None,
        "kiln_window_end": None,
        "status": "HARVESTED",
    })
    store.harvest_lots[rec["id"]] = rec
    return success_object(public(rec), status=201)


@bp.route("/api/harvest-lots/<lot_id>", methods=["GET"])
def get_harvest_lot_endpoint(lot_id):
    require_roles(ALL_ROLES)
    return success_object(public(get_harvest_lot(lot_id)))


@bp.route("/api/harvest-lots", methods=["GET"])
def list_harvest_lots():
    require_roles(ALL_ROLES)
    records = filtered_sorted(list(store.harvest_lots.values()), request.args, {
        "planting_plan_id": ("str", "planting_plan_id"),
        "kiln_id": ("str", "kiln_id"),
        "status": ("enum", "status", LOT_STATUSES),
    })
    limit, offset = parse_pagination(request.args)
    total = len(records)
    page = records[offset:offset + limit]
    return success_list([public(r) for r in page], limit, offset, total)


@bp.route("/api/harvest-lots/<lot_id>/load-kiln", methods=["POST"])
def load_kiln(lot_id):
    require_roles(FM)
    body = get_body()
    check_unknown_fields(body, {"kiln_id", "kiln_window_start", "kiln_window_end"})
    kiln_id = req_str(body, "kiln_id")
    start = req_datetime(body, "kiln_window_start")
    end = req_datetime(body, "kiln_window_end")
    if end <= start:
        raise invalid_request("kiln_window_end must be strictly after kiln_window_start")

    lot = get_harvest_lot(lot_id)
    get_kiln(kiln_id)
    if lot["status"] != "HARVESTED":
        raise invalid_state("Harvest lot is not HARVESTED")
    _check_window(kiln_id, start, end)

    lot["kiln_id"] = kiln_id
    lot["kiln_window_start"] = start
    lot["kiln_window_end"] = end
    lot["status"] = "IN_KILN"
    touch(lot)
    return success_object(public(lot))


@bp.route("/api/harvest-lots/<lot_id>/finish-drying", methods=["POST"])
def finish_drying(lot_id):
    require_roles(FM)
    body = get_body()
    check_unknown_fields(body, {"dried_lbs"})
    dried_lbs = req_int(body, "dried_lbs")

    lot = get_harvest_lot(lot_id)
    if lot["status"] != "IN_KILN":
        raise invalid_state("Harvest lot is not IN_KILN")
    # feasibility envelope: ceil(0.24 x wet) <= dried <= wet
    if not (dried_lbs_floor(lot["wet_lbs"]) <= dried_lbs <= lot["wet_lbs"]):
        raise ApiError(ERR_WEIGHT_IMPOSSIBLE, 422,
                       "dried_lbs is outside the feasible range")

    lot["dried_lbs"] = dried_lbs
    lot["moisture_pct"] = compute_moisture_pct(dried_lbs, lot["wet_lbs"])
    lot["status"] = "MOISTURE_CHECK"
    touch(lot)
    return success_object(public(lot))


@bp.route("/api/harvest-lots/<lot_id>/redry", methods=["POST"])
def redry(lot_id):
    require_roles(FM)
    body = get_body()
    check_unknown_fields(body, {"kiln_window_start", "kiln_window_end"})
    start = req_datetime(body, "kiln_window_start")
    end = req_datetime(body, "kiln_window_end")
    if end <= start:
        raise invalid_request("kiln_window_end must be strictly after kiln_window_start")

    lot = get_harvest_lot(lot_id)
    if lot["status"] != "MOISTURE_CHECK":
        raise invalid_state("Harvest lot is not MOISTURE_CHECK")
    # a lot already at or below the release threshold cannot redry
    if Decimal(str(lot["moisture_pct"])) <= MOISTURE_RELEASE_MAX_PCT:
        raise invalid_state("moisture_pct is at or below the release threshold; release instead")
    # same kiln, fresh window; the lot's own current window is excluded
    _check_window(lot["kiln_id"], start, end, exclude_lot_id=lot["id"])

    lot["kiln_window_start"] = start
    lot["kiln_window_end"] = end
    lot["status"] = "IN_KILN"
    touch(lot)
    return success_object(public(lot))


@bp.route("/api/harvest-lots/<lot_id>/release", methods=["POST"])
def release(lot_id):
    require_roles(FM)
    check_unknown_fields(get_body(), set())
    lot = get_harvest_lot(lot_id)
    if lot["status"] != "MOISTURE_CHECK":
        raise invalid_state("Harvest lot is not MOISTURE_CHECK")
    if Decimal(str(lot["moisture_pct"])) > MOISTURE_RELEASE_MAX_PCT:
        raise ApiError(ERR_MOISTURE_UNSAFE, 422,
                       "moisture_pct is above the 10.0 release threshold")
    lot["status"] = "DRIED"
    touch(lot)
    return success_object(public(lot))
