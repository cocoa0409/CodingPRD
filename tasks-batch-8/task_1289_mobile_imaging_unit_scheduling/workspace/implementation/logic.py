"""Business logic: calculations, accreditation derivation, day cascades,
billing statement creation. Implements SCAFFOLD Table 3 (calculations)."""
from datetime import datetime, date, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from core import (DB, get, touch, new_entity, now_iso, get_clock, clock_date,
                  to_minutes, rhu_cents, dec, fail)

MILEAGE_RATE_CENTS = 67
PER_DIEM_CENTS = 15000
TECH_DAILY_DOSE_LIMIT_MSV = Decimal('5.00')
TURNOVER_MINUTES = 10
SEDATION_BUFFER_MINUTES = 15
TRANSFER_SLA_MINUTES = 120
EXPIRING_WINDOW_DAYS = 30
DRL_MSV = {'CT_HEAD': Decimal('2.0'), 'CT_CHEST': Decimal('7.0'),
           'PET_ONCO': Decimal('10.0')}
TIER1_MIN_CENTS = 500000
TIER2_MIN_CENTS = 1000000
TIER1_PCT = 5
TIER2_PCT = 8

IONIZING_EXAMS = {'CT_HEAD', 'CT_CHEST', 'PET_ONCO'}
EXAM_MODALITY = {'CT_HEAD': 'CT', 'CT_CHEST': 'CT',
                 'MRI_BRAIN': 'MRI', 'PET_ONCO': 'PET'}

OPEN_APPT_STATUSES = ('REQUESTED', 'CONFIRMED', 'CHECKED_IN', 'SCANNING')


# ---------------------------------------------------------------- lookups
def appointments_of_day(day_id):
    return [a for a in DB['appointments'].values() if a['site_day_id'] == day_id]


def legs_of_day(day_id):
    return [l for l in DB['legs'].values() if l['site_day_id'] == day_id]


def staffing_of_day(day_id):
    return [s for s in DB['staffing'].values() if s['site_day_id'] == day_id]


def checklist_of_day(day_id):
    for c in DB['checklists'].values():
        if c['site_day_id'] == day_id:
            return c
    return None


def statement_of_day(day_id):
    for s in DB['statements'].values():
        if s['site_day_id'] == day_id:
            return s
    return None


def studies_of_appointment(appt_id):
    return [s for s in DB['studies'].values() if s['appointment_id'] == appt_id]


def days_of_plan(plan_id):
    return [d for d in DB['site_days'].values() if d['route_plan_id'] == plan_id]


# ---------------------------------------------------------------- accreditation
def derive_acc_status(expires_on_str, ref_date):
    exp = date.fromisoformat(expires_on_str)
    if exp < ref_date:
        return 'EXPIRED'
    if (exp - ref_date).days <= EXPIRING_WINDOW_DAYS:
        return 'EXPIRING_SOON'
    return 'ACTIVE'


def governing_record(unit):
    """Modality-matching record with max expires_on; tie -> later created."""
    recs = [r for r in DB['accreditations'].values()
            if r['unit_id'] == unit['id'] and r['modality'] == unit['modality']]
    if not recs:
        return None
    return max(recs, key=lambda r: (r['expires_on'], r['_seq']))


def accreditation_valid(unit):
    gov = governing_record(unit)
    return gov is not None and gov['status'] in ('ACTIVE', 'EXPIRING_SOON')


def rederive_accreditations_on_clock():
    """Re-derive statuses after a clock advance. Returns set of unit ids whose
    governing record flipped to EXPIRED in this call."""
    flipped = []
    for r in DB['accreditations'].values():
        if r['status'] == 'SUSPENDED':
            continue
        new_status = derive_acc_status(r['expires_on'], clock_date())
        if new_status != r['status']:
            old = r['status']
            r['status'] = new_status
            touch(r)
            if new_status == 'EXPIRED' and old != 'EXPIRED':
                flipped.append(r)
    units_to_cascade = set()
    for r in flipped:
        unit = DB['units'].get(r['unit_id'])
        if unit is None:
            continue
        gov = governing_record(unit)
        if gov is not None and gov['id'] == r['id']:
            units_to_cascade.add(unit['id'])
    return units_to_cascade


# ---------------------------------------------------------------- billing calc
def planned_window_minutes(day):
    return to_minutes(day['last_patient_time']) - to_minutes(day['first_patient_time'])


def completed_appointments(day):
    return [a for a in appointments_of_day(day['id']) if a['status'] == 'COMPLETED']


def no_show_count(day):
    return len([a for a in appointments_of_day(day['id'])
                if a['status'] == 'NO_SHOW'])


def billable_count(day, model, variant):
    aps = completed_appointments(day)
    if variant == 'final' and model == 'PER_SCAN':
        aps = [a for a in aps if any(s['status'] in ('DELIVERED', 'ACKNOWLEDGED')
                                     for s in studies_of_appointment(a['id']))]
    return len(aps)


def day_charge(day, contract, model, variant):
    """site_day_billing_amount: model variant x provisional/final variant."""
    status = day['status']
    if model == 'PER_DAY':
        if status == 'COMPLETED':
            return contract['day_rate_cents']
        if status == 'INTERRUPTED':
            window = planned_window_minutes(day)
            if window <= 0:
                prorated = 0
            else:
                frac = dec(day['delivered_service_minutes']) / dec(window)
                prorated = rhu_cents(dec(contract['day_rate_cents']) * frac)
            return max(contract['interruption_floor_cents'], prorated)
        # CANCELLED
        if day.get('cancel_reason') == 'ACCREDITATION_EXPIRED':
            return 0
        if day.get('_cancel_late'):
            return rhu_cents(dec(contract['day_rate_cents'])
                             * dec(contract['cancel_late_pct']))
        return 0
    # PER_SCAN
    if status == 'CANCELLED':
        if day.get('cancel_reason') == 'ACCREDITATION_EXPIRED':
            return 0
        if day.get('_cancel_late'):
            return rhu_cents(dec(contract['guaranteed_minimum_cents'])
                             * dec(contract['cancel_late_pct']))
        return 0
    billable = billable_count(day, model, variant)
    charge = (min(billable, contract['included_scan_quota'])
              * contract['scan_rate_cents']
              + max(0, billable - contract['included_scan_quota'])
              * contract['overage_scan_rate_cents']
              + no_show_count(day) * contract['no_show_fee_cents'])
    if day.get('_reached_ready') and billable == 0:
        charge = max(charge, contract['guaranteed_minimum_cents'])
    return charge


def create_statement(day):
    """Exactly one statement per site day, auto-created at close."""
    contract = DB['contracts'][day['contract_id']]
    model = contract['billing_model']
    amount = day_charge(day, contract, model, 'provisional')
    credit_granted = 0
    if model == 'PER_DAY' and day['status'] == 'INTERRUPTED':
        credit_granted = contract['day_rate_cents'] - amount
    credit_applied = 0
    if day.get('rescheduled_from_id'):
        src_stmt = statement_of_day(day['rescheduled_from_id'])
        if src_stmt is not None:
            credit_applied = src_stmt['credit_granted_cents']
    return new_entity('statements', {
        'site_day_id': day['id'],
        'contract_id': day['contract_id'],
        'billing_model_snapshot': model,
        'completed_scan_count': len(completed_appointments(day)),
        'no_show_count': no_show_count(day),
        'provisional_amount_cents': amount,
        'final_amount_cents': None,
        'credit_granted_cents': credit_granted,
        'credit_applied_cents': credit_applied,
        'net_due_cents': amount - credit_applied,
        'status': 'PROVISIONAL',
    })


def finalize_statement(stmt):
    day = DB['site_days'][stmt['site_day_id']]
    contract = DB['contracts'][stmt['contract_id']]
    amount = day_charge(day, contract, stmt['billing_model_snapshot'], 'final')
    stmt['final_amount_cents'] = amount
    stmt['net_due_cents'] = amount - stmt['credit_applied_cents']


# ---------------------------------------------------------------- day cascades
def _cancel_appointments(day, statuses, reason):
    for a in appointments_of_day(day['id']):
        if a['status'] in statuses:
            a['status'] = 'CANCELLED'
            a['cancel_reason'] = reason
            touch(a)


def _release_staffing(day, reason):
    for s in staffing_of_day(day['id']):
        if s['status'] == 'ASSIGNED':
            s['status'] = 'RELEASED'
            s['release_reason'] = reason
            touch(s)


def complete_day(day):
    day['delivered_service_minutes'] = planned_window_minutes(day)
    _release_staffing(day, 'DAY_COMPLETED')
    day['status'] = 'COMPLETED'
    touch(day)
    create_statement(day)


def cancel_day_manual(day, notice_hours):
    contract = DB['contracts'][day['contract_id']]
    day['_cancel_late'] = notice_hours < contract['cancel_notice_hours']
    day['cancel_reason'] = 'FACILITY_CANCEL'
    _cancel_appointments(day, ('REQUESTED', 'CONFIRMED', 'CHECKED_IN'),
                         'DAY_CANCELLED')
    _release_staffing(day, 'DAY_CANCELLED')
    for leg in legs_of_day(day['id']):
        if leg['status'] == 'PLANNED':
            leg['status'] = 'CANCELLED'
            touch(leg)
        elif leg['status'] == 'DISPATCHED':
            leg['status'] = 'FAILED'
            touch(leg)
    day['status'] = 'CANCELLED'
    touch(day)
    create_statement(day)


def cancel_day_accreditation(day):
    """System cancel when governing accreditation flips EXPIRED: appointments
    {REQUESTED, CONFIRMED} -> CANCELLED, zero-fee statement. (PRD 3.7)"""
    day['cancel_reason'] = 'ACCREDITATION_EXPIRED'
    _cancel_appointments(day, ('REQUESTED', 'CONFIRMED'), 'DAY_CANCELLED')
    day['status'] = 'CANCELLED'
    touch(day)
    create_statement(day)


def interrupt_day(day, reason):
    """Full interruption unwind; reason BREAKDOWN | OPERATOR_INTERRUPT."""
    window = planned_window_minutes(day)
    first_dt = datetime.combine(date.fromisoformat(day['service_date']),
                                datetime.min.time(),
                                tzinfo=timezone.utc) + timedelta(
                                    minutes=to_minutes(day['first_patient_time']))
    delta = (get_clock() - first_dt).total_seconds() / 60.0
    delivered = int(delta // 1)
    day['delivered_service_minutes'] = max(0, min(window, delivered))
    day['interrupt_reason'] = reason
    _cancel_appointments(day, OPEN_APPT_STATUSES, 'DAY_INTERRUPTED')
    _release_staffing(day, 'DAY_INTERRUPTED')
    for leg in legs_of_day(day['id']):
        if leg['status'] == 'DISPATCHED':
            leg['status'] = 'FAILED'
            touch(leg)
    day['status'] = 'INTERRUPTED'
    touch(day)
    create_statement(day)


# ---------------------------------------------------------------- dose calc
def _dose_sum_decimal(records):
    total = Decimal('0')
    for r in records:
        total += dec(r['dose_msv'])
    return total


def _quantize2(d):
    return d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


def tech_records(technologist_id):
    return [r for r in DB['dose_records'].values()
            if r['technologist_id'] == technologist_id]


def record_service_date(rec):
    appt = DB['appointments'].get(rec['appointment_id'])
    if appt is None:
        return None
    day = DB['site_days'].get(appt['site_day_id'])
    return day['service_date'] if day else None


def tech_day_dose(technologist_id, service_date_str):
    recs = [r for r in tech_records(technologist_id)
            if record_service_date(r) == service_date_str]
    return _dose_sum_decimal(recs)


def tech_current_day_dose(technologist_id):
    return tech_day_dose(technologist_id, clock_date().isoformat())


def tech_month_dose(technologist_id):
    prefix = clock_date().strftime('%Y-%m')
    recs = [r for r in tech_records(technologist_id)
            if (record_service_date(r) or '').startswith(prefix)]
    return _dose_sum_decimal(recs)


def projected_dose(technologist_id, day):
    """Prospective gate: records dated on the target service_date + estimated
    dose of the day's open appointments. 2dp, round-half-up."""
    total = tech_day_dose(technologist_id, day['service_date'])
    for a in appointments_of_day(day['id']):
        if a['status'] in OPEN_APPT_STATUSES:
            total += dec(a['estimated_dose_msv'])
    return _quantize2(total)


def appointment_actual_dose(appt_id):
    recs = [r for r in DB['dose_records'].values()
            if r['appointment_id'] == appt_id]
    return _quantize2(_dose_sum_decimal(recs))


# ---------------------------------------------------------------- travel stipend
def leg_stipend_cents(distance_miles, overnight):
    per_leg = rhu_cents(dec(distance_miles) * MILEAGE_RATE_CENTS)
    if overnight:
        per_leg += PER_DIEM_CENTS
    return per_leg


def plan_total_stipend(plan_id):
    total = 0
    for day in days_of_plan(plan_id):
        for leg in legs_of_day(day['id']):
            total += leg['stipend_cents']
    return total


# ---------------------------------------------------------------- misc
def unit_day_booked(unit_id, service_date_str):
    for d in DB['site_days'].values():
        if (d['unit_id'] == unit_id and d['service_date'] == service_date_str
                and d['status'] not in ('CANCELLED', 'RESCHEDULED')):
            return True
    return False


def transfer_budget_mb(day):
    checklist = checklist_of_day(day['id'])
    if checklist is None:
        return 0
    return int((dec(checklist['measured_uplink_mbps']) * Decimal('7.5'))
               .to_integral_value(rounding=ROUND_FLOOR))
