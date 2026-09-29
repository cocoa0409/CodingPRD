"""Allocation requests, panel scoring and review closure (PRD 3.7, 3.8)."""

from flask import Blueprint

from auth import (ALL_ROLES, authenticate, get_agency, get_cycle, get_request,
                  require_agency_self)
from envelope import created, filter_bool, filter_str, ok, paginate
from errors import ApiError
from store import (D, ZERO, base_entity, date_of, db, now_iso, q2,
                   sort_created_asc, today, touch)
from validators import (body, get_id, get_int, get_money, get_str, get_enum)

from services import aggregates, calc

bp = Blueprint("requests", __name__)

PRIORITY_AREAS = ("BASIC_NEEDS", "EDUCATION", "HEALTH", "FINANCIAL_STABILITY")
LIVE_REQUEST_BLOCKERS = (
    "DRAFT",
    "SUBMITTED",
    "UNDER_PANEL_REVIEW",
    "SUSPENDED_REVIEW",
    "PANEL_APPROVED",
    "AWARDED",
    "REPORTING",
    "CLOSED_SATISFIED",
)


# --------------------------------------------------------------------------- #
# reads
# --------------------------------------------------------------------------- #


@bp.get("/allocation-requests/<request_id>")
def read_request(request_id):
    authenticate(ALL_ROLES)
    return ok(get_request(request_id))


@bp.get("/allocation-requests")
def list_requests():
    authenticate(ALL_ROLES)
    rows = list(db.requests.values())
    cycle_id = filter_str("cycle_id")
    agency_id = filter_str("agency_id")
    status = filter_str("status")
    priority_area = filter_str("priority_area")
    if cycle_id is not None:
        rows = [r for r in rows if r["cycle_id"] == cycle_id]
    if agency_id is not None:
        rows = [r for r in rows if r["agency_id"] == agency_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    if priority_area is not None:
        rows = [r for r in rows if r["priority_area"] == priority_area]
    return paginate(sort_created_asc(rows))


@bp.get("/allocation-requests/<request_id>/scores")
def list_request_scores(request_id):
    authenticate(ALL_ROLES)
    get_request(request_id)
    rows = aggregates.request_scores(request_id)
    eligible = filter_bool("eligible")
    if eligible is not None:
        rows = [r for r in rows if r["eligible"] == eligible]
    return paginate(sort_created_asc(rows))


# --------------------------------------------------------------------------- #
# request lifecycle
# --------------------------------------------------------------------------- #


@bp.post("/allocation-requests")
def draft_request():
    role, user_id = authenticate(
        ("UnitedFundAdmin", "AgencyRepresentative", "AllocationsDirector")
    )
    data = body()
    cycle_id = get_id(data, "cycle_id")
    agency_id = get_id(data, "agency_id")
    requested_amount = get_money(data, "requested_amount", exclusive_min=0)
    priority_area = get_enum(data, "priority_area", PRIORITY_AREAS)
    narrative = get_str(data, "narrative_summary", min_len=1, max_len=2000)

    # Body FK resolution order (PRD 2.9): agency before cycle.
    get_agency(agency_id)
    get_cycle(cycle_id)

    if role == "AgencyRepresentative":
        require_agency_self(user_id, agency_id)

    for other in aggregates.cycle_requests(cycle_id):
        if other["agency_id"] == agency_id and other["status"] != "PANEL_DECLINED":
            raise ApiError("ERR_DUPLICATE_REQUEST_FOR_CYCLE")

    row = base_entity()
    row.update({
        "cycle_id": cycle_id,
        "agency_id": agency_id,
        "requested_amount": q2(requested_amount),
        "priority_area": priority_area,
        "narrative_summary": narrative,
        "status": "DRAFT",
        "status_before_suspension": None,
        "eligible_score_count": 0,
        "composite_score": None,
        "base_award": None,
        "designation_offset": None,
        "strategic_supplement": None,
        "total_award": None,
        "submitted_at": None,
        "awarded_at": None,
        "outcome_report_due_date": None,
    })
    db.requests[row["id"]] = row
    return created(row)


@bp.post("/allocation-requests/<request_id>/submit")
def submit_request(request_id):
    role, user_id = authenticate(("UnitedFundAdmin", "AgencyRepresentative"))
    body()
    req = get_request(request_id)
    if role == "AgencyRepresentative":
        require_agency_self(user_id, req["agency_id"])

    cycle = db.cycles[req["cycle_id"]]
    agency = db.agencies[req["agency_id"]]
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if cycle["posture"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    if req["status"] != "DRAFT":
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    if agency["membership_status"] != "GOOD_STANDING":
        raise ApiError("ERR_AGENCY_NOT_IN_GOOD_STANDING")
    if agency["outcome_report_delinquent"]:
        raise ApiError("ERR_OUTCOME_REPORT_DELINQUENT")

    clock_date = today()
    window_start = date_of(cycle["request_window_start"])
    window_end = date_of(cycle["request_window_end"])
    if not (window_start <= clock_date < window_end):
        raise ApiError("ERR_REQUEST_WINDOW_CLOSED")

    ceiling = D(cycle["max_award_per_agency"]) * calc.REQUEST_CAP_MULTIPLE
    if D(req["requested_amount"]) > ceiling:
        raise ApiError("ERR_AWARD_EXCEEDS_AGENCY_CAP")

    req["status"] = "SUBMITTED"
    req["submitted_at"] = now_iso()
    touch("request", req)
    aggregates.recompute_cycle_counts(cycle)
    return ok(req)


@bp.post("/allocation-requests/<request_id>/scores")
def file_score(request_id):
    role, user_id = authenticate(("VolunteerPanelist",))
    data = body()
    priority_alignment = get_int(
        data, "priority_alignment_score", minimum=0, maximum=100
    )
    outcome_evidence = get_int(data, "outcome_evidence_score", minimum=0, maximum=100)
    capacity = get_int(data, "capacity_score", minimum=0, maximum=100)

    req = get_request(request_id)
    cycle = db.cycles[req["cycle_id"]]
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if cycle["posture"] != "OPEN":
        raise ApiError("ERR_CYCLE_NOT_OPEN")
    if req["status"] not in ("SUBMITTED", "UNDER_PANEL_REVIEW"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    seat = aggregates.assignment_for(req["cycle_id"], user_id)
    # Gate 22 precedes gate 34 (PRD 2.10).
    if seat is not None and seat["conflict_declared"]:
        raise ApiError("ERR_PANELIST_CONFLICT_DECLARED")
    if seat is None:
        raise ApiError("ERR_PANELIST_NOT_ASSIGNED")
    for other in aggregates.request_scores(request_id):
        if other["panelist_id"] == user_id:
            raise ApiError("ERR_DUPLICATE_PANEL_SCORE")

    score = base_entity()
    score.update({
        "request_id": request_id,
        "panelist_id": user_id,
        "priority_alignment_score": priority_alignment,
        "outcome_evidence_score": outcome_evidence,
        "capacity_score": capacity,
        "weighted_score": calc.weighted_score(
            priority_alignment, outcome_evidence, capacity
        ),
        "eligible": True,
    })
    db.scores[score["id"]] = score

    if req["status"] == "SUBMITTED":
        req["status"] = "UNDER_PANEL_REVIEW"
    aggregates.recompute_eligible_score_count(req)
    touch("request", req)
    aggregates.recompute_panelist_counters(db.panelists[user_id])
    aggregates.recompute_assignment_score_count(seat)
    return created(score)


@bp.post("/allocation-requests/<request_id>/finalize-review")
def finalize_review(request_id):
    authenticate(("UnitedFundAdmin", "AllocationsDirector"))
    body()
    req = get_request(request_id)
    cycle = db.cycles[req["cycle_id"]]
    if cycle["posture"] == "FROZEN":
        raise ApiError("ERR_CYCLE_FROZEN")
    if req["status"] not in ("SUBMITTED", "UNDER_PANEL_REVIEW"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")

    pool = aggregates.eligible_score_pool(req)
    if not pool:
        raise ApiError("ERR_NO_ELIGIBLE_SCORES")
    if len(pool) < calc.PANEL_QUORUM:
        raise ApiError("ERR_PANEL_QUORUM_NOT_MET")

    req["eligible_score_count"] = len(pool)
    survivors, dropped = calc.select_trimmed(pool)
    for row in dropped:
        row["eligible"] = False
        touch("score", row)

    focus_match = req["priority_area"] == cycle["focus_priority_area"]
    composite = calc.composite_score(survivors, focus_match)
    req["composite_score"] = composite
    if composite >= calc.PANEL_APPROVAL_THRESHOLD:
        req["status"] = "PANEL_APPROVED"
    else:
        req["status"] = "PANEL_DECLINED"
    touch("request", req)
    return ok(req)


@bp.post("/allocation-requests/<request_id>/rescind-award")
def rescind_award(request_id):
    authenticate(("AllocationsDirector",))
    data = body()
    get_str(data, "reason_code", min_len=1)

    req = get_request(request_id)
    if req["status"] not in ("AWARDED", "REPORTING"):
        raise ApiError("ERR_REQUEST_INVALID_STATE")
    if aggregates.request_reports(request_id):
        raise ApiError("ERR_AWARD_ALREADY_REPORTED")

    req["status"] = "PANEL_APPROVED"
    req["base_award"] = None
    req["designation_offset"] = None
    req["strategic_supplement"] = None
    req["total_award"] = None
    req["awarded_at"] = None
    req["outcome_report_due_date"] = None
    touch("request", req)
    aggregates.recompute_cycle_pool(db.cycles[req["cycle_id"]])
    return ok(req)
