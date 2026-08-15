"""Traffic calming requests and the resources created beneath them
(PRD §3.2 filing & petition; §3.3 studies; §3.5 plans; §3.6 ballots;
§3.7 work orders; §3.8 removal requests)."""
from datetime import timedelta

from flask import Blueprint, g, request

from auth import require_roles, ALL_ROLES
from calc import required_signatures, study_window_conflicts, quorum_required
from envelope import object_response
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_REQUEST_INVALID_STATE,
    ERR_ACTIVE_REQUEST_EXISTS, ERR_SEGMENT_NOT_ELIGIBLE,
    ERR_HOUSEHOLD_NOT_ON_SEGMENT, ERR_DUPLICATE_HOUSEHOLD_SIGNATURE,
    ERR_STUDY_WINDOW_CONFLICT, ERR_POST_STUDY_TOO_EARLY,
    ERR_STALE_VERSION, ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE,
    ERR_REMOVAL_MIN_AGE_NOT_MET,
)
from helpers import (
    get_segment, get_request, paginated, recompute_signature_count,
    TERMINAL_REQUEST_STATUSES,
)
from store import store, touch
from validate import parse_body, Struct

bp = Blueprint("requests", __name__)

TREATMENT_TYPES = ("SPEED_HUMP", "CHICANE", "SIGNAGE")
STUDY_TYPES = ("INITIAL", "POST_INSTALLATION")
PETITION_WINDOW_DAYS = 90
POST_STUDY_SETTLING_DAYS = 30
REMOVAL_MIN_AGE_DAYS = 365


# ---------------------------------------------------------------- requests
@bp.post("/api/requests")
@require_roles("Resident")
def create_request():
    data, perr = parse_body()
    s = Struct(data, perr)
    segment_id = s.get_str("street_segment_id")
    title = s.get_str("title")
    budget = s.get_int("requested_budget_cents", min=1)
    # Tier 3: body FK existence
    seg = get_segment(segment_id) if segment_id is not None else None
    # Tier 8 structural
    s.raise_if_errors()
    resident = g.resident
    # PRD §3.2 gate order: household fronts the segment, program eligibility,
    # then one-live-request capacity.
    if resident["street_segment_id"] != segment_id:
        raise ApiError(422, ERR_HOUSEHOLD_NOT_ON_SEGMENT,
                       "The acting resident's household does not front this segment")
    if seg["functional_class"] == "ARTERIAL":
        raise ApiError(422, ERR_SEGMENT_NOT_ELIGIBLE,
                       "Traffic calming requests are not accepted for ARTERIAL segments")
    for r in store.requests.values():
        if r["street_segment_id"] == segment_id and r["status"] not in TERMINAL_REQUEST_STATUSES:
            raise ApiError(409, ERR_ACTIVE_REQUEST_EXISTS,
                           "Another non-terminal request already exists for this segment")
    req = {
        "id": store.new_id(),
        "street_segment_id": segment_id,
        "created_by_resident_id": g.user_id,
        "title": title,
        "requested_budget_cents": budget,
        "status": "SUBMITTED",
        "petition_opened_at": None,
        "petition_deadline_at": None,
        "required_signatures": None,
        "signature_count": None,
        "certified_score": None,
        "funding_cycle_id": None,
        "citywide_rank": None,
        "allocated_cents": 0,
        "installed_at": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
        "_ranked_cycle_id": None,
    }
    store.requests[req["id"]] = req
    return object_response(req, 201)


@bp.get("/api/requests/<reqId>")
@require_roles(*ALL_ROLES)
def get_one(reqId):
    return object_response(get_request(reqId))


@bp.get("/api/requests")
@require_roles(*ALL_ROLES)
def list_requests():
    return paginated(list(store.requests.values()), {
        "street_segment_id": request.args.get("street_segment_id"),
        "created_by_resident_id": request.args.get("created_by_resident_id"),
        "status": request.args.get("status"),
        "funding_cycle_id": request.args.get("funding_cycle_id"),
    })


@bp.post("/api/requests/<reqId>/open-petition")
@require_roles("TrafficEngineer")
def open_petition(reqId):
    req = get_request(reqId)
    if req["status"] != "SUBMITTED":
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "Petition can only be opened on a SUBMITTED request")
    seg = store.segments[req["street_segment_id"]]
    req["petition_opened_at"] = store.now
    req["petition_deadline_at"] = store.now + timedelta(days=PETITION_WINDOW_DAYS)
    req["required_signatures"] = required_signatures(seg["household_count"])
    req["signature_count"] = 0
    req["status"] = "PETITION_OPEN"
    touch(req)
    return object_response(req)


# ------------------------------------------------------- petition signatures
@bp.post("/api/requests/<rid>/petition-signatures")
@require_roles("Resident")
def sign_petition(rid):
    req = get_request(rid)
    if req["status"] != "PETITION_OPEN":
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "Petition is not open for this request")
    resident = g.resident
    if resident["street_segment_id"] != req["street_segment_id"]:
        raise ApiError(422, ERR_HOUSEHOLD_NOT_ON_SEGMENT,
                       "The signer's household does not front the request's segment")
    for s in store.signatures.values():
        if s["request_id"] == rid and s["household_ref"] == resident["household_ref"]:
            raise ApiError(409, ERR_DUPLICATE_HOUSEHOLD_SIGNATURE,
                           "A live signature for this household already exists on this request")
    sig = {
        "id": store.new_id(),
        "request_id": rid,
        "resident_id": g.user_id,
        "household_ref": resident["household_ref"],
        "signed_at": store.now,
        "created_at": store.now,
        "_seq": store.next_seq(),
    }
    store.signatures[sig["id"]] = sig
    recompute_signature_count(req)
    # Inclusive boundary: count exactly equal to the requirement flips the stage.
    if req["signature_count"] >= req["required_signatures"]:
        req["status"] = "PETITION_MET"
    touch(req)
    return object_response(sig, 201)


@bp.get("/api/requests/<rid>/petition-signatures")
@require_roles(*ALL_ROLES)
def list_signatures(rid):
    get_request(rid)
    items = [s for s in store.signatures.values() if s["request_id"] == rid]
    return paginated(items)


# ------------------------------------------------------------- speed studies
@bp.post("/api/requests/<reqId>/speed-studies")
@require_roles("TrafficEngineer")
def commission_study(reqId):
    req = get_request(reqId)
    data, perr = parse_body()
    s = Struct(data, perr)
    study_type = s.get_enum("study_type", STUDY_TYPES)
    win_start = s.get_date("window_start_date")
    win_end = s.get_date("window_end_date")
    if win_start is not None and win_end is not None and win_end < win_start:
        s.errors.append("window_end_date must not be before window_start_date")
    # Tier 5: request stage gate depends on study type
    if study_type == "INITIAL":
        if req["status"] != "PETITION_MET":
            raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                           "An INITIAL study requires a PETITION_MET request")
    elif study_type == "POST_INSTALLATION":
        if req["status"] != "INSTALLED":
            raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                           "A POST_INSTALLATION study requires an INSTALLED request")
        # Tier 7: thirty-day settling period against the logical clock
        if store.now < req["installed_at"] + timedelta(days=POST_STUDY_SETTLING_DAYS):
            raise ApiError(409, ERR_POST_STUDY_TOO_EARLY,
                           "Post-installation study attempted before installed_at + 30 days")
    # Tier 8: structural
    s.raise_if_errors()
    # Tier 8: buffered window conflict against every study on the segment
    segment_id = req["street_segment_id"]
    existing = [st for st in store.studies.values()
                if store.requests[st["request_id"]]["street_segment_id"] == segment_id
                and st["status"] in ("COLLECTING", "ANALYZED", "CERTIFIED")]
    if study_window_conflicts(win_start, win_end, existing):
        raise ApiError(409, ERR_STUDY_WINDOW_CONFLICT,
                       "Study window violates the 7-day inclusive buffer on this segment")
    baseline_p85 = None
    baseline_mean = None
    if study_type == "POST_INSTALLATION":
        for st in store.studies.values():
            if st["request_id"] == reqId and st["study_type"] == "INITIAL" \
                    and st["status"] == "CERTIFIED":
                baseline_p85 = st["certified_p85_mph"]
                baseline_mean = st["certified_mean_speed_mph"]
                break
    study = {
        "id": store.new_id(),
        "request_id": reqId,
        "study_type": study_type,
        "window_start_date": win_start,
        "window_end_date": win_end,
        "status": "COLLECTING",
        "observation_count": 0,
        "valid_observation_count": 0,
        "provisional_p85_mph": None,
        "provisional_mean_speed_mph": None,
        "provisional_avg_daily_volume": None,
        "provisional_score": None,
        "certified_p85_mph": None,
        "certified_mean_speed_mph": None,
        "certified_avg_daily_volume": None,
        "certified_score": None,
        "baseline_p85_mph": baseline_p85,
        "baseline_mean_speed_mph": baseline_mean,
        "p85_reduction_mph": None,
        "mean_reduction_mph": None,
        "meets_effectiveness_target": None,
        "meets_target_mean_variant": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.studies[study["id"]] = study
    if study_type == "INITIAL":
        req["status"] = "STUDY_IN_PROGRESS"
    else:
        req["status"] = "POST_STUDY_IN_PROGRESS"
    touch(req)
    return object_response(study, 201)


# ------------------------------------------------------------ treatment plans
@bp.post("/api/requests/<reqId>/treatment-plans")
@require_roles("TrafficEngineer")
def create_plan(reqId):
    req = get_request(reqId)
    data, perr = parse_body()
    s = Struct(data, perr)
    ttype = s.get_enum("treatment_type", TREATMENT_TYPES)
    cost = s.get_int("estimated_cost_cents", min=1)
    expected = s.get_int("expected_request_version")
    # Tier 4: OCC on the request version (PRD §2.7)
    if expected is not None and expected != req["version"]:
        raise ApiError(412, ERR_STALE_VERSION,
                       "expected_request_version does not match the request's current version")
    # Tier 5: stage gate
    if req["status"] not in ("FUNDED", "DESIGN_IN_PROGRESS"):
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "Treatment plans require a FUNDED or DESIGN_IN_PROGRESS request")
    # Tier 6: emergency-route safety gate
    seg = store.segments[req["street_segment_id"]]
    if ttype in ("SPEED_HUMP", "CHICANE") and seg["emergency_route"]:
        raise ApiError(422, ERR_TREATMENT_PROHIBITED_ON_EMERGENCY_ROUTE,
                       "Only SIGNAGE is permitted on a designated emergency route")
    # Tier 8: structural
    s.raise_if_errors()
    # Supersede any existing draft-stage plan (PRD §3.5)
    for p in store.plans.values():
        if p["request_id"] == reqId and p["status"] in (
                "DRAFT", "SUBMITTED_FOR_REVIEW", "REVISION_REQUESTED"):
            p["status"] = "WITHDRAWN"
            touch(p)
    plan = {
        "id": store.new_id(),
        "request_id": reqId,
        "treatment_type": ttype,
        "estimated_cost_cents": cost,
        "created_by_user_id": g.user_id,
        "status": "DRAFT",
        "approved_by_user_id": None,
        "submitted_at": None,
        "approved_at": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.plans[plan["id"]] = plan
    req["status"] = "DESIGN_IN_PROGRESS"
    touch(req)  # exactly one version increment for the whole act (PRD §3.5)
    return object_response(plan, 201)


# ------------------------------------------------------------------- ballots
@bp.post("/api/requests/<reqId>/ballots")
@require_roles("TrafficEngineer")
def create_ballot(reqId):
    req = get_request(reqId)
    data, perr = parse_body()
    s = Struct(data, perr)
    close_date = s.get_datetime("close_date")
    if req["status"] != "BALLOT_READY":
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "A ballot can only be opened on a BALLOT_READY request")
    s.raise_if_errors()
    seg = store.segments[req["street_segment_id"]]
    approved = None
    for p in store.plans.values():
        if p["request_id"] == reqId and p["status"] == "APPROVED":
            approved = p
            break
    ballot = {
        "id": store.new_id(),
        "request_id": reqId,
        "treatment_plan_id": approved["id"] if approved else None,
        "close_date": close_date,
        "eligible_households": seg["household_count"],
        "quorum_required": quorum_required(seg["household_count"]),
        "votes_received": 0,
        "votes_for": 0,
        "votes_against": 0,
        "status": "OPEN",
        "outcome": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.ballots[ballot["id"]] = ballot
    # The approved plan locks in the same act (PRD §3.6)
    if approved is not None:
        approved["status"] = "LOCKED"
        touch(approved)
    req["status"] = "BALLOT_OPEN"
    touch(req)
    return object_response(ballot, 201)


# --------------------------------------------------------- installation orders
@bp.post("/api/requests/<reqId>/installation-work-orders")
@require_roles("TrafficEngineer")
def create_work_order(reqId):
    req = get_request(reqId)
    data, perr = parse_body()
    s = Struct(data, perr)
    crew_ref = s.get_str("crew_ref")
    if req["status"] != "CONSENT_GRANTED":
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "A work order requires a CONSENT_GRANTED request")
    s.raise_if_errors()
    wo = {
        "id": store.new_id(),
        "request_id": reqId,
        "crew_ref": crew_ref,
        "scheduled_date": None,
        "duration_days": None,
        "schedule_status": "UNSCHEDULED",
        "emergency_review_status": "PENDING_REVIEW",
        "reviewed_by_user_id": None,
        "installed_at": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.work_orders[wo["id"]] = wo
    req["status"] = "INSTALLATION_PLANNED"
    touch(req)
    return object_response(wo, 201)


# ----------------------------------------------------------- removal requests
@bp.post("/api/requests/<reqId>/removal-requests")
@require_roles("Resident")
def create_removal(reqId):
    req = get_request(reqId)
    data, perr = parse_body()
    s = Struct(data, perr)
    reason = s.get_str("reason")
    if req["status"] != "EFFECTIVENESS_CERTIFIED":
        raise ApiError(409, ERR_REQUEST_INVALID_STATE,
                       "A removal request requires an EFFECTIVENESS_CERTIFIED request")
    # Tier 7: one-year minimum age against the logical clock
    if store.now < req["installed_at"] + timedelta(days=REMOVAL_MIN_AGE_DAYS):
        raise ApiError(409, ERR_REMOVAL_MIN_AGE_NOT_MET,
                       "Removal requested before installed_at + 365 days")
    s.raise_if_errors()
    rem = {
        "id": store.new_id(),
        "request_id": reqId,
        "created_by_resident_id": g.user_id,
        "reason": reason,
        "status": "PENDING_REVIEW",
        "decided_by_user_id": None,
        "created_at": store.now,
        "updated_at": store.now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.removals[rem["id"]] = rem
    req["status"] = "REMOVAL_REVIEW"
    touch(req)
    return object_response(rem, 201)
