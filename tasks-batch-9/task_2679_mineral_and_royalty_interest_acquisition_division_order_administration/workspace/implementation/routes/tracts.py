"""Tract files, the append-only chain of title, and certification (PRD 3.1)."""

import re
from decimal import Decimal

from flask import Blueprint

import calc
import guards
import response
import serializers
from db import clock_iso, db, stamp_new, stamp_new_immutable, touch
from errors import ApiError
from guards import (authorize, body, get_tract, opt_enum, opt_num, pagination,
                    paginate, req_date, req_enum, req_num, req_str)

bp = Blueprint("tracts", __name__)

ACTIVITY_TIERS = ("HIGH", "MODERATE", "LOW")
INSTRUMENT_TYPES = ("PATENT", "DEED", "PROBATE", "ASSIGNMENT")
BOOK_PAGE_RE = re.compile(r"^[0-9]{1,6}/[0-9]{1,6}$")


@bp.route("/tracts", methods=["POST"])
def create_tract():
    authorize("TitleAnalyst")
    payload = body()
    county = req_str(payload, "county", min_len=1, max_len=80)
    state_code = req_enum(payload, "state_code", guards.STATE_CODES)
    gross_acres = req_num(payload, "gross_acres", 4, minimum=0, exclusive_min=True)
    tier = opt_enum(payload, "operator_activity_tier", ACTIVITY_TIERS, default="MODERATE")

    row = {
        "county": county,
        "state_code": state_code,
        "gross_acres": gross_acres,
        "operator_activity_tier": tier,
        "title_status": "RESEARCH",
        "net_mineral_acres_certified": None,
        "existing_burden_fraction": None,
        "chain_entry_count": 0,
        "certified_at": None,
    }
    stamp_new(row)
    db.tracts[row["id"]] = row
    return response.created(serializers.tract_out(row))


@bp.route("/tracts/<tract_id>", methods=["GET"])
def read_tract(tract_id):
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin", "Operator")
    row = get_tract(tract_id)
    return response.ok(serializers.tract_out(row))


@bp.route("/tracts", methods=["GET"])
def list_tracts():
    authorize("TitleAnalyst", "AcquisitionManager", "DivisionOrderAdmin", "Operator")
    limit, offset = pagination()
    from flask import request
    state_code = request.args.get("state_code")
    title_status = request.args.get("title_status")
    rows = list(db.tracts.values())
    if state_code is not None:
        rows = [r for r in rows if r["state_code"] == state_code]
    if title_status is not None:
        rows = [r for r in rows if r["title_status"] == title_status]
    rows.sort(key=lambda r: r["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.tract_out(r) for r in page], limit, offset, total)


@bp.route("/tracts/<tract_id>/title-chain-entries", methods=["POST"])
def create_chain_entry(tract_id):
    authorize("TitleAnalyst")
    tract = get_tract(tract_id)
    payload = body()

    instrument_type = req_enum(payload, "instrument_type", INSTRUMENT_TYPES)
    instrument_date, _parsed = req_date(payload, "instrument_date")

    if instrument_type == "DEED":
        guards.must_be_absent(payload, "conveyed_fraction", "must be null for a DEED")
        conveyed_fraction = None
        conveyed_acres = req_num(payload, "conveyed_acres", 4, minimum=0)
    else:
        guards.must_be_absent(payload, "conveyed_acres",
                              "must be null for a %s" % instrument_type)
        conveyed_acres = None
        conveyed_fraction = req_num(payload, "conveyed_fraction", 6,
                                    minimum=0, maximum=1, exclusive_min=True)

    county_book_page = req_str(payload, "county_book_page")
    if not BOOK_PAGE_RE.match(county_book_page):
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'county_book_page' must match the clerk format "
                       "of 1-6 digits, a slash, then 1-6 digits.")
    grantor_name = req_str(payload, "grantor_name")
    grantee_name = req_str(payload, "grantee_name")

    # priority 79: the citation is unique within this tract's chain
    for existing in db.chain_entries.values():
        if (existing["tract_id"] == tract["id"]
                and existing["county_book_page"] == county_book_page):
            raise ApiError("ERR_DUPLICATE_BOOK_PAGE")

    row = {
        "tract_id": tract["id"],
        "instrument_type": instrument_type,
        "instrument_date": instrument_date,
        "conveyed_fraction": conveyed_fraction,
        "conveyed_acres": conveyed_acres,
        "county_book_page": county_book_page,
        "grantor_name": grantor_name,
        "grantee_name": grantee_name,
    }
    stamp_new_immutable(row)
    db.chain_entries[row["id"]] = row

    tract["chain_entry_count"] = tract["chain_entry_count"] + 1
    if tract["title_status"] == "CERTIFIED":
        tract["title_status"] = "RESEARCH"
        tract["net_mineral_acres_certified"] = None
        tract["existing_burden_fraction"] = None
        tract["certified_at"] = None
    touch(tract)
    return response.created(serializers.chain_entry_out(row))


@bp.route("/tracts/<tract_id>/title-chain-entries", methods=["GET"])
def list_chain_entries(tract_id):
    authorize("TitleAnalyst", "AcquisitionManager")
    tract = get_tract(tract_id)
    limit, offset = pagination()
    from flask import request
    instrument_type = request.args.get("instrument_type")
    rows = [e for e in db.chain_entries.values() if e["tract_id"] == tract["id"]]
    if instrument_type is not None:
        rows = [e for e in rows if e["instrument_type"] == instrument_type]
    # replay order: instrument_date ASC, created_at ASC (PRD 2.3)
    rows.sort(key=lambda e: (e["instrument_date"], e["_seq"]))
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.chain_entry_out(r) for r in page],
                            limit, offset, total)


@bp.route("/tracts/<tract_id>/certify-title", methods=["POST"])
def certify_title(tract_id):
    authorize("TitleAnalyst")
    tract = get_tract(tract_id)

    entries = calc.chain_entries_of(tract["id"])
    patents = [e for e in entries if e["instrument_type"] == "PATENT"]
    # priority 21 fires ahead of priority 22
    if len(entries) < 1 or len(patents) != 1:
        raise ApiError("ERR_TITLE_CHAIN_INCOMPLETE")
    if tract["title_status"] != "RESEARCH":
        raise ApiError("ERR_TRACT_STATE_INVALID")

    net_acres = calc.net_mineral_acres_from_chain(tract)   # priority 68
    burden = calc.tract_burden_fraction(tract)             # priority 69

    tract["net_mineral_acres_certified"] = net_acres
    tract["existing_burden_fraction"] = burden
    tract["title_status"] = "CERTIFIED"
    tract["certified_at"] = clock_iso()
    touch(tract)
    return response.ok(serializers.tract_out(tract))


@bp.route("/tracts/<tract_id>/unit-allocations", methods=["GET"])
def list_tract_allocations(tract_id):
    authorize("TitleAnalyst", "DivisionOrderAdmin", "Operator")
    tract = get_tract(tract_id)
    limit, offset = pagination()
    from flask import request
    allocation_status = request.args.get("allocation_status")
    rows = [a for a in db.allocations.values() if a["tract_id"] == tract["id"]]
    if allocation_status is not None:
        rows = [a for a in rows if a["allocation_status"] == allocation_status]
    rows.sort(key=lambda a: a["_seq"])
    page, total = paginate(rows, limit, offset)
    return response.listing([serializers.allocation_out(r) for r in page],
                            limit, offset, total)
