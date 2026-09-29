"""Product categories, clubs, players and mark rights (PRD 3.1)."""

import re

from flask import Blueprint

import constants as K
import db
import middleware as mw
import response
import serializers
import validate as V
from db import S, apply_changes, touch
from errors import ApiError
from middleware import (ROLE_AGENT, ROLE_CLUB, ROLE_COMPLIANCE, ROLE_MANAGER, guard,
                        paginate, pagination)
from services import domain

bp = Blueprint("catalog", __name__)

CATEGORY_CODE_RE = re.compile(r"^[A-Z][A-Z0-9_]{2,39}$")
CLUB_CODE_RE = re.compile(r"^[A-Z]{3}$")
MARK_CODE_RE = re.compile(r"^[A-Z0-9_]{3,40}$")


def _bad(message):
    raise ApiError("ERR_VALIDATION", message)


# --------------------------------------------------------------------------- #
# product categories                                                          #
# --------------------------------------------------------------------------- #

def _validate_tier_schedule(raw):
    if not isinstance(raw, list):
        _bad("tier_schedule must be an array.")
    if len(raw) < 1 or len(raw) > 5:
        _bad("tier_schedule must hold between 1 and 5 tiers.")
    tiers = []
    for entry in raw:
        if not isinstance(entry, dict):
            _bad("tier_schedule entries must be objects.")
        from_cents = entry.get("from_cents")
        to_cents = entry.get("to_cents", None)
        rate_bps = entry.get("rate_bps")
        if isinstance(from_cents, bool) or not isinstance(from_cents, int) or from_cents < 0:
            _bad("tier_schedule from_cents must be an integer of at least 0.")
        if to_cents is not None:
            if isinstance(to_cents, bool) or not isinstance(to_cents, int) or to_cents < 0:
                _bad("tier_schedule to_cents must be an integer of at least 0 or null.")
        if isinstance(rate_bps, bool) or not isinstance(rate_bps, int):
            _bad("tier_schedule rate_bps must be an integer.")
        if rate_bps < 100 or rate_bps > 3000:
            _bad("tier_schedule rate_bps must be between 100 and 3000.")
        tiers.append({"from_cents": from_cents, "to_cents": to_cents,
                      "rate_bps": rate_bps})

    if tiers[0]["from_cents"] != 0:
        _bad("tier_schedule must start at from_cents 0.")
    for index, tier in enumerate(tiers):
        last = index == len(tiers) - 1
        if last:
            if tier["to_cents"] is not None:
                _bad("the last tier must carry a to_cents of null.")
        else:
            if tier["to_cents"] is None:
                _bad("only the last tier may carry a to_cents of null.")
            if tier["to_cents"] <= tier["from_cents"]:
                _bad("tier_schedule must ascend.")
            if tier["to_cents"] != tiers[index + 1]["from_cents"]:
                _bad("tier_schedule must be contiguous.")
    return tiers


def _range(value, name, low, high):
    if value < low or value > high:
        _bad("%s must be between %d and %d." % (name, low, high))


@bp.post("/licensing/product-categories")
def create_category():
    ctx = guard([ROLE_MANAGER])
    body = ctx.body

    code = V.req_string(body, "category_code", 3, 40)
    if not CATEGORY_CODE_RE.match(code):
        _bad("category_code has an invalid format.")
    display_name = V.req_string(body, "display_name", 1, 200)
    base_rate = V.req_bps(body, "base_royalty_rate_bps")
    _range(base_rate, "base_royalty_rate_bps", 100, 3000)
    if "tier_schedule" not in body or body["tier_schedule"] is None:
        _bad("tier_schedule is required.")
    tiers = _validate_tier_schedule(body["tier_schedule"])
    closeout_rate = V.req_bps(body, "closeout_rate_bps")
    _range(closeout_rate, "closeout_rate_bps", 50, 3000)
    closeout_cap = V.opt_bps(body, "closeout_cap_pct_bps", 1500)
    _range(closeout_cap, "closeout_cap_pct_bps", 0, 5000)
    closeout_hard = V.opt_bps(body, "closeout_hard_limit_bps", 4000)
    _range(closeout_hard, "closeout_hard_limit_bps", closeout_cap, 10000)
    deduction_cap = V.opt_bps(body, "deduction_cap_pct_bps", 500)
    _range(deduction_cap, "deduction_cap_pct_bps", 0, 5000)
    deduction_hard = V.opt_bps(body, "deduction_hard_limit_bps", 2000)
    _range(deduction_hard, "deduction_hard_limit_bps", deduction_cap, 10000)
    exclusivity_allowed = V.opt_bool(body, "exclusivity_allowed", True)
    mg_floor = V.req_cents(body, "minimum_guarantee_floor_cents")
    advance_floor = V.opt_bps(body, "advance_floor_bps_of_mg", 2500)
    usage_class = V.req_enum(body, "mark_usage_class", K.MARK_USAGE_CLASSES)
    central_default = V.opt_bool(body, "central_licensing_default", True)

    for existing in S.categories.values():
        if existing["category_code"] == code:
            _bad("category_code must be unique.")

    row = db.base_row()
    row.update({
        "category_code": code,
        "display_name": display_name,
        "base_royalty_rate_bps": base_rate,
        "tier_schedule": tiers,
        "closeout_rate_bps": closeout_rate,
        "closeout_cap_pct_bps": closeout_cap,
        "closeout_hard_limit_bps": closeout_hard,
        "deduction_cap_pct_bps": deduction_cap,
        "deduction_hard_limit_bps": deduction_hard,
        "exclusivity_allowed": exclusivity_allowed,
        "minimum_guarantee_floor_cents": mg_floor,
        "advance_floor_bps_of_mg": advance_floor,
        "mark_usage_class": usage_class,
        "central_licensing_default": central_default,
    })
    S.categories[row["id"]] = row
    return response.created(serializers.dump("ProductCategory", row))


@bp.get("/licensing/product-categories")
def list_categories():
    guard(mw.ALL_ROLES)
    limit, offset = pagination()
    usage = mw.filter_enum("mark_usage_class", K.MARK_USAGE_CLASSES)
    exclusivity = mw.filter_bool("exclusivity_allowed")
    rows = list(S.categories.values())
    if usage is not None:
        rows = [r for r in rows if r["mark_usage_class"] == usage]
    if exclusivity is not None:
        rows = [r for r in rows if r["exclusivity_allowed"] == exclusivity]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("ProductCategory", page),
                            limit, offset, total)


@bp.get("/licensing/product-categories/<category_id>")
def get_category(category_id):
    guard(mw.ALL_ROLES)
    row = S.categories.get(category_id)
    if row is None:
        raise ApiError("ERR_CATEGORY_NOT_FOUND")
    return response.ok(serializers.dump("ProductCategory", row))


@bp.patch("/licensing/product-categories/<category_id>")
def patch_category(category_id):
    ctx = guard([ROLE_MANAGER])
    row = S.categories.get(category_id)
    if row is None:
        raise ApiError("ERR_CATEGORY_NOT_FOUND")
    body = ctx.body

    changes = {}
    if V.present(body, "tier_schedule"):
        changes["tier_schedule"] = _validate_tier_schedule(body["tier_schedule"])
    if V.present(body, "base_royalty_rate_bps"):
        value = V.req_bps(body, "base_royalty_rate_bps")
        _range(value, "base_royalty_rate_bps", 100, 3000)
        changes["base_royalty_rate_bps"] = value
    if V.present(body, "closeout_rate_bps"):
        value = V.req_bps(body, "closeout_rate_bps")
        _range(value, "closeout_rate_bps", 50, 3000)
        changes["closeout_rate_bps"] = value
    if V.present(body, "closeout_cap_pct_bps"):
        value = V.req_bps(body, "closeout_cap_pct_bps")
        _range(value, "closeout_cap_pct_bps", 0, 5000)
        changes["closeout_cap_pct_bps"] = value
    if V.present(body, "closeout_hard_limit_bps"):
        changes["closeout_hard_limit_bps"] = V.req_bps(body, "closeout_hard_limit_bps")
    if V.present(body, "deduction_cap_pct_bps"):
        value = V.req_bps(body, "deduction_cap_pct_bps")
        _range(value, "deduction_cap_pct_bps", 0, 5000)
        changes["deduction_cap_pct_bps"] = value
    if V.present(body, "deduction_hard_limit_bps"):
        changes["deduction_hard_limit_bps"] = V.req_bps(body, "deduction_hard_limit_bps")
    if V.present(body, "minimum_guarantee_floor_cents"):
        changes["minimum_guarantee_floor_cents"] = V.req_cents(
            body, "minimum_guarantee_floor_cents")
    if V.present(body, "advance_floor_bps_of_mg"):
        changes["advance_floor_bps_of_mg"] = V.req_bps(body, "advance_floor_bps_of_mg")
    if V.present(body, "exclusivity_allowed"):
        changes["exclusivity_allowed"] = V.req_bool(body, "exclusivity_allowed")
    if V.present(body, "central_licensing_default"):
        changes["central_licensing_default"] = V.req_bool(body, "central_licensing_default")

    merged_cap = changes.get("closeout_cap_pct_bps", row["closeout_cap_pct_bps"])
    merged_hard = changes.get("closeout_hard_limit_bps", row["closeout_hard_limit_bps"])
    _range(merged_hard, "closeout_hard_limit_bps", merged_cap, 10000)
    merged_dcap = changes.get("deduction_cap_pct_bps", row["deduction_cap_pct_bps"])
    merged_dhard = changes.get("deduction_hard_limit_bps", row["deduction_hard_limit_bps"])
    _range(merged_dhard, "deduction_hard_limit_bps", merged_dcap, 10000)

    row.update(changes)
    touch(row)
    return response.ok(serializers.dump("ProductCategory", row))


# --------------------------------------------------------------------------- #
# clubs                                                                       #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/clubs")
def create_club():
    ctx = guard([ROLE_MANAGER])
    body = ctx.body
    code = V.req_string(body, "club_code", 3, 3)
    if not CLUB_CODE_RE.match(code):
        _bad("club_code must be exactly three uppercase letters.")
    market_name = V.req_string(body, "market_name", 1, 200)
    units = V.req_units(body, "revenue_share_units")
    _range(units, "revenue_share_units", 1, 100)
    status = V.opt_enum(body, "status", K.CLUB_STATUSES, "ACTIVE")

    for existing in S.clubs.values():
        if existing["club_code"] == code:
            _bad("club_code must be unique.")

    row = db.base_row()
    row.update({
        "club_code": code,
        "market_name": market_name,
        "revenue_share_units": units,
        "status": status,
        "lifetime_distributed_cents": 0,
    })
    S.clubs[row["id"]] = row
    return response.created(serializers.dump("Club", row))


@bp.get("/licensing/clubs")
def list_clubs():
    guard(mw.ALL_ROLES)
    limit, offset = pagination()
    status = mw.filter_enum("status", K.CLUB_STATUSES)
    rows = list(S.clubs.values())
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("Club", page), limit, offset, total)


@bp.get("/licensing/clubs/<club_id>")
def get_club(club_id):
    ctx = guard([mw.ROLE_MANAGER, mw.ROLE_COMPLIANCE, mw.ROLE_FINANCE, mw.ROLE_AUDITOR,
                 ROLE_CLUB])
    mw.scope_club(ctx, club_id)
    row = S.clubs.get(club_id)
    if row is None:
        raise ApiError("ERR_CLUB_NOT_FOUND")
    return response.ok(serializers.dump("Club", row))


@bp.patch("/licensing/clubs/<club_id>")
def patch_club(club_id):
    ctx = guard([ROLE_MANAGER])
    row = S.clubs.get(club_id)
    if row is None:
        raise ApiError("ERR_CLUB_NOT_FOUND")
    body = ctx.body
    changes = {}
    if V.present(body, "revenue_share_units"):
        units = V.req_units(body, "revenue_share_units")
        _range(units, "revenue_share_units", 1, 100)
        changes["revenue_share_units"] = units
    if V.present(body, "status"):
        changes["status"] = V.req_enum(body, "status", K.CLUB_STATUSES)
    if V.present(body, "market_name"):
        changes["market_name"] = V.req_string(body, "market_name", 1, 200)
    row.update(changes)
    touch(row)
    return response.ok(serializers.dump("Club", row))


# --------------------------------------------------------------------------- #
# players                                                                     #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/clubs/<club_id>/players")
def create_player(club_id):
    ctx = guard([ROLE_MANAGER])
    club = S.clubs.get(club_id)
    if club is None:
        raise ApiError("ERR_CLUB_NOT_FOUND")
    body = ctx.body
    full_name = V.req_string(body, "full_name", 1, 200)
    opt_in = V.opt_bool(body, "group_licensing_opt_in", True)
    status = V.opt_enum(body, "status", K.PLAYER_STATUSES, "ACTIVE")

    row = db.base_row()
    row.update({
        "full_name": full_name,
        "club_id": club_id,
        "group_licensing_opt_in": opt_in,
        "individual_grant_category_ids": [],
        "status": status,
    })
    S.players[row["id"]] = row
    return response.created(serializers.dump("Player", row))


@bp.get("/licensing/players")
def list_players():
    guard([mw.ROLE_MANAGER, mw.ROLE_COMPLIANCE, mw.ROLE_FINANCE, mw.ROLE_AUDITOR,
           ROLE_CLUB, ROLE_AGENT])
    limit, offset = pagination()
    club_id = mw.filter_str("club_id")
    opt_in = mw.filter_bool("group_licensing_opt_in")
    status = mw.filter_enum("status", K.PLAYER_STATUSES)
    rows = list(S.players.values())
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if opt_in is not None:
        rows = [r for r in rows if r["group_licensing_opt_in"] == opt_in]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("Player", page), limit, offset, total)


@bp.get("/licensing/players/<player_id>")
def get_player(player_id):
    ctx = guard([mw.ROLE_MANAGER, mw.ROLE_COMPLIANCE, mw.ROLE_FINANCE, mw.ROLE_AUDITOR,
                 ROLE_CLUB, ROLE_AGENT])
    mw.scope_player(ctx, player_id)
    row = S.players.get(player_id)
    if row is None:
        raise ApiError("ERR_PLAYER_NOT_FOUND")
    return response.ok(serializers.dump("Player", row))


@bp.post("/licensing/players/<player_id>/group-licensing")
def set_group_licensing(player_id):
    ctx = guard([ROLE_AGENT, ROLE_MANAGER])
    mw.scope_player(ctx, player_id)
    player = S.players.get(player_id)
    if player is None:
        raise ApiError("ERR_PLAYER_NOT_FOUND")
    opt_in = V.req_bool(ctx.body, "opt_in")

    player["group_licensing_opt_in"] = opt_in
    touch(player)

    if opt_in is False:
        for mark in list(S.marks.values()):
            if (mark["owner_type"] == "PLAYER_GROUP" and mark["player_id"] == player_id
                    and mark["status"] in ("ACTIVE", "RESTRICTED")):
                domain.withdraw_mark(mark, mark.get("status_reason"))
    else:
        for mark in list(S.marks.values()):
            if (mark["owner_type"] == "PLAYER_GROUP" and mark["player_id"] == player_id
                    and mark["status"] == "WITHDRAWN"):
                mark["status"] = "ACTIVE"
                mark["status_reason"] = None
                mark["withdrawn_at"] = None
                touch(mark)
    return response.ok(serializers.dump("Player", player))


@bp.post("/licensing/players/<player_id>/individual-grants")
def set_individual_grant(player_id):
    ctx = guard([ROLE_AGENT, ROLE_MANAGER])
    mw.scope_player(ctx, player_id)
    player = S.players.get(player_id)
    if player is None:
        raise ApiError("ERR_PLAYER_NOT_FOUND")
    body = ctx.body
    category_id = body.get("category_id")
    if category_id is not None and category_id not in S.categories:
        raise ApiError("ERR_CATEGORY_NOT_FOUND")
    category_id = V.req_string(body, "category_id")
    granted = V.req_bool(body, "granted")

    grants = list(player["individual_grant_category_ids"])
    if granted:
        if category_id not in grants:
            grants.append(category_id)
    else:
        grants = [g for g in grants if g != category_id]
    player["individual_grant_category_ids"] = grants
    touch(player)
    return response.ok(serializers.dump("Player", player))


# --------------------------------------------------------------------------- #
# mark rights                                                                 #
# --------------------------------------------------------------------------- #

@bp.post("/licensing/mark-rights")
def create_mark():
    ctx = guard([ROLE_MANAGER])
    body = ctx.body

    club_id = body.get("club_id")
    if club_id is not None and club_id not in S.clubs:
        raise ApiError("ERR_CLUB_NOT_FOUND")
    player_id = body.get("player_id")
    if player_id is not None and player_id not in S.players:
        raise ApiError("ERR_PLAYER_NOT_FOUND")

    code = V.req_string(body, "mark_code", 3, 40)
    if not MARK_CODE_RE.match(code):
        _bad("mark_code has an invalid format.")
    owner_type = V.req_enum(body, "owner_type", K.MARK_OWNER_TYPES)
    usage_class = V.opt_enum(body, "usage_class", K.MARK_USAGE_VALUES, "PRIMARY")
    royalty_share = V.opt_bps(body, "royalty_share_bps", 0)
    if club_id is not None and not isinstance(club_id, str):
        _bad("club_id must be a string.")
    if player_id is not None and not isinstance(player_id, str):
        _bad("player_id must be a string.")

    if owner_type == "CLUB":
        if club_id is None:
            _bad("club_id is required when owner_type is CLUB.")
    elif club_id is not None:
        _bad("club_id must be null unless owner_type is CLUB.")

    if owner_type in ("PLAYER_GROUP", "PLAYER_INDIVIDUAL"):
        if player_id is None:
            _bad("player_id is required for player-owned marks.")
    elif player_id is not None:
        _bad("player_id must be null unless owner_type is a player type.")

    for existing in S.marks.values():
        if existing["mark_code"] == code:
            _bad("mark_code must be unique.")

    row = db.base_row()
    row.update({
        "mark_code": code,
        "owner_type": owner_type,
        "club_id": club_id,
        "player_id": player_id,
        "usage_class": usage_class,
        "royalty_share_bps": royalty_share,
        "status": "ACTIVE",
        "status_reason": None,
        "withdrawn_at": None,
    })
    S.marks[row["id"]] = row
    return response.created(serializers.dump("MarkRight", row))


@bp.get("/licensing/mark-rights")
def list_marks():
    guard(mw.ALL_ROLES)
    limit, offset = pagination()
    club_id = mw.filter_str("club_id")
    player_id = mw.filter_str("player_id")
    owner_type = mw.filter_enum("owner_type", K.MARK_OWNER_TYPES)
    status = mw.filter_enum("status", K.MARK_STATUSES)
    usage_class = mw.filter_enum("usage_class", K.MARK_USAGE_VALUES)
    rows = list(S.marks.values())
    if club_id is not None:
        rows = [r for r in rows if r["club_id"] == club_id]
    if player_id is not None:
        rows = [r for r in rows if r["player_id"] == player_id]
    if owner_type is not None:
        rows = [r for r in rows if r["owner_type"] == owner_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if usage_class is not None:
        rows = [r for r in rows if r["usage_class"] == usage_class]
    page, total = paginate(rows, limit, offset)
    return response.ok_list(serializers.dump_all("MarkRight", page), limit, offset, total)


@bp.get("/licensing/mark-rights/<mark_id>")
def get_mark(mark_id):
    guard(mw.ALL_ROLES)
    row = S.marks.get(mark_id)
    if row is None:
        raise ApiError("ERR_MARK_NOT_FOUND")
    return response.ok(serializers.dump("MarkRight", row))


@bp.post("/licensing/mark-rights/<mark_id>/status")
def mark_status(mark_id):
    ctx = guard([ROLE_COMPLIANCE, ROLE_CLUB])
    mark = S.marks.get(mark_id)
    if mark is None:
        raise ApiError("ERR_MARK_NOT_FOUND")
    if ctx.role == ROLE_CLUB:
        if mark["owner_type"] != "CLUB" or mark["club_id"] != ctx.uid:
            raise ApiError("ERR_FORBIDDEN_SCOPE",
                           "A club representative may only operate its own club marks.")
    action = V.req_enum(ctx.body, "action", ("RESTRICT", "WITHDRAW", "REINSTATE"))
    reason = V.opt_string(ctx.body, "reason")

    status = mark["status"]
    if action == "RESTRICT":
        if status != "ACTIVE":
            raise ApiError("ERR_INVALID_STATE")
        domain.restrict_mark(mark, reason)
    elif action == "WITHDRAW":
        if status not in ("ACTIVE", "RESTRICTED"):
            raise ApiError("ERR_INVALID_STATE")
        domain.withdraw_mark(mark, reason)
    else:
        if status not in ("RESTRICTED", "WITHDRAWN"):
            raise ApiError("ERR_INVALID_STATE")
        mark["status"] = "ACTIVE"
        mark["status_reason"] = None
        if status == "WITHDRAWN":
            mark["withdrawn_at"] = None
        touch(mark)
    return response.ok(serializers.dump("MarkRight", mark))
