"""Append-only ledger reads (PRD §2.6)."""
from flask import Blueprint, request

from db import store
from domain import get_required, ser_ledger
from envelope import ok, paginated_list
from security import (auth_ctx, require_roles, customer_owns,
                      customer_list_scope, ALL_ROLES)

bp = Blueprint('ledger', __name__)


@bp.route('/bank/ledger-entries/<lid>', methods=['GET'])
def get_ledger_entry(lid):
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    entry = get_required(store.ledger, lid, 'ERR_LEDGER_ENTRY_NOT_FOUND')
    customer_owns(ctx, entry['depositor_account_id'])
    return ok(ser_ledger(entry))


@bp.route('/bank/ledger-entries', methods=['GET'])
def list_ledger_entries():
    ctx = auth_ctx()
    require_roles(ctx, ALL_ROLES)
    account_id = customer_list_scope(ctx, request.args.get('depositor_account_id'))
    check_item_id = request.args.get('check_item_id')
    case_id = request.args.get('adjustment_case_id')
    fee_id = request.args.get('fee_assessment_id')
    recredit_id = request.args.get('recredit_request_id')
    entry_type = request.args.get('entry_type')
    items = [e for e in store.ledger.values()
             if (account_id is None or e['depositor_account_id'] == account_id)
             and (check_item_id is None or e['check_item_id'] == check_item_id)
             and (case_id is None or e['adjustment_case_id'] == case_id)
             and (fee_id is None or e['fee_assessment_id'] == fee_id)
             and (recredit_id is None or e['recredit_request_id'] == recredit_id)
             and (entry_type is None or e['entry_type'] == entry_type)]
    page, pagination = paginated_list(items)
    return ok([ser_ledger(e) for e in page], pagination=pagination)
