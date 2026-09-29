"""
Test infrastructure for the Precision Spring & Wire Form Manufacturing API.

Importing this package registers the error-id to HTTP-status mapping with the
framework validators, so `validate_error(response, error_id)` cross-checks the
status of every rejection without each call site restating it.
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
