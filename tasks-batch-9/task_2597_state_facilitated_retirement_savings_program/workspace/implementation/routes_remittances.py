"""Payroll remittance batches: draft, lines, submit, post, reject, reverse."""
from flask import Blueprint

import calc
import serializers
from auth import (get_employer, get_enrollment, get_remittance, own_employer,
                  require)
from errors import fail
from response import created, paginate, query_filter, single
from store import db
from util import add_days, fmt_date, parse_date
from validate import parse_body

bp = Blueprint("remittances", __name__)

REMITTANCE_ROLES = ["ProgramAdministrator", "ComplianceOfficer", "Recordkeeper", "Employer"]
REMITTANCE_STATUSES = ("DRAFT", "SUBMITTED", "POSTED", "REJECTED", "REVERSED")
LINE_STATUSES = ("PENDING", "POSTED", "REVERSED", "RETURNED")
LIVE_STATUSES = ("DRAFT", "SUBMITTED", "POSTED", "REJECTED")


def _overlaps(employer_id, start, end, exclude_id=None):
    for row in db.payroll_remittances.values():
        if row["employer_id"] != employer_id or row["id"] == exclude_id:
            continue
        if row["status"] == "REVERSED":
            continue
        other_start = parse_date(row["pay_period_start"])
        other_end = parse_date(row["pay_period_end"])
        if start <= other_end and other_start <= end:
            return True
    return False


@bp.route("/employers/<employer_id>/payroll-remittances", methods=["POST"])
def create_remittance(employer_id):
    principal = require(["Employer"])
    employer = get_employer(employer_id)
    own_employer(principal, employer_id)
    parsed = parse_body({
        "pay_period_start": {"type": "date", "required": True},
        "pay_period_end": {"type": "date", "required": True},
        "pay_date": {"type": "date", "required": True},
        "total_deducted_cents": {"type": "int", "required": True, "min": 1},
    })
    start = parse_date(parsed["pay_period_start"])
    end = parse_date(parsed["pay_period_end"])
    pay_date = parse_date(parsed["pay_date"])
    if end < start:
        fail("ERR_INVALID_REQUEST", "pay_period_end must be on or after pay_period_start")
    if pay_date < end:
        fail("ERR_INVALID_REQUEST", "pay_date must be on or after pay_period_end")
    if employer["registration_status"] != "REGISTERED":
        fail("ERR_EMPLOYER_NOT_REGISTERED", "only a registered employer may remit")
    if _overlaps(employer_id, start, end):
        fail("ERR_PAY_PERIOD_OVERLAP", "this pay period collides with a live batch")
    row = db.insert("payroll_remittances", {
        "employer_id": employer_id,
        "pay_period_start": parsed["pay_period_start"],
        "pay_period_end": parsed["pay_period_end"],
        "pay_date": parsed["pay_date"],
        "total_deducted_cents": parsed["total_deducted_cents"],
        "status": "DRAFT",
        "line_count": 0,
        "total_allocated_cents": 0,
        "total_excess_cents": 0,
        "days_late": 0,
        "submitted_at": None,
        "posted_at": None,
        "reversed_at": None,
        "posting_reference": None,
        "rejection_reason": None,
        "reversal_reason": None,
    })
    return created(serializers.remittance(row))


@bp.route("/payroll-remittances/<remittance_id>", methods=["GET"])
def read_remittance(remittance_id):
    principal = require(REMITTANCE_ROLES)
    row = get_remittance(remittance_id)
    own_employer(principal, row["employer_id"])
    return single(serializers.remittance(row))


@bp.route("/payroll-remittances", methods=["GET"])
def list_remittances():
    principal = require(REMITTANCE_ROLES)
    employer_id = query_filter("employer_id")
    status = query_filter("status", REMITTANCE_STATUSES)
    rows = db.ordered("payroll_remittances")
    if principal.is_employer:
        rows = [r for r in rows if r["employer_id"] == principal.user_id]
    if employer_id is not None:
        rows = [r for r in rows if r["employer_id"] == employer_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return paginate(rows, serializers.remittance)


# ------------------------------------------------------------ remittance lines

@bp.route("/payroll-remittances/<remittance_id>/remittance-lines", methods=["POST"])
def add_line(remittance_id):
    principal = require(["Employer"])
    remittance = get_remittance(remittance_id)
    own_employer(principal, remittance["employer_id"])
    parsed = parse_body({
        "enrollment_id": {"type": "str", "required": True},
        "gross_wages_cents": {"type": "int", "required": True, "min": 0},
        "deducted_cents": {"type": "int", "required": True, "min": 1},
    })
    enrollment = get_enrollment(parsed["enrollment_id"])
    if remittance["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_REMITTANCE_STATE_INVALID", "this batch no longer accepts lines")
    if enrollment["employer_id"] != remittance["employer_id"] or \
            enrollment["enrollment_status"] in ("OPTED_OUT", "TERMINATED") or \
            calc.posting_target_account(enrollment["participant_id"]) is None:
        fail("ERR_ENROLLMENT_NOT_DEDUCTIBLE",
             "this enrolment cannot carry a payroll deduction")
    expected = calc.expected_deduction_cents(parsed["gross_wages_cents"],
                                             enrollment["contribution_rate_bp"])
    if int(parsed["deducted_cents"]) != expected:
        fail("ERR_DEDUCTION_AMOUNT_MISMATCH",
             "the programme computed %d cents for this line" % expected)
    row = db.insert("remittance_lines", {
        "remittance_id": remittance_id,
        "enrollment_id": enrollment["id"],
        "gross_wages_cents": parsed["gross_wages_cents"],
        "deducted_cents": parsed["deducted_cents"],
        "expected_deduction_cents": expected,
        "allocated_cents": 0,
        "excess_cents": 0,
        "status": "PENDING",
        "_account_id": None,
    })
    calc.refresh_remittance(remittance)
    return created(serializers.remittance_line(row))


@bp.route("/payroll-remittances/<remittance_id>/remittance-lines", methods=["GET"])
def list_lines(remittance_id):
    principal = require(REMITTANCE_ROLES)
    remittance = get_remittance(remittance_id)
    own_employer(principal, remittance["employer_id"])
    status = query_filter("status", LINE_STATUSES)
    rows = [l for l in db.ordered("remittance_lines") if l["remittance_id"] == remittance_id]
    if status is not None:
        rows = [l for l in rows if l["status"] == status]
    return paginate(rows, serializers.remittance_line)


# ----------------------------------------------------------------- transitions

@bp.route("/payroll-remittances/<remittance_id>/submit", methods=["POST"])
def submit_remittance(remittance_id):
    principal = require(["Employer"])
    remittance = get_remittance(remittance_id)
    own_employer(principal, remittance["employer_id"])
    parse_body({"submission_note": {"type": "str", "nullable": True}})
    if remittance["status"] not in ("DRAFT", "REJECTED"):
        fail("ERR_REMITTANCE_STATE_INVALID", "this batch cannot be submitted")
    lines = calc.remittance_lines_of(remittance_id)
    if not lines:
        fail("ERR_REMITTANCE_TOTAL_MISMATCH", "a batch must carry at least one line")
    total = sum(int(l["deducted_cents"]) for l in lines)
    if total != int(remittance["total_deducted_cents"]):
        fail("ERR_REMITTANCE_TOTAL_MISMATCH",
             "the lines total %d cents against a declared %d" %
             (total, int(remittance["total_deducted_cents"])))
    remittance["status"] = "SUBMITTED"
    remittance["submitted_at"] = db.now_iso()
    remittance["rejection_reason"] = None
    due = add_days(parse_date(remittance["pay_date"]), int(calc.dial("remittance_due_days")))
    remittance["days_late"] = max(0, (db.today() - due).days)
    calc.refresh_remittance(remittance)
    db.touch(remittance)
    employer = db.employers.get(remittance["employer_id"])
    calc.refresh_employer(employer, bump=True)
    return single(serializers.remittance(remittance))


@bp.route("/payroll-remittances/<remittance_id>/reject", methods=["POST"])
def reject_remittance(remittance_id):
    require(["Recordkeeper", "ProgramAdministrator"])
    remittance = get_remittance(remittance_id)
    parsed = parse_body({"rejection_reason": {"type": "str", "required": True}})
    if remittance["status"] != "SUBMITTED":
        fail("ERR_REMITTANCE_STATE_INVALID", "only a submitted batch may be rejected")
    remittance["status"] = "REJECTED"
    remittance["rejection_reason"] = parsed["rejection_reason"]
    calc.refresh_remittance(remittance)
    db.touch(remittance)
    calc.refresh_employer(db.employers.get(remittance["employer_id"]), bump=True)
    return single(serializers.remittance(remittance))


@bp.route("/payroll-remittances/<remittance_id>/post", methods=["POST"])
def post_remittance(remittance_id):
    require(["Recordkeeper"])
    remittance = get_remittance(remittance_id)
    parsed = parse_body({"posting_reference": {"type": "str", "required": True}})
    if remittance["status"] != "SUBMITTED":
        fail("ERR_REMITTANCE_STATE_INVALID", "only a submitted batch may be posted")
    year = calc.program_year()
    lines = calc.remittance_lines_of(remittance_id)
    for line in lines:
        enrollment = db.enrollments.get(line["enrollment_id"])
        if enrollment is None or enrollment["enrollment_status"] != "ACTIVE":
            fail("ERR_ENROLLMENT_NOT_DEDUCTIBLE",
                 "every enrolment on a posted batch must be active")
        if calc.posting_target_account(enrollment["participant_id"]) is None:
            fail("ERR_ENROLLMENT_NOT_DEDUCTIBLE", "this saver has no open account")

    pay_date = remittance["pay_date"]
    ordered = sorted(lines, key=lambda l: (pay_date, l["id"]))
    touched = {}
    for line in ordered:
        enrollment = db.enrollments[line["enrollment_id"]]
        account = calc.posting_target_account(enrollment["participant_id"])
        state = touched.get(account["id"])
        if state is None:
            participant = db.participants.get(account["participant_id"])
            state = {
                "account": account,
                "ceiling": calc.annual_ceiling_cents(participant),
                "ytd": int(account["ytd_contribution_cents"]),
                "opening": int(account["balance_cents"]),
                "credited": 0,
                "excess": 0,
            }
            touched[account["id"]] = state
        allocated = int(line["deducted_cents"])
        room = max(0, state["ceiling"] - state["ytd"])
        excess = max(0, allocated - room)
        state["ytd"] += allocated
        state["credited"] += allocated
        state["excess"] += excess
        account["balance_cents"] = int(account["balance_cents"]) + allocated
        account["contribution_basis_cents"] = int(account["contribution_basis_cents"]) + allocated
        account["ytd_contribution_cents"] = int(account["ytd_contribution_cents"]) + allocated
        line["status"] = "POSTED"
        line["allocated_cents"] = allocated
        line["excess_cents"] = excess
        line["_account_id"] = account["id"]
        db.touch(line)

    remittance["status"] = "POSTED"
    remittance["posted_at"] = db.now_iso()
    remittance["posting_reference"] = parsed["posting_reference"]
    calc.refresh_remittance(remittance)
    db.touch(remittance)

    for state in touched.values():
        account = state["account"]
        if state["excess"] > 0:
            db.insert("excess_cases", {
                "account_id": account["id"],
                "calendar_year": int(year["calendar_year"]),
                "detected_excess_cents": state["excess"],
                "detected_at_pay_date": pay_date,
                "computation_period_start": fmt_date(db.today()),
                "opening_fmv_cents": state["opening"],
                "period_contributions_cents": state["credited"],
                "period_distributions_cents": 0,
                "closing_fmv_cents": None,
                "nia_adjusted_balance_cents": None,
                "nia_daily_prorata_cents": None,
                "nia_method_applied": None,
                "applied_nia_cents": None,
                "correction_method": None,
                "status": "DETECTED",
                "deadline_date": fmt_date(calc.correction_deadline_date(year["calendar_year"])),
                "corrected_amount_cents": None,
                "excise_tax_cents": 0,
                "settlement_reference": None,
                "completed_at": None,
                "_created_by_remittance_id": remittance_id,
            })
        calc.refresh_account(account, bump=True)

    calc.refresh_employer(db.employers.get(remittance["employer_id"]), bump=True)
    return single(serializers.remittance(remittance))


@bp.route("/payroll-remittances/<remittance_id>/reverse", methods=["POST"])
def reverse_remittance(remittance_id):
    require(["Recordkeeper"])
    remittance = get_remittance(remittance_id)
    parsed = parse_body({"reversal_reason": {"type": "str", "required": True}})
    if remittance["status"] != "POSTED":
        fail("ERR_REMITTANCE_STATE_INVALID", "only a posted batch may be reversed")
    cases = [c for c in db.excess_cases.values()
             if c.get("_created_by_remittance_id") == remittance_id]
    for case in cases:
        if case["status"] == "COMPLETED":
            fail("ERR_REMITTANCE_STATE_INVALID",
                 "a correction produced by this batch has already moved money")
    touched = {}
    for line in calc.remittance_lines_of(remittance_id):
        if line["status"] != "POSTED":
            continue
        account = db.participant_accounts.get(line.get("_account_id"))
        allocated = int(line["allocated_cents"])
        if account is not None:
            account["balance_cents"] = int(account["balance_cents"]) - allocated
            account["contribution_basis_cents"] = int(account["contribution_basis_cents"]) - allocated
            account["ytd_contribution_cents"] = int(account["ytd_contribution_cents"]) - allocated
            touched[account["id"]] = account
        line["status"] = "REVERSED"
        line["allocated_cents"] = 0
        line["excess_cents"] = 0
        db.touch(line)
    for case in cases:
        if case["status"] in ("DETECTED", "METHOD_ELECTED"):
            case["status"] = "VOIDED"
            db.touch(case)
            account = db.participant_accounts.get(case["account_id"])
            if account is not None:
                touched[account["id"]] = account
    remittance["status"] = "REVERSED"
    remittance["reversed_at"] = db.now_iso()
    remittance["reversal_reason"] = parsed["reversal_reason"]
    calc.refresh_remittance(remittance)
    db.touch(remittance)
    for account in touched.values():
        calc.refresh_account(account, bump=True)
    calc.refresh_employer(db.employers.get(remittance["employer_id"]), bump=True)
    return single(serializers.remittance(remittance))
