"""Cost-share pools, contributions, deposits, and charge entries."""
from flask import Blueprint

from auth import auth, own_or_403
from calc import (get_application, get_pool, get_deposit, find_pool,
                  find_deposit, deposit_required)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, now, touch
from validate import body, req, as_str, as_int

bp = Blueprint('money', __name__)

POOL_ROLES = ['Organizer', 'Neighbor', 'PermitOfficer', 'CityAdmin']
DEPOSIT_ROLES = ['Organizer', 'PermitOfficer', 'CityAdmin']


@bp.route('/permit-applications/<aid>/cost-share-pools', methods=['POST'])
def create_pool(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED', 'ISSUED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit pool creation' % app['status'], 409)
    if find_pool(aid) is not None:
        raise ApiError('ERR_DUPLICATE_RESOURCE',
                       'A cost-share pool already exists for this application', 409)
    b = body()
    target = as_int(req(b, 'target_cents'), 'target_cents')
    if target <= 0:
        raise ApiError('ERR_INVALID_REQUEST', 'target_cents must be > 0', 400)
    pool = entity(application_id=aid, target_cents=target, collected_cents=0,
                  refunded_cents=0, status='OPEN')
    db.pools[pool['id']] = pool
    return created(pool)


@bp.route('/permit-applications/<aid>/cost-share-pools', methods=['GET'])
def list_pools(aid):
    uid, role = auth(POOL_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([p for p in db.pools.values() if p['application_id'] == aid])


@bp.route('/cost-share-pools/<pid>', methods=['GET'])
def get_one_pool(pid):
    uid, role = auth(POOL_ROLES)
    pool = get_pool(pid)
    app = get_application(pool['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(pool)


@bp.route('/cost-share-pools/<pid>/contributions', methods=['POST'])
def contribute(pid):
    auth(['Neighbor'])
    pool = get_pool(pid)
    b = body()
    ha = as_str(req(b, 'household_address'), 'household_address')
    amount = as_int(req(b, 'amount_cents'), 'amount_cents')
    if pool['status'] != 'OPEN':
        raise ApiError('ERR_POOL_NOT_OPEN', 'Pool is not OPEN', 409)
    if amount < 100:
        raise ApiError('ERR_CONTRIBUTION_BELOW_MIN',
                       'Contributions must be at least 100 cents', 400)
    c = entity(pool_id=pool['id'], household_address=ha, amount_cents=amount,
               status='PAID', refunded_at=None)
    db.contributions[c['id']] = c
    pool['collected_cents'] += amount
    if pool['collected_cents'] >= pool['target_cents']:
        pool['status'] = 'FUNDED'
    touch(pool)
    return created(c)


@bp.route('/cost-share-pools/<pid>/contributions', methods=['GET'])
def list_contributions(pid):
    uid, role = auth(POOL_ROLES)
    pool = get_pool(pid)
    app = get_application(pool['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([c for c in db.contributions.values() if c['pool_id'] == pid])


@bp.route('/cost-share-pools/<pid>/close', methods=['POST'])
def close_pool(pid):
    uid, role = auth(['Organizer'])
    pool = get_pool(pid)
    app = get_application(pool['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    if pool['status'] not in ('OPEN', 'FUNDED'):
        raise ApiError('ERR_INVALID_STATE', 'Pool is not OPEN or FUNDED', 409)
    if app['status'] != 'ISSUED' or now() <= app['event_end_at']:
        raise ApiError('ERR_INVALID_STATE',
                       'Pool can be closed only after the event of an ISSUED application', 409)
    pool['status'] = 'CLOSED'
    touch(pool)
    return ok(pool)


@bp.route('/permit-applications/<aid>/deposits', methods=['POST'])
def create_deposit(aid):
    uid, role = auth(['Organizer'])
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    if app['status'] not in ('UNDER_REVIEW', 'SUSPENDED', 'APPROVED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Application state %s does not permit deposit creation' % app['status'], 409)
    if find_deposit(aid) is not None:
        raise ApiError('ERR_DUPLICATE_RESOURCE',
                       'A deposit already exists for this application', 409)
    required = deposit_required(app)
    dep = entity(application_id=aid, required_cents=required, held_cents=required,
                 charges_cents=0, refund_cents=None, status='HELD')
    db.deposits[dep['id']] = dep
    return created(dep)


@bp.route('/permit-applications/<aid>/deposits', methods=['GET'])
def list_deposits(aid):
    uid, role = auth(DEPOSIT_ROLES)
    app = get_application(aid)
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([d for d in db.deposits.values() if d['application_id'] == aid])


@bp.route('/deposits/<did>', methods=['GET'])
def get_one_deposit(did):
    uid, role = auth(DEPOSIT_ROLES)
    dep = get_deposit(did)
    app = get_application(dep['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok(dep)


@bp.route('/deposits/<did>/settle', methods=['POST'])
def settle_deposit(did):
    auth(['PermitOfficer'])
    dep = get_deposit(did)
    app = get_application(dep['application_id'])
    if dep['status'] != 'HELD':
        raise ApiError('ERR_INVALID_STATE', 'Deposit is not HELD', 409)
    if app['status'] not in ('ISSUED', 'REVOKED') or now() <= app['event_end_at']:
        raise ApiError('ERR_INVALID_STATE',
                       'Deposit can be settled only after the event of an ISSUED or REVOKED application',
                       409)
    dep['status'] = 'SETTLED'
    dep['refund_cents'] = dep['held_cents'] - dep['charges_cents']
    touch(dep)
    return ok(dep)


@bp.route('/deposits/<did>/charges', methods=['GET'])
def list_charges(did):
    uid, role = auth(DEPOSIT_ROLES)
    dep = get_deposit(did)
    app = get_application(dep['application_id'])
    own_or_403(role, uid, app['organizer_id'])
    return ok_list([c for c in db.charges.values() if c['deposit_id'] == did])
