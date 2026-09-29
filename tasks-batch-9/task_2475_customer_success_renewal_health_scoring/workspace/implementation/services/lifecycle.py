"""Account lifecycle actions and the cascades they carry."""
from datetime import timedelta

import db as store
from db import db, track
from errors import ApiError
from services import calc, coverage, derive, risk

LIFECYCLE_ACTIONS = ('RENEW', 'CHURN', 'WIN_BACK_TARGET', 'REACTIVATE', 'ARCHIVE',
                     'WAIVE_TTV_BREACH')
CHURN_ROOT_CAUSE_CODES = ('PRODUCT_GAP', 'PRICE', 'SPONSOR_CHURN',
                          'POOR_ONBOARDING', 'SUPPORT_QUALITY',
                          'MERGER_ACQUISITION')
# MERGER_ACQUISITION is the one root cause that bars a win-back campaign.
WIN_BACK_ELIGIBLE_ROOT_CAUSES = ('PRODUCT_GAP', 'PRICE', 'SPONSOR_CHURN',
                                 'POOR_ONBOARDING', 'SUPPORT_QUALITY')
ADVOCACY_LIVE_STATES = ('NOMINATED', 'APPROVED', 'ACTIVE', 'SUSPENDED')


def _lifecycle_invalid(account, action):
    return ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                    'Action %s is not available from lifecycle state %s.'
                    % (action, account['lifecycle_state']))


def revoke_advocacy(account):
    for enrollment in store.account_enrollments(account['id']):
        if enrollment['state'] in ADVOCACY_LIVE_STATES:
            track(enrollment)
            enrollment['state'] = 'REVOKED'


def suspend_active_advocacy(account):
    for enrollment in store.account_enrollments(account['id']):
        if enrollment['state'] == 'ACTIVE':
            track(enrollment)
            enrollment['state'] = 'SUSPENDED'


def stale_opportunity(opportunity):
    return db.now() > opportunity['_identified_at'] + timedelta(
        days=calc.OPPORTUNITY_STALE_DAYS)


def expire_stale_opportunities(account):
    expired = 0
    for opportunity in store.account_opportunities(account['id']):
        if opportunity['state'] != 'IDENTIFIED':
            continue
        if stale_opportunity(opportunity):
            track(opportunity)
            opportunity['state'] = 'EXPIRED'
            expired += 1
    return expired


def has_locked_forecast(account):
    return any(f['cs_state'] == 'LOCKED' for f in store.account_forecasts(account['id']))


def apply_action(account, action, churn_root_cause_code=None,
                 win_back_offer_bp=None, new_contract_end_date=None,
                 new_contract_end_raw=None):
    state = account['lifecycle_state']
    track(account)

    if action == 'RENEW':
        if state not in ('STEADY', 'AT_RISK'):
            raise _lifecycle_invalid(account, action)
        if not has_locked_forecast(account):
            raise ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                           'Renewal requires a renewal forecast whose cs_state is '
                           'LOCKED.')
        if account['coverage_posture'] == 'FROZEN':
            raise ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                           'Renewal requires a coverage posture that is not FROZEN.')
        account['lifecycle_state'] = 'RENEWED'
        if state == 'STEADY':
            # Renewing from STEADY also clears stale pipeline; renewing from
            # AT_RISK does not.
            expire_stale_opportunities(account)
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    if action == 'CHURN':
        if state not in ('ONBOARDING', 'ADOPTING', 'STEADY', 'AT_RISK'):
            raise _lifecycle_invalid(account, action)
        account['churn_root_cause_code'] = churn_root_cause_code
        account['lifecycle_state'] = 'CHURNED'
        for assignment in list(store.account_assignments(account['id'])):
            if assignment['state'] == 'COMMITTED':
                coverage.release(assignment)
        if state == 'ONBOARDING':
            for assignment in store.account_assignments(account['id']):
                if assignment['state'] == 'QUEUED':
                    track(assignment)
                    assignment['state'] = 'PREEMPTED'
                    assignment['released_at'] = db.clock_stamp()
            for milestone in store.account_milestones(account['id']):
                if milestone['state'] in ('PENDING', 'OVERDUE', 'BLOCKED'):
                    track(milestone)
                    milestone['state'] = 'WAIVED'
        if state == 'AT_RISK':
            for play in store.account_save_plays(account['id']):
                if play['state'] == 'ACTIVE':
                    track(play)
                    play['state'] = 'ABANDONED'
                    risk.decrement_open_plays(account)
            revoke_advocacy(account)
        if state != 'ONBOARDING':
            derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    if action == 'WIN_BACK_TARGET':
        if state != 'CHURNED':
            raise _lifecycle_invalid(account, action)
        if account['churn_root_cause_code'] not in WIN_BACK_ELIGIBLE_ROOT_CAUSES:
            raise ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                           'Churn root cause %s bars a win-back campaign.'
                           % account['churn_root_cause_code'])
        account['win_back_offer_bp'] = win_back_offer_bp
        account['lifecycle_state'] = 'WIN_BACK_TARGETED'
        derive.recompute_coverage_tier(account)
        # "The category is recomputed on every health recompute, on every account
        # lifecycle transition, and on every save-play transition into a terminal
        # state." The only edge that opts out is churn from ONBOARDING.
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    if action == 'REACTIVATE':
        if state != 'WIN_BACK_TARGETED':
            raise _lifecycle_invalid(account, action)
        if new_contract_end_date <= db.today():
            raise ApiError('ERR_CONTRACT_END_IN_PAST',
                           'new_contract_end_date must be strictly after the '
                           'current logical date.')
        account['contract_end_date'] = new_contract_end_raw
        account['_contract_end_date'] = new_contract_end_date
        account['contract_start_date'] = db.today().strftime('%Y-%m-%d')
        account['_contract_start_date'] = db.today()
        account['churn_root_cause_code'] = None
        account['win_back_offer_bp'] = None
        account['lifecycle_state'] = 'ADOPTING'
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    if action == 'ARCHIVE':
        if state != 'WIN_BACK_TARGETED':
            raise _lifecycle_invalid(account, action)
        for opportunity in store.account_opportunities(account['id']):
            if opportunity['state'] in ('IDENTIFIED', 'HANDED_OFF'):
                raise ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                               'The account still carries a live expansion '
                               'opportunity.')
        revoke_advocacy(account)
        account['lifecycle_state'] = 'ARCHIVED'
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    if action == 'WAIVE_TTV_BREACH':
        if state != 'ONBOARDING':
            raise _lifecycle_invalid(account, action)
        if not account['ttv_breach_flag']:
            raise ApiError('ERR_ACCOUNT_LIFECYCLE_INVALID',
                           'The account does not carry a time-to-value breach.')
        account['ttv_breach_flag'] = False
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
        return

    raise _lifecycle_invalid(account, action)


def evaluate_onboarding_completion(account):
    """ONBOARDING -> ADOPTING once every milestone of the account is COMPLETED or
    WAIVED."""
    if account['lifecycle_state'] != 'ONBOARDING':
        return False
    milestones = store.account_milestones(account['id'])
    if not milestones:
        return False
    if any(m['state'] not in ('COMPLETED', 'WAIVED') for m in milestones):
        return False
    track(account)
    account['lifecycle_state'] = 'ADOPTING'
    derive.recompute_ttv(account)
    account['ttv_breach_flag'] = False
    derive.derive_coverage_posture(account)
    return True


def evaluate_health_lifecycle_edges(account):
    """The lifecycle edges that depend on the freshly derived health tier."""
    state = account['lifecycle_state']
    tier = account['health_tier']
    plays = account['open_save_play_count']
    has_open_case = any(c['state'] in derive.OPEN_ESCALATION_STATES
                        for c in store.account_escalations(account['id']))
    moved = None
    if state == 'ADOPTING' and tier == 'GREEN' and plays == 0:
        moved = 'STEADY'
    elif state == 'ADOPTING' and tier == 'RED':
        moved = 'AT_RISK'
    elif state == 'STEADY' and tier == 'RED':
        moved = 'AT_RISK'
    elif state == 'AT_RISK' and tier == 'GREEN' and plays == 0 and not has_open_case:
        moved = 'STEADY'
    if moved is None:
        return None
    track(account)
    account['lifecycle_state'] = moved
    derive.recompute_renewal_likelihood(account)
    if moved == 'AT_RISK':
        suspend_active_advocacy(account)
    return moved
