"""Pet Adoption & Boarding Platform API."""
import os
import threading
import uuid
import random
import string
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

from flask import Flask, request, jsonify
from dateutil import parser as dateparser

app = Flask(__name__)
LOCK = threading.RLock()

# ----------------------------- Storage ----------------------------------------

shelters = {}
animals = {}
vaccinations = {}  # id -> record
adopters = {}
home_visits = {}
applications = {}
reservations = {}
settlements = {}
incidents = []

# ----------------------------- Constants --------------------------------------

SENIOR_AGE_MONTHS = 96
SENIOR_DISCOUNT = Decimal('0.5')
PEAK_UTILIZATION = Decimal('0.8')
PEAK_SURCHARGE = Decimal('0.10')
EARLY_CHECKIN_GRACE_HOURS = 24
HOME_VISIT_VALIDITY_DAYS = 180

VALID_ROLES = {
    'ShelterAdmin', 'Veterinarian', 'AdoptionReviewer', 'AdoptionApprover',
    'HomeVisitInspector', 'BoardingCoordinator', 'FinanceOfficer', 'Adopter',
}

SPECIES_VACCINES = {
    'DOG': ['RABIES', 'DISTEMPER', 'PARVO', 'BORDETELLA'],
    'CAT': ['RABIES', 'DISTEMPER', 'FELV'],
    'RABBIT': ['RABIES'],
    'OTHER': ['RABIES'],
}

VALID_SPECIES = set(SPECIES_VACCINES.keys())
VALID_VACCINE_TYPES = {'RABIES', 'DISTEMPER', 'PARVO', 'BORDETELLA', 'FELV'}
VALID_SPECIAL_CARE = {'NONE', 'MEDICAL', 'BEHAVIORAL'}
VALID_PAYMENT_METHODS = {'CARD', 'BANK_TRANSFER', 'CASH'}
VALID_SUBJECT_TYPES = {'ADOPTION', 'BOARDING'}

# ----------------------------- Utilities --------------------------------------

def now_utc():
    return datetime.now(timezone.utc)


def iso_ts(dt=None):
    dt = dt or now_utc()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{dt.microsecond // 1000:03d}' + 'Z'


def request_id():
    return 'req_petpaw_' + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))


def make_meta(extra=None):
    m = {
        'api_request_id': request_id(),
        'api_request_timestamp': iso_ts(),
    }
    if extra:
        m.update(extra)
    return m


def ok_single(obj, status=200):
    return jsonify({'meta': make_meta(), 'response_type': 'object', 'data': obj}), status


def ok_list(data, limit, offset, total):
    meta = make_meta({
        'limit': limit, 'offset': offset,
        'total_count': total, 'has_more': offset + limit < total,
    })
    return jsonify({'meta': meta, 'response_type': 'array', 'data': data}), 200


ERROR_STATUS = {
    'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER': 400,
    'ERR_INSUFFICIENT_PERMISSIONS': 403,
    'ERR_INVALID_REQUEST': 400,
    'ERR_INVALID_SCORE': 400,
    'ERR_VERSION_CONFLICT': 409,
    'ERR_SHELTER_NOT_FOUND': 404,
    'ERR_ANIMAL_NOT_FOUND': 404,
    'ERR_ADOPTER_NOT_FOUND': 404,
    'ERR_APPLICATION_NOT_FOUND': 404,
    'ERR_HOME_VISIT_NOT_FOUND': 404,
    'ERR_RESERVATION_NOT_FOUND': 404,
    'ERR_SETTLEMENT_NOT_FOUND': 404,
    'ERR_INVALID_STATE': 409,
    'ERR_SEGREGATION_OF_DUTIES': 403,
    'ERR_HOME_VISIT_REQUIRED': 409,
    'ERR_HOME_VISIT_FAILED': 409,
    'ERR_VACCINATION_NON_COMPLIANT': 409,
    'ERR_ADOPTER_DISQUALIFIED': 409,
    'ERR_ANIMAL_UNAVAILABLE': 409,
    'ERR_ANIMAL_ALREADY_RESERVED': 409,
    'ERR_ANIMAL_NOT_BOARDABLE': 409,
    'ERR_SHELTER_AT_CAPACITY': 409,
    'ERR_TOO_EARLY_FOR_CHECKIN': 409,
    'ERR_AMOUNT_MISMATCH': 409,
    'ERR_DUPLICATE_SETTLEMENT': 409,
    'ERR_FEE_NOT_SETTLED': 409,
    'ERR_FEE_REFUNDED': 409,
    'ERR_STALE_PINNED_REFERENCE': 409,
    'ERR_ANIMAL_ADOPTED': 409,
}

ERROR_MESSAGES = {
    'ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER': 'Missing or invalid X-User-ID / X-User-Role header.',
    'ERR_INSUFFICIENT_PERMISSIONS': 'Caller role is not entitled to this operation.',
    'ERR_INVALID_REQUEST': 'Request is malformed or missing required fields.',
    'ERR_INVALID_SCORE': 'safety_score must be within the [0..100] band.',
    'ERR_VERSION_CONFLICT': 'Supplied version does not match the live row version.',
    'ERR_SHELTER_NOT_FOUND': 'Shelter not found.',
    'ERR_ANIMAL_NOT_FOUND': 'Animal not found.',
    'ERR_ADOPTER_NOT_FOUND': 'Adopter not found.',
    'ERR_APPLICATION_NOT_FOUND': 'Adoption application not found.',
    'ERR_HOME_VISIT_NOT_FOUND': 'Home visit not found.',
    'ERR_RESERVATION_NOT_FOUND': 'Boarding reservation not found.',
    'ERR_SETTLEMENT_NOT_FOUND': 'Fee settlement not found.',
    'ERR_INVALID_STATE': 'Resource is not in a state that permits this transition.',
    'ERR_SEGREGATION_OF_DUTIES': 'Reviewer and approver must be different individuals.',
    'ERR_HOME_VISIT_REQUIRED': 'A passed, unexpired home visit is required.',
    'ERR_HOME_VISIT_FAILED': 'Home visit failed.',
    'ERR_VACCINATION_NON_COMPLIANT': 'Animal vaccination set is not compliant.',
    'ERR_ADOPTER_DISQUALIFIED': 'Adopter is disqualified.',
    'ERR_ANIMAL_UNAVAILABLE': 'Animal is not available for adoption.',
    'ERR_ANIMAL_ALREADY_RESERVED': 'Another approved adoption application already holds this animal.',
    'ERR_ANIMAL_NOT_BOARDABLE': 'Animal cannot be boarded in its current status.',
    'ERR_SHELTER_AT_CAPACITY': 'Shelter has no available boarding slots.',
    'ERR_TOO_EARLY_FOR_CHECKIN': 'Too early to check in for this reservation.',
    'ERR_AMOUNT_MISMATCH': 'Settlement amount does not match the authoritative figure.',
    'ERR_DUPLICATE_SETTLEMENT': 'A completed settlement already exists for this subject.',
    'ERR_FEE_NOT_SETTLED': 'Required fee settlement is not yet completed.',
    'ERR_FEE_REFUNDED': 'Fee was refunded for this application.',
    'ERR_STALE_PINNED_REFERENCE': 'Pinned animal version no longer matches the live row.',
    'ERR_ANIMAL_ADOPTED': 'Animal has been adopted.',
}


def err(code, message=None):
    msg = message or ERROR_MESSAGES.get(code, code)
    return jsonify({'meta': make_meta(), 'response_type': 'error',
                    'data': {'error_id': code, 'message': msg}}), ERROR_STATUS[code]


def new_id():
    return str(uuid.uuid4())


def parse_dt(s):
    try:
        dt = dateparser.isoparse(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def parse_date_or_dt(s):
    """Parse either a date (YYYY-MM-DD) or an ISO datetime; always return a UTC datetime."""
    if not isinstance(s, str):
        return None
    dt = parse_dt(s)
    return dt


def check_headers():
    uid = request.headers.get('X-User-ID', '')
    role = request.headers.get('X-User-Role', '')
    if uid is None or role is None:
        return None, None, err('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER')
    uid = uid.strip()
    role = role.strip()
    if not uid or not role or role not in VALID_ROLES:
        return None, None, err('ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER')
    return uid, role, None


def require_role(allowed):
    """Returns (uid, role, error_response). allowed can be 'Any' to mean any valid role."""
    uid, role, e = check_headers()
    if e is not None:
        return None, None, e
    if allowed == 'Any' or (isinstance(allowed, (list, tuple, set)) and 'Any' in allowed):
        return uid, role, None
    if isinstance(allowed, str):
        allowed = [allowed]
    if role not in allowed:
        return None, None, err('ERR_INSUFFICIENT_PERMISSIONS')
    return uid, role, None


def parse_limit_offset():
    try:
        limit = int(request.args.get('limit', 50))
        offset = int(request.args.get('offset', 0))
    except Exception:
        return None, None, err('ERR_INVALID_REQUEST')
    if limit < 1 or limit > 200 or offset < 0:
        return None, None, err('ERR_INVALID_REQUEST')
    return limit, offset, None


def paginate(items, limit, offset):
    items_sorted = sorted(items, key=lambda x: (x.get('created_at') or '', x.get('id') or ''))
    total = len(items_sorted)
    page = items_sorted[offset:offset + limit]
    return page, total


def bump(resource):
    resource['updated_at'] = iso_ts()
    resource['version'] = resource.get('version', 0) + 1


# ----------------------------- Serializers ------------------------------------

def serialize_shelter(s):
    reserved = compute_reserved_slots(s['id'])
    avail = max(0, s['boarding_capacity'] - reserved)
    return {
        'id': s['id'],
        'name': s['name'],
        'boarding_capacity': s['boarding_capacity'],
        'adoption_fee_base': s['adoption_fee_base'],
        'boarding_rate_per_night': s['boarding_rate_per_night'],
        'status': s['status'],
        'reserved_slots': reserved,
        'available_slots': avail,
        'version': s['version'],
        'created_at': s['created_at'],
        'updated_at': s['updated_at'],
    }


def serialize_animal(a):
    return {
        'id': a['id'],
        'shelter_id': a['shelter_id'],
        'name': a['name'],
        'species': a['species'],
        'age_months': a['age_months'],
        'temperament_tags': list(a.get('temperament_tags', [])),
        'adoption_fee_override': a.get('adoption_fee_override'),
        'special_care_level': a.get('special_care_level', 'NONE'),
        'status': a['status'],
        'intake_date': a['intake_date'],
        'version': a['version'],
        'created_at': a['created_at'],
        'updated_at': a['updated_at'],
    }


def serialize_vaccination(v):
    return {
        'id': v['id'],
        'animal_id': v['animal_id'],
        'vaccine_type': v['vaccine_type'],
        'administered_date': v['administered_date'],
        'expires_date': v['expires_date'],
        'lot_number': v['lot_number'],
        'created_at': v['created_at'],
    }


def serialize_adopter(a):
    # Derive effective home_visit_status
    status = a['home_visit_status']
    expires_at = a.get('home_visit_expires_at')
    if status == 'PASSED' and expires_at:
        exp_dt = parse_dt(expires_at)
        if exp_dt and exp_dt <= now_utc():
            status = 'EXPIRED'
    return {
        'id': a['id'],
        'full_name': a['full_name'],
        'household_size': a['household_size'],
        'has_yard': a['has_yard'],
        'home_visit_status': status,
        'home_visit_expires_at': expires_at,
        'disqualified': a['disqualified'],
        'version': a['version'],
        'created_at': a['created_at'],
        'updated_at': a['updated_at'],
    }


def serialize_home_visit(h):
    return {
        'id': h['id'],
        'adopter_id': h['adopter_id'],
        'scheduled_for': h['scheduled_for'],
        'inspector_id': h['inspector_id'],
        'safety_score': h.get('safety_score'),
        'yard_verified': h.get('yard_verified'),
        'status': h['status'],
        'completed_at': h.get('completed_at'),
        'version': h['version'],
        'created_at': h['created_at'],
        'updated_at': h['updated_at'],
    }


def serialize_application(a):
    return {
        'id': a['id'],
        'adopter_id': a['adopter_id'],
        'animal_id': a['animal_id'],
        'shelter_id': a['shelter_id'],
        'status': a['status'],
        'review_notes': a.get('review_notes'),
        'reviewer_user_id': a.get('reviewer_user_id'),
        'pinned_animal_version': a.get('pinned_animal_version'),
        'pinned_fee': a.get('pinned_fee'),
        'pinned_vaccination_snapshot': a.get('pinned_vaccination_snapshot'),
        'version': a['version'],
        'created_at': a['created_at'],
        'updated_at': a['updated_at'],
    }


def serialize_reservation(r):
    return {
        'id': r['id'],
        'shelter_id': r['shelter_id'],
        'animal_id': r['animal_id'],
        'owner_id': r['owner_id'],
        'check_in_date': r['check_in_date'],
        'check_out_date': r['check_out_date'],
        'status': r['status'],
        'quoted_total': r['quoted_total'],
        'final_total': r.get('final_total'),
        'version': r['version'],
        'created_at': r['created_at'],
        'updated_at': r['updated_at'],
    }


def serialize_settlement(s):
    return {
        'id': s['id'],
        'subject_type': s['subject_type'],
        'subject_id': s['subject_id'],
        'amount': s['amount'],
        'method': s['method'],
        'status': s['status'],
        'settled_at': s.get('settled_at'),
        'version': s['version'],
        'created_at': s['created_at'],
        'updated_at': s['updated_at'],
    }


# ----------------------------- Business Helpers -------------------------------

def compute_reserved_slots(shelter_id):
    return sum(
        1 for r in reservations.values()
        if r['shelter_id'] == shelter_id and r['status'] in ('RESERVED', 'ACTIVE')
    )


def compute_compliance(animal):
    required = SPECIES_VACCINES[animal['species']]
    recs = [v for v in vaccinations.values() if v['animal_id'] == animal['id']]
    latest = {}
    for v in recs:
        vt = v['vaccine_type']
        cur = latest.get(vt)
        if cur is None or v['administered_date'] > cur['administered_date']:
            latest[vt] = v
    now = now_utc()
    missing = []
    expired = []
    for vt in required:
        if vt not in latest:
            missing.append(vt)
        else:
            exp_dt = parse_dt(latest[vt]['expires_date'])
            if exp_dt is None or exp_dt <= now:
                expired.append(vt)
    status = 'COMPLIANT' if not missing and not expired else 'NON_COMPLIANT'
    return {'status': status, 'missing': missing, 'expired': expired}


def log_incident(incident_type, triggered_by, detail):
    inc = {
        'id': new_id(),
        'incident_type': incident_type,
        'triggered_by': triggered_by,
        'detail': detail,
        'created_at': iso_ts(),
    }
    incidents.append(inc)
    return inc


def fire_noncompliance_incident(animal, endpoint):
    comp = compute_compliance(animal)
    if comp['expired']:
        itype = 'VACCINE_EXPIRED'
    elif comp['missing']:
        itype = 'VACCINE_MISSING'
    else:
        itype = 'VACCINE_EXPIRED'
    detail = f"animal={animal['id']} missing={comp['missing']} expired={comp['expired']}"
    log_incident(itype, endpoint, detail)
    if endpoint.startswith('/adoption-applications'):
        log_incident('ADOPTION_BLOCKED', endpoint, detail)
    elif 'boarding' in endpoint:
        log_incident('BOARDING_BLOCKED', endpoint, detail)


def compute_adoption_fee(animal, shelter):
    if animal.get('adoption_fee_override') is not None:
        base = animal['adoption_fee_override']
    else:
        base = shelter['adoption_fee_base']
    if animal['age_months'] >= SENIOR_AGE_MONTHS:
        fee = (Decimal(base) * SENIOR_DISCOUNT).quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return int(fee)
    return int(base)


def compute_nights(check_in, check_out):
    ci = parse_dt(check_in)
    co = parse_dt(check_out)
    if ci is None or co is None:
        return None
    delta = (co.date() - ci.date()).days
    return delta


def compute_boarding_total(nights, rate, special_care, peak_applied):
    baseline = Decimal(rate) * Decimal(nights)
    multiplier = {
        'MEDICAL': Decimal('1.5'),
        'BEHAVIORAL': Decimal('1.25'),
        'NONE': Decimal('1.0'),
    }.get(special_care or 'NONE', Decimal('1.0'))
    total = baseline * multiplier
    if peak_applied:
        total = total + baseline * PEAK_SURCHARGE
    return int(total.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def effective_home_visit_status(adopter):
    status = adopter['home_visit_status']
    expires_at = adopter.get('home_visit_expires_at')
    if status == 'PASSED' and expires_at:
        exp_dt = parse_dt(expires_at)
        if exp_dt and exp_dt <= now_utc():
            return 'EXPIRED'
    return status


def get_completed_settlement(subject_type, subject_id):
    for s in settlements.values():
        if s['subject_type'] == subject_type and s['subject_id'] == subject_id and s['status'] == 'COMPLETED':
            return s
    return None


def fail_pending_settlements(subject_type, subject_id):
    for s in settlements.values():
        if s['subject_type'] == subject_type and s['subject_id'] == subject_id and s['status'] == 'PENDING':
            s['status'] = 'FAILED'
            bump(s)


def animal_has_active_holder(animal_id, exclude_app_id=None):
    for a in applications.values():
        if a['animal_id'] == animal_id and a['status'] in ('APPROVED', 'FINALIZED'):
            if exclude_app_id is None or a['id'] != exclude_app_id:
                return a
    return None


def animal_other_active_reservation(animal_id, exclude_rid=None):
    for r in reservations.values():
        if r['animal_id'] == animal_id and r['status'] in ('ACTIVE',):
            if exclude_rid is None or r['id'] != exclude_rid:
                return r
    return None


def body():
    raw = request.get_data(as_text=True).strip() if request.data else ''
    if not raw:
        return {}
    try:
        import json
        data = json.loads(raw)
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


# =============================================================================
# SHELTER ENDPOINTS
# =============================================================================

@app.post('/shelters')
def create_shelter():
    with LOCK:
        uid, role, e = require_role('ShelterAdmin')
        if e: return e
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        name = b.get('name')
        cap = b.get('boarding_capacity')
        fee_base = b.get('adoption_fee_base')
        rate = b.get('boarding_rate_per_night')
        if not isinstance(name, str) or not name.strip():
            return err('ERR_INVALID_REQUEST')
        if not isinstance(cap, int) or isinstance(cap, bool) or cap < 0:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(fee_base, int) or isinstance(fee_base, bool) or fee_base < 0:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(rate, int) or isinstance(rate, bool) or rate < 0:
            return err('ERR_INVALID_REQUEST')
        now_s = iso_ts()
        s = {
            'id': new_id(),
            'name': name,
            'boarding_capacity': cap,
            'adoption_fee_base': fee_base,
            'boarding_rate_per_night': rate,
            'status': 'OPEN',
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        shelters[s['id']] = s
        return ok_single(serialize_shelter(s), 201)


@app.get('/shelters')
def list_shelters():
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        limit, offset, er = parse_limit_offset()
        if er: return er
        items = [serialize_shelter(s) for s in shelters.values()]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.get('/shelters/<sid>')
def get_shelter(sid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        s = shelters.get(sid)
        if not s: return err('ERR_SHELTER_NOT_FOUND')
        return ok_single(serialize_shelter(s))


# =============================================================================
# ANIMAL ENDPOINTS
# =============================================================================

@app.post('/shelters/<sid>/animals')
def create_animal(sid):
    with LOCK:
        uid, role, e = require_role('ShelterAdmin')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        name = b.get('name')
        species = b.get('species')
        age = b.get('age_months')
        tags = b.get('temperament_tags', [])
        override = b.get('adoption_fee_override')
        special = b.get('special_care_level', 'NONE')
        if not isinstance(name, str) or not name.strip():
            return err('ERR_INVALID_REQUEST')
        if species not in VALID_SPECIES:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(age, int) or isinstance(age, bool) or age < 0:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            return err('ERR_INVALID_REQUEST')
        if override is not None and (not isinstance(override, int) or isinstance(override, bool) or override < 0):
            return err('ERR_INVALID_REQUEST')
        if special not in VALID_SPECIAL_CARE:
            return err('ERR_INVALID_REQUEST')
        now_s = iso_ts()
        a = {
            'id': new_id(),
            'shelter_id': sid,
            'name': name,
            'species': species,
            'age_months': age,
            'temperament_tags': list(tags),
            'adoption_fee_override': override,
            'special_care_level': special,
            'status': 'AVAILABLE',
            'intake_date': now_s,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        animals[a['id']] = a
        return ok_single(serialize_animal(a), 201)


@app.get('/shelters/<sid>/animals')
def list_animals(sid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        limit, offset, er = parse_limit_offset()
        if er: return er
        items = [serialize_animal(a) for a in animals.values() if a['shelter_id'] == sid]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.get('/shelters/<sid>/animals/<aid>')
def get_animal(sid, aid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        a = animals.get(aid)
        if not a: return err('ERR_ANIMAL_NOT_FOUND')
        if a['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        return ok_single(serialize_animal(a))


@app.patch('/shelters/<sid>/animals/<aid>')
def update_animal(sid, aid):
    with LOCK:
        uid, role, e = require_role('ShelterAdmin')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        a = animals.get(aid)
        if not a: return err('ERR_ANIMAL_NOT_FOUND')
        if a['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        ver = b.get('version')
        if ver is not None:
            if not isinstance(ver, int) or isinstance(ver, bool):
                return err('ERR_INVALID_REQUEST')
            if ver != a['version']:
                return err('ERR_VERSION_CONFLICT')
        # Validate updatable fields
        updates = {}
        if 'name' in b:
            if not isinstance(b['name'], str) or not b['name'].strip():
                return err('ERR_INVALID_REQUEST')
            updates['name'] = b['name']
        if 'temperament_tags' in b:
            tags = b['temperament_tags']
            if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
                return err('ERR_INVALID_REQUEST')
            updates['temperament_tags'] = list(tags)
        if 'adoption_fee_override' in b:
            ov = b['adoption_fee_override']
            if ov is not None and (not isinstance(ov, int) or isinstance(ov, bool) or ov < 0):
                return err('ERR_INVALID_REQUEST')
            updates['adoption_fee_override'] = ov
        if 'special_care_level' in b:
            sc = b['special_care_level']
            if sc not in VALID_SPECIAL_CARE:
                return err('ERR_INVALID_REQUEST')
            updates['special_care_level'] = sc
        a.update(updates)
        bump(a)
        return ok_single(serialize_animal(a))


# =============================================================================
# VACCINATION ENDPOINTS
# =============================================================================

@app.post('/shelters/<sid>/animals/<aid>/vaccinations')
def record_vaccination(sid, aid):
    with LOCK:
        uid, role, e = require_role(['ShelterAdmin', 'Veterinarian'])
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        a = animals.get(aid)
        if not a: return err('ERR_ANIMAL_NOT_FOUND')
        if a['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        vt = b.get('vaccine_type')
        adm = b.get('administered_date')
        exp = b.get('expires_date')
        lot = b.get('lot_number')
        if vt not in VALID_VACCINE_TYPES:
            return err('ERR_INVALID_REQUEST')
        adm_dt = parse_dt(adm) if adm else None
        exp_dt = parse_dt(exp) if exp else None
        if adm_dt is None or exp_dt is None:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(lot, str) or not lot.strip():
            return err('ERR_INVALID_REQUEST')
        now_s = iso_ts()
        v = {
            'id': new_id(),
            'animal_id': aid,
            'vaccine_type': vt,
            'administered_date': iso_ts(adm_dt),
            'expires_date': iso_ts(exp_dt),
            'lot_number': lot,
            'created_at': now_s,
        }
        vaccinations[v['id']] = v
        # Recording a vaccination is effectively a mutation of the animal
        bump(a)
        return ok_single(serialize_vaccination(v), 201)


@app.get('/shelters/<sid>/animals/<aid>/vaccinations')
def list_vaccinations(sid, aid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        a = animals.get(aid)
        if not a: return err('ERR_ANIMAL_NOT_FOUND')
        if a['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        vtype = request.args.get('vaccine_type')
        limit, offset, er = parse_limit_offset()
        if er: return er
        items = [serialize_vaccination(v) for v in vaccinations.values() if v['animal_id'] == aid]
        if vtype:
            if vtype not in VALID_VACCINE_TYPES:
                return err('ERR_INVALID_REQUEST')
            items = [v for v in items if v['vaccine_type'] == vtype]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.get('/shelters/<sid>/animals/<aid>/compliance')
def get_compliance(sid, aid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        a = animals.get(aid)
        if not a: return err('ERR_ANIMAL_NOT_FOUND')
        if a['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        comp = compute_compliance(a)
        return ok_single(comp)


# =============================================================================
# ADOPTER ENDPOINTS
# =============================================================================

@app.post('/adopters')
def create_adopter():
    with LOCK:
        uid, role, e = require_role(['Adopter', 'ShelterAdmin'])
        if e: return e
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        full_name = b.get('full_name')
        hs = b.get('household_size')
        hy = b.get('has_yard')
        if not isinstance(full_name, str) or not full_name.strip():
            return err('ERR_INVALID_REQUEST')
        if not isinstance(hs, int) or isinstance(hs, bool) or hs < 1:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(hy, bool):
            return err('ERR_INVALID_REQUEST')
        now_s = iso_ts()
        a = {
            'id': new_id(),
            'full_name': full_name,
            'household_size': hs,
            'has_yard': hy,
            'home_visit_status': 'PENDING',
            'home_visit_expires_at': None,
            'disqualified': False,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        adopters[a['id']] = a
        return ok_single(serialize_adopter(a), 201)


@app.get('/adopters/<aid>')
def get_adopter(aid):
    with LOCK:
        uid, role, e = require_role(['Adopter', 'AdoptionReviewer', 'AdoptionApprover', 'ShelterAdmin'])
        if e: return e
        a = adopters.get(aid)
        if not a: return err('ERR_ADOPTER_NOT_FOUND')
        return ok_single(serialize_adopter(a))


# =============================================================================
# HOME VISIT ENDPOINTS
# =============================================================================

@app.post('/adopters/<aid>/home-visits')
def schedule_home_visit(aid):
    with LOCK:
        uid, role, e = require_role('AdoptionReviewer')
        if e: return e
        a = adopters.get(aid)
        if not a: return err('ERR_ADOPTER_NOT_FOUND')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        scheduled_for = b.get('scheduled_for')
        inspector_id = b.get('inspector_id')
        sch_dt = parse_dt(scheduled_for) if scheduled_for else None
        if sch_dt is None:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(inspector_id, str) or not inspector_id.strip():
            return err('ERR_INVALID_REQUEST')
        now_s = iso_ts()
        h = {
            'id': new_id(),
            'adopter_id': aid,
            'scheduled_for': iso_ts(sch_dt),
            'inspector_id': inspector_id,
            'safety_score': None,
            'yard_verified': None,
            'status': 'SCHEDULED',
            'completed_at': None,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        home_visits[h['id']] = h
        return ok_single(serialize_home_visit(h), 201)


@app.get('/adopters/<aid>/home-visits')
def list_home_visits(aid):
    with LOCK:
        uid, role, e = require_role(['AdoptionReviewer', 'AdoptionApprover', 'Adopter'])
        if e: return e
        a = adopters.get(aid)
        if not a: return err('ERR_ADOPTER_NOT_FOUND')
        limit, offset, er = parse_limit_offset()
        if er: return er
        items = [serialize_home_visit(h) for h in home_visits.values() if h['adopter_id'] == aid]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.post('/adopters/<aid>/home-visits/<hvid>/submit')
def submit_home_visit(aid, hvid):
    with LOCK:
        uid, role, e = require_role('HomeVisitInspector')
        if e: return e
        a = adopters.get(aid)
        if not a: return err('ERR_ADOPTER_NOT_FOUND')
        h = home_visits.get(hvid)
        if not h: return err('ERR_HOME_VISIT_NOT_FOUND')
        if h['adopter_id'] != aid: return err('ERR_HOME_VISIT_NOT_FOUND')
        # Inspector ownership (level 2 — ERR_INSUFFICIENT_PERMISSIONS)
        if h['inspector_id'] != uid:
            return err('ERR_INSUFFICIENT_PERMISSIONS')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        score = b.get('safety_score')
        yard = b.get('yard_verified')
        if not isinstance(score, int) or isinstance(score, bool):
            return err('ERR_INVALID_REQUEST')
        if score < 0 or score > 100:
            return err('ERR_INVALID_SCORE')
        if yard is not None and not isinstance(yard, bool):
            return err('ERR_INVALID_REQUEST')
        if h['status'] != 'SCHEDULED':
            return err('ERR_INVALID_STATE')
        now_dt = now_utc()
        h['safety_score'] = score
        h['yard_verified'] = yard
        h['completed_at'] = iso_ts(now_dt)
        if score >= 70:
            h['status'] = 'PASSED'
            bump(h)
            # Update adopter
            a['home_visit_status'] = 'PASSED'
            a['home_visit_expires_at'] = iso_ts(now_dt + timedelta(days=HOME_VISIT_VALIDITY_DAYS))
            bump(a)
        else:
            h['status'] = 'FAILED'
            bump(h)
            # Cascade reject any applications in HOME_VISIT_REQUIRED for this adopter
            for app_ in list(applications.values()):
                if app_['adopter_id'] == aid and app_['status'] == 'HOME_VISIT_REQUIRED':
                    app_['status'] = 'REJECTED'
                    app_['last_error'] = 'ERR_HOME_VISIT_FAILED'
                    bump(app_)
                    # Release animal hold if any (shouldn't be HELD from HOME_VISIT_REQUIRED but defensive)
                    fail_pending_settlements('ADOPTION', app_['id'])
        return ok_single(serialize_home_visit(h))


@app.post('/adopters/<aid>/home-visits/<hvid>/cancel')
def cancel_home_visit(aid, hvid):
    with LOCK:
        uid, role, e = require_role(['Adopter', 'HomeVisitInspector'])
        if e: return e
        a = adopters.get(aid)
        if not a: return err('ERR_ADOPTER_NOT_FOUND')
        h = home_visits.get(hvid)
        if not h: return err('ERR_HOME_VISIT_NOT_FOUND')
        if h['adopter_id'] != aid: return err('ERR_HOME_VISIT_NOT_FOUND')
        if h['status'] != 'SCHEDULED':
            return err('ERR_INVALID_STATE')
        h['status'] = 'CANCELLED'
        bump(h)
        return ok_single(serialize_home_visit(h))


# =============================================================================
# ADOPTION APPLICATION ENDPOINTS
# =============================================================================

@app.post('/adoption-applications')
def create_application():
    with LOCK:
        uid, role, e = require_role('Adopter')
        if e: return e
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        adopter_id = b.get('adopter_id')
        animal_id = b.get('animal_id')
        review_notes = b.get('review_notes')
        if not isinstance(adopter_id, str) or not adopter_id:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(animal_id, str) or not animal_id:
            return err('ERR_INVALID_REQUEST')
        # Path-like existence for referenced resources
        adopter = adopters.get(adopter_id)
        if not adopter: return err('ERR_ADOPTER_NOT_FOUND')
        animal = animals.get(animal_id)
        if not animal: return err('ERR_ANIMAL_NOT_FOUND')
        # Business: animal_already_reserved if any APPROVED/FINALIZED application
        if animal_has_active_holder(animal_id):
            return err('ERR_ANIMAL_ALREADY_RESERVED')
        if animal['status'] not in ('AVAILABLE', 'HELD', 'BOARDING_ONLY'):
            return err('ERR_ANIMAL_UNAVAILABLE')
        if adopter['disqualified']:
            return err('ERR_ADOPTER_DISQUALIFIED')
        now_s = iso_ts()
        app_ = {
            'id': new_id(),
            'adopter_id': adopter_id,
            'animal_id': animal_id,
            'shelter_id': animal['shelter_id'],
            'status': 'SUBMITTED',
            'review_notes': review_notes if isinstance(review_notes, str) else None,
            'reviewer_user_id': None,
            'pinned_animal_version': None,
            'pinned_fee': None,
            'pinned_vaccination_snapshot': None,
            'applicant_user_id': uid,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        applications[app_['id']] = app_
        return ok_single(serialize_application(app_), 201)


@app.get('/adoption-applications')
def list_applications():
    with LOCK:
        uid, role, e = require_role(['AdoptionReviewer', 'AdoptionApprover', 'ShelterAdmin'])
        if e: return e
        limit, offset, er = parse_limit_offset()
        if er: return er
        status = request.args.get('status')
        adopter_id = request.args.get('adopter_id')
        animal_id = request.args.get('animal_id')
        items = list(applications.values())
        if status:
            items = [a for a in items if a['status'] == status]
        if adopter_id:
            items = [a for a in items if a['adopter_id'] == adopter_id]
        if animal_id:
            items = [a for a in items if a['animal_id'] == animal_id]
        items = [serialize_application(a) for a in items]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.get('/adoption-applications/<appid>')
def get_application(appid):
    with LOCK:
        uid, role, e = require_role(['AdoptionReviewer', 'AdoptionApprover', 'Adopter', 'ShelterAdmin'])
        if e: return e
        a = applications.get(appid)
        if not a: return err('ERR_APPLICATION_NOT_FOUND')
        return ok_single(serialize_application(a))


@app.post('/adoption-applications/<appid>/begin-review')
def begin_review(appid):
    with LOCK:
        uid, role, e = require_role('AdoptionReviewer')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        if app_['status'] != 'SUBMITTED':
            return err('ERR_INVALID_STATE')
        adopter = adopters.get(app_['adopter_id'])
        if adopter and adopter['disqualified']:
            return err('ERR_ADOPTER_DISQUALIFIED')
        app_['status'] = 'UNDER_REVIEW'
        app_['reviewer_user_id'] = uid
        bump(app_)
        return ok_single(serialize_application(app_))


@app.post('/adoption-applications/<appid>/request-home-visit')
def request_home_visit(appid):
    with LOCK:
        uid, role, e = require_role('AdoptionReviewer')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        if app_['status'] != 'UNDER_REVIEW':
            return err('ERR_INVALID_STATE')
        app_['status'] = 'HOME_VISIT_REQUIRED'
        bump(app_)
        return ok_single(serialize_application(app_))


@app.post('/adoption-applications/<appid>/approve')
def approve_application(appid):
    with LOCK:
        uid, role, e = require_role('AdoptionApprover')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        if app_['status'] not in ('UNDER_REVIEW', 'HOME_VISIT_REQUIRED'):
            return err('ERR_INVALID_STATE')
        # 1) Segregation of duties
        if app_.get('reviewer_user_id') and app_['reviewer_user_id'] == uid:
            return err('ERR_SEGREGATION_OF_DUTIES')
        adopter = adopters.get(app_['adopter_id'])
        animal = animals.get(app_['animal_id'])
        shelter = shelters.get(app_['shelter_id'])
        # 2) Home visit required
        if effective_home_visit_status(adopter) != 'PASSED':
            return err('ERR_HOME_VISIT_REQUIRED')
        # 3) Vaccination compliance
        comp = compute_compliance(animal)
        if comp['status'] != 'COMPLIANT':
            fire_noncompliance_incident(animal, f'/adoption-applications/{appid}/approve')
            return err('ERR_VACCINATION_NON_COMPLIANT')
        # 4) Animal availability
        if animal['status'] not in ('AVAILABLE', 'HELD'):
            return err('ERR_ANIMAL_UNAVAILABLE')
        # 5) Not already reserved by another app
        other = animal_has_active_holder(animal['id'], exclude_app_id=appid)
        if other:
            return err('ERR_ANIMAL_ALREADY_RESERVED')
        # All checks passed — perform approval
        fee = compute_adoption_fee(animal, shelter)
        app_['status'] = 'APPROVED'
        app_['pinned_fee'] = fee
        app_['pinned_vaccination_snapshot'] = comp
        # Transition animal to HELD
        animal['status'] = 'HELD'
        bump(animal)
        app_['pinned_animal_version'] = animal['version']
        bump(app_)
        # Cascade sibling applications
        for sib in list(applications.values()):
            if sib['id'] == appid: continue
            if sib['animal_id'] != animal['id']: continue
            if sib['status'] in ('SUBMITTED', 'UNDER_REVIEW', 'HOME_VISIT_REQUIRED'):
                sib['status'] = 'REJECTED'
                sib['last_error'] = 'ERR_ANIMAL_ALREADY_RESERVED'
                bump(sib)
                fail_pending_settlements('ADOPTION', sib['id'])
        return ok_single(serialize_application(app_))


@app.post('/adoption-applications/<appid>/reject')
def reject_application(appid):
    with LOCK:
        uid, role, e = require_role('AdoptionApprover')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        b = body() or {}
        if app_['status'] not in ('SUBMITTED', 'UNDER_REVIEW', 'HOME_VISIT_REQUIRED'):
            return err('ERR_INVALID_STATE')
        # Segregation of duties
        if app_.get('reviewer_user_id') and app_['reviewer_user_id'] == uid:
            return err('ERR_SEGREGATION_OF_DUTIES')
        if 'review_notes' in b and isinstance(b['review_notes'], str):
            app_['review_notes'] = b['review_notes']
        app_['status'] = 'REJECTED'
        bump(app_)
        # If this was the sole holder, fall animal back to AVAILABLE
        animal = animals.get(app_['animal_id'])
        if animal and animal['status'] == 'HELD':
            other = animal_has_active_holder(animal['id'], exclude_app_id=appid)
            if not other:
                animal['status'] = 'AVAILABLE'
                bump(animal)
        fail_pending_settlements('ADOPTION', appid)
        return ok_single(serialize_application(app_))


@app.post('/adoption-applications/<appid>/withdraw')
def withdraw_application(appid):
    with LOCK:
        uid, role, e = require_role('Adopter')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        if app_.get('applicant_user_id') and app_['applicant_user_id'] != uid:
            return err('ERR_INSUFFICIENT_PERMISSIONS')
        if app_['status'] == 'FINALIZED':
            return err('ERR_INVALID_STATE')
        if app_['status'] not in ('SUBMITTED', 'UNDER_REVIEW', 'HOME_VISIT_REQUIRED', 'APPROVED'):
            return err('ERR_INVALID_STATE')
        was_approved = app_['status'] == 'APPROVED'
        app_['status'] = 'WITHDRAWN'
        bump(app_)
        # Release any exclusive animal hold
        animal = animals.get(app_['animal_id'])
        if was_approved and animal and animal['status'] == 'HELD':
            other = animal_has_active_holder(animal['id'], exclude_app_id=appid)
            if not other:
                animal['status'] = 'AVAILABLE'
                bump(animal)
        fail_pending_settlements('ADOPTION', appid)
        return ok_single(serialize_application(app_))


@app.post('/adoption-applications/<appid>/finalize')
def finalize_application(appid):
    with LOCK:
        uid, role, e = require_role('AdoptionApprover')
        if e: return e
        app_ = applications.get(appid)
        if not app_: return err('ERR_APPLICATION_NOT_FOUND')
        if app_['status'] != 'APPROVED':
            return err('ERR_INVALID_STATE')
        # Require completed settlement
        completed = get_completed_settlement('ADOPTION', appid)
        if not completed:
            return err('ERR_FEE_NOT_SETTLED')
        animal = animals.get(app_['animal_id'])
        # Pinned version check
        if app_.get('pinned_animal_version') != animal['version']:
            return err('ERR_STALE_PINNED_REFERENCE')
        # Vaccination compliance
        comp = compute_compliance(animal)
        if comp['status'] != 'COMPLIANT':
            fire_noncompliance_incident(animal, f'/adoption-applications/{appid}/finalize')
            return err('ERR_VACCINATION_NON_COMPLIANT')
        app_['status'] = 'FINALIZED'
        bump(app_)
        animal['status'] = 'ADOPTED'
        bump(animal)
        # Cascade: any RESERVED BoardingReservation for this animal -> CANCELLED
        for r in list(reservations.values()):
            if r['animal_id'] == animal['id'] and r['status'] == 'RESERVED':
                r['status'] = 'CANCELLED'
                r['last_error'] = 'ERR_ANIMAL_ADOPTED'
                bump(r)
                fail_pending_settlements('BOARDING', r['id'])
        return ok_single(serialize_application(app_))


# =============================================================================
# BOARDING RESERVATION ENDPOINTS
# =============================================================================

@app.post('/shelters/<sid>/boarding-reservations')
def create_reservation(sid):
    with LOCK:
        uid, role, e = require_role(['BoardingCoordinator', 'Adopter'])
        if e: return e
        shelter = shelters.get(sid)
        if not shelter: return err('ERR_SHELTER_NOT_FOUND')
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        animal_id = b.get('animal_id')
        owner_id = b.get('owner_id')
        ci = b.get('check_in_date')
        co = b.get('check_out_date')
        if not isinstance(animal_id, str) or not animal_id:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(owner_id, str) or not owner_id:
            return err('ERR_INVALID_REQUEST')
        animal = animals.get(animal_id)
        if not animal: return err('ERR_ANIMAL_NOT_FOUND')
        if animal['shelter_id'] != sid: return err('ERR_ANIMAL_NOT_FOUND')
        adopter = adopters.get(owner_id)
        if not adopter: return err('ERR_ADOPTER_NOT_FOUND')
        ci_dt = parse_dt(ci) if ci else None
        co_dt = parse_dt(co) if co else None
        if ci_dt is None or co_dt is None:
            return err('ERR_INVALID_REQUEST')
        nights = (co_dt.date() - ci_dt.date()).days
        if nights < 1:
            return err('ERR_INVALID_REQUEST')
        # State: shelter must be OPEN for new reservations
        if shelter['status'] != 'OPEN':
            return err('ERR_INVALID_STATE')
        # Vaccination compliance (level 7)
        comp = compute_compliance(animal)
        if comp['status'] != 'COMPLIANT':
            fire_noncompliance_incident(animal, f'/shelters/{sid}/boarding-reservations')
            return err('ERR_VACCINATION_NON_COMPLIANT')
        # Boardable (level 8) — evaluated before capacity
        if animal['status'] in ('ADOPTED', 'RETIRED'):
            return err('ERR_ANIMAL_NOT_BOARDABLE')
        # Capacity
        reserved = compute_reserved_slots(sid)
        if reserved >= shelter['boarding_capacity']:
            return err('ERR_SHELTER_AT_CAPACITY')
        # Compute peak surcharge: utilization AFTER this reservation? Or BEFORE?
        # PRD: "at the time the reservation is recorded, the shelter's utilization - defined as reserved_slots divided by boarding_capacity"
        # We interpret this as utilization INCLUDING the new reservation (since reserved_slots is post-increment).
        new_reserved = reserved + 1
        utilization = Decimal(new_reserved) / Decimal(shelter['boarding_capacity']) if shelter['boarding_capacity'] > 0 else Decimal(0)
        peak = utilization >= PEAK_UTILIZATION
        special = animal.get('special_care_level', 'NONE')
        rate = shelter['boarding_rate_per_night']
        quoted = compute_boarding_total(nights, rate, special, peak)
        now_s = iso_ts()
        r = {
            'id': new_id(),
            'shelter_id': sid,
            'animal_id': animal_id,
            'owner_id': owner_id,
            'check_in_date': iso_ts(ci_dt),
            'check_out_date': iso_ts(co_dt),
            'status': 'RESERVED',
            'quoted_total': quoted,
            'final_total': None,
            'rate_at_reservation': rate,
            'special_care_at_reservation': special,
            'peak_applied_at_reservation': bool(peak),
            'owner_user_id': uid,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        reservations[r['id']] = r
        return ok_single(serialize_reservation(r), 201)


@app.get('/shelters/<sid>/boarding-reservations')
def list_reservations(sid):
    with LOCK:
        uid, role, e = require_role('Any')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        limit, offset, er = parse_limit_offset()
        if er: return er
        status = request.args.get('status')
        animal_id = request.args.get('animal_id')
        items = [r for r in reservations.values() if r['shelter_id'] == sid]
        if status:
            items = [r for r in items if r['status'] == status]
        if animal_id:
            items = [r for r in items if r['animal_id'] == animal_id]
        items = [serialize_reservation(r) for r in items]
        page, total = paginate(items, limit, offset)
        return ok_list(page, limit, offset, total)


@app.post('/shelters/<sid>/boarding-reservations/<rid>/check-in')
def check_in_reservation(sid, rid):
    with LOCK:
        uid, role, e = require_role('BoardingCoordinator')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        r = reservations.get(rid)
        if not r: return err('ERR_RESERVATION_NOT_FOUND')
        if r['shelter_id'] != sid: return err('ERR_RESERVATION_NOT_FOUND')
        if r['status'] != 'RESERVED':
            return err('ERR_INVALID_STATE')
        ci_dt = parse_dt(r['check_in_date'])
        now = now_utc()
        if now < ci_dt - timedelta(hours=EARLY_CHECKIN_GRACE_HOURS):
            return err('ERR_TOO_EARLY_FOR_CHECKIN')
        animal = animals.get(r['animal_id'])
        comp = compute_compliance(animal)
        if comp['status'] != 'COMPLIANT':
            fire_noncompliance_incident(animal, f'/shelters/{sid}/boarding-reservations/{rid}/check-in')
            return err('ERR_VACCINATION_NON_COMPLIANT')
        r['status'] = 'ACTIVE'
        bump(r)
        if animal['status'] == 'AVAILABLE':
            animal['status'] = 'BOARDING_ONLY'
            bump(animal)
        return ok_single(serialize_reservation(r))


@app.post('/shelters/<sid>/boarding-reservations/<rid>/check-out')
def check_out_reservation(sid, rid):
    with LOCK:
        uid, role, e = require_role('BoardingCoordinator')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        r = reservations.get(rid)
        if not r: return err('ERR_RESERVATION_NOT_FOUND')
        if r['shelter_id'] != sid: return err('ERR_RESERVATION_NOT_FOUND')
        if r['status'] != 'ACTIVE':
            return err('ERR_INVALID_STATE')
        # Compute final_total using actual check-out date (now)
        ci_dt = parse_dt(r['check_in_date'])
        now = now_utc()
        # whole-day difference, exclusive check-out
        nights = max(1, (now.date() - ci_dt.date()).days)
        if nights < 1:
            nights = 1
        final_total = compute_boarding_total(
            nights,
            r.get('rate_at_reservation'),
            r.get('special_care_at_reservation', 'NONE'),
            r.get('peak_applied_at_reservation', False),
        )
        r['final_total'] = final_total
        r['status'] = 'COMPLETED'
        r['check_out_date'] = iso_ts(now)
        bump(r)
        animal = animals.get(r['animal_id'])
        if animal and animal['status'] == 'BOARDING_ONLY':
            other = animal_other_active_reservation(animal['id'], exclude_rid=rid)
            if not other:
                animal['status'] = 'AVAILABLE'
                bump(animal)
        return ok_single(serialize_reservation(r))


@app.post('/shelters/<sid>/boarding-reservations/<rid>/settle')
def settle_reservation(sid, rid):
    with LOCK:
        uid, role, e = require_role('FinanceOfficer')
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        r = reservations.get(rid)
        if not r: return err('ERR_RESERVATION_NOT_FOUND')
        if r['shelter_id'] != sid: return err('ERR_RESERVATION_NOT_FOUND')
        if r['status'] != 'COMPLETED':
            return err('ERR_INVALID_STATE')
        completed = get_completed_settlement('BOARDING', rid)
        if not completed:
            return err('ERR_FEE_NOT_SETTLED')
        r['status'] = 'SETTLED'
        bump(r)
        return ok_single(serialize_reservation(r))


@app.post('/shelters/<sid>/boarding-reservations/<rid>/cancel')
def cancel_reservation(sid, rid):
    with LOCK:
        uid, role, e = require_role(['BoardingCoordinator', 'Adopter'])
        if e: return e
        if sid not in shelters: return err('ERR_SHELTER_NOT_FOUND')
        r = reservations.get(rid)
        if not r: return err('ERR_RESERVATION_NOT_FOUND')
        if r['shelter_id'] != sid: return err('ERR_RESERVATION_NOT_FOUND')
        # Adopter must be owner (level 2)
        if role == 'Adopter' and r.get('owner_user_id') and r['owner_user_id'] != uid:
            return err('ERR_INSUFFICIENT_PERMISSIONS')
        if r['status'] not in ('RESERVED', 'ACTIVE'):
            return err('ERR_INVALID_STATE')
        was_active = r['status'] == 'ACTIVE'
        r['status'] = 'CANCELLED'
        bump(r)
        # If animal was BOARDING_ONLY solely due to this reservation, revert
        animal = animals.get(r['animal_id'])
        if was_active and animal and animal['status'] == 'BOARDING_ONLY':
            other = animal_other_active_reservation(animal['id'], exclude_rid=rid)
            if not other:
                animal['status'] = 'AVAILABLE'
                bump(animal)
        fail_pending_settlements('BOARDING', rid)
        return ok_single(serialize_reservation(r))


# =============================================================================
# FEE SETTLEMENT ENDPOINTS
# =============================================================================

@app.post('/fee-settlements')
def create_settlement():
    with LOCK:
        uid, role, e = require_role(['FinanceOfficer', 'Adopter'])
        if e: return e
        b = body()
        if b is None: return err('ERR_INVALID_REQUEST')
        st = b.get('subject_type')
        sid = b.get('subject_id')
        amount = b.get('amount')
        method = b.get('method')
        if st not in VALID_SUBJECT_TYPES:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(sid, str) or not sid:
            return err('ERR_INVALID_REQUEST')
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 0:
            return err('ERR_INVALID_REQUEST')
        if method not in VALID_PAYMENT_METHODS:
            return err('ERR_INVALID_REQUEST')
        # Verify subject exists
        if st == 'ADOPTION':
            if sid not in applications:
                return err('ERR_APPLICATION_NOT_FOUND')
        else:
            if sid not in reservations:
                return err('ERR_RESERVATION_NOT_FOUND')
        now_s = iso_ts()
        s = {
            'id': new_id(),
            'subject_type': st,
            'subject_id': sid,
            'amount': amount,
            'method': method,
            'status': 'PENDING',
            'settled_at': None,
            'version': 1,
            'created_at': now_s,
            'updated_at': now_s,
        }
        settlements[s['id']] = s
        return ok_single(serialize_settlement(s), 201)


@app.post('/fee-settlements/<sid>/capture')
def capture_settlement(sid):
    with LOCK:
        uid, role, e = require_role('FinanceOfficer')
        if e: return e
        s = settlements.get(sid)
        if not s: return err('ERR_SETTLEMENT_NOT_FOUND')
        if s['status'] != 'PENDING':
            return err('ERR_INVALID_STATE')
        # Subject state check
        if s['subject_type'] == 'ADOPTION':
            app_ = applications.get(s['subject_id'])
            if not app_: return err('ERR_APPLICATION_NOT_FOUND')
            if app_['status'] != 'APPROVED':
                return err('ERR_INVALID_STATE')
            # Duplicate check
            for other in settlements.values():
                if other['id'] == sid: continue
                if other['subject_type'] == 'ADOPTION' and other['subject_id'] == s['subject_id'] and other['status'] == 'COMPLETED':
                    return err('ERR_DUPLICATE_SETTLEMENT')
            animal = animals.get(app_['animal_id'])
            shelter = shelters.get(app_['shelter_id'])
            live_fee = compute_adoption_fee(animal, shelter)
            if app_.get('pinned_fee') != live_fee:
                return err('ERR_AMOUNT_MISMATCH')
            if s['amount'] != app_.get('pinned_fee'):
                return err('ERR_AMOUNT_MISMATCH')
        else:
            r = reservations.get(s['subject_id'])
            if not r: return err('ERR_RESERVATION_NOT_FOUND')
            if r['status'] != 'COMPLETED':
                return err('ERR_INVALID_STATE')
            # Duplicate check
            for other in settlements.values():
                if other['id'] == sid: continue
                if other['subject_type'] == 'BOARDING' and other['subject_id'] == s['subject_id'] and other['status'] == 'COMPLETED':
                    return err('ERR_DUPLICATE_SETTLEMENT')
            auth = r.get('final_total') if r.get('final_total') is not None else r['quoted_total']
            if s['amount'] != auth:
                return err('ERR_AMOUNT_MISMATCH')
        s['status'] = 'COMPLETED'
        s['settled_at'] = iso_ts()
        bump(s)
        return ok_single(serialize_settlement(s))


@app.post('/fee-settlements/<sid>/refund')
def refund_settlement(sid):
    with LOCK:
        uid, role, e = require_role('FinanceOfficer')
        if e: return e
        s = settlements.get(sid)
        if not s: return err('ERR_SETTLEMENT_NOT_FOUND')
        if s['status'] != 'COMPLETED':
            return err('ERR_INVALID_STATE')
        # Subject must not be in terminal FINALIZED/SETTLED state
        if s['subject_type'] == 'ADOPTION':
            app_ = applications.get(s['subject_id'])
            if app_ and app_['status'] == 'FINALIZED':
                return err('ERR_INVALID_STATE')
        else:
            r = reservations.get(s['subject_id'])
            if r and r['status'] == 'SETTLED':
                return err('ERR_INVALID_STATE')
        s['status'] = 'REFUNDED'
        bump(s)
        # Cascade on adoption still APPROVED: reject with ERR_FEE_REFUNDED
        if s['subject_type'] == 'ADOPTION':
            app_ = applications.get(s['subject_id'])
            if app_ and app_['status'] == 'APPROVED':
                app_['status'] = 'REJECTED'
                app_['last_error'] = 'ERR_FEE_REFUNDED'
                bump(app_)
                animal = animals.get(app_['animal_id'])
                if animal and animal['status'] == 'HELD':
                    other = animal_has_active_holder(animal['id'], exclude_app_id=app_['id'])
                    if not other:
                        animal['status'] = 'AVAILABLE'
                        bump(animal)
        return ok_single(serialize_settlement(s))


@app.get('/fee-settlements/<sid>')
def get_settlement(sid):
    with LOCK:
        uid, role, e = require_role(['FinanceOfficer', 'Adopter'])
        if e: return e
        s = settlements.get(sid)
        if not s: return err('ERR_SETTLEMENT_NOT_FOUND')
        return ok_single(serialize_settlement(s))


# =============================================================================
# Error Handlers
# =============================================================================

@app.errorhandler(404)
def not_found(_):
    return jsonify({'meta': make_meta(), 'response_type': 'error',
                    'data': {'error_id': 'ERR_INVALID_REQUEST', 'message': 'Route not found.'}}), 404


@app.errorhandler(405)
def method_not_allowed(_):
    return jsonify({'meta': make_meta(), 'response_type': 'error',
                    'data': {'error_id': 'ERR_INVALID_REQUEST', 'message': 'Method not allowed.'}}), 405


@app.errorhandler(Exception)
def unhandled(e):
    return jsonify({'meta': make_meta(), 'response_type': 'error',
                    'data': {'error_id': 'ERR_INVALID_REQUEST', 'message': str(e)}}), 400


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
