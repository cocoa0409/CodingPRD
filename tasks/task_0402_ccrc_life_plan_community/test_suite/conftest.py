"""Pytest fixtures exposing test_helpers infrastructure.

The runner sets PYTHONPATH so test_helpers is importable, and manages the
server lifecycle (restarting it before each test).
"""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiClient,
    api_client,
    make_admissions_director_headers,
    make_care_coordinator_headers,
    make_finance_officer_headers,
    make_resident_headers,
)


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


@pytest.fixture
def finance_officer_headers():
    return TEST_USERS["finance_officer_headers"]


@pytest.fixture
def admissions_director_headers():
    return TEST_USERS["admissions_director_headers"]


@pytest.fixture
def care_coordinator_headers():
    return TEST_USERS["care_coordinator_headers"]


@pytest.fixture
def resident_headers_shared():
    """Shared Resident header. Use only for tests that do NOT exercise resident
    ownership."""
    return TEST_USERS["resident_headers"]


@pytest.fixture
def headers_factory():
    """Per-role builder functions; tests mint per-entity headers as needed."""
    return {
        "finance_officer": make_finance_officer_headers,
        "admissions_director": make_admissions_director_headers,
        "care_coordinator": make_care_coordinator_headers,
        "resident": make_resident_headers,
    }
