from flask import Blueprint

import db
from middleware import (
    auth, require_roles, pagination_args, get_or_404, ensure_state,
    check_client_owner,
)
from response import success, success_list

bp = Blueprint('metadata_tags', __name__)


def _owner_check_via_tag(uid, role, tag):
    d = db.deliverables.get(tag['deliverable_id'])
    proj = db.projects.get(d['project_id']) if d else None
    if proj is not None:
        check_client_owner(uid, role, proj)


@bp.get('/studio/deliverables/<did>/metadata-tags')
def list_tags_for_deliverable(did):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    d = get_or_404(db.deliverables, did)
    proj = db.projects.get(d['project_id'])
    if proj is not None:
        check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    items = [t for t in db.metadata_tags.values() if t['deliverable_id'] == did]
    items.sort(key=lambda t: t['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/metadata-tags/<tid>')
def get_tag(tid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    tag = get_or_404(db.metadata_tags, tid)
    _owner_check_via_tag(uid, role, tag)
    return success(db.public(tag), 200)


@bp.post('/studio/metadata-tags/<tid>/verify')
def verify_tag(tid):
    uid, role = auth()
    require_roles(role, ('QAChecker',))
    tag = get_or_404(db.metadata_tags, tid)
    ensure_state('MetadataTag', tag, 'embedding_status', ('EMBEDDED',))
    tag['embedding_status'] = 'VERIFIED'
    tag['verified_at'] = db.now_iso()
    db.touch(tag)
    return success(db.public(tag), 200)


@bp.post('/studio/metadata-tags/<tid>/flag-mismatch')
def flag_mismatch(tid):
    uid, role = auth()
    require_roles(role, ('QAChecker',))
    tag = get_or_404(db.metadata_tags, tid)
    ensure_state('MetadataTag', tag, 'embedding_status', ('EMBEDDED',))
    tag['embedding_status'] = 'MISMATCH'
    db.touch(tag)
    return success(db.public(tag), 200)


@bp.post('/studio/metadata-tags/<tid>/revoke')
def revoke_tag(tid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    tag = get_or_404(db.metadata_tags, tid)
    ensure_state('MetadataTag', tag, 'embedding_status', ('MISMATCH',))
    tag['embedding_status'] = 'REVOKED'
    db.touch(tag)
    return success(db.public(tag), 200)
