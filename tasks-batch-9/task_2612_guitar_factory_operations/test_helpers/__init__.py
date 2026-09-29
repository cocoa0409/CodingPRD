"""
Shared test infrastructure for the guitar factory operations service.

The modules here carry no assertions about the rules under test: they only make
requests, describe roles, name domain constants and rebuild preconditions, so a
test file can read as a statement about behaviour rather than as plumbing.
"""

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from . import assertions, constants, factories, fixtures, test_users  # noqa: F401
from .api_client import ApiClient  # noqa: F401
from .types import ApiResponse, Headers, JsonDict, JsonList, Params  # noqa: F401
