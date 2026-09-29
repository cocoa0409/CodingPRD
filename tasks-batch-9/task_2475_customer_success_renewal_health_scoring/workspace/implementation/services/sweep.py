"""The nightly sweep.  Four passes, in this order, all reading the logical
clock."""
import db as store
from db import db, track
from services import derive, lifecycle, risk


def run_daily_sweep():
    postures_before = {a['id']: a['coverage_posture'] for a in db.accounts.values()}

    # 1. overdue milestones
    milestones_marked_overdue = 0
    today = db.today()
    for milestone in store.ordered(db.onboarding_milestones):
        if milestone['state'] == 'PENDING' and milestone['_due_date'] < today:
            track(milestone)
            milestone['state'] = 'OVERDUE'
            milestones_marked_overdue += 1

    # 2. breached remediation commitments
    commitments_breached = 0
    for commitment in store.ordered(db.remediation_commitments):
        if commitment['state'] != 'ACCEPTED':
            continue
        if commitment['_due_date'] >= today:
            continue
        case = db.escalation_cases.get(commitment['escalation_case_id'])
        if case is None or case['state'] != 'COMMITTED':
            continue
        risk.breach_commitment(commitment, case)
        commitments_breached += 1

    # 3. stale expansion opportunities
    opportunities_expired = 0
    for opportunity in store.ordered(db.expansion_opportunities):
        if opportunity['state'] != 'IDENTIFIED':
            continue
        if lifecycle.stale_opportunity(opportunity):
            track(opportunity)
            opportunity['state'] = 'EXPIRED'
            opportunities_expired += 1

    # 4. time-to-value breach evaluation, then posture re-derivation
    for account in store.ordered(db.accounts):
        derive.evaluate_ttv_breach_flag(account)
        derive.derive_coverage_posture(account)

    accounts_repostured = 0
    for account in db.accounts.values():
        if postures_before.get(account['id']) != account['coverage_posture']:
            accounts_repostured += 1

    return {
        'milestones_marked_overdue': milestones_marked_overdue,
        'commitments_breached': commitments_breached,
        'opportunities_expired': opportunities_expired,
        'accounts_repostured': accounts_repostured,
    }
