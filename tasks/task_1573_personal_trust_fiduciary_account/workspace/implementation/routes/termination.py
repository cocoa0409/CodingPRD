"""TerminationCase gauntlet: reserve, clearance, approve, distribute, close."""

from flask import Blueprint, request

import clock
import db
import serialize
from errors import (ApiError, ERR_INVALID_STATE, ERR_SEGREGATION_OF_DUTIES,
                    ERR_INSUFFICIENT_AVAILABLE_BALANCE, ERR_UNFILED_TAX_RETURNS,
                    ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED)
from middleware import authenticate, require_role
from response import ok, ok_list
from serialize import termination_case_json
from services import workflow, calc
from services.workflow import find_or_404
from validation import get_body, validate, parse_pagination

bp = Blueprint("termination", __name__)

READ_ROLES = {"TrustOfficer", "TrustExecutive", "TrustOperationsOfficer",
              "TaxSpecialist"}


@bp.route("/trusts/termination-cases", methods=["GET"])
def list_cases():
    _, role = authenticate()
    limit, offset = parse_pagination()
    require_role(role, READ_ROLES)
    filters = []
    for param in ("trust_id", "status"):
        val = request.args.get(param)
        if val is not None:
            filters.append((param, val))
    items, total = workflow.list_page(db.termination_cases, filters,
                                      termination_case_json, limit, offset)
    return ok_list(items, limit, offset, total)


@bp.route("/trusts/termination-cases/<cid>", methods=["GET"])
def get_case(cid):
    _, role = authenticate()
    require_role(role, READ_ROLES)
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    return ok(termination_case_json(c))


@bp.route("/trusts/termination-cases/<cid>/reserve-liabilities", methods=["POST"])
def reserve_liabilities(cid):
    _, role = authenticate()
    data = get_body()
    v = validate(data, [
        ("reserve_taxes_cents", "nnint", True),
        ("reserve_fees_cents", "nnint", True),
    ])
    require_role(role, {"TrustOfficer"})
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    if c["status"] != "INITIATED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be INITIATED to reserve liabilities")
    # [11] funds check: reserves must fit available principal
    avail_p = (serialize.principal_balance(c["trust_id"])
               - serialize.reserved_principal(c["trust_id"]))
    if v["reserve_taxes_cents"] + v["reserve_fees_cents"] > avail_p:
        raise ApiError(ERR_INSUFFICIENT_AVAILABLE_BALANCE, 422,
                       "Reserves exceed available principal")
    c["reserve_taxes_cents"] = v["reserve_taxes_cents"]
    c["reserve_fees_cents"] = v["reserve_fees_cents"]
    c["status"] = "LIABILITIES_RESERVED"
    workflow.touch(c)
    return ok(termination_case_json(c))


@bp.route("/trusts/termination-cases/<cid>/record-tax-clearance", methods=["POST"])
def record_tax_clearance(cid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TaxSpecialist"})
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    if c["status"] != "LIABILITIES_RESERVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be LIABILITIES_RESERVED to record clearance")
    # [10] every TaxReturnFiling of the trust must be ACCEPTED
    for f in db.filings.values():
        if f["trust_id"] == c["trust_id"] and f["status"] != "ACCEPTED":
            raise ApiError(ERR_UNFILED_TAX_RETURNS, 409,
                           "A tax filing for this trust is not ACCEPTED")
    c["status"] = "TAX_CLEARANCE_RECEIVED"
    workflow.touch(c)
    return ok(termination_case_json(c))


@bp.route("/trusts/termination-cases/<cid>/approve-final-accounting",
          methods=["POST"])
def approve_final_accounting(cid):
    user_id, role = authenticate()
    get_body()
    require_role(role, {"TrustExecutive"})
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    # [4] segregation of duties: approver must differ from the initiator
    if c["initiated_by_user_id"] is not None and user_id == c["initiated_by_user_id"]:
        raise ApiError(ERR_SEGREGATION_OF_DUTIES, 403,
                       "Final-accounting approver must differ from the initiator")
    if c["status"] != "TAX_CLEARANCE_RECEIVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be TAX_CLEARANCE_RECEIVED to approve")
    c["status"] = "FINAL_ACCOUNTING_APPROVED"
    c["approved_by_user_id"] = user_id
    workflow.touch(c)
    return ok(termination_case_json(c))


@bp.route("/trusts/termination-cases/<cid>/distribute", methods=["POST"])
def distribute(cid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOperationsOfficer"})
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    if c["status"] != "FINAL_ACCOUNTING_APPROVED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be FINAL_ACCOUNTING_APPROVED to distribute")
    trust = db.trusts.get(c["trust_id"])
    income_pool = serialize.income_balance(c["trust_id"])
    principal_pool = (serialize.principal_balance(c["trust_id"])
                      - (c["reserve_taxes_cents"] or 0)
                      - (c["reserve_fees_cents"] or 0))
    income_lines = calc.build_distribution_lines(c["trust_id"], income_pool, "INCOME")
    remainder_lines = calc.build_distribution_lines(c["trust_id"], principal_pool,
                                                    "REMAINDER")
    c["distributable_income_cents"] = income_pool
    c["distributable_principal_cents"] = principal_pool
    c["distribution_lines"] = income_lines + remainder_lines
    value_date = clock.now_date().isoformat()
    for line in income_lines + remainder_lines:
        if line["amount_cents"] == 0:
            continue
        bucket = "INCOME" if line["beneficiary_class"] == "INCOME" else "PRINCIPAL"
        workflow.append_ledger(
            c["trust_id"], "DISTRIBUTION", bucket, -line["amount_cents"],
            value_date, source_entity_type="TERMINATION_CASE",
            source_entity_id=c["id"])
    c["status"] = "DISTRIBUTED"
    c["distributed_at"] = workflow.now_stamp()
    workflow.touch(c)
    # system transition: TrustAccount TERMINATING -> TERMINATED
    if trust is not None and trust["status"] == "TERMINATING":
        trust["status"] = "TERMINATED"
        workflow.bump_trust(trust)
    return ok(termination_case_json(c))


@bp.route("/trusts/termination-cases/<cid>/close", methods=["POST"])
def close_case(cid):
    _, role = authenticate()
    get_body()
    require_role(role, {"TrustOfficer"})
    c = find_or_404(db.termination_cases, cid, "TerminationCase")
    if c["status"] != "DISTRIBUTED":
        raise ApiError(ERR_INVALID_STATE, 409,
                       "Case must be DISTRIBUTED to close")
    trust = db.trusts.get(c["trust_id"])
    distributed_date = clock.parse_dt(c["distributed_at"]).date()
    fy = workflow.fiscal_year_for_date(trust, distributed_date)
    # final annual statement must be ACKNOWLEDGED
    acked = any(s["trust_id"] == c["trust_id"] and s["fiscal_year"] == fy
                and s["status"] == "ACKNOWLEDGED"
                for s in db.statements.values())
    if not acked:
        raise ApiError(ERR_FINAL_STATEMENT_NOT_ACKNOWLEDGED, 409,
                       "Final annual statement is not ACKNOWLEDGED")
    # final 1041 must be ACCEPTED
    accepted = any(f["trust_id"] == c["trust_id"] and f["tax_year"] == fy
                   and f["status"] == "ACCEPTED"
                   for f in db.filings.values())
    if not accepted:
        raise ApiError(ERR_UNFILED_TAX_RETURNS, 409,
                       "Final tax return is not ACCEPTED")
    c["status"] = "CLOSED"
    workflow.touch(c)
    # system transition: TrustAccount TERMINATED -> CLOSED
    if trust is not None and trust["status"] == "TERMINATED":
        trust["status"] = "CLOSED"
        workflow.bump_trust(trust)
    return ok(termination_case_json(c))
