"""Communities, lenders, properties and structures (PRD sections 3.1 and 3.4)."""
from flask import Blueprint

import calc
import enums
from authz import ROLE_PROVIDER_ANALYST, authorize
from db import all_rows, db, new_row, touch
from errors import fail
from response import created, ok
from services import (
    geocode_correction_cascade,
    must,
    recount_active_folio_count,
    recount_structure_count,
    store,
    touch_folio,
)
from shape import Field, read_body

bp = Blueprint("parties", __name__)

ANALYST = [ROLE_PROVIDER_ANALYST]


# --- communities -----------------------------------------------------------
@bp.post("/communities")
def register_community():
    authorize(ANALYST)
    body = read_body(
        [
            Field("community_id_code"),
            Field("name"),
            Field("state_code", "enum", enum=enums.STATE_CODES),
            Field(
                "participation_status",
                "enum",
                required=False,
                default="REGULAR",
                enum=enums.PARTICIPATION_STATUSES,
            ),
            Field("cbrs_flag", "bool", required=False, default=False),
            Field(
                "probation_surcharge_cents",
                "int",
                required=False,
                default=0,
                min_value=0,
            ),
        ]
    )
    for existing in all_rows("communities"):
        if existing["community_id_code"] == body["community_id_code"]:
            fail(
                "ERR_INVALID_REQUEST",
                "community_id_code '%s' is already registered."
                % body["community_id_code"],
            )
    row = new_row(
        community_id_code=body["community_id_code"],
        name=body["name"],
        state_code=body["state_code"],
        participation_status=body["participation_status"],
        cbrs_flag=body["cbrs_flag"],
        probation_surcharge_cents=body["probation_surcharge_cents"],
        coverage_availability=None,
        last_participation_change_at=db.now(),
        active_folio_count=0,
    )
    row["coverage_availability"] = calc.coverage_availability(row)
    return created(store("communities", row))


@bp.post("/communities/<community_id>/participation-changes")
def change_participation(community_id):
    authorize(ANALYST)
    body = read_body(
        [
            Field(
                "participation_status", "enum", enum=enums.PARTICIPATION_STATUSES
            ),
            Field("probation_surcharge_cents", "int", required=False, min_value=0),
        ]
    )
    community = must("communities", community_id)
    community["participation_status"] = body["participation_status"]
    if "probation_surcharge_cents" in body:
        community["probation_surcharge_cents"] = body["probation_surcharge_cents"]
    community["coverage_availability"] = calc.coverage_availability(community)
    community["last_participation_change_at"] = db.now()

    unavailable = community["coverage_availability"] == "UNAVAILABLE"
    for folio in all_rows("loan_folios"):
        prop = db.properties.get(folio["property_id"])
        if prop is None or prop["community_id"] != community["id"]:
            continue
        if folio["monitoring_status"] == "ACTIVE" and unavailable:
            folio["monitoring_status"] = "SUSPENDED"
        elif folio["monitoring_status"] == "SUSPENDED" and not unavailable:
            folio["monitoring_status"] = "ACTIVE"
        touch_folio(folio)

    recount_active_folio_count(community)
    touch(community)
    return ok(community)


# --- lenders ---------------------------------------------------------------
@bp.post("/lenders")
def register_lender():
    authorize(ANALYST)
    body = read_body(
        [
            Field("name"),
            Field("contact_email"),
            Field(
                "force_placement_authorized_flag", "bool", required=False, default=True
            ),
            Field("escrow_servicing_flag", "bool", required=False, default=True),
        ]
    )
    row = new_row(
        name=body["name"],
        contact_email=body["contact_email"],
        force_placement_authorized_flag=body["force_placement_authorized_flag"],
        escrow_servicing_flag=body["escrow_servicing_flag"],
        open_force_placement_count=0,
    )
    return created(store("lenders", row))


# --- properties ------------------------------------------------------------
def _geocode_fields():
    return [
        Field("latitude", "number", scale=6),
        Field("longitude", "number", scale=6),
        Field("geocode_method", "enum", enum=enums.GEOCODE_METHODS),
        Field(
            "geocode_confidence_score",
            "number",
            scale=2,
            min_value=0,
            max_value=1,
        ),
    ]


@bp.post("/properties")
def register_property():
    authorize(ANALYST)
    body = read_body(
        [
            Field("community_id"),
            Field("street_address"),
            Field("city"),
            Field("postal_code"),
            Field("map_panel_number"),
        ]
        + _geocode_fields()
    )
    must("communities", body["community_id"])
    row = new_row(
        community_id=body["community_id"],
        street_address=body["street_address"],
        city=body["city"],
        postal_code=body["postal_code"],
        map_panel_number=body["map_panel_number"],
        latitude=body["latitude"],
        longitude=body["longitude"],
        geocode_method=body["geocode_method"],
        geocode_confidence_score=body["geocode_confidence_score"],
        geocode_status=calc.geocode_status(
            body["geocode_method"], body["geocode_confidence_score"]
        ),
        geocode_buffer_ft=calc.geocode_buffer_ft(body["geocode_method"]),
        geocode_corrected_count=0,
        structure_count=0,
    )
    return created(store("properties", row))


@bp.post("/properties/<property_id>/geocode-corrections")
def correct_geocode(property_id):
    authorize(ANALYST)
    body = read_body(_geocode_fields())
    prop = must("properties", property_id)

    # HOP 1: the four supplied values replace the stored ones.
    prop["latitude"] = body["latitude"]
    prop["longitude"] = body["longitude"]
    prop["geocode_method"] = body["geocode_method"]
    prop["geocode_confidence_score"] = body["geocode_confidence_score"]
    prop["geocode_status"] = calc.geocode_status(
        body["geocode_method"], body["geocode_confidence_score"]
    )
    prop["geocode_buffer_ft"] = calc.geocode_buffer_ft(body["geocode_method"])
    prop["geocode_corrected_count"] = prop["geocode_corrected_count"] + 1
    touch(prop)

    # HOP 2: the parcel effectively moved, so its issued determinations are flagged.
    geocode_correction_cascade(prop)
    return ok(prop)


# --- structures ------------------------------------------------------------
@bp.post("/structures")
def add_structure():
    authorize(ANALYST)
    body = read_body(
        [
            Field("property_id"),
            Field("structure_label"),
            Field("occupancy_type", "enum", enum=enums.OCCUPANCY_TYPES),
            Field("foundation_type", "enum", enum=enums.FOUNDATION_TYPES),
            Field("replacement_cost_cents", "int", gt=0),
            Field("sfha_offset_ft", "number"),
            Field("post_firm_flag", "bool", required=False, default=True),
            Field("fill_placed_flag", "bool", required=False, default=False),
        ]
    )
    prop = must("properties", body["property_id"])
    row = new_row(
        property_id=prop["id"],
        structure_label=body["structure_label"],
        occupancy_type=body["occupancy_type"],
        foundation_type=body["foundation_type"],
        replacement_cost_cents=body["replacement_cost_cents"],
        sfha_offset_ft=body["sfha_offset_ft"],
        post_firm_flag=body["post_firm_flag"],
        fill_placed_flag=body["fill_placed_flag"],
        lowest_floor_elevation_ft=None,
        lowest_adjacent_grade_ft=None,
        elevation_source_certificate_id=None,
    )
    store("structures", row)
    recount_structure_count(prop)
    touch(prop)
    return created(row)
