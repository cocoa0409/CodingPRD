from flask import request

from db import db
from errors import (
    ERR_INVALID_REQUEST,
    ERR_REFERRAL_NOT_FOUND,
    ERR_TRANSPORT_OVERLAP,
    raise_error,
)
from middleware import require_roles
from response import paginate, success
from services import make_transport, serialise_transport
from util import parse_ts
from validate import (
    TRANSPORT_PLAN_MODE_ENUM,
    parse_pagination,
    require_body,
    require_enum,
    require_int,
    require_str,
)


def _referral_or_404(rid: str):
    r = db.referrals.get(rid)
    if not r:
        raise_error(ERR_REFERRAL_NOT_FOUND, f"referral {rid} not found")
    return r


def _client_of_referral(ref: dict) -> str | None:
    intake = db.intakes.get(ref["intake_id"])
    return intake["client_id"] if intake else None


def register(app):
    @app.post("/referrals/<rid>/transport-plans")
    @require_roles("Caseworker", "PlatformAdmin")
    def create_plan(rid):
        r = _referral_or_404(rid)
        body = require_body(request.get_json(silent=True))
        start_s = require_str(body, "pickup_start_ts")
        end_s = require_str(body, "pickup_end_ts")
        mode = require_enum(body, "mode", TRANSPORT_PLAN_MODE_ENUM)
        cost = require_int(body, "cost_cents")
        if cost < 0:
            raise_error(ERR_INVALID_REQUEST, "cost_cents must be >= 0")

        start_dt = parse_ts(start_s)
        end_dt = parse_ts(end_s)
        if not (end_dt > start_dt):
            raise_error(ERR_INVALID_REQUEST, "pickup_end_ts must be strictly greater than pickup_start_ts")

        # Priority 27: 30-minute buffer against every SCHEDULED plan for the same client.
        this_client_id = _client_of_referral(r)
        BUFFER_SECS = 30 * 60
        for tp in db.transport_plans.values():
            if tp["status"] != "SCHEDULED":
                continue
            other_ref = db.referrals.get(tp["referral_id"])
            if not other_ref:
                continue
            if _client_of_referral(other_ref) != this_client_id:
                continue
            other_start = parse_ts(tp["pickup_start_ts"])
            other_end = parse_ts(tp["pickup_end_ts"])
            # PRD §3.6: "the smaller of the two temporal gaps between them — the gap
            # measured in seconds between the closing endpoint of one interval and the
            # opening endpoint of the other".  The two directional gaps are
            #   (start_new - end_other)  and  (start_other - end_new).
            # If the intervals overlap, at least one of these is <= 0 (overlap = gap of 0).
            # If they don't overlap, exactly one is positive (the actual gap) and the
            # other is a large negative number.  The PRD's "smaller of the two gaps"
            # phrasing refers to the true temporal separation, which is the larger of
            # these two signed differences (the positive one when they don't overlap,
            # or zero/negative when they overlap).
            gap_a = (start_dt - other_end).total_seconds()
            gap_b = (other_start - end_dt).total_seconds()
            # Effective separation: 0 if intervals overlap, else the positive gap.
            separation = max(gap_a, gap_b)
            if separation < 0:
                separation = 0
            if separation < BUFFER_SECS:
                raise_error(ERR_TRANSPORT_OVERLAP,
                            "transport plan conflicts with an existing SCHEDULED plan for this client")

        entity = make_transport(rid, start_s, end_s, mode, cost)
        return success(serialise_transport(entity), 201)

    @app.get("/referrals/<rid>/transport-plans")
    @require_roles("Caseworker", "ProviderStaff", "PlatformAdmin")
    def list_plans(rid):
        _referral_or_404(rid)
        limit, offset = parse_pagination(request.args)
        items = [t for t in db.transport_plans.values() if t["referral_id"] == rid]
        items.sort(key=lambda x: x["created_at"])
        window, pg = paginate(items, limit, offset)
        return success([serialise_transport(t) for t in window], 200, "array", pg)
