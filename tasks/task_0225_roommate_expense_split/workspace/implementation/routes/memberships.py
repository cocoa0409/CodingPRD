"""Membership endpoints: read, list, activate (capacity/occupancy gates), and the
move-out redistribution cascade (PRD §3.3, §3.5)."""
from flask import Blueprint, request

import models
import response
from db import db
from errors import err
from middleware import authenticate, require_roles, parse_pagination, paginate
from services import calc
from services import household as hh

bp = Blueprint("memberships", __name__)

ALL_ROLES = {"Roommate", "DisputeMediator", "PlatformOperator"}


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        m = db.memberships.get(mid)
        if not m:
            raise err("ERR_NOT_FOUND", "Membership not found.")
        return response.ok(models.serialize(m))


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    with db.lock:
        p = authenticate()
        require_roles(p, ALL_ROLES)
        limit, offset = parse_pagination()
        items = list(db.memberships.values())
        profile_id = request.args.get("profile_id")
        household_id = request.args.get("household_id")
        if profile_id is not None:
            items = [x for x in items if x["profile_id"] == profile_id]
        if household_id is not None:
            items = [x for x in items if x["household_id"] == household_id]
        items = models.sort_by_created(items)
        page, meta = paginate(items, limit, offset)
        return response.ok_list(models.serialize_list(page), pagination=meta)


@bp.route("/memberships/<mid>/activate", methods=["POST"])
def activate_membership(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        m = db.memberships.get(mid)
        if not m:
            raise err("ERR_NOT_FOUND", "Membership not found.")
        household = db.households.get(m["household_id"])
        listing = hh.listing_for_household(household)
        # ownership: acting roommate must be the household manager (lister)
        if p.user_id != household["manager_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the manager may activate memberships.")
        # state: must be PENDING
        if m["status"] != "PENDING":
            raise err("ERR_INVALID_STATE", "Membership is not PENDING.")
        # household must be FORMING or ACTIVE
        if household["status"] not in ("FORMING", "ACTIVE"):
            raise err("ERR_INVALID_STATE", "Household is not in FORMING or ACTIVE state.")
        # priority 13: single-occupancy overlap (capacity == 1), BEFORE capacity gate
        if listing["capacity"] == 1:
            for other in hh.memberships_of(household["id"]):
                if other["id"] == m["id"] or other["status"] != "ACTIVE":
                    continue
                if calc.intervals_overlap(
                    m["move_in_date"], m["planned_move_out_date"],
                    other["move_in_date"], other["planned_move_out_date"],
                ):
                    raise err("ERR_OCCUPANCY_OVERLAP", "Occupancy interval overlaps an active member.")
        # priority 14: capacity count gate
        if household["active_member_count"] >= listing["capacity"]:
            raise err("ERR_ROOM_AT_CAPACITY", "Room is at capacity.")

        # ---- transition + cascade ----
        m["status"] = "ACTIVE"
        models.touch(m)
        hh.recompute_active_count(household)
        if household["status"] == "FORMING":
            household["status"] = "ACTIVE"
        if household["active_member_count"] >= listing["capacity"] and listing["status"] == "OPEN":
            listing["status"] = "CLOSED"
            models.touch(listing)
        hh.refresh_estimate(m, household)
        models.touch(household)
        return response.ok(models.serialize(m))


@bp.route("/memberships/<mid>/move-out", methods=["POST"])
def move_out_membership(mid):
    with db.lock:
        p = authenticate()
        require_roles(p, {"Roommate"})
        m = db.memberships.get(mid)
        if not m:
            raise err("ERR_NOT_FOUND", "Membership not found.")
        household = db.households.get(m["household_id"])
        # ownership: the membership's profile_id OR the household manager
        if p.user_id != m["profile_id"] and p.user_id != household["manager_id"]:
            raise err("ERR_NOT_RESOURCE_OWNER", "Only the member or manager may move out.")
        # state: must be ACTIVE
        if m["status"] != "ACTIVE":
            raise err("ERR_INVALID_STATE", "Membership is not ACTIVE.")
        # frozen gate (priority 7)
        if household["status"] == "FROZEN":
            raise err("ERR_HOUSEHOLD_FROZEN", "Household is frozen.")

        # ---- transition + deep cascade ----
        m["actual_move_out_date"] = db.now()
        m["status"] = "MOVED_OUT"
        models.touch(m)
        # final proration + split redistribution on the current-period unpaid RENT bill
        hh.apply_move_out_proration(household, m)
        # recompute active count (departing member now MOVED_OUT)
        hh.recompute_active_count(household)
        # recompute ledger / net balances; ledger_sum stays 0
        hh.recompute_net_balances(household)
        # dissolve if empty
        if household["active_member_count"] == 0:
            household["status"] = "DISSOLVED"
        # reopen listing if it had closed and is now below capacity
        hh.maybe_reopen_listing(household)
        models.touch(household)
        return response.ok(models.serialize(m))
