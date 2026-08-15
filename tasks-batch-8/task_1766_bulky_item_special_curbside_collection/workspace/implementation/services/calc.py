"""Business logic: calculations, allowance ledger, pricing, notifications.

Internal notes:
- Records store datetimes internally; serializers format them.
- Item allowance consumption carries an internal `_ledger_counted` marker so the
  REFUSED -> SCHEDULED recovery loop is idempotent (PRD 3.3: "the ledger is
  idempotent across this recovery loop ... items already counted keep their
  flags and are skipped").
"""
from datetime import datetime, time, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP

import db
from middleware import parse_date

# --- Fee constants (SCAFFOLD calculations.item_fee_quote / final_invoice) ---
OVER_ALLOWANCE_FEE_CENTS = 2500
REFRIGERANT_FEE_CENTS = 4500
OVERSIZE_FEE_CENTS = 1500
MATTRESS_FEE_CENTS = 1200
SURCHARGE_RATE = Decimal('0.085')
CONTAMINATION_PENALTY_CENTS = 3000

# --- Illegal dumping fine (calculations.illegal_dumping_fine) ---
BASE_FINE_CENTS = 25000
ESCALATION_CAP = 3

# --- Load units (calculations.request_load_units) ---
LOAD_BY_CATEGORY = {
    'STANDARD_FURNITURE': 2,
    'MATTRESS': 3,
    'APPLIANCE_NO_REFRIGERANT': 4,
    'APPLIANCE_WITH_REFRIGERANT': 5,
    'ELECTRONICS': 2,
    'TIRES': 1,
    'PROHIBITED': 0,
}
OVERSIZE_LOAD_MULTIPLIER = 2

CATEGORIES = set(LOAD_BY_CATEGORY.keys())

# --- Disposition routing (calculations.disposition_routing) ---
ROUTE_BY_CATEGORY = {
    'STANDARD_FURNITURE': 'LANDFILL',
    'MATTRESS': 'MATTRESS_RECYCLING',
    'APPLIANCE_NO_REFRIGERANT': 'METAL_RECYCLING',
    'APPLIANCE_WITH_REFRIGERANT': 'REFRIGERANT_RECOVERY',
    'ELECTRONICS': 'E_WASTE',
    'TIRES': 'TIRE_RECYCLING',
}

REFUSAL_REASON_CODES = {
    'IMPROPER_PREPARATION', 'PROHIBITED_ITEM', 'BLOCKED_ACCESS',
    'UNSAFE_SETOUT', 'EXCEEDS_DECLARED_ITEMS',
}
MISSED_REASON_CODES = {'NO_SETOUT', 'NOT_VISIBLE', 'GATE_LOCKED'}

ZONES = {'ZONE_NORTH', 'ZONE_SOUTH', 'ZONE_EAST', 'ZONE_WEST'}

PREP_INSTRUCTIONS = {
    'STANDARD_FURNITURE': 'Remove or secure all drawers and doors; place at the curb by 6:00 AM.',
    'MATTRESS': 'Seal the mattress or box spring in a plastic disposal bag before set-out.',
    'APPLIANCE_NO_REFRIGERANT': 'Remove or tape shut all doors; drain any residual water.',
    'APPLIANCE_WITH_REFRIGERANT': 'Refrigerant must be evacuated by a certified technician and the unit tagged before set-out.',
    'ELECTRONICS': 'Place electronics in a clear bag or open box; erase personal data.',
    'TIRES': 'Stack tires off the rim at the curb.',
    'PROHIBITED': 'This category is prohibited and cannot be collected curbside.',
}


def touch(rec):
    """PRD 2.5: version increments by exactly 1 on every mutation incl. cascades."""
    rec['updated_at'] = db.wall_now()
    rec['version'] += 1


def request_items(req_id):
    """Items of a request in deterministic order: created_at ASC, sequence_no ASC."""
    rows = [it for it in db.items.values() if it['pickup_request_id'] == req_id]
    rows.sort(key=lambda it: (it['created_at'], it['sequence_no']))
    return rows


def compute_load_units(req_id):
    total = 0
    for it in request_items(req_id):
        mult = OVERSIZE_LOAD_MULTIPLIER if it['is_oversize'] else 1
        total += LOAD_BY_CATEGORY[it['category']] * mult
    return total


def _round_half_up_int(dec):
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def _item_fee(item, within_allowance, amnesty_applied):
    base_over = 0 if within_allowance else OVER_ALLOWANCE_FEE_CENTS
    if amnesty_applied:
        base_over = 0  # amnesty waives only the over-allowance component
    refrigerant = REFRIGERANT_FEE_CENTS if item['category'] == 'APPLIANCE_WITH_REFRIGERANT' else 0
    oversize = OVERSIZE_FEE_CENTS if item['is_oversize'] else 0
    mattress = MATTRESS_FEE_CENTS if item['category'] == 'MATTRESS' else 0
    subtotal = base_over + refrigerant + oversize + mattress
    surcharge = _round_half_up_int(Decimal(subtotal) * SURCHARGE_RATE)
    return subtotal + surcharge


def run_quote(req, variant):
    """item_fee_quote: per-item surcharge rounded half-up BEFORE summing (pinned)."""
    total = 0
    for it in request_items(req['id']):
        if variant == 'provisional':
            fee = _item_fee(it, within_allowance=False, amnesty_applied=False)
        else:  # scheduled
            fee = _item_fee(it, it['within_allowance'], req['amnesty_applied'])
        it['item_fee_cents'] = fee
        total += fee
    req['provisional_total_cents'] = total
    return total


def get_or_create_ledger(household_id, year):
    key = (household_id, year)
    lid = db.allowance_index.get(key)
    if lid is not None:
        return db.allowances[lid]
    now = db.wall_now()
    row = {
        'id': db.new_id(),
        'household_id': household_id,
        'calendar_year': year,
        'items_consumed': 0,
        'items_released': 0,
        'over_allowance_items': 0,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.allowances[row['id']] = row
    db.allowance_index[key] = row['id']
    return row


def consume_allowance(household, req):
    """allowance_ledger consume. Idempotent for REFUSED -> SCHEDULED re-booking:
    items already counted on this request keep flags and are skipped."""
    year = int(req['scheduled_date'][:4])
    ledger = get_or_create_ledger(household['id'], year)
    remaining = household['annual_allowance_items'] - ledger['items_consumed']
    changed = False
    for it in request_items(req['id']):
        if it.get('_ledger_counted'):
            continue
        if remaining > 0:
            it['within_allowance'] = True
            ledger['items_consumed'] += 1
            remaining -= 1
        else:
            it['within_allowance'] = False
            ledger['over_allowance_items'] += 1
        it['_ledger_counted'] = True
        changed = True
    if changed:
        touch(ledger)
    return ledger


def release_allowance(req):
    """allowance_ledger release (scheduled-cancel / miss / cancel-after-refusal)."""
    if not req['scheduled_date']:
        return
    year = int(req['scheduled_date'][:4])
    lid = db.allowance_index.get((req['household_id'], year))
    ledger = db.allowances[lid] if lid else None
    n_within = 0
    n_over = 0
    for it in request_items(req['id']):
        if it.get('_ledger_counted'):
            if it['within_allowance']:
                n_within += 1
            else:
                n_over += 1
        it['within_allowance'] = False
        it['_ledger_counted'] = False
    if ledger is not None and (n_within or n_over):
        ledger['items_consumed'] -= n_within
        ledger['items_released'] += n_within
        ledger['over_allowance_items'] -= n_over
        touch(ledger)


def amnesty_applies(scheduled_date_str):
    """True iff an ACTIVE window's half-open interval contains the date's midnight."""
    d = parse_date(scheduled_date_str)
    if d is None:
        return False
    midnight = datetime.combine(d, time.min, tzinfo=timezone.utc)
    for w in db.amnesty_windows.values():
        if w['status'] != 'ACTIVE':
            continue
        if w['starts_at'] <= midnight < w['ends_at']:
            return True
    return False


def projected_fields(route):
    """route_fullness projected variant: SCHEDULED requests only."""
    load = 0
    for r in db.pickup_requests.values():
        if r['route_day_id'] == route['id'] and r['status'] == 'SCHEDULED':
            load += r['load_units']
    maxu = route['max_load_units']
    if maxu > 0:
        pct = _round_half_up_int(Decimal(100 * load) / Decimal(maxu))
    else:
        pct = 0
    return load, pct


def final_invoice_amount(req, flagged_item_ids):
    """final_invoice: provisional_total + flat contamination penalty per flagged item."""
    return req['provisional_total_cents'] + CONTAMINATION_PENALTY_CENTS * len(flagged_item_ids)


def illegal_dumping_fine_amount(report):
    """Prior confirmed violations escalate: base * 2^min(priors, cap).
    Priors: DETERMINED_ILLEGAL, reported_at strictly earlier; ties by created_at ASC."""
    priors = 0
    for r in db.reports.values():
        if r['id'] == report['id']:
            continue
        if r['household_id'] != report['household_id']:
            continue
        if r['status'] != 'DETERMINED_ILLEGAL':
            continue
        if (r['reported_at'] < report['reported_at'] or
                (r['reported_at'] == report['reported_at'] and r['created_at'] < report['created_at'])):
            priors += 1
    return BASE_FINE_CENTS * (2 ** min(priors, ESCALATION_CAP))


def create_assessment(pickup_request_id, household_id, kind, amount_cents):
    now = db.wall_now()
    a = {
        'id': db.new_id(),
        'pickup_request_id': pickup_request_id,
        'household_id': household_id,
        'kind': kind,
        'amount_cents': amount_cents,
        'status': 'PENDING',
        'settled_at': None,
        'created_at': now,
        'updated_at': now,
        'version': 1,
    }
    db.assessments[a['id']] = a
    return a


def waive_pending_quote(req_id):
    """System cascade: void the PENDING PROVISIONAL_QUOTE assessment, if any."""
    for a in db.assessments.values():
        if (a['pickup_request_id'] == req_id and a['kind'] == 'PROVISIONAL_QUOTE'
                and a['status'] == 'PENDING'):
            a['status'] = 'WAIVED'
            a['settled_at'] = db.get_clock()
            touch(a)


def emit_notification(req_id, kind, reason_code=None, message=''):
    n = {
        'id': db.new_id(),
        'pickup_request_id': req_id,
        'kind': kind,
        'reason_code': reason_code,
        'message': message,
        'created_at': db.wall_now(),
    }
    db.notifications[n['id']] = n
    return n


def refusal_message(req_id, reason_code):
    lines = [f'Pickup refused: {reason_code}.', 'Preparation instructions:']
    for it in request_items(req_id):
        lines.append(f"- {it['category']}: {PREP_INSTRUCTIONS[it['category']]}")
    return '\n'.join(lines)


def qualifying_scheduled_link(report):
    """True iff the report links a request that is SCHEDULED with scheduled_date
    within [reported_at date - 1 day, reported_at date + 1 day] (inclusive)."""
    rid = report['pickup_request_id']
    if not rid:
        return False
    req = db.pickup_requests.get(rid)
    if req is None or req['status'] != 'SCHEDULED' or not req['scheduled_date']:
        return False
    sched = parse_date(req['scheduled_date'])
    if sched is None:
        return False
    rep_date = report['reported_at'].astimezone(timezone.utc).date()
    return (rep_date - timedelta(days=1)) <= sched <= (rep_date + timedelta(days=1))
