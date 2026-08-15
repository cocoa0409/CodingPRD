"""RepairNotice lifecycle: create/list/read, issue, extensions (OCC),
appeal, appeal-decision, inspections (PASS/FAIL with delinquency cascade)."""
from flask import Blueprint, g, request

from db import db, base_entity, touch
from errors import ApiError, not_found, ownership, segregation
from middleware import ALL_ROLES, require_roles
from response import ok_list, ok_object
from services import (OPEN_DEFECT_STATUSES, TERMINAL_NOTICE_STATUSES,
                      HARDSHIP_EXTENSION_DAYS, APPEAL_RESET_DAYS,
                      owner_id_of_parcel, release_notice_defects,
                      recompute_delinquency_flag, ser_inspection, ser_notice,
                      transition_notice_to_delinquent, verify_notice_defects)
from util import add_days, new_id, now_iso
from validation import get_body, parse_pagination, validate

bp = Blueprint('notices', __name__)


def _defect_under_active_notice(defect_id, exclude_notice_id=None):
    for n in db.notices.values():
        if n['id'] == exclude_notice_id:
            continue
        if n['status'] in TERMINAL_NOTICE_STATUSES:
            continue
        if defect_id in n['defect_ids']:
            return True
    return False


@bp.post('/repair-notices')
@require_roles('ProgramCoordinator')
def create_notice():
    vals = validate(get_body(), [
        ('parcel_id', 'str', True, {}),
        ('defect_ids', 'str_list', True, {}),
        ('base_deadline_days', 'int', False, {'default': 45, 'positive': True}),
        ('prior_notice_id', 'str', False, {'default': None}),
    ])
    # priority 4: body FK existence left-to-right (parcel_id, defect_ids, prior_notice_id)
    parcel = db.parcels.get(vals['parcel_id'])
    if not parcel:
        raise not_found('parcel')
    defects = []
    for did in vals['defect_ids']:
        d = db.defects.get(did)
        if not d:
            raise not_found('defect')
        defects.append(d)
    prior = None
    if vals['prior_notice_id'] is not None:
        prior = db.notices.get(vals['prior_notice_id'])
        if not prior:
            raise not_found('notice')
    # priority 5: defect state at create
    for d in defects:
        if d['status'] not in OPEN_DEFECT_STATUSES:
            raise ApiError('ERR_INVALID_DEFECT_STATE', 409,
                           'A referenced defect is not OPEN or AWAITING_FORESTRY')
    # priority 7: referential composition, in PRD §3.3 order
    if not vals['defect_ids']:
        raise ApiError('ERR_NO_ELIGIBLE_DEFECTS', 422, 'defect_ids must be non-empty')
    parcel_segment_ids = {s['id'] for s in db.segments.values()
                          if s['parcel_id'] == parcel['id']}
    for d in defects:
        if d['segment_id'] not in parcel_segment_ids:
            raise ApiError('ERR_DEFECT_NOT_IN_PARCEL', 422,
                           'A defect does not belong to this parcel')
    for d in defects:
        if _defect_under_active_notice(d['id']):
            raise ApiError('ERR_DEFECT_UNDER_ACTIVE_NOTICE', 422,
                           'A defect is already covered by a non-terminal notice')
    if parcel['owner_responsibility_pct'] <= 0:
        raise ApiError('ERR_CITY_PARCEL_NOT_NOTICABLE', 422,
                       'City-owned parcels cannot be noticed')
    if prior is not None and (prior['status'] != 'VOID'
                              or prior['parcel_id'] != parcel['id']):
        raise ApiError('ERR_INVALID_NOTICE_REFERENCE', 422,
                       'prior_notice_id must reference a VOID notice on the same parcel')
    n = base_entity()
    n.update({
        'parcel_id': parcel['id'],
        'defect_ids': list(vals['defect_ids']),
        'base_deadline_days': vals['base_deadline_days'],
        'issued_at': None,
        'compliance_deadline': None,
        'prior_notice_id': vals['prior_notice_id'],
        'issued_by_user_id': None,
        'appeal_status': 'NONE',
        'appeal_grounds': None,
        'appeal_decided_by_user_id': None,
        'appeal_decided_at': None,
        'status': 'DRAFT',
    })
    db.notices[n['id']] = n
    return ok_object(ser_notice(n), 201)


@bp.get('/repair-notices')
@require_roles(*ALL_ROLES)
def list_notices():
    rows = list(db.notices.values())
    if g.role == 'PropertyOwner':
        rows = [n for n in rows if owner_id_of_parcel(n['parcel_id']) == g.uid]
    parcel_id = request.args.get('parcel_id')
    if parcel_id is not None:
        rows = [n for n in rows if n['parcel_id'] == parcel_id]
    prior_notice_id = request.args.get('prior_notice_id')
    if prior_notice_id is not None:
        rows = [n for n in rows if n['prior_notice_id'] == prior_notice_id]
    status = request.args.get('status')
    if status is not None:
        rows = [n for n in rows if n['status'] == status]
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser_notice(n) for n in page], total, limit, offset)


@bp.get('/repair-notices/<nid>')
@require_roles(*ALL_ROLES)
def get_notice(nid):
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    return ok_object(ser_notice(n))


@bp.post('/repair-notices/<nid>/issue')
@require_roles('ProgramCoordinator')
def issue_notice(nid):
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    if n['status'] != 'DRAFT':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409, 'Notice is not DRAFT')
    for did in n['defect_ids']:
        d = db.defects.get(did)
        if not d or d['status'] not in OPEN_DEFECT_STATUSES:
            raise ApiError('ERR_INVALID_DEFECT_STATE', 409,
                           'A referenced defect is not OPEN or AWAITING_FORESTRY')
    n['status'] = 'ISSUED'
    n['issued_at'] = db.clock
    n['issued_by_user_id'] = g.uid
    days = n['base_deadline_days']
    parcel = db.parcels.get(n['parcel_id'])
    owner = db.owners.get(parcel['owner_id']) if parcel else None
    if owner and owner['hardship_tier'] != 'NONE':
        days += HARDSHIP_EXTENSION_DAYS
    n['compliance_deadline'] = add_days(db.clock, days)
    touch(n)
    for did in n['defect_ids']:
        d = db.defects[did]
        if d['status'] == 'OPEN':
            d['status'] = 'UNDER_REPAIR'
            touch(d)
        seg = db.segments[d['segment_id']]
        if seg['status'] == 'FLAGGED':
            seg['status'] = 'UNDER_NOTICE'
            touch(seg)
    return ok_object(ser_notice(n))


@bp.post('/repair-notices/<nid>/extensions')
@require_roles('ProgramCoordinator')
def extend_notice(nid):
    vals = validate(get_body(), [
        ('extra_days', 'int', True, {'positive': True}),
        ('expected_notice_version', 'int', True, {}),
    ])
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    if n['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409, 'Notice is not ISSUED')
    if vals['expected_notice_version'] != n['version']:
        raise ApiError('ERR_STALE_NOTICE_VERSION', 412,
                       'expected_notice_version does not match current version')
    n['compliance_deadline'] = add_days(n['compliance_deadline'], vals['extra_days'])
    touch(n)
    return ok_object(ser_notice(n))


@bp.post('/repair-notices/<nid>/appeal')
@require_roles('PropertyOwner')
def appeal_notice(nid):
    vals = validate(get_body(), [('grounds', 'str', True, {})])
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    if owner_id_of_parcel(n['parcel_id']) != g.uid:
        raise ownership('Acting owner does not own this notice\'s parcel')
    if n['status'] != 'ISSUED':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409, 'Notice is not ISSUED')
    if n['appeal_status'] not in ('NONE', 'UPHELD'):
        raise ApiError('ERR_APPEAL_ALREADY_PENDING', 409,
                       'An appeal is already pending or the notice was voided')
    if db.clock > n['compliance_deadline']:
        raise ApiError('ERR_APPEAL_WINDOW_CLOSED', 422,
                       'The compliance deadline has passed')
    n['status'] = 'UNDER_APPEAL'
    n['appeal_status'] = 'PENDING'
    n['appeal_grounds'] = vals['grounds']
    touch(n)
    return ok_object(ser_notice(n))


@bp.post('/repair-notices/<nid>/appeal-decision')
@require_roles('HearingOfficer')
def decide_appeal(nid):
    vals = validate(get_body(), [
        ('decision', 'enum', True, {'values': ['UPHELD', 'REVERSED']}),
    ])
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    if n['status'] != 'UNDER_APPEAL' or n['appeal_status'] != 'PENDING':
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409,
                       'Notice has no pending appeal')
    if g.uid == n['issued_by_user_id']:
        raise segregation('Appeal decider must differ from the notice issuer')
    n['appeal_decided_by_user_id'] = g.uid
    n['appeal_decided_at'] = db.clock
    if vals['decision'] == 'UPHELD':
        n['appeal_status'] = 'UPHELD'
        n['status'] = 'ISSUED'
        n['compliance_deadline'] = add_days(db.clock, APPEAL_RESET_DAYS)
    else:  # REVERSED
        n['appeal_status'] = 'REVERSED'
        n['status'] = 'VOID'
        release_notice_defects(n)
    touch(n)
    return ok_object(ser_notice(n))


@bp.post('/repair-notices/<nid>/inspections')
@require_roles('Inspector')
def create_inspection(nid):
    vals = validate(get_body(), [
        ('result', 'enum', True, {'values': ['PASS', 'FAIL']}),
        ('notes', 'str', False, {'default': None}),
    ])
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    if n['status'] not in ('ISSUED', 'DELINQUENT'):
        raise ApiError('ERR_INVALID_NOTICE_STATE', 409,
                       'Notice is not open to inspection')
    if vals['result'] == 'PASS':
        for did in n['defect_ids']:
            d = db.defects.get(did)
            if d and d['recorded_by_inspector_id'] == g.uid:
                raise segregation('Inspector recorded a covered defect')
        for did in n['defect_ids']:
            d = db.defects.get(did)
            if d and d['status'] != 'UNDER_REPAIR':
                raise ApiError('ERR_FORESTRY_NOT_CLEARED', 409,
                               'A covered defect is still awaiting forestry')
    rec = {'id': new_id(), 'created_at': now_iso(), '_seq': next(db.seq),
           'notice_id': n['id'], 'inspector_id': g.uid,
           'result': vals['result'], 'notes': vals['notes']}
    db.inspections[rec['id']] = rec
    if vals['result'] == 'PASS':
        verify_notice_defects(n)
        n['status'] = 'COMPLIANT'
        touch(n)
        parcel = db.parcels.get(n['parcel_id'])
        if parcel:
            recompute_delinquency_flag(parcel)
    else:  # FAIL
        if n['status'] == 'ISSUED' and db.clock > n['compliance_deadline']:
            transition_notice_to_delinquent(n)
    return ok_object(ser_inspection(rec), 201)


@bp.get('/repair-notices/<nid>/inspections')
@require_roles(*ALL_ROLES)
def list_inspections(nid):
    n = db.notices.get(nid)
    if not n:
        raise not_found('notice')
    rows = [r for r in db.inspections.values() if r['notice_id'] == nid]
    if g.role == 'PropertyOwner' and owner_id_of_parcel(n['parcel_id']) != g.uid:
        rows = []
    limit, offset = parse_pagination(request.args)
    rows = sorted(rows, key=lambda e: e['_seq'])
    total = len(rows)
    page = rows[offset:offset + limit]
    return ok_list([ser_inspection(r) for r in page], total, limit, offset)
