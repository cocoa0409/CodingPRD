"""Sponsorship deals and deliverables (§3.7): negotiation arc, activation with
category exclusivity, parallel performance/disclosure axes, OCC reschedule."""

from datetime import timedelta

from flask import Blueprint, request

import db
import domain
from core import (ApiError, auth, body, err_invalid_request, err_invalid_state,
                  err_not_found, err_ownership, ok_obj, paginate, pagination,
                  req_dt, req_enum, req_int, req_str, require_role)

bp = Blueprint("deals", __name__)

CATEGORIES = ("GAMING_HARDWARE", "ENERGY_DRINK", "VPN", "GAME_PUBLISHER", "OTHER")
DEAL_ACTIONS = ("PROPOSE", "ACCEPT", "ACTIVATE", "CANCEL")
DELIVERABLE_KINDS = ("AD_READ", "SPONSORED_SEGMENT", "LOGO_PLACEMENT", "PRODUCT_PLACEMENT")
DELIVERABLE_ACTIONS = ("PERFORM", "DISCLOSE", "VERIFY", "DISPUTE")
DEAL_READ_ROLES = ("PlatformAdmin", "Creator", "Sponsor")
SPONSORSHIP_FEE_BPS = 1000
DISCLOSURE_WINDOW_HOURS = 24
MISS_BREACH_THRESHOLD = 3


def flights_intersect(a_start, a_end, b_start, b_end):
    """Closed-interval intersection: a shared boundary instant counts."""
    return a_start <= b_end and b_start <= a_end


def breach_deal(deal):
    """ACTIVE -> BREACHED with the clawback chargeback against the
    activation-time SPONSORSHIP event (the original event is NOT flipped)."""
    deal["deal_status"] = "BREACHED"
    db.touch(deal)
    domain.create_revenue_event(
        deal["channel_id"], "CHARGEBACK", -deal["total_value_cents"],
        SPONSORSHIP_FEE_BPS, db.now(),
        reverses_event_id=deal.get("_activation_event_id"))


# ---------------------------------------------------------------------------
# Deals
# ---------------------------------------------------------------------------
@bp.post("/api/channels/<channel_id>/deals")
def create_deal(channel_id):
    uid, role = auth()
    b = body()
    sponsor_ref = req_str(b, "sponsor_ref")
    title = req_str(b, "title")
    category = req_enum(b, "category", CATEGORIES)
    total_value_cents = req_int(b, "total_value_cents", lo=0)
    flight_start = req_dt(b, "flight_start")
    flight_end = req_dt(b, "flight_end")
    required_deliverable_count = req_int(b, "required_deliverable_count", lo=0)
    if flight_end < flight_start:
        raise err_invalid_request("flight_end must not precede flight_start")
    require_role(role, ("Creator",))
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    if uid != channel_id:
        raise err_ownership()
    d = db.new_entity(
        channel_id=channel_id,
        sponsor_ref=sponsor_ref,
        title=title,
        category=category,
        total_value_cents=total_value_cents,
        flight_start=flight_start,
        flight_end=flight_end,
        required_deliverable_count=required_deliverable_count,
        deal_status="DRAFT",
        miss_count=0,
        _activation_event_id=None,
    )
    db.store.deals[d["id"]] = d
    return ok_obj(domain.deal_json(d), status=201)


@bp.get("/api/deals/<deal_id>")
def get_deal(deal_id):
    uid, role = auth()
    require_role(role, DEAL_READ_ROLES)
    d = db.store.deals.get(deal_id)
    if d is None:
        raise err_not_found("Deal not found")
    return ok_obj(domain.deal_json(d))


@bp.get("/api/channels/<channel_id>/deals")
def list_deals(channel_id):
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, DEAL_READ_ROLES)
    if domain.get_channel(channel_id) is None:
        raise err_not_found("Channel not found")
    deals = [d for d in db.store.deals.values() if d["channel_id"] == channel_id]
    for name in ("deal_status", "category"):
        v = request.args.get(name)
        if v is not None:
            deals = [d for d in deals if d[name] == v]
    return paginate(deals, limit, offset, domain.deal_json)


@bp.post("/api/deals/<deal_id>/transition")
def transition_deal(deal_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", DEAL_ACTIONS)
    if action == "ACCEPT":
        require_role(role, ("Sponsor",))
    else:
        require_role(role, ("Creator",))
    d = db.store.deals.get(deal_id)
    if d is None:
        raise err_not_found("Deal not found")
    if role == "Creator" and uid != d["channel_id"]:
        raise err_ownership()

    if action == "PROPOSE":
        if d["deal_status"] != "DRAFT":
            raise err_invalid_state("Only a DRAFT deal can be proposed")
        d["deal_status"] = "PROPOSED"
    elif action == "ACCEPT":
        if d["deal_status"] != "PROPOSED":
            raise err_invalid_state("Only a PROPOSED deal can be accepted")
        if uid != d["sponsor_ref"]:
            raise ApiError("ERR_SPONSOR_MISMATCH", 403,
                           "Sponsor X-User-ID must equal the deal's sponsor_ref")
        d["deal_status"] = "ACCEPTED"
    elif action == "ACTIVATE":
        if d["deal_status"] != "ACCEPTED":
            raise err_invalid_state("Only an ACCEPTED deal can be activated")
        # The clock must fall within the closed flight interval.
        if not (d["flight_start"] <= db.now() <= d["flight_end"]):
            raise err_invalid_state("Deal activation is outside the flight window")
        ch = domain.get_channel(d["channel_id"])
        if domain.monetization_posture(ch) == "SUSPENDED":
            raise ApiError("ERR_CHANNEL_SUSPENDED", 409,
                           "Channel monetization_posture is SUSPENDED")
        # Category exclusivity (14): no other ACCEPTED/ACTIVE same-category deal
        # whose closed flight interval intersects this one.
        for other in db.store.deals.values():
            if other["id"] == d["id"] or other["channel_id"] != d["channel_id"]:
                continue
            if other["deal_status"] in ("ACCEPTED", "ACTIVE") \
                    and other["category"] == d["category"] \
                    and flights_intersect(d["flight_start"], d["flight_end"],
                                          other["flight_start"], other["flight_end"]):
                raise ApiError("ERR_CATEGORY_EXCLUSIVITY_CONFLICT", 409,
                               "A same-category ACCEPTED/ACTIVE deal's flight intersects")
        d["deal_status"] = "ACTIVE"
        db.touch(d)
        # Activation books the revenue: SPONSORSHIP event, 10% platform cut.
        e = domain.create_revenue_event(d["channel_id"], "SPONSORSHIP",
                                        d["total_value_cents"], SPONSORSHIP_FEE_BPS,
                                        db.now())
        d["_activation_event_id"] = e["id"]
        return ok_obj(domain.deal_json(d))
    else:  # CANCEL
        if d["deal_status"] not in ("DRAFT", "PROPOSED", "ACCEPTED"):
            raise err_invalid_state("Only a DRAFT, PROPOSED, or ACCEPTED deal can be cancelled")
        d["deal_status"] = "CANCELLED"

    db.touch(d)
    return ok_obj(domain.deal_json(d))


# ---------------------------------------------------------------------------
# Deliverables
# ---------------------------------------------------------------------------
@bp.post("/api/deals/<deal_id>/deliverables")
def create_deliverable(deal_id):
    uid, role = auth()
    b = body()
    kind = req_enum(b, "kind", DELIVERABLE_KINDS)
    due_at = req_dt(b, "due_at")
    stream_id = b.get("stream_id")
    if stream_id is not None and not isinstance(stream_id, str):
        raise err_invalid_request("Field 'stream_id' must be a string")
    require_role(role, ("Creator",))
    d = db.store.deals.get(deal_id)
    if d is None:
        raise err_not_found("Deal not found")
    stream = None
    if stream_id is not None:
        stream = db.store.streams.get(stream_id)
        if stream is None or stream["channel_id"] != d["channel_id"]:
            raise err_not_found("Stream not found in this deal's channel")
    # due_at must lie within the deal's (closed) flight — well-formedness rule.
    if not (d["flight_start"] <= due_at <= d["flight_end"]):
        raise err_invalid_request("due_at must lie within the deal's flight")
    if uid != d["channel_id"]:
        raise err_ownership()
    # Deliverables may be added only while the deal is ACTIVE.
    if d["deal_status"] != "ACTIVE":
        raise err_invalid_state("Deliverables may be added only to an ACTIVE deal")
    dv = db.new_entity(
        deal_id=deal_id,
        stream_id=stream_id,
        kind=kind,
        due_at=due_at,
        performance_status="SCHEDULED",
        disclosure_status="PENDING",
        performed_at=None,
        disclosure_deadline=None,
    )
    db.store.deliverables[dv["id"]] = dv
    return ok_obj(domain.deliverable_json(dv), status=201)


@bp.get("/api/deliverables/<deliverable_id>")
def get_deliverable(deliverable_id):
    uid, role = auth()
    require_role(role, DEAL_READ_ROLES)
    dv = db.store.deliverables.get(deliverable_id)
    if dv is None:
        raise err_not_found("Deliverable not found")
    return ok_obj(domain.deliverable_json(dv))


@bp.get("/api/deliverables")
def list_deliverables():
    uid, role = auth()
    limit, offset = pagination()
    require_role(role, DEAL_READ_ROLES)
    dvs = list(db.store.deliverables.values())
    for name in ("deal_id", "stream_id", "performance_status", "disclosure_status"):
        v = request.args.get(name)
        if v is not None:
            dvs = [d for d in dvs if d[name] == v]
    return paginate(dvs, limit, offset, domain.deliverable_json)


@bp.post("/api/deliverables/<deliverable_id>/transition")
def transition_deliverable(deliverable_id):
    uid, role = auth()
    b = body()
    action = req_enum(b, "action", DELIVERABLE_ACTIONS)
    stream_id = b.get("stream_id")
    if stream_id is not None and not isinstance(stream_id, str):
        raise err_invalid_request("Field 'stream_id' must be a string")
    if action == "PERFORM" and not stream_id:
        raise err_invalid_request("PERFORM requires a stream_id")
    if action in ("PERFORM", "DISCLOSE"):
        require_role(role, ("Creator",))
    else:
        require_role(role, ("Sponsor",))
    dv = db.store.deliverables.get(deliverable_id)
    if dv is None:
        raise err_not_found("Deliverable not found")
    deal = db.store.deals.get(dv["deal_id"])
    if deal is None:
        raise err_not_found("Deal not found")
    stream = None
    if stream_id is not None:
        stream = db.store.streams.get(stream_id)
        if stream is None or stream["channel_id"] != deal["channel_id"]:
            raise err_not_found("Stream not found in this deal's channel")
    if role == "Creator" and uid != deal["channel_id"]:
        raise err_ownership()

    if action == "PERFORM":
        if dv["performance_status"] != "SCHEDULED":
            raise err_invalid_state("Only a SCHEDULED deliverable can be performed")
        if stream["stream_status"] != "ENDED":
            raise err_invalid_state("The referenced stream must have ENDED")
        ch = domain.get_channel(deal["channel_id"])
        if domain.monetization_posture(ch) == "SUSPENDED":
            raise ApiError("ERR_CHANNEL_SUSPENDED", 409,
                           "Channel monetization_posture is SUSPENDED")
        if db.now() > dv["due_at"]:
            raise ApiError("ERR_DELIVERABLE_OVERDUE", 409,
                           "Performance is past the deliverable's due_at")
        dv["performance_status"] = "PERFORMED"
        dv["performed_at"] = db.now()
        dv["disclosure_deadline"] = db.now() + timedelta(hours=DISCLOSURE_WINDOW_HOURS)
        dv["stream_id"] = stream_id

    elif action == "DISCLOSE":
        if dv["performance_status"] != "PERFORMED":
            raise err_invalid_state("Only a PERFORMED deliverable can be disclosed")
        if dv["disclosure_status"] != "PENDING":
            raise err_invalid_state("The disclosure axis has already moved")
        if db.now() <= dv["disclosure_deadline"]:
            dv["disclosure_status"] = "DISCLOSED_ON_TIME"
        else:
            dv["disclosure_status"] = "DISCLOSED_LATE"  # flips disclosure_compliant false

    elif action == "VERIFY":
        if dv["performance_status"] not in ("PERFORMED", "DISPUTED"):
            raise err_invalid_state("Only a PERFORMED or DISPUTED deliverable can be verified")
        if uid != deal["sponsor_ref"]:
            raise ApiError("ERR_SPONSOR_MISMATCH", 403,
                           "Sponsor X-User-ID must equal the deal's sponsor_ref")
        if dv["disclosure_status"] not in ("DISCLOSED_ON_TIME", "DISCLOSED_LATE"):
            raise ApiError("ERR_DISCLOSURE_REQUIRED", 409,
                           "Disclosure must be recorded before verification")
        dv["performance_status"] = "VERIFIED"

    else:  # DISPUTE
        if dv["performance_status"] != "PERFORMED":
            raise err_invalid_state("Only a PERFORMED deliverable can be disputed")
        if uid != deal["sponsor_ref"]:
            raise ApiError("ERR_SPONSOR_MISMATCH", 403,
                           "Sponsor X-User-ID must equal the deal's sponsor_ref")
        dv["performance_status"] = "DISPUTED"

    db.touch(dv)
    return ok_obj(domain.deliverable_json(dv))


@bp.post("/api/deliverables/<deliverable_id>/reschedule")
def reschedule_deliverable(deliverable_id):
    uid, role = auth()
    b = body()
    due_at = req_dt(b, "due_at")
    expected_version = req_int(b, "expected_deliverable_version")
    require_role(role, ("Creator",))
    dv = db.store.deliverables.get(deliverable_id)
    if dv is None:
        raise err_not_found("Deliverable not found")
    deal = db.store.deals.get(dv["deal_id"])
    if deal is None:
        raise err_not_found("Deal not found")
    # The new due_at must lie within the deal flight (well-formedness rule).
    if not (deal["flight_start"] <= due_at <= deal["flight_end"]):
        raise err_invalid_request("due_at must lie within the deal's flight")
    if uid != deal["channel_id"]:
        raise err_ownership()
    if dv["performance_status"] not in ("MISSED", "DISPUTED"):
        raise err_invalid_state("Only a MISSED or DISPUTED deliverable can be rescheduled")
    if expected_version != dv["version"]:
        raise ApiError("ERR_STALE_VERSION", 412,
                       "expected_deliverable_version does not match the deliverable's current version")
    was_disputed = dv["performance_status"] == "DISPUTED"
    dv["performance_status"] = "SCHEDULED"
    dv["due_at"] = due_at
    dv["disclosure_status"] = "PENDING"
    dv["disclosure_deadline"] = None
    if was_disputed:
        dv["performed_at"] = None
        dv["stream_id"] = None
    # miss_count is NOT decremented — misses are permanent history.
    db.touch(dv)  # version increments by exactly 1
    return ok_obj(domain.deliverable_json(dv))
