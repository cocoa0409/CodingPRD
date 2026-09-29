"""
pytest wiring for the WIC vendor authorization compliance suite.

The server is restarted before every test, so each test starts against an empty
database and builds the state it needs through the documented endpoints. All
fixtures here are therefore function-scoped.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import (  # noqa: E402
    ANALYST_HEADERS,
    ANALYST_TWO_HEADERS,
    INVESTIGATOR_HEADERS,
    INVESTIGATOR_TWO_HEADERS,
    SUPERVISOR_HEADERS,
    SUPERVISOR_TWO_HEADERS,
    SYSTEM_HEADERS,
    ApiClient,
    fixtures,
)


@pytest.fixture
def api() -> ApiClient:
    """A client bound to the API under test."""
    return ApiClient()


# ---------------------------------------------------------------------------
# Header fixtures for the four opaque roles
# ---------------------------------------------------------------------------


@pytest.fixture
def analyst_headers():
    return ANALYST_HEADERS


@pytest.fixture
def analyst_two_headers():
    return ANALYST_TWO_HEADERS


@pytest.fixture
def supervisor_headers():
    return SUPERVISOR_HEADERS


@pytest.fixture
def supervisor_two_headers():
    return SUPERVISOR_TWO_HEADERS


@pytest.fixture
def investigator_headers():
    return INVESTIGATOR_HEADERS


@pytest.fixture
def investigator_two_headers():
    return INVESTIGATOR_TWO_HEADERS


@pytest.fixture
def system_headers():
    return SYSTEM_HEADERS


# ---------------------------------------------------------------------------
# Composite state
# ---------------------------------------------------------------------------


@pytest.fixture
def catalogue(api):
    """The peer group, the milk category and item, and an open price cycle."""
    return fixtures.bootstrap_catalogue(api)


@pytest.fixture
def catalogue_with_juice(api):
    """The catalogue plus a second, non-required category and item."""
    return fixtures.bootstrap_catalogue(api, with_juice=True)


@pytest.fixture
def authorized_vendor(api):
    """The catalogue and one AUTHORIZED vendor; the cycle is still open."""
    return fixtures.authorized_vendor_setup(api)


@pytest.fixture
def published_ceiling(api):
    """The backbone with the cycle closed and published, giving one ACTIVE ceiling."""
    return fixtures.published_ceiling_setup(api)


@pytest.fixture
def adjudicated_claim(api):
    """The backbone plus one adjudicated single-line claim."""
    return fixtures.adjudicated_claim_setup(api)


@pytest.fixture
def pending_adjustment(api):
    """The backbone, an adjudicated claim, and one PENDING adjustment."""
    return fixtures.pending_adjustment_setup(api)


@pytest.fixture
def served_case(api):
    """The backbone plus one sanction case in NOTICE_SERVED."""
    return fixtures.served_case_setup(api)


@pytest.fixture
def failed_visit(api):
    """The backbone plus one failed routine visit."""
    return fixtures.failed_visit_setup(api)


@pytest.fixture
def two_authorized_vendors(api):
    """Two AUTHORIZED vendors inside the same peer group."""
    return fixtures.two_authorized_vendors_setup(api)
