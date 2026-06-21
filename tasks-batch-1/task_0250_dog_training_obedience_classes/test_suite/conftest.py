"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so `test_helpers` is importable, and owns server lifecycle
(restarting the API server via start.sh before every test). Tests therefore start against
an empty database and build all preconditions from scratch via the helpers below.
"""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def admin_manager_headers():
    return TEST_USERS["admin_manager_headers"]


@pytest.fixture
def owner_headers():
    return TEST_USERS["owner_headers"]


@pytest.fixture
def trainer_headers():
    return TEST_USERS["trainer_headers"]
