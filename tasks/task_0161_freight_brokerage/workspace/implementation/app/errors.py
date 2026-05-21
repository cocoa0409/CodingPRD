"""Error catalogue and Flask handlers (PRD §5 / SCAFFOLD §1.6)."""

from __future__ import annotations

from typing import Optional

from flask import Flask, jsonify

from .envelope import build_meta


class ApiError(Exception):
    """Structured API error carrying error_id, http_status, and message."""

    def __init__(self, error_id: str, http_status: int, message: Optional[str] = None) -> None:
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Authentication / Authorisation ---
ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER = "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER"
ERR_INSUFFICIENT_PERMISSIONS = "ERR_INSUFFICIENT_PERMISSIONS"

# --- Not found ---
ERR_BROKERAGE_NOT_FOUND = "ERR_BROKERAGE_NOT_FOUND"
ERR_SHIPPER_NOT_FOUND = "ERR_SHIPPER_NOT_FOUND"
ERR_CARRIER_NOT_FOUND = "ERR_CARRIER_NOT_FOUND"
ERR_QUOTE_REQUEST_NOT_FOUND = "ERR_QUOTE_REQUEST_NOT_FOUND"
ERR_RATE_CONTRACT_NOT_FOUND = "ERR_RATE_CONTRACT_NOT_FOUND"
ERR_LOAD_NOT_FOUND = "ERR_LOAD_NOT_FOUND"
ERR_ACCESSORIAL_CHARGE_NOT_FOUND = "ERR_ACCESSORIAL_CHARGE_NOT_FOUND"
ERR_INVOICE_NOT_FOUND = "ERR_INVOICE_NOT_FOUND"
ERR_DISPUTE_CLAIM_NOT_FOUND = "ERR_DISPUTE_CLAIM_NOT_FOUND"

# --- Input validation ---
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_CARRIER_AUTHORITY = "ERR_INVALID_CARRIER_AUTHORITY"
ERR_INVALID_DELIVERY_TIMES = "ERR_INVALID_DELIVERY_TIMES"
ERR_COUNTER_OFFER_INVALID = "ERR_COUNTER_OFFER_INVALID"
ERR_SETTLED_CREDIT_INVALID = "ERR_SETTLED_CREDIT_INVALID"
ERR_CLAIM_AMOUNT_INVALID = "ERR_CLAIM_AMOUNT_INVALID"

# --- Carrier qualification / safety ---
ERR_INSURANCE_EXPIRED = "ERR_INSURANCE_EXPIRED"
ERR_SMARTWAY_REQUIRED = "ERR_SMARTWAY_REQUIRED"
ERR_SAFETY_SCORE_TOO_LOW = "ERR_SAFETY_SCORE_TOO_LOW"
ERR_CARRIER_AUTHORITY_DUPLICATE = "ERR_CARRIER_AUTHORITY_DUPLICATE"
ERR_CARRIER_HAS_OPEN_LOADS = "ERR_CARRIER_HAS_OPEN_LOADS"

# --- State preconditions ---
ERR_SHIPPER_SUSPENDED = "ERR_SHIPPER_SUSPENDED"
ERR_QUOTE_NOT_OPEN = "ERR_QUOTE_NOT_OPEN"
ERR_QUOTE_NOT_QUOTED = "ERR_QUOTE_NOT_QUOTED"
ERR_QUOTE_EXPIRED = "ERR_QUOTE_EXPIRED"
ERR_QUOTE_NOT_ACCEPTED = "ERR_QUOTE_NOT_ACCEPTED"
ERR_LOAD_NOT_TENDERED = "ERR_LOAD_NOT_TENDERED"
ERR_LOAD_NOT_ACCEPTED = "ERR_LOAD_NOT_ACCEPTED"
ERR_LOAD_NOT_IN_TRANSIT = "ERR_LOAD_NOT_IN_TRANSIT"
ERR_LOAD_NOT_DELIVERED = "ERR_LOAD_NOT_DELIVERED"
ERR_LOAD_NOT_CANCELLABLE = "ERR_LOAD_NOT_CANCELLABLE"
ERR_CARRIER_NOT_PENDING = "ERR_CARRIER_NOT_PENDING"
ERR_CARRIER_NOT_QUALIFIED = "ERR_CARRIER_NOT_QUALIFIED"
ERR_CARRIER_NOT_SUSPENDED = "ERR_CARRIER_NOT_SUSPENDED"
ERR_ACCESSORIAL_NOT_REQUESTED = "ERR_ACCESSORIAL_NOT_REQUESTED"
ERR_ACCESSORIAL_PENDING = "ERR_ACCESSORIAL_PENDING"

# --- Invoice / factoring / dispute states ---
ERR_INVOICE_NOT_FACTORABLE = "ERR_INVOICE_NOT_FACTORABLE"
ERR_INVOICE_HAS_OPEN_DISPUTE = "ERR_INVOICE_HAS_OPEN_DISPUTE"
ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING = "ERR_INVOICE_NOT_DISPUTABLE_AFTER_FACTORING"
ERR_INVOICE_NOTHING_TO_WRITE_OFF = "ERR_INVOICE_NOTHING_TO_WRITE_OFF"
ERR_CLAIM_NOT_OPEN = "ERR_CLAIM_NOT_OPEN"
ERR_CLAIM_NOT_IN_REVIEW = "ERR_CLAIM_NOT_IN_REVIEW"
ERR_CLAIM_NOT_COUNTER_OFFERED = "ERR_CLAIM_NOT_COUNTER_OFFERED"

# --- Rate contracts ---
ERR_RATE_CONTRACT_OVERLAP = "ERR_RATE_CONTRACT_OVERLAP"
ERR_RATE_CONTRACT_AMBIGUOUS = "ERR_RATE_CONTRACT_AMBIGUOUS"

# --- Fiscal ---
ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED = "ERR_SHIPPER_CREDIT_LIMIT_EXCEEDED"

# --- Optimistic concurrency ---
ERR_STALE_DATA = "ERR_STALE_DATA"


def make_error_body(error_id: str, message: str) -> dict:
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {"error_id": error_id, "message": message},
    }


def register_error_handlers(app: Flask) -> None:
    @app.errorhandler(ApiError)
    def handle_api_error(err: ApiError):
        body = make_error_body(err.error_id, err.message)
        return jsonify(body), err.http_status

    @app.errorhandler(404)
    def handle_404(_err):
        # Any unmapped path falls through to here; we surface a 404 with our
        # envelope.  The brokerage-not-found case is explicitly raised inside
        # the route handlers as ERR_BROKERAGE_NOT_FOUND.
        body = make_error_body(ERR_BROKERAGE_NOT_FOUND, "Resource path not found.")
        return jsonify(body), 404

    @app.errorhandler(405)
    def handle_405(_err):
        body = make_error_body(ERR_INVALID_REQUEST, "Method not allowed.")
        return jsonify(body), 400

    @app.errorhandler(400)
    def handle_400(_err):
        body = make_error_body(ERR_INVALID_REQUEST, "Malformed request body.")
        return jsonify(body), 400

    @app.errorhandler(Exception)
    def handle_unexpected(err):  # pragma: no cover — defensive only
        body = make_error_body(ERR_INVALID_REQUEST, f"Unhandled: {err}")
        return jsonify(body), 400
