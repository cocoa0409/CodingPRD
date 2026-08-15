"""ShadowPayrollRecord endpoints (PRD §3.3): DRAFT create, post with the ledger
cascade, void with compensation."""
from flask import Blueprint, request

from db import db
from errors import (
    raise_error,
    ERR_DUPLICATE_PAYROLL_PERIOD,
    ERR_INVALID_STATE,
    ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED,
    ERR_PER_DIEM_DAYS_INVALID,
    ERR_PERIOD_OUTSIDE_ASSIGNMENT,
    ERR_SPLIT_NOT_ACTIVE,
)
from middleware import authorized
from response import success_object
from routes.helpers import get_one, list_response, public
from services.calculations import compute_record_fields
from services.core import (
    assignment_of,
    create_chargeback_entry,
    employee_of_assignment,
    new_record,
    policy_of_assignment,
    program_of_assignment,
    rerun_overrun_posture_check,
    touch,
)
from validate import (
    days_in_month, get_body, req_field, req_int, require_fk, require_path_resource,
)

bp = Blueprint("shadow_payroll_records", __name__)

OPEN_SETTLEMENT_STATES = {"CALCULATED", "PENDING_REVIEW", "APPROVED", "DISPUTED"}


@bp.post("/mobility/shadow-payroll-records")
def create_record():
    authorized(["PayrollSpecialist"])
    body = get_body()
    # Existence (priority 3).
    asg = require_fk("assignments", req_field(body, "assignment_id"), "assignment_id")
    # Shape (priority 4).
    tax_year = req_int(body, "tax_year")
    period_month = req_int(body, "period_month", minimum=1, maximum=12)
    total_gross_cents = req_int(body, "total_gross_cents", minimum=0)
    per_diem_days = req_int(body, "per_diem_days", minimum=0)
    housing_receipts_cents = req_int(body, "housing_receipts_cents", minimum=0)
    # State gate (priority 5): the assignment must be ACTIVE.
    if asg["status"] != "ACTIVE":
        raise_error(ERR_INVALID_STATE, "shadow payroll records require an ACTIVE assignment")
    # Referential gate (priority 8): an ACTIVE payroll split must exist.
    split = None
    for sp in db["payroll_splits"].values():
        if sp["assignment_id"] == asg["id"] and sp["status"] == "ACTIVE":
            split = sp
            break
    if split is None:
        raise_error(ERR_SPLIT_NOT_ACTIVE, "an ACTIVE payroll split is required")
    # Date-window rule (priority 9): the record's month must intersect the
    # assignment window — evaluated before the uniqueness sweep.
    window_start = (asg["start_date"],)
    period_first = f"{tax_year:04d}-{period_month:02d}-01"
    period_last = f"{tax_year:04d}-{period_month:02d}-{days_in_month(tax_year, period_month):02d}"
    if period_last < asg["start_date"] or period_first > asg["planned_end_date"]:
        raise_error(
            ERR_PERIOD_OUTSIDE_ASSIGNMENT,
            "the record's period does not intersect the assignment window",
        )
    # Uniqueness/quantity family (priority 10), catalog order.
    for r in db["shadow_payroll_records"].values():
        if (r["assignment_id"] == asg["id"] and r["tax_year"] == tax_year
                and r["period_month"] == period_month and r["status"] in ("DRAFT", "POSTED")):
            raise_error(ERR_DUPLICATE_PAYROLL_PERIOD, "a DRAFT or POSTED record already exists for this period")
    if per_diem_days > days_in_month(tax_year, period_month):
        raise_error(ERR_PER_DIEM_DAYS_INVALID, "per_diem_days exceeds the number of days in the month")

    policy = policy_of_assignment(asg)
    employee = employee_of_assignment(asg)
    fields = compute_record_fields(
        total_gross_cents=total_gross_cents,
        per_diem_days=per_diem_days,
        housing_receipts_cents=housing_receipts_cents,
        home_payroll_pct=split["home_payroll_pct"],
        coc_exempt=split["coc_exempt"],
        per_diem_daily_cents=policy["per_diem_daily_cents"],
        cola_pct=policy["cola_pct"],
        housing_monthly_cap_cents=policy["housing_monthly_cap_cents"],
        family_size=employee["family_size"],
    )
    rec = new_record("shadow_payroll_records", {
        "assignment_id": asg["id"],
        "tax_year": tax_year,
        "period_month": period_month,
        "total_gross_cents": total_gross_cents,
        "per_diem_days": per_diem_days,
        "housing_receipts_cents": housing_receipts_cents,
        **fields,
        "status": "DRAFT",
    })
    return success_object(public(rec), status=201)


@bp.get("/mobility/shadow-payroll-records/<rid>")
def get_record(rid):
    return get_one("shadow_payroll_records", rid)


@bp.get("/mobility/shadow-payroll-records")
def list_records():
    return list_response("shadow_payroll_records", {
        "assignment_id": request.args.get("assignment_id"),
        "tax_year": request.args.get("tax_year"),
        "status": request.args.get("status"),
    })


@bp.post("/mobility/shadow-payroll-records/<rid>/post")
def post_record(rid):
    authorized(["PayrollSpecialist"])
    rec = require_path_resource("shadow_payroll_records", rid)
    if rec["status"] != "DRAFT":
        raise_error(ERR_INVALID_STATE, "only a DRAFT record can be posted")
    asg = assignment_of(rec)
    split_active = any(
        sp["assignment_id"] == asg["id"] and sp["status"] == "ACTIVE"
        for sp in db["payroll_splits"].values()
    )
    if not split_active:
        raise_error(ERR_SPLIT_NOT_ACTIVE, "an ACTIVE payroll split is required to post")
    # Cumulative per-diem annual cap (priority 11): inclusive boundary — exactly
    # reaching the cap is accepted, one day beyond is rejected.
    program = program_of_assignment(asg)
    used = sum(
        r["per_diem_days"]
        for r in db["shadow_payroll_records"].values()
        if r["assignment_id"] == asg["id"] and r["tax_year"] == rec["tax_year"]
        and r["status"] == "POSTED"
    )
    if used + rec["per_diem_days"] > program["per_diem_annual_day_cap"]:
        raise_error(
            ERR_PER_DIEM_ANNUAL_CAP_EXCEEDED,
            "posting would exceed the program's per-diem annual day cap",
        )

    rec["status"] = "POSTED"
    touch(rec)
    # Cascade hop 1: create the PERIOD_COST chargeback entry from frozen fields.
    amount = (rec["host_gross_cents"] + rec["employer_host_tax_cents"]
              + rec["employer_socsec_cents"] + rec["per_diem_cents"] + rec["housing_cents"])
    entry = create_chargeback_entry(asg, "PERIOD_COST", amount, source_record_id=rec["id"])
    # Cascade hop 2: assignment YTD aggregates.
    asg["ytd_chargeback_cents"] += entry["amount_cents"]
    asg["ytd_gross_cents"] += rec["total_gross_cents"]
    asg["ytd_hypo_withheld_cents"] += rec["hypothetical_tax_cents"]
    asg["ytd_per_diem_days"] += rec["per_diem_days"]
    touch(asg, bump_version=False)
    # Cascade hop 3: the overrun posture check.
    rerun_overrun_posture_check(asg)
    return success_object(public(rec))


@bp.post("/mobility/shadow-payroll-records/<rid>/void")
def void_record(rid):
    authorized(["PayrollSpecialist"])
    rec = require_path_resource("shadow_payroll_records", rid)
    if rec["status"] not in ("DRAFT", "POSTED"):
        raise_error(ERR_INVALID_STATE, "only a DRAFT or POSTED record can be voided")
    if rec["status"] == "POSTED":
        # Posted source records under an open settlement are frozen.
        for s in db["settlements"].values():
            if (s["assignment_id"] == rec["assignment_id"] and s["tax_year"] == rec["tax_year"]
                    and s["status"] in OPEN_SETTLEMENT_STATES):
                raise_error(
                    ERR_INVALID_STATE,
                    "posted records under an open settlement are frozen",
                )
    was_posted = rec["status"] == "POSTED"
    rec["status"] = "VOIDED"
    touch(rec)
    if was_posted:
        asg = assignment_of(rec)
        # Compensate: void the record's PERIOD_COST entry, decrement YTDs.
        for e in db["chargeback_entries"].values():
            if (e.get("source_record_id") == rec["id"] and e["entry_type"] == "PERIOD_COST"
                    and e["status"] != "VOIDED"):
                if e["status"] == "POSTED":
                    program = program_of_assignment(asg)
                    program["total_posted_chargeback_cents"] -= e["amount_cents"]
                    touch(program, bump_version=False)
                e["status"] = "VOIDED"
                touch(e)
                asg["ytd_chargeback_cents"] -= e["amount_cents"]
                break
        asg["ytd_gross_cents"] -= rec["total_gross_cents"]
        asg["ytd_hypo_withheld_cents"] -= rec["hypothetical_tax_cents"]
        asg["ytd_per_diem_days"] -= rec["per_diem_days"]
        touch(asg, bump_version=False)
        rerun_overrun_posture_check(asg)
    return success_object(public(rec))
