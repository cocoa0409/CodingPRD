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
def finance_headers():
    return TEST_USERS["finance_headers"]


@pytest.fixture
def student_headers():
    """Placeholder Student headers — only safe for non-ownership tests
    (e.g., 400-on-bad-payload, 404 on missing resource). For ownership-gated
    calls, use make_student_headers(student["id"]) directly."""
    return TEST_USERS["student_headers"]


@pytest.fixture
def professor_headers():
    """Placeholder Professor headers — only safe for non-signer tests.
    For signer-gated calls, use make_professor_headers(professor["id"])."""
    return TEST_USERS["professor_headers"]
