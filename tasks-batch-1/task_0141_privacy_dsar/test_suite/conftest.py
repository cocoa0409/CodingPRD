"""Pytest fixtures exposing test_helpers infrastructure for the Privacy DSAR suite."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle is managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def intake_agent_headers():
    return TEST_USERS["intake_agent_headers"]


@pytest.fixture
def privacy_officer_headers():
    return TEST_USERS["privacy_officer_headers"]


@pytest.fixture
def fulfillment_worker_headers():
    return TEST_USERS["fulfillment_worker_headers"]


@pytest.fixture
def processor_agent_headers():
    return TEST_USERS["processor_agent_headers"]


@pytest.fixture
def data_subject_agent_headers():
    return TEST_USERS["data_subject_agent_headers"]
