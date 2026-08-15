"""Payroll export routes: create."""
from flask import Blueprint

from db import db
from errors import (
    raise_error,
    ERR_NOT_FOUND,
    ERR_PAYROLL_PERIOD_NOT_CLOSED,
    ERR_PAYROLL_EXPORT_EXISTS,
    ERR_STATEMENTS_NOT_APPROVED,
)
from middleware import authorized
from response import success_object
from util import new_id, now_ts, touch, serialize
from validate import get_body, req_str, req_int

bp = Blueprint("payroll_exports", __name__)

ADMIN_ONLY = ["CompAdmin"]


@bp.route("/payroll-exports", methods=["POST"])
def create_payroll_export():
    caller = authorized(ADMIN_ONLY)
    body = get_body()

    program_id = req_str(body, "program_id")
    period_index = req_int(body, "period_index")

    # Priority 3: program exists
    program = db["programs"].get(program_id)
    if program is None:
        raise_error(ERR_NOT_FOUND, f"program not found: {program_id}")

    # Priority 6: period must be closed (< current_period_index)
    if period_index >= program["current_period_index"]:
        raise_error(ERR_PAYROLL_PERIOD_NOT_CLOSED,
                    f"period {period_index} is not yet closed (current={program['current_period_index']})")

    # Priority 7: one export per (program, period)
    for e in db["payroll_exports"].values():
        if e["program_id"] == program_id and e["period_index"] == period_index:
            raise_error(ERR_PAYROLL_EXPORT_EXISTS,
                        f"export already exists for program {program_id} period {period_index}")

    # Find all statements for this program+period
    program_assignment_ids = {
        a["id"] for a in db["assignments"].values()
        if a["program_id"] == program_id
    }
    period_statements = [
        s for s in db["statements"].values()
        if s["assignment_id"] in program_assignment_ids
        and s["period_index"] == period_index
    ]

    # Priority 7: all statements must be APPROVED
    for s in period_statements:
        if s["status"] == "DRAFT":
            raise_error(ERR_STATEMENTS_NOT_APPROVED,
                        f"statement {s['id']} is still DRAFT")

    # Transition APPROVED -> EXPORTED
    statement_ids = []
    total_cents = 0
    for s in period_statements:
        if s["status"] == "APPROVED":
            s["status"] = "EXPORTED"
            touch(s)
            statement_ids.append(s["id"])
            total_cents += s["net_payable_cents"]

    # Create export record (immutable: id + created_at only, no updated_at/version)
    export = {
        "id": new_id(),
        "created_at": now_ts(),
        "program_id": program_id,
        "period_index": period_index,
        "statement_ids": statement_ids,
        "statement_count": len(statement_ids),
        "total_cents": total_cents,
    }
    db["payroll_exports"][export["id"]] = export

    # Relieve accrual
    program["accrued_balance_cents"] -= total_cents
    touch(program)

    return success_object(serialize(export), 201)
