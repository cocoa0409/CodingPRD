"""Pytest fixtures exposing test_helpers infrastructure."""
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by prd-bench-local-runner."""
    return api_client


@pytest.fixture
def manager_headers():
    """SugarhouseManager (opaque role) headers."""
    return TEST_USERS["manager_headers"]


@pytest.fixture
def inspector_headers():
    """CertInspector (opaque role) headers."""
    return TEST_USERS["inspector_headers"]


@pytest.fixture
def fieldcrew_headers():
    """FieldCrew fallback headers — only for tests that do not exercise an
    ownership-gated operator reference (collected_by)."""
    return TEST_USERS["fieldcrew_headers"]


@pytest.fixture
def sugarmaker_headers():
    """SugarMaker fallback headers — only for tests that do not exercise an
    ownership-gated operator reference (boiled_by / evaluator_id)."""
    return TEST_USERS["sugarmaker_headers"]
