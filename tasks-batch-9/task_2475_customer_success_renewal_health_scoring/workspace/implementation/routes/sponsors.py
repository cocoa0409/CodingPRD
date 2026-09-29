"""Sponsor contacts: E18-E21."""
from flask import Blueprint

import db as store
import middleware as mw
import response as resp
from db import base_row, db, mark_fresh, touch
from services import derive, serialize
from services.lookup import account as get_account
from services.lookup import sponsor_contact as get_sponsor

bp = Blueprint('sponsors', __name__)

SENIORITIES = ('CXO', 'VP', 'DIRECTOR', 'MANAGER')
SPONSOR_STATUSES = ('ACTIVE', 'DEPARTED')


@bp.route('/accounts/<account_id>/sponsor-contacts', methods=['POST'])
def create_sponsor(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    account = get_account(account_id)
    data = mw.body()
    full_name = mw.as_string(data, 'full_name')
    seniority = mw.as_enum(data, 'seniority', SENIORITIES)
    is_economic_buyer = mw.as_bool(data, 'is_economic_buyer')

    row = base_row()
    row.update({
        'account_id': account['id'],
        'full_name': full_name,
        'seniority': seniority,
        'is_economic_buyer': is_economic_buyer,
        'status': 'ACTIVE',
    })
    db.sponsor_contacts[row['id']] = row
    mark_fresh(row)

    derive.recompute_exec_engagement_score(account)
    derive.recompute_health_scores(account)
    derive.derive_coverage_posture(account)
    return resp.entity(serialize.sponsor_contact, row, 201)


@bp.route('/sponsor-contacts/<sponsor_id>', methods=['GET'])
def read_sponsor(sponsor_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    sponsor = get_sponsor(sponsor_id)
    return resp.entity(serialize.sponsor_contact, sponsor, 200)


@bp.route('/accounts/<account_id>/sponsor-contacts', methods=['GET'])
def list_sponsors(account_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin', 'CsExecutive'))
    account = get_account(account_id)
    limit, offset = mw.pagination()
    status = mw.query_enum('status', SPONSOR_STATUSES)
    rows = store.account_sponsors(account['id'])
    if status is not None:
        rows = [r for r in rows if r['status'] == status]
    return resp.collection(serialize.sponsor_contact, rows, limit, offset)


@bp.route('/sponsor-contacts/<sponsor_id>', methods=['PATCH'])
def patch_sponsor(sponsor_id):
    mw.authenticate(('CsmUser', 'CsOpsAdmin'))
    sponsor = get_sponsor(sponsor_id)
    data = mw.body()
    status = mw.as_enum(data, 'status', SPONSOR_STATUSES, required=False)
    seniority = mw.as_enum(data, 'seniority', SENIORITIES, required=False)
    is_economic_buyer = mw.as_bool(data, 'is_economic_buyer', required=False)

    touch(sponsor)
    if status is not None:
        sponsor['status'] = status
    if seniority is not None:
        sponsor['seniority'] = seniority
    if is_economic_buyer is not None:
        sponsor['is_economic_buyer'] = is_economic_buyer

    account = db.accounts.get(sponsor['account_id'])
    if account is not None:
        derive.recompute_exec_engagement_score(account)
        derive.recompute_health_scores(account)
        derive.recompute_renewal_likelihood(account)
        derive.derive_coverage_posture(account)
    return resp.entity(serialize.sponsor_contact, sponsor, 200)
