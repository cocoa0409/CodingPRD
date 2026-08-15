"""Lease endpoints (PRD sections 3.1, 3.2, 3.8)."""
from flask import Blueprint, g, request

from db import db, base_fields
from errors import (ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_REQUEST,
                    ERR_LEASE_STATE_FORBIDS, ERR_PREMISES_TERM_OVERLAP,
                    ERR_INVALID_DATE_RANGE, ERR_STALE_VERSION)
from middleware import (require_roles, body_json, req_str, req_int, opt_int,
                        req_date, valid_date_str, require_lease_owner)
from response import ok, ok_list
from services.core import (pub, touch, parse_date, cascade_lease_close,
                           lease_performance)
from services.validation import check_enum, paginate

bp = Blueprint('leases', __name__)

LEASE_CATEGORIES = ('FOOD', 'RETAIL', 'SERVICES')
LEASE_ACTIONS = ('ACTIVATE', 'DECLARE_DEFAULT', 'CURE_DEFAULT', 'TERMINATE', 'REMARKET')
DEFAULT_REASONS = ('NONPAYMENT', 'HOURS_SHORTFALL', 'ACDBE_NONCOMPLIANCE', 'OTHER')
LEASE_STATUSES = ('DRAFT', 'ACTIVE', 'DEFAULTED', 'TERMINATED', 'EXPIRED', 'REMARKETING')
# Statuses participating in the premises term-overlap occupation rule.
OCCUPYING_STATUSES = ('DRAFT', 'ACTIVE', 'DEFAULTED')

# Economics fields amendable via PATCH while the lease is DRAFT.
PATCH_INT_FIELDS = ('mag_annual_cents', 'pct_rate_below_bp', 'pct_breakpoint_cents',
                    'pct_rate_above_bp', 'acdbe_goal_bp', 'ti_allowance_cents',
                    'min_spe_cents')


def get_lease_or_404(lid):
    lease = db.leases.get(lid)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Lease not found')
    return lease


@bp.route('/concessions/leases', methods=['POST'])
def create_lease():
    require_roles('AirportAdmin')
    body = body_json()
    # Stage 3: body FK existence (tenant_id).
    tenant_id = body.get('tenant_id')
    if isinstance(tenant_id, str) and tenant_id not in db.tenants:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced tenant does not exist')
    # Stage 4: request shape.
    tenant_id = req_str(body, 'tenant_id')
    if tenant_id not in db.tenants:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced tenant does not exist')
    premises_code = req_str(body, 'premises_code')
    category = req_str(body, 'category')
    term_start = req_date(body, 'term_start_date')
    term_end = req_date(body, 'term_end_date')
    mag = req_int(body, 'mag_annual_cents')
    rate_below = req_int(body, 'pct_rate_below_bp')
    bp_cents = req_int(body, 'pct_breakpoint_cents')
    rate_above = req_int(body, 'pct_rate_above_bp')
    goal = req_int(body, 'acdbe_goal_bp')
    ti = req_int(body, 'ti_allowance_cents')
    buildout = req_date(body, 'buildout_deadline')
    min_spe = req_int(body, 'min_spe_cents')
    # Stage 5: enum membership.
    check_enum(category, LEASE_CATEGORIES, 'category')
    # Stage 7: premises occupation (runs before date coherence per PRD 2.8).
    ns, ne = parse_date(term_start), parse_date(term_end)
    for other in db.leases.values():
        if other['status'] not in OCCUPYING_STATUSES:
            continue
        if other['premises_code'] != premises_code:
            continue
        os_ = parse_date(other['term_start_date'])
        oe = parse_date(other['term_end_date'])
        # Half-open [start, end) overlap; adjacency (start == other end) allowed.
        if ns < oe and os_ < ne:
            raise ApiError(ERR_PREMISES_TERM_OVERLAP, 409,
                           'Premises term overlaps an existing lease')
    # Stage 8: temporal windows.
    if not ns < ne:
        raise ApiError(ERR_INVALID_DATE_RANGE, 422,
                       'term_start_date must be strictly before term_end_date')
    rec = base_fields()
    rec.update({
        'tenant_id': tenant_id,
        'premises_code': premises_code,
        'category': category,
        'term_start_date': term_start,
        'term_end_date': term_end,
        'mag_annual_cents': mag,
        'pct_rate_below_bp': rate_below,
        'pct_breakpoint_cents': bp_cents,
        'pct_rate_above_bp': rate_above,
        'acdbe_goal_bp': goal,
        'ti_allowance_cents': ti,
        'buildout_deadline': buildout,
        'min_spe_cents': min_spe,
        'status': 'DRAFT',
        'default_reason': None,
        'arrears_cents': 0,
        'ti_remaining_cents': ti,
    })
    db.leases[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/leases', methods=['GET'])
def list_leases():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant', 'Auditor')
    items = sorted(db.leases.values(), key=lambda l: l['_seq'])
    f_tenant = request.args.get('tenant_id')
    f_premises = request.args.get('premises_code')
    f_status = request.args.get('status')
    if f_status is not None:
        check_enum(f_status, LEASE_STATUSES, 'status')
    if g.role == 'Tenant':
        items = [l for l in items if l['tenant_id'] == g.user_id]
    if f_tenant is not None:
        items = [l for l in items if l['tenant_id'] == f_tenant]
    if f_premises is not None:
        items = [l for l in items if l['premises_code'] == f_premises]
    if f_status is not None:
        items = [l for l in items if l['status'] == f_status]
    page, meta = paginate(items)
    return ok_list([pub(l) for l in page], meta)


@bp.route('/concessions/leases/<lid>', methods=['GET'])
def get_lease(lid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant', 'Auditor')
    lease = get_lease_or_404(lid)
    if g.role == 'Tenant':
        require_lease_owner(lease)
    return ok(pub(lease))


@bp.route('/concessions/leases/<lid>', methods=['PATCH'])
def patch_lease(lid):
    require_roles('AirportAdmin')
    lease = get_lease_or_404(lid)
    body = body_json()
    # Stage 4: shape. expected_lease_version is mandatory (PRD 2.7).
    if 'expected_lease_version' not in body or body['expected_lease_version'] is None:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Required field missing: expected_lease_version')
    expected = body['expected_lease_version']
    if not isinstance(expected, int) or isinstance(expected, bool):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'Field malformed: expected_lease_version')
    updates = {}
    for f in PATCH_INT_FIELDS:
        v = opt_int(body, f)
        if v is not None:
            updates[f] = v
    if 'buildout_deadline' in body and body['buildout_deadline'] is not None:
        if not valid_date_str(body['buildout_deadline']):
            raise ApiError(ERR_INVALID_REQUEST, 400, 'Field malformed: buildout_deadline')
        updates['buildout_deadline'] = body['buildout_deadline']
    # Stage 6: amendment allowed only while DRAFT (precedes the OCC check).
    if lease['status'] != 'DRAFT':
        raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                       'Lease amendment allowed only in DRAFT')
    # Stage 10: optimistic concurrency on Lease.version.
    if expected != lease['version']:
        raise ApiError(ERR_STALE_VERSION, 412,
                       'expected_lease_version does not match current Lease.version')
    lease.update(updates)
    touch(lease)
    return ok(pub(lease))


@bp.route('/concessions/leases/<lid>/transition', methods=['POST'])
def transition_lease(lid):
    require_roles('AirportAdmin')
    lease = get_lease_or_404(lid)
    body = body_json()
    action = req_str(body, 'action')
    check_enum(action, LEASE_ACTIONS, 'action')
    reason = None
    if action == 'DECLARE_DEFAULT':
        reason = req_str(body, 'reason')
        check_enum(reason, DEFAULT_REASONS, 'reason')

    if action == 'ACTIVATE':
        if lease['status'] != 'DRAFT':
            raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                           'ACTIVATE is valid only from DRAFT')
        lease['status'] = 'ACTIVE'
    elif action == 'DECLARE_DEFAULT':
        if lease['status'] != 'ACTIVE':
            raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                           'DECLARE_DEFAULT is valid only from ACTIVE')
        lease['status'] = 'DEFAULTED'
        lease['default_reason'] = reason
    elif action == 'CURE_DEFAULT':
        if lease['status'] != 'DEFAULTED':
            raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                           'CURE_DEFAULT is valid only from DEFAULTED')
        lease['status'] = 'ACTIVE'
        lease['default_reason'] = None
    elif action == 'TERMINATE':
        if lease['status'] not in ('ACTIVE', 'DEFAULTED'):
            raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                           'TERMINATE is valid only from ACTIVE or DEFAULTED')
        lease['status'] = 'TERMINATED'
        cascade_lease_close(lease)
    elif action == 'REMARKET':
        if lease['status'] != 'TERMINATED':
            raise ApiError(ERR_LEASE_STATE_FORBIDS, 409,
                           'REMARKET is valid only from TERMINATED')
        lease['status'] = 'REMARKETING'
    touch(lease)
    return ok(pub(lease))


@bp.route('/concessions/leases/<lid>/performance', methods=['GET'])
def get_performance(lid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant')
    lease = get_lease_or_404(lid)
    if g.role == 'Tenant':
        require_lease_owner(lease)
    return ok(lease_performance(lease))
