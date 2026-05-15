"""Error IDs and HTTP status mapping (PRD §5 Error Code Catalogue).

After definition the mapping is registered with the framework so that
validate_error() can auto-check HTTP status codes without each test
passing them explicitly.
"""
from __future__ import annotations

from enum import Enum

from prd_bench_local_runner.testing.validators import set_error_http_status_map


class ApiErrorId(str, Enum):
    # Auth / authorization (PRD §2.1, §5)
    ERR_AUTH_MISSING = "ERR_AUTH_MISSING"
    ERR_AUTH_INVALID_ROLE = "ERR_AUTH_INVALID_ROLE"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence (PRD §2.5, §5)
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_FK_NOT_FOUND = "ERR_FK_NOT_FOUND"

    # Concurrency (PRD §2.6, §5)
    ERR_VERSION_MISMATCH = "ERR_VERSION_MISMATCH"

    # State / lifecycle (PRD §3.4, §3.5, §3.6, §5)
    ERR_REGISTRATION_WINDOW_CLOSED = "ERR_REGISTRATION_WINDOW_CLOSED"
    ERR_INVALID_STATE_FOR_TRANSITION = "ERR_INVALID_STATE_FOR_TRANSITION"
    ERR_LOTTERY_NOT_READY = "ERR_LOTTERY_NOT_READY"
    ERR_LOTTERY_ALREADY_DRAWN = "ERR_LOTTERY_ALREADY_DRAWN"
    ERR_LOTTERY_SEED_MISSING = "ERR_LOTTERY_SEED_MISSING"

    # Transfer / capacity (PRD §3.3, §5)
    ERR_TRANSFER_NOT_APPROVED = "ERR_TRANSFER_NOT_APPROVED"
    ERR_DISTRICT_NO_TRANSFERS = "ERR_DISTRICT_NO_TRANSFERS"
    ERR_DISTRICT_CAPACITY_EXCEEDED = "ERR_DISTRICT_CAPACITY_EXCEEDED"

    # Application business rules (PRD §3.1, §3.4, §5)
    ERR_GRADE_MISMATCH = "ERR_GRADE_MISMATCH"
    ERR_GRADE_NOT_OFFERED = "ERR_GRADE_NOT_OFFERED"
    ERR_DUPLICATE_CHOICE_RANK = "ERR_DUPLICATE_CHOICE_RANK"
    ERR_TOO_MANY_CHOICES = "ERR_TOO_MANY_CHOICES"

    # Temporal (PRD §3.6, §5)
    ERR_OFFER_EXPIRED = "ERR_OFFER_EXPIRED"
    ERR_WITHDRAW_GRACE_PASSED = "ERR_WITHDRAW_GRACE_PASSED"

    # Concurrency outcomes (PRD §2.11, §5)
    ERR_STUDENT_ALREADY_ACCEPTED = "ERR_STUDENT_ALREADY_ACCEPTED"
    ERR_SEAT_NOT_AVAILABLE = "ERR_SEAT_NOT_AVAILABLE"

    # Fiscal / seat capacity (PRD §3.1, §5)
    ERR_SEATS_BELOW_COMMITTED = "ERR_SEATS_BELOW_COMMITTED"

    # Generic shape/range violation (PRD §2.1, §5)
    ERR_VALIDATION = "ERR_VALIDATION"


# Per PRD §5 Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_AUTH_MISSING: 401,
    ApiErrorId.ERR_AUTH_INVALID_ROLE: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_FK_NOT_FOUND: 422,
    ApiErrorId.ERR_VERSION_MISMATCH: 409,
    ApiErrorId.ERR_REGISTRATION_WINDOW_CLOSED: 409,
    ApiErrorId.ERR_INVALID_STATE_FOR_TRANSITION: 409,
    ApiErrorId.ERR_LOTTERY_NOT_READY: 409,
    ApiErrorId.ERR_LOTTERY_ALREADY_DRAWN: 409,
    ApiErrorId.ERR_LOTTERY_SEED_MISSING: 422,
    ApiErrorId.ERR_TRANSFER_NOT_APPROVED: 422,
    ApiErrorId.ERR_DISTRICT_NO_TRANSFERS: 422,
    ApiErrorId.ERR_DISTRICT_CAPACITY_EXCEEDED: 409,
    ApiErrorId.ERR_GRADE_MISMATCH: 422,
    ApiErrorId.ERR_GRADE_NOT_OFFERED: 422,
    ApiErrorId.ERR_DUPLICATE_CHOICE_RANK: 422,
    ApiErrorId.ERR_OFFER_EXPIRED: 409,
    ApiErrorId.ERR_TOO_MANY_CHOICES: 422,
    ApiErrorId.ERR_STUDENT_ALREADY_ACCEPTED: 409,
    ApiErrorId.ERR_SEAT_NOT_AVAILABLE: 409,
    ApiErrorId.ERR_SEATS_BELOW_COMMITTED: 422,
    ApiErrorId.ERR_WITHDRAW_GRACE_PASSED: 409,
    ApiErrorId.ERR_VALIDATION: 422,
}


# Register with the framework so validate_error() auto-checks HTTP status.
set_error_http_status_map({k.value: v for k, v in HTTP_STATUS_CODES.items()})


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
