from flask import Blueprint

from db import STORE, make_rec, sort_created
from errors import ApiError, ERR_INVALID_REQUEST, ERR_NOT_FOUND, ERR_INVALID_STATE_TRANSITION
from response import ok_object, ok_list
import serializers as ser
from validate import require_roles, body, req_str, opt_str, req_enum, req_bool

bp = Blueprint("clauses", __name__)

CLAUSE_TYPES = {"TERMINATION_FOR_CONVENIENCE", "EXTENDED_PAYMENT_TERMS", "PENALTY",
                "RIGHT_OF_RETURN", "ACCEPTANCE_CLAUSE", "MOST_FAVORED_CUSTOMER"}
ALL_READ = ("RevenueAccountant", "RevenueManager", "ContractReviewer", "Controller")


@bp.post("/revrec/contracts/<contract_id>/clauses")
def create_clause(contract_id):
    require_roles("RevenueAccountant")
    c = STORE.contracts.get(contract_id)
    if c is None:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    data = body()
    clause_code = req_str(data, "clause_code")
    clause_type = req_enum(data, "clause_type", CLAUSE_TYPES)
    is_non_standard = req_bool(data, "is_non_standard")
    clause_text = opt_str(data, "clause_text")
    if c["status"] not in ("DRAFT", "CHANGES_REQUESTED"):
        raise ApiError(ERR_INVALID_STATE_TRANSITION, 409,
                       "clauses may be recorded only while the contract is DRAFT or CHANGES_REQUESTED")
    for cl in STORE.clauses.values():
        if cl["contract_id"] == contract_id and cl["clause_code"] == clause_code:
            raise ApiError(ERR_INVALID_REQUEST, 400, "clause_code must be unique within its contract")
    rec = make_rec(STORE.clauses, {
        "contract_id": contract_id,
        "clause_code": clause_code,
        "clause_type": clause_type,
        "is_non_standard": is_non_standard,
        "clause_text": clause_text,
        "status": "PENDING_REVIEW" if is_non_standard else "APPROVED",
    })
    return ok_object(ser.clause(rec), 201)


@bp.get("/revrec/contracts/<contract_id>/clauses")
def list_clauses(contract_id):
    require_roles(*ALL_READ)
    if contract_id not in STORE.contracts:
        raise ApiError(ERR_NOT_FOUND, 404, "contract id does not identify an existing contract")
    items = sort_created([cl for cl in STORE.clauses.values() if cl["contract_id"] == contract_id])
    return ok_list([ser.clause(cl) for cl in items], len(items) or 1, 0, len(items))
