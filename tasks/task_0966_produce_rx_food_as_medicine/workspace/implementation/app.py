#!/usr/bin/env python3
"""Produce-Rx & Food-as-Medicine Program API.

Single-file Flask implementation. In-memory stores only; no persistence.
Logical clock default: 2026-05-01T00:00:00Z.
"""

import itertools
import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, jsonify, request

app = Flask(__name__)
app.url_map.strict_slashes = False

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

class _Clock:
    def __init__(self):
        self.current = datetime(2026, 5, 1, 0, 0, 0, tzinfo=timezone.utc)


CLOCK = _Clock()


def now_dt():
    return CLOCK.current


def iso(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '%03dZ' % (dt.microsecond // 1000)


def wall_iso():
    return iso(datetime.now(timezone.utc))


def parse_dt(s):
    if not isinstance(s, str):
        raise ValueError('not a string')
    t = s.strip()
    if t.endswith('Z'):
        t = t[:-1] + '+00:00'
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


def is_valid_date(s):
    if not isinstance(s, str) or not DATE_RE.match(s):
        return False
    try:
        datetime.strptime(s, '%Y-%m-%d')
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------------------
# Errors / envelope
# ---------------------------------------------------------------------------

class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


def err(error_id, status, message):
    raise ApiError(error_id, status, message)


def _meta():
    return {
        'api_request_id': 'req_' + ''.join(
            random.choices(string.ascii_letters + string.digits, k=20)),
        'api_request_timestamp': wall_iso(),
    }


def success(data, code=200, rtype='object', page=None):
    m = _meta()
    if page is not None:
        m.update(page)
    return jsonify({'meta': m, 'response_type': rtype, 'data': data}), code


@app.errorhandler(ApiError)
def handle_api_error(e):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': e.error_id, 'message': e.message},
    }), e.status


@app.errorhandler(404)
def handle_404(e):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': 'ERR_NOT_FOUND',
                 'message': 'Referenced resource id does not exist'},
    }), 404


@app.errorhandler(405)
def handle_405(e):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': 'ERR_NOT_FOUND',
                 'message': 'Referenced resource id does not exist'},
    }), 404


@app.errorhandler(Exception)
def handle_500(e):
    return jsonify({
        'meta': _meta(),
        'response_type': 'error',
        'data': {'error_id': 'ERR_INTERNAL', 'message': 'Internal server error'},
    }), 500


# ---------------------------------------------------------------------------
# Stores (in-memory only, start empty)
# ---------------------------------------------------------------------------

PROGRAMS = {}
FUNDERS = {}
POOLS = {}
CLINICS = {}
RETAILERS = {}
PATIENTS = {}
REFERRALS = {}
ENROLLMENTS = {}
CYCLES = {}
VOUCHERS = {}
REDEMPTIONS = {}
SESSIONS = {}
COMPLETIONS = {}
READINGS = {}
REPORTS = {}
RENEWALS = {}

SEQ = itertools.count(1)


def new_entity(fields, thin=False):
    e = dict(fields)
    e['id'] = str(uuid.uuid4())
    ts = iso(now_dt())
    e['created_at'] = ts
    if not thin:
        e['updated_at'] = ts
        e['version'] = 1
    e['_seq'] = next(SEQ)
    return e


def touch(e):
    e['updated_at'] = iso(now_dt())
    e['version'] = e.get('version', 1) + 1


def pub(e):
    return {k: v for k, v in e.items() if not k.startswith('_')}


def get_or_404(store, key):
    if not isinstance(key, str):
        err('ERR_VALIDATION', 400, 'Missing or invalid id field')
    e = store.get(key)
    if e is None:
        err('ERR_NOT_FOUND', 404, 'Referenced resource id does not exist')
    return e


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------

ROLE_NAMES = {'ProgramAdmin', 'FunderAnalyst', 'ClinicStaff', 'Participant',
              'RetailerStaff', 'Educator'}


def auth(*allowed):
    uid = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not uid or not role or role not in ROLE_NAMES:
        err('ERR_UNAUTHENTICATED', 401,
            'Missing or unknown X-User-Role / X-User-ID headers')
    if allowed and role not in allowed:
        err('ERR_FORBIDDEN', 403, 'Role not allowed on this endpoint')
    return uid, role


def json_body():
    b = request.get_json(silent=True)
    if not isinstance(b, dict):
        return {}
    return b


# ---------------------------------------------------------------------------
# Field validators (priority 4 shape checks -> ERR_VALIDATION 400)
# ---------------------------------------------------------------------------

def req_str(b, f):
    v = b.get(f)
    if not isinstance(v, str) or v == '':
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


def opt_str(b, f):
    v = b.get(f)
    if v is None:
        return None
    if not isinstance(v, str):
        err('ERR_VALIDATION', 400, 'Invalid field: %s' % f)
    return v


def req_int(b, f, minv=None):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, int):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    if minv is not None and v < minv:
        err('ERR_VALIDATION', 400, 'Field out of range: %s' % f)
    return v


def req_num(b, f):
    v = b.get(f)
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


def req_bool(b, f):
    v = b.get(f)
    if not isinstance(v, bool):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


def req_enum(b, f, values):
    v = b.get(f)
    if v not in values:
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


def req_date(b, f):
    v = b.get(f)
    if not is_valid_date(v):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


def req_dt(b, f):
    v = b.get(f)
    if not isinstance(v, str):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    try:
        parse_dt(v)
    except (ValueError, TypeError):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: %s' % f)
    return v


# ---------------------------------------------------------------------------
# Pagination (limit/offset, defaults 10/0, limit clamped to [1,100])
# ---------------------------------------------------------------------------

def paginate(items):
    items = sorted(items, key=lambda e: (e['created_at'], e['_seq']))
    total = len(items)
    raw_limit = request.args.get('limit', '10')
    raw_offset = request.args.get('offset', '0')
    try:
        limit = int(raw_limit)
        offset = int(raw_offset)
    except (TypeError, ValueError):
        err('ERR_VALIDATION', 400, 'Invalid pagination parameters')
    limit = max(1, min(100, limit))
    offset = max(0, offset)
    page_items = [pub(e) for e in items[offset:offset + limit]]
    meta = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': (offset + len(page_items)) < total,
    }
    return success(page_items, 200, rtype='array', page=meta)


# ---------------------------------------------------------------------------
# Shared domain helpers
# ---------------------------------------------------------------------------

TIER_MULT = {'T1': Decimal('1.00'), 'T2': Decimal('1.10'), 'T3': Decimal('1.25')}
URGENT_MULT = Decimal('1.10')
STD_MULT = Decimal('1.00')
REFERRAL_EXPIRY_DAYS = 14
TERMINAL_REFERRAL = {'APPROVED', 'WITHDRAWN', 'EXPIRED'}
TERMINAL_ENROLLMENT = {'TERMINATED', 'COMPLETED'}


def round_cents(d):
    return int(d.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def program_of_enrollment(enr):
    return PROGRAMS.get(enr['program_id'])


def vouchers_of_enrollment(enr_id):
    return [v for v in VOUCHERS.values() if v['enrollment_id'] == enr_id]


def compute_face_value(enr, prog):
    hh = min(enr['household_size'], prog['max_household_size'])
    base = prog['base_monthly_benefit_cents'] + (hh - 1) * prog['household_increment_cents']
    tier_mult = TIER_MULT[enr['engagement_tier']]
    ref = REFERRALS.get(enr['referral_id'])
    prio = URGENT_MULT if (ref and ref.get('priority') == 'URGENT') else STD_MULT
    return round_cents(Decimal(base) * tier_mult * prio)


def a1c_improved(readings, threshold):
    """readings: list of A1C BiometricReading dicts (already source-filtered)."""
    if len(readings) < 2:
        return False

    def mkey(r):
        return r['_measured']

    baseline = min(readings, key=lambda r: (r['_measured'], r['created_at'], r['_seq']))
    max_m = max(mkey(r) for r in readings)
    latest = min((r for r in readings if r['_measured'] == max_m),
                 key=lambda r: (r['created_at'], r['_seq']))
    delta = Decimal(str(latest['value'])) - Decimal(str(baseline['value']))
    dq = delta.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    tq = Decimal(str(threshold)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)
    return dq <= -tq


def a1c_counts(prog):
    inclusive = 0
    verified = 0
    for enr in ENROLLMENTS.values():
        if enr['program_id'] != prog['id']:
            continue
        if enr['status'] not in ('ACTIVE', 'SUSPENDED', 'LAPSED'):
            continue
        a1cs = [r for r in READINGS.values()
                if r['enrollment_id'] == enr['id'] and r['kind'] == 'A1C']
        if a1c_improved(a1cs, prog['outcome_improvement_threshold']):
            inclusive += 1
        verified_readings = [r for r in a1cs if r['source'] == 'LAB_VERIFIED']
        if a1c_improved(verified_readings, prog['outcome_improvement_threshold']):
            verified += 1
    return inclusive, verified


def freeze_program_if_pool_lost(prog):
    if prog['status'] != 'ACTIVE':
        return
    has_funded = any(p['program_id'] == prog['id'] and p['status'] == 'FUNDED'
                     for p in POOLS.values())
    if has_funded:
        return
    prog['status'] = 'FROZEN'
    touch(prog)
    for enr in ENROLLMENTS.values():
        if enr['program_id'] == prog['id'] and enr['status'] == 'ACTIVE':
            enr['status'] = 'SUSPENDED'
            touch(enr)


def unfreeze_program(prog):
    if prog['status'] == 'FROZEN':
        prog['status'] = 'ACTIVE'
        touch(prog)


# ---------------------------------------------------------------------------
# Logical clock endpoint
# ---------------------------------------------------------------------------

@app.post('/_clock/set_current_utc')
def set_clock():
    auth('ProgramAdmin')
    b = json_body()
    v = req_dt(b, 'to_iso8601')
    CLOCK.current = parse_dt(v)
    return success({'current_utc': iso(CLOCK.current)}, 200)


# ---------------------------------------------------------------------------
# Programs
# ---------------------------------------------------------------------------

@app.post('/programs')
def create_program():
    auth('ProgramAdmin')
    b = json_body()
    p = new_entity({
        'name': req_str(b, 'name'),
        'start_date': req_date(b, 'start_date'),
        'end_date': req_date(b, 'end_date'),
        'base_monthly_benefit_cents': req_int(b, 'base_monthly_benefit_cents'),
        'household_increment_cents': req_int(b, 'household_increment_cents'),
        'max_household_size': req_int(b, 'max_household_size'),
        'double_up_multiplier': req_num(b, 'double_up_multiplier'),
        'double_up_daily_cap_cents': req_int(b, 'double_up_daily_cap_cents'),
        'double_up_pool_cents': req_int(b, 'double_up_pool_cents'),
        'double_up_matched_cents': 0,
        'double_up_remaining_cents': req_int(b, 'double_up_pool_cents'),
        'tier2_completions': req_int(b, 'tier2_completions'),
        'tier3_completions': req_int(b, 'tier3_completions'),
        'renewal_window_days': req_int(b, 'renewal_window_days'),
        'outcome_improvement_threshold': req_num(b, 'outcome_improvement_threshold'),
        'status': 'DRAFT',
        'ops_run_index': 0,
    })
    PROGRAMS[p['id']] = p
    return success(pub(p), 201)


@app.get('/programs/<programId>')
def get_program(programId):
    auth('ProgramAdmin', 'FunderAnalyst', 'ClinicStaff')
    return success(pub(get_or_404(PROGRAMS, programId)), 200)


@app.get('/programs')
def list_programs():
    auth('ProgramAdmin', 'FunderAnalyst', 'ClinicStaff')
    items = list(PROGRAMS.values())
    status = request.args.get('status')
    if status is not None:
        items = [p for p in items if p['status'] == status]
    return paginate(items)


@app.post('/programs/<programId>/activate')
def activate_program(programId):
    auth('ProgramAdmin')
    p = get_or_404(PROGRAMS, programId)
    if p['status'] == 'CLOSED':
        err('ERR_ALREADY_TERMINAL', 409, 'Program is CLOSED')
    if p['status'] != 'DRAFT':
        err('ERR_INVALID_STATE', 409, 'Program is not in DRAFT')
    has_funded = any(pl['program_id'] == p['id'] and pl['status'] == 'FUNDED'
                     for pl in POOLS.values())
    if not has_funded:
        err('ERR_NO_FUNDED_POOL', 409,
            'Program activation requires at least one FUNDED pool')
    p['status'] = 'ACTIVE'
    touch(p)
    return success(pub(p), 200)


@app.post('/programs/<programId>/close')
def close_program(programId):
    auth('ProgramAdmin')
    p = get_or_404(PROGRAMS, programId)
    if p['status'] == 'CLOSED':
        err('ERR_ALREADY_TERMINAL', 409, 'Program is CLOSED')
    if p['status'] == 'DRAFT':
        err('ERR_INVALID_STATE', 409, 'Program must be ACTIVE or FROZEN to close')
    if any(c['program_id'] == p['id'] and c['status'] == 'OPEN'
           for c in CYCLES.values()):
        err('ERR_OPEN_CYCLES_EXIST', 409,
            'Program close attempted while a cycle is OPEN')
    p['status'] = 'CLOSED'
    touch(p)
    for enr in ENROLLMENTS.values():
        if enr['program_id'] != p['id']:
            continue
        if enr['status'] in ('ACTIVE', 'LAPSED'):
            enr['status'] = 'COMPLETED'
            touch(enr)
        elif enr['status'] == 'SUSPENDED':
            enr['status'] = 'TERMINATED'
            touch(enr)
    return success(pub(p), 200)


@app.post('/programs/<programId>/run-ops')
def run_ops(programId):
    auth('ProgramAdmin')
    p = get_or_404(PROGRAMS, programId)
    now = now_dt()
    expired = 0
    for r in REFERRALS.values():
        if r['program_id'] != p['id']:
            continue
        if r['status'] not in ('SUBMITTED', 'UNDER_REVIEW'):
            continue
        if now - parse_dt(r['created_at']) > timedelta(days=REFERRAL_EXPIRY_DAYS):
            r['status'] = 'EXPIRED'
            touch(r)
            expired += 1
    lapsed = 0
    closed_cycles = [c for c in CYCLES.values()
                     if c['program_id'] == p['id'] and c['status'] == 'CLOSED']
    if closed_cycles:
        latest = max(closed_cycles, key=lambda c: c['period_index'])
        for enr in ENROLLMENTS.values():
            if enr['program_id'] != p['id'] or enr['status'] != 'ACTIVE':
                continue
            vs = [v for v in VOUCHERS.values()
                  if v['enrollment_id'] == enr['id']
                  and v['benefit_cycle_id'] == latest['id']]
            if vs and sum(v['redeemed_cents'] for v in vs) == 0:
                enr['status'] = 'LAPSED'
                enr['lapsed_at'] = iso(now)
                touch(enr)
                lapsed += 1
    p['ops_run_index'] += 1
    touch(p)
    return success({
        'ops_run_index': p['ops_run_index'],
        'expired_referral_count': expired,
        'lapsed_enrollment_count': lapsed,
    }, 200)


@app.get('/programs/<programId>/summary')
def program_summary(programId):
    auth('ProgramAdmin', 'FunderAnalyst')
    p = get_or_404(PROGRAMS, programId)
    pools = [pl for pl in POOLS.values() if pl['program_id'] == p['id']]
    committed = sum(pl['committed_cents'] for pl in pools)
    disbursed = sum(pl['disbursed_cents'] for pl in pools)
    reserved = sum(pl['reserved_cents'] for pl in pools)
    live = [e for e in ENROLLMENTS.values()
            if e['program_id'] == p['id']
            and e['status'] in ('ACTIVE', 'SUSPENDED', 'LAPSED')]
    inc, ver = a1c_counts(p)
    return success({
        'committed_cents': committed,
        'reserved_cents': reserved,
        'disbursed_cents': disbursed,
        'available_cents': committed - disbursed - reserved,
        'double_up_matched_cents': p['double_up_matched_cents'],
        'double_up_remaining_cents': p['double_up_remaining_cents'],
        'active_enrollment_count': sum(
            1 for e in ENROLLMENTS.values()
            if e['program_id'] == p['id'] and e['status'] == 'ACTIVE'),
        'tier_t1_count': sum(1 for e in live if e['engagement_tier'] == 'T1'),
        'tier_t2_count': sum(1 for e in live if e['engagement_tier'] == 'T2'),
        'tier_t3_count': sum(1 for e in live if e['engagement_tier'] == 'T3'),
        'a1c_improved_inclusive_count': inc,
        'a1c_improved_verified_count': ver,
    }, 200)


# ---------------------------------------------------------------------------
# Funders
# ---------------------------------------------------------------------------

@app.post('/funders')
def create_funder():
    auth('ProgramAdmin')
    b = json_body()
    f = new_entity({
        'name': req_str(b, 'name'),
        'contact_email': req_str(b, 'contact_email'),
        'total_commitment_cents': req_int(b, 'total_commitment_cents'),
        'status': 'ACTIVE',
    })
    FUNDERS[f['id']] = f
    return success(pub(f), 201)


@app.get('/funders/<funderId>')
def get_funder(funderId):
    auth('ProgramAdmin', 'FunderAnalyst')
    return success(pub(get_or_404(FUNDERS, funderId)), 200)


@app.post('/funders/<funderId>/suspend')
def suspend_funder(funderId):
    auth('ProgramAdmin')
    f = get_or_404(FUNDERS, funderId)
    if f['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 409, 'Funder is not ACTIVE')
    f['status'] = 'SUSPENDED'
    touch(f)
    affected_programs = set()
    for pool in POOLS.values():
        if pool['funder_id'] == f['id'] and pool['status'] == 'FUNDED':
            pool['status'] = 'SUSPENDED'
            touch(pool)
            affected_programs.add(pool['program_id'])
    for pid in affected_programs:
        freeze_program_if_pool_lost(PROGRAMS[pid])
    return success(pub(f), 200)


@app.post('/funders/<funderId>/reinstate')
def reinstate_funder(funderId):
    auth('ProgramAdmin')
    f = get_or_404(FUNDERS, funderId)
    if f['status'] != 'SUSPENDED':
        err('ERR_INVALID_STATE', 409, 'Funder is not SUSPENDED')
    f['status'] = 'ACTIVE'
    touch(f)
    for pool in POOLS.values():
        if pool['funder_id'] == f['id'] and pool['status'] == 'SUSPENDED':
            pool['status'] = 'FUNDED'
            touch(pool)
            unfreeze_program(PROGRAMS[pool['program_id']])
    return success(pub(f), 200)


# ---------------------------------------------------------------------------
# Funding pools
# ---------------------------------------------------------------------------

@app.post('/funding-pools')
def create_pool():
    auth('ProgramAdmin')
    b = json_body()
    prog = get_or_404(PROGRAMS, b.get('program_id'))
    funder = get_or_404(FUNDERS, b.get('funder_id'))
    committed = req_int(b, 'committed_cents')
    total = sum(pl['committed_cents'] for pl in POOLS.values()
                if pl['funder_id'] == funder['id']) + committed
    if total > funder['total_commitment_cents']:
        err('ERR_COMMITMENT_EXCEEDED', 422,
            'Sum of pool committed_cents would exceed funder total_commitment_cents')
    pool = new_entity({
        'program_id': prog['id'],
        'funder_id': funder['id'],
        'committed_cents': committed,
        'disbursed_cents': 0,
        'reserved_cents': 0,
        'available_cents': committed,
        'status': 'PENDING',
    })
    POOLS[pool['id']] = pool
    return success(pub(pool), 201)


@app.get('/funding-pools/<poolId>')
def get_pool(poolId):
    auth('ProgramAdmin', 'FunderAnalyst')
    return success(pub(get_or_404(POOLS, poolId)), 200)


@app.get('/funding-pools')
def list_pools():
    auth('ProgramAdmin', 'FunderAnalyst')
    items = list(POOLS.values())
    pid = request.args.get('program_id')
    fid = request.args.get('funder_id')
    if pid is not None:
        items = [p for p in items if p['program_id'] == pid]
    if fid is not None:
        items = [p for p in items if p['funder_id'] == fid]
    return paginate(items)


@app.post('/funding-pools/<poolId>/fund')
def fund_pool(poolId):
    uid, _ = auth('FunderAnalyst')
    pool = get_or_404(POOLS, poolId)
    if pool['funder_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Only the pool\'s own funder may fund it')
    if pool['status'] == 'CLOSED':
        err('ERR_ALREADY_TERMINAL', 409, 'Pool is CLOSED')
    if pool['status'] != 'PENDING':
        err('ERR_INVALID_STATE', 409, 'Pool is not PENDING')
    funder = FUNDERS.get(pool['funder_id'])
    if funder is None or funder['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 409, 'Funder is not ACTIVE')
    prog = PROGRAMS.get(pool['program_id'])
    if prog is None or prog['status'] not in ('DRAFT', 'ACTIVE', 'FROZEN'):
        err('ERR_PROGRAM_NOT_ACTIVE', 409,
            'Pool funding requires program in DRAFT, ACTIVE, or FROZEN')
    pool['status'] = 'FUNDED'
    touch(pool)
    unfreeze_program(prog)
    return success(pub(pool), 200)


@app.post('/funding-pools/<poolId>/close')
def close_pool(poolId):
    auth('ProgramAdmin')
    pool = get_or_404(POOLS, poolId)
    if pool['status'] == 'CLOSED':
        err('ERR_ALREADY_TERMINAL', 409, 'Pool is CLOSED')
    if pool['status'] not in ('FUNDED', 'SUSPENDED'):
        err('ERR_INVALID_STATE', 409, 'Pool must be FUNDED or SUSPENDED to close')
    if pool['reserved_cents'] != 0:
        err('ERR_POOL_BUSY', 409,
            'Pool close attempted while reserved_cents > 0')
    pool['status'] = 'CLOSED'
    touch(pool)
    return success(pub(pool), 200)


# ---------------------------------------------------------------------------
# Clinics
# ---------------------------------------------------------------------------

@app.post('/clinics')
def create_clinic():
    auth('ProgramAdmin')
    b = json_body()
    name = req_str(b, 'name')
    npi = req_str(b, 'npi_number')
    cap = req_int(b, 'max_active_referrals')
    if any(c['npi_number'] == npi for c in CLINICS.values()):
        err('ERR_VALIDATION', 400, 'Duplicate npi_number')
    c = new_entity({
        'name': name,
        'npi_number': npi,
        'max_active_referrals': cap,
        'status': 'ACTIVE',
    })
    CLINICS[c['id']] = c
    return success(pub(c), 201)


@app.get('/clinics/<clinicId>')
def get_clinic(clinicId):
    auth('ProgramAdmin', 'ClinicStaff')
    return success(pub(get_or_404(CLINICS, clinicId)), 200)


@app.post('/clinics/<clinicId>/suspend')
def suspend_clinic(clinicId):
    auth('ProgramAdmin')
    c = get_or_404(CLINICS, clinicId)
    if c['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 409, 'Clinic is not ACTIVE')
    c['status'] = 'SUSPENDED'
    touch(c)
    return success(pub(c), 200)


@app.post('/clinics/<clinicId>/reinstate')
def reinstate_clinic(clinicId):
    auth('ProgramAdmin')
    c = get_or_404(CLINICS, clinicId)
    if c['status'] != 'SUSPENDED':
        err('ERR_INVALID_STATE', 409, 'Clinic is not SUSPENDED')
    c['status'] = 'ACTIVE'
    touch(c)
    return success(pub(c), 200)


# ---------------------------------------------------------------------------
# Retailers
# ---------------------------------------------------------------------------

@app.post('/retailers')
def create_retailer():
    auth('ProgramAdmin')
    b = json_body()
    r = new_entity({
        'name': req_str(b, 'name'),
        'kind': req_enum(b, 'kind', ['GROCERY', 'FARMERS_MARKET', 'MOBILE_MARKET']),
        'double_up_eligible': req_bool(b, 'double_up_eligible'),
        'status': 'ACTIVE',
    })
    RETAILERS[r['id']] = r
    return success(pub(r), 201)


@app.get('/retailers/<retailerId>')
def get_retailer(retailerId):
    auth('ProgramAdmin', 'RetailerStaff')
    return success(pub(get_or_404(RETAILERS, retailerId)), 200)


@app.post('/retailers/<retailerId>/suspend')
def suspend_retailer(retailerId):
    auth('ProgramAdmin')
    r = get_or_404(RETAILERS, retailerId)
    if r['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 409, 'Retailer is not ACTIVE')
    r['status'] = 'SUSPENDED'
    touch(r)
    return success(pub(r), 200)


@app.post('/retailers/<retailerId>/reinstate')
def reinstate_retailer(retailerId):
    auth('ProgramAdmin')
    r = get_or_404(RETAILERS, retailerId)
    if r['status'] != 'SUSPENDED':
        err('ERR_INVALID_STATE', 409, 'Retailer is not SUSPENDED')
    r['status'] = 'ACTIVE'
    touch(r)
    return success(pub(r), 200)


# ---------------------------------------------------------------------------
# Patients
# ---------------------------------------------------------------------------

@app.post('/patients')
def create_patient():
    uid, _ = auth('ClinicStaff')
    b = json_body()
    cid = b.get('clinic_id')
    if isinstance(cid, str) and cid != uid:
        err('ERR_FORBIDDEN', 403,
            'Patient clinic_id must equal the acting clinic')
    clinic = get_or_404(CLINICS, cid)
    p = new_entity({
        'clinic_id': clinic['id'],
        'full_name': req_str(b, 'full_name'),
        'date_of_birth': req_date(b, 'date_of_birth'),
        'household_size': req_int(b, 'household_size', minv=1),
        'consent_status': 'PENDING',
    })
    if clinic['status'] != 'ACTIVE':
        err('ERR_CLINIC_SUSPENDED', 409,
            'Clinic is SUSPENDED; patient registration blocked')
    PATIENTS[p['id']] = p
    return success(pub(p), 201)


@app.get('/patients/<patientId>')
def get_patient(patientId):
    uid, role = auth('ProgramAdmin', 'ClinicStaff', 'Participant')
    if role == 'Participant' and patientId != uid:
        err('ERR_FORBIDDEN', 403, 'Participant may read only their own record')
    return success(pub(get_or_404(PATIENTS, patientId)), 200)


@app.get('/patients')
def list_patients():
    auth('ProgramAdmin', 'ClinicStaff')
    items = list(PATIENTS.values())
    cid = request.args.get('clinic_id')
    if cid is not None:
        items = [p for p in items if p['clinic_id'] == cid]
    return paginate(items)


@app.post('/patients/<patientId>/grant-consent')
def grant_consent(patientId):
    uid, _ = auth('ClinicStaff')
    p = get_or_404(PATIENTS, patientId)
    if p['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Acting clinic does not own the patient')
    if p['consent_status'] == 'GRANTED':
        err('ERR_INVALID_STATE', 409, 'Consent already GRANTED')
    p['consent_status'] = 'GRANTED'
    touch(p)
    return success(pub(p), 200)


@app.post('/patients/<patientId>/revoke-consent')
def revoke_consent(patientId):
    uid, _ = auth('ClinicStaff')
    p = get_or_404(PATIENTS, patientId)
    if p['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Acting clinic does not own the patient')
    if p['consent_status'] != 'GRANTED':
        err('ERR_INVALID_STATE', 409, 'Consent is not GRANTED')
    p['consent_status'] = 'REVOKED'
    touch(p)
    return success(pub(p), 200)


# ---------------------------------------------------------------------------
# Referrals
# ---------------------------------------------------------------------------

@app.post('/referrals')
def create_referral():
    uid, _ = auth('ClinicStaff')
    b = json_body()
    cid = b.get('clinic_id')
    if isinstance(cid, str) and cid != uid:
        err('ERR_FORBIDDEN', 403, 'Acting clinic must own the referral')
    clinic = get_or_404(CLINICS, cid)
    patient = get_or_404(PATIENTS, b.get('patient_id'))
    program = get_or_404(PROGRAMS, b.get('program_id'))
    diagnosis = req_str(b, 'diagnosis_code')
    priority = req_enum(b, 'priority', ['STANDARD', 'URGENT'])
    # clinical safety (priority 7)
    if patient['consent_status'] != 'GRANTED':
        err('ERR_CONSENT_REVOKED', 422, 'Patient consent is not GRANTED')
    # uniqueness / capacity (priority 9)
    if any(r['patient_id'] == patient['id'] and r['program_id'] == program['id']
           and r['status'] not in TERMINAL_REFERRAL for r in REFERRALS.values()):
        err('ERR_DUPLICATE_REFERRAL', 409,
            'A non-terminal referral already exists for (patient, program)')
    active_count = sum(1 for r in REFERRALS.values()
                       if r['clinic_id'] == clinic['id']
                       and r['status'] in ('SUBMITTED', 'UNDER_REVIEW'))
    if active_count >= clinic['max_active_referrals']:
        err('ERR_CLINIC_REFERRAL_CAP', 409,
            'Clinic active-referral cap reached')
    # cross-entity gates (priority 10)
    if clinic['status'] != 'ACTIVE':
        err('ERR_CLINIC_SUSPENDED', 409, 'Clinic is SUSPENDED')
    if clinic['id'] != patient['clinic_id']:
        err('ERR_PATIENT_CLINIC_MISMATCH', 422,
            'referral.clinic_id differs from patient.clinic_id')
    r = new_entity({
        'clinic_id': clinic['id'],
        'patient_id': patient['id'],
        'program_id': program['id'],
        'diagnosis_code': diagnosis,
        'priority': priority,
        'decision_reason': None,
        'appeal_reason': None,
        'appeal_count': 0,
        'enrollment_id': None,
        'status': 'SUBMITTED',
    })
    REFERRALS[r['id']] = r
    return success(pub(r), 201)


@app.get('/referrals/<referralId>')
def get_referral(referralId):
    auth('ProgramAdmin', 'ClinicStaff')
    return success(pub(get_or_404(REFERRALS, referralId)), 200)


@app.get('/referrals')
def list_referrals():
    auth('ProgramAdmin', 'ClinicStaff')
    items = list(REFERRALS.values())
    for param, field in (('clinic_id', 'clinic_id'), ('patient_id', 'patient_id'),
                         ('program_id', 'program_id'),
                         ('enrollment_id', 'enrollment_id')):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[field] == v]
    return paginate(items)


def _referral_transition_gate(r, allowed_from):
    if r['status'] in TERMINAL_REFERRAL:
        err('ERR_ALREADY_TERMINAL', 409,
            'Transition attempted from a terminal state')
    if r['status'] not in allowed_from:
        err('ERR_REFERRAL_NOT_REVIEWABLE', 409,
            'Referral is not in the required state')


@app.post('/referrals/<referralId>/start-review')
def start_review(referralId):
    auth('ProgramAdmin')
    r = get_or_404(REFERRALS, referralId)
    _referral_transition_gate(r, ('SUBMITTED',))
    r['status'] = 'UNDER_REVIEW'
    touch(r)
    return success(pub(r), 200)


@app.post('/referrals/<referralId>/approve')
def approve_referral(referralId):
    auth('ProgramAdmin')
    r = get_or_404(REFERRALS, referralId)
    _referral_transition_gate(r, ('UNDER_REVIEW',))
    prog = PROGRAMS.get(r['program_id'])
    if prog is None or prog['status'] != 'ACTIVE':
        err('ERR_PROGRAM_NOT_ACTIVE', 409, 'Program is not ACTIVE')
    patient = PATIENTS.get(r['patient_id'])
    if patient is None or patient['consent_status'] != 'GRANTED':
        err('ERR_CONSENT_REVOKED', 422, 'Patient consent is not GRANTED')
    if any(e['patient_id'] == r['patient_id'] and e['program_id'] == r['program_id']
           and e['status'] in ('ACTIVE', 'SUSPENDED', 'LAPSED')
           for e in ENROLLMENTS.values()):
        err('ERR_DUPLICATE_ENROLLMENT', 409,
            'An ACTIVE/SUSPENDED/LAPSED enrollment already exists for (patient, program)')
    enr = new_entity({
        'program_id': r['program_id'],
        'patient_id': r['patient_id'],
        'referral_id': r['id'],
        'household_size': patient['household_size'],
        'engagement_tier': 'T1',
        'lifetime_redeemed_cents': 0,
        'lifetime_match_cents': 0,
        'lapsed_at': None,
        'status': 'ACTIVE',
    })
    ENROLLMENTS[enr['id']] = enr
    r['status'] = 'APPROVED'
    r['enrollment_id'] = enr['id']
    touch(r)
    return success(pub(r), 200)


@app.post('/referrals/<referralId>/decline')
def decline_referral(referralId):
    auth('ProgramAdmin')
    r = get_or_404(REFERRALS, referralId)
    b = json_body()
    reason = req_str(b, 'decision_reason')
    _referral_transition_gate(r, ('UNDER_REVIEW',))
    r['status'] = 'DECLINED'
    r['decision_reason'] = reason
    touch(r)
    return success(pub(r), 200)


@app.post('/referrals/<referralId>/appeal')
def appeal_referral(referralId):
    uid, _ = auth('ClinicStaff')
    r = get_or_404(REFERRALS, referralId)
    if r['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Acting clinic does not own the referral')
    b = json_body()
    reason = req_str(b, 'appeal_reason')
    _referral_transition_gate(r, ('DECLINED',))
    r['status'] = 'UNDER_REVIEW'
    r['appeal_reason'] = reason
    r['appeal_count'] += 1
    touch(r)
    return success(pub(r), 200)


@app.post('/referrals/<referralId>/withdraw')
def withdraw_referral(referralId):
    uid, _ = auth('ClinicStaff')
    r = get_or_404(REFERRALS, referralId)
    if r['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Acting clinic does not own the referral')
    _referral_transition_gate(r, ('SUBMITTED', 'UNDER_REVIEW'))
    r['status'] = 'WITHDRAWN'
    touch(r)
    return success(pub(r), 200)


# ---------------------------------------------------------------------------
# Enrollments
# ---------------------------------------------------------------------------

@app.get('/enrollments/<enrollmentId>')
def get_enrollment(enrollmentId):
    uid, role = auth('ProgramAdmin', 'ClinicStaff', 'Participant')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    if role == 'Participant' and enr['patient_id'] != uid:
        err('ERR_FORBIDDEN', 403, 'Participant may read only their own records')
    return success(pub(enr), 200)


@app.get('/enrollments')
def list_enrollments():
    uid, role = auth('ProgramAdmin', 'ClinicStaff', 'Participant')
    items = list(ENROLLMENTS.values())
    if role == 'Participant':
        items = [e for e in items if e['patient_id'] == uid]
    for param in ('program_id', 'patient_id', 'referral_id'):
        v = request.args.get(param)
        if v is not None:
            items = [e for e in items if e[param] == v]
    return paginate(items)


@app.post('/enrollments/<enrollmentId>/suspend')
def suspend_enrollment(enrollmentId):
    auth('ProgramAdmin')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    if enr['status'] in TERMINAL_ENROLLMENT:
        err('ERR_ALREADY_TERMINAL', 409, 'Enrollment is terminal')
    if enr['status'] != 'ACTIVE':
        err('ERR_INVALID_STATE', 409, 'Enrollment is not ACTIVE')
    enr['status'] = 'SUSPENDED'
    touch(enr)
    return success(pub(enr), 200)


@app.post('/enrollments/<enrollmentId>/reinstate')
def reinstate_enrollment(enrollmentId):
    auth('ProgramAdmin')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    if enr['status'] in TERMINAL_ENROLLMENT:
        err('ERR_ALREADY_TERMINAL', 409, 'Enrollment is terminal')
    if enr['status'] != 'SUSPENDED':
        err('ERR_INVALID_STATE', 409, 'Enrollment is not SUSPENDED')
    prog = program_of_enrollment(enr)
    if prog is not None and prog['status'] == 'FROZEN':
        err('ERR_PROGRAM_FROZEN', 409,
            'Enrollment reinstate attempted while program is FROZEN')
    if prog is not None and prog['status'] == 'CLOSED':
        err('ERR_PROGRAM_NOT_ACTIVE', 409, 'Program is CLOSED')
    enr['status'] = 'ACTIVE'
    touch(enr)
    return success(pub(enr), 200)


@app.post('/enrollments/<enrollmentId>/terminate')
def terminate_enrollment(enrollmentId):
    auth('ProgramAdmin')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    b = json_body()
    req_str(b, 'reason')
    if enr['status'] in TERMINAL_ENROLLMENT:
        err('ERR_ALREADY_TERMINAL', 409, 'Enrollment is terminal')
    if enr['status'] not in ('ACTIVE', 'SUSPENDED', 'LAPSED'):
        err('ERR_INVALID_STATE', 409, 'Enrollment cannot be terminated')
    enr['status'] = 'TERMINATED'
    touch(enr)
    return success(pub(enr), 200)


# ---------------------------------------------------------------------------
# Benefit cycles
# ---------------------------------------------------------------------------

@app.post('/programs/<programId>/cycles')
def create_cycle(programId):
    auth('ProgramAdmin')
    prog = get_or_404(PROGRAMS, programId)
    b = json_body()
    period_index = req_int(b, 'period_index')
    sd = req_date(b, 'start_date')
    ed = req_date(b, 'end_date')
    if any(c['program_id'] == prog['id'] and c['period_index'] == period_index
           for c in CYCLES.values()):
        err('ERR_VALIDATION', 400, 'Duplicate period_index within program')
    if sd >= ed:
        err('ERR_INVALID_DATE_RANGE', 400, 'start_date must precede end_date')
    if sd < prog['start_date'] or ed > prog['end_date']:
        err('ERR_INVALID_DATE_RANGE', 400,
            'Cycle window must lie within the program window')
    for c in CYCLES.values():
        if c['program_id'] != prog['id']:
            continue
        if sd < c['end_date'] and c['start_date'] < ed:
            err('ERR_PERIOD_OVERLAP', 409,
                'Benefit cycle period overlaps an existing cycle')
    c = new_entity({
        'program_id': prog['id'],
        'period_index': period_index,
        'start_date': sd,
        'end_date': ed,
        'status': 'SCHEDULED',
    })
    CYCLES[c['id']] = c
    return success(pub(c), 201)


@app.get('/cycles/<cycleId>')
def get_cycle(cycleId):
    auth('ProgramAdmin', 'FunderAnalyst', 'ClinicStaff')
    return success(pub(get_or_404(CYCLES, cycleId)), 200)


@app.get('/cycles')
def list_cycles():
    auth('ProgramAdmin', 'FunderAnalyst', 'ClinicStaff')
    items = list(CYCLES.values())
    pid = request.args.get('program_id')
    if pid is not None:
        items = [c for c in items if c['program_id'] == pid]
    return paginate(items)


@app.post('/cycles/<cycleId>/open')
def open_cycle(cycleId):
    auth('ProgramAdmin')
    c = get_or_404(CYCLES, cycleId)
    if c['status'] == 'CLOSED':
        err('ERR_ALREADY_TERMINAL', 409, 'Cycle is CLOSED')
    if c['status'] != 'SCHEDULED':
        err('ERR_INVALID_STATE', 409, 'Cycle is not SCHEDULED')
    prog = PROGRAMS.get(c['program_id'])
    if prog is None or prog['status'] != 'ACTIVE':
        err('ERR_PROGRAM_NOT_ACTIVE', 409, 'Program is not ACTIVE')
    if any(o['program_id'] == c['program_id'] and o['status'] == 'OPEN'
           and o['id'] != c['id'] for o in CYCLES.values()):
        err('ERR_CYCLE_ALREADY_OPEN', 409,
            'Another cycle of the program is already OPEN')
    if any(o['program_id'] == c['program_id']
           and o['period_index'] < c['period_index']
           and o['status'] != 'CLOSED' for o in CYCLES.values()):
        err('ERR_PRIOR_CYCLE_UNCLOSED', 409,
            'A cycle with lower period_index is not CLOSED')
    c['status'] = 'OPEN'
    touch(c)
    return success(pub(c), 200)


@app.post('/cycles/<cycleId>/issue')
def issue_cycle(cycleId):
    auth('ProgramAdmin')
    c = get_or_404(CYCLES, cycleId)
    if c['status'] != 'OPEN':
        err('ERR_CYCLE_NOT_OPEN', 409, 'Cycle is not OPEN')
    prog = PROGRAMS.get(c['program_id'])
    funded = [pl for pl in POOLS.values()
              if pl['program_id'] == c['program_id'] and pl['status'] == 'FUNDED']
    if not funded:
        err('ERR_POOL_NOT_FUNDED', 409, 'Issuance requires a FUNDED pool')
    pool = min(funded, key=lambda pl: (pl['created_at'], pl['_seq']))
    candidates = []
    for enr in ENROLLMENTS.values():
        if enr['program_id'] != c['program_id'] or enr['status'] != 'ACTIVE':
            continue
        if any(v['enrollment_id'] == enr['id']
               and v['benefit_cycle_id'] == c['id'] for v in VOUCHERS.values()):
            continue
        ref = REFERRALS.get(enr['referral_id'])
        patient = PATIENTS.get(enr['patient_id'])
        candidates.append((
            enr['created_at'], enr['_seq'],
            ref['created_at'] if ref else '', ref['_seq'] if ref else 0,
            patient['created_at'] if patient else '',
            patient['_seq'] if patient else 0,
            enr,
        ))
    candidates.sort(key=lambda t: (t[0], t[1], t[2], t[3], t[4], t[5]))
    issued = 0
    total_face = 0
    skipped = []
    for *_, enr in candidates:
        face = compute_face_value(enr, prog)
        if pool['available_cents'] >= face:
            v = new_entity({
                'enrollment_id': enr['id'],
                'benefit_cycle_id': c['id'],
                'face_value_cents': face,
                'redeemed_cents': 0,
                'remaining_cents': face,
                'status': 'ISSUED',
            })
            v['_pool_id'] = pool['id']
            VOUCHERS[v['id']] = v
            pool['reserved_cents'] += face
            pool['available_cents'] -= face
            issued += 1
            total_face += face
        else:
            skipped.append(enr['id'])
    touch(pool)
    return success({
        'issued_count': issued,
        'total_face_value_cents': total_face,
        'skipped_enrollment_ids': skipped,
    }, 200)


@app.post('/cycles/<cycleId>/close')
def close_cycle(cycleId):
    auth('ProgramAdmin')
    c = get_or_404(CYCLES, cycleId)
    if c['status'] != 'OPEN':
        err('ERR_CYCLE_NOT_OPEN', 409, 'Cycle is not OPEN')
    issued = sorted(
        (v for v in VOUCHERS.values()
         if v['benefit_cycle_id'] == c['id'] and v['status'] == 'ISSUED'),
        key=lambda v: (v['created_at'], v['_seq']))
    touched_pools = set()
    for v in issued:
        pool = POOLS.get(v.get('_pool_id'))
        if pool is not None:
            pool['reserved_cents'] -= v['remaining_cents']
            pool['available_cents'] += v['remaining_cents']
            touched_pools.add(pool['id'])
        v['status'] = 'EXPIRED'
        touch(v)
    for pid in touched_pools:
        touch(POOLS[pid])
    c['status'] = 'CLOSED'
    touch(c)
    return success(pub(c), 200)


# ---------------------------------------------------------------------------
# Vouchers
# ---------------------------------------------------------------------------

@app.get('/vouchers/<voucherId>')
def get_voucher(voucherId):
    uid, role = auth('ProgramAdmin', 'ClinicStaff', 'Participant')
    v = get_or_404(VOUCHERS, voucherId)
    if role == 'Participant':
        enr = ENROLLMENTS.get(v['enrollment_id'])
        if enr is None or enr['patient_id'] != uid:
            err('ERR_FORBIDDEN', 403,
                'Participant may read only their own records')
    return success(pub(v), 200)


@app.get('/vouchers')
def list_vouchers():
    uid, role = auth('ProgramAdmin', 'ClinicStaff', 'Participant')
    items = list(VOUCHERS.values())
    if role == 'Participant':
        own_enrs = {e['id'] for e in ENROLLMENTS.values()
                    if e['patient_id'] == uid}
        items = [v for v in items if v['enrollment_id'] in own_enrs]
    for param in ('enrollment_id', 'benefit_cycle_id'):
        val = request.args.get(param)
        if val is not None:
            items = [v for v in items if v[param] == val]
    return paginate(items)


@app.post('/vouchers/<voucherId>/void')
def void_voucher(voucherId):
    auth('ProgramAdmin')
    v = get_or_404(VOUCHERS, voucherId)
    b = json_body()
    req_str(b, 'reason')
    if v['status'] != 'ISSUED':
        err('ERR_VOUCHER_NOT_REDEEMABLE', 409, 'Voucher is not ISSUED')
    pool = POOLS.get(v.get('_pool_id'))
    if pool is not None:
        pool['reserved_cents'] -= v['remaining_cents']
        pool['available_cents'] += v['remaining_cents']
        touch(pool)
    v['status'] = 'VOIDED'
    touch(v)
    return success(pub(v), 200)


# ---------------------------------------------------------------------------
# Redemptions
# ---------------------------------------------------------------------------

LINE_CATEGORIES = {'PRODUCE_ELIGIBLE', 'STAPLE', 'OTHER'}


@app.post('/redemptions')
def create_redemption():
    uid, _ = auth('RetailerStaff')
    b = json_body()
    rid = b.get('retailer_id')
    if isinstance(rid, str) and rid != uid:
        err('ERR_FORBIDDEN', 403,
            'Redemption retailer_id must equal the acting retailer')
    retailer = get_or_404(RETAILERS, rid)
    enr = get_or_404(ENROLLMENTS, b.get('enrollment_id'))
    lines = b.get('lines')
    if not isinstance(lines, list):
        err('ERR_VALIDATION', 400, 'Missing or invalid field: lines')
    if len(lines) == 0:
        err('ERR_INVALID_TENDER', 422, 'Redemption lines empty')
    norm_lines = []
    for ln in lines:
        if not isinstance(ln, dict):
            err('ERR_INVALID_TENDER', 422, 'Invalid redemption line')
        cat = ln.get('category')
        amt = ln.get('amount_cents')
        if cat not in LINE_CATEGORIES:
            err('ERR_INVALID_TENDER', 422, 'Unknown line category')
        if isinstance(amt, bool) or not isinstance(amt, int) or amt <= 0:
            err('ERR_INVALID_TENDER', 422, 'amount_cents must be a positive integer')
        norm_lines.append({'category': cat, 'amount_cents': amt})
    # state gate (priority 6)
    if enr['status'] != 'ACTIVE':
        err('ERR_ENROLLMENT_NOT_ACTIVE', 409, 'Enrollment is not ACTIVE')
    # cross-entity gate (priority 10)
    if retailer['status'] != 'ACTIVE':
        err('ERR_RETAILER_SUSPENDED', 409, 'Retailer is SUSPENDED')
    prog = program_of_enrollment(enr)
    subtotal = sum(ln['amount_cents'] for ln in norm_lines)
    pe_cents = sum(ln['amount_cents'] for ln in norm_lines
                   if ln['category'] == 'PRODUCE_ELIGIBLE')
    mult = Decimal(str(prog['double_up_multiplier']))
    raw_match = sum(
        round_cents(Decimal(ln['amount_cents']) * mult)
        for ln in norm_lines if ln['category'] == 'PRODUCE_ELIGIBLE')
    if not retailer['double_up_eligible']:
        match = 0
    else:
        today = iso(now_dt())[:10]
        matched_today = sum(
            r['match_cents'] for r in REDEMPTIONS.values()
            if r['enrollment_id'] == enr['id'] and r['status'] == 'SETTLED'
            and r['redeemed_at'][:10] == today)
        daily_remaining = prog['double_up_daily_cap_cents'] - matched_today
        match = min(raw_match, daily_remaining,
                    prog['double_up_remaining_cents'])
        if match < 0:
            match = 0
    issued_vs = sorted(
        (v for v in VOUCHERS.values()
         if v['enrollment_id'] == enr['id'] and v['status'] == 'ISSUED'),
        key=lambda v: (v['created_at'], v['_seq']))
    voucher = issued_vs[0] if issued_vs else None
    if voucher is not None:
        applied = min(voucher['remaining_cents'], subtotal - match)
    else:
        applied = 0
    if applied < 0:
        applied = 0
    voucher_id = voucher['id'] if (voucher is not None and applied > 0) else None
    patient_pay = subtotal - match - applied
    r = new_entity({
        'retailer_id': retailer['id'],
        'enrollment_id': enr['id'],
        'lines': norm_lines,
        'subtotal_cents': subtotal,
        'produce_eligible_cents': pe_cents,
        'match_cents': match,
        'voucher_applied_cents': applied,
        'voucher_id': voucher_id,
        'patient_pay_cents': patient_pay,
        'redeemed_at': iso(now_dt()),
        'status': 'SETTLED',
    })
    REDEMPTIONS[r['id']] = r
    if voucher is not None and applied > 0:
        voucher['redeemed_cents'] += applied
        voucher['remaining_cents'] = (
            voucher['face_value_cents'] - voucher['redeemed_cents'])
        if voucher['remaining_cents'] == 0:
            voucher['status'] = 'EXHAUSTED'
        touch(voucher)
        pool = POOLS.get(voucher.get('_pool_id'))
        if pool is not None:
            pool['disbursed_cents'] += applied
            pool['reserved_cents'] -= applied
            touch(pool)
    if match > 0:
        prog['double_up_matched_cents'] += match
        prog['double_up_remaining_cents'] -= match
        touch(prog)
    if applied > 0 or match > 0:
        enr['lifetime_redeemed_cents'] += applied
        enr['lifetime_match_cents'] += match
        touch(enr)
    return success(pub(r), 201)


@app.get('/redemptions/<redemptionId>')
def get_redemption(redemptionId):
    uid, role = auth('ProgramAdmin', 'RetailerStaff', 'FunderAnalyst')
    r = get_or_404(REDEMPTIONS, redemptionId)
    if role == 'RetailerStaff' and r['retailer_id'] != uid:
        err('ERR_FORBIDDEN', 403,
            'RetailerStaff sees only their own retailer\'s redemptions')
    return success(pub(r), 200)


@app.get('/redemptions')
def list_redemptions():
    uid, role = auth('ProgramAdmin', 'RetailerStaff', 'FunderAnalyst')
    items = list(REDEMPTIONS.values())
    if role == 'RetailerStaff':
        items = [r for r in items if r['retailer_id'] == uid]
    for param in ('retailer_id', 'enrollment_id', 'voucher_id'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    return paginate(items)


@app.post('/redemptions/<redemptionId>/void')
def void_redemption(redemptionId):
    uid, role = auth('RetailerStaff', 'ProgramAdmin')
    r = get_or_404(REDEMPTIONS, redemptionId)
    if role == 'RetailerStaff' and r['retailer_id'] != uid:
        err('ERR_FORBIDDEN', 403,
            'Only the owning retailer or a ProgramAdmin may void')
    b = json_body()
    req_str(b, 'reason')
    if r['status'] == 'VOIDED':
        err('ERR_VOID_NOT_ALLOWED', 409, 'Redemption already VOIDED')
    enr = ENROLLMENTS.get(r['enrollment_id'])
    prog = program_of_enrollment(enr) if enr else None
    if r['voucher_id']:
        voucher = VOUCHERS.get(r['voucher_id'])
        cycle = CYCLES.get(voucher['benefit_cycle_id']) if voucher else None
        if cycle is None or cycle['status'] != 'OPEN':
            err('ERR_VOID_NOT_ALLOWED', 409,
                'Void allowed only while the voucher\'s cycle is OPEN')
    else:
        if prog is not None and prog['status'] == 'CLOSED':
            err('ERR_VOID_NOT_ALLOWED', 409,
                'Void not allowed after program CLOSED')
    applied = r['voucher_applied_cents']
    match = r['match_cents']
    r['status'] = 'VOIDED'
    touch(r)
    if r['voucher_id'] and applied > 0:
        voucher = VOUCHERS.get(r['voucher_id'])
        if voucher is not None:
            voucher['redeemed_cents'] -= applied
            voucher['remaining_cents'] = (
                voucher['face_value_cents'] - voucher['redeemed_cents'])
            if voucher['status'] == 'EXHAUSTED' and voucher['remaining_cents'] > 0:
                voucher['status'] = 'ISSUED'
            touch(voucher)
            pool = POOLS.get(voucher.get('_pool_id'))
            if pool is not None:
                pool['disbursed_cents'] -= applied
                pool['reserved_cents'] += applied
                touch(pool)
    if match > 0 and prog is not None:
        prog['double_up_matched_cents'] -= match
        prog['double_up_remaining_cents'] += match
        touch(prog)
    if enr is not None and (applied > 0 or match > 0):
        enr['lifetime_redeemed_cents'] -= applied
        enr['lifetime_match_cents'] -= match
        touch(enr)
    return success(pub(r), 200)


# ---------------------------------------------------------------------------
# Education sessions & completions
# ---------------------------------------------------------------------------

@app.post('/programs/<programId>/education-sessions')
def create_session(programId):
    uid, role = auth('ProgramAdmin', 'Educator')
    prog = get_or_404(PROGRAMS, programId)
    b = json_body()
    topic = req_str(b, 'topic')
    venue = req_str(b, 'venue')
    starts = req_dt(b, 'starts_at')
    ends = req_dt(b, 'ends_at')
    capacity = req_int(b, 'capacity', minv=1)
    if role == 'Educator':
        educator_ref = uid
    else:
        educator_ref = req_str(b, 'educator_ref')
    start_dt = parse_dt(starts)
    end_dt = parse_dt(ends)
    if end_dt <= start_dt:
        err('ERR_INVALID_DATE_RANGE', 400, 'ends_at must be after starts_at')
    buf = timedelta(minutes=30)
    for s in SESSIONS.values():
        if s['program_id'] != prog['id'] or s['venue'] != venue:
            continue
        if s['status'] == 'CANCELLED':
            continue
        if parse_dt(s['starts_at']) - buf < end_dt and \
                start_dt < parse_dt(s['ends_at']) + buf:
            err('ERR_VENUE_CONFLICT', 409,
                'Education session venue occupied within the 30-minute buffer')
    s = new_entity({
        'program_id': prog['id'],
        'topic': topic,
        'venue': venue,
        'starts_at': starts,
        'ends_at': ends,
        'capacity': capacity,
        'educator_ref': educator_ref,
        'status': 'SCHEDULED',
    })
    SESSIONS[s['id']] = s
    return success(pub(s), 201)


@app.get('/education-sessions/<sessionId>')
def get_session(sessionId):
    auth('ProgramAdmin', 'Educator', 'ClinicStaff')
    return success(pub(get_or_404(SESSIONS, sessionId)), 200)


@app.get('/education-sessions')
def list_sessions():
    auth('ProgramAdmin', 'Educator', 'ClinicStaff')
    items = list(SESSIONS.values())
    pid = request.args.get('program_id')
    if pid is not None:
        items = [s for s in items if s['program_id'] == pid]
    return paginate(items)


@app.post('/education-sessions/<sessionId>/complete')
def complete_session(sessionId):
    auth('Educator')
    s = get_or_404(SESSIONS, sessionId)
    if s['status'] != 'SCHEDULED':
        err('ERR_SESSION_NOT_SCHEDULED', 409, 'Session is not SCHEDULED')
    s['status'] = 'COMPLETED'
    touch(s)
    return success(pub(s), 200)


@app.post('/education-sessions/<sessionId>/cancel')
def cancel_session(sessionId):
    auth('Educator')
    s = get_or_404(SESSIONS, sessionId)
    if s['status'] != 'SCHEDULED':
        err('ERR_SESSION_NOT_SCHEDULED', 409, 'Session is not SCHEDULED')
    s['status'] = 'CANCELLED'
    touch(s)
    return success(pub(s), 200)


@app.post('/education-sessions/<sessionId>/completions')
def create_completion(sessionId):
    auth('Educator')
    s = get_or_404(SESSIONS, sessionId)
    b = json_body()
    enr = get_or_404(ENROLLMENTS, b.get('enrollment_id'))
    minutes = req_int(b, 'minutes_attended')
    if minutes <= 0:
        err('ERR_VALIDATION', 400, 'minutes_attended must be > 0')
    passed = req_bool(b, 'passed')
    if s['status'] != 'COMPLETED':
        err('ERR_SESSION_NOT_SCHEDULED', 409,
            'Completion recorded for a non-COMPLETED session')
    if enr['status'] != 'ACTIVE':
        err('ERR_ENROLLMENT_NOT_ACTIVE', 409, 'Enrollment is not ACTIVE')
    existing = [c for c in COMPLETIONS.values() if c['session_id'] == s['id']]
    if len(existing) >= s['capacity']:
        err('ERR_SESSION_FULL', 409,
            'Completion count for the session already equals capacity')
    if any(c['enrollment_id'] == enr['id'] for c in existing):
        err('ERR_DUPLICATE_COMPLETION', 409,
            'Completion already exists for (enrollment, session)')
    comp = new_entity({
        'enrollment_id': enr['id'],
        'session_id': s['id'],
        'minutes_attended': minutes,
        'passed': passed,
    }, thin=True)
    COMPLETIONS[comp['id']] = comp
    prog = program_of_enrollment(enr)
    passed_count = sum(1 for c in COMPLETIONS.values()
                       if c['enrollment_id'] == enr['id'] and c['passed'])
    if passed_count >= prog['tier3_completions']:
        tier = 'T3'
    elif passed_count >= prog['tier2_completions']:
        tier = 'T2'
    else:
        tier = 'T1'
    if tier != enr['engagement_tier']:
        enr['engagement_tier'] = tier
        touch(enr)
    return success(pub(comp), 201)


@app.get('/education-completions/<completionId>')
def get_completion(completionId):
    auth('ProgramAdmin', 'Educator', 'ClinicStaff')
    return success(pub(get_or_404(COMPLETIONS, completionId)), 200)


@app.get('/education-completions')
def list_completions():
    auth('ProgramAdmin', 'Educator', 'ClinicStaff')
    items = list(COMPLETIONS.values())
    for param in ('enrollment_id', 'session_id'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c[param] == v]
    return paginate(items)


# ---------------------------------------------------------------------------
# Biometric readings
# ---------------------------------------------------------------------------

@app.post('/enrollments/<enrollmentId>/biometric-readings')
def create_reading(enrollmentId):
    uid, _ = auth('ClinicStaff')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    patient = PATIENTS.get(enr['patient_id'])
    if patient is None or patient['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403,
            'Acting clinic does not own the enrollment\'s patient')
    b = json_body()
    kind = req_enum(b, 'kind', ['A1C', 'WEIGHT_KG', 'SYSTOLIC_BP'])
    value = req_num(b, 'value')
    measured = req_dt(b, 'measured_at')
    source = req_enum(b, 'source', ['CLINIC', 'LAB_VERIFIED', 'SELF_REPORT'])
    # clinical safety (priority 7)
    if patient['consent_status'] != 'GRANTED':
        err('ERR_CONSENT_REVOKED', 422, 'Patient consent is not GRANTED')
    if kind == 'A1C':
        dv = Decimal(str(value))
        if dv < Decimal('3.0') or dv > Decimal('20.0'):
            err('ERR_A1C_OUT_OF_RANGE', 422,
                'A1C value outside [3.0, 20.0]')
    # cross-entity gate (priority 10)
    clinic = CLINICS.get(patient['clinic_id'])
    if clinic is None or clinic['status'] != 'ACTIVE':
        err('ERR_CLINIC_SUSPENDED', 409, 'Clinic is SUSPENDED')
    r = new_entity({
        'enrollment_id': enr['id'],
        'kind': kind,
        'value': value,
        'measured_at': measured,
        'source': source,
    }, thin=True)
    r['_measured'] = parse_dt(measured)
    READINGS[r['id']] = r
    return success(pub(r), 201)


@app.get('/biometric-readings/<readingId>')
def get_reading(readingId):
    auth('ProgramAdmin', 'ClinicStaff')
    return success(pub(get_or_404(READINGS, readingId)), 200)


@app.get('/biometric-readings')
def list_readings():
    auth('ProgramAdmin', 'ClinicStaff')
    items = list(READINGS.values())
    eid = request.args.get('enrollment_id')
    if eid is not None:
        items = [r for r in items if r['enrollment_id'] == eid]
    return paginate(items)


# ---------------------------------------------------------------------------
# Funder reports
# ---------------------------------------------------------------------------

@app.post('/programs/<programId>/funder-reports')
def create_report(programId):
    auth('ProgramAdmin')
    prog = get_or_404(PROGRAMS, programId)
    b = json_body()
    pool = get_or_404(POOLS, b.get('funding_pool_id'))
    ps = req_date(b, 'period_start')
    pe = req_date(b, 'period_end')
    basis = req_enum(b, 'basis', ['ACCRUAL', 'CASH'])
    expected = req_int(b, 'expected_program_version')
    if pool['program_id'] != prog['id']:
        err('ERR_VALIDATION', 400,
            'funding_pool_id must be a pool of this program')
    # OCC (priority 5)
    if expected != prog['version']:
        err('ERR_STALE_VERSION', 412,
            'expected_program_version does not match the program version')
    # temporal (priority 8)
    if ps >= pe:
        err('ERR_INVALID_DATE_RANGE', 400,
            'period_start must precede period_end')
    if basis == 'ACCRUAL':
        utilization = pool['disbursed_cents'] + pool['reserved_cents']
    else:
        utilization = pool['disbursed_cents']
    total_redeemed = 0
    total_match = 0
    for r in REDEMPTIONS.values():
        if r['status'] != 'SETTLED':
            continue
        enr = ENROLLMENTS.get(r['enrollment_id'])
        if enr is None or enr['program_id'] != prog['id']:
            continue
        day = r['redeemed_at'][:10]
        if ps <= day < pe:
            total_redeemed += r['voucher_applied_cents']
            total_match += r['match_cents']
    active_enrollments = sum(
        1 for e in ENROLLMENTS.values()
        if e['program_id'] == prog['id'] and e['status'] == 'ACTIVE')
    inc, ver = a1c_counts(prog)
    a1c_count = inc if basis == 'ACCRUAL' else ver
    for rep in REPORTS.values():
        if (rep['funding_pool_id'] == pool['id']
                and rep['period_start'] == ps and rep['period_end'] == pe
                and rep['status'] in ('DRAFT', 'RETURNED')):
            rep['status'] = 'SUPERSEDED'
            touch(rep)
    rep = new_entity({
        'program_id': prog['id'],
        'funding_pool_id': pool['id'],
        'period_start': ps,
        'period_end': pe,
        'basis': basis,
        'utilization_cents': utilization,
        'total_redeemed_cents': total_redeemed,
        'total_match_cents': total_match,
        'active_enrollments': active_enrollments,
        'a1c_improved_count': a1c_count,
        'revision_count': 0,
        'return_reason': None,
        'status': 'DRAFT',
    })
    REPORTS[rep['id']] = rep
    touch(prog)
    return success(pub(rep), 201)


@app.get('/funder-reports/<reportId>')
def get_report(reportId):
    auth('ProgramAdmin', 'FunderAnalyst')
    return success(pub(get_or_404(REPORTS, reportId)), 200)


@app.get('/funder-reports')
def list_reports():
    auth('ProgramAdmin', 'FunderAnalyst')
    items = list(REPORTS.values())
    for param in ('program_id', 'funding_pool_id'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    return paginate(items)


def _report_pool_funder(rep):
    pool = POOLS.get(rep['funding_pool_id'])
    return pool['funder_id'] if pool else None


@app.post('/funder-reports/<reportId>/submit')
def submit_report(reportId):
    auth('ProgramAdmin')
    rep = get_or_404(REPORTS, reportId)
    if rep['status'] not in ('DRAFT', 'RETURNED'):
        err('ERR_REPORT_NOT_EDITABLE', 409,
            'Report is not in a submittable state')
    rep['status'] = 'SUBMITTED'
    touch(rep)
    return success(pub(rep), 200)


@app.post('/funder-reports/<reportId>/accept')
def accept_report(reportId):
    uid, _ = auth('FunderAnalyst')
    rep = get_or_404(REPORTS, reportId)
    if _report_pool_funder(rep) != uid:
        err('ERR_FORBIDDEN', 403,
            'Only the pool\'s own funder may accept the report')
    if rep['status'] != 'SUBMITTED':
        err('ERR_REPORT_NOT_EDITABLE', 409, 'Report is not SUBMITTED')
    rep['status'] = 'ACCEPTED'
    touch(rep)
    return success(pub(rep), 200)


@app.post('/funder-reports/<reportId>/return')
def return_report(reportId):
    uid, _ = auth('FunderAnalyst')
    rep = get_or_404(REPORTS, reportId)
    if _report_pool_funder(rep) != uid:
        err('ERR_FORBIDDEN', 403,
            'Only the pool\'s own funder may return the report')
    b = json_body()
    reason = req_str(b, 'return_reason')
    if rep['status'] != 'SUBMITTED':
        err('ERR_REPORT_NOT_EDITABLE', 409, 'Report is not SUBMITTED')
    rep['status'] = 'RETURNED'
    rep['return_reason'] = reason
    rep['revision_count'] += 1
    touch(rep)
    return success(pub(rep), 200)


# ---------------------------------------------------------------------------
# Renewals
# ---------------------------------------------------------------------------

@app.post('/enrollments/<enrollmentId>/renewals')
def create_renewal(enrollmentId):
    uid, _ = auth('ClinicStaff')
    enr = get_or_404(ENROLLMENTS, enrollmentId)
    patient = PATIENTS.get(enr['patient_id'])
    if patient is None or patient['clinic_id'] != uid:
        err('ERR_FORBIDDEN', 403,
            'Acting clinic does not own the enrollment\'s patient')
    b = json_body()
    reason = req_str(b, 'reason')
    expected = req_int(b, 'expected_enrollment_version')
    # OCC (priority 5)
    if expected != enr['version']:
        err('ERR_STALE_VERSION', 412,
            'expected_enrollment_version does not match the enrollment version')
    # state (priority 6)
    if enr['status'] not in ('ACTIVE', 'LAPSED'):
        err('ERR_RENEWAL_NOT_ACTIONABLE', 409,
            'Renewal requires an ACTIVE or LAPSED enrollment')
    # temporal (priority 8)
    if enr['status'] == 'LAPSED':
        prog = program_of_enrollment(enr)
        window = timedelta(days=prog['renewal_window_days'])
        if now_dt() - parse_dt(enr['lapsed_at']) > window:
            err('ERR_OUTSIDE_RENEWAL_WINDOW', 422,
                'Renewal created after the renewal window')
    for r in RENEWALS.values():
        if r['enrollment_id'] == enr['id'] and r['status'] == 'DRAFT':
            r['status'] = 'SUPERSEDED'
            touch(r)
    ren = new_entity({
        'enrollment_id': enr['id'],
        'reason': reason,
        'resubmit_count': 0,
        'denial_reason': None,
        'status': 'DRAFT',
    })
    RENEWALS[ren['id']] = ren
    touch(enr)
    return success(pub(ren), 201)


@app.get('/renewals/<renewalId>')
def get_renewal(renewalId):
    auth('ProgramAdmin', 'ClinicStaff')
    return success(pub(get_or_404(RENEWALS, renewalId)), 200)


@app.get('/renewals')
def list_renewals():
    auth('ProgramAdmin', 'ClinicStaff')
    items = list(RENEWALS.values())
    eid = request.args.get('enrollment_id')
    if eid is not None:
        items = [r for r in items if r['enrollment_id'] == eid]
    return paginate(items)


def _renewal_owner_clinic(ren):
    enr = ENROLLMENTS.get(ren['enrollment_id'])
    if enr is None:
        return None
    patient = PATIENTS.get(enr['patient_id'])
    return patient['clinic_id'] if patient else None


@app.post('/renewals/<renewalId>/submit')
def submit_renewal(renewalId):
    uid, _ = auth('ClinicStaff')
    ren = get_or_404(RENEWALS, renewalId)
    if _renewal_owner_clinic(ren) != uid:
        err('ERR_FORBIDDEN', 403,
            'Acting clinic does not own the enrollment\'s patient')
    if ren['status'] != 'DRAFT':
        err('ERR_RENEWAL_NOT_ACTIONABLE', 409, 'Renewal is not DRAFT')
    ren['status'] = 'SUBMITTED'
    touch(ren)
    return success(pub(ren), 200)


@app.post('/renewals/<renewalId>/approve')
def approve_renewal(renewalId):
    auth('ProgramAdmin')
    ren = get_or_404(RENEWALS, renewalId)
    if ren['status'] != 'SUBMITTED':
        err('ERR_RENEWAL_NOT_ACTIONABLE', 409, 'Renewal is not SUBMITTED')
    enr = ENROLLMENTS.get(ren['enrollment_id'])
    patient = PATIENTS.get(enr['patient_id']) if enr else None
    clinic = CLINICS.get(patient['clinic_id']) if patient else None
    if clinic is None or clinic['status'] != 'ACTIVE':
        err('ERR_CLINIC_SUSPENDED', 409,
            'Clinic of the enrollment\'s patient is not ACTIVE')
    ren['status'] = 'APPROVED'
    touch(ren)
    if enr is not None and enr['status'] == 'LAPSED':
        enr['status'] = 'ACTIVE'
        enr['lapsed_at'] = None
        touch(enr)
    return success(pub(ren), 200)


@app.post('/renewals/<renewalId>/deny')
def deny_renewal(renewalId):
    auth('ProgramAdmin')
    ren = get_or_404(RENEWALS, renewalId)
    b = json_body()
    reason = req_str(b, 'denial_reason')
    if ren['status'] != 'SUBMITTED':
        err('ERR_RENEWAL_NOT_ACTIONABLE', 409, 'Renewal is not SUBMITTED')
    ren['status'] = 'DENIED'
    ren['denial_reason'] = reason
    touch(ren)
    return success(pub(ren), 200)


@app.post('/renewals/<renewalId>/resubmit')
def resubmit_renewal(renewalId):
    uid, _ = auth('ClinicStaff')
    ren = get_or_404(RENEWALS, renewalId)
    if _renewal_owner_clinic(ren) != uid:
        err('ERR_FORBIDDEN', 403,
            'Acting clinic does not own the enrollment\'s patient')
    b = json_body()
    ren['reason'] = req_str(b, 'reason')
    if ren['status'] != 'DENIED':
        err('ERR_RENEWAL_NOT_ACTIONABLE', 409, 'Renewal is not DENIED')
    ren['status'] = 'SUBMITTED'
    ren['resubmit_count'] += 1
    touch(ren)
    return success(pub(ren), 200)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
