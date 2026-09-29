"""Commission runs and commission statements."""

from flask import Blueprint

from common import (
    clock_str,
    new_row,
    opt_str,
    pagination,
    paginate,
    q_enum,
    q_str,
    raw_body,
    req_enum,
    req_int,
    req_str,
    touch,
)
from db import db
from errors import ApiError
from middleware import actor_id, auth, own_consultant
from response import created, ok, ok_list
from services.commission import active_statements, calculate_run
from services.genealogy import by_created
from services.lookup import fetch, peek

bp = Blueprint("runs", __name__)

RUN_STATUSES = ("DRAFT", "CALCULATED", "APPROVED", "PAID", "REVERSED")
STATEMENT_STATUSES = ("ACTIVE", "SUPERSEDED", "VOIDED")
PAYOUT_STATUSES = ("PENDING", "PAYABLE", "CARRIED_FORWARD", "PAID", "VOIDED")

READ_ROLES = [
    "Consultant",
    "CommissionAnalyst",
    "FinanceController",
    "LegalReviewer",
    "PlatformAdmin",
]

RUN_TOTAL_FIELDS = (
    "gross_total_cents",
    "forfeited_to_company_cents",
    "distributable_pool_cents",
    "withheld_total_cents",
    "net_payable_total_cents",
    "paid_total_cents",
    "carry_forward_total_cents",
    "reversed_total_cents",
)


def statement_sort_key(statement):
    return (statement["created_at"], statement["calculation_sequence"], statement["_seq"])


@bp.post("/commission-runs")
def create_run():
    auth(["CommissionAnalyst"])
    body = raw_body()
    qualification_period_id = req_str(body, "qualification_period_id", min_len=1)
    expected_version = req_int(body, "expected_qualification_period_version", minimum=0)

    period = fetch("period", qualification_period_id)

    if expected_version != int(period["version"]):
        raise ApiError("ERR_STALE_PERIOD_VERSION")
    if period["status"] != "CLOSED":
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    for existing in db.runs.values():
        if existing["qualification_period_id"] == period["id"] and existing["status"] in (
            "DRAFT",
            "CALCULATED",
            "APPROVED",
            "PAID",
        ):
            raise ApiError("ERR_RUN_ALREADY_EXISTS")

    row = new_row()
    row.update(
        {
            "qualification_period_id": period["id"],
            "period_code": period["period_code"],
            "compression_mode_snapshot": None,
            "status": "DRAFT",
            "calculation_sequence": 0,
            "calculated_by_user_id": None,
            "approved_by_user_id": None,
            "statement_count": 0,
            "gross_total_cents": 0,
            "forfeited_to_company_cents": 0,
            "distributable_pool_cents": 0,
            "withheld_total_cents": 0,
            "net_payable_total_cents": 0,
            "paid_total_cents": 0,
            "carry_forward_total_cents": 0,
            "reversed_total_cents": 0,
            "paid_at": None,
            "reversed_at": None,
            "correction_flagged": False,
        }
    )
    db.runs[row["id"]] = row
    touch(period)
    return created(row)


@bp.get("/commission-runs")
def list_runs():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "qualification_period_id": q_str("qualification_period_id"),
        "period_code": q_str("period_code"),
        "status": q_enum("status", RUN_STATUSES),
    }
    rows = by_created(list(db.runs.values()))
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/commission-runs/<run_id>")
def read_run(run_id):
    auth(READ_ROLES)
    return ok(fetch("run", run_id))


@bp.post("/commission-runs/<run_id>/calculate")
def calculate(run_id):
    auth(["CommissionAnalyst"])
    run = fetch("run", run_id)
    if run["status"] != "DRAFT":
        raise ApiError("ERR_RUN_NOT_DRAFT")
    period = db.periods.get(run["qualification_period_id"])
    if period is None or period["status"] != "CLOSED":
        raise ApiError("ERR_PERIOD_NOT_CLOSED")
    plan = db.plans.get(period["compensation_plan_id"])
    calculate_run(run, period, plan, actor_id())
    return ok(run)


@bp.post("/commission-runs/<run_id>/approval-decision")
def approval_decision(run_id):
    auth(["FinanceController"])
    body = raw_body()
    decision = req_enum(body, "decision", ("APPROVE", "REJECT"))
    opt_str(body, "decision_note")

    run = fetch("run", run_id)
    if run["status"] != "CALCULATED":
        raise ApiError("ERR_RUN_NOT_CALCULATED")
    if actor_id() == run.get("calculated_by_user_id"):
        raise ApiError("ERR_SEGREGATION_OF_DUTIES")

    actives = active_statements(run["id"])
    if decision == "APPROVE":
        for statement in actives:
            consultant = db.consultants.get(statement["consultant_id"])
            if consultant is not None and consultant["status"] == "SUSPENDED":
                raise ApiError("ERR_SUSPENDED_EARNER_BLOCKS_APPROVAL")
        for statement in actives:
            statement["payout_status"] = "PAYABLE"
            touch(statement)
        run["status"] = "APPROVED"
        run["approved_by_user_id"] = actor_id()
    else:
        for statement in actives:
            statement["status"] = "SUPERSEDED"
            statement["payout_status"] = "PENDING"
            touch(statement)
        for field in RUN_TOTAL_FIELDS:
            run[field] = 0
        run["statement_count"] = 0
        run["compression_mode_snapshot"] = None
        run["status"] = "DRAFT"
    touch(run)
    return ok(run)


@bp.post("/commission-runs/<run_id>/pay")
def pay_run(run_id):
    auth(["FinanceController"])
    run = fetch("run", run_id)
    if run["status"] != "APPROVED":
        raise ApiError("ERR_RUN_NOT_APPROVED")

    period = db.periods.get(run["qualification_period_id"])
    plan = db.plans.get(period["compensation_plan_id"]) if period else None
    min_payout = int(plan["min_payout_cents"]) if plan else 0

    actives = active_statements(run["id"])

    # payout_hold as it stood at the start of the transition.
    hold_snapshot = {}
    for statement in actives:
        consultant_id = statement["consultant_id"]
        if consultant_id not in hold_snapshot:
            consultant = db.consultants.get(consultant_id)
            hold_snapshot[consultant_id] = bool(consultant["payout_hold"]) if consultant else False

    for statement in actives:
        consultant = db.consultants.get(statement["consultant_id"])
        if consultant is not None:
            consultant["clawback_balance_cents"] = int(
                consultant["clawback_balance_cents"]
            ) - int(statement["withholding_cents"])
            consultant["payout_hold"] = int(consultant["clawback_balance_cents"]) > 0

        net_payable = int(statement["net_payable_cents"])
        was_on_hold = hold_snapshot.get(statement["consultant_id"], False)
        if net_payable >= min_payout and not was_on_hold:
            statement["paid_cents"] = net_payable
            statement["carry_forward_cents"] = 0
            statement["payout_status"] = "PAID"
            if consultant is not None:
                consultant["lifetime_commission_paid_cents"] = int(
                    consultant["lifetime_commission_paid_cents"]
                ) + net_payable
        else:
            statement["paid_cents"] = 0
            statement["carry_forward_cents"] = net_payable
            statement["payout_status"] = "CARRIED_FORWARD"
            if consultant is not None:
                consultant["carry_forward_cents"] = int(
                    consultant["carry_forward_cents"]
                ) + net_payable
        touch(statement)
        if consultant is not None:
            touch(consultant)

    run["paid_total_cents"] = sum(int(s["paid_cents"]) for s in active_statements(run["id"]))
    run["carry_forward_total_cents"] = sum(
        int(s["carry_forward_cents"]) for s in active_statements(run["id"])
    )
    run["status"] = "PAID"
    run["paid_at"] = clock_str()
    touch(run)
    return ok(run)


@bp.post("/commission-runs/<run_id>/reverse")
def reverse_run(run_id):
    auth(["FinanceController"])
    body = raw_body()
    req_str(body, "reversal_reason", min_len=1)

    run = fetch("run", run_id)
    if run["status"] != "PAID":
        raise ApiError("ERR_RUN_NOT_PAID")

    for statement in active_statements(run["id"]):
        previous_payout = statement["payout_status"]
        consultant = db.consultants.get(statement["consultant_id"])
        statement["status"] = "VOIDED"
        statement["payout_status"] = "VOIDED"
        touch(statement)
        if consultant is None:
            continue
        if previous_payout == "PAID":
            consultant["lifetime_commission_paid_cents"] = int(
                consultant["lifetime_commission_paid_cents"]
            ) - int(statement["paid_cents"])
            consultant["clawback_balance_cents"] = int(
                consultant["clawback_balance_cents"]
            ) + int(statement["paid_cents"])
            if int(consultant["clawback_balance_cents"]) > 0:
                consultant["payout_hold"] = True
            touch(consultant)
        elif previous_payout == "CARRIED_FORWARD":
            consultant["carry_forward_cents"] = int(consultant["carry_forward_cents"]) - int(
                statement["carry_forward_cents"]
            )
            touch(consultant)

    run["reversed_total_cents"] = int(run["paid_total_cents"])
    run["status"] = "REVERSED"
    run["reversed_at"] = clock_str()
    touch(run)

    for disclosure in db.disclosures.values():
        if disclosure["commission_run_id"] == run["id"] and disclosure["status"] == "PUBLISHED":
            disclosure["status"] = "SUPERSEDED"
            disclosure["supersede_reason"] = "RUN_REVERSED"
            touch(disclosure)

    return ok(run)


# --------------------------------------------------------------------------
# Commission statements
# --------------------------------------------------------------------------

@bp.get("/commission-statements")
def list_statements():
    auth(READ_ROLES)
    limit, offset = pagination()
    filters = {
        "commission_run_id": q_str("commission_run_id"),
        "consultant_id": q_str("consultant_id"),
        "period_code": q_str("period_code"),
        "status": q_enum("status", STATEMENT_STATUSES),
        "payout_status": q_enum("payout_status", PAYOUT_STATUSES),
        "paid_as_rank_code": q_str("paid_as_rank_code"),
    }
    rows = sorted(db.statements.values(), key=statement_sort_key)
    for field, value in filters.items():
        if value is not None:
            rows = [r for r in rows if r.get(field) == value]
    page, total = paginate(rows, limit, offset)
    return ok_list(page, total, limit, offset)


@bp.get("/commission-statements/<statement_id>")
def read_statement(statement_id):
    auth(READ_ROLES)
    existing = peek("statement", statement_id)
    if existing is not None:
        own_consultant(existing["consultant_id"])
    return ok(fetch("statement", statement_id))
