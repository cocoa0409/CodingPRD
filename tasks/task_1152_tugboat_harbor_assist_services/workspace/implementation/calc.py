"""Calculations (PRD §2.7, §3), cascades (§2.9) and serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, touch, new_id, stamp_new, stamp_new_immutable
from util import fmt_dt, fmt_opt, half_open_overlap

D = Decimal

MANEUVER_FACTOR = {
    'DOCKING': D('1.5'), 'UNDOCKING': D('1.2'), 'SHIFTING': D('1.0'),
    'ESCORT': D('0.8'), 'TOWAGE': D('2.0'),
}
LOA_SURCHARGE_THRESHOLD_M = 200
LOA_MULTIPLIER = D('1.25')
MIN_BOLLARD_PULL_TONS = D('20.0')

MIN_CAP_CENTS = 10_000_000
TUG_VALUE_CAP_FRACTION = D('0.5')
VOYAGE_INVOICE_MULTIPLE = D('20')
DEDUCTIBLE_PCT = D('0.10')

REQUIRED_REST_SECONDS = 600 * 60
REST_WINDOW = timedelta(hours=24)


def cents(dec):
    return int(dec.quantize(D('1'), rounding=ROUND_HALF_UP))


# ------------------------------------------------------------ calculations

def required_bollard_pull(vessel, maneuver_type):
    base = D(vessel['deadweight_tonnage']) * MANEUVER_FACTOR[maneuver_type] / D(1000)
    if vessel['loa_meters'] > LOA_SURCHARGE_THRESHOLD_M:
        base = base * LOA_MULTIPLIER
    val = base.quantize(D('0.1'), rounding=ROUND_HALF_UP)
    if val < MIN_BOLLARD_PULL_TONS:
        val = MIN_BOLLARD_PULL_TONS
    return float(val)


def compute_invoice_lines(job, basis):
    """invoice_charge (PRD §3.8): per-line half-up rounding BEFORE summation."""
    tariff = store.tariff_rates[job['tariff_rate_id']]
    base_fee = tariff['base_fee_cents']
    tug_hire = 0
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['participated']:
            tug = store.tugs[a['tug_id']]
            secs = D(str((a['window_end'] - a['window_start']).total_seconds()))
            hours = (secs / D(3600)).quantize(D('0.01'), rounding=ROUND_HALF_UP)
            line = (D(tug['hourly_rate_cents']) * hours).quantize(D('1'), rounding=ROUND_HALF_UP)
            tug_hire += int(line)
    if basis == 'SCHEDULED':
        standby_minutes = 0
    else:
        delta = (job['actual_start'] - job['scheduled_start']).total_seconds()
        standby_minutes = max(0, int(delta // 60))
    billable = max(0, standby_minutes - tariff['free_standby_minutes'])
    blocks = -(-billable // tariff['standby_block_minutes'])
    standby_cents = blocks * tariff['standby_block_rate_cents']
    subtotal = base_fee + tug_hire + standby_cents
    if job['had_weather_hold']:
        surcharge = cents(D(subtotal) * D(str(tariff['weather_surcharge_pct'])))
    else:
        surcharge = 0
    return {
        'variant_basis': basis,
        'base_fee_cents': base_fee,
        'tug_hire_cents': tug_hire,
        'standby_minutes': standby_minutes,
        'standby_cents': standby_cents,
        'weather_surcharge_cents': surcharge,
        'total_cents': subtotal + surcharge,
    }


def claim_economics(incident, claimed_amount_cents):
    """liability_settlement (PRD §3.9): cap -> min -> deductible -> subtract."""
    finalized = None
    job_id = incident.get('job_order_id')
    if job_id:
        for inv in store.invoices.values():
            if inv['job_order_id'] == job_id and inv['status'] == 'FINALIZED':
                finalized = inv
                break
    if finalized is not None:
        variant = 'PER_VOYAGE'
        cap_raw = cents(VOYAGE_INVOICE_MULTIPLE * D(finalized['total_cents']))
    else:
        variant = 'PER_INCIDENT'
        tug = store.tugs[incident['tug_id']]
        cap_raw = cents(TUG_VALUE_CAP_FRACTION * D(tug['insured_value_cents']))
    cap = max(MIN_CAP_CENTS, cap_raw)
    capped = min(claimed_amount_cents, cap)
    deductible = cents(DEDUCTIBLE_PCT * D(capped))
    payout = capped - deductible
    return variant, cap, deductible, payout


def recompute_vessel_outstanding(vessel_id):
    """vessel_outstanding (PRD §3.9): PROVISIONAL+FINALIZED totals minus SETTLED payouts."""
    inv_sum = 0
    for inv in store.invoices.values():
        if inv['status'] in ('PROVISIONAL', 'FINALIZED'):
            job = store.job_orders.get(inv['job_order_id'])
            if job and job['vessel_id'] == vessel_id:
                inv_sum += inv['total_cents']
    pay_sum = 0
    for cl in store.damage_claims.values():
        if cl['vessel_id'] == vessel_id and cl['status'] == 'SETTLED':
            pay_sum += cl['payout_cents']
    vessel = store.vessels.get(vessel_id)
    if vessel is None:
        return
    new_val = max(0, inv_sum - pay_sum)
    if new_val != vessel['outstanding_billed_cents']:
        vessel['outstanding_billed_cents'] = new_val
        touch(vessel)


# ------------------------------------------------------------ cascades

def any_active_restriction_overlaps(start, end):
    for r in store.weather_restrictions.values():
        if r['status'] == 'ACTIVE' and half_open_overlap(
                r['effective_start'], r['effective_end'], start, end):
            return True
    return False


def cascade_tug_knockout(tug):
    """Supersede future CONFIRMED assignments; demote their CONFIRMED jobs."""
    for a in list(store.tug_assignments.values()):
        if (a['tug_id'] == tug['id'] and a['status'] == 'CONFIRMED'
                and a['window_start'] > now()):
            a['status'] = 'SUPERSEDED'
            touch(a)
            job = store.job_orders.get(a['job_order_id'])
            if job is not None and job['status'] == 'CONFIRMED':
                job['status'] = 'REQUESTED'
                job['needs_reassignment'] = True
                touch(job)


def latest_inspections_per_item(tug_id):
    latest = {}
    for gi in store.gear_inspections.values():
        if gi['tug_id'] != tug_id:
            continue
        cur = latest.get(gi['inspection_item'])
        if cur is None or (gi['inspected_at'], gi['_seq']) >= (cur['inspected_at'], cur['_seq']):
            latest[gi['inspection_item']] = gi
    return latest


def latest_inspection_overall(tug_id):
    best = None
    for gi in store.gear_inspections.values():
        if gi['tug_id'] != tug_id:
            continue
        if best is None or (gi['inspected_at'], gi['_seq']) > (best['inspected_at'], best['_seq']):
            best = gi
    return best


def gear_clean(tug_id):
    """No gear item whose latest inspection is FAILED."""
    for gi in latest_inspections_per_item(tug_id).values():
        if gi['outcome'] == 'FAILED':
            return False
    return True


def has_unresolved_major_incident(tug_id):
    for inc in store.incidents.values():
        if (inc['tug_id'] == tug_id
                and inc['status'] in ('REPORTED', 'UNDER_INVESTIGATION')
                and inc['severity'] in ('MAJOR', 'CRITICAL')):
            return True
    return False


def apply_gear_inspection_cascade(rec):
    tug = store.tugs[rec['tug_id']]
    if rec['outcome'] == 'FAILED':
        if tug['operational_status'] == 'AVAILABLE':
            tug['operational_status'] = 'RESTRICTED'
            touch(tug)
            cascade_tug_knockout(tug)
    else:  # PASSED
        if tug['operational_status'] == 'RESTRICTED':
            if gear_clean(tug['id']) and not has_unresolved_major_incident(tug['id']):
                tug['operational_status'] = 'AVAILABLE'
                touch(tug)


def apply_incident_cascade(incident):
    if incident['severity'] not in ('MAJOR', 'CRITICAL'):
        return
    tug = store.tugs[incident['tug_id']]
    if tug['operational_status'] in ('AVAILABLE', 'RESTRICTED'):
        tug['operational_status'] = 'OUT_OF_SERVICE'
        touch(tug)
        cascade_tug_knockout(tug)


def apply_incident_resolve_cascade(incident):
    tug = store.tugs[incident['tug_id']]
    if tug['operational_status'] != 'OUT_OF_SERVICE':
        return
    if has_unresolved_major_incident(tug['id']):
        return
    tug['operational_status'] = 'AVAILABLE' if gear_clean(tug['id']) else 'RESTRICTED'
    touch(tug)


def apply_restriction_created(rec):
    for job in store.job_orders.values():
        if job['status'] == 'DISPATCHED' and half_open_overlap(
                rec['effective_start'], rec['effective_end'],
                job['scheduled_start'], job['scheduled_end']):
            job['status'] = 'ON_HOLD'
            job['had_weather_hold'] = True
            touch(job)


def apply_restriction_lifted():
    for job in store.job_orders.values():
        if job['status'] == 'ON_HOLD' and not any_active_restriction_overlaps(
                job['scheduled_start'], job['scheduled_end']):
            job['status'] = 'DISPATCHED'
            touch(job)


def release_assignments_on_cancel(job):
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['status'] in ('PROPOSED', 'CONFIRMED'):
            a['status'] = 'RELEASED'
            touch(a)


def cancel_bookings_on_cancel(job):
    for b in store.pilot_bookings.values():
        if b['job_order_id'] == job['id'] and b['status'] in ('REQUESTED', 'CONFIRMED'):
            b['status'] = 'CANCELLED'
            touch(b)


def supersede_on_amend_from_confirmed(job):
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['status'] == 'CONFIRMED':
            a['status'] = 'SUPERSEDED'
            touch(a)
    for b in store.pilot_bookings.values():
        if b['job_order_id'] == job['id'] and b['status'] in ('REQUESTED', 'CONFIRMED'):
            b['status'] = 'SUPERSEDED'
            touch(b)


def activate_assignments_on_start(job):
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['status'] == 'CONFIRMED':
            a['status'] = 'ACTIVE'
            a['participated'] = True
            touch(a)


def settle_on_complete(job):
    for a in store.tug_assignments.values():
        if a['job_order_id'] == job['id'] and a['status'] == 'ACTIVE':
            a['status'] = 'RELEASED'
            touch(a)
    for b in store.pilot_bookings.values():
        if b['job_order_id'] != job['id']:
            continue
        if b['status'] == 'BOARDED':
            b['status'] = 'COMPLETED'
            touch(b)
        elif b['status'] == 'CONFIRMED':
            b['status'] = 'NO_SHOW'
            touch(b)
    lines = compute_invoice_lines(job, 'SCHEDULED')
    inv = {
        'id': new_id(),
        'job_order_id': job['id'],
        'status': 'PROVISIONAL',
        **lines,
    }
    stamp_new(inv)
    store.invoices[inv['id']] = inv
    recompute_vessel_outstanding(job['vessel_id'])
    return inv


# ------------------------------------------------------------ serializers

def ser_vessel(v):
    return {
        'id': v['id'], 'name': v['name'], 'imo_number': v['imo_number'],
        'deadweight_tonnage': v['deadweight_tonnage'], 'loa_meters': v['loa_meters'],
        'outstanding_billed_cents': v['outstanding_billed_cents'],
        'created_at': fmt_dt(v['created_at']), 'updated_at': fmt_dt(v['updated_at']),
        'version': v['version'],
    }


def ser_tug(t):
    return {
        'id': t['id'], 'name': t['name'],
        'bollard_pull_tons': t['bollard_pull_tons'], 'horsepower': t['horsepower'],
        'hourly_rate_cents': t['hourly_rate_cents'],
        'insured_value_cents': t['insured_value_cents'],
        'home_port': t.get('home_port'),
        'operational_status': t['operational_status'],
        'created_at': fmt_dt(t['created_at']), 'updated_at': fmt_dt(t['updated_at']),
        'version': t['version'],
    }


def ser_pilot(p):
    return {
        'id': p['id'], 'name': p['name'], 'license_class': p['license_class'],
        'active': p['active'],
        'created_at': fmt_dt(p['created_at']), 'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_crew(cm):
    return {
        'id': cm['id'], 'full_name': cm['full_name'], 'crew_role': cm['crew_role'],
        'max_watch_hours': cm['max_watch_hours'],
        'created_at': fmt_dt(cm['created_at']), 'updated_at': fmt_dt(cm['updated_at']),
        'version': cm['version'],
    }


def ser_tariff(t):
    return {
        'id': t['id'], 'tariff_code': t['tariff_code'],
        'maneuver_type': t['maneuver_type'], 'base_fee_cents': t['base_fee_cents'],
        'free_standby_minutes': t['free_standby_minutes'],
        'standby_block_minutes': t['standby_block_minutes'],
        'standby_block_rate_cents': t['standby_block_rate_cents'],
        'weather_surcharge_pct': t['weather_surcharge_pct'],
        'effective_from': fmt_dt(t['effective_from']),
        'effective_to': fmt_dt(t['effective_to']),
        'created_at': fmt_dt(t['created_at']), 'updated_at': fmt_dt(t['updated_at']),
        'version': t['version'],
    }


def ser_job(j):
    return {
        'id': j['id'], 'vessel_id': j['vessel_id'],
        'tariff_rate_id': j['tariff_rate_id'], 'maneuver_type': j['maneuver_type'],
        'scheduled_start': fmt_dt(j['scheduled_start']),
        'scheduled_end': fmt_dt(j['scheduled_end']),
        'required_bollard_pull_tons': j['required_bollard_pull_tons'],
        'actual_start': fmt_opt(j['actual_start']),
        'actual_end': fmt_opt(j['actual_end']),
        'had_weather_hold': j['had_weather_hold'],
        'needs_reassignment': j['needs_reassignment'],
        'cancel_reason': j.get('cancel_reason'),
        'status': j['status'],
        'created_at': fmt_dt(j['created_at']), 'updated_at': fmt_dt(j['updated_at']),
        'version': j['version'],
    }


def ser_assignment(a):
    return {
        'id': a['id'], 'job_order_id': a['job_order_id'], 'tug_id': a['tug_id'],
        'window_start': fmt_dt(a['window_start']), 'window_end': fmt_dt(a['window_end']),
        'participated': a['participated'], 'status': a['status'],
        'created_at': fmt_dt(a['created_at']), 'updated_at': fmt_dt(a['updated_at']),
        'version': a['version'],
    }


def ser_booking(b):
    return {
        'id': b['id'], 'job_order_id': b['job_order_id'], 'pilot_id': b['pilot_id'],
        'window_start': fmt_dt(b['window_start']), 'window_end': fmt_dt(b['window_end']),
        'status': b['status'],
        'created_at': fmt_dt(b['created_at']), 'updated_at': fmt_dt(b['updated_at']),
        'version': b['version'],
    }


def ser_watch(w):
    return {
        'id': w['id'], 'tug_assignment_id': w['tug_assignment_id'],
        'crew_member_id': w['crew_member_id'],
        'watch_start': fmt_dt(w['watch_start']), 'watch_end': fmt_dt(w['watch_end']),
        'created_at': fmt_dt(w['created_at']), 'updated_at': fmt_dt(w['updated_at']),
        'version': w['version'],
    }


def ser_inspection(g):
    return {
        'id': g['id'], 'tug_id': g['tug_id'], 'inspection_item': g['inspection_item'],
        'outcome': g['outcome'],
        'inspected_at': fmt_dt(g['inspected_at']),
        'next_due_at': fmt_dt(g['next_due_at']),
        'deficiency_notes': g.get('deficiency_notes'),
        'created_at': fmt_dt(g['created_at']),
    }


def ser_incident(i):
    return {
        'id': i['id'], 'tug_id': i['tug_id'], 'job_order_id': i.get('job_order_id'),
        'incident_type': i['incident_type'], 'severity': i['severity'],
        'occurred_at': fmt_dt(i['occurred_at']), 'description': i['description'],
        'resolution_notes': i.get('resolution_notes'), 'status': i['status'],
        'created_at': fmt_dt(i['created_at']), 'updated_at': fmt_dt(i['updated_at']),
        'version': i['version'],
    }


def ser_restriction(r):
    return {
        'id': r['id'], 'restriction_type': r['restriction_type'],
        'threshold_value': r['threshold_value'], 'port_area': r['port_area'],
        'effective_start': fmt_dt(r['effective_start']),
        'effective_end': fmt_dt(r['effective_end']),
        'status': r['status'],
        'created_at': fmt_dt(r['created_at']), 'updated_at': fmt_dt(r['updated_at']),
        'version': r['version'],
    }


def ser_invoice(inv):
    return {
        'id': inv['id'], 'job_order_id': inv['job_order_id'], 'status': inv['status'],
        'variant_basis': inv['variant_basis'],
        'base_fee_cents': inv['base_fee_cents'],
        'tug_hire_cents': inv['tug_hire_cents'],
        'standby_minutes': inv['standby_minutes'],
        'standby_cents': inv['standby_cents'],
        'weather_surcharge_cents': inv['weather_surcharge_cents'],
        'total_cents': inv['total_cents'],
        'created_at': fmt_dt(inv['created_at']), 'updated_at': fmt_dt(inv['updated_at']),
        'version': inv['version'],
    }


def ser_claim(cl):
    return {
        'id': cl['id'], 'incident_id': cl['incident_id'], 'vessel_id': cl['vessel_id'],
        'claimed_amount_cents': cl['claimed_amount_cents'],
        'liability_variant': cl['liability_variant'],
        'liability_cap_cents': cl['liability_cap_cents'],
        'deductible_cents': cl['deductible_cents'],
        'payout_cents': cl['payout_cents'],
        'reviewer_notes': cl.get('reviewer_notes'),
        'status': cl['status'],
        'created_at': fmt_dt(cl['created_at']), 'updated_at': fmt_dt(cl['updated_at']),
        'version': cl['version'],
    }
