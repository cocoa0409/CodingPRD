"""Test infrastructure for the Immigration Legal Services Program PRD.

Importing this package registers the PRD section 5 error-id -> HTTP status map
with the shared validators, so ``assert_error`` can check both halves of an
error contract from a single call.
"""

from . import api_errors  # noqa: F401  (import side effect: registers the status map)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .test_users import (  # noqa: F401
    GRANT_ANALYST_HEADERS,
    PROGRAM_DIRECTOR_HEADERS,
    TEST_USERS,
    make_case_representative_headers,
    make_client_portal_headers,
    make_intake_screener_headers,
    make_supervising_attorney_headers,
)
from .fixtures import (  # noqa: F401
    Env,
    accept_intake,
    add_evidence,
    add_supervisor_assignment,
    create_client,
    drive_evidence,
    recognition_with_accredited_rep,
    set_clock,
    template_a,
    template_b,
)

# Shared client instance. The base URL comes from API_BASE_URL, which the
# runner sets; the module-level singleton keeps one connection pool per process.
api_client = ApiClient()

__all__ = [
    "ApiClient",
    "GRANT_ANALYST_HEADERS",
    "PROGRAM_DIRECTOR_HEADERS",
    "TEST_USERS",
    "api_client",
    "make_case_representative_headers",
    "make_client_portal_headers",
    "make_intake_screener_headers",
    "make_supervising_attorney_headers",
    "Env",
    "accept_intake",
    "add_evidence",
    "add_supervisor_assignment",
    "api_errors",
    "assertions",
    "constants",
    "create_client",
    "drive_evidence",
    "factories",
    "fixtures",
    "recognition_with_accredited_rep",
    "set_clock",
    "template_a",
    "template_b",
    "test_users",
    "types",
]
