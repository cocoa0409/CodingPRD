"""Test infrastructure for the Superfund site remediation service.

Import surface:

* `api_client` / `ApiClient` -- one method per endpoint in the PRD.
* `TEST_USERS` and the `make_*_headers` builders -- role headers, including the
  two entity-backed roles whose `X-User-ID` is an entity identifier.
* `ApiErrorId` / `HTTP_STATUS_CODES` -- the error catalogue and its statuses.
* `factories` -- request payload builders.
* `assertions` -- domain assertion helpers, re-exporting the framework
  validators so a test file needs only one import site.
* `fixtures` -- lifecycle builders and the composite pytest fixtures.
"""
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
    assert_cost_precision,
    assert_exactly_one_succeeds,
    assert_race_outcome,
    assert_timestamp_format,
    assert_version_incremented,
    build_user_headers,
    get_success_data,
    is_iso8601_timestamp,
    is_valid_uuid,
    run_race,
    validate_error,
    validate_error_is_one_of,
    validate_paginated,
    validate_success,
)

from . import assertions, constants, factories
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .test_users import (
    AUTHOR_PM_ID,
    COMMUNITY_ID,
    COUNSEL_ID,
    FACILITATOR_ID,
    REVIEWER_PM_ID,
    SIGNER_PM_ID,
    TEST_USERS,
    make_community_headers,
    make_contractor_headers,
    make_counsel_headers,
    make_facilitator_headers,
    make_headers,
    make_project_manager_headers,
    make_prp_representative_headers,
)

__all__ = [
    "ApiClient",
    "ApiErrorId",
    "AUTHOR_PM_ID",
    "COMMUNITY_ID",
    "COUNSEL_ID",
    "FACILITATOR_ID",
    "GenericApiClient",
    "HTTP_STATUS_CODES",
    "NON_EXISTENT_UUID",
    "REVIEWER_PM_ID",
    "SIGNER_PM_ID",
    "TEST_USERS",
    "api_client",
    "assert_at_least_one_succeeds",
    "assert_cost_precision",
    "assert_exactly_one_succeeds",
    "assert_race_outcome",
    "assert_timestamp_format",
    "assert_version_incremented",
    "assertions",
    "build_user_headers",
    "constants",
    "factories",
    "get_success_data",
    "is_iso8601_timestamp",
    "is_valid_uuid",
    "make_community_headers",
    "make_contractor_headers",
    "make_counsel_headers",
    "make_facilitator_headers",
    "make_headers",
    "make_project_manager_headers",
    "make_prp_representative_headers",
    "run_race",
    "validate_error",
    "validate_error_is_one_of",
    "validate_paginated",
    "validate_success",
]
