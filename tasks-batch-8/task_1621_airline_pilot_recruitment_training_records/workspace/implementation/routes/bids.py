"""Bid periods and bids: seniority-snapshot ranking and award execution."""

from datetime import datetime, timezone

from flask import Blueprint, request

from db import store
from errors import ApiError
from middleware import require_roles
from services import (
    bump, get_applicant, get_bid, get_bid_period, get_equipment,
    has_valid_first_medical, ser_bid, ser_bid_period, stamp_new,
)
from util import (
    get_body, is_int, pagination_params, req_int, req_str, req_ts, sort_rows,
    success_list, success_object,
)

bp = Blueprint("bids", __name__)

PERIOD_READ_ROLES = ("Recruiter", "CrewScheduler", "TrainingCoordinator", "Pilot", "SystemAdmin")


# ---- Bid periods -----------------------------------------------------------------

@bp.post("/bid-periods")
def create_bid_period():
    require_roles("CrewScheduler", "SystemAdmin")
    body = get_body()
    equipment_id = req_str(body, "equipment_id")
    opens_at = req_ts(body, "opens_at")
    closes_at = req_ts(body, "closes_at")
    seats_available = body.get("seats_available")
    get_equipment(equipment_id)
    if not closes_at > opens_at:
        raise ApiError("ERR_INVALID_REQUEST", "closes_at must be strictly after opens_at")
    if not is_int(seats_available) or seats_available < 1:
        raise ApiError("ERR_INVALID_REQUEST", "seats_available must be an integer >= 1")
    period = stamp_new({
        "equipment_id": equipment_id,
        "opens_at": opens_at,
        "closes_at": closes_at,
        "seats_available": seats_available,
        "status": "DRAFT",
        "awarded_at": None,
    })
    store.bid_periods[period["id"]] = period
    return success_object(ser_bid_period(period), 201)


@bp.get("/bid-periods")
def list_bid_periods():
    require_roles(*PERIOD_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.bid_periods.values())
    equipment_id = request.args.get("equipment_id")
    status = request.args.get("status")
    if equipment_id is not None:
        rows = [p for p in rows if p["equipment_id"] == equipment_id]
    if status is not None:
        rows = [p for p in rows if p["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_bid_period(p) for p in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/bid-periods/<pid>")
def read_bid_period(pid):
    require_roles(*PERIOD_READ_ROLES)
    return success_object(ser_bid_period(get_bid_period(pid)))


@bp.post("/bid-periods/<pid>/open")
def open_bid_period(pid):
    require_roles("CrewScheduler", "SystemAdmin")
    period = get_bid_period(pid)
    if period["status"] != "DRAFT":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "open requires status DRAFT, found %s" % period["status"])
    now = store.now()
    if not (period["opens_at"] <= now <= period["closes_at"]):
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "open requires the logical clock inside the bidding window")
    period["status"] = "OPEN"
    bump(period)
    return success_object(ser_bid_period(period))


@bp.post("/bid-periods/<pid>/close")
def close_bid_period(pid):
    require_roles("CrewScheduler", "SystemAdmin")
    period = get_bid_period(pid)
    if period["status"] != "OPEN":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "close requires status OPEN, found %s" % period["status"])
    period["status"] = "CLOSED"
    bump(period)
    return success_object(ser_bid_period(period))


@bp.post("/bid-periods/<pid>/award")
def award_bid_period(pid):
    require_roles("CrewScheduler", "SystemAdmin")
    period = get_bid_period(pid)
    if period["status"] != "CLOSED":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "award requires status CLOSED, found %s" % period["status"])
    now = store.now()
    submitted = [b for b in store.bids.values()
                 if b["bid_period_id"] == pid and b["status"] == "SUBMITTED"]

    def eligible(b):
        applicant = store.applicants.get(b["applicant_id"])
        return (applicant is not None and applicant["status"] == "CLEARED"
                and has_valid_first_medical(b["applicant_id"]))

    eligible_bids = [b for b in submitted if eligible(b)]
    ineligible_bids = [b for b in submitted if not eligible(b)]

    # Ranking: seniority_snapshot ASC; ties by applicant.cleared_at ASC then
    # applicant.email ASC. Applicant.id never participates.
    _MAX_DT = datetime.max.replace(tzinfo=timezone.utc)

    def rank_key(b):
        applicant = store.applicants.get(b["applicant_id"])
        snapshot = b["seniority_snapshot"]
        snapshot_key = snapshot if snapshot is not None else float("inf")
        cleared_at = applicant["cleared_at"] if applicant and applicant["cleared_at"] else None
        email = applicant["email"] if applicant else ""
        return (snapshot_key, cleared_at if cleared_at is not None else _MAX_DT, email, b.get("_seq", 0))

    ranked = sorted(eligible_bids, key=rank_key)
    winners = ranked[:period["seats_available"]]
    losers = ranked[period["seats_available"]:]
    for b in winners:
        b["status"] = "AWARDED"
        b["awarded_at"] = now
        b["updated_at"] = now
        applicant = store.applicants.get(b["applicant_id"])
        if applicant is not None:
            applicant["current_equipment_id"] = period["equipment_id"]
            bump(applicant)
    for b in losers:
        b["status"] = "DENIED"
        b["denial_reason"] = "INSUFFICIENT_SENIORITY"
        b["updated_at"] = now
    for b in ineligible_bids:
        b["status"] = "DENIED"
        b["denial_reason"] = "INELIGIBLE"
        b["updated_at"] = now
    period["status"] = "AWARDED"
    period["awarded_at"] = now
    bump(period)
    return success_object(ser_bid_period(period))


@bp.post("/bid-periods/<pid>/finalize")
def finalize_bid_period(pid):
    require_roles("CrewScheduler", "SystemAdmin")
    period = get_bid_period(pid)
    if period["status"] != "AWARDED":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "finalize requires status AWARDED, found %s" % period["status"])
    period["status"] = "FINALIZED"
    bump(period)
    return success_object(ser_bid_period(period))


# ---- Bids -------------------------------------------------------------------------

@bp.post("/bids")
def create_bid():
    user_id, role = require_roles("CrewScheduler", "Pilot", "SystemAdmin")
    body = get_body()
    bid_period_id = req_str(body, "bid_period_id")
    applicant_id = req_str(body, "applicant_id")
    preference_rank = body.get("preference_rank")
    if role == "Pilot" and applicant_id != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Pilot may bid only under their own applicant_id")
    get_applicant(applicant_id)   # existence, §2.8 reference order
    period = get_bid_period(bid_period_id)
    if period["status"] != "OPEN":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "bid submission requires an OPEN period, found %s" % period["status"])
    if not is_int(preference_rank) or preference_rank < 1:
        raise ApiError("ERR_INVALID_REQUEST", "preference_rank must be an integer >= 1")
    if any(b["bid_period_id"] == bid_period_id and b["applicant_id"] == applicant_id
           for b in store.bids.values()):
        raise ApiError("ERR_DUPLICATE_BID", "One bid per applicant per bid period")
    applicant = store.applicants.get(applicant_id)
    bid = stamp_new({
        "bid_period_id": bid_period_id,
        "applicant_id": applicant_id,
        "preference_rank": preference_rank,
        "status": "SUBMITTED",
        "denial_reason": None,
        "seniority_snapshot": applicant["seniority_number"] if applicant else None,
        "awarded_at": None,
    })
    store.bids[bid["id"]] = bid
    return success_object(ser_bid(bid), 201)


@bp.get("/bids")
def list_bids():
    require_roles(*PERIOD_READ_ROLES)
    limit, offset = pagination_params()
    rows = list(store.bids.values())
    bid_period_id = request.args.get("bid_period_id")
    applicant_id = request.args.get("applicant_id")
    status = request.args.get("status")
    if bid_period_id is not None:
        rows = [b for b in rows if b["bid_period_id"] == bid_period_id]
    if applicant_id is not None:
        rows = [b for b in rows if b["applicant_id"] == applicant_id]
    if status is not None:
        rows = [b for b in rows if b["status"] == status]
    rows = sort_rows(rows)
    total = len(rows)
    return success_list([ser_bid(b) for b in rows[offset:offset + limit]], limit, offset, total)


@bp.get("/bids/<bid>")
def read_bid(bid):
    require_roles(*PERIOD_READ_ROLES)
    return success_object(ser_bid(get_bid(bid)))


@bp.post("/bids/<bid>/withdraw")
def withdraw_bid(bid):
    user_id, role = require_roles("CrewScheduler", "Pilot", "SystemAdmin")
    b = get_bid(bid)
    if role == "Pilot" and b["applicant_id"] != user_id:
        raise ApiError("ERR_FORBIDDEN_ROLE", "Pilot may withdraw only their own bids")
    if b["status"] != "SUBMITTED":
        raise ApiError("ERR_BID_INVALID_STATE",
                       "withdraw requires status SUBMITTED, found %s" % b["status"])
    period = store.bid_periods.get(b["bid_period_id"])
    if period is None or period["status"] != "OPEN":
        raise ApiError("ERR_BID_PERIOD_INVALID_STATE",
                       "bid withdrawal requires the period to still be OPEN")
    b["status"] = "WITHDRAWN"
    bump(b)
    return success_object(ser_bid(b))
