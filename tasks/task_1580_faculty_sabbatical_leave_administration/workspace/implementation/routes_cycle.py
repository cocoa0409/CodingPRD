"""Routes: leave cycles (incl. allocation), leave applications, committee reviews."""
from decimal import Decimal

from flask import request

from db import SEQ, STORE, clock_now, touch
from flask_app import app
from services import (CREDITS_PER_SEMESTER, MIN_CERTIFIED_SERVICE_MONTHS,
                      add_ledger_entry, application_plans, cancel_scheduled_grant,
                      compute_weighted_total, create_grant, department_mutated,
                      faculty_balances, has_active_overlap,
                      recompute_review_aggregates, ser_application, ser_cycle,
                      ser_review)
from util import (D, add_months, auth_context, body_json, fail, new_id, ok,
                  optional_string, paginate, parse_dt, parse_int, require_role,
                  require_string, sort_items, windows_overlap)

PROVOST = {'ProvostOffice'}
FACULTY_ONLY = {'Faculty'}
COMMITTEE = {'CommitteeMember'}
LEAVE_TYPES = {'SABBATICAL', 'MEDICAL', 'PERSONAL', 'PROFESSIONAL'}
IN_FLIGHT = {'DRAFT', 'UNDER_REVIEW', 'REVISION_REQUESTED'}


# ---------------------------------------------------------------------------
# Leave cycles
# ---------------------------------------------------------------------------
@app.route('/leave-cycles', methods=['POST'])
def create_cycle():
    uid, role = auth_context()
    body = body_json()
    name = require_string(body, 'name')
    academic_year = require_string(body, 'academic_year')
    quota = parse_int(body.get('award_quota'))
    if quota is None or quota < 1:
        fail('ERR_INVALID_REQUEST', 'award_quota is required and must be an integer >= 1.')
    require_role(role, PROVOST)
    now = clock_now()
    cycle = {
        'id': new_id(), '_seq': next(SEQ),
        'name': name, 'academic_year': academic_year,
        'award_quota': quota, 'status': 'DRAFT', 'awarded_count': 0,
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['cycles'][cycle['id']] = cycle
    return ok(ser_cycle(cycle), 201)


@app.route('/leave-cycles', methods=['GET'])
def list_cycles():
    auth_context()
    items = sort_items(STORE['cycles'].values())
    status = request.args.get('status')
    if status is not None:
        items = [c for c in items if c['status'] == status]
    page, meta = paginate(items)
    return ok([ser_cycle(c) for c in page], 200, pagination=meta, response_type='array')


@app.route('/leave-cycles/<cid>', methods=['GET'])
def get_cycle(cid):
    auth_context()
    cycle = STORE['cycles'].get(cid)
    if cycle is None:
        fail('ERR_CYCLE_NOT_FOUND')
    return ok(ser_cycle(cycle))


def _cycle_or_404(cid):
    cycle = STORE['cycles'].get(cid)
    if cycle is None:
        fail('ERR_CYCLE_NOT_FOUND')
    return cycle


@app.route('/leave-cycles/<cid>/open', methods=['POST'])
def open_cycle(cid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    cycle = _cycle_or_404(cid)
    if cycle['status'] != 'DRAFT':
        fail('ERR_INVALID_CYCLE_STATE')
    cycle['status'] = 'OPEN'
    touch(cycle)
    return ok(ser_cycle(cycle))


@app.route('/leave-cycles/<cid>/close', methods=['POST'])
def close_cycle(cid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    cycle = _cycle_or_404(cid)
    if cycle['status'] != 'OPEN':
        fail('ERR_INVALID_CYCLE_STATE')
    cycle['status'] = 'CLOSED'
    touch(cycle)
    return ok(ser_cycle(cycle))


@app.route('/leave-cycles/<cid>/allocate', methods=['POST'])
def allocate_cycle(cid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    cycle = _cycle_or_404(cid)
    if cycle['status'] != 'CLOSED':
        fail('ERR_CYCLE_NOT_CLOSED')

    candidates = [a for a in STORE['applications'].values()
                  if a['cycle_id'] == cid and a['leave_type'] == 'SABBATICAL'
                  and a['status'] == 'UNDER_REVIEW']

    def rank_key(a):
        _, lifetime = faculty_balances(a['applicant_faculty_id'])
        comp = a['composite_score'] if a['composite_score'] is not None else Decimal('0')
        return (-comp, -lifetime, a['created_at'], a['_seq'])

    ranked = sorted([a for a in candidates if a['quorum_met']], key=rank_key)
    for i, a in enumerate(ranked, start=1):
        a['final_rank'] = i

    awarded = 0
    quota = cycle['award_quota']
    for a in ranked:
        plan = None
        if a['current_coverage_plan_id']:
            plan = STORE['plans'].get(a['current_coverage_plan_id'])
        credit, _ = faculty_balances(a['applicant_faculty_id'])
        cost = CREDITS_PER_SEMESTER * a['requested_duration_semesters']
        if plan is None or plan['status'] != 'APPROVED':
            a['status'] = 'NOT_AWARDED'
            a['award_outcome'] = 'NO_APPROVED_COVERAGE'
            touch(a)
        elif credit < cost:
            a['status'] = 'NOT_AWARDED'
            a['award_outcome'] = 'INSUFFICIENT_CREDITS'
            touch(a)
        elif awarded >= quota:
            a['status'] = 'NOT_AWARDED'
            a['award_outcome'] = 'QUOTA_EXCEEDED'
            touch(a)
        else:
            a['status'] = 'AWARDED'
            a['award_outcome'] = 'AWARDED'
            a['funding_status'] = 'COVERAGE_CONFIRMED'
            touch(a)
            create_grant(a)
            plan['status'] = 'CONFIRMED'
            touch(plan)
            add_ledger_entry(a['applicant_faculty_id'], 'CONSUME', -cost)
            awarded += 1

    for a in sort_items([a for a in candidates if not a['quorum_met']]):
        a['status'] = 'NOT_AWARDED'
        a['award_outcome'] = 'INCOMPLETE_REVIEWS'
        touch(a)

    cycle['awarded_count'] = awarded
    cycle['status'] = 'ALLOCATED'
    touch(cycle)
    return ok(ser_cycle(cycle))


@app.route('/leave-cycles/<cid>/finalize', methods=['POST'])
def finalize_cycle(cid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    cycle = _cycle_or_404(cid)
    if cycle['status'] != 'ALLOCATED':
        fail('ERR_CYCLE_NOT_ALLOCATED')
    cycle['status'] = 'FINALIZED'
    touch(cycle)
    return ok(ser_cycle(cycle))


# ---------------------------------------------------------------------------
# Leave applications
# ---------------------------------------------------------------------------
def _combo_allowed(leave_type, duration, pct):
    if leave_type == 'SABBATICAL':
        return (duration == 1 and pct == 100) or (duration == 2 and pct in (50, 75))
    if leave_type == 'PROFESSIONAL':
        return duration in (1, 2) and pct == 100
    # MEDICAL / PERSONAL
    return duration in (1, 2) and pct == 0


def _window_shape_ok(start, end, semesters):
    return end > start and end == add_months(start, semesters * 6)


def _has_other_in_flight(faculty_id, exclude_app_id=None):
    for a in STORE['applications'].values():
        if a['applicant_faculty_id'] != faculty_id:
            continue
        if exclude_app_id and a['id'] == exclude_app_id:
            continue
        if a['status'] in IN_FLIGHT:
            return True
    return False


@app.route('/leave-applications', methods=['POST'])
def create_application():
    uid, role = auth_context()
    body = body_json()
    leave_type = body.get('leave_type')
    if leave_type not in LEAVE_TYPES:
        fail('ERR_INVALID_REQUEST', 'leave_type must be one of SABBATICAL, MEDICAL, PERSONAL, PROFESSIONAL.')
    duration = parse_int(body.get('requested_duration_semesters'))
    if duration is None:
        fail('ERR_INVALID_REQUEST', 'requested_duration_semesters is required and must be an integer.')
    pct = parse_int(body.get('requested_salary_pct'))
    if pct is None:
        fail('ERR_INVALID_REQUEST', 'requested_salary_pct is required and must be an integer.')
    start = parse_dt(body.get('proposed_start_date'))
    end = parse_dt(body.get('proposed_end_date'))
    if start is None or end is None:
        fail('ERR_INVALID_REQUEST', 'proposed_start_date and proposed_end_date are required ISO-8601 timestamps.')
    proposal_text = optional_string(body, 'proposal_text')
    cycle_id = body.get('cycle_id')
    if cycle_id is not None and not isinstance(cycle_id, str):
        fail('ERR_INVALID_REQUEST', 'cycle_id must be a string when provided.')
    require_role(role, FACULTY_ONLY)
    # tier 4: existence, faculty (caller) before cycle
    fac = STORE['faculty'].get(uid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    if cycle_id is not None and cycle_id not in STORE['cycles']:
        fail('ERR_CYCLE_NOT_FOUND')
    # tier 9: eligibility combos (the duplicate-active gate lives at
    # submission per PRD 3.3 — creation must allow a second DRAFT to exist,
    # otherwise the submission-time rule could never fire)
    if not _combo_allowed(leave_type, duration, pct):
        fail('ERR_INVALID_DURATION_SALARY_COMBO')
    if (leave_type == 'SABBATICAL') != (cycle_id is not None):
        fail('ERR_INVALID_REQUEST', 'cycle_id is required exactly when leave_type is SABBATICAL.')
    # tier 10: window shape and overlap
    if not _window_shape_ok(start, end, duration):
        fail('ERR_INVALID_DATE_RANGE')
    if has_active_overlap(uid, start, end):
        fail('ERR_LEAVE_WINDOW_OVERLAP')
    now = clock_now()
    application = {
        'id': new_id(), '_seq': next(SEQ),
        'applicant_faculty_id': uid, 'cycle_id': cycle_id,
        'leave_type': leave_type,
        'requested_duration_semesters': duration,
        'requested_salary_pct': pct,
        'proposed_start_date': start, 'proposed_end_date': end,
        'proposal_text': proposal_text,
        'status': 'DRAFT', 'funding_status': 'NONE',
        'composite_score': None, 'submitted_review_count': 0,
        'quorum_met': False, 'final_rank': None, 'award_outcome': None,
        'current_coverage_plan_id': None,
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['applications'][application['id']] = application
    return ok(ser_application(application), 201)


@app.route('/leave-applications', methods=['GET'])
def list_applications():
    auth_context()
    items = sort_items(STORE['applications'].values())
    for param, field in (('applicant_faculty_id', 'applicant_faculty_id'),
                         ('cycle_id', 'cycle_id'),
                         ('status', 'status'),
                         ('leave_type', 'leave_type')):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a[field] == v]
    page, meta = paginate(items)
    return ok([ser_application(a) for a in page], 200, pagination=meta, response_type='array')


def _application_or_404(aid):
    application = STORE['applications'].get(aid)
    if application is None:
        fail('ERR_APPLICATION_NOT_FOUND')
    return application


@app.route('/leave-applications/<aid>', methods=['GET'])
def get_application(aid):
    auth_context()
    return ok(ser_application(_application_or_404(aid)))


@app.route('/leave-applications/<aid>/submit', methods=['POST'])
def submit_application(aid):
    uid, role = auth_context()
    body_json()
    require_role(role, FACULTY_ONLY)
    application = _application_or_404(aid)
    if application['applicant_faculty_id'] != uid:
        fail('ERR_NOT_RESOURCE_OWNER')
    # tier 7: from-state gates
    if application['status'] not in ('DRAFT', 'REVISION_REQUESTED'):
        fail('ERR_INVALID_APPLICATION_STATE')
    if application['leave_type'] == 'SABBATICAL':
        cycle = STORE['cycles'].get(application['cycle_id'])
        if cycle is None:
            fail('ERR_CYCLE_NOT_FOUND')
        if cycle['status'] != 'OPEN':
            fail('ERR_CYCLE_NOT_OPEN')
    fid = application['applicant_faculty_id']
    # tier 8: standing cross-resource gates
    if any(r['faculty_id'] == fid and r['status'] == 'OVERDUE'
           for r in STORE['reports'].values()):
        fail('ERR_OVERDUE_REPORT_BLOCKS')
    if any(r['faculty_id'] == fid and r['status'] == 'DEFAULTED'
           for r in STORE['repayments'].values()):
        fail('ERR_DEFAULTED_REPAYMENT_BLOCKS')
    # tier 9: uniqueness / eligibility
    if _has_other_in_flight(fid, exclude_app_id=application['id']):
        fail('ERR_DUPLICATE_ACTIVE_APPLICATION')
    is_sabbatical = application['leave_type'] == 'SABBATICAL'
    credit, lifetime = faculty_balances(fid)
    if is_sabbatical and lifetime < MIN_CERTIFIED_SERVICE_MONTHS:
        fail('ERR_INSUFFICIENT_SERVICE_MONTHS')
    # tier 10: temporal / window
    if not _window_shape_ok(application['proposed_start_date'],
                            application['proposed_end_date'],
                            application['requested_duration_semesters']):
        fail('ERR_INVALID_DATE_RANGE')
    if has_active_overlap(fid, application['proposed_start_date'],
                          application['proposed_end_date']):
        fail('ERR_LEAVE_WINDOW_OVERLAP')
    # tier 11: fiscal
    if is_sabbatical and credit < CREDITS_PER_SEMESTER * application['requested_duration_semesters']:
        fail('ERR_INSUFFICIENT_SABBATICAL_CREDITS')
    application['status'] = 'UNDER_REVIEW'
    touch(application)
    return ok(ser_application(application))


@app.route('/leave-applications/<aid>/request-revision', methods=['POST'])
def request_revision_application(aid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    application = _application_or_404(aid)
    if application['status'] != 'UNDER_REVIEW':
        fail('ERR_INVALID_APPLICATION_STATE')
    application['status'] = 'REVISION_REQUESTED'
    touch(application)
    return ok(ser_application(application))


@app.route('/leave-applications/<aid>/withdraw', methods=['POST'])
def withdraw_application(aid):
    uid, role = auth_context()
    body_json()
    require_role(role, FACULTY_ONLY)
    application = _application_or_404(aid)
    if application['applicant_faculty_id'] != uid:
        fail('ERR_NOT_RESOURCE_OWNER')
    if application['status'] not in ('DRAFT', 'UNDER_REVIEW', 'REVISION_REQUESTED'):
        fail('ERR_INVALID_APPLICATION_STATE')
    for plan in application_plans(application['id']):
        if plan['status'] in ('DRAFT', 'SUBMITTED', 'REVISION_REQUESTED'):
            plan['status'] = 'SUPERSEDED'
            touch(plan)
        elif plan['status'] == 'APPROVED':
            plan['status'] = 'RELEASED'
            touch(plan)
            dept = STORE['departments'].get(plan['department_id'])
            if dept is not None:
                department_mutated(dept)
    application['funding_status'] = 'NONE'
    application['current_coverage_plan_id'] = None
    application['status'] = 'WITHDRAWN'
    touch(application)
    return ok(ser_application(application))


@app.route('/leave-applications/<aid>/decide', methods=['POST'])
def decide_application(aid):
    uid, role = auth_context()
    body = body_json()
    decision = body.get('decision')
    if decision not in ('APPROVED', 'DENIED'):
        fail('ERR_INVALID_REQUEST', 'decision must be APPROVED or DENIED.')
    optional_string(body, 'comments')
    require_role(role, PROVOST)
    application = _application_or_404(aid)
    if application['status'] != 'UNDER_REVIEW':
        fail('ERR_INVALID_APPLICATION_STATE')
    if application['leave_type'] == 'SABBATICAL':
        fail('ERR_SABBATICAL_REQUIRES_ALLOCATION')
    if decision == 'DENIED':
        application['status'] = 'DENIED'
        touch(application)
        return ok(ser_application(application))
    # APPROVED: no overlapping ACTIVE grant for the faculty
    fid = application['applicant_faculty_id']
    if has_active_overlap(fid, application['proposed_start_date'],
                          application['proposed_end_date']):
        fail('ERR_LEAVE_WINDOW_OVERLAP')
    create_grant(application)
    if application['leave_type'] == 'MEDICAL':
        # Medical precedence: cancel overlapping SCHEDULED sabbatical grants.
        overlapping = sort_items([
            g for g in STORE['grants'].values()
            if g['faculty_id'] == fid and g['status'] == 'SCHEDULED'
            and g['leave_type'] == 'SABBATICAL'
            and windows_overlap(g['start_date'], g['end_date'],
                                application['proposed_start_date'],
                                application['proposed_end_date'])])
        for g in overlapping:
            cancel_scheduled_grant(g)
    application['status'] = 'APPROVED'
    touch(application)
    return ok(ser_application(application))


# ---------------------------------------------------------------------------
# Committee reviews
# ---------------------------------------------------------------------------
def _parse_score(body, field):
    v = body.get(field)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        fail('ERR_INVALID_REQUEST', '{} is required and must be a number in 0..100 with at most 1 decimal place.'.format(field))
    d = D(v)
    if d < 0 or d > 100 or -d.as_tuple().exponent > 1:
        fail('ERR_INVALID_REQUEST', '{} must be in 0..100 with at most 1 decimal place.'.format(field))
    return d


@app.route('/committee-reviews', methods=['POST'])
def create_review():
    uid, role = auth_context()
    body = body_json()
    application_id = body.get('application_id')
    if not isinstance(application_id, str) or not application_id:
        fail('ERR_INVALID_REQUEST', 'application_id is required.')
    merit = _parse_score(body, 'scholarly_merit')
    curriculum = _parse_score(body, 'curriculum_benefit')
    feasibility = _parse_score(body, 'feasibility')
    comments = optional_string(body, 'comments')
    require_role(role, COMMITTEE)
    # tier 4: faculty (caller) then application
    reviewer = STORE['faculty'].get(uid)
    if reviewer is None:
        fail('ERR_FACULTY_NOT_FOUND')
    application = STORE['applications'].get(application_id)
    if application is None:
        fail('ERR_APPLICATION_NOT_FOUND')
    # tier 5: segregation — reviewer != applicant and different department
    applicant = STORE['faculty'].get(application['applicant_faculty_id'])
    if uid == application['applicant_faculty_id'] or (
            applicant is not None and reviewer['department_id'] == applicant['department_id']):
        fail('ERR_REVIEWER_CONFLICT')
    # tier 7: application must be UNDER_REVIEW
    if application['status'] != 'UNDER_REVIEW':
        fail('ERR_INVALID_APPLICATION_STATE')
    # tier 9: one review per (reviewer, application) in any status
    for r in STORE['reviews'].values():
        if r['application_id'] == application_id and r['reviewer_faculty_id'] == uid:
            fail('ERR_DUPLICATE_REVIEW')
    now = clock_now()
    review = {
        'id': new_id(), '_seq': next(SEQ),
        'application_id': application_id, 'reviewer_faculty_id': uid,
        'scholarly_merit': merit, 'curriculum_benefit': curriculum,
        'feasibility': feasibility, 'comments': comments,
        'weighted_total': compute_weighted_total(merit, curriculum, feasibility),
        'status': 'DRAFT',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['reviews'][review['id']] = review
    return ok(ser_review(review), 201)


@app.route('/committee-reviews', methods=['GET'])
def list_reviews():
    auth_context()
    items = sort_items(STORE['reviews'].values())
    for param, field in (('application_id', 'application_id'),
                         ('reviewer_faculty_id', 'reviewer_faculty_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, meta = paginate(items)
    return ok([ser_review(r) for r in page], 200, pagination=meta, response_type='array')


@app.route('/committee-reviews/<rid>', methods=['GET'])
def get_review(rid):
    auth_context()
    review = STORE['reviews'].get(rid)
    if review is None:
        fail('ERR_REVIEW_NOT_FOUND')
    return ok(ser_review(review))


@app.route('/committee-reviews/<rid>/submit', methods=['POST'])
def submit_review(rid):
    uid, role = auth_context()
    body_json()
    require_role(role, COMMITTEE)
    review = STORE['reviews'].get(rid)
    if review is None:
        fail('ERR_REVIEW_NOT_FOUND')
    if review['reviewer_faculty_id'] != uid:
        fail('ERR_NOT_RESOURCE_OWNER')
    if review['status'] != 'DRAFT':
        fail('ERR_INVALID_REVIEW_STATE')
    application = STORE['applications'].get(review['application_id'])
    if application is None or application['status'] != 'UNDER_REVIEW':
        fail('ERR_INVALID_APPLICATION_STATE')
    review['status'] = 'SUBMITTED'
    touch(review)
    recompute_review_aggregates(application)
    touch(application)
    return ok(ser_review(review))
