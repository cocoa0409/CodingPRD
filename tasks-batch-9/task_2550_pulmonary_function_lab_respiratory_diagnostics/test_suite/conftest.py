"""Pytest wiring for the pulmonary function laboratory suite.

The harness owns the server: it is already listening when a test starts, it is
restarted between tests, and it reads ``API_BASE_URL`` from the environment.
Tests therefore never start, stop or health-check it — they only talk to it.

Because every test meets a freshly emptied database, each scenario builds its
own preconditions through the published endpoints.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from test_helpers import api_errors  # noqa: E402,F401  (registers error statuses)
from test_helpers.api_client import ApiClient  # noqa: E402
from test_helpers.test_users import (  # noqa: E402
    COMPLIANCE_AUDITOR,
    LAB_MANAGER,
)


@pytest.fixture
def api() -> ApiClient:
    """A client for the laboratory API, aimed at the harness's server."""
    return ApiClient()


@pytest.fixture
def manager_headers():
    """The lab manager's identity headers; the role is recognised on its own."""
    return LAB_MANAGER


@pytest.fixture
def auditor_headers():
    """The compliance auditor's identity headers."""
    return COMPLIANCE_AUDITOR
