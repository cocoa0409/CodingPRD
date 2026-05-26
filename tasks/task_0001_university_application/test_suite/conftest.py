"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_applicant_headers,
    make_admissions_headers,
    make_financial_aid_headers,
    make_platform_admin_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def applicant_headers():
    """Shared Applicant header constant. Use ONLY for non-ownership-gated calls.
    For ownership-gated calls, build per-applicant headers with make_applicant_headers(id).
    """
    return TEST_USERS["applicant_headers"]


@pytest.fixture
def admissions_headers():
    return TEST_USERS["admissions_headers"]


@pytest.fixture
def financial_aid_headers():
    return TEST_USERS["financial_aid_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def headers_factory():
    """Factory exposing builder functions so tests can mint per-entity headers."""
    return {
        "applicant": make_applicant_headers,
        "admissions": make_admissions_headers,
        "financial_aid": make_financial_aid_headers,
        "platform_admin": make_platform_admin_headers,
    }
