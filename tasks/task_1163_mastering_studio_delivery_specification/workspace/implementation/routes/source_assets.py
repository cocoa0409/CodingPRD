from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_DUPLICATE_ASSET, ERR_SOURCE_BELOW_SPEC,
    ERR_ENTITY_NOT_ACTIVE,
)
from middleware import (
    auth, require_roles, body, req_field, as_str, as_int, as_num,
    pagination_args, get_or_404, ensure_state,
    check_client_owner, check_engineer_assigned, SHA256_RE,
)
from response import success, success_list

bp = Blueprint('source_assets', __name__)

CHANNELS = (1, 2, 6, 8)


def _project_of(asset):
    return db.projects.get(asset['project_id'])


@bp.post('/studio/projects/<pid>/source-assets')
def upload_asset(pid):
    uid, role = auth()
    require_roles(role, ('Client', 'Engineer'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    check_engineer_assigned(uid, role, proj)
    data = body()
    filename = as_str(req_field(data, 'filename'), 'filename')
    sha256 = as_str(req_field(data, 'sha256'), 'sha256')
    if not SHA256_RE.match(sha256):
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'sha256 must be 64 lowercase hexadecimal characters')
    sample_rate_hz = as_int(req_field(data, 'sample_rate_hz'), 'sample_rate_hz')
    bit_depth = as_int(req_field(data, 'bit_depth'), 'bit_depth')
    duration_seconds = as_num(req_field(data, 'duration_seconds'), 'duration_seconds')
    if duration_seconds <= 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'duration_seconds must be > 0')
    channels = as_int(req_field(data, 'channels'), 'channels')
    if channels not in CHANNELS:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'channels must be one of 1, 2, 6, 8')
    # Guard 5: state — intake is reachable from BOOKED or while in INTAKE.
    ensure_state('Project', proj, 'status', ('BOOKED', 'INTAKE'))
    # Guard 10: checksum uniqueness within the project.
    for a in db.source_assets.values():
        if a['project_id'] == pid and a['sha256'] == sha256:
            raise ApiError(ERR_DUPLICATE_ASSET, 409,
                           'sha256 already present on this project')
    # First upload to a BOOKED project moves it BOOKED -> INTAKE; this path
    # requires the assigned engineer AVAILABLE. Check before mutating anything.
    if proj['status'] == 'BOOKED':
        eng = db.engineers.get(proj.get('assigned_engineer_id') or '')
        if eng is None or eng['availability_status'] != 'AVAILABLE':
            raise ApiError(ERR_ENTITY_NOT_ACTIVE, 422, 'Engineer is not AVAILABLE')
    rec = db.new_record()
    rec.update({
        'project_id': pid,
        'filename': filename,
        'sha256': sha256,
        'sample_rate_hz': sample_rate_hz,
        'bit_depth': bit_depth,
        'duration_seconds': duration_seconds,
        'channels': channels,
        'qc_status': 'PENDING',
        'qc_failure_reason': None,
    })
    db.source_assets[rec['id']] = rec
    if proj['status'] == 'BOOKED':
        proj['status'] = 'INTAKE'
        db.touch(proj)
        for slot in db.session_slots.values():
            if slot.get('project_id') == pid and slot['status'] == 'BOOKED':
                slot['status'] = 'CONSUMED'
                db.touch(slot)
    return success(db.public(rec), 201)


@bp.get('/studio/projects/<pid>/source-assets')
def list_project_assets(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    qc_status = request.args.get('qc_status')
    items = [a for a in db.source_assets.values() if a['project_id'] == pid]
    if qc_status is not None:
        items = [a for a in items if a['qc_status'] == qc_status]
    items.sort(key=lambda a: a['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/source-assets/<aid>')
def get_asset(aid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    asset = get_or_404(db.source_assets, aid)
    proj = _project_of(asset)
    if proj is not None:
        check_client_owner(uid, role, proj)
    return success(db.public(asset), 200)


@bp.post('/studio/source-assets/<aid>/qc-pass')
def qc_pass_asset(aid):
    uid, role = auth()
    require_roles(role, ('Engineer', 'QAChecker'))
    asset = get_or_404(db.source_assets, aid)
    proj = _project_of(asset)
    if proj is not None:
        check_engineer_assigned(uid, role, proj)
    ensure_state('SourceAsset', asset, 'qc_status', ('PENDING',))
    # Guard 19: source must meet the platform target.
    profile = db.platform_profiles.get(proj['target_platform_profile_id']) if proj else None
    if profile is not None:
        if (asset['sample_rate_hz'] < profile['required_sample_rate_hz']
                or asset['bit_depth'] < profile['required_bit_depth']):
            raise ApiError(ERR_SOURCE_BELOW_SPEC, 422,
                           'Source asset is below the platform sample-rate or bit-depth requirement')
    asset['qc_status'] = 'PASSED'
    db.touch(asset)
    return success(db.public(asset), 200)


@bp.post('/studio/source-assets/<aid>/qc-fail')
def qc_fail_asset(aid):
    uid, role = auth()
    require_roles(role, ('Engineer', 'QAChecker'))
    asset = get_or_404(db.source_assets, aid)
    proj = _project_of(asset)
    if proj is not None:
        check_engineer_assigned(uid, role, proj)
    ensure_state('SourceAsset', asset, 'qc_status', ('PENDING',))
    data = body()
    reason = as_str(req_field(data, 'qc_failure_reason'), 'qc_failure_reason')
    asset['qc_status'] = 'FAILED'
    asset['qc_failure_reason'] = reason
    db.touch(asset)
    return success(db.public(asset), 200)


@bp.post('/studio/source-assets/<aid>/qc-waive')
def qc_waive_asset(aid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    asset = get_or_404(db.source_assets, aid)
    ensure_state('SourceAsset', asset, 'qc_status', ('FAILED',))
    asset['qc_status'] = 'WAIVED'
    db.touch(asset)
    return success(db.public(asset), 200)
