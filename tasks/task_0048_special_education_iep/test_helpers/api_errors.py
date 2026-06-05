"""Error IDs and HTTP status mapping (PRD §5).

After defining the mapping we register it with the framework so
`validate_error()` cross-checks the HTTP status automatically.
"""
from enum import Enum
from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"
    ERR_INVALID_REQUEST = "ERR_INVALID_REQUEST"
    ERR_INVALID_RANGE = "ERR_INVALID_RANGE"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_STALE_VERSION = "ERR_STALE_VERSION"
    ERR_CONSENT_NOT_GRANTED = "ERR_CONSENT_NOT_GRANTED"
    ERR_STUDENT_NOT_ELIGIBLE = "ERR_STUDENT_NOT_ELIGIBLE"
    ERR_IEP_NOT_ACTIVE = "ERR_IEP_NOT_ACTIVE"
    ERR_TRANSITION_AGE_NOT_MET = "ERR_TRANSITION_AGE_NOT_MET"
    ERR_ACTIVE_IEP_EXISTS = "ERR_ACTIVE_IEP_EXISTS"


HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_FK_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_REQUEST: 400,
    ApiErrorId.ERR_INVALID_RANGE: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_STALE_VERSION: 412,
    ApiErrorId.ERR_CONSENT_NOT_GRANTED: 409,
    ApiErrorId.ERR_STUDENT_NOT_ELIGIBLE: 409,
    ApiErrorId.ERR_IEP_NOT_ACTIVE: 409,
    ApiErrorId.ERR_TRANSITION_AGE_NOT_MET: 409,
    ApiErrorId.ERR_ACTIVE_IEP_EXISTS: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(HTTP_STATUS_CODES)
