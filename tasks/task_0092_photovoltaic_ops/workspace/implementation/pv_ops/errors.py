"""Error classes, error-id constants, and the central error handler."""
from __future__ import annotations

from typing import Optional

from flask import Flask, jsonify


# ---- Error ID constants ----
ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
ERR_VALIDATION = "ERR_VALIDATION"
ERR_SUPPLIER_BLACKLISTED = "ERR_SUPPLIER_BLACKLISTED"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_DEFECT_PARENT_SUBJECT_MISMATCH = "ERR_DEFECT_PARENT_SUBJECT_MISMATCH"
ERR_SETTLEMENT_NOT_CONFIRMED = "ERR_SETTLEMENT_NOT_CONFIRMED"
ERR_PERIOD_NOT_ENDED = "ERR_PERIOD_NOT_ENDED"
ERR_NO_METERING_RECORDS = "ERR_NO_METERING_RECORDS"
ERR_SETTLEMENT_PERIOD_OVERLAP = "ERR_SETTLEMENT_PERIOD_OVERLAP"
ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE = "ERR_SUBSIDY_INELIGIBLE_BY_COMMISSIONING_DATE"
ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW = "ERR_SUBSIDY_OUT_OF_ELIGIBILITY_WINDOW"
ERR_DOCUMENTS_INCOMPLETE = "ERR_DOCUMENTS_INCOMPLETE"
ERR_MARKET_TRADING_DISABLED = "ERR_MARKET_TRADING_DISABLED"
ERR_MARKET_PRICE_REQUIRED = "ERR_MARKET_PRICE_REQUIRED"
ERR_INVESTOR_SHARES_INVALID = "ERR_INVESTOR_SHARES_INVALID"
ERR_SPARE_PART_INSUFFICIENT = "ERR_SPARE_PART_INSUFFICIENT"
ERR_SUBSIDY_BELOW_THRESHOLD = "ERR_SUBSIDY_BELOW_THRESHOLD"
ERR_RECONCILIATION_OUT_OF_TOLERANCE = "ERR_RECONCILIATION_OUT_OF_TOLERANCE"
ERR_ALARM_INFO_NOT_ACKABLE = "ERR_ALARM_INFO_NOT_ACKABLE"
ERR_ALARM_ALREADY_ACKED = "ERR_ALARM_ALREADY_ACKED"
ERR_ALARM_DEDUP_RACE = "ERR_ALARM_DEDUP_RACE"
ERR_ALARM_CODE_UNMAPPED = "ERR_ALARM_CODE_UNMAPPED"
ERR_INVOICE_DUPLICATE = "ERR_INVOICE_DUPLICATE"
ERR_UNIQUE_VIOLATION = "ERR_UNIQUE_VIOLATION"


class APIError(Exception):
    def __init__(self, error_id: str, http_status: int, message: Optional[str] = None) -> None:
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id
        super().__init__(self.message)


def register_error_handlers(app: Flask) -> None:
    from pv_ops.responses import build_error_envelope

    @app.errorhandler(APIError)
    def handle_api_error(err: APIError):
        body = build_error_envelope(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(_e):
        body = build_error_envelope(ERR_NOT_FOUND, "Resource not found")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_e):
        body = build_error_envelope(ERR_VALIDATION, "Method not allowed")
        return jsonify(body), 405

    @app.errorhandler(400)
    def handle_400(_e):
        body = build_error_envelope(ERR_VALIDATION, "Bad request")
        return jsonify(body), 422

    @app.errorhandler(Exception)
    def handle_uncaught(e: Exception):
        body = build_error_envelope(ERR_VALIDATION, str(e))
        return jsonify(body), 422
