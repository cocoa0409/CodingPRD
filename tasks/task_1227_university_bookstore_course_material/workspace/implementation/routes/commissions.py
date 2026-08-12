"""Commission statements: PROVISIONAL snapshot at creation, FINAL recompute at
issue, compliance-posture gate, and segregation of duties (PRD §3.10)."""

from flask import Blueprint, request

from db import store, new_entity, touch, pub
from errors import (
    ApiError, ERR_INVALID_STATE, ERR_DUPLICATE_COMMISSION_STATEMENT,
    ERR_TERM_NOT_COMPLIANT, ERR_SOD_COMMISSION_CONFLICT,
)
from middleware import require_roles, body, get_str, get_or_404
from response import success, list_response
from services import compute_commission, plan_term_id, plan_publisher_id

bp = Blueprint("commissions", __name__)


@bp.post("/bookstore/commission-statements")
def create_statement():
    require_roles("FinanceAdmin")
    data = body()
    publisher_id = get_str(data, "publisher_id")
    term_id = get_str(data, "term_id")
    get_or_404(store.publishers, publisher_id, "publisher")
    get_or_404(store.terms, term_id, "term")
    for s in store.commission_statements.values():
        if (s["publisher_id"] == publisher_id and s["term_id"] == term_id
                and s["status"] in ("DRAFT", "ISSUED")):
            raise ApiError(ERR_DUPLICATE_COMMISSION_STATEMENT, 409,
                           "non-terminal statement exists for (publisher, term)")
    calc = compute_commission(publisher_id, term_id)  # PROVISIONAL snapshot
    stmt = new_entity()
    stmt.update({
        "publisher_id": publisher_id,
        "term_id": term_id,
        "calculation_variant": "PROVISIONAL",
        "gross_sales_cents": calc["gross_sales_cents"],
        "returns_cents": calc["returns_cents"],
        "net_sales_cents": calc["net_sales_cents"],
        "commission_cents": calc["commission_cents"],
        "status": "DRAFT",
        "issued_by_user_id": None,
    })
    store.commission_statements[stmt["id"]] = stmt
    return success(pub(stmt), status=201)


@bp.get("/bookstore/commission-statements")
def list_statements():
    require_roles("FinanceAdmin", "BookstoreManager")
    publisher_id = request.args.get("publisher_id")
    term_id = request.args.get("term_id")
    status = request.args.get("status")
    items = [
        s for s in store.commission_statements.values()
        if (publisher_id is None or s["publisher_id"] == publisher_id)
        and (term_id is None or s["term_id"] == term_id)
        and (status is None or s["status"] == status)
    ]
    return list_response(items)


@bp.get("/bookstore/commission-statements/<sid>")
def get_statement(sid):
    require_roles("FinanceAdmin")
    return success(pub(get_or_404(store.commission_statements, sid,
                                  "commission statement")))


@bp.post("/bookstore/commission-statements/<sid>/issue")
def issue_statement(sid):
    uid, _ = require_roles("FinanceAdmin")
    stmt = get_or_404(store.commission_statements, sid, "commission statement")
    if stmt["status"] != "DRAFT":
        raise ApiError(ERR_INVALID_STATE, 409, "statement not in DRAFT")
    # business safety (priority 6): segregation of duties — the issuer must
    # differ from every committed buy-plan committer for this publisher+term
    committers = set()
    for p in store.buy_plans.values():
        if p["status"] not in ("COMMITTED", "RECEIVED"):
            continue
        if (plan_term_id(p) == stmt["term_id"]
                and plan_publisher_id(p) == stmt["publisher_id"]):
            committers.add(p["committed_by_user_id"])
    if uid in committers:
        raise ApiError(ERR_SOD_COMMISSION_CONFLICT, 403,
                       "issuer committed buy plans for this publisher+term")
    # business referential (priority 9): term posture must be CLEAR
    term = store.terms[stmt["term_id"]]
    if term["compliance_posture"] != "CLEAR":
        raise ApiError(ERR_TERM_NOT_COMPLIANT, 422,
                       "term compliance posture is RESTRICTED")
    # FINAL recompute: folds in returns processed between creation and issue,
    # then locks
    calc = compute_commission(stmt["publisher_id"], stmt["term_id"])
    stmt["calculation_variant"] = "FINAL"
    stmt["gross_sales_cents"] = calc["gross_sales_cents"]
    stmt["returns_cents"] = calc["returns_cents"]
    stmt["net_sales_cents"] = calc["net_sales_cents"]
    stmt["commission_cents"] = calc["commission_cents"]
    stmt["issued_by_user_id"] = uid
    stmt["status"] = "ISSUED"
    touch(stmt)
    return success(pub(stmt))


@bp.post("/bookstore/commission-statements/<sid>/settle")
def settle_statement(sid):
    require_roles("FinanceAdmin")
    stmt = get_or_404(store.commission_statements, sid, "commission statement")
    if stmt["status"] != "ISSUED":
        raise ApiError(ERR_INVALID_STATE, 409, "statement not in ISSUED")
    stmt["status"] = "SETTLED"
    touch(stmt)
    return success(pub(stmt))
