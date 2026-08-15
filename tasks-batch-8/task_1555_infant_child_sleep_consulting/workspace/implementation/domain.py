"""Domain logic: derived fields, calculations (scaffold §1.3), selectors and
cascades, plus entity serializers."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from db import store, now, touch, fmt_dt, fmt_date
from errors import ApiError

# ---- pricing / entitlement constants (calculations table) ----
TIER_BASE = {'BASIC': 29900, 'STANDARD': 54900, 'PREMIUM': 89900}
NEWBORN_SURCHARGE_CENTS = 4950
REPEAT_DISCOUNT_PCT = Decimal('0.15')
TIER_WEEKS = {'BASIC': 2, 'STANDARD': 4, 'PREMIUM': 6}
TIER_CALLS = {'BASIC': 1, 'STANDARD': 3, 'PREMIUM': 6}
TIER_MESSAGES = {'BASIC': 5, 'STANDARD': 15, 'PREMIUM': 40}
TIER_SLA_HOURS = {'BASIC': 48, 'STANDARD': 24, 'PREMIUM': 12}
SLA_CREDIT_CENTS = 1000
SLA_CREDIT_CAP_PCT = Decimal('0.10')
CALL_VALUE_CENTS = 7500
MESSAGE_VALUE_CENTS = 1200
GUARANTEE_REFUND_PCT = Decimal('0.50')
COOLING_OFF_HOURS = 48
FOLLOW_UP_WINDOW_DAYS = 180
SESSION_BUFFER_MINUTES = 15
GUARANTEE_MIN_REVIEWED_LOGS = 14
GUARANTEE_WINDOW_LOGS = 7
GUARANTEE_MIN_MISSES = 4

ALLOWED_METHODS = {
    'NEWBORN': {'GENTLE_NO_CRY'},
    'INFANT': {'GENTLE_NO_CRY', 'FERBER_GRADUATED', 'CHAIR_METHOD'},
    'TODDLER': {'GENTLE_NO_CRY', 'FERBER_GRADUATED', 'CHAIR_METHOD', 'EXTINCTION'},
    'PRESCHOOL': {'GENTLE_NO_CRY', 'FERBER_GRADUATED', 'CHAIR_METHOD', 'EXTINCTION'},
}
BAND_MODIFIER = {'NEWBORN': -5, 'INFANT': 0, 'TODDLER': 5, 'PRESCHOOL': 10}


def round_half_up_cents(dec):
    return int(dec.quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def clamp(v, lo=0, hi=100):
    return max(lo, min(hi, v))


# ---- child age (calculations.child_age_and_band) ----
def case_age_months(case):
    birth = case['child_birth_date']
    c = now().date()
    months = (c.year - birth.year) * 12 + (c.month - birth.month)
    if c.day < birth.day:
        months -= 1
    return max(0, months)


def band_for_months(months):
    if months <= 3:
        return 'NEWBORN'
    if months <= 11:
        return 'INFANT'
    if months <= 35:
        return 'TODDLER'
    return 'PRESCHOOL'


def case_age_band(case):
    return band_for_months(case_age_months(case))


# ---- severity scoring (calculations.assessment_severity_score) ----
def _ceil_div(a, b):
    return -(-a // b)


def provisional_score(a):
    base = (10 * a['night_wakings']
            + 4 * a['night_feeds']
            + a['bedtime_resistance_minutes'] // 3
            + max(0, _ceil_div(150 - a['nap_total_minutes'], 15)))
    if a['medical_flags']:
        base -= 20
    if a['preterm_birth']:
        base -= 10
    return clamp(base)


def reviewed_score(provisional, adjustment_points, band):
    return clamp(provisional + adjustment_points + BAND_MODIFIER[band])


# ---- derived counts ----
def consultant_active_case_count(consultant_id):
    return sum(1 for c in store.cases.values()
               if c['consultant_id'] == consultant_id and c['status'] == 'ACTIVE_SUPPORT')


def family_is_repeat(family_id):
    return any(c['family_id'] == family_id and c['status'] == 'COMPLETED'
               for c in store.cases.values())


def course_enrolled_count(course_id):
    return sum(1 for e in store.enrollments.values()
               if e['course_id'] == course_id and e['status'] == 'ENROLLED')


def current_plan(case_id):
    """The case's latest non-SUPERSEDED plan, or None."""
    plans = [p for p in store.plans.values()
             if p['case_id'] == case_id and p['status'] != 'SUPERSEDED']
    if not plans:
        return None
    plans.sort(key=lambda p: (p['plan_sequence'], p['_seq']))
    return plans[-1]


# ---- package pricing (calculations.package_price_cents) ----
def price_package(case, family, tier, apply_credit_cents):
    gross = TIER_BASE[tier]
    if case_age_band(case) == 'NEWBORN':
        gross += NEWBORN_SURCHARGE_CENTS
    if family_is_repeat(family['id']):
        # Pinned order: discount rounded half-up to whole cents FIRST, then subtracted.
        discount = round_half_up_cents(Decimal(gross) * REPEAT_DISCOUNT_PCT)
    else:
        discount = 0
    credit_cap = gross - discount
    if (apply_credit_cents < 0
            or apply_credit_cents > min(family['credit_balance_cents'], credit_cap)):
        raise ApiError('ERR_INVALID_REQUEST', 400,
                       'apply_credit_cents must lie between 0 and the smaller of '
                       'the family credit balance and the gross-minus-discount remainder')
    net = gross - discount - apply_credit_cents
    return gross, discount, net


# ---- entitlement ledger ----
def reeval_depleted(pkg):
    """ACTIVE -> DEPLETED when a consumption leaves both entitlements at zero."""
    if (pkg['status'] == 'ACTIVE'
            and pkg['remaining_calls'] <= 0 and pkg['remaining_messages'] <= 0):
        pkg['status'] = 'DEPLETED'
        touch(pkg)


# ---- consumable package selector (calculations.consumable_package_selector) ----
def select_consumable_package(case_id):
    today = now().date()
    cands = [p for p in store.packages.values()
             if p['case_id'] == case_id and p['status'] == 'ACTIVE'
             and p['starts_on'] <= today <= p['expires_on']]
    if not cands:
        return None
    cands.sort(key=lambda p: (p['starts_on'], p['created_at'], p['_seq']))
    return cands[0]


def select_refund_subject(case_id):
    cands = [p for p in store.packages.values()
             if p['case_id'] == case_id and p['status'] in ('ACTIVE', 'DEPLETED', 'EXPIRED')]
    if not cands:
        return None
    # latest starts_on; tie -> later created_at
    cands.sort(key=lambda p: (p['starts_on'], p['created_at'], p['_seq']))
    return cands[-1]


# ---- consultant calendar overlap (calculations.session_overlap_check) ----
def has_scheduling_conflict(consultant_id, start, end):
    buf = timedelta(minutes=SESSION_BUFFER_MINUTES)
    for s in store.sessions.values():
        if s['status'] != 'SCHEDULED':
            continue
        scase = store.cases.get(s['case_id'])
        if scase is None or scase['consultant_id'] != consultant_id:
            continue
        if start < s['scheduled_end'] + buf and s['scheduled_start'] < end + buf:
            return True
    return False


# ---- INITIAL package window overlap (calculations.package_window_overlap) ----
def has_window_overlap(case_id, starts_on, expires_on):
    for p in store.packages.values():
        if p['case_id'] != case_id or p['status'] != 'ACTIVE':
            continue
        if not (expires_on < p['starts_on'] or starts_on > p['expires_on']):
            return True
    return False


# ---- refunds (calculations.refund_amount_cents / refund_eligibility / guarantee) ----
def reviewed_logs(case_id):
    return [l for l in store.logs.values()
            if l['case_id'] == case_id
            and l['review_status'] in ('REVIEWED_ON_TRACK', 'REVIEWED_REGRESSION')]


def refund_amount_cents(pkg, refund_type):
    if refund_type == 'COOLING_OFF':
        return pkg['net_price_cents']
    if refund_type == 'GUARANTEE':
        return round_half_up_cents(Decimal(pkg['net_price_cents']) * GUARANTEE_REFUND_PCT)
    # PRO_RATA: consumption counts read from session/message ROWS.
    completed_sessions = sum(1 for s in store.sessions.values()
                             if s['package_id'] == pkg['id'] and s['status'] == 'COMPLETED')
    sent_messages = sum(1 for m in store.messages.values()
                        if m['package_id'] == pkg['id'])
    consumed = completed_sessions * CALL_VALUE_CENTS + sent_messages * MESSAGE_VALUE_CENTS
    return max(0, pkg['net_price_cents'] - consumed)


def guarantee_eligible(case, pkg):
    if pkg['status'] != 'EXPIRED':
        return False
    rlogs = reviewed_logs(case['id'])
    if len(rlogs) < GUARANTEE_MIN_REVIEWED_LOGS:
        return False
    recent = sorted(rlogs, key=lambda l: l['log_date'], reverse=True)[:GUARANTEE_WINDOW_LOGS]
    misses = sum(1 for l in recent
                 if l['night_wake_count'] > case['guarantee_goal_night_wakings'])
    return misses >= GUARANTEE_MIN_MISSES


def refund_eligible(case, pkg, refund_type):
    t = now()
    if refund_type == 'COOLING_OFF':
        if t > pkg['purchased_at'] + timedelta(hours=COOLING_OFF_HOURS):
            return False
        if any(s['package_id'] == pkg['id'] and s['status'] == 'COMPLETED'
               for s in store.sessions.values()):
            return False
        if any(m['package_id'] == pkg['id'] for m in store.messages.values()):
            return False
        if reviewed_logs(case['id']):
            return False
        return True
    if refund_type == 'GUARANTEE':
        return guarantee_eligible(case, pkg)
    # PRO_RATA
    if pkg['status'] != 'ACTIVE':
        return False
    if t <= pkg['purchased_at'] + timedelta(hours=COOLING_OFF_HOURS):
        return False
    return refund_amount_cents(pkg, 'PRO_RATA') > 0


# ---- cascades ----
def regression_cascade(case):
    """Log reviewed REGRESSION: plan ACTIVE -> NEEDS_ADJUSTMENT (link 1),
    case ACTIVE_SUPPORT -> NEEDS_ATTENTION (link 2); already-in-target links
    are no-ops."""
    plan = current_plan(case['id'])
    if plan is not None and plan['status'] == 'ACTIVE':
        plan['status'] = 'NEEDS_ADJUSTMENT'
        touch(plan)
    if case['status'] == 'ACTIVE_SUPPORT':
        case['status'] = 'NEEDS_ATTENTION'
        touch(case)


def refund_paid_cascade(case):
    """Link 1: case -> CLOSED_REFUNDED. Link 2: plans CANCELLED, packages
    CLOSED_EARLY (remaining frozen at 0), scheduled sessions CANCELLED."""
    if case['status'] in ('ACTIVE_SUPPORT', 'NEEDS_ATTENTION'):
        case['status'] = 'CLOSED_REFUNDED'
        touch(case)
    for p in store.plans.values():
        if p['case_id'] == case['id'] and p['status'] in ('ACTIVE', 'NEEDS_ADJUSTMENT'):
            p['status'] = 'CANCELLED'
            touch(p)
    for pkg in store.packages.values():
        if pkg['case_id'] == case['id'] and pkg['status'] in ('ACTIVE', 'DEPLETED'):
            pkg['status'] = 'CLOSED_EARLY'
            pkg['remaining_calls'] = 0
            pkg['remaining_messages'] = 0
            touch(pkg)
    for s in store.sessions.values():
        if s['case_id'] == case['id'] and s['status'] == 'SCHEDULED':
            s['status'] = 'CANCELLED'
            touch(s)


# ---- serializers ----
def ser_consultant(c):
    return {
        'id': c['id'],
        'full_name': c['full_name'],
        'certification_no': c['certification_no'],
        'max_active_cases': c['max_active_cases'],
        'active_case_count': consultant_active_case_count(c['id']),
        'created_at': fmt_dt(c['created_at']),
        'updated_at': fmt_dt(c['updated_at']),
        'version': c['version'],
    }


def ser_family(f):
    return {
        'id': f['id'],
        'full_name': f['full_name'],
        'email': f['email'],
        'credit_balance_cents': f['credit_balance_cents'],
        'is_repeat_client': family_is_repeat(f['id']),
        'created_at': fmt_dt(f['created_at']),
        'updated_at': fmt_dt(f['updated_at']),
        'version': f['version'],
    }


def ser_case(c):
    months = case_age_months(c)
    return {
        'id': c['id'],
        'family_id': c['family_id'],
        'consultant_id': c['consultant_id'],
        'child_birth_date': fmt_date(c['child_birth_date']),
        'delivery_mode': c['delivery_mode'],
        'guarantee_goal_night_wakings': c['guarantee_goal_night_wakings'],
        'child_age_months': months,
        'age_band': band_for_months(months),
        'status': c['status'],
        'completed_at': fmt_dt(c['completed_at']),
        'created_at': fmt_dt(c['created_at']),
        'updated_at': fmt_dt(c['updated_at']),
        'version': c['version'],
    }


def ser_questionnaire(q):
    return {
        'id': q['id'],
        'case_id': q['case_id'],
        'answers': q['answers'],
        'provisional_severity_score': q['provisional_severity_score'],
        'adjustment_points': q['adjustment_points'],
        'reviewed_severity_score': q['reviewed_severity_score'],
        'review_note': q['review_note'],
        'status': q['status'],
        'created_at': fmt_dt(q['created_at']),
        'updated_at': fmt_dt(q['updated_at']),
        'version': q['version'],
    }


def ser_plan(p):
    return {
        'id': p['id'],
        'case_id': p['case_id'],
        'plan_sequence': p['plan_sequence'],
        'age_band': p['age_band'],
        'method': p['method'],
        'target_night_wake_count': p['target_night_wake_count'],
        'target_longest_stretch_minutes': p['target_longest_stretch_minutes'],
        'notes': p['notes'],
        'status': p['status'],
        'created_at': fmt_dt(p['created_at']),
        'updated_at': fmt_dt(p['updated_at']),
        'version': p['version'],
    }


def ser_package(pkg):
    if pkg['status'] == 'CLOSED_EARLY':
        remaining_calls, remaining_messages = 0, 0
    else:
        remaining_calls = max(0, pkg['remaining_calls'])
        remaining_messages = max(0, pkg['remaining_messages'])
    return {
        'id': pkg['id'],
        'case_id': pkg['case_id'],
        'tier': pkg['tier'],
        'kind': pkg['kind'],
        'purchased_at': fmt_dt(pkg['purchased_at']),
        'starts_on': fmt_date(pkg['starts_on']),
        'duration_weeks': pkg['duration_weeks'],
        'expires_on': fmt_date(pkg['expires_on']),
        'included_calls': pkg['included_calls'],
        'included_messages': pkg['included_messages'],
        'response_sla_hours': pkg['response_sla_hours'],
        'remaining_calls': remaining_calls,
        'remaining_messages': remaining_messages,
        'gross_price_cents': pkg['gross_price_cents'],
        'repeat_discount_cents': pkg['repeat_discount_cents'],
        'credit_applied_cents': pkg['credit_applied_cents'],
        'net_price_cents': pkg['net_price_cents'],
        'sla_credit_total_cents': pkg['sla_credit_total_cents'],
        'status': pkg['status'],
        'created_at': fmt_dt(pkg['created_at']),
        'updated_at': fmt_dt(pkg['updated_at']),
        'version': pkg['version'],
    }


def ser_log(l):
    return {
        'id': l['id'],
        'case_id': l['case_id'],
        'log_date': fmt_date(l['log_date']),
        'night_wake_count': l['night_wake_count'],
        'longest_stretch_minutes': l['longest_stretch_minutes'],
        'nap_count': l['nap_count'],
        'nap_total_minutes': l['nap_total_minutes'],
        'notes': l['notes'],
        'review_status': l['review_status'],
        'review_note': l['review_note'],
        'created_at': fmt_dt(l['created_at']),
        'updated_at': fmt_dt(l['updated_at']),
        'version': l['version'],
    }


def ser_session(s):
    return {
        'id': s['id'],
        'case_id': s['case_id'],
        'package_id': s['package_id'],
        'session_type': s['session_type'],
        'scheduled_start': fmt_dt(s['scheduled_start']),
        'scheduled_end': fmt_dt(s['scheduled_end']),
        'status': s['status'],
        'created_at': fmt_dt(s['created_at']),
        'updated_at': fmt_dt(s['updated_at']),
        'version': s['version'],
    }


def ser_message(m):
    return {
        'id': m['id'],
        'case_id': m['case_id'],
        'package_id': m['package_id'],
        'body': m['body'],
        'response_body': m['response_body'],
        'first_responded_at': fmt_dt(m['first_responded_at']),
        'sla_breached': m['sla_breached'],
        'credit_granted_cents': m['credit_granted_cents'],
        'status': m['status'],
        'created_at': fmt_dt(m['created_at']),
        'updated_at': fmt_dt(m['updated_at']),
        'version': m['version'],
    }


def ser_refund(r):
    return {
        'id': r['id'],
        'case_id': r['case_id'],
        'package_id': r['package_id'],
        'refund_type': r['refund_type'],
        'reason': r['reason'],
        'amount_cents': r['amount_cents'],
        'denial_reason': r['denial_reason'],
        'status': r['status'],
        'created_at': fmt_dt(r['created_at']),
        'updated_at': fmt_dt(r['updated_at']),
        'version': r['version'],
    }


def ser_course(c):
    return {
        'id': c['id'],
        'consultant_id': c['consultant_id'],
        'title': c['title'],
        'starts_on': fmt_date(c['starts_on']),
        'capacity': c['capacity'],
        'price_cents': c['price_cents'],
        'enrolled_count': course_enrolled_count(c['id']),
        'created_at': fmt_dt(c['created_at']),
        'updated_at': fmt_dt(c['updated_at']),
        'version': c['version'],
    }


def ser_enrollment(e):
    return {
        'id': e['id'],
        'course_id': e['course_id'],
        'case_id': e['case_id'],
        'status': e['status'],
        'promoted_at': fmt_dt(e['promoted_at']),
        'created_at': fmt_dt(e['created_at']),
        'updated_at': fmt_dt(e['updated_at']),
        'version': e['version'],
    }
