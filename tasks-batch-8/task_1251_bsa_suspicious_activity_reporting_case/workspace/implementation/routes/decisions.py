"""Subject account decisioning (EXIT / RESTRICT / RETAIN) and the exit cascade."""
from flask import Blueprint

import db
import response
from errors import ApiError
from middleware import ALL_ROLES, authn, authz, get_body, pagination_params
from services.core import maybe_exit_customer, recompute_customer_risk
from util import (ACCOUNT_DECISIONS, base_entity, req_enum, req_str, serialize,
                  sort_created, touch)

bp = Blueprint("decisions", __name__)


def _get(store, rid, label):
    entity = store.get(rid)
    if entity is None:
        raise ApiError("ERR_NOT_FOUND", f"{label} '{rid}' does not exist", 404)
    return entity


@bp.route("/accounts/<rid>/exit-decisions", methods=["POST"])
def propose_decision(rid):
    body = get_body()
    decision = req_enum(body, "decision", ACCOUNT_DECISIONS)
    rationale = req_str(body, "rationale")
    user_id, role = authn()
    authz(role, ["BSAAnalyst"])
    account = _get(db.accounts, rid, "Account")
    record = base_entity()
    record.update({
        "account_id": account["id"],
        "decision": decision,
        "rationale": rationale,
        "status": "PROPOSED",
        "proposed_by_analyst_id": user_id,
        "approved_by_analyst_id": None,
        "executed_at": None,
    })
    db.decisions[record["id"]] = record
    return response.success(serialize(record), status=201)


@bp.route("/accounts/<rid>/exit-decisions", methods=["GET"])
def list_account_decisions(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    account = _get(db.accounts, rid, "Account")
    limit, offset = pagination_params()
    items = sort_created([d for d in db.decisions.values()
                          if d["account_id"] == account["id"]])
    return response.paginated([serialize(d) for d in items], limit, offset)


@bp.route("/account-decisions/<rid>", methods=["GET"])
def get_decision(rid):
    _, role = authn()
    authz(role, ALL_ROLES)
    record = _get(db.decisions, rid, "AccountDecision")
    return response.success(serialize(record), status=200)


@bp.route("/account-decisions/<rid>/approve", methods=["POST"])
def approve_decision(rid):
    user_id, role = authn()
    authz(role, ["BSAManager"])
    record = _get(db.decisions, rid, "AccountDecision")
    if user_id == record["proposed_by_analyst_id"]:
        raise ApiError("ERR_SEGREGATION_OF_DUTIES",
                       "Approver must differ from the proposing analyst", 403)
    if record["status"] != "PROPOSED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Decision in status {record['status']} cannot be approved", 409)
    record["status"] = "APPROVED"
    record["approved_by_analyst_id"] = user_id
    touch(record)
    return response.success(serialize(record), status=200)


@bp.route("/account-decisions/<rid>/execute", methods=["POST"])
def execute_decision(rid):
    _, role = authn()
    authz(role, ["BSAManager"])
    record = _get(db.decisions, rid, "AccountDecision")
    if record["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Decision in status {record['status']} cannot be executed", 409)
    account = _get(db.accounts, record["account_id"], "Account")
    if account["status"] not in {"OPEN", "RESTRICTED"}:
        raise ApiError("ERR_ACCOUNT_NOT_OPEN",
                       "Decision execution requires the account to be OPEN or "
                       "RESTRICTED", 409)
    record["status"] = "EXECUTED"
    record["executed_at"] = db.now()
    touch(record)

    customer = db.customers.get(account["customer_id"])
    if record["decision"] == "EXIT":
        account["status"] = "EXITED"
        touch(account)
        if customer is not None:
            maybe_exit_customer(customer)  # fires alert/share cascades on exit
    elif record["decision"] == "RESTRICT":
        if account["status"] == "OPEN":
            account["status"] = "RESTRICTED"
            account["restriction_reason"] = "DECISION"
            touch(account)
    elif record["decision"] == "RETAIN":
        if account["status"] == "RESTRICTED":
            account["status"] = "OPEN"
            account["restriction_reason"] = None
            touch(account)
    if customer is not None:
        recompute_customer_risk(customer)
    return response.success(serialize(record), status=200)


@bp.route("/account-decisions/<rid>/reverse", methods=["POST"])
def reverse_decision(rid):
    body = get_body()
    req_str(body, "rationale")
    _, role = authn()
    authz(role, ["BSAManager"])
    record = _get(db.decisions, rid, "AccountDecision")
    if record["status"] != "APPROVED":
        raise ApiError("ERR_INVALID_STATE",
                       f"Decision in status {record['status']} cannot be reversed", 409)
    record["status"] = "REVERSED"
    touch(record)
    return response.success(serialize(record), status=200)
