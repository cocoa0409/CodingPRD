"""Barrel export: framework generics + PRD-specific helpers."""
# Framework generics (re-exported for convenience)
from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
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

# PRD-specific
from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    assert_bindery_ticket,
    assert_customer,
    assert_estimate,
    assert_gang_run,
    assert_invoice,
    assert_invoice_monetary_conservation,
    assert_job,
    assert_mail_drop,
    assert_paper_lot,
    assert_paper_purchase_order,
    assert_paper_stock,
    assert_press,
    assert_press_run,
    assert_proof,
    assert_reprint_claim,
)
from .constants import *  # noqa: F401,F403
from .factories import *  # noqa: F401,F403
from .test_users import TEST_USERS, make_customer_headers, make_plant_manager_headers
from .fixtures import *  # noqa: F401,F403
from .types import *  # noqa: F401,F403
