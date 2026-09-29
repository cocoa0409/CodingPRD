"""Shared test infrastructure for the Affiliate Homeownership Sweat Equity API.

Importing this package registers the error-id to HTTP-status map with the
framework validators.
"""

from . import api_errors, assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import HomeownershipClient  # noqa: F401
from .test_users import (  # noqa: F401
    ADMIN,
    APPROVER,
    COMMITTEE_ALICE,
    COMMITTEE_BRUNO,
    COORDINATOR,
    CREW_LEAD,
    NO_HEADERS,
    OFFICER,
    make_applicant_headers,
    make_headers,
    make_volunteer_headers,
)

__all__ = [
    "HomeownershipClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "ADMIN",
    "APPROVER",
    "COMMITTEE_ALICE",
    "COMMITTEE_BRUNO",
    "COORDINATOR",
    "CREW_LEAD",
    "NO_HEADERS",
    "OFFICER",
    "make_applicant_headers",
    "make_headers",
    "make_volunteer_headers",
]
