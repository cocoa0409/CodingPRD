"""Test infrastructure for the dependent eligibility verification audit API."""
from __future__ import annotations

from prd_bench_local_runner.testing.validators import set_error_http_status_map

from . import api_errors, assertions, constants, factories, fixtures, test_users, types
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS
from .fixtures import Builder
from .types import Ctx

set_error_http_status_map(ERROR_HTTP_STATUS)

__all__ = [
    "ApiClient",
    "Builder",
    "Ctx",
    "ERROR_HTTP_STATUS",
    "api_errors",
    "assertions",
    "constants",
    "factories",
    "fixtures",
    "test_users",
    "types",
]
