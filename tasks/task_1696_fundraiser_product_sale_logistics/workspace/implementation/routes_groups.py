"""StudentGroup endpoints."""

from flask import Blueprint

import db
import errors
import helpers
import middleware
import services
from helpers import (
    get_campaign, get_group, new_id, now_iso, paginate, sort_created, ledger_sort,
    req_string, opt_string, req_int,
    serialize_group, serialize_seller, serialize_ledger_entry,
)
from middleware import get_body, parse_pagination
from response import success_object, success_list

bp = Blueprint("groups", __name__)


@bp.post("/fundraiser/groups")
def create_group():
    middleware.require_role("GroupCoordinator")
    body = get_body(required=True)
    campaign_id = req_string(body, "campaign_id")
    name = req_string(body, "name")
    teacher_name = opt_string(body, "teacher_name", default=None)
    campaign = get_campaign(campaign_id)
    if campaign["status"] not in ("DRAFT", "OPEN"):
        raise errors.err_invalid_state("Groups may only be created while the campaign is DRAFT or OPEN")
    for g in db.groups.values():
        if g["campaign_id"] == campaign_id and g["name"] == name:
            raise errors.err_duplicate_group_name()
    gid = new_id()
    group = {
        "id": gid,
        "campaign_id": campaign_id,
        "name": name,
        "teacher_name": teacher_name,
        "provisional_proceeds_cents": 0,
        "proceeds_balance_cents": 0,
        "final_proceeds_cents": None,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "version": 1,
    }
    db.groups[gid] = group
    return success_object(serialize_group(group), status=201)


@bp.get("/fundraiser/groups/<gid>")
def read_group(gid):
    middleware.any_role()
    group = get_group(gid)
    return success_object(serialize_group(group))


@bp.get("/fundraiser/groups/<gid>/sellers")
def list_group_sellers(gid):
    middleware.any_role()
    get_group(gid)
    limit, offset = parse_pagination()
    items = sort_created([s for s in db.sellers.values() if s["group_id"] == gid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_seller(s) for s in page], limit, offset, total)


@bp.get("/fundraiser/groups/<gid>/ledger")
def list_group_ledger(gid):
    middleware.require_role("FundraiserAdmin", "Treasurer")
    get_group(gid)
    limit, offset = parse_pagination()
    items = ledger_sort([e for e in db.ledger_entries.values() if e["group_id"] == gid])
    page, total = paginate(items, limit, offset)
    return success_list([serialize_ledger_entry(e) for e in page], limit, offset, total)


@bp.post("/fundraiser/groups/<gid>/adjustments")
def post_adjustment(gid):
    middleware.require_role("Treasurer")
    group = get_group(gid)
    body = get_body(required=True)
    amount = req_int(body, "amount_cents")
    memo = req_string(body, "memo")
    entry = services.post_ledger_entry(
        group_id=gid, campaign_id=group["campaign_id"],
        entry_type="MANUAL_ADJUSTMENT", amount_cents=amount,
        reference_type=None, reference_id=None,
        memo=memo,
    )
    group["provisional_proceeds_cents"] = services.recompute_group_provisional(gid)
    helpers.touch(group)
    return success_object(serialize_ledger_entry(entry), status=201)
