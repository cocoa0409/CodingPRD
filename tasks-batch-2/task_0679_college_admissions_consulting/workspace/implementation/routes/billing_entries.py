from flask import Blueprint, request

from db import store
from middleware import authenticate, require_roles
from common import (
    get_json_body, require_string, require_enum, require_int, opt_int, opt_string,
    get_or_404, parse_pagination, paginate,
)
from response import success, success_list
from errors import (
    err, ERR_FORBIDDEN, ERR_REFERENCE_NOT_FOUND, ERR_INVALID_REQUEST, ERR_INVALID_STATE,
)
from services.billing import append_billing_entry, serialize_billing_entry

bp = Blueprint("billing_entries", __name__)


@bp.route("/billing-entries", methods=["POST"])
def create_billing_entry():
    caller = authenticate()
    require_roles(caller, {"Counselor"})
    body = get_json_body()
    contract_id = require_string(body, "contract_id")
    entry_type = require_enum(body, "entry_type", {"CHARGE", "CREDIT"})
    source_kind = require_enum(body, "source_kind", {"TASK", "APPOINTMENT", "ESSAY", "MANUAL"})
    amount_cents = require_int(body, "amount_cents")
    if amount_cents <= 0:
        raise err(ERR_INVALID_REQUEST, "amount_cents must be > 0")
    source_id = body.get("source_id", None)
    if source_id is not None and not isinstance(source_id, str):
        raise err(ERR_INVALID_REQUEST, "source_id must be a string or null")
    minutes = opt_int(body, "minutes", 0)
    if minutes < 0:
        raise err(ERR_INVALID_REQUEST, "minutes must be >= 0")
    memo = opt_string(body, "memo", "")

    with store.lock:
        contract = store.contracts.get(contract_id)
        if contract is None:
            raise err(ERR_REFERENCE_NOT_FOUND, "contract_id does not reference an existing contract")
        if contract.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this contract")
        if contract.get("status") != "ACTIVE":
            raise err(ERR_INVALID_STATE, "Contract is not ACTIVE")

        entry = append_billing_entry(
            contract=contract,
            entry_type=entry_type,
            source_kind=source_kind,
            amount_cents=amount_cents,
            source_id=source_id,
            minutes=minutes,
            memo=memo,
            recompute=True,
        )
        return success(serialize_billing_entry(entry), 201)


@bp.route("/billing-entries/<entry_id>", methods=["GET"])
def get_billing_entry(entry_id):
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    with store.lock:
        e = get_or_404(store.billing_entries, entry_id)
        contract = store.contracts.get(e.get("contract_id"))
        _assert_access(caller, contract)
        return success(serialize_billing_entry(e))


@bp.route("/billing-entries", methods=["GET"])
def list_billing_entries():
    caller = authenticate()
    require_roles(caller, {"Counselor", "Student"})
    limit, offset = parse_pagination()
    filt_contract = request.args.get("contract_id")
    with store.lock:
        rows = list(store.billing_entries.values())
        # scope by ownership through contract
        def visible(e):
            contract = store.contracts.get(e.get("contract_id"))
            if contract is None:
                return False
            if caller.is_counselor:
                return contract.get("counselor_id") == caller.user_id
            if caller.is_student:
                return contract.get("student_id") == caller.user_id
            return False
        rows = [r for r in rows if visible(r)]
        if filt_contract is not None:
            rows = [r for r in rows if r.get("contract_id") == filt_contract]
        page, total = paginate(rows, limit, offset)
        return success_list([serialize_billing_entry(r) for r in page], limit, offset, total)


def _assert_access(caller, contract):
    if contract is None:
        raise err(ERR_FORBIDDEN, "Not permitted")
    if caller.is_counselor:
        if contract.get("counselor_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Counselor does not own this entry")
    elif caller.is_student:
        if contract.get("student_id") != caller.user_id:
            raise err(ERR_FORBIDDEN, "Student does not own this entry")
