"""Post-closing servicing: landowner disputes and revenue-share events (PRD 3.8)."""

from datetime import timedelta

from flask import Blueprint

import calc
import engine as E
import validate as V
from auth import principal
from db import db
from errors import fail
from response import created, ok, ok_list

bp = Blueprint("servicing", __name__)

DISPUTE_TYPES = ("ACCESS", "INTERFERENCE", "PROPERTY_USE")
DISPUTE_STATUSES = ("OPEN", "CURE_PENDING", "REOPENED", "UPHELD", "DISMISSED", "RESOLVED")
EVENT_TYPES = ("COLOCATION_ADDED", "AMENDMENT", "RENT_INCREASE")
AMENDMENT_STATUSES = ("RECORDED", "REVERSED")

DISPUTE_WRITE_ROLES = ("Landowner", "ServicingAgent", "PlatformAdmin")
DISPUTE_READ_ROLES = DISPUTE_WRITE_ROLES + ("PortfolioManager",)
AMENDMENT_READ_ROLES = ("ServicingAgent", "PortfolioManager", "PlatformAdmin", "Landowner")

ROLE_ACTIONS = {
    "ServicingAgent": ("START_CURE",),
    "Landowner": ("CONFIRM_CURE", "REOPEN"),
    "PlatformAdmin": ("UPHOLD", "DISMISS"),
}
DISPUTE_ACTIONS = ("START_CURE", "CONFIRM_CURE", "REOPEN", "UPHOLD", "DISMISS")

DISPUTE_TRANSITIONS = {
    "START_CURE": ("OPEN", "REOPENED"),
    "CONFIRM_CURE": ("CURE_PENDING",),
    "REOPEN": ("CURE_PENDING",),
    "UPHOLD": ("OPEN", "REOPENED"),
    "DISMISS": ("OPEN", "REOPENED"),
}


def _landowner_of_stream(stream):
    return db.landowners.get(stream["landowner_id"])


def _restore_performing(stream):
    if E.open_disputes_count(stream["id"]) == 0 and stream["servicing_status"] == "WATCHLIST":
        E.set_servicing_status(stream, "PERFORMING")


# --------------------------------------------------------------------- disputes

@bp.post("/lease-streams/<sid>/disputes")
def open_dispute(sid):
    user_id, role = principal(*DISPUTE_WRITE_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    b = V.body()
    dispute_type = V.req_enum(b, "dispute_type", DISPUTE_TYPES)
    description = V.req_str(b, "description")

    landowner = _landowner_of_stream(stream)
    if role == "Landowner" and (landowner is None or landowner["id"] != user_id):
        fail("ERR_NOT_DEAL_LANDOWNER")

    for existing in E.disputes_of(stream["id"]):
        if (existing["dispute_type"] == dispute_type
                and existing["status"] in E.DISPUTE_OPEN_STATUSES):
            fail("ERR_DISPUTE_ALREADY_OPEN")

    dispute = E.new_entity(
        lease_stream_id=stream["id"],
        dispute_type=dispute_type,
        description=description,
        raised_by_role=role,
        status="OPEN",
        cure_attempts=0,
        cure_deadline=None,
        resolved_at=None,
    )
    db.disputes[dispute["id"]] = dispute
    E.recompute_open_dispute_count(landowner)

    deal = E.active_deal_of_stream(stream["id"])
    if deal is not None:
        E.recompute_settlement(deal)
    return created(E.dispute_json(dispute))


@bp.get("/lease-streams/<sid>/disputes")
def list_disputes(sid):
    principal(*DISPUTE_READ_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    limit, offset = V.pagination()
    status = V.enum_filter("status", DISPUTE_STATUSES)
    dispute_type = V.enum_filter("dispute_type", DISPUTE_TYPES)
    rows = E.disputes_of(stream["id"])
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if dispute_type is not None:
        rows = [r for r in rows if r["dispute_type"] == dispute_type]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.dispute_json(r) for r in page], total, limit, offset)


@bp.get("/disputes/<did>")
def get_dispute(did):
    principal(*DISPUTE_READ_ROLES)
    dispute = E.find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    return ok(E.dispute_json(dispute))


@bp.post("/disputes/<did>/transitions")
def dispute_transition(did):
    user_id, role = principal(*DISPUTE_WRITE_ROLES)
    dispute = E.find("disputes", did, "ERR_DISPUTE_NOT_FOUND")
    b = V.body()
    action = V.req_enum(b, "action", DISPUTE_ACTIONS)

    stream = db.lease_streams.get(dispute["lease_stream_id"])
    landowner = _landowner_of_stream(stream) if stream else None

    if role == "Landowner" and (landowner is None or landowner["id"] != user_id):
        fail("ERR_NOT_DEAL_LANDOWNER")
    if action not in ROLE_ACTIONS[role]:
        fail("ERR_ACTION_ROLE_MISMATCH")
    if dispute["status"] not in DISPUTE_TRANSITIONS[action]:
        fail("ERR_INVALID_DISPUTE_STATE")

    if action == "START_CURE":
        if dispute["cure_attempts"] >= calc.MAX_CURE_ATTEMPTS:
            fail("ERR_CURE_ATTEMPTS_EXHAUSTED")
        from_open = dispute["status"] == "OPEN"
        dispute["status"] = "CURE_PENDING"
        dispute["cure_attempts"] += 1
        dispute["cure_deadline"] = E.now() + timedelta(days=calc.CURE_DEADLINE_DAYS)
        E.touch(dispute)
        if from_open and stream is not None and stream["servicing_status"] == "PERFORMING":
            E.set_servicing_status(stream, "WATCHLIST")

    elif action == "CONFIRM_CURE":
        dispute["status"] = "RESOLVED"
        dispute["resolved_at"] = E.now()
        E.touch(dispute)
        E.recompute_open_dispute_count(landowner)
        if stream is not None:
            _restore_performing(stream)

    elif action == "REOPEN":
        dispute["status"] = "REOPENED"
        E.touch(dispute)
        E.recompute_open_dispute_count(landowner)

    elif action == "UPHOLD":
        dispute["status"] = "UPHELD"
        dispute["resolved_at"] = E.now()
        E.touch(dispute)
        E.recompute_open_dispute_count(landowner)
        if stream is not None:
            E.set_servicing_status(stream, "IMPAIRED")

    else:  # DISMISS
        from_reopened = dispute["status"] == "REOPENED"
        dispute["status"] = "DISMISSED"
        dispute["resolved_at"] = E.now()
        E.touch(dispute)
        E.recompute_open_dispute_count(landowner)
        if from_reopened and stream is not None:
            _restore_performing(stream)

    return ok(E.dispute_json(dispute))


# ------------------------------------------------------------ amendment events

@bp.post("/lease-streams/<sid>/amendment-events")
def record_amendment(sid):
    principal("ServicingAgent")
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    b = V.body()
    event_type = V.req_enum(b, "event_type", EVENT_TYPES)
    gross = V.req_int(b, "gross_amount_cents", minimum=1)
    effective_date = V.req_date(b, "effective_date")
    pass_through = V.opt_int(b, "pass_through_cost_cents", default=0, minimum=0)

    if stream["acquisition_status"] != "ACQUIRED":
        fail("ERR_STREAM_NOT_ACQUIRED")

    deal = E.closed_deal_of_stream(stream["id"])
    share_bps = deal["revenue_share_bps"] if deal is not None else 2500
    figures = calc.amendment_split(event_type, gross, pass_through, share_bps)

    event = E.new_entity(
        lease_stream_id=stream["id"],
        event_type=event_type,
        gross_amount_cents=gross,
        pass_through_cost_cents=pass_through,
        effective_date=effective_date,
        status="RECORDED",
        reversal_reason=None,
        **figures,
    )
    db.amendments[event["id"]] = event

    stream["cumulative_revenue_share_landowner_cents"] += figures["landowner_share_cents"]
    stream["cumulative_revenue_share_acquirer_cents"] += figures["acquirer_share_cents"]
    E.touch(stream)
    return created(E.amendment_json(event))


@bp.get("/lease-streams/<sid>/amendment-events")
def list_amendments(sid):
    principal(*AMENDMENT_READ_ROLES)
    stream = E.find("lease_streams", sid, "ERR_LEASE_STREAM_NOT_FOUND")
    limit, offset = V.pagination()
    event_type = V.enum_filter("event_type", EVENT_TYPES)
    status = V.enum_filter("status", AMENDMENT_STATUSES)
    rows = E.amendments_of(stream["id"])
    if event_type is not None:
        rows = [r for r in rows if r["event_type"] == event_type]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    page, total = E.paginate(rows, limit, offset)
    return ok_list([E.amendment_json(r) for r in page], total, limit, offset)


@bp.post("/amendment-events/<aid>/reverse")
def reverse_amendment(aid):
    principal("ServicingAgent")
    event = E.find("amendments", aid, "ERR_AMENDMENT_NOT_FOUND")
    b = V.body()
    reason = V.req_str(b, "reversal_reason")

    if event["status"] != "RECORDED":
        fail("ERR_INVALID_AMENDMENT_STATE")

    event["status"] = "REVERSED"
    event["reversal_reason"] = reason
    E.touch(event)

    stream = db.lease_streams.get(event["lease_stream_id"])
    if stream is not None:
        stream["cumulative_revenue_share_landowner_cents"] -= event["landowner_share_cents"]
        stream["cumulative_revenue_share_acquirer_cents"] -= event["acquirer_share_cents"]
        E.touch(stream)
    return ok(E.amendment_json(event))
