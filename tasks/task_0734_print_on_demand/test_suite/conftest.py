"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_creator_headers,
    make_fulfillment_partner_headers,
    make_anonymous_headers,
    make_platform_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def anonymous_headers():
    return TEST_USERS["anonymous_headers"]


@pytest.fixture
def creator_headers_fallback():
    """Fallback Creator headers — use ONLY for tests that do not exercise ownership."""
    return TEST_USERS["creator_headers"]


@pytest.fixture
def fulfillment_partner_headers_fallback():
    """Fallback FulfillmentPartner headers — non-ownership tests only."""
    return TEST_USERS["fulfillment_partner_headers"]


# Builder fixtures — the tests use these to build ownership-threaded headers.

@pytest.fixture
def creator_headers_for():
    """Returns a factory: creator_headers_for(creator_id) -> dict."""
    return make_creator_headers


@pytest.fixture
def partner_headers_for():
    """Returns a factory: partner_headers_for(partner_id) -> dict."""
    return make_fulfillment_partner_headers


@pytest.fixture
def anonymous_headers_factory():
    return make_anonymous_headers


@pytest.fixture
def admin_headers_factory():
    return make_platform_admin_headers
