"""Pytest fixture bridge — exposes the test_helpers utilities as
pytest fixtures, so the test functions take the helpers as named
parameters rather than importing the module-level singletons.

The PYTHONPATH that makes the sibling `test_helpers` package importable
is set by the prd-bench Docker harness before the pytest subprocess
starts, so this file does no `sys.path` manipulation.

Per the PRD §2.7 logical-wall-clock contract, the harness's
`/_clock/advance` operator endpoint is the only way to push time
forward; the `clock_anchor` fixture exposes the deterministic
TIME_ANCHOR_UNIX_SECONDS constant from the factories module so each
test can derive its window relative to a stable epoch.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Make the sibling test_helpers package importable without relying on a
# pyproject.toml — the test_helpers directory sits next to the
# test_suite directory at the task root.  The runner harness's
# PYTHONPATH normally covers this, but the explicit sys.path insertion
# is a safety net for invocations that do not set it.
_HERE = Path(__file__).resolve().parent
_TASK_ROOT = _HERE.parent
if str(_TASK_ROOT) not in sys.path:
    sys.path.insert(0, str(_TASK_ROOT))

import pytest

from test_helpers import (  # noqa: E402
    ADMIN_HEADERS,
    AUDIT_HEADERS,
    LIAISON_HEADERS,
    PRODUCER_HEADERS,
    SPONSOR_HEADERS,
    STAGE_HEADERS,
    TEST_USERS,
    TICKETING_HEADERS,
    UNKNOWN_ROLE_HEADERS,
    NO_HEADERS,
    ApiClient,
    api_client as _api_client_singleton,
)
from test_helpers.factories import TIME_ANCHOR_UNIX_SECONDS  # noqa: E402


@pytest.fixture(scope="session")
def api() -> ApiClient:
    """Session-scoped HTTP client.  The server's lifecycle is managed by
    the prd-bench Docker harness; this fixture does not start or stop
    the server."""
    # The base URL is read from API_BASE_URL by the client at import
    # time; here we just hand back the module-level singleton so every
    # test reuses the same HTTP connection pool.
    return _api_client_singleton


# ---------------------------------------------------------------------------
# Per-role header fixtures, one per concrete role from PRD §2.1.
# ---------------------------------------------------------------------------


@pytest.fixture
def producer_headers():
    return PRODUCER_HEADERS


@pytest.fixture
def liaison_headers():
    return LIAISON_HEADERS


@pytest.fixture
def stage_headers():
    return STAGE_HEADERS


@pytest.fixture
def ticketing_headers():
    return TICKETING_HEADERS


@pytest.fixture
def sponsor_headers():
    return SPONSOR_HEADERS


@pytest.fixture
def audit_headers():
    return AUDIT_HEADERS


@pytest.fixture
def admin_headers():
    return ADMIN_HEADERS


@pytest.fixture
def unknown_role_headers():
    """A header bundle whose X-User-Role is a string outside the seven
    concrete role names — for the PRD §2.1 unknown-role gate test."""
    return UNKNOWN_ROLE_HEADERS


@pytest.fixture
def no_headers():
    """Empty header bundle — for the PRD §2.1 missing-header gate test
    which surfaces ERR_MISSING_USER_CONTEXT_HEADER at HTTP 400."""
    return NO_HEADERS


@pytest.fixture
def all_test_users():
    """The full mapping of role-name-key → header bundle."""
    return TEST_USERS


@pytest.fixture(scope="session")
def time_anchor() -> int:
    """The deterministic anchor in Unix seconds that the factories
    module uses as the default start of a festival's bookable window.
    Tests can build wall-clock arithmetic relative to this anchor and
    drive the `/_clock/advance` endpoint to land on the right
    threshold."""
    return TIME_ANCHOR_UNIX_SECONDS
