"""Equipment pools, their maintenance, and equipment issues."""

from flask import Blueprint

import calc
import cascade
import serial
import validate as v
from envelope import created, ok, ok_list
from errors import ApiError
from routes_venue import get_venue
from store import db, ordered, stamp_new, touch

bp = Blueprint("equipment", __name__)

ASSET_CLASSES = ("STAGE_DECK", "DASHER_BOARD_SET", "FLOOR_PANEL_SET", "CURTAIN_SYSTEM",
                 "ICE_COVER_PANEL_SET", "BASKETBALL_FLOOR")
MAINTENANCE_ACTIONS = ("START", "COMPLETE")


def get_asset(asset_id):
    asset = db.assets.get(asset_id)
    if asset is None:
        raise ApiError("ERR_EQUIPMENT_NOT_FOUND")
    return asset


def get_issue(issue_id):
    issue = db.issues.get(issue_id)
    if issue is None:
        raise ApiError("ERR_EQUIPMENT_NOT_FOUND")
    return issue


@bp.post("/venues/<venue_id>/equipment-assets")
def create_asset(venue_id):
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    fields = {
        "asset_class": v.req_enum(payload, "asset_class", ASSET_CLASSES),
        "units_total": v.req_int(payload, "units_total", 1, 500),
        "service_interval_cycles": v.opt_int(payload, "service_interval_cycles", 12, 1, 200),
    }
    venue = get_venue(venue_id)
    fields["venue_id"] = venue["id"]
    fields["units_out_of_service"] = 0
    fields["cycles_since_service"] = 0
    fields["status"] = "IN_SERVICE"
    stamp_new(fields)
    db.assets[fields["id"]] = fields
    return created(serial.asset(fields))


@bp.get("/venues/<venue_id>/equipment-assets")
def list_venue_assets(venue_id):
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    venue = get_venue(venue_id)
    asset_class = v.filter_arg("asset_class")
    status = v.filter_arg("status")
    matched = [a for a in db.assets.values() if a["venue_id"] == venue["id"]]
    if asset_class is not None:
        matched = [a for a in matched if a["asset_class"] == asset_class]
    if status is not None:
        matched = [a for a in matched if a["status"] == status]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.asset(a) for a in page], limit, offset, total)


@bp.get("/equipment-assets/<asset_id>")
def read_asset(asset_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.asset(get_asset(asset_id)))


@bp.post("/equipment-assets/<asset_id>/maintenance")
def maintenance(asset_id):
    v.auth(("VenueOperationsDirector",))
    payload = v.body()
    action = v.req_enum(payload, "action", MAINTENANCE_ACTIONS)
    asset = get_asset(asset_id)
    if action == "START":
        if asset["status"] != "IN_SERVICE":
            raise ApiError("ERR_INVALID_ISSUE_STATE")
        if calc.outstanding_issued_units(asset["id"]) > 0:
            raise ApiError("ERR_INVALID_ISSUE_STATE",
                           "The pool still has units out on issue.")
        asset["status"] = "OUT_OF_SERVICE"
    else:
        if asset["status"] != "OUT_OF_SERVICE":
            raise ApiError("ERR_INVALID_ISSUE_STATE")
        asset["status"] = "IN_SERVICE"
        asset["units_out_of_service"] = 0
        asset["cycles_since_service"] = 0
    touch(asset)
    return ok(serial.asset(asset))


@bp.post("/equipment-issues")
def create_issue():
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    asset_id = v.req_id(payload, "asset_id")
    order_id = v.req_id(payload, "changeover_order_id")
    units_issued = v.req_int(payload, "units_issued", 1)

    asset = get_asset(asset_id)
    order = db.orders.get(order_id)
    if order is None:
        raise ApiError("ERR_CHANGEOVER_ORDER_NOT_FOUND")

    # Ladder 9: from-state legality on the changeover order.
    if order["status"] in calc.TERMINAL_ORDER_STATES:
        raise ApiError("ERR_INVALID_ORDER_STATE")
    # Ladder 11: pool availability for issue.
    if asset["status"] != "IN_SERVICE":
        raise ApiError("ERR_ASSET_OUT_OF_SERVICE")
    # Ladder 16: constraint satisfaction.
    if units_issued > calc.equipment_units_available(asset):
        raise ApiError("ERR_EQUIPMENT_UNITS_UNAVAILABLE")
    # Ladder 17: referential scoping.
    if asset["venue_id"] != order["venue_id"]:
        raise ApiError("ERR_VENUE_SCOPE_MISMATCH")

    row = {
        "asset_id": asset["id"],
        "changeover_order_id": order["id"],
        "units_issued": units_issued,
        "damaged_units": 0,
        "status": "ISSUED",
        "returned_at_utc": None,
        "return_reason": None,
    }
    stamp_new(row)
    db.issues[row["id"]] = row
    return created(serial.issue(row))


@bp.get("/equipment-issues/<issue_id>")
def read_issue(issue_id):
    v.auth(v.ALL_ROLES)
    return ok(serial.issue(get_issue(issue_id)))


@bp.get("/equipment-issues")
def list_issues():
    v.auth(v.ALL_ROLES)
    limit, offset = v.pagination()
    asset_id = v.filter_arg("asset_id")
    order_id = v.filter_arg("changeover_order_id")
    status = v.filter_arg("status")
    matched = list(db.issues.values())
    if asset_id is not None:
        matched = [i for i in matched if i["asset_id"] == asset_id]
    if order_id is not None:
        matched = [i for i in matched if i["changeover_order_id"] == order_id]
    if status is not None:
        matched = [i for i in matched if i["status"] == status]
    matched = ordered(matched)
    page, total = v.paginate(matched, limit, offset)
    return ok_list([serial.issue(i) for i in page], limit, offset, total)


@bp.post("/equipment-issues/<issue_id>/return")
def return_units(issue_id):
    v.auth(("ChangeoverSupervisor",))
    payload = v.body()
    damaged_units = v.opt_int(payload, "damaged_units", 0, 0)
    issue = get_issue(issue_id)
    # Ladder 5: damaged_units no greater than the issue's units_issued.
    if damaged_units > int(issue["units_issued"]):
        v.bad("damaged_units may not exceed units_issued.")
    # Ladder 9: from-state legality.
    if issue["status"] != "ISSUED":
        raise ApiError("ERR_INVALID_ISSUE_STATE")
    cascade.return_issue(issue, damaged_units, "OPERATOR_RETURN")
    return ok(serial.issue(issue))
