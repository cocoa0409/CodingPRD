"""Error classes and error-id constants.

Every error_id and http_status here is taken verbatim from PRD §5 (Error Code
Catalogue) and SCAFFOLD §1.6.
"""


class ApiError(Exception):
    """An error carrying an error_id, a human-readable message, and an HTTP status."""

    def __init__(self, error_id, http_status, message=None):
        super().__init__(message or error_id)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message or error_id


# --- Error catalogue (PRD §5 / SCAFFOLD §1.6) --------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"            # 401
ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"                  # 403
ERR_CONTRACT_NOT_FOUND = "ERR_CONTRACT_NOT_FOUND"      # 404
ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"      # 404
ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"    # 404
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"            # 400
ERR_INVALID_STATE = "ERR_INVALID_STATE"               # 409
ERR_STALE_VERSION = "ERR_STALE_VERSION"               # 412
ERR_NO_VERSION = "ERR_NO_VERSION"                      # 409
ERR_SELF_APPROVAL = "ERR_SELF_APPROVAL"               # 403
ERR_MANDATORY_CLAUSE_MISSING = "ERR_MANDATORY_CLAUSE_MISSING"  # 409
ERR_DEVIATION_REQUIRED = "ERR_DEVIATION_REQUIRED"     # 409
ERR_DEVIATION_STALE = "ERR_DEVIATION_STALE"           # 409
ERR_SIGNERS_INCOMPLETE = "ERR_SIGNERS_INCOMPLETE"     # 409
ERR_RENEWAL_NOT_DUE = "ERR_RENEWAL_NOT_DUE"           # 409
ERR_OPEN_BREACH = "ERR_OPEN_BREACH"                   # 409
ERR_DUPLICATE_CLAUSE_KEY = "ERR_DUPLICATE_CLAUSE_KEY"  # 409
ERR_CLAUSE_IN_USE = "ERR_CLAUSE_IN_USE"               # 409
ERR_TEMPLATE_IN_USE = "ERR_TEMPLATE_IN_USE"           # 409
ERR_VALIDATION_RANGE = "ERR_VALIDATION_RANGE"         # 422


# Convenience constructors -----------------------------------------------------
def unauthenticated(msg="Missing or invalid authentication headers."):
    return ApiError(ERR_UNAUTHENTICATED, 401, msg)


def unauthorized(msg="Role not permitted for this operation."):
    return ApiError(ERR_UNAUTHORIZED, 403, msg)


def contract_not_found(msg="Contract not found."):
    return ApiError(ERR_CONTRACT_NOT_FOUND, 404, msg)


def resource_not_found(msg="Resource not found."):
    return ApiError(ERR_RESOURCE_NOT_FOUND, 404, msg)


def reference_not_found(msg="Referenced resource not found."):
    return ApiError(ERR_REFERENCE_NOT_FOUND, 404, msg)


def invalid_request(msg="Invalid request payload."):
    return ApiError(ERR_INVALID_REQUEST, 400, msg)


def invalid_state(msg="Resource is not in a valid state for this transition."):
    return ApiError(ERR_INVALID_STATE, 409, msg)


def stale_version(msg="Expected version does not match current version."):
    return ApiError(ERR_STALE_VERSION, 412, msg)


def no_version(msg="Contract has no version yet."):
    return ApiError(ERR_NO_VERSION, 409, msg)


def self_approval(msg="Segregation of duties violation."):
    return ApiError(ERR_SELF_APPROVAL, 403, msg)


def mandatory_clause_missing(msg="A mandatory clause is missing from the version."):
    return ApiError(ERR_MANDATORY_CLAUSE_MISSING, 409, msg)


def deviation_required(msg="Deviation approval required before signature."):
    return ApiError(ERR_DEVIATION_REQUIRED, 409, msg)


def deviation_stale(msg="Deviation approval version is no longer current."):
    return ApiError(ERR_DEVIATION_STALE, 409, msg)


def signers_incomplete(msg="Signer list must include INTERNAL and COUNTERPARTY."):
    return ApiError(ERR_SIGNERS_INCOMPLETE, 409, msg)


def renewal_not_due(msg="No renewal alert is due for this contract."):
    return ApiError(ERR_RENEWAL_NOT_DUE, 409, msg)


def open_breach(msg="Contract has a breached obligation."):
    return ApiError(ERR_OPEN_BREACH, 409, msg)


def duplicate_clause_key(msg="clause_key already used by an active clause."):
    return ApiError(ERR_DUPLICATE_CLAUSE_KEY, 409, msg)


def clause_in_use(msg="Clause template is in use by a working contract."):
    return ApiError(ERR_CLAUSE_IN_USE, 409, msg)


def template_in_use(msg="Contract template is in use by a working contract."):
    return ApiError(ERR_TEMPLATE_IN_USE, 409, msg)


def validation_range(msg="Numeric input out of declared range."):
    return ApiError(ERR_VALIDATION_RANGE, 422, msg)
