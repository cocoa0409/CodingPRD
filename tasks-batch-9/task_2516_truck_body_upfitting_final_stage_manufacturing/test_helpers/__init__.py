"""Test infrastructure for the Truck Body Upfitting & Final Stage Manufacturing API.

Layout:
  constants.py   — PRD-transcribed roles, enumerations, numeric tables, catalog rows
  types.py       — TypedDict shape of every persisted entity
  api_errors.py  — error identifiers plus the §5 error-to-HTTP mapping
  api_client.py  — one method per endpoint of §4
  factories.py   — request-payload builders with PRD-legal defaults
  assertions.py  — domain assertions over the derived fields of §2.8 and §2.10
  test_users.py  — pre-built auth headers for every role of §2.1
  fixtures.py    — composite state builders driven purely through the API

Importing this package registers the error-to-HTTP mapping with the shared
response validators.
"""

from . import api_errors  # noqa: F401  (registers the error/HTTP status map)
from . import assertions, constants, factories, fixtures, test_users, types
from .api_client import UpfitApiClient

__all__ = [
    "UpfitApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
