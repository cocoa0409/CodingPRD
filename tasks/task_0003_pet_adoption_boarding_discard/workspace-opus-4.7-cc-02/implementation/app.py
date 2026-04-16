"""Pet Adoption Boarding API."""
import os
import math
import threading
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from flask import Flask, request, jsonify

app = Flask(__name__)
app.url_map.strict_slashes = False

_LOCK = threading.RLock()

STORE = {
    'shelters': {},
    'animals': {},
    'vaccination_records': {},
    'adopters': {},
    'adoption_applications': {},
    'home_visits': {},
    'boarding_reservations': {},
    'boarding_matches': {},
    'fee_invoices': {},
    'compliance_holds': {},
    'fee_schedules': {},
}

VALID_ROLES = {'ShelterManager', 'CaseWorker', 'Veterinarian'}

VACCINE_TYPES = {'RABIES', 'DHPP', 'BORDETELLA', 'FVRCP', 'RHDV'}
SPECIES_SET = {'DOG', 'CAT', 'RABBIT', 'BIRD', 'OTHER'}
TEMPERAMENT_SET = {'CALM', 'MODERATE', 'ENERGETIC', 'AGGRESSIVE'}
SPECIAL_NEEDS_SET = {'MEDICATION_REQUIRED', 'DIET_RESTRICTED', 'MOBILITY_LIMITED'}
HOME_TYPE_SET = {'HOUSE', 'APARTMENT', 'FARM', 'OTHER'}
FEE_TYPES = {'ADOPTION_BASE', 'BOARDING_DAILY', 'SPECIAL_NEEDS_SURCHARGE',
             'VACCINATION_FEE', 'LOYALTY_DISCOUNT'}
HOLD_SEVERITIES = {'LOW', 'MEDIUM', 'HIGH', 'CRITICAL'}

SPECIES_VAX = {
    'DOG': {'RABIES', 'DHPP', 'BORDETELLA'},
    'CAT': {'RABIES', 'FVRCP'},
    'RABBIT': {'RHDV'},
    'BIRD': set(),
    'OTHER': set(),
}


# ============ Utilities ============

def now_iso():
    dt = datetime.now(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + f'{ms:03d}Z'


def gen_request_id():
    return 'req_' + uuid.uuid4().hex[:16]


def gen_id():
    return str(uuid.uuid4())


def round_money(value):
    if value is None:
        return 0.0
    d = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(d)


def round_score_2dp(value):
    d = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    return float(d)


def parse_date(s):
    """Parse date or datetime string. Returns datetime with UTC tz."""
    if s is None:
        return None
    if isinstance(s, (datetime, date)):
        if isinstance(s, datetime):
            return s if s.tzinfo else s.replace(tzinfo=timezone.utc)
        return datetime(s.year, s.month, s.day, tzinfo=timezone.utc)
    if not isinstance(s, str):
        return None
    s2 = s.strip()
    try:
        if 'T' in s2:
            if s2.endswith('Z'):
                s2 = s2[:-1] + '+00:00'
            dt = datetime.fromisoformat(s2)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        else:
            d = date.fromisoformat(s2)
            return datetime(d.year, d.month, d.day, tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_date_only(s):
    if s is None:
        return None
    if isinstance(s, date) and not isinstance(s, datetime):
        return s
    if isinstance(s, datetime):
        return s.date()
    if not isinstance(s, str):
        return None
    try:
        if 'T' in s:
            dt = parse_date(s)
            return dt.date() if dt else None
        return date.fromisoformat(s)
    except (ValueError, TypeError):
        return None


def envelope_success(data, status=200, response_type='object', pagination=None):
    meta = {
        'api_request_id': gen_request_id(),
        'api_request_timestamp': now_iso(),
    }
    if pagination:
        meta.update(pagination)
    return jsonify({
        'meta': meta,
        'response_type': response_type,
        'data': data,
    }), status


def envelope_error(error_id, message, status):
    return jsonify({
        'meta': {
            'api_request_id': gen_request_id(),
            'api_request_timestamp': now_iso(),
        },
        'response_type': 'error',
        'data': {
            'error_id': error_id,
            'message': message,
        },
    }), status


# ============ Auth ============

ERR_MAP_STATUS = {
    'ERR_AUTH_REQUIRED': 401,
    'ERR_FORBIDDEN': 403,
    'ERR_INVALID_REQUEST': 400,
    'ERR_INVALID_DATES': 400,
    'ERR_PAYMENT_AMOUNT_INVALID': 400,
    'ERR_SHELTER_NOT_FOUND': 404,
    'ERR_ANIMAL_NOT_FOUND': 404,
    'ERR_ADOPTER_NOT_FOUND': 404,
    'ERR_APPLICATION_NOT_FOUND': 404,
    'ERR_RESERVATION_NOT_FOUND': 404,
    'ERR_INVOICE_NOT_FOUND': 404,
    'ERR_HOLD_NOT_FOUND': 404,
    'ERR_HOME_VISIT_NOT_FOUND': 404,
    'ERR_FEE_SCHEDULE_NOT_FOUND': 404,
    'ERR_VACCINATION_RECORD_NOT_FOUND': 404,
    'ERR_INVALID_STATE': 409,
    'ERR_SHELTER_SUSPENDED': 409,
    'ERR_ANIMAL_NOT_AVAILABLE': 409,
    'ERR_ADOPTER_BLACKLISTED': 409,
    'ERR_VACCINATION_NOT_COMPLIANT': 409,
    'ERR_COMPLIANCE_HOLD_ACTIVE': 409,
    'ERR_SELF_APPROVAL': 409,
    'ERR_STALE_ANIMAL_DATA': 409,
    'ERR_STALE_ADOPTER_DATA': 409,
    'ERR_HOME_VISIT_REQUIRED': 409,
    'ERR_REVIEWER_MISMATCH': 409,
    'ERR_ASSESSOR_MISMATCH': 409,
    'ERR_BOARDING_DATE_OVERLAP': 409,
    'ERR_BOARDING_CAPACITY_FULL': 409,
    'ERR_FEE_NOT_PAID': 409,
    'ERR_INVOICE_HAS_PAYMENTS': 409,
    'ERR_STALE_DATA': 409,
}


def err(error_id, message=None):
    msg = message or error_id.replace('ERR_', '').replace('_', ' ').title()
    return envelope_error(error_id, msg, ERR_MAP_STATUS.get(error_id, 400))


def check_auth(allowed_roles=None):
    user_id = request.headers.get('X-User-ID')
    role = request.headers.get('X-User-Role')
    if not user_id or not role or role not in VALID_ROLES:
        return None, None, err('ERR_AUTH_REQUIRED', 'Authentication required.')
    if allowed_roles and role not in allowed_roles:
        return None, None, err('ERR_FORBIDDEN', 'Role not permitted.')
    return user_id, role, None


# ============ Pagination ============

def paginate(items, _meta=None):
    try:
        limit = int(request.args.get('limit', 20))
        offset = int(request.args.get('offset', 0))
    except (ValueError, TypeError):
        return None, err('ERR_INVALID_REQUEST', 'Invalid pagination parameters.')
    if limit < 1 or limit > 100 or offset < 0:
        return None, err('ERR_INVALID_REQUEST', 'Invalid pagination parameters.')
    total = len(items)
    sliced = items[offset:offset + limit]
    pagination = {
        'limit': limit,
        'offset': offset,
        'total_count': total,
        'has_more': offset + limit < total,
    }
    return (sliced, pagination), None


# ============ Domain Logic ============

def compute_vaccination_compliance(animal_id, species, for_boarding=False):
    required = set(SPECIES_VAX.get(species, set()))
    if for_boarding and species != 'BIRD':
        required.add('BORDETELLA')
    if not required:
        return True
    today = date.today()
    valid_types = set()
    for rec in STORE['vaccination_records'].values():
        if rec['animal_id'] != animal_id:
            continue
        expiry = parse_date_only(rec.get('expiry_date'))
        if expiry is None:
            continue
        if expiry >= today:
            valid_types.add(rec['vaccine_type'])
    return required.issubset(valid_types)


def has_active_hi_hold(animal_id):
    for h in STORE['compliance_holds'].values():
        if h['animal_id'] == animal_id and h['status'] == 'ACTIVE' \
                and h['severity'] in ('HIGH', 'CRITICAL'):
            return True
    return False


def has_active_critical_hold_in_shelter(shelter_id):
    for h in STORE['compliance_holds'].values():
        if h['status'] != 'ACTIVE' or h['severity'] != 'CRITICAL':
            continue
        a = STORE['animals'].get(h['animal_id'])
        if a and a['shelter_id'] == shelter_id:
            return True
    return False


def count_active_holds_in_shelter(shelter_id):
    n = 0
    for h in STORE['compliance_holds'].values():
        if h['status'] != 'ACTIVE':
            continue
        a = STORE['animals'].get(h['animal_id'])
        if a and a['shelter_id'] == shelter_id:
            n += 1
    return n


def compute_boarding_compatible_tags(animal):
    tags = [animal['species'], animal['temperament']]
    for t in animal.get('special_needs') or []:
        tags.append(t)
    return tags


def recompute_animal_derived(animal):
    animal['vaccination_compliant'] = compute_vaccination_compliance(
        animal['id'], animal['species'], for_boarding=False)
    animal['boarding_compatible_tags'] = compute_boarding_compatible_tags(animal)
    no_hold = not has_active_hi_hold(animal['id'])
    animal['adoption_eligible'] = (
        animal['vaccination_compliant']
        and animal['status'] == 'AVAILABLE'
        and no_hold
    )
    animal['updated_at'] = now_iso()
    animal['version'] += 1


def recompute_shelter_compliance(shelter_id):
    shelter = STORE['shelters'].get(shelter_id)
    if not shelter:
        return
    animals = [a for a in STORE['animals'].values()
               if a['shelter_id'] == shelter_id and a['status'] != 'ADOPTED']
    if not animals:
        score = Decimal('100')
    else:
        compliant = sum(1 for a in animals if a['vaccination_compliant'])
        ratio = Decimal(compliant) / Decimal(len(animals)) * Decimal('100')
        penalty = Decimal(count_active_holds_in_shelter(shelter_id)) * Decimal('5')
        score = ratio - penalty
        if score < 0:
            score = Decimal('0')
        if score > 100:
            score = Decimal('100')
    shelter['compliance_score'] = float(score.quantize(Decimal('0.01'),
                                                        rounding=ROUND_HALF_UP))
    shelter['updated_at'] = now_iso()
    shelter['version'] += 1


def bump(resource):
    resource['updated_at'] = now_iso()
    resource['version'] += 1


# ============ Fee calc ============

def find_active_fee_schedule(shelter_id, fee_type, species):
    now = datetime.now(timezone.utc)
    candidates = []
    for fs in STORE['fee_schedules'].values():
        if fs['shelter_id'] != shelter_id:
            continue
        if fs['fee_type'] != fee_type:
            continue
        if fs['species'] != species:
            continue
        eff_from = parse_date(fs['effective_from'])
        eff_to = parse_date(fs.get('effective_to'))
        if eff_from and eff_from > now:
            continue
        if eff_to and eff_to < now:
            continue
        candidates.append(fs)
    if not candidates:
        return None
    candidates.sort(key=lambda x: parse_date(x['effective_from']) or datetime.min.replace(tzinfo=timezone.utc),
                    reverse=True)
    return candidates[0]


def update_fee_schedule_active_flags():
    now = datetime.now(timezone.utc)
    for fs in STORE['fee_schedules'].values():
        eff_from = parse_date(fs['effective_from'])
        eff_to = parse_date(fs.get('effective_to'))
        active = True
        if eff_from and eff_from > now:
            active = False
        if eff_to and eff_to < now:
            active = False
        fs['is_active'] = active


def calc_adoption_fee(shelter, animal, adopter):
    species = animal['species']
    base_fs = find_active_fee_schedule(shelter['id'], 'ADOPTION_BASE', species)
    base_amount = Decimal(str(base_fs['amount'])) if base_fs else Decimal('0')

    is_senior = animal.get('age_months', 0) >= 84
    if is_senior:
        base_amount = base_amount * Decimal('0.5')

    sn_fs = find_active_fee_schedule(shelter['id'], 'SPECIAL_NEEDS_SURCHARGE', species)
    sn_amount_per = Decimal(str(sn_fs['amount'])) if sn_fs else Decimal('0')
    special_needs = animal.get('special_needs') or []
    surcharge = sn_amount_per * Decimal(len(special_needs))

    subtotal = base_amount + surcharge

    loyalty_fs = find_active_fee_schedule(shelter['id'], 'LOYALTY_DISCOUNT', 'ALL')
    loyalty_rate = Decimal(str(loyalty_fs['amount'])) if loyalty_fs else Decimal('0')
    discount = Decimal('0')
    if adopter.get('adoption_history_count', 0) >= 2:
        discount = (subtotal * loyalty_rate / Decimal('100')).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)

    taxable = subtotal - discount
    if taxable < 0:
        taxable = Decimal('0')
    tax_rate = Decimal(str(shelter.get('tax_rate', 0)))
    tax = (taxable * tax_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (taxable + tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    line_items = [
        {'description': f'Adoption base fee ({species})',
         'amount': float(base_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))},
    ]
    if len(special_needs) > 0:
        line_items.append({
            'description': f'Special needs surcharge x{len(special_needs)}',
            'amount': float(surcharge.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        })

    return {
        'subtotal': float(subtotal.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)),
        'discount_amount': float(discount),
        'tax_amount': float(tax),
        'total_amount': float(total),
        'line_items': line_items,
    }


def calc_boarding_fee(shelter, animal, check_in, check_out):
    species = animal['species']
    delta_sec = (check_out - check_in).total_seconds()
    if delta_sec <= 0:
        days = 0
    else:
        days = math.ceil(delta_sec / 86400)

    daily_fs = find_active_fee_schedule(shelter['id'], 'BOARDING_DAILY', species)
    daily = Decimal(str(daily_fs['amount'])) if daily_fs else Decimal('0')

    sn_fs = find_active_fee_schedule(shelter['id'], 'SPECIAL_NEEDS_SURCHARGE', species)
    sn_per_day = Decimal(str(sn_fs['amount'])) if sn_fs else Decimal('0')
    special_needs = animal.get('special_needs') or []
    sn_total_per_day = sn_per_day * Decimal(len(special_needs))

    effective_daily = daily + sn_total_per_day
    long_stay = days > 14
    if long_stay:
        effective_daily = effective_daily * Decimal('0.9')

    subtotal = (effective_daily * Decimal(days)).quantize(Decimal('0.01'),
                                                          rounding=ROUND_HALF_UP)
    tax_rate = Decimal(str(shelter.get('tax_rate', 0)))
    tax = (subtotal * tax_rate).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    total = (subtotal + tax).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    line_items = [
        {'description': f'Boarding daily ({species}) x{days}',
         'amount': float((daily * Decimal(days)).quantize(Decimal('0.01'),
                                                          rounding=ROUND_HALF_UP))},
    ]
    if len(special_needs) > 0:
        line_items.append({
            'description': f'Special needs surcharge x{len(special_needs)} x{days}d',
            'amount': float((sn_total_per_day * Decimal(days)).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)),
        })
    if long_stay:
        line_items.append({
            'description': 'Long stay 10% discount',
            'amount': float(((daily + sn_total_per_day) * Decimal(days) * Decimal('-0.1')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP)),
        })

    return {
        'subtotal': float(subtotal),
        'discount_amount': 0.0,
        'tax_amount': float(tax),
        'total_amount': float(total),
        'line_items': line_items,
        'duration_days': days,
    }


def create_invoice(shelter_id, related_type, related_id, fee_calc):
    now = now_iso()
    total = round_money(fee_calc['total_amount'])
    inv = {
        'id': gen_id(),
        'shelter_id': shelter_id,
        'related_resource_type': related_type,
        'related_resource_id': related_id,
        'line_items': fee_calc['line_items'],
        'subtotal': round_money(fee_calc['subtotal']),
        'discount_amount': round_money(fee_calc.get('discount_amount', 0)),
        'tax_amount': round_money(fee_calc['tax_amount']),
        'total_amount': total,
        'paid_amount': 0.0,
        'balance_due': total,
        'refund_amount': 0.0,
        'status': 'ISSUED',
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    STORE['fee_invoices'][inv['id']] = inv
    return inv


# ============ Compliance cascade ============

def apply_compliance_hold_effects(animal, severity):
    if severity in ('HIGH', 'CRITICAL'):
        animal['status'] = 'UNAVAILABLE'
        animal['adoption_eligible'] = False
        bump(animal)
        recompute_shelter_compliance(animal['shelter_id'])


def resolve_compliance_hold_effects(animal):
    if not has_active_hi_hold(animal['id']):
        if animal['status'] == 'UNAVAILABLE':
            animal['status'] = 'AVAILABLE'
    recompute_animal_derived(animal)
    recompute_shelter_compliance(animal['shelter_id'])


# ============ Boarding compatibility ============

def compute_boarding_match(animal, shelter_id):
    base = Decimal('100')
    penalty = Decimal('0')
    conflicts = []
    # Find currently CHECKED_IN at shelter
    checked_in_reservations = [
        r for r in STORE['boarding_reservations'].values()
        if r['shelter_id'] == shelter_id and r['status'] == 'CHECKED_IN'
        and r['animal_id'] != animal['id']
    ]
    for r in checked_in_reservations:
        other = STORE['animals'].get(r['animal_id'])
        if not other:
            continue
        if other['species'] != animal['species']:
            penalty += Decimal('10')
            if 'SPECIES_MISMATCH' not in conflicts:
                conflicts.append('SPECIES_MISMATCH')
        if animal['temperament'] == 'AGGRESSIVE' or other['temperament'] == 'AGGRESSIVE':
            penalty += Decimal('25')
            if (animal['temperament'] == 'AGGRESSIVE' and other['temperament'] == 'CALM') \
                    or (animal['temperament'] == 'CALM' and other['temperament'] == 'AGGRESSIVE'):
                if 'AGGRESSIVE_NEAR_CALM' not in conflicts:
                    conflicts.append('AGGRESSIVE_NEAR_CALM')
        if (animal['temperament'] == 'ENERGETIC' and other['temperament'] == 'CALM') \
                or (animal['temperament'] == 'CALM' and other['temperament'] == 'ENERGETIC'):
            penalty += Decimal('15')
    penalty += Decimal('5') * Decimal(len(animal.get('special_needs') or []))

    score = base - penalty
    if score < 0:
        score = Decimal('0')

    temperament = animal['temperament']
    species = animal['species']
    if temperament == 'AGGRESSIVE':
        zone = 'ISOLATION'
    elif temperament == 'ENERGETIC':
        zone = 'ACTIVE'
    elif species in ('CAT', 'BIRD', 'RABBIT'):
        zone = 'SMALL_ANIMAL'
    else:
        zone = 'GENERAL'

    return {
        'compatibility_score': float(score.quantize(Decimal('0.01'),
                                                     rounding=ROUND_HALF_UP)),
        'boarding_zone': zone,
        'conflict_flags': conflicts,
    }


# ============ Validation helpers ============

def require_fields(body, fields):
    missing = [f for f in fields if f not in body or body.get(f) is None]
    if missing:
        return err('ERR_INVALID_REQUEST', f'Missing fields: {", ".join(missing)}')
    return None


def check_version(resource, body):
    if body is not None and 'version' in body and body['version'] is not None:
        if body['version'] != resource['version']:
            return err('ERR_STALE_DATA', 'Version mismatch.')
    return None


# ============ Shelter endpoints ============

@app.route('/shelters', methods=['POST'])
def create_shelter():
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['name', 'address', 'boarding_capacity'])
    if r: return r
    try:
        cap = int(body['boarding_capacity'])
    except (ValueError, TypeError):
        return err('ERR_INVALID_REQUEST', 'Invalid boarding_capacity.')
    if cap < 0:
        return err('ERR_INVALID_REQUEST', 'boarding_capacity must be >= 0.')
    tax_rate = body.get('tax_rate', 0)
    try:
        tax_rate = float(tax_rate)
    except (ValueError, TypeError):
        return err('ERR_INVALID_REQUEST', 'Invalid tax_rate.')
    with _LOCK:
        now = now_iso()
        s = {
            'id': gen_id(),
            'name': body['name'],
            'address': body['address'],
            'boarding_capacity': cap,
            'tax_rate': tax_rate,
            'status': 'OPEN',
            'current_boarding_count': 0,
            'adoption_count': 0,
            'compliance_score': 100.0,
            'revenue_balance': 0.0,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['shelters'][s['id']] = s
        return envelope_success(s, 201)


@app.route('/shelters', methods=['GET'])
def list_shelters():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    items = sorted(STORE['shelters'].values(), key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/shelters/<shelter_id>', methods=['GET'])
def get_shelter(shelter_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    s = STORE['shelters'].get(shelter_id)
    if not s:
        return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
    return envelope_success(s)


@app.route('/shelters/<shelter_id>/suspend', methods=['POST'])
def suspend_shelter(shelter_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        s = STORE['shelters'].get(shelter_id)
        if not s:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(s, body)
        if v: return v
        if s['status'] != 'OPEN':
            return err('ERR_INVALID_STATE', 'Shelter is not open.')
        s['status'] = 'SUSPENDED'
        bump(s)
        return envelope_success(s)


@app.route('/shelters/<shelter_id>/reopen', methods=['POST'])
def reopen_shelter(shelter_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        s = STORE['shelters'].get(shelter_id)
        if not s:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(s, body)
        if v: return v
        if s['status'] != 'SUSPENDED':
            return err('ERR_INVALID_STATE', 'Shelter is not suspended.')
        if has_active_critical_hold_in_shelter(shelter_id):
            return err('ERR_COMPLIANCE_HOLD_ACTIVE',
                       'Active CRITICAL compliance hold prevents reopen.')
        s['status'] = 'OPEN'
        bump(s)
        return envelope_success(s)


# ============ Animal endpoints ============

@app.route('/animals', methods=['POST'])
def create_animal():
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['shelter_id', 'name', 'species', 'breed',
                              'age_months', 'weight_kg', 'temperament'])
    if r: return r
    with _LOCK:
        shelter = STORE['shelters'].get(body['shelter_id'])
        if not shelter:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        if body['species'] not in SPECIES_SET:
            return err('ERR_INVALID_REQUEST', 'Invalid species.')
        if body['temperament'] not in TEMPERAMENT_SET:
            return err('ERR_INVALID_REQUEST', 'Invalid temperament.')
        try:
            age = int(body['age_months'])
            weight = float(body['weight_kg'])
        except (ValueError, TypeError):
            return err('ERR_INVALID_REQUEST', 'Invalid numeric field.')
        if age < 0 or weight < 0:
            return err('ERR_INVALID_REQUEST', 'Numeric field must be non-negative.')
        sn = body.get('special_needs') or []
        if not isinstance(sn, list):
            return err('ERR_INVALID_REQUEST', 'special_needs must be list.')
        for t in sn:
            if t not in SPECIAL_NEEDS_SET:
                return err('ERR_INVALID_REQUEST', f'Invalid special_needs tag: {t}')
        now = now_iso()
        a = {
            'id': gen_id(),
            'shelter_id': body['shelter_id'],
            'name': body['name'],
            'species': body['species'],
            'breed': body['breed'],
            'age_months': age,
            'weight_kg': weight,
            'temperament': body['temperament'],
            'special_needs': sn,
            'status': 'INTAKE',
            'vaccination_compliant': False,
            'adoption_eligible': False,
            'boarding_compatible_tags': [],
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['animals'][a['id']] = a
        a['vaccination_compliant'] = compute_vaccination_compliance(
            a['id'], a['species'], for_boarding=False)
        a['boarding_compatible_tags'] = compute_boarding_compatible_tags(a)
        recompute_shelter_compliance(a['shelter_id'])
        return envelope_success(a, 201)


@app.route('/animals', methods=['GET'])
def list_animals():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    items = list(STORE['animals'].values())
    sid = request.args.get('shelter_id')
    status = request.args.get('status')
    species = request.args.get('species')
    if sid:
        items = [a for a in items if a['shelter_id'] == sid]
    if status:
        items = [a for a in items if a['status'] == status]
    if species:
        items = [a for a in items if a['species'] == species]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/animals/<animal_id>', methods=['GET'])
def get_animal(animal_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    a = STORE['animals'].get(animal_id)
    if not a:
        return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
    return envelope_success(a)


@app.route('/animals/<animal_id>', methods=['PATCH'])
def update_animal(animal_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        a = STORE['animals'].get(animal_id)
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(a, body)
        if v: return v
        for f in ('name', 'breed'):
            if f in body and body[f] is not None:
                a[f] = body[f]
        if 'age_months' in body and body['age_months'] is not None:
            try:
                a['age_months'] = int(body['age_months'])
            except (ValueError, TypeError):
                return err('ERR_INVALID_REQUEST', 'Invalid age_months.')
        if 'weight_kg' in body and body['weight_kg'] is not None:
            try:
                a['weight_kg'] = float(body['weight_kg'])
            except (ValueError, TypeError):
                return err('ERR_INVALID_REQUEST', 'Invalid weight_kg.')
        if 'temperament' in body and body['temperament'] is not None:
            if body['temperament'] not in TEMPERAMENT_SET:
                return err('ERR_INVALID_REQUEST', 'Invalid temperament.')
            a['temperament'] = body['temperament']
        if 'special_needs' in body and body['special_needs'] is not None:
            sn = body['special_needs']
            if not isinstance(sn, list):
                return err('ERR_INVALID_REQUEST', 'special_needs must be list.')
            for t in sn:
                if t not in SPECIAL_NEEDS_SET:
                    return err('ERR_INVALID_REQUEST', f'Invalid special_needs tag: {t}')
            a['special_needs'] = sn
        recompute_animal_derived(a)
        return envelope_success(a)


@app.route('/animals/<animal_id>/make-available', methods=['POST'])
def make_available(animal_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        a = STORE['animals'].get(animal_id)
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(a, body)
        if v: return v
        if a['status'] != 'INTAKE':
            return err('ERR_INVALID_STATE', 'Animal not in INTAKE state.')
        a['vaccination_compliant'] = compute_vaccination_compliance(
            a['id'], a['species'], for_boarding=False)
        if not a['vaccination_compliant']:
            return err('ERR_VACCINATION_NOT_COMPLIANT',
                       'Animal vaccination not compliant.')
        if has_active_hi_hold(a['id']):
            return err('ERR_COMPLIANCE_HOLD_ACTIVE',
                       'Active HIGH/CRITICAL hold blocks availability.')
        a['status'] = 'AVAILABLE'
        recompute_animal_derived(a)
        recompute_shelter_compliance(a['shelter_id'])
        return envelope_success(a)


# ============ Vaccination records ============

@app.route('/vaccination-records', methods=['POST'])
def create_vax():
    user_id, role, er = check_auth(['Veterinarian'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['animal_id', 'vaccine_type',
                              'administered_date', 'expiry_date'])
    if r: return r
    with _LOCK:
        a = STORE['animals'].get(body['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        if body['vaccine_type'] not in VACCINE_TYPES:
            return err('ERR_INVALID_REQUEST', 'Invalid vaccine_type.')
        adm = parse_date_only(body['administered_date'])
        exp = parse_date_only(body['expiry_date'])
        if adm is None or exp is None:
            return err('ERR_INVALID_REQUEST', 'Invalid dates.')
        if exp < adm:
            return err('ERR_INVALID_DATES', 'expiry_date must be >= administered_date.')
        now = now_iso()
        rec = {
            'id': gen_id(),
            'animal_id': body['animal_id'],
            'vaccine_type': body['vaccine_type'],
            'administered_date': body['administered_date'],
            'expiry_date': body['expiry_date'],
            'administered_by': body.get('administered_by'),
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['vaccination_records'][rec['id']] = rec
        recompute_animal_derived(a)
        recompute_shelter_compliance(a['shelter_id'])
        return envelope_success(rec, 201)


@app.route('/vaccination-records', methods=['GET'])
def list_vax():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    items = list(STORE['vaccination_records'].values())
    aid = request.args.get('animal_id')
    vtype = request.args.get('vaccine_type')
    if aid:
        items = [x for x in items if x['animal_id'] == aid]
    if vtype:
        items = [x for x in items if x['vaccine_type'] == vtype]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/vaccination-records/<record_id>', methods=['GET'])
def get_vax(record_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    rec = STORE['vaccination_records'].get(record_id)
    if not rec:
        return err('ERR_VACCINATION_RECORD_NOT_FOUND', 'Not found.')
    return envelope_success(rec)


# ============ Adopters ============

@app.route('/adopters', methods=['POST'])
def create_adopter():
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['shelter_id', 'full_name', 'email', 'phone',
                              'home_type', 'has_yard', 'has_other_pets'])
    if r: return r
    with _LOCK:
        s = STORE['shelters'].get(body['shelter_id'])
        if not s:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        if body['home_type'] not in HOME_TYPE_SET:
            return err('ERR_INVALID_REQUEST', 'Invalid home_type.')
        if not isinstance(body['has_yard'], bool) or not isinstance(body['has_other_pets'], bool):
            return err('ERR_INVALID_REQUEST', 'Invalid boolean fields.')
        ops = body.get('other_pet_species') or []
        if not isinstance(ops, list):
            return err('ERR_INVALID_REQUEST', 'other_pet_species must be list.')
        now = now_iso()
        ad = {
            'id': gen_id(),
            'shelter_id': body['shelter_id'],
            'full_name': body['full_name'],
            'email': body['email'],
            'phone': body['phone'],
            'home_type': body['home_type'],
            'has_yard': body['has_yard'],
            'has_other_pets': body['has_other_pets'],
            'other_pet_species': ops,
            'status': 'ACTIVE',
            'adoption_history_count': 0,
            'home_visit_passed': False,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['adopters'][ad['id']] = ad
        return envelope_success(ad, 201)


@app.route('/adopters', methods=['GET'])
def list_adopters():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    items = list(STORE['adopters'].values())
    sid = request.args.get('shelter_id')
    st = request.args.get('status')
    if sid:
        items = [x for x in items if x['shelter_id'] == sid]
    if st:
        items = [x for x in items if x['status'] == st]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/adopters/<adopter_id>', methods=['GET'])
def get_adopter(adopter_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    ad = STORE['adopters'].get(adopter_id)
    if not ad:
        return err('ERR_ADOPTER_NOT_FOUND', 'Adopter not found.')
    return envelope_success(ad)


@app.route('/adopters/<adopter_id>', methods=['PATCH'])
def update_adopter(adopter_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        ad = STORE['adopters'].get(adopter_id)
        if not ad:
            return err('ERR_ADOPTER_NOT_FOUND', 'Adopter not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(ad, body)
        if v: return v
        for f in ('full_name', 'email', 'phone'):
            if f in body and body[f] is not None:
                ad[f] = body[f]
        if 'home_type' in body and body['home_type'] is not None:
            if body['home_type'] not in HOME_TYPE_SET:
                return err('ERR_INVALID_REQUEST', 'Invalid home_type.')
            ad['home_type'] = body['home_type']
        if 'has_yard' in body and body['has_yard'] is not None:
            if not isinstance(body['has_yard'], bool):
                return err('ERR_INVALID_REQUEST', 'has_yard must be boolean.')
            ad['has_yard'] = body['has_yard']
        if 'has_other_pets' in body and body['has_other_pets'] is not None:
            if not isinstance(body['has_other_pets'], bool):
                return err('ERR_INVALID_REQUEST', 'has_other_pets must be boolean.')
            ad['has_other_pets'] = body['has_other_pets']
        if 'other_pet_species' in body and body['other_pet_species'] is not None:
            if not isinstance(body['other_pet_species'], list):
                return err('ERR_INVALID_REQUEST', 'other_pet_species must be list.')
            ad['other_pet_species'] = body['other_pet_species']
        bump(ad)
        return envelope_success(ad)


@app.route('/adopters/<adopter_id>/blacklist', methods=['POST'])
def blacklist_adopter(adopter_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        ad = STORE['adopters'].get(adopter_id)
        if not ad:
            return err('ERR_ADOPTER_NOT_FOUND', 'Adopter not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(ad, body)
        if v: return v
        if ad['status'] == 'BLACKLISTED':
            return err('ERR_INVALID_STATE', 'Already blacklisted.')
        ad['status'] = 'BLACKLISTED'
        bump(ad)
        # Withdraw applications in SUBMITTED/UNDER_REVIEW
        for app_rec in STORE['adoption_applications'].values():
            if app_rec['adopter_id'] == adopter_id and app_rec['status'] in (
                    'SUBMITTED', 'UNDER_REVIEW'):
                app_rec['status'] = 'WITHDRAWN'
                bump(app_rec)
                # Cancel associated home visits
                for hv in STORE['home_visits'].values():
                    if hv['application_id'] == app_rec['id'] and hv['status'] == 'SCHEDULED':
                        hv['status'] = 'CANCELLED'
                        bump(hv)
        return envelope_success(ad)


# ============ Adoption Applications ============

@app.route('/adoption-applications', methods=['POST'])
def create_application():
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['animal_id', 'adopter_id', 'reason'])
    if r: return r
    with _LOCK:
        a = STORE['animals'].get(body['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        ad = STORE['adopters'].get(body['adopter_id'])
        if not ad:
            return err('ERR_ADOPTER_NOT_FOUND', 'Adopter not found.')
        shelter = STORE['shelters'].get(a['shelter_id'])
        if not shelter:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        if shelter['status'] != 'OPEN':
            return err('ERR_SHELTER_SUSPENDED', 'Shelter suspended.')
        if a['status'] != 'AVAILABLE':
            return err('ERR_ANIMAL_NOT_AVAILABLE', 'Animal not available.')
        if ad['status'] != 'ACTIVE':
            return err('ERR_ADOPTER_BLACKLISTED', 'Adopter not active.')
        now = now_iso()
        app_rec = {
            'id': gen_id(),
            'animal_id': a['id'],
            'adopter_id': ad['id'],
            'shelter_id': a['shelter_id'],
            'reason': body['reason'],
            'status': 'SUBMITTED',
            'reviewer_id': None,
            'approver_id': None,
            'animal_version': None,
            'adopter_version': None,
            'fee_invoice_id': None,
            'rejection_reason': None,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['adoption_applications'][app_rec['id']] = app_rec
        return envelope_success(app_rec, 201)


@app.route('/adoption-applications', methods=['GET'])
def list_applications():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    items = list(STORE['adoption_applications'].values())
    aid = request.args.get('animal_id')
    adid = request.args.get('adopter_id')
    sid = request.args.get('shelter_id')
    st = request.args.get('status')
    if aid:
        items = [x for x in items if x['animal_id'] == aid]
    if adid:
        items = [x for x in items if x['adopter_id'] == adid]
    if sid:
        items = [x for x in items if x['shelter_id'] == sid]
    if st:
        items = [x for x in items if x['status'] == st]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/adoption-applications/<app_id>', methods=['GET'])
def get_application(app_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    app_rec = STORE['adoption_applications'].get(app_id)
    if not app_rec:
        return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
    return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/start-review', methods=['POST'])
def start_review(app_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] != 'SUBMITTED':
            return err('ERR_INVALID_STATE', 'Application not in SUBMITTED.')
        a = STORE['animals'].get(app_rec['animal_id'])
        ad = STORE['adopters'].get(app_rec['adopter_id'])
        app_rec['status'] = 'UNDER_REVIEW'
        app_rec['reviewer_id'] = user_id
        app_rec['animal_version'] = a['version']
        app_rec['adopter_version'] = ad['version']
        bump(app_rec)
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/require-home-visit', methods=['POST'])
def require_home_visit(app_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] != 'UNDER_REVIEW':
            return err('ERR_INVALID_STATE', 'Must be UNDER_REVIEW.')
        if app_rec['reviewer_id'] != user_id:
            return err('ERR_REVIEWER_MISMATCH', 'Only the reviewer may act.')
        app_rec['status'] = 'HOME_VISIT_REQUIRED'
        bump(app_rec)
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/complete-review', methods=['POST'])
def complete_review(app_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] not in ('UNDER_REVIEW', 'HOME_VISIT_REQUIRED'):
            return err('ERR_INVALID_STATE', 'Invalid state for complete-review.')
        if app_rec['reviewer_id'] != user_id:
            return err('ERR_REVIEWER_MISMATCH', 'Only reviewer may act.')
        a = STORE['animals'].get(app_rec['animal_id'])
        ad = STORE['adopters'].get(app_rec['adopter_id'])
        if a['species'] == 'DOG' and not ad.get('home_visit_passed'):
            return err('ERR_HOME_VISIT_REQUIRED', 'Home visit required for dog.')
        app_rec['status'] = 'REVIEWED'
        bump(app_rec)
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/approve', methods=['POST'])
def approve_application(app_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] != 'REVIEWED':
            return err('ERR_INVALID_STATE', 'Must be REVIEWED.')
        if user_id == app_rec['reviewer_id']:
            return err('ERR_SELF_APPROVAL', 'Approver must differ from reviewer.')
        a = STORE['animals'].get(app_rec['animal_id'])
        ad = STORE['adopters'].get(app_rec['adopter_id'])
        shelter = STORE['shelters'].get(app_rec['shelter_id'])
        if not shelter or shelter['status'] != 'OPEN':
            return err('ERR_SHELTER_SUSPENDED', 'Shelter not open.')
        if app_rec['animal_version'] != a['version']:
            return err('ERR_STALE_ANIMAL_DATA', 'Animal changed since review.')
        if app_rec['adopter_version'] != ad['version']:
            return err('ERR_STALE_ADOPTER_DATA', 'Adopter changed since review.')
        if a['status'] != 'AVAILABLE':
            return err('ERR_ANIMAL_NOT_AVAILABLE', 'Animal no longer available.')
        # Only one APPROVED/COMPLETED per animal
        for other in STORE['adoption_applications'].values():
            if other['id'] == app_rec['id']:
                continue
            if other['animal_id'] == a['id'] and other['status'] in ('APPROVED', 'COMPLETED'):
                return err('ERR_ANIMAL_NOT_AVAILABLE',
                           'Another application is APPROVED/COMPLETED.')
        app_rec['status'] = 'APPROVED'
        app_rec['approver_id'] = user_id
        a['status'] = 'ADOPTION_PENDING'
        a['adoption_eligible'] = False
        bump(a)
        fee = calc_adoption_fee(shelter, a, ad)
        inv = create_invoice(shelter['id'], 'adoption_application',
                             app_rec['id'], fee)
        app_rec['fee_invoice_id'] = inv['id']
        bump(app_rec)
        recompute_shelter_compliance(shelter['id'])
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/reject', methods=['POST'])
def reject_application(app_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        reason = body.get('rejection_reason')
        if not reason:
            return err('ERR_INVALID_REQUEST', 'rejection_reason required.')
        if app_rec['status'] not in ('REVIEWED', 'UNDER_REVIEW', 'HOME_VISIT_REQUIRED',
                                     'HOME_VISIT_SCHEDULED', 'SUBMITTED'):
            return err('ERR_INVALID_STATE', 'Cannot reject in this state.')
        app_rec['status'] = 'REJECTED'
        app_rec['rejection_reason'] = reason
        bump(app_rec)
        a = STORE['animals'].get(app_rec['animal_id'])
        if a and a['status'] == 'ADOPTION_PENDING':
            a['status'] = 'AVAILABLE'
            recompute_animal_derived(a)
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/complete', methods=['POST'])
def complete_application(app_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] != 'APPROVED':
            return err('ERR_INVALID_STATE', 'Application not APPROVED.')
        inv_id = app_rec.get('fee_invoice_id')
        inv = STORE['fee_invoices'].get(inv_id) if inv_id else None
        if not inv or inv['status'] != 'PAID':
            return err('ERR_FEE_NOT_PAID', 'Fee invoice not paid.')
        a = STORE['animals'].get(app_rec['animal_id'])
        ad = STORE['adopters'].get(app_rec['adopter_id'])
        shelter = STORE['shelters'].get(app_rec['shelter_id'])
        app_rec['status'] = 'COMPLETED'
        bump(app_rec)
        if a:
            a['status'] = 'ADOPTED'
            a['adoption_eligible'] = False
            bump(a)
        if ad:
            ad['adoption_history_count'] = ad.get('adoption_history_count', 0) + 1
            bump(ad)
        if shelter:
            shelter['adoption_count'] = shelter.get('adoption_count', 0) + 1
            bump(shelter)
            recompute_shelter_compliance(shelter['id'])
        return envelope_success(app_rec)


@app.route('/adoption-applications/<app_id>/withdraw', methods=['POST'])
def withdraw_application(app_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        app_rec = STORE['adoption_applications'].get(app_id)
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(app_rec, body)
        if v: return v
        if app_rec['status'] in ('COMPLETED', 'REJECTED', 'WITHDRAWN'):
            return err('ERR_INVALID_STATE', 'Cannot withdraw terminated application.')
        if app_rec['status'] == 'APPROVED':
            return err('ERR_INVALID_STATE', 'Cannot withdraw approved application.')
        app_rec['status'] = 'WITHDRAWN'
        bump(app_rec)
        a = STORE['animals'].get(app_rec['animal_id'])
        if a and a['status'] == 'ADOPTION_PENDING':
            a['status'] = 'AVAILABLE'
            recompute_animal_derived(a)
        for hv in STORE['home_visits'].values():
            if hv['application_id'] == app_rec['id'] and hv['status'] == 'SCHEDULED':
                hv['status'] = 'CANCELLED'
                bump(hv)
        return envelope_success(app_rec)


# ============ Home visits ============

@app.route('/home-visits', methods=['POST'])
def create_home_visit():
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['adopter_id', 'application_id', 'scheduled_date'])
    if r: return r
    with _LOCK:
        ad = STORE['adopters'].get(body['adopter_id'])
        if not ad:
            return err('ERR_ADOPTER_NOT_FOUND', 'Adopter not found.')
        app_rec = STORE['adoption_applications'].get(body['application_id'])
        if not app_rec:
            return err('ERR_APPLICATION_NOT_FOUND', 'Application not found.')
        sched = parse_date(body['scheduled_date'])
        if sched is None:
            return err('ERR_INVALID_REQUEST', 'Invalid scheduled_date.')
        if app_rec['status'] not in ('HOME_VISIT_REQUIRED', 'UNDER_REVIEW'):
            return err('ERR_INVALID_STATE', 'Application must require home visit.')
        now = now_iso()
        hv = {
            'id': gen_id(),
            'adopter_id': ad['id'],
            'application_id': app_rec['id'],
            'case_worker_id': user_id,
            'scheduled_date': body['scheduled_date'],
            'status': 'SCHEDULED',
            'overall_score': None,
            'outcome': None,
            'notes': None,
            'yard_adequate': None,
            'space_adequate': None,
            'safety_hazards_found': None,
            'existing_pets_compatible': None,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['home_visits'][hv['id']] = hv
        app_rec['status'] = 'HOME_VISIT_SCHEDULED'
        bump(app_rec)
        return envelope_success(hv, 201)


@app.route('/home-visits', methods=['GET'])
def list_home_visits():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    items = list(STORE['home_visits'].values())
    aid = request.args.get('adopter_id')
    app_id = request.args.get('application_id')
    st = request.args.get('status')
    if aid:
        items = [x for x in items if x['adopter_id'] == aid]
    if app_id:
        items = [x for x in items if x['application_id'] == app_id]
    if st:
        items = [x for x in items if x['status'] == st]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/home-visits/<hv_id>', methods=['GET'])
def get_home_visit(hv_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    hv = STORE['home_visits'].get(hv_id)
    if not hv:
        return err('ERR_HOME_VISIT_NOT_FOUND', 'Not found.')
    return envelope_success(hv)


@app.route('/home-visits/<hv_id>/complete', methods=['POST'])
def complete_home_visit(hv_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        hv = STORE['home_visits'].get(hv_id)
        if not hv:
            return err('ERR_HOME_VISIT_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(hv, body)
        if v: return v
        if hv['status'] != 'SCHEDULED':
            return err('ERR_INVALID_STATE', 'Home visit not scheduled.')
        if hv['case_worker_id'] != user_id:
            return err('ERR_ASSESSOR_MISMATCH', 'Only assigned case worker.')
        r = require_fields(body, ['yard_adequate', 'space_adequate',
                                  'safety_hazards_found',
                                  'existing_pets_compatible', 'notes'])
        if r: return r
        for f in ('yard_adequate', 'space_adequate',
                  'safety_hazards_found', 'existing_pets_compatible'):
            if not isinstance(body[f], bool):
                return err('ERR_INVALID_REQUEST', f'{f} must be bool.')
        app_rec = STORE['adoption_applications'].get(hv['application_id'])
        a = STORE['animals'].get(app_rec['animal_id']) if app_rec else None
        species = a['species'] if a else 'DOG'

        yard_w = 25
        space_w = 30
        if species in ('CAT', 'BIRD', 'RABBIT'):
            yard_w = 0
            space_w = 45
        safety_w = 25
        pets_w = 20

        score = 0
        if body['yard_adequate']:
            score += yard_w
        if body['space_adequate']:
            score += space_w
        if not body['safety_hazards_found']:
            score += safety_w
        if body['existing_pets_compatible']:
            score += pets_w

        if score >= 70:
            outcome = 'PASS'
        elif score >= 50:
            outcome = 'CONDITIONAL_PASS'
        else:
            outcome = 'FAIL'

        hv['yard_adequate'] = body['yard_adequate']
        hv['space_adequate'] = body['space_adequate']
        hv['safety_hazards_found'] = body['safety_hazards_found']
        hv['existing_pets_compatible'] = body['existing_pets_compatible']
        hv['notes'] = body['notes']
        hv['overall_score'] = score
        hv['outcome'] = outcome
        hv['status'] = 'COMPLETED'
        bump(hv)

        ad = STORE['adopters'].get(hv['adopter_id'])
        if outcome in ('PASS', 'CONDITIONAL_PASS'):
            if ad:
                ad['home_visit_passed'] = True
                bump(ad)
            if app_rec and app_rec['status'] == 'HOME_VISIT_SCHEDULED':
                app_rec['status'] = 'REVIEWED'
                bump(app_rec)
        else:
            if app_rec:
                app_rec['status'] = 'REJECTED'
                app_rec['rejection_reason'] = 'Home visit failed'
                bump(app_rec)
                if a and a['status'] == 'ADOPTION_PENDING':
                    a['status'] = 'AVAILABLE'
                    recompute_animal_derived(a)
        return envelope_success(hv)


@app.route('/home-visits/<hv_id>/cancel', methods=['POST'])
def cancel_home_visit(hv_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        hv = STORE['home_visits'].get(hv_id)
        if not hv:
            return err('ERR_HOME_VISIT_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(hv, body)
        if v: return v
        if hv['status'] != 'SCHEDULED':
            return err('ERR_INVALID_STATE', 'Not scheduled.')
        hv['status'] = 'CANCELLED'
        bump(hv)
        app_rec = STORE['adoption_applications'].get(hv['application_id'])
        if app_rec and app_rec['status'] == 'HOME_VISIT_SCHEDULED':
            app_rec['status'] = 'HOME_VISIT_REQUIRED'
            bump(app_rec)
        return envelope_success(hv)


# ============ Boarding reservations ============

@app.route('/boarding-reservations', methods=['POST'])
def create_reservation():
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['shelter_id', 'animal_id', 'owner_name',
                              'owner_contact', 'check_in_date', 'check_out_date'])
    if r: return r
    with _LOCK:
        shelter = STORE['shelters'].get(body['shelter_id'])
        if not shelter:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        a = STORE['animals'].get(body['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        if shelter['status'] != 'OPEN':
            return err('ERR_SHELTER_SUSPENDED', 'Shelter suspended.')
        ci = parse_date(body['check_in_date'])
        co = parse_date(body['check_out_date'])
        if ci is None or co is None:
            return err('ERR_INVALID_REQUEST', 'Invalid dates.')
        if co <= ci:
            return err('ERR_INVALID_DATES', 'check_out must be after check_in.')
        delta = (co - ci).total_seconds()
        days = math.ceil(delta / 86400) if delta > 0 else 0
        now = now_iso()
        res = {
            'id': gen_id(),
            'shelter_id': shelter['id'],
            'animal_id': a['id'],
            'owner_name': body['owner_name'],
            'owner_contact': body['owner_contact'],
            'check_in_date': body['check_in_date'],
            'check_out_date': body['check_out_date'],
            'special_instructions': body.get('special_instructions'),
            'status': 'REQUESTED',
            'duration_days': days,
            'actual_check_in': None,
            'actual_check_out': None,
            'fee_invoice_id': None,
            'boarding_match_id': None,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['boarding_reservations'][res['id']] = res
        return envelope_success(res, 201)


@app.route('/boarding-reservations', methods=['GET'])
def list_reservations():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    items = list(STORE['boarding_reservations'].values())
    sid = request.args.get('shelter_id')
    aid = request.args.get('animal_id')
    st = request.args.get('status')
    if sid:
        items = [x for x in items if x['shelter_id'] == sid]
    if aid:
        items = [x for x in items if x['animal_id'] == aid]
    if st:
        items = [x for x in items if x['status'] == st]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/boarding-reservations/<res_id>', methods=['GET'])
def get_reservation(res_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    res = STORE['boarding_reservations'].get(res_id)
    if not res:
        return err('ERR_RESERVATION_NOT_FOUND', 'Not found.')
    return envelope_success(res)


def _date_overlap(a_start, a_end, b_start, b_end):
    return a_start < b_end and b_start < a_end


@app.route('/boarding-reservations/<res_id>/confirm', methods=['POST'])
def confirm_reservation(res_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        res = STORE['boarding_reservations'].get(res_id)
        if not res:
            return err('ERR_RESERVATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(res, body)
        if v: return v
        if res['status'] != 'REQUESTED':
            return err('ERR_INVALID_STATE', 'Not in REQUESTED.')
        shelter = STORE['shelters'].get(res['shelter_id'])
        if not shelter or shelter['status'] != 'OPEN':
            return err('ERR_SHELTER_SUSPENDED', 'Shelter not open.')
        a = STORE['animals'].get(res['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        if not compute_vaccination_compliance(a['id'], a['species'], for_boarding=True):
            return err('ERR_VACCINATION_NOT_COMPLIANT', 'Vaccination not compliant.')
        if shelter['current_boarding_count'] >= shelter['boarding_capacity']:
            return err('ERR_BOARDING_CAPACITY_FULL', 'Capacity full.')
        # Check overlap
        ci = parse_date(res['check_in_date'])
        co = parse_date(res['check_out_date'])
        for other in STORE['boarding_reservations'].values():
            if other['id'] == res['id']:
                continue
            if other['animal_id'] != a['id']:
                continue
            if other['status'] not in ('CONFIRMED', 'CHECKED_IN'):
                continue
            o_ci = parse_date(other['check_in_date'])
            o_co = parse_date(other['check_out_date'])
            if _date_overlap(ci, co, o_ci, o_co):
                return err('ERR_BOARDING_DATE_OVERLAP', 'Date overlap.')
        res['status'] = 'CONFIRMED'
        # Create boarding match
        match_data = compute_boarding_match(a, shelter['id'])
        match_now = now_iso()
        match = {
            'id': gen_id(),
            'reservation_id': res['id'],
            'animal_id': a['id'],
            'shelter_id': shelter['id'],
            'compatibility_score': match_data['compatibility_score'],
            'boarding_zone': match_data['boarding_zone'],
            'conflict_flags': match_data['conflict_flags'],
            'created_at': match_now,
        }
        STORE['boarding_matches'][match['id']] = match
        res['boarding_match_id'] = match['id']
        # Create fee invoice
        fee = calc_boarding_fee(shelter, a, ci, co)
        inv = create_invoice(shelter['id'], 'boarding_reservation',
                             res['id'], fee)
        res['fee_invoice_id'] = inv['id']
        bump(res)
        return envelope_success(res)


@app.route('/boarding-reservations/<res_id>/check-in', methods=['POST'])
def check_in_reservation(res_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        res = STORE['boarding_reservations'].get(res_id)
        if not res:
            return err('ERR_RESERVATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(res, body)
        if v: return v
        if res['status'] != 'CONFIRMED':
            return err('ERR_INVALID_STATE', 'Not in CONFIRMED.')
        a = STORE['animals'].get(res['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        if not compute_vaccination_compliance(a['id'], a['species'], for_boarding=True):
            return err('ERR_VACCINATION_NOT_COMPLIANT', 'Vaccination expired.')
        if has_active_hi_hold(a['id']):
            return err('ERR_COMPLIANCE_HOLD_ACTIVE', 'Active HIGH/CRITICAL hold.')
        res['status'] = 'CHECKED_IN'
        res['actual_check_in'] = now_iso()
        bump(res)
        shelter = STORE['shelters'].get(res['shelter_id'])
        if shelter:
            shelter['current_boarding_count'] += 1
            bump(shelter)
        # Transition animal to BOARDING if shelter-owned (AVAILABLE or INTAKE)
        if a['status'] in ('AVAILABLE', 'INTAKE'):
            a['status'] = 'BOARDING'
            recompute_animal_derived(a)
        return envelope_success(res)


@app.route('/boarding-reservations/<res_id>/check-out', methods=['POST'])
def check_out_reservation(res_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        res = STORE['boarding_reservations'].get(res_id)
        if not res:
            return err('ERR_RESERVATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(res, body)
        if v: return v
        if res['status'] != 'CHECKED_IN':
            return err('ERR_INVALID_STATE', 'Not in CHECKED_IN.')
        now = now_iso()
        res['actual_check_out'] = now
        actual_ci = parse_date(res['actual_check_in']) if res.get('actual_check_in') else parse_date(res['check_in_date'])
        actual_co = parse_date(now)
        planned_ci = parse_date(res['check_in_date'])
        planned_co = parse_date(res['check_out_date'])
        delta = (actual_co - actual_ci).total_seconds()
        actual_days = math.ceil(delta / 86400) if delta > 0 else 0
        res['duration_days'] = actual_days
        # Recalc fee if actual differs
        shelter = STORE['shelters'].get(res['shelter_id'])
        a = STORE['animals'].get(res['animal_id'])
        if res.get('fee_invoice_id') and shelter and a:
            inv = STORE['fee_invoices'].get(res['fee_invoice_id'])
            if inv and inv['status'] in ('ISSUED', 'DRAFT', 'PARTIALLY_PAID'):
                planned_delta = (planned_co - planned_ci).total_seconds()
                planned_days = math.ceil(planned_delta / 86400) if planned_delta > 0 else 0
                if actual_days != planned_days:
                    fee = calc_boarding_fee(shelter, a, actual_ci, actual_co)
                    inv['line_items'] = fee['line_items']
                    inv['subtotal'] = round_money(fee['subtotal'])
                    inv['tax_amount'] = round_money(fee['tax_amount'])
                    inv['total_amount'] = round_money(fee['total_amount'])
                    inv['balance_due'] = round_money(
                        inv['total_amount'] - inv['paid_amount'])
                    bump(inv)
        res['status'] = 'CHECKED_OUT'
        bump(res)
        if shelter:
            shelter['current_boarding_count'] = max(
                0, shelter['current_boarding_count'] - 1)
            bump(shelter)
        if a and a['status'] == 'BOARDING':
            a['status'] = 'AVAILABLE'
            recompute_animal_derived(a)
        return envelope_success(res)


@app.route('/boarding-reservations/<res_id>/cancel', methods=['POST'])
def cancel_reservation(res_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        res = STORE['boarding_reservations'].get(res_id)
        if not res:
            return err('ERR_RESERVATION_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(res, body)
        if v: return v
        if res['status'] not in ('REQUESTED', 'CONFIRMED'):
            return err('ERR_INVALID_STATE', 'Cannot cancel.')
        was_confirmed = res['status'] == 'CONFIRMED'
        res['status'] = 'CANCELLED'
        bump(res)
        if was_confirmed and res.get('boarding_match_id'):
            match = STORE['boarding_matches'].get(res['boarding_match_id'])
            if match:
                match['voided'] = True
        if res.get('fee_invoice_id'):
            inv = STORE['fee_invoices'].get(res['fee_invoice_id'])
            if inv:
                if inv['status'] == 'ISSUED':
                    inv['status'] = 'VOID'
                    bump(inv)
                elif inv['status'] == 'PAID':
                    # initiate refund
                    inv['refund_amount'] = inv['paid_amount']
                    inv['status'] = 'REFUNDED'
                    shelter = STORE['shelters'].get(res['shelter_id'])
                    if shelter:
                        shelter['revenue_balance'] = round_money(
                            shelter['revenue_balance'] - inv['paid_amount'])
                        bump(shelter)
                    bump(inv)
                elif inv['status'] == 'PARTIALLY_PAID':
                    inv['refund_amount'] = inv['paid_amount']
                    inv['status'] = 'REFUNDED'
                    shelter = STORE['shelters'].get(res['shelter_id'])
                    if shelter:
                        shelter['revenue_balance'] = round_money(
                            shelter['revenue_balance'] - inv['paid_amount'])
                        bump(shelter)
                    bump(inv)
        return envelope_success(res)


# ============ Fee invoices ============

@app.route('/fee-invoices', methods=['GET'])
def list_invoices():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    items = list(STORE['fee_invoices'].values())
    sid = request.args.get('shelter_id')
    st = request.args.get('status')
    if sid:
        items = [x for x in items if x['shelter_id'] == sid]
    if st:
        items = [x for x in items if x['status'] == st]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/fee-invoices/<invoice_id>', methods=['GET'])
def get_invoice(invoice_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    inv = STORE['fee_invoices'].get(invoice_id)
    if not inv:
        return err('ERR_INVOICE_NOT_FOUND', 'Not found.')
    return envelope_success(inv)


@app.route('/fee-invoices/<invoice_id>/pay', methods=['POST'])
def pay_invoice(invoice_id):
    user_id, role, er = check_auth(['CaseWorker'])
    if er: return er
    with _LOCK:
        inv = STORE['fee_invoices'].get(invoice_id)
        if not inv:
            return err('ERR_INVOICE_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(inv, body)
        if v: return v
        if inv['status'] not in ('ISSUED', 'PARTIALLY_PAID'):
            return err('ERR_INVALID_STATE', 'Invoice not payable.')
        amount = body.get('amount')
        if amount is None:
            return err('ERR_INVALID_REQUEST', 'amount required.')
        try:
            amount_d = Decimal(str(amount))
        except Exception:
            return err('ERR_PAYMENT_AMOUNT_INVALID', 'Invalid amount.')
        if amount_d <= 0:
            return err('ERR_PAYMENT_AMOUNT_INVALID', 'Amount must be positive.')
        balance = Decimal(str(inv['balance_due']))
        if amount_d > balance:
            return err('ERR_PAYMENT_AMOUNT_INVALID',
                       'Amount exceeds balance due.')
        amount_d = amount_d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        new_paid = Decimal(str(inv['paid_amount'])) + amount_d
        new_paid = new_paid.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        total = Decimal(str(inv['total_amount'])).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP)
        inv['paid_amount'] = float(new_paid)
        inv['balance_due'] = float((total - new_paid).quantize(
            Decimal('0.01'), rounding=ROUND_HALF_UP))
        if new_paid >= total:
            inv['status'] = 'PAID'
        else:
            inv['status'] = 'PARTIALLY_PAID'
        bump(inv)
        shelter = STORE['shelters'].get(inv['shelter_id'])
        if shelter:
            shelter['revenue_balance'] = round_money(
                shelter['revenue_balance'] + float(amount_d))
            bump(shelter)
        return envelope_success(inv)


@app.route('/fee-invoices/<invoice_id>/refund', methods=['POST'])
def refund_invoice(invoice_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        inv = STORE['fee_invoices'].get(invoice_id)
        if not inv:
            return err('ERR_INVOICE_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(inv, body)
        if v: return v
        if inv['status'] not in ('PAID', 'PARTIALLY_PAID'):
            return err('ERR_INVALID_STATE', 'Only paid invoices can be refunded.')
        refund_amt = inv['paid_amount']
        inv['refund_amount'] = refund_amt
        inv['status'] = 'REFUNDED'
        bump(inv)
        shelter = STORE['shelters'].get(inv['shelter_id'])
        if shelter:
            shelter['revenue_balance'] = round_money(
                shelter['revenue_balance'] - refund_amt)
            bump(shelter)
        return envelope_success(inv)


@app.route('/fee-invoices/<invoice_id>/void', methods=['POST'])
def void_invoice(invoice_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        inv = STORE['fee_invoices'].get(invoice_id)
        if not inv:
            return err('ERR_INVOICE_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(inv, body)
        if v: return v
        if inv['status'] not in ('DRAFT', 'ISSUED'):
            return err('ERR_INVALID_STATE', 'Invoice cannot be voided.')
        if inv['paid_amount'] and inv['paid_amount'] > 0:
            return err('ERR_INVOICE_HAS_PAYMENTS', 'Invoice has payments.')
        inv['status'] = 'VOID'
        bump(inv)
        return envelope_success(inv)


# ============ Compliance holds ============

@app.route('/compliance-holds', methods=['POST'])
def create_hold():
    user_id, role, er = check_auth(['Veterinarian', 'ShelterManager'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['animal_id', 'severity', 'reason'])
    if r: return r
    with _LOCK:
        a = STORE['animals'].get(body['animal_id'])
        if not a:
            return err('ERR_ANIMAL_NOT_FOUND', 'Animal not found.')
        sev = body['severity']
        if sev not in HOLD_SEVERITIES:
            return err('ERR_INVALID_REQUEST', 'Invalid severity.')
        now = now_iso()
        h = {
            'id': gen_id(),
            'animal_id': a['id'],
            'severity': sev,
            'reason': body['reason'],
            'status': 'ACTIVE',
            'resolution_notes': None,
            'created_by': user_id,
            'resolved_by': None,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['compliance_holds'][h['id']] = h
        if sev in ('HIGH', 'CRITICAL'):
            apply_compliance_hold_effects(a, sev)
        else:
            recompute_shelter_compliance(a['shelter_id'])
        return envelope_success(h, 201)


@app.route('/compliance-holds', methods=['GET'])
def list_holds():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    items = list(STORE['compliance_holds'].values())
    aid = request.args.get('animal_id')
    st = request.args.get('status')
    sev = request.args.get('severity')
    if aid:
        items = [x for x in items if x['animal_id'] == aid]
    if st:
        items = [x for x in items if x['status'] == st]
    if sev:
        items = [x for x in items if x['severity'] == sev]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/compliance-holds/<hold_id>', methods=['GET'])
def get_hold(hold_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker', 'Veterinarian'])
    if er: return er
    h = STORE['compliance_holds'].get(hold_id)
    if not h:
        return err('ERR_HOLD_NOT_FOUND', 'Not found.')
    return envelope_success(h)


@app.route('/compliance-holds/<hold_id>/resolve', methods=['POST'])
def resolve_hold(hold_id):
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    with _LOCK:
        h = STORE['compliance_holds'].get(hold_id)
        if not h:
            return err('ERR_HOLD_NOT_FOUND', 'Not found.')
        body = request.get_json(silent=True) or {}
        v = check_version(h, body)
        if v: return v
        if h['status'] != 'ACTIVE':
            return err('ERR_INVALID_STATE', 'Hold already resolved.')
        notes = body.get('resolution_notes')
        if not notes:
            return err('ERR_INVALID_REQUEST', 'resolution_notes required.')
        h['status'] = 'RESOLVED'
        h['resolution_notes'] = notes
        h['resolved_by'] = user_id
        bump(h)
        a = STORE['animals'].get(h['animal_id'])
        if a:
            resolve_compliance_hold_effects(a)
        return envelope_success(h)


# ============ Fee schedules ============

@app.route('/fee-schedules', methods=['POST'])
def create_fee_schedule():
    user_id, role, er = check_auth(['ShelterManager'])
    if er: return er
    body = request.get_json(silent=True) or {}
    r = require_fields(body, ['shelter_id', 'fee_type', 'species',
                              'amount', 'effective_from'])
    if r: return r
    with _LOCK:
        s = STORE['shelters'].get(body['shelter_id'])
        if not s:
            return err('ERR_SHELTER_NOT_FOUND', 'Shelter not found.')
        if body['fee_type'] not in FEE_TYPES:
            return err('ERR_INVALID_REQUEST', 'Invalid fee_type.')
        species = body['species']
        if species not in SPECIES_SET and species != 'ALL':
            return err('ERR_INVALID_REQUEST', 'Invalid species.')
        try:
            amount = float(body['amount'])
        except (ValueError, TypeError):
            return err('ERR_INVALID_REQUEST', 'Invalid amount.')
        ef = parse_date(body['effective_from'])
        et = parse_date(body.get('effective_to'))
        if ef is None:
            return err('ERR_INVALID_REQUEST', 'Invalid effective_from.')
        if body.get('effective_to') is not None and et is None:
            return err('ERR_INVALID_REQUEST', 'Invalid effective_to.')
        if et is not None and et <= ef:
            return err('ERR_INVALID_DATES', 'effective_to must be after effective_from.')
        now_dt = datetime.now(timezone.utc)
        is_active = (ef <= now_dt) and (et is None or et > now_dt)
        now = now_iso()
        fs = {
            'id': gen_id(),
            'shelter_id': body['shelter_id'],
            'fee_type': body['fee_type'],
            'species': species,
            'amount': amount,
            'effective_from': body['effective_from'],
            'effective_to': body.get('effective_to'),
            'is_active': is_active,
            'created_at': now,
            'updated_at': now,
            'version': 1,
        }
        STORE['fee_schedules'][fs['id']] = fs
        return envelope_success(fs, 201)


@app.route('/fee-schedules', methods=['GET'])
def list_fee_schedules():
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    update_fee_schedule_active_flags()
    items = list(STORE['fee_schedules'].values())
    sid = request.args.get('shelter_id')
    ft = request.args.get('fee_type')
    sp = request.args.get('species')
    if sid:
        items = [x for x in items if x['shelter_id'] == sid]
    if ft:
        items = [x for x in items if x['fee_type'] == ft]
    if sp:
        items = [x for x in items if x['species'] == sp]
    items.sort(key=lambda x: x['created_at'])
    pager, er = paginate(items)
    if er: return er
    data, pagination = pager
    return envelope_success(data, 200, 'array', pagination)


@app.route('/fee-schedules/<fs_id>', methods=['GET'])
def get_fee_schedule(fs_id):
    user_id, role, er = check_auth(['ShelterManager', 'CaseWorker'])
    if er: return er
    update_fee_schedule_active_flags()
    fs = STORE['fee_schedules'].get(fs_id)
    if not fs:
        return err('ERR_FEE_SCHEDULE_NOT_FOUND', 'Not found.')
    return envelope_success(fs)


# ============ Errors ============

@app.errorhandler(404)
def not_found(_):
    return envelope_error('ERR_INVALID_REQUEST', 'Route not found.', 404)


@app.errorhandler(405)
def method_not_allowed(_):
    return envelope_error('ERR_INVALID_REQUEST', 'Method not allowed.', 405)


@app.errorhandler(Exception)
def unhandled(e):
    return envelope_error('ERR_INVALID_REQUEST', str(e), 400)


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, threaded=True)
