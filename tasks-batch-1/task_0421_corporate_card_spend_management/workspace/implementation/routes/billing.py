"""Statements, billing cycle, repayments (PRD §3.6)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch, LOCK
from middleware import get_user_context, require_role, get_json_body
from response import success, success_list
from services.common import (
    get_or_404, require_fields, require_positive_int, as_int_field, paginate, serialize,
    recompute_available_credit, q as _q, filter_items as _filter,
)
from services.calculations import (
    compute_statement_balance, compute_minimum_due, statement_cashback_total,
)
from services.statements import open_new_statement, max_cycle_index, set_due_at

bp = Blueprint("billing", __name__)


# ----------------------------------------------------- Statement reads
@bp.route("/statements/<stmt_id>", methods=["GET"])
def get_statement(stmt_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.statements, stmt_id)), 200)


@bp.route("/statements", methods=["GET"])
def list_statements():
    get_user_context()
    with LOCK:
        items = list(db.statements.values())
        items = _filter(items, {"company_id": _q("company_id"), "status": _q("status")})
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/statements/<stmt_id>/close", methods=["POST"])
def close_statement(stmt_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        stmt = get_or_404(db.statements, stmt_id)
        if stmt["status"] != "OPEN":
            raise errors.err(errors.ERR_INVALID_STATE, "Statement is not OPEN.")
        company = db.companies.get(stmt["company_id"])
        if company.get("clock_utc") is None:
            raise errors.err(errors.ERR_CLOCK_NOT_SET, "Company clock is not set.")

        # closed_at = clock; due_at = closed_at + 21 days.
        stmt["closed_at"] = company["clock_utc"]
        stmt["due_at"] = set_due_at(stmt, company["clock_utc"])
        # statement_balance first, then minimum_due (fixed order).
        balance, swept = compute_statement_balance(stmt, company)
        # accrual sweep: assign swept CLEARED tx to this statement.
        for tx_id in swept:
            tx = db.transactions.get(tx_id)
            if tx is not None:
                tx["statement_id"] = stmt["id"]
                touch(tx)
        stmt["closing_balance_cents"] = balance
        stmt["minimum_due_cents"] = compute_minimum_due(balance, company)
        stmt["status"] = "CLOSED"
        touch(stmt)

        # CASCADE: a new OPEN statement with cycle_index+1.
        next_idx = max_cycle_index(company["id"]) + 1
        open_new_statement(company, cycle_index=next_idx)

        # CASCADE: company available credit recomputed (closing balance now posted).
        recompute_available_credit(company)
        touch(company)
        return success(serialize(stmt), 200)


@bp.route("/statements/<stmt_id>/issue", methods=["POST"])
def issue_statement(stmt_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        stmt = get_or_404(db.statements, stmt_id)
        if stmt["status"] != "CLOSED":
            raise errors.err(errors.ERR_INVALID_STATE, "Statement is not CLOSED.")
        stmt["status"] = "DUE"
        touch(stmt)
        return success(serialize(stmt), 200)


@bp.route("/statements/<stmt_id>/cashback-summary", methods=["GET"])
def cashback_summary(stmt_id):
    get_user_context()
    with LOCK:
        stmt = get_or_404(db.statements, stmt_id)
        total, count = statement_cashback_total(stmt)
        return success({
            "statement_id": stmt["id"],
            "statement_cashback_cents": total,
            "settled_transaction_count": count,
        }, 200)


# ----------------------------------------------------- Repayments
@bp.route("/repayments", methods=["POST"])
def create_repayment():
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    body = get_json_body()
    require_fields(body, ["statement_id", "amount_cents", "expected_statement_version"])
    with LOCK:
        stmt = get_or_404(db.statements, body["statement_id"])
        amount = require_positive_int(body, "amount_cents")
        expected = as_int_field(body, "expected_statement_version")
        # OCC check comes after positivity (priority 5 vs 16) but the PRD describes
        # it among the repayment workflow; state check (DUE/PAST_DUE) precedes OCC.
        if stmt["status"] not in ("DUE", "PAST_DUE"):
            raise errors.err(errors.ERR_INVALID_STATE, "Statement is not DUE/PAST_DUE.")
        if expected != stmt["version"]:
            raise errors.err(errors.ERR_STALE_VERSION, "Statement version is stale.")
        repayment = {
            "statement_id": stmt["id"],
            "company_id": stmt["company_id"],
            "amount_cents": amount,
            "expected_statement_version": expected,
            "status": "INITIATED",
        }
        stamp_create(repayment)
        db.repayments[repayment["id"]] = repayment
        return success(serialize(repayment), 201)


@bp.route("/repayments/<repayment_id>", methods=["GET"])
def get_repayment(repayment_id):
    get_user_context()
    with LOCK:
        return success(serialize(get_or_404(db.repayments, repayment_id)), 200)


@bp.route("/repayments", methods=["GET"])
def list_repayments():
    get_user_context()
    with LOCK:
        items = list(db.repayments.values())
        items = _filter(items, {
            "statement_id": _q("statement_id"),
            "company_id": _q("company_id"),
            "status": _q("status"),
        })
        page, limit, offset, total = paginate(items)
        return success_list(page, limit, offset, total)


@bp.route("/repayments/<repayment_id>/clear", methods=["POST"])
def clear_repayment(repayment_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        rp = get_or_404(db.repayments, repayment_id)
        if rp["status"] != "INITIATED":
            raise errors.err(errors.ERR_INVALID_STATE, "Repayment is not INITIATED.")
        rp["status"] = "CLEARED"
        touch(rp)
        stmt = db.statements.get(rp["statement_id"])
        company = db.companies.get(rp["company_id"])
        # CASCADE: statement.amount_repaid += amount.
        stmt["amount_repaid_cents"] += rp["amount_cents"]
        # CASCADE: statement -> PAID if amount_repaid >= minimum_due (from DUE or PAST_DUE).
        if (stmt["status"] in ("DUE", "PAST_DUE")
                and stmt["amount_repaid_cents"] >= stmt["minimum_due_cents"]):
            stmt["status"] = "PAID"
        touch(stmt)
        # CASCADE: company available credit rises (posted_unpaid shrinks).
        recompute_available_credit(company)
        touch(company)
        return success(serialize(rp), 200)


@bp.route("/repayments/<repayment_id>/fail", methods=["POST"])
def fail_repayment(repayment_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        rp = get_or_404(db.repayments, repayment_id)
        if rp["status"] != "INITIATED":
            raise errors.err(errors.ERR_INVALID_STATE, "Repayment is not INITIATED.")
        rp["status"] = "FAILED"
        touch(rp)
        return success(serialize(rp), 200)


@bp.route("/repayments/<repayment_id>/reverse", methods=["POST"])
def reverse_repayment(repayment_id):
    _, role = get_user_context()
    require_role(role, {"FinanceAdmin"})
    get_json_body()
    with LOCK:
        rp = get_or_404(db.repayments, repayment_id)
        if rp["status"] != "CLEARED":
            raise errors.err(errors.ERR_INVALID_STATE, "Repayment is not CLEARED.")
        rp["status"] = "REVERSED"
        touch(rp)
        stmt = db.statements.get(rp["statement_id"])
        company = db.companies.get(rp["company_id"])
        # CASCADE (compensating): amount_repaid -= amount.
        stmt["amount_repaid_cents"] -= rp["amount_cents"]
        # if PAID and now below minimum_due, revert PAID -> DUE.
        if stmt["status"] == "PAID" and stmt["amount_repaid_cents"] < stmt["minimum_due_cents"]:
            stmt["status"] = "DUE"
        touch(stmt)
        recompute_available_credit(company)
        touch(company)
        return success(serialize(rp), 200)
