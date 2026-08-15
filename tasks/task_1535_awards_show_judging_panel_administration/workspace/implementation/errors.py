"""API error type carrying the scaffold-defined error_id and HTTP status."""


class ApiError(Exception):
    def __init__(self, error_id, status, message):
        super().__init__(message)
        self.error_id = error_id
        self.status = status
        self.message = message


# ---- auth / request shape ----
ERR_UNAUTHENTICATED = ("ERR_UNAUTHENTICATED", 401)
ERR_FORBIDDEN_ROLE = ("ERR_FORBIDDEN_ROLE", 403)
ERR_INVALID_REQUEST = ("ERR_INVALID_REQUEST", 400)
ERR_NOT_FOUND = ("ERR_NOT_FOUND", 404)
ERR_REFERENCE_NOT_FOUND = ("ERR_REFERENCE_NOT_FOUND", 404)

# ---- state (409) ----
ERR_INVALID_STATE = ("ERR_INVALID_STATE", 409)
ERR_ALREADY_TERMINAL = ("ERR_ALREADY_TERMINAL", 409)

# ---- OCC (412) ----
ERR_STALE_VERSION = ("ERR_STALE_VERSION", 412)

# ---- temporal / window (422) ----
ERR_OUTSIDE_WINDOW = ("ERR_OUTSIDE_WINDOW", 422)
ERR_ELIGIBILITY_WINDOW = ("ERR_ELIGIBILITY_WINDOW", 422)
ERR_CEREMONY_OVERLAP = ("ERR_CEREMONY_OVERLAP", 422)
ERR_ROUND_WINDOW_TOO_CLOSE = ("ERR_ROUND_WINDOW_TOO_CLOSE", 422)

# ---- business safety (422) ----
ERR_CONFLICT_OF_INTEREST = ("ERR_CONFLICT_OF_INTEREST", 422)
ERR_SEGREGATION_OF_DUTIES = ("ERR_SEGREGATION_OF_DUTIES", 422)

# ---- constraint / uniqueness ----
ERR_DUPLICATE = ("ERR_DUPLICATE", 409)
ERR_CONSTRAINT_VIOLATION = ("ERR_CONSTRAINT_VIOLATION", 422)

# ---- fiscal (402) ----
ERR_FISCAL_BLOCK = ("ERR_FISCAL_BLOCK", 402)

# ---- referential / panel / ballot (422) ----
ERR_PANEL_INCOMPLETE = ("ERR_PANEL_INCOMPLETE", 422)
ERR_INCOMPLETE_BALLOT = ("ERR_INCOMPLETE_BALLOT", 422)
ERR_REFERENTIAL_INTEGRITY = ("ERR_REFERENTIAL_INTEGRITY", 422)
ERR_APPEAL_CAP_EXCEEDED = ("ERR_APPEAL_CAP_EXCEEDED", 422)

# ---- embargo / audit ----
ERR_EMBARGO_ACTIVE = ("ERR_EMBARGO_ACTIVE", 403)
ERR_HASH_CHAIN_BROKEN = ("ERR_HASH_CHAIN_BROKEN", 409)


def raise_err(spec, message):
    raise ApiError(spec[0], spec[1], message)
