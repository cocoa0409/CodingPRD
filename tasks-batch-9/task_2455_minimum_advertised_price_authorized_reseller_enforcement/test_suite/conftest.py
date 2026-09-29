"""Pytest fixtures exposing the test_helpers infrastructure.

The runner owns the server lifecycle and restarts it before every test, so each
test observes an empty database and builds everything it needs through the
declared endpoints.
"""
import pytest
from prd_bench_local_runner.testing.validators import set_error_http_status_map

from test_helpers import (
    ADMIN_HEADERS,
    ANALYST_2_HEADERS,
    ANALYST_HEADERS,
    HTTP_STATUS_CODES,
    ApiClient,
    BCM_2_HEADERS,
    BCM_HEADERS,
    COUNSEL_2_HEADERS,
    COUNSEL_HEADERS,
    api_client,
)
from test_helpers.constants import DEFAULT_CLOCK
from test_helpers.fixtures import pin_clock

set_error_http_status_map(HTTP_STATUS_CODES)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client; the runner manages the server lifecycle."""
    return api_client


@pytest.fixture
def brand_channel_manager_headers():
    return BCM_HEADERS


@pytest.fixture
def second_brand_channel_manager_headers():
    return BCM_2_HEADERS


@pytest.fixture
def brand_legal_counsel_headers():
    return COUNSEL_HEADERS


@pytest.fixture
def second_brand_legal_counsel_headers():
    return COUNSEL_2_HEADERS


@pytest.fixture
def monitoring_analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture
def second_monitoring_analyst_headers():
    return ANALYST_2_HEADERS


@pytest.fixture
def platform_admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def default_clock():
    """Pin the logical clock explicitly to the instant it reads before any pin."""
    pin_clock(DEFAULT_CLOCK)
    return DEFAULT_CLOCK
