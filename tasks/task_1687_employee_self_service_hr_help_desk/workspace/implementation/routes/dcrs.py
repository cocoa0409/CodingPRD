"""Data change requests + fraud verification (parallel state dimensions)."""
import random
from datetime import timedelta

from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from routes.employees import recompute_has_pending_dcr
from serializers import ser_dcr, ser_fraud_verification
from validate import (enum_filter, get_body, opt_str, parse_pagination,
                      req_dict, req_enum, req_int, req_str, str_filter,
                      paginate, MISSING)

bp = Blueprint('dcrs', __name__)

CHANGE_TYPES = ('ADDRESS', 'DIRECT_DEPOSIT')
APPROVAL_STATUSES = ('PENDING_VERIFICATION', 'PENDING_APPROVAL', 'APPLIED',
                     'REJECTED', 'CANCELLED')
VERIFY_METHODS = ('SECURITY_CODE', 'MANAGER_CONFIRMATION')
BANK_ACCOUNT_TYPES = ('CHECKING', 'SAVINGS')
FRAUD_MAX_ATTEMPTS = 3
FRAUD_LOOKBACK_DAYS = 30

ADDRESS_FIELDS = ('address_line1', 'city', 'region', 'postal_code')
DEPOSIT_FIELDS = ('bank_routing_number', 'bank_account_number',
                  'bank_account_type')

_READ_ROLES = ('Employee', 'HRDataSteward', 'HRServicesAdmin')


def _get_dcr(dcr_id):
    d = db.dcrs.get(dcr_id)
    if d is None:
        raise ApiError('ERR_DCR_NOT_FOUND', 404, 'no such data change request')
    return d


def _fv_for(dcr_id):
    for f in db.fraud_verifications.values():
        if f['dcr_id'] == dcr_id:
            return f
    return None


def _fraud_required(employee_id, change_type):
    """DIRECT_DEPOSIT always requires verification; ADDRESS requires it iff the
    employee has any FraudVerification in FAILED/LOCKED created within the
    trailing 30 days."""
    if change_type == 'DIRECT_DEPOSIT':
        return True
    cutoff = db.now() - timedelta(days=FRAUD_LOOKBACK_DAYS)
    for f in db.fraud_verifications.values():
        if f['status'] not in ('FAILED', 'LOCKED'):
            continue
        if f['created_at'] < cutoff:
            continue
        d = db.dcrs.get(f['dcr_id'])
        if d is not None and d['employee_id'] == employee_id:
            return True
    return False


@bp.post('/data-change-requests')
def create_dcr():
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    raw_eid = body.get('employee_id')
    if isinstance(raw_eid, str) and raw_eid and raw_eid != ctx.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employee_id must equal the caller X-User-ID')
    employee_id = req_str(body, 'employee_id')
    change_type = req_enum(body, 'change_type', CHANGE_TYPES)
    new_values = req_dict(body, 'new_values')
    # Sub-field completeness for the change_type.
    required_fields = ADDRESS_FIELDS if change_type == 'ADDRESS' else DEPOSIT_FIELDS
    cleaned = {}
    for f in required_fields:
        v = new_values.get(f)
        if not isinstance(v, str) or v == '':
            raise ApiError('ERR_VALIDATION', 400,
                           'new_values.%s is required for %s' % (f, change_type))
        cleaned[f] = v
    if change_type == 'DIRECT_DEPOSIT' and cleaned['bank_account_type'] not in BANK_ACCOUNT_TYPES:
        raise ApiError('ERR_INVALID_ENUM', 400,
                       'bank_account_type must be CHECKING|SAVINGS')
    expected = req_int(body, 'expected_employee_version')
    if employee_id != ctx.user_id:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employee_id must equal the caller X-User-ID')
    employee = db.employees.get(employee_id)
    if employee is None:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'no such employee')
    # Business-safety gate: the subject employee must be ACTIVE.
    if employee['status'] != 'ACTIVE':
        raise ApiError('ERR_EMPLOYEE_INACTIVE', 422,
                       'employee must be ACTIVE to submit a data change')
    # One pending request per employee per change type.
    for d in db.dcrs.values():
        if d['employee_id'] == employee_id and d['change_type'] == change_type \
                and d['approval_status'] in ('PENDING_VERIFICATION', 'PENDING_APPROVAL'):
            raise ApiError('ERR_DUPLICATE_DATA_CHANGE_PENDING', 409,
                           'a pending request of this change_type already exists')
    if expected != employee['version']:
        raise ApiError('ERR_STALE_EMPLOYEE_VERSION', 412,
                       'expected_employee_version does not match current version')
    required = _fraud_required(employee_id, change_type)
    rec = {
        'employee_id': employee_id,
        'change_type': change_type,
        'new_values': cleaned,
        'approval_status': 'PENDING_VERIFICATION' if required else 'PENDING_APPROVAL',
        'fraud_status': 'PENDING' if required else 'NOT_REQUIRED',
        'submitted_at': db.now(),
        'decided_by_user_id': None,
        'decided_at': None,
        'applied_at': None,
        'reject_reason': None,
    }
    db.stamp_common(rec)
    db.dcrs[rec['id']] = rec
    if required:
        fv = {
            'dcr_id': rec['id'],
            'method': 'MANAGER_CONFIRMATION' if employee['manager_id'] else 'SECURITY_CODE',
            'challenge_code': '%06d' % random.randint(0, 999999),
            'attempts': 0,
            'status': 'PENDING',
            'verified_by_user_id': None,
            'verified_at': None,
        }
        db.stamp_common(fv)
        db.fraud_verifications[fv['id']] = fv
    recompute_has_pending_dcr(employee)
    return ok_object(ser_dcr(rec), status=201)


@bp.get('/data-change-requests')
def list_dcrs():
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    emp_f = str_filter('employee_id')
    status_f = enum_filter('approval_status', APPROVAL_STATUSES)
    type_f = enum_filter('change_type', CHANGE_TYPES)
    limit, offset = parse_pagination()
    rows = list(db.dcrs.values())
    if ctx.role == 'Employee':
        rows = [d for d in rows if d['employee_id'] == ctx.user_id]
    elif emp_f is not MISSING:
        rows = [d for d in rows if d['employee_id'] == emp_f]
    if status_f is not MISSING:
        rows = [d for d in rows if d['approval_status'] == status_f]
    if type_f is not MISSING:
        rows = [d for d in rows if d['change_type'] == type_f]
    rows.sort(key=lambda d: (d['created_at'], d['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_dcr(d) for d in page], limit, offset, total)


@bp.get('/data-change-requests/<dcr_id>')
def get_dcr(dcr_id):
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    d = _get_dcr(dcr_id)
    if ctx.role == 'Employee' and ctx.user_id != d['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may read only their own requests')
    return ok_object(ser_dcr(d))


@bp.get('/data-change-requests/<dcr_id>/fraud-verifications')
def list_fraud_verifications(dcr_id):
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    d = _get_dcr(dcr_id)
    if ctx.role == 'Employee' and ctx.user_id != d['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may read only their own requests')
    limit, offset = parse_pagination()
    rows = [f for f in db.fraud_verifications.values() if f['dcr_id'] == d['id']]
    rows.sort(key=lambda f: (f['created_at'], f['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_fraud_verification(f) for f in page], limit, offset, total)


@bp.post('/data-change-requests/<dcr_id>/verify')
def verify_dcr(dcr_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    body = get_body()
    method = req_enum(body, 'method', VERIFY_METHODS)
    evidence = opt_str(body, 'evidence_code')
    if method == 'SECURITY_CODE' and evidence is None:
        raise ApiError('ERR_VALIDATION', 400,
                       'evidence_code is required for SECURITY_CODE')
    d = _get_dcr(dcr_id)
    employee = db.employees.get(d['employee_id'])
    # Caller identity depends on the channel: the owning employee supplies the
    # challenge code; the manager of record confirms.
    if method == 'SECURITY_CODE':
        if ctx.user_id != d['employee_id']:
            raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                           'only the owning employee may supply the challenge code')
    else:
        if employee is None or ctx.user_id != employee['manager_id']:
            raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                           'only the manager of record may confirm')
    fv = _fv_for(d['id'])
    if fv is None:
        raise ApiError('ERR_DCR_INVALID_STATE', 409,
                       'this request requires no fraud verification')
    if fv['method'] != method:
        raise ApiError('ERR_VALIDATION', 400,
                       'method does not match the issued verification method')
    # The LOCKED lockout is raised at state-check priority, ahead of the
    # generic DCR state error.
    if fv['status'] == 'LOCKED':
        raise ApiError('ERR_FRAUD_VERIFICATION_LOCKED', 409,
                       'the fraud verification is locked')
    if d['approval_status'] != 'PENDING_VERIFICATION' or fv['status'] == 'VERIFIED':
        raise ApiError('ERR_DCR_INVALID_STATE', 409,
                       'request is not pending verification')
    if method == 'MANAGER_CONFIRMATION' or evidence == fv['challenge_code']:
        # Success: verification settles, request advances to PENDING_APPROVAL.
        fv['status'] = 'VERIFIED'
        fv['verified_by_user_id'] = ctx.user_id
        fv['verified_at'] = db.now()
        bump(fv)
        d['fraud_status'] = 'VERIFIED'
        d['approval_status'] = 'PENDING_APPROVAL'
        bump(d)
        return ok_object(ser_dcr(d))
    # Wrong evidence: the rejection carries a persisted mutation.
    fv['attempts'] += 1
    fv['status'] = 'FAILED'
    bump(fv)
    d['fraud_status'] = 'FAILED'
    if fv['attempts'] >= FRAUD_MAX_ATTEMPTS:
        fv['status'] = 'LOCKED'
        d['fraud_status'] = 'LOCKED'
        d['approval_status'] = 'REJECTED'
        d['reject_reason'] = 'FRAUD_VERIFICATION_LOCKED'
        if employee is not None:
            recompute_has_pending_dcr(employee)
    bump(d)
    raise ApiError('ERR_FRAUD_EVIDENCE_MISMATCH', 422,
                   'evidence_code does not match the challenge code')


@bp.post('/data-change-requests/<dcr_id>/approve')
def approve_dcr(dcr_id):
    ctx = authenticate()
    require_roles(ctx, 'HRDataSteward')
    d = _get_dcr(dcr_id)
    if d['approval_status'] not in ('PENDING_VERIFICATION', 'PENDING_APPROVAL'):
        raise ApiError('ERR_DCR_INVALID_STATE', 409,
                       'request is not in an approvable state')
    # Fraud gate first: it is a business-safety rejection, not a state error.
    if d['fraud_status'] not in ('VERIFIED', 'NOT_REQUIRED'):
        raise ApiError('ERR_FRAUD_VERIFICATION_REQUIRED', 409,
                       'fraud verification is required before approval')
    employee = db.employees.get(d['employee_id'])
    if employee is None or employee['status'] != 'ACTIVE':
        raise ApiError('ERR_EMPLOYEE_INACTIVE', 422,
                       'employee must be ACTIVE to apply a data change')
    if ctx.user_id == d['employee_id']:
        raise ApiError('ERR_SELF_APPROVAL_FORBIDDEN', 403,
                       'a steward may not decide their own request')
    fv = _fv_for(d['id'])
    if fv is not None and fv['verified_by_user_id'] is not None \
            and ctx.user_id == fv['verified_by_user_id']:
        raise ApiError('ERR_VERIFIER_CANNOT_APPROVE', 403,
                       'the verifier may not approve the same request')
    now = db.now()
    # Apply atomically: write profile fields, audit each changed field.
    fields = ADDRESS_FIELDS if d['change_type'] == 'ADDRESS' else DEPOSIT_FIELDS
    changed = []
    for f in fields:
        old = employee[f]
        new = d['new_values'].get(f)
        if old != new:
            changed.append((f, old, new))
        employee[f] = new
    bump(employee)  # profile write
    for field, old, new in changed:
        entry = {
            'employee_id': employee['id'],
            'dcr_id': d['id'],
            'field_changed': field,
            'old_value': None if old is None else str(old),
            'new_value': str(new),
            'changed_by_user_id': ctx.user_id,
            'change_source': 'DCR_APPLIED',
        }
        db.stamp_created(entry)  # append-only: id + created_at only
        db.audit_entries[entry['id']] = entry
    d['approval_status'] = 'APPLIED'
    d['decided_by_user_id'] = ctx.user_id
    d['decided_at'] = now
    d['applied_at'] = now
    bump(d)
    # Applying invalidates sibling in-flight requests.
    siblings = [o for o in db.dcrs.values()
                if o['employee_id'] == employee['id'] and o['id'] != d['id']
                and o['approval_status'] in ('PENDING_VERIFICATION',
                                             'PENDING_APPROVAL')]
    siblings.sort(key=lambda o: o['_seq'])
    for o in siblings:
        o['approval_status'] = 'CANCELLED'
        bump(o)
    recompute_has_pending_dcr(employee)
    return ok_object(ser_dcr(d))


@bp.post('/data-change-requests/<dcr_id>/reject')
def reject_dcr(dcr_id):
    ctx = authenticate()
    require_roles(ctx, 'HRDataSteward')
    body = get_body()
    reason = req_str(body, 'reason')
    d = _get_dcr(dcr_id)
    if d['approval_status'] != 'PENDING_APPROVAL':
        raise ApiError('ERR_DCR_INVALID_STATE', 409,
                       'only a PENDING_APPROVAL request may be rejected')
    if ctx.user_id == d['employee_id']:
        raise ApiError('ERR_SELF_APPROVAL_FORBIDDEN', 403,
                       'a steward may not decide their own request')
    d['approval_status'] = 'REJECTED'
    d['reject_reason'] = reason
    d['decided_by_user_id'] = ctx.user_id
    d['decided_at'] = db.now()
    bump(d)
    employee = db.employees.get(d['employee_id'])
    if employee is not None:
        recompute_has_pending_dcr(employee)
    return ok_object(ser_dcr(d))


@bp.post('/data-change-requests/<dcr_id>/cancel')
def cancel_dcr(dcr_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee')
    d = _get_dcr(dcr_id)
    if ctx.user_id != d['employee_id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403,
                       'employees may cancel only their own requests')
    if d['approval_status'] not in ('PENDING_VERIFICATION', 'PENDING_APPROVAL'):
        raise ApiError('ERR_DCR_INVALID_STATE', 409,
                       'request is not pending')
    d['approval_status'] = 'CANCELLED'
    bump(d)
    employee = db.employees.get(d['employee_id'])
    if employee is not None:
        recompute_has_pending_dcr(employee)
    return ok_object(ser_dcr(d))
