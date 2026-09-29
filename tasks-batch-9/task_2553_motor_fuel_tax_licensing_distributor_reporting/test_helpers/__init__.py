"""Test infrastructure for the Motor Fuel Tax Licensing & Distributor Reporting API.

Importing this package gives a test everything it needs: the framework's generic
validators, the typed client, the error catalogue, the domain assertions, the
payload factories, the domain constants and the composite fixtures.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    GenericApiClient,
    assert_at_least_one_succeeds,
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

from .types import *  # noqa: F401,F403
from .api_client import (  # noqa: F401
    ApiClient,
    api_client,
    make_audit_manager_headers,
    make_field_inspector_headers,
    make_licensee_agent_headers,
    make_licensing_officer_headers,
    make_returns_examiner_headers,
    make_tax_supervisor_headers,
)
from .api_errors import HTTP_STATUS_CODES, ApiErrorId  # noqa: F401
from .assertions import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .constants import *  # noqa: F401,F403
from .test_users import (  # noqa: F401
    ALL_ROLES,
    AUDIT_MANAGER_ALT_ID,
    AUDIT_MANAGER_ID,
    FIELD_INSPECTOR_ID,
    LICENSING_OFFICER_ID,
    OPERATOR_ROLES,
    RETURNS_EXAMINER_ALT_ID,
    RETURNS_EXAMINER_ID,
    ROLE_AUDIT_MANAGER,
    ROLE_FIELD_INSPECTOR,
    ROLE_LICENSEE_AGENT,
    ROLE_LICENSING_OFFICER,
    ROLE_RETURNS_EXAMINER,
    ROLE_TAX_SUPERVISOR,
    TAX_SUPERVISOR_ALT_ID,
    TAX_SUPERVISOR_ID,
    TEST_USERS,
    headers_for,
)
from .fixtures import BuiltReturn, MftWorld, clock_default, world  # noqa: F401
