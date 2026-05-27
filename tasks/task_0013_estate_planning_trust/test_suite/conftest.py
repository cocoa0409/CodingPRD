"""Pytest fixtures exposing test_helpers infrastructure to the test suite.

Server lifecycle is managed by prd-bench-local-runner — the runner restarts
the server before every individual pytest test, so every test starts against
an empty database.
"""
import pytest

from test_helpers import (
    api_client,
    ApiClient,
    TEST_USERS,
    make_planner_headers,
    make_judge_headers,
    make_registrar_headers,
    make_creditor_headers,
    make_platform_admin_headers,
    make_executor_headers,
    make_beneficiary_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle handled by the runner."""
    return api_client


@pytest.fixture
def planner_headers():
    return TEST_USERS["planner_headers"]


@pytest.fixture
def judge_headers():
    return TEST_USERS["judge_headers"]


@pytest.fixture
def registrar_headers():
    return TEST_USERS["registrar_headers"]


@pytest.fixture
def creditor_headers():
    return TEST_USERS["creditor_headers"]


@pytest.fixture
def platform_admin_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def executor_headers_fallback():
    """Fallback Executor headers for non-ownership tests; for ownership-gated
    calls use make_executor_headers(executor_id)."""
    return TEST_USERS["executor_headers"]


@pytest.fixture
def beneficiary_headers_fallback():
    """Fallback Beneficiary headers for non-ownership tests; for
    ownership-gated calls use make_beneficiary_headers(designation_id)."""
    return TEST_USERS["beneficiary_headers"]
