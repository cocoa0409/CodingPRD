"""Parcel enrollment, reclassification and subdivision (PRD 3.2)."""

from fractions import Fraction

from flask import Blueprint

import response as R
import validation as V
from db import by_seq, db, new_row, to_fraction, touch
from errors import ApiError
from middleware import READ_ALL, auth
from services import calc
from services import constants as C
from services import state as S

bp = Blueprint("parcels", __name__)


@bp.post("/parcels")
@auth("AssociationSecretary")
def create_parcel():
    body = V.get_body()
    road_segment_id = V.req_str(body, "road_segment_id")
    deed_book_page = V.req_str(body, "deed_book_page")
    frontage_feet = V.req_num(body, "frontage_feet", exclusive_minimum=0)
    usage_class = V.req_enum(body, "usage_class", C.USAGE_CLASSES)
    trips_per_day = V.req_num(body, "trips_per_day", minimum=0)
    covenant_recorded = V.req_bool(body, "covenant_recorded")

    S.require("segment", road_segment_id)

    row = new_row({
        "road_segment_id": road_segment_id,
        "parent_parcel_id": None,
        "deed_book_page": deed_book_page,
        "frontage_feet": frontage_feet,
        "usage_class": usage_class,
        "trips_per_day": trips_per_day,
        "covenant_recorded": covenant_recorded,
        "status": "ACTIVE",
        "frontage_share_units": Fraction(0),
        "trip_share_units": Fraction(0),
    })
    calc.parcel_units(row)
    db.parcels[row["id"]] = row
    return R.ok(row, 201)


@bp.get("/parcels/<parcel_id>")
@auth(*READ_ALL)
def read_parcel(parcel_id):
    return R.ok(S.require("parcel", parcel_id))


@bp.get("/parcels")
@auth(*READ_ALL)
def list_parcels():
    limit, offset = V.pagination()
    segment_id = V.query_str("road_segment_id")
    parent_id = V.query_str("parent_parcel_id")
    status = V.query_enum("status", C.PARCEL_STATUSES)

    rows = by_seq(list(db.parcels.values()))
    if segment_id is not None:
        rows = [r for r in rows if r["road_segment_id"] == segment_id]
    if parent_id is not None:
        rows = [r for r in rows if r["parent_parcel_id"] == parent_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = V.paginate(rows, limit, offset)
    return R.ok_list(page, limit, offset, total)


@bp.patch("/parcels/<parcel_id>")
@auth("AssociationSecretary")
def reclassify_parcel(parcel_id):
    body = V.get_body()
    expected_version = V.req_int(body, "expected_parcel_version", minimum=0)
    frontage_feet = V.opt_num(body, "frontage_feet", None, exclusive_minimum=0)
    usage_class = V.opt_enum(body, "usage_class", C.USAGE_CLASSES)
    trips_per_day = V.opt_num(body, "trips_per_day", None, minimum=0)

    parcel = S.require("parcel", parcel_id)

    if expected_version != parcel["version"]:
        raise ApiError("ERR_STALE_PARCEL_VERSION",
                       "expected_parcel_version does not match the parcel's current version.")

    association = S.association_of_parcel(parcel)
    if association is not None and S.has_certified_roll(association["id"]):
        raise ApiError("ERR_CERTIFIED_ROLL_LOCKED",
                       "A roll of this association is CERTIFIED; parcel data is frozen.")
    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_PARCEL_NOT_ACTIVE", "Only an ACTIVE parcel may be reclassified.")

    if frontage_feet is not None:
        parcel["frontage_feet"] = frontage_feet
    if usage_class is not None:
        parcel["usage_class"] = usage_class
    if trips_per_day is not None:
        parcel["trips_per_day"] = trips_per_day
    calc.parcel_units(parcel)
    touch(parcel)
    return R.ok(parcel)


@bp.post("/parcels/<parcel_id>/subdivide")
@auth("AssociationSecretary")
def subdivide_parcel(parcel_id):
    body = V.get_body()
    children = body.get("children")
    if not isinstance(children, list) or len(children) < 2:
        raise ApiError("ERR_INVALID_REQUEST",
                       "Field 'children' must be an array of at least two objects.")
    specs = []
    for index, child in enumerate(children):
        if not isinstance(child, dict):
            raise ApiError("ERR_INVALID_REQUEST",
                           "children[%d] must be an object." % index)
        specs.append((
            V.req_str(child, "deed_book_page"),
            V.req_num(child, "frontage_feet", exclusive_minimum=0),
        ))

    parcel = S.require("parcel", parcel_id)

    association = S.association_of_parcel(parcel)
    if association is not None and S.has_certified_roll(association["id"]):
        raise ApiError("ERR_CERTIFIED_ROLL_LOCKED",
                       "A roll of this association is CERTIFIED; parcel data is frozen.")
    if parcel["status"] != "ACTIVE":
        raise ApiError("ERR_PARCEL_NOT_ACTIVE", "Only an ACTIVE parcel may be subdivided.")

    total = sum((to_fraction(frontage) for _, frontage in specs), Fraction(0))
    if total != to_fraction(parcel["frontage_feet"]):
        raise ApiError("ERR_FRONTAGE_MISMATCH",
                       "The children's frontage_feet must sum exactly to the parent's frontage_feet.")

    for charge in S.by_parcel_charges(parcel["id"]):
        if charge["status"] in ("OPEN", "DELINQUENT", "LIEN_ENCUMBERED"):
            raise ApiError("ERR_PARCEL_HAS_OPEN_CHARGES",
                           "The parcel carries an outstanding assessment charge.")

    created = []
    for deed_book_page, frontage in specs:
        child = new_row({
            "road_segment_id": parcel["road_segment_id"],
            "parent_parcel_id": parcel["id"],
            "deed_book_page": deed_book_page,
            "frontage_feet": frontage,
            "usage_class": "UNDEVELOPED",
            "trips_per_day": 0,
            "covenant_recorded": False,
            "status": "PENDING_CONNECTION",
            "frontage_share_units": Fraction(0),
            "trip_share_units": Fraction(0),
        })
        calc.parcel_units(child)
        db.parcels[child["id"]] = child
        created.append(child)

    parcel["status"] = "SUBDIVIDED"
    touch(parcel)
    return R.ok({"parent_parcel": parcel, "children": created})
