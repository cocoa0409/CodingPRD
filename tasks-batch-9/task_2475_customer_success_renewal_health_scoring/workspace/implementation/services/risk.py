"""Save-play failure, escalation breach cascade and the remediation credit
ledger."""
import db as store
from db import db, track
from services import calc, derive


def decrement_open_plays(account):
    track(account)
    if account['open_save_play_count'] > 0:
        account['open_save_play_count'] -= 1


def increment_open_plays(account):
    track(account)
    account['open_save_play_count'] += 1


def fail_save_play(play, outcome_note=None):
    """ACTIVE -> FAILED with the full account consequence."""
    track(play)
    play['state'] = 'FAILED'
    if outcome_note is not None:
        play['outcome_note'] = outcome_note
    account = db.accounts.get(play['account_id'])
    if account is None:
        return
    decrement_open_plays(account)
    derive.apply_save_failure_penalty(account)
    derive.recompute_renewal_likelihood(account)
    derive.derive_coverage_posture(account)


def add_outstanding(account, cents):
    track(account)
    account['remediation_credit_outstanding_cents'] += cents


def subtract_outstanding(account, cents):
    track(account)
    account['remediation_credit_outstanding_cents'] -= cents
    if account['remediation_credit_outstanding_cents'] < 0:
        account['remediation_credit_outstanding_cents'] = 0


def breach_commitment(commitment, case):
    """Sweep breach cascade: the commitment breaches, the case is disputed and
    reopened for another round, and the underlying save play fails."""
    account = db.accounts.get(case['account_id'])
    track(commitment)
    commitment['state'] = 'BREACHED'
    if account is not None:
        subtract_outstanding(account, commitment['credit_cents'])
    track(case)
    case['state'] = 'DISPUTED'
    case['remediation_round'] += 1
    play = db.save_plays.get(case['save_play_id'])
    if play is not None and play['state'] == 'ACTIVE':
        fail_save_play(play)
    elif account is not None:
        derive.derive_coverage_posture(account)


def delivered_commitment_total(case_id):
    return sum(c['credit_cents'] for c in store.case_commitments(case_id)
               if c['state'] == 'DELIVERED')


def resolve_case(case, account):
    """RESOLVED: the settlement credit is computed, moved into the settled
    counter and taken out of the outstanding counter."""
    delivered = delivered_commitment_total(case['id'])
    final = calc.settlement_credit(account['arr_cents'], case['severity'], delivered)
    track(case)
    case['final_credit_cents'] = final
    case['state'] = 'RESOLVED'
    track(account)
    account['remediation_credit_settled_cents'] += final
    subtract_outstanding(account, delivered)
    derive.derive_coverage_posture(account)


def withdraw_case(case, account):
    for commitment in store.case_commitments(case['id']):
        if commitment['state'] in ('PROPOSED', 'ACCEPTED'):
            was_accepted = commitment['state'] == 'ACCEPTED'
            track(commitment)
            commitment['state'] = 'WITHDRAWN'
            if was_accepted and account is not None:
                subtract_outstanding(account, commitment['credit_cents'])
    track(case)
    case['state'] = 'WITHDRAWN'
    if account is not None:
        derive.derive_coverage_posture(account)


def save_play_day_capacity_ok(account_id, play):
    """No calendar day inside the window may already carry the maximum number of
    ACTIVE plays for the account.  Windows are closed intervals."""
    start = play['_window_start_date']
    end = play['_window_end_date']
    active = [p for p in store.account_save_plays(account_id)
              if p['state'] == 'ACTIVE' and p['id'] != play['id']]
    from datetime import timedelta
    day = start
    while day <= end:
        overlapping = 0
        for other in active:
            if other['_window_start_date'] <= day <= other['_window_end_date']:
                overlapping += 1
        if overlapping >= calc.MAX_CONCURRENT_SAVE_PLAYS:
            return False
        day = day + timedelta(days=1)
    return True
