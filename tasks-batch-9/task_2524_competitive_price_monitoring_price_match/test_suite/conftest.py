"""Pytest fixtures exposing the pricing test_helpers infrastructure."""
import pytest

from test_helpers import (
    ApiClient,
    TEST_USERS,
    api_client,
    make_store_associate_headers,
    make_store_manager_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by the runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pricing_analyst_headers():
    return TEST_USERS["pricing_analyst_headers"]


@pytest.fixture
def pricing_manager_headers():
    return TEST_USERS["pricing_manager_headers"]


@pytest.fixture
def compliance_officer_headers():
    return TEST_USERS["compliance_officer_headers"]


@pytest.fixture
def data_collector_headers():
    return TEST_USERS["data_collector_headers"]


@pytest.fixture
def store_associate_headers():
    """Generic StoreAssociate headers. Store-scoped calls must instead use
    ``store_associate_for`` so that X-User-ID carries the acting store's id."""
    return TEST_USERS["store_associate_headers"]


@pytest.fixture
def store_manager_headers():
    """Generic StoreManager headers. Store-scoped calls must instead use
    ``store_manager_for`` so that X-User-ID carries the acting store's id."""
    return TEST_USERS["store_manager_headers"]


@pytest.fixture
def store_associate_for():
    """Builder for StoreAssociate headers bound to a particular store id."""
    return make_store_associate_headers


@pytest.fixture
def store_manager_for():
    """Builder for StoreManager headers bound to a particular store id."""
    return make_store_manager_headers
