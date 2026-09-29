"""Error catalogue: every error_id the PRD publishes, with its HTTP status.

Registering the map with the framework lets validate_error() check the status
line automatically whenever a test names an error_id.
"""

from prd_bench_local_runner.testing.validators import set_error_http_status_map

# --------------------------------------------------------------------------
# Authentication and authorisation
# --------------------------------------------------------------------------
ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
ERR_FORBIDDEN_ROLE = "ERR_FORBIDDEN_ROLE"
ERR_NOT_RESOURCE_OWNER = "ERR_NOT_RESOURCE_OWNER"

# --------------------------------------------------------------------------
# Request shape
# --------------------------------------------------------------------------
ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"

# --------------------------------------------------------------------------
# Existence
# --------------------------------------------------------------------------
ERR_INTEROP_PROFILE_NOT_FOUND = "ERR_INTEROP_PROFILE_NOT_FOUND"
ERR_HOLDER_NOT_FOUND = "ERR_HOLDER_NOT_FOUND"
ERR_PROOFING_SESSION_NOT_FOUND = "ERR_PROOFING_SESSION_NOT_FOUND"
ERR_DEVICE_NOT_FOUND = "ERR_DEVICE_NOT_FOUND"
ERR_CREDENTIAL_NOT_FOUND = "ERR_CREDENTIAL_NOT_FOUND"
ERR_UPDATE_ORDER_NOT_FOUND = "ERR_UPDATE_ORDER_NOT_FOUND"
ERR_UPDATE_DELIVERY_NOT_FOUND = "ERR_UPDATE_DELIVERY_NOT_FOUND"
ERR_VERIFIER_NOT_FOUND = "ERR_VERIFIER_NOT_FOUND"
ERR_READER_APP_NOT_FOUND = "ERR_READER_APP_NOT_FOUND"
ERR_PRESENTATION_SESSION_NOT_FOUND = "ERR_PRESENTATION_SESSION_NOT_FOUND"

# --------------------------------------------------------------------------
# State
# --------------------------------------------------------------------------
ERR_INVALID_STATE = "ERR_INVALID_STATE"
ERR_DELIVERY_NOT_PENDING = "ERR_DELIVERY_NOT_PENDING"
ERR_SESSION_NOT_CONSENT_PENDING = "ERR_SESSION_NOT_CONSENT_PENDING"
ERR_BILLING_ALREADY_VOIDED = "ERR_BILLING_ALREADY_VOIDED"

# --------------------------------------------------------------------------
# Optimistic concurrency
# --------------------------------------------------------------------------
ERR_STALE_DEVICE_VERSION = "ERR_STALE_DEVICE_VERSION"
ERR_STALE_INTEROP_VERSION = "ERR_STALE_INTEROP_VERSION"

# --------------------------------------------------------------------------
# Segregation of duties
# --------------------------------------------------------------------------
ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"

# --------------------------------------------------------------------------
# Privacy and presentation policy
# --------------------------------------------------------------------------
ERR_HANDSET_SURRENDER_PROHIBITED = "ERR_HANDSET_SURRENDER_PROHIBITED"
ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED = (
    "ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED"
)
ERR_READER_NOT_TRUSTED = "ERR_READER_NOT_TRUSTED"
ERR_VERIFIER_NOT_TRUSTED = "ERR_VERIFIER_NOT_TRUSTED"
ERR_DATA_MINIMIZATION_VIOLATION = "ERR_DATA_MINIMIZATION_VIOLATION"
ERR_RETENTION_CEILING_EXCEEDED = "ERR_RETENTION_CEILING_EXCEEDED"

# --------------------------------------------------------------------------
# Device binding
# --------------------------------------------------------------------------
ERR_DEVICE_BINDING_MISMATCH = "ERR_DEVICE_BINDING_MISMATCH"
ERR_DEVICE_NOT_BOUND = "ERR_DEVICE_NOT_BOUND"
ERR_PROTECTION_METHOD_MISMATCH = "ERR_PROTECTION_METHOD_MISMATCH"

# --------------------------------------------------------------------------
# Eligibility, assurance and caps
# --------------------------------------------------------------------------
ERR_PHYSICAL_CREDENTIAL_INELIGIBLE = "ERR_PHYSICAL_CREDENTIAL_INELIGIBLE"
ERR_PROOFING_ASSURANCE_EXPIRED = "ERR_PROOFING_ASSURANCE_EXPIRED"
ERR_ASSURANCE_LEVEL_INSUFFICIENT = "ERR_ASSURANCE_LEVEL_INSUFFICIENT"
ERR_INSUFFICIENT_EVIDENCE = "ERR_INSUFFICIENT_EVIDENCE"
ERR_DEVICE_LIMIT_EXCEEDED = "ERR_DEVICE_LIMIT_EXCEEDED"
ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED = "ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED"

# --------------------------------------------------------------------------
# Interval and uniqueness conflicts
# --------------------------------------------------------------------------
ERR_CREDENTIAL_VALIDITY_OVERLAP = "ERR_CREDENTIAL_VALIDITY_OVERLAP"
ERR_TRUST_LIST_WINDOW_OVERLAP = "ERR_TRUST_LIST_WINDOW_OVERLAP"
ERR_TRUST_LIST_WINDOW_GAP = "ERR_TRUST_LIST_WINDOW_GAP"
ERR_CERT_WINDOW_CONFLICT = "ERR_CERT_WINDOW_CONFLICT"
ERR_DUPLICATE_READER_APP = "ERR_DUPLICATE_READER_APP"

# --------------------------------------------------------------------------
# Revocation distribution and billing
# --------------------------------------------------------------------------
ERR_REVOCATION_STATUS_STALE = "ERR_REVOCATION_STATUS_STALE"
ERR_VERIFIER_ACCOUNT_DELINQUENT = "ERR_VERIFIER_ACCOUNT_DELINQUENT"


ERROR_HTTP_STATUS = {
    ERR_UNAUTHENTICATED: 401,
    ERR_FORBIDDEN_ROLE: 403,
    ERR_INVALID_REQUEST: 400,
    ERR_INTEROP_PROFILE_NOT_FOUND: 404,
    ERR_HOLDER_NOT_FOUND: 404,
    ERR_PROOFING_SESSION_NOT_FOUND: 404,
    ERR_DEVICE_NOT_FOUND: 404,
    ERR_CREDENTIAL_NOT_FOUND: 404,
    ERR_UPDATE_ORDER_NOT_FOUND: 404,
    ERR_UPDATE_DELIVERY_NOT_FOUND: 404,
    ERR_VERIFIER_NOT_FOUND: 404,
    ERR_READER_APP_NOT_FOUND: 404,
    ERR_PRESENTATION_SESSION_NOT_FOUND: 404,
    ERR_NOT_RESOURCE_OWNER: 403,
    ERR_INVALID_STATE: 409,
    ERR_DELIVERY_NOT_PENDING: 409,
    ERR_SESSION_NOT_CONSENT_PENDING: 409,
    ERR_BILLING_ALREADY_VOIDED: 409,
    ERR_STALE_DEVICE_VERSION: 412,
    ERR_STALE_INTEROP_VERSION: 412,
    ERR_SEGREGATION_OF_DUTIES: 409,
    ERR_HANDSET_SURRENDER_PROHIBITED: 422,
    ERR_LAW_ENFORCEMENT_CONTEXT_NOT_PERMITTED: 403,
    ERR_READER_NOT_TRUSTED: 403,
    ERR_VERIFIER_NOT_TRUSTED: 403,
    ERR_DEVICE_BINDING_MISMATCH: 409,
    ERR_DEVICE_NOT_BOUND: 409,
    ERR_PHYSICAL_CREDENTIAL_INELIGIBLE: 422,
    ERR_PROOFING_ASSURANCE_EXPIRED: 409,
    ERR_CREDENTIAL_VALIDITY_OVERLAP: 409,
    ERR_TRUST_LIST_WINDOW_OVERLAP: 409,
    ERR_TRUST_LIST_WINDOW_GAP: 422,
    ERR_CERT_WINDOW_CONFLICT: 422,
    ERR_DUPLICATE_READER_APP: 409,
    ERR_ASSURANCE_LEVEL_INSUFFICIENT: 422,
    ERR_DEVICE_LIMIT_EXCEEDED: 409,
    ERR_ACTIVE_CREDENTIAL_LIMIT_EXCEEDED: 409,
    ERR_DATA_MINIMIZATION_VIOLATION: 422,
    ERR_PROTECTION_METHOD_MISMATCH: 422,
    ERR_REVOCATION_STATUS_STALE: 409,
    ERR_INSUFFICIENT_EVIDENCE: 422,
    ERR_RETENTION_CEILING_EXCEEDED: 422,
    ERR_VERIFIER_ACCOUNT_DELINQUENT: 402,
}

set_error_http_status_map(ERROR_HTTP_STATUS)
