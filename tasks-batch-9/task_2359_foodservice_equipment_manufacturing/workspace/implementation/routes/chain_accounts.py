"""ChainAccount endpoints (PRD Section 3.3)."""
from flask import Blueprint

import validate
from db import db, insert, touch, ordered
from middleware import authorize, chain_scope
from response import ok, created, ok_list
from routes.helpers import find, unique_code

bp = Blueprint("chain_accounts", __name__)


def _nullable_string(payload, field):
    """Present-and-null means 'clear it'; absent means 'leave it alone'."""
    if field not in payload:
        return False, None
    value = payload[field]
    if value is None:
        return True, None
    if not isinstance(value, str) or len(value) < 1:
        validate.bad("'%s' must be a non-empty string or null" % field)
    return True, value


@bp.post("/chain-accounts")
def create_chain_account():
    authorize("ChannelManager", "PlatformAdmin")
    payload = validate.body()
    account_code = validate.string_field(payload, "account_code", min_len=1, max_len=32)
    name = validate.string_field(payload, "name", min_len=1)
    contracted_unit_volume = validate.int_field(payload, "contracted_unit_volume", minimum=0)
    _, dealer_of_record = _nullable_string(payload, "dealer_of_record")
    _, consultant_firm = _nullable_string(payload, "consultant_firm")

    unique_code(db.chain_accounts, account_code=account_code)

    account = insert(db.chain_accounts, {
        "account_code": account_code,
        "name": name,
        "contracted_unit_volume": contracted_unit_volume,
        "dealer_of_record": dealer_of_record,
        "consultant_firm": consultant_firm,
    })
    return created(account)


@bp.get("/chain-accounts")
def list_chain_accounts():
    authorize("ChannelManager", "ApplicationEngineer", "EngineeringApprover", "PlatformAdmin")
    limit, offset = validate.pagination()
    return ok_list(ordered(db.chain_accounts), limit, offset)


@bp.get("/chain-accounts/<account_id>")
def get_chain_account(account_id):
    actor = authorize("ChannelManager", "ApplicationEngineer", "EngineeringApprover",
                      "ChainAdmin", "PlatformAdmin")
    chain_scope(actor, account_id)
    account = find(db.chain_accounts, account_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    return ok(account)


@bp.patch("/chain-accounts/<account_id>")
def patch_chain_account(account_id):
    authorize("ChannelManager", "PlatformAdmin")
    payload = validate.body()
    contracted_unit_volume = validate.int_field(payload, "contracted_unit_volume",
                                                required=False, minimum=0)
    dealer_present, dealer_of_record = _nullable_string(payload, "dealer_of_record")
    consultant_present, consultant_firm = _nullable_string(payload, "consultant_firm")

    account = find(db.chain_accounts, account_id, "ERR_CHAIN_RESOURCE_NOT_FOUND")
    if contracted_unit_volume is not None:
        account["contracted_unit_volume"] = contracted_unit_volume
    if dealer_present:
        account["dealer_of_record"] = dealer_of_record
    if consultant_present:
        account["consultant_firm"] = consultant_firm
    touch(account)
    return ok(account)
