"""Parcel endpoints (PRD 3.2)."""

from flask import Blueprint, g, request

from db import base_row, created_key, db, touch
from errors import ApiError
from middleware import authenticate, require_owner
from response import created, listing, ok, pagination
from services import calc, lookup, serialize
from validation import Payload, body_fk, raw_body

bp = Blueprint("parcels", __name__)

PARCEL_STATUSES = ("ELIGIBLE", "UNDER_APPLICATION", "ENCUMBERED", "WITHDRAWN")

CREATE_FIELDS = (
    "landowner_id",
    "county",
    "acres",
    "prime_soil_acres",
    "statewide_important_soil_acres",
    "contiguous_preserved_acres",
    "road_frontage_feet",
    "sewer_available",
    "zoning_min_lot_acres",
    "baseline_dwelling_rights",
    "unrestricted_value_cents",
    "restricted_value_cents",
    "mortgage_lienholder_name",
)

PATCH_FIELDS = (
    "expected_parcel_version",
    "contiguous_preserved_acres",
    "road_frontage_feet",
    "sewer_available",
    "zoning_min_lot_acres",
    "unrestricted_value_cents",
    "restricted_value_cents",
    "mortgage_lienholder_name",
)


def _rescore(parcel):
    parcel["soil_quality_score"] = calc.parcel_soil_quality_score(
        parcel["acres"],
        parcel["prime_soil_acres"],
        parcel["statewide_important_soil_acres"],
    )
    parcel["development_pressure_score"] = calc.parcel_development_pressure_score(
        parcel["road_frontage_feet"],
        parcel["sewer_available"],
        parcel["zoning_min_lot_acres"],
    )


@bp.post("/parcels")
def create_parcel():
    _, role = authenticate(("Landowner", "ProgramAdmin"))
    body = raw_body()
    landowner = lookup.get_landowner(body_fk(body, "landowner_id"))
    payload = Payload(body, CREATE_FIELDS)
    payload.string("landowner_id", min_len=1)
    county = payload.string("county", min_len=1, max_len=80)
    acres = payload.decimal("acres", exclusive_min=0)
    prime = payload.decimal("prime_soil_acres", minimum=0)
    important = payload.decimal("statewide_important_soil_acres", minimum=0)
    contiguous = payload.decimal("contiguous_preserved_acres", minimum=0)
    frontage = payload.integer("road_frontage_feet", minimum=0)
    sewer = payload.boolean("sewer_available")
    zoning = payload.decimal("zoning_min_lot_acres", exclusive_min=0)
    baseline = payload.integer("baseline_dwelling_rights", minimum=0)
    unrestricted = payload.integer("unrestricted_value_cents", minimum=1)
    restricted = payload.integer("restricted_value_cents", minimum=0)
    lienholder = payload.string(
        "mortgage_lienholder_name", required=False, default=None, min_len=1, max_len=160
    )
    if prime + important > acres:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "prime_soil_acres + statewide_important_soil_acres may not exceed acres",
        )
    if restricted >= unrestricted:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "restricted_value_cents must be strictly below unrestricted_value_cents",
        )

    if role == "Landowner":
        require_owner(landowner["id"])

    row = base_row()
    row.update(
        {
            "landowner_id": landowner["id"],
            "county": county,
            "acres": acres,
            "prime_soil_acres": prime,
            "statewide_important_soil_acres": important,
            "contiguous_preserved_acres": contiguous,
            "road_frontage_feet": frontage,
            "sewer_available": sewer,
            "zoning_min_lot_acres": zoning,
            "baseline_dwelling_rights": baseline,
            "unrestricted_value_cents": unrestricted,
            "restricted_value_cents": restricted,
            "mortgage_lienholder_name": lienholder,
            "status": "ELIGIBLE",
        }
    )
    _rescore(row)
    db.parcels[row["id"]] = row
    return created(serialize.parcel(row))


@bp.get("/parcels/<parcel_id>")
def read_parcel(parcel_id):
    authenticate(
        (
            "ProgramAdmin",
            "AcquisitionOfficer",
            "AppraisalReviewer",
            "StewardshipMonitor",
            "Landowner",
        )
    )
    return ok(serialize.parcel(lookup.get_parcel(parcel_id)))


@bp.get("/parcels")
def list_parcels():
    authenticate(
        ("ProgramAdmin", "AcquisitionOfficer", "StewardshipMonitor", "Landowner")
    )
    limit, offset = pagination(request.args)
    landowner_id = request.args.get("landowner_id")
    status = request.args.get("status")
    county = request.args.get("county")
    if status is not None and status not in PARCEL_STATUSES:
        raise ApiError("ERR_INVALID_REQUEST", "status filter is not a valid parcel status")
    rows = list(db.parcels.values())
    if landowner_id is not None:
        rows = [r for r in rows if r["landowner_id"] == landowner_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if county is not None:
        rows = [r for r in rows if r["county"] == county]
    rows.sort(key=lambda r: (r["created_at"], r["id"]))
    return listing(rows, limit, offset, serialize.parcel)


@bp.patch("/parcels/<parcel_id>")
def patch_parcel(parcel_id):
    authenticate(("ProgramAdmin",))
    parcel = lookup.get_parcel(parcel_id)
    payload = Payload(raw_body(), PATCH_FIELDS)
    expected = payload.integer("expected_parcel_version", minimum=0)
    contiguous = payload.decimal("contiguous_preserved_acres", required=False, minimum=0)
    frontage = payload.integer("road_frontage_feet", required=False, minimum=0)
    sewer = payload.boolean("sewer_available", required=False)
    zoning = payload.decimal("zoning_min_lot_acres", required=False, exclusive_min=0)
    unrestricted = payload.integer("unrestricted_value_cents", required=False, minimum=1)
    restricted = payload.integer("restricted_value_cents", required=False, minimum=0)
    lienholder_given = "mortgage_lienholder_name" in payload.body
    lienholder = payload.string(
        "mortgage_lienholder_name", required=False, default=None, min_len=1, max_len=160
    )

    if expected != parcel["version"]:
        raise ApiError(
            "ERR_STALE_PARCEL_VERSION", "expected_parcel_version does not match Parcel.version"
        )

    if contiguous is not None:
        parcel["contiguous_preserved_acres"] = contiguous
    if frontage is not None:
        parcel["road_frontage_feet"] = frontage
    if sewer is not None:
        parcel["sewer_available"] = sewer
    if zoning is not None:
        parcel["zoning_min_lot_acres"] = zoning
    if unrestricted is not None:
        parcel["unrestricted_value_cents"] = unrestricted
    if restricted is not None:
        parcel["restricted_value_cents"] = restricted
    if lienholder_given:
        parcel["mortgage_lienholder_name"] = lienholder

    _rescore(parcel)
    touch(parcel)
    return ok(serialize.parcel(parcel))
