"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import api_client, ApiClient, TEST_USERS


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def ethics_officer_headers():
    return TEST_USERS["ethics_officer_headers"]


@pytest.fixture
def investigator_headers():
    return TEST_USERS["investigator_headers"]


@pytest.fixture
def adjudicator_headers():
    return TEST_USERS["adjudicator_headers"]


@pytest.fixture
def public_headers():
    return TEST_USERS["public_headers"]


@pytest.fixture
def filer_headers():
    return TEST_USERS["filer_headers"]
