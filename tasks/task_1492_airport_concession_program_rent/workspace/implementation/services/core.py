"""Shared business logic: calculations (scaffold Table 3), derived-field
reconciliation, cascades, and the logical-clock sweeps.

All money is integer cents, all rates are basis points, and every rounding is
round half up (PRD section 2.5).
"""
import calendar
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import g

from db import db, now_iso

MONTHS_PER_YEAR = 12
SETTLEMENT_DUE_DAYS = 30

SETTLEMENT_ACTIVE_STATUSES = ('INVOICED', 'PARTIALLY_PAID', 'OVERDUE')


def pub(ent):
    """Public view of a stored record (internal bookkeeping keys removed)."""
    return {k: v for k, v in ent.items() if not k.startswith('_')}


def touch(ent):
    """Record a mutation: version +1 and updated_at refresh.

    Deduplicated per request so a multi-step operation bumps each affected
    resource exactly once.
    """
    seen = getattr(g, '_touch_seen', None)
    if seen is None:
        seen = g._touch_seen = set()
    key = id(ent)
    if key in seen:
        return
    seen.add(key)
    ent['version'] += 1
    ent['updated_at'] = now_iso()


def rhu_int(numer, denom=1):
    """round_half_up(numer / denom) to integer cents/bp using Decimal."""
    return int((Decimal(numer) / Decimal(denom)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))


def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


def month_add(month, n):
    y = int(month[:4])
    m = int(month[5:7])
    idx = y * 12 + (m - 1) + n
    return '{0}-{1:02d}'.format(idx // 12, idx % 12 + 1)


def current_month():
    return db.clock.strftime('%Y-%m')


# ---------------------------------------------------------------------------
# calculations.monthly_percentage_rent
# ---------------------------------------------------------------------------
def monthly_percentage_rent(lease, effective_gross):
    bp = lease['pct_breakpoint_cents']
    below = lease['pct_rate_below_bp']
    above = lease['pct_rate_above_bp']
    if effective_gross <= bp:
        # Boundary is inclusive: gross == breakpoint stays in tier 1.
        total = effective_gross * below
    else:
        total = bp * below + (effective_gross - bp) * above
    # Rounded half up to integer cents ONCE per monthly report.
    return rhu_int(total, 10000)


def effective_gross_of(report):
    if report['status'] == 'ADJUSTED':
        return report['restated_gross_sales_cents']
    return report['gross_sales_cents']


def effective_gross_map(lease_id, year):
    """month -> effective gross for ACCEPTED/ADJUSTED reports of the lease/year."""
    res = {}
    prefix = '{0}-'.format(year)
    for r in db.sales_reports.values():
        if r['lease_id'] != lease_id:
            continue
        if r['status'] not in ('ACCEPTED', 'ADJUSTED'):
            continue
        if not r['period_month'].startswith(prefix):
            continue
        res[r['period_month']] = effective_gross_of(r)
    return res


# ---------------------------------------------------------------------------
# calculations.annual_rent_settlement — MAG proration side
# ---------------------------------------------------------------------------
def mag_due_for_year(lease, year):
    ts = parse_date(lease['term_start_date'])
    te = parse_date(lease['term_end_date'])
    weight = Decimal('0')
    for m in range(1, 13):
        days_in_m = calendar.monthrange(year, m)[1]
        m_start = date(year, m, 1)
        m_end_excl = m_start + timedelta(days=days_in_m)
        lo = max(m_start, ts)
        hi = min(m_end_excl, te)
        covered = (hi - lo).days
        if covered <= 0:
            continue
        if covered == days_in_m:
            weight += Decimal(1)
        else:
            # Partial month: 4-decimal proration, rounded half up before summing.
            weight += (Decimal(covered) / Decimal(days_in_m)).quantize(
                Decimal('0.0001'), rounding=ROUND_HALF_UP)
    return int((Decimal(lease['mag_annual_cents']) * weight / Decimal(MONTHS_PER_YEAR)).quantize(
        Decimal('1'), rounding=ROUND_HALF_UP))


def compute_settlement_amounts(lease, st, variant):
    """Pure computation; returns the field dict (does not store or touch)."""
    year = st['period_year']
    mag = mag_due_for_year(lease, year)
    eff = effective_gross_map(lease['id'], year)
    pct = 0
    if variant == 'PROVISIONAL':
        # Every month of the year contributes: reported months at their
        # percentage rent, unreported months projected at MAG/12.
        for m in range(1, 13):
            key = '{0}-{1:02d}'.format(year, m)
            if key in eff:
                pct += monthly_percentage_rent(lease, eff[key])
            else:
                pct += rhu_int(lease['mag_annual_cents'], MONTHS_PER_YEAR)
    else:
        # FINAL: only ACCEPTED/ADJUSTED reports count; unreported months -> 0.
        for gross in eff.values():
            pct += monthly_percentage_rent(lease, gross)
    true_up = max(0, pct - mag)
    amount_due = mag + true_up
    paid = sum(p['amount_cents'] for p in db.payments.values()
               if p['settlement_id'] == st['id'] and p['status'] == 'POSTED')
    return {
        'mag_due_cents': mag,
        'percentage_due_cents': pct,
        'true_up_due_cents': true_up,
        'amount_due_cents': amount_due,
        'amount_paid_cents': paid,
        'balance_due_cents': amount_due - paid,
    }


def variant_for_status(status):
    return 'PROVISIONAL' if status == 'ACCRUING' else 'FINAL'


def recalc_settlement(st, variant=None, touch_it=True):
    lease = db.leases[st['lease_id']]
    if variant is None:
        variant = variant_for_status(st['status'])
    st['variant_used'] = variant
    st.update(compute_settlement_amounts(lease, st, variant))
    if touch_it:
        touch(st)


def find_settlement(lease_id, year):
    for s in db.settlements.values():
        if s['lease_id'] == lease_id and s['period_year'] == year:
            return s
    return None


# ---------------------------------------------------------------------------
# calculations.arrears_reconciliation / ti_allowance_reconciliation
# ---------------------------------------------------------------------------
def recompute_arrears(lease, touch_it=True):
    lease['arrears_cents'] = sum(
        s['balance_due_cents'] for s in db.settlements.values()
        if s['lease_id'] == lease['id'] and s['status'] in SETTLEMENT_ACTIVE_STATUSES)
    if touch_it:
        touch(lease)


def recompute_ti(lease, touch_it=True):
    committed = sum(d['amount_cents'] for d in db.draws.values()
                    if d['lease_id'] == lease['id'] and d['status'] in ('DISBURSED', 'APPROVED'))
    lease['ti_remaining_cents'] = lease['ti_allowance_cents'] - committed
    if touch_it:
        touch(lease)


# ---------------------------------------------------------------------------
# Lease termination / expiry cascades
# ---------------------------------------------------------------------------
def cascade_lease_close(lease):
    """Draws in REQUESTED/APPROVED -> CANCELLED; waivers in REQUESTED ->
    REJECTED; the approved-pending TI reserve is released."""
    for d in db.draws.values():
        if d['lease_id'] == lease['id'] and d['status'] in ('REQUESTED', 'APPROVED'):
            d['status'] = 'CANCELLED'
            touch(d)
    for w in db.waivers.values():
        if w['lease_id'] == lease['id'] and w['status'] == 'REQUESTED':
            w['status'] = 'REJECTED'
            touch(w)
    recompute_ti(lease)


# ---------------------------------------------------------------------------
# Logical-clock sweeps (PRD section 2.4)
# ---------------------------------------------------------------------------
def run_clock_sweeps():
    today = db.clock.date()
    # Lease expiry sweep: ACTIVE/DEFAULTED with current date > term_end_date
    # (strict boundary — equality does not expire) -> EXPIRED with cascades.
    for lease in list(db.leases.values()):
        if lease['status'] in ('ACTIVE', 'DEFAULTED') and today > parse_date(lease['term_end_date']):
            lease['status'] = 'EXPIRED'
            cascade_lease_close(lease)
            touch(lease)
    # Settlement overdue sweep: INVOICED/PARTIALLY_PAID, due_date earlier than
    # the new current date, balance still positive -> OVERDUE.
    for st in list(db.settlements.values()):
        if (st['status'] in ('INVOICED', 'PARTIALLY_PAID') and st['due_date']
                and today > parse_date(st['due_date']) and st['balance_due_cents'] > 0):
            was_invoiced = st['status'] == 'INVOICED'
            st['status'] = 'OVERDUE'
            touch(st)
            if was_invoiced:
                # Arrears value is unchanged; the lease's updated_at refreshes.
                touch(db.leases[st['lease_id']])


# ---------------------------------------------------------------------------
# calculations.sales_per_enplanement (PRD section 3.8)
# ---------------------------------------------------------------------------
def lease_performance(lease):
    eff = {}
    for r in db.sales_reports.values():
        if r['lease_id'] == lease['id'] and r['status'] in ('ACCEPTED', 'ADJUSTED'):
            eff[r['period_month']] = effective_gross_of(r)
    snaps = {s['month']: s['enplanements'] for s in db.enplanements.values()}

    def window_stats(months):
        qualifying = [m for m in months if m in eff and m in snaps]
        if not qualifying:
            return None, 0, 0
        sales = sum(eff[m] for m in qualifying)
        enp = sum(snaps[m] for m in qualifying)
        return rhu_int(sales * 100, enp), sales, enp

    if eff:
        latest = max(eff.keys())
        ttm_months = [month_add(latest, -i) for i in range(11, -1, -1)]
        spe_ttm, sales_ttm, enp_ttm = window_stats(ttm_months)
    else:
        spe_ttm, sales_ttm, enp_ttm = None, 0, 0

    cy = db.clock.year
    cm = db.clock.month
    ytd_months = ['{0}-{1:02d}'.format(cy, m) for m in range(1, cm + 1)]
    spe_ytd, _sales_ytd, _enp_ytd = window_stats(ytd_months)

    if spe_ttm is None:
        outcome = 'INSUFFICIENT_DATA'
    elif spe_ttm < lease['min_spe_cents']:
        outcome = 'UNDERPERFORMING'
    else:
        outcome = 'SATISFACTORY'

    return {
        'spe_ttm_cents': spe_ttm,
        'spe_ytd_cents': spe_ytd,
        'sales_ttm_cents': sales_ttm,
        'enplanements_ttm': enp_ttm,
        'review_outcome': outcome,
    }


# ---------------------------------------------------------------------------
# calculations.acdbe_attainment (PRD section 3.7)
# ---------------------------------------------------------------------------
def acdbe_total_gross(lease_id, year):
    return sum(effective_gross_map(lease_id, year).values())


def acdbe_attainment_bp(numerator, total_gross):
    if total_gross == 0:
        return 0
    return rhu_int(numerator * 10000, total_gross)


# ---------------------------------------------------------------------------
# calculations.policy_violation_penalty (PRD section 3.9)
# ---------------------------------------------------------------------------
HOURS_PENALTY_PER_HOUR_CENTS = 25000
PRICING_MIN_PENALTY_CENTS = 5000
PRICING_OVERCHARGE_MULTIPLIER = 2


def violation_penalty(kind, shortfall_minutes, overcharge_cents):
    if kind == 'OPERATING_HOURS':
        # Ceil per violation event: any partial hour counts as a full hour.
        hours = -(-shortfall_minutes // 60)
        return hours * HOURS_PENALTY_PER_HOUR_CENTS
    return max(PRICING_MIN_PENALTY_CENTS, PRICING_OVERCHARGE_MULTIPLIER * overcharge_cents)
