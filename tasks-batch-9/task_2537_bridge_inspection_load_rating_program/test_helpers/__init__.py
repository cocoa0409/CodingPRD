"""
Test helpers for the Bridge Inspection & Load Rating Program API.

This package is the PRD-specific layer between the generic framework in
`prd_bench_local_runner.testing` and the claim-driven tests in `test_suite/`.
Importing it registers the error-to-HTTP-status map of PRD §5 so that
`validate_error` can cross-check statuses.
"""

from . import api_errors  # noqa: F401  (import registers the PRD §5 status map)
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import BridgeProgramClient
from .test_users import (  # noqa: F401
    FHWA_REVIEWER_ALT_USER_ID,
    FHWA_REVIEWER_USER_ID,
    PERMIT_OFFICER_USER_ID,
    PROGRAM_ADMIN_ALT_USER_ID,
    PROGRAM_ADMIN_USER_ID,
    TEST_USERS,
    fhwa_reviewer_headers,
    make_bridge_inspector_headers,
    make_district_engineer_headers,
    make_headers,
    make_qa_reviewer_headers,
    make_rating_engineer_headers,
    permit_officer_headers,
    program_admin_headers,
)

__all__ = [
    "BridgeProgramClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "TEST_USERS",
    "PROGRAM_ADMIN_USER_ID",
    "PROGRAM_ADMIN_ALT_USER_ID",
    "PERMIT_OFFICER_USER_ID",
    "FHWA_REVIEWER_USER_ID",
    "FHWA_REVIEWER_ALT_USER_ID",
    "program_admin_headers",
    "permit_officer_headers",
    "fhwa_reviewer_headers",
    "make_bridge_inspector_headers",
    "make_qa_reviewer_headers",
    "make_rating_engineer_headers",
    "make_district_engineer_headers",
    "make_headers",
]
