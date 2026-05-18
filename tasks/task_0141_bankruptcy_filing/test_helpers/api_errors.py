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
    # Schema — PRD §5
    ERR_BAD_REQUEST = "ERR_BAD_REQUEST"

    # Auth — PRD §2.1
    ERR_UNAUTHENTICATED = "ERR_UNAUTHENTICATED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"

    # Existence — PRD §2.5
    ERR_NOT_FOUND = "ERR_NOT_FOUND"

    # State — PRD §2.6
    ERR_INVALID_STATE = "ERR_INVALID_STATE"

    # Automatic stay — PRD §2.7
    ERR_AUTOMATIC_STAY_VIOLATION = "ERR_AUTOMATIC_STAY_VIOLATION"

    # Plan submission against wrong chapter — PRD §3.8
    ERR_NOT_CHAPTER_13 = "ERR_NOT_CHAPTER_13"

    # 341 meeting — PRD §3.5
    ERR_MEETING_TOO_EARLY = "ERR_MEETING_TOO_EARLY"
    ERR_MEETING_DATE_NOT_REACHED = "ERR_MEETING_DATE_NOT_REACHED"

    # Filing preconditions — PRD §3.4
    ERR_SCHEDULES_INCOMPLETE = "ERR_SCHEDULES_INCOMPLETE"
    ERR_MEANS_TEST_NOT_RUN = "ERR_MEANS_TEST_NOT_RUN"
    ERR_PRESUMPTION_OF_ABUSE = "ERR_PRESUMPTION_OF_ABUSE"

    # Plan confirmation — PRD §3.8
    ERR_PLAN_UNDERFUNDED = "ERR_PLAN_UNDERFUNDED"
    ERR_PLAN_MONTHS_MISMATCH = "ERR_PLAN_MONTHS_MISMATCH"

    # Chapter-13 discharge — PRD §3.10
    ERR_PLAN_NOT_COMPLETE = "ERR_PLAN_NOT_COMPLETE"
    ERR_PLAN_IN_DEFAULT = "ERR_PLAN_IN_DEFAULT"

    # Dismissal from IN_REPAYMENT — PRD §3.11
    ERR_DISMISSAL_NOT_WARRANTED = "ERR_DISMISSAL_NOT_WARRANTED"

    # Claim creation — PRD §3.6
    ERR_CLAIM_AMOUNT_INVALID = "ERR_CLAIM_AMOUNT_INVALID"
    ERR_CLAIM_CLASS_MISMATCH = "ERR_CLAIM_CLASS_MISMATCH"

    # Plan submission / payment uniqueness — PRD §3.8 / §3.9
    ERR_PAYMENT_SEQUENCE_DUPLICATE = "ERR_PAYMENT_SEQUENCE_DUPLICATE"
    ERR_PLAN_ALREADY_EXISTS = "ERR_PLAN_ALREADY_EXISTS"

    # OCC — PRD §2.8
    ERR_STALE_DATA = "ERR_STALE_DATA"


# PRD §5 — Error Code Catalogue.
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_BAD_REQUEST: 400,
    ApiErrorId.ERR_UNAUTHENTICATED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_AUTOMATIC_STAY_VIOLATION: 409,
    ApiErrorId.ERR_NOT_CHAPTER_13: 409,
    ApiErrorId.ERR_MEETING_TOO_EARLY: 422,
    ApiErrorId.ERR_MEETING_DATE_NOT_REACHED: 409,
    ApiErrorId.ERR_SCHEDULES_INCOMPLETE: 409,
    ApiErrorId.ERR_MEANS_TEST_NOT_RUN: 409,
    ApiErrorId.ERR_PRESUMPTION_OF_ABUSE: 409,
    ApiErrorId.ERR_PLAN_UNDERFUNDED: 422,
    ApiErrorId.ERR_PLAN_MONTHS_MISMATCH: 422,
    ApiErrorId.ERR_PLAN_NOT_COMPLETE: 409,
    ApiErrorId.ERR_PLAN_IN_DEFAULT: 409,
    ApiErrorId.ERR_DISMISSAL_NOT_WARRANTED: 409,
    ApiErrorId.ERR_CLAIM_AMOUNT_INVALID: 422,
    ApiErrorId.ERR_CLAIM_CLASS_MISMATCH: 422,
    ApiErrorId.ERR_PAYMENT_SEQUENCE_DUPLICATE: 409,
    ApiErrorId.ERR_PLAN_ALREADY_EXISTS: 409,
    ApiErrorId.ERR_STALE_DATA: 409,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
