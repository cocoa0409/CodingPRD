"""Domain services: serializers, derived values, cascades, sweeps."""
from datetime import timedelta
from decimal import Decimal

from db import STORE, SEQ, clock_now, touch
from util import (D, iso, money_out, new_id, q2, whole_months_between,
                  windows_overlap)

COST_PER_COURSE = Decimal('8000.00')
CREDITS_PER_SEMESTER = 36
RESTORE_PER_UNUSED_MONTH = 6
REVIEW_QUORUM = 3
DROP_LOWEST_MIN = 4
MAX_FELLOWSHIP_OFFSET_PCT = Decimal('0.50')
DEPT_MAX_ACTIVE_LEAVES = 2
MIN_CERTIFIED_SERVICE_MONTHS = 72


# ---------------------------------------------------------------------------
# Lookups
# ---------------------------------------------------------------------------
def application_plans(app_id):
    return [p for p in STORE['plans'].values() if p['application_id'] == app_id]


def confirmed_plan(app_id):
    for p in application_plans(app_id):
        if p['status'] == 'CONFIRMED':
            return p
    return None


def settled_plan(app_id):
    for p in application_plans(app_id):
        if p['status'] == 'SETTLED':
            return p
    return None


def add_ledger_entry(faculty_id, entry_type, delta, month=None,
                     affects_lifetime=False, note=None):
    entry = {
        'id': new_id(), '_seq': next(SEQ),
        'faculty_id': faculty_id, 'entry_type': entry_type,
        'credits_delta': delta, 'affects_lifetime': bool(affects_lifetime),
        'month': month, 'note': note,
        'created_at': clock_now(),
    }
    STORE['ledger'].append(entry)
    return entry


def faculty_balances(faculty_id):
    credit = 0
    lifetime = 0
    for e in STORE['ledger']:
        if e['faculty_id'] != faculty_id:
            continue
        credit += e['credits_delta']
        if e['entry_type'] == 'EARN' or (e['entry_type'] == 'ADJUST' and e['affects_lifetime']):
            lifetime += e['credits_delta']
    return credit, lifetime


def department_recompute(dept):
    """Recompute reserved/spent buckets and posture from the plans of record."""
    plans = [p for p in STORE['plans'].values() if p['department_id'] == dept['id']]
    dept['reserved_amount'] = sum(
        (p['provisional_cost'] for p in plans if p['status'] in ('APPROVED', 'CONFIRMED')),
        Decimal('0'))
    dept['spent_amount'] = sum(
        (p['final_cost'] for p in plans if p['status'] == 'SETTLED' and p['final_cost'] is not None),
        Decimal('0'))
    committed = dept['reserved_amount'] + dept['spent_amount']
    pool = dept['replacement_pool']
    # Exact rational comparison via cross-multiplication (no floats).
    if committed * 100 >= pool * 95:
        dept['posture'] = 'FROZEN'
    elif committed * 100 >= pool * 70:
        dept['posture'] = 'CONSTRAINED'
    else:
        dept['posture'] = 'OPEN'


def department_mutated(dept):
    department_recompute(dept)
    touch(dept)


def recompute_review_aggregates(app):
    subs = [r for r in STORE['reviews'].values()
            if r['application_id'] == app['id'] and r['status'] == 'SUBMITTED']
    app['submitted_review_count'] = len(subs)
    app['quorum_met'] = len(subs) >= REVIEW_QUORUM
    if not subs:
        app['composite_score'] = None
        return
    totals = [r['weighted_total'] for r in subs]
    kept = list(totals)
    if len(kept) >= DROP_LOWEST_MIN:
        kept.remove(min(kept))
    app['composite_score'] = q2(sum(kept, Decimal('0')) / Decimal(len(kept)))


def compute_weighted_total(merit, curr, feas):
    return (q2(D('0.45') * merit) + q2(D('0.35') * curr) + q2(D('0.20') * feas))


def has_active_overlap(faculty_id, start, end, exclude_grant_id=None):
    for g in STORE['grants'].values():
        if g['faculty_id'] != faculty_id or g['status'] != 'ACTIVE':
            continue
        if exclude_grant_id and g['id'] == exclude_grant_id:
            continue
        if windows_overlap(g['start_date'], g['end_date'], start, end):
            return True
    return False


def dept_capacity_worst(dept_id, start, end, exclude_grant_id=None):
    """Max simultaneous OTHER ACTIVE grants of the department inside [start, end)."""
    others = []
    for g in STORE['grants'].values():
        if g['status'] != 'ACTIVE' or g['id'] == exclude_grant_id:
            continue
        fac = STORE['faculty'].get(g['faculty_id'])
        if fac is None or fac['department_id'] != dept_id:
            continue
        if windows_overlap(g['start_date'], g['end_date'], start, end):
            others.append(g)
    points = {start}
    for g in others:
        s, e = max(g['start_date'], start), min(g['end_date'], end)
        if s < e:
            points.add(s)
            points.add(e)
    worst = 0
    for t in points:
        if t >= end:
            continue
        count = sum(1 for g in others if g['start_date'] <= t < g['end_date'])
        worst = max(worst, count)
    return worst


def sweep_overdue_and_defaults():
    """Clock-driven transitions, also evaluated lazily on every request."""
    now = clock_now()
    for r in STORE['reports'].values():
        if r['status'] == 'DUE' and now > r['due_date']:
            r['status'] = 'OVERDUE'
            touch(r)
    for rp in STORE['repayments'].values():
        if rp['status'] == 'ACTIVE' and now > rp['due_date'] and rp['amount_outstanding'] > 0:
            rp['status'] = 'DEFAULTED'
            touch(rp)


# ---------------------------------------------------------------------------
# Cascades
# ---------------------------------------------------------------------------
def cancel_scheduled_grant(grant):
    """SCHEDULED -> CANCELLED with the full unwind (separation / medical cascade)."""
    grant['status'] = 'CANCELLED'
    touch(grant)
    app = STORE['applications'].get(grant['application_id'])
    if grant['leave_type'] == 'SABBATICAL':
        add_ledger_entry(grant['faculty_id'], 'RESTORE',
                         CREDITS_PER_SEMESTER * grant['duration_semesters'])
        if app is not None:
            plan = confirmed_plan(app['id'])
            if plan is not None:
                plan['status'] = 'RELEASED'
                touch(plan)
                dept = STORE['departments'].get(plan['department_id'])
                if dept is not None:
                    department_mutated(dept)
            app['funding_status'] = 'COVERAGE_RELEASED'
            for f in STORE['fellowships'].values():
                if f['application_id'] == app['id'] and f['status'] == 'VERIFIED':
                    f['status'] = 'DECLINED'
                    touch(f)
    if app is not None:
        app['status'] = 'RESCINDED'
        touch(app)


def create_repayment_for_breach(ob):
    grant = STORE['grants'].get(ob['grant_id'])
    base = Decimal('0')
    if grant is not None and grant['net_salary'] is not None:
        base += grant['net_salary']
    if grant is not None:
        plan = settled_plan(grant['application_id'])
        if plan is not None and plan['final_cost'] is not None:
            base += plan['final_cost']
    required = ob['required_months']
    monthly = q2(base / Decimal(required))
    owed = base - monthly * ob['fulfilled_months']
    now = clock_now()
    rp = {
        'id': new_id(), '_seq': next(SEQ),
        'obligation_id': ob['id'], 'faculty_id': ob['faculty_id'],
        'base_amount': base,
        'fulfilled_months_at_breach': ob['fulfilled_months'],
        'monthly_forgiveness': monthly,
        'amount_owed': owed,
        'amount_outstanding': owed,
        'due_date': now + timedelta(days=365),
        'status': 'ACTIVE',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['repayments'][rp['id']] = rp
    return rp


def breach_obligation(ob):
    ob['status'] = 'BREACHED'
    touch(ob)
    return create_repayment_for_breach(ob)


def obligation_base(ob):
    grant = STORE['grants'].get(ob['grant_id'])
    base = Decimal('0')
    if grant is not None and grant['net_salary'] is not None:
        base += grant['net_salary']
    if grant is not None:
        plan = settled_plan(grant['application_id'])
        if plan is not None and plan['final_cost'] is not None:
            base += plan['final_cost']
    return base


def create_grant(app):
    """LeaveGrant born SCHEDULED from an application's proposed window/terms;
    salary figures stay unset until activation."""
    now = clock_now()
    g = {
        'id': new_id(), '_seq': next(SEQ),
        'application_id': app['id'], 'faculty_id': app['applicant_faculty_id'],
        'leave_type': app['leave_type'],
        'start_date': app['proposed_start_date'],
        'end_date': app['proposed_end_date'],
        'duration_semesters': app['requested_duration_semesters'],
        'salary_pct': app['requested_salary_pct'],
        'gross_salary': None, 'fellowship_offset_total': Decimal('0'),
        'net_salary': None, 'actual_months': None,
        'status': 'SCHEDULED',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['grants'][g['id']] = g
    return g


def create_service_obligation(grant, required_months, end_date):
    from util import month_of, prev_month_str
    now = clock_now()
    ob = {
        'id': new_id(), '_seq': next(SEQ),
        'faculty_id': grant['faculty_id'], 'grant_id': grant['id'],
        'required_months': required_months, 'fulfilled_months': 0,
        'last_credited_month': prev_month_str(month_of(end_date)),
        'status': 'IN_PROGRESS',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['obligations'][ob['id']] = ob
    return ob


def create_accomplishment_report(grant, end_date):
    now = clock_now()
    rep = {
        'id': new_id(), '_seq': next(SEQ),
        'grant_id': grant['id'], 'faculty_id': grant['faculty_id'],
        'due_date': end_date + timedelta(days=90),
        'report_text': None, 'submitted_at': None, 'submitted_late': False,
        'decision_comments': None, 'status': 'DUE',
        'created_at': now, 'updated_at': now, 'version': 1,
    }
    STORE['reports'][rep['id']] = rep
    return rep


def settle_confirmed_plan(app, final_cost):
    """CONFIRMED plan -> SETTLED with the given final cost; dept buckets recompute."""
    plan = confirmed_plan(app['id'])
    if plan is not None:
        plan['status'] = 'SETTLED'
        plan['final_cost'] = q2(final_cost)
        touch(plan)
        dept = STORE['departments'].get(plan['department_id'])
        if dept is not None:
            department_mutated(dept)
    app['funding_status'] = 'COVERAGE_SETTLED'
    touch(app)


def curtail_grant(grant, actual_return_date):
    """Shared curtailment mechanics for POST /curtail and ON_LEAVE separation.
    Returns the created ServiceObligation (sabbatical/professional) or None."""
    planned_months = grant['duration_semesters'] * 6
    actual = max(1, min(whole_months_between(grant['start_date'], actual_return_date),
                        planned_months))
    grant['actual_months'] = actual
    grant['end_date'] = actual_return_date
    grant['status'] = 'CURTAILED'
    touch(grant)
    app = STORE['applications'].get(grant['application_id'])
    obligation = None
    if grant['leave_type'] == 'SABBATICAL':
        unused = planned_months - actual
        if unused > 0:
            add_ledger_entry(grant['faculty_id'], 'RESTORE',
                             RESTORE_PER_UNUSED_MONTH * unused)
        if app is not None:
            plan = confirmed_plan(app['id'])
            if plan is not None:
                final = q2(plan['provisional_cost'] * Decimal(actual) / Decimal(planned_months))
                settle_confirmed_plan(app, final)
    if grant['leave_type'] in ('SABBATICAL', 'PROFESSIONAL'):
        obligation = create_service_obligation(grant, actual, actual_return_date)
    fac = STORE['faculty'].get(grant['faculty_id'])
    if fac is not None and fac['status'] == 'ON_LEAVE':
        fac['status'] = 'ACTIVE'
        touch(fac)
    return obligation


# ---------------------------------------------------------------------------
# Serializers
# ---------------------------------------------------------------------------
def ser_department(d):
    return {
        'id': d['id'], 'name': d['name'], 'chair_faculty_id': d['chair_faculty_id'],
        'replacement_pool': money_out(d['replacement_pool']),
        'reserved_amount': money_out(d['reserved_amount']),
        'spent_amount': money_out(d['spent_amount']),
        'available_amount': money_out(d['replacement_pool'] - d['reserved_amount'] - d['spent_amount']),
        'posture': d['posture'],
        'created_at': iso(d['created_at']), 'updated_at': iso(d['updated_at']),
        'version': d['version'],
    }


def ser_faculty(f):
    credit, lifetime = faculty_balances(f['id'])
    return {
        'id': f['id'], 'employee_number': f['employee_number'],
        'full_name': f['full_name'], 'department_id': f['department_id'],
        'academic_rank': f['academic_rank'], 'hire_date': iso(f['hire_date']),
        'annual_base_salary': money_out(f['annual_base_salary']),
        'status': f['status'],
        'lifetime_service_months': lifetime,
        'credit_balance': credit,
        'last_accrued_month': f['last_accrued_month'],
        'created_at': iso(f['created_at']), 'updated_at': iso(f['updated_at']),
        'version': f['version'],
    }


def ser_cycle(c):
    return {
        'id': c['id'], 'name': c['name'], 'academic_year': c['academic_year'],
        'award_quota': c['award_quota'], 'status': c['status'],
        'awarded_count': c['awarded_count'],
        'created_at': iso(c['created_at']), 'updated_at': iso(c['updated_at']),
        'version': c['version'],
    }


def ser_application(a):
    return {
        'id': a['id'], 'applicant_faculty_id': a['applicant_faculty_id'],
        'cycle_id': a['cycle_id'], 'leave_type': a['leave_type'],
        'requested_duration_semesters': a['requested_duration_semesters'],
        'requested_salary_pct': a['requested_salary_pct'],
        'proposed_start_date': iso(a['proposed_start_date']),
        'proposed_end_date': iso(a['proposed_end_date']),
        'proposal_text': a['proposal_text'],
        'status': a['status'], 'funding_status': a['funding_status'],
        'composite_score': money_out(a['composite_score']) if a['composite_score'] is not None else None,
        'submitted_review_count': a['submitted_review_count'],
        'quorum_met': a['quorum_met'],
        'final_rank': a['final_rank'], 'award_outcome': a['award_outcome'],
        'current_coverage_plan_id': a['current_coverage_plan_id'],
        'created_at': iso(a['created_at']), 'updated_at': iso(a['updated_at']),
        'version': a['version'],
    }


def ser_review(r):
    return {
        'id': r['id'], 'application_id': r['application_id'],
        'reviewer_faculty_id': r['reviewer_faculty_id'],
        'scholarly_merit': money_out(r['scholarly_merit']),
        'curriculum_benefit': money_out(r['curriculum_benefit']),
        'feasibility': money_out(r['feasibility']),
        'comments': r['comments'],
        'weighted_total': money_out(r['weighted_total']),
        'status': r['status'],
        'created_at': iso(r['created_at']), 'updated_at': iso(r['updated_at']),
        'version': r['version'],
    }


def ser_plan(p):
    return {
        'id': p['id'], 'application_id': p['application_id'],
        'department_id': p['department_id'],
        'supersedes_plan_id': p['supersedes_plan_id'],
        'courses_to_cover': p['courses_to_cover'],
        'provisional_cost': money_out(p['provisional_cost']),
        'final_cost': money_out(p['final_cost']) if p['final_cost'] is not None else None,
        'status': p['status'],
        'created_at': iso(p['created_at']), 'updated_at': iso(p['updated_at']),
        'version': p['version'],
    }


def ser_grant(g):
    return {
        'id': g['id'], 'application_id': g['application_id'],
        'faculty_id': g['faculty_id'], 'leave_type': g['leave_type'],
        'start_date': iso(g['start_date']), 'end_date': iso(g['end_date']),
        'duration_semesters': g['duration_semesters'],
        'salary_pct': g['salary_pct'],
        'gross_salary': money_out(g['gross_salary']) if g['gross_salary'] is not None else None,
        'fellowship_offset_total': money_out(g['fellowship_offset_total']),
        'net_salary': money_out(g['net_salary']) if g['net_salary'] is not None else None,
        'actual_months': g['actual_months'],
        'status': g['status'],
        'created_at': iso(g['created_at']), 'updated_at': iso(g['updated_at']),
        'version': g['version'],
    }


def ser_fellowship(f):
    return {
        'id': f['id'], 'faculty_id': f['faculty_id'],
        'application_id': f['application_id'], 'name': f['name'],
        'amount': money_out(f['amount']),
        'window_start_date': iso(f['window_start_date']),
        'window_end_date': iso(f['window_end_date']),
        'applied_offset': money_out(f['applied_offset']),
        'status': f['status'],
        'created_at': iso(f['created_at']), 'updated_at': iso(f['updated_at']),
        'version': f['version'],
    }


def ser_obligation(o):
    base = obligation_base(o)
    required = o['required_months']
    if required > 0:
        projected = q2(base * Decimal(required - o['fulfilled_months']) / Decimal(required))
    else:
        projected = Decimal('0')
    return {
        'id': o['id'], 'faculty_id': o['faculty_id'], 'grant_id': o['grant_id'],
        'required_months': o['required_months'],
        'fulfilled_months': o['fulfilled_months'],
        'last_credited_month': o['last_credited_month'],
        'projected_liability': money_out(projected),
        'status': o['status'],
        'created_at': iso(o['created_at']), 'updated_at': iso(o['updated_at']),
        'version': o['version'],
    }


def ser_repayment(r):
    return {
        'id': r['id'], 'obligation_id': r['obligation_id'],
        'faculty_id': r['faculty_id'],
        'base_amount': money_out(r['base_amount']),
        'fulfilled_months_at_breach': r['fulfilled_months_at_breach'],
        'monthly_forgiveness': money_out(r['monthly_forgiveness']),
        'amount_owed': money_out(r['amount_owed']),
        'amount_outstanding': money_out(r['amount_outstanding']),
        'due_date': iso(r['due_date']),
        'status': r['status'],
        'created_at': iso(r['created_at']), 'updated_at': iso(r['updated_at']),
        'version': r['version'],
    }


def ser_payment(p):
    return {
        'id': p['id'], 'repayment_id': p['repayment_id'],
        'amount': money_out(p['amount']),
        'resulting_outstanding': money_out(p['resulting_outstanding']),
        'created_at': iso(p['created_at']),
    }


def ser_report(r):
    return {
        'id': r['id'], 'grant_id': r['grant_id'], 'faculty_id': r['faculty_id'],
        'due_date': iso(r['due_date']),
        'report_text': r['report_text'],
        'submitted_at': iso(r['submitted_at']) if r['submitted_at'] is not None else None,
        'submitted_late': r['submitted_late'],
        'decision_comments': r['decision_comments'],
        'status': r['status'],
        'created_at': iso(r['created_at']), 'updated_at': iso(r['updated_at']),
        'version': r['version'],
    }


def ser_ledger_entry(e):
    return {
        'id': e['id'], 'faculty_id': e['faculty_id'],
        'entry_type': e['entry_type'], 'credits_delta': e['credits_delta'],
        'affects_lifetime': e['affects_lifetime'],
        'month': e['month'], 'note': e['note'],
        'created_at': iso(e['created_at']),
    }
