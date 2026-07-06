"""Client account routes (PRD §3.1, §3.7)."""
from flask import Blueprint, request

import db
import response
from errors import (
    err, ERR_INVALID_STATE, ERR_CLIENT_NOT_ACTIVE,
)
from middleware import (
    get_user_context, require_role, get_json_body, get_pagination,
    require_string,
)
from services import lookup, listing, calc
from services.budget import recompute_client_derived, recompute_client_budget
from services.serialize import client_out
from services.ledger import append_ledger

bp = Blueprint("clients", __name__)


def _serialize(c):
    # Refresh read-derived computed counters before returning.
    recompute_client_derived(c)
    return client_out(c)


@bp.post("/clients")
def create_client():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    body = get_json_body()
    name = require_string(body, "name")
    account_manager_id = require_string(body, "account_manager_id")
    with db.LOCK:
        c = {
            "id": db.new_id(),
            "name": name,
            "account_manager_id": account_manager_id,
            "status": "ONBOARDING",
            "retainer_fee_cents": 0,
            "boost_budget_limit_cents": 0,
            "boost_reserved_cents": 0,
            "boost_spent_cents": 0,
            "boost_available_cents": 0,
            "monthly_post_quota": 0,
            "posts_published_this_cycle": 0,
            "current_cycle_index": 0,
            "open_conversation_count": 0,
        }
        db.stamp_create(c, full=True)
        db.clients[c["id"]] = c
        return response.created(_serialize(c))


@bp.get("/clients")
def list_clients():
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    limit, offset = get_pagination()
    with db.LOCK:
        rows = listing.apply_filters(list(db.clients.values()), {
            "status": request.args.get("status"),
            "account_manager_id": request.args.get("account_manager_id"),
        })
        rows = listing.sort_by_created(rows)
        window, total = listing.paginate(rows, limit, offset)
        return response.list_ok([_serialize(c) for c in window], limit, offset, total)


@bp.get("/clients/<client_id>")
def get_client(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        return response.ok(_serialize(c))


@bp.post("/clients/<client_id>/activate")
def activate_client(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        # state machine: ONBOARDING -> ACTIVE
        if c["status"] != "ONBOARDING":
            raise err(ERR_INVALID_STATE, "Client must be ONBOARDING to activate")
        # preconditions: exactly one ACTIVE package + at least one LIVE channel
        active_packages = [
            p for p in db.retainer_packages.values()
            if p["client_id"] == client_id and p["status"] == "ACTIVE"
        ]
        live_channels = [
            ch for ch in db.channels.values()
            if ch["client_id"] == client_id and ch["status"] == "LIVE"
        ]
        if len(active_packages) != 1 or len(live_channels) < 1:
            raise err(ERR_INVALID_STATE,
                      "Client activation requires exactly one ACTIVE package and a LIVE channel")
        pkg = active_packages[0]
        c["status"] = "ACTIVE"
        c["retainer_fee_cents"] = pkg["monthly_retainer_fee_cents"]
        c["boost_budget_limit_cents"] = pkg["monthly_boost_budget_cents"]
        c["monthly_post_quota"] = pkg["monthly_post_quota"]
        recompute_client_budget(c)
        db.touch(c)
        append_ledger(
            client_id=client_id,
            entry_type="RETAINER_CHARGE",
            amount_cents=c["retainer_fee_cents"],
            boost_campaign_id=None,
            cycle_index=c["current_cycle_index"],
        )
        return response.ok(_serialize(c))


@bp.post("/clients/<client_id>/suspend")
def suspend_client(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        if c["status"] != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Client must be ACTIVE to suspend")
        c["status"] = "SUSPENDED"
        db.touch(c)
        return response.ok(_serialize(c))


@bp.post("/clients/<client_id>/reinstate")
def reinstate_client(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        if c["status"] != "SUSPENDED":
            raise err(ERR_INVALID_STATE, "Client must be SUSPENDED to reinstate")
        c["status"] = "ACTIVE"
        db.touch(c)
        return response.ok(_serialize(c))


@bp.post("/clients/<client_id>/churn")
def churn_client(client_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        if c["status"] not in ("ONBOARDING", "ACTIVE", "SUSPENDED"):
            raise err(ERR_INVALID_STATE, "Client cannot be churned from its current state")
        # precondition: no boost campaign in RESERVED or RUNNING
        active_boosts = [
            b for b in db.boost_campaigns.values()
            if b["client_id"] == client_id and b["status"] in ("RESERVED", "RUNNING")
        ]
        if active_boosts:
            raise err(ERR_INVALID_STATE,
                      "Client has active boost campaigns; cannot churn")
        c["status"] = "CHURNED"
        db.touch(c)
        # cascade: disconnect all non-DISCONNECTED channels
        client_channel_ids = set()
        for ch in db.channels.values():
            if ch["client_id"] == client_id:
                client_channel_ids.add(ch["id"])
                if ch["status"] != "DISCONNECTED":
                    _disconnect_channel_cascade(ch)
        # cascade: resolve OPEN/ASSIGNED/ESCALATED conversations on those channels
        for conv in db.conversations.values():
            if conv["channel_id"] in client_channel_ids and \
                    conv["status"] in ("OPEN", "ASSIGNED", "ESCALATED"):
                conv["status"] = "RESOLVED"
                db.touch(conv)
        return response.ok(_serialize(c))


def _disconnect_channel_cascade(ch):
    """Drive a channel to DISCONNECTED with its slot/content cascade.

    Mirrors the channel-disconnect side effects (PRD §3.2): release RESERVED
    slots; each released slot's SCHEDULED content reverts to APPROVED with its
    scheduled_slot_id cleared.
    """
    ch["status"] = "DISCONNECTED"
    db.touch(ch)
    for slot in db.schedule_slots.values():
        if slot["channel_id"] == ch["id"] and slot["status"] == "RESERVED":
            slot["status"] = "RELEASED"
            db.touch(slot)
            ci = db.content_items.get(slot["content_item_id"])
            if ci is not None and ci["status"] == "SCHEDULED":
                ci["status"] = "APPROVED"
                ci["scheduled_slot_id"] = None
                db.touch(ci)


@bp.post("/clients/<client_id>/cycles/close")
def close_cycle(client_id):
    _, role = get_user_context()
    require_role(role, {"PlatformAdmin", "AccountManager"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        c["current_cycle_index"] += 1
        db.touch(c)
        # posts_published_this_cycle recomputes to 0 for the new cycle.
        return response.ok(_serialize(c))


@bp.get("/clients/<client_id>/churn-quote")
def churn_quote(client_id):
    _, role = get_user_context()
    require_role(role, {"AccountManager", "PlatformAdmin", "FinanceController"})
    with db.LOCK:
        c = lookup.get_client(client_id)
        recompute_client_derived(c)
        quota = c["monthly_post_quota"] if c["monthly_post_quota"] >= 1 else 1
        forward, prorated = calc.retainer_churn_quote(
            c["retainer_fee_cents"], c["posts_published_this_cycle"], quota
        )
        return response.ok({
            "forward_full_cents": forward,
            "chronological_prorated_cents": prorated,
        })
