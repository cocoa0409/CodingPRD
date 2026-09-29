"""
Test infrastructure for the Salt Deicing Operations API compliance suite.

Import surface:

    from test_helpers import SaltApiClient, api_errors, constants, factories, fixtures
    from test_helpers.assertions import assert_common_fields, assert_tons
    from test_helpers.test_users import MINE_PLANNER, make_depot_manager_headers

Importing this package registers the PRD §5 error_id -> HTTP status mapping with
the generic response validators, so validate_error() cross-checks status codes.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import SaltApiClient

__all__ = [
    "SaltApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
