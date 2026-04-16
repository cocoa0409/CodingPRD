import os
import uuid
import sqlite3
import json
import math
import decimal
from datetime import datetime, timezone
from functools import wraps
from flask import Flask, request, jsonify, g

app = Flask(__name__)
DATABASE = '/app/shelter.db'

# ── Decimal helpers ──

def round_half_up(value, decimals=2):
    d = decimal.Decimal(str(value))
    factor = decimal.Decimal(10) ** -decimals
    return float(d.quantize(factor, rounding=decimal.ROUND_HALF_UP))


def gen_id():
    return str(uuid.uuid4())


def now_ts():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.') + \
           f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def req_id():
    return "req_" + uuid.uuid4().hex[:16]


# ── DB helpers ──

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA journal_mode=WAL")
        g.db.execute("PRAGMA foreign_keys=ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop('db', None)
    if db:
        db.close()


def init_db():
    db = sqlite3.connect(DATABASE)
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript(SCHEMA)
    db.commit()
    db.close()


SCHEMA = """
CREATE TABLE IF NOT EXISTS shelters (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    address TEXT NOT NULL,
    boarding_capacity INTEGER NOT NULL,
    current_boarding_count INTEGER NOT NULL DEFAULT 0,
    adoption_count INTEGER NOT NULL DEFAULT 0,
    compliance_score REAL NOT NULL DEFAULT 100.0,
    revenue_balance REAL NOT NULL DEFAULT 0.0,
    tax_rate REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'OPEN',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS animals (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    name TEXT NOT NULL,
    species TEXT NOT NULL,
    breed TEXT NOT NULL,
    age_months INTEGER NOT NULL,
    weight_kg REAL NOT NULL,
    temperament TEXT NOT NULL,
    special_needs TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'INTAKE',
    vaccination_compliant INTEGER NOT NULL DEFAULT 0,
    adoption_eligible INTEGER NOT NULL DEFAULT 0,
    boarding_compatible_tags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);

CREATE TABLE IF NOT EXISTS vaccination_records (
    id TEXT PRIMARY KEY,
    animal_id TEXT NOT NULL,
    vaccine_type TEXT NOT NULL,
    administered_date TEXT NOT NULL,
    expiry_date TEXT NOT NULL,
    administered_by TEXT NOT NULL,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (animal_id) REFERENCES animals(id)
);

CREATE TABLE IF NOT EXISTS adopters (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL,
    phone TEXT NOT NULL,
    home_type TEXT NOT NULL,
    has_yard INTEGER NOT NULL DEFAULT 0,
    has_other_pets INTEGER NOT NULL DEFAULT 0,
    other_pet_species TEXT NOT NULL DEFAULT '[]',
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    adoption_history_count INTEGER NOT NULL DEFAULT 0,
    home_visit_passed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);

CREATE TABLE IF NOT EXISTS adoption_applications (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    animal_id TEXT NOT NULL,
    adopter_id TEXT NOT NULL,
    reason TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SUBMITTED',
    reviewer_id TEXT,
    approver_id TEXT,
    animal_version INTEGER,
    adopter_version INTEGER,
    rejection_reason TEXT,
    fee_invoice_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id),
    FOREIGN KEY (animal_id) REFERENCES animals(id),
    FOREIGN KEY (adopter_id) REFERENCES adopters(id)
);

CREATE TABLE IF NOT EXISTS home_visits (
    id TEXT PRIMARY KEY,
    adopter_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    case_worker_id TEXT NOT NULL,
    scheduled_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'SCHEDULED',
    yard_adequate INTEGER,
    space_adequate INTEGER,
    safety_hazards_found INTEGER,
    existing_pets_compatible INTEGER,
    overall_score REAL,
    result TEXT,
    notes TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (adopter_id) REFERENCES adopters(id),
    FOREIGN KEY (application_id) REFERENCES adoption_applications(id)
);

CREATE TABLE IF NOT EXISTS boarding_reservations (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    animal_id TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    owner_contact TEXT NOT NULL,
    check_in_date TEXT NOT NULL,
    check_out_date TEXT NOT NULL,
    actual_check_in TEXT,
    actual_check_out TEXT,
    duration_days INTEGER NOT NULL,
    special_instructions TEXT,
    status TEXT NOT NULL DEFAULT 'REQUESTED',
    fee_invoice_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id),
    FOREIGN KEY (animal_id) REFERENCES animals(id)
);

CREATE TABLE IF NOT EXISTS boarding_matches (
    id TEXT PRIMARY KEY,
    reservation_id TEXT NOT NULL,
    animal_id TEXT NOT NULL,
    shelter_id TEXT NOT NULL,
    compatibility_score REAL NOT NULL,
    boarding_zone TEXT NOT NULL,
    conflict_flags TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    FOREIGN KEY (reservation_id) REFERENCES boarding_reservations(id),
    FOREIGN KEY (animal_id) REFERENCES animals(id),
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);

CREATE TABLE IF NOT EXISTS fee_invoices (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    invoice_type TEXT NOT NULL,
    reference_id TEXT NOT NULL,
    line_items TEXT NOT NULL DEFAULT '[]',
    subtotal REAL NOT NULL DEFAULT 0.0,
    discount REAL NOT NULL DEFAULT 0.0,
    tax REAL NOT NULL DEFAULT 0.0,
    total_amount REAL NOT NULL DEFAULT 0.0,
    paid_amount REAL NOT NULL DEFAULT 0.0,
    balance_due REAL NOT NULL DEFAULT 0.0,
    refund_amount REAL NOT NULL DEFAULT 0.0,
    status TEXT NOT NULL DEFAULT 'DRAFT',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);

CREATE TABLE IF NOT EXISTS compliance_holds (
    id TEXT PRIMARY KEY,
    animal_id TEXT NOT NULL,
    shelter_id TEXT NOT NULL,
    severity TEXT NOT NULL,
    reason TEXT NOT NULL,
    placed_by TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'ACTIVE',
    resolution_notes TEXT,
    resolved_by TEXT,
    resolved_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (animal_id) REFERENCES animals(id),
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);

CREATE TABLE IF NOT EXISTS fee_schedules (
    id TEXT PRIMARY KEY,
    shelter_id TEXT NOT NULL,
    fee_type TEXT NOT NULL,
    species TEXT NOT NULL,
    amount REAL NOT NULL,
    effective_from TEXT NOT NULL,
    effective_to TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    version INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (shelter_id) REFERENCES shelters(id)
);
"""


# ── Response helpers ──

def success_response(data, status_code=200, response_type="object", pagination=None):
    meta = {
        "api_request_id": req_id(),
        "api_request_timestamp": now_ts()
    }
    if pagination:
        meta.update(pagination)
    body = {
        "meta": meta,
        "response_type": response_type,
        "data": data
    }
    return jsonify(body), status_code


def error_response(error_id, message, status_code):
    body = {
        "meta": {
            "api_request_id": req_id(),
            "api_request_timestamp": now_ts()
        },
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message
        }
    }
    return jsonify(body), status_code


# ── Auth ──

def get_auth():
    user_id = request.headers.get('X-User-ID')
    user_role = request.headers.get('X-User-Role')
    if not user_id or not user_role:
        return None, None
    if user_role not in ('ShelterManager', 'CaseWorker', 'Veterinarian'):
        return None, None
    return user_id, user_role


def require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            user_id, user_role = get_auth()
            if not user_id or not user_role:
                return error_response("ERR_AUTH_REQUIRED", "Authentication required.", 401)
            if user_role not in roles:
                return error_response("ERR_FORBIDDEN", "You do not have permission for this action.", 403)
            g.user_id = user_id
            g.user_role = user_role
            return f(*args, **kwargs)
        return wrapper
    return decorator


# ── Row to dict ──

def row_to_dict(row):
    if row is None:
        return None
    d = dict(row)
    # Parse JSON fields
    for key in ('special_needs', 'boarding_compatible_tags', 'other_pet_species', 'line_items', 'conflict_flags'):
        if key in d and isinstance(d[key], str):
            try:
                d[key] = json.loads(d[key])
            except (json.JSONDecodeError, TypeError):
                pass
    # Convert boolean fields
    for key in ('vaccination_compliant', 'adoption_eligible', 'has_yard', 'has_other_pets',
                'home_visit_passed', 'is_active', 'yard_adequate', 'space_adequate',
                'safety_hazards_found', 'existing_pets_compatible'):
        if key in d and d[key] is not None:
            d[key] = bool(d[key])
    return d


# ── Pagination helper ──

def paginate_query(base_query, params, count_query, count_params):
    limit = request.args.get('limit', 20, type=int)
    offset = request.args.get('offset', 0, type=int)
    limit = max(1, min(100, limit))
    offset = max(0, offset)

    db = get_db()
    total = db.execute(count_query, count_params).fetchone()[0]
    rows = db.execute(base_query + " LIMIT ? OFFSET ?", params + (limit, offset)).fetchall()
    items = [row_to_dict(r) for r in rows]
    pagination = {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": (offset + limit) < total
    }
    return success_response(items, 200, "array", pagination)


# ── Vaccination compliance ──

SPECIES_VACCINES = {
    'DOG': {'RABIES', 'DHPP', 'BORDETELLA'},
    'CAT': {'RABIES', 'FVRCP'},
    'RABBIT': {'RHDV'},
    'BIRD': set(),
    'OTHER': set()
}

BOARDING_VACCINES = {
    'DOG': {'RABIES', 'DHPP', 'BORDETELLA'},
    'CAT': {'RABIES', 'FVRCP', 'BORDETELLA'},
    'RABBIT': {'RHDV', 'BORDETELLA'},
    'BIRD': set(),
    'OTHER': {'BORDETELLA'}
}


def check_vaccination_compliance(db, animal_id, species):
    required = SPECIES_VACCINES.get(species, set())
    if not required:
        return True
    now = now_ts()
    records = db.execute(
        "SELECT vaccine_type, expiry_date FROM vaccination_records WHERE animal_id = ?",
        (animal_id,)
    ).fetchall()
    valid_types = set()
    for r in records:
        if r['expiry_date'] > now:
            valid_types.add(r['vaccine_type'])
    return required.issubset(valid_types)


def check_boarding_vaccination(db, animal_id, species):
    required = BOARDING_VACCINES.get(species, set())
    if not required:
        return True
    now = now_ts()
    records = db.execute(
        "SELECT vaccine_type, expiry_date FROM vaccination_records WHERE animal_id = ?",
        (animal_id,)
    ).fetchall()
    valid_types = set()
    for r in records:
        if r['expiry_date'] > now:
            valid_types.add(r['vaccine_type'])
    return required.issubset(valid_types)


def update_animal_compliance(db, animal_id):
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()
    if not animal:
        return
    species = animal['species']
    compliant = check_vaccination_compliance(db, animal_id, species)
    ts = now_ts()

    # Check active high/critical holds
    has_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE' AND severity IN ('HIGH', 'CRITICAL')",
        (animal_id,)
    ).fetchone()[0] > 0

    # Check any active hold
    has_any_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE'",
        (animal_id,)
    ).fetchone()[0] > 0

    eligible = compliant and animal['status'] == 'AVAILABLE' and not has_any_hold

    db.execute(
        "UPDATE animals SET vaccination_compliant = ?, adoption_eligible = ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (1 if compliant else 0, 1 if eligible else 0, ts, animal_id)
    )


def update_shelter_compliance_score(db, shelter_id):
    animals = db.execute(
        "SELECT id, vaccination_compliant FROM animals WHERE shelter_id = ? AND status != 'ADOPTED'",
        (shelter_id,)
    ).fetchall()
    total = len(animals)
    if total == 0:
        score = 100.0
    else:
        compliant_count = sum(1 for a in animals if a['vaccination_compliant'])
        ratio = (compliant_count / total) * 100
        holds = db.execute(
            "SELECT COUNT(*) FROM compliance_holds WHERE shelter_id = ? AND status = 'ACTIVE'",
            (shelter_id,)
        ).fetchone()[0]
        score = ratio - (holds * 5)
        score = max(0, score)
    score = round_half_up(score, 2)
    ts = now_ts()
    db.execute(
        "UPDATE shelters SET compliance_score = ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (score, ts, shelter_id)
    )


def compute_boarding_tags(animal):
    tags = [animal['species'], animal['temperament']]
    sn = animal['special_needs']
    if isinstance(sn, str):
        sn = json.loads(sn)
    tags.extend(sn)
    return tags


# ── Version check ──

def check_version(db, table, resource_id, body):
    if 'version' in body and body['version'] is not None:
        current = db.execute(f"SELECT version FROM {table} WHERE id = ?", (resource_id,)).fetchone()
        if current and current['version'] != body['version']:
            return error_response("ERR_STALE_DATA", "Resource has been modified.", 409)
    return None


# ── Fee calculation helpers ──

def get_active_fee(db, shelter_id, fee_type, species):
    now = now_ts()
    row = db.execute(
        """SELECT * FROM fee_schedules WHERE shelter_id = ? AND fee_type = ? AND species = ?
           AND effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)
           ORDER BY effective_from DESC LIMIT 1""",
        (shelter_id, fee_type, species, now, now)
    ).fetchone()
    if not row:
        row = db.execute(
            """SELECT * FROM fee_schedules WHERE shelter_id = ? AND fee_type = ? AND species = 'ALL'
               AND effective_from <= ? AND (effective_to IS NULL OR effective_to > ?)
               ORDER BY effective_from DESC LIMIT 1""",
            (shelter_id, fee_type, now, now)
        ).fetchone()
    return row


def calc_adoption_fee(db, shelter_id, animal, adopter):
    line_items = []
    species = animal['species']

    # Base fee
    base_entry = get_active_fee(db, shelter_id, 'ADOPTION_BASE', species)
    base_amount = base_entry['amount'] if base_entry else 0

    # Senior discount (84+ months)
    if animal['age_months'] >= 84:
        base_amount = round_half_up(base_amount * 0.5, 2)
        line_items.append({"description": "Adoption base fee (senior discount 50%)", "amount": base_amount})
    else:
        line_items.append({"description": "Adoption base fee", "amount": base_amount})

    subtotal = base_amount

    # Special needs surcharges
    sn = animal['special_needs']
    if isinstance(sn, str):
        sn = json.loads(sn)
    surcharge_entry = get_active_fee(db, shelter_id, 'SPECIAL_NEEDS_SURCHARGE', species)
    surcharge_per = surcharge_entry['amount'] if surcharge_entry else 0
    for tag in sn:
        line_items.append({"description": f"Special needs surcharge: {tag}", "amount": surcharge_per})
        subtotal += surcharge_per

    subtotal = round_half_up(subtotal, 2)

    # Loyalty discount
    discount = 0
    if adopter['adoption_history_count'] >= 2:
        loyalty_entry = get_active_fee(db, shelter_id, 'LOYALTY_DISCOUNT', 'ALL')
        if loyalty_entry:
            discount_rate = loyalty_entry['amount']  # percentage
            discount = round_half_up(subtotal * (discount_rate / 100), 2)
            line_items.append({"description": "Loyalty discount", "amount": -discount})

    # Tax
    shelter = db.execute("SELECT tax_rate FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    tax_rate = shelter['tax_rate'] if shelter else 0
    net = round_half_up(subtotal - discount, 2)
    tax = round_half_up(net * tax_rate, 2)
    if tax > 0:
        line_items.append({"description": "Tax", "amount": tax})

    total = round_half_up(net + tax, 2)

    return line_items, subtotal, discount, tax, total


def calc_boarding_fee(db, shelter_id, animal, duration_days):
    line_items = []
    species = animal['species']

    daily_entry = get_active_fee(db, shelter_id, 'BOARDING_DAILY', species)
    daily_rate = daily_entry['amount'] if daily_entry else 0

    sn = animal['special_needs']
    if isinstance(sn, str):
        sn = json.loads(sn)

    surcharge_entry = get_active_fee(db, shelter_id, 'SPECIAL_NEEDS_SURCHARGE', species)
    surcharge_per = surcharge_entry['amount'] if surcharge_entry else 0
    total_surcharge = surcharge_per * len(sn)

    effective_daily = daily_rate + total_surcharge

    line_items.append({"description": "Boarding daily rate", "amount": daily_rate})
    for tag in sn:
        line_items.append({"description": f"Special needs daily surcharge: {tag}", "amount": surcharge_per})

    # Long-stay discount (>14 days)
    discount = 0
    if duration_days > 14:
        discount_amount = round_half_up(effective_daily * 0.10, 2)
        effective_daily = round_half_up(effective_daily - discount_amount, 2)
        discount = round_half_up(discount_amount * duration_days, 2)
        line_items.append({"description": "Long-stay discount (10%)", "amount": -round_half_up(discount_amount * duration_days, 2)})

    subtotal = round_half_up(effective_daily * duration_days, 2)

    shelter = db.execute("SELECT tax_rate FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    tax_rate = shelter['tax_rate'] if shelter else 0
    tax = round_half_up(subtotal * tax_rate, 2)
    if tax > 0:
        line_items.append({"description": "Tax", "amount": tax})

    total = round_half_up(subtotal + tax, 2)

    return line_items, round_half_up(subtotal + discount, 2), discount, tax, total


def compute_duration_days(check_in, check_out):
    fmt = '%Y-%m-%dT%H:%M:%S'
    # Handle various date formats
    for f in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            d1 = datetime.strptime(check_in.replace('Z', '').split('.')[0] if '.' in check_in else check_in.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
            break
        except ValueError:
            try:
                d1 = datetime.strptime(check_in, '%Y-%m-%d')
                break
            except ValueError:
                continue
    for f in ('%Y-%m-%dT%H:%M:%S.%fZ', '%Y-%m-%dT%H:%M:%SZ', '%Y-%m-%dT%H:%M:%S', '%Y-%m-%d'):
        try:
            d2 = datetime.strptime(check_out.replace('Z', '').split('.')[0] if '.' in check_out else check_out.replace('Z', ''), '%Y-%m-%dT%H:%M:%S')
            break
        except ValueError:
            try:
                d2 = datetime.strptime(check_out, '%Y-%m-%d')
                break
            except ValueError:
                continue
    diff_seconds = (d2 - d1).total_seconds()
    return math.ceil(diff_seconds / 86400)


# ── Boarding compatibility ──

def compute_boarding_match(db, shelter_id, animal):
    checked_in = db.execute(
        """SELECT a.* FROM animals a
           JOIN boarding_reservations br ON br.animal_id = a.id
           WHERE br.shelter_id = ? AND br.status = 'CHECKED_IN'""",
        (shelter_id,)
    ).fetchall()

    score = 100
    conflict_flags = []

    incoming_species = animal['species']
    incoming_temp = animal['temperament']
    incoming_sn = animal['special_needs']
    if isinstance(incoming_sn, str):
        incoming_sn = json.loads(incoming_sn)

    for resident in checked_in:
        r = row_to_dict(resident)
        if r['species'] != incoming_species:
            score -= 10
            if 'SPECIES_MISMATCH' not in conflict_flags:
                conflict_flags.append('SPECIES_MISMATCH')

        if incoming_temp == 'AGGRESSIVE' or r['temperament'] == 'AGGRESSIVE':
            score -= 25
            if incoming_temp == 'AGGRESSIVE' and r['temperament'] == 'CALM':
                if 'AGGRESSIVE_NEAR_CALM' not in conflict_flags:
                    conflict_flags.append('AGGRESSIVE_NEAR_CALM')
            if r['temperament'] == 'AGGRESSIVE' and incoming_temp == 'CALM':
                if 'AGGRESSIVE_NEAR_CALM' not in conflict_flags:
                    conflict_flags.append('AGGRESSIVE_NEAR_CALM')

        if (incoming_temp == 'ENERGETIC' and r['temperament'] == 'CALM') or \
           (incoming_temp == 'CALM' and r['temperament'] == 'ENERGETIC'):
            score -= 15
            if 'ENERGY_MISMATCH' not in conflict_flags:
                conflict_flags.append('ENERGY_MISMATCH')

    for tag in incoming_sn:
        score -= 5

    score = max(0, score)

    # Zone assignment
    if incoming_temp == 'AGGRESSIVE':
        zone = 'ISOLATION'
    elif incoming_temp == 'ENERGETIC':
        zone = 'ACTIVE'
    elif incoming_species in ('CAT', 'BIRD', 'RABBIT'):
        zone = 'SMALL_ANIMAL'
    else:
        zone = 'GENERAL'

    return round_half_up(score, 2), zone, conflict_flags


# ════════════════════════════════════════════════════════════
# SHELTER ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/shelters', methods=['POST'])
@require_roles('ShelterManager')
def create_shelter():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('name', 'address', 'boarding_capacity'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    ts = now_ts()
    sid = gen_id()
    tax_rate = body.get('tax_rate', 0)
    db = get_db()
    db.execute(
        """INSERT INTO shelters (id, name, address, boarding_capacity, tax_rate, status,
           current_boarding_count, adoption_count, compliance_score, revenue_balance, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, 'OPEN', 0, 0, 100.0, 0.0, ?, ?, 1)""",
        (sid, body['name'], body['address'], body['boarding_capacity'], tax_rate, ts, ts)
    )
    db.commit()
    shelter = row_to_dict(db.execute("SELECT * FROM shelters WHERE id = ?", (sid,)).fetchone())
    return success_response(shelter, 201)


@app.route('/shelters', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def list_shelters():
    db = get_db()
    return paginate_query(
        "SELECT * FROM shelters ORDER BY created_at ASC", (),
        "SELECT COUNT(*) FROM shelters", ()
    )


@app.route('/shelters/<shelter_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def get_shelter(shelter_id):
    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)
    return success_response(row_to_dict(shelter))


@app.route('/shelters/<shelter_id>/suspend', methods=['POST'])
@require_roles('ShelterManager')
def suspend_shelter(shelter_id):
    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)
    if shelter['status'] != 'OPEN':
        return error_response("ERR_INVALID_STATE", "Shelter is not open.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'shelters', shelter_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE shelters SET status = 'SUSPENDED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, shelter_id)
    )
    db.commit()
    shelter = row_to_dict(db.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone())
    return success_response(shelter)


@app.route('/shelters/<shelter_id>/reopen', methods=['POST'])
@require_roles('ShelterManager')
def reopen_shelter(shelter_id):
    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)
    if shelter['status'] != 'SUSPENDED':
        return error_response("ERR_INVALID_STATE", "Shelter is not suspended.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'shelters', shelter_id, body)
    if ver_err:
        return ver_err

    # Check for CRITICAL holds
    critical = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE shelter_id = ? AND status = 'ACTIVE' AND severity = 'CRITICAL'",
        (shelter_id,)
    ).fetchone()[0]
    if critical > 0:
        return error_response("ERR_COMPLIANCE_HOLD_ACTIVE", "Active critical compliance holds exist.", 409)

    ts = now_ts()
    db.execute(
        "UPDATE shelters SET status = 'OPEN', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, shelter_id)
    )
    db.commit()
    shelter = row_to_dict(db.execute("SELECT * FROM shelters WHERE id = ?", (shelter_id,)).fetchone())
    return success_response(shelter)


# ════════════════════════════════════════════════════════════
# ANIMAL ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/animals', methods=['POST'])
@require_roles('CaseWorker')
def create_animal():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('shelter_id', 'name', 'species', 'breed', 'age_months', 'weight_kg', 'temperament'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    if body['species'] not in ('DOG', 'CAT', 'RABBIT', 'BIRD', 'OTHER'):
        return error_response("ERR_INVALID_REQUEST", "Invalid species.", 400)
    if body['temperament'] not in ('CALM', 'MODERATE', 'ENERGETIC', 'AGGRESSIVE'):
        return error_response("ERR_INVALID_REQUEST", "Invalid temperament.", 400)

    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (body['shelter_id'],)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)

    ts = now_ts()
    aid = gen_id()
    special_needs = json.dumps(body.get('special_needs', []))

    # Compute initial vaccination compliance
    compliant = check_vaccination_compliance(db, aid, body['species'])

    db.execute(
        """INSERT INTO animals (id, shelter_id, name, species, breed, age_months, weight_kg,
           temperament, special_needs, status, vaccination_compliant, adoption_eligible,
           boarding_compatible_tags, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'INTAKE', ?, 0, '[]', ?, ?, 1)""",
        (aid, body['shelter_id'], body['name'], body['species'], body['breed'],
         body['age_months'], body['weight_kg'], body['temperament'], special_needs,
         1 if compliant else 0, ts, ts)
    )
    db.commit()

    update_shelter_compliance_score(db, body['shelter_id'])
    db.commit()

    animal = row_to_dict(db.execute("SELECT * FROM animals WHERE id = ?", (aid,)).fetchone())
    return success_response(animal, 201)


@app.route('/animals', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def list_animals():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('species', 'species'), ('status', 'status')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM animals{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM animals{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/animals/<animal_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def get_animal(animal_id):
    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)
    return success_response(row_to_dict(animal))


@app.route('/animals/<animal_id>', methods=['PATCH'])
@require_roles('CaseWorker')
def update_animal(animal_id):
    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'animals', animal_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    updates = {}
    for field in ('name', 'breed', 'age_months', 'weight_kg', 'temperament', 'special_needs'):
        if field in body:
            if field == 'special_needs':
                updates[field] = json.dumps(body[field])
            else:
                updates[field] = body[field]

    if not updates:
        return success_response(row_to_dict(animal))

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values())
    vals.extend([ts, animal_id])
    db.execute(
        f"UPDATE animals SET {set_clause}, updated_at = ?, version = version + 1 WHERE id = ?",
        vals
    )

    # Recompute tags and eligibility
    updated = db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()
    ua = row_to_dict(updated)
    tags = compute_boarding_tags(ua)
    compliant = check_vaccination_compliance(db, animal_id, ua['species'])

    has_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE'",
        (animal_id,)
    ).fetchone()[0] > 0
    eligible = compliant and ua['status'] == 'AVAILABLE' and not has_hold

    db.execute(
        "UPDATE animals SET boarding_compatible_tags = ?, vaccination_compliant = ?, adoption_eligible = ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (json.dumps(tags), 1 if compliant else 0, 1 if eligible else 0, ts, animal_id)
    )
    db.commit()

    animal = row_to_dict(db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone())
    return success_response(animal)


@app.route('/animals/<animal_id>/make-available', methods=['POST'])
@require_roles('CaseWorker')
def make_animal_available(animal_id):
    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)
    if animal['status'] != 'INTAKE':
        return error_response("ERR_INVALID_STATE", "Animal is not in INTAKE status.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'animals', animal_id, body)
    if ver_err:
        return ver_err

    # Check vaccination compliance
    compliant = check_vaccination_compliance(db, animal_id, animal['species'])
    if not compliant:
        return error_response("ERR_VACCINATION_NOT_COMPLIANT", "Animal vaccination requirements not met.", 409)

    # Check high/critical holds
    has_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE' AND severity IN ('HIGH', 'CRITICAL')",
        (animal_id,)
    ).fetchone()[0] > 0
    if has_hold:
        return error_response("ERR_COMPLIANCE_HOLD_ACTIVE", "Active compliance hold exists.", 409)

    has_any_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE'",
        (animal_id,)
    ).fetchone()[0] > 0

    a = row_to_dict(animal)
    tags = compute_boarding_tags(a)
    eligible = compliant and not has_any_hold

    ts = now_ts()
    db.execute(
        """UPDATE animals SET status = 'AVAILABLE', vaccination_compliant = 1, adoption_eligible = ?,
           boarding_compatible_tags = ?, updated_at = ?, version = version + 1 WHERE id = ?""",
        (1 if eligible else 0, json.dumps(tags), ts, animal_id)
    )
    db.commit()

    update_shelter_compliance_score(db, animal['shelter_id'])
    db.commit()

    animal = row_to_dict(db.execute("SELECT * FROM animals WHERE id = ?", (animal_id,)).fetchone())
    return success_response(animal)


# ════════════════════════════════════════════════════════════
# VACCINATION RECORDS
# ════════════════════════════════════════════════════════════

@app.route('/vaccination-records', methods=['POST'])
@require_roles('Veterinarian')
def create_vaccination_record():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('animal_id', 'vaccine_type', 'administered_date', 'expiry_date'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (body['animal_id'],)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)

    ts = now_ts()
    rid = gen_id()
    db.execute(
        """INSERT INTO vaccination_records (id, animal_id, vaccine_type, administered_date, expiry_date,
           administered_by, notes, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (rid, body['animal_id'], body['vaccine_type'], body['administered_date'],
         body['expiry_date'], g.user_id, body.get('notes'), ts, ts)
    )
    db.commit()

    # Update compliance
    update_animal_compliance(db, body['animal_id'])
    update_shelter_compliance_score(db, animal['shelter_id'])
    db.commit()

    record = row_to_dict(db.execute("SELECT * FROM vaccination_records WHERE id = ?", (rid,)).fetchone())
    return success_response(record, 201)


@app.route('/vaccination-records', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def list_vaccination_records():
    db = get_db()
    conditions = []
    params = []
    val = request.args.get('animal_id')
    if val:
        conditions.append("animal_id = ?")
        params.append(val)

    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM vaccination_records{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM vaccination_records{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/vaccination-records/<record_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def get_vaccination_record(record_id):
    db = get_db()
    record = db.execute("SELECT * FROM vaccination_records WHERE id = ?", (record_id,)).fetchone()
    if not record:
        return error_response("ERR_VACCINATION_RECORD_NOT_FOUND", "Vaccination record not found.", 404)
    return success_response(row_to_dict(record))


# ════════════════════════════════════════════════════════════
# ADOPTER ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/adopters', methods=['POST'])
@require_roles('CaseWorker')
def create_adopter():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('shelter_id', 'full_name', 'email', 'phone', 'home_type', 'has_yard', 'has_other_pets'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (body['shelter_id'],)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)

    ts = now_ts()
    aid = gen_id()
    db.execute(
        """INSERT INTO adopters (id, shelter_id, full_name, email, phone, home_type, has_yard,
           has_other_pets, other_pet_species, status, adoption_history_count, home_visit_passed,
           created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'ACTIVE', 0, 0, ?, ?, 1)""",
        (aid, body['shelter_id'], body['full_name'], body['email'], body['phone'],
         body['home_type'], 1 if body['has_yard'] else 0, 1 if body['has_other_pets'] else 0,
         json.dumps(body.get('other_pet_species', [])), ts, ts)
    )
    db.commit()
    adopter = row_to_dict(db.execute("SELECT * FROM adopters WHERE id = ?", (aid,)).fetchone())
    return success_response(adopter, 201)


@app.route('/adopters', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_adopters():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('status', 'status')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM adopters{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM adopters{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/adopters/<adopter_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_adopter(adopter_id):
    db = get_db()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (adopter_id,)).fetchone()
    if not adopter:
        return error_response("ERR_ADOPTER_NOT_FOUND", "Adopter not found.", 404)
    return success_response(row_to_dict(adopter))


@app.route('/adopters/<adopter_id>', methods=['PATCH'])
@require_roles('CaseWorker')
def update_adopter(adopter_id):
    db = get_db()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (adopter_id,)).fetchone()
    if not adopter:
        return error_response("ERR_ADOPTER_NOT_FOUND", "Adopter not found.", 404)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adopters', adopter_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    updates = {}
    for field in ('full_name', 'email', 'phone', 'home_type', 'has_yard', 'has_other_pets', 'other_pet_species'):
        if field in body:
            if field == 'other_pet_species':
                updates[field] = json.dumps(body[field])
            elif field in ('has_yard', 'has_other_pets'):
                updates[field] = 1 if body[field] else 0
            else:
                updates[field] = body[field]

    if not updates:
        return success_response(row_to_dict(adopter))

    set_clause = ", ".join(f"{k} = ?" for k in updates)
    vals = list(updates.values())
    vals.extend([ts, adopter_id])
    db.execute(f"UPDATE adopters SET {set_clause}, updated_at = ?, version = version + 1 WHERE id = ?", vals)
    db.commit()

    adopter = row_to_dict(db.execute("SELECT * FROM adopters WHERE id = ?", (adopter_id,)).fetchone())
    return success_response(adopter)


@app.route('/adopters/<adopter_id>/blacklist', methods=['POST'])
@require_roles('ShelterManager')
def blacklist_adopter(adopter_id):
    db = get_db()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (adopter_id,)).fetchone()
    if not adopter:
        return error_response("ERR_ADOPTER_NOT_FOUND", "Adopter not found.", 404)
    if adopter['status'] != 'ACTIVE':
        return error_response("ERR_INVALID_STATE", "Adopter is not active.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adopters', adopter_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE adopters SET status = 'BLACKLISTED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, adopter_id)
    )

    # Withdraw all SUBMITTED or UNDER_REVIEW applications
    apps = db.execute(
        "SELECT id FROM adoption_applications WHERE adopter_id = ? AND status IN ('SUBMITTED', 'UNDER_REVIEW')",
        (adopter_id,)
    ).fetchall()
    for app_row in apps:
        db.execute(
            "UPDATE adoption_applications SET status = 'WITHDRAWN', updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, app_row['id'])
        )

    db.commit()
    adopter = row_to_dict(db.execute("SELECT * FROM adopters WHERE id = ?", (adopter_id,)).fetchone())
    return success_response(adopter)


# ════════════════════════════════════════════════════════════
# ADOPTION APPLICATION ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/adoption-applications', methods=['POST'])
@require_roles('CaseWorker')
def create_application():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('animal_id', 'adopter_id', 'reason'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (body['animal_id'],)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (body['adopter_id'],)).fetchone()
    if not adopter:
        return error_response("ERR_ADOPTER_NOT_FOUND", "Adopter not found.", 404)

    if animal['status'] != 'AVAILABLE':
        return error_response("ERR_ANIMAL_NOT_AVAILABLE", "Animal is not available.", 409)
    if adopter['status'] != 'ACTIVE':
        return error_response("ERR_ADOPTER_BLACKLISTED", "Adopter is blacklisted.", 409)

    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (animal['shelter_id'],)).fetchone()
    if shelter['status'] != 'OPEN':
        return error_response("ERR_SHELTER_SUSPENDED", "Shelter is suspended.", 409)

    ts = now_ts()
    appid = gen_id()
    db.execute(
        """INSERT INTO adoption_applications (id, shelter_id, animal_id, adopter_id, reason, status,
           created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, 'SUBMITTED', ?, ?, 1)""",
        (appid, animal['shelter_id'], body['animal_id'], body['adopter_id'], body['reason'], ts, ts)
    )
    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (appid,)).fetchone())
    return success_response(app_data, 201)


@app.route('/adoption-applications', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_applications():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('animal_id', 'animal_id'),
                       ('adopter_id', 'adopter_id'), ('status', 'status')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM adoption_applications{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM adoption_applications{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/adoption-applications/<app_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_application(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    return success_response(row_to_dict(application))


@app.route('/adoption-applications/<app_id>/start-review', methods=['POST'])
@require_roles('CaseWorker')
def start_review(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] != 'SUBMITTED':
        return error_response("ERR_INVALID_STATE", "Application is not in SUBMITTED status.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    animal = db.execute("SELECT version FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()
    adopter = db.execute("SELECT version FROM adopters WHERE id = ?", (application['adopter_id'],)).fetchone()

    ts = now_ts()
    db.execute(
        """UPDATE adoption_applications SET status = 'UNDER_REVIEW', reviewer_id = ?,
           animal_version = ?, adopter_version = ?, updated_at = ?, version = version + 1
           WHERE id = ?""",
        (g.user_id, animal['version'], adopter['version'], ts, app_id)
    )
    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/require-home-visit', methods=['POST'])
@require_roles('CaseWorker')
def require_home_visit(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] != 'UNDER_REVIEW':
        return error_response("ERR_INVALID_STATE", "Application is not under review.", 409)
    if application['reviewer_id'] != g.user_id:
        return error_response("ERR_REVIEWER_MISMATCH", "Only the assigned reviewer can perform this action.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE adoption_applications SET status = 'HOME_VISIT_REQUIRED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, app_id)
    )
    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/complete-review', methods=['POST'])
@require_roles('CaseWorker')
def complete_review(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] not in ('UNDER_REVIEW', 'REVIEWED_AFTER_HOME_VISIT'):
        # Also allow from HOME_VISIT states if the visit passed
        if application['status'] != 'REVIEWED':
            if application['status'] not in ('UNDER_REVIEW',):
                return error_response("ERR_INVALID_STATE", "Application is not in reviewable state.", 409)
    if application['reviewer_id'] != g.user_id:
        return error_response("ERR_REVIEWER_MISMATCH", "Only the assigned reviewer can perform this action.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    # For dogs, require home visit passed
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (application['adopter_id'],)).fetchone()
    if animal['species'] == 'DOG':
        if not adopter['home_visit_passed']:
            return error_response("ERR_HOME_VISIT_REQUIRED", "Home visit is required for dog adoptions.", 409)

    ts = now_ts()
    # Re-pin versions at review completion to capture any changes during the review process
    db.execute(
        """UPDATE adoption_applications SET status = 'REVIEWED', animal_version = ?, adopter_version = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (animal['version'], adopter['version'], ts, app_id)
    )
    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/approve', methods=['POST'])
@require_roles('ShelterManager')
def approve_application(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] != 'REVIEWED':
        return error_response("ERR_INVALID_STATE", "Application is not reviewed.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    # Self-approval check
    if g.user_id == application['reviewer_id']:
        return error_response("ERR_SELF_APPROVAL", "Reviewer cannot approve their own review.", 409)

    # Stale data checks
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (application['adopter_id'],)).fetchone()

    if application['animal_version'] is not None and animal['version'] != application['animal_version']:
        return error_response("ERR_STALE_ANIMAL_DATA", "Animal data has changed since review.", 409)
    if application['adopter_version'] is not None and adopter['version'] != application['adopter_version']:
        return error_response("ERR_STALE_ADOPTER_DATA", "Adopter data has changed since review.", 409)
    if animal['status'] != 'AVAILABLE':
        return error_response("ERR_ANIMAL_NOT_AVAILABLE", "Animal is not available.", 409)

    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (application['shelter_id'],)).fetchone()
    if shelter['status'] != 'OPEN':
        return error_response("ERR_SHELTER_SUSPENDED", "Shelter is suspended.", 409)

    # Check no other approved/completed app for same animal
    existing = db.execute(
        "SELECT COUNT(*) FROM adoption_applications WHERE animal_id = ? AND status IN ('APPROVED', 'COMPLETED') AND id != ?",
        (application['animal_id'], app_id)
    ).fetchone()[0]
    if existing > 0:
        return error_response("ERR_ANIMAL_NOT_AVAILABLE", "Animal already has an approved application.", 409)

    # Generate fee invoice
    a = row_to_dict(animal)
    ad = row_to_dict(adopter)
    line_items, subtotal, discount, tax, total = calc_adoption_fee(db, application['shelter_id'], a, ad)

    ts = now_ts()
    inv_id = gen_id()
    db.execute(
        """INSERT INTO fee_invoices (id, shelter_id, invoice_type, reference_id, line_items,
           subtotal, discount, tax, total_amount, paid_amount, balance_due, refund_amount,
           status, created_at, updated_at, version)
           VALUES (?, ?, 'ADOPTION', ?, ?, ?, ?, ?, ?, 0, ?, 0, 'ISSUED', ?, ?, 1)""",
        (inv_id, application['shelter_id'], app_id, json.dumps(line_items),
         subtotal, discount, tax, total, total, ts, ts)
    )

    # Update application
    db.execute(
        """UPDATE adoption_applications SET status = 'APPROVED', approver_id = ?, fee_invoice_id = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (g.user_id, inv_id, ts, app_id)
    )

    # Update animal
    db.execute(
        "UPDATE animals SET status = 'ADOPTION_PENDING', adoption_eligible = 0, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, application['animal_id'])
    )

    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/reject', methods=['POST'])
@require_roles('ShelterManager')
def reject_application(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] != 'REVIEWED':
        return error_response("ERR_INVALID_STATE", "Application is not reviewed.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    if 'rejection_reason' not in body:
        return error_response("ERR_INVALID_REQUEST", "Missing rejection_reason.", 400)

    ts = now_ts()
    db.execute(
        """UPDATE adoption_applications SET status = 'REJECTED', rejection_reason = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (body['rejection_reason'], ts, app_id)
    )

    # If animal was ADOPTION_PENDING, revert
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()
    if animal['status'] == 'ADOPTION_PENDING':
        db.execute(
            "UPDATE animals SET status = 'AVAILABLE', adoption_eligible = 1, updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, application['animal_id'])
        )

    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/complete', methods=['POST'])
@require_roles('CaseWorker')
def complete_application(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] != 'APPROVED':
        return error_response("ERR_INVALID_STATE", "Application is not approved.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    # Check fee paid
    if application['fee_invoice_id']:
        invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (application['fee_invoice_id'],)).fetchone()
        if invoice and invoice['status'] != 'PAID':
            return error_response("ERR_FEE_NOT_PAID", "Fee invoice must be paid before completing adoption.", 409)

    ts = now_ts()
    db.execute(
        "UPDATE adoption_applications SET status = 'COMPLETED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, app_id)
    )

    # Update animal to ADOPTED
    db.execute(
        "UPDATE animals SET status = 'ADOPTED', adoption_eligible = 0, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, application['animal_id'])
    )

    # Increment shelter adoption count
    db.execute(
        "UPDATE shelters SET adoption_count = adoption_count + 1, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, application['shelter_id'])
    )

    # Increment adopter history
    db.execute(
        "UPDATE adopters SET adoption_history_count = adoption_history_count + 1, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, application['adopter_id'])
    )

    db.commit()

    update_shelter_compliance_score(db, application['shelter_id'])
    db.commit()

    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


@app.route('/adoption-applications/<app_id>/withdraw', methods=['POST'])
@require_roles('CaseWorker')
def withdraw_application(app_id):
    db = get_db()
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] in ('APPROVED', 'COMPLETED', 'REJECTED', 'WITHDRAWN'):
        return error_response("ERR_INVALID_STATE", "Application cannot be withdrawn.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'adoption_applications', app_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE adoption_applications SET status = 'WITHDRAWN', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, app_id)
    )

    # If animal was ADOPTION_PENDING, revert
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()
    if animal['status'] == 'ADOPTION_PENDING':
        db.execute(
            "UPDATE animals SET status = 'AVAILABLE', adoption_eligible = 1, updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, application['animal_id'])
        )

    # Cancel scheduled home visits
    db.execute(
        "UPDATE home_visits SET status = 'CANCELLED', updated_at = ?, version = version + 1 WHERE application_id = ? AND status = 'SCHEDULED'",
        (ts, app_id)
    )

    db.commit()
    app_data = row_to_dict(db.execute("SELECT * FROM adoption_applications WHERE id = ?", (app_id,)).fetchone())
    return success_response(app_data)


# ════════════════════════════════════════════════════════════
# HOME VISIT ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/home-visits', methods=['POST'])
@require_roles('CaseWorker')
def create_home_visit():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('adopter_id', 'application_id', 'scheduled_date'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    db = get_db()
    adopter = db.execute("SELECT * FROM adopters WHERE id = ?", (body['adopter_id'],)).fetchone()
    if not adopter:
        return error_response("ERR_ADOPTER_NOT_FOUND", "Adopter not found.", 404)
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (body['application_id'],)).fetchone()
    if not application:
        return error_response("ERR_APPLICATION_NOT_FOUND", "Application not found.", 404)
    if application['status'] not in ('HOME_VISIT_REQUIRED',):
        return error_response("ERR_INVALID_STATE", "Application does not require home visit.", 409)

    ts = now_ts()
    hid = gen_id()
    db.execute(
        """INSERT INTO home_visits (id, adopter_id, application_id, case_worker_id, scheduled_date,
           status, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, 'SCHEDULED', ?, ?, 1)""",
        (hid, body['adopter_id'], body['application_id'], g.user_id, body['scheduled_date'], ts, ts)
    )

    # Update application to HOME_VISIT_SCHEDULED
    db.execute(
        "UPDATE adoption_applications SET status = 'HOME_VISIT_SCHEDULED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, body['application_id'])
    )

    db.commit()
    visit = row_to_dict(db.execute("SELECT * FROM home_visits WHERE id = ?", (hid,)).fetchone())
    return success_response(visit, 201)


@app.route('/home-visits', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_home_visits():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('adopter_id', 'adopter_id'), ('application_id', 'application_id')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM home_visits{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM home_visits{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/home-visits/<visit_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_home_visit(visit_id):
    db = get_db()
    visit = db.execute("SELECT * FROM home_visits WHERE id = ?", (visit_id,)).fetchone()
    if not visit:
        return error_response("ERR_HOME_VISIT_NOT_FOUND", "Home visit not found.", 404)
    return success_response(row_to_dict(visit))


@app.route('/home-visits/<visit_id>/complete', methods=['POST'])
@require_roles('CaseWorker')
def complete_home_visit(visit_id):
    db = get_db()
    visit = db.execute("SELECT * FROM home_visits WHERE id = ?", (visit_id,)).fetchone()
    if not visit:
        return error_response("ERR_HOME_VISIT_NOT_FOUND", "Home visit not found.", 404)
    if visit['status'] != 'SCHEDULED':
        return error_response("ERR_INVALID_STATE", "Home visit is not scheduled.", 409)
    if visit['case_worker_id'] != g.user_id:
        return error_response("ERR_ASSESSOR_MISMATCH", "Only the assigned case worker can complete this visit.", 409)

    body = request.get_json(force=True, silent=True) or {}
    for field in ('yard_adequate', 'space_adequate', 'safety_hazards_found', 'existing_pets_compatible', 'notes'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    ver_err = check_version(db, 'home_visits', visit_id, body)
    if ver_err:
        return ver_err

    # Get the application to find the animal
    application = db.execute("SELECT * FROM adoption_applications WHERE id = ?", (visit['application_id'],)).fetchone()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (application['animal_id'],)).fetchone()

    # Compute score
    species = animal['species']
    no_yard_species = species in ('CAT', 'BIRD', 'RABBIT')

    if no_yard_species:
        yard_weight = 0
        space_weight = 45
    else:
        yard_weight = 25
        space_weight = 30

    hazard_weight = 25
    pet_weight = 20

    yard_score = yard_weight if body['yard_adequate'] else 0
    space_score = space_weight if body['space_adequate'] else 0
    hazard_score = hazard_weight if not body['safety_hazards_found'] else 0
    pet_score = pet_weight if body['existing_pets_compatible'] else 0

    overall = yard_score + space_score + hazard_score + pet_score

    if overall >= 70:
        result = 'PASS'
    elif overall >= 50:
        result = 'CONDITIONAL_PASS'
    else:
        result = 'FAIL'

    ts = now_ts()
    db.execute(
        """UPDATE home_visits SET status = 'COMPLETED', yard_adequate = ?, space_adequate = ?,
           safety_hazards_found = ?, existing_pets_compatible = ?, overall_score = ?, result = ?,
           notes = ?, updated_at = ?, version = version + 1 WHERE id = ?""",
        (1 if body['yard_adequate'] else 0, 1 if body['space_adequate'] else 0,
         1 if body['safety_hazards_found'] else 0, 1 if body['existing_pets_compatible'] else 0,
         overall, result, body['notes'], ts, visit_id)
    )

    if result in ('PASS', 'CONDITIONAL_PASS'):
        # Update adopter home_visit_passed
        db.execute(
            "UPDATE adopters SET home_visit_passed = 1, updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, visit['adopter_id'])
        )
        # Advance application to REVIEWED
        db.execute(
            "UPDATE adoption_applications SET status = 'REVIEWED', updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, visit['application_id'])
        )
    else:
        # FAIL - reject application
        db.execute(
            """UPDATE adoption_applications SET status = 'REJECTED', rejection_reason = 'Home visit failed',
               updated_at = ?, version = version + 1 WHERE id = ?""",
            (ts, visit['application_id'])
        )
        # Revert animal if ADOPTION_PENDING
        if animal['status'] == 'ADOPTION_PENDING':
            db.execute(
                "UPDATE animals SET status = 'AVAILABLE', adoption_eligible = 1, updated_at = ?, version = version + 1 WHERE id = ?",
                (ts, application['animal_id'])
            )

    db.commit()
    visit = row_to_dict(db.execute("SELECT * FROM home_visits WHERE id = ?", (visit_id,)).fetchone())
    return success_response(visit)


@app.route('/home-visits/<visit_id>/cancel', methods=['POST'])
@require_roles('CaseWorker')
def cancel_home_visit(visit_id):
    db = get_db()
    visit = db.execute("SELECT * FROM home_visits WHERE id = ?", (visit_id,)).fetchone()
    if not visit:
        return error_response("ERR_HOME_VISIT_NOT_FOUND", "Home visit not found.", 404)
    if visit['status'] != 'SCHEDULED':
        return error_response("ERR_INVALID_STATE", "Home visit is not scheduled.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'home_visits', visit_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE home_visits SET status = 'CANCELLED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, visit_id)
    )

    # Revert application to HOME_VISIT_REQUIRED
    db.execute(
        "UPDATE adoption_applications SET status = 'HOME_VISIT_REQUIRED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, visit['application_id'])
    )

    db.commit()
    visit = row_to_dict(db.execute("SELECT * FROM home_visits WHERE id = ?", (visit_id,)).fetchone())
    return success_response(visit)


# ════════════════════════════════════════════════════════════
# BOARDING RESERVATION ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/boarding-reservations', methods=['POST'])
@require_roles('CaseWorker')
def create_boarding_reservation():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('shelter_id', 'animal_id', 'owner_name', 'owner_contact', 'check_in_date', 'check_out_date'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (body['shelter_id'],)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (body['animal_id'],)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)

    if shelter['status'] != 'OPEN':
        return error_response("ERR_SHELTER_SUSPENDED", "Shelter is suspended.", 409)

    # Validate dates
    if body['check_out_date'] <= body['check_in_date']:
        return error_response("ERR_INVALID_DATES", "Check-out must be after check-in.", 400)

    duration = compute_duration_days(body['check_in_date'], body['check_out_date'])

    ts = now_ts()
    rid = gen_id()
    db.execute(
        """INSERT INTO boarding_reservations (id, shelter_id, animal_id, owner_name, owner_contact,
           check_in_date, check_out_date, duration_days, special_instructions, status,
           created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'REQUESTED', ?, ?, 1)""",
        (rid, body['shelter_id'], body['animal_id'], body['owner_name'], body['owner_contact'],
         body['check_in_date'], body['check_out_date'], duration,
         body.get('special_instructions'), ts, ts)
    )
    db.commit()
    reservation = row_to_dict(db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (rid,)).fetchone())
    return success_response(reservation, 201)


@app.route('/boarding-reservations', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_boarding_reservations():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('animal_id', 'animal_id'), ('status', 'status')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM boarding_reservations{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM boarding_reservations{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/boarding-reservations/<res_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_boarding_reservation(res_id):
    db = get_db()
    reservation = db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone()
    if not reservation:
        return error_response("ERR_RESERVATION_NOT_FOUND", "Reservation not found.", 404)
    return success_response(row_to_dict(reservation))


@app.route('/boarding-reservations/<res_id>/confirm', methods=['POST'])
@require_roles('ShelterManager')
def confirm_boarding(res_id):
    db = get_db()
    reservation = db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone()
    if not reservation:
        return error_response("ERR_RESERVATION_NOT_FOUND", "Reservation not found.", 404)
    if reservation['status'] != 'REQUESTED':
        return error_response("ERR_INVALID_STATE", "Reservation is not in REQUESTED status.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'boarding_reservations', res_id, body)
    if ver_err:
        return ver_err

    animal = db.execute("SELECT * FROM animals WHERE id = ?", (reservation['animal_id'],)).fetchone()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (reservation['shelter_id'],)).fetchone()

    if shelter['status'] != 'OPEN':
        return error_response("ERR_SHELTER_SUSPENDED", "Shelter is suspended.", 409)

    # Check boarding vaccination compliance
    if not check_boarding_vaccination(db, reservation['animal_id'], animal['species']):
        return error_response("ERR_VACCINATION_NOT_COMPLIANT", "Animal does not meet boarding vaccination requirements.", 409)

    # Check capacity
    if shelter['current_boarding_count'] >= shelter['boarding_capacity']:
        return error_response("ERR_BOARDING_CAPACITY_FULL", "Shelter has reached maximum boarding capacity.", 409)

    # Check date overlap
    overlaps = db.execute(
        """SELECT COUNT(*) FROM boarding_reservations
           WHERE animal_id = ? AND status IN ('CONFIRMED', 'CHECKED_IN')
           AND id != ? AND check_in_date < ? AND check_out_date > ?""",
        (reservation['animal_id'], res_id, reservation['check_out_date'], reservation['check_in_date'])
    ).fetchone()[0]
    if overlaps > 0:
        return error_response("ERR_BOARDING_DATE_OVERLAP", "Overlapping reservation exists.", 409)

    # Compute boarding match
    a = row_to_dict(animal)
    compat_score, zone, conflict_flags = compute_boarding_match(db, reservation['shelter_id'], a)

    ts = now_ts()
    match_id = gen_id()
    db.execute(
        """INSERT INTO boarding_matches (id, reservation_id, animal_id, shelter_id,
           compatibility_score, boarding_zone, conflict_flags, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (match_id, res_id, reservation['animal_id'], reservation['shelter_id'],
         compat_score, zone, json.dumps(conflict_flags), ts)
    )

    # Generate fee invoice
    line_items, subtotal, discount, tax, total = calc_boarding_fee(
        db, reservation['shelter_id'], a, reservation['duration_days']
    )

    inv_id = gen_id()
    db.execute(
        """INSERT INTO fee_invoices (id, shelter_id, invoice_type, reference_id, line_items,
           subtotal, discount, tax, total_amount, paid_amount, balance_due, refund_amount,
           status, created_at, updated_at, version)
           VALUES (?, ?, 'BOARDING', ?, ?, ?, ?, ?, ?, 0, ?, 0, 'ISSUED', ?, ?, 1)""",
        (inv_id, reservation['shelter_id'], res_id, json.dumps(line_items),
         subtotal, discount, tax, total, total, ts, ts)
    )

    db.execute(
        """UPDATE boarding_reservations SET status = 'CONFIRMED', fee_invoice_id = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (inv_id, ts, res_id)
    )
    db.commit()

    reservation = row_to_dict(db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone())
    return success_response(reservation)


@app.route('/boarding-reservations/<res_id>/check-in', methods=['POST'])
@require_roles('CaseWorker')
def check_in_boarding(res_id):
    db = get_db()
    reservation = db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone()
    if not reservation:
        return error_response("ERR_RESERVATION_NOT_FOUND", "Reservation not found.", 404)
    if reservation['status'] != 'CONFIRMED':
        return error_response("ERR_INVALID_STATE", "Reservation is not confirmed.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'boarding_reservations', res_id, body)
    if ver_err:
        return ver_err

    animal = db.execute("SELECT * FROM animals WHERE id = ?", (reservation['animal_id'],)).fetchone()

    # Re-verify vaccination compliance for boarding
    if not check_boarding_vaccination(db, reservation['animal_id'], animal['species']):
        return error_response("ERR_VACCINATION_NOT_COMPLIANT", "Animal vaccination expired.", 409)

    # Check compliance holds
    has_hold = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE' AND severity IN ('HIGH', 'CRITICAL')",
        (reservation['animal_id'],)
    ).fetchone()[0] > 0
    if has_hold:
        return error_response("ERR_COMPLIANCE_HOLD_ACTIVE", "Active compliance hold on animal.", 409)

    ts = now_ts()
    db.execute(
        """UPDATE boarding_reservations SET status = 'CHECKED_IN', actual_check_in = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (ts, ts, res_id)
    )

    # Increment boarding count
    db.execute(
        "UPDATE shelters SET current_boarding_count = current_boarding_count + 1, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, reservation['shelter_id'])
    )

    # If animal belongs to shelter, set to BOARDING
    if animal['shelter_id'] == reservation['shelter_id']:
        db.execute(
            "UPDATE animals SET status = 'BOARDING', adoption_eligible = 0, updated_at = ?, version = version + 1 WHERE id = ?",
            (ts, reservation['animal_id'])
        )

    db.commit()
    reservation = row_to_dict(db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone())
    return success_response(reservation)


@app.route('/boarding-reservations/<res_id>/check-out', methods=['POST'])
@require_roles('CaseWorker')
def check_out_boarding(res_id):
    db = get_db()
    reservation = db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone()
    if not reservation:
        return error_response("ERR_RESERVATION_NOT_FOUND", "Reservation not found.", 404)
    if reservation['status'] != 'CHECKED_IN':
        return error_response("ERR_INVALID_STATE", "Reservation is not checked in.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'boarding_reservations', res_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    actual_check_in = reservation['actual_check_in']
    actual_check_out = ts

    # Recompute duration
    new_duration = compute_duration_days(actual_check_in, actual_check_out)

    db.execute(
        """UPDATE boarding_reservations SET status = 'CHECKED_OUT', actual_check_out = ?,
           duration_days = ?, updated_at = ?, version = version + 1 WHERE id = ?""",
        (actual_check_out, new_duration, ts, res_id)
    )

    # Decrement boarding count
    db.execute(
        "UPDATE shelters SET current_boarding_count = MAX(0, current_boarding_count - 1), updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, reservation['shelter_id'])
    )

    # If animal belongs to shelter, revert to AVAILABLE
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (reservation['animal_id'],)).fetchone()
    if animal['shelter_id'] == reservation['shelter_id']:
        has_hold = db.execute(
            "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE' AND severity IN ('HIGH', 'CRITICAL')",
            (reservation['animal_id'],)
        ).fetchone()[0] > 0
        if not has_hold:
            compliant = check_vaccination_compliance(db, reservation['animal_id'], animal['species'])
            has_any_hold = db.execute(
                "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE'",
                (reservation['animal_id'],)
            ).fetchone()[0] > 0
            eligible = compliant and not has_any_hold
            db.execute(
                "UPDATE animals SET status = 'AVAILABLE', adoption_eligible = ?, updated_at = ?, version = version + 1 WHERE id = ?",
                (1 if eligible else 0, ts, reservation['animal_id'])
            )
        else:
            db.execute(
                "UPDATE animals SET status = 'UNAVAILABLE', adoption_eligible = 0, updated_at = ?, version = version + 1 WHERE id = ?",
                (ts, reservation['animal_id'])
            )

    # Adjust fee invoice if duration changed
    if reservation['fee_invoice_id'] and new_duration != reservation['duration_days']:
        a = row_to_dict(animal)
        line_items, subtotal, discount, tax, total = calc_boarding_fee(
            db, reservation['shelter_id'], a, new_duration
        )
        invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (reservation['fee_invoice_id'],)).fetchone()
        paid = invoice['paid_amount'] if invoice else 0
        balance = round_half_up(total - paid, 2)
        db.execute(
            """UPDATE fee_invoices SET line_items = ?, subtotal = ?, discount = ?, tax = ?,
               total_amount = ?, balance_due = ?, updated_at = ?, version = version + 1
               WHERE id = ?""",
            (json.dumps(line_items), subtotal, discount, tax, total, balance, ts, reservation['fee_invoice_id'])
        )

    db.commit()
    reservation = row_to_dict(db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone())
    return success_response(reservation)


@app.route('/boarding-reservations/<res_id>/cancel', methods=['POST'])
@require_roles('CaseWorker')
def cancel_boarding(res_id):
    db = get_db()
    reservation = db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone()
    if not reservation:
        return error_response("ERR_RESERVATION_NOT_FOUND", "Reservation not found.", 404)
    if reservation['status'] not in ('REQUESTED', 'CONFIRMED'):
        return error_response("ERR_INVALID_STATE", "Reservation cannot be cancelled.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'boarding_reservations', res_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()

    # If confirmed, void match and handle invoice
    if reservation['status'] == 'CONFIRMED':
        # Void boarding match
        db.execute(
            "DELETE FROM boarding_matches WHERE reservation_id = ?",
            (res_id,)
        )

        if reservation['fee_invoice_id']:
            invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (reservation['fee_invoice_id'],)).fetchone()
            if invoice:
                if invoice['status'] == 'ISSUED' and invoice['paid_amount'] == 0:
                    db.execute(
                        "UPDATE fee_invoices SET status = 'VOID', updated_at = ?, version = version + 1 WHERE id = ?",
                        (ts, reservation['fee_invoice_id'])
                    )
                elif invoice['status'] == 'PAID':
                    # Refund
                    refund_amt = invoice['paid_amount']
                    db.execute(
                        """UPDATE fee_invoices SET status = 'REFUNDED', refund_amount = ?, balance_due = 0,
                           updated_at = ?, version = version + 1 WHERE id = ?""",
                        (refund_amt, ts, reservation['fee_invoice_id'])
                    )
                    db.execute(
                        "UPDATE shelters SET revenue_balance = revenue_balance - ?, updated_at = ?, version = version + 1 WHERE id = ?",
                        (refund_amt, ts, reservation['shelter_id'])
                    )

    db.execute(
        "UPDATE boarding_reservations SET status = 'CANCELLED', updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, res_id)
    )
    db.commit()
    reservation = row_to_dict(db.execute("SELECT * FROM boarding_reservations WHERE id = ?", (res_id,)).fetchone())
    return success_response(reservation)


# ════════════════════════════════════════════════════════════
# FEE INVOICE ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/fee-invoices', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_fee_invoices():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('status', 'status'), ('invoice_type', 'invoice_type')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM fee_invoices{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM fee_invoices{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/fee-invoices/<inv_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_fee_invoice(inv_id):
    db = get_db()
    invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone()
    if not invoice:
        return error_response("ERR_INVOICE_NOT_FOUND", "Invoice not found.", 404)
    return success_response(row_to_dict(invoice))


@app.route('/fee-invoices/<inv_id>/pay', methods=['POST'])
@require_roles('CaseWorker')
def pay_invoice(inv_id):
    db = get_db()
    invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone()
    if not invoice:
        return error_response("ERR_INVOICE_NOT_FOUND", "Invoice not found.", 404)
    if invoice['status'] not in ('ISSUED', 'PARTIALLY_PAID'):
        return error_response("ERR_INVALID_STATE", "Invoice cannot accept payment.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'fee_invoices', inv_id, body)
    if ver_err:
        return ver_err

    if 'amount' not in body:
        return error_response("ERR_INVALID_REQUEST", "Missing amount.", 400)

    amount = body['amount']
    if amount <= 0 or amount > invoice['balance_due']:
        return error_response("ERR_PAYMENT_AMOUNT_INVALID", "Invalid payment amount.", 400)

    new_paid = round_half_up(invoice['paid_amount'] + amount, 2)
    new_balance = round_half_up(invoice['total_amount'] - new_paid, 2)
    new_status = 'PAID' if new_balance == 0 else 'PARTIALLY_PAID'

    ts = now_ts()
    db.execute(
        """UPDATE fee_invoices SET paid_amount = ?, balance_due = ?, status = ?,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (new_paid, new_balance, new_status, ts, inv_id)
    )

    # Increase shelter revenue
    db.execute(
        "UPDATE shelters SET revenue_balance = revenue_balance + ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (amount, ts, invoice['shelter_id'])
    )

    db.commit()
    invoice = row_to_dict(db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone())
    return success_response(invoice)


@app.route('/fee-invoices/<inv_id>/refund', methods=['POST'])
@require_roles('ShelterManager')
def refund_invoice(inv_id):
    db = get_db()
    invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone()
    if not invoice:
        return error_response("ERR_INVOICE_NOT_FOUND", "Invoice not found.", 404)
    if invoice['status'] not in ('PAID', 'PARTIALLY_PAID'):
        return error_response("ERR_INVALID_STATE", "Invoice is not paid.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'fee_invoices', inv_id, body)
    if ver_err:
        return ver_err

    refund_amt = invoice['paid_amount']
    ts = now_ts()
    db.execute(
        """UPDATE fee_invoices SET status = 'REFUNDED', refund_amount = ?, balance_due = 0,
           updated_at = ?, version = version + 1 WHERE id = ?""",
        (refund_amt, ts, inv_id)
    )
    db.execute(
        "UPDATE shelters SET revenue_balance = revenue_balance - ?, updated_at = ?, version = version + 1 WHERE id = ?",
        (refund_amt, ts, invoice['shelter_id'])
    )
    db.commit()
    invoice = row_to_dict(db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone())
    return success_response(invoice)


@app.route('/fee-invoices/<inv_id>/void', methods=['POST'])
@require_roles('ShelterManager')
def void_invoice(inv_id):
    db = get_db()
    invoice = db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone()
    if not invoice:
        return error_response("ERR_INVOICE_NOT_FOUND", "Invoice not found.", 404)
    if invoice['status'] not in ('DRAFT', 'ISSUED'):
        return error_response("ERR_INVALID_STATE", "Invoice cannot be voided.", 409)
    if invoice['paid_amount'] > 0:
        return error_response("ERR_INVOICE_HAS_PAYMENTS", "Invoice has payments.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'fee_invoices', inv_id, body)
    if ver_err:
        return ver_err

    ts = now_ts()
    db.execute(
        "UPDATE fee_invoices SET status = 'VOID', balance_due = 0, updated_at = ?, version = version + 1 WHERE id = ?",
        (ts, inv_id)
    )
    db.commit()
    invoice = row_to_dict(db.execute("SELECT * FROM fee_invoices WHERE id = ?", (inv_id,)).fetchone())
    return success_response(invoice)


# ════════════════════════════════════════════════════════════
# COMPLIANCE HOLD ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/compliance-holds', methods=['POST'])
@require_roles('Veterinarian', 'ShelterManager')
def create_compliance_hold():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('animal_id', 'severity', 'reason'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    if body['severity'] not in ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL'):
        return error_response("ERR_INVALID_REQUEST", "Invalid severity.", 400)

    db = get_db()
    animal = db.execute("SELECT * FROM animals WHERE id = ?", (body['animal_id'],)).fetchone()
    if not animal:
        return error_response("ERR_ANIMAL_NOT_FOUND", "Animal not found.", 404)

    ts = now_ts()
    hid = gen_id()
    db.execute(
        """INSERT INTO compliance_holds (id, animal_id, shelter_id, severity, reason, placed_by,
           status, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, 'ACTIVE', ?, ?, 1)""",
        (hid, body['animal_id'], animal['shelter_id'], body['severity'], body['reason'], g.user_id, ts, ts)
    )

    # If HIGH or CRITICAL, transition animal to UNAVAILABLE
    if body['severity'] in ('HIGH', 'CRITICAL'):
        if animal['status'] not in ('ADOPTED',):
            db.execute(
                "UPDATE animals SET status = 'UNAVAILABLE', adoption_eligible = 0, updated_at = ?, version = version + 1 WHERE id = ?",
                (ts, body['animal_id'])
            )

    # Update compliance
    update_animal_compliance(db, body['animal_id'])
    update_shelter_compliance_score(db, animal['shelter_id'])

    db.commit()
    hold = row_to_dict(db.execute("SELECT * FROM compliance_holds WHERE id = ?", (hid,)).fetchone())
    return success_response(hold, 201)


@app.route('/compliance-holds', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def list_compliance_holds():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('animal_id', 'animal_id'), ('shelter_id', 'shelter_id'), ('status', 'status')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM compliance_holds{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM compliance_holds{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/compliance-holds/<hold_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker', 'Veterinarian')
def get_compliance_hold(hold_id):
    db = get_db()
    hold = db.execute("SELECT * FROM compliance_holds WHERE id = ?", (hold_id,)).fetchone()
    if not hold:
        return error_response("ERR_HOLD_NOT_FOUND", "Compliance hold not found.", 404)
    return success_response(row_to_dict(hold))


@app.route('/compliance-holds/<hold_id>/resolve', methods=['POST'])
@require_roles('ShelterManager')
def resolve_compliance_hold(hold_id):
    db = get_db()
    hold = db.execute("SELECT * FROM compliance_holds WHERE id = ?", (hold_id,)).fetchone()
    if not hold:
        return error_response("ERR_HOLD_NOT_FOUND", "Compliance hold not found.", 404)
    if hold['status'] != 'ACTIVE':
        return error_response("ERR_INVALID_STATE", "Hold is not active.", 409)

    body = request.get_json(force=True, silent=True) or {}
    ver_err = check_version(db, 'compliance_holds', hold_id, body)
    if ver_err:
        return ver_err

    if 'resolution_notes' not in body:
        return error_response("ERR_INVALID_REQUEST", "Missing resolution_notes.", 400)

    ts = now_ts()
    db.execute(
        """UPDATE compliance_holds SET status = 'RESOLVED', resolution_notes = ?, resolved_by = ?,
           resolved_at = ?, updated_at = ?, version = version + 1 WHERE id = ?""",
        (body['resolution_notes'], g.user_id, ts, ts, hold_id)
    )

    # Check if all HIGH/CRITICAL holds are resolved for this animal
    remaining = db.execute(
        "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE' AND severity IN ('HIGH', 'CRITICAL')",
        (hold['animal_id'],)
    ).fetchone()[0]

    animal = db.execute("SELECT * FROM animals WHERE id = ?", (hold['animal_id'],)).fetchone()
    if remaining == 0 and animal['status'] == 'UNAVAILABLE':
        # Revert to AVAILABLE
        compliant = check_vaccination_compliance(db, hold['animal_id'], animal['species'])
        has_any_hold = db.execute(
            "SELECT COUNT(*) FROM compliance_holds WHERE animal_id = ? AND status = 'ACTIVE'",
            (hold['animal_id'],)
        ).fetchone()[0] > 0
        eligible = compliant and not has_any_hold
        db.execute(
            "UPDATE animals SET status = 'AVAILABLE', vaccination_compliant = ?, adoption_eligible = ?, updated_at = ?, version = version + 1 WHERE id = ?",
            (1 if compliant else 0, 1 if eligible else 0, ts, hold['animal_id'])
        )

    update_animal_compliance(db, hold['animal_id'])
    update_shelter_compliance_score(db, hold['shelter_id'])
    db.commit()

    hold = row_to_dict(db.execute("SELECT * FROM compliance_holds WHERE id = ?", (hold_id,)).fetchone())
    return success_response(hold)


# ════════════════════════════════════════════════════════════
# FEE SCHEDULE ENDPOINTS
# ════════════════════════════════════════════════════════════

@app.route('/fee-schedules', methods=['POST'])
@require_roles('ShelterManager')
def create_fee_schedule():
    body = request.get_json(force=True, silent=True) or {}
    for field in ('shelter_id', 'fee_type', 'species', 'amount', 'effective_from'):
        if field not in body:
            return error_response("ERR_INVALID_REQUEST", f"Missing required field: {field}", 400)

    if body['fee_type'] not in ('ADOPTION_BASE', 'BOARDING_DAILY', 'SPECIAL_NEEDS_SURCHARGE',
                                 'VACCINATION_FEE', 'LOYALTY_DISCOUNT'):
        return error_response("ERR_INVALID_REQUEST", "Invalid fee_type.", 400)

    db = get_db()
    shelter = db.execute("SELECT * FROM shelters WHERE id = ?", (body['shelter_id'],)).fetchone()
    if not shelter:
        return error_response("ERR_SHELTER_NOT_FOUND", "Shelter not found.", 404)

    effective_to = body.get('effective_to')
    if effective_to and effective_to <= body['effective_from']:
        return error_response("ERR_INVALID_DATES", "effective_to must be after effective_from.", 400)

    # Compute is_active
    now = now_ts()
    is_active = body['effective_from'] <= now and (effective_to is None or effective_to > now)

    ts = now_ts()
    fid = gen_id()
    db.execute(
        """INSERT INTO fee_schedules (id, shelter_id, fee_type, species, amount, effective_from,
           effective_to, is_active, created_at, updated_at, version)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)""",
        (fid, body['shelter_id'], body['fee_type'], body['species'], body['amount'],
         body['effective_from'], effective_to, 1 if is_active else 0, ts, ts)
    )
    db.commit()
    schedule = row_to_dict(db.execute("SELECT * FROM fee_schedules WHERE id = ?", (fid,)).fetchone())
    return success_response(schedule, 201)


@app.route('/fee-schedules', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def list_fee_schedules():
    db = get_db()
    conditions = []
    params = []
    for filt, col in [('shelter_id', 'shelter_id'), ('fee_type', 'fee_type'), ('species', 'species')]:
        val = request.args.get(filt)
        if val:
            conditions.append(f"{col} = ?")
            params.append(val)
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    base = f"SELECT * FROM fee_schedules{where} ORDER BY created_at ASC"
    count = f"SELECT COUNT(*) FROM fee_schedules{where}"
    return paginate_query(base, tuple(params), count, tuple(params))


@app.route('/fee-schedules/<fs_id>', methods=['GET'])
@require_roles('ShelterManager', 'CaseWorker')
def get_fee_schedule(fs_id):
    db = get_db()
    schedule = db.execute("SELECT * FROM fee_schedules WHERE id = ?", (fs_id,)).fetchone()
    if not schedule:
        return error_response("ERR_FEE_SCHEDULE_NOT_FOUND", "Fee schedule not found.", 404)
    return success_response(row_to_dict(schedule))


# ════════════════════════════════════════════════════════════
# MAIN
# ════════════════════════════════════════════════════════════

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)
