"""Parcels, structures, and the computed improvement summary."""

from flask import Blueprint

from db import base_fields, db, iso, sort_rows, touch
from errors import fail
from middleware import ALL_ROLES, require
from response import list_response, object_response, raw_response
from services import calc, engine
from validation import (body, fk, lookup, pagination, paginate, query_filters,
                        req_bool, req_enum, req_int, req_num, req_str)

bp = Blueprint("properties", __name__)


# ------------------------------------------------------------------ Property


@bp.post("/properties")
def create_property():
    require("FloodplainAdministrator")
    data = body()
    community_id = fk(data, "community_id", "community")
    panel_id = fk(data, "firm_panel_id", "firm_panel")
    parcel_id = req_str(data, "parcel_id")
    mapped_area_code = req_str(data, "mapped_area_code")
    owner_name = req_str(data, "owner_name")
    owner_email = req_str(data, "owner_email")

    lookup("community", community_id)
    panel = lookup("firm_panel", panel_id)

    if panel["status"] != "EFFECTIVE":
        fail("ERR_PANEL_NOT_EFFECTIVE")
    for existing in db.properties.values():
        if existing["community_id"] == community_id and existing["parcel_id"] == parcel_id:
            fail("ERR_DUPLICATE_PARCEL_ID")

    row = base_fields()
    row.update({
        "community_id": community_id,
        "firm_panel_id": panel_id,
        "parcel_id": parcel_id,
        "mapped_area_code": mapped_area_code,
        "owner_name": owner_name,
        "owner_email": owner_email,
        "repetitive_loss_area_id": None,
        "qualifying_claim_count": 0,
        "max_window_claim_count": 0,
        "cumulative_claim_paid_usd": calc.money(0),
        "repetitive_loss_status": "NONE",
    })
    db.properties[row["id"]] = row
    return object_response(row, 201)


@bp.get("/properties/<property_id>")
def read_property(property_id):
    require(*ALL_ROLES)
    return object_response(lookup("property", property_id))


@bp.get("/properties")
def list_properties():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.properties.values()), {
        "community_id": ("community_id", None),
        "firm_panel_id": ("firm_panel_id", None),
        "repetitive_loss_area_id": ("repetitive_loss_area_id", None),
        "repetitive_loss_status": ("repetitive_loss_status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


# ----------------------------------------------------------------- Structure


@bp.post("/structures")
def create_structure():
    require("FloodplainAdministrator")
    data = body()
    property_id = fk(data, "property_id", "property")
    structure_use = req_enum(data, "structure_use", calc.STRUCTURE_USES)
    pre_firm = req_bool(data, "pre_firm")
    construction_year = req_int(data, "construction_year")
    market_value = req_num(data, "market_value_usd", exclusive_min=0)
    grade = req_num(data, "highest_adjacent_grade_ft")
    lookup("property", property_id)

    row = base_fields()
    row.update({
        "property_id": property_id,
        "structure_use": structure_use,
        "pre_firm": pre_firm,
        "construction_year": construction_year,
        "market_value_usd": calc.money(market_value),
        "highest_adjacent_grade_ft": calc.r1(grade),
        "lowest_floor_elevation_ft": None,
        "compliance_status": "PRE_FIRM_EXISTING" if pre_firm else "PENDING_CERTIFICATE",
        "substantial_status": "NONE",
        "anchor_record_id": None,
        "cumulative_counted_cost_usd": calc.money(0),
        "cumulative_improvement_pct": calc.r2(0),
        "single_event_improvement_pct": calc.r2(0),
    })
    db.structures[row["id"]] = row
    return object_response(row, 201)


@bp.get("/structures/<structure_id>")
def read_structure(structure_id):
    require(*ALL_ROLES)
    return object_response(lookup("structure", structure_id))


@bp.get("/structures")
def list_structures():
    require(*ALL_ROLES)
    limit, offset = pagination()
    rows = query_filters(list(db.structures.values()), {
        "property_id": ("property_id", None),
        "anchor_record_id": ("anchor_record_id", None),
        "compliance_status": ("compliance_status", None),
        "substantial_status": ("substantial_status", None),
    })
    page, total = paginate(rows, limit, offset)
    return list_response(page, limit, offset, total)


@bp.patch("/structures/<structure_id>")
def amend_structure(structure_id):
    require("FloodplainAdministrator")
    structure = lookup("structure", structure_id)
    data = body()
    market_value = req_num(data, "market_value_usd", exclusive_min=0)

    structure["market_value_usd"] = calc.money(market_value)
    engine.recompute_aggregates(structure)
    touch(structure)
    return object_response(structure)


@bp.get("/structures/<structure_id>/improvement-summary")
def improvement_summary(structure_id):
    require(*ALL_ROLES)
    structure = lookup("structure", structure_id)
    anchor, start, end, inside = engine.improvement_window(structure)
    return raw_response({
        "structure_id": structure["id"],
        "anchor_record_id": anchor["id"] if anchor else None,
        "window_start_date": iso(start) if start else None,
        "window_end_date": iso(end) if end else None,
        "counted_record_count": len(sort_rows(inside)),
        "cumulative_counted_cost_usd": float(structure["cumulative_counted_cost_usd"]),
        "cumulative_improvement_pct": float(structure["cumulative_improvement_pct"]),
        "single_event_improvement_pct": float(structure["single_event_improvement_pct"]),
    })
