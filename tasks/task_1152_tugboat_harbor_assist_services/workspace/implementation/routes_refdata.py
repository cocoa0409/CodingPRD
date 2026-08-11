"""Reference data: tugs, vessels, pilots, crew members, tariff rates."""
from flask import Blueprint

from db import store, new_id, stamp_new
from util import (
    authenticate, require_roles, not_found, ok_object, ok_list,
    json_body, Check, get_str, get_int, get_num, get_bool, get_enum, get_dt,
    parse_pagination, check_enum_filter, page_slice, store_get,
)
from calc import ser_tug, ser_vessel, ser_pilot, ser_crew, ser_tariff

bp = Blueprint('refdata', __name__)

ADMIN = ('PortAdmin',)
ALL = ('PortAdmin', 'VesselAgent', 'PortDispatcher', 'Pilot',
       'TugCaptain', 'MarineSurveyor', 'ClaimsAdjuster')

TUG_STATUSES = {'AVAILABLE', 'RESTRICTED', 'OUT_OF_SERVICE'}
LICENSE_CLASSES = {'CLASS_I', 'CLASS_II', 'CLASS_III'}
CREW_ROLES = {'CAPTAIN', 'MATE', 'ENGINEER', 'DECKHAND'}
MANEUVER_TYPES = {'DOCKING', 'UNDOCKING', 'SHIFTING', 'ESCORT', 'TOWAGE'}


# ------------------------------------------------------------------ tugs

@bp.route('/api/tugs', methods=['POST'])
def create_tug():
    _, role = authenticate()
    require_roles(role, ADMIN)
    body = json_body()
    c = Check()
    name = get_str(body, 'name', c)
    bp_tons = get_num(body, 'bollard_pull_tons', c, lo=0, lo_exclusive=True)
    hp = get_int(body, 'horsepower', c, lo=0, lo_exclusive=True)
    rate = get_int(body, 'hourly_rate_cents', c, lo=0)
    insured = get_int(body, 'insured_value_cents', c, lo=0)
    home_port = get_str(body, 'home_port', c, required=False)
    c.raise_deferred()
    rec = {
        'id': new_id(), 'name': name, 'bollard_pull_tons': bp_tons,
        'horsepower': hp, 'hourly_rate_cents': rate,
        'insured_value_cents': insured, 'home_port': home_port,
        'operational_status': 'AVAILABLE',
    }
    stamp_new(rec)
    store.tugs[rec['id']] = rec
    return ok_object(ser_tug(rec), 201)


@bp.route('/api/tugs', methods=['GET'])
def list_tugs():
    authenticate()
    c = Check()
    limit, offset = parse_pagination(c)
    status = check_enum_filter('operational_status', TUG_STATUSES, c)
    c.raise_deferred()
    recs = [t for t in store.tugs.values()
            if status is None or t['operational_status'] == status]
    page, total = page_slice(recs, limit, offset)
    return ok_list([ser_tug(t) for t in page], limit, offset, total)


@bp.route('/api/tugs/<tid>', methods=['GET'])
def get_tug(tid):
    authenticate()
    tug = store.tugs.get(tid)
    if tug is None:
        not_found('tug')
    return ok_object(ser_tug(tug))


# ------------------------------------------------------------------ vessels

@bp.route('/api/vessels', methods=['POST'])
def create_vessel():
    _, role = authenticate()
    require_roles(role, ADMIN)
    body = json_body()
    c = Check()
    name = get_str(body, 'name', c)
    imo = get_str(body, 'imo_number', c)
    dwt = get_int(body, 'deadweight_tonnage', c, lo=0, lo_exclusive=True)
    loa = get_num(body, 'loa_meters', c, lo=0, lo_exclusive=True)
    if imo is not None:
        for v in store.vessels.values():
            if v['imo_number'] == imo:
                c.bad_request = True
                break
    c.raise_deferred()
    rec = {
        'id': new_id(), 'name': name, 'imo_number': imo,
        'deadweight_tonnage': dwt, 'loa_meters': loa,
        'outstanding_billed_cents': 0,
    }
    stamp_new(rec)
    store.vessels[rec['id']] = rec
    return ok_object(ser_vessel(rec), 201)


@bp.route('/api/vessels/<vid>', methods=['GET'])
def get_vessel(vid):
    authenticate()
    v = store.vessels.get(vid)
    if v is None:
        not_found('vessel')
    return ok_object(ser_vessel(v))


# ------------------------------------------------------------------ pilots

@bp.route('/api/pilots', methods=['POST'])
def create_pilot():
    _, role = authenticate()
    require_roles(role, ADMIN)
    body = json_body()
    c = Check()
    name = get_str(body, 'name', c)
    lc = get_enum(body, 'license_class', LICENSE_CLASSES, c)
    active = get_bool(body, 'active', c, required=False)
    c.raise_deferred()
    rec = {
        'id': new_id(), 'name': name, 'license_class': lc,
        'active': True if active is None else active,
    }
    stamp_new(rec)
    store.pilots[rec['id']] = rec
    return ok_object(ser_pilot(rec), 201)


@bp.route('/api/pilots/<pid>', methods=['GET'])
def get_pilot(pid):
    authenticate()
    p = store.pilots.get(pid)
    if p is None:
        not_found('pilot')
    return ok_object(ser_pilot(p))


# ------------------------------------------------------------------ crew

@bp.route('/api/crew-members', methods=['POST'])
def create_crew_member():
    _, role = authenticate()
    require_roles(role, ADMIN)
    body = json_body()
    c = Check()
    full_name = get_str(body, 'full_name', c)
    crew_role = get_enum(body, 'crew_role', CREW_ROLES, c)
    mwh = get_int(body, 'max_watch_hours', c, required=False, lo=1)
    c.raise_deferred()
    rec = {
        'id': new_id(), 'full_name': full_name, 'crew_role': crew_role,
        'max_watch_hours': 12 if mwh is None else mwh,
    }
    stamp_new(rec)
    store.crew_members[rec['id']] = rec
    return ok_object(ser_crew(rec), 201)


@bp.route('/api/crew-members/<cid>', methods=['GET'])
def get_crew_member(cid):
    authenticate()
    cm = store.crew_members.get(cid)
    if cm is None:
        not_found('crew member')
    return ok_object(ser_crew(cm))


# ------------------------------------------------------------------ tariffs

@bp.route('/api/tariff-rates', methods=['POST'])
def create_tariff():
    _, role = authenticate()
    require_roles(role, ADMIN)
    body = json_body()
    c = Check()
    code = get_str(body, 'tariff_code', c)
    maneuver = get_enum(body, 'maneuver_type', MANEUVER_TYPES, c)
    base_fee = get_int(body, 'base_fee_cents', c, lo=0)
    sb_rate = get_int(body, 'standby_block_rate_cents', c, lo=0)
    free_min = get_int(body, 'free_standby_minutes', c, required=False, lo=0)
    sb_min = get_int(body, 'standby_block_minutes', c, required=False, lo=1)
    surcharge = get_num(body, 'weather_surcharge_pct', c, required=False, lo=0)
    eff_from = get_dt(body, 'effective_from', c)
    eff_to = get_dt(body, 'effective_to', c)
    if code is not None:
        for t in store.tariff_rates.values():
            if t['tariff_code'] == code:
                c.bad_request = True
                break
    if eff_from is not None and eff_to is not None and eff_to < eff_from:
        c.bad_request = True
    c.raise_deferred()
    rec = {
        'id': new_id(), 'tariff_code': code, 'maneuver_type': maneuver,
        'base_fee_cents': base_fee,
        'free_standby_minutes': 30 if free_min is None else free_min,
        'standby_block_minutes': 15 if sb_min is None else sb_min,
        'standby_block_rate_cents': sb_rate,
        'weather_surcharge_pct': 0.0 if surcharge is None else surcharge,
        'effective_from': eff_from, 'effective_to': eff_to,
    }
    stamp_new(rec)
    store.tariff_rates[rec['id']] = rec
    return ok_object(ser_tariff(rec), 201)


@bp.route('/api/tariff-rates/<tid>', methods=['GET'])
def get_tariff(tid):
    authenticate()
    t = store.tariff_rates.get(tid)
    if t is None:
        not_found('tariff rate')
    return ok_object(ser_tariff(t))
