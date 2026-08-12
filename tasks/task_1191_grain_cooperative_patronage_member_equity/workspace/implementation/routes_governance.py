"""Routes: estate claims, unclaimed equity lots, board resolutions, tax forms."""
from datetime import timedelta

from flask import Blueprint, request

from common import (db, base_fields, touch, public, success, paginate, authn, body,
                    require, as_int, as_str, err, now, iso, parse_dt,
                    require_own_member, ESTATE_CLAIM_WINDOW_DAYS)
from services import (RESOLUTION_KINDS, check_resolution_ref, subject_exists,
                      seated_delegate_ids, delegate_is_seated,
                      unfreeze_member_certificates, recompute_member_equity,
                      is_executor_of)

bp = Blueprint('governance', __name__)


def _get_member_or_404(member_id):
    m = db.members.get(member_id)
    if m is None:
        err('ERR_NOT_FOUND', 'Member not found')
    return m


# ---------------------------------------------------------------- estate claims
@bp.get('/coop/estate_claims/<claim_id>')
def get_estate_claim(claim_id):
    role, uid = authn(['CoopRegistrar', 'BoardSecretary', 'CoopTreasurer', 'Member'])
    c = db.estate_claims.get(claim_id)
    if c is None:
        err('ERR_NOT_FOUND', 'Estate claim not found')
    if role == 'Member' and uid not in (c['deceased_member_id'], c['executor_member_id']):
        err('ERR_FORBIDDEN', 'Members may only view claims in their own capacity')
    return success(public(c))


@bp.get('/coop/members/<member_id>/estate_claims')
def list_member_estate_claims(member_id):
    role, uid = authn(['CoopRegistrar', 'BoardSecretary', 'CoopTreasurer', 'Member'])
    _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    items = [c for c in db.estate_claims.values()
             if c['deceased_member_id'] == member_id or c['executor_member_id'] == member_id]
    status = request.args.get('status')
    if status is not None:
        items = [c for c in items if c['status'] == status]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/estate_claims')
def list_estate_claims():
    authn(['CoopRegistrar', 'BoardSecretary', 'CoopTreasurer'])
    items = list(db.estate_claims.values())
    for param in ('deceased_member_id', 'executor_member_id', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [c for c in items if c.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/estate_claims/<claim_id>/record_probate')
def record_probate(claim_id):
    authn(['CoopRegistrar'])
    c = db.estate_claims.get(claim_id)
    if c is None:
        err('ERR_NOT_FOUND', 'Estate claim not found')
    data = body()
    require(data, 'probate_completed_at')
    from common import as_dt
    probate_at = as_dt(data, 'probate_completed_at')
    if c['status'] != 'FILED':
        err('ERR_INVALID_STATE', 'Claim must be FILED to record probate')
    eligible_at = parse_dt(c['filed_at']) + timedelta(days=c['claim_window_days'])
    if now() < eligible_at:
        err('ERR_COMPLIANCE_GATE',
            'Estate claim window must elapse before probate is recorded')
    c['probate_completed_at'] = iso(probate_at)
    c['status'] = 'PROBATED'
    touch(c)
    return success(public(c))


@bp.post('/coop/estate_claims/<claim_id>/decide')
def decide_estate_claim(claim_id):
    authn(['BoardSecretary'])
    c = db.estate_claims.get(claim_id)
    if c is None:
        err('ERR_NOT_FOUND', 'Estate claim not found')
    data = body()
    require(data, 'decision', 'resolution_id')
    decision = as_str(data, 'decision')
    if decision not in ('APPROVE', 'DENY'):
        err('ERR_INVALID_REQUEST', 'decision must be APPROVE or DENY')
    resolution_id = as_str(data, 'resolution_id')
    if c['status'] != 'PROBATED':
        err('ERR_INVALID_STATE', 'Claim must be PROBATED to decide')
    if decision == 'APPROVE':
        check_resolution_ref(resolution_id, 'APPROVE_ESTATE', claim_id)
        c['status'] = 'APPROVED'
        touch(c)
        # Release the decedent's FROZEN certificates back to ACTIVE.
        unfreeze_member_certificates(c['deceased_member_id'])
        recompute_member_equity(c['deceased_member_id'])
    else:
        res = db.resolutions.get(resolution_id)
        if res is None:
            err('ERR_REFERENTIAL', 'Referenced resolution does not exist')
        c['status'] = 'DENIED'
        touch(c)
    return success(public(c))


# ---------------------------------------------------------------- unclaimed lots
@bp.post('/coop/unclaimed_lots')
def create_unclaimed_lot():
    authn(['CoopRegistrar'])
    data = body()
    require(data, 'certificate_id', 'last_known_member_id', 'state_code')
    cert_id = as_str(data, 'certificate_id')
    member_id = as_str(data, 'last_known_member_id')
    state_code = as_str(data, 'state_code')
    dormancy_years = data.get('dormancy_years', 5)
    if isinstance(dormancy_years, bool) or not isinstance(dormancy_years, int):
        err('ERR_INVALID_REQUEST', 'dormancy_years must be an integer')
    if cert_id not in db.certificates:
        err('ERR_REFERENTIAL', 'certificate_id does not reference an existing certificate')
    if member_id not in db.members:
        err('ERR_REFERENTIAL', 'last_known_member_id does not reference an existing member')
    from services import gregorian_years
    start = now()
    lot = base_fields()
    lot.update({
        'certificate_id': cert_id,
        'last_known_member_id': member_id,
        'dormancy_started_at': iso(start),
        'escheat_eligible_at': iso(start + gregorian_years(dormancy_years)),
        'dormancy_years': dormancy_years,
        'state_code': state_code,
        'status': 'DORMANT',
    })
    db.lots[lot['id']] = lot
    return success(public(lot), 201)


def _get_lot_or_404(lot_id):
    lot = db.lots.get(lot_id)
    if lot is None:
        err('ERR_NOT_FOUND', 'Unclaimed equity lot not found')
    return lot


@bp.get('/coop/unclaimed_lots/<lot_id>')
def get_unclaimed_lot(lot_id):
    role, uid = authn(['CoopRegistrar', 'CoopTreasurer', 'BoardSecretary', 'Member'])
    lot = _get_lot_or_404(lot_id)
    if role == 'Member' and uid != lot['last_known_member_id']:
        err('ERR_FORBIDDEN', 'Members may only view their own unclaimed lots')
    return success(public(lot))


@bp.get('/coop/unclaimed_lots')
def list_unclaimed_lots():
    authn(['CoopRegistrar', 'CoopTreasurer', 'BoardSecretary'])
    items = list(db.lots.values())
    for param in ('certificate_id', 'last_known_member_id', 'status', 'state_code'):
        v = request.args.get(param)
        if v is not None:
            items = [l for l in items if l.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/unclaimed_lots/<lot_id>/notify')
def notify_unclaimed_lot(lot_id):
    authn(['CoopRegistrar'])
    lot = _get_lot_or_404(lot_id)
    if lot['status'] != 'DORMANT':
        err('ERR_INVALID_STATE', 'Lot must be DORMANT to notify')
    lot['status'] = 'NOTIFIED'
    touch(lot)
    return success(public(lot))


@bp.post('/coop/unclaimed_lots/<lot_id>/escheat')
def escheat_unclaimed_lot(lot_id):
    authn(['CoopTreasurer'])
    lot = _get_lot_or_404(lot_id)
    data = body()
    require(data, 'resolution_id')
    resolution_id = as_str(data, 'resolution_id')
    if lot['status'] != 'ESCHEAT_PENDING':
        err('ERR_INVALID_STATE', 'Lot must be ESCHEAT_PENDING to escheat')
    check_resolution_ref(resolution_id, 'AUTHORIZE_ESCHEAT', lot_id)
    lot['status'] = 'ESCHEATED'
    touch(lot)
    cert = db.certificates.get(lot['certificate_id'])
    if cert is not None and cert['status'] not in ('REVOKED', 'ESCHEATED', 'REDEEMED'):
        if cert['outstanding_cents'] > 0:
            db.disbursements.append({
                'certificate_id': cert['id'],
                'member_id': cert['member_id'],
                'fiscal_year_id': cert['fiscal_year_id'],
                'equity_class': cert['equity_class'],
                'amount_cents': cert['outstanding_cents'],
                'at': iso(now()),
            })
        cert['outstanding_cents'] = 0
        cert['status'] = 'ESCHEATED'
        touch(cert)
        recompute_member_equity(cert['member_id'])
    return success(public(lot))


@bp.post('/coop/unclaimed_lots/<lot_id>/recover')
def recover_unclaimed_lot(lot_id):
    role, uid = authn(['Member'])
    lot = _get_lot_or_404(lot_id)
    if lot['status'] != 'NOTIFIED':
        err('ERR_INVALID_STATE', 'Lot must be NOTIFIED to recover')
    if uid != lot['last_known_member_id']:
        err('ERR_FORBIDDEN', 'Only the member of record may recover the lot')
    lot['status'] = 'RECOVERED'
    touch(lot)
    return success(public(lot))


# ---------------------------------------------------------------- board resolutions
@bp.post('/coop/board_resolutions')
def create_resolution():
    authn(['BoardSecretary'])
    data = body()
    require(data, 'resolution_code', 'kind', 'subject_ref_id', 'quorum_required',
            'voting_opens_at', 'voting_closes_at')
    resolution_code = as_str(data, 'resolution_code')
    kind = as_str(data, 'kind')
    if kind not in RESOLUTION_KINDS:
        err('ERR_INVALID_REQUEST', 'kind must be one of {0}'.format(RESOLUTION_KINDS))
    subject_ref_id = as_str(data, 'subject_ref_id')
    quorum = as_int(data, 'quorum_required')
    from common import as_dt
    opens = as_dt(data, 'voting_opens_at')
    closes = as_dt(data, 'voting_closes_at')
    if any(r['resolution_code'] == resolution_code for r in db.resolutions.values()):
        err('ERR_CONSTRAINT_VIOLATION', 'resolution_code must be unique')
    if not subject_exists(subject_ref_id):
        err('ERR_REFERENTIAL', 'subject_ref_id does not reference an existing entity')
    r = base_fields()
    r.update({
        'resolution_code': resolution_code,
        'kind': kind,
        'subject_ref_id': subject_ref_id,
        'status': 'PROPOSED',
        'votes_for': 0,
        'votes_against': 0,
        'quorum_required': quorum,
        'voting_opens_at': iso(opens),
        'voting_closes_at': iso(closes),
        '_voters': [],
    })
    db.resolutions[r['id']] = r
    return success(public(r), 201)


def _get_resolution_or_404(res_id):
    r = db.resolutions.get(res_id)
    if r is None:
        err('ERR_NOT_FOUND', 'Board resolution not found')
    return r


@bp.get('/coop/board_resolutions/<res_id>')
def get_resolution(res_id):
    authn(['BoardSecretary', 'CoopRegistrar', 'CoopTreasurer', 'CoopAccountant'])
    return success(public(_get_resolution_or_404(res_id)))


@bp.post('/coop/board_resolutions/<res_id>/open_voting')
def open_voting(res_id):
    authn(['BoardSecretary'])
    r = _get_resolution_or_404(res_id)
    if r['status'] != 'PROPOSED':
        err('ERR_INVALID_STATE', 'Resolution must be PROPOSED to open voting')
    if now() < parse_dt(r['voting_opens_at']):
        err('ERR_TEMPORAL_WINDOW', 'Voting window has not opened')
    r['status'] = 'VOTING'
    touch(r)
    return success(public(r))


@bp.post('/coop/board_resolutions/<res_id>/record_vote')
def record_vote(res_id):
    authn(['BoardSecretary'])
    r = _get_resolution_or_404(res_id)
    data = body()
    require(data, 'delegate_id', 'vote')
    delegate_id = as_str(data, 'delegate_id')
    vote = as_str(data, 'vote').upper()
    if vote not in ('FOR', 'AGAINST'):
        err('ERR_INVALID_REQUEST', 'vote must be FOR or AGAINST')
    if r['status'] != 'VOTING':
        err('ERR_INVALID_STATE', 'Resolution must be VOTING to record votes')
    delegate = db.delegates.get(delegate_id)
    if delegate is None:
        err('ERR_REFERENTIAL', 'delegate_id does not reference an existing delegate')
    if not delegate_is_seated(delegate):
        err('ERR_INVALID_STATE', 'Only seated delegates may vote')
    if vote == 'FOR':
        r['votes_for'] += 1
    else:
        r['votes_against'] += 1
    if delegate_id not in r['_voters']:
        r['_voters'].append(delegate_id)
    touch(r)
    # Tally when the window has closed or every seated delegate has voted.
    seated = set(seated_delegate_ids())
    all_voted = seated.issubset(set(r['_voters'])) and len(seated) > 0
    if now() >= parse_dt(r['voting_closes_at']) or all_voted:
        total = r['votes_for'] + r['votes_against']
        if total < r['quorum_required']:
            err('ERR_QUORUM_NOT_MET', 'Quorum not met; resolution cannot be tallied')
        r['status'] = 'PASSED' if r['votes_for'] > r['votes_against'] else 'REJECTED'
        touch(r)
    return success(public(r))


@bp.post('/coop/board_resolutions/<res_id>/table')
def table_resolution(res_id):
    authn(['BoardSecretary'])
    r = _get_resolution_or_404(res_id)
    if r['status'] != 'PROPOSED':
        err('ERR_INVALID_STATE', 'Resolution must be PROPOSED to table')
    r['status'] = 'TABLED'
    touch(r)
    return success(public(r))


# ---------------------------------------------------------------- patron tax forms
@bp.get('/coop/tax_forms/<form_id>')
def get_tax_form(form_id):
    role, uid = authn(['CoopAccountant', 'CoopTreasurer', 'Member'])
    f = db.tax_forms.get(form_id)
    if f is None:
        err('ERR_NOT_FOUND', 'Tax form not found')
    require_own_member(role, uid, f['member_id'])
    return success(public(f))


@bp.get('/coop/members/<member_id>/tax_forms')
def list_member_tax_forms(member_id):
    role, uid = authn(['CoopAccountant', 'CoopTreasurer', 'Member'])
    _get_member_or_404(member_id)
    require_own_member(role, uid, member_id)
    items = [f for f in db.tax_forms.values() if f['member_id'] == member_id]
    fy_id = request.args.get('fiscal_year_id')
    form_type = request.args.get('form_type')
    if fy_id is not None:
        items = [f for f in items if f['fiscal_year_id'] == fy_id]
    if form_type is not None:
        items = [f for f in items if f['form_type'] == form_type]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.get('/coop/tax_forms')
def list_tax_forms():
    authn(['CoopAccountant', 'CoopTreasurer', 'BoardSecretary'])
    items = list(db.tax_forms.values())
    for param in ('member_id', 'fiscal_year_id', 'corrects_form_id', 'form_type', 'status'):
        v = request.args.get(param)
        if v is not None:
            items = [f for f in items if f.get(param) == v]
    page_items, page = paginate(items)
    return success(page_items, 200, page)


@bp.post('/coop/tax_forms/<form_id>/void')
def void_tax_form(form_id):
    authn(['CoopAccountant'])
    f = db.tax_forms.get(form_id)
    if f is None:
        err('ERR_NOT_FOUND', 'Tax form not found')
    data = body()
    require(data, 'reason')
    as_str(data, 'reason')
    if f['status'] != 'ISSUED':
        err('ERR_INVALID_STATE', 'Only an ISSUED tax form may be voided')
    f['status'] = 'VOID'
    touch(f)
    return success(public(f))
