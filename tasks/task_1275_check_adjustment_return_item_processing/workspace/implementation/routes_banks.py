"""Clearing banks (PRD §3.1) and per-bank claim listing."""
from flask import Blueprint, request

from db import store, base_fields
from domain import get_required, ser_bank, ser_claim, body, req_string, opt_int, opt_enum
from envelope import ok, paginated_list
from errors import ApiError
from security import auth_ctx, require_roles, OPS_ROLES

bp = Blueprint('banks', __name__)


@bp.route('/bank/clearing-banks', methods=['POST'])
def create_bank():
    ctx = auth_ctx()
    require_roles(ctx, ['OperationsAdmin'])
    data = body()

    name = req_string(data, 'name')
    routing_number = req_string(data, 'routing_number')

    # Structural (priority 9): unique routing_number
    for b in store.clearing_banks.values():
        if b['routing_number'] == routing_number:
            raise ApiError('ERR_DUPLICATE_ROUTING_NUMBER', 409,
                           'routing_number already exists')

    bank = dict(base_fields())
    bank.update({
        'name': name,
        'routing_number': routing_number,
        'claim_window_business_days': opt_int(data, 'claim_window_business_days', 3),
        'warranty_window_days': opt_int(data, 'warranty_window_days', 7),
        'daily_claim_capacity': opt_int(data, 'daily_claim_capacity', 10),
        'status': opt_enum(data, 'status', ['ACTIVE', 'SUSPENDED'], 'ACTIVE'),
    })
    store.clearing_banks[bank['id']] = bank
    return ok(ser_bank(bank), status=201)


@bp.route('/bank/clearing-banks/<bid>', methods=['GET'])
def get_bank(bid):
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    bank = get_required(store.clearing_banks, bid, 'ERR_CLEARING_BANK_NOT_FOUND')
    return ok(ser_bank(bank))


@bp.route('/bank/clearing-banks/<bid>/claims', methods=['GET'])
def list_bank_claims(bid):
    ctx = auth_ctx()
    require_roles(ctx, OPS_ROLES)
    bank = get_required(store.clearing_banks, bid, 'ERR_CLEARING_BANK_NOT_FOUND')
    status = request.args.get('status')
    items = [c for c in store.claims.values()
             if c['clearing_bank_id'] == bank['id']
             and (status is None or c['status'] == status)]
    page, pagination = paginated_list(items)
    return ok([ser_claim(c) for c in page], pagination=pagination)
