"""Subscription tiers, viewers, subscriptions, and perk grants (§3.4)."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, add_months, auth, body, err_invalid_request,
                  err_invalid_state, err_not_found, err_ownership, ok_obj,
                  paginate, pagination, req_enum, req_int, req_str,
                  require_role)

bp = Blueprint("community", __name__)

TIER_CODES = ("TIER_1", "TIER_2", "TIER_3")
ALL_ROLES = ("PlatformAdmin", "Creator", "Moderator", "Sponsor", "TrustAgent", "AppealsOfficer")
VIEWER_READ_ROLES = ("PlatformAdmin", "Creator", "Moderator", "AppealsOfficer")
SUB_READ_ROLES = ("PlatformAdmin", "Creator")
PERK_SLA_DAYS = 14


# ---------------------------------------------------------------------------
# Tiers
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/tiers")
def create_tier(channel_id):
    uid, role = auth()
    b = body()
    tier_code = req_enum(b, "tier_code", TIER_CODES)
    monthly_price_cents = req_int(b, "monthly_price_cents", lo=0)
    revenue_share_bps = req_int(b, "revenue_share_bps", lo=0, hi=10000)
    perk_inventory_total = req_int(b, "perk_inventory_total", lo=0)
    require_role(role, ("Creator",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    if uid != ch["id"]:
        raise err_ownership()
    # At most one ACTIVE tier per (channel, tier_code).
    if any(t["channel_id"] == channel_id and t["tier_code"] == tier_code
           and t["tier_status"] == "ACTIVE" for t in db.store.tiers.values()):
        raise ApiError("ERR_TIER_CODE_IN_USE", 409,
                       "Another ACTIVE tier with the same tier_code exists on this channel")
    t = db.new_entity(
        channel_id=channel_id,
        tier_code=tier_code,
        monthly_price_cents=monthly_price_cents,
        revenue_share_bps=revenue_share_bps,
        perk_inventory_total=perk_inventory_total,
        tier_status="ACTIVE",
    )
    db.store.tiers[t["id"]] = t
    return ok_obj(domain.tier_json(t), status=201)


@bp.get("/api/tiers/<tier_id>")
def get_tier(tier_id):
    uid, role = auth()
    require_role(role, ALL_ROLES)
    t = db.store.tiers.get(tier_id)
    if t is None:
        raise err_not_found("Tier not found")
    return ok_obj(domain.tier_json(t))


@bp.get("/api/channels/<channel_id>/tiers")
def list_tiers(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, ALL_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    tiers = [t for t in db.store.tiers.values() if t["channel_id"] == channel_id]
    status = request.args.get("tier_status")
    if status is not None:
        tiers = [t for t in tiers if t["tier_status"] == status]
    return paginate(tiers, limit, offset, domain.tier_json)


@bp.post("/api/tiers/<tier_id>/transition")
def transition_tier(tier_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("RETIRE", "REACTIVATE"))
    require_role(role, ("Creator",))
    t = db.store.tiers.get(tier_id)
    if t is None:
        raise err_not_found("Tier not found")
    if uid != t["channel_id"]:
        raise err_ownership()
    if action == "RETIRE":
        if t["tier_status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE tier can be retired")
        t["tier_status"] = "RETIRED"
    else:  # REACTIVATE
        if t["tier_status"] != "RETIRED":
            raise err_invalid_state("Only a RETIRED tier can be reactivated")
        if any(x["id"] != t["id"] and x["channel_id"] == t["channel_id"]
               and x["tier_code"] == t["tier_code"] and x["tier_status"] == "ACTIVE"
               for x in db.store.tiers.values()):
            raise ApiError("ERR_TIER_CODE_IN_USE", 409,
                           "Another ACTIVE tier with the same tier_code exists on this channel")
        t["tier_status"] = "ACTIVE"
    db.touch(t)
    return ok_obj(domain.tier_json(t))


# ---------------------------------------------------------------------------
# Viewers
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/viewers")
def create_viewer(channel_id):
    uid, role = auth()
    b = body()
    handle = req_str(b, "handle")
    require_role(role, ("PlatformAdmin",))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    v = db.new_entity(
        channel_id=channel_id,
        handle=handle,
        lifetime_spend_cents=0,
    )
    db.store.viewers[v["id"]] = v
    return ok_obj(domain.viewer_json(v), status=201)


@bp.get("/api/viewers/<viewer_id>")
def get_viewer(viewer_id):
    uid, role = auth()
    require_role(role, VIEWER_READ_ROLES)
    v = db.store.viewers.get(viewer_id)
    if v is None:
        raise err_not_found("Viewer not found")
    return ok_obj(domain.viewer_json(v))


@bp.get("/api/channels/<channel_id>/viewers")
def list_viewers(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, VIEWER_READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    viewers = [v for v in db.store.viewers.values() if v["channel_id"] == channel_id]
    standing = request.args.get("standing")
    if standing is not None:
        viewers = [v for v in viewers if domain.viewer_standing(v) == standing]
    return paginate(viewers, limit, offset, domain.viewer_json)


# ---------------------------------------------------------------------------
# Subscriptions
# ---------------------------------------------------------------------------
def start_subscription(ch, viewer, tier):
    """Shared by the create endpoint and (indirectly) nothing else: birth is
    ACTIVE with cycle-1 charges, a MERCH grant, and viewer spend accrual."""
    ts = db.now()
    sub = db.new_entity(
        channel_id=ch["id"],
        viewer_id=viewer["id"],
        tier_id=tier["id"],
        sub_status="ACTIVE",
        started_at=ts,
        current_period_end=add_months(ts, 1),
        cycles_paid=1,
    )
    db.store.subscriptions[sub["id"]] = sub
    grant_cycle(ch, viewer, tier, sub)
    return sub


def grant_cycle(ch, viewer, tier, sub):
    """Record one paid cycle: PENDING SUBSCRIPTION revenue event + PENDING
    MERCH perk grant due in 14 days + viewer spend accrual."""
    domain.create_revenue_event(
        ch["id"], "SUBSCRIPTION", tier["monthly_price_cents"],
        10000 - tier["revenue_share_bps"], db.now())
    g = db.new_entity(
        subscription_id=sub["id"],
        perk_kind="MERCH",
        perk_status="PENDING",
        due_at=db.now() + timedelta(days=PERK_SLA_DAYS),
        failure_count=0,
        fulfilled_at=None,
    )
    db.store.perk_grants[g["id"]] = g
    viewer["lifetime_spend_cents"] += tier["monthly_price_cents"]
    db.touch(viewer)


@bp.post("/api/channels/<channel_id>/subscriptions")
def create_subscription(channel_id):
    uid, role = auth()
    b = body()
    viewer_id = req_str(b, "viewer_id")
    tier_id = req_str(b, "tier_id")
    require_role(role, ("PlatformAdmin",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    viewer = db.store.viewers.get(viewer_id)
    if viewer is None or viewer["channel_id"] != channel_id:
        raise err_not_found("Viewer not found in this channel")
    tier = db.store.tiers.get(tier_id)
    if tier is None or tier["channel_id"] != channel_id:
        raise err_not_found("Tier not found in this channel")
    # State (priority 6): a RETIRED tier admits no new subscriptions.
    if tier["tier_status"] != "ACTIVE":
        raise err_invalid_state("New subscriptions referencing a RETIRED tier are rejected")
    # Cross-reference rule (priority 23): a BANNED viewer cannot subscribe.
    if domain.viewer_standing(viewer) == "BANNED":
        raise ApiError("ERR_VIEWER_BANNED", 409,
                       "Subscription create for a BANNED viewer is rejected")
    sub = start_subscription(ch, viewer, tier)
    return ok_obj(domain.subscription_json(sub), status=201)


@bp.get("/api/subscriptions/<subscription_id>")
def get_subscription(subscription_id):
    uid, role = auth()
    require_role(role, SUB_READ_ROLES)
    s = db.store.subscriptions.get(subscription_id)
    if s is None:
        raise err_not_found("Subscription not found")
    return ok_obj(domain.subscription_json(s))


@bp.get("/api/subscriptions")
def list_subscriptions():
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, SUB_READ_ROLES)
    subs = list(db.store.subscriptions.values())
    for name in ("channel_id", "viewer_id", "tier_id", "sub_status"):
        v = request.args.get(name)
        if v is not None:
            subs = [s for s in subs if s[name] == v]
    return paginate(subs, limit, offset, domain.subscription_json)


@bp.post("/api/subscriptions/<subscription_id>/transition")
def transition_subscription(subscription_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("MARK_PAST_DUE", "RECOVER", "CANCEL"))
    if action in ("MARK_PAST_DUE", "RECOVER"):
        require_role(role, ("PlatformAdmin",))
    else:
        require_role(role, ("Creator",))
    s = db.store.subscriptions.get(subscription_id)
    if s is None:
        raise err_not_found("Subscription not found")
    if role == "Creator" and uid != s["channel_id"]:
        raise err_ownership()

    if action == "MARK_PAST_DUE":
        if s["sub_status"] != "ACTIVE":
            raise err_invalid_state("Only an ACTIVE subscription can become PAST_DUE")
        s["sub_status"] = "PAST_DUE"
    elif action == "RECOVER":
        if s["sub_status"] != "PAST_DUE":
            raise err_invalid_state("Only a PAST_DUE subscription can recover")
        viewer = db.store.viewers.get(s["viewer_id"])
        if viewer is not None and domain.viewer_standing(viewer) == "BANNED":
            raise ApiError("ERR_VIEWER_BANNED", 409,
                           "Subscription recover for a BANNED viewer is rejected")
        s["sub_status"] = "ACTIVE"
    else:  # CANCEL
        if s["sub_status"] not in ("ACTIVE", "PAST_DUE"):
            raise err_invalid_state("Only an ACTIVE or PAST_DUE subscription can be cancelled")
        domain.cancel_subscription(s)  # touches s and voids PENDING/FAILED perks
        return ok_obj(domain.subscription_json(s))

    db.touch(s)
    return ok_obj(domain.subscription_json(s))


# ---------------------------------------------------------------------------
# Perk grants
# ---------------------------------------------------------------------------
@bp.get("/api/subscriptions/<subscription_id>/perk-grants")
def list_perk_grants(subscription_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, SUB_READ_ROLES)
    if subscription_id not in db.store.subscriptions:
        raise err_not_found("Subscription not found")
    grants = [g for g in db.store.perk_grants.values()
              if g["subscription_id"] == subscription_id]
    status = request.args.get("perk_status")
    if status is not None:
        grants = [g for g in grants if g["perk_status"] == status]
    return paginate(grants, limit, offset, domain.perk_grant_json)


@bp.post("/api/perk-grants/<perk_grant_id>/transition")
def transition_perk_grant(perk_grant_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", ("FULFILL", "FAIL", "RETRY", "VOID"))
    require_role(role, ("Creator",))
    g = db.store.perk_grants.get(perk_grant_id)
    if g is None:
        raise err_not_found("Perk grant not found")
    sub = db.store.subscriptions.get(g["subscription_id"])
    if sub is None:
        raise err_not_found("Subscription not found")
    if uid != sub["channel_id"]:
        raise err_ownership()
    tier = db.store.tiers.get(sub["tier_id"])

    if action == "FULFILL":
        if g["perk_status"] != "PENDING":
            raise err_invalid_state("Only a PENDING perk grant can be fulfilled")
        if tier is not None and domain.tier_inventory_remaining(tier) <= 0:
            raise ApiError("ERR_PERK_INVENTORY_EXHAUSTED", 409,
                           "Tier perk_inventory_remaining is 0")
        g["perk_status"] = "FULFILLED"  # inventory derives from FULFILLED count
        g["fulfilled_at"] = db.now()
    elif action == "FAIL":
        if g["perk_status"] != "PENDING":
            raise err_invalid_state("Only a PENDING perk grant can fail")
        g["perk_status"] = "FAILED"
        g["failure_count"] += 1
    elif action == "RETRY":
        if g["perk_status"] != "FAILED":
            raise err_invalid_state("Only a FAILED perk grant can be retried")
        if db.now() > g["due_at"]:
            raise err_invalid_state("Past-SLA grants are no longer retryable")
        g["perk_status"] = "PENDING"
    else:  # VOID
        if g["perk_status"] != "FULFILLED":
            raise err_invalid_state("Only a FULFILLED perk grant can be voided")
        g["perk_status"] = "VOIDED"  # inventory derives: FULFILLED count drops

    db.touch(g)
    return ok_obj(domain.perk_grant_json(g))
