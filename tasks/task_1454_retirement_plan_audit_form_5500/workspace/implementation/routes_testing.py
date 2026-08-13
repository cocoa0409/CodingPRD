"""Nondiscrimination test results, late-deposit assessments, findings, corrective actions."""
from decimal import Decimal

from flask import Blueprint, g, request

from auth import roles_allowed
from dates import parse_date
from domain import (action_participant_id, correction_deadline,
                    create_auto_finding, is_deposit_action, lost_earnings_cents,
                    recompute_balance, recompute_posture, round_cents,
                    run_adp_test, run_coverage_test, excise_threshold,
                    actions_of_finding)
from envelope import success_list, success_object
from errors import (ERR_ASSESSMENT_NOT_CONFIRMED, ERR_CORRECTION_NOT_ALLOWED,
                    ERR_DISTRIBUTION_EXCEEDS_BALANCE, ERR_INVALID_REQUEST,
                    ERR_INVALID_STATE, ERR_NOT_FOUND, ERR_SOD,
                    ERR_STALE_ENGAGEMENT_VERSION, ERR_WAIVER_NOT_ALLOWED,
                    raise_err)
from store import base_fields, public, store, touch
from validate import (get_body, opt_enum, opt_str, paginate, parse_bool_param,
                      parse_pagination, req_date, req_enum, req_int, req_str,
                      sorted_created)

bp = Blueprint('testing', __name__)

TEST_TYPES = ('ADP', 'ACP', 'COVERAGE_410B')
TEST_METHODS = ('CURRENT_YEAR', 'PRIOR_YEAR')
CATEGORIES = ('LATE_REMITTANCE', 'NONDISCRIMINATION_FAILURE', 'RECONCILIATION_BREAK',
              'FEE_DISCLOSURE_GAP', 'FILING_DEFECT')
SEVERITIES = ('HIGH', 'MEDIUM', 'LOW')
ACTION_TYPES = ('LOST_EARNINGS_DEPOSIT', 'CORRECTIVE_DISTRIBUTION', 'QNEC_CONTRIBUTION',
                'QMAC_CONTRIBUTION', 'FEE_REDISCLOSURE')
VARIANTS = ('VFCP', 'EPCRS')


def get_test_result_or_404(tid):
    t = store.test_results.get(tid)
    if t is None:
        raise_err(ERR_NOT_FOUND, 'Test result %s not found' % tid)
    return t


def get_assessment_or_404(aid):
    a = store.assessments.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, 'Assessment %s not found' % aid)
    return a


def get_finding_or_404(fid):
    f = store.findings.get(fid)
    if f is None:
        raise_err(ERR_NOT_FOUND, 'Finding %s not found' % fid)
    return f


def get_action_or_404(aid):
    a = store.corrective_actions.get(aid)
    if a is None:
        raise_err(ERR_NOT_FOUND, 'Corrective action %s not found' % aid)
    return a


# --- test results ----------------------------------------------------------------
@bp.route('/plan-audit/test-results', methods=['POST'])
@roles_allowed('TPASpecialist')
def create_test_result():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    test_type = req_enum(body, 'test_type', TEST_TYPES)
    testing_method = opt_enum(body, 'testing_method', TEST_METHODS, 'CURRENT_YEAR')
    expected_version = req_int(body, 'expected_engagement_version')
    eng = store.engagements.get(engagement_id)
    if eng is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    if expected_version != eng['version']:
        raise_err(ERR_STALE_ENGAGEMENT_VERSION,
                  'Engagement version has advanced; re-read before computing a test')
    if test_type == 'COVERAGE_410B':
        computed = run_coverage_test(eng)
    else:
        computed = run_adp_test(eng, test_type)
    t = base_fields()
    t.update({
        'engagement_id': engagement_id,
        'test_type': test_type,
        'testing_method': testing_method,
        'hce_avg_pct': computed['hce_avg_pct'],
        'nhce_avg_pct': computed['nhce_avg_pct'],
        'max_allowed_hce_pct': computed['max_allowed_hce_pct'],
        'coverage_ratio_pct': computed['coverage_ratio_pct'],
        'result': computed['result'],
        'excess_contribution_cents': computed['excess_contribution_cents'],
        'correction_deadline': correction_deadline(eng).isoformat(),
        'is_current_official': False,
        'status': 'COMPUTED',
        '_refunds': computed['_refunds'],
    })
    store.test_results[t['id']] = t
    touch(eng)  # creating a result increments the engagement version (OCC currency)
    return success_object(public(t), status=201)


@bp.route('/plan-audit/test-results', methods=['GET'])
@roles_allowed('Any')
def list_test_results():
    limit, offset = parse_pagination()
    items = sorted_created(store.test_results.values())
    for param, field in (('engagement_id', 'engagement_id'),
                         ('test_type', 'test_type'), ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [t for t in items if t.get(field) == v]
    official = parse_bool_param('is_current_official')
    if official is not None:
        items = [t for t in items if t['is_current_official'] == official]
    page, total = paginate(items, limit, offset)
    return success_list([public(t) for t in page], total, limit, offset)


@bp.route('/plan-audit/test-results/<tid>', methods=['GET'])
@roles_allowed('Any')
def get_test_result(tid):
    return success_object(public(get_test_result_or_404(tid)))


@bp.route('/plan-audit/test-results/<tid>/finalize', methods=['POST'])
@roles_allowed('PlanAuditor')
def finalize_test_result(tid):
    t = get_test_result_or_404(tid)
    if t['status'] != 'COMPUTED':
        raise_err(ERR_INVALID_STATE, 'Only a COMPUTED test result can be finalized')
    # Supersede the prior official FINAL result for (engagement, test_type).
    for other in store.test_results.values():
        if (other['engagement_id'] == t['engagement_id']
                and other['test_type'] == t['test_type']
                and other['status'] == 'FINAL'):
            other['status'] = 'SUPERSEDED'
            other['is_current_official'] = False
            touch(other)
    t['status'] = 'FINAL'
    t['is_current_official'] = True
    touch(t)
    if t['result'] == 'FAIL':
        create_auto_finding(t['engagement_id'], 'TEST_FAILURE_AUTO',
                            'NONDISCRIMINATION_FAILURE', 'HIGH',
                            test_result_id=t['id'])
    else:
        eng = store.engagements.get(t['engagement_id'])
        if eng is not None:
            recompute_posture(eng)
    return success_object(public(t))


# --- late contribution assessments -------------------------------------------------
@bp.route('/plan-audit/late-contribution-assessments', methods=['GET'])
@roles_allowed('Any')
def list_assessments():
    limit, offset = parse_pagination()
    items = sorted_created(store.assessments.values())
    for param, field in (('engagement_id', 'engagement_id'),
                         ('contribution_id', 'contribution_id'), ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    page, total = paginate(items, limit, offset)
    return success_list([public(a) for a in page], total, limit, offset)


@bp.route('/plan-audit/late-contribution-assessments/<aid>', methods=['GET'])
@roles_allowed('Any')
def get_assessment(aid):
    return success_object(public(get_assessment_or_404(aid)))


@bp.route('/plan-audit/late-contribution-assessments/<aid>/confirm', methods=['POST'])
@roles_allowed('PlanAuditor')
def confirm_assessment(aid):
    a = get_assessment_or_404(aid)
    if a['status'] != 'ASSESSED':
        raise_err(ERR_INVALID_STATE, 'Only an ASSESSED assessment can be confirmed')
    a['status'] = 'CONFIRMED'
    touch(a)
    create_auto_finding(a['engagement_id'], 'LATE_DEPOSIT_AUTO', 'LATE_REMITTANCE',
                        a['severity_hint'], contribution_id=a['contribution_id'])
    return success_object(public(a))


@bp.route('/plan-audit/late-contribution-assessments/<aid>/dismiss', methods=['POST'])
@roles_allowed('PlanAuditor')
def dismiss_assessment(aid):
    a = get_assessment_or_404(aid)
    if a['status'] != 'ASSESSED':
        raise_err(ERR_INVALID_STATE, 'Only an ASSESSED assessment can be dismissed')
    body = get_body()
    req_str(body, 'reason')
    a['status'] = 'DISMISSED'
    touch(a)
    return success_object(public(a))


# --- findings ----------------------------------------------------------------------
@bp.route('/plan-audit/findings', methods=['POST'])
@roles_allowed('PlanAuditor')
def create_finding():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    category = req_enum(body, 'category', CATEGORIES)
    severity = req_enum(body, 'severity', SEVERITIES)
    description = req_str(body, 'description')
    contribution_id = opt_str(body, 'contribution_id')
    test_result_id = opt_str(body, 'test_result_id')
    if store.engagements.get(engagement_id) is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    if contribution_id is not None:
        c = store.contributions.get(contribution_id)
        if c is None or c['engagement_id'] != engagement_id:
            raise_err(ERR_NOT_FOUND, 'Contribution %s not found in this engagement'
                      % contribution_id)
    if test_result_id is not None:
        t = store.test_results.get(test_result_id)
        if t is None or t['engagement_id'] != engagement_id:
            raise_err(ERR_NOT_FOUND, 'Test result %s not found in this engagement'
                      % test_result_id)
    f = base_fields()
    f.update({
        'engagement_id': engagement_id,
        'source': 'AUDITOR_MANUAL',
        'category': category,
        'severity': severity,
        'description': description,
        'contribution_id': contribution_id,
        'test_result_id': test_result_id,
        'status': 'OPEN',
    })
    store.findings[f['id']] = f
    eng = store.engagements.get(engagement_id)
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(f), status=201)


@bp.route('/plan-audit/findings', methods=['GET'])
@roles_allowed('Any')
def list_findings():
    limit, offset = parse_pagination()
    items = sorted_created(store.findings.values())
    for param, field in (('engagement_id', 'engagement_id'), ('status', 'status'),
                         ('severity', 'severity'), ('category', 'category'),
                         ('contribution_id', 'contribution_id'),
                         ('test_result_id', 'test_result_id')):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(field) == v]
    page, total = paginate(items, limit, offset)
    return success_list([public(f) for f in page], total, limit, offset)


@bp.route('/plan-audit/findings/<fid>', methods=['GET'])
@roles_allowed('Any')
def get_finding(fid):
    return success_object(public(get_finding_or_404(fid)))


@bp.route('/plan-audit/findings/<fid>/acknowledge', methods=['POST'])
@roles_allowed('SponsorAdmin')
def acknowledge_finding(fid):
    f = get_finding_or_404(fid)
    if f['status'] != 'OPEN':
        raise_err(ERR_INVALID_STATE, 'Only an OPEN finding can be acknowledged')
    f['status'] = 'ACKNOWLEDGED'
    touch(f)
    return success_object(public(f))


@bp.route('/plan-audit/findings/<fid>/waive', methods=['POST'])
@roles_allowed('EngagementManager')
def waive_finding(fid):
    f = get_finding_or_404(fid)
    if f['status'] not in ('OPEN', 'ACKNOWLEDGED'):
        raise_err(ERR_INVALID_STATE, 'Finding in %s cannot be waived' % f['status'])
    if f['severity'] == 'HIGH':
        raise_err(ERR_WAIVER_NOT_ALLOWED, 'HIGH severity findings cannot be waived')
    if f['status'] == 'OPEN':
        # Waiving from OPEN requires a non-empty justification.
        body = get_body()
        req_str(body, 'justification')
    f['status'] = 'WAIVED'
    touch(f)
    eng = store.engagements.get(f['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(f))


@bp.route('/plan-audit/findings/<fid>/verify_close', methods=['POST'])
@roles_allowed('PlanAuditor')
def verify_close_finding(fid):
    f = get_finding_or_404(fid)
    if f['status'] != 'CORRECTED':
        raise_err(ERR_INVALID_STATE, 'Only a CORRECTED finding can be verified closed')
    for a in actions_of_finding(fid):
        if a['status'] != 'VOIDED' and a['status'] != 'VERIFIED':
            raise_err(ERR_INVALID_STATE,
                      'All non-voided corrective actions must be VERIFIED')
    f['status'] = 'VERIFIED_CLOSED'
    touch(f)
    eng = store.engagements.get(f['engagement_id'])
    if eng is not None:
        recompute_posture(eng)
    return success_object(public(f))


# --- corrective actions --------------------------------------------------------------
@bp.route('/plan-audit/corrective-actions', methods=['POST'])
@roles_allowed('SponsorAdmin')
def create_action():
    body = get_body()
    engagement_id = req_str(body, 'engagement_id')
    finding_id = req_str(body, 'finding_id')
    action_type = req_enum(body, 'action_type', ACTION_TYPES)
    principal = req_int(body, 'principal_cents', 1)
    planned = req_date(body, 'planned_execution_date')
    variant = opt_enum(body, 'earnings_variant', VARIANTS, 'VFCP')
    participant_id = opt_str(body, 'participant_id')
    assessment_id = opt_str(body, 'assessment_id')
    if store.engagements.get(engagement_id) is None:
        raise_err(ERR_NOT_FOUND, 'Engagement %s not found' % engagement_id)
    finding = store.findings.get(finding_id)
    if finding is None or finding['engagement_id'] != engagement_id:
        raise_err(ERR_NOT_FOUND, 'Finding %s not found in this engagement' % finding_id)
    assessment = None
    if action_type == 'LOST_EARNINGS_DEPOSIT':
        if assessment_id is None:
            raise_err(ERR_INVALID_REQUEST,
                      'assessment_id is required for LOST_EARNINGS_DEPOSIT')
        assessment = store.assessments.get(assessment_id)
        if assessment is None or assessment['engagement_id'] != engagement_id:
            raise_err(ERR_NOT_FOUND, 'Assessment %s not found in this engagement'
                      % assessment_id)
    if action_type in ('CORRECTIVE_DISTRIBUTION', 'QNEC_CONTRIBUTION'):
        if participant_id is None:
            raise_err(ERR_INVALID_REQUEST,
                      'participant_id is required for %s' % action_type)
    if participant_id is not None:
        p = store.participants.get(participant_id)
        if p is None or p['engagement_id'] != engagement_id:
            raise_err(ERR_NOT_FOUND, 'Participant %s not found in this engagement'
                      % participant_id)
    if finding['status'] not in ('OPEN', 'ACKNOWLEDGED', 'CORRECTION_IN_PROGRESS'):
        raise_err(ERR_CORRECTION_NOT_ALLOWED,
                  'Cannot propose a corrective action against a %s finding'
                  % finding['status'])
    if action_type == 'LOST_EARNINGS_DEPOSIT' and assessment['status'] != 'CONFIRMED':
        raise_err(ERR_ASSESSMENT_NOT_CONFIRMED,
                  'Referenced assessment is not CONFIRMED')
    earnings = 0
    if action_type == 'LOST_EARNINGS_DEPOSIT':
        earnings = lost_earnings_cents(assessment['amount_cents'],
                                       parse_date(assessment['payroll_date']),
                                       parse_date(assessment['deposit_date']),
                                       planned, variant)
    a = base_fields()
    a.update({
        'engagement_id': engagement_id,
        'finding_id': finding_id,
        'assessment_id': assessment_id,
        'participant_id': participant_id,
        'action_type': action_type,
        'principal_cents': principal,
        'earnings_variant': variant,
        'earnings_cents': earnings,
        'excise_tax_cents': 0,
        'total_amount_cents': principal + earnings,
        'planned_execution_date': planned.isoformat(),
        'executed_date': None,
        'proposed_by_user_id': g.user_id,
        'approved_by_user_id': None,
        'status': 'PROPOSED',
    })
    store.corrective_actions[a['id']] = a
    return success_object(public(a), status=201)


@bp.route('/plan-audit/corrective-actions', methods=['GET'])
@roles_allowed('Any')
def list_actions():
    limit, offset = parse_pagination()
    items = sorted_created(store.corrective_actions.values())
    for param, field in (('engagement_id', 'engagement_id'), ('finding_id', 'finding_id'),
                         ('participant_id', 'participant_id'),
                         ('assessment_id', 'assessment_id'), ('status', 'status')):
        v = request.args.get(param)
        if v is not None:
            items = [a for a in items if a.get(field) == v]
    page, total = paginate(items, limit, offset)
    return success_list([public(a) for a in page], total, limit, offset)


@bp.route('/plan-audit/corrective-actions/<aid>', methods=['GET'])
@roles_allowed('Any')
def get_action(aid):
    return success_object(public(get_action_or_404(aid)))


@bp.route('/plan-audit/corrective-actions/<aid>/approve', methods=['POST'])
@roles_allowed('EngagementManager')
def approve_action(aid):
    a = get_action_or_404(aid)
    if a['status'] != 'PROPOSED':
        raise_err(ERR_INVALID_STATE, 'Only a PROPOSED action can be approved')
    finding = store.findings.get(a['finding_id'])
    if finding is None or finding['status'] not in ('ACKNOWLEDGED', 'CORRECTION_IN_PROGRESS'):
        raise_err(ERR_CORRECTION_NOT_ALLOWED,
                  'Finding must be ACKNOWLEDGED or CORRECTION_IN_PROGRESS to approve')
    if g.user_id == a['proposed_by_user_id']:
        raise_err(ERR_SOD, 'Approver must differ from proposer')
    a['approved_by_user_id'] = g.user_id
    a['status'] = 'APPROVED'
    touch(a)
    if finding['status'] == 'ACKNOWLEDGED':
        finding['status'] = 'CORRECTION_IN_PROGRESS'
        touch(finding)
    return success_object(public(a))


def _maybe_close_finding(finding):
    """Finding -> CORRECTED when all linked non-REJECTED/non-VOIDED actions are
    EXECUTED or VERIFIED, with at least one such action."""
    actions = [a for a in actions_of_finding(finding['id'])
               if a['status'] not in ('REJECTED', 'VOIDED')]
    if actions and all(a['status'] in ('EXECUTED', 'VERIFIED') for a in actions):
        if finding['status'] == 'CORRECTION_IN_PROGRESS':
            finding['status'] = 'CORRECTED'
            touch(finding)
            eng = store.engagements.get(finding['engagement_id'])
            if eng is not None:
                recompute_posture(eng)


@bp.route('/plan-audit/corrective-actions/<aid>/execute', methods=['POST'])
@roles_allowed('SponsorAdmin')
def execute_action(aid):
    a = get_action_or_404(aid)
    if a['status'] != 'APPROVED':
        raise_err(ERR_INVALID_STATE, 'Only an APPROVED action can be executed')
    eng = store.engagements.get(a['engagement_id'])
    participant = None
    pid = action_participant_id(a)
    if pid is not None:
        participant = store.participants.get(pid)
    if a['action_type'] == 'CORRECTIVE_DISTRIBUTION':
        if participant is None:
            raise_err(ERR_INVALID_REQUEST, 'Distribution requires a participant')
        if a['total_amount_cents'] > participant['account_balance_cents']:
            raise_err(ERR_DISTRIBUTION_EXCEEDS_BALANCE,
                      'Distribution total exceeds the participant account balance')
    a['executed_date'] = store.clock_date().isoformat()
    if a['action_type'] == 'CORRECTIVE_DISTRIBUTION' and eng is not None:
        if store.clock_date() > excise_threshold(eng):
            a['excise_tax_cents'] = round_cents(
                Decimal(a['principal_cents']) * Decimal('0.10'))
        else:
            a['excise_tax_cents'] = 0
    a['status'] = 'EXECUTED'
    touch(a)
    if participant is not None and (is_deposit_action(a)
                                    or a['action_type'] == 'CORRECTIVE_DISTRIBUTION'):
        recompute_balance(participant)
        touch(participant)
    # Cascade: linked assessment -> CORRECTED; contribution timeliness -> CORRECTED.
    if a.get('assessment_id'):
        asmt = store.assessments.get(a['assessment_id'])
        if asmt is not None and asmt['status'] == 'CONFIRMED':
            asmt['status'] = 'CORRECTED'
            touch(asmt)
        contrib = store.contributions.get(asmt['contribution_id']) if asmt else None
        if contrib is not None and contrib['timeliness_status'] == 'LATE':
            contrib['timeliness_status'] = 'CORRECTED'
            touch(contrib)
    finding = store.findings.get(a['finding_id'])
    if finding is not None:
        _maybe_close_finding(finding)
    return success_object(public(a))


@bp.route('/plan-audit/corrective-actions/<aid>/verify', methods=['POST'])
@roles_allowed('PlanAuditor')
def verify_action(aid):
    a = get_action_or_404(aid)
    if a['status'] != 'EXECUTED':
        raise_err(ERR_INVALID_STATE, 'Only an EXECUTED action can be verified')
    a['status'] = 'VERIFIED'
    touch(a)
    return success_object(public(a))


@bp.route('/plan-audit/corrective-actions/<aid>/void', methods=['POST'])
@roles_allowed('EngagementManager')
def void_action(aid):
    a = get_action_or_404(aid)
    body = get_body()
    reason = req_str(body, 'reason')
    if a['status'] == 'PROPOSED':
        if reason.startswith('REJECT:'):
            a['status'] = 'REJECTED'
            touch(a)
            return success_object(public(a))
        raise_err(ERR_INVALID_STATE,
                  'A PROPOSED action can only be voided with a REJECT: reason')
    if a['status'] not in ('APPROVED', 'EXECUTED'):
        raise_err(ERR_INVALID_STATE, 'Action in %s cannot be voided' % a['status'])
    was_executed = a['status'] == 'EXECUTED'
    a['status'] = 'VOIDED'
    touch(a)
    if was_executed:
        # Compensating reversal: recompute excludes VOIDED actions exactly.
        pid = action_participant_id(a)
        participant = store.participants.get(pid) if pid else None
        if participant is not None:
            recompute_balance(participant)
            touch(participant)
        # Linked finding reopens: CORRECTED -> CORRECTION_IN_PROGRESS.
        finding = store.findings.get(a['finding_id'])
        if finding is not None and finding['status'] == 'CORRECTED':
            finding['status'] = 'CORRECTION_IN_PROGRESS'
            touch(finding)
            eng = store.engagements.get(finding['engagement_id'])
            if eng is not None:
                recompute_posture(eng)
        # Linked LateContributionAssessment stays CORRECTED (no revert).
    return success_object(public(a))
