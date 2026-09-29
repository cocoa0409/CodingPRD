"""
Test infrastructure for the Out-of-District Special Education Placement &
Tuition API.

Modules:
  api_client   one method per declared endpoint
  api_errors   the error catalogue with its HTTP statuses and the refusal ladder
  assertions   domain assertions, including the two conservation identities
  constants    every named business constant quoted from the requirements
  factories    valid-by-default request payloads with keyword overrides
  fixtures     composite state builders, in five tiers
  test_users   role headers and the two entity-backed header builders
  types        TypedDict shapes for the fifteen resource types
"""

from .api_client import ApiClient
from .api_errors import (
    ERROR_HTTP_STATUS,
    REFUSAL_LADDER,
)
from . import api_errors
from . import assertions
from . import constants
from . import factories
from . import fixtures
from . import test_users
from . import types

__all__ = [
    "ApiClient",
    "ERROR_HTTP_STATUS",
    "REFUSAL_LADDER",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
