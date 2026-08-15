"""Routes: coverage plans, leave grants, fellowships, obligations, repayments, reports."""
from decimal import Decimal

from flask import request

from db import SEQ, STORE, clock_now, touch
from flask_app import app
from services import (COST_PER_COURSE, DEPT_MAX_ACTIVE_LEAVES,
                      MAX_FELLOWSHIP_OFFSET_PCT, application_plans,
                      confirmed_plan, create_accomplishment_report,
                      create_service_obligation, curtail_grant,
                      department_mutated, dept_capacity_worst,
                      has_active_overlap, ser_fellowship, ser_grant,
                      ser_obligation, ser_payment, ser_plan, ser_repayment,
                      ser_report, settle_confirmed_plan)
from util import (D, auth_context, body_json, fail, new_id, ok, optional_string,
                  overlap_seconds, paginate, parse_dt, parse_int,
                  parse_positive_money, q2, require_role, require_string,
                  sort_items)

ADMIN = {'LeaveAdministrator'}
PROVOST = {'ProvostOffice'}
FACULTY_ONLY = {'Faculty'}
PLAN_WRITERS = {'DepartmentChair', 'ProvostOffice'}
PRE_AWARD = {'DRAFT', 'UNDER_REVIEW', 'REVISION_REQUESTED'}
SUPERSEDABLE = {'DRAFT', 'SUBMITTED', 'REVISION_REQUESTED'}


# ---------------------------------------------------------------------------
# Coverage plans
# ---------------------------------------------------------------------------
@app.route('/coverage-plans', methods=['POST'])
def create_plan():
    uid, role = auth_context()
    body = body_json()
    application_id = body.get('application_id')
    if not isinstance(application_id, str) or not application_id:
        fail('ERR_INVALID_REQUEST', 'application_id is required.')
    courses = parse_int(body.get('courses_to_cover'))
    if courses is None or courses < 1 or courses > 40:
        fail('ERR_INVALID_REQUEST', 'courses_to_cover is required and must be an integer between 1 and 40.')
    supersedes_id = body.get('supersedes_plan_id')
    if supersedes_id is not None and not isinstance(supersedes_id, str):
        fail('ERR_INVALID_REQUEST', 'supersedes_plan_id must be a string when provided.')
    expected = parse_int(body.get('expected_application_version'))
    if expected is None:
        fail('ERR_INVALID_REQUEST', 'expected_application_version is required.')
    require_role(role, PLAN_WRITERS)
    # tier 4: existence, application then plan
    application = STORE['applications'].get(application_id)
    if application is None:
        fail('ERR_APPLICATION_NOT_FOUND')
    supersedes_target = None
    if supersedes_id is not None:
        supersedes_target = STORE['plans'].get(supersedes_id)
        if supersedes_target is None:
            fail('ERR_COVERAGE_PLAN_NOT_FOUND')
        if supersedes_target['application_id'] != application_id:
            fail('ERR_INVALID_REQUEST', 'supersedes_plan_id must reference a plan of the same application.')
    # tier 5: segregation of duties and chair-department match
    applicant = STORE['faculty'].get(application['applicant_faculty_id'])
    dept_id = applicant['department_id'] if applicant is not None else None
    if role == 'DepartmentChair':
        if uid == application['applicant_faculty_id']:
            fail('ERR_SEGREGATION_OF_DUTIES')
        dept = STORE['departments'].get(dept_id)
        if dept is None or dept['chair_faculty_id'] != uid:
            fail('ERR_CHAIR_DEPARTMENT_MISMATCH')
    # tier 6: optimistic concurrency on the application
    if expected != application['version']:
        fail('ERR_STALE_VERSION')
    # tier 7: application must be sabbatical and pre-award
    if application['leave_type'] != 'SABBATICAL':
        fail('ERR_INVALID_REQUEST', 'Coverage plans may only be filed for sabbatical applications.')
    if application['status'] not in PRE_AWARD:
        fail('ERR_INVALID_APPLICATION_STATE')
    # resolve the supersede target: explicit, else the current plan
    if supersedes_target is None and application['current_coverage_plan_id']:
        supersedes_target = STORE['plans'].get(application['current_coverage_plan_id'])
    if supersedes_target is not None:
        if supersedes_target['status'] not in SUPERSEDABLE:
            fail('ERR_INVALID_PLAN_STATE')
        was_current = application['current_coverage_plan_id'] == supersedes_target['id']
        supersedes_target['status'] = 'SUPERSEDED'
        touch(supersedes_target)
        if was_current and application['funding_status'] == 'COVERAGE_SUBMITTED':
            application['funding_status'] = 'NONE'
    now = clock_now()
    plan = {
        'id': new_id(), '_seq': next(SEQ),
        'application_id': application_id, 'department_id': dept_id,
        'supersedes_plan_id': supersedes_id,
        'courses_to_cover': courses,
        'provisional_cost': q2(D(courses) * COST_PER_COURSE),
        'final_cost': None,
        'status': 'DRAFT',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['plans'][plan['id']] = plan
    application['current_coverage_plan_id'] = plan['id']
    touch(application)
    return ok(ser_plan(plan), 201)


@app.route('/coverage-plans', methods=['GET'])
def list_plans():
    auth_context()
    items = sort_items(STORE['plans'].values())
    for param, field in (('application_id', 'application_id'),
                         ('department_id', 'department_id'),
                         ('status', 'status'),
                         ('supersedes_plan_id', 'supersedes_plan_id')):
        v = request.args.get(param)
        if v is not None:
            items = [p for p in items if p[field] == v]
    page, meta = paginate(items)
    return ok([ser_plan(p) for p in page], 200, pagination=meta, response_type='array')


def _plan_or_404(pid):
    plan = STORE['plans'].get(pid)
    if plan is None:
        fail('ERR_COVERAGE_PLAN_NOT_FOUND')
    return plan


@app.route('/coverage-plans/<pid>', methods=['GET'])
def get_plan(pid):
    auth_context()
    return ok(ser_plan(_plan_or_404(pid)))


def _check_chair_authority(uid, role, plan):
    if role == 'DepartmentChair':
        dept = STORE['departments'].get(plan['department_id'])
        if dept is None or dept['chair_faculty_id'] != uid:
            fail('ERR_CHAIR_DEPARTMENT_MISMATCH')


@app.route('/coverage-plans/<pid>/submit', methods=['POST'])
def submit_plan(pid):
    uid, role = auth_context()
    body_json()
    require_role(role, PLAN_WRITERS)
    plan = _plan_or_404(pid)
    _check_chair_authority(uid, role, plan)
    if plan['status'] != 'DRAFT':
        fail('ERR_INVALID_PLAN_STATE')
    application = STORE['applications'].get(plan['application_id'])
    if application is None or application['status'] not in ('UNDER_REVIEW', 'REVISION_REQUESTED'):
        fail('ERR_INVALID_APPLICATION_STATE')
    dept = STORE['departments'].get(plan['department_id'])
    if dept is not None and dept['posture'] == 'FROZEN':
        fail('ERR_DEPARTMENT_FROZEN')
    plan['status'] = 'SUBMITTED'
    touch(plan)
    if application is not None:
        application['funding_status'] = 'COVERAGE_SUBMITTED'
        touch(application)
    return ok(ser_plan(plan))


@app.route('/coverage-plans/<pid>/approve', methods=['POST'])
def approve_plan(pid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    plan = _plan_or_404(pid)
    if plan['status'] != 'SUBMITTED':
        fail('ERR_INVALID_PLAN_STATE')
    dept = STORE['departments'].get(plan['department_id'])
    if dept is not None:
        if dept['posture'] == 'FROZEN':
            fail('ERR_DEPARTMENT_FROZEN')
        available = dept['replacement_pool'] - dept['reserved_amount'] - dept['spent_amount']
        if available < plan['provisional_cost']:
            fail('ERR_INSUFFICIENT_COVERAGE_BUDGET')
    plan['status'] = 'APPROVED'
    touch(plan)
    if dept is not None:
        department_mutated(dept)
    application = STORE['applications'].get(plan['application_id'])
    if application is not None:
        application['funding_status'] = 'COVERAGE_APPROVED'
        touch(application)
    return ok(ser_plan(plan))


@app.route('/coverage-plans/<pid>/request-revision', methods=['POST'])
def request_revision_plan(pid):
    uid, role = auth_context()
    body_json()
    require_role(role, PROVOST)
    plan = _plan_or_404(pid)
    if plan['status'] != 'SUBMITTED':
        fail('ERR_INVALID_PLAN_STATE')
    plan['status'] = 'REVISION_REQUESTED'
    touch(plan)
    return ok(ser_plan(plan))


# ---------------------------------------------------------------------------
# Leave grants
# ---------------------------------------------------------------------------
@app.route('/leave-grants', methods=['GET'])
def list_grants():
    auth_context()
    items = sort_items(STORE['grants'].values())
    for param, field in (('faculty_id', 'faculty_id'),
                         ('application_id', 'application_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [g for g in items if g[field] == v]
    page, meta = paginate(items)
    return ok([ser_grant(g) for g in page], 200, pagination=meta, response_type='array')


def _grant_or_404(gid):
    grant = STORE['grants'].get(gid)
    if grant is None:
        fail('ERR_GRANT_NOT_FOUND')
    return grant


@app.route('/leave-grants/<gid>', methods=['GET'])
def get_grant(gid):
    auth_context()
    return ok(ser_grant(_grant_or_404(gid)))


@app.route('/leave-grants/<gid>/activate', methods=['POST'])
def activate_grant(gid):
    uid, role = auth_context()
    body_json()
    require_role(role, ADMIN)
    grant = _grant_or_404(gid)
    # tier 7 state gates
    if grant['status'] != 'SCHEDULED':
        fail('ERR_INVALID_GRANT_STATE')
    fac = STORE['faculty'].get(grant['faculty_id'])
    if fac is None or fac['status'] != 'ACTIVE':
        fail('ERR_INVALID_FACULTY_STATE')
    # tier 10 temporal gates
    now = clock_now()
    if now < grant['start_date']:
        fail('ERR_GRANT_START_NOT_REACHED')
    if has_active_overlap(grant['faculty_id'], grant['start_date'], grant['end_date']):
        fail('ERR_LEAVE_WINDOW_OVERLAP')
    worst = dept_capacity_worst(fac['department_id'], grant['start_date'],
                                grant['end_date'], exclude_grant_id=grant['id'])
    if worst >= DEPT_MAX_ACTIVE_LEAVES:
        fail('ERR_DEPARTMENT_LEAVE_CAPACITY')
    # Money, in pinned evaluation order.
    months = grant['duration_semesters'] * 6
    gross = q2(fac['annual_base_salary'] * D(grant['salary_pct']) * D(months) / D(1200))
    cap = q2(gross * MAX_FELLOWSHIP_OFFSET_PCT)
    window_secs = (grant['end_date'] - grant['start_date']).total_seconds()
    eligible = []
    for f in STORE['fellowships'].values():
        if f['application_id'] != grant['application_id'] or f['status'] != 'VERIFIED':
            continue
        ov = overlap_seconds(f['window_start_date'], f['window_end_date'],
                             grant['start_date'], grant['end_date'])
        if ov * 2 >= window_secs:
            eligible.append(f)
    remaining = cap
    total = Decimal('0')
    for f in sorted(eligible, key=lambda x: (x['created_at'], x['_seq'])):
        applied = min(f['amount'], remaining)
        f['applied_offset'] = applied
        f['status'] = 'APPLIED'
        touch(f)
        remaining -= applied
        total += applied
    grant['gross_salary'] = gross
    grant['fellowship_offset_total'] = total
    grant['net_salary'] = gross - total
    grant['status'] = 'ACTIVE'
    touch(grant)
    fac['status'] = 'ON_LEAVE'
    touch(fac)
    return ok(ser_grant(grant))


@app.route('/leave-grants/<gid>/complete', methods=['POST'])
def complete_grant(gid):
    uid, role = auth_context()
    body_json()
    require_role(role, ADMIN)
    grant = _grant_or_404(gid)
    if grant['status'] != 'ACTIVE':
        fail('ERR_INVALID_GRANT_STATE')
    now = clock_now()
    if now < grant['end_date']:
        fail('ERR_INVALID_DATE_RANGE', 'The grant end date has not been reached.')
    grant['actual_months'] = grant['duration_semesters'] * 6
    grant['status'] = 'COMPLETED'
    touch(grant)
    fac = STORE['faculty'].get(grant['faculty_id'])
    if fac is not None and fac['status'] == 'ON_LEAVE':
        fac['status'] = 'ACTIVE'
        touch(fac)
    application = STORE['applications'].get(grant['application_id'])
    if grant['leave_type'] == 'SABBATICAL' and application is not None:
        plan = confirmed_plan(application['id'])
        if plan is not None:
            settle_confirmed_plan(application, plan['provisional_cost'])
    if grant['leave_type'] in ('SABBATICAL', 'PROFESSIONAL'):
        create_service_obligation(grant, grant['actual_months'], grant['end_date'])
        create_accomplishment_report(grant, grant['end_date'])
    return ok(ser_grant(grant))


@app.route('/leave-grants/<gid>/curtail', methods=['POST'])
def curtail_grant_route(gid):
    uid, role = auth_context()
    body = body_json()
    actual_return = parse_dt(body.get('actual_return_date'))
    if actual_return is None:
        fail('ERR_INVALID_REQUEST', 'actual_return_date is required and must be a valid ISO-8601 timestamp.')
    require_role(role, ADMIN)
    grant = _grant_or_404(gid)
    if grant['status'] != 'ACTIVE':
        fail('ERR_INVALID_GRANT_STATE')
    now = clock_now()
    if not (grant['start_date'] < actual_return < grant['end_date']) or now < actual_return:
        fail('ERR_INVALID_DATE_RANGE')
    curtail_grant(grant, actual_return)
    return ok(ser_grant(grant))


# ---------------------------------------------------------------------------
# External fellowships
# ---------------------------------------------------------------------------
@app.route('/external-fellowships', methods=['POST'])
def create_fellowship():
    uid, role = auth_context()
    body = body_json()
    application_id = body.get('application_id')
    if not isinstance(application_id, str) or not application_id:
        fail('ERR_INVALID_REQUEST', 'application_id is required.')
    name = require_string(body, 'name')
    amount = parse_positive_money(body.get('amount'))
    if amount is None:
        fail('ERR_INVALID_REQUEST', 'amount is required and must be a positive number.')
    w_start = parse_dt(body.get('window_start_date'))
    w_end = parse_dt(body.get('window_end_date'))
    if w_start is None or w_end is None:
        fail('ERR_INVALID_REQUEST', 'window_start_date and window_end_date are required ISO-8601 timestamps.')
    require_role(role, FACULTY_ONLY)
    fac = STORE['faculty'].get(uid)
    if fac is None:
        fail('ERR_FACULTY_NOT_FOUND')
    application = STORE['applications'].get(application_id)
    if application is None:
        fail('ERR_APPLICATION_NOT_FOUND')
    if application['leave_type'] != 'SABBATICAL' or application['applicant_faculty_id'] != uid:
        fail('ERR_INVALID_REQUEST', 'application_id must reference a sabbatical application of the reporting faculty.')
    if not (w_end > w_start):
        fail('ERR_INVALID_DATE_RANGE')
    now = clock_now()
    fellowship = {
        'id': new_id(), '_seq': next(SEQ),
        'faculty_id': uid, 'application_id': application_id,
        'name': name, 'amount': amount,
        'window_start_date': w_start, 'window_end_date': w_end,
        'applied_offset': Decimal('0'), 'status': 'REPORTED',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['fellowships'][fellowship['id']] = fellowship
    return ok(ser_fellowship(fellowship), 201)


@app.route('/external-fellowships', methods=['GET'])
def list_fellowships():
    auth_context()
    items = sort_items(STORE['fellowships'].values())
    for param, field in (('faculty_id', 'faculty_id'),
                         ('application_id', 'application_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f[field] == v]
    page, meta = paginate(items)
    return ok([ser_fellowship(f) for f in page], 200, pagination=meta, response_type='array')


def _fellowship_or_404(fid):
    fellowship = STORE['fellowships'].get(fid)
    if fellowship is None:
        fail('ERR_FELLOWSHIP_NOT_FOUND')
    return fellowship


@app.route('/external-fellowships/<fid>', methods=['GET'])
def get_fellowship(fid):
    auth_context()
    return ok(ser_fellowship(_fellowship_or_404(fid)))


@app.route('/external-fellowships/<fid>/verify', methods=['POST'])
def verify_fellowship(fid):
    uid, role = auth_context()
    body_json()
    require_role(role, ADMIN)
    fellowship = _fellowship_or_404(fid)
    if fellowship['status'] != 'REPORTED':
        fail('ERR_INVALID_FELLOWSHIP_STATE')
    application = STORE['applications'].get(fellowship['application_id'])
    if application is not None:
        w_start, w_end = application['proposed_start_date'], application['proposed_end_date']
        window_secs = (w_end - w_start).total_seconds()
        ov = overlap_seconds(fellowship['window_start_date'], fellowship['window_end_date'],
                             w_start, w_end)
        if ov * 2 < window_secs:
            fail('ERR_FELLOWSHIP_OVERLAP_INSUFFICIENT')
    fellowship['status'] = 'VERIFIED'
    touch(fellowship)
    return ok(ser_fellowship(fellowship))


@app.route('/external-fellowships/<fid>/decline', methods=['POST'])
def decline_fellowship(fid):
    uid, role = auth_context()
    body_json()
    require_role(role, FACULTY_ONLY)
    fellowship = _fellowship_or_404(fid)
    if fellowship['faculty_id'] != uid:
        fail('ERR_NOT_RESOURCE_OWNER')
    if fellowship['status'] not in ('REPORTED', 'VERIFIED'):
        fail('ERR_INVALID_FELLOWSHIP_STATE')
    fellowship['status'] = 'DECLINED'
    touch(fellowship)
    return ok(ser_fellowship(fellowship))


# ---------------------------------------------------------------------------
# Service obligations
# ---------------------------------------------------------------------------
@app.route('/service-obligations', methods=['GET'])
def list_obligations():
    auth_context()
    items = sort_items(STORE['obligations'].values())
    for param, field in (('faculty_id', 'faculty_id'),
                         ('grant_id', 'grant_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [o for o in items if o[field] == v]
    page, meta = paginate(items)
    return ok([ser_obligation(o) for o in page], 200, pagination=meta, response_type='array')


@app.route('/service-obligations/<oid>', methods=['GET'])
def get_obligation(oid):
    auth_context()
    ob = STORE['obligations'].get(oid)
    if ob is None:
        fail('ERR_OBLIGATION_NOT_FOUND')
    return ok(ser_obligation(ob))


# ---------------------------------------------------------------------------
# Repayment obligations and payments
# ---------------------------------------------------------------------------
@app.route('/repayment-obligations', methods=['GET'])
def list_repayments():
    auth_context()
    items = sort_items(STORE['repayments'].values())
    for param, field in (('faculty_id', 'faculty_id'),
                         ('obligation_id', 'obligation_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, meta = paginate(items)
    return ok([ser_repayment(r) for r in page], 200, pagination=meta, response_type='array')


def _repayment_or_404(rid):
    rp = STORE['repayments'].get(rid)
    if rp is None:
        fail('ERR_REPAYMENT_NOT_FOUND')
    return rp


@app.route('/repayment-obligations/<rid>', methods=['GET'])
def get_repayment(rid):
    auth_context()
    return ok(ser_repayment(_repayment_or_404(rid)))


@app.route('/repayment-obligations/<rid>/payments', methods=['GET'])
def list_payments(rid):
    auth_context()
    rp = _repayment_or_404(rid)
    items = sort_items([p for p in STORE['payments'].values()
                        if p['repayment_id'] == rp['id']])
    page, meta = paginate(items)
    return ok([ser_payment(p) for p in page], 200, pagination=meta, response_type='array')


@app.route('/repayment-obligations/<rid>/payments', methods=['POST'])
def create_payment(rid):
    uid, role = auth_context()
    body = body_json()
    amount = parse_positive_money(body.get('amount'))
    if amount is None:
        fail('ERR_INVALID_REQUEST', 'amount is required and must be a positive number.')
    expected = parse_int(body.get('expected_repayment_version'))
    if expected is None:
        fail('ERR_INVALID_REQUEST', 'expected_repayment_version is required.')
    require_role(role, ADMIN)
    rp = _repayment_or_404(rid)
    if expected != rp['version']:
        fail('ERR_STALE_VERSION')
    if rp['status'] not in ('ACTIVE', 'DEFAULTED'):
        fail('ERR_INVALID_REPAYMENT_STATE')
    if amount > rp['amount_outstanding']:
        fail('ERR_PAYMENT_EXCEEDS_OUTSTANDING')
    now = clock_now()
    rp['amount_outstanding'] = rp['amount_outstanding'] - amount
    payment = {
        'id': new_id(), '_seq': next(SEQ),
        'repayment_id': rp['id'], 'amount': amount,
        'resulting_outstanding': rp['amount_outstanding'],
        'created_at': now,
    }
    STORE['payments'][payment['id']] = payment
    if rp['amount_outstanding'] == 0:
        rp['status'] = 'SETTLED'
    touch(rp)
    return ok(ser_payment(payment), 201)


@app.route('/repayment-obligations/<rid>/waive', methods=['POST'])
def waive_repayment(rid):
    uid, role = auth_context()
    body = body_json()
    optional_string(body, 'comments')
    require_role(role, PROVOST)
    rp = _repayment_or_404(rid)
    if rp['status'] not in ('ACTIVE', 'DEFAULTED'):
        fail('ERR_INVALID_REPAYMENT_STATE')
    rp['status'] = 'WAIVED'
    rp['amount_outstanding'] = Decimal('0')
    touch(rp)
    return ok(ser_repayment(rp))


# ---------------------------------------------------------------------------
# Accomplishment reports
# ---------------------------------------------------------------------------
@app.route('/accomplishment-reports', methods=['GET'])
def list_reports():
    auth_context()
    items = sort_items(STORE['reports'].values())
    for param, field in (('faculty_id', 'faculty_id'),
                         ('grant_id', 'grant_id'),
                         ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    page, meta = paginate(items)
    return ok([ser_report(r) for r in page], 200, pagination=meta, response_type='array')


def _report_or_404(rid):
    rep = STORE['reports'].get(rid)
    if rep is None:
        fail('ERR_REPORT_NOT_FOUND')
    return rep


@app.route('/accomplishment-reports/<rid>', methods=['GET'])
def get_report(rid):
    auth_context()
    return ok(ser_report(_report_or_404(rid)))


@app.route('/accomplishment-reports/<rid>/submit', methods=['POST'])
def submit_report(rid):
    uid, role = auth_context()
    body = body_json()
    text = require_string(body, 'report_text')
    require_role(role, FACULTY_ONLY)
    rep = _report_or_404(rid)
    if rep['faculty_id'] != uid:
        fail('ERR_NOT_RESOURCE_OWNER')
    if rep['status'] not in ('DUE', 'OVERDUE', 'REVISION_REQUIRED'):
        fail('ERR_INVALID_REPORT_STATE')
    if rep['status'] == 'DUE':
        rep['submitted_late'] = False
    elif rep['status'] == 'OVERDUE':
        rep['submitted_late'] = True
    # REVISION_REQUIRED: submitted_late is sticky / unchanged
    rep['report_text'] = text
    rep['submitted_at'] = clock_now()
    rep['status'] = 'SUBMITTED'
    touch(rep)
    return ok(ser_report(rep))


@app.route('/accomplishment-reports/<rid>/review', methods=['POST'])
def review_report(rid):
    uid, role = auth_context()
    body = body_json()
    decision = body.get('decision')
    if decision not in ('ACCEPTED', 'REJECTED'):
        fail('ERR_INVALID_REQUEST', 'decision must be ACCEPTED or REJECTED.')
    comments = optional_string(body, 'comments')
    require_role(role, PROVOST)
    rep = _report_or_404(rid)
    if rep['status'] != 'SUBMITTED':
        fail('ERR_INVALID_REPORT_STATE')
    if decision == 'ACCEPTED':
        rep['status'] = 'ACCEPTED'
    else:
        rep['status'] = 'REVISION_REQUIRED'
        rep['decision_comments'] = comments
    touch(rep)
    return ok(ser_report(rep))
