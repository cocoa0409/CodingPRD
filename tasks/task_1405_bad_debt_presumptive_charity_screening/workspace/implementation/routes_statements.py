"""Statement endpoints: issue, list-by-account, get, mark-delivered,
mark-returned (PRD 3.2)."""

from datetime import date, timedelta

from flask import Blueprint

from db import db
from errors import ApiError, ERR_NOT_STATEMENT_ELIGIBLE, invalid_state, not_found
from middleware import (
    ROLE_COLLECTOR,
    ROLE_COUNSELOR,
    ROLE_OFFICER,
    authenticate,
)
from response import ok_list, ok_object
from services import (
    STATEMENT_CYCLE_DAYS,
    STATEMENT_ELIGIBLE_STATUSES,
    serialize_statement,
)
from util import base_record, now_iso, paginate, touch

bp = Blueprint("statements", __name__)

_READ_ROLES = [ROLE_COLLECTOR, ROLE_COUNSELOR, ROLE_OFFICER]


def get_statement_or_404(statement_id):
    stmt = db.statements.get(statement_id)
    if stmt is None:
        raise not_found("statement not found")
    return stmt


@bp.post("/self-pay/accounts/<account_id>/statements")
def issue_statement(account_id):
    authenticate([ROLE_COLLECTOR])
    from routes_accounts import get_account_or_404
    account = get_account_or_404(account_id)
    if account["status"] not in STATEMENT_ELIGIBLE_STATUSES:
        raise ApiError(
            ERR_NOT_STATEMENT_ELIGIBLE,
            "statement issuance requires account status OPEN, IN_EARLY_OUT or "
            "IN_COLLECTIONS",
            409,
        )
    prior = [s["statement_index"] for s in db.statements.values()
             if s["account_id"] == account_id]
    index = (max(prior) + 1) if prior else 1
    gl = date.fromisoformat(account["guarantor_liability_date"])
    due_date = gl + timedelta(days=index * STATEMENT_CYCLE_DAYS)
    rec = base_record()
    rec.update({
        "account_id": account_id,
        "statement_index": index,
        "issued_at": now_iso(),
        "due_date": due_date.isoformat(),
        "balance_at_issue_cents": account["current_balance_cents"],
        # creation issues immediately: DRAFT is never observable
        "status": "SENT",
    })
    db.statements[rec["id"]] = rec
    touch(account)  # statements_sent_count derived; version bump per PRD 3.2
    return ok_object(serialize_statement(rec), 201)


@bp.get("/self-pay/accounts/<account_id>/statements")
def list_statements(account_id):
    authenticate(_READ_ROLES)
    from routes_accounts import get_account_or_404
    get_account_or_404(account_id)
    items = [s for s in db.statements.values() if s["account_id"] == account_id]
    page, meta = paginate(items)
    return ok_list([serialize_statement(s) for s in page], meta)


@bp.get("/self-pay/statements/<statement_id>")
def get_statement(statement_id):
    authenticate(_READ_ROLES)
    return ok_object(serialize_statement(get_statement_or_404(statement_id)))


@bp.post("/self-pay/statements/<statement_id>/mark-delivered")
def mark_delivered(statement_id):
    authenticate([ROLE_COLLECTOR])
    stmt = get_statement_or_404(statement_id)
    if stmt["status"] != "SENT":
        raise invalid_state("only a SENT statement can be marked delivered")
    stmt["status"] = "DELIVERED"
    touch(stmt)
    return ok_object(serialize_statement(stmt))


@bp.post("/self-pay/statements/<statement_id>/mark-returned")
def mark_returned(statement_id):
    authenticate([ROLE_COLLECTOR])
    stmt = get_statement_or_404(statement_id)
    if stmt["status"] != "SENT":
        raise invalid_state("only a SENT statement can be marked returned")
    stmt["status"] = "RETURNED_UNDELIVERABLE"
    touch(stmt)
    # a returned statement no longer counts toward the statement cycle
    # (statements_sent_count is derived); the account mutation bumps version
    account = db.accounts.get(stmt["account_id"])
    if account is not None:
        touch(account)
    return ok_object(serialize_statement(stmt))
