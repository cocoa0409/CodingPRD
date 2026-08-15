"""Network resources: facilities, units, contracts (+ period invoice)."""
from flask import Blueprint, request

from core import (DB, auth, body, ok_object, ok_list, serialize, sorted_items,
                  apply_filters, new_entity, touch, get, fail,
                  f_str, f_int, f_num, f_enum, f_enum_array, invalid_request,
                  rhu_cents, dec)
import logic

bp = Blueprint('network', __name__)

OD = ('OperationsDirector',)
ALL = None  # any declared role
MODALITIES = ('MRI', 'CT', 'PET')


def serialize_unit(u):
    return serialize(u)


def serialize_plan_stub(p):
    return serialize(p)


# ---------------------------------------------------------------- facilities
@bp.post('/api/facilities')
def create_facility():
    auth(OD)
    d = body()
    e = new_entity('facilities', {
        'name': f_str(d, 'name'),
        'address': f_str(d, 'address'),
        'supported_modalities': f_enum_array(d, 'supported_modalities', MODALITIES),
        'pad_amps_available': f_int(d, 'pad_amps_available'),
        'pad_voltage': f_int(d, 'pad_voltage'),
        'pad_level_tolerance_deg': f_num(d, 'pad_level_tolerance_deg'),
    })
    return ok_object(serialize(e), 201)


@bp.get('/api/facilities')
def list_facilities():
    auth(ALL)
    return ok_list(sorted_items('facilities'))


@bp.get('/api/facilities/<fid>')
def get_facility(fid):
    auth(ALL)
    return ok_object(serialize(get('facilities', fid, 'ERR_FACILITY_NOT_FOUND')))


# ---------------------------------------------------------------- units
@bp.post('/api/units')
def create_unit():
    auth(OD)
    d = body()
    e = new_entity('units', {
        'unit_code': f_str(d, 'unit_code'),
        'modality': f_enum(d, 'modality', MODALITIES),
        'power_required_amps': f_int(d, 'power_required_amps'),
        'voltage_required': f_int(d, 'voltage_required'),
        'setup_minutes': f_int(d, 'setup_minutes'),
        'teardown_minutes': f_int(d, 'teardown_minutes'),
        'home_base_name': f_str(d, 'home_base_name'),
        'status': 'ACTIVE_SERVICE',
        'active_breakdown_id': None,
    })
    return ok_object(serialize(e), 201)


@bp.get('/api/units')
def list_units():
    auth(ALL)
    items = apply_filters(sorted_items('units'),
                          {'modality': 'modality',
                           'active_breakdown_id': 'active_breakdown_id'})
    return ok_list(items)


@bp.get('/api/units/<uid>')
def get_unit(uid):
    auth(ALL)
    return ok_object(serialize(get('units', uid, 'ERR_UNIT_NOT_FOUND')))


@bp.post('/api/units/<uid>/maintenance')
def unit_maintenance(uid):
    auth(OD)
    unit = get('units', uid, 'ERR_UNIT_NOT_FOUND')
    if unit['status'] != 'ACTIVE_SERVICE':
        fail('ERR_INVALID_STATE', 409, 'Unit must be ACTIVE_SERVICE for maintenance')
    for day in DB['site_days'].values():
        if (day['unit_id'] == uid and
                day['status'] in ('EN_ROUTE', 'SETTING_UP', 'READY', 'IN_SERVICE')):
            fail('ERR_UNIT_HAS_ACTIVE_DAY', 409,
                 'Unit has a site day in flight')
    unit['status'] = 'MAINTENANCE'
    touch(unit)
    return ok_object(serialize(unit))


@bp.post('/api/units/<uid>/return-to-service')
def unit_return_to_service(uid):
    auth(OD)
    unit = get('units', uid, 'ERR_UNIT_NOT_FOUND')
    if unit['status'] != 'MAINTENANCE':
        fail('ERR_INVALID_STATE', 409, 'Unit must be MAINTENANCE')
    unit['status'] = 'ACTIVE_SERVICE'
    touch(unit)
    return ok_object(serialize(unit))


# ---------------------------------------------------------------- contracts
@bp.post('/api/contracts')
def create_contract():
    auth(OD)
    d = body()
    facility_id = f_str(d, 'facility_id')
    billing_model = f_enum(d, 'billing_model', ('PER_DAY', 'PER_SCAN'))
    fields = {
        'facility_id': facility_id,
        'billing_model': billing_model,
        'day_rate_cents': f_int(d, 'day_rate_cents'),
        'scan_rate_cents': f_int(d, 'scan_rate_cents'),
        'included_scan_quota': f_int(d, 'included_scan_quota'),
        'overage_scan_rate_cents': f_int(d, 'overage_scan_rate_cents'),
        'guaranteed_minimum_cents': f_int(d, 'guaranteed_minimum_cents'),
        'no_show_fee_cents': f_int(d, 'no_show_fee_cents'),
        'cancel_notice_hours': f_int(d, 'cancel_notice_hours'),
        'cancel_late_pct': f_num(d, 'cancel_late_pct'),
        'monthly_scan_cap': f_int(d, 'monthly_scan_cap'),
        'interruption_floor_cents': f_int(d, 'interruption_floor_cents'),
    }
    get('facilities', facility_id, 'ERR_FACILITY_NOT_FOUND')
    e = new_entity('contracts', fields)
    return ok_object(serialize(e), 201)


@bp.get('/api/contracts')
def list_contracts():
    auth(ALL)
    items = apply_filters(sorted_items('contracts'), {'facility_id': 'facility_id'})
    return ok_list(items)


@bp.get('/api/contracts/<cid>')
def get_contract(cid):
    auth(ALL)
    return ok_object(serialize(get('contracts', cid, 'ERR_CONTRACT_NOT_FOUND')))


@bp.get('/api/contracts/<cid>/period-invoice')
def period_invoice(cid):
    auth(OD)
    contract = get('contracts', cid, 'ERR_CONTRACT_NOT_FOUND')
    month = request.args.get('month')
    if month is None:
        invalid_request('month query parameter is required (YYYY-MM)')
    import re
    if not re.match(r'^\d{4}-(0[1-9]|1[0-2])$', month):
        invalid_request('month must be YYYY-MM')
    gross = 0
    for stmt in DB['statements'].values():
        if stmt['contract_id'] != cid:
            continue
        if stmt['status'] not in ('FINALIZED', 'INVOICED', 'PAID'):
            continue
        day = DB['site_days'].get(stmt['site_day_id'])
        if day is None:
            continue
        if day['service_date'].startswith(month):
            gross += stmt['net_due_cents']
    if gross >= logic.TIER2_MIN_CENTS:
        tier = logic.TIER2_PCT
    elif gross >= logic.TIER1_MIN_CENTS:
        tier = logic.TIER1_PCT
    else:
        tier = 0
    discount = rhu_cents(dec(gross) * tier / 100)
    return ok_object({
        'month': month,
        'gross_cents': gross,
        'tier_pct': tier,
        'discount_cents': discount,
        'net_cents': gross - discount,
    })
