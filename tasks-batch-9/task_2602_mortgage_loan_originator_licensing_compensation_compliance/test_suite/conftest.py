"""Shared fixtures for the suite.

The runner starts a fresh server with an empty store before every test, so
each fixture builds the preconditions it needs from scratch through the API.
"""
import pytest

from test_helpers.api_client import ApiClient
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    authorized_originator,
    locked_loan,
    originator_with_plan,
)
from test_helpers.test_users import (
    admin_headers,
    analyst_headers,
    designer_headers,
    examiner_headers,
    loan_ops_headers,
    officer_headers,
)


@pytest.fixture
def api():
    """A client bound to the server the runner started for this test."""
    return ApiClient()


@pytest.fixture
def analyst():
    """Licensing desk headers."""
    return analyst_headers()


@pytest.fixture
def designer():
    """Compensation plan designer headers."""
    return designer_headers()


@pytest.fixture
def officer():
    """Compliance officer headers."""
    return officer_headers()


@pytest.fixture
def loan_ops():
    """Closing and servicing desk headers."""
    return loan_ops_headers()


@pytest.fixture
def examiner():
    """Examination coordinator headers."""
    return examiner_headers()


@pytest.fixture
def admin():
    """Platform administrator headers: the clock and the nightly sweep."""
    return admin_headers()
