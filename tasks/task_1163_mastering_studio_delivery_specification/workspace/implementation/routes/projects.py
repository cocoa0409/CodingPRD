from datetime import timedelta

from flask import Blueprint, request

import db
from errors import (
    ApiError, ERR_INVALID_REQUEST, ERR_INVALID_FORMAT, ERR_INVALID_TIME_BOUNDARY,
    ERR_DUPLICATE_UPC, ERR_ENTITY_NOT_ACTIVE, ERR_STALE_VERSION,
    ERR_INSUFFICIENT_CREDIT, ERR_INVALID_STATE, ERR_NOT_FOUND,
    ERR_CLIENT_NOT_OWNER, ERR_ALREADY_TERMINAL,
)
from middleware import (
    auth, require_roles, body, req_field, opt_field, as_str, as_int, as_enum,
    as_datetime, pagination_args, get_or_404, ensure_state,
    check_client_owner, check_engineer_assigned, UPC_RE,
)
from response import success, success_list
from services import pricing
from services.capacity import select_engineer

bp = Blueprint('projects', __name__)

RUSH_TIERS = ('STANDARD', 'EXPRESS', 'RUSH', 'EMERGENCY')
STORAGE_CLASSES = ('HOT', 'WARM', 'COLD', 'GLACIER')


def _open_round(project, notes=None):
    rule = pricing.rule_for_tier(project['rush_tier']) or pricing._DEFAULT_RULE
    opened = db.now_dt()
    rnd = db.new_record()
    rnd.update({
        'project_id': project['id'],
        'round_index': project['revision_round_count'] + 1,
        'status': 'OPEN',
        'opened_at': db.iso(opened),
        'submitted_at': None,
        'resolved_at': None,
        'deadline_at': db.iso(opened + timedelta(hours=rule['sla_hours'])),
        'notes': notes,
    })
    db.revision_rounds[rnd['id']] = rnd
    project['current_revision_round_id'] = rnd['id']
    project['revision_round_count'] += 1
    client = db.clients.get(project['client_id'])
    if client is not None:
        client['lifetime_revision_count'] += 1
        db.touch(client)
    return rnd


def _consume_booked_slots(project):
    for slot in db.session_slots.values():
        if slot.get('project_id') == project['id'] and slot['status'] == 'BOOKED':
            slot['status'] = 'CONSUMED'
            db.touch(slot)


def _release_project_slots(project):
    for slot in db.session_slots.values():
        if slot.get('project_id') == project['id'] and slot['status'] in ('HELD', 'BOOKED'):
            slot['status'] = 'RELEASED'
            db.touch(slot)


def _decrement_engineer(project):
    eng_id = project.get('assigned_engineer_id')
    if eng_id:
        eng = db.engineers.get(eng_id)
        if eng is not None:
            eng['active_project_count'] -= 1
            db.touch(eng)


def _cancel_project(project):
    _release_project_slots(project)
    _decrement_engineer(project)
    project['status'] = 'CANCELLED'
    db.touch(project)


@bp.post('/studio/projects')
def create_project():
    uid, role = auth()
    require_roles(role, ('Client',))
    data = body()
    client_id = as_str(req_field(data, 'client_id'), 'client_id')
    title = as_str(req_field(data, 'title'), 'title')
    profile_id = as_str(req_field(data, 'target_platform_profile_id'), 'target_platform_profile_id')
    start_raw = req_field(data, 'scheduled_start_at')
    duration = as_int(req_field(data, 'scheduled_duration_minutes'), 'scheduled_duration_minutes')
    rush_tier = opt_field(data, 'rush_tier', 'STANDARD')
    rush_tier = as_enum(rush_tier, 'rush_tier', RUSH_TIERS)
    upc = opt_field(data, 'upc')
    # Guard 4: body FK existence.
    get_or_404(db.clients, client_id)
    get_or_404(db.platform_profiles, profile_id)
    # Ownership: a client creates projects for themselves.
    if client_id != uid:
        raise ApiError(ERR_CLIENT_NOT_OWNER, 403,
                       'Client attempting to create a project for another client')
    # Duration: multiple of 30 in [60, 480].
    if duration % 30 != 0 or duration < 60 or duration > 480:
        raise ApiError(ERR_INVALID_REQUEST, 400,
                       'scheduled_duration_minutes must be a multiple of 30 in [60, 480]')
    start_dt = as_datetime(start_raw, 'scheduled_start_at')
    # Guard 9: 30-minute boundary.
    if not db.on_grid(start_dt):
        raise ApiError(ERR_INVALID_TIME_BOUNDARY, 400,
                       'scheduled_start_at must land on a 30-minute boundary')
    if upc is not None:
        # Guard 11: UPC uniqueness. Guard 12: UPC format.
        for p in db.projects.values():
            if p.get('upc') is not None and p['upc'] == upc:
                raise ApiError(ERR_DUPLICATE_UPC, 409, 'UPC already registered to another Project')
        if not isinstance(upc, str) or not UPC_RE.match(upc):
            raise ApiError(ERR_INVALID_FORMAT, 400, 'upc must be a 12-digit numeric string')
    rec = db.new_record()
    rec.update({
        'client_id': client_id,
        'title': title,
        'upc': upc,
        'status': 'DRAFT',
        'assigned_engineer_id': None,
        'scheduled_start_at': db.iso(start_dt),
        'scheduled_duration_minutes': duration,
        'target_platform_profile_id': profile_id,
        'rush_tier': rush_tier,
        'quoted_price_cents': 0,
        'final_price_cents': 0,
        'current_revision_round_id': None,
        'revision_round_count': 0,
        'archive_bundle_id': None,
    })
    db.projects[rec['id']] = rec
    return success(db.public(rec), 201)


@bp.get('/studio/projects')
def list_projects():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    items = list(db.projects.values())
    if role == 'Client':
        items = [p for p in items if p['client_id'] == uid]
    for f in ('client_id', 'status', 'assigned_engineer_id', 'target_platform_profile_id',
              'current_revision_round_id', 'archive_bundle_id'):
        val = request.args.get(f)
        if val is not None:
            items = [p for p in items if p.get(f) == val]
    items.sort(key=lambda p: p['_seq'])
    total = len(items)
    page = items[offset:offset + limit]
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/projects/<pid>')
def get_project(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/book')
def book_project(pid):
    uid, role = auth()
    require_roles(role, ('Client',))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    data = body()
    expected_client_version = as_int(req_field(data, 'expected_client_version'),
                                     'expected_client_version')
    client = db.clients.get(proj['client_id'])
    if client is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Owning client not found')
    # Guard 5: state.
    ensure_state('Project', proj, 'status', ('DRAFT',))
    # Guard 6: client must be ACTIVE.
    if client['status'] != 'ACTIVE':
        raise ApiError(ERR_ENTITY_NOT_ACTIVE, 422, 'Client is not ACTIVE')
    # Guards 7/8: slot overlap + capacity via the engineer selector.
    start = db.parse_dt(proj['scheduled_start_at'])
    end = start + timedelta(minutes=proj['scheduled_duration_minutes'])
    engineer = select_engineer(start, end, proj['scheduled_duration_minutes'])
    # Guard 20 (last): optimistic concurrency on the client.
    if expected_client_version != client['version']:
        raise ApiError(ERR_STALE_VERSION, 412,
                       'expected_client_version does not match current client version')
    # Side effects (atomic).
    slot = db.new_record()
    slot.update({
        'engineer_id': engineer['id'],
        'project_id': proj['id'],
        'slot_start_at': proj['scheduled_start_at'],
        'slot_end_at': db.iso(end),
        'status': 'BOOKED',
        'held_expires_at': None,
    })
    db.session_slots[slot['id']] = slot
    proj['assigned_engineer_id'] = engineer['id']
    engineer['active_project_count'] += 1
    db.touch(engineer)
    proj['quoted_price_cents'] = pricing.quote_provisional(proj, engineer)
    proj['status'] = 'BOOKED'
    db.touch(proj)
    db.touch(client)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/cancel')
def cancel_project(pid):
    uid, role = auth()
    require_roles(role, ('Client', 'StudioManager'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    ensure_state('Project', proj, 'status', ('DRAFT', 'BOOKED', 'INTAKE'))
    _cancel_project(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/begin-intake')
def begin_intake(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('BOOKED',))
    engineer = db.engineers.get(uid)
    if engineer is None or engineer['availability_status'] != 'AVAILABLE':
        raise ApiError(ERR_ENTITY_NOT_ACTIVE, 422, 'Engineer is not AVAILABLE')
    proj['status'] = 'INTAKE'
    db.touch(proj)
    _consume_booked_slots(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/qc/complete')
def qc_complete(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('INTAKE',))
    assets = [a for a in db.source_assets.values() if a['project_id'] == pid]
    if any(a['qc_status'] not in ('PASSED', 'WAIVED') for a in assets):
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Not all source assets have reached PASSED or WAIVED')
    proj['status'] = 'QC_PASSED'
    db.touch(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/start-mastering')
def start_mastering(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('QC_PASSED',))
    _open_round(proj)
    proj['status'] = 'MASTERING'
    db.touch(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/deliver')
def deliver(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('APPROVED',))
    has_verified = any(
        d['project_id'] == pid
        and d['revision_round_id'] == proj['current_revision_round_id']
        and d['status'] == 'VERIFIED'
        for d in db.deliverables.values()
    )
    if not has_verified:
        raise ApiError(ERR_INVALID_STATE, 409,
                       'No VERIFIED deliverable exists for the current revision round')
    proj['status'] = 'DELIVERING'
    db.touch(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/finalize-delivery')
def finalize_delivery(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('DELIVERING',))
    pending = [
        d for d in db.deliverables.values()
        if d['project_id'] == pid
        and d['revision_round_id'] == proj['current_revision_round_id']
        and d['status'] not in ('VERIFIED', 'RETIRED')
    ]
    if pending:
        raise ApiError(ERR_INVALID_STATE, 409,
                       'Not all deliverables for the current round are VERIFIED or RETIRED')
    proj['status'] = 'DELIVERED'
    db.touch(proj)
    return success(db.public(proj), 200)


@bp.post('/studio/projects/<pid>/archive')
def archive_project(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager',))
    proj = get_or_404(db.projects, pid)
    data = body()
    storage_class = as_enum(req_field(data, 'storage_class'), 'storage_class', STORAGE_CLASSES)
    size = as_int(req_field(data, 'archive_size_bytes'), 'archive_size_bytes')
    if size < 0:
        raise ApiError(ERR_INVALID_REQUEST, 400, 'archive_size_bytes must be >= 0')
    ensure_state('Project', proj, 'status', ('DELIVERED',))
    bundle = db.new_record()
    bundle.update({
        'project_id': pid,
        'storage_class': storage_class,
        'archive_size_bytes': size,
        'recall_status': 'NONE',
        'recalled_at': None,
        'restored_at': None,
        'recall_fee_cents': 0,
    })
    db.archive_bundles[bundle['id']] = bundle
    proj['archive_bundle_id'] = bundle['id']
    proj['status'] = 'ARCHIVED'
    _decrement_engineer(proj)
    db.touch(proj)
    return success(db.public(bundle), 200)


def _do_recall(proj, bundle):
    ensure_state('Project', proj, 'status', ('ARCHIVED',))
    if bundle['recall_status'] in ('RESTORED', 'FAILED'):
        raise ApiError(ERR_ALREADY_TERMINAL, 409,
                       'ArchiveBundle is already in terminal recall state %s' % bundle['recall_status'])
    if bundle['recall_status'] != 'NONE':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'ArchiveBundle recall_status is %s, not NONE' % bundle['recall_status'])
    fee = pricing.compute_recall_fee(bundle)
    client = db.clients.get(proj['client_id'])
    if client is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'Owning client not found')
    # Guard 14: credit sufficiency.
    if client['account_credit_cents'] - fee < 0:
        raise ApiError(ERR_INSUFFICIENT_CREDIT, 402,
                       'Client balance would go negative after recall fee debit')
    bundle['recall_status'] = 'PENDING'
    bundle['recalled_at'] = db.now_iso()
    bundle['recall_fee_cents'] = fee
    db.touch(bundle)
    client['account_credit_cents'] -= fee
    db.touch(client)
    proj['status'] = 'RECALLED'
    db.touch(proj)
    return bundle


@bp.post('/studio/projects/<pid>/recall')
def recall_project(pid):
    uid, role = auth()
    require_roles(role, ('Client',))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    bundle = db.archive_bundles.get(proj.get('archive_bundle_id') or '')
    if bundle is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'No archive bundle for project')
    _do_recall(proj, bundle)
    return success(db.public(bundle), 200)


@bp.post('/studio/projects/<pid>/resume-from-recall')
def resume_from_recall(pid):
    uid, role = auth()
    require_roles(role, ('Engineer',))
    proj = get_or_404(db.projects, pid)
    check_engineer_assigned(uid, role, proj)
    ensure_state('Project', proj, 'status', ('RECALLED',))
    bundle = db.archive_bundles.get(proj.get('archive_bundle_id') or '')
    if bundle is None:
        raise ApiError(ERR_NOT_FOUND, 404, 'No archive bundle for project')
    if bundle['recall_status'] == 'FAILED':
        raise ApiError(ERR_ALREADY_TERMINAL, 409, 'ArchiveBundle restore FAILED')
    if bundle['recall_status'] != 'RESTORED':
        raise ApiError(ERR_INVALID_STATE, 409,
                       'ArchiveBundle recall_status is %s, not RESTORED' % bundle['recall_status'])
    eng = db.engineers.get(proj.get('assigned_engineer_id') or '')
    if eng is not None:
        eng['active_project_count'] += 1
        db.touch(eng)
    proj['status'] = 'MASTERING'
    db.touch(proj)
    return success(db.public(proj), 200)
