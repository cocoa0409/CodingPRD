"""Matches and tours."""
from flask import Blueprint, request

import store
import calc
import services as svc
import validate as V
import envelope as E
import constants as C
from rbac import guard, deny_ownership
from errors import ApiError
from serialize import dump
from protected import PROTECTED

bp = Blueprint("match", __name__)


# ===========================================================================
# Matches
# ===========================================================================
@bp.post("/matches")
def create_match():
    uid, role = guard(["Advisor"])
    body = V.get_body()
    V.reject_protected(body, {"inquiry_id", "community_id", "care_level"}, PROTECTED["match"])
    inquiry_id = V.req_str(body, "inquiry_id")
    community_id = V.req_str(body, "community_id")
    care_level = V.req_enum(body, "care_level", C.CARE_LEVELS)
    inquiry = V.lookup("inquiries", inquiry_id, "ERR_INQUIRY_NOT_FOUND")
    community = V.lookup("communities", community_id, "ERR_COMMUNITY_NOT_FOUND")
    # (12) community active
    if community["status"] != "ACTIVE":
        raise ApiError("ERR_COMMUNITY_NOT_ACTIVE", "Community is not active.")
    # (13) approved assessment + inquiry status
    assessment = svc.assessment_for_inquiry(inquiry_id)
    if assessment is None or assessment["status"] != "APPROVED":
        raise ApiError("ERR_ASSESSMENT_NOT_APPROVED", "Inquiry has no approved assessment.")
    if inquiry["status"] not in ("ASSESSED", "MATCHING", "TOURING"):
        raise ApiError("ERR_INQUIRY_INVALID_STATE", "Inquiry state does not permit matching.")
    # (17) duplicate match
    for m in store.DB["matches"].values():
        if (m["inquiry_id"] == inquiry_id and m["community_id"] == community_id
                and m["status"] not in ("DECLINED", "WITHDRAWN")):
            raise ApiError("ERR_DUPLICATE_MATCH", "A live match already exists for this pair.")
    # (20) OPEN inventory for care level
    inv = svc.open_inventory_for(community_id, care_level)
    if inv is None:
        raise ApiError("ERR_CARE_LEVEL_UNAVAILABLE", "No open unit pool for this care level.")
    # (33) budget
    if inv["monthly_rate_cents"] > assessment["affordability_ceiling_cents"]:
        raise ApiError("ERR_BUDGET_EXCEEDED", "Rate exceeds affordability ceiling.")
    rate = inv["monthly_rate_cents"]
    fit = calc.match_fit_score(care_level, assessment["recommended_care_level"],
                               assessment["affordability_ceiling_cents"], rate,
                               community["quality_rating"], inv["available_units"])
    row = svc.new_row("matches", {
        "inquiry_id": inquiry_id, "community_id": community_id, "care_level": care_level,
        "quoted_monthly_rate_cents": rate, "fit_score": fit, "status": "PROPOSED",
        "decline_reason_code": None, "tour_round": 0,
    })
    inquiry["match_count"] = inquiry["match_count"] + 1
    if inquiry["status"] == "ASSESSED":
        inquiry["status"] = "MATCHING"
        svc.touch(inquiry)
    return E.created(dump(row))


@bp.get("/matches/<match_id>")
def get_match(match_id):
    guard(C.ALL_ROLES)
    m = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    return E.ok(dump(m))


@bp.get("/matches")
def list_matches():
    guard(C.ALL_ROLES)
    rows = list(store.DB["matches"].values())
    for key in ("inquiry_id", "community_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


@bp.post("/matches/<match_id>/shortlist")
def shortlist_match(match_id):
    guard(["Advisor", "Family"])
    m = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    V.get_body()
    if m["status"] not in ("PROPOSED", "TOURED"):
        raise ApiError("ERR_MATCH_INVALID_STATE", "Match cannot be shortlisted in its state.")
    m["status"] = "SHORTLISTED"
    svc.touch(m)
    return E.ok(dump(m))


@bp.post("/matches/<match_id>/decline")
def decline_match(match_id):
    guard(["Advisor", "Family"])
    m = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason_code"}, PROTECTED["match"])
    reason_code = V.req_str(body, "reason_code")
    if m["status"] not in ("PROPOSED", "SHORTLISTED", "TOURED"):
        raise ApiError("ERR_MATCH_INVALID_STATE", "Match cannot be declined in its state.")
    m["status"] = "DECLINED"
    m["decline_reason_code"] = reason_code
    svc.touch(m)
    inquiry = store.DB["inquiries"].get(m["inquiry_id"])
    if inquiry is not None:
        inquiry["match_count"] = inquiry["match_count"] - 1
    return E.ok(dump(m))


@bp.post("/matches/<match_id>/select")
def select_match(match_id):
    guard(["Advisor"])
    m = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    V.get_body()
    if m["status"] != "TOURED":
        raise ApiError("ERR_MATCH_INVALID_STATE", "Match must be TOURED to select.")
    community = store.DB["communities"].get(m["community_id"])
    if community is None or community["status"] != "ACTIVE":
        raise ApiError("ERR_COMMUNITY_NOT_ACTIVE", "Community is not active.")
    m["status"] = "SELECTED"
    svc.touch(m)
    return E.ok(dump(m))


# ===========================================================================
# Tours
# ===========================================================================
@bp.post("/tours")
def create_tour():
    uid, role = guard(["Advisor"])
    body = V.get_body()
    V.reject_protected(body, {"match_id", "scheduled_start", "scheduled_end", "mode"},
                       PROTECTED["tour"])
    match_id = V.req_str(body, "match_id")
    if "scheduled_start" not in body:
        raise ApiError("ERR_VALIDATION", "scheduled_start is required.")
    if "scheduled_end" not in body:
        raise ApiError("ERR_VALIDATION", "scheduled_end is required.")
    start_dt = V.req_datetime(body, "scheduled_start")
    end_dt = V.req_datetime(body, "scheduled_end")
    raw_start = body["scheduled_start"]
    raw_end = body["scheduled_end"]
    mode = V.req_enum(body, "mode", C.TOUR_MODE)
    match = V.lookup("matches", match_id, "ERR_MATCH_NOT_FOUND")
    # (10) match state
    if match["status"] != "SHORTLISTED":
        raise ApiError("ERR_MATCH_INVALID_STATE", "Match must be SHORTLISTED to book a tour.")
    community = store.DB["communities"][match["community_id"]]
    # (12) community active
    if community["status"] != "ACTIVE":
        raise ApiError("ERR_COMMUNITY_NOT_ACTIVE", "Community is not active.")
    # (24) time window
    now = store.get_now()
    duration_min = (end_dt - start_dt).total_seconds() / 60.0
    if not (end_dt > start_dt) or duration_min < C.TOUR_MIN_MINUTES \
            or duration_min > C.TOUR_MAX_MINUTES or start_dt < now:
        raise ApiError("ERR_TOUR_OUTSIDE_HOURS", "Tour time window is invalid.")
    inquiry = store.DB["inquiries"][match["inquiry_id"]]
    advisor_id = inquiry["assigned_advisor_id"]
    # (25) community tour-slot capacity — closed-interval intersection
    slot_count = 0
    for t in store.DB["tours"].values():
        if t["community_id"] == match["community_id"] and t["status"] == "SCHEDULED":
            if t["_start_dt"] <= end_dt and start_dt <= t["_end_dt"]:
                slot_count += 1
    if slot_count >= community["tour_slot_capacity"]:
        raise ApiError("ERR_TOUR_SLOT_CONFLICT", "Community tour-slot capacity reached.")
    # (26) advisor calendar — strict buffered overlap
    from datetime import timedelta
    for t in store.DB["tours"].values():
        if t["advisor_id"] == advisor_id and t["status"] == "SCHEDULED":
            buffer_min = C.TRAVEL_BUFFER_MINUTES if (mode == "IN_PERSON" or t["mode"] == "IN_PERSON") else 0
            b = timedelta(minutes=buffer_min)
            if start_dt < t["_end_dt"] + b and t["_start_dt"] < end_dt + b:
                raise ApiError("ERR_ADVISOR_SCHEDULE_CONFLICT", "Advisor calendar conflict.")
    row = svc.new_row("tours", {
        "match_id": match_id, "advisor_id": advisor_id,
        "community_id": match["community_id"], "scheduled_start": raw_start,
        "scheduled_end": raw_end, "_start_dt": start_dt, "_end_dt": end_dt,
        "mode": mode, "status": "SCHEDULED", "outcome_rating": None,
        "cancel_reason_code": None,
    })
    match["status"] = "TOUR_SCHEDULED"
    match["tour_round"] = match["tour_round"] + 1
    svc.touch(match)
    if inquiry["status"] == "MATCHING":
        inquiry["status"] = "TOURING"
        svc.touch(inquiry)
    return E.created(dump(row))


@bp.get("/tours/<tour_id>")
def get_tour(tour_id):
    guard(C.ALL_ROLES)
    t = V.lookup("tours", tour_id, "ERR_TOUR_NOT_FOUND")
    return E.ok(dump(t))


@bp.get("/tours")
def list_tours():
    guard(C.ALL_ROLES)
    rows = list(store.DB["tours"].values())
    for key in ("match_id", "advisor_id", "community_id", "status"):
        val = request.args.get(key)
        if val is not None:
            rows = [r for r in rows if r.get(key) == val]
    items, limit, offset, total, has_more = V.paginate(rows, dump)
    return E.ok_list(items, limit, offset, total, has_more)


def _match_back_to_shortlist(tour):
    match = store.DB["matches"].get(tour["match_id"])
    if match is not None and match["status"] == "TOUR_SCHEDULED":
        match["status"] = "SHORTLISTED"
        svc.touch(match)


@bp.post("/tours/<tour_id>/complete")
def complete_tour(tour_id):
    uid, role = guard(["Advisor"])
    t = V.lookup("tours", tour_id, "ERR_TOUR_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"outcome_rating"}, PROTECTED["tour"])
    outcome = V.req_int(body, "outcome_rating", 1, 5)
    if uid != t["advisor_id"]:
        deny_ownership()
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_TOUR_INVALID_STATE", "Tour is not SCHEDULED.")
    t["outcome_rating"] = outcome
    t["status"] = "COMPLETED"
    match = store.DB["matches"].get(t["match_id"])
    if match is not None and match["status"] == "TOUR_SCHEDULED":
        match["status"] = "TOURED"
        svc.touch(match)
    svc.touch(t)
    return E.ok(dump(t))


@bp.post("/tours/<tour_id>/cancel")
def cancel_tour(tour_id):
    uid, role = guard(["Advisor", "Family"])
    t = V.lookup("tours", tour_id, "ERR_TOUR_NOT_FOUND")
    body = V.get_body()
    V.reject_protected(body, {"reason_code"}, PROTECTED["tour"])
    reason_code = V.req_str(body, "reason_code")
    if role == "Advisor" and uid != t["advisor_id"]:
        deny_ownership()
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_TOUR_INVALID_STATE", "Tour is not SCHEDULED.")
    t["cancel_reason_code"] = reason_code
    t["status"] = "CANCELLED"
    _match_back_to_shortlist(t)
    svc.touch(t)
    return E.ok(dump(t))


@bp.post("/tours/<tour_id>/no-show")
def no_show_tour(tour_id):
    uid, role = guard(["Advisor"])
    t = V.lookup("tours", tour_id, "ERR_TOUR_NOT_FOUND")
    V.get_body()
    if uid != t["advisor_id"]:
        deny_ownership()
    if t["status"] != "SCHEDULED":
        raise ApiError("ERR_TOUR_INVALID_STATE", "Tour is not SCHEDULED.")
    t["status"] = "NO_SHOW"
    _match_back_to_shortlist(t)
    svc.touch(t)
    return E.ok(dump(t))
