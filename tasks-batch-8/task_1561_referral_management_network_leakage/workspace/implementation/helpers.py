"""Shared domain helpers: constants, request validation, pagination,
derived fields, serializers, and leakage-record creation."""
import json
import math
from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import request

from db import store, now, next_seq, new_id
from errors import fail
from response import fmt_dt

# ---------------- constants (SCAFFOLD calculations) ----------------
SPECIALTIES = ['CARDIOLOGY', 'ORTHOPEDICS', 'NEUROLOGY', 'DERMATOLOGY', 'ENDOCRINOLOGY']
URGENCIES = ['STAT', 'URGENT', 'ROUTINE']
SLA_DAYS = {'STAT': 2, 'URGENT': 7, 'ROUTINE': 30}
TIERS = ['PREFERRED', 'STANDARD']
CONFIRM_CHANNELS = ['PHONE', 'PORTAL', 'LETTER']
CANCEL_REASONS = ['PATIENT_WENT_OUT_OF_NETWORK', 'PATIENT_DECLINED', 'CLINICAL_DUPLICATE', 'OTHER']
CHOICE_TYPES = ['IN_NETWORK_PREFERRED', 'OUT_OF_NETWORK_PATIENT_REQUEST', 'OUT_OF_NETWORK_CAPACITY']
AUTH_OUTCOMES = ['OBTAINED', 'DENIED']
CLOSURE_OUTCOMES = ['VERIFIED_CLOSED', 'REOPENED']
BUFFER = timedelta(minutes=15)   # appointment overlap buffer
GRACE = timedelta(minutes=15)    # no-show grace
OVERDUE = timedelta(hours=24)    # overdue-unconfirmed window
STRIKE_LIMIT = 3
STRIKE_WEIGHT = 25
RISK_CAP = 100
NOTE_RETURN_DELTA = timedelta(days=14)
WATCH_COUNT = 2
BASE_CENTS = {
    'CARDIOLOGY': 42000,
    'ORTHOPEDICS': 33500,
    'NEUROLOGY': 50000,
    'DERMATOLOGY': 18000,
    'ENDOCRINOLOGY': 26000,
}

ACTIVE_APPT = ('SCHEDULED', 'CONFIRMED')


# ---------------- request body / field validation ----------------
def get_body():
    raw = request.get_data()
    if not raw:
        return {}
    try:
        body = json.loads(raw, parse_float=Decimal)
    except Exception:
        fail('ERR_INVALID_REQUEST', 400, 'Malformed JSON body')
    if not isinstance(body, dict):
        fail('ERR_INVALID_REQUEST', 400, 'Request body must be a JSON object')
    return body


def parse_dt_value(v):
    if not isinstance(v, str):
        return None
    s = v[:-1] + '+00:00' if v.endswith('Z') else v
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date_value(v):
    if not isinstance(v, str) or len(v) != 10 or v[4] != '-' or v[7] != '-':
        return None
    try:
        return datetime.strptime(v, '%Y-%m-%d').date()
    except ValueError:
        return None


def is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def f_str(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    if not isinstance(v, str):
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be a string' % name)
    return v


def f_enum(body, name, values, required=True):
    v = f_str(body, name, required)
    if v is None:
        return None
    if v not in values:
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be one of %s' % (name, values))
    return v


def f_bool(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    if not isinstance(v, bool):
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be a boolean' % name)
    return v


def f_int(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    if not is_int(v):
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be an integer' % name)
    return v


def f_datetime(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    dt = parse_dt_value(v)
    if dt is None:
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be a valid ISO8601 datetime' % name)
    return dt


def f_date(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    d = parse_date_value(v)
    if d is None:
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be a valid YYYY-MM-DD date' % name)
    return d


def f_number(body, name, required=True):
    v = body.get(name)
    if v is None:
        if required:
            fail('ERR_INVALID_REQUEST', 400, 'Missing required field: %s' % name)
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float, Decimal)):
        fail('ERR_INVALID_REQUEST', 400, 'Field %s must be a number' % name)
    return v if isinstance(v, Decimal) else Decimal(v)


# ---------------- pagination ----------------
def paginate(items):
    raw_limit = request.args.get('limit')
    raw_offset = request.args.get('offset')
    limit = 10
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST', 400, 'limit must be an integer')
        if limit < 1 or limit > 100:
            fail('ERR_INVALID_REQUEST', 400, 'limit must be between 1 and 100')
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail('ERR_INVALID_REQUEST', 400, 'offset must be an integer')
        if offset < 0:
            fail('ERR_INVALID_REQUEST', 400, 'offset must be >= 0')
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def by_creation(rec):
    return (rec['created_at'], rec['seq'])


# ---------------- record scaffolding ----------------
def scaffold_record():
    ts = now()
    return {'id': new_id(), 'created_at': ts, 'updated_at': ts, 'version': 1, 'seq': next_seq()}


def bump(rec):
    rec['version'] += 1
    rec['updated_at'] = now()


# ---------------- derived fields ----------------
def specialist_booked_count(sid):
    return sum(1 for a in store.appointments.values()
               if a['specialist_id'] == sid and a['status'] in ACTIVE_APPT)


def patient_strikes(pid):
    cnt = 0
    for a in store.appointments.values():
        if a['status'] != 'NO_SHOW':
            continue
        r = store.referrals.get(a['referral_id'])
        if r and r['patient_id'] == pid:
            cnt += 1
    return cnt


def patient_overdue_unconfirmed(pid):
    t = now()
    cnt = 0
    for a in store.appointments.values():
        if a['status'] != 'SCHEDULED':
            continue
        r = store.referrals.get(a['referral_id'])
        if r and r['patient_id'] == pid and t >= a['scheduled_start'] + OVERDUE:
            cnt += 1
    return cnt


def provider_leakage_count(pid):
    return sum(1 for l in store.leakage_records.values()
               if l['attributed_referring_provider_id'] == pid)


def referral_leaked(rid):
    return any(l['referral_id'] == rid for l in store.leakage_records.values())


def active_participation(sid, plan_id):
    today = now().date()
    best = None
    for p in store.participations.values():
        if (p['specialist_id'] == sid and p['insurance_plan_id'] == plan_id
                and p['status'] == 'ACTIVE'
                and p['effective_from'] <= today <= p['effective_to']):
            if best is None or p['seq'] > best['seq']:
                best = p
    return best


def matching_auth_rule(specialty, plan_id):
    """ACTIVE rule for the (specialty, plan) pair, or None."""
    for r in store.auth_rules.values():
        if (r['specialty'] == specialty and r['insurance_plan_id'] == plan_id
                and r['status'] == 'ACTIVE'):
            return r
    return None


def latest_auth_record(rid):
    recs = [a for a in store.auth_records.values() if a['referral_id'] == rid]
    if not recs:
        return None
    return max(recs, key=lambda a: a['seq'])


def referral_completed(rid):
    return any(a['referral_id'] == rid and a['status'] == 'COMPLETED'
               for a in store.appointments.values())


def rate4(num, den):
    if den == 0:
        return 0.0
    return float((Decimal(num) / Decimal(den)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP))


def provider_intake_set(pid, start_dt=None, end_dt=None):
    """Referrals of the provider with status != REJECTED, optionally windowed
    by created_at in [start_dt, end_dt). Statuses evaluated at call time."""
    out = []
    for r in store.referrals.values():
        if r['referring_provider_id'] != pid or r['status'] == 'REJECTED':
            continue
        if start_dt is not None and r['created_at'] < start_dt:
            continue
        if end_dt is not None and r['created_at'] >= end_dt:
            continue
        out.append(r)
    return out


def exposure_of(referral_ids):
    return sum(l['estimated_value_cents'] for l in store.leakage_records.values()
               if l['referral_id'] in referral_ids)


# ---------------- side-effect helpers ----------------
def create_leakage_record(referral, category):
    plan = store.plans.get(referral['insurance_plan_id'])
    factor = plan['payer_mix_factor'] if plan else Decimal(1)
    value = int((Decimal(BASE_CENTS[referral['specialty']]) * factor).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP))
    rec = {
        'id': new_id(),
        'created_at': now(),
        'seq': next_seq(),
        'referral_id': referral['id'],
        'category': category,
        'attributed_referring_provider_id': referral['referring_provider_id'],
        'estimated_value_cents': value,
    }
    store.leakage_records[rec['id']] = rec
    return rec


def cascade_cancel_appointment(appt, superseded=False):
    """Cancel an active appointment as a side effect (supersede, referral
    cancel, or aging expiry). Frees the booked slot (derived counter)."""
    appt['status'] = 'CANCELLED'
    if superseded:
        appt['superseded'] = True
    bump(appt)


def active_appointments_of_referral(rid, exclude_id=None):
    return [a for a in store.appointments.values()
            if a['referral_id'] == rid and a['status'] in ACTIVE_APPT and a['id'] != exclude_id]


# ---------------- serializers ----------------
def num_out(d):
    """Serialize a Decimal as int when integral, else float."""
    if isinstance(d, Decimal):
        if d == d.to_integral_value():
            return int(d)
        return float(d)
    return d


def ser_provider(p):
    count = provider_leakage_count(p['id'])
    return {
        'id': p['id'], 'name': p['name'], 'npi': p['npi'], 'specialty': p['specialty'],
        'status': p['status'],
        'leakage_event_count': count,
        'watch_flag': count >= WATCH_COUNT,
        'created_at': fmt_dt(p['created_at']), 'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_specialist(s):
    return {
        'id': s['id'], 'name': s['name'], 'npi': s['npi'], 'specialty': s['specialty'],
        'base_region': s['base_region'], 'weekly_capacity': s['weekly_capacity'],
        'accepts_new_patients': s['accepts_new_patients'],
        'accepts_urgent': s['accepts_urgent'],
        'booked_appointments_count': specialist_booked_count(s['id']),
        'status': s['status'],
        'created_at': fmt_dt(s['created_at']), 'updated_at': fmt_dt(s['updated_at']),
        'version': s['version'],
    }


def ser_plan(p):
    return {
        'id': p['id'], 'plan_code': p['plan_code'], 'payer_name': p['payer_name'],
        'payer_mix_factor': num_out(p['payer_mix_factor']),
        'status': p['status'],
        'created_at': fmt_dt(p['created_at']), 'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_patient(p):
    strikes = patient_strikes(p['id'])
    overdue = patient_overdue_unconfirmed(p['id'])
    confirmed = min(RISK_CAP, STRIKE_WEIGHT * strikes)
    forward = min(RISK_CAP, STRIKE_WEIGHT * (strikes + 0.5 * overdue))
    if forward == int(forward):
        forward = int(forward)
    return {
        'id': p['id'], 'mrn': p['mrn'], 'full_name': p['full_name'],
        'date_of_birth': p['date_of_birth'], 'region': p['region'],
        'insurance_plan_id': p['insurance_plan_id'],
        'no_show_strikes': strikes,
        'status': 'OUTREACH_REQUIRED' if strikes >= STRIKE_LIMIT else 'ACTIVE',
        'no_show_risk_confirmed': confirmed,
        'no_show_risk_forward': forward,
        'created_at': fmt_dt(p['created_at']), 'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_participation(p):
    return {
        'id': p['id'], 'specialist_id': p['specialist_id'],
        'insurance_plan_id': p['insurance_plan_id'], 'tier': p['tier'],
        'effective_from': p['effective_from'].isoformat(),
        'effective_to': p['effective_to'].isoformat(),
        'status': p['status'],
        'created_at': fmt_dt(p['created_at']), 'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_auth_rule(r):
    return {
        'id': r['id'], 'specialty': r['specialty'],
        'insurance_plan_id': r['insurance_plan_id'],
        'requires_auth': r['requires_auth'],
        'auth_validity_days': r['auth_validity_days'],
        'status': r['status'],
        'created_at': fmt_dt(r['created_at']), 'updated_at': fmt_dt(r['updated_at']),
        'version': r['version'],
    }


def ser_referral(r):
    age = math.floor((now() - r['created_at']).total_seconds() / 86400)
    return {
        'id': r['id'],
        'referring_provider_id': r['referring_provider_id'],
        'patient_id': r['patient_id'],
        'specialty': r['specialty'],
        'diagnosis_code': r['diagnosis_code'],
        'urgency': r['urgency'],
        'insurance_plan_id': r['insurance_plan_id'],
        'in_network_preference': r['in_network_preference'],
        'patient_choice_documented': r['patient_choice_documented'],
        'patient_choice_type': r['patient_choice_type'],
        'patient_choice_note': r['patient_choice_note'],
        'target_specialist_id': r['target_specialist_id'],
        'match_score': r['match_score'],
        'status': r['status'],
        'auth_status': r['auth_status'],
        'triaged_at': fmt_dt(r['triaged_at']) if r['triaged_at'] else None,
        'sla_due_at': fmt_dt(r['sla_due_at']) if r['sla_due_at'] else None,
        'age_days': age,
        'ever_scheduled': r['ever_scheduled'],
        'escalation_flag': r['escalation_flag'],
        'leaked': referral_leaked(r['id']),
        'out_of_network': r['out_of_network'],
        'cancel_reason': r['cancel_reason'],
        'needs_info_note': r['needs_info_note'],
        'created_at': fmt_dt(r['created_at']), 'updated_at': fmt_dt(r['updated_at']),
        'version': r['version'],
    }


def ser_auth_record(a):
    return {
        'id': a['id'], 'referral_id': a['referral_id'],
        'auth_number': a['auth_number'],
        'obtained_at': fmt_dt(a['obtained_at']),
        'expires_on': fmt_dt(a['expires_on']),
        'status': a['status'],
        'created_at': fmt_dt(a['created_at']), 'updated_at': fmt_dt(a['updated_at']),
        'version': a['version'],
    }


def ser_appointment(a):
    return {
        'id': a['id'], 'referral_id': a['referral_id'],
        'specialist_id': a['specialist_id'],
        'scheduled_start': fmt_dt(a['scheduled_start']),
        'scheduled_end': fmt_dt(a['scheduled_end']),
        'status': a['status'],
        'confirmation_channel': a['confirmation_channel'],
        'confirmed_at': fmt_dt(a['confirmed_at']) if a['confirmed_at'] else None,
        'completed_at': fmt_dt(a['completed_at']) if a['completed_at'] else None,
        'superseded': a['superseded'],
        'excuse_reason': a['excuse_reason'],
        'scheduled_by_user_id': a['scheduled_by_user_id'],
        'created_at': fmt_dt(a['created_at']), 'updated_at': fmt_dt(a['updated_at']),
        'version': a['version'],
    }


def ser_consult_note(n):
    return {
        'id': n['id'], 'referral_id': n['referral_id'],
        'appointment_id': n['appointment_id'],
        'author_specialist_id': n['author_specialist_id'],
        'findings_summary': n['findings_summary'],
        'follow_up_recommended': n['follow_up_recommended'],
        'note_sequence': n['note_sequence'],
        'returned_within_sla': n['returned_within_sla'],
        'created_at': fmt_dt(n['created_at']),
    }


def ser_loop_closure(c):
    return {
        'id': c['id'], 'referral_id': c['referral_id'],
        'outcome': c['outcome'], 'verification_note': c['verification_note'],
        'verifier_user_id': c['verifier_user_id'],
        'created_at': fmt_dt(c['created_at']),
    }


def ser_leakage_record(l):
    return {
        'id': l['id'], 'referral_id': l['referral_id'],
        'category': l['category'],
        'attributed_referring_provider_id': l['attributed_referring_provider_id'],
        'estimated_value_cents': l['estimated_value_cents'],
        'created_at': fmt_dt(l['created_at']),
    }


def ser_snapshot(s):
    return {
        'id': s['id'],
        'referring_provider_id': s['referring_provider_id'],
        'period_start': s['period_start'].isoformat(),
        'period_end': s['period_end'].isoformat(),
        'intake_count': s['intake_count'],
        'completed_count': s['completed_count'],
        'scheduled_basis_count': s['scheduled_basis_count'],
        'leaked_count': s['leaked_count'],
        'conversion_rate_intake': s['conversion_rate_intake'],
        'conversion_rate_scheduled': s['conversion_rate_scheduled'],
        'leakage_rate': s['leakage_rate'],
        'estimated_leakage_exposure_cents': s['estimated_leakage_exposure_cents'],
        'closed_at': fmt_dt(s['closed_at']),
        'created_at': fmt_dt(s['created_at']),
    }
