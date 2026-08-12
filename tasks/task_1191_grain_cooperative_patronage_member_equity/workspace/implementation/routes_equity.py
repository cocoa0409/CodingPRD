"""Routes: allocations, certificates, revolvement cycles, redemption requests."""
from datetime import timedelta

from flask import Blueprint, request

from common import (db, base_fields, touch, public, success, paginate, authn, body,
                    require, as_int, as_str, err, now, iso, parse_dt,
                    require_own_member, APPEAL_WINDOW_DAYS)
from services import (EQUITY_CLASSES, REQUEST_KINDS, KIND_TO_RESOLUTION,
                      recompute_member_equity, revoke_certificate,
                      check_resolution_ref, appointment_conflicts,
                      find_cycle_for_request, run_disburse, check_request_actor,
                      is_executor_of)

bp = Blueprint('equity', __name__)


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        err('ERR_NOT_FOUND', 'Member not found')
    return m


def _get_fy_or_404(fy_id):
    fy = db.fiscal_years.get(fy_id)
    if fy is None:
        err('ERR_NOT_FOUND', 'Fiscal year not found')
    return fy


# ---------------------------------------------------------------- allocations
@bp.get('/coop/allocations/<alloc_id>')
def get_allocation(alloc_id):
    authn(['CoopAccountant', 'CoopTreasurer', 'BoardSecretary'])
    a = db.allocations.get(alloc_id)
    if a is None:
        err('ERR_NOT_FOUND', 'Allocation not found')
    return success(public(a))


@bp.get('/coop/fiscal_years/<fy_id>/allocations')
def list_year_allocations(fy_id):
    authn(['CoopAccountant', 'CoopTreasurer', 'BoardSecretary', 'ExternalAuditor'])
    _get_fy_or_404(fy_id)
    items = [a for a in db.allocations.values() if a['fiscal_year_id'] == fy_id]
    status = request.args.get('status')
    variant = request.args.get('variant')
    if status is not None:
        items = [a for a in items if a['status'] == status]
    if variant is not None:
        items = [a for a in items if a['variant'] == variant]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/allocations')
def list_allocations():
    authn(['CoopAccountant', 'CoopTreasurer', 'BoardSecretary'])
    items = list(db.allocations.values())
    member_id = request.args.get('member_id')
    fy_id = request.args.get('fiscal_year_id')
    status = request.args.get('status')
    variant = request.args.get('variant')
    if member_id is not None:
        items = [a for a in items if a['member_id'] == member_id]
    if fy_id is not None:
        items = [a for a in items if a['fiscal_year_id'] == fy_id]
    if status is not None:
        items = [a for a in items if a['status'] == status]
    if variant is not None:
        items = [a for a in items if a['variant'] == variant]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/allocations/<alloc_id>/reverse')
def reverse_allocation(alloc_id):
    authn(['CoopAccountant'])
    a = db.allocations.get(alloc_id)
    if a is None:
        err('ERR_NOT_FOUND', 'Allocation not found')
    data = body()
    require(data, 'reason')
    as_str(data, 'reason')
    if a['status'] != 'PROVISIONAL':
        err('ERR_INVALID_STATE', 'Only a PROVISIONAL allocation may be reversed')
    fy = db.fiscal_years.get(a['fiscal_year_id'])
    if fy is not None and fy['status'] == 'CLOSED_FINAL':
        err('ERR_INVALID_STATE', 'Allocation in a CLOSED_FINAL year cannot be reversed')
    a['status'] = 'REVERSED'
    touch(a)
    for c in db.certificates.values():
        if c['allocation_id'] == alloc_id and c['status'] not in ('REVOKED',):
            revoke_certificate(c)
    recompute_member_equity(a['member_id'])
    return success(public(a))


# ---------------------------------------------------------------- certificates
@bp.get('/coop/certificates/<cert_id>')
def get_certificate(cert_id):
    role, uid = authn(['CoopTreasurer', 'CoopAccountant', 'BoardSecretary', 'Member'])
    c = db.certificates.get(cert_id)
    if c is None:
        err('ERR_NOT_FOUND', 'Certificate not found')
    require_own_member(role, uid, c['member_id'])
    return success(public(c))


@bp.get('/coop/members/<member_id>/certificates')
def list_member_certificates(member_id):
    role, uid = authn(['CoopTreasurer', 'CoopAccountant', 'BoardSecretary',
                       'CoopRegistrar', 'Member'])
    _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    items = [c for c in db.certificates.values() if c['member_id'] == member_id]
    status = request.args.get('status')
    equity_class = request.args.get('equity_class')
    if status is not None:
        items = [c for c in items if c['status'] == status]
    if equity_class is not None:
        items = [c for c in items if c['equity_class'] == equity_class]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/certificates')
def list_certificates():
    authn(['CoopTreasurer', 'CoopAccountant', 'BoardSecretary', 'CoopRegistrar'])
    items = list(db.certificates.values())
    for param in ('member_id', 'fiscal_year_id', 'allocation_id', 'revolvement_cycle_id',
                  'replaces_certificate_id', 'status', 'equity_class'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


# ---------------------------------------------------------------- revolvement cycles
@bp.post('/coop/revolvement_cycles')
def create_cycle():
    authn(['BoardSecretary'])
    data = body()
    require(data, 'cycle_code', 'equity_class', 'target_year_offset', 'window_start',
            'window_end', 'budget_cap_cents', 'board_resolution_id')
    cycle_code = as_str(data, 'cycle_code')
    equity_class = as_str(data, 'equity_class')
    if equity_class not in EQUITY_CLASSES:
        err('ERR_INVALID_REQUEST', 'equity_class must be QUALIFIED or NONQUALIFIED')
    target_offset = as_int(data, 'target_year_offset')
    window_start = None
    window_end = None
    from common import as_dt
    window_start = as_dt(data, 'window_start')
    window_end = as_dt(data, 'window_end')
    budget_cap = as_int(data, 'budget_cap_cents')
    resolution_id = as_str(data, 'board_resolution_id')
    cyc = base_fields()
    cyc.update({
        'cycle_code': cycle_code,
        'equity_class': equity_class,
        'target_year_offset': target_offset,
        'window_start': iso(window_start),
        'window_end': iso(window_end),
        'status': 'PLANNED',
        'budget_cap_cents': budget_cap,
        'redeemed_cents': 0,
        'board_resolution_id': resolution_id,
    })
    db.cycles[cyc['id']] = cyc
    return success(public(cyc), 201)


def _get_cycle_or_404(cycle_id):
    cyc = db.cycles.get(cycle_id)
    if cyc is None:
        err('ERR_NOT_FOUND', 'Revolvement cycle not found')
    return cyc


@bp.get('/coop/revolvement_cycles/<cycle_id>')
def get_cycle(cycle_id):
    authn(['BoardSecretary', 'CoopTreasurer', 'CoopAccountant'])
    return success(public(_get_cycle_or_404(cycle_id)))


@bp.get('/coop/revolvement_cycles')
def list_cycles():
    authn(['BoardSecretary', 'CoopTreasurer', 'CoopAccountant'])
    items = list(db.cycles.values())
    for param in ('board_resolution_id', 'equity_class', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/revolvement_cycles/<cycle_id>/open')
def open_cycle(cycle_id):
    from services import has_passed_resolution, gregorian_years
    authn(['BoardSecretary'])
    cyc = _get_cycle_or_404(cycle_id)
    if cyc['status'] != 'PLANNED':
        err('ERR_INVALID_STATE', 'Cycle must be PLANNED to open')
    if not has_passed_resolution('OPEN_REVOLVEMENT', cycle_id):
        err('ERR_INVALID_STATE',
            'A PASSED OPEN_REVOLVEMENT resolution referencing this cycle is required')
    if now() < parse_dt(cyc['window_start']):
        err('ERR_TEMPORAL_WINDOW', 'Revolvement window has not been reached')
    ws = parse_dt(cyc['window_start'])
    we = parse_dt(cyc['window_end'])
    for other in db.cycles.values():
        if (other['id'] != cycle_id and other['equity_class'] == cyc['equity_class']
                and other['status'] == 'OPEN'):
            ows = parse_dt(other['window_start'])
            owe = parse_dt(other['window_end'])
            if ws < owe and ows < we:
                err('ERR_CYCLE_OVERLAP',
                    'Another OPEN cycle for the same equity class overlaps this window')
    cyc['status'] = 'OPEN'
    touch(cyc)
    # Assign the cycle to eligible certificates.
    for cert in db.certificates.values():
        if (cert['equity_class'] == cyc['equity_class'] and cert['status'] == 'ACTIVE'
                and now() >= parse_dt(cert['issued_at']) + gregorian_years(cyc['target_year_offset'])):
            cert['revolvement_cycle_id'] = cycle_id
            touch(cert)
    return success(public(cyc))


@bp.post('/coop/revolvement_cycles/<cycle_id>/close')
def close_cycle(cycle_id):
    authn(['BoardSecretary'])
    cyc = _get_cycle_or_404(cycle_id)
    if cyc['status'] != 'OPEN':
        err('ERR_INVALID_STATE', 'Cycle must be OPEN to close')
    if not (now() >= parse_dt(cyc['window_end']) or cyc['redeemed_cents'] >= cyc['budget_cap_cents']):
        err('ERR_INVALID_STATE', 'Cycle window has not ended and budget cap not reached')
    cyc['status'] = 'CLOSED'
    touch(cyc)
    return success(public(cyc))


@bp.post('/coop/revolvement_cycles/<cycle_id>/cancel')
def cancel_cycle(cycle_id):
    authn(['BoardSecretary'])
    cyc = _get_cycle_or_404(cycle_id)
    if cyc['status'] != 'PLANNED':
        err('ERR_INVALID_STATE', 'Cycle must be PLANNED to cancel')
    cyc['status'] = 'CANCELLED'
    touch(cyc)
    return success(public(cyc))


# ---------------------------------------------------------------- redemption requests
@bp.post('/coop/redemption_requests')
def create_redemption_request():
    role, uid = authn(['Member'])
    data = body()
    require(data, 'member_id', 'kind', 'certificate_ids', 'requested_amount_cents',
            'appointment_at')
    member_id = as_str(data, 'member_id')
    kind = as_str(data, 'kind')
    if kind not in REQUEST_KINDS:
        err('ERR_INVALID_REQUEST', 'kind must be one of {0}'.format(REQUEST_KINDS))
    cert_ids = data.get('certificate_ids')
    if not isinstance(cert_ids, list) or not cert_ids:
        err('ERR_INVALID_REQUEST', 'certificate_ids must be a non-empty array')
    amount = as_int(data, 'requested_amount_cents')
    from common import as_dt
    appointment = as_dt(data, 'appointment_at')
    appeal_of = data.get('appeal_of_request_id')
    if appeal_of is not None:
        appeal_of = as_str(data, 'appeal_of_request_id')
    member = db.members.get(member_id)
    if member is None:
        err('ERR_REFERENTIAL', 'member_id does not reference an existing member')
    if uid != member_id:
        if not (member['status'] == 'DECEASED' and is_executor_of(uid, member_id)):
            err('ERR_FORBIDDEN', 'Members may only file redemption requests for themselves')
    if appointment < now():
        err('ERR_TEMPORAL_WINDOW', 'Appointment slot must not lie in the past')
    certs = []
    for cid in cert_ids:
        c = db.certificates.get(cid)
        if c is None:
            err('ERR_REFERENTIAL', 'Listed certificate does not exist')
        if c['member_id'] != member_id:
            err('ERR_CERTIFICATE_OWNERSHIP', 'Listed certificate not owned by requesting member')
        certs.append(c)
    if appeal_of is not None:
        orig = db.redemption_requests.get(appeal_of)
        if orig is None or orig['status'] != 'REJECTED' or orig['member_id'] != member_id:
            err('ERR_REFERENTIAL',
                'appeal_of_request_id must point to a REJECTED request of the same member')
    total_outstanding = sum(c['outstanding_cents'] for c in certs)
    if amount > total_outstanding:
        err('ERR_FISCAL', 'requested_amount_cents exceeds sum of outstanding certificate value')
    r = base_fields()
    r.update({
        'member_id': member_id,
        'kind': kind,
        'certificate_ids': list(cert_ids),
        'requested_amount_cents': amount,
        'status': 'PENDING',
        'appointment_at': iso(appointment),
        'appeal_of_request_id': appeal_of,
        'resolution_id': None,
        'decided_at': None,
        'cancel_reason': None,
    })
    db.redemption_requests[r['id']] = r
    return success(public(r), 201)


def _get_request_or_404(req_id):
    r = db.redemption_requests.get(req_id)
    if r is None:
        err('ERR_NOT_FOUND', 'Redemption request not found')
    return r


@bp.get('/coop/redemption_requests/<req_id>')
def get_redemption_request(req_id):
    role, uid = authn(['Member', 'CoopTreasurer', 'BoardSecretary', 'CoopRegistrar'])
    r = _get_request_or_404(req_id)
    if role == 'Member':
        check_request_actor(r, uid)
    return success(public(r))


@bp.get('/coop/members/<member_id>/redemption_requests')
def list_member_redemption_requests(member_id):
    role, uid = authn(['Member', 'CoopTreasurer', 'BoardSecretary', 'CoopRegistrar'])
    _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    items = [r for r in db.redemption_requests.values() if r['member_id'] == member_id]
    status = request.args.get('status')
    kind = request.args.get('kind')
    if status is not None:
        items = [r for r in items if r['status'] == status]
    if kind is not None:
        items = [r for r in items if r['kind'] == kind]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/redemption_requests')
def list_redemption_requests():
    authn(['CoopTreasurer', 'BoardSecretary', 'CoopRegistrar'])
    items = list(db.redemption_requests.values())
    for param in ('member_id', 'resolution_id', 'appeal_of_request_id', 'status', 'kind'):
        v = request.args.get(param)
        if v is not None:
            items = [r for r in items if r.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/redemption_requests/<req_id>/submit_for_review')
def submit_for_review(req_id):
    role, uid = authn(['Member'])
    r = _get_request_or_404(req_id)
    check_request_actor(r, uid)
    if r['status'] != 'PENDING':
        err('ERR_INVALID_STATE', 'Request must be PENDING to submit for review')
    member = db.members.get(r['member_id'])
    if member is None or member['status'] not in ('ACTIVE', 'INACTIVE', 'DECEASED'):
        err('ERR_INVALID_STATE', 'Requesting member status does not permit submission')
    if member['status'] == 'DECEASED' and not is_executor_of(uid, r['member_id']):
        err('ERR_INVALID_STATE', 'Only an estate executor may submit for a DECEASED member')
    certs = [db.certificates[cid] for cid in r['certificate_ids'] if cid in db.certificates]
    for c in certs:
        if c['member_id'] != r['member_id']:
            err('ERR_CERTIFICATE_OWNERSHIP', 'Listed certificate not owned by requesting member')
    for c in certs:
        if c['status'] == 'FROZEN':
            err('ERR_CERTIFICATE_FROZEN', 'Certificate in FROZEN status cannot be redeemed')
        if c['status'] != 'ACTIVE':
            err('ERR_INVALID_STATE', 'All listed certificates must be in ACTIVE status')
    if parse_dt(r['appointment_at']) < now():
        err('ERR_TEMPORAL_WINDOW', 'Appointment slot lies in the past')
    if appointment_conflicts(r['appointment_at'], exclude_id=r['id']):
        err('ERR_APPOINTMENT_CONFLICT', 'Office appointment slot overlaps an existing request')
    if r['requested_amount_cents'] <= 0:
        err('ERR_FISCAL', 'requested_amount_cents must be greater than zero')
    r['status'] = 'UNDER_REVIEW'
    touch(r)
    return success(public(r))


@bp.post('/coop/redemption_requests/<req_id>/decide')
def decide_redemption_request(req_id):
    authn(['BoardSecretary'])
    r = _get_request_or_404(req_id)
    data = body()
    require(data, 'decision', 'resolution_id')
    decision = as_str(data, 'decision')
    if decision not in ('APPROVE', 'REJECT'):
        err('ERR_INVALID_REQUEST', 'decision must be APPROVE or REJECT')
    resolution_id = as_str(data, 'resolution_id')
    if r['status'] != 'UNDER_REVIEW':
        err('ERR_INVALID_STATE', 'Request must be UNDER_REVIEW to decide')
    res = check_resolution_ref(resolution_id, KIND_TO_RESOLUTION[r['kind']], req_id)
    if decision == 'APPROVE':
        certs = [db.certificates[cid] for cid in r['certificate_ids'] if cid in db.certificates]
        if r['kind'] == 'CYCLE_REDEMPTION':
            cyc = find_cycle_for_request(r)
            if cyc is None or cyc['status'] != 'OPEN':
                err('ERR_INVALID_STATE', 'Parent revolvement cycle must be OPEN')
            if cyc['redeemed_cents'] + r['requested_amount_cents'] > cyc['budget_cap_cents']:
                err('ERR_CYCLE_BUDGET_EXCEEDED',
                    'Redemption would exceed the cycle budget cap')
        if r['kind'] == 'ESTATE':
            claim = None
            for c in db.estate_claims.values():
                if c['deceased_member_id'] == r['member_id'] and c['status'] in ('PROBATED', 'APPROVED'):
                    claim = c
                    break
            if claim is None:
                err('ERR_INVALID_STATE',
                    'Estate claim must be PROBATED or APPROVED to approve an ESTATE request')
            eligible_at = parse_dt(claim['filed_at']) + timedelta(days=claim['claim_window_days'])
            if now() < eligible_at:
                err('ERR_ESTATE_WINDOW_NOT_ELAPSED',
                    'Estate claim filing window has not elapsed')
        for c in certs:
            fy = db.fiscal_years.get(c['fiscal_year_id'])
            if fy is None or fy['status'] != 'CLOSED_FINAL':
                err('ERR_INVALID_STATE',
                    'Issuing fiscal year must be CLOSED_FINAL before redemption approval')
        r['status'] = 'APPROVED'
    else:
        r['status'] = 'REJECTED'
    r['resolution_id'] = res['id']
    r['decided_at'] = iso(now())
    touch(r)
    return success(public(r))


@bp.post('/coop/redemption_requests/<req_id>/appeal')
def appeal_redemption_request(req_id):
    role, uid = authn(['Member'])
    r = _get_request_or_404(req_id)
    check_request_actor(r, uid)
    if r['status'] != 'REJECTED':
        err('ERR_INVALID_STATE', 'Only a REJECTED request may be appealed')
    decided = parse_dt(r['decided_at']) if r['decided_at'] else None
    if decided is None or now() > decided + timedelta(days=APPEAL_WINDOW_DAYS):
        err('ERR_TEMPORAL_WINDOW', 'Appeal window has passed')
    r['status'] = 'APPEALED'
    touch(r)
    new_req = base_fields()
    new_req.update({
        'member_id': r['member_id'],
        'kind': r['kind'],
        'certificate_ids': list(r['certificate_ids']),
        'requested_amount_cents': r['requested_amount_cents'],
        'status': 'UNDER_REVIEW',
        'appointment_at': r['appointment_at'],
        'appeal_of_request_id': r['id'],
        'resolution_id': None,
        'decided_at': None,
        'cancel_reason': None,
    })
    db.redemption_requests[new_req['id']] = new_req
    return success(public(r))


@bp.post('/coop/redemption_requests/<req_id>/disburse')
def disburse_redemption_request(req_id):
    authn(['CoopTreasurer'])
    r = _get_request_or_404(req_id)
    data = body()
    require(data, 'expected_certificate_versions')
    expected = data.get('expected_certificate_versions')
    certs = [db.certificates[cid] for cid in r['certificate_ids'] if cid in db.certificates]
    # OCC check on every listed certificate.
    if isinstance(expected, dict):
        version_map = expected
    elif isinstance(expected, list):
        version_map = dict(zip(r['certificate_ids'], expected))
    else:
        err('ERR_INVALID_REQUEST',
            'expected_certificate_versions must be an array or object')
    for c in certs:
        exp = version_map.get(c['id'])
        if exp is None or not isinstance(exp, int) or isinstance(exp, bool):
            err('ERR_INVALID_REQUEST',
                'expected_certificate_versions must cover every listed certificate')
        if exp != c['version']:
            err('ERR_STALE_CERTIFICATE_VERSION',
                'Certificate version has advanced; re-read and retry')
    if r['status'] != 'APPROVED':
        err('ERR_INVALID_STATE', 'Request must be APPROVED to disburse')
    for c in certs:
        if c['status'] == 'FROZEN':
            err('ERR_CERTIFICATE_FROZEN', 'Certificate in FROZEN status cannot be redeemed')
    if appointment_conflicts(r['appointment_at'], exclude_id=r['id']):
        err('ERR_APPOINTMENT_CONFLICT', 'Office appointment slot overlaps an existing request')
    for c in certs:
        if c['status'] not in ('ACTIVE', 'PARTIALLY_REDEEMED'):
            err('ERR_INVALID_STATE', 'Listed certificates must be ACTIVE or PARTIALLY_REDEEMED')
        if c['redeemable_at'] is None or now() < parse_dt(c['redeemable_at']):
            err('ERR_CERTIFICATE_NOT_REDEEMABLE',
                'Certificate holding period has not elapsed')
    run_disburse(r)
    return success(public(r))


@bp.post('/coop/redemption_requests/<req_id>/cancel')
def cancel_redemption_request(req_id):
    role, uid = authn(['Member'])
    r = _get_request_or_404(req_id)
    check_request_actor(r, uid)
    if r['status'] != 'PENDING':
        err('ERR_INVALID_STATE', 'Only a PENDING request may be cancelled')
    r['status'] = 'CANCELLED'
    touch(r)
    return success(public(r))
