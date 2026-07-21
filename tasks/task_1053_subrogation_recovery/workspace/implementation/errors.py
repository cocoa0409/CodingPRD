"""Error catalog (§1.6 / PRD §5)."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


def missing_headers():
    return ApiError("ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", 400,
                    "X-User-ID or X-User-Role header missing or malformed")


def forbidden_role():
    return ApiError("ERR_FORBIDDEN_FOR_ROLE", 403,
                    "Role is not permitted for this endpoint")


def not_found():
    return ApiError("ERR_NOT_FOUND", 404, "Referenced resource does not exist")


def not_claim_owner():
    return ApiError("ERR_NOT_CLAIM_OWNER", 403,
                    "CarrierUser does not own this claim")


def invalid_request(msg="Malformed request body"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def sod():
    return ApiError("ERR_SEGREGATION_OF_DUTIES", 403,
                    "Approver may not be the settlement proposer")


def invalid_state(msg="Resource is not in a state that permits this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def adverse_not_arbitrable():
    return ApiError("ERR_ADVERSE_NOT_ARBITRABLE", 409,
                    "Adverse party is not arbitration eligible")


def demand_not_disputed():
    return ApiError("ERR_DEMAND_NOT_DISPUTED", 409,
                    "No disputed demand exists for this claim")


def statute_expired():
    return ApiError("ERR_STATUTE_EXPIRED", 409,
                    "Action attempted at or after the claim's statute deadline")


def arbitration_window_closed():
    return ApiError("ERR_ARBITRATION_WINDOW_CLOSED", 409,
                    "Arbitration filed at or after the disputed demand's window")


def demand_window_open():
    return ApiError("ERR_DEMAND_WINDOW_OPEN", 409,
                    "An existing demand's response window is still open")


def hearing_window_conflict():
    return ApiError("ERR_HEARING_WINDOW_CONFLICT", 409,
                    "Hearing window conflicts with another hearing on the same adverse party")


def exceeds_authority():
    return ApiError("ERR_EXCEEDS_SETTLEMENT_AUTHORITY", 409,
                    "Settlement amount exceeds managerial authority")


def payment_exceeds_settlement():
    return ApiError("ERR_PAYMENT_EXCEEDS_SETTLEMENT", 422,
                    "Cumulative cleared payments plus this amount exceed the settled amount")


def carrier_suspended():
    return ApiError("ERR_CARRIER_SUSPENDED", 409, "Carrier is suspended")


def statement_not_open():
    return ApiError("ERR_STATEMENT_NOT_OPEN", 409,
                    "Commission statement is not OPEN or has no lines")


def stale_claim_version():
    return ApiError("ERR_STALE_CLAIM_VERSION", 412,
                    "expected_claim_version does not match the claim's current version")
