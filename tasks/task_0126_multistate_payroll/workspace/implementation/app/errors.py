"""Error class and Flask handlers — error IDs and HTTP codes per scaffold §1.6."""
from __future__ import annotations

from flask import Flask, jsonify

from .responses import error_envelope


class APIError(Exception):
    """Raised to surface a structured error response."""

    def __init__(self, error_id: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# ---------------------------------------------------------------------------
# Error factories — every id maps to scaffold's §1.6 error catalog.
# ---------------------------------------------------------------------------

def err_invalid_user_context(msg: str = "X-User-ID and X-User-Role headers are required and recognized") -> APIError:
    return APIError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", msg, 400)


def err_insufficient_permissions(msg: str = "Role is not authorized for this endpoint") -> APIError:
    return APIError("ERR_INSUFFICIENT_PERMISSIONS", msg, 403)


def err_employee_not_found(msg: str = "Employee not found") -> APIError:
    return APIError("ERR_EMPLOYEE_NOT_FOUND", msg, 404)


def err_w4_profile_not_found(msg: str = "W-4 profile not found") -> APIError:
    return APIError("ERR_W4_PROFILE_NOT_FOUND", msg, 404)


def err_pay_period_not_found(msg: str = "Pay period not found") -> APIError:
    return APIError("ERR_PAY_PERIOD_NOT_FOUND", msg, 404)


def err_payroll_item_not_found(msg: str = "Payroll item not found") -> APIError:
    return APIError("ERR_PAYROLL_ITEM_NOT_FOUND", msg, 404)


def err_paycheck_not_found(msg: str = "Paycheck not found") -> APIError:
    return APIError("ERR_PAYCHECK_NOT_FOUND", msg, 404)


def err_garnishment_not_found(msg: str = "Garnishment order not found") -> APIError:
    return APIError("ERR_GARNISHMENT_ORDER_NOT_FOUND", msg, 404)


def err_remittance_not_found(msg: str = "Remittance period not found") -> APIError:
    return APIError("ERR_REMITTANCE_NOT_FOUND", msg, 404)


def err_tax_bracket_not_found(msg: str = "Tax bracket table not found") -> APIError:
    return APIError("ERR_TAX_BRACKET_NOT_FOUND", msg, 404)


def err_pay_period_not_open(msg: str = "Pay period is not OPEN") -> APIError:
    return APIError("ERR_PAY_PERIOD_NOT_OPEN", msg, 409)


def err_pay_period_not_lockable(msg: str = "Pay period is not lockable") -> APIError:
    return APIError("ERR_PAY_PERIOD_NOT_LOCKABLE", msg, 409)


def err_paycheck_not_draft(msg: str = "Paycheck is not DRAFT") -> APIError:
    return APIError("ERR_PAYCHECK_NOT_DRAFT", msg, 409)


def err_paycheck_not_calculated(msg: str = "Paycheck is not CALCULATED") -> APIError:
    return APIError("ERR_PAYCHECK_NOT_CALCULATED", msg, 409)


def err_paycheck_not_approved(msg: str = "Paycheck is not APPROVED") -> APIError:
    return APIError("ERR_PAYCHECK_NOT_APPROVED", msg, 409)


def err_paycheck_not_correctable(msg: str = "Paycheck is not in APPROVED or PAID state") -> APIError:
    return APIError("ERR_PAYCHECK_NOT_CORRECTABLE", msg, 409)


def err_remittance_not_draft(msg: str = "Remittance is not DRAFT") -> APIError:
    return APIError("ERR_REMITTANCE_NOT_DRAFT", msg, 409)


def err_remittance_not_finalized(msg: str = "Remittance is not FINALIZED") -> APIError:
    return APIError("ERR_REMITTANCE_NOT_FINALIZED", msg, 409)


def err_remittance_not_remitted(msg: str = "Remittance is not REMITTED") -> APIError:
    return APIError("ERR_REMITTANCE_NOT_REMITTED", msg, 409)


def err_garnishment_not_active(msg: str = "Garnishment order is not ACTIVE") -> APIError:
    return APIError("ERR_GARNISHMENT_NOT_ACTIVE", msg, 409)


def err_segregation_of_duties(msg: str = "Segregation of duties violation") -> APIError:
    return APIError("ERR_SEGREGATION_OF_DUTIES", msg, 403)


def err_no_w4(msg: str = "No active W-4 profile for the employee at this pay period") -> APIError:
    return APIError("ERR_NO_W4", msg, 409)


def err_no_prior_year_w4(msg: str = "No prior-year W-4 profile to pre-fill from") -> APIError:
    return APIError("ERR_NO_PRIOR_YEAR_W4", msg, 409)


def err_terminated_employee(msg: str = "Employee is TERMINATED outside the final-settlement window") -> APIError:
    return APIError("ERR_TERMINATED_EMPLOYEE", msg, 409)


def err_pending_paychecks(msg: str = "Employee has DRAFT or CALCULATED paychecks") -> APIError:
    return APIError("ERR_PENDING_PAYCHECKS", msg, 409)


def err_invalid_pay_period_dates(msg: str = "Pay period dates are invalid") -> APIError:
    return APIError("ERR_INVALID_PAY_PERIOD_DATES", msg, 400)


def err_invalid_hours(msg: str = "Payroll item hours are invalid") -> APIError:
    return APIError("ERR_INVALID_HOURS", msg, 400)


def err_invalid_garnishment_cap(msg: str = "cap_pct_of_disposable must be 1..100") -> APIError:
    return APIError("ERR_INVALID_GARNISHMENT_CAP", msg, 400)


def err_duplicate_paycheck_for_employee(msg: str = "Paycheck already exists for this (pay_period, employee)") -> APIError:
    return APIError("ERR_DUPLICATE_PAYCHECK_FOR_EMPLOYEE", msg, 409)


def err_duplicate_remittance(msg: str = "Remittance already exists for (tax_year, tax_month)") -> APIError:
    return APIError("ERR_DUPLICATE_REMITTANCE", msg, 409)


def err_w4_prefill_already_done(msg: str = "Pre-fill already performed for this employee/tax_year") -> APIError:
    return APIError("ERR_W4_PREFILL_ALREADY_DONE", msg, 409)


def err_no_payroll_items(msg: str = "Pay period has no payroll items") -> APIError:
    return APIError("ERR_NO_PAYROLL_ITEMS", msg, 409)


def err_uncalculated_items(msg: str = "At least one paycheck is still in DRAFT") -> APIError:
    return APIError("ERR_UNCALCULATED_ITEMS", msg, 409)


def err_open_pay_periods_in_month(msg: str = "Not all PayPeriods in this month are CLOSED") -> APIError:
    return APIError("ERR_OPEN_PAY_PERIODS_IN_MONTH", msg, 409)


def err_unapproved_paychecks_in_month(msg: str = "Some paychecks in this month are not APPROVED/PAID/VOIDED") -> APIError:
    return APIError("ERR_UNAPPROVED_PAYCHECKS_IN_MONTH", msg, 409)


def err_no_amendment_basis(msg: str = "No correction paychecks to amend this remittance") -> APIError:
    return APIError("ERR_NO_AMENDMENT_BASIS", msg, 409)


def err_negative_net_pay(msg: str = "Approval would result in negative net pay") -> APIError:
    return APIError("ERR_NEGATIVE_NET_PAY", msg, 402)


def err_stale_data(msg: str = "Supplied version does not match server version") -> APIError:
    return APIError("ERR_STALE_DATA", msg, 409)


def err_invalid_request(msg: str = "Malformed request") -> APIError:
    return APIError("ERR_INVALID_REQUEST", msg, 400)


# ---------------------------------------------------------------------------
# Flask integration
# ---------------------------------------------------------------------------

def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(APIError)
    def _handle_api_error(exc: APIError):
        body = error_envelope(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(_exc):
        body = error_envelope("ERR_INVALID_REQUEST", "Route not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(_exc):
        body = error_envelope("ERR_INVALID_REQUEST", "Method not allowed for this path")
        return jsonify(body), 405

    @app.errorhandler(400)
    def _handle_400(_exc):
        body = error_envelope("ERR_INVALID_REQUEST", "Malformed request")
        return jsonify(body), 400

    @app.errorhandler(415)
    def _handle_415(_exc):
        body = error_envelope("ERR_INVALID_REQUEST", "Unsupported media type")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def _handle_unexpected(exc):  # pragma: no cover — defensive
        body = error_envelope("ERR_INVALID_REQUEST", f"Unexpected server error: {exc}")
        return jsonify(body), 400
