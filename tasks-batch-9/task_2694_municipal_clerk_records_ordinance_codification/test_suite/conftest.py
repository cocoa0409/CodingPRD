"""Shared pytest fixtures for the Municipal Clerk Records & Ordinance
Codification suite.

The harness restarts the API against an empty database before every individual
test, so each fixture rebuilds the state it needs from scratch through the
endpoints PRD section 4 declares. Importing ``test_helpers`` also registers the
error-id to HTTP-status mapping of PRD section 5 with the runner's validators.
"""

from typing import Any, Dict

import pytest

from test_helpers import api_client as _api_client
from test_helpers import fixtures as fx


@pytest.fixture
def client():
    """The HTTP client for the ``/clerk`` surface."""
    return _api_client


@pytest.fixture
def venue() -> Dict[str, Any]:
    """One AVAILABLE venue, the precondition for scheduling any meeting."""
    return fx.create_venue()


@pytest.fixture
def scheduled_meeting() -> Dict[str, Any]:
    """A venue plus a COUNCIL / REGULAR meeting in its initial SCHEDULED state."""
    return fx.scheduled_meeting()


@pytest.fixture
def noticed_meeting() -> Dict[str, Any]:
    """A meeting driven to NOTICED behind a posted one-item agenda packet."""
    return fx.noticed_meeting()


@pytest.fixture
def meeting_in_session() -> Dict[str, Any]:
    """A NOTICED meeting called to order with five members present."""
    return fx.in_session_meeting(5)


@pytest.fixture
def adjourned_meeting() -> Dict[str, Any]:
    """An adjourned meeting whose DRAFT minutes exist."""
    return fx.adjourned_meeting_with_minutes(5)


@pytest.fixture
def ordinance_series() -> Dict[str, Any]:
    """An OPEN 2026 ORDINANCE numbering series."""
    return fx.create_number_series()


@pytest.fixture
def resolution_series() -> Dict[str, Any]:
    """An OPEN 2026 RESOLUTION numbering series."""
    return fx.create_number_series(instrument_class="RESOLUTION")


@pytest.fixture
def code_title() -> Dict[str, Any]:
    """One ACTIVE code title with no sections yet."""
    return fx.create_code_title()


@pytest.fixture
def open_cycle() -> Dict[str, Any]:
    """A code title carrying one OPEN supplement cycle."""
    return fx.code_title_with_open_cycle()


@pytest.fixture
def record_series() -> Dict[str, Any]:
    """One record series on the CREATION retention anchor, no accessions."""
    return fx.create_record_series()


@pytest.fixture
def records_request() -> Dict[str, Any]:
    """A public records request in RECEIVED / NOT_ASSESSED."""
    return fx.create_records_request()


@pytest.fixture
def request_under_review() -> Dict[str, Any]:
    """A public records request whose disclosure axis has been opened."""
    return fx.request_under_review()
