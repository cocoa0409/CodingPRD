"""IncomeReport filing -> obligation -> optional Payment (PRD §3.8)."""
from flask import Blueprint

import errors
from db import db, stamp_create, touch
from middleware import require_role
from response import success
from services import serialize
from services.calc import monthly_obligation
from services.common import (
    get_json_body, lookup, require_fields, as_int, as_enum,
)
from services.derive import recompute_isa_ledger
from services.timeutil import parse_dt

bp = Blueprint("income_reports", __name__)

EMPLOYMENT = {"EMPLOYED", "UNEMPLOYED", "UNDEREMPLOYED"}


def _overlaps_half_open(a_start, a_end, b_start, b_end):
    """Half-open [start, end) overlap: a_start < b_end and b_start < a_end."""
    return a_start < b_end and b_start < a_end


@bp.post("/income-reports")
def create_income_report():
    require_role("ServicingOfficer", "Student")
    body = get_json_body()
    require_fields(body, ["isa_contract_id", "period_start", "period_end",
                          "gross_income_cents", "employment_status"])
    contract_id = body["isa_contract_id"]
    if not isinstance(contract_id, str):
        raise errors.invalid_request("isa_contract_id must be a string")
    contract = lookup(db.isa_contracts, contract_id)  # existence first

    gross = as_int(body, "gross_income_cents", min_value=0)
    employment = as_enum(body, "employment_status", EMPLOYMENT)
    p_start = parse_dt(body["period_start"], "period_start")
    p_end = parse_dt(body["period_end"], "period_end")

    # period overlap check against existing reports for same contract (half-open)
    for r in db.income_reports.values():
        if r["isa_contract_id"] == contract_id and _overlaps_half_open(
            p_start, p_end, r["_period_start_dt"], r["_period_end_dt"]
        ):
            raise errors.ApiError(errors.ERR_INCOME_PERIOD_OVERLAP, 409,
                                  "Income report period overlaps an existing report")

    recompute_isa_ledger(contract)
    obligation = monthly_obligation(contract, gross)

    r = {
        "isa_contract_id": contract_id,
        "period_start": body["period_start"],
        "period_end": body["period_end"],
        "_period_start_dt": p_start,
        "_period_end_dt": p_end,
        "_period_start_key": p_start.isoformat(),
        "gross_income_cents": gross,
        "employment_status": employment,
        "obligation_cents": obligation,
        "payment_id": None,
    }
    stamp_create(r)
    db.income_reports[r["id"]] = r

    if obligation > 0:
        pay = {
            "isa_contract_id": contract_id,
            "income_report_id": r["id"],
            "amount_cents": obligation,
            "collection_status": "PENDING",
            "refund_status": "NONE",
        }
        stamp_create(pay)
        db.payments[pay["id"]] = pay
        r["payment_id"] = pay["id"]
        touch(r)

    return success(serialize.income_report_view(r), status=201)


@bp.get("/income-reports/<rid>")
def get_income_report(rid):
    require_role("ServicingOfficer", "ComplianceOfficer", "Student")
    r = lookup(db.income_reports, rid)
    return success(serialize.income_report_view(r))
