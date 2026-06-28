"""Subscription endpoints and lifecycle (PRD §3.3)."""

import secrets

from flask import request

import common
import db
import errors
import ownership
import serialize
from common import new_common, touch
from response import success, list_success
from routehelpers import auth_and_role, body
from timeutil import parse_iso


def _periods_overlap(start_a, end_a, start_b, end_b):
    """Closed [start, end] interval overlap (PRD §3.3): a_start <= b_end and b_start <= a_end."""
    return start_a <= end_b and start_b <= end_a


def register(app):
    @app.route("/subscriptions", methods=["POST"])
    def create_subscription():
        caller = auth_and_role(["Listener"])
        data = body()
        listener_id = common.require_str(data, "listener_id")
        show_id = common.require_str(data, "show_id")
        price_cents = common.require_int(data, "price_cents")
        if price_cents < 0:
            raise errors.err(errors.ERR_INVALID_REQUEST, "price_cents must be >= 0")
        period_start = common.require_str(data, "period_start")
        period_end = common.require_str(data, "period_end")
        try:
            parse_iso(period_start)
            parse_iso(period_end)
        except ValueError:
            raise errors.err(errors.ERR_INVALID_REQUEST, "period_start/period_end must be ISO 8601 timestamps")
        # Ownership: a Listener creates only their own subscription.
        if listener_id != caller.user_id:
            raise errors.err(errors.ERR_NOT_RESOURCE_OWNER, "Listener may only create their own subscription")
        ownership.get_listener(listener_id)
        ownership.get_show(show_id)
        rec = new_common()
        rec.update({
            "listener_id": listener_id,
            "show_id": show_id,
            "price_cents": price_cents,
            "status": "PENDING",
            "period_start": period_start,
            "period_end": period_end,
            "access_token": None,
        })
        db.db.subscriptions[rec["id"]] = rec
        return success(serialize.subscription(rec), status=201)

    @app.route("/subscriptions", methods=["GET"])
    def list_subscriptions():
        auth_and_role(["PlatformAdmin", "Listener", "Publisher"])
        limit, offset = common.parse_pagination(request.args)
        items = list(db.db.subscriptions.values())
        listener_id = request.args.get("listener_id")
        if listener_id:
            items = [s for s in items if s["listener_id"] == listener_id]
        show_id = request.args.get("show_id")
        if show_id:
            items = [s for s in items if s["show_id"] == show_id]
        status = request.args.get("status")
        if status:
            items = [s for s in items if s["status"] == status]
        items = common.sort_by_created(items)
        total = len(items)
        page = common.paginate(items, limit, offset)
        return list_success([serialize.subscription(s) for s in page], limit, offset, total)

    @app.route("/subscriptions/<sid>", methods=["GET"])
    def get_subscription(sid):
        auth_and_role(["PlatformAdmin", "Listener"])
        s = ownership.get_subscription(sid)
        return success(serialize.subscription(s), status=200)

    @app.route("/subscriptions/<sid>/activate", methods=["POST"])
    def activate_subscription(sid):
        caller = auth_and_role(["Listener"])
        sub = ownership.get_subscription(sid)
        ownership.assert_listener_owns_subscription(caller, sub)
        # State: PENDING/PAST_DUE -> ACTIVE.
        if sub["status"] not in ("PENDING", "PAST_DUE"):
            raise errors.err(errors.ERR_INVALID_STATE, "Subscription cannot be activated from its current state")
        data = body()
        # Renewed period (optional); applied when supplied (PRD §3.3 reactivation).
        new_start = data.get("period_start")
        new_end = data.get("period_end")
        if new_start is not None or new_end is not None:
            if new_start is None or new_end is None:
                raise errors.err(errors.ERR_INVALID_REQUEST, "Both period_start and period_end required to renew")
            if not isinstance(new_start, str) or not isinstance(new_end, str):
                raise errors.err(errors.ERR_INVALID_REQUEST, "period_start/period_end must be strings")
            try:
                parse_iso(new_start)
                parse_iso(new_end)
            except ValueError:
                raise errors.err(errors.ERR_INVALID_REQUEST, "period_start/period_end must be ISO 8601 timestamps")
            eff_start, eff_end = new_start, new_end
        else:
            eff_start, eff_end = sub["period_start"], sub["period_end"]
        # Business: PRD §3.3 order — private feed first, then period overlap.
        if not _has_private_enabled_feed(sub["show_id"]):
            raise errors.err(errors.ERR_NO_PRIVATE_FEED, "Show has no PRIVATE ENABLED feed")
        if _overlaps_existing(sub, eff_start, eff_end):
            raise errors.err(errors.ERR_SUBSCRIPTION_PERIOD_OVERLAP,
                             "Subscription period overlaps an existing ACTIVE/PAST_DUE subscription")
        sub["period_start"] = eff_start
        sub["period_end"] = eff_end
        sub["status"] = "ACTIVE"
        # Mint an access token on activation (PRD §3.3). A reactivated PAST_DUE
        # subscription that still holds a token keeps a valid one either way.
        if sub.get("access_token") is None:
            sub["access_token"] = "tok_" + secrets.token_hex(16)
        touch(sub)
        return success(serialize.subscription(sub), status=200)

    @app.route("/subscriptions/<sid>/mark-past-due", methods=["POST"])
    def mark_past_due(sid):
        auth_and_role(["PlatformAdmin"])
        sub = ownership.get_subscription(sid)
        if sub["status"] != "ACTIVE":
            raise errors.err(errors.ERR_INVALID_STATE, "Only an ACTIVE subscription may be marked past due")
        sub["status"] = "PAST_DUE"
        touch(sub)
        return success(serialize.subscription(sub), status=200)

    @app.route("/subscriptions/<sid>/cancel", methods=["POST"])
    def cancel_subscription(sid):
        caller = auth_and_role(["Listener"])
        sub = ownership.get_subscription(sid)
        ownership.assert_listener_owns_subscription(caller, sub)
        if sub["status"] not in ("ACTIVE", "PAST_DUE"):
            raise errors.err(errors.ERR_INVALID_STATE, "Subscription cannot be cancelled from its current state")
        sub["status"] = "CANCELLED"
        sub["access_token"] = None
        touch(sub)
        return success(serialize.subscription(sub), status=200)


def _has_private_enabled_feed(show_id):
    for f in db.db.feeds.values():
        if f["show_id"] == show_id and f["visibility"] == "PRIVATE" and f["status"] == "ENABLED":
            return True
    return False


def _overlaps_existing(sub, eff_start, eff_end):
    start = parse_iso(eff_start)
    end = parse_iso(eff_end)
    for other in db.db.subscriptions.values():
        if other["id"] == sub["id"]:
            continue
        if other["listener_id"] != sub["listener_id"] or other["show_id"] != sub["show_id"]:
            continue
        if other["status"] not in ("ACTIVE", "PAST_DUE"):
            continue
        if _periods_overlap(start, end, parse_iso(other["period_start"]), parse_iso(other["period_end"])):
            return True
    return False
