"""Administrative time control + periodic sweep (PRD §2.9, §3.13)."""
from datetime import timedelta

from flask import Blueprint

import db
import errors
import response
import validate
from clock import clock
from middleware import authenticate, require_roles
from services import domain
from timeutil import parse_iso

bp = Blueprint("admin", __name__)


@bp.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    data = validate.body()
    to_iso = validate.require(data, "to_iso8601", str)
    try:
        dt = parse_iso(to_iso)
    except ValueError:
        raise errors.invalid_request("to_iso8601 must be an ISO 8601 timestamp.")
    clock.set(dt)
    return response.object_response({}, 200)


@bp.route("/_billing/run_suspension_sweep", methods=["POST"])
def run_sweep():
    caller = authenticate()
    require_roles(caller, {"PlatformAdmin"})
    now = clock.now()

    # Pass 1: PAST_DUE memberships past grace -> SUSPENDED (with cascade).
    for member in list(db.members.values()):
        if member["membership_status"] != "PAST_DUE":
            continue
        membership = _membership_for_member(member["id"])
        if membership is None or membership.get("past_due_since") is None:
            continue
        practice = db.practices[member["practice_id"]]
        grace_end = membership["past_due_since"] + timedelta(days=practice["grace_period_days"])
        if now >= grace_end:
            member["membership_status"] = "SUSPENDED"
            db.touch(member)
            # Panel recount (member leaves active panel).
            pid = member.get("assigned_provider_id")
            if pid is not None:
                provider = db.providers.get(pid)
                if provider is not None:
                    domain.recompute_provider_panel(provider)
            # Cancel BOOKED/CHECKED_IN visits, adjust slots.
            domain.cancel_open_visits_for_member(member)

    # Pass 2: AUTHORIZED referrals past expires_at -> EXPIRED.
    for ref in db.referrals.values():
        if ref["referral_status"] == "AUTHORIZED" and ref.get("expires_at") is not None:
            if now >= ref["expires_at"]:
                ref["referral_status"] = "EXPIRED"
                db.touch(ref)

    # Pass 3: OPEN message threads past response_deadline -> ESCALATED.
    for thread in db.message_threads.values():
        if thread["thread_status"] == "OPEN" and thread.get("response_deadline") is not None:
            if now >= thread["response_deadline"]:
                thread["thread_status"] = "ESCALATED"
                db.touch(thread)

    return response.object_response({}, 200)


def _membership_for_member(member_id):
    for ms in db.memberships.values():
        if ms["member_id"] == member_id:
            return ms
    return None
