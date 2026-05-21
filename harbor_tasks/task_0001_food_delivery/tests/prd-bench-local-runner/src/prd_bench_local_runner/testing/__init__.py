"""
prd_bench_local_runner.testing — Generic testing utilities for API compliance tests.

Provides domain-agnostic infrastructure that every test suite needs:
- GenericApiClient: base HTTP client with _request() method
- Response validators: validate_success, validate_error, validate_paginated, etc.
- Common assertions: UUID, timestamp, cost precision, version increment, race outcomes
- Role header builder: build_user_headers()
- Constants: NON_EXISTENT_UUID

Domain-specific code (endpoint methods, payload factories, entity assertions,
business constants, composite fixtures) is written separately and imports from here.
"""

from .client import GenericApiClient
from .validators import (
    validate_success,
    validate_error,
    validate_paginated,
    validate_error_is_one_of,
    get_success_data,
)
from .assertions import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
    assert_version_incremented,
    assert_timestamp_format,
    assert_race_outcome,
    assert_exactly_one_succeeds,
    assert_at_least_one_succeeds,
    run_race,
)
from .headers import build_user_headers
from .constants import NON_EXISTENT_UUID

__all__ = [
    # Client
    "GenericApiClient",
    # Validators
    "validate_success",
    "validate_error",
    "validate_paginated",
    "validate_error_is_one_of",
    "get_success_data",
    # Assertions
    "is_valid_uuid",
    "is_iso8601_timestamp",
    "assert_cost_precision",
    "assert_version_incremented",
    "assert_timestamp_format",
    "assert_race_outcome",
    "assert_exactly_one_succeeds",
    "assert_at_least_one_succeeds",
    "run_race",
    # Headers
    "build_user_headers",
    # Constants
    "NON_EXISTENT_UUID",
]
