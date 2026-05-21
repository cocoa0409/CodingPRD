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
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    # State / OCC — PRD §2.5, §2.10
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Hazmat — PRD §2.6
    ERR_HAZMAT_HUB_NOT_CERTIFIED = "ERR_HAZMAT_HUB_NOT_CERTIFIED"
    ERR_DRIVER_NO_HAZMAT_ENDORSEMENT = "ERR_DRIVER_NO_HAZMAT_ENDORSEMENT"
    # Signature / driver-release — PRD §2.7
    ERR_DRIVER_RELEASE_NOT_AUTHORIZED = "ERR_DRIVER_RELEASE_NOT_AUTHORIZED"
    ERR_SIGNATURE_MISSING = "ERR_SIGNATURE_MISSING"
    # Delivery temporal — PRD §3.5
    ERR_OUTSIDE_TIME_WINDOW = "ERR_OUTSIDE_TIME_WINDOW"
    # Appointment / planning temporal — PRD §3.5, §3.7
    ERR_APPOINTMENT_WINDOW_INVALID = "ERR_APPOINTMENT_WINDOW_INVALID"
    ERR_TIME_WINDOW_INFEASIBLE = "ERR_TIME_WINDOW_INFEASIBLE"
    # Route / parcel constraints — PRD §3.4, §3.5
    ERR_PARCEL_ALREADY_ON_ROUTE = "ERR_PARCEL_ALREADY_ON_ROUTE"
    ERR_ROUTE_NOT_PLANNED = "ERR_ROUTE_NOT_PLANNED"
    # Routing — PRD §3.3
    ERR_HUB_NOT_SERVICING_POSTAL = "ERR_HUB_NOT_SERVICING_POSTAL"
    # Redelivery — PRD §3.5
    ERR_REDELIVERY_LIMIT_EXCEEDED = "ERR_REDELIVERY_LIMIT_EXCEEDED"
    ERR_CUSTOMER_REDELIVERY_CAP_REACHED = "ERR_CUSTOMER_REDELIVERY_CAP_REACHED"
    # Fiscal — PRD §3.3
    ERR_PARCEL_WEIGHT_OUT_OF_RANGE = "ERR_PARCEL_WEIGHT_OUT_OF_RANGE"
    ERR_DECLARED_VALUE_OUT_OF_RANGE = "ERR_DECLARED_VALUE_OUT_OF_RANGE"
    # Clock — PRD §2.11
    ERR_CLOCK_BACKWARDS = "ERR_CLOCK_BACKWARDS"


# PRD §5 Error Code Catalogue: error_id -> HTTP status.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_HAZMAT_HUB_NOT_CERTIFIED: 422,
    ApiErrorId.ERR_DRIVER_NO_HAZMAT_ENDORSEMENT: 422,
    ApiErrorId.ERR_DRIVER_RELEASE_NOT_AUTHORIZED: 422,
    ApiErrorId.ERR_SIGNATURE_MISSING: 422,
    ApiErrorId.ERR_OUTSIDE_TIME_WINDOW: 422,
    ApiErrorId.ERR_APPOINTMENT_WINDOW_INVALID: 422,
    ApiErrorId.ERR_TIME_WINDOW_INFEASIBLE: 422,
    ApiErrorId.ERR_PARCEL_ALREADY_ON_ROUTE: 409,
    ApiErrorId.ERR_ROUTE_NOT_PLANNED: 409,
    ApiErrorId.ERR_HUB_NOT_SERVICING_POSTAL: 422,
    ApiErrorId.ERR_REDELIVERY_LIMIT_EXCEEDED: 422,
    ApiErrorId.ERR_CUSTOMER_REDELIVERY_CAP_REACHED: 422,
    ApiErrorId.ERR_PARCEL_WEIGHT_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_DECLARED_VALUE_OUT_OF_RANGE: 422,
    ApiErrorId.ERR_CLOCK_BACKWARDS: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
