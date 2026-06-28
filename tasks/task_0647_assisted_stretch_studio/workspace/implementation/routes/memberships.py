"""Membership routes: purchase, freeze, unfreeze, cancel, renew (PRD §3.7).

OCC on version via expected_membership_version (PRD §2.7).
Freeze cascades into the calendar; cancel cascades to HELD bookings.
"""
from datetime import timedelta

from flask import Blueprint, request

from db import store
from errors import (
    err, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_STATE,
    ERR_STALE_MEMBERSHIP_VERSION, ERR_MEMBERSHIP_NOT_ALLOWED, ERR_VALIDATION,
)
from middleware import authenticate, require_role, forbid
from response import success, success_list
from util import (
    get_json_body, require_str, require_int, opt_int, require_enum,
    parse_pagination, paginate, parse_iso, now_clock,
)
from services.common import make_full, bump
from services.calc import membership_freeze_proration
from services.wallet import membership_wallet_fields
from services.booking import cascade_cancel_release
from services import serialize

bp = Blueprint("memberships", __name__)

MEMBER_ROLES = ["StudioManager", "FrontDesk", "Member"]
TIERS = {"STARTER", "PLUS", "PRO"}


def _ownership_for_member(p, member_id):
    if p.is_member and p.user_id != member_id:
        forbid()


@bp.route("/memberships", methods=["POST"])
def create_membership():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    body = get_json_body()
    member_id = require_str(body, "member_id")
    location_id = require_str(body, "location_id")
    tier = require_enum(body, "tier", TIERS)
    monthly_fee = require_int(body, "monthly_fee_cents", minimum=0)
    included = require_int(body, "included_credits", minimum=0)
    rollover_cap = opt_int(body, "rollover_cap", 0, minimum=0)

    _ownership_for_member(p, member_id)

    member = store.members.get(member_id)
    if member is None:
        raise err(ERR_NOT_FOUND, "Member not found.")
    if location_id not in store.locations:
        raise err(ERR_NOT_FOUND, "Location not found.")

    # priority 14: intro gating + one ACTIVE/FROZEN membership per (member, location).
    if not member["intro_completed"]:
        raise err(ERR_MEMBERSHIP_NOT_ALLOWED, "Member has not completed intro.")
    for m in store.memberships.values():
        if (m["member_id"] == member_id and m["location_id"] == location_id
                and m["status"] in ("ACTIVE", "FROZEN")):
            raise err(ERR_MEMBERSHIP_NOT_ALLOWED,
                      "Member already has an active/frozen membership at this location.")

    rec = make_full({
        "member_id": member_id,
        "location_id": location_id,
        "tier": tier,
        "monthly_fee_cents": monthly_fee,
        "included_credits": included,
        "rollover_cap": rollover_cap,
        "granted_credits": included,
        "cycle_anchor_utc": store.clock["current_utc"],
        "status": "ACTIVE",
        "freeze_credit_cents": 0,
    })
    store.memberships[rec["id"]] = rec
    return success(serialize.membership_view(rec), 201)


@bp.route("/memberships", methods=["GET"])
def list_memberships():
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    limit, offset = parse_pagination()
    member_id = _qs("member_id")
    location_id = _qs("location_id")
    status = _qs("status")
    items = [r for r in store.memberships.values()
             if (member_id is None or r["member_id"] == member_id)
             and (location_id is None or r["location_id"] == location_id)
             and (status is None or r["status"] == status)]
    if p.is_member:
        items = [r for r in items if r["member_id"] == p.user_id]
    window, total = paginate(items, limit, offset)
    return success_list([serialize.membership_view(r) for r in window], limit, offset, total)


@bp.route("/memberships/<mid>", methods=["GET"])
def get_membership(mid):
    p = authenticate()
    require_role(p, MEMBER_ROLES)
    rec = store.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Membership not found.")
    _ownership_for_member(p, rec["member_id"])
    return success(serialize.membership_view(rec), 200)


def _check_occ(rec, body):
    expected = body.get("expected_membership_version")
    if expected is None:
        raise err(ERR_VALIDATION, "expected_membership_version is required.")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise err(ERR_VALIDATION, "expected_membership_version must be an integer.")
    if expected != rec["version"]:
        raise err(ERR_STALE_MEMBERSHIP_VERSION,
                  "expected_membership_version does not match current version.")


@bp.route("/memberships/<mid>/freeze", methods=["POST"])
def freeze_membership(mid):
    p = authenticate()
    require_role(p, ["StudioManager", "Member"])
    rec = store.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Membership not found.")
    _ownership_for_member(p, rec["member_id"])
    body = get_json_body()
    freeze_start = require_str(body, "freeze_start_utc")
    freeze_end = require_str(body, "freeze_end_utc")
    start_dt = parse_iso(freeze_start)
    end_dt = parse_iso(freeze_end)

    # state precedes OCC? Per scaffold validations priority: state (5) before OCC (6).
    if rec["status"] != "ACTIVE":
        raise err(ERR_INVALID_STATE, "Membership is not ACTIVE.")
    _check_occ(rec, body)
    # freeze_end must be later than the current clock.
    if not (end_dt > now_clock()):
        raise err(ERR_VALIDATION, "freeze_end_utc must be later than the current clock.")

    # Apply state + proration + version bump.
    rec["status"] = "FROZEN"
    credit = membership_freeze_proration(rec["monthly_fee_cents"], start_dt, end_dt)
    rec["freeze_credit_cents"] = rec.get("freeze_credit_cents", 0) + credit

    # Cascade: covered CONFIRMED/REQUESTED bookings funded by this membership
    # whose session_start_utc in [freeze_start, freeze_end) -> CANCELLED + RELEASED.
    for b in list(store.bookings.values()):
        if b["funding_source"] != "MEMBERSHIP" or b["funding_id"] != mid:
            continue
        if b["schedule_status"] not in ("CONFIRMED", "REQUESTED"):
            continue
        b_start = parse_iso(b["session_start_utc"])
        if start_dt <= b_start < end_dt:
            cascade_cancel_release(b)

    bump(rec)
    return success(serialize.membership_view(rec), 200)


@bp.route("/memberships/<mid>/unfreeze", methods=["POST"])
def unfreeze_membership(mid):
    p = authenticate()
    require_role(p, ["StudioManager", "Member"])
    rec = store.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Membership not found.")
    _ownership_for_member(p, rec["member_id"])
    body = get_json_body()
    if rec["status"] != "FROZEN":
        raise err(ERR_INVALID_STATE, "Membership is not FROZEN.")
    _check_occ(rec, body)
    rec["status"] = "ACTIVE"
    bump(rec)
    return success(serialize.membership_view(rec), 200)


@bp.route("/memberships/<mid>/cancel", methods=["POST"])
def cancel_membership(mid):
    p = authenticate()
    require_role(p, ["StudioManager", "Member"])
    rec = store.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Membership not found.")
    _ownership_for_member(p, rec["member_id"])
    body = get_json_body()
    if rec["status"] not in ("ACTIVE", "FROZEN"):
        raise err(ERR_INVALID_STATE, "Membership cannot be cancelled from its current state.")
    _check_occ(rec, body)
    rec["status"] = "CANCELLED"
    # Cascade: all HELD bookings funded by this membership -> CANCELLED + RELEASED.
    for b in list(store.bookings.values()):
        if b["funding_source"] != "MEMBERSHIP" or b["funding_id"] != mid:
            continue
        if b["credit_status"] == "HELD":
            cascade_cancel_release(b)
    bump(rec)
    return success(serialize.membership_view(rec), 200)


@bp.route("/memberships/<mid>/renew", methods=["POST"])
def renew_membership(mid):
    p = authenticate()
    require_role(p, ["StudioManager"])
    rec = store.memberships.get(mid)
    if rec is None:
        raise err(ERR_NOT_FOUND, "Membership not found.")
    # carried = min(available_credits, rollover_cap), evaluated on the PRE-renewal
    # wallet (PRD §3.7). Then consumed resets to 0 (held holds persist).
    available = membership_wallet_fields(rec)["available_credits"]
    carried = min(available, rec["rollover_cap"])
    rec["granted_credits"] = rec["included_credits"] + carried
    # consumed_credits reset to 0: capture the current raw consumed sum as the
    # baseline so future wallet reads exclude prior-cycle consumption. Booking
    # records are never mutated, preserving funding_id filters and reschedule links.
    rec["consumed_baseline"] = _raw_membership_consumed(rec["id"])
    rec["cycle_anchor_utc"] = _advance_30_days(rec["cycle_anchor_utc"])
    rec["freeze_credit_cents"] = 0
    bump(rec)
    return success(serialize.membership_view(rec), 200)


def _raw_membership_consumed(membership_id):
    return sum(b["credit_cost"] for b in store.bookings.values()
               if b["funding_source"] == "MEMBERSHIP"
               and b["funding_id"] == membership_id
               and b["credit_status"] in ("CONSUMED", "FORFEITED"))


def _advance_30_days(iso_str):
    dt = parse_iso(iso_str)
    dt2 = dt + timedelta(days=30)
    s = dt2.isoformat()
    if s.endswith("+00:00"):
        s = s[:-6] + "Z"
    return s


def _qs(name):
    v = request.args.get(name)
    if v is None or v == "":
        return None
    return v
