"""Shared fixtures for the governance API suite.

The server lifecycle belongs to the runner: it is relaunched before each test, so
every test starts against an empty database and builds only the rows it needs.
"""
import pytest
from test_helpers import ApiClient, api_client
from test_helpers.fixtures import adopt_policy
from test_helpers.test_users import SECRETARY, STAFF


@pytest.fixture(scope="session")
def client() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def staff():
    """Headers for a `GovernanceStaff` operator (opaque identifier)."""
    return STAFF


@pytest.fixture
def secretary():
    """Headers for a `CorporateSecretary` operator (opaque identifier)."""
    return SECRETARY


@pytest.fixture
def policy(client):
    """A governing policy with every threshold stated explicitly."""
    return adopt_policy(client)
