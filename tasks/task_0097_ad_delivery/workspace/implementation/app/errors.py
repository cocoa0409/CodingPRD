"""Error catalog and Flask error-handler registration."""
from flask import jsonify, request
from werkzeug.exceptions import HTTPException

from .response import build_meta


# Mapping of error_id -> (http_status, default_message)
ERROR_CATALOG = {
    # auth
    "ERR_MISSING_USER_CONTEXT": (401, "X-User-ID or X-User-Role header is missing."),
    "ERR_FORBIDDEN_ROLE": (403, "Role is not authorised for this operation."),
    "ERR_SEGREGATION_OF_DUTIES_VIOLATION": (403, "Reviewer cannot decide a creative belonging to their own advertiser."),
    "ERR_APPEAL_SAME_REVIEWER": (403, "Appeal decider must not be the original rejection reviewer."),

    # validation
    "ERR_INVALID_REQUEST": (400, "The request is malformed or missing required fields."),
    "ERR_INVALID_FREQUENCY_CAP": (400, "frequency_cap_per_user_per_day must be >= 1."),
    "ERR_EMPTY_AUCTION_POOL": (400, "candidate_ad_group_ids must contain at least one id."),
    "ERR_INVALID_ATTRIBUTION_WINDOW": (400, "attribution_window_days must be within [1, 90]."),
    "ERR_INVALID_CAMPAIGN_DATES": (400, "start_date must be on or before end_date."),

    # existence
    "ERR_ADVERTISER_NOT_FOUND": (404, "Advertiser not found."),
    "ERR_CAMPAIGN_NOT_FOUND": (404, "Campaign not found."),
    "ERR_AD_GROUP_NOT_FOUND": (404, "Ad-group not found."),
    "ERR_CREATIVE_NOT_FOUND": (404, "Creative not found."),
    "ERR_QUALIFICATION_DOC_NOT_FOUND": (404, "Qualification document not found."),
    "ERR_BILLING_EVENT_NOT_FOUND": (404, "Billing event not found."),
    "ERR_CONVERSION_NOT_FOUND": (404, "Conversion not found."),
    "ERR_WALLET_TX_NOT_FOUND": (404, "Wallet transaction not found."),
    "ERR_AUDIENCE_NOT_FOUND": (422, "Remarketing audience id is unknown."),

    # state
    "ERR_ADVERTISER_SUSPENDED": (409, "Advertiser is SUSPENDED."),
    "ERR_ADVERTISER_CLOSED": (409, "Advertiser is CLOSED."),
    "ERR_ADVERTISER_NOT_ACTIVE": (409, "Advertiser must be ACTIVE for this operation."),
    "ERR_INVALID_CAMPAIGN_STATE": (409, "Campaign is not in a state that permits this operation."),
    "ERR_INVALID_AD_GROUP_STATE": (409, "Ad-group is not in a state that permits this operation."),
    "ERR_INVALID_CREATIVE_STATE": (409, "Creative is not in a state that permits this operation."),
    "ERR_REVIEW_ALREADY_DECIDED": (409, "Creative is no longer in PENDING_HUMAN_REVIEW."),
    "ERR_APPEAL_ALREADY_FILED": (409, "Creative already has an appeal filed."),
    "ERR_INVALID_BILLING_EVENT_STATE": (409, "Billing event is not in a state that permits this operation."),
    "ERR_DUPLICATE_BILLING_EVENT": (409, "Duplicate (event_type, auction_event_id, dedup_key) detected."),
    "ERR_QUALIFICATION_REQUIRED": (422, "Advertiser qualification must be VERIFIED for regulated industries."),
    "ERR_DISCLAIMER_REQUIRED": (422, "required_disclaimer must be present for regulated industries."),

    # fiscal
    "ERR_INVALID_BUDGET": (422, "Budget shape is invalid."),
    "ERR_INVALID_CREDIT_LINE": (422, "credit_line_cents incompatible with billing_mode."),
    "ERR_ZERO_BALANCE": (402, "Cannot activate while balance_state is ZERO_BALANCE."),
    "ERR_INSUFFICIENT_BALANCE": (402, "Operation would breach available balance."),
    "ERR_REFUND_WOULD_BREACH_CREDIT_FLOOR": (409, "Refund/reversal would breach the credit floor."),
    "ERR_IDEMPOTENCY_CONFLICT": (409, "Wallet transaction with same idempotency key already exists."),
    "ERR_CANNOT_CLOSE_WITH_ACTIVE_CAMPAIGNS": (409, "Cannot close advertiser while a campaign is ACTIVE."),
}


class ApiError(Exception):
    def __init__(self, error_id: str, message: str | None = None, http_status: int | None = None):
        default_status, default_message = ERROR_CATALOG.get(error_id, (400, "Unknown error."))
        self.error_id = error_id
        self.message = message or default_message
        self.http_status = http_status or default_status
        super().__init__(self.message)


def _error_body(error_id: str, message: str) -> dict:
    return {
        "meta": build_meta(),
        "response_type": "error",
        "data": {
            "error_id": error_id,
            "message": message,
        },
    }


def register_error_handlers(app):
    @app.errorhandler(ApiError)
    def _handle_api_error(exc: ApiError):
        body = _error_body(exc.error_id, exc.message)
        return jsonify(body), exc.http_status

    @app.errorhandler(404)
    def _handle_404(exc):
        # Path not matched by any route — return a generic invalid-request envelope.
        body = _error_body("ERR_INVALID_REQUEST", f"No route matched: {request.path}")
        return jsonify(body), 404

    @app.errorhandler(405)
    def _handle_405(exc):
        body = _error_body("ERR_INVALID_REQUEST", f"Method {request.method} not allowed for {request.path}")
        return jsonify(body), 405

    @app.errorhandler(HTTPException)
    def _handle_http(exc: HTTPException):
        body = _error_body("ERR_INVALID_REQUEST", exc.description or "HTTP error.")
        return jsonify(body), exc.code or 400

    @app.errorhandler(Exception)
    def _handle_uncaught(exc: Exception):
        body = _error_body("ERR_INVALID_REQUEST", str(exc))
        return jsonify(body), 400
