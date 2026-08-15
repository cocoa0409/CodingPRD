"""Employees: create/list/read, lifecycle status, per-employee audit log."""
from flask import Blueprint

import db
from db import bump
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_employee, ser_audit_entry
from validate import (get_body, opt_enum, opt_str, parse_pagination, req_str,
                      str_filter, enum_filter, paginate, MISSING)

bp = Blueprint('employees', __name__)

EMPLOYEE_STATUSES = ('ACTIVE', 'ON_LEAVE', 'TERMINATED')
_LIST_ROLES = ('HRServicesAdmin', 'HRDataSteward', 'HelpDeskAgent',
               'SpecialistAgent', 'SensitiveCaseManager', 'WorkforcePlanner',
               'KnowledgeManager')
_READ_ROLES = ('Employee', 'HRServicesAdmin', 'HRDataSteward', 'HelpDeskAgent',
               'SpecialistAgent', 'SensitiveCaseManager')


def recompute_has_pending_dcr(employee):
    """True exactly while any DCR of the employee is PENDING_*. A flip is a
    mutation: bump version + updated_at."""
    pending = any(d['employee_id'] == employee['id']
                  and d['approval_status'] in ('PENDING_VERIFICATION',
                                               'PENDING_APPROVAL')
                  for d in db.dcrs.values())
    if employee['has_pending_dcr'] != pending:
        employee['has_pending_dcr'] = pending
        bump(employee)


@bp.post('/employees')
def create_employee():
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    number = req_str(body, 'employee_number')
    full_name = req_str(body, 'full_name')
    email = req_str(body, 'email')
    manager_id = opt_str(body, 'manager_id')
    status = opt_enum(body, 'status', EMPLOYEE_STATUSES, default='ACTIVE')
    if manager_id is not None and manager_id not in db.employees:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'manager_id references no employee')
    for e in db.employees.values():
        if e['employee_number'] == number:
            raise ApiError('ERR_DUPLICATE_EMPLOYEE_NUMBER', 409,
                           'employee_number already exists')
    rec = {
        'employee_number': number,
        'full_name': full_name,
        'email': email,
        'status': status,
        'manager_id': manager_id,
        'address_line1': None,
        'city': None,
        'region': None,
        'postal_code': None,
        'bank_routing_number': None,
        'bank_account_number': None,
        'bank_account_type': None,
        'has_pending_dcr': False,
    }
    db.stamp_common(rec)
    db.employees[rec['id']] = rec
    return ok_object(ser_employee(rec), status=201)


@bp.get('/employees')
def list_employees():
    ctx = authenticate()
    require_roles(ctx, *_LIST_ROLES)
    status_f = enum_filter('status', EMPLOYEE_STATUSES)
    manager_f = str_filter('manager_id')
    limit, offset = parse_pagination()
    rows = list(db.employees.values())
    if status_f is not MISSING:
        rows = [e for e in rows if e['status'] == status_f]
    if manager_f is not MISSING:
        rows = [e for e in rows if e['manager_id'] == manager_f]
    rows.sort(key=lambda e: (e['created_at'], e['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_employee(e) for e in page], limit, offset, total)


@bp.get('/employees/<emp_id>')
def get_employee(emp_id):
    ctx = authenticate()
    require_roles(ctx, *_READ_ROLES)
    e = db.employees.get(emp_id)
    if e is None:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'no such employee')
    if ctx.role == 'Employee' and ctx.user_id != e['id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'employees may read only their own record')
    return ok_object(ser_employee(e))


@bp.post('/employees/<emp_id>/status')
def set_employee_status(emp_id):
    ctx = authenticate()
    require_roles(ctx, 'HRServicesAdmin')
    body = get_body()
    new_status = req_str(body, 'status')
    if new_status not in EMPLOYEE_STATUSES:
        raise ApiError('ERR_INVALID_ENUM', 400, 'status must be ACTIVE|ON_LEAVE|TERMINATED')
    e = db.employees.get(emp_id)
    if e is None:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'no such employee')
    cur = e['status']
    ok_transition = (
        (cur == 'ACTIVE' and new_status in ('ON_LEAVE', 'TERMINATED')) or
        (cur == 'ON_LEAVE' and new_status in ('ACTIVE', 'TERMINATED'))
    )
    if not ok_transition:
        raise ApiError('ERR_EMPLOYEE_INVALID_STATE', 409,
                       'invalid employee status transition')
    e['status'] = new_status
    bump(e)
    if new_status == 'TERMINATED':
        # Cascade: pending DCRs -> CANCELLED (open tickets are NOT cancelled).
        pending = [d for d in db.dcrs.values()
                   if d['employee_id'] == e['id']
                   and d['approval_status'] in ('PENDING_VERIFICATION',
                                                'PENDING_APPROVAL')]
        pending.sort(key=lambda d: d['_seq'])
        for d in pending:
            d['approval_status'] = 'CANCELLED'
            bump(d)
        recompute_has_pending_dcr(e)
    return ok_object(ser_employee(e))


@bp.get('/employees/<emp_id>/audit-log')
def employee_audit_log(emp_id):
    ctx = authenticate()
    require_roles(ctx, 'Employee', 'HRServicesAdmin', 'HRDataSteward')
    e = db.employees.get(emp_id)
    if e is None:
        raise ApiError('ERR_EMPLOYEE_NOT_FOUND', 404, 'no such employee')
    if ctx.role == 'Employee' and ctx.user_id != e['id']:
        raise ApiError('ERR_FORBIDDEN_ROLE', 403, 'employees may read only their own audit log')
    limit, offset = parse_pagination()
    rows = [a for a in db.audit_entries.values() if a['employee_id'] == emp_id]
    # Newest first: the second exception to the default sort.
    rows.sort(key=lambda a: (-a['created_at'].timestamp(), -a['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_audit_entry(a) for a in page], limit, offset, total)
