"""Committee sessions, decisions, and votes (quorum, recusal, remand)."""
from flask import Blueprint, g

import serialize
from db import STORE, new_entity, touch, now_dt, now_iso
from errors import (
    raise_err, ERR_VALIDATION, ERR_STALE_VERSION, ERR_INVALID_STATE,
    ERR_COMMITTEE_SESSION_CONFLICT, ERR_COMMITTEE_SESSION_NOT_OPEN,
    ERR_DECISION_ALREADY_OPEN, ERR_DUPLICATE_VOTE, ERR_ONLY_CHAIR_MAY_REMAND,
    ERR_SESSION_LEVEL_MISMATCH, ERR_SOD_COMMITTEE_RECUSAL,
)
from middleware import require_roles, ALL_ROLES
from response import success_object
from routes.common import get_or_404, render_list, body_fk_exists
from services import exposure, policy
from validation import get_body, req_str, req_int, req_enum, req_datetime

bp = Blueprint("committee", __name__)

LEVELS = {"SMALL", "STANDARD", "LARGE"}
# level -> (committee size, votes_required, decline_threshold)
QUORUM = {
    "SMALL": (2, 2, 1),
    "STANDARD": (3, 2, 2),
    "LARGE": (5, 4, 2),
}
TIER_SMALL_CAP_CENTS = 100000000        # $1,000,000.00 inclusive
TIER_STANDARD_CAP_CENTS = 1000000000    # $10,000,000.00 inclusive
VOTES = {"APPROVE", "DECLINE", "REMAND"}


def compute_level_required(app, borrower):
    proposed = app['proposed_amount_cents'] or 0
    if proposed <= TIER_SMALL_CAP_CENTS:
        level = "SMALL"
    elif proposed <= TIER_STANDARD_CAP_CENTS:
        level = "STANDARD"
    else:
        level = "LARGE"
    if borrower['is_reg_o_insider'] or policy.any_high_exception_open_or_waived(app['id']):
        level = {"SMALL": "STANDARD", "STANDARD": "LARGE", "LARGE": "LARGE"}[level]
    return level


@bp.post("/credit/committee-sessions")
def create_session():
    require_roles("CommitteeChair")
    body = get_body()
    level = req_enum(body, "level", LEVELS)
    starts_at = req_datetime(body, "starts_at")
    ends_at = req_datetime(body, "ends_at")
    if not ends_at > starts_at:
        raise_err(ERR_VALIDATION, "ends_at must be strictly after starts_at.")

    # Half-open interval overlap against SCHEDULED sessions; back-to-back allowed.
    from db import format_dt
    for existing in STORE.committee_sessions.values():
        if existing['status'] != 'SCHEDULED':
            continue
        ex_start = existing['_starts_at_dt']
        ex_end = existing['_ends_at_dt']
        if ex_start < ends_at and starts_at < ex_end:
            raise_err(ERR_COMMITTEE_SESSION_CONFLICT,
                      "Session window overlaps an existing SCHEDULED session.")

    session = new_entity()
    session.update({
        'level': level,
        'starts_at': body['starts_at'],
        'ends_at': body['ends_at'],
        '_starts_at_dt': starts_at,
        '_ends_at_dt': ends_at,
        'status': 'SCHEDULED',
    })
    STORE.committee_sessions[session['id']] = session
    return success_object(serialize.committee_session(session), status=201)


@bp.get("/credit/committee-sessions/<sid>")
def get_session(sid):
    require_roles(*ALL_ROLES)
    session = get_or_404(STORE.committee_sessions, sid, "CommitteeSession")
    return success_object(serialize.committee_session(session))


@bp.get("/credit/committee-sessions/<sid>/committee-decisions")
def session_decisions(sid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.committee_sessions, sid, "CommitteeSession")
    items = [d for d in STORE.committee_decisions.values() if d['committee_session_id'] == sid]
    return render_list(items, serialize.committee_decision)


@bp.post("/credit/committee-decisions")
def open_decision():
    require_roles("CommitteeChair")
    body = get_body()
    app_id = req_str(body, "loan_application_id")
    session_id = req_str(body, "committee_session_id")
    expected_version = req_int(body, "expected_loan_application_version")
    body_fk_exists(STORE.loan_applications, app_id, "LoanApplication")
    body_fk_exists(STORE.committee_sessions, session_id, "CommitteeSession")

    app = STORE.loan_applications[app_id]
    session = STORE.committee_sessions[session_id]

    # Stage 5: optimistic concurrency on the application version.
    if expected_version != app['version']:
        raise_err(ERR_STALE_VERSION,
                  "expected_loan_application_version %s does not match current application version %s."
                  % (expected_version, app['version']))
    # Stage 6: state legality.
    if app['status'] != 'COMMITTEE_REVIEW':
        raise_err(ERR_INVALID_STATE, "Application status is %s; opening a decision requires COMMITTEE_REVIEW." % app['status'])
    # Priority 21: at most one OPEN decision per application.
    if any(d['status'] == 'OPEN' for d in exposure.decisions_of_app(app_id)):
        raise_err(ERR_DECISION_ALREADY_OPEN, "An OPEN committee decision already exists for this application.")

    borrower = get_or_404(STORE.borrowers, app['borrower_id'], "Borrower")
    level_required = compute_level_required(app, borrower)
    # Priority 24: session level must equal the computed level.
    if session['level'] != level_required:
        raise_err(ERR_SESSION_LEVEL_MISMATCH,
                  "Session level %s does not match the decision's computed level_required %s."
                  % (session['level'], level_required))

    _, votes_required, _ = QUORUM[level_required]
    decision = new_entity()
    decision.update({
        'loan_application_id': app_id,
        'committee_session_id': session_id,
        'level_required': level_required,
        'votes_required': votes_required,
        'votes': [],
        'votes_for': 0,
        'votes_against': 0,
        'chair_approved': False,
        'status': 'OPEN',
    })
    STORE.committee_decisions[decision['id']] = decision

    app['committee_level_required'] = level_required
    touch(app)
    return success_object(serialize.committee_decision(decision), status=201)


@bp.get("/credit/loan-applications/<aid>/committee-decisions")
def application_decisions(aid):
    require_roles(*ALL_ROLES)
    get_or_404(STORE.loan_applications, aid, "LoanApplication")
    return render_list(exposure.decisions_of_app(aid), serialize.committee_decision)


@bp.post("/credit/committee-decisions/<did>/votes")
def cast_vote(did):
    require_roles("CommitteeMember", "CommitteeChair")
    decision = get_or_404(STORE.committee_decisions, did, "CommitteeDecision")
    body = get_body()
    vote = req_enum(body, "vote", VOTES)

    app = get_or_404(STORE.loan_applications, decision['loan_application_id'], "LoanApplication")
    # State legality: decision OPEN and application still under committee review.
    if decision['status'] != 'OPEN' or app['status'] != 'COMMITTEE_REVIEW':
        raise_err(ERR_INVALID_STATE,
                  "Decision status is %s; votes require an OPEN decision on an application in COMMITTEE_REVIEW."
                  % decision['status'])
    # Recusal: the originator may not vote.
    if g.user_id == app['originating_officer_id']:
        raise_err(ERR_SOD_COMMITTEE_RECUSAL,
                  "The originating officer is recused from voting on this application.")
    # Duplicate vote.
    if any(v['officer_id'] == g.user_id for v in decision['votes']):
        raise_err(ERR_DUPLICATE_VOTE, "The voting officer has already cast a vote on this decision.")
    # REMAND is chair-only.
    if vote == 'REMAND' and g.user_role != 'CommitteeChair':
        raise_err(ERR_ONLY_CHAIR_MAY_REMAND, "Only a CommitteeChair may cast a REMAND vote.")
    # Session window: clock within [starts_at, ends_at) and session SCHEDULED.
    session = get_or_404(STORE.committee_sessions, decision['committee_session_id'], "CommitteeSession")
    now = now_dt()
    if session['status'] != 'SCHEDULED' or not (session['_starts_at_dt'] <= now < session['_ends_at_dt']):
        raise_err(ERR_COMMITTEE_SESSION_NOT_OPEN,
                  "The committee session is not open for votes at the current logical time.")

    decision['votes'].append({
        'officer_id': g.user_id,
        'vote': vote,
        'cast_at': now_iso(),
    })
    if vote == 'APPROVE':
        decision['votes_for'] += 1
        if g.user_role == 'CommitteeChair':
            decision['chair_approved'] = True
    elif vote == 'DECLINE':
        decision['votes_against'] += 1

    level = decision['level_required']
    _, votes_required, decline_threshold = QUORUM[level]

    # Closure evaluation: REMAND immediate; APPROVE rule before DECLINE rule.
    if vote == 'REMAND':
        decision['status'] = 'REMANDED'
        app['status'] = 'EXCEPTION_REVIEW'
        touch(app)
    elif decision['votes_for'] >= votes_required and (level != 'LARGE' or decision['chair_approved']):
        decision['status'] = 'APPROVED'
        app['status'] = 'TERM_SHEET_NEGOTIATION'
        touch(app)
    elif decision['votes_against'] >= decline_threshold:
        decision['status'] = 'DECLINED'
        app['status'] = 'DECLINED'
        touch(app)
        for appraisal in exposure.appraisals_of_app(app['id']):
            if appraisal['status'] in ('ENGAGED', 'REPORT_RECEIVED'):
                appraisal['status'] = 'CANCELLED'
                touch(appraisal)
    touch(decision)
    return success_object(serialize.committee_decision(decision), status=201)
