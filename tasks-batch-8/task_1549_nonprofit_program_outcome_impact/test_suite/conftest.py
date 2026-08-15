"""Pytest fixtures exposing the test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is owned by the runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["program_director_headers"]


@pytest.fixture
def lead_headers():
    return TEST_USERS["evaluation_lead_headers"]


@pytest.fixture
def collector_headers():
    """Shared FieldCollector headers. Observation recording uses a specific
    collector user id via make_field_collector_headers(user_id)."""
    return TEST_USERS["field_collector_headers"]


@pytest.fixture
def steward_headers():
    """Shared DataSteward headers. Segregation-of-duties tests must pin a
    specific steward id via make_data_steward_headers(user_id)."""
    return TEST_USERS["data_steward_headers"]


@pytest.fixture
def privacy_headers():
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def funder_viewer_headers():
    """Shared FunderViewer headers. Ownership-gated calls must instead use
    make_funder_viewer_headers(funder["id"])."""
    return TEST_USERS["funder_viewer_headers"]


@pytest.fixture
def vendor_analyst_headers():
    """Shared VendorAnalyst headers. Scope-gated calls must instead use
    make_vendor_analyst_headers(engagement["id"])."""
    return TEST_USERS["vendor_analyst_headers"]
