"""Entitlement endpoints: purchase, activate, freeze, thaw, cancel."""
import math

from flask import Blueprint

import constants as C
from db import store
from errors import err
from clock import parse_iso, format_iso_ms, add_days
from middleware import authenticate, require_roles
from models import make_entitlement, serialize, touch
from response import success
from helpers import (get_json_body, require_int, require_datetime, find_or_404)

bp = Blueprint("entitlements", __name__)

KINDS = {"MEMBERSHIP", "CLASS_PACK", "INTRO"}


def _owner_check(principal, ent):
    if principal.is_member and principal.user_id != ent["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only act on their own entitlements")


@bp.post("/entitlements")
def purchase_entitlement():
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    body = get_json_body()

    member_id = body.get("member_id")
    if not isinstance(member_id, str) or not member_id:
        raise err("ERR_INVALID_REQUEST", "member_id is required")
    member = find_or_404(store.members, member_id, "Member")

    # A Member may only purchase for themselves.
    if principal.is_member and principal.user_id != member_id:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only purchase their own entitlements")

    if body.get("kind") not in KINDS:
        raise err("ERR_INVALID_REQUEST", "kind invalid")
    kind = body["kind"]

    price_cents = require_int(body, "price_cents", minimum=0)
    credits_total = require_int(body, "credits_total", minimum=-1)
    cycle_start_dt = require_datetime(body, "cycle_start_utc")

    auto_renew = body.get("auto_renew", False)
    if auto_renew is None:
        auto_renew = False
    if not isinstance(auto_renew, bool):
        raise err("ERR_INVALID_REQUEST", "auto_renew must be a boolean")

    rollover_cap = body.get("rollover_cap")
    if rollover_cap is None:
        rollover_cap = 0
    else:
        if isinstance(rollover_cap, bool) or not isinstance(rollover_cap, int) or rollover_cap < 0:
            raise err("ERR_INVALID_REQUEST", "rollover_cap must be an integer >= 0")

    intro_offer_id = body.get("intro_offer_id")

    if kind == "INTRO":
        # intro_offer_id required and must reference an existing offer.
        if not isinstance(intro_offer_id, str) or not intro_offer_id:
            raise err("ERR_INVALID_REQUEST", "intro_offer_id is required for INTRO")
        offer = find_or_404(store.intro_offers, intro_offer_id, "IntroOffer")
        # Eligibility: new student, ACTIVE offer, at most one INTRO per member.
        if not member["is_new_student"]:
            raise err("ERR_INTRO_NOT_ELIGIBLE", "Member is not a new student")
        if offer["status"] != "ACTIVE":
            raise err("ERR_INTRO_NOT_ELIGIBLE", "IntroOffer is not ACTIVE")
        already = any(e for e in store.entitlements.values()
                      if e["member_id"] == member_id and e["kind"] == "INTRO")
        if already:
            raise err("ERR_INTRO_NOT_ELIGIBLE", "Member already holds an INTRO entitlement")
    else:
        # intro_offer_id must be null for non-INTRO.
        intro_offer_id = None

    cycle_end_dt = add_days(cycle_start_dt, C.CYCLE_LENGTH_DAYS)

    ent = make_entitlement(
        member_id, kind, intro_offer_id, price_cents, credits_total,
        body["cycle_start_utc"], format_iso_ms(cycle_end_dt), auto_renew, rollover_cap)
    store.entitlements[ent["id"]] = ent
    return success(serialize(ent), status=201)


@bp.get("/entitlements/<eid>")
def get_entitlement(eid):
    principal = authenticate()
    require_roles(principal, {"StudioManager", "Member"})
    ent = find_or_404(store.entitlements, eid, "Entitlement")
    if principal.is_member and principal.user_id != ent["member_id"]:
        raise err("ERR_NOT_RESOURCE_OWNER", "Members may only fetch their own entitlements")
    return success(serialize(ent))


@bp.post("/entitlements/<eid>/activate")
def activate_entitlement(eid):
    principal = authenticate()
    require_roles(principal, {"StudioManager"})
    ent = find_or_404(store.entitlements, eid, "Entitlement")
    if ent["lifecycle_status"] != "PENDING":
        raise err("ERR_INVALID_STATE", "Entitlement is not PENDING")
    if store.clock.now() < parse_iso(ent["cycle_start_utc"]):
        raise err("ERR_INVALID_STATE", "Logical clock has not reached cycle_start_utc")
    ent["lifecycle_status"] = "ACTIVE"
    touch(ent)
    return success(serialize(ent))


@bp.post("/entitlements/<eid>/freeze")
def freeze_entitlement(eid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    ent = find_or_404(store.entitlements, eid, "Entitlement")
    _owner_check(principal, ent)
    if ent["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Entitlement is not ACTIVE")
    if ent["freeze_status"] == "FROZEN":
        raise err("ERR_ENTITLEMENT_FROZEN", "Entitlement is already FROZEN")
    if ent["frozen_days_consumed"] >= C.FREEZE_MAX_DAYS_PER_CYCLE:
        raise err("ERR_FREEZE_LIMIT_REACHED", "Freeze ceiling reached for this cycle")
    ent["freeze_status"] = "FROZEN"
    ent["frozen_at_utc"] = store.now_iso()
    touch(ent)
    return success(serialize(ent))


@bp.post("/entitlements/<eid>/thaw")
def thaw_entitlement(eid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    ent = find_or_404(store.entitlements, eid, "Entitlement")
    _owner_check(principal, ent)
    if ent["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Entitlement is not ACTIVE")
    if ent["freeze_status"] != "FROZEN":
        raise err("ERR_ENTITLEMENT_FROZEN", "Entitlement is not FROZEN")

    frozen_at = parse_iso(ent["frozen_at_utc"])
    now = store.clock.now()
    elapsed_seconds = (now - frozen_at).total_seconds()
    # Frozen duration: ceil to whole days.
    frozen_days = math.ceil(elapsed_seconds / 86400.0)
    if frozen_days < 0:
        frozen_days = 0
    # Cap so frozen_days_consumed + frozen_days <= FREEZE_MAX_DAYS_PER_CYCLE.
    remaining_cap = C.FREEZE_MAX_DAYS_PER_CYCLE - ent["frozen_days_consumed"]
    if frozen_days > remaining_cap:
        frozen_days = remaining_cap
    if frozen_days < 0:
        frozen_days = 0

    new_cycle_end = add_days(parse_iso(ent["cycle_end_utc"]), frozen_days)
    ent["cycle_end_utc"] = format_iso_ms(new_cycle_end)
    ent["frozen_days_consumed"] += frozen_days
    ent["freeze_status"] = "UNFROZEN"
    ent["frozen_at_utc"] = None
    touch(ent)
    return success(serialize(ent))


@bp.post("/entitlements/<eid>/cancel")
def cancel_entitlement(eid):
    principal = authenticate()
    require_roles(principal, {"Member", "StudioManager"})
    ent = find_or_404(store.entitlements, eid, "Entitlement")
    _owner_check(principal, ent)
    if ent["lifecycle_status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", "Entitlement is not ACTIVE")
    ent["lifecycle_status"] = "CANCELLED"
    ent["auto_renew"] = False
    touch(ent)
    return success(serialize(ent))
