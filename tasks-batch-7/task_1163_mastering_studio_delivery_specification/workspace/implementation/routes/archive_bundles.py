from flask import Blueprint, request

import db
from errors import ApiError, ERR_NOT_FOUND
from middleware import (
    auth, require_roles, pagination_args, get_or_404, ensure_state,
    check_client_owner,
)
from response import success, success_list
from routes.projects import _do_recall

bp = Blueprint('archive_bundles', __name__)


def _bundle_project(bundle):
    return db.projects.get(bundle['project_id'])


@bp.get('/studio/archive-bundles')
def list_bundles():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'QAChecker'))
    limit, offset = pagination_args()
    items = list(db.archive_bundles.values())
    if role == 'Client':
        owned = {p['id'] for p in db.projects.values() if p['client_id'] == uid}
        items = [b for b in items if b['project_id'] in owned]
    project_id = request.args.get('project_id')
    if project_id is not None:
        items = [b for b in items if b['project_id'] == project_id]
    recall_status = request.args.get('recall_status')
    if recall_status is not None:
        items = [b for b in items if b['recall_status'] == recall_status]
    items.sort(key=lambda b: b['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/archive-bundles/<bid>')
def get_bundle(bid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'QAChecker'))
    bundle = get_or_404(db.archive_bundles, bid)
    proj = _bundle_project(bundle)
    if proj is not None:
        check_client_owner(uid, role, proj)
    return success(db.public(bundle), 200)


@bp.post('/studio/archive-bundles/<bid>/recall')
def recall_bundle(bid):
    uid, role = auth()
    require_roles(role, ('Client',))
    bundle = get_or_404(db.archive_bundles, bid)
    proj = _bundle_project(bundle)
    if proj is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Bundle project not found')
    check_client_owner(uid, role, proj)
    _do_recall(proj, bundle)
    return success(db.public(bundle), 200)


@bp.post('/studio/archive-bundles/<bid>/begin-restore')
def begin_restore(bid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    bundle = get_or_404(db.archive_bundles, bid)
    ensure_state('ArchiveBundle', bundle, 'recall_status', ('PENDING',))
    bundle['recall_status'] = 'RESTORING'
    db.touch(bundle)
    return success(db.public(bundle), 200)


@bp.post('/studio/archive-bundles/<bid>/complete-restore')
def complete_restore(bid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    bundle = get_or_404(db.archive_bundles, bid)
    ensure_state('ArchiveBundle', bundle, 'recall_status', ('RESTORING',))
    bundle['recall_status'] = 'RESTORED'
    bundle['restored_at'] = db.now_iso()
    db.touch(bundle)
    return success(db.public(bundle), 200)


@bp.post('/studio/archive-bundles/<bid>/fail-restore')
def fail_restore(bid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    bundle = get_or_404(db.archive_bundles, bid)
    ensure_state('ArchiveBundle', bundle, 'recall_status', ('RESTORING',))
    bundle['recall_status'] = 'FAILED'
    db.touch(bundle)
    return success(db.public(bundle), 200)
