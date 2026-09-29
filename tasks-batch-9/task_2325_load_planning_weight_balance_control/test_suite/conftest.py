"""Shared pytest wiring for the load planning and weight-and-balance suite.

Importing ``test_helpers`` installs the error-id to HTTP status map that the
framework's ``validate_error`` uses, so every test module gets consistent status
checking simply by importing this package.
"""

from __future__ import annotations

import pytest

import test_helpers
from test_helpers import api_client


@pytest.fixture
def client():
    """The typed API client bound to the runner-supplied base URL."""
    return api_client


@pytest.fixture(autouse=True)
def _error_status_map():
    """Ensure the contract's error-id to HTTP status map is registered."""
    from prd_bench_local_runner.testing.validators import set_error_http_status_map

    set_error_http_status_map(test_helpers.HTTP_STATUS_CODES)
    yield
