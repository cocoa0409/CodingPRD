"""Sales report endpoints (PRD section 3.3)."""
from flask import Blueprint, g, request

from db import db, base_fields, now_iso
from errors import (ApiError, ERR_NOT_FOUND, ERR_FORBIDDEN, ERR_INVALID_ENUM,
                    ERR_LEASE_NOT_ACTIVE, ERR_REPORT_NOT_SUBMITTABLE,
                    ERR_REPORT_NOT_EDITABLE, ERR_REPORT_NOT_REVIEWABLE,
                    ERR_REPORT_PERIOD_DUPLICATE, ERR_REPORT_PERIOD_FUTURE,
                    ERR_INVALID_AMOUNT)
from middleware import (require_roles, body_json, req_str, req_int, req_month,
                        require_lease_owner)
from response import ok, ok_list
from services.core import (pub, touch, current_month, find_settlement,
                           recalc_settlement, recompute_arrears)
from services.validation import check_enum, paginate

bp = Blueprint('sales_reports', __name__)

REPORT_ACTIONS = ('SUBMIT', 'ACCEPT', 'DISPUTE')
REPORT_STATUSES = ('DRAFT', 'SUBMITTED', 'ACCEPTED', 'DISPUTED', 'ADJUSTED')
# Statuses blocking a fresh filing for the same (lease, period_month).
# DISPUTED deliberately does not block (PRD 3.3).
BLOCKING_STATUSES = ('DRAFT', 'SUBMITTED', 'ACCEPTED', 'ADJUSTED')


def get_report_or_404(rid):
    r = db.sales_reports.get(rid)
    if r is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Sales report not found')
    return r


@bp.route('/concessions/sales-reports', methods=['POST'])
def create_report():
    require_roles('Tenant')
    body = body_json()
    # Stage 3: body FK existence.
    lease_id = body.get('lease_id')
    if isinstance(lease_id, str) and lease_id not in db.leases:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    lease_id = req_str(body, 'lease_id')
    lease = db.leases.get(lease_id)
    if lease is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Referenced lease does not exist')
    # Stage 2 tenant-scoped ownership of the target lease.
    require_lease_owner(lease)
    period_month = req_month(body, 'period_month')
    gross = req_int(body, 'gross_sales_cents')
    # Stage 7: one report per (lease, month) among blocking statuses.
    for r in db.sales_reports.values():
        if (r['lease_id'] == lease_id and r['period_month'] == period_month
                and r['status'] in BLOCKING_STATUSES):
            raise ApiError(ERR_REPORT_PERIOD_DUPLICATE, 409,
                           'A report already exists for this lease and month')
    # Stage 8: period must not be after the logical clock's current month.
    if period_month > current_month():
        raise ApiError(ERR_REPORT_PERIOD_FUTURE, 422,
                       'Report period_month is after the current month')
    # Stage 9: gross may be zero but never negative.
    if gross < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, 'gross_sales_cents must be >= 0')
    rec = base_fields()
    rec.update({
        'lease_id': lease_id,
        'period_month': period_month,
        'gross_sales_cents': gross,
        'restated_gross_sales_cents': None,
        'status': 'DRAFT',
        'submitted_at': None,
    })
    db.sales_reports[rec['id']] = rec
    return ok(pub(rec), status=201)


@bp.route('/concessions/sales-reports', methods=['GET'])
def list_reports():
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant', 'Auditor')
    items = sorted(db.sales_reports.values(), key=lambda r: r['_seq'])
    f_lease = request.args.get('lease_id')
    f_status = request.args.get('status')
    f_month = request.args.get('period_month')
    if f_status is not None:
        check_enum(f_status, REPORT_STATUSES, 'status')
    if g.role == 'Tenant':
        own = {l['id'] for l in db.leases.values() if l['tenant_id'] == g.user_id}
        items = [r for r in items if r['lease_id'] in own]
    if f_lease is not None:
        items = [r for r in items if r['lease_id'] == f_lease]
    if f_status is not None:
        items = [r for r in items if r['status'] == f_status]
    if f_month is not None:
        items = [r for r in items if r['period_month'] == f_month]
    page, meta = paginate(items)
    return ok_list([pub(r) for r in page], meta)


@bp.route('/concessions/sales-reports/<rid>', methods=['GET'])
def get_report(rid):
    require_roles('AirportAdmin', 'ConcessionAnalyst', 'Tenant', 'Auditor')
    r = get_report_or_404(rid)
    if g.role == 'Tenant':
        require_lease_owner(db.leases[r['lease_id']])
    return ok(pub(r))


@bp.route('/concessions/sales-reports/<rid>', methods=['PATCH'])
def patch_report(rid):
    require_roles('Tenant')
    r = get_report_or_404(rid)
    require_lease_owner(db.leases[r['lease_id']])
    body = body_json()
    gross = req_int(body, 'gross_sales_cents')
    # Stage 6: editable only while DRAFT or DISPUTED.
    if r['status'] not in ('DRAFT', 'DISPUTED'):
        raise ApiError(ERR_REPORT_NOT_EDITABLE, 409,
                       'Report is editable only in DRAFT or DISPUTED')
    if gross < 0:
        raise ApiError(ERR_INVALID_AMOUNT, 422, 'gross_sales_cents must be >= 0')
    r['gross_sales_cents'] = gross
    touch(r)
    return ok(pub(r))


@bp.route('/concessions/sales-reports/<rid>/transition', methods=['POST'])
def transition_report(rid):
    require_roles('Tenant', 'ConcessionAnalyst')
    r = get_report_or_404(rid)
    body = body_json()
    action = req_str(body, 'action')
    check_enum(action, REPORT_ACTIONS, 'action')
    lease = db.leases[r['lease_id']]

    if action == 'SUBMIT':
        if g.role != 'Tenant':
            raise ApiError(ERR_FORBIDDEN, 403, 'SUBMIT is a Tenant action')
        require_lease_owner(lease)
        # The cross-entity lease-active check precedes the report-state check.
        if lease['status'] != 'ACTIVE':
            raise ApiError(ERR_LEASE_NOT_ACTIVE, 409,
                           'Submission requires an ACTIVE lease')
        if r['status'] not in ('DRAFT', 'DISPUTED'):
            raise ApiError(ERR_REPORT_NOT_SUBMITTABLE, 409,
                           'SUBMIT is valid only from DRAFT or DISPUTED')
        r['status'] = 'SUBMITTED'
        r['submitted_at'] = now_iso()
        touch(r)
        return ok(pub(r))

    # ACCEPT / DISPUTE are ConcessionAnalyst actions.
    if g.role != 'ConcessionAnalyst':
        raise ApiError(ERR_FORBIDDEN, 403,
                       'ACCEPT and DISPUTE are ConcessionAnalyst actions')
    if r['status'] != 'SUBMITTED':
        raise ApiError(ERR_REPORT_NOT_REVIEWABLE, 409,
                       'ACCEPT/DISPUTE are valid only from SUBMITTED')
    if action == 'DISPUTE':
        r['status'] = 'DISPUTED'
        touch(r)
        return ok(pub(r))
    # ACCEPT
    r['status'] = 'ACCEPTED'
    touch(r)
    # Cross-entity cascade: recalculate the owning settlement (if any) under
    # the variant implied by its current status; the lease's version
    # increments with its updated_at refreshed.
    year = int(r['period_month'][:4])
    st = find_settlement(r['lease_id'], year)
    if st is not None:
        recalc_settlement(st)
        recompute_arrears(lease)
    return ok(pub(r))
