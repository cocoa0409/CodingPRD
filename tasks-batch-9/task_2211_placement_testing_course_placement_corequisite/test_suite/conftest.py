"""Shared pytest wiring for the PRD compliance suite.

The harness relaunches the API server before every individual test, so each test
begins against an empty database and every precondition is built from scratch
through the endpoints the PRD declares.  Nothing here mutates server state.
"""
import pytest

from test_helpers import api_client as _api_client
from test_helpers.test_users import (
    make_assessment_director_headers,
    make_assessment_staff_headers,
    make_instructor_headers,
    make_proctor_headers,
    make_registrar_headers,
    make_system_admin_headers,
)


@pytest.fixture(scope="session")
def api():
    """The stateless HTTP client every test drives the API through."""
    return _api_client


@pytest.fixture
def system_admin_headers():
    return make_system_admin_headers()


@pytest.fixture
def assessment_director_headers():
    return make_assessment_director_headers()


@pytest.fixture
def assessment_staff_headers():
    return make_assessment_staff_headers()


@pytest.fixture
def proctor_headers():
    return make_proctor_headers()


@pytest.fixture
def instructor_headers():
    return make_instructor_headers()


@pytest.fixture
def registrar_headers():
    return make_registrar_headers()
