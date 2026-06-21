"""P2P Small Business Lending API — Flask entry point.

In-memory store, no persistence; the store starts empty on every boot.
"""
import os
from decimal import Decimal

from flask import Flask, request

import calculations
import errors
import services
import validation as vld
from clock import clock, parse_iso8601, format_iso8601
from db import db, make_common, touch
from errors import ApiError
from middleware import require_auth
from response import success_object, success_list, error_response
from serializers import (
    serialize_borrower, serialize_application, serialize_loan,
    serialize_investor, serialize_investment, serialize_repayment,
    serialize_allocation, serialize_disclosure,
)

app = Flask(__name__)


# --------------------------------------------------------------------------- #
# Error handling
# --------------------------------------------------------------------------- #

@app.errorhandler(ApiError)
def handle_api_error(exc):
    return error_response(exc.error_id, exc.message, exc.http_status)


@app.errorhandler(404)
def handle_404(_exc):
    return error_response(errors.ERR_NOT_FOUND, "The requested route was not found.", 404)


@app.errorhandler(405)
def handle_405(_exc):
    return error_response(errors.ERR_NOT_FOUND, "Method not allowed.", 404)


@app.errorhandler(Exception)
def handle_unexpected(exc):
    if isinstance(exc, ApiError):
        return handle_api_error(exc)
    return error_response(errors.ERR_VALIDATION, "Unexpected error: %s" % exc, 400)


# --------------------------------------------------------------------------- #
# Generic list helper
# --------------------------------------------------------------------------- #

def list_response(rows, serializer):
    limit, offset = vld.parse_pagination()
    rows = sorted(rows, key=lambda r: r["_seq"])
    total = len(rows)
    page = vld.paginate(rows, limit, offset)
    items = [serializer(r) for r in page]
    return success_list(items, limit, offset, total)


# =========================================================================== #
# Borrowers
# =========================================================================== #

@app.route("/borrowers", methods=["POST"])
def create_borrower():
    # Self-registration: ERR_UNAUTHENTICATED does not apply; but if headers are
    # supplied the role must be permitted.
    require_auth({"Borrower", "PlatformAdmin"}, anonymous_ok=True)
    body = vld.get_body()

    business_name = vld.require_string(body, "business_name")
    ein = vld.require_string(body, "ein")
    state_code = vld.require_string(body, "state_code")

    # ein unique across borrowers.
    for b in db.borrowers.values():
        if b["ein"] == ein:
            raise errors.validation("ein must be unique across borrowers.")

    borrower = make_common(common_fields=True)
    borrower.update({
        "business_name": business_name,
        "ein": ein,
        "state_code": state_code,
        "status": "ACTIVE",
    })
    db.borrowers[borrower["id"]] = borrower
    return success_object(serialize_borrower(borrower), status=201)


@app.route("/borrowers/<bid>", methods=["GET"])
def get_borrower(bid):
    require_auth({"Borrower", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    b = services.get_borrower(bid)
    if b is None:
        raise errors.not_found("Borrower not found.")
    return success_object(serialize_borrower(b))


@app.route("/borrowers/<bid>/suspend", methods=["POST"])
def suspend_borrower(bid):
    require_auth({"PlatformAdmin"})
    b = services.get_borrower(bid)
    if b is None:
        raise errors.not_found("Borrower not found.")
    b["status"] = "SUSPENDED"
    touch(b)
    return success_object(serialize_borrower(b))


# =========================================================================== #
# Loan Applications
# =========================================================================== #

@app.route("/loan-applications", methods=["POST"])
def create_application():
    require_auth({"Borrower"})
    body = vld.get_body()

    borrower_id = vld.require_string(body, "borrower_id")
    requested_principal_cents = vld.require_int(body, "requested_principal_cents")
    term_months = vld.require_int(body, "term_months")
    plaid_avg = vld.require_int(body, "plaid_avg_monthly_revenue_cents")
    plaid_debt = vld.require_int(body, "plaid_monthly_debt_payment_cents")
    plaid_nsf = vld.require_int(body, "plaid_nsf_count_90d")
    plaid_age = vld.require_int(body, "plaid_account_age_months")

    # Constraint checks (ERR_VALIDATION) before existence? Existence is priority 3,
    # ERR_VALIDATION is a separate catch-all. We validate field constraints here;
    # existence of borrower_id is checked after the field shape is acceptable.
    if not (100000 <= requested_principal_cents <= 50000000):
        raise errors.validation("requested_principal_cents must be between 100000 and 50000000.")
    if term_months not in (12, 24, 36, 60):
        raise errors.validation("term_months must be one of 12, 24, 36, 60.")
    if plaid_avg < 0:
        raise errors.validation("plaid_avg_monthly_revenue_cents must be >= 0.")
    if plaid_debt < 0:
        raise errors.validation("plaid_monthly_debt_payment_cents must be >= 0.")
    if plaid_nsf < 0:
        raise errors.validation("plaid_nsf_count_90d must be >= 0.")
    if plaid_age < 0:
        raise errors.validation("plaid_account_age_months must be >= 0.")

    # Existence of referenced borrower.
    if services.get_borrower(borrower_id) is None:
        raise errors.not_found("Borrower not found.")

    appn = make_common(common_fields=True)
    appn.update({
        "borrower_id": borrower_id,
        "requested_principal_cents": requested_principal_cents,
        "term_months": term_months,
        "plaid_avg_monthly_revenue_cents": plaid_avg,
        "plaid_monthly_debt_payment_cents": plaid_debt,
        "plaid_nsf_count_90d": plaid_nsf,
        "plaid_account_age_months": plaid_age,
        "credit_score": None,
        "risk_grade": None,
        "offered_apr": None,
        "scored_by_user_id": None,
        "status": "SUBMITTED",
    })
    db.loan_applications[appn["id"]] = appn
    return success_object(serialize_application(appn), status=201)


@app.route("/loan-applications/<app_id>", methods=["GET"])
def get_application(app_id):
    require_auth({"Borrower", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    a = services.get_application(app_id)
    if a is None:
        raise errors.not_found("Loan application not found.")
    return success_object(serialize_application(a))


@app.route("/loan-applications", methods=["GET"])
def list_applications():
    require_auth({"Underwriter", "PlatformAdmin"})
    borrower_id = request.args.get("borrower_id")
    status = request.args.get("status")
    rows = list(db.loan_applications.values())
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize_application)


@app.route("/loan-applications/<app_id>/score", methods=["POST"])
def score_application(app_id):
    user_id, _role = require_auth({"Underwriter"})
    a = services.get_application(app_id)
    if a is None:
        raise errors.not_found("Loan application not found.")
    if a["status"] != "SUBMITTED":
        raise errors.invalid_state("Scoring requires a SUBMITTED application.")
    # Borrower must be ACTIVE.
    borrower = services.get_borrower(a["borrower_id"])
    if borrower is None:
        raise errors.not_found("Borrower not found.")
    if borrower["status"] != "ACTIVE":
        raise errors.invalid_state("Scoring requires the borrower to be ACTIVE.")
    services.score_application(a, user_id)
    return success_object(serialize_application(a))


@app.route("/loan-applications/<app_id>/approve", methods=["POST"])
def approve_application(app_id):
    user_id, _role = require_auth({"Underwriter"})
    a = services.get_application(app_id)
    if a is None:
        raise errors.not_found("Loan application not found.")
    if a["status"] != "SCORED":
        raise errors.invalid_state("Approval requires a SCORED application.")
    # Segregation of duties (priority 5) before fundability (priority 6).
    if user_id == a["scored_by_user_id"]:
        raise ApiError(errors.ERR_SEGREGATION_OF_DUTIES, 403,
                       "An underwriter may not approve an application they scored.")
    if a["risk_grade"] == "F":
        raise ApiError(errors.ERR_GRADE_NOT_FUNDABLE, 422,
                       "A grade-F application may not be approved.")
    services.approve_application(a)
    return success_object(serialize_application(a))


@app.route("/loan-applications/<app_id>/reject", methods=["POST"])
def reject_application(app_id):
    require_auth({"Underwriter"})
    a = services.get_application(app_id)
    if a is None:
        raise errors.not_found("Loan application not found.")
    if a["status"] != "SCORED":
        raise errors.invalid_state("Rejection requires a SCORED application.")
    services.reject_application(a)
    return success_object(serialize_application(a))


# =========================================================================== #
# Loans
# =========================================================================== #

@app.route("/loans/<loan_id>", methods=["GET"])
def get_loan(loan_id):
    require_auth({"Borrower", "Investor", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    return success_object(serialize_loan(loan))


@app.route("/loans", methods=["GET"])
def list_loans():
    require_auth({"Investor", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    application_id = request.args.get("application_id")
    borrower_id = request.args.get("borrower_id")
    status = request.args.get("status")
    rows = list(db.loans.values())
    if application_id is not None:
        rows = [r for r in rows if r["application_id"] == application_id]
    if borrower_id is not None:
        rows = [r for r in rows if r["borrower_id"] == borrower_id]
    if status is not None:
        rows = [r for r in rows if r["status"] == status]
    return list_response(rows, serialize_loan)


@app.route("/loans/<loan_id>/schedule", methods=["GET"])
def get_schedule(loan_id):
    require_auth({"Borrower", "Investor", "Underwriter", "PlatformAdmin"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    level_payment_cents, periods = calculations.amortization_schedule(
        loan["principal_cents"], loan["apr"], loan["term_months"])
    data = {
        "level_payment_cents": level_payment_cents,
        "periods": periods,
    }
    return success_object(data)


@app.route("/loans/<loan_id>/disburse", methods=["POST"])
def disburse_loan(loan_id):
    require_auth({"PlatformAdmin"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    if loan["status"] != "FUNDING":
        raise errors.invalid_state("Disburse requires a FUNDING loan.")
    services.disburse_loan(loan)
    return success_object(serialize_loan(loan))


@app.route("/loans/<loan_id>/assess-late-fee", methods=["POST"])
def assess_late_fee(loan_id):
    require_auth({"PlatformAdmin"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    if loan["status"] != "REPAYMENT":
        raise errors.invalid_state("Late-fee assessment requires a loan in REPAYMENT.")
    services.assess_late_fee(loan)
    return success_object(serialize_loan(loan))


@app.route("/loans/<loan_id>/charge-off", methods=["POST"])
def charge_off(loan_id):
    require_auth({"PlatformAdmin"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    if loan["status"] != "DEFAULTED":
        raise errors.invalid_state("Charge-off requires a DEFAULTED loan.")
    services.charge_off_loan(loan)
    return success_object(serialize_loan(loan))


@app.route("/loans/<loan_id>/repayments", methods=["POST"])
def create_repayment(loan_id):
    user_id, role = require_auth({"Borrower", "PlatformAdmin"})
    body = vld.get_body()

    amount_cents = vld.require_int(body, "amount_cents")
    if amount_cents < 1:
        raise errors.validation("amount_cents must be at least 1.")
    kind = vld.optional_string(body, "kind", "SCHEDULED")
    if kind not in ("SCHEDULED", "RECOVERY"):
        raise errors.validation("kind must be one of SCHEDULED or RECOVERY.")

    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")

    if kind == "SCHEDULED":
        if loan["status"] != "REPAYMENT":
            raise errors.invalid_state("A SCHEDULED repayment requires a loan in REPAYMENT.")
        repayment = services.process_scheduled_repayment(loan, amount_cents)
    else:  # RECOVERY
        # RECOVERY is a PlatformAdmin operation per RBAC.
        if role != "PlatformAdmin":
            raise errors.forbidden_role("RECOVERY repayments may only be posted by a PlatformAdmin.")
        if loan["status"] != "CHARGED_OFF":
            raise errors.invalid_state("A RECOVERY repayment requires a CHARGED_OFF loan.")
        repayment = services.process_recovery_repayment(loan, amount_cents)

    return success_object(serialize_repayment(repayment), status=201)


@app.route("/loans/<loan_id>/repayments", methods=["GET"])
def list_loan_repayments(loan_id):
    require_auth({"Borrower", "Investor", "Underwriter", "PlatformAdmin"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    rows = [r for r in db.repayments.values() if r["loan_id"] == loan_id]
    return list_response(rows, serialize_repayment)


@app.route("/loans/<loan_id>/investments", methods=["GET"])
def list_loan_investments(loan_id):
    require_auth({"Investor", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    rows = [i for i in db.investments.values() if i["loan_id"] == loan_id]
    return list_response(rows, serialize_investment)


@app.route("/loans/<loan_id>/compliance-disclosures", methods=["GET"])
def list_loan_disclosures(loan_id):
    require_auth({"Investor", "Underwriter", "PlatformAdmin", "ComplianceOfficer"})
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")
    document_type = request.args.get("document_type")
    status = request.args.get("status")
    rows = [d for d in db.compliance_disclosures.values() if d["loan_id"] == loan_id]
    if document_type is not None:
        rows = [d for d in rows if d["document_type"] == document_type]
    if status is not None:
        rows = [d for d in rows if d["status"] == status]
    return list_response(rows, serialize_disclosure)


# =========================================================================== #
# Repayments
# =========================================================================== #

@app.route("/repayments/<repayment_id>", methods=["GET"])
def get_repayment(repayment_id):
    require_auth({"Borrower", "Investor", "Underwriter", "PlatformAdmin"})
    r = services.get_repayment(repayment_id)
    if r is None:
        raise errors.not_found("Repayment not found.")
    return success_object(serialize_repayment(r))


@app.route("/repayments/<repayment_id>/allocations", methods=["GET"])
def list_repayment_allocations(repayment_id):
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    r = services.get_repayment(repayment_id)
    if r is None:
        raise errors.not_found("Repayment not found.")
    rows = [a for a in db.repayment_allocations.values() if a["repayment_id"] == repayment_id]
    return list_response(rows, serialize_allocation)


# =========================================================================== #
# Investors
# =========================================================================== #

@app.route("/investors", methods=["POST"])
def create_investor():
    require_auth({"Investor", "PlatformAdmin"}, anonymous_ok=True)
    body = vld.get_body()

    display_name = vld.require_string(body, "display_name")
    max_pct = vld.optional_number(body, "max_single_loan_pct", None)
    if max_pct is None:
        max_single_loan_pct = Decimal("0.25")
    else:
        max_dec = Decimal(str(max_pct))
        if not (max_dec > 0 and max_dec <= 1):
            raise errors.validation("max_single_loan_pct must be > 0 and <= 1.")
        max_single_loan_pct = max_dec

    investor = make_common(common_fields=True)
    investor.update({
        "display_name": display_name,
        "capital_base_cents": 0,
        "committed_capital_cents": 0,
        "max_single_loan_pct": max_single_loan_pct,
        "status": "ACTIVE",
    })
    db.investors[investor["id"]] = investor
    return success_object(serialize_investor(investor), status=201)


@app.route("/investors/<investor_id>", methods=["GET"])
def get_investor(investor_id):
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    inv = services.get_investor(investor_id)
    if inv is None:
        raise errors.not_found("Investor not found.")
    return success_object(serialize_investor(inv))


@app.route("/investors/<investor_id>/suspend", methods=["POST"])
def suspend_investor(investor_id):
    require_auth({"PlatformAdmin"})
    inv = services.get_investor(investor_id)
    if inv is None:
        raise errors.not_found("Investor not found.")
    inv["status"] = "SUSPENDED"
    touch(inv)
    return success_object(serialize_investor(inv))


@app.route("/investors/<investor_id>/deposit", methods=["POST"])
def deposit_investor(investor_id):
    require_auth({"Investor", "PlatformAdmin"})
    body = vld.get_body()
    amount_cents = vld.require_int(body, "amount_cents")
    if amount_cents < 1:
        raise errors.validation("amount_cents must be at least 1.")
    inv = services.get_investor(investor_id)
    if inv is None:
        raise errors.not_found("Investor not found.")
    inv["capital_base_cents"] += amount_cents
    touch(inv)
    return success_object(serialize_investor(inv))


# =========================================================================== #
# Investments
# =========================================================================== #

@app.route("/investments", methods=["POST"])
def create_investment():
    require_auth({"Investor"})
    body = vld.get_body()

    investor_id = vld.require_string(body, "investor_id")
    loan_id = vld.require_string(body, "loan_id")
    amount_cents = vld.require_int(body, "amount_cents")
    expected_loan_version = vld.require_int(body, "expected_loan_version")

    if amount_cents < 2500:
        raise errors.validation("amount_cents must be at least 2500.")

    # Existence left-to-right: investor_id then loan_id.
    investor = services.get_investor(investor_id)
    if investor is None:
        raise errors.not_found("Investor not found.")
    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")

    investment = services.commit_investment(investor, loan, amount_cents, expected_loan_version)
    return success_object(serialize_investment(investment), status=201)


@app.route("/investments/<investment_id>", methods=["GET"])
def get_investment(investment_id):
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    inv = services.get_investment(investment_id)
    if inv is None:
        raise errors.not_found("Investment not found.")
    return success_object(serialize_investment(inv))


@app.route("/investments", methods=["GET"])
def list_investments():
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    investor_id = request.args.get("investor_id")
    loan_id = request.args.get("loan_id")
    rows = list(db.investments.values())
    if investor_id is not None:
        rows = [r for r in rows if r["investor_id"] == investor_id]
    if loan_id is not None:
        rows = [r for r in rows if r["loan_id"] == loan_id]
    return list_response(rows, serialize_investment)


@app.route("/investments/<investment_id>/allocations", methods=["GET"])
def list_investment_allocations(investment_id):
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    inv = services.get_investment(investment_id)
    if inv is None:
        raise errors.not_found("Investment not found.")
    rows = [a for a in db.repayment_allocations.values() if a["investment_id"] == investment_id]
    return list_response(rows, serialize_allocation)


# =========================================================================== #
# Compliance Disclosures
# =========================================================================== #

@app.route("/compliance-disclosures", methods=["POST"])
def create_disclosure():
    user_id, _role = require_auth({"ComplianceOfficer"})
    body = vld.get_body()

    loan_id = vld.require_string(body, "loan_id")
    document_type = vld.require_string(body, "document_type")
    if document_type not in ("SERIES_NOTE_PROSPECTUS", "RISK_FACTORS", "ANNUAL_REPORT"):
        raise errors.validation("document_type must be one of SERIES_NOTE_PROSPECTUS, RISK_FACTORS, ANNUAL_REPORT.")

    loan = services.get_loan(loan_id)
    if loan is None:
        raise errors.not_found("Loan not found.")

    disclosure = services.file_disclosure(loan_id, document_type, user_id)
    return success_object(serialize_disclosure(disclosure), status=201)


@app.route("/compliance-disclosures/<disclosure_id>", methods=["GET"])
def get_disclosure(disclosure_id):
    require_auth({"Investor", "PlatformAdmin", "ComplianceOfficer"})
    d = services.get_disclosure(disclosure_id)
    if d is None:
        raise errors.not_found("Compliance disclosure not found.")
    return success_object(serialize_disclosure(d))


# =========================================================================== #
# Logical clock (test-driving)
# =========================================================================== #

@app.route("/_clock/set_current_utc", methods=["POST"])
def set_clock():
    require_auth({"PlatformAdmin"})
    body = vld.get_body()
    to_iso = vld.require_string(body, "to_iso8601")
    try:
        dt = parse_iso8601(to_iso)
    except (ValueError, TypeError):
        raise errors.validation("to_iso8601 must be a valid ISO 8601 timestamp.")
    clock.set(dt)
    return success_object({"current_utc": format_iso8601(dt)})


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port, threaded=True)
