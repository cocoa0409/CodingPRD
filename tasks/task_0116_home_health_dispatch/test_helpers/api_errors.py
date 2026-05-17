"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition, the mapping is registered with the framework so
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import (
    set_error_http_status_map,
)


class ApiErrorId(str, Enum):
    # Auth / access — PRD §2.1
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State — PRD §2.9
    ERR_OASIS_NOT_DRAFT = "ERR_OASIS_NOT_DRAFT"
    ERR_OASIS_NOT_LOCKED = "ERR_OASIS_NOT_LOCKED"
    ERR_EPISODE_NOT_OPEN = "ERR_EPISODE_NOT_OPEN"
    ERR_VISIT_NOT_SCHEDULED = "ERR_VISIT_NOT_SCHEDULED"
    ERR_MILEAGE_VISIT_NOT_COMPLETED = "ERR_MILEAGE_VISIT_NOT_COMPLETED"

    # Safety / compliance — PRD §3.5
    ERR_CLINICIAN_LICENSE_EXPIRED = "ERR_CLINICIAN_LICENSE_EXPIRED"
    ERR_CLINICIAN_NOT_AVAILABLE = "ERR_CLINICIAN_NOT_AVAILABLE"
    ERR_DISCIPLINE_MISMATCH = "ERR_DISCIPLINE_MISMATCH"
    ERR_RECERT_WINDOW_VIOLATION = "ERR_RECERT_WINDOW_VIOLATION"

    # Temporal / referential — PRD §3.5 / §3.4
    ERR_VISIT_OUTSIDE_EPISODE = "ERR_VISIT_OUTSIDE_EPISODE"
    ERR_VISIT_TIME_INVALID = "ERR_VISIT_TIME_INVALID"
    ERR_CLINICIAN_DOUBLE_BOOKED = "ERR_CLINICIAN_DOUBLE_BOOKED"
    ERR_OASIS_ALREADY_USED = "ERR_OASIS_ALREADY_USED"
    ERR_PATIENT_HAS_OPEN_EPISODE = "ERR_PATIENT_HAS_OPEN_EPISODE"

    # Fiscal / quota — PRD §3.5
    ERR_HHA_HOURS_EXCEEDED = "ERR_HHA_HOURS_EXCEEDED"

    # Business constraints — PRD §3.6 / §2.8
    ERR_MILEAGE_NOT_POSITIVE = "ERR_MILEAGE_NOT_POSITIVE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"

    # Clock — PRD §2.7
    ERR_CLOCK_BACKWARDS = "ERR_CLOCK_BACKWARDS"


# PRD §5 Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_OASIS_NOT_DRAFT: 409,
    ApiErrorId.ERR_OASIS_NOT_LOCKED: 409,
    ApiErrorId.ERR_EPISODE_NOT_OPEN: 409,
    ApiErrorId.ERR_VISIT_NOT_SCHEDULED: 409,
    ApiErrorId.ERR_MILEAGE_VISIT_NOT_COMPLETED: 409,
    ApiErrorId.ERR_CLINICIAN_LICENSE_EXPIRED: 422,
    ApiErrorId.ERR_CLINICIAN_NOT_AVAILABLE: 422,
    ApiErrorId.ERR_DISCIPLINE_MISMATCH: 422,
    ApiErrorId.ERR_RECERT_WINDOW_VIOLATION: 422,
    ApiErrorId.ERR_VISIT_OUTSIDE_EPISODE: 422,
    ApiErrorId.ERR_VISIT_TIME_INVALID: 422,
    ApiErrorId.ERR_CLINICIAN_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_OASIS_ALREADY_USED: 409,
    ApiErrorId.ERR_PATIENT_HAS_OPEN_EPISODE: 409,
    ApiErrorId.ERR_HHA_HOURS_EXCEEDED: 422,
    ApiErrorId.ERR_MILEAGE_NOT_POSITIVE: 422,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_CLOCK_BACKWARDS: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
