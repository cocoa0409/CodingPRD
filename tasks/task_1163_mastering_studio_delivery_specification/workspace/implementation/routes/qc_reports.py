from flask import Blueprint, request

import db
from middleware import (
    auth, require_roles, body, req_field, opt_field, as_num, as_bool, as_enum,
    pagination_args, get_or_404, bool_filter, check_client_owner,
)
from response import success, success_list

bp = Blueprint('qc_reports', __name__)

CHECK_CODES = ('LOUDNESS_IN_TOL', 'TRUE_PEAK_IN_TOL', 'LRA_IN_TOL', 'FORMAT_MATCH',
               'ISRC_PRESENT', 'UPC_MATCH', 'CLIP_FREE', 'DC_OFFSET_OK', 'PHASE_COHERENT')


def _apply_filters(args, items):
    check_code = args.get('check_code')
    if check_code is not None:
        items = [r for r in items if r['check_code'] == check_code]
    passed = bool_filter('passed')
    if passed is not None:
        items = [r for r in items if r['passed'] == passed]
    project_id = args.get('project_id')
    if project_id is not None:
        items = [r for r in items if r['project_id'] == project_id]
    deliverable_id = args.get('deliverable_id')
    if deliverable_id is not None:
        items = [r for r in items if r['deliverable_id'] == deliverable_id]
    return items


def _page(items, limit, offset):
    items.sort(key=lambda r: r['_seq'])
    total = len(items)
    return items[offset:offset + limit], total


@bp.post('/studio/deliverables/<did>/qc-reports')
def create_report(did):
    uid, role = auth()
    require_roles(role, ('QAChecker', 'Engineer'))
    d = get_or_404(db.deliverables, did)
    data = body()
    check_code = as_enum(req_field(data, 'check_code'), 'check_code', CHECK_CODES)
    passed = as_bool(req_field(data, 'passed'), 'passed')
    measured_value = opt_field(data, 'measured_value')
    if measured_value is not None:
        measured_value = as_num(measured_value, 'measured_value')
    tolerance = opt_field(data, 'tolerance')
    if tolerance is not None:
        tolerance = as_num(tolerance, 'tolerance')
    rec = db.new_record()
    rec.update({
        'deliverable_id': did,
        'project_id': d['project_id'],
        'check_code': check_code,
        'passed': passed,
        'measured_value': measured_value,
        'tolerance': tolerance,
    })
    db.qc_reports[rec['id']] = rec
    # System-maintained pointer to the latest QC run on the deliverable.
    d['qc_report_id'] = rec['id']
    db.touch(d)
    return success(db.public(rec), 201)


@bp.get('/studio/projects/<pid>/qc-reports')
def list_project_reports(pid):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    proj = get_or_404(db.projects, pid)
    check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    items = [r for r in db.qc_reports.values() if r['project_id'] == pid]
    items = _apply_filters(request.args, items)
    page, total = _page(items, limit, offset)
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/qc-reports')
def list_reports():
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    limit, offset = pagination_args()
    items = list(db.qc_reports.values())
    if role == 'Client':
        owned = {p['id'] for p in db.projects.values() if p['client_id'] == uid}
        items = [r for r in items if r['project_id'] in owned]
    items = _apply_filters(request.args, items)
    page, total = _page(items, limit, offset)
    return success_list(db.public_list(page), limit, offset, total)


@bp.get('/studio/deliverables/<did>/qc-reports')
def list_deliverable_reports(did):
    uid, role = auth()
    require_roles(role, ('StudioManager', 'Client', 'Engineer', 'QAChecker'))
    d = get_or_404(db.deliverables, did)
    proj = db.projects.get(d['project_id'])
    if proj is not None:
        check_client_owner(uid, role, proj)
    limit, offset = pagination_args()
    items = [r for r in db.qc_reports.values() if r['deliverable_id'] == did]
    items = _apply_filters(request.args, items)
    page, total = _page(items, limit, offset)
    return success_list(db.public_list(page), limit, offset, total)
