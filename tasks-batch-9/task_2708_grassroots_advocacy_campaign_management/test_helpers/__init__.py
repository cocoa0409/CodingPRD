"""Shared test infrastructure for the grassroots advocacy campaign API.

Importing this package registers the error identifier to HTTP status map with
the framework validators, so ``validate_error(response, ERR_X)`` cross-checks
the transport status automatically.
"""

from . import api_errors  # noqa: F401  (import registers the error status map)
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import AdvocacyClient

__all__ = [
    "AdvocacyClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
