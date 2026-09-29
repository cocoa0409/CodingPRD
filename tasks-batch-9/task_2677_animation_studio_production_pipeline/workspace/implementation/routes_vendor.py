"""Outsourcing partners, packages and vendor QC."""
from flask import Blueprint, g

from calc import (D, SECURITY_LEVELS, budget_position, by_created, num, package_out,
                  partner_out, partner_quality_score, recompute_production,
                  spend_ceiling_cents)
from flows import (approve_task, enter_retake, fk_lookup, get_package, get_partner,
                   get_production, get_task, package_tasks, reconcile_production,
                   reconcile_tasks, require_phase, tasks_linked_to)
from helpers import (ALL_READ, ApiError, COORDINATOR, PARTNER_REP, READ_WITH_PARTNER,
                     SUPERVISOR, arg, authenticate, body_json, get_bool, get_enum,
                     get_int, get_number, get_str, get_str_array, paginate, success,
                     validation_error)
from store import base_row, db, now, touch

bp = Blueprint('vendor', __name__)

PARTNER_STATUSES = ('ONBOARDING', 'APPROVED', 'SUSPENDED')
SECURITY_TIERS = ('TIER1', 'TIER2', 'TIER3')
NOT_WRAPPED = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE', 'DELIVERY')
RECALLABLE = ('ISSUED', 'IN_PROGRESS', 'DELIVERED')


def tier_ordinal(level):
    return SECURITY_LEVELS.index(level)


# ---------------------------------------------------------------------- partners
@bp.route('/studio/outsource-partners', methods=['POST'])
def create_partner():
    authenticate((COORDINATOR,))
    body = body_json()
    legal_name = get_str(body, 'legal_name', min_len=1)
    level = get_enum(body, 'security_certification_level', SECURITY_LEVELS,
                     required=False, default='NONE')
    mfa = get_bool(body, 'mfa_enforced', required=False, default=False)
    watermark = get_bool(body, 'watermark_required', required=False, default=True)
    partner = base_row()
    partner.update({
        'legal_name': legal_name,
        'security_certification_level': level,
        'mfa_enforced': mfa,
        'watermark_required': watermark,
        'status': 'ONBOARDING',
        'qc_decided_package_count': 0,
    })
    db.partners[partner['id']] = partner
    return success(partner_out(partner), 201)


@bp.route('/studio/outsource-partners', methods=['GET'])
def list_partners():
    authenticate(ALL_READ)
    rows = list(db.partners.values())
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return paginate(by_created(rows), partner_out)


@bp.route('/studio/outsource-partners/<partner_id>', methods=['GET'])
def read_partner(partner_id):
    authenticate(ALL_READ)
    return success(partner_out(get_partner(partner_id)))


def _suspend(partner):
    """Widest cascade in the vendor aggregate: recall every live package, restore
    the budget position, unlink and retake the covered stage work."""
    packages = [p for p in db.packages.values()
                if p['partner_id'] == partner['id'] and p['status'] in RECALLABLE]
    touched_tasks = []
    productions = []
    for package in by_created(packages):
        package['status'] = 'RECALLED'
        package['fee_committed_cents'] = 0
        touch(package)
        production = db.productions.get(package['production_id'])
        if production is not None and production['id'] not in [p['id'] for p in productions]:
            productions.append(production)
        for task in by_created(tasks_linked_to(package['id'])):
            task['outsource_package_id'] = None
            if task['status'] in ('SUBMITTED', 'IN_REVIEW', 'APPROVED'):
                enter_retake(task)
            else:
                touch(task)
            touched_tasks.append(task)
    reconcile_tasks(touched_tasks)
    for production in productions:
        recompute_production(production)


@bp.route('/studio/outsource-partners/<partner_id>/status', methods=['POST'])
def partner_status(partner_id):
    authenticate((COORDINATOR,))
    partner = get_partner(partner_id)
    body = body_json()
    target = get_enum(body, 'status', PARTNER_STATUSES)
    current = partner['status']
    legal = ((current == 'ONBOARDING' and target == 'APPROVED')
             or (current == 'APPROVED' and target == 'SUSPENDED')
             or (current == 'SUSPENDED' and target == 'APPROVED'))
    if not legal:
        raise ApiError('ERR_PARTNER_STATE_INVALID', 409,
                       'a partner in %s may not move to %s' % (current, target))
    if current == 'ONBOARDING' and partner['security_certification_level'] == 'NONE':
        raise ApiError('ERR_SECURITY_REQUIREMENT_UNMET', 422,
                       'an uncertified partner may not be approved')
    if target == 'SUSPENDED':
        _suspend(partner)
    partner['status'] = target
    touch(partner)
    return success(partner_out(partner))


# ---------------------------------------------------------------------- packages
@bp.route('/studio/outsource-packages', methods=['POST'])
def create_package():
    authenticate((COORDINATOR,))
    body = body_json()
    production = fk_lookup(body, 'production_id', get_production)
    partner = fk_lookup(body, 'partner_id', get_partner)
    raw_tasks = body.get('stage_task_ids') if isinstance(body, dict) else None
    if isinstance(raw_tasks, list):
        for element in raw_tasks:
            if isinstance(element, str) and element.strip():
                get_task(element)
    production_id = get_str(body, 'production_id', min_len=1)
    partner_id = get_str(body, 'partner_id', min_len=1)
    package_code = get_str(body, 'package_code', min_len=1)
    security_tier = get_enum(body, 'security_tier', SECURITY_TIERS)
    fee_cents = get_int(body, 'fee_cents', minimum=0)
    stage_task_ids = get_str_array(body, 'stage_task_ids', required=False, default=[])
    quality_min = get_number(body, 'quality_min_score', required=False,
                             default=D('70.00'), minimum=0, maximum=100, places=2)
    if production is None:
        production = get_production(production_id)
    if partner is None:
        partner = get_partner(partner_id)
    require_phase(production, NOT_WRAPPED)
    for other in db.packages.values():
        if (other['production_id'] == production['id']
                and other['package_code'] == package_code):
            raise ApiError('ERR_DUPLICATE_CODE', 409,
                           'package_code is already used in this production')
    package = base_row()
    package.update({
        'production_id': production['id'],
        'partner_id': partner['id'],
        'package_code': package_code,
        'security_tier': security_tier,
        'quality_min_score': D(quality_min).quantize(D('0.01')),
        'fee_cents': fee_cents,
        'fee_committed_cents': 0,
        'stage_task_ids': list(stage_task_ids),
        'status': 'DRAFT',
        'watermark_applied': False,
        'delivery_count': 0,
        'qc_score': None,
        'qc_decided_at': None,
    })
    db.packages[package['id']] = package
    return success(package_out(package), 201)


@bp.route('/studio/outsource-packages', methods=['GET'])
def list_packages():
    authenticate(READ_WITH_PARTNER)
    rows = list(db.packages.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    partner_id = arg('partner_id')
    if partner_id is not None:
        rows = [r for r in rows if r['partner_id'] == partner_id]
    status = arg('status')
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return paginate(by_created(rows), package_out)


@bp.route('/studio/outsource-packages/<package_id>', methods=['GET'])
def read_package(package_id):
    authenticate(READ_WITH_PARTNER)
    return success(package_out(get_package(package_id)))


@bp.route('/studio/outsource-packages/<package_id>/issue', methods=['POST'])
def issue_package(package_id):
    authenticate((COORDINATOR,))
    package = get_package(package_id)
    production = db.productions.get(package['production_id'])
    partner = db.partners.get(package['partner_id'])
    require_phase(production, ('PRODUCTION_ACTIVE',))
    if package['status'] != 'DRAFT':
        raise ApiError('ERR_PACKAGE_STATE_INVALID', 409,
                       'a package in %s may not be issued' % package['status'])
    if partner is None or partner['status'] != 'APPROVED':
        raise ApiError('ERR_PARTNER_SUSPENDED', 409,
                       'the partner is not APPROVED')
    if tier_ordinal(partner['security_certification_level']) < tier_ordinal(package['security_tier']):
        raise ApiError('ERR_SECURITY_TIER_INSUFFICIENT', 422,
                       'the partner is not certified for %s' % package['security_tier'])
    if partner_quality_score(partner, 'ROLLING_90D') < D(package['quality_min_score']):
        raise ApiError('ERR_PARTNER_QUALITY_BELOW_STANDARD', 422,
                       'the partner rolling quality score is below quality_min_score')
    for task_id in package['stage_task_ids']:
        task = db.tasks.get(task_id)
        shot = db.shots.get(task['shot_id']) if task is not None else None
        if shot is None or shot['production_id'] != package['production_id']:
            raise ApiError('ERR_CROSS_PRODUCTION_REFERENCE', 422,
                           'stage task %s does not belong to this production' % task_id)
    if production is not None:
        prospective = budget_position(production,
                                     extra_package_fee_cents=package['fee_cents'])
        if prospective['total_committed_cents'] > spend_ceiling_cents(production):
            raise ApiError('ERR_BUDGET_WOULD_EXCEED', 402,
                           'issuing this package would exceed the spending ceiling')
    package['status'] = 'ISSUED'
    touch(package)
    for task in package_tasks(package):
        task['outsource_package_id'] = package['id']
        touch(task)
    return success(package_out(package))


@bp.route('/studio/outsource-packages/<package_id>/accept', methods=['POST'])
def accept_package(package_id):
    user_id, _role = authenticate((PARTNER_REP,))
    package = get_package(package_id)
    if user_id != package['partner_id']:
        raise ApiError('ERR_NOT_PACKAGE_PARTNER', 403,
                       'only the package partner may accept it')
    production = db.productions.get(package['production_id'])
    require_phase(production, NOT_WRAPPED)
    if package['status'] != 'ISSUED':
        raise ApiError('ERR_PACKAGE_STATE_INVALID', 409,
                       'a package in %s may not be accepted' % package['status'])
    partner = db.partners.get(package['partner_id'])
    if partner is None or partner['status'] != 'APPROVED':
        raise ApiError('ERR_PARTNER_SUSPENDED', 409, 'the partner is not APPROVED')
    package['status'] = 'IN_PROGRESS'
    package['fee_committed_cents'] = package['fee_cents']
    touch(package)
    reconcile_production(production)
    return success(package_out(package))


@bp.route('/studio/outsource-packages/<package_id>/deliver', methods=['POST'])
def deliver_package(package_id):
    user_id, _role = authenticate((PARTNER_REP,))
    package = get_package(package_id)
    body = body_json()
    watermark_applied = get_bool(body, 'watermark_applied')
    if user_id != package['partner_id']:
        raise ApiError('ERR_NOT_PACKAGE_PARTNER', 403,
                       'only the package partner may deliver it')
    production = db.productions.get(package['production_id'])
    require_phase(production, NOT_WRAPPED)
    if package['status'] not in ('IN_PROGRESS', 'QC_FAILED'):
        raise ApiError('ERR_PACKAGE_STATE_INVALID', 409,
                       'a package in %s may not be delivered' % package['status'])
    partner = db.partners.get(package['partner_id'])
    if partner is not None and partner['status'] == 'SUSPENDED':
        raise ApiError('ERR_PARTNER_SUSPENDED', 409, 'the partner is suspended')
    if partner is not None and partner['watermark_required'] and not watermark_applied:
        raise ApiError('ERR_SECURITY_REQUIREMENT_UNMET', 422,
                       'this partner must apply a forensic watermark')
    if (partner is not None and package['security_tier'] in ('TIER2', 'TIER3')
            and not partner['mfa_enforced']):
        raise ApiError('ERR_SECURITY_REQUIREMENT_UNMET', 422,
                       'MFA is required for %s work' % package['security_tier'])
    redelivery = package['status'] == 'QC_FAILED'
    package['watermark_applied'] = watermark_applied
    package['status'] = 'DELIVERED'
    package['delivery_count'] += 1
    touch(package)
    moved = []
    wanted = 'RETAKE' if redelivery else 'IN_PROGRESS'
    for task in package_tasks(package):
        if task['status'] != wanted:
            continue
        task['status'] = 'SUBMITTED'
        task['submitted_at'] = now()
        if not redelivery:
            task['submitted_by_user_id'] = user_id
        touch(task)
        moved.append(task)
    reconcile_tasks(moved)
    return success(package_out(package))


@bp.route('/studio/outsource-packages/<package_id>/qc-decision', methods=['POST'])
def qc_package(package_id):
    user_id, _role = authenticate((SUPERVISOR,))
    package = get_package(package_id)
    body = body_json()
    decision = get_enum(body, 'decision', ('PASS', 'FAIL'))
    qc_score = get_int(body, 'qc_score', minimum=0, maximum=100)
    production = db.productions.get(package['production_id'])
    require_phase(production, NOT_WRAPPED)
    if package['status'] != 'DELIVERED':
        raise ApiError('ERR_PACKAGE_STATE_INVALID', 409,
                       'a package in %s may not be QC decided' % package['status'])
    minimum = D(package['quality_min_score'])
    if decision == 'PASS' and D(qc_score) < minimum:
        raise validation_error('PASS requires qc_score >= quality_min_score')
    if decision == 'FAIL' and D(qc_score) >= minimum:
        raise validation_error('FAIL requires qc_score < quality_min_score')
    package['qc_score'] = qc_score
    package['qc_decided_at'] = now()
    package['status'] = 'QC_PASSED' if decision == 'PASS' else 'QC_FAILED'
    touch(package)
    partner = db.partners.get(package['partner_id'])
    if partner is not None:
        partner['qc_decided_package_count'] += 1
        touch(partner)
    moved = []
    if decision == 'PASS':
        for task in package_tasks(package):
            if task['status'] in ('SUBMITTED', 'IN_REVIEW'):
                approve_task(task, user_id)
                moved.append(task)
    else:
        for task in package_tasks(package):
            if task['status'] in ('SUBMITTED', 'IN_REVIEW', 'APPROVED'):
                enter_retake(task)
                moved.append(task)
    reconcile_tasks(moved)
    reconcile_production(production)
    return success(package_out(package))
