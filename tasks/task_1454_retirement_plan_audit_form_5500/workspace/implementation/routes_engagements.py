"""Engagement lifecycle routes."""
from flask import Blueprint, g

from auth import roles_allowed
from dates import business_days_between, parse_date
from domain import (any_fee_reportable, contributions_of, create_auto_finding,
                    lost_earnings_cents, recompute_participant_count,
                    recompute_posture)
from envelope import success_list, success_object
from errors import (ERR_INVALID_REQUEST, ERR_INVALID_STATE, ERR_NOT_FOUND,
                    ERR_OPEN_FINDINGS_REMAIN, ERR_PARTICIPANT_COUNT_REQUIRED,
                    ERR_PLAN_YEAR_OVERLAP, ERR_TEST_NOT_FINAL, raise_err)
from store import base_fields, public, store, touch
from validate import (get_body, opt_bool, paginate, parse_pagination, req_date,
                      req_enum, req_str, sorted_created)

bp = Blueprint('engagements', __name__)

PLAN_TYPES = ('DC', 'DB', 'DC_401K')
FUNDING = ('TRUST', 'INSURANCE', 'SPLIT')
PRIOR_SCHED = ('H', 'I', 'NONE_FIRST_YEAR')


def get_engagement_or_404(eid):
    eng = store.engagements.get(eid)
    if eng is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % eid)
    return eng


def _transition(eng, from_status, to_status):
    if eng['status'] != from_status:
        raise_err(ERR_INVALID_STATE,
                  'Engagement in %s cannot move to %s' % (eng['status'], to_status))
    eng['status'] = to_status
    touch(eng)
    return eng


@bp.route('/plan-audit/engagements', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_engagement():
    body = get_body()
    sponsor_ein = req_str(body, 'sponsor_ein')
    plan_number = req_str(body, 'plan_number')
    plan_name = req_str(body, 'plan_name')
    py_start = req_date(body, 'plan_year_start')
    py_end = req_date(body, 'plan_year_end')
    plan_type = req_enum(body, 'plan_type', PLAN_TYPES)
    funding = req_enum(body, 'funding_arrangement', FUNDING)
    prior = req_enum(body, 'prior_year_schedule_type', PRIOR_SCHED)
    election = opt_bool(body, 'use_80120_election', False)
    if py_end <= py_start:
        raise_err(ERR_INVALID_REQUEST, 'plan_year_end must be after plan_year_start')
    for other in store.engagements.values():
        if (other['sponsor_ein'] == sponsor_ein and other['plan_number'] == plan_number):
            o_start, o_end = parse_date(other['plan_year_start']), parse_date(other['plan_year_end'])
            if py_start < o_end and o_start < py_end:  # half-open overlap; adjacency allowed
                raise_err(ERR_PLAN_YEAR_OVERLAP,
                          'Plan year overlaps an existing engagement for this plan')
    eng = base_fields()
    eng.update({
        'sponsor_ein': sponsor_ein,
        'plan_number': plan_number,
        'plan_name': plan_name,
        'plan_year_start': py_start.isoformat(),
        'plan_year_end': py_end.isoformat(),
        'plan_type': plan_type,
        'funding_arrangement': funding,
        'prior_year_schedule_type': prior,
        'use_80120_election': election,
        'status': 'DRAFT',
        'participant_count_beginning': None,
        'audit_required': None,
        'required_schedule_type': None,
        'remittance_standard_days': None,
        'auditor_report_ref': None,
        'posture': 'ON_TRACK',
    })
    store.engagements[eng['id']] = eng
    return success_object(public(eng), status=201)


@bp.route('/plan-audit/engagements', methods=['GET'])
@roles_allowed('Any')
def list_engagements():
    from flask import request
    limit, offset = parse_pagination()
    items = sorted_created(store.engagements.values())
    sponsor = request.args.get('sponsor_ein')
    status = request.args.get('status')
    posture = request.args.get('posture')
    if sponsor is not None:
        items = [e for e in items if e['sponsor_ein'] == sponsor]
    if status is not None:
        items = [e for e in items if e['status'] == status]
    if posture is not None:
        items = [e for e in items if e['posture'] == posture]
    page, total = paginate(items, limit, offset)
    return success_list([public(e) for e in page], total, limit, offset)


@bp.route('/plan-audit/engagements/<eid>', methods=['GET'])
@roles_allowed('Any')
def get_engagement(eid):
    eng = get_engagement_or_404(eid)
    recompute_posture(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/activate', methods=['POST'])
@roles_allowed('SponsorAdmin')
def activate(eid):
    eng = get_engagement_or_404(eid)
    _transition(eng, 'DRAFT', 'DATA_COLLECTION')
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/begin_testing', methods=['POST'])
@roles_allowed('TPASpecialist')
def begin_testing(eid):
    eng = get_engagement_or_404(eid)
    _transition(eng, 'DATA_COLLECTION', 'TESTING')
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/begin_fieldwork', methods=['POST'])
@roles_allowed('PlanAuditor')
def begin_fieldwork(eid):
    eng = get_engagement_or_404(eid)
    if eng['status'] != 'TESTING':
        raise_err(ERR_INVALID_STATE, 'Engagement must be in TESTING to begin fieldwork')
    if eng['participant_count_beginning'] is None:
        raise_err(ERR_PARTICIPANT_COUNT_REQUIRED,
                  'Participant count must be computed before fieldwork')
    eng['status'] = 'FIELDWORK'
    touch(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/attach_audit_report', methods=['POST'])
@roles_allowed('PlanAuditor')
def attach_audit_report(eid):
    eng = get_engagement_or_404(eid)
    body = get_body()
    eng['auditor_report_ref'] = req_str(body, 'auditor_report_ref')
    touch(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/issue_report', methods=['POST'])
@roles_allowed('PlanAuditor')
def issue_report(eid):
    eng = get_engagement_or_404(eid)
    if eng['status'] != 'FIELDWORK':
        raise_err(ERR_INVALID_STATE, 'Engagement must be in FIELDWORK to issue the report')
    if eng['participant_count_beginning'] is None:
        raise_err(ERR_PARTICIPANT_COUNT_REQUIRED,
                  'Participant count must be computed before issuing the report')
    for t in store.test_results.values():
        if t['engagement_id'] == eid and t['status'] == 'COMPUTED':
            raise_err(ERR_TEST_NOT_FINAL,
                      'A test result is still COMPUTED; finalize it before issuing the report')
    eng['status'] = 'REPORT_ISSUED'
    touch(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/reopen_data_collection', methods=['POST'])
@roles_allowed('EngagementManager')
def reopen_data_collection(eid):
    eng = get_engagement_or_404(eid)
    _transition(eng, 'FIELDWORK', 'DATA_COLLECTION')
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/reopen_fieldwork', methods=['POST'])
@roles_allowed('EngagementManager')
def reopen_fieldwork(eid):
    eng = get_engagement_or_404(eid)
    _transition(eng, 'REPORT_ISSUED', 'FIELDWORK')
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/complete', methods=['POST'])
@roles_allowed('EngagementManager')
def complete(eid):
    eng = get_engagement_or_404(eid)
    if eng['status'] != 'REPORT_ISSUED':
        raise_err(ERR_INVALID_STATE, 'Engagement must be in REPORT_ISSUED to complete')
    # Pinned precondition order: findings sweep FIRST, filing-status check SECOND.
    for f in store.findings.values():
        if (f['engagement_id'] == eid and f['status'] in
                ('OPEN', 'ACKNOWLEDGED', 'CORRECTION_IN_PROGRESS', 'CORRECTED')):
            raise_err(ERR_OPEN_FINDINGS_REMAIN,
                      'Findings remain that are not VERIFIED_CLOSED or WAIVED')
    from domain import filing_of
    filing = filing_of(eid)
    if filing is not None and filing['status'] != 'ACCEPTED':
        raise_err(ERR_INVALID_STATE,
                  'The engagement filing must be ACCEPTED before completion')
    eng['status'] = 'COMPLETED'
    touch(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/recompute_participant_count', methods=['POST'])
@roles_allowed('TPASpecialist')
def recompute_count(eid):
    eng = get_engagement_or_404(eid)
    if eng['status'] not in ('DRAFT', 'DATA_COLLECTION', 'TESTING', 'FIELDWORK'):
        raise_err(ERR_INVALID_STATE,
                  'Participant count may be recomputed only before report issuance')
    recompute_participant_count(eng)
    touch(eng)
    return success_object(public(eng))


@bp.route('/plan-audit/engagements/<eid>/late-deposit-scan', methods=['POST'])
@roles_allowed('TPASpecialist', 'PlanAuditor')
def late_deposit_scan(eid):
    eng = get_engagement_or_404(eid)
    std = eng['remittance_standard_days']
    if std is None:
        raise_err(ERR_PARTICIPANT_COUNT_REQUIRED,
                  'Participant count (and remittance standard) must be computed first')
    for c in sorted_created(contributions_of(eid)):
        if c['timeliness_status'] not in ('PENDING', 'ON_TIME'):
            continue
        elapsed = business_days_between(parse_date(c['payroll_date']),
                                        parse_date(c['deposit_date']))
        if elapsed > std:
            c['timeliness_status'] = 'LATE'
            c['business_days_elapsed'] = elapsed
            touch(c)
            existing = [a for a in store.assessments.values()
                        if a['contribution_id'] == c['id']]
            if not existing:
                asmt = base_fields()
                days_late = elapsed - std
                asmt.update({
                    'engagement_id': eid,
                    'contribution_id': c['id'],
                    'payroll_date': c['payroll_date'],
                    'deposit_date': c['deposit_date'],
                    'amount_cents': c['amount_cents'],
                    'business_days_late': days_late,
                    'lost_earnings_vfcp_cents': lost_earnings_cents(
                        c['amount_cents'], parse_date(c['payroll_date']),
                        parse_date(c['deposit_date']), store.clock_date(), 'VFCP'),
                    'severity_hint': 'HIGH' if days_late > 10 else 'MEDIUM',
                    'status': 'ASSESSED',
                })
                store.assessments[asmt['id']] = asmt
        elif c['timeliness_status'] == 'PENDING':
            c['timeliness_status'] = 'ON_TIME'
            c['business_days_elapsed'] = elapsed
            touch(c)
    items = sorted_created(a for a in store.assessments.values()
                           if a['engagement_id'] == eid)
    return success_list([public(a) for a in items], len(items), len(items) or 10, 0)
    # NOTE: response_type stays "array"; pagination meta reflects the full set.


@bp.route('/plan-audit/engagements/<eid>/compute-fee-disclosure', methods=['POST'])
@roles_allowed('TPASpecialist')
def compute_fee_disclosure(eid):
    eng = get_engagement_or_404(eid)
    body = get_body()
    filing_id = req_str(body, 'filing_id')
    filing = store.filings.get(filing_id)
    if filing is None or filing['engagement_id'] != eid:
        raise_err(ERR_NOT_FOUND, 'Filing %s not found for this engagement' % filing_id)
    providers = sorted({f['provider_name'] for f in store.fees.values()
                        if f['engagement_id'] == eid})
    entry_ids = []
    reportable_count = 0
    reportable_total = 0
    for name in providers:
        fee_rows = sorted_created(f for f in store.fees.values()
                                  if f['engagement_id'] == eid and f['provider_name'] == name)
        total = sum(f['amount_cents'] for f in fee_rows
                    if f['compensation_type'] in ('DIRECT', 'INDIRECT'))
        if total < 500000:
            continue
        reportable_count += 1
        reportable_total += total
        fee_ids = [f['id'] for f in fee_rows if f['compensation_type'] in ('DIRECT', 'INDIRECT')]
        line_item = 'C-1c %s' % name
        existing = None
        for se in store.schedule_entries.values():
            if (se['filing_id'] == filing_id and se['schedule_type'] == 'C'
                    and se['line_item'] == line_item):
                existing = se
                break
        if existing is not None:
            existing['amount_cents'] = total
            existing['payload'] = {'service_provider_fee_ids': fee_ids}
            touch(existing)
            entry_ids.append(existing['id'])
        else:
            se = base_fields()
            se.update({
                'filing_id': filing_id,
                'schedule_type': 'C',
                'line_item': line_item,
                'amount_cents': total,
                'payload': {'service_provider_fee_ids': fee_ids},
                'status': 'DRAFT',
            })
            store.schedule_entries[se['id']] = se
            entry_ids.append(se['id'])
    return success_object({
        'reportable_provider_count': reportable_count,
        'reportable_total_cents': reportable_total,
        'schedule_entry_ids': entry_ids,
    })
