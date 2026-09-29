"""Test infrastructure for the Drive-Thru Speed-Of-Service API.

Import surface:

* `constants`   — domain literals taken from the PRD.
* `api_errors`  — the error catalogue and its HTTP status map.
* `test_users`  — role names, identities and header builders.
* `api_client`  — one method per declared endpoint.
* `factories`   — request-body builders.
* `fixtures`    — composite preconditions built through the API.
* `assertions`  — domain invariant checks.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import DriveThruApiClient
from .fixtures import StoreContext, at, set_clock, setup_store

__all__ = [
    "DriveThruApiClient",
    "StoreContext",
    "api_errors",
    "assertions",
    "at",
    "constants",
    "factories",
    "fixtures",
    "set_clock",
    "setup_store",
    "test_users",
    "types",
]
