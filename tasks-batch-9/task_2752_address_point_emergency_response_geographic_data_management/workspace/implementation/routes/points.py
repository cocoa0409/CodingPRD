"""Address points, subaddress units and confidence scoring."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from store import base_record, db, sorted_rows, touch

bp = Blueprint("points", __name__)

SIDES = ["LEFT", "RIGHT"]
SOURCES = ["PARCEL", "PERMIT", "POSTAL", "FIELD"]
UNIT_TYPES = ["UNIT", "APT", "STE", "BLDG"]
POINT_STATUSES = ["PENDING", "ACTIVE", "RETIRED", "VOIDED"]
LIVE = ("PENDING", "ACTIVE")


def _subaddress_invalid(why):
    raise ApiError("ERR_SUBADDRESS_PARENT_INVALID", why)


def duplicate_exists(road_id, side, house_number, suffix, unit_id):
    key = (road_id, side, house_number, suffix, unit_id)
    for row in db.points.values():
        if row["status"] not in LIVE:
            continue
        other = (row["road_centerline_id"], row["side"], row["house_number"],
                 row["house_number_suffix"], row["unit_id"])
        if other == key:
            return True
    return False


def mint_point(**fields):
    """Create an address point row from already-validated field values."""
    row = base_record()
    row.update({
        "house_number": fields["house_number"],
        "house_number_suffix": fields.get("house_number_suffix"),
        "road_centerline_id": fields["road_centerline_id"],
        "side": fields["side"],
        "unit_type": fields.get("unit_type"),
        "unit_id": fields.get("unit_id"),
        "parent_address_point_id": fields.get("parent_address_point_id"),
        "jurisdiction_id": fields.get("jurisdiction_id"),
        "cell_id": fields.get("cell_id"),
        "source": fields["source"],
        "postal_city": fields.get("postal_city"),
        "geometry_verified": bool(fields.get("geometry_verified")),
        "latitude": fields.get("latitude"),
        "longitude": fields.get("longitude"),
        "status": "PENDING",
        "confidence_score": None,
        "certified_confidence_score": None,
        "confidence_basis": "PROVISIONAL",
        "superseded_by_address_point_id": None,
        "retired_at": None,
        "retire_reason": None,
    })
    row["confidence_score"] = calc.confidence_score(row, "provisional")
    db.points[row["id"]] = row
    return row


@bp.post("/address-points")
def create_point():
    v.auth(["GisAnalyst"])
    data = v.body()
    road = v.maybe_find("road", v.raw_ref(data, "road_centerline_id"))
    cell = v.maybe_find("cell", v.raw_ref(data, "cell_id"))
    parent = v.maybe_find("point", v.raw_ref(data, "parent_address_point_id"))

    house_number = v.req_int(data, "house_number", 0, 999999)
    v.req_id(data, "road_centerline_id")
    side = v.req_enum(data, "side", SIDES)
    source = v.req_enum(data, "source", SOURCES)
    postal_city = v.req_str(data, "postal_city", 1, 60)
    v.req_id(data, "cell_id")
    suffix = v.opt_str(data, "house_number_suffix", 1, 4, r"^[A-Z]{1,4}$")
    unit_type = v.opt_enum(data, "unit_type", UNIT_TYPES)
    unit_id = v.opt_str(data, "unit_id", 1, 8, r"^[A-Z0-9]{1,8}$")
    parent_id = v.opt_id(data, "parent_address_point_id")
    geometry_verified = v.opt_bool(data, "geometry_verified", False)
    latitude = v.opt_number(data, "latitude", -90, 90)
    longitude = v.opt_number(data, "longitude", -180, 180)

    # ---- 1: subaddress shape ------------------------------------------------
    if unit_id is not None and parent_id is None:
        _subaddress_invalid("unit_id may not be supplied without parent_address_point_id.")
    if parent_id is not None and unit_id is None:
        _subaddress_invalid("parent_address_point_id may not be supplied without unit_id.")
    if unit_type is not None and unit_id is None:
        _subaddress_invalid("unit_type may not be supplied without unit_id.")
    if parent is not None:
        if parent.get("parent_address_point_id") is not None:
            _subaddress_invalid("Subaddress units may not nest beneath another unit.")
        if parent["status"] in ("RETIRED", "VOIDED"):
            _subaddress_invalid("The nominated parent is %s." % parent["status"])
        if parent["road_centerline_id"] != road["id"]:
            _subaddress_invalid("The nominated parent sits on a different centerline.")
        if parent["side"] != side:
            _subaddress_invalid("The nominated parent sits on the other side of the centerline.")
        if parent["house_number"] != house_number:
            _subaddress_invalid("A unit must carry its parent's house_number %d."
                                % parent["house_number"])

    # ---- 2: parity ----------------------------------------------------------
    low, high, parity = calc.side_range(road, side)
    want = 0 if parity == "EVEN" else 1
    if house_number % 2 != want:
        raise ApiError("ERR_ADDRESS_PARITY_MISMATCH",
                       "house_number %d does not carry the %s side parity %s."
                       % (house_number, side, parity))

    # ---- 3: range membership ------------------------------------------------
    if low is None or high is None or not (low <= house_number <= high):
        raise ApiError("ERR_ADDRESS_OUTSIDE_RANGE",
                       "house_number %d falls outside the %s range %s-%s."
                       % (house_number, side, low, high))

    # ---- 4: duplication -----------------------------------------------------
    if duplicate_exists(road["id"], side, house_number, suffix, unit_id):
        raise ApiError("ERR_DUPLICATE_ADDRESS",
                       "That address is already held by a PENDING or ACTIVE point.")

    row = mint_point(
        house_number=house_number,
        house_number_suffix=suffix,
        road_centerline_id=road["id"],
        side=side,
        unit_type=unit_type,
        unit_id=unit_id,
        parent_address_point_id=parent_id,
        jurisdiction_id=road["jurisdiction_id"],
        cell_id=cell["id"],
        source=source,
        postal_city=postal_city.upper(),
        geometry_verified=geometry_verified,
        latitude=latitude,
        longitude=longitude,
    )
    return created(ser.point(row))


@bp.get("/address-points/<identifier>")
def get_point(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("point", identifier)
    return ok(ser.point(row))


@bp.get("/address-points")
def list_points():
    v.auth(v.ALL_ROLES)
    road_id = v.q_str("road_centerline_id")
    if road_id is not None:
        v.find("road", road_id)
    parent_id = v.q_str("parent_address_point_id")
    if parent_id is not None:
        v.find("point", parent_id)
    successor_id = v.q_str("superseded_by_address_point_id")
    if successor_id is not None:
        v.find("point", successor_id)
    cell_id = v.q_str("cell_id")
    if cell_id is not None:
        v.find("cell", cell_id)
    jurisdiction_id = v.q_str("jurisdiction_id")
    if jurisdiction_id is not None:
        v.find("jurisdiction", jurisdiction_id)
    status = v.q_enum("status", POINT_STATUSES)
    side = v.q_enum("side", SIDES)
    include_retired = v.q_bool("include_retired", False)
    limit, offset = v.pagination()

    rows = sorted_rows(list(db.points.values()))
    if not include_retired:
        rows = [r for r in rows if r["status"] in LIVE]
    if road_id is not None:
        rows = [r for r in rows if r["road_centerline_id"] == road_id]
    if parent_id is not None:
        rows = [r for r in rows if r["parent_address_point_id"] == parent_id]
    if successor_id is not None:
        rows = [r for r in rows if r["superseded_by_address_point_id"] == successor_id]
    if cell_id is not None:
        rows = [r for r in rows if r["cell_id"] == cell_id]
    if jurisdiction_id is not None:
        rows = [r for r in rows if r["jurisdiction_id"] == jurisdiction_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if side is not None:
        rows = [r for r in rows if r["side"] == side]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.point(r) for r in page], limit, offset, total)


@bp.post("/address-points/<identifier>/activate")
def activate_point(identifier):
    v.auth(["GisAnalyst"])
    point = v.find("point", identifier)
    if point["status"] != "PENDING":
        raise ApiError("ERR_ADDRESS_POINT_INVALID_STATE",
                       "Only a PENDING address point may be activated; this one is %s."
                       % point["status"])
    road = db.roads.get(point["road_centerline_id"])
    if road is None or road["status"] not in ("VALIDATED", "PUBLISHED"):
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "The centerline must be VALIDATED or PUBLISHED before its addresses "
                       "may be activated.")
    if calc.open_discrepancy_case_count(road["id"]) > 0:
        raise ApiError("ERR_ROAD_FROZEN_BY_DISCREPANCY")
    if point["unit_id"] is not None:
        parent = db.points.get(point["parent_address_point_id"])
        if parent is None or parent["status"] != "ACTIVE":
            raise ApiError("ERR_ADDRESS_POINT_INVALID_STATE",
                           "A subaddress unit may only be activated once its parent is ACTIVE.")

    point["status"] = "ACTIVE"
    point["confidence_score"] = calc.confidence_score(point, "provisional")
    touch(point)
    cascade.pin_staleness_for_point(point)
    return ok(ser.point(point))


@bp.post("/address-points/<identifier>/retire")
def retire_point(identifier):
    v.auth(["GisAnalyst"])
    point = v.find("point", identifier)
    data = v.body()
    successor = v.maybe_find("point", v.raw_ref(data, "superseded_by_address_point_id"))
    v.req_str(data, "retire_reason", 1)
    successor_id = v.opt_id(data, "superseded_by_address_point_id")

    if point["status"] not in LIVE:
        raise ApiError("ERR_ADDRESS_POINT_INVALID_STATE",
                       "A %s address point cannot be retired." % point["status"])
    if successor is not None and successor["status"] not in LIVE:
        raise ApiError("ERR_ADDRESS_POINT_INVALID_STATE",
                       "The nominated successor is %s." % successor["status"])

    point["superseded_by_address_point_id"] = successor_id
    cascade.terminate_point(point, "RETIRED",
                            "REPLACED" if successor_id is not None else "ANALYST_RETIRED")
    cascade.retire_child_units(point)
    return ok(ser.point(point))
