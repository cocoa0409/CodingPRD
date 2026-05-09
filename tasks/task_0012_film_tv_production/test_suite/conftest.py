"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH so `test_helpers` is importable without sys.path
hacks. Server lifecycle is also the runner's job — this file just wires up
fixtures.
"""
import pytest

from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def executive_producer_headers():
    return TEST_USERS["executive_producer_headers"]


@pytest.fixture
def line_producer_headers():
    return TEST_USERS["line_producer_headers"]


@pytest.fixture
def finance_controller_headers():
    return TEST_USERS["finance_controller_headers"]


@pytest.fixture
def casting_director_headers():
    return TEST_USERS["casting_director_headers"]


@pytest.fixture
def production_coordinator_headers():
    return TEST_USERS["production_coordinator_headers"]
