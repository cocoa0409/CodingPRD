from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_FORMAT,
    ERR_METADATA_MISMATCH, ERR_QC_FAILED, ERR_NO_SUPERSEDING_DELIVERABLE,
    ERR_INVALID_STATE,
)
from middleware import (
    auth, require_roles, body, req_field, opt_field, as_str, as_int, as_num,
    as_enum, pagination_args, get_or_404, ensure_state,
    check_client_owner, check_engineer_assigned, UPC_RE, ISRC_RE,
)
from response import success, success_list
from services.loudness import compliance_passed

bp = Blueprint('deliverables', __name__)

DELIVERABLE_KINDS = ('DDP', 'STEM_PACK', 'INSTRUMENTAL', 'MASTER_WAV',
                     'MASTER_FLAC', 'MASTER_AAC', 'VINYL_PREMASTER')


def _project_of(d):
    return db.projects.get(d['project_id'])


def _list_filtered(args, items):
    for f in ('project_id', 'revision_round_id', 'qc_report_id', 'deliverable_kind', 'status'):
        val = args.get(f)
        if val is not None:
            items = [d for d in items if d.get(f) == val]
    return items


@bp.post('/studio/projects/<pid>/deliverables')
def create_deliverable(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    data = body()
    round_id = as_str(req_field(data, 'revision_round_id'), 'revision_round_id')
    kind = as_enum(req_field(data, 'deliverable_kind'), 'deliverable_kind', DELIVERABLE_KINDS)
    integrated_lufs = as_num(req_field(data, 'integrated_lufs'), 'integrated_lufs')
    true_peak_dbtp = as_num(req_field(data, 'true_peak_dbtp'), 'true_peak_dbtp')
    loudness_range_lu = as_num(req_field(data, 'loudness_range_lu'), 'loudness_range_lu')
    sample_rate_hz = as_int(req_field(data, 'sample_rate_hz'), 'sample_rate_hz')
    bit_depth = as_int(req_field(data, 'bit_depth'), 'bit_depth')
    # Guard 4: the producing round must exist under this project.
    rnd = db.revision_rounds.get(round_id)
    if rnd is None or rnd['project_id'] != pid:
        raise ApiError(ERR_NOT_FOUND, 404, 'Revision round not found for this project')
    rec = db.new_record()
    rec.update({
        'project_id': pid,
        'revision_round_id': round_id,
        'deliverable_kind': kind,
        'integrated_lufs': integrated_lufs,
        'true_peak_dbtp': true_peak_dbtp,
        'loudness_range_lu': loudness_range_lu,
        'sample_rate_hz': sample_rate_hz,
        'bit_depth': bit_depth,
        'status': 'BUILDING',
        'qc_report_id': None,
    })
    db.deliverables[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/projects/<pid>/deliverables')
def list_project_deliverables(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    items = [d for d in db.deliverables.values() if d['project_id'] == pid]
    items = _list_filtered(request.args, items)
    items.sort(key=lambda d: d['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/deliverables')
def list_deliverables():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    items = list(db.deliverables.values())
    if role == 'Client':
        owned = {p['id'] for p in db.projects.values() if p['client_id'] == uid}
        items = [d for d in items if d['project_id'] in owned]
    items = _list_filtered(request.args, items)
    items.sort(key=lambda d: d['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/deliverables/<did>')
def get_deliverable(did):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    d = get_or_404(db.deliverables, did)
    proj = _project_of(d)
    if proj is not None:
        check_client_owner(uid, role, proj)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/submit-qc')
def submit_qc(did):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    d = get_or_404(db.deliverables, did)
    proj = _project_of(d)
    if proj is not None:
        check_engineer_assigned(uid, role, proj)
    ensure_state('Deliverable', d, 'status', ('BUILDING',))
    d['status'] = 'QC_PENDING'
    db.touch(d)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/qc-pass')
def qc_pass(did):
    uid, role = auth()
    require_roles(role, ('QAChecker',))
    d = get_or_404(db.deliverables, did)
    ensure_state('Deliverable', d, 'status', ('QC_PENDING',))
    reports = [r for r in db.qc_reports.values() if r['deliverable_id'] == did]
    if any(not r['passed'] for r in reports):
        raise ApiError(ERR_QC_FAILED, 422, 'At least one QCReport has passed=false')
    # Guard 18: loudness/format compliance against the project's platform profile.
    proj = _project_of(d)
    profile = db.platform_profiles.get(proj['target_platform_profile_id']) if proj else None
    if profile is None or not compliance_passed(d, profile):
        raise ApiError(ERR_QC_FAILED, 422,
                       'Deliverable loudness/format QC checks did not pass')
    d['status'] = 'READY'
    db.touch(d)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/qc-fail')
def qc_fail(did):
    uid, role = auth()
    require_roles(role, ('QAChecker',))
    d = get_or_404(db.deliverables, did)
    ensure_state('Deliverable', d, 'status', ('QC_PENDING',))
    reports = [r for r in db.qc_reports.values() if r['deliverable_id'] == did]
    if not any(not r['passed'] for r in reports):
        raise ApiError(ERR_QC_FAILED, 422, 'No failing QCReport exists for this deliverable')
    d['status'] = 'QC_FAILED'
    db.touch(d)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/rebuild')
def rebuild(did):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    d = get_or_404(db.deliverables, did)
    proj = _project_of(d)
    if proj is not None:
        check_engineer_assigned(uid, role, proj)
    ensure_state('Deliverable', d, 'status', ('QC_FAILED',))
    d['status'] = 'BUILDING'
    db.touch(d)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/metadata-tags')
def embed_metadata(did):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    d = get_or_404(db.deliverables, did)
    proj = _project_of(d)
    if proj is not None:
        check_engineer_assigned(uid, role, proj)
    data = body()
    isrc = as_str(req_field(data, 'isrc'), 'isrc')
    upc = opt_field(data, 'upc')
    ensure_state('Deliverable', d, 'status', ('READY',))
    # Guard 12: code formats.
    if not ISRC_RE.match(isrc):
        raise ApiError(ERR_INVALID_FORMAT, 400, 'isrc does not match the ISRC format')
    if upc is not None and (not isinstance(upc, str) or not UPC_RE.match(upc)):
        raise ApiError(ERR_INVALID_FORMAT, 400, 'upc must be a 12-digit numeric string')
    # Guard 13: metadata consistency with the parent project.
    if proj is not None and proj.get('upc') is not None and upc != proj['upc']:
        raise ApiError(ERR_METADATA_MISMATCH, 422,
                       'MetadataTag.upc must equal the parent project upc')
    # ISRC uniqueness per deliverable kind within the project.
    for t in db.metadata_tags.values():
        other = db.deliverables.get(t['deliverable_id'])
        if (other is not None and other['project_id'] == d['project_id']
                and other['deliverable_kind'] == d['deliverable_kind']
                and t['isrc'] == isrc and t['embedding_status'] != 'REVOKED'):
            raise ApiError(ERR_INVALID_REQUEST, 409,
                           'isrc already used for this deliverable kind within the project')
    tag = db.new_record()
    tag.update({
        'deliverable_id': did,
        'isrc': isrc,
        'upc': upc,
        'embedding_status': 'EMBEDDED',
        'embedded_at': db.now_iso(),
        'verified_at': None,
    })
    db.metadata_tags[tag['id']] = tag
    d['status'] = 'EMBEDDED'
    db.touch(d)
    return success(db.public(tag), 201)


@bp.post('/studio/deliverables/<did>/verify-metadata')
def verify_metadata(did):
    uid, role = auth()
    require_roles(role, ('QAChecker',))
    d = get_or_404(db.deliverables, did)
    ensure_state('Deliverable', d, 'status', ('EMBEDDED',))
    tags = [t for t in db.metadata_tags.values() if t['deliverable_id'] == did]
    tags.sort(key=lambda t: t['_seq'])
    tag = tags[-1] if tags else None
    if tag is None or tag['embedding_status'] != 'EMBEDDED':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'No EMBEDDED metadata tag exists for this deliverable')
    tag['embedding_status'] = 'VERIFIED'
    tag['verified_at'] = db.now_iso()
    db.touch(tag)
    d['status'] = 'VERIFIED'
    db.touch(d)
    return success(db.public(d), 200)


@bp.post('/studio/deliverables/<did>/retire')
def retire(did):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    d = get_or_404(db.deliverables, did)
    ensure_state('Deliverable', d, 'status', ('VERIFIED',))
    # Guard 17: supersession — a newer deliverable for the same (project, round).
    newer = any(
        o['project_id'] == d['project_id']
        and o['revision_round_id'] == d['revision_round_id']
        and o['_seq'] > d['_seq']
        for o in db.deliverables.values()
    )
    if not newer:
        raise ApiError(ERR_NO_SUPERSEDING_DELIVERABLE, 409,
                       'No newer deliverable exists for the same project and revision round')
    d['status'] = 'RETIRED'
    db.touch(d)
    for t in db.metadata_tags.values():
        if t['deliverable_id'] == did and t['embedding_status'] != 'REVOKED':
            t['embedding_status'] = 'REVOKED'
            db.touch(t)
    return success(db.public(d), 200)
