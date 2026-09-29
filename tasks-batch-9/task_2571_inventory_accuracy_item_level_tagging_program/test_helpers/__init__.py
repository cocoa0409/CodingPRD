"""
Shared test infrastructure for the inventory integrity API.

Submodules:
    constants   - named numbers, enum tuples and canonical fixture values
    api_errors  - error identifier constants plus their HTTP status registration
    test_users  - role headers and the per-entity identity header builders
    types       - response shapes
    api_client  - one method per declared endpoint
    assertions  - domain assertions over the response bodies
    factories   - request payload builders
    fixtures    - setup chains that build preconditions through the API
"""

from . import (  # noqa: F401
    api_client,
    api_errors,
    assertions,
    constants,
    factories,
    fixtures,
    test_users,
    types,
)
from .api_client import ApiClient  # noqa: F401
