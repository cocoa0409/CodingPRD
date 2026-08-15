"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def ops_headers():
    return TEST_USERS["operations_manager_headers"]


@pytest.fixture
def intake_headers():
    return TEST_USERS["intake_coordinator_headers"]


@pytest.fixture
def editor_headers():
    return TEST_USERS["caption_editor_headers"]


@pytest.fixture
def ad_producer_headers():
    return TEST_USERS["ad_producer_headers"]


@pytest.fixture
def qc_headers():
    return TEST_USERS["qc_specialist_headers"]


@pytest.fixture
def scheduler_headers():
    return TEST_USERS["scheduler_headers"]
