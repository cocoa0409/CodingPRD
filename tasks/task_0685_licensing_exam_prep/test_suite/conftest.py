"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def learner_headers():
    return TEST_USERS["learner_headers"]


@pytest.fixture
def content_admin_headers():
    return TEST_USERS["content_admin_headers"]


@pytest.fixture
def exam_proctor_headers():
    return TEST_USERS["exam_proctor_headers"]


@pytest.fixture
def platform_ops_headers():
    return TEST_USERS["platform_ops_headers"]
