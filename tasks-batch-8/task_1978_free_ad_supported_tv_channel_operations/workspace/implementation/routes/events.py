"""Viewership events (append-only)."""

from db import store, new_id, next_seq, now_str
from db import fmt_dt
from errors import (
    raise_err,
    ERR_INVALID_REQUEST,
    ERR_REFERENCE_NOT_FOUND,
    ERR_FORBIDDEN_OWNERSHIP,
)
from middleware import (
    caller,
    require_roles,
    body,
    ROLE_PLATFORM_ADMIN,
    ROLE_CHANNEL_PROGRAMMER,
    ROLE_AD_OPS,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
    ROLE_DISTRIBUTOR_PARTNER,
)
from response import created, ok, paginate
from serializers import ser_event
from services.core import get_or_404
from util import req_str, req_enum, req_datetime, opt_int, is_int
from flask import Blueprint, request

bp = Blueprint("events", __name__)

EVENT_TYPES = ("SESSION_START", "SESSION_END", "CONTENT_WATCH", "AD_IMPRESSION", "AD_COMPLETE")

INTERNAL_READ_ROLES = [
    ROLE_PLATFORM_ADMIN,
    ROLE_CHANNEL_PROGRAMMER,
    ROLE_AD_OPS,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
]

# Companion references required per event type; all other companion fields
# must be null.
REQUIRED_BY_TYPE = {
    "SESSION_START": (),
    "SESSION_END": (),
    "CONTENT_WATCH": ("content_id", "watch_seconds"),
    "AD_IMPRESSION": ("break_id", "decision_id"),
    "AD_COMPLETE": ("break_id",),
}
COMPANION_FIELDS = ("break_id", "decision_id", "content_id", "watch_seconds", "quantity")


@bp.route("/v1/viewership-events", methods=["POST"])
def create_event():
    user_id, role = caller()
    b = body()
    channel_id = req_str(b, "channel_id")
    event_type = req_enum(b, "event_type", EVENT_TYPES)
    viewer_session_id = req_str(b, "viewer_session_id")
    occurred = req_datetime(b, "occurred_at_utc")
    platform_id = b.get("platform_id")
    if platform_id is not None and not isinstance(platform_id, str):
        raise_err(ERR_INVALID_REQUEST, "platform_id must be a string")
    if role == ROLE_PLATFORM_ADMIN and platform_id is None:
        raise_err(ERR_INVALID_REQUEST, "PlatformAdmin must pass platform_id explicitly")

    required = REQUIRED_BY_TYPE[event_type]
    for f in required:
        if b.get(f) is None:
            raise_err(ERR_INVALID_REQUEST, "Field '%s' is required for %s" % (f, event_type))
    for f in COMPANION_FIELDS:
        if f == "quantity":
            # quantity applies to AD_IMPRESSION only.
            if event_type != "AD_IMPRESSION" and b.get("quantity") is not None:
                raise_err(ERR_INVALID_REQUEST, "quantity applies to AD_IMPRESSION only")
            continue
        if f not in required and b.get(f) is not None:
            raise_err(ERR_INVALID_REQUEST, "Field '%s' must be null for %s" % (f, event_type))
    watch_seconds = None
    if event_type == "CONTENT_WATCH":
        watch_seconds = b.get("watch_seconds")
        if not is_int(watch_seconds) or watch_seconds < 0:
            raise_err(ERR_INVALID_REQUEST, "watch_seconds must be a non-negative integer")
    quantity = 1
    if event_type == "AD_IMPRESSION":
        q = opt_int(b, "quantity")
        if q is not None:
            if q <= 0:
                raise_err(ERR_INVALID_REQUEST, "quantity must be > 0")
            quantity = q

    require_roles(role, [ROLE_DISTRIBUTOR_PARTNER, ROLE_PLATFORM_ADMIN])

    # Tier 4: body FK targets exist.
    if channel_id not in store.channels:
        raise_err(ERR_REFERENCE_NOT_FOUND, "channel_id does not reference an existing channel")
    effective_platform = platform_id if platform_id is not None else user_id
    if effective_platform not in store.distributor_platforms:
        raise_err(ERR_REFERENCE_NOT_FOUND, "platform_id does not reference an existing platform")
    if b.get("break_id") is not None and b["break_id"] not in store.ad_breaks:
        raise_err(ERR_REFERENCE_NOT_FOUND, "break_id does not reference an existing ad break")
    if b.get("decision_id") is not None and b["decision_id"] not in store.fill_decisions:
        raise_err(ERR_REFERENCE_NOT_FOUND, "decision_id does not reference an existing fill decision")
    if b.get("content_id") is not None and b["content_id"] not in store.content_assets:
        raise_err(ERR_REFERENCE_NOT_FOUND, "content_id does not reference an existing content asset")

    # Tier 5: DistributorPartner ownership — platform_id must equal the
    # caller's platform id; when omitted it is stamped from the identity.
    if role == ROLE_DISTRIBUTOR_PARTNER and platform_id is not None and platform_id != user_id:
        raise_err(ERR_FORBIDDEN_OWNERSHIP, "Partners may only submit events for their own platform")

    rec = {
        "id": new_id(),
        "channel_id": channel_id,
        "platform_id": effective_platform,
        "event_type": event_type,
        "break_id": b.get("break_id"),
        "decision_id": b.get("decision_id"),
        "content_id": b.get("content_id"),
        "viewer_session_id": viewer_session_id,
        "occurred_at_utc": fmt_dt(occurred),
        "watch_seconds": watch_seconds,
        "quantity": quantity if event_type == "AD_IMPRESSION" else None,
        "created_at": now_str(),
        "_occurred": occurred,
        "_seq": next_seq(),
    }
    store.viewership_events[rec["id"]] = rec
    return created(ser_event(rec))


@bp.route("/v1/viewership-events", methods=["GET"])
def list_events():
    _, role = caller()
    require_roles(role, INTERNAL_READ_ROLES)
    recs = list(store.viewership_events.values())
    for param in ("channel_id", "platform_id", "break_id", "decision_id", "content_id", "event_type"):
        v = request.args.get(param)
        if v is not None:
            recs = [r for r in recs if r[param] == v]
    return paginate(recs, ser_event)


@bp.route("/v1/viewership-events/<event_id>", methods=["GET"])
def get_event(event_id):
    _, role = caller()
    require_roles(role, INTERNAL_READ_ROLES)
    rec = get_or_404(store.viewership_events, event_id, "ViewershipEvent")
    return ok(ser_event(rec))
