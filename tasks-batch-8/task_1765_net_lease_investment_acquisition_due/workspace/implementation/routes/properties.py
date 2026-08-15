"""Property routes (PRD §3.2)."""

from flask import Blueprint

import db
from errors import ApiError
from middleware import bump, require_role
from response import created, ok, ok_list
from routes.common import body, req_enum, req_int, req_str
from services import domain

bp = Blueprint("properties", __name__)

ALL_ROLES = ("AcquisitionsAnalyst", "UnderwritingCommittee", "DueDiligenceOfficer",
             "CapitalMarketsOfficer", "EscrowOfficer", "AssetManager", "PlatformAdmin")
PROPERTY_TYPES = {"RETAIL", "INDUSTRIAL", "OFFICE", "MEDICAL", "QSR"}


@bp.route("/acquisition-deals/deals/<deal_id>/properties", methods=["POST"])
def create_property(deal_id):
    require_role("AcquisitionsAnalyst")
    deal = domain.get_deal(deal_id)
    data = body()
    address = req_str(data, "address")
    property_type = req_enum(data, "property_type", PROPERTY_TYPES)
    rentable_sqft = req_int(data, "rentable_sqft")
    if rentable_sqft <= 0:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       "rentable_sqft must be greater than zero", 400)
    year_built = req_int(data, "year_built")
    current_year = db.clock_now().year
    if year_built < 1800 or year_built > current_year:
        raise ApiError("ERR_FIELD_CONSTRAINT_VIOLATION",
                       f"year_built must be between 1800 and {current_year}", 400)
    prop = db.make_record({
        "deal_id": deal["id"],
        "address": address,
        "property_type": property_type,
        "rentable_sqft": rentable_sqft,
        "year_built": year_built,
        "status": "IDENTIFIED",
    })
    db.stores["properties"][prop["id"]] = prop
    return created(db.pub(prop))


@bp.route("/acquisition-deals/deals/<deal_id>/properties", methods=["GET"])
def list_properties(deal_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    return ok_list(domain.properties_of(deal["id"]))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>", methods=["GET"])
def get_property(deal_id, property_id):
    require_role(*ALL_ROLES)
    deal = domain.get_deal(deal_id)
    return ok(db.pub(domain.get_property_scoped(deal, property_id)))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/mark-surveyed", methods=["POST"])
def mark_surveyed(deal_id, property_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    if prop["status"] != "IDENTIFIED":
        raise ApiError("ERR_PROPERTY_INVALID_STATE",
                       "mark-surveyed requires status IDENTIFIED", 409)
    prop["status"] = "SURVEYED"
    bump(prop)
    return ok(db.pub(prop))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/clear", methods=["POST"])
def clear_property(deal_id, property_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    if prop["status"] != "SURVEYED":
        raise ApiError("ERR_PROPERTY_INVALID_STATE",
                       "clear requires status SURVEYED", 409)
    prop["status"] = "CLEAR"
    bump(prop)
    return ok(db.pub(prop))


@bp.route("/acquisition-deals/deals/<deal_id>/properties/<property_id>/flag", methods=["POST"])
def flag_property(deal_id, property_id):
    require_role("DueDiligenceOfficer")
    deal = domain.get_deal(deal_id)
    prop = domain.get_property_scoped(deal, property_id)
    if prop["status"] != "SURVEYED":
        raise ApiError("ERR_PROPERTY_INVALID_STATE",
                       "flag requires status SURVEYED", 409)
    prop["status"] = "FLAGGED"
    bump(prop)
    return ok(db.pub(prop))
