"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ad_ops_headers():
    return TEST_USERS["ad_ops_headers"]


@pytest.fixture
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def ingestion_headers():
    return TEST_USERS["ingestion_headers"]


@pytest.fixture
def advertiser_headers():
    return TEST_USERS["advertiser_headers"]


@pytest.fixture
def agency_headers():
    return TEST_USERS["agency_headers"]


@pytest.fixture
def show_producer_headers():
    return TEST_USERS["show_producer_headers"]
