"""Test infrastructure for the Studio Operations API compliance suite.

Importing this package registers the PRD §5 error_id -> HTTP status mapping with
the framework validators, so `validate_error(response, ERR_X)` cross-checks the
status code automatically.
"""

from . import api_errors, assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .test_users import (  # noqa: F401
    ADMIN,
    CONTENT_OPS,
    COORDINATOR,
    PRODUCER,
    QC_REVIEWER,
    QC_REVIEWER_ID,
    TEST_USERS,
    make_headers,
    make_photographer_headers,
    make_qc_reviewer_headers,
    make_retoucher_headers,
)

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "TEST_USERS",
    "ADMIN",
    "COORDINATOR",
    "PRODUCER",
    "QC_REVIEWER",
    "QC_REVIEWER_ID",
    "CONTENT_OPS",
    "make_photographer_headers",
    "make_retoucher_headers",
    "make_qc_reviewer_headers",
    "make_headers",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
]
