"""Test infrastructure for the Regional CPA Settlement API.

Importing this package gives a test the domain client, the payload builders, the
composite setup builders, the acting principals, the error catalogue, the domain
constants and the domain assertions.
"""

from . import api_errors, assertions, constants, factories, fixtures, test_users
from .api_client import CpaApiClient
from .api_errors import (
    ERROR_HTTP_STATUS,
    NOT_FOUND_BY_ENTITY,
    register_error_status_map,
)
from .types import (
    AgreementScenario,
    CycleScenario,
    Headers,
    JsonDict,
    SettledCycleScenario,
    StaffedBaseScenario,
)

__all__ = [
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "CpaApiClient",
    "ERROR_HTTP_STATUS",
    "NOT_FOUND_BY_ENTITY",
    "register_error_status_map",
    "AgreementScenario",
    "CycleScenario",
    "SettledCycleScenario",
    "StaffedBaseScenario",
    "Headers",
    "JsonDict",
]
