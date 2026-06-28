"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_underwriter_headers,
    make_senior_underwriter_headers,
    make_claims_examiner_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def underwriter_headers():
    return TEST_USERS["underwriter_headers"]


@pytest.fixture
def senior_underwriter_headers():
    return TEST_USERS["senior_underwriter_headers"]


@pytest.fixture
def claims_examiner_headers():
    return TEST_USERS["claims_examiner_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-identity headers."""
    return {
        "underwriter": make_underwriter_headers,
        "senior_underwriter": make_senior_underwriter_headers,
        "claims_examiner": make_claims_examiner_headers,
    }
