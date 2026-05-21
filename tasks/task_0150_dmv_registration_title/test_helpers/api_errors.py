"""Error IDs and HTTP status mapping — PRD §5 Error Code Catalogue.

After definition, the mapping is registered with the framework so
validate_error() auto-checks HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth — PRD §2.1
    ERR_AUTH_REQUIRED = "ERR_AUTH_REQUIRED"
    ERR_INVALID_ROLE = "ERR_INVALID_ROLE"
    ERR_ROLE_FORBIDDEN = "ERR_ROLE_FORBIDDEN"
    # Existence — PRD §2.7
    ERR_RESOURCE_NOT_FOUND = "ERR_RESOURCE_NOT_FOUND"
    # State checks
    ERR_VIN_ON_HOLD = "ERR_VIN_ON_HOLD"
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VEHICLE_SALVAGE_LOCKED = "ERR_VEHICLE_SALVAGE_LOCKED"
    # Business safety
    ERR_EMISSIONS_EXPIRED = "ERR_EMISSIONS_EXPIRED"
    ERR_OWNER_REAL_ID_REVOKED = "ERR_OWNER_REAL_ID_REVOKED"
    # Business referential
    ERR_LIEN_ACTIVE = "ERR_LIEN_ACTIVE"
    # Business temporal
    ERR_INSPECTION_SLOT_OVERLAP = "ERR_INSPECTION_SLOT_OVERLAP"
    # Business constraints
    ERR_PLATE_NUMBER_TAKEN = "ERR_PLATE_NUMBER_TAKEN"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    ERR_REVISION_LIMIT_EXCEEDED = "ERR_REVISION_LIMIT_EXCEEDED"
    ERR_ODOMETER_ROLLBACK = "ERR_ODOMETER_ROLLBACK"
    # Business fiscal
    ERR_PAYMENT_REQUIRED = "ERR_PAYMENT_REQUIRED"
    # Owner holds
    ERR_OWNER_HAS_HOLDS = "ERR_OWNER_HAS_HOLDS"
    # Lien release
    ERR_RELEASE_REFERENCE_REQUIRED = "ERR_RELEASE_REFERENCE_REQUIRED"
    ERR_LIEN_ALREADY_RELEASED = "ERR_LIEN_ALREADY_RELEASED"
    # OCC
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Validation
    ERR_VALIDATION = "ERR_VALIDATION"


# PRD §5 — Error Code Catalogue (HTTP status mapping).
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_REQUIRED: 401,
    ApiErrorId.ERR_INVALID_ROLE: 403,
    ApiErrorId.ERR_ROLE_FORBIDDEN: 403,
    ApiErrorId.ERR_RESOURCE_NOT_FOUND: 404,
    ApiErrorId.ERR_VIN_ON_HOLD: 409,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VEHICLE_SALVAGE_LOCKED: 409,
    ApiErrorId.ERR_EMISSIONS_EXPIRED: 409,
    ApiErrorId.ERR_OWNER_REAL_ID_REVOKED: 409,
    ApiErrorId.ERR_LIEN_ACTIVE: 409,
    ApiErrorId.ERR_INSPECTION_SLOT_OVERLAP: 409,
    ApiErrorId.ERR_PLATE_NUMBER_TAKEN: 409,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_REVISION_LIMIT_EXCEEDED: 409,
    ApiErrorId.ERR_ODOMETER_ROLLBACK: 409,
    ApiErrorId.ERR_PAYMENT_REQUIRED: 402,
    ApiErrorId.ERR_OWNER_HAS_HOLDS: 409,
    ApiErrorId.ERR_RELEASE_REFERENCE_REQUIRED: 422,
    ApiErrorId.ERR_LIEN_ALREADY_RELEASED: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
