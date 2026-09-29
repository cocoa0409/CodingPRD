"""Coverage assignment admission, preemption, release and the CSM capacity
ledger."""
import db as store
from db import db, track
from services import derive


def sync_capacity(csm):
    csm['capacity_units_available'] = (csm['capacity_units_total']
                                       - csm['capacity_units_committed'])


def committed_load(csm_id):
    return sum(a['load_units'] for a in store.csm_assignments(csm_id)
               if a['state'] == 'COMMITTED')


def sync_assigned_csm(account):
    """assigned_csm_id names the manager of the account's single COMMITTED
    assignment and is null whenever no COMMITTED assignment remains."""
    track(account)
    holder = None
    for assignment in store.account_assignments(account['id']):
        if assignment['state'] == 'COMMITTED':
            holder = assignment['csm_id']
    account['assigned_csm_id'] = holder


def eligible_pool(account):
    """ACTIVE CSMs whose coverage_specialty equals the account's coverage_tier.
    The pool is not filtered by remaining capacity."""
    pool = [c for c in store.ordered(db.csms)
            if c['status'] == 'ACTIVE'
            and c['coverage_specialty'] == account['coverage_tier']]
    return pool


def select_csm(account):
    pool = eligible_pool(account)
    if not pool:
        return None
    ranked = sorted(pool, key=lambda c: (-c['capacity_units_available'],
                                         c['created_at'], c['_seq']))
    return ranked[0]


def admit(assignment, csm):
    """Admission test: the manager is ACTIVE and has at least load_units of
    remaining capacity (inclusive)."""
    if csm['status'] != 'ACTIVE':
        return False
    if csm['capacity_units_available'] < assignment['load_units']:
        return False
    track(assignment)
    track(csm)
    assignment['state'] = 'COMMITTED'
    assignment['committed_at'] = db.clock_stamp()
    csm['capacity_units_committed'] += assignment['load_units']
    sync_capacity(csm)
    return True


def preempt_predecessors(account, new_assignment):
    """Every earlier QUEUED or COMMITTED assignment of the account is
    superseded."""
    for assignment in store.account_assignments(account['id']):
        if assignment['id'] == new_assignment['id']:
            continue
        if assignment['state'] not in ('QUEUED', 'COMMITTED'):
            continue
        was_committed = assignment['state'] == 'COMMITTED'
        track(assignment)
        assignment['state'] = 'PREEMPTED'
        assignment['superseded_by_assignment_id'] = new_assignment['id']
        assignment['released_at'] = db.clock_stamp()
        if was_committed:
            csm = db.csms.get(assignment['csm_id'])
            if csm is not None:
                track(csm)
                csm['capacity_units_committed'] -= assignment['load_units']
                sync_capacity(csm)


def promote_queued(csm):
    """After capacity frees up, the queued assignment of this manager with the
    lowest created_at that fits the freed capacity is committed."""
    candidates = [a for a in store.csm_assignments(csm['id'])
                  if a['state'] == 'QUEUED'
                  and a['load_units'] <= csm['capacity_units_available']]
    if not candidates:
        return None
    candidates.sort(key=lambda a: (a['created_at'], a['_seq']))
    winner = candidates[0]
    track(winner)
    track(csm)
    winner['state'] = 'COMMITTED'
    winner['committed_at'] = db.clock_stamp()
    csm['capacity_units_committed'] += winner['load_units']
    sync_capacity(csm)
    promoted_account = db.accounts.get(winner['account_id'])
    if promoted_account is not None:
        sync_assigned_csm(promoted_account)
        derive.derive_coverage_posture(promoted_account)
    return winner


def release(assignment, release_reason=None):
    """The four-link release cascade."""
    track(assignment)
    assignment['state'] = 'RELEASED'
    assignment['released_at'] = db.clock_stamp()
    if release_reason is not None:
        assignment['release_reason'] = release_reason

    csm = db.csms.get(assignment['csm_id'])
    if csm is not None:
        track(csm)
        csm['capacity_units_committed'] -= assignment['load_units']
        sync_capacity(csm)
        promote_queued(csm)

    account = db.accounts.get(assignment['account_id'])
    if account is not None:
        sync_assigned_csm(account)
        derive.derive_coverage_posture(account)
