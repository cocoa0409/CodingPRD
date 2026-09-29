"""
Test infrastructure for the Player Tracking Data Ops API.

Importing this package registers the error_id -> HTTP status mapping with the
framework validators, so `validate_error(response, error_id)` cross-checks the
status without every call site repeating it.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient
from .fixtures import World

__all__ = [
    "ApiClient",
    "World",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
