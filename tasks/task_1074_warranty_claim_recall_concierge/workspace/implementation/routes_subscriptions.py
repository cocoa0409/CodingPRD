"""Subscriptions: create, change-plan (OCC), lifecycle transitions, reads."""
from flask import Blueprint, request

import store
import serializers as S
from store import touch
from common import (
    bad_request, get_body, new_common, ok, ok_list, optional_bool, paginate,
    require_auth, require_enum, require_household_member, resolve_or_404,
)
from errors import ApiError
from util import parse_dt

bp_subscriptions = Blueprint("subscriptions", __name__)

SUB_READ_ROLES = ["HouseholdOwner", "HouseholdMember", "ConciergeAgent", "PlatformAdmin"]
TIERS = {"BASIC", "PLUS", "PREMIUM"}


def _try_period(body):
    ps = body.get("period_start")
    pe = body.get("period_end")
    try:
        psd = parse_dt(ps)
        ped = parse_dt(pe)
    except (ValueError, TypeError):
        return None
    if psd >= ped:
        return None
    return psd, ped


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    # touching endpoints do NOT overlap (strict)
    return a_start < b_end and b_start < a_end


@bp_subscriptions.route("/households/<hid>/subscriptions", methods=["POST"])
def create_subscription(hid):
    role, uid = require_auth(["HouseholdOwner"])
    household = resolve_or_404(store.households, hid)
    require_household_member(uid, hid, require_owner=True)
    body = get_body()

    parsed = _try_period(body)
    if parsed is not None:
        psd, ped = parsed
        for s in store.subscriptions.values():
            if s["household_id"] != hid or s["status"] == "CANCELLED":
                continue
            if _overlaps_half_open(psd, ped, parse_dt(s["period_start"]), parse_dt(s["period_end"])):
                raise ApiError("ERR_SUBSCRIPTION_PERIOD_OVERLAP")

    tier = require_enum(body, "tier", TIERS)
    if not isinstance(body.get("period_start"), str) or not isinstance(body.get("period_end"), str):
        raise bad_request("period_start and period_end are required.")
    if parsed is None:
        raise bad_request("period_start must be a valid instant strictly before period_end.")
    auto_renew = optional_bool(body, "auto_renew", True)

    rec = new_common()
    rec.update({
        "household_id": hid,
        "tier": tier,
        "status": "ACTIVE",
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "claims_used": 0,
        "auto_renew": auto_renew,
    })
    store.subscriptions[rec["id"]] = rec
    return ok(S.subscription(rec), 201)


@bp_subscriptions.route("/subscriptions/<sid>/change-plan", methods=["POST"])
def change_plan(sid):
    role, uid = require_auth(["HouseholdOwner"])
    sub = resolve_or_404(store.subscriptions, sid)
    require_household_member(uid, sub["household_id"], require_owner=True)
    body = get_body()

    expected = body.get("expected_subscription_version")
    if isinstance(expected, bool) or not isinstance(expected, int):
        raise bad_request("expected_subscription_version is required and must be an integer.")
    if expected != sub["version"]:
        raise ApiError("ERR_STALE_VERSION")
    tier = require_enum(body, "tier", TIERS)

    sub["tier"] = tier
    touch(sub)
    return ok(S.subscription(sub))


@bp_subscriptions.route("/subscriptions/<sid>/mark-past-due", methods=["POST"])
def mark_past_due(sid):
    require_auth(["PlatformAdmin"])
    sub = resolve_or_404(store.subscriptions, sid)
    if sub["status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = "PAST_DUE"
    touch(sub)
    return ok(S.subscription(sub))


@bp_subscriptions.route("/subscriptions/<sid>/reinstate", methods=["POST"])
def reinstate(sid):
    role, uid = require_auth(["HouseholdOwner"])
    sub = resolve_or_404(store.subscriptions, sid)
    require_household_member(uid, sub["household_id"], require_owner=True)
    if sub["status"] != "PAST_DUE":
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = "ACTIVE"
    touch(sub)
    return ok(S.subscription(sub))


@bp_subscriptions.route("/subscriptions/<sid>/cancel", methods=["POST"])
def cancel(sid):
    role, uid = require_auth(["HouseholdOwner"])
    sub = resolve_or_404(store.subscriptions, sid)
    require_household_member(uid, sub["household_id"], require_owner=True)
    if sub["status"] not in ("ACTIVE", "PAST_DUE"):
        raise ApiError("ERR_INVALID_STATE")
    sub["status"] = "CANCELLED"
    touch(sub)
    return ok(S.subscription(sub))


@bp_subscriptions.route("/subscriptions/<sid>", methods=["GET"])
def get_subscription(sid):
    require_auth(SUB_READ_ROLES)
    rec = resolve_or_404(store.subscriptions, sid)
    return ok(S.subscription(rec))


@bp_subscriptions.route("/subscriptions", methods=["GET"])
def list_subscriptions():
    require_auth(SUB_READ_ROLES)
    hid = request.args.get("household_id")
    records = list(store.subscriptions.values())
    if hid is not None:
        records = [s for s in records if s["household_id"] == hid]
    items, pagination = paginate(records, S.subscription)
    return ok_list(items, pagination)
