"""Error classes and error ID constants for the Production Insurance API.

All error identifiers and HTTP statuses are read from SCAFFOLD.yaml Table 6
and PRD.md section 5.
"""


class ApiError(Exception):
    """Carries error_id, message and http_status through to the handler."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# --- Error catalog (id -> http status) -------------------------------------
ERRORS = {
    "ERR_UNAUTHENTICATED": 401,
    "ERR_FORBIDDEN": 403,
    "ERR_SELF_SETTLEMENT_FORBIDDEN": 403,
    "ERR_NOT_FOUND": 404,
    "ERR_INVALID_STATE": 409,
    "ERR_DUPLICATE_IDENTIFIER": 409,
    "ERR_STALE_VERSION": 412,
    "ERR_INVALID_ENUM": 400,
    "ERR_INVALID_REQUEST": 400,
    "ERR_ADDITIONAL_INSURED_REQUIRED": 400,
    "ERR_TEMPORAL_RANGE_INVALID": 422,
    "ERR_CERT_WINDOW_OUTSIDE_POLICY": 422,
    "ERR_WINDOW_ELAPSED": 422,
    "ERR_FOREIGN_TRAVEL_OVERLAP": 422,
    "ERR_POSTURE_BLOCKS_ISSUANCE": 422,
    "ERR_POSTURE_BLOCKS_BOND": 422,
    "ERR_POSTURE_BLOCKS_FOREIGN": 422,
    "ERR_COVERAGE_LINE_NOT_BOUND": 422,
    "ERR_CAST_ENDORSEMENT_INVALID": 422,
    "ERR_CAST_ENDORSEMENT_MISSING": 422,
    "ERR_CAST_EXAM_INCOMPLETE": 422,
    "ERR_EO_CLEARANCE_INCOMPLETE": 422,
    "ERR_GL_PREREQUISITE_MISSING": 422,
    "ERR_NO_BOUND_POLICY": 422,
    "ERR_BOND_NOT_ISSUED": 422,
    "ERR_MANDATORY_CLEARANCE_OPEN": 422,
    "ERR_OPEN_CLAIMS_BLOCK_WRAP": 422,
    "ERR_OPEN_CLAIMS_BLOCK_CANCEL": 422,
    "ERR_OPEN_CLAIMS_BLOCK_POLICY_CANCEL": 422,
    "ERR_DRAFT_CERTIFICATES_OPEN": 422,
    "ERR_POLICY_NOT_CLAIMABLE": 422,
    "ERR_REFERENCED_STATE_INVALID": 422,
    "ERR_SETTLEMENT_EXCEEDS_RESERVE": 422,
    "ERR_FISCAL_CONSTRAINT_VIOLATED": 422,
    "ERR_DEDUCTIBLE_CAP_EXCEEDED": 422,
    "ERR_AUDIT_PENDING_BLOCKS_RENEWAL": 422,
    "ERR_RENEWAL_OFFER_EXPIRED": 422,
    # Used by certificate issuance when the production is not ACTIVE.
    # Named in the state machine / PRD section 3.5 but absent from the
    # catalog; business-gate semantics => 422.
    "ERR_PRODUCTION_NOT_ACTIVE": 422,
}


def err(error_id, message):
    """Build an ApiError using the cataloged HTTP status for error_id."""
    return ApiError(error_id, ERRORS[error_id], message)
