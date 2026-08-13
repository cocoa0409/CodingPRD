"""Compliance resources: breakdown events, radiation dose records,
accreditation records."""
from flask import Blueprint

from core import (DB, auth, body, ok_object, ok_list, serialize, sorted_items,
                  apply_filters, new_entity, touch, get, fail, clock_date,
                  f_str, f_num, f_enum, f_date, dec)
from decimal import Decimal, ROUND_HALF_UP
import logic

bp = Blueprint('compliance', __name__)

OD = ('OperationsDirector',)
TECH = ('Technologist',)
CO = ('ComplianceOfficer',)
ALL = None
SEVERITIES = ('MINOR', 'MAJOR', 'CRITICAL')
BODIES = ('ACR', 'IAC', 'TJC')
MODALITIES = ('MRI', 'CT', 'PET')


# ---------------------------------------------------------------- breakdowns
@bp.post('/api/breakdowns')
def create_breakdown():
    auth(('Technologist', 'OperationsDirector'))
    d = body()
    unit_id = f_str(d, 'unit_id')
    site_day_id = f_str(d, 'site_day_id', required=False, default=None)
    severity = f_enum(d, 'severity', SEVERITIES)
    description = f_str(d, 'description')
    unit = get('units', unit_id, 'ERR_UNIT_NOT_FOUND')
    day = None
    if site_day_id is not None:
        day = get('site_days', site_day_id, 'ERR_SITE_DAY_NOT_FOUND')
    if severity == 'CRITICAL' and unit['status'] != 'ACTIVE_SERVICE':
        fail('ERR_UNIT_OUT_OF_SERVICE', 409,
             'Unit is not ACTIVE_SERVICE; CRITICAL breakdown rejected')
    event = new_entity('breakdowns', {
        'unit_id': unit_id,
        'site_day_id': site_day_id,
        'severity': severity,
        'description': description,
        'status': 'REPORTED',
        'downtime_hours': None,
        'resolution_notes': None,
    })
    # severity-driven cascades
    if severity in ('MAJOR', 'CRITICAL') and day is not None and \
            day['status'] in ('SETTING_UP', 'READY', 'IN_SERVICE'):
        logic.interrupt_day(day, 'BREAKDOWN')
    if severity == 'CRITICAL':
        unit['status'] = 'OUT_OF_SERVICE'
        unit['active_breakdown_id'] = event['id']
        touch(unit)
    return ok_object(serialize(event), 201)


@bp.get('/api/breakdowns')
def list_breakdowns():
    auth(ALL)
    items = apply_filters(sorted_items('breakdowns'),
                          {'unit_id': 'unit_id', 'site_day_id': 'site_day_id'})
    return ok_list(items)


@bp.get('/api/breakdowns/<bid>')
def get_breakdown(bid):
    auth(ALL)
    return ok_object(serialize(get('breakdowns', bid, 'ERR_BREAKDOWN_NOT_FOUND')))


@bp.post('/api/breakdowns/<bid>/resolve')
def resolve_breakdown(bid):
    auth(OD)
    event = get('breakdowns', bid, 'ERR_BREAKDOWN_NOT_FOUND')
    d = body()
    downtime_hours = f_num(d, 'downtime_hours')
    resolution_notes = f_str(d, 'resolution_notes')
    if event['status'] != 'REPORTED':
        fail('ERR_BREAKDOWN_ALREADY_RESOLVED', 409,
             'Breakdown must be REPORTED to resolve')
    event['downtime_hours'] = downtime_hours
    event['resolution_notes'] = resolution_notes
    event['status'] = 'RESOLVED'
    touch(event)
    unit = DB['units'].get(event['unit_id'])
    if (event['severity'] == 'CRITICAL' and unit is not None
            and unit.get('active_breakdown_id') == event['id']):
        unit['status'] = 'ACTIVE_SERVICE'
        unit['active_breakdown_id'] = None
        touch(unit)
    return ok_object(serialize(event))


# ---------------------------------------------------------------- dose records
@bp.post('/api/dose-records')
def create_dose_record():
    uid, _ = auth(TECH)
    d = body()
    appointment_id = f_str(d, 'appointment_id')
    technologist_id = f_str(d, 'technologist_id')
    dose_msv = f_num(d, 'dose_msv')
    appt = get('appointments', appointment_id, 'ERR_APPOINTMENT_NOT_FOUND')
    tech = get('technologists', technologist_id, 'ERR_TECHNOLOGIST_NOT_FOUND')
    # state (5)
    if appt['status'] != 'COMPLETED':
        fail('ERR_INVALID_STATE', 409,
             'Dose records require a COMPLETED appointment')
    # radiation safety (6): ionizing modalities only
    if appt['exam_type'] not in logic.IONIZING_EXAMS:
        fail('ERR_DOSE_NOT_APPLICABLE', 422,
             'Dose records apply only to CT/PET exams')
    # identity/ownership (8)
    if technologist_id != uid:
        fail('ERR_TECHNOLOGIST_IDENTITY_MISMATCH', 403,
             'technologist_id must equal X-User-ID')
    staffed = any(s for s in logic.staffing_of_day(appt['site_day_id'])
                  if s['technologist_id'] == uid and s['status'] == 'ASSIGNED')
    if not staffed:
        fail('ERR_TECHNOLOGIST_NOT_STAFFED', 422,
             'Acting technologist holds no ASSIGNED staffing on this day')
    dose_1dp = dec(dose_msv).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    drl_exceeded = dose_1dp > logic.DRL_MSV[appt['exam_type']]
    e = new_entity('dose_records', {
        'appointment_id': appointment_id,
        'technologist_id': technologist_id,
        'dose_msv': dose_msv,
        'drl_exceeded': drl_exceeded,
    }, common=False)  # immutable: no updated_at, no version
    # derived-field recomputation bumps carrier resources (PRD 2.5)
    touch(appt)
    touch(tech)
    return ok_object(serialize(e), 201)


@bp.get('/api/dose-records')
def list_dose_records():
    auth(ALL)
    items = apply_filters(sorted_items('dose_records'),
                          {'appointment_id': 'appointment_id',
                           'technologist_id': 'technologist_id'})
    return ok_list(items)


@bp.get('/api/dose-records/<rid>')
def get_dose_record(rid):
    auth(ALL)
    return ok_object(serialize(get('dose_records', rid, 'ERR_NOT_FOUND')))


# ---------------------------------------------------------------- accreditations
@bp.post('/api/accreditations')
def create_accreditation():
    auth(CO)
    d = body()
    unit_id = f_str(d, 'unit_id')
    accrediting_body = f_enum(d, 'accrediting_body', BODIES)
    modality = f_enum(d, 'modality', MODALITIES)
    issued_on = f_date(d, 'issued_on')
    expires_on = f_date(d, 'expires_on')
    get('units', unit_id, 'ERR_UNIT_NOT_FOUND')
    e = new_entity('accreditations', {
        'unit_id': unit_id,
        'accrediting_body': accrediting_body,
        'modality': modality,
        'issued_on': issued_on,
        'expires_on': expires_on,
        'status': logic.derive_acc_status(expires_on, clock_date()),
        'suspend_reason': None,
    })
    return ok_object(serialize(e), 201)


@bp.get('/api/accreditations')
def list_accreditations():
    auth(ALL)
    items = apply_filters(sorted_items('accreditations'),
                          {'unit_id': 'unit_id', 'status': 'status'})
    return ok_list(items)


@bp.get('/api/accreditations/<aid>')
def get_accreditation(aid):
    auth(ALL)
    return ok_object(serialize(get('accreditations', aid,
                                   'ERR_ACCREDITATION_NOT_FOUND')))


@bp.post('/api/accreditations/<aid>/suspend')
def suspend_accreditation(aid):
    auth(CO)
    rec = get('accreditations', aid, 'ERR_ACCREDITATION_NOT_FOUND')
    d = body()
    reason = f_str(d, 'reason')
    if rec['status'] not in ('ACTIVE', 'EXPIRING_SOON'):
        fail('ERR_INVALID_STATE', 409,
             'Only ACTIVE or EXPIRING_SOON records may be suspended')
    rec['status'] = 'SUSPENDED'
    rec['suspend_reason'] = reason
    touch(rec)
    return ok_object(serialize(rec))


@bp.post('/api/accreditations/<aid>/reinstate')
def reinstate_accreditation(aid):
    auth(CO)
    rec = get('accreditations', aid, 'ERR_ACCREDITATION_NOT_FOUND')
    if rec['status'] != 'SUSPENDED':
        fail('ERR_INVALID_STATE', 409, 'Only SUSPENDED records may be reinstated')
    rec['status'] = logic.derive_acc_status(rec['expires_on'], clock_date())
    rec['suspend_reason'] = None
    touch(rec)
    return ok_object(serialize(rec))
