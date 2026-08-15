"""Global audit trail of employee data changes."""
from flask import Blueprint

import db
from errors import ApiError
from middleware import authenticate, require_roles
from response import ok_list, ok_object
from serializers import ser_audit_entry
from validate import (enum_filter, parse_pagination, str_filter, paginate,
                      MISSING)

bp = Blueprint('audit', __name__)

_ROLES = ('HRServicesAdmin', 'HRDataSteward')


@bp.get('/audit-log-entries')
def list_audit_entries():
    ctx = authenticate()
    require_roles(ctx, *_ROLES)
    emp_f = str_filter('employee_id')
    dcr_f = str_filter('dcr_id')
    source_f = enum_filter('change_source', ('DCR_APPLIED',))
    limit, offset = parse_pagination()
    rows = list(db.audit_entries.values())
    if emp_f is not MISSING:
        rows = [a for a in rows if a['employee_id'] == emp_f]
    if dcr_f is not MISSING:
        rows = [a for a in rows if a['dcr_id'] == dcr_f]
    if source_f is not MISSING:
        rows = [a for a in rows if a['change_source'] == source_f]
    # Default sort (the newest-first exception applies only to the
    # per-employee audit trail): created_at ascending.
    rows.sort(key=lambda a: (a['created_at'], a['_seq']))
    page, total = paginate(rows, limit, offset)
    return ok_list([ser_audit_entry(a) for a in page], limit, offset, total)


@bp.get('/audit-log-entries/<entry_id>')
def get_audit_entry(entry_id):
    ctx = authenticate()
    require_roles(ctx, *_ROLES)
    a = db.audit_entries.get(entry_id)
    if a is None:
        raise ApiError('ERR_AUDIT_ENTRY_NOT_FOUND', 404, 'no such audit log entry')
    return ok_object(ser_audit_entry(a))
