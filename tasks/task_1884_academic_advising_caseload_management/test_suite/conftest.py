"""Pytest fixtures exposing test_helpers infrastructure.

The runner owns server lifecycle and PYTHONPATH; this module only wires the
pre-built role headers and the API client into pytest fixtures.
"""
import pytest

from test_helpers import TEST_USERS, ApiClient, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def director_headers():
    return TEST_USERS["director_headers"]


@pytest.fixture
def advisor_headers():
    return TEST_USERS["advisor_headers"]


@pytest.fixture
def front_desk_headers():
    return TEST_USERS["front_desk_headers"]


@pytest.fixture
def faculty_headers():
    return TEST_USERS["faculty_headers"]
