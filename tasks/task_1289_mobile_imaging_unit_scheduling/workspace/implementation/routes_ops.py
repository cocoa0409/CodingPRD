"""Operational resources: technologists, staffing assignments, patient
appointments, setup checklists."""
from flask import Blueprint

from core import (DB, auth, body, ok_object, ok_list, serialize, sorted_items,
                  apply_filters, new_entity, touch, get, fail, now_iso,
                  f_str, f_int, f_num, f_bool, f_enum, f_enum_array,
                  f_time, to_minutes)
import logic

bp = Blueprint('ops', __name__)

OD = ('OperationsDirector',)
FC = ('FacilityCoordinator',)
TECH = ('Technologist',)
ALL = None
MODALITIES = ('MRI', 'CT', 'PET')
EXAM_TYPES = ('CT_HEAD', 'CT_CHEST', 'MRI_BRAIN', 'PET_ONCO')


# ---------------------------------------------------------------- technologists
def serialize_tech(t):
    out = serialize(t)
    out['current_day_dose_msv'] = float(logic.tech_current_day_dose(t['id']))
    out['monthly_dose_msv'] = float(logic.tech_month_dose(t['id']))
    return out


@bp.post('/api/technologists')
def create_technologist():
    auth(OD)
    d = body()
    e = new_entity('technologists', {
        'full_name': f_str(d, 'full_name'),
        'modality_certs': f_enum_array(d, 'modality_certs', MODALITIES),
        'home_base_name': f_str(d, 'home_base_name'),
        'max_daily_drive_minutes': f_int(d, 'max_daily_drive_minutes'),
    })
    return ok_object(serialize_tech(e), 201)


@bp.get('/api/technologists')
def list_technologists():
    auth(ALL)
    return ok_list(sorted_items('technologists'), serialize_tech)


@bp.get('/api/technologists/<tid>')
def get_technologist(tid):
    auth(ALL)
    return ok_object(serialize_tech(get('technologists', tid,
                                        'ERR_TECHNOLOGIST_NOT_FOUND')))


# ---------------------------------------------------------------- staffing
@bp.post('/api/staffing-assignments')
def create_staffing():
    auth(OD)
    d = body()
    site_day_id = f_str(d, 'site_day_id')
    technologist_id = f_str(d, 'technologist_id')
    estimated_drive_minutes = f_int(d, 'estimated_drive_minutes')
    day = get('site_days', site_day_id, 'ERR_SITE_DAY_NOT_FOUND')
    tech = get('technologists', technologist_id, 'ERR_TECHNOLOGIST_NOT_FOUND')
    # radiation safety (6): projected dose gate
    projected = logic.projected_dose(technologist_id, day)
    if projected > logic.TECH_DAILY_DOSE_LIMIT_MSV:
        fail('ERR_DOSE_LIMIT_EXCEEDED', 422,
             'projected_dose_msv exceeds the 5.0 mSv daily limit')
    # credential linkage (9): modality cert
    unit = DB['units'][day['unit_id']]
    if unit['modality'] not in tech['modality_certs']:
        fail('ERR_MODALITY_CERT_MISMATCH', 422,
             'Technologist lacks certification for the unit modality')
    # resource conflicts (11): single-day staffing then drive time
    for s in DB['staffing'].values():
        if (s['technologist_id'] == technologist_id and s['status'] == 'ASSIGNED'):
            other_day = DB['site_days'].get(s['site_day_id'])
            if other_day is not None and \
                    other_day['service_date'] == day['service_date']:
                fail('ERR_STAFFING_DATE_CONFLICT', 409,
                     'Technologist already ASSIGNED on that service_date')
    if estimated_drive_minutes > tech['max_daily_drive_minutes']:
        fail('ERR_DRIVE_TIME_EXCEEDED', 422,
             'estimated_drive_minutes exceeds max_daily_drive_minutes')
    e = new_entity('staffing', {
        'site_day_id': site_day_id,
        'technologist_id': technologist_id,
        'estimated_drive_minutes': estimated_drive_minutes,
        'projected_dose_msv': float(projected),
        'status': 'ASSIGNED',
        'release_reason': None,
    })
    return ok_object(serialize(e), 201)


@bp.get('/api/staffing-assignments')
def list_staffing():
    auth(ALL)
    items = apply_filters(sorted_items('staffing'),
                          {'site_day_id': 'site_day_id',
                           'technologist_id': 'technologist_id',
                           'status': 'status'})
    return ok_list(items)


@bp.get('/api/staffing-assignments/<sid>')
def get_staffing(sid):
    auth(ALL)
    return ok_object(serialize(get('staffing', sid, 'ERR_STAFFING_NOT_FOUND')))


@bp.post('/api/staffing-assignments/<sid>/release')
def release_staffing(sid):
    auth(OD)
    s = get('staffing', sid, 'ERR_STAFFING_NOT_FOUND')
    if s['status'] != 'ASSIGNED':
        fail('ERR_INVALID_STATE', 409, 'Assignment must be ASSIGNED to release')
    s['status'] = 'RELEASED'
    s['release_reason'] = 'MANUAL'
    touch(s)
    return ok_object(serialize(s))


# ---------------------------------------------------------------- appointments
def serialize_appt(a):
    out = serialize(a)
    out['actual_dose_msv'] = float(logic.appointment_actual_dose(a['id']))
    return out


def _staffed(day_id, tech_id):
    return any(s for s in logic.staffing_of_day(day_id)
               if s['technologist_id'] == tech_id and s['status'] == 'ASSIGNED')


@bp.post('/api/appointments')
def create_appointment():
    uid, _ = auth(FC)
    d = body()
    site_day_id = f_str(d, 'site_day_id')
    patient_ref = f_str(d, 'patient_ref')
    exam_type = f_enum(d, 'exam_type', EXAM_TYPES)
    scheduled_start = f_time(d, 'scheduled_start')
    duration_minutes = f_int(d, 'duration_minutes')
    if duration_minutes <= 0:
        fail('ERR_INVALID_REQUEST', 400, 'duration_minutes must be positive')
    sedation_required = f_bool(d, 'sedation_required', required=False,
                               default=False)
    estimated_dose_msv = f_num(d, 'estimated_dose_msv')
    insurance_preauth = f_str(d, 'insurance_preauth', required=False,
                              default=None)
    # existence (3)
    day = get('site_days', site_day_id, 'ERR_SITE_DAY_NOT_FOUND')
    # state (5): bookable
    if day['status'] in ('INTERRUPTED', 'CANCELLED', 'COMPLETED', 'RESCHEDULED'):
        fail('ERR_SITE_DAY_NOT_BOOKABLE', 409,
             'Site day accepts no appointments in its current state')
    # identity/ownership (8): coordinator facility match
    if uid != day['facility_id']:
        fail('ERR_FACILITY_MISMATCH', 403,
             'Coordinator facility differs from the site day facility')
    # credential linkage (9): exam modality prefix vs unit modality
    unit = DB['units'][day['unit_id']]
    if logic.EXAM_MODALITY[exam_type] != unit['modality']:
        fail('ERR_MODALITY_NOT_SUPPORTED', 422,
             'Exam modality prefix differs from the unit modality')
    # resource conflicts (11): slot inside window, then overlap
    start = to_minutes(scheduled_start)
    eff_end = start + duration_minutes + \
        (logic.SEDATION_BUFFER_MINUTES if sedation_required else 0)
    if start < to_minutes(day['first_patient_time']) or \
            eff_end > to_minutes(day['last_patient_time']):
        fail('ERR_SLOT_OUTSIDE_WINDOW', 422,
             'Appointment slot falls outside the on-site window')
    for a in logic.appointments_of_day(site_day_id):
        if a['status'] not in logic.OPEN_APPT_STATUSES:
            continue
        a_start = to_minutes(a['scheduled_start'])
        a_end = a_start + a['duration_minutes'] + \
            (logic.SEDATION_BUFFER_MINUTES if a['sedation_required'] else 0)
        if start < a_end + logic.TURNOVER_MINUTES and \
                a_start < eff_end + logic.TURNOVER_MINUTES:
            fail('ERR_SLOT_OVERLAP', 409,
                 'Appointment collides with an existing slot')
    # fiscal (13): monthly scan cap (checked last)
    contract = DB['contracts'][day['contract_id']]
    month = day['service_date'][:7]
    count = 0
    for other_day in DB['site_days'].values():
        if other_day['contract_id'] != contract['id']:
            continue
        if not other_day['service_date'].startswith(month):
            continue
        for a in logic.appointments_of_day(other_day['id']):
            if a['status'] != 'CANCELLED':
                count += 1
    if count >= contract['monthly_scan_cap']:
        fail('ERR_SCAN_CAP_EXCEEDED', 402,
             'Contract monthly scan cap reached')
    e = new_entity('appointments', {
        'site_day_id': site_day_id,
        'patient_ref': patient_ref,
        'exam_type': exam_type,
        'scheduled_start': scheduled_start,
        'duration_minutes': duration_minutes,
        'sedation_required': sedation_required,
        'estimated_dose_msv': estimated_dose_msv,
        'insurance_preauth': insurance_preauth,
        'status': 'REQUESTED',
        'cancel_reason': None,
        'completed_at': None,
    })
    return ok_object(serialize_appt(e), 201)


@bp.get('/api/appointments')
def list_appointments():
    auth(ALL)
    items = apply_filters(sorted_items('appointments'),
                          {'site_day_id': 'site_day_id', 'status': 'status'})
    return ok_list(items, serialize_appt)


@bp.get('/api/appointments/<aid>')
def get_appointment(aid):
    auth(ALL)
    return ok_object(serialize_appt(get('appointments', aid,
                                        'ERR_APPOINTMENT_NOT_FOUND')))


@bp.post('/api/appointments/<aid>/confirm')
def confirm_appointment(aid):
    auth(OD)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] != 'REQUESTED':
        fail('ERR_INVALID_STATE', 409, 'Appointment must be REQUESTED')
    a['status'] = 'CONFIRMED'
    touch(a)
    return ok_object(serialize_appt(a))


@bp.post('/api/appointments/<aid>/check-in')
def check_in(aid):
    auth(FC)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] != 'CONFIRMED':
        fail('ERR_INVALID_STATE', 409, 'Appointment must be CONFIRMED')
    day = DB['site_days'][a['site_day_id']]
    if day['status'] not in ('READY', 'IN_SERVICE'):
        fail('ERR_SITE_DAY_NOT_IN_SERVICE', 409,
             'Site day must be READY or IN_SERVICE for check-in')
    a['status'] = 'CHECKED_IN'
    touch(a)
    return ok_object(serialize_appt(a))


@bp.post('/api/appointments/<aid>/begin-scan')
def begin_scan(aid):
    uid, _ = auth(TECH)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] != 'CHECKED_IN':
        fail('ERR_INVALID_STATE', 409, 'Appointment must be CHECKED_IN')
    day = DB['site_days'][a['site_day_id']]
    if day['status'] != 'IN_SERVICE':
        fail('ERR_SITE_DAY_NOT_IN_SERVICE', 409,
             'Site day must be IN_SERVICE')
    if not _staffed(day['id'], uid):
        fail('ERR_TECHNOLOGIST_NOT_STAFFED', 422,
             'Acting technologist holds no ASSIGNED staffing on this day')
    a['status'] = 'SCANNING'
    touch(a)
    return ok_object(serialize_appt(a))


@bp.post('/api/appointments/<aid>/complete-scan')
def complete_scan(aid):
    uid, _ = auth(TECH)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] != 'SCANNING':
        fail('ERR_INVALID_STATE', 409, 'Appointment must be SCANNING')
    if not _staffed(a['site_day_id'], uid):
        fail('ERR_TECHNOLOGIST_NOT_STAFFED', 422,
             'Acting technologist holds no ASSIGNED staffing on this day')
    a['status'] = 'COMPLETED'
    a['completed_at'] = now_iso()
    touch(a)
    return ok_object(serialize_appt(a))


@bp.post('/api/appointments/<aid>/cancel')
def cancel_appointment(aid):
    auth(FC)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] not in ('REQUESTED', 'CONFIRMED'):
        fail('ERR_APPOINTMENT_NOT_CANCELLABLE', 409,
             'Manual cancel allowed only from REQUESTED or CONFIRMED')
    a['status'] = 'CANCELLED'
    a['cancel_reason'] = 'PATIENT_CANCELLED'
    touch(a)
    return ok_object(serialize_appt(a))


@bp.post('/api/appointments/<aid>/mark-no-show')
def mark_no_show(aid):
    auth(FC)
    a = get('appointments', aid, 'ERR_APPOINTMENT_NOT_FOUND')
    if a['status'] != 'CONFIRMED':
        fail('ERR_INVALID_STATE', 409, 'Appointment must be CONFIRMED')
    day = DB['site_days'][a['site_day_id']]
    if day['status'] != 'IN_SERVICE':
        fail('ERR_SITE_DAY_NOT_IN_SERVICE', 409,
             'Site day must be IN_SERVICE')
    a['status'] = 'NO_SHOW'
    touch(a)
    return ok_object(serialize_appt(a))


# ---------------------------------------------------------------- checklists
CHECKLIST_ITEMS = {
    'POWER_VERIFY': 'power_verify_passed',
    'PAD_LEVEL': 'pad_level_passed',
    'CHILLER': 'chiller_passed',
    'RF_SHIELD': 'rf_shield_passed',
    'NETWORK_LINK': 'network_link_passed',
}


def _checklist_status(c):
    booleans = (c['power_verify_passed'], c['pad_level_passed'],
                c['chiller_passed'], c['rf_shield_passed'],
                c['network_link_passed'])
    return 'ALL_PASSED' if all(booleans) else 'HAS_FAILURES'


@bp.post('/api/setup-checklists')
def create_checklist():
    auth(TECH)
    d = body()
    site_day_id = f_str(d, 'site_day_id')
    fields = {
        'site_day_id': site_day_id,
        'power_verify_passed': f_bool(d, 'power_verify_passed'),
        'measured_amps': f_int(d, 'measured_amps'),
        'pad_level_passed': f_bool(d, 'pad_level_passed'),
        'chiller_passed': f_bool(d, 'chiller_passed'),
        'rf_shield_passed': f_bool(d, 'rf_shield_passed'),
        'network_link_passed': f_bool(d, 'network_link_passed'),
        'measured_uplink_mbps': f_int(d, 'measured_uplink_mbps'),
    }
    day = get('site_days', site_day_id, 'ERR_SITE_DAY_NOT_FOUND')
    if day['status'] != 'SETTING_UP':
        fail('ERR_INVALID_STATE', 409,
             'Checklist may be recorded only while the day is SETTING_UP')
    if logic.checklist_of_day(site_day_id) is not None:
        fail('ERR_CHECKLIST_EXISTS', 409, 'Exactly one checklist per site day')
    fields['status'] = _checklist_status(fields)
    e = new_entity('checklists', fields)
    return ok_object(serialize(e), 201)


@bp.get('/api/setup-checklists')
def list_checklists():
    auth(ALL)
    items = apply_filters(sorted_items('checklists'),
                          {'site_day_id': 'site_day_id'})
    return ok_list(items)


@bp.get('/api/setup-checklists/<cid>')
def get_checklist(cid):
    auth(ALL)
    return ok_object(serialize(get('checklists', cid, 'ERR_CHECKLIST_NOT_FOUND')))


@bp.post('/api/setup-checklists/<cid>/record-item')
def record_item(cid):
    auth(TECH)
    c = get('checklists', cid, 'ERR_CHECKLIST_NOT_FOUND')
    d = body()
    item_key = f_enum(d, 'item_key', tuple(CHECKLIST_ITEMS.keys()))
    passed = f_bool(d, 'passed')
    measured_value = f_int(d, 'measured_value', required=False, default=None)
    c[CHECKLIST_ITEMS[item_key]] = passed
    if measured_value is not None:
        if item_key == 'POWER_VERIFY':
            c['measured_amps'] = measured_value
        elif item_key == 'NETWORK_LINK':
            c['measured_uplink_mbps'] = measured_value
    c['status'] = _checklist_status(c)
    touch(c)
    return ok_object(serialize(c))
