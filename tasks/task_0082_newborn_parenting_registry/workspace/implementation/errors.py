"""Error classes and error ID constants.

Every error_id and HTTP status here is taken verbatim from SCAFFOLD.yaml §1.6
and PRD §5 (the error catalogue).
"""


class APIError(Exception):
    def __init__(self, error_id: str, message: str, http_status: int):
        super().__init__(message)
        self.error_id = error_id
        self.message = message
        self.http_status = http_status


# --- Auth -------------------------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"          # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                # 403

# --- Existence / structural -------------------------------------------------
ERR_NOT_FOUND = "ERR_NOT_FOUND"                      # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"          # 400

# --- State / OCC ------------------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"              # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"              # 412

# --- Business rules ---------------------------------------------------------
ERR_NICU_CRITERIA_MET = "ERR_NICU_CRITERIA_MET"                  # 422
ERR_NICU_CRITERIA_NOT_MET = "ERR_NICU_CRITERIA_NOT_MET"          # 422
ERR_PHARMACY_SIGNOFF_REQUIRED = "ERR_PHARMACY_SIGNOFF_REQUIRED"  # 422
ERR_BIRTH_CERT_PREREQUISITE = "ERR_BIRTH_CERT_PREREQUISITE"      # 422
ERR_DISCHARGE_PREREQUISITE = "ERR_DISCHARGE_PREREQUISITE"        # 422
ERR_LEGAL_NAME_REQUIRED = "ERR_LEGAL_NAME_REQUIRED"              # 422
ERR_SEP_WINDOW_CLOSED = "ERR_SEP_WINDOW_CLOSED"                  # 422
ERR_READINESS_BELOW_THRESHOLD = "ERR_READINESS_BELOW_THRESHOLD"  # 422
ERR_DUPLICATE_BIRTH_SEQUENCE = "ERR_DUPLICATE_BIRTH_SEQUENCE"    # 409
ERR_NO_ACTIVE_NICU_STAY = "ERR_NO_ACTIVE_NICU_STAY"              # 422
ERR_DEPENDENT_SLOTS_EXHAUSTED = "ERR_DEPENDENT_SLOTS_EXHAUSTED"  # 422
ERR_ADMIT_WINDOW_CLOSED = "ERR_ADMIT_WINDOW_CLOSED"              # 422
ERR_BAG_ALREADY_ISSUED = "ERR_BAG_ALREADY_ISSUED"                # 409
ERR_BED_INTERVAL_OVERLAP = "ERR_BED_INTERVAL_OVERLAP"            # 409
ERR_CONSULT_BUFFER_CONFLICT = "ERR_CONSULT_BUFFER_CONFLICT"      # 409
ERR_VALIDATION = "ERR_VALIDATION"                                # 422


# --- Helper constructors ----------------------------------------------------
def unauthenticated(msg: str = "Missing or invalid X-User-ID / X-User-Role header.") -> APIError:
    return APIError(ERR_UNAUTHENTICATED, msg, 401)


def unauthorized(msg: str = "Role is not authorized for this operation.") -> APIError:
    return APIError(ERR_UNAUTHORIZED, msg, 403)


def not_found(msg: str = "Resource not found.") -> APIError:
    return APIError(ERR_NOT_FOUND, msg, 404)


def invalid_request(msg: str = "Malformed or missing request fields.") -> APIError:
    return APIError(ERR_INVALID_REQUEST, msg, 400)


def invalid_state(msg: str = "Resource is not in a state that permits this transition.") -> APIError:
    return APIError(ERR_INVALID_STATE, msg, 409)


def stale_version(msg: str = "Expected version does not match the current version.") -> APIError:
    return APIError(ERR_STALE_VERSION, msg, 412)
