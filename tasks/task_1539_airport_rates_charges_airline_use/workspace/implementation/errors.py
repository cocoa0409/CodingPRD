"""Error taxonomy: exact error ids and HTTP statuses from the scaffold catalog."""


class ApiError(Exception):
    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# -- catalog ---------------------------------------------------------------
def invalid_request(msg="Required field missing, wrong type, or enum value outside declared set"):
    return ApiError("ERR_INVALID_REQUEST", 400, msg)


def unauthenticated(msg="X-User-ID / X-User-Role header missing or role unrecognized"):
    return ApiError("ERR_UNAUTHENTICATED", 401, msg)


def forbidden(msg="Role not permitted for this endpoint"):
    return ApiError("ERR_FORBIDDEN", 403, msg)


def not_found(msg="Path id does not resolve"):
    return ApiError("ERR_NOT_FOUND", 404, msg)


def fk_not_found(msg="Body FK reference does not resolve"):
    return ApiError("ERR_FK_NOT_FOUND", 422, msg)


def invalid_state(msg="Resource in wrong state for this transition"):
    return ApiError("ERR_INVALID_STATE", 409, msg)


def stale_version(msg="Expected version does not match current version"):
    return ApiError("ERR_STALE_VERSION", 412, msg)


def temporal_violation(msg="Logical clock outside allowed window"):
    return ApiError("ERR_TEMPORAL_VIOLATION", 422, msg)


def fiscal_year_closed(msg="FiscalYear is CLOSED; writes blocked"):
    return ApiError("ERR_FISCAL_YEAR_CLOSED", 409, msg)


def airline_suspended(msg="Airline credit standing is SUSPENDED"):
    return ApiError("ERR_AIRLINE_SUSPENDED", 409, msg)


def not_signatory(msg="Voting airline does not hold an active SIGNATORY agreement on this fiscal year"):
    return ApiError("ERR_NOT_SIGNATORY", 422, msg)


def duplicate_vote(msg="Airline has already voted on this CapitalProject"):
    return ApiError("ERR_DUPLICATE_VOTE", 409, msg)


def project_already_decided(msg="CapitalProject no longer accepts votes"):
    return ApiError("ERR_PROJECT_ALREADY_DECIDED", 409, msg)


def rate_not_derivable(msg="Rate derivation divisor zero or terminal pool exceeded"):
    return ApiError("ERR_RATE_NOT_DERIVABLE", 422, msg)


def no_activity(msg="Settlement compute requires at least one ActivityRecord"):
    return ApiError("ERR_NO_ACTIVITY", 422, msg)


def unsettled_lines(msg="Finalize blocked: at least one settlement line still PENDING"):
    return ApiError("ERR_UNSETTLED_LINES", 409, msg)


def pfc_ineligible(msg="Carrier is not PFC eligible (must be PASSENGER class with PFC approval)"):
    return ApiError("ERR_PFC_INELIGIBLE", 422, msg)


def countersign_lapsed(msg="Logical clock is past the countersign deadline"):
    return ApiError("ERR_COUNTERSIGN_LAPSED", 422, msg)


def methodology_mismatch(msg="Operation valid only under a different methodology"):
    return ApiError("ERR_METHODOLOGY_MISMATCH", 422, msg)


def dispute_window_expired(msg="Dispute raised outside the dispute window"):
    return ApiError("ERR_DISPUTE_WINDOW_EXPIRED", 422, msg)


def agreement_superseded(msg="AirlineAgreement has been superseded; mutations blocked"):
    return ApiError("ERR_AGREEMENT_SUPERSEDED", 409, msg)


def double_countersign(msg="Agreement is already SIGNATORY"):
    return ApiError("ERR_DOUBLE_COUNTERSIGN", 409, msg)
