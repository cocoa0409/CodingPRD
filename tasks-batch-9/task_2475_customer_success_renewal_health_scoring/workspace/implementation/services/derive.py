"""Derived account state: health components, composite scores, tier, coverage
tier, coverage posture, time-to-value and renewal likelihood."""
from datetime import timedelta
from decimal import Decimal as D

import db as store
from db import db, track
from services import calc


# ---------------------------------------------------------------------------
# signal ordering
# ---------------------------------------------------------------------------

def usage_rows_recent_first(account_id):
    """Usage rows ordered by period_end_date descending, created_at ascending as
    the tie-break."""
    rows = store.account_signals(account_id, 'USAGE_PERIOD')
    rows = sorted(rows, key=lambda r: (r['created_at'], r['_seq']))
    rows.sort(key=lambda r: r['period_end_date'], reverse=True)
    return rows


def support_rows_in_window(account_id):
    now = db.now()
    start = now - timedelta(days=calc.SUPPORT_WINDOW_DAYS)
    result = []
    for row in store.account_signals(account_id, 'SUPPORT_TICKET'):
        opened = row.get('_opened_at')
        if opened is None:
            continue
        if start < opened <= now:
            result.append(row)
    return result


# ---------------------------------------------------------------------------
# individual components
# ---------------------------------------------------------------------------

def recompute_adoption_index(account):
    track(account)
    account['adoption_index'] = calc.adoption_index(
        usage_rows_recent_first(account['id']))


def recompute_support_risk_penalty(account):
    track(account)
    account['support_risk_penalty'] = calc.support_risk_penalty(
        support_rows_in_window(account['id']))


def recompute_exec_engagement_score(account):
    track(account)
    now = db.now()
    start = now - timedelta(days=calc.EXEC_WINDOW_DAYS)
    held_senior = 0
    held_junior = 0
    no_shows = 0
    for engagement in store.account_engagements(account['id']):
        if engagement['state'] not in ('HELD', 'NO_SHOW'):
            continue
        started = engagement['_start_at']
        if not (start < started <= now):
            continue
        if engagement['state'] == 'NO_SHOW':
            no_shows += 1
            continue
        sponsor = db.sponsor_contacts.get(engagement['sponsor_contact_id'])
        seniority = sponsor['seniority'] if sponsor else None
        if seniority in calc.SENIOR_SENIORITIES:
            held_senior += 1
        elif seniority in calc.JUNIOR_SENIORITIES:
            held_junior += 1
    has_buyer = any(s['status'] == 'ACTIVE' and s['is_economic_buyer']
                    for s in store.account_sponsors(account['id']))
    account['exec_engagement_score'] = calc.exec_engagement_score(
        held_senior, held_junior, no_shows, has_buyer)


OUTCOME_INPUT_STATUSES = ('DEFINED', 'IN_PROGRESS', 'ATTAINED', 'MISSED')


def recompute_outcome_attainment_index(account):
    track(account)
    pairs = []
    for goal in store.account_goals(account['id']):
        if goal['status'] not in OUTCOME_INPUT_STATUSES:
            continue
        track(goal)
        goal['attainment_pct'] = calc.attainment_pct(goal['actual_value'],
                                                     goal['target_value'])
        pairs.append((goal['attainment_pct'], goal['weight_bp']))
    account['outcome_attainment_index'] = calc.outcome_attainment_index(pairs)


def recompute_health_scores(account):
    """Both variants of the composite score, then the tier from the snapshot."""
    track(account)
    support_component = D('100.00') - D(account['support_risk_penalty'])
    usage_rows = usage_rows_recent_first(account['id'])
    snapshot_adoption = (D(usage_rows[0]['usage_row_index'])
                         if usage_rows else D('0.00'))
    trended_adoption = D(account['adoption_index'])
    account['snapshot_health_score'] = calc.health_score(
        snapshot_adoption, support_component, account['exec_engagement_score'],
        account['outcome_attainment_index'])
    account['trended_health_score'] = calc.health_score(
        trended_adoption, support_component, account['exec_engagement_score'],
        account['outcome_attainment_index'])
    account['health_tier'] = calc.health_tier(account['snapshot_health_score'])


def recompute_all_components(account):
    recompute_adoption_index(account)
    recompute_support_risk_penalty(account)
    recompute_exec_engagement_score(account)
    recompute_outcome_attainment_index(account)
    recompute_health_scores(account)


def apply_save_failure_penalty(account):
    """Both stored scores drop by the save-failure penalty, floored at zero, and
    the tier is re-derived."""
    track(account)
    for field in ('snapshot_health_score', 'trended_health_score'):
        value = D(account[field]) - calc.SAVE_FAILURE_PENALTY
        if value < D('0.00'):
            value = D('0.00')
        account[field] = calc.r2(value)
    account['health_tier'] = calc.health_tier(account['snapshot_health_score'])


# ---------------------------------------------------------------------------
# renewal likelihood
# ---------------------------------------------------------------------------

def days_to_renewal(account):
    return (account['_contract_end_date'] - db.today()).days


def recompute_renewal_likelihood(account):
    track(account)
    account['renewal_likelihood'] = calc.renewal_likelihood(
        account['lifecycle_state'], account['trended_health_score'],
        account['open_save_play_count'], days_to_renewal(account))


# ---------------------------------------------------------------------------
# coverage tier
# ---------------------------------------------------------------------------

def recompute_coverage_tier(account):
    track(account)
    account['coverage_tier'] = calc.coverage_tier_assignment(
        account['lifecycle_state'], account['arr_cents'],
        account['segment_band'], account['health_tier'])


# ---------------------------------------------------------------------------
# time to value
# ---------------------------------------------------------------------------

def _completed_milestone(account_id, code):
    for milestone in store.account_milestones(account_id):
        if milestone['milestone_code'] == code and milestone['state'] == 'COMPLETED':
            return milestone
    return None


def recompute_ttv(account):
    track(account)
    go_live = _completed_milestone(account['id'], 'GO_LIVE')
    kickoff = _completed_milestone(account['id'], 'KICKOFF')
    if go_live is not None:
        account['contractual_ttv_days'] = (
            go_live['_completed_date'] - account['_contract_start_date']).days
    else:
        account['contractual_ttv_days'] = None
    if go_live is not None and kickoff is not None:
        account['activation_ttv_days'] = (
            go_live['_completed_date'] - kickoff['_completed_date']).days
    else:
        account['activation_ttv_days'] = None


def evaluate_ttv_breach_flag(account):
    """Sweep rule: raise while still onboarding past target, clear once the
    account is no longer onboarding."""
    if account['lifecycle_state'] != 'ONBOARDING':
        if account['ttv_breach_flag']:
            track(account)
            account['ttv_breach_flag'] = False
        return
    elapsed = (db.today() - account['_contract_start_date']).days
    target = calc.TTV_TARGET_DAYS[account['segment_band']]
    if elapsed > target and not account['ttv_breach_flag']:
        track(account)
        account['ttv_breach_flag'] = True


# ---------------------------------------------------------------------------
# coverage posture
# ---------------------------------------------------------------------------

OPEN_ESCALATION_STATES = ('OPEN', 'COMMITTED', 'DISPUTED')


def derive_coverage_posture(account):
    track(account)
    previous = account['coverage_posture']
    lifecycle = account['lifecycle_state']
    if lifecycle in calc.DORMANT_LIFECYCLES or (
            lifecycle == 'ONBOARDING' and account['ttv_breach_flag']):
        posture = 'FROZEN'
    elif (account['open_save_play_count'] > 0
          or any(c['state'] in OPEN_ESCALATION_STATES
                 for c in store.account_escalations(account['id']))
          or not any(a['state'] == 'COMMITTED'
                     for a in store.account_assignments(account['id']))):
        posture = 'RESTRICTED'
    else:
        posture = 'OPEN'
    account['coverage_posture'] = posture

    if posture == 'FROZEN' and previous != 'FROZEN' and lifecycle == 'ONBOARDING':
        for milestone in store.account_milestones(account['id']):
            if milestone['state'] in ('PENDING', 'OVERDUE'):
                track(milestone)
                milestone['state'] = 'BLOCKED'
    elif previous == 'FROZEN' and posture != 'FROZEN':
        for milestone in store.account_milestones(account['id']):
            if milestone['state'] == 'BLOCKED':
                track(milestone)
                milestone['state'] = 'PENDING'
    return posture


# ---------------------------------------------------------------------------
# reference call cap
# ---------------------------------------------------------------------------

def recompute_reference_calls_cap(account):
    track(account)
    account['reference_calls_cap'] = calc.REFERENCE_CALL_CAP[account['segment_band']]


def open_save_play_count(account_id):
    return len([p for p in store.account_save_plays(account_id)
                if p['state'] == 'ACTIVE'])
