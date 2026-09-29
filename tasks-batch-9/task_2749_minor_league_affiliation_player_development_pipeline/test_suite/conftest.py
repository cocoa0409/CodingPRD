"""Pytest fixtures exposing the test_helpers infrastructure.

The runner restarts the server before every individual test, so each test sees
an empty database and every fixture below builds its preconditions from
scratch through the public API.
"""

import pytest

from test_helpers import (
    COMPLIANCE_OFFICER_ALT_HEADERS,
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_ALT_HEADERS,
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
)


@pytest.fixture
def api() -> ApiClient:
    """API client bound to the server under test (base URL from the runner)."""
    return ApiClient()


@pytest.fixture
def farm_director_headers():
    return FARM_DIRECTOR_HEADERS


@pytest.fixture
def farm_director_alt_headers():
    return FARM_DIRECTOR_ALT_HEADERS


@pytest.fixture
def medical_director_headers():
    return MEDICAL_DIRECTOR_HEADERS


@pytest.fixture
def compliance_officer_headers():
    return COMPLIANCE_OFFICER_HEADERS


@pytest.fixture
def compliance_officer_alt_headers():
    return COMPLIANCE_OFFICER_ALT_HEADERS


@pytest.fixture
def international_scout_headers():
    return INTERNATIONAL_SCOUT_HEADERS
