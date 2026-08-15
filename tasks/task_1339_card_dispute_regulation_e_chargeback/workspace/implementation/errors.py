"""Error classes and error ID constants for the Card Dispute & Reg E API."""


class ApiError(Exception):
    """Exception carrying the scaffold-defined error triple."""

    def __init__(self, error_id, http_status, message):
        super().__init__(message)
        self.error_id = error_id
        self.http_status = http_status
        self.message = message


# Error ID constants (from SCAFFOLD.yaml §1.6 / PRD §5)
ERR_MISSING_AUTH = "ERR_MISSING_AUTH"
ERR_FORBIDDEN = "ERR_FORBIDDEN"
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
ERR_NOT_FOUND = "ERR_NOT_FOUND"
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DUPLICATE_ACTIVE_DISPUTE = "ERR_DUPLICATE_ACTIVE_DISPUTE"
ERR_ACCOUNT_RESTRICTED = "ERR_ACCOUNT_RESTRICTED"
ERR_STALE_VERSION = "ERR_STALE_VERSION"
ERR_SOD_VIOLATION = "ERR_SOD_VIOLATION"
ERR_PROVISIONAL_CREDIT_REQUIRED = "ERR_PROVISIONAL_CREDIT_REQUIRED"
ERR_INVESTIGATION_WINDOW_EXPIRED = "ERR_INVESTIGATION_WINDOW_EXPIRED"
ERR_NETWORK_DEADLINE_PASSED = "ERR_NETWORK_DEADLINE_PASSED"
ERR_REVERSAL_NOTICE_PENDING = "ERR_REVERSAL_NOTICE_PENDING"
ERR_NETWORK_WINDOW_ACTIVE = "ERR_NETWORK_WINDOW_ACTIVE"
ERR_REASON_CODE_MISMATCH = "ERR_REASON_CODE_MISMATCH"
ERR_EVIDENCE_REQUIRED = "ERR_EVIDENCE_REQUIRED"
ERR_CLAIM_EXCEEDS_TRANSACTION = "ERR_CLAIM_EXCEEDS_TRANSACTION"
ERR_LOSS_EXCEEDS_OUTSTANDING = "ERR_LOSS_EXCEEDS_OUTSTANDING"


def missing_auth(message="X-User-ID or X-User-Role header missing or unrecognized"):
    return ApiError(ERR_MISSING_AUTH, 400, message)


def forbidden(message="Role not permitted for this endpoint, or ownership check failed"):
    return ApiError(ERR_FORBIDDEN, 403, message)


def invalid_request(message="Request body failed schema validation"):
    return ApiError(ERR_INVALID_REQUEST, 400, message)


def not_found(message="Referenced resource id does not exist"):
    return ApiError(ERR_NOT_FOUND, 404, message)


def invalid_state(message="Entity not in a from-state permitted for the requested transition"):
    return ApiError(ERR_INVALID_STATE, 409, message)


def duplicate_active_dispute(message="CardTransaction already referenced by a non-terminal DisputeCase"):
    return ApiError(ERR_DUPLICATE_ACTIVE_DISPUTE, 409, message)


def account_restricted(message="POST /card-transactions against a RESTRICTED account"):
    return ApiError(ERR_ACCOUNT_RESTRICTED, 409, message)


def stale_version(message="expected_dispute_version does not match current DisputeCase.version"):
    return ApiError(ERR_STALE_VERSION, 412, message)


def sod_violation(message="Resolving investigator is the same X-User-ID as the intake agent"):
    return ApiError(ERR_SOD_VIOLATION, 403, message)


def provisional_credit_required(message="Resolve attempted after provisional_credit_due_at with no credit ever granted"):
    return ApiError(ERR_PROVISIONAL_CREDIT_REQUIRED, 422, message)


def investigation_window_expired(message="NO_ERROR resolution attempted after investigation_deadline_at"):
    return ApiError(ERR_INVESTIGATION_WINDOW_EXPIRED, 422, message)


def network_deadline_passed(message="Chargeback filing attempted after network_filing_deadline_at"):
    return ApiError(ERR_NETWORK_DEADLINE_PASSED, 422, message)


def reversal_notice_pending(message="Manual credit reversal before 3 business days elapsed since REVERSAL_NOTICE"):
    return ApiError(ERR_REVERSAL_NOTICE_PENDING, 422, message)


def network_window_active(message="Another chargeback on the same transaction occupies its response window"):
    return ApiError(ERR_NETWORK_WINDOW_ACTIVE, 409, message)


def reason_code_mismatch(message="Reason code does not match transaction network or fraud classification"):
    return ApiError(ERR_REASON_CODE_MISMATCH, 422, message)


def evidence_required(message="Representment submitted with an empty evidence_documents array"):
    return ApiError(ERR_EVIDENCE_REQUIRED, 422, message)


def claim_exceeds_transaction(message="claim_amount_cents exceeds the transaction's amount_cents"):
    return ApiError(ERR_CLAIM_EXCEEDS_TRANSACTION, 422, message)


def loss_exceeds_outstanding(message="Manual RECOVERY_RECEIVED exceeds outstanding_loss_cents"):
    return ApiError(ERR_LOSS_EXCEEDS_OUTSTANDING, 422, message)
