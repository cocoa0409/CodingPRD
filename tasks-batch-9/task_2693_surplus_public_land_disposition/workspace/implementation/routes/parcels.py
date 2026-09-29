"""Parcels and title curative items (PRD 3.1, 3.2)."""

from flask import Blueprint

import clockmod
import db
import listing
import lookup
import response
import shape
from errors import fail
from middleware import (AGENCY_REP, APPRAISER, BIDDER, CLERK, FINANCE, MONITOR, RPO,
                        SYSADMIN, authorize)
from services import derive

bp = Blueprint("parcels", __name__)

OWNERSHIP_STATUSES = ("AGENCY_OWNED", "CONVEYED", "REVERTED_TO_AGENCY")
VALUATION_STATUSES = ("UNVALUED", "CURRENT", "STALE")
ITEM_TYPES = ("LIEN", "ENCROACHMENT", "MISSING_ACCESS_EASEMENT", "BOUNDARY_GAP",
              "UNRECORDED_LEASE")
ITEM_STATUSES = ("OPEN", "CURED", "WAIVED_WITH_ENDORSEMENT", "RESERVED_AS_EASEMENT")
RESOLUTIONS = ("CURED", "WAIVED_WITH_ENDORSEMENT", "RESERVED_AS_EASEMENT")


@bp.post("/parcels")
@authorize(RPO)
def create_parcel():
    payload = shape.body()
    apn = shape.req_str(payload, "apn", 1, 40)
    address = shape.req_str(payload, "address", 1)
    acreage = shape.req_positive_number(payload, "acreage")
    zoning_code = shape.req_str(payload, "zoning_code", 1)
    book_value = shape.req_cents(payload, "book_value_cents")
    custodian_id = payload.get("custodian_agency_id")
    if custodian_id is None:
        fail("ERR_INVALID_REQUEST", "custodian_agency_id is required.")
    lookup.must_fk("agencies", custodian_id)
    if any(p["apn"] == apn for p in db.all_rows("parcels")):
        fail("ERR_DUPLICATE_KEY", "apn %s is already in the inventory." % apn)
    row = db.insert("parcels", {
        "apn": apn,
        "address": address,
        "acreage": acreage,
        "zoning_code": zoning_code,
        "book_value_cents": book_value,
        "custodian_agency_id": custodian_id,
        "ownership_status": "AGENCY_OWNED",
    })
    return response.object_response(derive.parcel_out(row), 201)


@bp.get("/parcels/<row_id>")
@authorize(RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, APPRAISER, BIDDER, SYSADMIN)
def get_parcel(row_id):
    row = lookup.must("parcels", row_id)
    return response.object_response(derive.parcel_out(row))


@bp.get("/parcels")
@authorize(RPO, CLERK, MONITOR, FINANCE, AGENCY_REP, BIDDER, SYSADMIN)
def list_parcels():
    limit, offset = listing.bounds()
    custodian_id = shape.query_str("custodian_agency_id")
    ownership_status = shape.query_enum("ownership_status", OWNERSHIP_STATUSES)
    valuation_status = shape.query_enum("valuation_status", VALUATION_STATUSES)
    ready = shape.query_bool("disposition_ready")
    rows = db.all_rows("parcels")
    if custodian_id is not None:
        rows = [r for r in rows if r["custodian_agency_id"] == custodian_id]
    if ownership_status is not None:
        rows = [r for r in rows if r["ownership_status"] == ownership_status]
    if valuation_status is not None:
        rows = [r for r in rows if derive.valuation_status(r) == valuation_status]
    if ready is not None:
        rows = [r for r in rows if derive.disposition_ready(r) == ready]
    return listing.respond(rows, derive.parcel_out, limit, offset, listing.by_created_at)


@bp.patch("/parcels/<row_id>")
@authorize(RPO)
def patch_parcel(row_id):
    payload = shape.body()
    book_value = shape.opt_cents(payload, "book_value_cents")
    zoning_code = shape.opt_str(payload, "zoning_code", 1)
    address = shape.opt_str(payload, "address", 1)
    row = lookup.must("parcels", row_id)
    if book_value is not None:
        row["book_value_cents"] = book_value
    if zoning_code is not None:
        row["zoning_code"] = zoning_code
    if address is not None:
        row["address"] = address
    db.touch(row)
    return response.object_response(derive.parcel_out(row))


# --------------------------------------------------------------------------
# Title curative items
# --------------------------------------------------------------------------

@bp.post("/parcels/<row_id>/title-items")
@authorize(RPO)
def create_title_item(row_id):
    payload = shape.body()
    item_type = shape.req_enum(payload, "item_type", ITEM_TYPES)
    description = shape.req_str(payload, "description", 1)
    estimate = shape.req_cents(payload, "cure_cost_estimate_cents")
    parcel = lookup.must("parcels", row_id)
    row = db.insert("title_items", {
        "parcel_id": parcel["id"],
        "item_type": item_type,
        "description": description,
        "cure_cost_estimate_cents": estimate,
        "status": "OPEN",
        "actual_cure_cost_cents": None,
        "easement_purpose": None,
        "easement_area_sqft": None,
        "resolved_at": None,
    })
    return response.object_response(derive.title_item_out(row), 201)


@bp.get("/parcels/<row_id>/title-items")
@authorize(RPO, CLERK, MONITOR, AGENCY_REP, SYSADMIN)
def list_parcel_title_items(row_id):
    limit, offset = listing.bounds()
    status = shape.query_enum("status", ITEM_STATUSES)
    parcel = lookup.must("parcels", row_id)
    rows = [t for t in db.all_rows("title_items") if t["parcel_id"] == parcel["id"]]
    if status is not None:
        rows = [t for t in rows if t["status"] == status]
    return listing.respond(rows, derive.title_item_out, limit, offset, listing.by_created_at)


@bp.get("/title-items/<row_id>")
@authorize(RPO, CLERK, MONITOR, AGENCY_REP, SYSADMIN)
def get_title_item(row_id):
    row = lookup.must("title_items", row_id)
    return response.object_response(derive.title_item_out(row))


@bp.post("/title-items/<row_id>/resolve")
@authorize(RPO)
def resolve_title_item(row_id):
    payload = shape.body()
    resolution = shape.req_enum(payload, "resolution", RESOLUTIONS)
    actual_cost = shape.opt_cents(payload, "actual_cure_cost_cents")
    easement_purpose = None
    easement_area = None
    if resolution == "RESERVED_AS_EASEMENT":
        easement_purpose = shape.req_str(payload, "easement_purpose", 1)
        # PRD 3.2 constrains the area only to be supplied and "strictly greater
        # than zero"; the integer discipline of 2.6/2.10 is scoped to `_cents`
        # fields, so a fractional area is a well-formed request.
        easement_area = shape.req_positive_number(payload, "easement_area_sqft")
    row = lookup.must("title_items", row_id)
    if row["status"] != "OPEN":
        fail("ERR_INVALID_TITLE_ITEM_STATE",
             "A title item that is %s cannot be resolved again." % row["status"])

    if resolution == "CURED":
        row["actual_cure_cost_cents"] = (actual_cost if actual_cost is not None
                                        else row["cure_cost_estimate_cents"])
    else:
        row["actual_cure_cost_cents"] = 0
    if resolution == "RESERVED_AS_EASEMENT":
        row["easement_purpose"] = easement_purpose
        row["easement_area_sqft"] = easement_area
    row["status"] = resolution
    row["resolved_at"] = clockmod.now()
    db.touch(row)
    return response.object_response(derive.title_item_out(row))
