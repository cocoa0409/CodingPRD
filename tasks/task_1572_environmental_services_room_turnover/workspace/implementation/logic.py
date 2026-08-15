"""Calculations, cascades, selectors, and serializers (SCAFFOLD §1.3)."""
import math
from datetime import timedelta
from decimal import Decimal

from common import ApiError, fmt_dt, new_id, now, round2, round_int
from store import store

CLEAN_TYPES = ['ROUTINE', 'ISOLATION', 'TERMINAL']
BED_KINDS = ['STANDARD', 'ISOLATION', 'ICU']
URGENCY_TIERS = ['STAT', 'URGENT', 'STANDARD']
PATHOGEN_CLASSES = ['C_DIFF', 'MRSA', 'NOROVIRUS', 'OTHER']
ITEM_CODES = ['DISINFECTANT', 'PPE_PACK', 'CLOTH', 'SEALANT']
CAPABILITIES = ['CLEAN', 'AUDIT']
CERTIFICATIONS = ['ISO_CERT', 'TERMINAL_CERT']

OPEN_REQUEST_STATUSES = ['QUEUED', 'ASSIGNED', 'IN_PROGRESS', 'PENDING_QA', 'NEEDS_RECLEAN']
TERMINAL_REQUEST_STATUSES = ['VERIFIED', 'CANCELLED']

URGENCY_BASE = {'STAT': 1000, 'URGENT': 500, 'STANDARD': 100}
TIER_BASE = {'STAT': 10000, 'URGENT': 5000, 'STANDARD': 0}
TIER_RANK = {'STAT': 3, 'URGENT': 2, 'STANDARD': 1}
BREACH_BOOST = 2500
SCARCITY_BONUS = 50
WAIT_CAP_MINUTES = 120
WAIT_WEIGHT_PER_MINUTE = 2
STAT_CAP_MINUTES = 45
BASE_CREDIT = {'ROUTINE': Decimal('1.00'), 'ISOLATION': Decimal('1.50'),
               'TERMINAL': Decimal('2.00')}
EF_FLOOR = Decimal('0.50')
EF_CAP = Decimal('1.50')
QA_FAIL_PENALTY = Decimal('5.00')
STAT_ELIGIBILITY_THRESHOLD = Decimal('80.00')
FLUORESCENT_PASS_FRACTION = Decimal('0.85')
RECLEAN_CONSUMPTION_RATIO = Decimal('0.5')
MAINTENANCE_CAP_PCT = Decimal('0.20')
NOTIFICATION_EXPIRY_MINUTES = 60

BOM = {
    'ROUTINE': [('DISINFECTANT', 2), ('CLOTH', 4)],
    'ISOLATION': [('DISINFECTANT', 4), ('PPE_PACK', 2), ('CLOTH', 6)],
    'TERMINAL': [('DISINFECTANT', 6), ('PPE_PACK', 3), ('CLOTH', 8), ('SEALANT', 1)],
}
CERT_REQUIRED = {'ROUTINE': None, 'ISOLATION': 'ISO_CERT', 'TERMINAL': 'TERMINAL_CERT'}


def touch(entity):
    entity['updated_at'] = now()
    entity['version'] += 1


def standard_by_type(clean_type):
    for s in store.standards.values():
        if s['clean_type'] == clean_type:
            return s
    return None


def item_by_code(item_code):
    for i in store.supply_items.values():
        if i['item_code'] == item_code:
            return i
    return None


# ------------------------------------------------------------ demand scoring
def demand_score(d):
    wait_seconds = (now() - d['created_at']).total_seconds()
    wait_minutes = max(0, math.floor(wait_seconds / 60))
    score = Decimal(URGENCY_BASE[d['urgency_tier']])
    score += Decimal(min(wait_minutes, WAIT_CAP_MINUTES) * WAIT_WEIGHT_PER_MINUTE)
    ready_count = sum(1 for b in store.beds.values()
                      if b['unit_id'] == d['unit_id']
                      and b['bed_kind'] == d['required_bed_kind']
                      and b['bed_status'] == 'READY')
    if ready_count == 0:
        score += Decimal(SCARCITY_BONUS)
    return round2(score)


# ------------------------------------------------------ clean-request scoring
def contributing_demands(req):
    bed = store.beds.get(req['bed_id'])
    if bed is None:
        return []
    return [d for d in store.demands.values()
            if d['unit_id'] == req['unit_id'] and d['status'] == 'OPEN'
            and d['required_bed_kind'] == bed['bed_kind']]


def request_tier(req):
    contrib = contributing_demands(req)
    if not contrib:
        return 'STANDARD'
    return max(contrib, key=lambda d: TIER_RANK[d['urgency_tier']])['urgency_tier']


def request_score(req):
    tier = request_tier(req)
    contrib = contributing_demands(req)
    demand_part = max((demand_score(d) for d in contrib), default=Decimal('0'))
    score = Decimal(TIER_BASE[tier]) + demand_part
    if req['sla_breached']:
        score += Decimal(BREACH_BOOST)
    return round2(score)


# -------------------------------------------------------- time standard (pin)
def compute_standard_target(base_minutes, mult_bps, with_outbreak, tier):
    raw = Decimal(base_minutes)
    if with_outbreak:
        raw = raw * Decimal(mult_bps) / Decimal(10000)
    target = round_int(raw)
    if tier == 'STAT':
        target = min(target, STAT_CAP_MINUTES)
    return target


def pin_request(req, standard, posture):
    with_outbreak = posture == 'OUTBREAK'
    req['pinned_base_minutes'] = standard['base_minutes']
    req['pinned_outbreak_multiplier_bps'] = standard['outbreak_multiplier_bps']
    req['pinned_with_outbreak'] = with_outbreak
    target = compute_standard_target(standard['base_minutes'],
                                     standard['outbreak_multiplier_bps'],
                                     with_outbreak, request_tier(req))
    req['sla_target_minutes'] = target
    req['sla_due_at'] = req['created_at'] + timedelta(minutes=target)


def current_estimate(req):
    std = standard_by_type(req['clean_type'])
    if std is None:
        return None
    unit = store.units.get(req['unit_id'])
    posture = unit['outbreak_posture'] if unit else 'NORMAL'
    return compute_standard_target(std['base_minutes'], std['outbreak_multiplier_bps'],
                                   posture == 'OUTBREAK', request_tier(req))


def planned_end(req):
    if req['planned_start_at'] is None:
        return None
    return req['planned_start_at'] + timedelta(minutes=req['sla_target_minutes'])


def create_clean_request(bed, clean_type):
    std = standard_by_type(clean_type)
    if std is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % clean_type, 404)
    now_ = now()
    req = {
        'id': new_id(), 'bed_id': bed['id'], 'unit_id': bed['unit_id'],
        'clean_type': clean_type, 'status': 'QUEUED', 'sla_breached': False,
        'assigned_staff_id': None, 'last_completed_by_staff_id': None,
        'reclean_count': 0, 'planned_start_at': None,
        'first_started_at': None, 'started_at': None, 'completed_at': None,
        'verified_at': None, 'supply_reserved': False, '_reserved_lines': None,
        'pinned_base_minutes': None, 'pinned_outbreak_multiplier_bps': None,
        'pinned_with_outbreak': False, 'sla_target_minutes': None, 'sla_due_at': None,
        '_tat_total_at_verify': None, '_tat_clean_at_verify': None,
        'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq(),
    }
    unit = store.units[bed['unit_id']]
    pin_request(req, std, unit['outbreak_posture'])
    store.requests[req['id']] = req
    return req


# ------------------------------------------------------------------ supplies
def on_hand(item_id):
    return sum(e['quantity_delta'] for e in store.ledger.values()
               if e['supply_item_id'] == item_id)


def reserved_qty(item):
    total = 0
    for r in store.requests.values():
        if r['supply_reserved'] and r.get('_reserved_lines'):
            total += r['_reserved_lines'].get(item['item_code'], 0)
    return total


def stock_status(item):
    return 'LOW' if on_hand(item['id']) <= item['reorder_threshold'] else 'STOCKED'


def bom_lines(clean_type, reclean_count):
    lines = []
    for code, qty in BOM[clean_type]:
        if reclean_count > 0:
            qty = round_int(Decimal(qty) * RECLEAN_CONSUMPTION_RATIO)
        lines.append((code, qty))
    return lines


def write_ledger(supply_item_id, entry_type, quantity_delta, clean_request_id=None, note=None):
    entry = {
        'id': new_id(), 'supply_item_id': supply_item_id,
        'clean_request_id': clean_request_id, 'entry_type': entry_type,
        'quantity_delta': quantity_delta, 'note': note,
        'created_at': now(), '_seq': store.next_seq(),
    }
    store.ledger[entry['id']] = entry
    return entry


# -------------------------------------------------------------------- staff
def active_clean_count(staff_id):
    return sum(1 for r in store.requests.values()
               if r['assigned_staff_id'] == staff_id
               and r['status'] in ('ASSIGNED', 'IN_PROGRESS'))


def productivity_score(s):
    if s['shift_seconds_today'] == 0:
        return Decimal('0.00')
    hours = Decimal(s['shift_seconds_today']) / Decimal(3600)
    score = Decimal(100) * s['verified_credit_total'] / hours
    score -= QA_FAIL_PENALTY * Decimal(s['qa_fail_count'])
    score = round2(score)
    return score if score > 0 else Decimal('0.00')


def stat_eligible(s):
    return s['completed_clean_count'] == 0 or productivity_score(s) >= STAT_ELIGIBILITY_THRESHOLD


def staff_window_conflict(staff_id, exclude_req_id, new_start, new_end):
    buf = timedelta(minutes=10)
    for r in store.requests.values():
        if r['assigned_staff_id'] != staff_id or r['id'] == exclude_req_id:
            continue
        if r['status'] not in ('ASSIGNED', 'IN_PROGRESS'):
            continue
        ps = r['planned_start_at']
        if ps is None:
            continue
        pe = ps + timedelta(minutes=r['sla_target_minutes'])
        if not (new_start >= pe + buf or ps >= new_end + buf):
            return True
    return False


def certification_covers(staff, clean_type):
    required = CERT_REQUIRED[clean_type]
    return required is None or required in staff['certifications']


# -------------------------------------------------------------- audit result
def audit_result(clean_type, audit_method, rlu_reading, marker_fraction_removed):
    std = standard_by_type(clean_type)
    if std is None:
        raise ApiError('ERR_STANDARD_NOT_FOUND',
                       'No clean standard exists for clean_type %s' % clean_type, 404)
    if audit_method == 'ATP_SWAB':
        threshold = std['atp_rlu_threshold']
        result = 'PASS' if rlu_reading <= threshold else 'FAIL'
        return result, threshold
    threshold = FLUORESCENT_PASS_FRACTION
    result = 'PASS' if Decimal(str(marker_fraction_removed)) >= threshold else 'FAIL'
    return result, float(threshold)


# ------------------------------------------------------------------ cascades
def apply_pass(req):
    now_ = now()
    req['status'] = 'VERIFIED'
    req['verified_at'] = now_
    touch(req)
    completer = store.staff.get(req['last_completed_by_staff_id'])
    if completer is not None:
        actual_seconds = (req['completed_at'] - req['started_at']).total_seconds()
        actual_minutes = max(1, math.floor(actual_seconds / 60))
        ef = Decimal(req['sla_target_minutes']) / Decimal(actual_minutes)
        ef = min(EF_CAP, max(EF_FLOOR, ef))
        credit = round2(BASE_CREDIT[req['clean_type']] * ef)
        completer['completed_clean_count'] += 1
        completer['verified_credit_total'] += credit
        touch(completer)
    bed = store.beds[req['bed_id']]
    bed['bed_status'] = 'READY'
    bed['last_ready_at'] = now_
    base = bed['last_discharge_at'] or bed['created_at']
    tat_total = math.floor((now_ - base).total_seconds() / 60)
    tat_clean = math.floor((req['verified_at'] - req['first_started_at']).total_seconds() / 60)
    bed['tat_total_minutes'] = tat_total
    bed['tat_clean_minutes'] = tat_clean
    touch(bed)
    req['_tat_total_at_verify'] = tat_total
    req['_tat_clean_at_verify'] = tat_clean
    bed_ready_match(bed)


def apply_fail(req):
    req['status'] = 'NEEDS_RECLEAN'
    req['reclean_count'] += 1
    touch(req)
    completer = store.staff.get(req['last_completed_by_staff_id'])
    if completer is not None:
        completer['qa_fail_count'] += 1
        touch(completer)
    bed = store.beds[req['bed_id']]
    bed['bed_status'] = 'VACANT_DIRTY'
    touch(bed)


def bed_ready_match(bed):
    candidates = [d for d in store.demands.values()
                  if d['unit_id'] == bed['unit_id'] and d['status'] == 'OPEN'
                  and d['required_bed_kind'] == bed['bed_kind']]
    if not candidates:
        return
    candidates.sort(key=lambda d: (-demand_score(d), d['created_at'], d['_seq']))
    top = candidates[0]
    top['status'] = 'MATCHED'
    top['matched_bed_id'] = bed['id']
    touch(top)
    now_ = now()
    notif = {
        'id': new_id(), 'bed_id': bed['id'], 'demand_id': top['id'],
        'status': 'SENT', 'sent_at': now_, 'acknowledged_at': None,
        'created_at': now_, 'updated_at': now_, 'version': 1, '_seq': store.next_seq(),
    }
    store.notifications[notif['id']] = notif


def retract_bed_notifications(bed):
    """mark-soiled / maintenance-activation cascade (depth 3)."""
    for n in store.notifications.values():
        if n['bed_id'] == bed['id'] and n['status'] in ('SENT', 'ACKNOWLEDGED'):
            n['status'] = 'RETRACTED'
            touch(n)
            d = store.demands.get(n['demand_id'])
            if d is not None and d['status'] == 'MATCHED' and d['matched_bed_id'] == bed['id']:
                d['status'] = 'OPEN'
                d['matched_bed_id'] = None
                touch(d)


# ------------------------------------------------------------------ ops-run
def nearest_rank(series, p):
    if not series:
        return None
    s = sorted(series)
    rank = math.ceil(p / 100 * len(s))
    return s[rank - 1]


def ops_run(unit):
    now_ = now()
    # 1. SLA breach sweep
    for r in store.requests.values():
        if r['unit_id'] == unit['id'] and r['status'] in ('QUEUED', 'ASSIGNED', 'IN_PROGRESS'):
            if now_ > r['sla_due_at'] and not r['sla_breached']:
                r['sla_breached'] = True
                touch(r)
    # 2. demand expiry (strict before; equality stays OPEN)
    for d in store.demands.values():
        if d['unit_id'] == unit['id'] and d['status'] == 'OPEN' and d['needed_by'] < now_:
            d['status'] = 'EXPIRED'
            touch(d)
    # 3. notification expiry (strictly more than 60 minutes old)
    for n in store.notifications.values():
        bed = store.beds.get(n['bed_id'])
        if bed is None or bed['unit_id'] != unit['id']:
            continue
        if n['status'] == 'SENT' and now_ > n['sent_at'] + timedelta(minutes=NOTIFICATION_EXPIRY_MINUTES):
            n['status'] = 'EXPIRED'
            touch(n)
            d = store.demands.get(n['demand_id'])
            if d is not None and d['status'] == 'MATCHED':
                d['status'] = 'OPEN'
                d['matched_bed_id'] = None
                touch(d)
    # 4. rematch pass
    for bed in store.beds.values():
        if bed['unit_id'] != unit['id'] or bed['bed_status'] != 'READY':
            continue
        has_open_notif = any(n for n in store.notifications.values()
                             if n['bed_id'] == bed['id']
                             and n['status'] in ('SENT', 'ACKNOWLEDGED'))
        if not has_open_notif:
            bed_ready_match(bed)
    # snapshot over [prev window_end or unit.created_at, now)
    prev_ends = [s['window_end'] for s in store.snapshots.values()
                 if s['unit_id'] == unit['id']]
    window_start = max(prev_ends) if prev_ends else unit['created_at']
    verified_set = [r for r in store.requests.values()
                    if r['unit_id'] == unit['id'] and r['verified_at'] is not None
                    and window_start <= r['verified_at'] < now_]
    tat_totals = [r['_tat_total_at_verify'] for r in verified_set]
    tat_cleans = [r['_tat_clean_at_verify'] for r in verified_set]
    snap = {
        'id': new_id(), 'unit_id': unit['id'], 'ops_run_index': unit['ops_run_index'],
        'window_start': window_start, 'window_end': now_,
        'verified_count': len(verified_set),
        'sla_breach_count': sum(1 for r in verified_set if r['verified_at'] > r['sla_due_at']),
        'tat_total_p50_minutes': nearest_rank(tat_totals, 50),
        'tat_total_p90_minutes': nearest_rank(tat_totals, 90),
        'tat_clean_p50_minutes': nearest_rank(tat_cleans, 50),
        'tat_clean_p90_minutes': nearest_rank(tat_cleans, 90),
        'created_at': now_, '_seq': store.next_seq(),
    }
    store.snapshots[snap['id']] = snap
    unit['ops_run_index'] += 1
    touch(unit)
    return snap


# ----------------------------------------------------- maintenance capacity
def maintenance_capacity_ok(bed, new_start, new_end, exclude_id=None):
    unit_beds = [b for b in store.beds.values() if b['unit_id'] == bed['unit_id']]
    cap = max(1, int(MAINTENANCE_CAP_PCT * Decimal(len(unit_beds))))
    existing = [w for w in store.windows.values()
                if w['id'] != exclude_id and w['status'] in ('SCHEDULED', 'ACTIVE')
                and store.beds[w['bed_id']]['unit_id'] == bed['unit_id']]
    overlapping = [w for w in existing
                   if w['start_at'] < new_end and new_start < w['end_at']]
    instants = {new_start} | {w['start_at'] for w in overlapping}
    for t in instants:
        count = sum(1 for w in overlapping if w['start_at'] <= t < w['end_at'])
        if count + 1 > cap:
            return False
    return True


# ------------------------------------------------------------- serializers
def unit_dict(u):
    return {'id': u['id'], 'unit_code': u['unit_code'], 'display_name': u['display_name'],
            'outbreak_posture': u['outbreak_posture'], 'ops_run_index': u['ops_run_index'],
            'created_at': fmt_dt(u['created_at']), 'updated_at': fmt_dt(u['updated_at']),
            'version': u['version']}


def bed_dict(b):
    return {'id': b['id'], 'unit_id': b['unit_id'], 'bed_code': b['bed_code'],
            'bed_kind': b['bed_kind'], 'bed_status': b['bed_status'],
            'last_discharge_at': fmt_dt(b['last_discharge_at']),
            'last_ready_at': fmt_dt(b['last_ready_at']),
            'tat_total_minutes': b['tat_total_minutes'],
            'tat_clean_minutes': b['tat_clean_minutes'],
            'created_at': fmt_dt(b['created_at']), 'updated_at': fmt_dt(b['updated_at']),
            'version': b['version']}


def demand_dict(d):
    return {'id': d['id'], 'unit_id': d['unit_id'],
            'required_bed_kind': d['required_bed_kind'],
            'urgency_tier': d['urgency_tier'], 'needed_by': fmt_dt(d['needed_by']),
            'status': d['status'], 'priority_score': float(demand_score(d)),
            'matched_bed_id': d['matched_bed_id'],
            'fulfilled_at': fmt_dt(d['fulfilled_at']),
            'created_at': fmt_dt(d['created_at']), 'updated_at': fmt_dt(d['updated_at']),
            'version': d['version']}


def request_dict(r):
    return {'id': r['id'], 'bed_id': r['bed_id'], 'unit_id': r['unit_id'],
            'clean_type': r['clean_type'], 'status': r['status'],
            'priority_tier': request_tier(r),
            'priority_score': float(request_score(r)),
            'sla_target_minutes': r['sla_target_minutes'],
            'sla_due_at': fmt_dt(r['sla_due_at']),
            'sla_breached': r['sla_breached'],
            'current_estimate_minutes': current_estimate(r),
            'pinned_base_minutes': r['pinned_base_minutes'],
            'pinned_outbreak_multiplier_bps': r['pinned_outbreak_multiplier_bps'],
            'pinned_with_outbreak': r['pinned_with_outbreak'],
            'assigned_staff_id': r['assigned_staff_id'],
            'last_completed_by_staff_id': r['last_completed_by_staff_id'],
            'reclean_count': r['reclean_count'],
            'planned_start_at': fmt_dt(r['planned_start_at']),
            'planned_end_at': fmt_dt(planned_end(r)),
            'first_started_at': fmt_dt(r['first_started_at']),
            'started_at': fmt_dt(r['started_at']),
            'completed_at': fmt_dt(r['completed_at']),
            'verified_at': fmt_dt(r['verified_at']),
            'supply_reserved': r['supply_reserved'],
            'created_at': fmt_dt(r['created_at']), 'updated_at': fmt_dt(r['updated_at']),
            'version': r['version']}


def staff_dict(s):
    return {'id': s['id'], 'employee_code': s['employee_code'],
            'display_name': s['display_name'], 'capabilities': s['capabilities'],
            'certifications': s['certifications'], 'shift_status': s['shift_status'],
            'active_clean_count': active_clean_count(s['id']),
            'completed_clean_count': s['completed_clean_count'],
            'verified_credit_total': float(round2(s['verified_credit_total'])),
            'qa_fail_count': s['qa_fail_count'],
            'shift_seconds_today': s['shift_seconds_today'],
            'productivity_score': float(productivity_score(s)),
            'stat_eligible': stat_eligible(s),
            'last_clock_in_at': fmt_dt(s['last_clock_in_at']),
            'break_started_at': fmt_dt(s['break_started_at']),
            'created_at': fmt_dt(s['created_at']), 'updated_at': fmt_dt(s['updated_at']),
            'version': s['version']}


def audit_dict(a):
    return {'id': a['id'], 'clean_request_id': a['clean_request_id'],
            'auditor_id': a['auditor_id'], 'audit_method': a['audit_method'],
            'rlu_reading': a['rlu_reading'],
            'marker_fraction_removed': a['marker_fraction_removed'],
            'result': a['result'], 'threshold_used': a['threshold_used'],
            'audit_status': a['audit_status'],
            'created_ops_run_index': a['created_ops_run_index'],
            'created_at': fmt_dt(a['created_at']), 'updated_at': fmt_dt(a['updated_at']),
            'version': a['version']}


def supply_item_dict(i):
    return {'id': i['id'], 'item_code': i['item_code'], 'display_name': i['display_name'],
            'on_hand_quantity': on_hand(i['id']), 'reserved_quantity': reserved_qty(i),
            'reorder_threshold': i['reorder_threshold'], 'stock_status': stock_status(i),
            'created_at': fmt_dt(i['created_at']), 'updated_at': fmt_dt(i['updated_at']),
            'version': i['version']}


def ledger_dict(e):
    return {'id': e['id'], 'supply_item_id': e['supply_item_id'],
            'clean_request_id': e['clean_request_id'], 'entry_type': e['entry_type'],
            'quantity_delta': e['quantity_delta'], 'note': e['note'],
            'created_at': fmt_dt(e['created_at'])}


def outbreak_dict(o):
    return {'id': o['id'], 'unit_id': o['unit_id'], 'pathogen_class': o['pathogen_class'],
            'declared_reason': o['declared_reason'], 'status': o['status'],
            'activated_at': fmt_dt(o['activated_at']), 'lifted_at': fmt_dt(o['lifted_at']),
            'created_at': fmt_dt(o['created_at']), 'updated_at': fmt_dt(o['updated_at']),
            'version': o['version']}


def notification_dict(n):
    return {'id': n['id'], 'bed_id': n['bed_id'], 'demand_id': n['demand_id'],
            'status': n['status'], 'sent_at': fmt_dt(n['sent_at']),
            'acknowledged_at': fmt_dt(n['acknowledged_at']),
            'created_at': fmt_dt(n['created_at']), 'updated_at': fmt_dt(n['updated_at']),
            'version': n['version']}


def window_dict(w):
    return {'id': w['id'], 'bed_id': w['bed_id'], 'start_at': fmt_dt(w['start_at']),
            'end_at': fmt_dt(w['end_at']), 'reason': w['reason'], 'status': w['status'],
            'created_at': fmt_dt(w['created_at']), 'updated_at': fmt_dt(w['updated_at']),
            'version': w['version']}


def standard_dict(s):
    return {'id': s['id'], 'clean_type': s['clean_type'], 'base_minutes': s['base_minutes'],
            'outbreak_multiplier_bps': s['outbreak_multiplier_bps'],
            'atp_rlu_threshold': s['atp_rlu_threshold'],
            'created_at': fmt_dt(s['created_at']), 'updated_at': fmt_dt(s['updated_at']),
            'version': s['version']}


def snapshot_dict(s):
    return {'id': s['id'], 'unit_id': s['unit_id'], 'ops_run_index': s['ops_run_index'],
            'window_start': fmt_dt(s['window_start']), 'window_end': fmt_dt(s['window_end']),
            'verified_count': s['verified_count'], 'sla_breach_count': s['sla_breach_count'],
            'tat_total_p50_minutes': s['tat_total_p50_minutes'],
            'tat_total_p90_minutes': s['tat_total_p90_minutes'],
            'tat_clean_p50_minutes': s['tat_clean_p50_minutes'],
            'tat_clean_p90_minutes': s['tat_clean_p90_minutes'],
            'created_at': fmt_dt(s['created_at'])}
