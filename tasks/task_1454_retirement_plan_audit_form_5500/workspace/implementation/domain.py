"""Domain services: computed fields, calculations, posture aggregate, cascades."""
from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from dates import (add_months, business_days_between, last_day_of_month,
                   parse_date, roll_forward_weekend)
from store import base_fields, store, touch

# --- constants from the scaffold calculations table -------------------------
AUDIT_THRESHOLD = 100
EIGHTY_120_LOW = 80
EIGHTY_120_HIGH = 120
SMALL_PLAN_SAFE_HARBOR_DAYS = 7
LARGE_PLAN_ADMIN_FEASIBLE_DAYS = 3
VFCP_UNDERPAYMENT_ANNUAL_PCT = Decimal('8.0')
EPCRS_PLAN_ANNUAL_PCT = Decimal('5.0')
DAY_BASIS = Decimal('365')
SCHEDULE_C_THRESHOLD_CENTS = 500000
DFVCP_PER_DAY_CENTS = 1000
DFVCP_CAP_SMALL_CENTS = 75000
DFVCP_CAP_LARGE_CENTS = 200000
COVERAGE_RATIO_PASS_PCT = Decimal('70.00')


def round_dec(value, places):
    q = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(q, rounding=ROUND_HALF_UP)


def round_cents(value):
    return int(round_dec(value, 0))


# --- lookups ---------------------------------------------------------------
def engagements_of():
    return store.engagements.values()


def participants_of(engagement_id):
    return [p for p in store.participants.values() if p['engagement_id'] == engagement_id]


def contributions_of(engagement_id):
    return [c for c in store.contributions.values() if c['engagement_id'] == engagement_id]


def statements_of(engagement_id):
    return [s for s in store.trust_statements.values() if s['engagement_id'] == engagement_id]


def test_results_of(engagement_id):
    return [t for t in store.test_results.values() if t['engagement_id'] == engagement_id]


def findings_of(engagement_id):
    return [f for f in store.findings.values() if f['engagement_id'] == engagement_id]


def filing_of(engagement_id):
    for f in store.filings.values():
        if f['engagement_id'] == engagement_id:
            return f
    return None


def extensions_of(filing_id):
    return [e for e in store.extensions.values() if e['filing_id'] == filing_id]


def actions_of_finding(finding_id):
    return [a for a in store.corrective_actions.values() if a['finding_id'] == finding_id]


# --- participant balances ---------------------------------------------------
def action_participant_id(action):
    """Participant whose balance an action affects (None for no balance effect)."""
    if action['action_type'] == 'LOST_EARNINGS_DEPOSIT':
        asmt = store.assessments.get(action.get('assessment_id'))
        if asmt:
            contrib = store.contributions.get(asmt['contribution_id'])
            if contrib:
                return contrib['participant_id']
        return action.get('participant_id')
    if action['action_type'] in ('CORRECTIVE_DISTRIBUTION', 'QNEC_CONTRIBUTION',
                                 'QMAC_CONTRIBUTION'):
        return action.get('participant_id')
    return None  # FEE_REDISCLOSURE


def is_deposit_action(action):
    return action['action_type'] in ('LOST_EARNINGS_DEPOSIT', 'QNEC_CONTRIBUTION',
                                     'QMAC_CONTRIBUTION')


def recompute_balance(participant):
    bal = participant['opening_balance_cents']
    for c in store.contributions.values():
        if c['participant_id'] == participant['id'] and c['match_status'] == 'MATCHED':
            bal += c['amount_cents']
    for a in store.corrective_actions.values():
        if a['status'] in ('EXECUTED', 'VERIFIED') and action_participant_id(a) == participant['id']:
            if is_deposit_action(a):
                bal += a['total_amount_cents']
            elif a['action_type'] == 'CORRECTIVE_DISTRIBUTION':
                bal -= a['total_amount_cents']
    participant['account_balance_cents'] = bal


# --- trust reconciliation ----------------------------------------------------
def recompute_statement(stmt):
    matched = sum(c['amount_cents'] for c in store.contributions.values()
                  if c.get('trust_statement_id') == stmt['id'] and c['match_status'] == 'MATCHED')
    stmt['matched_contribution_cents'] = matched
    stmt['unreconciled_deposit_cents'] = (stmt['reported_deposit_total_cents']
                                          - matched - stmt['adjustment_cents'])


# --- filing due dates / extension freshness ----------------------------------
def original_due_dates(eng):
    """Return (raw, rolled) original due date for the engagement's plan year."""
    last_day_of_py = parse_date(eng['plan_year_end']) - timedelta(days=1)
    raw = last_day_of_month(add_months(last_day_of_py, 7))
    return raw, roll_forward_weekend(raw)


def extended_due_date(raw_original):
    m = raw_original.month + 3
    y = raw_original.year + (m - 1) // 12
    m = (m - 1) % 12 + 1
    return roll_forward_weekend(_safe_date(y, m, 15))


def _safe_date(y, m, day):
    from calendar import monthrange
    from datetime import date
    return date(y, m, min(day, monthrange(y, m)[1]))


def active_extension(filing):
    """The GRANTED or USED extension of the filing, if any."""
    for e in extensions_of(filing['id']):
        if e['status'] in ('GRANTED', 'USED'):
            return e
    return None


def refresh_filing(filing):
    ext = active_extension(filing)
    filing['effective_due_date'] = ext['extended_due_date'] if ext else filing['original_due_date']
    filing['has_active_extension'] = any(e['status'] == 'GRANTED'
                                         for e in extensions_of(filing['id']))


# --- posture aggregate (PRD 2.9) ----------------------------------------------
def compute_posture(eng):
    eid = eng['id']
    for f in findings_of(eid):
        if f['status'] == 'OPEN' and f['severity'] == 'HIGH':
            return 'BLOCKED'
    for t in test_results_of(eid):
        if t['is_current_official'] and t['status'] == 'FINAL' and t['result'] == 'FAIL':
            return 'BLOCKED'
    for s in statements_of(eid):
        if s['status'] == 'DISCREPANCY':
            return 'BLOCKED'
    for f in findings_of(eid):
        if f['status'] in ('OPEN', 'ACKNOWLEDGED', 'CORRECTION_IN_PROGRESS', 'CORRECTED'):
            return 'AT_RISK'
    filing = filing_of(eid)
    if filing is not None and filing['status'] not in ('FILED', 'ACCEPTED'):
        refresh_filing(filing)
        if store.clock_date() > parse_date(filing['effective_due_date']):
            return 'AT_RISK'
    return 'ON_TRACK'


def recompute_posture(eng):
    new = compute_posture(eng)
    old = eng['posture']
    if new != old:
        eng['posture'] = new
        if new == 'BLOCKED':
            # Entering BLOCKED reverts any READY_TO_FILE filing to SCHEDULES_COMPLETE.
            filing = filing_of(eng['id'])
            if filing is not None and filing['status'] == 'READY_TO_FILE':
                filing['status'] = 'SCHEDULES_COMPLETE'
                touch(filing)


def apply_time_rules():
    """Logical-clock-driven rules: extension expiry, then posture re-evaluation."""
    today = store.clock_date()
    for ext in store.extensions.values():
        if ext['status'] == 'GRANTED':
            filing = store.filings.get(ext['filing_id'])
            if filing is not None and filing['status'] not in ('FILED', 'ACCEPTED'):
                if today > parse_date(ext['extended_due_date']):
                    ext['status'] = 'EXPIRED'
                    touch(ext)
    for eng in store.engagements.values():
        recompute_posture(eng)


# --- participant count determination (calc: participant_count_determination) ---
def recompute_participant_count(eng):
    count = 0
    for p in participants_of(eng['id']):
        if not p['is_eligible']:
            continue
        if p['status'] in ('ACTIVE', 'RETIRED_WITH_BALANCE'):
            count += 1
        elif p['status'] in ('SEPARATED_WITH_BALANCE', 'DECEASED') and p['account_balance_cents'] > 0:
            count += 1
    eng['participant_count_beginning'] = count
    if (eng['use_80120_election'] and eng['prior_year_schedule_type'] == 'I'
            and EIGHTY_120_LOW <= count <= EIGHTY_120_HIGH):
        eng['audit_required'] = False
        eng['required_schedule_type'] = 'I'
    else:
        eng['audit_required'] = count >= AUDIT_THRESHOLD
        eng['required_schedule_type'] = 'H' if eng['audit_required'] else 'I'
    eng['remittance_standard_days'] = (SMALL_PLAN_SAFE_HARBOR_DAYS
                                       if eng['required_schedule_type'] == 'I'
                                       else LARGE_PLAN_ADMIN_FEASIBLE_DAYS)


# --- lost earnings (calc: lost_earnings_on_late_deposit) ------------------------
def lost_earnings_cents(principal_cents, payroll_date, deposit_date, correction_date, variant):
    """Per-segment round-half-up to cents, THEN sum (pinned rounding order)."""
    rate = VFCP_UNDERPAYMENT_ANNUAL_PCT if variant == 'VFCP' else EPCRS_PLAN_ANNUAL_PCT
    d1 = (deposit_date - payroll_date).days
    d2 = (correction_date - deposit_date).days
    if d1 < 0:
        d1 = 0
    if d2 < 0:
        d2 = 0
    p = Decimal(principal_cents)
    seg1 = round_cents(p * rate / Decimal(100) * Decimal(d1) / DAY_BASIS)
    seg2 = round_cents(p * rate / Decimal(100) * Decimal(d2) / DAY_BASIS)
    return seg1 + seg2


# --- nondiscrimination testing (calc: adp_test / coverage_ratio_410b) -----------
def _adr(participant, deferral_override=None):
    deferral = participant['deferral_amount_cy_cents'] if deferral_override is None else deferral_override
    return round_dec(Decimal(deferral) * Decimal(100)
                     / Decimal(participant['compensation_cy_cents']), 4)


def _test_input_set(engagement_id):
    return [p for p in participants_of(engagement_id)
            if p['is_eligible']
            and p['status'] in ('ACTIVE', 'SEPARATED_WITH_BALANCE', 'RETIRED_WITH_BALANCE')
            and p['compensation_cy_cents'] > 0]


def _latest_failed_adp(engagement_id):
    candidates = [t for t in test_results_of(engagement_id)
                  if t['test_type'] == 'ADP' and t['result'] == 'FAIL'
                  and t.get('_refunds')]
    if not candidates:
        return None
    return max(candidates, key=lambda t: t['_seq'])


def run_adp_test(eng, test_type):
    """ADP/ACP share the shape. ACP consumes post-refund deferral figures when a
    failed ADP result exists (pinned evaluation order: ADP refund then ACP)."""
    from errors import ERR_INVALID_REQUEST, raise_err
    population = _test_input_set(eng['id'])
    refunds = {}
    if test_type == 'ACP':
        prior = _latest_failed_adp(eng['id'])
        if prior is not None:
            refunds = prior['_refunds']
    nhces, hces = [], []
    for p in population:
        override = None
        if p['id'] in refunds:
            override = max(0, p['deferral_amount_cy_cents'] - refunds[p['id']])
        entry = (p, _adr(p, override))
        (hces if p['is_hce'] else nhces).append(entry)
    if not nhces or not hces:
        raise_err(ERR_INVALID_REQUEST,
                  '%s test requires at least one NHCE and one HCE in the input set' % test_type)
    nhce_avg = round_dec(sum(a for _, a in nhces) / Decimal(len(nhces)), 2)
    hce_avg = round_dec(sum(a for _, a in hces) / Decimal(len(hces)), 2)
    agg = round_dec(Decimal('1.25') * nhce_avg, 2)
    alt = min(round_dec(Decimal('2') * nhce_avg, 2), round_dec(nhce_avg + Decimal('2.00'), 2))
    max_allowed = max(agg, alt)
    result = 'PASS' if hce_avg <= max_allowed else 'FAIL'
    excess = 0
    refund_map = {}
    if result == 'FAIL':
        excess, refund_map = _leveling(hces, hce_avg, max_allowed)
    return {
        'hce_avg_pct': float(hce_avg),
        'nhce_avg_pct': float(nhce_avg),
        'max_allowed_hce_pct': float(max_allowed),
        'coverage_ratio_pct': None,
        'result': result,
        'excess_contribution_cents': excess,
        '_refunds': refund_map,
    }


def _leveling(hces, hce_avg, max_allowed):
    """Leveling method: shed S ADR points from the highest-ADR HCEs.

    Returns (excess_contribution_cents, {participant_id: refund_cents}).
    Ties break by participant created_at ascending, then external_ref ascending.
    """
    n = len(hces)
    target = round_dec((hce_avg - max_allowed) * Decimal(n), 2)
    order = sorted(hces, key=lambda t: (Decimal(0) - t[1], t[0]['created_at'], t[0]['external_ref']))
    adrs = [t[1] for t in order]
    reductions = [Decimal(0)] * n
    remaining = target
    k = 0
    while remaining > 0 and k < n:
        gap = adrs[k] - adrs[k + 1] if k + 1 < n else adrs[k]
        group = k + 1
        if gap <= 0:
            k += 1
            continue
        if remaining >= gap * group:
            for i in range(group):
                reductions[i] += gap
                adrs[i] -= gap
            remaining -= gap * group
            k += 1
        else:
            share = remaining / Decimal(group)
            for i in range(group):
                reductions[i] += share
            remaining = Decimal(0)
    excess = 0
    refunds = {}
    for i in range(n):
        if reductions[i] > 0:
            cents = round_cents(reductions[i] / Decimal(100)
                                * Decimal(order[i][0]['compensation_cy_cents']))
            excess += cents
            refunds[order[i][0]['id']] = cents
    return excess, refunds


def run_coverage_test(eng):
    from errors import ERR_INVALID_REQUEST, raise_err
    all_p = participants_of(eng['id'])
    total_hce = sum(1 for p in all_p if p['is_hce'])
    total_nhce = sum(1 for p in all_p if not p['is_hce'])
    if total_hce == 0 or total_nhce == 0:
        raise_err(ERR_INVALID_REQUEST,
                  'Coverage test is not meaningful with an empty HCE or NHCE group')
    ben_hce = sum(1 for p in all_p if p['is_hce'] and p['is_eligible'])
    ben_nhce = sum(1 for p in all_p if not p['is_hce'] and p['is_eligible'])
    ratio = round_dec((Decimal(ben_nhce) / Decimal(total_nhce))
                      / (Decimal(ben_hce) / Decimal(total_hce)) * Decimal(100), 2)
    return {
        'hce_avg_pct': None,
        'nhce_avg_pct': None,
        'max_allowed_hce_pct': None,
        'coverage_ratio_pct': float(ratio),
        'result': 'PASS' if ratio >= COVERAGE_RATIO_PASS_PCT else 'FAIL',
        'excess_contribution_cents': 0,
        '_refunds': {},
    }


def correction_deadline(eng):
    """Last day of the plan year following the plan year tested."""
    start = parse_date(eng['plan_year_start'])
    end = parse_date(eng['plan_year_end'])
    py_days = (end - start).days
    return end + timedelta(days=py_days - 1)


# --- schedule C fee aggregation (calc: schedule_c_fee_aggregation) -------------
def provider_reportable_total(engagement_id, provider_name):
    return sum(f['amount_cents'] for f in store.fees.values()
               if f['engagement_id'] == engagement_id
               and f['provider_name'] == provider_name
               and f['compensation_type'] in ('DIRECT', 'INDIRECT'))


def recompute_provider_flags(engagement_id, provider_name):
    flag = provider_reportable_total(engagement_id, provider_name) >= SCHEDULE_C_THRESHOLD_CENTS
    for f in store.fees.values():
        if f['engagement_id'] == engagement_id and f['provider_name'] == provider_name:
            f['reportable_on_schedule_c'] = flag


def any_fee_reportable(engagement_id):
    return any(f['reportable_on_schedule_c'] for f in store.fees.values()
               if f['engagement_id'] == engagement_id)


# --- excise tax window for corrective distributions ---------------------------
def excise_threshold(eng):
    """plan_year_end + 2.5 months (2 months + half-month of 15 days from PY close)."""
    last_day_of_py = parse_date(eng['plan_year_end']) - timedelta(days=1)
    return add_months(last_day_of_py, 2) + timedelta(days=15)


# --- auto finding creation -----------------------------------------------------
def create_auto_finding(engagement_id, source, category, severity,
                        contribution_id=None, test_result_id=None):
    finding = base_fields()
    finding.update({
        'engagement_id': engagement_id,
        'source': source,
        'category': category,
        'severity': severity,
        'description': ('Late remittance of participant deferral deposits'
                        if source == 'LATE_DEPOSIT_AUTO'
                        else 'Nondiscrimination test failure'),
        'contribution_id': contribution_id,
        'test_result_id': test_result_id,
        'status': 'OPEN',
    })
    store.findings[finding['id']] = finding
    eng = store.engagements.get(engagement_id)
    if eng is not None:
        recompute_posture(eng)
    return finding
