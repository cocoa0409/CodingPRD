"""
Test infrastructure for the Neurodiagnostic EMU API suite.

Importing this package registers the error_id -> HTTP status map with the
framework validators, so `validate_error` cross-checks statuses everywhere.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    assert_timestamp_format,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import api_errors, assertions, constants, factories, fixtures, test_users
from .api_client import ApiClient
from .api_errors import ERROR_HTTP_STATUS
from .assertions import (
    assert_admission_dimensions,
    assert_alert_dimensions,
    assert_append_only_preamble,
    assert_capture_value,
    assert_case_tallies,
    assert_fields_null,
    assert_fields_zero,
    assert_full_preamble,
    assert_id_set,
    assert_ids_equal,
    assert_instant_equals,
    assert_ledger,
    assert_ledger_conserved,
    assert_storage_value,
    assert_study_dimensions,
    assert_turnaround_value,
    assert_unit_storage,
    assert_version_is,
    assert_whole_minutes,
)
from .fixtures import Baseline

__all__ = [
    "ApiClient",
    "Baseline",
    "ERROR_HTTP_STATUS",
    "NON_EXISTENT_UUID",
    "api_errors",
    "assert_admission_dimensions",
    "assert_alert_dimensions",
    "assert_append_only_preamble",
    "assert_capture_value",
    "assert_case_tallies",
    "assert_fields_null",
    "assert_fields_zero",
    "assert_full_preamble",
    "assert_id_set",
    "assert_ids_equal",
    "assert_instant_equals",
    "assert_ledger",
    "assert_ledger_conserved",
    "assert_storage_value",
    "assert_study_dimensions",
    "assert_timestamp_format",
    "assert_turnaround_value",
    "assert_unit_storage",
    "assert_version_is",
    "assert_whole_minutes",
    "assertions",
    "build_user_headers",
    "constants",
    "factories",
    "fixtures",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "test_users",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
