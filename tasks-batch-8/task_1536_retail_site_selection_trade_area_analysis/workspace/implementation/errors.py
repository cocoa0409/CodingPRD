"""Error classes and error ID constants (from the scaffold error catalog)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


ERR_MISSING_AUTH_HEADER = "ERR_MISSING_AUTH_HEADER"          # 401
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"                    # 403
ERR_NOT_FOUND = "ERR_NOT_FOUND"                              # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"                  # 400
ERR_STALE_VERSION = "ERR_STALE_VERSION"                      # 412
ERR_INVALID_STATE = "ERR_INVALID_STATE"                      # 409
ERR_ALREADY_TERMINAL = "ERR_ALREADY_TERMINAL"                # 409
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"      # 403
ERR_VOTER_INELIGIBLE = "ERR_VOTER_INELIGIBLE"                # 403
ERR_NOT_CHAIR = "ERR_NOT_CHAIR"                              # 403
ERR_DUPLICATE_VOTE = "ERR_DUPLICATE_VOTE"                    # 409
ERR_DUPLICATE_STORE_CODE = "ERR_DUPLICATE_STORE_CODE"        # 409
ERR_CREW_CODE_TAKEN = "ERR_CREW_CODE_TAKEN"                  # 409
ERR_CHAIR_CONFLICT = "ERR_CHAIR_CONFLICT"                    # 409
ERR_DUPLICATE_MILESTONE = "ERR_DUPLICATE_MILESTONE"          # 409
ERR_LOI_EXCLUSIVITY_OVERLAP = "ERR_LOI_EXCLUSIVITY_OVERLAP"  # 409
ERR_FORMAT_SQFT_MISMATCH = "ERR_FORMAT_SQFT_MISMATCH"        # 422
ERR_WINDOW_IN_PAST = "ERR_WINDOW_IN_PAST"                    # 422
ERR_DEADLINE_IN_PAST = "ERR_DEADLINE_IN_PAST"                # 422
ERR_CREW_WINDOW_CONFLICT = "ERR_CREW_WINDOW_CONFLICT"        # 409
ERR_MILESTONE_OUT_OF_ORDER = "ERR_MILESTONE_OUT_OF_ORDER"    # 409
ERR_PERIOD_GAP = "ERR_PERIOD_GAP"                            # 422
ERR_MARKET_NOT_QUALIFIED = "ERR_MARKET_NOT_QUALIFIED"        # 409
ERR_TRADE_AREA_NOT_LOCKED = "ERR_TRADE_AREA_NOT_LOCKED"      # 409
ERR_FORECAST_NOT_LOCKED = "ERR_FORECAST_NOT_LOCKED"          # 409
ERR_LOI_NOT_ACCEPTED = "ERR_LOI_NOT_ACCEPTED"                # 409
ERR_CREW_NOT_AVAILABLE = "ERR_CREW_NOT_AVAILABLE"            # 409
ERR_BUILD_NOT_COMPLETE = "ERR_BUILD_NOT_COMPLETE"            # 409
ERR_SITE_NOT_OPEN = "ERR_SITE_NOT_OPEN"                      # 409
ERR_ASKING_RENT_ABOVE_MARKET_CAP = "ERR_ASKING_RENT_ABOVE_MARKET_CAP"  # 422
ERR_CANNIBALIZATION_EXCEEDS_CAP = "ERR_CANNIBALIZATION_EXCEEDS_CAP"    # 422
ERR_OCCUPANCY_RATIO_RED = "ERR_OCCUPANCY_RATIO_RED"          # 422
ERR_CHAIR_OVERRIDE_REQUIRED = "ERR_CHAIR_OVERRIDE_REQUIRED"  # 422
ERR_BUDGET_CAP_EXCEEDED = "ERR_BUDGET_CAP_EXCEEDED"          # 422
ERR_LEASE_TERMS_DRIFT = "ERR_LEASE_TERMS_DRIFT"              # 422
ERR_NO_ELIGIBLE_VOTERS = "ERR_NO_ELIGIBLE_VOTERS"            # 422


def missing_auth(msg="Authentication headers missing or role not declared"):
    return ApiError(ERR_MISSING_AUTH_HEADER, 401, msg)


def forbidden(msg="Acting role is not authorized for this endpoint"):
    return ApiError(ERR_FORBIDDEN_ROLE, 403, msg)


def not_found(msg="Referenced resource does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, msg)


def invalid_request(msg="Request body failed validation"):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def invalid_state(msg="Resource state does not permit this transition"):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def already_terminal(msg="Resource is in a terminal state"):
    return ApiError(ERR_ALREADY_TERMINAL, 409, msg)
