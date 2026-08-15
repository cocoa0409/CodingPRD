"""Billing statements (system-created) and image studies."""
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint

from core import (DB, auth, body, ok_object, ok_list, serialize, sorted_items,
                  apply_filters, new_entity, touch, get, fail, now_iso,
                  get_clock, parse_iso_dt, f_str, f_int, f_enum)
import logic

bp = Blueprint('billing', __name__)

OD = ('OperationsDirector',)
FC = ('FacilityCoordinator',)
TECH = ('Technologist',)
RR = ('ReadingRadiologist',)
ALL = None


# ---------------------------------------------------------------- statements
@bp.get('/api/billing-statements')
def list_statements():
    auth(ALL)
    items = apply_filters(sorted_items('statements'),
                          {'site_day_id': 'site_day_id',
                           'contract_id': 'contract_id', 'status': 'status'})
    return ok_list(items)


@bp.get('/api/billing-statements/<sid>')
def get_statement(sid):
    auth(ALL)
    return ok_object(serialize(get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')))


@bp.post('/api/billing-statements/<sid>/finalize')
def finalize_statement(sid):
    auth(OD)
    stmt = get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')
    if stmt['status'] != 'PROVISIONAL':
        fail('ERR_STATEMENT_NOT_FINALIZABLE', 409,
             'Statement must be PROVISIONAL to finalize')
    logic.finalize_statement(stmt)
    stmt['status'] = 'FINALIZED'
    touch(stmt)
    return ok_object(serialize(stmt))


@bp.post('/api/billing-statements/<sid>/dispute')
def dispute_statement(sid):
    uid, _ = auth(FC)
    stmt = get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')
    d = body()
    f_str(d, 'reason')
    if stmt['status'] != 'FINALIZED':
        fail('ERR_INVALID_STATE', 409, 'Statement must be FINALIZED to dispute')
    day = DB['site_days'][stmt['site_day_id']]
    if uid != day['facility_id']:
        fail('ERR_FACILITY_MISMATCH', 403,
             'Coordinator facility differs from the statement facility')
    stmt['status'] = 'DISPUTED'
    touch(stmt)
    return ok_object(serialize(stmt))


@bp.post('/api/billing-statements/<sid>/resolve-dispute')
def resolve_dispute(sid):
    auth(OD)
    stmt = get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')
    d = body()
    resolution = f_enum(d, 'resolution', ('UPHOLD', 'ADJUST'))
    adjusted = None
    if resolution == 'ADJUST':
        adjusted = f_int(d, 'adjusted_amount_cents')
    if stmt['status'] != 'DISPUTED':
        fail('ERR_INVALID_STATE', 409,
             'Statement must be DISPUTED to resolve a dispute')
    if resolution == 'ADJUST':
        stmt['final_amount_cents'] = adjusted
        stmt['net_due_cents'] = adjusted - stmt['credit_applied_cents']
    stmt['status'] = 'FINALIZED'
    touch(stmt)
    return ok_object(serialize(stmt))


@bp.post('/api/billing-statements/<sid>/invoice')
def invoice_statement(sid):
    auth(OD)
    stmt = get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')
    if stmt['status'] != 'FINALIZED':
        fail('ERR_INVALID_STATE', 409, 'Statement must be FINALIZED to invoice')
    stmt['status'] = 'INVOICED'
    touch(stmt)
    return ok_object(serialize(stmt))


@bp.post('/api/billing-statements/<sid>/mark-paid')
def mark_paid(sid):
    auth(OD)
    stmt = get('statements', sid, 'ERR_STATEMENT_NOT_FOUND')
    d = body()
    paid_amount_cents = f_int(d, 'paid_amount_cents')
    if stmt['status'] != 'INVOICED':
        fail('ERR_INVALID_STATE', 409, 'Statement must be INVOICED to mark paid')
    if paid_amount_cents != stmt['net_due_cents']:
        fail('ERR_PAYMENT_AMOUNT_MISMATCH', 422,
             'paid_amount_cents must equal net_due_cents')
    stmt['status'] = 'PAID'
    touch(stmt)
    return ok_object(serialize(stmt))


# ---------------------------------------------------------------- image studies
@bp.post('/api/image-studies')
def create_study():
    auth(TECH)
    d = body()
    appointment_id = f_str(d, 'appointment_id')
    study_uid = f_str(d, 'study_uid')
    size_mb = f_int(d, 'size_mb')
    appt = get('appointments', appointment_id, 'ERR_APPOINTMENT_NOT_FOUND')
    if appt['status'] != 'COMPLETED':
        fail('ERR_INVALID_STATE', 409,
             'Image studies require a COMPLETED appointment')
    e = new_entity('studies', {
        'appointment_id': appointment_id,
        'study_uid': study_uid,
        'size_mb': size_mb,
        'transfer_attempts': 0,
        'delivered_at': None,
        'acknowledged_at': None,
        'sla_breached': False,
        'status': 'QUEUED',
    })
    return ok_object(serialize(e), 201)


@bp.get('/api/image-studies')
def list_studies():
    auth(ALL)
    items = apply_filters(sorted_items('studies'),
                          {'appointment_id': 'appointment_id',
                           'status': 'status'})
    return ok_list(items)


@bp.get('/api/image-studies/<sid>')
def get_study(sid):
    auth(ALL)
    return ok_object(serialize(get('studies', sid, 'ERR_STUDY_NOT_FOUND')))


@bp.post('/api/image-studies/<sid>/transmit')
def transmit_study(sid):
    auth(TECH)
    study = get('studies', sid, 'ERR_STUDY_NOT_FOUND')
    if study['status'] != 'QUEUED':
        fail('ERR_STUDY_NOT_TRANSFERRABLE', 409,
             'Transmit requires the study to be QUEUED')
    appt = DB['appointments'][study['appointment_id']]
    day = DB['site_days'][appt['site_day_id']]
    budget = logic.transfer_budget_mb(day)
    study['transfer_attempts'] += 1
    if study['size_mb'] <= budget:
        study['status'] = 'DELIVERED'
        study['delivered_at'] = now_iso()
    else:
        study['status'] = 'TRANSFER_FAILED'
    touch(study)
    return ok_object(serialize(study))


@bp.post('/api/image-studies/<sid>/retry')
def retry_study(sid):
    auth(TECH)
    study = get('studies', sid, 'ERR_STUDY_NOT_FOUND')
    if study['status'] != 'TRANSFER_FAILED':
        fail('ERR_STUDY_NOT_TRANSFERRABLE', 409,
             'Retry requires the study to be TRANSFER_FAILED')
    study['status'] = 'QUEUED'
    touch(study)
    return ok_object(serialize(study))


@bp.post('/api/image-studies/<sid>/acknowledge')
def acknowledge_study(sid):
    auth(RR)
    study = get('studies', sid, 'ERR_STUDY_NOT_FOUND')
    if study['status'] != 'DELIVERED':
        fail('ERR_INVALID_STATE', 409, 'Acknowledge requires DELIVERED')
    appt = DB['appointments'][study['appointment_id']]
    ack_dt = get_clock()
    completed_dt = parse_iso_dt(appt['completed_at'])
    elapsed_minutes = (ack_dt - completed_dt).total_seconds() / 60.0
    study['acknowledged_at'] = now_iso()
    study['sla_breached'] = elapsed_minutes > logic.TRANSFER_SLA_MINUTES
    study['status'] = 'ACKNOWLEDGED'
    touch(study)
    return ok_object(serialize(study))
