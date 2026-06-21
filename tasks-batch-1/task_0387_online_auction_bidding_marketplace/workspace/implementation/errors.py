"""Error classes and error-id constants.

Error IDs and HTTP statuses are taken verbatim from PRD §5 Error Code Catalogue
and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# PRD §5 Error Code Catalogue (error_id -> http status)
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"            # 403
ERR_NOT_OWNER = "ERR_NOT_OWNER"                      # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"             # 409
ERR_AUCTION_CLOSED = "ERR_AUCTION_CLOSED"           # 409
ERR_WINDOW_EXPIRED = "ERR_WINDOW_EXPIRED"           # 409
ERR_SELF_TRADING = "ERR_SELF_TRADING"               # 422
ERR_SELLER_SUSPENDED = "ERR_SELLER_SUSPENDED"       # 422
ERR_BID_TOO_LOW = "ERR_BID_TOO_LOW"                 # 422
ERR_OFFER_INVALID = "ERR_OFFER_INVALID"             # 422
ERR_OFFER_ROUND_LIMIT = "ERR_OFFER_ROUND_LIMIT"     # 422
ERR_RETRACT_NOT_ALLOWED = "ERR_RETRACT_NOT_ALLOWED" # 422
ERR_FEEDBACK_NOT_ELIGIBLE = "ERR_FEEDBACK_NOT_ELIGIBLE"  # 422
ERR_DISPUTE_NOT_ELIGIBLE = "ERR_DISPUTE_NOT_ELIGIBLE"    # 422
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"         # 422
ERR_REFUND_EXCEEDS_PAID = "ERR_REFUND_EXCEEDS_PAID" # 422
ERR_ACCOUNT_CLOSED = "ERR_ACCOUNT_CLOSED"           # 403


def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def forbidden_role(msg="Acting role is not permitted for this operation."):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_owner(msg="Acting account does not own the targeted resource."):
    return ApiError(ERR_NOT_OWNER, 403, msg)


def not_found(msg="Referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def stale_version(msg="The expected version does not match the current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="The requested transition is not defined from the current state."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def auction_closed(msg="The auction is closed or the listing is terminal."):
    return ApiError(ERR_AUCTION_CLOSED, 409, msg)


def window_expired(msg="The operation is outside its temporal window."):
    return ApiError(ERR_WINDOW_EXPIRED, 409, msg)


def self_trading(msg="A seller may not trade against their own listing."):
    return ApiError(ERR_SELF_TRADING, 422, msg)


def seller_suspended(msg="A suspended seller may not publish listings."):
    return ApiError(ERR_SELLER_SUSPENDED, 422, msg)


def bid_too_low(msg="The bid is below the minimum acceptable bid."):
    return ApiError(ERR_BID_TOO_LOW, 422, msg)


def offer_invalid(msg="The offer amount is out of range or the listing does not accept offers."):
    return ApiError(ERR_OFFER_INVALID, 422, msg)


def offer_round_limit(msg="The offer round cap has been reached."):
    return ApiError(ERR_OFFER_ROUND_LIMIT, 422, msg)


def retract_not_allowed(msg="The bid may not be retracted."):
    return ApiError(ERR_RETRACT_NOT_ALLOWED, 422, msg)


def feedback_not_eligible(msg="The order is not eligible for feedback."):
    return ApiError(ERR_FEEDBACK_NOT_ELIGIBLE, 422, msg)


def dispute_not_eligible(msg="The order is not eligible for a dispute."):
    return ApiError(ERR_DISPUTE_NOT_ELIGIBLE, 422, msg)


def invalid_request(msg="The request is missing a required field or violates a constraint."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def refund_exceeds_paid(msg="The approved amount exceeds the order's paid amount."):
    return ApiError(ERR_REFUND_EXCEEDS_PAID, 422, msg)


def account_closed(msg="A closed account may not perform any mutation."):
    return ApiError(ERR_ACCOUNT_CLOSED, 403, msg)
