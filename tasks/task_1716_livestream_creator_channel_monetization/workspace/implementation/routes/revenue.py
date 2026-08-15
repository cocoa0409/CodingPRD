"""Revenue event ingestion, reads, and chargeback reversal (§3.2)."""

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_not_found,
                  ok_obj, opt_str, paginate, pagination, req_dt, req_enum,
                  req_int, require_role)

bp = Blueprint("revenue", __name__)

KINDS = ("SUBSCRIPTION", "TIP", "AD_SHARE", "SPONSORSHIP", "CHARGEBACK")
READ_ROLES = ("PlatformAdmin", "Creator")


@bp.post("/api/channels/<channel_id>/revenue-events")
def ingest_revenue_event(channel_id):
    uid, role = auth()
    b = body()
    kind = req_enum(b, "kind", KINDS)
    gross_cents = req_int(b, "gross_cents")
    platform_fee_bps = req_int(b, "platform_fee_bps", lo=0, hi=10000)
    occurred_at = req_dt(b, "occurred_at")
    reverses_event_id = b.get("reverses_event_id")
    if reverses_event_id is not None and not isinstance(reverses_event_id, str):
        raise err_invalid_request("Field 'reverses_event_id' must be a string")
    # Only CHARGEBACK may carry a negative gross; only CHARGEBACK carries the
    # self-referential reverses_event_id (required for that kind, absent else).
    if kind == "CHARGEBACK":
        if not reverses_event_id:
            raise err_invalid_request("CHARGEBACK events require reverses_event_id")
    else:
        if gross_cents < 0:
            raise err_invalid_request("Only CHARGEBACK events may carry a negative gross_cents")
        if reverses_event_id is not None:
            raise err_invalid_request("reverses_event_id is set on CHARGEBACK events only")
    require_role(role, ("PlatformAdmin",))
    ch = domain.get_channel(channel_id)
    if ch is None:
        raise err_not_found("Channel not found")
    if reverses_event_id is not None:
        target = db.store.revenue_events.get(reverses_event_id)
        if target is None or target["channel_id"] != channel_id:
            raise err_not_found("reverses_event_id does not reference an event of this channel")
    e = domain.create_revenue_event(channel_id, kind, gross_cents, platform_fee_bps,
                                    occurred_at, reverses_event_id)
    return ok_obj(domain.revenue_event_json(e), status=201)


@bp.get("/api/revenue-events/<revenue_event_id>")
def get_revenue_event(revenue_event_id):
    uid, role = auth()
    require_role(role, READ_ROLES)
    e = db.store.revenue_events.get(revenue_event_id)
    if e is None:
        raise err_not_found("Revenue event not found")
    return ok_obj(domain.revenue_event_json(e))


@bp.get("/api/revenue-events")
def list_revenue_events():
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, READ_ROLES)
    events = list(db.store.revenue_events.values())
    for name, field in (("channel_id", "channel_id"), ("kind", "kind"),
                        ("recognition_status", "recognition_status"),
                        ("settlement_month", "settlement_month"),
                        ("reverses_event_id", "reverses_event_id")):
        v = request.args.get(name)
        if v is not None:
            events = [e for e in events if e[field] == v]
    return paginate(events, limit, offset, domain.revenue_event_json)


@bp.post("/api/revenue-events/<revenue_event_id>/reverse")
def reverse_revenue_event(revenue_event_id):
    uid, role = auth()
    b = body()
    reason = b.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise err_invalid_request("Field 'reason' is required")
    require_role(role, ("PlatformAdmin",))
    e = db.store.revenue_events.get(revenue_event_id)
    if e is None:
        raise err_not_found("Revenue event not found")
    # Three chargeability guards, all ERR_CHARGEABILITY_VIOLATION (409).
    def violation(msg):
        return ApiError("ERR_CHARGEABILITY_VIOLATION", 409, msg)
    if e["kind"] == "CHARGEBACK":
        raise violation("A CHARGEBACK event cannot be reversed")
    if e["recognition_status"] != "CLEARED":
        raise violation("Only a CLEARED revenue event can be reversed")
    if any(x["kind"] == "CHARGEBACK" and x["reverses_event_id"] == e["id"]
           for x in db.store.revenue_events.values()):
        raise violation("A chargeback already exists for this event")
    e["recognition_status"] = "REVERSED"  # terminal; ledger rows are immutable otherwise
    cb = domain.create_revenue_event(
        e["channel_id"], "CHARGEBACK", -e["gross_cents"], e["platform_fee_bps"],
        db.now(), reverses_event_id=e["id"])
    return ok_obj(domain.revenue_event_json(cb), status=201)
