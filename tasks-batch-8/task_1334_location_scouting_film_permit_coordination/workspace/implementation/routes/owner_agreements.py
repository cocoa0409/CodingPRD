"""OwnerAgreement endpoints."""

from flask import Blueprint, request
from middleware import require_role, ALL_ROLES
from response import success_object, success_list
from errors import *
from db import store
from services.helpers import (
    require_fields, require_str, require_int, optional_int,
    make_entity, touch, get_production, get_location, get_scoped,
    list_filtered, paginate, get_pagination_params, parse_date,
)
from services.calculations import deposit_required, calendar_days_in_window

bp = Blueprint("owner_agreements", __name__)


def _has_accepted_scout(production_id, location_id):
    """Check if an ACCEPTED ScoutPackage exists for (production, location)."""
    for sp in store.scout_packages.values():
        if (sp.get("production_id") == production_id
                and sp.get("location_id") == location_id
                and sp["status"] == "ACCEPTED"):
            return True
    return False


@bp.route("/productions/<pid>/owner-agreements", methods=["POST"])
def create_owner_agreement(pid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["location_id", "shoot_start_date", "shoot_end_date"])
    loc_id = require_str(payload, "location_id")
    get_location(loc_id)
    entity = make_entity({
        "production_id": pid,
        "location_id": loc_id,
        "shoot_start_date": require_str(payload, "shoot_start_date"),
        "shoot_end_date": require_str(payload, "shoot_end_date"),
        "proposed_day_rate_cents": 0,
        "round_count": 0,
        "max_rounds": optional_int(payload, "max_rounds", 5),
        "agreed_day_rate_cents": 0,
        "status": "DRAFT",
    })
    store.owner_agreements[entity["id"]] = entity
    return success_object(entity, 201)


@bp.route("/productions/<pid>/owner-agreements", methods=["GET"])
def list_owner_agreements(pid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    limit, offset = get_pagination_params(request.args)
    filters = {}
    for f in ("location_id", "status"):
        v = request.args.get(f)
        if v:
            filters[f] = v
    items = list_filtered(store.owner_agreements, filters, production_id=pid)
    page, total = paginate(items, limit, offset)
    return success_list(page, limit, offset, total)


@bp.route("/productions/<pid>/owner-agreements/<rid>", methods=["GET"])
def get_owner_agreement(pid, rid):
    user_id, role = require_role(*ALL_ROLES)
    p = get_production(pid)
    oa = get_scoped(store.owner_agreements, rid, pid, "OwnerAgreement")
    return success_object(oa)


@bp.route("/productions/<pid>/owner-agreements/<rid>/propose", methods=["POST"])
def propose_agreement(pid, rid):
    user_id, role = require_role("LocationManager")
    p = get_production(pid)
    oa = get_scoped(store.owner_agreements, rid, pid, "OwnerAgreement")
    if oa["status"] not in ("DRAFT", "COUNTERED"):
        raise ApiError(ERR_INVALID_STATE, "OwnerAgreement must be DRAFT or COUNTERED to propose", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["proposed_day_rate_cents"])
    rate = require_int(payload, "proposed_day_rate_cents")
    if oa["status"] == "DRAFT":
        # First proposal requires ACCEPTED scout package
        if not _has_accepted_scout(pid, oa["location_id"]):
            raise ApiError(ERR_SCOUT_NOT_ACCEPTED, "No ACCEPTED scout package for this location", 422)
        if rate <= 0:
            raise ApiError(ERR_INVALID_REQUEST, "proposed_day_rate_cents must be > 0", 400)
    # Round cap check
    if oa["round_count"] + 1 > oa["max_rounds"]:
        raise ApiError(ERR_NEGOTIATION_EXHAUSTED, "Negotiation round cap exceeded", 422)
    oa["round_count"] += 1
    oa["proposed_day_rate_cents"] = rate
    oa["status"] = "PROPOSED"
    touch(oa)
    return success_object(oa)


@bp.route("/productions/<pid>/owner-agreements/<rid>/counter", methods=["POST"])
def counter_agreement(pid, rid):
    user_id, role = require_role("OwnerRep")
    p = get_production(pid)
    oa = get_scoped(store.owner_agreements, rid, pid, "OwnerAgreement")
    if oa["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "OwnerAgreement must be PROPOSED to counter", 409)
    payload = request.get_json(silent=True) or {}
    require_fields(payload, ["proposed_day_rate_cents"])
    rate = require_int(payload, "proposed_day_rate_cents")
    # Round cap check: counter rejected when round_count would exceed max_rounds
    if oa["round_count"] >= oa["max_rounds"]:
        raise ApiError(ERR_NEGOTIATION_EXHAUSTED, "Negotiation round cap exceeded", 422)
    oa["proposed_day_rate_cents"] = rate
    oa["status"] = "COUNTERED"
    touch(oa)
    return success_object(oa)


@bp.route("/productions/<pid>/owner-agreements/<rid>/accept", methods=["POST"])
def accept_agreement(pid, rid):
    user_id, role = require_role("LocationManager", "OwnerRep")
    p = get_production(pid)
    oa = get_scoped(store.owner_agreements, rid, pid, "OwnerAgreement")
    # OwnerRep accepts PROPOSED; LocationManager accepts COUNTERED
    if role == "OwnerRep" and oa["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "OwnerRep can only accept a PROPOSED agreement", 409)
    if role == "LocationManager" and oa["status"] != "COUNTERED":
        raise ApiError(ERR_INVALID_STATE, "LocationManager can only accept a COUNTERED agreement", 409)
    # Location must not be RETIRED
    loc = get_location(oa["location_id"])
    if loc["status"] == "RETIRED":
        raise ApiError(ERR_INVALID_STATE, "Location is RETIRED", 409)
    oa["agreed_day_rate_cents"] = oa["proposed_day_rate_cents"]
    oa["status"] = "EXECUTED"
    touch(oa)
    # Cascade: Location -> AGREEMENT_EXECUTED
    if loc["status"] == "SCOUTING":
        loc["status"] = "AGREEMENT_EXECUTED"
        touch(loc)
    # Recompute required_amount_cents on any deposit account for this location
    for da in store.deposit_accounts.values():
        if da.get("production_id") == pid and da.get("location_id") == oa["location_id"]:
            shoot_days = calendar_days_in_window(
                parse_date(oa["shoot_start_date"]),
                parse_date(oa["shoot_end_date"])
            )
            da["required_amount_cents"] = deposit_required(
                loc["deposit_floor_cents"], oa["agreed_day_rate_cents"], shoot_days
            )
            touch(da)
    return success_object(oa)


@bp.route("/productions/<pid>/owner-agreements/<rid>/walk-away", methods=["POST"])
def walk_away_agreement(pid, rid):
    user_id, role = require_role("LocationManager", "OwnerRep")
    p = get_production(pid)
    oa = get_scoped(store.owner_agreements, rid, pid, "OwnerAgreement")
    # Manager walks away from PROPOSED; OwnerRep walks away from COUNTERED
    if role == "LocationManager" and oa["status"] != "PROPOSED":
        raise ApiError(ERR_INVALID_STATE, "LocationManager can only walk away from PROPOSED", 409)
    if role == "OwnerRep" and oa["status"] != "COUNTERED":
        raise ApiError(ERR_INVALID_STATE, "OwnerRep can only walk away from COUNTERED", 409)
    oa["status"] = "COLLAPSED"
    touch(oa)
    return success_object(oa)
