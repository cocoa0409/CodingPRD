"""Engagements: agreements, delivery, review, handoff, valuation, feedback.

PRD 3.6 - 3.9.  Every handler calls the ladder guards of `guards.py` in
ascending priority order, so the global rejection precedence is visible in the
call sequence itself.
"""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, request as flask_request

import calc
import config as C
import domain
import guards as G
import response as R
import serialize as Z
import store as S
from calc import dec, rnd
from errors import ApiError
from guards import route

bp = Blueprint("engagements", __name__)

ALL_FIVE = [
    C.ROLE_PROGRAM_MANAGER,
    C.ROLE_SCOPING_SPECIALIST,
    C.ROLE_VOLUNTEER,
    C.ROLE_PARTNER_CONTACT,
    C.ROLE_QUALITY_REVIEWER,
]
PM_V_PC = [C.ROLE_PROGRAM_MANAGER, C.ROLE_VOLUNTEER, C.ROLE_PARTNER_CONTACT]
PM_V = [C.ROLE_PROGRAM_MANAGER, C.ROLE_VOLUNTEER]
V_PC = [C.ROLE_VOLUNTEER, C.ROLE_PARTNER_CONTACT]

ENGAGEMENT_FILTERS = (
    "project_request_id",
    "volunteer_id",
    "cycle_id",
    "scope_definition_id",
    "availability_window_id",
    "match_offer_id",
    "work_status",
    "valuation_status",
    "quality_gate",
)


def _party():
    return "VOLUNTEER" if G.role() == C.ROLE_VOLUNTEER else "PARTNER"


def _pinned(engagement):
    return S.get("scope_definitions", engagement["scope_definition_id"])


def _window(engagement):
    return S.get("availability_windows", engagement["availability_window_id"])


def _partner(engagement):
    req = S.get("project_requests", engagement["project_request_id"])
    if req is None:
        return None
    return S.get("partner_orgs", req["partner_org_id"])


# --------------------------------------------------------------------------- #
# engagement reads
# --------------------------------------------------------------------------- #
@route(bp, "/engagements/<engagement_id>", ["GET"], ALL_FIVE)
def get_engagement(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    return R.ok(Z.engagement(engagement))


@route(bp, "/engagements", ["GET"], ALL_FIVE)
def list_engagements():
    rows = S.all_rows("engagements")
    for key in ENGAGEMENT_FILTERS:
        value = flask_request.args.get(key)
        if value:
            rows = [r for r in rows if r[key] == value]
    return R.paginate(rows, Z.engagement)


# --------------------------------------------------------------------------- #
# agreements (PRD 3.6)
# --------------------------------------------------------------------------- #
@route(
    bp, "/engagements/<engagement_id>/agreements", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def create_agreement(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    scope = _pinned(engagement)
    payload = G.body()
    expected_version = G.v_int(payload, "expected_engagement_version", minimum=0)
    ip_disposition = G.v_enum(
        payload,
        "ip_disposition",
        C.IP_DISPOSITIONS,
        required=False,
        default=None if scope is None else scope["ip_disposition"],
    )
    confidentiality_tier = G.v_enum(
        payload,
        "confidentiality_tier",
        C.CONFIDENTIALITY_TIERS,
        required=False,
        default=None if scope is None else scope["confidentiality_tier"],
    )
    indemnity_cap = G.v_num(
        payload, "indemnity_cap_usd", minimum=0, maximum="100000.00", places=2
    )
    G.g30_engagement_version(engagement, expected_version)

    for prior in S.where("agreements", engagement_id=engagement["id"]):
        if prior["status"] in ("DRAFTED", "SENT", "COUNTERED"):
            prior["status"] = "VOIDED"
            prior["void_reason"] = "TERMS_REJECTED"
            S.touch(prior)

    row = S.insert(
        "agreements",
        {
            "engagement_id": engagement["id"],
            "ip_disposition": ip_disposition,
            "confidentiality_tier": confidentiality_tier,
            "indemnity_cap_usd": indemnity_cap,
            "counter_round": 0,
            "terms_revision_no": 1,
            "last_countered_by": None,
            "volunteer_signed_at": None,
            "partner_signed_at": None,
            "status": "DRAFTED",
            "void_reason": None,
        },
    )
    S.touch(engagement)
    return R.created(Z.agreement(row))


@route(bp, "/engagements/<engagement_id>/agreements", ["GET"], PM_V_PC)
def list_agreements(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("agreements", engagement_id=engagement["id"])
    rows.sort(key=S.order_key, reverse=True)
    return R.paginate(rows, Z.agreement)


@route(bp, "/agreements/<agreement_id>/send", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def send_agreement(agreement_id):
    agreement = G.g10_agreement(agreement_id)
    engagement = S.get("engagements", agreement["engagement_id"])
    G.g23_work_state(engagement, ("NOT_STARTED",))
    G.g25_agreement_state(agreement, ("DRAFTED", "COUNTERED"))
    if int(agreement["counter_round"]) > C.MAX_COUNTER_ROUNDS:
        raise ApiError("ERR_COUNTER_LIMIT_EXCEEDED")
    G.g49_scope_approved(_pinned(engagement))
    agreement["status"] = "SENT"
    agreement["volunteer_signed_at"] = None
    agreement["partner_signed_at"] = None
    S.touch(agreement)
    return R.ok(Z.agreement(agreement))


@route(bp, "/agreements/<agreement_id>/counter", ["POST"], V_PC)
def counter_agreement(agreement_id):
    agreement = G.g10_agreement(agreement_id)
    engagement = S.get("engagements", agreement["engagement_id"])
    G.g15_owns_engagement(engagement)
    payload = G.body()
    ip_disposition = G.v_enum(payload, "ip_disposition", C.IP_DISPOSITIONS)
    confidentiality_tier = G.v_enum(
        payload, "confidentiality_tier", C.CONFIDENTIALITY_TIERS
    )
    indemnity_cap = G.v_num(
        payload, "indemnity_cap_usd", minimum=0, maximum="100000.00", places=2
    )
    G.g25_agreement_state(agreement, ("SENT",))
    party = _party()
    if not G.g37_counter_limit(agreement, party):
        # the allowance is spent: the document dies and the engagement with it
        agreement["status"] = "VOIDED"
        agreement["void_reason"] = "COUNTER_LIMIT_EXCEEDED"
        S.touch(agreement)
        domain.terminate_engagement(engagement, "AGREEMENT_VOIDED")
        raise ApiError("ERR_COUNTER_LIMIT_EXCEEDED")

    agreement["status"] = "COUNTERED"
    agreement["counter_round"] = int(agreement["counter_round"]) + 1
    agreement["terms_revision_no"] = int(agreement["counter_round"]) + 1
    agreement["ip_disposition"] = ip_disposition
    agreement["confidentiality_tier"] = confidentiality_tier
    agreement["indemnity_cap_usd"] = indemnity_cap
    agreement["volunteer_signed_at"] = None
    agreement["partner_signed_at"] = None
    agreement["last_countered_by"] = party
    S.touch(agreement)
    return R.ok(Z.agreement(agreement))


@route(bp, "/agreements/<agreement_id>/execute", ["POST"], V_PC)
def execute_agreement(agreement_id):
    agreement = G.g10_agreement(agreement_id)
    engagement = S.get("engagements", agreement["engagement_id"])
    G.g15_owns_engagement(engagement)
    G.g25_agreement_state(agreement, ("SENT",))
    party = _party()
    own = "volunteer_signed_at" if party == "VOLUNTEER" else "partner_signed_at"
    other = "partner_signed_at" if party == "VOLUNTEER" else "volunteer_signed_at"
    if agreement[own] is not None:
        raise ApiError(
            "ERR_INVALID_AGREEMENT_STATE", "this party has already signed"
        )
    G.g35_ip_terms(agreement, _pinned(engagement))
    agreement[own] = S.now()
    if agreement[other] is not None:
        agreement["status"] = "EXECUTED"
    S.touch(agreement)
    return R.ok(Z.agreement(agreement))


@route(bp, "/agreements/<agreement_id>/void", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def void_agreement(agreement_id):
    agreement = G.g10_agreement(agreement_id)
    engagement = S.get("engagements", agreement["engagement_id"])
    payload = G.body()
    G.v_enum(payload, "void_reason", C.AGREEMENT_VOID_REASONS, required=False)
    G.g25_agreement_state(agreement, ("DRAFTED", "SENT", "COUNTERED"))
    agreement["status"] = "VOIDED"
    agreement["void_reason"] = "TERMS_REJECTED"
    S.touch(agreement)
    if engagement is not None and engagement["work_status"] in C.LIVE_WORK_STATUSES:
        domain.terminate_engagement(engagement, "AGREEMENT_VOIDED")
    return R.ok(Z.agreement(agreement))


# --------------------------------------------------------------------------- #
# delivery (PRD 3.7)
# --------------------------------------------------------------------------- #
@route(bp, "/engagements/<engagement_id>/start", ["POST"], [C.ROLE_VOLUNTEER])
def start_engagement(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    G.g15_owns_engagement(engagement)
    G.g23_work_state(engagement, ("NOT_STARTED",))
    G.g31_partner_not_suspended(_partner(engagement))
    G.g33_volunteer_active(S.get("volunteers", engagement["volunteer_id"]))
    G.g36_agreement_executed(engagement)
    engagement["work_status"] = "IN_PROGRESS"
    S.touch(engagement)
    req = S.get("project_requests", engagement["project_request_id"])
    if req is not None and req["status"] == "ENGAGED":
        req["status"] = "IN_DELIVERY"
        S.touch(req)
    return R.ok(Z.engagement(engagement))


@route(
    bp, "/engagements/<engagement_id>/milestones", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def create_milestone(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    payload = G.body()
    due_at = G.v_dt(payload, "due_at")
    G.g40_milestone_due(engagement, _window(engagement), due_at)
    G.g44_milestone_spacing(engagement["id"], due_at)
    G.g45_checkin_saturation(engagement["volunteer_id"], due_at)
    sequence_no = 1
    for sibling in S.where("milestones", engagement_id=engagement["id"]):
        sequence_no = max(sequence_no, int(sibling["sequence_no"]) + 1)
    row = S.insert(
        "milestones",
        {
            "engagement_id": engagement["id"],
            "sequence_no": sequence_no,
            "due_at": due_at,
            "checkin_status": "SCHEDULED",
            "held_at": None,
            "reported_cumulative_hours": None,
            "variance_hours": None,
            "escalation_raised": False,
            "waiver_reason": None,
        },
    )
    return R.created(Z.milestone(row))


@route(bp, "/engagements/<engagement_id>/milestones", ["GET"], PM_V_PC)
def list_milestones(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("milestones", engagement_id=engagement["id"])
    rows.sort(key=lambda m: (int(m["sequence_no"]), m["created_at"], m["_seq"]))
    return R.paginate(rows, Z.milestone)


@route(bp, "/milestones/<milestone_id>", ["GET"], PM_V_PC)
def get_milestone(milestone_id):
    milestone = G.g11_milestone(milestone_id)
    return R.ok(Z.milestone(milestone))


@route(bp, "/milestones/<milestone_id>/time-logs", ["GET"], PM_V)
def list_milestone_time_logs(milestone_id):
    milestone = G.g11_milestone(milestone_id)
    rows = [
        l
        for l in S.all_rows("time_logs")
        if l["milestone_id"] == milestone["id"]
    ]
    rows.sort(key=lambda l: (l["work_date"], l["created_at"], l["_seq"]))
    return R.paginate(rows, Z.time_log)


@route(bp, "/milestones/<milestone_id>/hold", ["POST"], [C.ROLE_PROGRAM_MANAGER])
def hold_milestone(milestone_id):
    milestone = G.g11_milestone(milestone_id)
    engagement = S.get("engagements", milestone["engagement_id"])
    payload = G.body()
    reported = G.v_num(payload, "reported_cumulative_hours", minimum=0, places=2)
    G.g23_work_state(engagement, ("IN_PROGRESS",))
    G.g26_milestone_scheduled(milestone)
    earliest = milestone["due_at"] - timedelta(hours=C.MILESTONE_GRACE_HOURS)
    if S.now() < earliest:
        raise ApiError("ERR_VALIDATION", "a check-in may be held at most 24h early")

    now = S.now()
    milestone["checkin_status"] = "HELD"
    milestone["held_at"] = now
    milestone["reported_cumulative_hours"] = reported

    for log in S.where("time_logs", engagement_id=engagement["id"]):
        if not log["approved"] and log["work_date"] <= milestone["due_at"]:
            log["approved"] = True
            log["approved_at"] = now
            log["milestone_id"] = milestone["id"]

    approved = calc.approved_hours(engagement)
    pct, level = calc.creep(engagement)
    milestone["variance_hours"] = rnd(dec(reported) - approved, 2)
    milestone["escalation_raised"] = level in ("ESCALATED", "BREACH")
    S.touch(milestone)
    S.touch(engagement)

    if level == "BREACH":
        domain.terminate_engagement(engagement, "SCOPE_BREACH")
        req = S.get("project_requests", engagement["project_request_id"])
        if req is not None and req["status"] == "IN_DELIVERY":
            req["status"] = "RESCOPING"
            domain.supersede_approved_revision(req)
            S.touch(req)
    return R.ok(Z.milestone(milestone))


@route(bp, "/engagements/<engagement_id>/time-logs", ["POST"], [C.ROLE_VOLUNTEER])
def create_time_log(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    G.g15_owns_engagement(engagement)
    payload = G.body()
    work_date = G.v_dt(payload, "work_date")
    hours = G.v_num(payload, "hours", minimum=0, maximum="12.00", places=2)
    activity_class = G.v_enum(payload, "activity_class", C.ACTIVITY_CLASSES)
    G.g19_positive(hours, "hours")
    G.g23_work_state(engagement, ("IN_PROGRESS",))
    volunteer = S.get("volunteers", engagement["volunteer_id"])
    G.g33_volunteer_active(volunteer)
    G.g36_agreement_executed(engagement)
    window = _window(engagement)
    G.g41_log_inside_window(window, work_date)
    G.g55_log_hours(window, hours)
    G.g56_no_breach(engagement)
    row = S.insert(
        "time_logs",
        {
            "engagement_id": engagement["id"],
            "milestone_id": None,
            "work_date": work_date,
            "hours": hours,
            "activity_class": activity_class,
            "rate_basis_usd": rnd(volunteer["professional_rate_usd_per_hour"], 2),
            "approved": False,
            "approved_at": None,
            "logged_by_user_id": G.user_id(),
        },
        versioned=False,
    )
    S.touch(engagement)
    return R.created(Z.time_log(row))


@route(bp, "/engagements/<engagement_id>/time-logs", ["GET"], PM_V_PC)
def list_time_logs(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("time_logs", engagement_id=engagement["id"])
    rows.sort(key=lambda l: (l["work_date"], l["created_at"], l["_seq"]))
    return R.paginate(rows, Z.time_log)


# --------------------------------------------------------------------------- #
# scope change requests
# --------------------------------------------------------------------------- #
def _apply_change(engagement, scr):
    engagement["committed_hours"] = rnd(
        dec(engagement["committed_hours"]) + dec(scr["additional_hours"]), 2
    )
    S.touch(engagement)


@route(bp, "/engagements/<engagement_id>/scope-change-requests", ["POST"], V_PC)
def create_scope_change(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    G.g15_owns_engagement(engagement)
    payload = G.body()
    additional_hours = G.v_num(
        payload, "additional_hours", minimum=0, maximum="200.00", places=2
    )
    additional_deliverable_count = G.v_int(
        payload, "additional_deliverable_count", minimum=0, maximum=10
    )
    justification = G.v_str(payload, "justification", min_len=1, max_len=500)
    G.g23_work_state(engagement, ("IN_PROGRESS",))

    projected = calc.projection(engagement, additional_hours)
    tier = calc.decision_tier(projected, additional_deliverable_count)
    req = S.get("project_requests", engagement["project_request_id"])

    if tier == "RESCOPE_REQUIRED":
        G.g50_rescope_limit(req)
    if tier == "AUTO_APPROVABLE":
        G.g55_window_hours(_window(engagement), additional_hours)

    row = S.insert(
        "scope_change_requests",
        {
            "engagement_id": engagement["id"],
            "requested_by": _party(),
            "additional_hours": additional_hours,
            "additional_deliverable_count": additional_deliverable_count,
            "justification": justification,
            "projected_creep_pct": projected,
            "decision_tier": tier,
            "status": "PENDING",
            "decided_by_user_id": None,
            "decided_at": None,
            "resulting_scope_revision_no": None,
        },
    )

    if tier == "AUTO_APPROVABLE":
        row["status"] = "APPROVED"
        row["decided_by_user_id"] = G.user_id()
        row["decided_at"] = S.now()
        _apply_change(engagement, row)
        S.touch(row)
    elif tier == "RESCOPE_REQUIRED":
        row["status"] = "ESCALATED"
        S.touch(row)
        domain.terminate_engagement(engagement, "SCOPE_BREACH")
        if req is not None and req["status"] == "IN_DELIVERY":
            req["status"] = "RESCOPING"
            req["rescope_count"] = int(req["rescope_count"]) + 1
            domain.supersede_approved_revision(req)
            S.touch(req)
    return R.created(Z.scope_change_request(row))


@route(bp, "/engagements/<engagement_id>/scope-change-requests", ["GET"], PM_V_PC)
def list_scope_changes(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("scope_change_requests", engagement_id=engagement["id"])
    return R.paginate(rows, Z.scope_change_request)


@route(
    bp,
    "/scope-change-requests/<scr_id>/decide",
    ["POST"],
    [C.ROLE_PROGRAM_MANAGER],
)
def decide_scope_change(scr_id):
    scr = G.g12_scope_change(scr_id)
    engagement = S.get("engagements", scr["engagement_id"])
    payload = G.body()
    decision = G.v_enum(payload, "decision", ("APPROVE", "REJECT"))
    G.g28_scope_change_pending(scr)
    if decision == "APPROVE":
        G.g55_window_hours(_window(engagement), scr["additional_hours"])
    scr["decided_by_user_id"] = G.user_id()
    scr["decided_at"] = S.now()
    if decision == "APPROVE":
        scr["status"] = "APPROVED"
        _apply_change(engagement, scr)
    else:
        scr["status"] = "REJECTED"
    S.touch(scr)
    return R.ok(Z.scope_change_request(scr))


# --------------------------------------------------------------------------- #
# submission
# --------------------------------------------------------------------------- #
@route(bp, "/engagements/<engagement_id>/submit", ["POST"], [C.ROLE_VOLUNTEER])
def submit_engagement(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    G.g15_owns_engagement(engagement)
    G.g23_work_state(engagement, ("IN_PROGRESS",))
    G.g33_volunteer_active(S.get("volunteers", engagement["volunteer_id"]))
    G.g56_no_breach(engagement)
    held = [
        m
        for m in S.where("milestones", engagement_id=engagement["id"])
        if m["checkin_status"] == "HELD"
    ]
    if not held:
        raise ApiError(
            "ERR_INVALID_WORK_STATE", "at least one check-in must have been held"
        )
    now = S.now()
    for log in S.where("time_logs", engagement_id=engagement["id"]):
        if not log["approved"]:
            log["approved"] = True
            log["approved_at"] = now
    engagement["work_status"] = "SUBMITTED"
    S.touch(engagement)
    return R.ok(Z.engagement(engagement))


# --------------------------------------------------------------------------- #
# quality review (PRD 3.8)
# --------------------------------------------------------------------------- #
@route(
    bp,
    "/engagements/<engagement_id>/quality-reviews",
    ["POST"],
    [C.ROLE_QUALITY_REVIEWER],
)
def open_quality_review(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    G.g16_review_open(engagement)
    G.g23_work_state(engagement, ("SUBMITTED",))
    rounds = S.where("quality_reviews", engagement_id=engagement["id"])
    if rounds:
        latest = max(rounds, key=lambda r: int(r["round_no"]))
        if latest["status"] != "REWORK_REQUESTED":
            raise ApiError(
                "ERR_REVIEW_NOT_SCORED",
                "a new round opens only after a round returned for rework",
            )
    round_no = 1
    for prior in rounds:
        round_no = max(round_no, int(prior["round_no"]) + 1)
    row = S.insert(
        "quality_reviews",
        {
            "engagement_id": engagement["id"],
            "reviewer_user_id": G.user_id(),
            "round_no": round_no,
            "scored_deliverable_count": 0,
            "weighted_score": None,
            "outcome": "PENDING",
            "status": "OPEN",
            "rework_deadline_at": None,
            "decided_at": None,
        },
    )
    return R.created(Z.quality_review(row))


@route(
    bp,
    "/engagements/<engagement_id>/quality-reviews",
    ["GET"],
    [
        C.ROLE_PROGRAM_MANAGER,
        C.ROLE_QUALITY_REVIEWER,
        C.ROLE_VOLUNTEER,
        C.ROLE_PARTNER_CONTACT,
    ],
)
def list_quality_reviews(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("quality_reviews", engagement_id=engagement["id"])
    rows.sort(key=lambda r: (int(r["round_no"]), r["created_at"], r["_seq"]))
    return R.paginate(rows, Z.quality_review)


@route(
    bp, "/quality-reviews/<review_id>/score", ["POST"], [C.ROLE_QUALITY_REVIEWER]
)
def score_quality_review(review_id):
    review = G.g13_review(review_id)
    engagement = S.get("engagements", review["engagement_id"])
    payload = G.body()
    G.g14_deliverable_ids(engagement["scope_definition_id"], payload)
    G.g16_review_act(review, engagement)
    entries = payload.get("deliverable_scores")
    if not isinstance(entries, list):
        raise ApiError("ERR_VALIDATION", "deliverable_scores must be a list")
    for entry in entries:
        if not isinstance(entry, dict):
            raise ApiError("ERR_VALIDATION", "deliverable_scores entries are objects")
        G.v_id(entry, "deliverable_id")
        G.v_int(entry, "review_score", minimum=0, maximum=5)
    G.g23_work_state(engagement, ("SUBMITTED",))
    G.g27_review_state(review, "OPEN")
    G.g48_deliverable_set(engagement["scope_definition_id"], entries)

    for entry in entries:
        deliverable = S.get("deliverables", entry["deliverable_id"])
        deliverable["review_score"] = entry["review_score"]

    score, outcome = calc.quality_score(engagement["scope_definition_id"])
    active = calc.active_deliverables(engagement["scope_definition_id"])
    review["weighted_score"] = score
    review["outcome"] = outcome
    review["scored_deliverable_count"] = sum(
        1 for d in active if d["review_score"] is not None
    )
    review["status"] = "SCORED"
    S.touch(review)
    return R.ok(Z.quality_review(review))


@route(
    bp, "/quality-reviews/<review_id>/decide", ["POST"], [C.ROLE_QUALITY_REVIEWER]
)
def decide_quality_review(review_id):
    review = G.g13_review(review_id)
    engagement = S.get("engagements", review["engagement_id"])
    G.g16_review_act(review, engagement)
    payload = G.body()
    request_rework = G.v_bool(payload, "request_rework", required=False, default=False)
    G.g23_work_state(engagement, ("SUBMITTED",))
    G.g27_review_state(review, "SCORED")
    if review["outcome"] == "PENDING":
        raise ApiError("ERR_REVIEW_NOT_SCORED", "the outcome is still pending")

    now = S.now()
    active = calc.active_deliverables(engagement["scope_definition_id"])

    if request_rework:
        if review["outcome"] != "CONDITIONAL" or int(review["round_no"]) >= 2:
            raise ApiError(
                "ERR_REVIEW_NOT_SCORED", "rework is unavailable for this round"
            )
        review["status"] = "REWORK_REQUESTED"
        review["decided_at"] = now
        review["rework_deadline_at"] = now + timedelta(
            hours=C.REWORK_DEADLINE_HOURS
        )
        S.touch(review)
        for deliverable in active:
            deliverable["review_score"] = None
            deliverable["review_status"] = "PENDING"
        engagement["work_status"] = "IN_PROGRESS"
        S.touch(engagement)
        return R.ok(Z.quality_review(review))

    review["status"] = "DECIDED"
    review["decided_at"] = now
    S.touch(review)

    if review["outcome"] == "FAIL":
        engagement["quality_gate"] = "FAILED"
        domain.terminate_engagement(engagement, "QUALITY_FAILURE")
        return R.ok(Z.quality_review(review))

    engagement["quality_gate"] = (
        "PASSED" if review["outcome"] == "PASS" else "CONDITIONAL"
    )
    engagement["work_status"] = "ACCEPTED"
    S.touch(engagement)
    for deliverable in active:
        score = deliverable["review_score"]
        deliverable["review_status"] = (
            "ACCEPTED" if score is not None and int(score) >= 3 else "REJECTED"
        )
    return R.ok(Z.quality_review(review))


# --------------------------------------------------------------------------- #
# handoff and termination (PRD 3.8, 3.9)
# --------------------------------------------------------------------------- #
@route(
    bp, "/engagements/<engagement_id>/handoff", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def handoff_engagement(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    payload = G.body()
    attested = G.v_bool(payload, "confidentiality_attested", required=False)
    artifact_count = G.v_int(payload, "handoff_artifact_count", minimum=1)
    certificate = G.v_str(
        payload, "destruction_certificate_ref", required=False, min_len=1, max_len=200
    )
    G.g23_work_state(engagement, ("ACCEPTED",))
    scope = _pinned(engagement)
    G.g34_attestation(scope, attested, certificate)
    G.g35_ip_terms(G.governing_agreement(engagement["id"]), scope)
    G.g49_scope_approved(scope)

    engagement["confidentiality_attested"] = True
    engagement["destruction_certificate_ref"] = certificate
    engagement["handoff_artifact_count"] = artifact_count
    engagement["handoff_at"] = S.now()
    engagement["work_status"] = "HANDED_OFF"
    S.touch(engagement)

    req = S.get("project_requests", engagement["project_request_id"])
    if req is not None and req["status"] == "IN_DELIVERY":
        req["status"] = "CLOSED"
        req["closed_at"] = S.now()
        S.touch(req)
    domain.refresh_reliability(S.get("volunteers", engagement["volunteer_id"]))
    return R.ok(Z.engagement(engagement))


@route(
    bp, "/engagements/<engagement_id>/terminate", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def terminate_engagement_route(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    payload = G.body()
    reason = G.v_enum(
        payload, "termination_reason", C.TERMINATION_REASONS, required=False
    )
    G.g23_work_state(engagement, C.LIVE_WORK_STATUSES)
    if engagement["work_status"] == "ACCEPTED" and engagement["handoff_at"] is not None:
        raise ApiError("ERR_INVALID_WORK_STATE", "the package was already handed off")
    domain.terminate_engagement(engagement, reason or "ADMIN")
    return R.ok(Z.engagement(engagement))


# --------------------------------------------------------------------------- #
# valuation (PRD 3.9)
# --------------------------------------------------------------------------- #
VALUATION_MOVES = {
    ("UNVALUED", "PROVISIONAL"),
    ("PROVISIONAL", "FINAL"),
    ("UNVALUED", "FINAL"),
    # PRD 2.7: "A valuation post stamps `superseded_at` on the prior non-superseded
    # record of the same `method`" -- a same-stage re-post is therefore legitimate and
    # is gated only by the three conditions PRD 2.12 item 24 enumerates.
    ("PROVISIONAL", "PROVISIONAL"),
    ("FINAL", "FINAL"),
}


@route(
    bp, "/engagements/<engagement_id>/valuations", ["POST"], [C.ROLE_PROGRAM_MANAGER]
)
def post_valuation(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    payload = G.body()
    expected_version = G.v_int(payload, "expected_engagement_version", minimum=0)
    method = G.v_enum(payload, "method", C.VALUATION_METHODS)
    stage = G.g24_valuation_stage(engagement)
    current = engagement["valuation_status"]
    if (current, stage) not in VALUATION_MOVES:
        raise ApiError("ERR_INVALID_VALUATION_STATE")
    existing = S.where("valuation_records", engagement_id=engagement["id"])
    if current == "UNVALUED" and stage == "FINAL" and existing:
        raise ApiError("ERR_INVALID_VALUATION_STATE")
    G.g30_engagement_version(engagement, expected_version)

    domain.supersede_records(engagement["id"], method=method)
    volunteer = S.get("volunteers", engagement["volunteer_id"])
    record = domain.post_valuation_record(engagement, volunteer, method, stage)
    engagement["valuation_status"] = stage
    S.touch(engagement)
    return R.created(Z.valuation_record(record))


@route(bp, "/engagements/<engagement_id>/valuation-records", ["GET"], PM_V_PC)
def list_valuation_records(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("valuation_records", engagement_id=engagement["id"])
    return R.paginate(rows, Z.valuation_record)


# --------------------------------------------------------------------------- #
# partner feedback (PRD 3.9)
# --------------------------------------------------------------------------- #
@route(
    bp,
    "/engagements/<engagement_id>/satisfaction-surveys",
    ["POST"],
    [C.ROLE_PARTNER_CONTACT],
)
def create_satisfaction_survey(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    req = S.get("project_requests", engagement["project_request_id"])
    G.g15_owns_partner(req["partner_org_id"])
    payload = G.body()
    expertise = G.v_int(payload, "score_expertise", minimum=1, maximum=5)
    responsiveness = G.v_int(payload, "score_responsiveness", minimum=1, maximum=5)
    deliverable_fit = G.v_int(payload, "score_deliverable_fit", minimum=1, maximum=5)
    would_recommend = G.v_bool(payload, "would_recommend")
    G.g23_work_state(engagement, ("HANDED_OFF", "TERMINATED"))
    partner = S.get("partner_orgs", req["partner_org_id"])
    G.g31_partner_not_suspended(partner)

    row = S.insert(
        "satisfaction_surveys",
        {
            "engagement_id": engagement["id"],
            "partner_org_id": partner["id"],
            "submitted_at": S.now(),
            "score_expertise": expertise,
            "score_responsiveness": responsiveness,
            "score_deliverable_fit": deliverable_fit,
            "would_recommend": would_recommend,
            "composite_score": calc.satisfaction_composite(
                expertise, responsiveness, deliverable_fit
            ),
            "counted_in_index": False,
        },
        versioned=False,
    )
    domain.rebuild_satisfaction(partner)
    return R.created(Z.satisfaction_survey(row))


@route(
    bp,
    "/engagements/<engagement_id>/satisfaction-surveys",
    ["GET"],
    [C.ROLE_PROGRAM_MANAGER, C.ROLE_PARTNER_CONTACT, C.ROLE_VOLUNTEER],
)
def list_engagement_surveys(engagement_id):
    engagement = G.g09_engagement(engagement_id)
    rows = S.where("satisfaction_surveys", engagement_id=engagement["id"])
    rows.sort(key=lambda s: (s["submitted_at"], s["created_at"], s["_seq"]))
    return R.paginate(rows, Z.satisfaction_survey)
