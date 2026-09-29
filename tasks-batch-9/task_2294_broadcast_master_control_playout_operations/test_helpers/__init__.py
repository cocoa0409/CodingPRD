"""Test helper package for the Broadcast Master Control API.

Re-exports the framework generics alongside this domain's client, vocabularies,
error catalogue, payload factories, entity assertions and composite fixtures so
a test module needs a single import site.
"""
from prd_bench_local_runner.testing import (
    GenericApiClient,
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

from .api_client import ApiClient, api_client
from .api_errors import HTTP_STATUS_CODES, ApiErrorId
from .assertions import (
    as_run_kinds,
    assert_append_only_common_fields,
    assert_as_run_entry,
    assert_asset,
    assert_assigned_equals_channel_sum,
    assert_bandwidth_conservation,
    assert_channel,
    assert_envelope_meta,
    assert_feed_window,
    assert_full_common_fields,
    assert_multiplex,
    assert_operator,
    assert_override,
    assert_playlist,
    assert_playlist_item,
    assert_qc_report,
    assert_regulatory_notification,
    assert_spot_count_conservation,
    assert_spot_order,
    assert_tail_seconds_conservation,
    assert_technical_fault,
    assert_transmitter,
    item_by_sequence,
)
from .constants import CLOCK_DEFAULT_UTC, TEST_DEFAULTS, THRESHOLDS
from . import factories
from . import fixtures
from .test_users import (
    ADMIN,
    COMPLIANCE,
    TEST_USERS,
    TRAFFIC,
    make_admin_headers,
    make_compliance_headers,
    make_engineer_headers,
    make_headers,
    make_master_control_headers,
    make_program_director_headers,
    make_qc_headers,
    make_traffic_headers,
)
from . import types
