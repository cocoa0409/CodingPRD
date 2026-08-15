"""Royalty statements: create/finalize/mark-paid with segregation of duties
(PRD §3.9)."""
from flask import Blueprint, request

from auth import (
    require_roles,
    ROLE_FINANCE_ANALYST,
    ROLE_FINANCE_CONTROLLER,
)
from domain import ATTRIBUTION_MODES, compute_statement, list_page, ser_statement
from errors import (
    err,
    ERR_STATEMENT_NOT_FOUND,
    ERR_HOLDER_NOT_FOUND,
    ERR_STATEMENT_PERIOD_OVERLAP,
    ERR_STATEMENT_NOT_DRAFT,
    ERR_STATEMENT_NOT_FINALIZED,
    ERR_SEGREGATION_OF_DUTIES,
)
from response import ok_list, ok_object
from store import DB, mutate
from validate import check_window_order, field_dt, field_enum, field_str, json_body

bp = Blueprint("statements", __name__)


def _get_statement_or_404(sid):
    rec = DB.get("statements", sid)
    if rec is None:
        err(ERR_STATEMENT_NOT_FOUND, "referenced royalty statement does not exist")
    return rec


@bp.route("/licensing/royalty-statements", methods=["POST"])
def create_statement():
    require_roles(ROLE_FINANCE_ANALYST)
    body = json_body()
    rights_holder_id = field_str(body, "rights_holder_id")
    period_start = field_dt(body, "period_start")
    period_end = field_dt(body, "period_end")
    check_window_order(period_start, period_end, "statement period")
    attribution_mode = field_enum(body, "attribution_mode", ATTRIBUTION_MODES)

    if DB.get("holders", rights_holder_id) is None:
        err(ERR_HOLDER_NOT_FOUND, "referenced rights holder does not exist")

    # Closed-interval overlap against other DRAFT/FINALIZED statements of the
    # same holder (PAID statements do not block).
    for s in DB.all("statements"):
        if s["rights_holder_id"] != rights_holder_id:
            continue
        if s["statement_status"] not in ("DRAFT", "FINALIZED"):
            continue
        if s["period_start"] <= period_end and period_start <= s["period_end"]:
            err(
                ERR_STATEMENT_PERIOD_OVERLAP,
                "statement period overlaps another open statement of this holder",
            )

    rec = DB.insert(
        "statements",
        {
            "rights_holder_id": rights_holder_id,
            "period_start": period_start,
            "period_end": period_end,
            "attribution_mode": attribution_mode,
            "included_report_ids": [],
            "gross_revenue_cents": 0,
            "studio_net_royalty_cents": 0,
            "holder_royalty_due_cents": 0,
            "statement_status": "DRAFT",
            "finalized_by_user_id": None,
            "paid_by_user_id": None,
        },
    )
    compute_statement(rec)
    return ok_object(ser_statement(rec), status=201)


@bp.route("/licensing/royalty-statements", methods=["GET"])
def list_statements():
    require_roles(ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER)
    records = DB.all("statements")
    holder_id = request.args.get("rights_holder_id")
    if holder_id is not None:
        records = [s for s in records if s["rights_holder_id"] == holder_id]
    status = request.args.get("statement_status")
    if status is not None:
        records = [s for s in records if s["statement_status"] == status]
    page, limit, offset, total = list_page(records, request.args)
    return ok_list([ser_statement(s) for s in page], limit, offset, total)


@bp.route("/licensing/royalty-statements/<sid>", methods=["GET"])
def get_statement(sid):
    require_roles(ROLE_FINANCE_ANALYST, ROLE_FINANCE_CONTROLLER)
    rec = _get_statement_or_404(sid)
    return ok_object(ser_statement(rec))


@bp.route("/licensing/royalty-statements/<sid>/finalize", methods=["POST"])
def finalize_statement(sid):
    user_id, _role = require_roles(ROLE_FINANCE_ANALYST)
    rec = _get_statement_or_404(sid)
    if rec["statement_status"] != "DRAFT":
        err(ERR_STATEMENT_NOT_DRAFT, "only a DRAFT statement can be finalized")
    # Fresh snapshot of the totals at finalize time.
    compute_statement(rec)
    rec["statement_status"] = "FINALIZED"
    rec["finalized_by_user_id"] = user_id
    mutate(rec)
    return ok_object(ser_statement(rec))


@bp.route("/licensing/royalty-statements/<sid>/mark-paid", methods=["POST"])
def mark_paid_statement(sid):
    user_id, _role = require_roles(ROLE_FINANCE_CONTROLLER)
    rec = _get_statement_or_404(sid)
    if rec["statement_status"] != "FINALIZED":
        err(ERR_STATEMENT_NOT_FINALIZED, "only a FINALIZED statement can be marked paid")
    # Segregation of duties: payer must differ from finalizer.
    if user_id == rec["finalized_by_user_id"]:
        err(ERR_SEGREGATION_OF_DUTIES, "statement payer must differ from the finalizer")
    rec["statement_status"] = "PAID"
    rec["paid_by_user_id"] = user_id
    mutate(rec)
    return ok_object(ser_statement(rec))
