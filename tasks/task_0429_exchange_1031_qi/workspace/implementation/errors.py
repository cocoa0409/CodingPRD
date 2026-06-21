"""Error classes and error-id constants.

Every error_id and HTTP status is taken verbatim from SCAFFOLD.yaml §1.6 / PRD §5.
"""


class ApiError(Exception):
    """A domain error carrying a machine-readable id, message, and HTTP status."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) ---
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
ERR_ID_DEADLINE_PASSED = "ERR_ID_DEADLINE_PASSED"
ERR_EXCHANGE_DEADLINE_PASSED = "ERR_EXCHANGE_DEADLINE_PASSED"
ERR_THREE_PROPERTY_RULE_VIOLATED = "ERR_THREE_PROPERTY_RULE_VIOLATED"
ERR_TWO_HUNDRED_PCT_RULE_VIOLATED = "ERR_TWO_HUNDRED_PCT_RULE_VIOLATED"
ERR_NOT_IDENTIFIED = "ERR_NOT_IDENTIFIED"
ERR_TRUST_LOCKED = "ERR_TRUST_LOCKED"
ERR_INSUFFICIENT_TRUST_FUNDS = "ERR_INSUFFICIENT_TRUST_FUNDS"
ERR_STALE_TRUST_VERSION = "ERR_STALE_TRUST_VERSION"
ERR_DUPLICATE_TAXPAYER_ID = "ERR_DUPLICATE_TAXPAYER_ID"
ERR_TRUST_ALREADY_EXISTS = "ERR_TRUST_ALREADY_EXISTS"


def unauthenticated(msg="Missing or malformed authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="The acting role is not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def not_found(msg="The referenced resource does not exist."):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="The request body is missing or invalid."):
    return ApiError(ERR_INVALID_REQUEST, 422, msg)


def invalid_state(msg="The target entity is not in a state from which this transition is defined."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def segregation_of_duties(msg="The approving officer is the same operator as the exchange coordinator."):
    return ApiError(ERR_SEGREGATION_OF_DUTIES, 403, msg)


def id_deadline_passed(msg="Identification finalize attempted after the 45-day identification deadline."):
    return ApiError(ERR_ID_DEADLINE_PASSED, 409, msg)


def exchange_deadline_passed(msg="Operation attempted after the 180-day exchange deadline."):
    return ApiError(ERR_EXCHANGE_DEADLINE_PASSED, 409, msg)


def three_property_rule_violated(msg="THREE_PROPERTY identification finalize with more than 3 candidate properties."):
    return ApiError(ERR_THREE_PROPERTY_RULE_VIOLATED, 409, msg)


def two_hundred_pct_rule_violated(msg="TWO_HUNDRED_PCT identification aggregate candidate FMV exceeds 200% of relinquished FMV."):
    return ApiError(ERR_TWO_HUNDRED_PCT_RULE_VIOLATED, 409, msg)


def not_identified(msg="Replacement references a candidate not under this exchange's finalized identification or already withdrawn."):
    return ApiError(ERR_NOT_IDENTIFIED, 409, msg)


def trust_locked(msg="The qualified trust is locked; no new disbursement create or approval is allowed."):
    return ApiError(ERR_TRUST_LOCKED, 409, msg)


def insufficient_trust_funds(msg="Disbursement approval amount exceeds the trust's available balance."):
    return ApiError(ERR_INSUFFICIENT_TRUST_FUNDS, 409, msg)


def stale_trust_version(msg="expected_qualified_trust_version does not match the trust's current version."):
    return ApiError(ERR_STALE_TRUST_VERSION, 412, msg)


def duplicate_taxpayer_id(msg="An exchanger with this taxpayer_id already exists."):
    return ApiError(ERR_DUPLICATE_TAXPAYER_ID, 409, msg)


def trust_already_exists(msg="This exchange already has a qualified trust."):
    return ApiError(ERR_TRUST_ALREADY_EXISTS, 409, msg)
