"""Test helper package for the nonprofit restructuring API compliance suite.

Importing this package registers the error catalogue's HTTP status map with the
framework validators, so every validate_error() call cross-checks the status.
"""

from test_helpers import api_errors as _api_errors  # noqa: F401  (registers the status map)
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    CHARITIES_REGULATOR,
    DILIGENCE_LEAD,
    DILIGENCE_LEAD_2,
    DILIGENCE_LEAD_3,
    INTEGRATION_MANAGER,
    INTEGRATION_MANAGER_2,
    NO_HEADERS,
    PLATFORM_ADMIN,
    TRUST_COUNSEL,
    TRUST_COUNSEL_2,
    UNKNOWN_ROLE,
    make_board_secretary_headers,
    make_strategy_officer_headers,
)

# Shared client instance; the runner owns the server lifecycle.
api_client = ApiClient()

TEST_USERS = {
    "platform_admin": PLATFORM_ADMIN,
    "diligence_lead": DILIGENCE_LEAD,
    "diligence_lead_2": DILIGENCE_LEAD_2,
    "diligence_lead_3": DILIGENCE_LEAD_3,
    "trust_counsel": TRUST_COUNSEL,
    "trust_counsel_2": TRUST_COUNSEL_2,
    "charities_regulator": CHARITIES_REGULATOR,
    "integration_manager": INTEGRATION_MANAGER,
    "integration_manager_2": INTEGRATION_MANAGER_2,
    "no_headers": NO_HEADERS,
    "unknown_role": UNKNOWN_ROLE,
}

__all__ = [
    "ApiClient",
    "api_client",
    "TEST_USERS",
    "make_strategy_officer_headers",
    "make_board_secretary_headers",
]
