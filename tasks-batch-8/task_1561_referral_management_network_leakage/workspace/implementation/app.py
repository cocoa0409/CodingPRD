"""Referral Management & Network Leakage API — Flask implementation.

Purely in-memory storage; nothing is seeded at startup. Every entity is
constructed via the declared API surface. Validation follows the priority
order of PRD section 2.7.
"""
import os
from datetime import datetime, timezone, timedelta, time as dtime
from decimal import Decimal

from flask import Flask, request

from db import store, now, set_clock, new_id, next_seq
from errors import ApiError, fail
from response import success_object, success_list, error_response, fmt_dt
from middleware import authenticate, ALL_ROLES
from helpers import (
    SPECIALTIES, URGENCIES, SLA_DAYS, TIERS, CONFIRM_CHANNELS, CANCEL_REASONS,
    CHOICE_TYPES, AUTH_OUTCOMES, CLOSURE_OUTCOMES, BUFFER, GRACE,
    ACTIVE_APPT,
    get_body, f_str, f_enum, f_bool, f_int, f_datetime, f_date, f_number,
    parse_date_value, paginate, by_creation, scaffold_record, bump,
    specialist_booked_count, active_participation, matching_auth_rule,
    latest_auth_record, referral_leaked, referral_completed, rate4,
    patient_strikes,
    provider_intake_set, exposure_of, create_leakage_record,
    cascade_cancel_appointment, active_appointments_of_referral,
    ser_provider, ser_specialist, ser_plan, ser_patient, ser_participation,
    ser_auth_rule, ser_referral, ser_auth_record, ser_appointment,
    ser_consult_note, ser_loop_closure, ser_leakage_record, ser_snapshot,
)

app = Flask(__name__)

READERS = ALL_ROLES  # roles allowed on global GET reads


@app.errorhandler(ApiError)
def handle_api_error(err):
    return error_response(err)


# ---------------------------------------------------------------- clock
@app.post('/_clock/set_current_utc')
def clock_set():
    authenticate(['NetworkAdmin'])
    body = get_body()
    dt = f_datetime(body, 'to_iso8601')
    set_clock(dt)
    return success_object({'current_utc': fmt_dt(dt)})


# ---------------------------------------------------------------- referring providers
@app.post('/referring-providers')
def create_referring_provider():
    authenticate(['NetworkAdmin'])
    body = get_body()
    name = f_str(body, 'name')
    npi = f_str(body, 'npi')
    specialty = f_str(body, 'specialty')
    if (any(p['npi'] == npi for p in store.referring_providers.values())
            or any(s['npi'] == npi for s in store.specialists.values())):
        fail('ERR_DUPLICATE_NPI', 409, 'NPI already registered')
    rec = scaffold_record()
    rec.update({'name': name, 'npi': npi, 'specialty': specialty, 'status': 'ACTIVE'})
    store.referring_providers[rec['id']] = rec
    return success_object(ser_provider(rec), 201)


@app.get('/referring-providers')
def list_referring_providers():
    authenticate(READERS)
    items = sorted(store.referring_providers.values(), key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [p for p in items if p['status'] == st]
    sp = request.args.get('specialty')
    if sp is not None:
        items = [p for p in items if p['specialty'] == sp]
    page, limit, offset, total = paginate(items)
    return success_list([ser_provider(p) for p in page], limit, offset, total)


def get_provider_or_404(pid):
    p = store.referring_providers.get(pid)
    if not p:
        fail('ERR_PROVIDER_NOT_FOUND', 404, 'Referring provider not found')
    return p


@app.get('/referring-providers/<pid>')
def get_referring_provider(pid):
    authenticate(READERS)
    return success_object(ser_provider(get_provider_or_404(pid)))


@app.post('/referring-providers/<pid>/suspend')
def suspend_referring_provider(pid):
    authenticate(['NetworkAdmin'])
    p = get_provider_or_404(pid)
    if p['status'] != 'ACTIVE':
        fail('ERR_INVALID_STATE', 409, 'Provider is not ACTIVE')
    p['status'] = 'SUSPENDED'
    bump(p)
    return success_object(ser_provider(p))


@app.post('/referring-providers/<pid>/reactivate')
def reactivate_referring_provider(pid):
    authenticate(['NetworkAdmin'])
    p = get_provider_or_404(pid)
    if p['status'] != 'SUSPENDED':
        fail('ERR_INVALID_STATE', 409, 'Provider is not SUSPENDED')
    p['status'] = 'ACTIVE'
    bump(p)
    return success_object(ser_provider(p))


def check_provider_scope_ownership(pid, uid, role):
    """A ReferringProvider may only access their own provider-scoped reads."""
    if role == 'ReferringProvider' and uid != pid:
        fail('ERR_OWNERSHIP_VIOLATION', 403,
             'Referring providers may only access their own resources')


@app.get('/referring-providers/<pid>/referrals')
def provider_referrals(pid):
    uid, role = authenticate(READERS)
    check_provider_scope_ownership(pid, uid, role)
    get_provider_or_404(pid)
    items = sorted([r for r in store.referrals.values()
                    if r['referring_provider_id'] == pid], key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [r for r in items if r['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_referral(r) for r in page], limit, offset, total)


@app.get('/referring-providers/<pid>/leakage-records')
def provider_leakage_records(pid):
    uid, role = authenticate(['NetworkAdmin', 'ReferralCoordinator',
                              'ComplianceAuditor', 'ReferringProvider'])
    check_provider_scope_ownership(pid, uid, role)
    get_provider_or_404(pid)
    items = sorted([l for l in store.leakage_records.values()
                    if l['attributed_referring_provider_id'] == pid], key=by_creation)
    cat = request.args.get('category')
    if cat is not None:
        items = [l for l in items if l['category'] == cat]
    page, limit, offset, total = paginate(items)
    return success_list([ser_leakage_record(l) for l in page], limit, offset, total)


@app.get('/referring-providers/<pid>/leakage-snapshots')
def provider_leakage_snapshots(pid):
    uid, role = authenticate(['NetworkAdmin', 'ReferralCoordinator',
                              'ComplianceAuditor', 'ReferringProvider'])
    check_provider_scope_ownership(pid, uid, role)
    get_provider_or_404(pid)
    items = sorted([s for s in store.snapshots.values()
                    if s['referring_provider_id'] == pid], key=by_creation)
    page, limit, offset, total = paginate(items)
    return success_list([ser_snapshot(s) for s in page], limit, offset, total)


@app.get('/referring-providers/<pid>/leakage-report')
def provider_leakage_report(pid):
    uid, role = authenticate(['NetworkAdmin', 'ReferralCoordinator', 'ReferringProvider'])
    check_provider_scope_ownership(pid, uid, role)
    get_provider_or_404(pid)
    basis = request.args.get('basis', 'INTAKE')
    if basis not in ('INTAKE', 'SCHEDULED'):
        fail('ERR_INVALID_REQUEST', 400, 'basis must be INTAKE or SCHEDULED')
    intake = provider_intake_set(pid)
    completed = [r for r in intake if referral_completed(r['id'])]
    scheduled_basis = [r for r in intake if r['ever_scheduled']]
    leaked = [r for r in intake if referral_leaked(r['id'])]
    if basis == 'INTAKE':
        conversion = rate4(len(completed), len(intake))
    else:
        conversion = rate4(len(completed), len(scheduled_basis))
    data = {
        'basis': basis,
        'intake_count': len(intake),
        'completed_count': len(completed),
        'leaked_count': len(leaked),
        'conversion_rate': conversion,
        'leakage_rate': rate4(len(leaked), len(intake)),
        'estimated_leakage_exposure_cents': exposure_of({r['id'] for r in leaked}),
    }
    return success_object(data)


# ---------------------------------------------------------------- specialists
@app.post('/specialty-providers')
def create_specialist():
    authenticate(['NetworkAdmin'])
    body = get_body()
    name = f_str(body, 'name')
    npi = f_str(body, 'npi')
    specialty = f_enum(body, 'specialty', SPECIALTIES)
    base_region = f_str(body, 'base_region')
    weekly_capacity = f_int(body, 'weekly_capacity')
    if weekly_capacity < 1:
        fail('ERR_INVALID_REQUEST', 400, 'weekly_capacity must be >= 1')
    accepts_new = f_bool(body, 'accepts_new_patients', required=False)
    accepts_urgent = f_bool(body, 'accepts_urgent', required=False)
    if (any(s['npi'] == npi for s in store.specialists.values())
            or any(p['npi'] == npi for p in store.referring_providers.values())):
        fail('ERR_DUPLICATE_NPI', 409, 'NPI already registered')
    rec = scaffold_record()
    rec.update({
        'name': name, 'npi': npi, 'specialty': specialty, 'base_region': base_region,
        'weekly_capacity': weekly_capacity,
        'accepts_new_patients': True if accepts_new is None else accepts_new,
        'accepts_urgent': False if accepts_urgent is None else accepts_urgent,
        'status': 'ACTIVE',
    })
    store.specialists[rec['id']] = rec
    return success_object(ser_specialist(rec), 201)


@app.get('/specialty-providers')
def list_specialists():
    authenticate(READERS)
    items = sorted(store.specialists.values(), key=by_creation)
    sp = request.args.get('specialty')
    if sp is not None:
        items = [s for s in items if s['specialty'] == sp]
    st = request.args.get('status')
    if st is not None:
        items = [s for s in items if s['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_specialist(s) for s in page], limit, offset, total)


def get_specialist_or_404(sid):
    s = store.specialists.get(sid)
    if not s:
        fail('ERR_SPECIALIST_NOT_FOUND', 404, 'Specialist not found')
    return s


@app.get('/specialty-providers/<sid>')
def get_specialist(sid):
    authenticate(READERS)
    return success_object(ser_specialist(get_specialist_or_404(sid)))


@app.post('/specialty-providers/<sid>/suspend')
def suspend_specialist(sid):
    authenticate(['NetworkAdmin'])
    s = get_specialist_or_404(sid)
    if s['status'] != 'ACTIVE':
        fail('ERR_INVALID_STATE', 409, 'Specialist is not ACTIVE')
    s['status'] = 'SUSPENDED'
    bump(s)
    return success_object(ser_specialist(s))


@app.post('/specialty-providers/<sid>/reactivate')
def reactivate_specialist(sid):
    authenticate(['NetworkAdmin'])
    s = get_specialist_or_404(sid)
    if s['status'] != 'SUSPENDED':
        fail('ERR_INVALID_STATE', 409, 'Specialist is not SUSPENDED')
    s['status'] = 'ACTIVE'
    bump(s)
    return success_object(ser_specialist(s))


@app.get('/specialty-providers/<sid>/network-participations')
def specialist_participations(sid):
    authenticate(READERS)
    get_specialist_or_404(sid)
    items = sorted([p for p in store.participations.values()
                    if p['specialist_id'] == sid], key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [p for p in items if p['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_participation(p) for p in page], limit, offset, total)


@app.get('/specialty-providers/<sid>/appointments')
def specialist_appointments(sid):
    authenticate(['NetworkAdmin', 'ReferralCoordinator', 'ComplianceAuditor',
                  'SpecialistProvider'])
    get_specialist_or_404(sid)
    items = sorted([a for a in store.appointments.values()
                    if a['specialist_id'] == sid], key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [a for a in items if a['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_appointment(a) for a in page], limit, offset, total)


# ---------------------------------------------------------------- patients
@app.post('/patients')
def create_patient():
    authenticate(['NetworkAdmin'])
    body = get_body()
    mrn = f_str(body, 'mrn')
    full_name = f_str(body, 'full_name')
    dob = f_date(body, 'date_of_birth')
    region = f_str(body, 'region')
    plan_id = f_str(body, 'insurance_plan_id')
    if plan_id not in store.plans:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    if any(p['mrn'] == mrn for p in store.patients.values()):
        fail('ERR_DUPLICATE_MRN', 409, 'MRN already registered')
    rec = scaffold_record()
    rec.update({
        'mrn': mrn, 'full_name': full_name, 'date_of_birth': dob.isoformat(),
        'region': region, 'insurance_plan_id': plan_id,
    })
    store.patients[rec['id']] = rec
    return success_object(ser_patient(rec), 201)


@app.get('/patients')
def list_patients():
    authenticate(READERS)
    items = sorted(store.patients.values(), key=by_creation)
    plan = request.args.get('insurance_plan_id')
    if plan is not None:
        items = [p for p in items if p['insurance_plan_id'] == plan]
    st = request.args.get('status')
    if st is not None:
        items = [p for p in items if ser_patient(p)['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_patient(p) for p in page], limit, offset, total)


def get_patient_or_404(pid):
    p = store.patients.get(pid)
    if not p:
        fail('ERR_PATIENT_NOT_FOUND', 404, 'Patient not found')
    return p


@app.get('/patients/<pid>')
def get_patient(pid):
    authenticate(READERS)
    return success_object(ser_patient(get_patient_or_404(pid)))


@app.get('/patients/<pid>/referrals')
def patient_referrals(pid):
    authenticate(READERS)
    get_patient_or_404(pid)
    items = sorted([r for r in store.referrals.values() if r['patient_id'] == pid],
                   key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [r for r in items if r['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_referral(r) for r in page], limit, offset, total)


# ---------------------------------------------------------------- insurance plans
@app.post('/insurance-plans')
def create_plan():
    authenticate(['NetworkAdmin'])
    body = get_body()
    plan_code = f_str(body, 'plan_code')
    payer_name = f_str(body, 'payer_name')
    factor = f_number(body, 'payer_mix_factor')
    if factor <= 0:
        fail('ERR_INVALID_REQUEST', 400, 'payer_mix_factor must be > 0')
    if any(p['plan_code'] == plan_code for p in store.plans.values()):
        fail('ERR_DUPLICATE_PLAN_CODE', 409, 'Plan code already exists')
    rec = scaffold_record()
    rec.update({'plan_code': plan_code, 'payer_name': payer_name,
                'payer_mix_factor': factor, 'status': 'ACTIVE'})
    store.plans[rec['id']] = rec
    return success_object(ser_plan(rec), 201)


@app.get('/insurance-plans')
def list_plans():
    authenticate(READERS)
    items = sorted(store.plans.values(), key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [p for p in items if p['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_plan(p) for p in page], limit, offset, total)


def get_plan_or_404(pid):
    p = store.plans.get(pid)
    if not p:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    return p


@app.get('/insurance-plans/<pid>')
def get_plan(pid):
    authenticate(READERS)
    return success_object(ser_plan(get_plan_or_404(pid)))


@app.post('/insurance-plans/<pid>/retire')
def retire_plan(pid):
    authenticate(['NetworkAdmin'])
    p = get_plan_or_404(pid)
    if p['status'] != 'ACTIVE':
        fail('ERR_INVALID_STATE', 409, 'Plan is not ACTIVE')
    p['status'] = 'RETIRED'
    bump(p)
    return success_object(ser_plan(p))


# ---------------------------------------------------------------- network participation
@app.post('/network-participations')
def create_participation():
    authenticate(['NetworkAdmin'])
    body = get_body()
    specialist_id = f_str(body, 'specialist_id')
    plan_id = f_str(body, 'insurance_plan_id')
    tier = f_enum(body, 'tier', TIERS)
    eff_from = f_date(body, 'effective_from')
    eff_to = f_date(body, 'effective_to')
    if specialist_id not in store.specialists:
        fail('ERR_SPECIALIST_NOT_FOUND', 404, 'Specialist not found')
    plan = store.plans.get(plan_id)
    if not plan:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    if plan['status'] == 'RETIRED':
        fail('ERR_PLAN_RETIRED', 409, 'Plan is retired')
    if eff_to < eff_from:
        fail('ERR_INVALID_WINDOW', 400, 'effective_to must be >= effective_from')
    for p in store.participations.values():
        if (p['specialist_id'] == specialist_id and p['insurance_plan_id'] == plan_id
                and p['status'] == 'ACTIVE'
                and eff_from <= p['effective_to'] and eff_to >= p['effective_from']):
            fail('ERR_PARTICIPATION_WINDOW_OVERLAP', 409,
                 'Overlapping ACTIVE participation window for this specialist and plan')
    rec = scaffold_record()
    rec.update({'specialist_id': specialist_id, 'insurance_plan_id': plan_id,
                'tier': tier, 'effective_from': eff_from, 'effective_to': eff_to,
                'status': 'ACTIVE'})
    store.participations[rec['id']] = rec
    return success_object(ser_participation(rec), 201)


@app.get('/network-participations')
def list_participations():
    authenticate(READERS)
    items = sorted(store.participations.values(), key=by_creation)
    sid = request.args.get('specialist_id')
    if sid is not None:
        items = [p for p in items if p['specialist_id'] == sid]
    pl = request.args.get('insurance_plan_id')
    if pl is not None:
        items = [p for p in items if p['insurance_plan_id'] == pl]
    st = request.args.get('status')
    if st is not None:
        items = [p for p in items if p['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_participation(p) for p in page], limit, offset, total)


@app.get('/network-participations/<pid>')
def get_participation(pid):
    authenticate(READERS)
    p = store.participations.get(pid)
    if not p:
        fail('ERR_PARTICIPATION_NOT_FOUND', 404, 'Participation not found')
    return success_object(ser_participation(p))


@app.post('/network-participations/<pid>/terminate')
def terminate_participation(pid):
    authenticate(['NetworkAdmin'])
    p = store.participations.get(pid)
    if not p:
        fail('ERR_PARTICIPATION_NOT_FOUND', 404, 'Participation not found')
    if p['status'] != 'ACTIVE':
        fail('ERR_INVALID_STATE', 409, 'Participation is not ACTIVE')
    p['status'] = 'TERMINATED'
    bump(p)
    return success_object(ser_participation(p))


# ---------------------------------------------------------------- prior auth rules
@app.post('/prior-auth-rules')
def create_auth_rule():
    authenticate(['NetworkAdmin'])
    body = get_body()
    specialty = f_enum(body, 'specialty', SPECIALTIES)
    plan_id = f_str(body, 'insurance_plan_id')
    requires_auth = f_bool(body, 'requires_auth')
    validity = f_int(body, 'auth_validity_days')
    if validity < 1:
        fail('ERR_INVALID_REQUEST', 400, 'auth_validity_days must be >= 1')
    plan = store.plans.get(plan_id)
    if not plan:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    if plan['status'] == 'RETIRED':
        fail('ERR_PLAN_RETIRED', 409, 'Plan is retired')
    if matching_auth_rule(specialty, plan_id) is not None:
        fail('ERR_DUPLICATE_AUTH_RULE', 409,
             'An ACTIVE rule already exists for this specialty and plan')
    rec = scaffold_record()
    rec.update({'specialty': specialty, 'insurance_plan_id': plan_id,
                'requires_auth': requires_auth, 'auth_validity_days': validity,
                'status': 'ACTIVE'})
    store.auth_rules[rec['id']] = rec
    return success_object(ser_auth_rule(rec), 201)


@app.get('/prior-auth-rules')
def list_auth_rules():
    authenticate(READERS)
    items = sorted(store.auth_rules.values(), key=by_creation)
    sp = request.args.get('specialty')
    if sp is not None:
        items = [r for r in items if r['specialty'] == sp]
    pl = request.args.get('insurance_plan_id')
    if pl is not None:
        items = [r for r in items if r['insurance_plan_id'] == pl]
    st = request.args.get('status')
    if st is not None:
        items = [r for r in items if r['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_auth_rule(r) for r in page], limit, offset, total)


@app.get('/prior-auth-rules/<rid>')
def get_auth_rule(rid):
    authenticate(READERS)
    r = store.auth_rules.get(rid)
    if not r:
        fail('ERR_AUTH_RULE_NOT_FOUND', 404, 'Prior auth rule not found')
    return success_object(ser_auth_rule(r))


@app.post('/prior-auth-rules/<rid>/retire')
def retire_auth_rule(rid):
    authenticate(['NetworkAdmin'])
    r = store.auth_rules.get(rid)
    if not r:
        fail('ERR_AUTH_RULE_NOT_FOUND', 404, 'Prior auth rule not found')
    if r['status'] != 'ACTIVE':
        fail('ERR_INVALID_STATE', 409, 'Rule is not ACTIVE')
    r['status'] = 'RETIRED'
    bump(r)
    return success_object(ser_auth_rule(r))


# ---------------------------------------------------------------- referrals
@app.post('/referrals')
def create_referral():
    uid, role = authenticate(['ReferringProvider'])
    body = get_body()
    patient_id = f_str(body, 'patient_id')
    specialty = f_enum(body, 'specialty', SPECIALTIES)
    diagnosis_code = f_str(body, 'diagnosis_code')
    urgency = f_enum(body, 'urgency', URGENCIES)
    plan_id = f_str(body, 'insurance_plan_id', required=False)
    in_network_pref = f_bool(body, 'in_network_preference', required=False)
    provider = store.referring_providers.get(uid)
    if not provider:
        fail('ERR_PROVIDER_NOT_FOUND', 404, 'Referring provider not found')
    patient = store.patients.get(patient_id)
    if not patient:
        fail('ERR_PATIENT_NOT_FOUND', 404, 'Patient not found')
    effective_plan_id = plan_id if plan_id else patient['insurance_plan_id']
    plan = store.plans.get(effective_plan_id)
    if not plan:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    if provider['status'] == 'SUSPENDED':
        fail('ERR_PROVIDER_SUSPENDED', 403, 'Referring provider is suspended')
    if plan['status'] == 'RETIRED':
        fail('ERR_PLAN_RETIRED', 409, 'Plan is retired')
    rec = scaffold_record()
    rec.update({
        'referring_provider_id': uid,
        'patient_id': patient_id,
        'specialty': specialty,
        'diagnosis_code': diagnosis_code,
        'urgency': urgency,
        'insurance_plan_id': effective_plan_id,
        'in_network_preference': True if in_network_pref is None else in_network_pref,
        'patient_choice_documented': False,
        'patient_choice_type': 'NONE',
        'patient_choice_note': '',
        'target_specialist_id': None,
        'match_score': None,
        'status': 'PENDING_TRIAGE',
        'auth_status': 'NOT_EVALUATED',
        'triaged_at': None,
        'sla_due_at': None,
        'ever_scheduled': False,
        'escalation_flag': False,
        'out_of_network': False,
        'cancel_reason': None,
        'needs_info_note': '',
    })
    store.referrals[rec['id']] = rec
    return success_object(ser_referral(rec), 201)


@app.get('/referrals')
def list_referrals():
    uid, role = authenticate(READERS)
    items = list(store.referrals.values())
    if role == 'ReferringProvider':
        items = [r for r in items if r['referring_provider_id'] == uid]
    for param in ('referring_provider_id', 'patient_id', 'status', 'specialty',
                  'target_specialist_id', 'insurance_plan_id'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r[param] == v]
    raw_leaked = request.args.get('leaked')
    if raw_leaked is not None:
        if raw_leaked == 'true':
            items = [r for r in items if referral_leaked(r['id'])]
        elif raw_leaked == 'false':
            items = [r for r in items if not referral_leaked(r['id'])]
        else:
            fail('ERR_INVALID_REQUEST', 400, 'leaked must be true or false')
    items.sort(key=by_creation)
    page, limit, offset, total = paginate(items)
    return success_list([ser_referral(r) for r in page], limit, offset, total)


def get_referral_or_404(rid):
    r = store.referrals.get(rid)
    if not r:
        fail('ERR_REFERRAL_NOT_FOUND', 404, 'Referral not found')
    return r


def check_referral_ownership(r, uid, role):
    if role == 'ReferringProvider' and r['referring_provider_id'] != uid:
        fail('ERR_OWNERSHIP_VIOLATION', 403,
             'Referring providers may only access their own referrals')


@app.get('/referrals/<rid>')
def get_referral(rid):
    uid, role = authenticate(READERS)
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/request-info')
def request_info(rid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    note = f_str(body, 'note')
    r = get_referral_or_404(rid)
    if r['status'] != 'PENDING_TRIAGE':
        fail('ERR_INVALID_STATE', 409, 'Referral is not PENDING_TRIAGE')
    r['status'] = 'NEEDS_INFO'
    r['needs_info_note'] = note
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/resubmit')
def resubmit_referral(rid):
    uid, role = authenticate(['ReferringProvider'])
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    body = get_body()
    diagnosis_code = f_str(body, 'diagnosis_code', required=False)
    urgency = f_enum(body, 'urgency', URGENCIES, required=False)
    in_network_pref = f_bool(body, 'in_network_preference', required=False)
    plan_id = f_str(body, 'insurance_plan_id', required=False)
    if plan_id is not None and plan_id not in store.plans:
        fail('ERR_PLAN_NOT_FOUND', 404, 'Insurance plan not found')
    if r['status'] != 'NEEDS_INFO':
        fail('ERR_INVALID_STATE', 409, 'Referral is not NEEDS_INFO')
    if diagnosis_code is not None:
        r['diagnosis_code'] = diagnosis_code
    if urgency is not None:
        r['urgency'] = urgency
    if in_network_pref is not None:
        r['in_network_preference'] = in_network_pref
    if plan_id is not None:
        r['insurance_plan_id'] = plan_id
    r['status'] = 'PENDING_TRIAGE'
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/reject')
def reject_referral(rid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    f_str(body, 'reason')
    r = get_referral_or_404(rid)
    if r['status'] != 'PENDING_TRIAGE':
        fail('ERR_INVALID_STATE', 409, 'Referral is not PENDING_TRIAGE')
    r['status'] = 'REJECTED'
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/accept')
def accept_referral(rid):
    authenticate(['ReferralCoordinator'])
    r = get_referral_or_404(rid)
    if r['status'] != 'PENDING_TRIAGE':
        fail('ERR_INVALID_STATE', 409, 'Referral is not PENDING_TRIAGE')
    ts = now()
    r['triaged_at'] = ts
    r['sla_due_at'] = ts + timedelta(days=SLA_DAYS[r['urgency']])
    rule = matching_auth_rule(r['specialty'], r['insurance_plan_id'])
    r['auth_status'] = 'AUTH_REQUIRED' if (rule and rule['requires_auth']) else 'NOT_REQUIRED'
    r['status'] = 'ACCEPTED'
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/auto-match')
def auto_match(rid):
    authenticate(['ReferralCoordinator'])
    r = get_referral_or_404(rid)
    patient = store.patients.get(r['patient_id'])
    pool = []
    for s in store.specialists.values():
        if s['specialty'] != r['specialty']:
            continue
        if s['status'] != 'ACTIVE':
            continue
        if not s['accepts_new_patients']:
            continue
        if r['urgency'] == 'STAT' and not s['accepts_urgent']:
            continue
        part = active_participation(s['id'], r['insurance_plan_id'])
        if part is None:
            continue
        score = 50
        score += 25 if part['tier'] == 'PREFERRED' else 10
        # utilization >= 0.8 as an exact rational comparison (inclusive)
        if specialist_booked_count(s['id']) * 5 >= s['weekly_capacity'] * 4:
            score -= 15
        score += 20 if r['urgency'] == 'STAT' else (10 if r['urgency'] == 'URGENT' else 0)
        if patient is not None and s['base_region'] == patient['region']:
            score += 5
        score = min(100, max(0, score))
        pool.append((s, score))
    if not pool:
        fail('ERR_NO_ELIGIBLE_SPECIALIST', 422, 'No eligible specialist in the pool')
    pool.sort(key=lambda t: (-t[1], t[0]['created_at'], t[0]['seq']))
    winner, score = pool[0]
    r['target_specialist_id'] = winner['id']
    r['match_score'] = score
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/assign-specialist')
def assign_specialist(rid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    specialist_id = f_str(body, 'specialist_id')
    r = get_referral_or_404(rid)
    s = store.specialists.get(specialist_id)
    if not s:
        fail('ERR_SPECIALIST_NOT_FOUND', 404, 'Specialist not found')
    if (s['status'] != 'ACTIVE' or not s['accepts_new_patients']
            or s['specialty'] != r['specialty']):
        fail('ERR_SPECIALTY_MISMATCH', 422,
             'Specialist is inactive, not accepting, or specialty differs')
    r['target_specialist_id'] = s['id']
    r['match_score'] = None
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/document-patient-choice')
def document_patient_choice(rid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    choice_type = f_enum(body, 'choice_type', CHOICE_TYPES)
    note = f_str(body, 'note')
    r = get_referral_or_404(rid)
    if r['status'] != 'ACCEPTED':
        fail('ERR_INVALID_STATE', 409, 'Patient choice may only be documented while ACCEPTED')
    r['patient_choice_documented'] = True
    r['patient_choice_type'] = choice_type
    r['patient_choice_note'] = note
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/cancel')
def cancel_referral(rid):
    uid, role = authenticate(['ReferringProvider', 'ReferralCoordinator'])
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    body = get_body()
    reason = f_enum(body, 'reason', CANCEL_REASONS)
    if r['status'] not in ('PENDING_TRIAGE', 'NEEDS_INFO', 'ACCEPTED', 'SCHEDULED',
                           'VISIT_COMPLETED', 'PENDING_VERIFICATION'):
        fail('ERR_INVALID_STATE', 409, 'Referral is in a terminal state')
    r['cancel_reason'] = reason
    r['status'] = 'CANCELLED'
    for a in active_appointments_of_referral(r['id']):
        cascade_cancel_appointment(a)
    if reason == 'PATIENT_WENT_OUT_OF_NETWORK' and not referral_leaked(r['id']):
        create_leakage_record(r, 'PATIENT_CHOICE_OUT_OF_NETWORK')
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/auth/submit')
def auth_submit(rid):
    authenticate(['ReferralCoordinator'])
    r = get_referral_or_404(rid)
    if (r['auth_status'] not in ('AUTH_REQUIRED', 'AUTH_DENIED', 'AUTH_EXPIRED')
            or r['status'] not in ('ACCEPTED', 'SCHEDULED')):
        fail('ERR_INVALID_STATE', 409,
             'Auth submit requires auth_status in {AUTH_REQUIRED, AUTH_DENIED, '
             'AUTH_EXPIRED} and status in {ACCEPTED, SCHEDULED}')
    r['auth_status'] = 'AUTH_PENDING'
    bump(r)
    return success_object(ser_referral(r))


@app.post('/referrals/<rid>/auth/record-outcome')
def auth_record_outcome(rid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    outcome = f_enum(body, 'outcome', AUTH_OUTCOMES)
    auth_number = None
    if outcome == 'OBTAINED':
        auth_number = body.get('auth_number')
        if not isinstance(auth_number, str) or auth_number == '':
            fail('ERR_INVALID_REQUEST', 400,
                 'auth_number is required and must be non-empty when outcome is OBTAINED')
    r = get_referral_or_404(rid)
    if r['auth_status'] != 'AUTH_PENDING':
        fail('ERR_INVALID_STATE', 409, 'Referral auth_status is not AUTH_PENDING')
    if outcome == 'OBTAINED':
        rule = matching_auth_rule(r['specialty'], r['insurance_plan_id'])
        if rule is None:
            candidates = [x for x in store.auth_rules.values()
                          if x['specialty'] == r['specialty']
                          and x['insurance_plan_id'] == r['insurance_plan_id']]
            rule = max(candidates, key=lambda x: x['seq']) if candidates else None
        days = rule['auth_validity_days'] if rule else 1
        obtained = now()
        rec = scaffold_record()
        rec.update({
            'referral_id': r['id'],
            'auth_number': auth_number,
            'obtained_at': obtained,
            'expires_on': obtained + timedelta(days=days),
            'status': 'ACTIVE',
        })
        store.auth_records[rec['id']] = rec
        r['auth_status'] = 'AUTH_OBTAINED'
    else:
        r['auth_status'] = 'AUTH_DENIED'
    bump(r)
    return success_object(ser_referral(r))


# ---------------------------------------------------------------- booking
@app.post('/referrals/<rid>/appointments')
def book_appointment(rid):
    uid, role = authenticate(['ReferralCoordinator'])
    body = get_body()
    expected_version = f_int(body, 'expected_referral_version')
    start = f_datetime(body, 'scheduled_start')
    end = f_datetime(body, 'scheduled_end')
    payload_specialist_id = f_str(body, 'specialist_id', required=False)
    r = get_referral_or_404(rid)
    payload_specialist = None
    if payload_specialist_id is not None:
        payload_specialist = store.specialists.get(payload_specialist_id)
        if payload_specialist is None:
            fail('ERR_SPECIALIST_NOT_FOUND', 404, 'Specialist not found')
    # OCC (priority 6): after existence, before any state or business rule
    if expected_version != r['version']:
        fail('ERR_STALE_VERSION', 412,
             'expected_referral_version does not match current referral version')
    # state preconditions
    if r['status'] not in ('ACCEPTED', 'SCHEDULED'):
        fail('ERR_INVALID_STATE', 409,
             'Booking requires referral status ACCEPTED or SCHEDULED')
    if r['auth_status'] == 'NOT_REQUIRED':
        pass
    elif r['auth_status'] == 'AUTH_OBTAINED':
        rec = latest_auth_record(r['id'])
        if rec is None or rec['status'] != 'ACTIVE':
            fail('ERR_AUTH_NOT_SATISFIED', 409, 'Authorization record is not ACTIVE')
    else:
        fail('ERR_AUTH_NOT_SATISFIED', 409,
             'Referral authorization status does not permit booking')
    # effective specialist validity
    if payload_specialist is not None:
        s = payload_specialist
    elif r['target_specialist_id'] is not None:
        s = store.specialists.get(r['target_specialist_id'])
    else:
        s = None
    if s is None:
        fail('ERR_SPECIALIST_NOT_FOUND', 404, 'No effective specialist for booking')
    if (s['status'] != 'ACTIVE' or not s['accepts_new_patients']
            or s['specialty'] != r['specialty']):
        fail('ERR_SPECIALTY_MISMATCH', 422,
             'Specialist is inactive, not accepting, or specialty differs')
    if (r['target_specialist_id'] is not None and payload_specialist_id is not None
            and payload_specialist_id != r['target_specialist_id']):
        fail('ERR_TARGET_MISMATCH', 422,
             'Payload specialist differs from the referral target specialist')
    # participation gate
    oon_bypass = False
    if active_participation(s['id'], r['insurance_plan_id']) is None:
        if (r['patient_choice_documented']
                and r['patient_choice_type'] in ('OUT_OF_NETWORK_PATIENT_REQUEST',
                                                 'OUT_OF_NETWORK_CAPACITY')):
            oon_bypass = True
        else:
            fail('ERR_NO_ACTIVE_PARTICIPATION', 409,
                 'No ACTIVE participation and no documented out-of-network choice')
    # window shape
    if end <= start:
        fail('ERR_INVALID_WINDOW', 400, 'scheduled_end must be after scheduled_start')
    if start < now():
        fail('ERR_INVALID_WINDOW', 400, 'scheduled_start must not be in the past')
    # overlap: half-open [start, end + 15m) against other specialists' active
    # appointments; appointments of this same referral are superseded by this
    # booking and therefore excluded.
    new_lo, new_hi = start, end + BUFFER
    for a in store.appointments.values():
        if (a['specialist_id'] != s['id'] or a['status'] not in ACTIVE_APPT
                or a['referral_id'] == r['id']):
            continue
        ex_lo, ex_hi = a['scheduled_start'], a['scheduled_end'] + BUFFER
        if new_lo < ex_hi and ex_lo < new_hi:
            fail('ERR_APPOINTMENT_OVERLAP', 409,
                 'Appointment overlaps an existing booking for this specialist')
    # side effects (atomic)
    for a in active_appointments_of_referral(r['id']):
        cascade_cancel_appointment(a, superseded=True)
    appt = scaffold_record()
    appt.update({
        'referral_id': r['id'],
        'specialist_id': s['id'],
        'scheduled_start': start,
        'scheduled_end': end,
        'status': 'SCHEDULED',
        'confirmation_channel': None,
        'confirmed_at': None,
        'completed_at': None,
        'superseded': False,
        'excuse_reason': '',
        'scheduled_by_user_id': uid,
    })
    store.appointments[appt['id']] = appt
    r['status'] = 'SCHEDULED'
    r['ever_scheduled'] = True
    if oon_bypass:
        r['out_of_network'] = True
        category = ('PATIENT_CHOICE_OUT_OF_NETWORK'
                    if r['patient_choice_type'] == 'OUT_OF_NETWORK_PATIENT_REQUEST'
                    else 'CAPACITY_OUT_OF_NETWORK')
        create_leakage_record(r, category)
    bump(r)
    return success_object(ser_appointment(appt), 201)


# ---------------------------------------------------------------- referral sub-resources
@app.get('/referrals/<rid>/appointments')
def referral_appointments(rid):
    uid, role = authenticate(READERS)
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    items = sorted([a for a in store.appointments.values() if a['referral_id'] == rid],
                   key=by_creation)
    st = request.args.get('status')
    if st is not None:
        items = [a for a in items if a['status'] == st]
    page, limit, offset, total = paginate(items)
    return success_list([ser_appointment(a) for a in page], limit, offset, total)


@app.get('/referrals/<rid>/authorization-records')
def referral_auth_records(rid):
    uid, role = authenticate(READERS)
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    items = sorted([a for a in store.auth_records.values() if a['referral_id'] == rid],
                   key=by_creation)
    page, limit, offset, total = paginate(items)
    return success_list([ser_auth_record(a) for a in page], limit, offset, total)


@app.get('/referrals/<rid>/consult-notes')
def referral_consult_notes(rid):
    uid, role = authenticate(READERS)
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    items = sorted([n for n in store.consult_notes.values() if n['referral_id'] == rid],
                   key=lambda n: (n['note_sequence'], n['seq']))
    page, limit, offset, total = paginate(items)
    return success_list([ser_consult_note(n) for n in page], limit, offset, total)


@app.get('/referrals/<rid>/loop-closures')
def referral_loop_closures(rid):
    uid, role = authenticate(READERS)
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    items = sorted([c for c in store.loop_closures.values() if c['referral_id'] == rid],
                   key=by_creation)
    page, limit, offset, total = paginate(items)
    return success_list([ser_loop_closure(c) for c in page], limit, offset, total)


@app.get('/referrals/<rid>/leakage-records')
def referral_leakage_records(rid):
    uid, role = authenticate(['NetworkAdmin', 'ReferralCoordinator',
                              'ComplianceAuditor', 'ReferringProvider'])
    r = get_referral_or_404(rid)
    check_referral_ownership(r, uid, role)
    items = sorted([l for l in store.leakage_records.values() if l['referral_id'] == rid],
                   key=by_creation)
    page, limit, offset, total = paginate(items)
    return success_list([ser_leakage_record(l) for l in page], limit, offset, total)


@app.post('/referrals/<rid>/loop-closures')
def create_loop_closure(rid):
    uid, role = authenticate(['ComplianceAuditor'])
    body = get_body()
    expected_version = f_int(body, 'expected_referral_version')
    outcome = f_enum(body, 'outcome', CLOSURE_OUTCOMES)
    note = f_str(body, 'verification_note')
    r = get_referral_or_404(rid)
    if expected_version != r['version']:
        fail('ERR_STALE_VERSION', 412,
             'expected_referral_version does not match current referral version')
    if r['status'] != 'PENDING_VERIFICATION':
        fail('ERR_INVALID_STATE', 409, 'Referral is not PENDING_VERIFICATION')
    completed = [a for a in store.appointments.values()
                 if a['referral_id'] == rid and a['status'] == 'COMPLETED']
    if completed:
        latest = max(completed, key=lambda a: (a['completed_at'], a['seq']))
        if latest['scheduled_by_user_id'] == uid:
            fail('ERR_SOD_CONFLICT', 403,
                 'Verifier may not be the user who scheduled the latest completed appointment')
    rec = {
        'id': new_id(),
        'created_at': now(),
        'seq': next_seq(),
        'referral_id': rid,
        'outcome': outcome,
        'verification_note': note,
        'verifier_user_id': uid,
    }
    store.loop_closures[rec['id']] = rec
    r['status'] = 'CLOSED' if outcome == 'VERIFIED_CLOSED' else 'VISIT_COMPLETED'
    bump(r)
    return success_object(ser_loop_closure(rec), 201)


@app.post('/referrals/aging-sweep')
def aging_sweep():
    authenticate(['ReferralCoordinator'])
    expired_referral_ids = []
    for r in sorted(store.referrals.values(), key=by_creation):
        if (r['status'] in ('ACCEPTED', 'SCHEDULED', 'VISIT_COMPLETED',
                            'PENDING_VERIFICATION')
                and r['sla_due_at'] is not None and now() >= r['sla_due_at']):
            r['status'] = 'EXPIRED'
            create_leakage_record(r, 'EXPIRED_UNRESOLVED')
            for a in active_appointments_of_referral(r['id']):
                cascade_cancel_appointment(a)
            bump(r)
            expired_referral_ids.append(r['id'])
    expired_auth_ids = []
    for r in sorted(store.referrals.values(), key=by_creation):
        if r['auth_status'] == 'AUTH_OBTAINED' and r['status'] in ('ACCEPTED', 'SCHEDULED'):
            rec = latest_auth_record(r['id'])
            if rec is not None and rec['status'] == 'ACTIVE' and now() >= rec['expires_on']:
                rec['status'] = 'EXPIRED'
                bump(rec)
                r['auth_status'] = 'AUTH_EXPIRED'
                bump(r)
                expired_auth_ids.append(rec['id'])
    return success_object({
        'expired_referral_ids': expired_referral_ids,
        'expired_count': len(expired_referral_ids),
        'expired_auth_record_ids': expired_auth_ids,
    })


# ---------------------------------------------------------------- appointments
def get_appointment_or_404(aid):
    a = store.appointments.get(aid)
    if not a:
        fail('ERR_APPOINTMENT_NOT_FOUND', 404, 'Appointment not found')
    return a


def maybe_revert_referral_to_accepted(rid):
    """System transition SCHEDULED -> ACCEPTED when no active appointment
    of the referral remains."""
    r = store.referrals.get(rid)
    if r is not None and r['status'] == 'SCHEDULED' and not active_appointments_of_referral(rid):
        r['status'] = 'ACCEPTED'
        bump(r)


def set_escalation_for_patient(pid, value):
    for r in store.referrals.values():
        if r['patient_id'] != pid:
            continue
        if value and r['status'] in ('ACCEPTED', 'SCHEDULED'):
            r['escalation_flag'] = True
        elif not value and r['escalation_flag']:
            r['escalation_flag'] = False


@app.get('/appointments/<aid>')
def get_appointment(aid):
    authenticate(READERS)
    return success_object(ser_appointment(get_appointment_or_404(aid)))


@app.post('/appointments/<aid>/confirm')
def confirm_appointment(aid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    channel = f_enum(body, 'confirmation_channel', CONFIRM_CHANNELS)
    a = get_appointment_or_404(aid)
    if a['status'] != 'SCHEDULED':
        fail('ERR_INVALID_STATE', 409, 'Appointment is not SCHEDULED')
    a['confirmation_channel'] = channel
    a['confirmed_at'] = now()
    a['status'] = 'CONFIRMED'
    bump(a)
    return success_object(ser_appointment(a))


@app.post('/appointments/<aid>/complete')
def complete_appointment(aid):
    uid, role = authenticate(['SpecialistProvider'])
    a = get_appointment_or_404(aid)
    if a['specialist_id'] != uid:
        fail('ERR_OWNERSHIP_VIOLATION', 403,
             'Only the owning specialist may complete this appointment')
    if a['status'] != 'CONFIRMED':
        fail('ERR_NOT_CONFIRMED', 409, 'Appointment is not CONFIRMED')
    if now() < a['scheduled_start']:
        fail('ERR_COMPLETE_TOO_EARLY', 422,
             'Appointment cannot be completed before its scheduled start')
    a['completed_at'] = now()
    a['status'] = 'COMPLETED'
    bump(a)
    r = store.referrals.get(a['referral_id'])
    if r is not None and r['status'] == 'SCHEDULED':
        r['status'] = 'VISIT_COMPLETED'
        if r['auth_status'] == 'AUTH_OBTAINED':
            rec = latest_auth_record(r['id'])
            if rec is not None and rec['status'] == 'ACTIVE':
                rec['status'] = 'CONSUMED'
                bump(rec)
        bump(r)
    return success_object(ser_appointment(a))


@app.post('/appointments/<aid>/mark-no-show')
def mark_no_show(aid):
    authenticate(['ReferralCoordinator'])
    a = get_appointment_or_404(aid)
    if a['status'] not in ACTIVE_APPT:
        fail('ERR_INVALID_STATE', 409, 'Appointment is not active')
    if now() < a['scheduled_start'] + GRACE:
        fail('ERR_NO_SHOW_TOO_EARLY', 422,
             'No-show may only be marked at or after scheduled start plus 15 minutes')
    r = store.referrals.get(a['referral_id'])
    pid = r['patient_id'] if r else None
    old_strikes = patient_strikes(pid) if pid else 0
    a['status'] = 'NO_SHOW'
    bump(a)
    if pid:
        new_strikes = patient_strikes(pid)
        if old_strikes < 3 <= new_strikes:
            set_escalation_for_patient(pid, True)
    maybe_revert_referral_to_accepted(a['referral_id'])
    return success_object(ser_appointment(a))


@app.post('/appointments/<aid>/excuse')
def excuse_appointment(aid):
    authenticate(['ReferralCoordinator'])
    body = get_body()
    reason = f_str(body, 'reason')
    a = get_appointment_or_404(aid)
    if a['status'] != 'NO_SHOW':
        fail('ERR_INVALID_STATE', 409, 'Appointment is not NO_SHOW')
    r = store.referrals.get(a['referral_id'])
    pid = r['patient_id'] if r else None
    old_strikes = patient_strikes(pid) if pid else 0
    a['excuse_reason'] = reason
    a['status'] = 'EXCUSED'
    bump(a)
    if pid:
        new_strikes = patient_strikes(pid)
        if old_strikes >= 3 > new_strikes:
            set_escalation_for_patient(pid, False)
    return success_object(ser_appointment(a))


@app.post('/appointments/<aid>/cancel')
def cancel_appointment(aid):
    authenticate(['ReferralCoordinator'])
    a = get_appointment_or_404(aid)
    if a['status'] not in ACTIVE_APPT:
        fail('ERR_INVALID_STATE', 409, 'Appointment is not active')
    a['status'] = 'CANCELLED'
    bump(a)
    maybe_revert_referral_to_accepted(a['referral_id'])
    return success_object(ser_appointment(a))


@app.post('/appointments/<aid>/consult-note')
def create_consult_note(aid):
    uid, role = authenticate(['SpecialistProvider'])
    a = get_appointment_or_404(aid)
    if a['specialist_id'] != uid:
        fail('ERR_OWNERSHIP_VIOLATION', 403,
             'Only the owning specialist may submit a consult note')
    body = get_body()
    findings = f_str(body, 'findings_summary')
    follow_up = f_bool(body, 'follow_up_recommended')
    if a['status'] != 'COMPLETED':
        fail('ERR_INVALID_STATE', 409, 'Appointment is not COMPLETED')
    r = store.referrals.get(a['referral_id'])
    if r is None or r['status'] != 'VISIT_COMPLETED':
        fail('ERR_INVALID_STATE', 409, 'Referral is not VISIT_COMPLETED')
    prior = sum(1 for n in store.consult_notes.values() if n['referral_id'] == r['id'])
    created = now()
    rec = {
        'id': new_id(),
        'created_at': created,
        'seq': next_seq(),
        'referral_id': r['id'],
        'appointment_id': a['id'],
        'author_specialist_id': uid,
        'findings_summary': findings,
        'follow_up_recommended': follow_up,
        'note_sequence': prior + 1,
        'returned_within_sla': created <= a['completed_at'] + timedelta(days=14),
    }
    store.consult_notes[rec['id']] = rec
    r['status'] = 'PENDING_VERIFICATION'
    bump(r)
    return success_object(ser_consult_note(rec), 201)


@app.get('/appointments/<aid>/consult-notes')
def appointment_consult_notes(aid):
    authenticate(READERS)
    get_appointment_or_404(aid)
    items = sorted([n for n in store.consult_notes.values() if n['appointment_id'] == aid],
                   key=lambda n: (n['note_sequence'], n['seq']))
    page, limit, offset, total = paginate(items)
    return success_list([ser_consult_note(n) for n in page], limit, offset, total)


# ---------------------------------------------------------------- consult notes
@app.get('/consult-notes')
def list_consult_notes():
    authenticate(['NetworkAdmin', 'ReferralCoordinator', 'ComplianceAuditor'])
    items = sorted(store.consult_notes.values(), key=by_creation)
    author = request.args.get('author_specialist_id')
    if author is not None:
        items = [n for n in items if n['author_specialist_id'] == author]
    ref = request.args.get('referral_id')
    if ref is not None:
        items = [n for n in items if n['referral_id'] == ref]
    page, limit, offset, total = paginate(items)
    return success_list([ser_consult_note(n) for n in page], limit, offset, total)


@app.get('/consult-notes/<nid>')
def get_consult_note(nid):
    authenticate(READERS)
    n = store.consult_notes.get(nid)
    if not n:
        fail('ERR_CONSULT_NOTE_NOT_FOUND', 404, 'Consult note not found')
    return success_object(ser_consult_note(n))


# ---------------------------------------------------------------- analytics
@app.post('/analytics/periods/close')
def close_period():
    authenticate(['NetworkAdmin'])
    body = get_body()
    period_start = f_date(body, 'period_start')
    period_end = f_date(body, 'period_end')
    if not period_end > period_start:
        fail('ERR_INVALID_PERIOD', 400, 'period_end must be after period_start')
    if now().date() < period_end:
        fail('ERR_PERIOD_NOT_ENDED', 409, 'The period has not ended yet')
    if any(s['period_start'] == period_start and s['period_end'] == period_end
           for s in store.snapshots.values()):
        fail('ERR_PERIOD_ALREADY_CLOSED', 409, 'Period already closed')
    start_dt = datetime.combine(period_start, dtime.min, tzinfo=timezone.utc)
    end_dt = datetime.combine(period_end, dtime.min, tzinfo=timezone.utc)
    snap_ids = []
    for p in sorted(store.referring_providers.values(), key=by_creation):
        intake = provider_intake_set(p['id'], start_dt, end_dt)
        if not intake:
            continue
        completed = [r for r in intake if referral_completed(r['id'])]
        scheduled_basis = [r for r in intake if r['ever_scheduled']]
        leaked = [r for r in intake if referral_leaked(r['id'])]
        snap = {
            'id': new_id(),
            'created_at': now(),
            'seq': next_seq(),
            'referring_provider_id': p['id'],
            'period_start': period_start,
            'period_end': period_end,
            'intake_count': len(intake),
            'completed_count': len(completed),
            'scheduled_basis_count': len(scheduled_basis),
            'leaked_count': len(leaked),
            'conversion_rate_intake': rate4(len(completed), len(intake)),
            'conversion_rate_scheduled': rate4(len(completed), len(scheduled_basis)),
            'leakage_rate': rate4(len(leaked), len(intake)),
            'estimated_leakage_exposure_cents': exposure_of({r['id'] for r in leaked}),
            'closed_at': now(),
        }
        store.snapshots[snap['id']] = snap
        snap_ids.append(snap['id'])
    return success_object({'snapshot_count': len(snap_ids), 'snapshot_ids': snap_ids}, 201)


@app.get('/analytics/snapshots')
def list_snapshots():
    uid, role = authenticate(['NetworkAdmin', 'ReferralCoordinator',
                              'ComplianceAuditor', 'ReferringProvider'])
    items = sorted(store.snapshots.values(), key=by_creation)
    if role == 'ReferringProvider':
        param = request.args.get('referring_provider_id')
        if param is not None and param != uid:
            fail('ERR_OWNERSHIP_VIOLATION', 403,
                 'Referring providers may only read their own snapshots')
        items = [s for s in items if s['referring_provider_id'] == uid]
    else:
        param = request.args.get('referring_provider_id')
        if param is not None:
            items = [s for s in items if s['referring_provider_id'] == param]
    ps = request.args.get('period_start')
    if ps is not None:
        d = parse_date_value(ps)
        items = [s for s in items if d is not None and s['period_start'] == d]
    pe = request.args.get('period_end')
    if pe is not None:
        d = parse_date_value(pe)
        items = [s for s in items if d is not None and s['period_end'] == d]
    page, limit, offset, total = paginate(items)
    return success_list([ser_snapshot(s) for s in page], limit, offset, total)


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', '10000')))
