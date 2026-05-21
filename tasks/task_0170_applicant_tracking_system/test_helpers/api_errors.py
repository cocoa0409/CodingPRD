"""Error IDs and HTTP status mapping — PRD §5.

The mapping is registered with the framework at import time so
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
    ERR_UNAUTHORIZED = "ERR_UNAUTHORIZED"
    ERR_FORBIDDEN = "ERR_FORBIDDEN"
    # Existence — PRD §2.6
    ERR_NOT_FOUND = "ERR_NOT_FOUND"
    ERR_REFERENCE_NOT_FOUND = "ERR_REFERENCE_NOT_FOUND"
    # Generic validation — PRD §5
    ERR_VALIDATION = "ERR_VALIDATION"
    # State / concurrency — PRD §2.5, §2.9
    ERR_INVALID_STATE = "ERR_INVALID_STATE"
    ERR_VERSION_CONFLICT = "ERR_VERSION_CONFLICT"
    # Business safety — PRD §2.9
    ERR_EEO_DATA_MISSING = "ERR_EEO_DATA_MISSING"
    ERR_SEGREGATION_OF_DUTIES = "ERR_SEGREGATION_OF_DUTIES"
    # Business referential — PRD §3.1
    ERR_REFERRAL_REQUIRES_REFERRER = "ERR_REFERRAL_REQUIRES_REFERRER"
    # Business constraints — PRD §3.4, §3.2, §3.3
    ERR_INTERVIEWER_DOUBLE_BOOKED = "ERR_INTERVIEWER_DOUBLE_BOOKED"
    ERR_RECRUITER_REQUISITION_CAP = "ERR_RECRUITER_REQUISITION_CAP"
    ERR_DUPLICATE_APPLICATION = "ERR_DUPLICATE_APPLICATION"
    ERR_NO_QUALIFYING_FEEDBACK = "ERR_NO_QUALIFYING_FEEDBACK"
    ERR_EMPTY_PANEL = "ERR_EMPTY_PANEL"
    # Business fiscal — PRD §3.5, §3.6
    ERR_OFFER_EXCEEDS_REQ_BUDGET = "ERR_OFFER_EXCEEDS_REQ_BUDGET"
    ERR_MANAGER_BUDGET_EXCEEDED = "ERR_MANAGER_BUDGET_EXCEEDED"
    ERR_HEADCOUNT_EXCEEDED = "ERR_HEADCOUNT_EXCEEDED"
    # Compliance — PRD §3.6
    ERR_DIVERSITY_GOAL_NOT_MET = "ERR_DIVERSITY_GOAL_NOT_MET"
    # Temporal — PRD §3.5, §3.4
    ERR_OFFER_EXPIRES_IN_PAST = "ERR_OFFER_EXPIRES_IN_PAST"
    ERR_INTERVIEW_TIMING = "ERR_INTERVIEW_TIMING"
    # Field-level immutability — PRD §2.9, §3.2, §3.5
    ERR_HEADCOUNT_IMMUTABLE = "ERR_HEADCOUNT_IMMUTABLE"
    ERR_OFFER_FIELDS_IMMUTABLE = "ERR_OFFER_FIELDS_IMMUTABLE"


# PRD §5 — Error Code Catalogue
HTTP_STATUS_CODES: dict = {
    ApiErrorId.ERR_UNAUTHORIZED: 401,
    ApiErrorId.ERR_FORBIDDEN: 403,
    ApiErrorId.ERR_NOT_FOUND: 404,
    ApiErrorId.ERR_REFERENCE_NOT_FOUND: 422,
    ApiErrorId.ERR_VALIDATION: 422,
    ApiErrorId.ERR_INVALID_STATE: 409,
    ApiErrorId.ERR_VERSION_CONFLICT: 409,
    ApiErrorId.ERR_EEO_DATA_MISSING: 422,
    ApiErrorId.ERR_SEGREGATION_OF_DUTIES: 403,
    ApiErrorId.ERR_REFERRAL_REQUIRES_REFERRER: 422,
    ApiErrorId.ERR_INTERVIEWER_DOUBLE_BOOKED: 409,
    ApiErrorId.ERR_RECRUITER_REQUISITION_CAP: 409,
    ApiErrorId.ERR_DUPLICATE_APPLICATION: 409,
    ApiErrorId.ERR_NO_QUALIFYING_FEEDBACK: 409,
    ApiErrorId.ERR_OFFER_EXCEEDS_REQ_BUDGET: 422,
    ApiErrorId.ERR_MANAGER_BUDGET_EXCEEDED: 422,
    ApiErrorId.ERR_HEADCOUNT_EXCEEDED: 409,
    ApiErrorId.ERR_DIVERSITY_GOAL_NOT_MET: 422,
    ApiErrorId.ERR_OFFER_EXPIRES_IN_PAST: 422,
    ApiErrorId.ERR_INTERVIEW_TIMING: 409,
    ApiErrorId.ERR_EMPTY_PANEL: 409,
    ApiErrorId.ERR_HEADCOUNT_IMMUTABLE: 422,
    ApiErrorId.ERR_OFFER_FIELDS_IMMUTABLE: 422,
}


# Register with framework so validate_error() auto-checks HTTP status.
set_error_http_status_map(
    {k.value: v for k, v in HTTP_STATUS_CODES.items()},
)


__all__ = ["ApiErrorId", "HTTP_STATUS_CODES"]
