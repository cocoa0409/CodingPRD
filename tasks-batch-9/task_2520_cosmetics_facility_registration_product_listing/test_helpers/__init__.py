"""Test helpers for the Cosmetics Facility Registration & Product Listing API.

Importing this package registers the error catalogue's HTTP status mapping with
the framework validators.
"""

from . import api_errors  # noqa: F401  (registers the error -> status mapping)
from . import assertions, constants, factories, fixtures, types  # noqa: F401
from .api_client import CosmeticsApiClient
from .test_users import (
    OFFICER_1,
    OFFICER_2,
    OFFICER_HEADERS,
    OFFICER_2_HEADERS,
    OPERATOR_1,
    OPERATOR_HEADERS,
    REVIEWER_1,
    REVIEWER_2,
    REVIEWER_HEADERS,
    REVIEWER_2_HEADERS,
    TEST_USERS,
    headers_with_unknown_role,
    headers_without_role,
    headers_without_user_id,
    make_facility_registrant_headers,
    make_officer_headers,
    make_operator_headers,
    make_responsible_person_agent_headers,
    make_reviewer_headers,
)

__all__ = [
    "CosmeticsApiClient",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "types",
    "TEST_USERS",
    "REVIEWER_1",
    "REVIEWER_2",
    "OFFICER_1",
    "OFFICER_2",
    "OPERATOR_1",
    "REVIEWER_HEADERS",
    "REVIEWER_2_HEADERS",
    "OFFICER_HEADERS",
    "OFFICER_2_HEADERS",
    "OPERATOR_HEADERS",
    "make_facility_registrant_headers",
    "make_responsible_person_agent_headers",
    "make_reviewer_headers",
    "make_officer_headers",
    "make_operator_headers",
    "headers_without_user_id",
    "headers_without_role",
    "headers_with_unknown_role",
]
