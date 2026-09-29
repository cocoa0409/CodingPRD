"""Pytest fixtures exposing the shared test infrastructure.

The server is relaunched before every test, so each test opens on an empty
database and builds all of its preconditions through the public API.
"""
import pytest

from test_helpers import ApiClient, api_client
from test_helpers.test_users import (
    anonymous_headers,
    brand_lead_headers,
    community_manager_headers,
    compliance_reviewer_headers,
    media_buyer_headers,
    persona_researcher_headers,
    recruiting_ops_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner owns the server lifecycle."""
    return api_client


@pytest.fixture
def brand_lead():
    return brand_lead_headers()


@pytest.fixture
def persona_researcher():
    return persona_researcher_headers()


@pytest.fixture
def compliance_reviewer():
    return compliance_reviewer_headers()


@pytest.fixture
def media_buyer():
    return media_buyer_headers()


@pytest.fixture
def community_manager():
    return community_manager_headers()


@pytest.fixture
def recruiting_ops():
    return recruiting_ops_headers()


@pytest.fixture
def anonymous():
    return anonymous_headers()
