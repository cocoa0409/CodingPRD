"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest
from test_helpers import (
    api_client, ApiClient, TEST_USERS, ANONYMOUS_HEADERS,
    make_account_manager_headers, make_coder_headers, make_biller_headers,
    make_denial_specialist_headers, make_payment_poster_headers,
    make_credentialing_specialist_headers, make_practice_user_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def account_manager_headers():
    return TEST_USERS["account_manager_headers"]


@pytest.fixture
def coder_headers():
    return TEST_USERS["coder_headers"]


@pytest.fixture
def biller_headers():
    return TEST_USERS["biller_headers"]


@pytest.fixture
def denial_specialist_headers():
    return TEST_USERS["denial_specialist_headers"]


@pytest.fixture
def payment_poster_headers():
    return TEST_USERS["payment_poster_headers"]


@pytest.fixture
def credentialing_specialist_headers():
    return TEST_USERS["credentialing_specialist_headers"]


@pytest.fixture
def anonymous_headers():
    return ANONYMOUS_HEADERS
