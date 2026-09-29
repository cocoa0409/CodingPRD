"""Pytest fixtures exposing the shared test infrastructure.

The harness starts the service and publishes its base URL before pytest runs,
so nothing here launches, stops or health-checks a server.
"""

import pytest

from test_helpers import AdvocacyClient
from test_helpers.test_users import (
    TEST_USERS,
    USER_CAMPAIGN_DIRECTOR,
    USER_COMPLIANCE_OFFICER,
    USER_FIELD_ORGANIZER,
    USER_MESSAGE_STRATEGIST,
    make_campaign_director_headers,
    make_compliance_officer_headers,
    make_field_organizer_headers,
    make_message_strategist_headers,
)


@pytest.fixture(scope="session")
def api() -> AdvocacyClient:
    """A client pointed at the running service."""
    return AdvocacyClient()


@pytest.fixture
def test_users() -> dict:
    """The shared identity table, keyed by role name."""
    return TEST_USERS


# --------------------------------------------------------------------------
# Header fixtures, one per role that has a fixed operator identity
# --------------------------------------------------------------------------

@pytest.fixture
def director_headers() -> dict:
    """Headers for the campaign director who runs the campaigns under test."""
    return make_campaign_director_headers(USER_CAMPAIGN_DIRECTOR)


@pytest.fixture
def organizer_headers() -> dict:
    """Headers for the field organizer who enrols supporters and files actions."""
    return make_field_organizer_headers(USER_FIELD_ORGANIZER)


@pytest.fixture
def compliance_headers() -> dict:
    """Headers for the compliance officer who reviews copy and clears waves."""
    return make_compliance_officer_headers(USER_COMPLIANCE_OFFICER)


@pytest.fixture
def strategist_headers() -> dict:
    """Headers for the message strategist who authors copy and segments."""
    return make_message_strategist_headers(USER_MESSAGE_STRATEGIST)
