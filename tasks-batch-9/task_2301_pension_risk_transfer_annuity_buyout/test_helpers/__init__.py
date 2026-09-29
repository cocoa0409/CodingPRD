"""Test infrastructure for the Pension Risk Transfer & Annuity Buyout API.

Importing this package registers the error-to-HTTP-status map with the
framework validators, so `validate_error` checks both halves of an error
contract from anywhere in the suite.
"""

from . import api_errors  # noqa: F401  (registers the error status map on import)
from . import assertions, constants, factories, fixtures, types
from .api_client import PrtApiClient, api_client
from .test_users import (
    ACTUARY_ALT_USER_ID,
    ACTUARY_USER_ID,
    ADMINISTRATOR_USER_ID,
    ALL_ROLE_NAMES,
    FIDUCIARY_ALT_USER_ID,
    FIDUCIARY_USER_ID,
    OPAQUE_ROLE_NAMES,
    REGULATOR_USER_ID,
    SPONSOR_ALT_USER_ID,
    SPONSOR_USER_ID,
    TEST_USERS,
    actuary_alt_headers,
    actuary_headers,
    administrator_headers,
    fiduciary_alt_headers,
    fiduciary_headers,
    make_expert_headers,
    make_insurer_rep_headers,
    make_participant_headers,
    opaque_headers,
    regulator_headers,
    sponsor_alt_headers,
    sponsor_headers,
)

__all__ = [
    "api_client",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "PrtApiClient",
    "TEST_USERS",
    "ALL_ROLE_NAMES",
    "OPAQUE_ROLE_NAMES",
    "SPONSOR_USER_ID",
    "SPONSOR_ALT_USER_ID",
    "FIDUCIARY_USER_ID",
    "FIDUCIARY_ALT_USER_ID",
    "ACTUARY_USER_ID",
    "ACTUARY_ALT_USER_ID",
    "ADMINISTRATOR_USER_ID",
    "REGULATOR_USER_ID",
    "sponsor_headers",
    "sponsor_alt_headers",
    "fiduciary_headers",
    "fiduciary_alt_headers",
    "actuary_headers",
    "actuary_alt_headers",
    "administrator_headers",
    "regulator_headers",
    "opaque_headers",
    "make_insurer_rep_headers",
    "make_participant_headers",
    "make_expert_headers",
]
