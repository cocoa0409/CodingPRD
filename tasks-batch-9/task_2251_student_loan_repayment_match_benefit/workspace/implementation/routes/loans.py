"""Loan accounts, annual claims and certification lines (PRD 3.4, 3.5, 3.9)."""

from flask import Blueprint, request

import db
from errors import fail
from middleware import (auth, body, opt_str, req_enum, req_int, req_str,
                        req_ts)
from response import object_response, paginated
from services import calc, effects, lookup, serialize

bp = Blueprint("loans", __name__)

LOAN_VERIFICATION_STATUSES = ("VERIFIED", "DISQUALIFIED")
CERTIFICATION_METHODS = ("SELF_CERTIFICATION", "SERVICER_STATEMENT")
DECISIONS = ("RETURN", "ACCEPT")
RESOLUTIONS = ("CLEAR", "VOID")
OVERLAP_CERT_STATUSES = ("DRAFT", "SUBMITTED", "ACCEPTED", "AUDIT_HOLD")
TERMINAL_CERT_STATUSES = ("VOIDED", "SUPERSEDED")


# --------------------------------------------------------------------------
# loan accounts
# --------------------------------------------------------------------------

@bp.post("/loan-accounts")
def create_loan_account():
    user_id, role = auth("Employee", "BenefitsAdministrator")
    payload = body()
    employee_id = req_str(payload, "employee_id")
    servicer_name = req_str(payload, "servicer_name")
    account_last4 = req_str(payload, "account_last4")
    if len(account_last4) != 4 or not account_last4.isdigit():
        fail("ERR_INVALID_REQUEST",
             "account_last4 must be exactly four digits")
    principal = req_int(payload, "original_principal_cents", minimum=1)
    employee = lookup.employee(employee_id)
    lookup.require_owner(role, user_id, employee["id"])

    row = {
        "employee_id": employee["id"],
        "servicer_name": servicer_name,
        "account_last4": account_last4,
        "original_principal_cents": principal,
        "status": "UNVERIFIED",
        "evidence_ref": None,
    }
    db.stamp_new(row)
    db.db.loan_accounts[row["id"]] = row
    return object_response(serialize.loan_account(row), 201)


@bp.get("/loan-accounts")
def list_loan_accounts():
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    rows = lookup.scope_to_owner(db.rows("loan_accounts"), role, user_id)
    employee_id = request.args.get("employee_id")
    if employee_id:
        rows = [r for r in rows if r["employee_id"] == employee_id]
    status = request.args.get("status")
    if status:
        rows = [r for r in rows if r["status"] == status]
    return paginated(rows, serialize.loan_account)


@bp.get("/loan-accounts/<loan_account_id>")
def get_loan_account(loan_account_id):
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    row = lookup.loan_account(loan_account_id)
    lookup.require_owner(role, user_id, row["employee_id"])
    return object_response(serialize.loan_account(row))


@bp.post("/loan-accounts/<loan_account_id>/verification")
def verify_loan_account(loan_account_id):
    auth("BenefitsAdministrator")
    payload = body()
    to_status = req_enum(payload, "to_status", LOAN_VERIFICATION_STATUSES)
    evidence_ref = opt_str(payload, "evidence_ref")
    account = lookup.loan_account(loan_account_id)
    account["status"] = to_status
    if evidence_ref is not None:
        account["evidence_ref"] = evidence_ref
    db.touch(account)
    return object_response(serialize.loan_account(account))


# --------------------------------------------------------------------------
# annual claims
# --------------------------------------------------------------------------

@bp.post("/loan-certifications")
def create_certification():
    user_id, role = auth("Employee")
    payload = body()
    employee_id = req_str(payload, "employee_id")
    plan_year_id = req_str(payload, "plan_year_id")
    method = req_enum(payload, "certification_method", CERTIFICATION_METHODS)
    expected_version = req_int(payload, "expected_employee_version")
    supersedes_id = opt_str(payload, "supersedes_certification_id")

    plan_year = lookup.plan_year(plan_year_id)
    employee = lookup.employee(employee_id)
    superseded = (lookup.certification(supersedes_id)
                  if supersedes_id is not None else None)

    lookup.require_owner(role, user_id, employee["id"])

    if expected_version != employee["version"]:
        fail("ERR_STALE_EMPLOYEE_VERSION",
             "expected_employee_version %s does not match the employee's "
             "current version %s" % (expected_version, employee["version"]))

    if plan_year["status"] != "OPEN":
        fail("ERR_PLAN_YEAR_LOCKED", "the plan year is not OPEN")

    if employee["employment_status"] == "TERMINATED":
        fail("ERR_EMPLOYEE_NOT_ELIGIBLE",
             "a terminated participant may not open a claim")

    for other in calc.certifications_of(employee["id"], plan_year["id"]):
        if other["status"] in ("DRAFT", "SUBMITTED"):
            fail("ERR_DUPLICATE_OPEN_CERTIFICATION",
                 "another claim of this employee and plan year is still open")
    if superseded is not None:
        if (superseded["employee_id"] != employee["id"]
                or superseded["plan_year_id"] != plan_year["id"]
                or superseded["status"] != "ACCEPTED"):
            fail("ERR_DUPLICATE_OPEN_CERTIFICATION",
                 "supersedes_certification_id must name an ACCEPTED claim of "
                 "the same employee and plan year")

    row = {
        "employee_id": employee["id"],
        "plan_year_id": plan_year["id"],
        "supersedes_certification_id": supersedes_id,
        "certification_method": method,
        "status": "DRAFT",
        "submitted_at": None,
        "decided_at": None,
        "accepted_by_user_id": None,
        "return_count": 0,
        "eligible_total_cents": 0,
        "capped_by_statutory_room": False,
        "audit_hold_reason": None,
        "void_reason": None,
    }
    db.stamp_new(row)
    db.db.loan_certifications[row["id"]] = row
    db.touch(employee)
    return object_response(serialize.loan_certification(row), 201)


@bp.get("/loan-certifications")
def list_certifications():
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    rows = lookup.scope_to_owner(db.rows("loan_certifications"), role, user_id)
    for name in ("employee_id", "plan_year_id", "status",
                 "supersedes_certification_id"):
        value = request.args.get(name)
        if value:
            rows = [r for r in rows if r[name] == value]
    return paginated(rows, serialize.loan_certification)


@bp.get("/loan-certifications/<certification_id>")
def get_certification(certification_id):
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    cert = lookup.certification(certification_id)
    lookup.require_owner(role, user_id, cert["employee_id"])
    return object_response(serialize.loan_certification(cert))


def _guard_not_terminal(cert):
    if cert["status"] in TERMINAL_CERT_STATUSES:
        fail("ERR_CERTIFICATION_TERMINAL",
             "the claim is already %s" % cert["status"])


def _guard_from_state(cert, allowed):
    if cert["status"] not in allowed:
        fail("ERR_CERTIFICATION_STATE_INVALID",
             "the claim is %s" % cert["status"])


# --------------------------------------------------------------------------
# certification lines
# --------------------------------------------------------------------------

@bp.post("/loan-certifications/<certification_id>/lines")
def create_line(certification_id):
    user_id, role = auth("Employee")
    payload = body()
    loan_account_id = req_str(payload, "loan_account_id")
    payment_date, payment_dt = req_ts(payload, "payment_date")
    amount = req_int(payload, "amount_cents", minimum=1)
    covered_start, covered_start_dt = req_ts(payload, "covered_period_start")
    covered_end, covered_end_dt = req_ts(payload, "covered_period_end")
    if not covered_end_dt > covered_start_dt:
        fail("ERR_INVALID_REQUEST",
             "covered_period_end must be strictly after covered_period_start")

    cert = lookup.certification(certification_id)
    account = lookup.loan_account(loan_account_id)
    lookup.require_owner(role, user_id, cert["employee_id"])

    plan_year = db.db.plan_years.get(cert["plan_year_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail("ERR_PLAN_YEAR_LOCKED", "the plan year is not OPEN")
    _guard_not_terminal(cert)
    _guard_from_state(cert, ("DRAFT", "RETURNED"))

    if account["status"] != "VERIFIED":
        fail("ERR_LOAN_NOT_VERIFIED",
             "the referenced loan account is not VERIFIED")

    if not (plan_year["_period_start_dt"] <= payment_dt
            <= plan_year["_period_end_dt"]):
        fail("ERR_PAYMENT_DATE_OUTSIDE_PLAN_YEAR",
             "payment_date falls outside the plan year window")
    if payment_dt > db.now():
        fail("ERR_PAYMENT_DATE_IN_FUTURE", "payment_date is in the future")

    for line in db.rows("certification_lines"):
        if line["loan_account_id"] != account["id"]:
            continue
        parent = db.db.loan_certifications.get(line["certification_id"])
        if parent is None or parent["status"] not in OVERLAP_CERT_STATUSES:
            continue
        # Half-open windows: touching endpoints do not intersect.
        if (covered_start_dt < line["_covered_end_dt"]
                and line["_covered_start_dt"] < covered_end_dt):
            fail("ERR_COVERED_PERIOD_OVERLAP",
                 "the covered billing window is already certified")

    row = {
        "certification_id": cert["id"],
        "loan_account_id": account["id"],
        "payment_date": payment_date,
        "amount_cents": amount,
        "covered_period_start": covered_start,
        "covered_period_end": covered_end,
        "_covered_start_dt": covered_start_dt,
        "_covered_end_dt": covered_end_dt,
    }
    db.stamp_new(row, versioned=False)
    db.db.certification_lines[row["id"]] = row
    db.touch(cert)
    return object_response(serialize.certification_line(row), 201)


@bp.get("/loan-certifications/<certification_id>/lines")
def list_lines_of_certification(certification_id):
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    cert = lookup.certification(certification_id)
    lookup.require_owner(role, user_id, cert["employee_id"])
    rows = [l for l in db.rows("certification_lines")
            if l["certification_id"] == cert["id"]]
    return paginated(rows, serialize.certification_line)


@bp.get("/certification-lines")
def list_lines():
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    rows = db.rows("certification_lines")
    if role == "Employee":
        rows = [l for l in rows
                if (db.db.loan_certifications.get(l["certification_id"]) or {})
                .get("employee_id") == user_id]
    certification_id = request.args.get("certification_id")
    if certification_id:
        rows = [l for l in rows
                if l["certification_id"] == certification_id]
    loan_account_id = request.args.get("loan_account_id")
    if loan_account_id:
        rows = [l for l in rows if l["loan_account_id"] == loan_account_id]
    return paginated(rows, serialize.certification_line)


@bp.get("/certification-lines/<certification_line_id>")
def get_line(certification_line_id):
    user_id, role = auth("Employee", "BenefitsAdministrator",
                         "ComplianceAuditor")
    line = lookup.audit_row("certification_lines", certification_line_id)
    parent = db.db.loan_certifications.get(line["certification_id"])
    lookup.require_owner(role, user_id,
                         parent["employee_id"] if parent else None)
    return object_response(serialize.certification_line(line))


# --------------------------------------------------------------------------
# submit / decide / audit
# --------------------------------------------------------------------------

@bp.post("/loan-certifications/<certification_id>/submit")
def submit_certification(certification_id):
    user_id, role = auth("Employee")
    body()
    cert = lookup.certification(certification_id)
    lookup.require_owner(role, user_id, cert["employee_id"])

    plan_year = db.db.plan_years.get(cert["plan_year_id"])
    employee = db.db.employees.get(cert["employee_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail("ERR_PLAN_YEAR_LOCKED", "the plan year is not OPEN")
    _guard_not_terminal(cert)
    _guard_from_state(cert, ("DRAFT", "RETURNED"))

    if employee["employment_status"] == "TERMINATED":
        fail("ERR_EMPLOYEE_NOT_ELIGIBLE",
             "a terminated participant may not submit a claim")

    clock = db.now()
    if not (plan_year["_window_open_dt"] <= clock
            <= plan_year["_deadline_dt"]):
        fail("ERR_CERTIFICATION_WINDOW_CLOSED",
             "the certification window is not open")

    if not calc.lines_of(cert["id"]):
        fail("ERR_NO_CERTIFIED_LINES", "the claim carries no payment line")

    room = (plan_year["annual_deferral_limit_cents"]
            - calc.ytd_deferral(employee["id"], plan_year["id"])
            - calc.reserved_certified(employee["id"], plan_year["id"],
                                      exclude_id=cert["id"]))
    if max(room, 0) <= 0:
        fail("ERR_QSLP_SPACE_EXHAUSTED",
             "no statutory space remains for this participant")

    cert["status"] = "SUBMITTED"
    cert["submitted_at"] = db.now_iso()
    db.touch(cert)
    db.touch(employee)
    return object_response(serialize.loan_certification(cert))


@bp.post("/loan-certifications/<certification_id>/decision")
def decide_certification(certification_id):
    user_id, _role = auth("BenefitsAdministrator")
    payload = body()
    decision = req_enum(payload, "decision", DECISIONS)
    opt_str(payload, "reason")
    cert = lookup.certification(certification_id)

    plan_year = db.db.plan_years.get(cert["plan_year_id"])
    employee = db.db.employees.get(cert["employee_id"])
    if plan_year is None or plan_year["status"] != "OPEN":
        fail("ERR_PLAN_YEAR_LOCKED", "the plan year is not OPEN")
    _guard_not_terminal(cert)
    _guard_from_state(cert, ("SUBMITTED",))

    if decision == "ACCEPT":
        effective = [a for a in db.rows("plan_amendments")
                     if a["plan_year_id"] == plan_year["id"]
                     and a["status"] == "EFFECTIVE"]
        if not effective:
            fail("ERR_AMENDMENT_NOT_EFFECTIVE",
                 "no plan amendment of this plan year is EFFECTIVE")
        for line in calc.lines_of(cert["id"]):
            account = db.db.loan_accounts.get(line["loan_account_id"])
            if account is None or account["status"] != "VERIFIED":
                fail("ERR_LOAN_NOT_VERIFIED",
                     "a certified line references a loan that is not VERIFIED")
        effects.accept_certification(cert, plan_year, employee, user_id)
    else:
        cert["status"] = "RETURNED"
        cert["return_count"] += 1
        cert["decided_at"] = db.now_iso()
        db.touch(cert)
        db.touch(employee)

    return object_response(serialize.loan_certification(cert))


@bp.post("/loan-certifications/<certification_id>/audit-hold")
def audit_hold(certification_id):
    auth("ComplianceAuditor")
    payload = body()
    reason = req_str(payload, "reason")
    cert = lookup.certification(certification_id)
    _guard_not_terminal(cert)
    _guard_from_state(cert, ("ACCEPTED",))
    cert["status"] = "AUDIT_HOLD"
    cert["audit_hold_reason"] = reason
    db.touch(cert)
    return object_response(serialize.loan_certification(cert))


@bp.post("/loan-certifications/<certification_id>/audit-release")
def audit_release(certification_id):
    user_id, _role = auth("ComplianceAuditor")
    payload = body()
    resolution = req_enum(payload, "resolution", RESOLUTIONS)
    note = opt_str(payload, "note")
    cert = lookup.certification(certification_id)
    _guard_not_terminal(cert)
    _guard_from_state(cert, ("AUDIT_HOLD",))

    if resolution == "VOID":
        if cert["accepted_by_user_id"] is not None \
                and cert["accepted_by_user_id"] == user_id:
            fail("ERR_SEGREGATION_OF_DUTIES",
                 "the voiding caller accepted this claim")
        plan_year = db.db.plan_years.get(cert["plan_year_id"])
        employee = db.db.employees.get(cert["employee_id"])
        effects.void_certification(cert, plan_year, employee, user_id, note)
    else:
        cert["status"] = "ACCEPTED"
        cert["audit_hold_reason"] = None
        db.touch(cert)

    return object_response(serialize.loan_certification(cert))
