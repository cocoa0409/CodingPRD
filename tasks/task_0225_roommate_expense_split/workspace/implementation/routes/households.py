"""Household read endpoints and reverse-reachability sub-resource lists (PRD §2.5)."""
from flask import Blueprint, request

import models
import response
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate

bp = Blueprint("households", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}


@bp.route("/households/<hid>", methods=["GET"])
def get_household(hid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        h = db.households.get(hid)
        if not h:
            raise err("ERR_NOT_FOUND", "Household not found.")
        return response.ok(models.serialize(h))


@bp.route("/households", methods=["GET"])
def list_households():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.households.values())
        manager_id = request.args.get("manager_id")
        listing_id = request.args.get("listing_id")
        if manager_id is not None:
            items = [x for x in items if x["manager_id"] == manager_id]
        if listing_id is not None:
            items = [x for x in items if x["listing_id"] == listing_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


def _sub_list(hid, collection, predicate):
    p = authenticate()
    require_roles(p, ALL_ROLES)
    if hid not in db.households:
        raise err("ERR_NOT_FOUND", "Household not found.")
    limit, offset = parse_pagination()
    items = [x for x in collection.values() if predicate(x)]
    items = models.sort_by_created(items)
    return paginate(items, limit, offset)


@bp.route("/households/<hid>/memberships", methods=["GET"])
def list_household_memberships(hid):
    with db.lock:
        page, meta = _sub_list(hid, db.memberships, lambda x: x["household_id"] == hid)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/households/<hid>/bills", methods=["GET"])
def list_household_bills(hid):
    with db.lock:
        page, meta = _sub_list(hid, db.bills, lambda x: x["household_id"] == hid)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/households/<hid>/expenses", methods=["GET"])
def list_household_expenses(hid):
    with db.lock:
        page, meta = _sub_list(hid, db.expenses, lambda x: x["household_id"] == hid)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/households/<hid>/settlements", methods=["GET"])
def list_household_settlements(hid):
    with db.lock:
        page, meta = _sub_list(hid, db.settlements, lambda x: x["household_id"] == hid)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/households/<hid>/disputes", methods=["GET"])
def list_household_disputes(hid):
    with db.lock:
        page, meta = _sub_list(hid, db.disputes, lambda x: x["household_id"] == hid)
        return response.ok_list(models.serialize_list(page), pagination=meta)
