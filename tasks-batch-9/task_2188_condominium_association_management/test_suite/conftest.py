"""Shared pytest configuration for the condominium association test suite.

The runner restarts the server with an empty store before each test, so every
fixture here builds its world from scratch through the public API.
"""

from __future__ import annotations

from test_helpers import api_errors  # noqa: F401  (registers the error/status map)
from test_helpers.fixtures import (  # noqa: F401  (re-exported as fixtures)
    active_contract_association,
    adjuster_headers,
    api,
    attorney_headers,
    bare_association,
    board_association,
    manager_headers,
    roofed_board_association,
    title_agent_headers,
    two_owner_association,
)

__all__ = [
    "api",
    "manager_headers",
    "adjuster_headers",
    "attorney_headers",
    "title_agent_headers",
    "bare_association",
    "board_association",
    "two_owner_association",
    "roofed_board_association",
    "active_contract_association",
]
