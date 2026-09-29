"""
Pytest fixtures for the Lender Appraisal Review Desk compliance suite.

The harness restarts the service before each test, so every test observes an empty
database and builds its own preconditions. These fixtures expose the endpoint
client and the role headers; anything with more shape than that is built by an
explicit call to a helper inside the test body, so that the setup a test depends on
is visible at the point of use.
"""

import pytest

from test_helpers import (
    CHIEF_APPRAISER_HEADERS,
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    LOAN_OFFICER_HEADERS,
    ApiClient,
)


@pytest.fixture
def api() -> ApiClient:
    """Endpoint client bound to the service under test."""
    return ApiClient()


@pytest.fixture
def loan_officer():
    """Headers for the loan officer who owns loan files."""
    return LOAN_OFFICER_HEADERS


@pytest.fixture
def desk_reviewer():
    """Headers for the appraisal desk reviewer."""
    return DESK_REVIEWER_HEADERS


@pytest.fixture
def chief_appraiser():
    """Headers for the panel authority."""
    return CHIEF_APPRAISER_HEADERS


@pytest.fixture
def compliance_officer():
    """Headers for the compliance officer who owns the bias screen."""
    return COMPLIANCE_HEADERS
