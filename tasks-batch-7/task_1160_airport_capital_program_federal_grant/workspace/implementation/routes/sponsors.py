"""Sponsors and airfield facilities."""
import re

from flask import Blueprint, request

from auth import ALL_ROLES, require
from domain import (AIRPORT_TIERS, FACILITY_TYPES, ser_facility, ser_sponsor)
from errors import err_validation
from store import DB
from util import (as_enum, as_number, as_str, body, get_or_404, need,
                  new_entity, respond, respond_list)

bp = Blueprint("sponsors", __name__)

LOC_ID_RE = re.compile(r"^[A-Z]{3}$")


@bp.route("/aip/sponsors", methods=["POST"])
@require("FAAManager")
def create_sponsor():
    b = body()
    name = as_str(need(b, "sponsor_name"), "sponsor_name")
    loc_id = as_str(need(b, "loc_id"), "loc_id")
    if not LOC_ID_RE.match(loc_id):
        raise err_validation("loc_id must be exactly 3 uppercase letters A-Z")
    tier = as_enum(need(b, "airport_size_tier"), "airport_size_tier",
                   AIRPORT_TIERS)
    total = as_number(need(b, "npe_entitlement_total"), "npe_entitlement_total")
    if total < 0:
        raise err_validation("npe_entitlement_total must be >= 0")
    if any(s["loc_id"] == loc_id for s in DB.sponsors.values()):
        raise err_validation("loc_id must be unique across all sponsors")
    s = new_entity()
    s.update({"sponsor_name": name, "loc_id": loc_id,
              "airport_size_tier": tier, "npe_entitlement_total": total,
              "npe_entitlement_available": total, "status": "ACTIVE"})
    DB.sponsors[s["id"]] = s
    return respond(ser_sponsor(s), 201)


@bp.route("/aip/sponsors", methods=["GET"])
@require(*ALL_ROLES)
def list_sponsors():
    return respond_list(list(DB.sponsors.values()), ser_sponsor)


@bp.route("/aip/sponsors/<sponsorId>", methods=["GET"])
@require(*ALL_ROLES)
def get_sponsor(sponsorId):
    return respond(ser_sponsor(get_or_404(DB.sponsors, sponsorId, "Sponsor")))


@bp.route("/aip/facilities", methods=["POST"])
@require("SponsorStaff")
def create_facility():
    b = body()
    if "sponsor_id" not in b or b["sponsor_id"] is None:
        raise err_validation("Missing required field: sponsor_id")
    sponsor = get_or_404(DB.sponsors, b["sponsor_id"], "Sponsor")
    name = as_str(need(b, "facility_name"), "facility_name")
    ftype = as_enum(need(b, "facility_type"), "facility_type", FACILITY_TYPES)
    f = new_entity()
    f.update({"sponsor_id": sponsor["id"], "facility_name": name,
              "facility_type": ftype})
    DB.facilities[f["id"]] = f
    return respond(ser_facility(f), 201)


@bp.route("/aip/facilities", methods=["GET"])
@require(*ALL_ROLES)
def list_facilities():
    items = list(DB.facilities.values())
    sponsor_id = request.args.get("sponsor_id")
    facility_type = request.args.get("facility_type")
    if sponsor_id is not None:
        items = [f for f in items if f["sponsor_id"] == sponsor_id]
    if facility_type is not None:
        items = [f for f in items if f["facility_type"] == facility_type]
    return respond_list(items, ser_facility)


@bp.route("/aip/facilities/<facilityId>", methods=["GET"])
@require(*ALL_ROLES)
def get_facility(facilityId):
    return respond(ser_facility(
        get_or_404(DB.facilities, facilityId, "AirfieldFacility")))
