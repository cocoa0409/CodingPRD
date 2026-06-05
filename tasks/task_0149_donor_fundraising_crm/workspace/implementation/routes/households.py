"""Household endpoints (CampaignManager owns mutations; all roles read)."""

from flask import Blueprint, request

import db
import errors
import lookup
import models
import response
import services
import util
from middleware import authenticate, require_role

bp = Blueprint("households", __name__)

POLICIES = {"FULL_TO_ALL", "SPLIT_EVEN", "PRIMARY_ONLY"}
ALL_ROLES = {"GiftAdmin", "CampaignManager", "DonorRelations"}


def _serialize(h):
    services.recompute_household_member_count(h)
    services.recompute_household_total(h)
    return models.serialize(h)


@bp.post("/households")
def create_household():
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        body = util.get_json_body()
        name = util.req_string(body, "name", min_len=1, max_len=120)
        policy = util.opt_enum(body, "soft_credit_policy", POLICIES, default="FULL_TO_ALL")
        primary_donor_id = util.opt_id(body, "primary_donor_id", default=None)
        # primary_donor_id existence is validated only on PATCH per the spec
        # (creation default is null; membership check is a PATCH rule §1.4 p17).
        h = models.new_record({
            "name": name,
            "primary_donor_id": primary_donor_id,
            "soft_credit_policy": policy,
            "total_soft_credit_cents": 0,
            "member_count": 0,
        }, common=True)
        db.households[h["id"]] = h
        return response.object_response(models.serialize(h), status=201)


@bp.get("/households/<hid>")
def get_household(hid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        h = lookup.household(hid)
        return response.object_response(_serialize(h))


@bp.get("/households")
def list_households():
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        limit, offset = util.parse_pagination()
        primary = request.args.get("primary_donor_id")
        rows = list(db.households.values())
        if primary is not None:
            rows = [h for h in rows if h.get("primary_donor_id") == primary]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        for h in page:
            services.recompute_household_member_count(h)
            services.recompute_household_total(h)
        return response.array_response(models.serialize_list(page), limit, offset, total)


@bp.patch("/households/<hid>")
def patch_household(hid):
    _, role = authenticate()
    require_role(role, {"CampaignManager"})
    with db.LOCK:
        h = lookup.household(hid)
        body = util.get_json_body()

        new_name = None
        new_policy = None
        new_primary = None
        set_primary = False

        if "name" in body and body["name"] is not None:
            new_name = util.req_string(body, "name", min_len=1, max_len=120)
        if "soft_credit_policy" in body and body["soft_credit_policy"] is not None:
            new_policy = util.req_enum(body, "soft_credit_policy", POLICIES)
        if "primary_donor_id" in body:
            set_primary = True
            new_primary = util.opt_id(body, "primary_donor_id", default=None)

        # Existence of primary donor FK (ERR_NOT_FOUND) before membership rule.
        if set_primary and new_primary is not None:
            donor = lookup.donor(new_primary)
            # §1.4 priority 17: must be a member of this household.
            if donor.get("household_id") != h["id"]:
                raise errors.ApiError(errors.ERR_PRIMARY_NOT_MEMBER, 422,
                                      "primary_donor_id is not a member of the household.")

        if new_name is not None:
            h["name"] = new_name
        if new_policy is not None:
            h["soft_credit_policy"] = new_policy
        if set_primary:
            h["primary_donor_id"] = new_primary

        models.touch(h)
        return response.object_response(_serialize(h))


@bp.get("/households/<hid>/soft-credits")
def list_household_soft_credits(hid):
    _, role = authenticate()
    require_role(role, ALL_ROLES)
    with db.LOCK:
        lookup.household(hid)
        limit, offset = util.parse_pagination()
        rows = [sc for sc in db.soft_credits.values() if sc["household_id"] == hid]
        rows = util.sort_by_created(rows)
        page, total = util.paginate(rows, limit, offset)
        return response.array_response(models.serialize_list(page), limit, offset, total)
