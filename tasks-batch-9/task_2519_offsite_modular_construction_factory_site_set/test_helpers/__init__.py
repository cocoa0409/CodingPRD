"""Test infrastructure for the offsite modular construction API.

Importing this package registers the error identifier to HTTP status mapping
with the shared response validators, so every ``validate_error`` call
cross-checks the status of the rejection it names.
"""

from . import api_errors  # noqa: F401  (registers the error/status mapping)
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import ModularApiClient
from .api_errors import ERROR_HTTP_STATUS
from .fixtures import World

__all__ = [
    "ModularApiClient",
    "ERROR_HTTP_STATUS",
    "World",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
