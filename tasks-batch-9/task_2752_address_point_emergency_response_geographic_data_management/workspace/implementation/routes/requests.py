"""Address assignment requests for new construction: three parallel dimensions."""

from flask import Blueprint

import calc
import cascade
import serialize as ser
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes.points import mint_point
from store import base_record, db, sorted_rows, touch

bp = Blueprint("requests", __name__)

SIDES = ["LEFT", "RIGHT"]
REVIEW_STATUSES = ["PENDING_REVIEW", "GIS_APPROVED", "GIS_REJECTED"]
UTILITY_STATUSES = ["PENDING_UTILITY", "UTILITY_CLEARED", "UTILITY_HELD"]
FULFILLMENT_STATUSES = ["OPEN", "READY_TO_ASSIGN", "FULFILLED", "CLOSED_REJECTED", "VOIDED"]
LIVE = ("PENDING", "ACTIVE")


def _unit_sort_key(row):
    unit_id = row.get("unit_id") or ""
    if unit_id.isdigit():
        return (0, int(unit_id), "")
    return (1, 0, unit_id)


def _minted_points(request_row):
    """The base point and its units, base first then units by ascending unit_id."""
    base_id = request_row.get("assigned_address_point_id")
    if base_id is None:
        return []
    out = []
    base = db.points.get(base_id)
    if base is not None:
        out.append(base)
    units = [p for p in db.points.values() if p.get("parent_address_point_id") == base_id]
    out.extend(sorted(units, key=_unit_sort_key))
    return out


@bp.post("/address-assignment-requests")
def create_request():
    v.auth(["PermitCoordinator"])
    data = v.body()
    road = v.maybe_find("road", v.raw_ref(data, "road_centerline_id"))
    permit_number = v.req_str(data, "permit_number", 1, 32)
    parcel_id = v.req_str(data, "parcel_id", 1, 32)
    v.req_id(data, "road_centerline_id")
    side = v.req_enum(data, "side", SIDES)
    requested_unit_count = v.opt_int(data, "requested_unit_count", 0, 99, 0)
    proposed_house_number = v.opt_int(data, "proposed_house_number", 0, 999999)

    for row in db.requests.values():
        if row["permit_number"] == permit_number:
            raise ApiError("ERR_DUPLICATE_PERMIT_NUMBER",
                           "Permit number '%s' already has an assignment request." % permit_number)

    row = base_record()
    row.update({
        "permit_number": permit_number,
        "parcel_id": parcel_id,
        "road_centerline_id": road["id"],
        "side": side,
        "requested_unit_count": requested_unit_count,
        "proposed_house_number": proposed_house_number,
        "review_status": "PENDING_REVIEW",
        "utility_status": "PENDING_UTILITY",
        "fulfillment_status": "OPEN",
        "assigned_address_point_id": None,
        "assigned_house_number": None,
        "minted_point_count": 0,
        "review_note": None,
        "utility_note": None,
        "void_reason": None,
    })
    db.requests[row["id"]] = row
    return created(ser.request(row))


@bp.get("/address-assignment-requests/<identifier>")
def get_request(identifier):
    v.auth(v.ALL_ROLES)
    row = v.find("request", identifier)
    return ok(ser.request(row))


@bp.get("/address-assignment-requests")
def list_requests():
    v.auth(v.ALL_ROLES)
    road_id = v.q_str("road_centerline_id")
    if road_id is not None:
        v.find("road", road_id)
    point_id = v.q_str("assigned_address_point_id")
    if point_id is not None:
        v.find("point", point_id)
    review_status = v.q_enum("review_status", REVIEW_STATUSES)
    utility_status = v.q_enum("utility_status", UTILITY_STATUSES)
    fulfillment_status = v.q_enum("fulfillment_status", FULFILLMENT_STATUSES)
    permit_number = v.q_str("permit_number")
    limit, offset = v.pagination()

    rows = sorted_rows(list(db.requests.values()))
    if road_id is not None:
        rows = [r for r in rows if r["road_centerline_id"] == road_id]
    if point_id is not None:
        rows = [r for r in rows if r["assigned_address_point_id"] == point_id]
    if review_status is not None:
        rows = [r for r in rows if r["review_status"] == review_status]
    if utility_status is not None:
        rows = [r for r in rows if r["utility_status"] == utility_status]
    if fulfillment_status is not None:
        rows = [r for r in rows if r["fulfillment_status"] == fulfillment_status]
    if permit_number is not None:
        rows = [r for r in rows if r["permit_number"] == permit_number]
    page, total = v.page(rows, limit, offset)
    return ok_list([ser.request(r) for r in page], limit, offset, total)


@bp.post("/address-assignment-requests/<identifier>/gis-review")
def gis_review(identifier):
    v.auth(["GisAnalyst"])
    row = v.find("request", identifier)
    data = v.body()
    decision = v.req_enum(data, "decision", ["APPROVE", "REJECT"])
    note = v.opt_str(data, "review_note", 0, 500)

    if row["review_status"] != "PENDING_REVIEW":
        raise ApiError("ERR_REQUEST_INVALID_STATE",
                       "The review dimension is already %s." % row["review_status"])
    if row["fulfillment_status"] != "OPEN":
        raise ApiError("ERR_REQUEST_NOT_READY",
                       "The request's fulfillment_status is %s." % row["fulfillment_status"])

    if note is not None:
        row["review_note"] = note
    if decision == "APPROVE":
        row["review_status"] = "GIS_APPROVED"
        if row["utility_status"] == "UTILITY_CLEARED":
            row["fulfillment_status"] = "READY_TO_ASSIGN"
    else:
        row["review_status"] = "GIS_REJECTED"
        row["fulfillment_status"] = "CLOSED_REJECTED"
    touch(row)
    return ok(ser.request(row))


@bp.post("/address-assignment-requests/<identifier>/utility-clearance")
def utility_clearance(identifier):
    v.auth(["PermitCoordinator"])
    row = v.find("request", identifier)
    data = v.body()
    decision = v.req_enum(data, "decision", ["CLEAR", "HOLD"])
    note = v.opt_str(data, "utility_note", 0, 500)

    if row["fulfillment_status"] not in ("OPEN", "READY_TO_ASSIGN"):
        raise ApiError("ERR_REQUEST_INVALID_STATE",
                       "A request whose fulfillment_status is %s accepts no further utility "
                       "action." % row["fulfillment_status"])
    target = "UTILITY_CLEARED" if decision == "CLEAR" else "UTILITY_HELD"
    if row["utility_status"] == target:
        raise ApiError("ERR_REQUEST_INVALID_STATE",
                       "The utility dimension is already %s." % target)

    if note is not None:
        row["utility_note"] = note
    row["utility_status"] = target
    if target == "UTILITY_CLEARED":
        if row["review_status"] == "GIS_APPROVED":
            row["fulfillment_status"] = "READY_TO_ASSIGN"
    else:
        if row["fulfillment_status"] == "READY_TO_ASSIGN":
            row["fulfillment_status"] = "OPEN"
    touch(row)
    return ok(ser.request(row))


@bp.post("/address-assignment-requests/<identifier>/assign")
def assign(identifier):
    v.auth(["GisAnalyst"])
    row = v.find("request", identifier)
    if row["fulfillment_status"] != "READY_TO_ASSIGN":
        raise ApiError("ERR_REQUEST_NOT_READY",
                       "The request's fulfillment_status is %s, not READY_TO_ASSIGN."
                       % row["fulfillment_status"])
    road = db.roads.get(row["road_centerline_id"])
    if road is None or road["status"] == "RETIRED":
        raise ApiError("ERR_ROAD_INVALID_STATE",
                       "The centerline is RETIRED and can absorb no new addresses.")

    candidates = calc.candidate_house_numbers(road, row["side"])
    if not candidates:
        raise ApiError("ERR_NO_ASSIGNABLE_ADDRESS",
                       "The %s range on this centerline is exhausted." % row["side"])
    proposed = row["proposed_house_number"]
    if proposed is not None:
        if proposed not in candidates:
            raise ApiError("ERR_HOUSE_NUMBER_UNAVAILABLE",
                           "House number %d is not an available candidate on the %s side."
                           % (proposed, row["side"]))
        chosen = proposed
    else:
        chosen = candidates[0]

    jurisdiction = db.jurisdictions.get(road["jurisdiction_id"])
    postal_city = jurisdiction["postal_city"] if jurisdiction is not None else None
    cells = sorted([c for c in db.cells.values()
                    if c["jurisdiction_id"] == road["jurisdiction_id"]],
                   key=lambda c: c["cell_code"])
    cell_id = cells[0]["id"] if cells else None

    base = mint_point(
        house_number=chosen,
        road_centerline_id=road["id"],
        side=row["side"],
        jurisdiction_id=road["jurisdiction_id"],
        cell_id=cell_id,
        source="PERMIT",
        postal_city=postal_city,
        geometry_verified=False,
    )
    for index in range(1, row["requested_unit_count"] + 1):
        mint_point(
            house_number=chosen,
            road_centerline_id=road["id"],
            side=row["side"],
            unit_type="UNIT",
            unit_id=str(index),
            parent_address_point_id=base["id"],
            jurisdiction_id=road["jurisdiction_id"],
            cell_id=cell_id,
            source="PERMIT",
            postal_city=postal_city,
            geometry_verified=False,
        )

    row["assigned_house_number"] = chosen
    row["assigned_address_point_id"] = base["id"]
    row["minted_point_count"] = 1 + row["requested_unit_count"]
    row["fulfillment_status"] = "FULFILLED"
    touch(row)
    return ok(ser.request(row))


@bp.post("/address-assignment-requests/<identifier>/void")
def void_request(identifier):
    v.auth(["PermitCoordinator"])
    row = v.find("request", identifier)
    data = v.body()
    reason = v.req_str(data, "void_reason", 1)
    if row["fulfillment_status"] not in ("OPEN", "READY_TO_ASSIGN", "FULFILLED"):
        raise ApiError("ERR_REQUEST_NOT_READY",
                       "A request whose fulfillment_status is %s cannot be voided."
                       % row["fulfillment_status"])

    was_fulfilled = row["fulfillment_status"] == "FULFILLED"
    row["void_reason"] = reason
    row["fulfillment_status"] = "VOIDED"
    touch(row)

    if was_fulfilled:
        for point in _minted_points(row):
            if point["status"] not in LIVE:
                continue
            cascade.terminate_point(point, "VOIDED", "REQUEST_VOIDED")
    return ok(ser.request(row))
