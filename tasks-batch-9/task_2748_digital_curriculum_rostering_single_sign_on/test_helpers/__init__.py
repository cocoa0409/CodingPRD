"""
Test infrastructure for the Digital Curriculum Rostering & Single Sign-On API.

Importing this package registers the error_id -> HTTP status mapping with the
framework validators, so `validate_error` cross-checks statuses everywhere.

Modules:
- types        — domain enumerations
- constants    — business constants, defaults and worked-example literals
- api_errors   — every error identifier plus its HTTP status
- test_users   — pre-built auth headers for the five roles
- api_client   — one method per endpoint
- assertions   — domain assertions over records, counters and list pages
- factories    — request-payload builders
- fixtures     — composite setup helpers, from single entities to whole districts
"""

from . import api_errors  # noqa: F401  (registers the error/status map)
from . import assertions, constants, factories, fixtures, test_users, types  # noqa: F401
from .api_client import RosteringApiClient  # noqa: F401

__all__ = [
    "RosteringApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
