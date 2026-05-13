"""Pytest fixtures exposing test_helpers infrastructure.

The runner manages PYTHONPATH and server lifecycle. This conftest just
wires per-role headers and the session-scoped api client.
"""
from __future__ import annotations
import pytest

from test_helpers import ApiClient, TEST_USERS, api_client


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped API client. Server lifecycle managed by the runner."""
    return api_client


# ---------------------------------------------------------------------------
# Role-header fixtures. Per PRD §2.1, PlatformAdmin, HotlineOperator,
# Dispatcher, Supervisor, and SurveyAgent are OPAQUE so shared constants
# are canonical. DepartmentHandler is entity_backed: tests that exercise
# ownership MUST use the per-instance builder
# make_department_handler_headers(handler['id']).
# ---------------------------------------------------------------------------
@pytest.fixture
def pa_headers():
    return TEST_USERS["platform_admin_headers"]


@pytest.fixture
def pa_headers_alt():
    return TEST_USERS["platform_admin_headers_alt"]


@pytest.fixture
def ho_headers():
    return TEST_USERS["hotline_operator_headers"]


@pytest.fixture
def ho_headers_alt():
    return TEST_USERS["hotline_operator_headers_alt"]


@pytest.fixture
def dispatcher_headers():
    return TEST_USERS["dispatcher_headers"]


@pytest.fixture
def supervisor_headers():
    return TEST_USERS["supervisor_headers"]


@pytest.fixture
def survey_agent_headers():
    return TEST_USERS["survey_agent_headers"]


@pytest.fixture
def department_handler_headers():
    """Fallback DepartmentHandler headers — X-User-ID 'handler-fallback'.

    PRD §2.1: DepartmentHandler ownership-gated endpoints compare
    X-User-ID to the LEAD assignment's handler_id; this constant matches
    no real Handler.id, so use it only for tests that do NOT exercise
    ownership (missing-auth, wrong-role, missing-resource scenarios).
    """
    return TEST_USERS["department_handler_headers"]
