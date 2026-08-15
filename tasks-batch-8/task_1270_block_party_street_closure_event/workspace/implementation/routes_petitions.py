"""Petitions and petition signatures."""
from flask import Blueprint, request

from auth import auth, own_or_403
from calc import (ensure_fresh, get_petition, get_segment, petition_threshold,
                  recompute_petition, support_metric, petition_deficient)
from envelope import ok, created, ok_list
from errors import ApiError
from store import db, entity, now, touch
from validate import body, req, as_str, opt_bool

bp = Blueprint('petitions', __name__)

PETITION_READ = ['Organizer', 'Neighbor', 'PermitOfficer', 'CityAdmin']


def _acting_organizer(uid):
    org = db.organizers.get(uid)
    if org is None:
        raise ApiError('ERR_NOT_FOUND', 'Organizer not found', 404)
    if org['standing'] == 'SUSPENDED':
        raise ApiError('ERR_ORGANIZER_SUSPENDED',
                       'Suspended organizers cannot create petitions or applications', 403)
    return org


@bp.route('/petitions', methods=['POST'])
def create_petition():
    uid, role = auth(['Organizer'])
    _acting_organizer(uid)
    b = body()
    seg = get_segment(as_str(req(b, 'segment_id'), 'segment_id'))
    required, mode = petition_threshold(seg)
    p = entity(
        segment_id=seg['id'],
        organizer_id=uid,
        required_signatures=required,
        support_mode=mode,
        valid_signature_count=0,
        distinct_household_count=0,
        status='COLLECTING',
        deficiency_note=None,
        cure_round=0,
    )
    db.petitions[p['id']] = p
    return created(p)


@bp.route('/petitions/<pid>', methods=['GET'])
def get_one_petition(pid):
    uid, role = auth(PETITION_READ)
    p = get_petition(pid)
    own_or_403(role, uid, p['organizer_id'])
    return ok(p)


@bp.route('/petitions/<pid>/signatures', methods=['POST'])
def add_signature(pid):
    auth(['Neighbor'])
    p = get_petition(pid)
    if p['status'] == 'LOCKED':
        raise ApiError('ERR_PETITION_LOCKED', 'Petition is locked', 409)
    if p['status'] != 'COLLECTING':
        raise ApiError('ERR_INVALID_STATE',
                       'Signatures are accepted only while the petition is COLLECTING', 409)
    b = body()
    ha = as_str(req(b, 'household_address'), 'household_address')
    sn = as_str(req(b, 'signer_name'), 'signer_name')
    se = as_str(req(b, 'signer_email'), 'signer_email')
    ib = opt_bool(b, 'is_business', False)
    for s in db.signatures.values():
        if (s['petition_id'] == p['id'] and s['status'] == 'ACTIVE'
                and s['household_address'] == ha and s['signer_email'] == se):
            raise ApiError('ERR_DUPLICATE_SIGNATURE',
                           'An ACTIVE signature with this household_address and signer_email already exists',
                           409)
    sig = entity(
        petition_id=p['id'],
        household_address=ha,
        signer_name=sn,
        signer_email=se,
        is_business=ib,
        status='ACTIVE',
        withdrawn_at=None,
    )
    db.signatures[sig['id']] = sig
    recompute_petition(p)
    touch(p)
    return created(sig)


@bp.route('/petitions/<pid>/signatures', methods=['GET'])
def list_signatures(pid):
    uid, role = auth(PETITION_READ)
    p = get_petition(pid)
    own_or_403(role, uid, p['organizer_id'])
    rows = [s for s in db.signatures.values() if s['petition_id'] == p['id']]
    status = request.args.get('status')
    if status is not None:
        if status not in ('ACTIVE', 'WITHDRAWN'):
            raise ApiError('ERR_INVALID_REQUEST', 'status filter must be ACTIVE or WITHDRAWN', 400)
        rows = [s for s in rows if s['status'] == status]
    return ok_list(rows)


@bp.route('/petitions/<pid>/signatures/<sid>/withdraw', methods=['POST'])
def withdraw_signature(pid, sid):
    auth(['Neighbor'])
    p = get_petition(pid)
    sig = db.signatures.get(sid)
    if sig is None or sig['petition_id'] != p['id']:
        raise ApiError('ERR_NOT_FOUND', 'PetitionSignature not found', 404)
    if sig['status'] != 'ACTIVE':
        raise ApiError('ERR_INVALID_STATE', 'Signature is not ACTIVE', 409)
    if p['status'] == 'LOCKED':
        raise ApiError('ERR_PETITION_LOCKED', 'Petition is locked', 409)
    if p['status'] not in ('COLLECTING', 'SUBMITTED', 'VERIFIED'):
        raise ApiError('ERR_INVALID_STATE',
                       'Petition state does not permit withdrawal', 409)
    sig['status'] = 'WITHDRAWN'
    sig['withdrawn_at'] = now()
    touch(sig)
    recompute_petition(p)
    touch(p)
    if p['status'] == 'VERIFIED' and support_metric(p) < p['required_signatures']:
        petition_deficient(p, 'signature withdrawal below threshold')
    return ok(sig)


@bp.route('/petitions/<pid>/submit', methods=['POST'])
def submit_petition(pid):
    uid, role = auth(['Organizer'])
    p = get_petition(pid)
    own_or_403(role, uid, p['organizer_id'])
    if p['status'] != 'COLLECTING':
        raise ApiError('ERR_INVALID_STATE', 'Petition is not COLLECTING', 409)
    if support_metric(p) < p['required_signatures']:
        raise ApiError('ERR_SIGNATURE_THRESHOLD_NOT_MET',
                       'Support metric is below required_signatures', 409)
    p['status'] = 'SUBMITTED'
    touch(p)
    return ok(p)


@bp.route('/petitions/<pid>/verify', methods=['POST'])
def verify_petition(pid):
    auth(['PermitOfficer'])
    p = get_petition(pid)
    b = body()
    decision = req(b, 'decision')
    if decision not in ('APPROVE', 'DEFICIENT'):
        raise ApiError('ERR_INVALID_REQUEST', 'decision must be APPROVE or DEFICIENT', 400)
    if p['status'] != 'SUBMITTED':
        raise ApiError('ERR_INVALID_STATE', 'Petition is not SUBMITTED', 409)
    if decision == 'APPROVE':
        if support_metric(p) < p['required_signatures']:
            raise ApiError('ERR_SIGNATURE_THRESHOLD_NOT_MET',
                           'Support metric is below required_signatures', 409)
        p['status'] = 'VERIFIED'
        touch(p)
        for a in db.applications.values():
            if a['petition_id'] == p['id'] and a['status'] == 'SUSPENDED':
                a['status'] = 'UNDER_REVIEW'
                touch(a)
    else:
        p['status'] = 'DEFICIENT'
        p['deficiency_note'] = b.get('note')
        touch(p)
    return ok(p)


@bp.route('/petitions/<pid>/cure', methods=['POST'])
def cure_petition(pid):
    uid, role = auth(['Organizer'])
    p = get_petition(pid)
    own_or_403(role, uid, p['organizer_id'])
    if p['status'] != 'DEFICIENT':
        raise ApiError('ERR_INVALID_STATE', 'Petition is not DEFICIENT', 409)
    p['status'] = 'COLLECTING'
    p['cure_round'] += 1
    touch(p)
    return ok(p)


@bp.route('/petitions/<pid>/permit-applications', methods=['GET'])
def petition_applications(pid):
    uid, role = auth(['Organizer', 'PermitOfficer', 'CityAdmin'])
    p = get_petition(pid)
    own_or_403(role, uid, p['organizer_id'])
    rows = []
    for a in db.applications.values():
        if a['petition_id'] == p['id']:
            ensure_fresh(a)
            rows.append(a)
    return ok_list(rows)
