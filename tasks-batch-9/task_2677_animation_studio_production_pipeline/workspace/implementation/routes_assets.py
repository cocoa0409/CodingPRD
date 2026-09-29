"""Assets: the build dimension, the reuse library dimension and reuse credit."""
from flask import Blueprint

from calc import (BUILD_CHAIN, D, MAX_CHAIN_DEPTH, asset_out, by_created,
                  chain_descendants, chain_stale, recompute_asset_credit, walk_chain)
from flows import fk_lookup, get_asset, get_production, require_phase
from helpers import (ALL_READ, ApiError, ARTIST, PM, SUPERVISOR, arg, authenticate,
                     body_json, get_enum, get_number, get_str, paginate, success,
                     validation_error)
from store import base_row, db, touch

bp = Blueprint('assets', __name__)

ASSET_TYPES = ('CHARACTER_MODEL', 'PROP', 'ENVIRONMENT', 'RIG', 'SURFACING_PACKAGE')
BUILD_STATUSES = BUILD_CHAIN + ('RETIRED',)
CREATE_PHASES = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE')
NOT_WRAPPED = ('PRE_PRODUCTION', 'PRODUCTION_ACTIVE', 'DELIVERY')


def _guard_chain(asset_id, source_id):
    depth, error = walk_chain(source_id, seed_visited=(asset_id,) if asset_id else ())
    if error == 'CYCLE':
        raise ApiError('ERR_ASSET_REUSE_CYCLE', 422,
                       'the reuse chain would revisit an asset already on the walk')
    if error == 'TOO_LONG':
        raise validation_error('the reuse chain may not exceed %d edges' % MAX_CHAIN_DEPTH)
    return depth


@bp.route('/studio/assets', methods=['POST'])
def create_asset():
    authenticate((PM, ARTIST))
    body = body_json()
    production = fk_lookup(body, 'production_id', get_production)
    source = fk_lookup(body, 'derived_from_asset_id', get_asset)
    production_id = get_str(body, 'production_id', min_len=1)
    asset_code = get_str(body, 'asset_code', min_len=1)
    asset_type = get_enum(body, 'asset_type', ASSET_TYPES)
    base_points = get_number(body, 'base_complexity_points', exclusive_min=0, places=2)
    source_id = get_str(body, 'derived_from_asset_id', required=False, default=None,
                        min_len=1)
    if production is None:
        production = get_production(production_id)
    require_phase(production, CREATE_PHASES)
    if source is not None and source['production_id'] != production['id']:
        raise ApiError('ERR_CROSS_PRODUCTION_REFERENCE', 422,
                       'derived_from_asset_id belongs to another production')
    if source_id is not None:
        _guard_chain(None, source_id)
    for row in db.assets.values():
        if row['production_id'] == production['id'] and row['asset_code'] == asset_code:
            raise ApiError('ERR_DUPLICATE_CODE', 409,
                           'asset_code is already in use in this production')

    asset = base_row()
    asset.update({
        'production_id': production['id'],
        'derived_from_asset_id': source_id,
        'asset_code': asset_code,
        'asset_type': asset_type,
        'build_status': 'BRIEFED',
        'library_status': 'PRIVATE',
        'base_complexity_points': D(base_points).quantize(D('0.01')),
        'reuse_depth': 0,
        'reuse_discount_pct': D('0.00'),
        'effective_complexity_points': D('0.00'),
        'reuse_source_stale': False,
        'library_submitted_by_user_id': None,
        'library_decided_by_user_id': None,
    })
    recompute_asset_credit(asset)
    db.assets[asset['id']] = asset
    return success(asset_out(asset), 201)


@bp.route('/studio/assets', methods=['GET'])
def list_assets():
    authenticate(ALL_READ)
    rows = list(db.assets.values())
    production_id = arg('production_id')
    if production_id is not None:
        rows = [r for r in rows if r['production_id'] == production_id]
    source_id = arg('derived_from_asset_id')
    if source_id is not None:
        rows = [r for r in rows if r['derived_from_asset_id'] == source_id]
    build_status = arg('build_status')
    if build_status is not None:
        rows = [r for r in rows if r['build_status'] == build_status]
    library_status = arg('library_status')
    if library_status is not None:
        rows = [r for r in rows if r['library_status'] == library_status]
    return paginate(by_created(rows), asset_out)


@bp.route('/studio/assets/<asset_id>', methods=['GET'])
def read_asset(asset_id):
    authenticate(ALL_READ)
    return success(asset_out(get_asset(asset_id)))


@bp.route('/studio/assets/<asset_id>/advance-build', methods=['POST'])
def advance_build(asset_id):
    authenticate((ARTIST,))
    asset = get_asset(asset_id)
    body = body_json()
    to_status = get_enum(body, 'to_build_status', BUILD_STATUSES)
    production = db.productions.get(asset['production_id'])
    require_phase(production, CREATE_PHASES)
    current = asset['build_status']
    if to_status == 'RETIRED':
        if current != 'PUBLISHED':
            raise ApiError('ERR_ASSET_BUILD_STATE_INVALID', 409,
                           'only a PUBLISHED asset may be retired')
    else:
        index = BUILD_CHAIN.index(current) if current in BUILD_CHAIN else None
        successor = None
        if index is not None and index + 1 < len(BUILD_CHAIN):
            successor = BUILD_CHAIN[index + 1]
        if successor is None or to_status != successor:
            raise ApiError('ERR_ASSET_BUILD_STATE_INVALID', 409,
                           '%s is not the immediate successor of %s' % (to_status, current))
    asset['build_status'] = to_status
    touch(asset)
    if to_status == 'RETIRED' and asset['library_status'] == 'LIBRARY_APPROVED':
        asset['library_status'] = 'LIBRARY_DEPRECATED'
        for descendant in chain_descendants(asset):
            if not descendant['reuse_source_stale']:
                descendant['reuse_source_stale'] = True
                recompute_asset_credit(descendant)
                touch(descendant)
    return success(asset_out(asset))


@bp.route('/studio/assets/<asset_id>/library-submit', methods=['POST'])
def library_submit(asset_id):
    user_id, _role = authenticate((ARTIST,))
    asset = get_asset(asset_id)
    production = db.productions.get(asset['production_id'])
    require_phase(production, NOT_WRAPPED)
    if asset['build_status'] != 'PUBLISHED':
        raise ApiError('ERR_ASSET_BUILD_STATE_INVALID', 409,
                       'only a PUBLISHED asset may be nominated')
    if asset['library_status'] != 'PRIVATE':
        raise ApiError('ERR_ASSET_LIBRARY_STATE_INVALID', 409,
                       'library_status must be PRIVATE to nominate')
    asset['library_status'] = 'LIBRARY_CANDIDATE'
    asset['library_submitted_by_user_id'] = user_id
    touch(asset)
    return success(asset_out(asset))


@bp.route('/studio/assets/<asset_id>/library-decision', methods=['POST'])
def library_decision(asset_id):
    user_id, _role = authenticate((SUPERVISOR,))
    asset = get_asset(asset_id)
    body = body_json()
    decision = get_enum(body, 'decision', ('APPROVED', 'REJECTED'))
    if (asset['library_submitted_by_user_id'] is not None
            and asset['library_submitted_by_user_id'] == user_id):
        raise ApiError('ERR_SEGREGATION_OF_DUTIES', 403,
                       'the nominator may not decide this library submission')
    production = db.productions.get(asset['production_id'])
    require_phase(production, NOT_WRAPPED)
    if asset['library_status'] != 'LIBRARY_CANDIDATE':
        raise ApiError('ERR_ASSET_LIBRARY_STATE_INVALID', 409,
                       'library_status must be LIBRARY_CANDIDATE to decide')
    asset['library_status'] = 'LIBRARY_APPROVED' if decision == 'APPROVED' else 'PRIVATE'
    asset['library_decided_by_user_id'] = user_id
    touch(asset)
    return success(asset_out(asset))


@bp.route('/studio/assets/<asset_id>/relink-source', methods=['POST'])
def relink_source(asset_id):
    authenticate((PM,))
    asset = get_asset(asset_id)
    body = body_json()
    source = fk_lookup(body, 'derived_from_asset_id', get_asset)
    source_id = get_str(body, 'derived_from_asset_id', min_len=1)
    if source is None:
        source = get_asset(source_id)
    production = db.productions.get(asset['production_id'])
    require_phase(production, NOT_WRAPPED)
    if source['production_id'] != asset['production_id']:
        raise ApiError('ERR_CROSS_PRODUCTION_REFERENCE', 422,
                       'derived_from_asset_id belongs to another production')
    _guard_chain(asset['id'], source_id)
    asset['derived_from_asset_id'] = source_id
    asset['reuse_source_stale'] = chain_stale(asset)
    recompute_asset_credit(asset)
    touch(asset)
    return success(asset_out(asset))
