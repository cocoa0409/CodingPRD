"""
FleetCare test infrastructure.

Importing this package registers the error catalogue with the framework validators,
so ``validate_error`` cross-checks the HTTP status of every error a test names.

Everything a test needs is re-exported here: the client, the payload factories, the
domain assertions, the business constants, the role headers and the composite setup
builders. Tests should import from ``test_helpers`` and never reach into a submodule
or into ``prd_bench_local_runner`` directly, except for the generic validators which
are re-exported below for convenience.
"""

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

from . import api_errors  # noqa: F401  (registers the error/status map on import)
from .api_client import FleetCareClient
from .api_errors import ERROR_HTTP_STATUS  # noqa: F401
from .api_errors import *  # noqa: F401,F403  (every ERR_* identifier)
from .assertions import (
    assert_common_fields,
    assert_created_at_ascending,
    assert_envelope_meta,
    assert_error_envelope,
    assert_fields,
    assert_instant,
    assert_iso8601_millis,
    assert_money,
    assert_null_fields,
    assert_pagination_meta,
    assert_part_inventory_identity,
    assert_parts_allowance_identity,
    assert_score_precision,
    assert_technician_capacity_identity,
    assert_two_decimals,
    canonical_instant,
    expected_credit_cents,
    expected_pm_compliance_pct,
)
from .constants import *  # noqa: F401,F403
from .factories import (
    allowance_adjustment_payload,
    call_cancel_payload,
    checklist_item,
    checklist_result_payload,
    club_payload,
    contract_payload,
    credit_reconciliation_payload,
    dispatch_payload,
    duty_status_payload,
    equipment_model_payload,
    equipment_payload,
    inventory_adjustment_payload,
    part_order_cancel_payload,
    part_payload,
    parts_hold_payload,
    preventive_visit_payload,
    quote_decline_payload,
    release_payload,
    renewal_quote_payload,
    resolve_payload,
    safety_doc_reject_payload,
    safety_doc_submit_payload,
    service_call_payload,
    suspend_payload,
    tag_out_payload,
    technician_payload,
    usage_reading_payload,
    visit_cancel_payload,
    waive_payload,
)
from .fixtures import (
    activate_contract,
    admin,
    api,
    arrive_call,
    assignment_for_call,
    assignment_for_visit,
    build_fleet,
    call_on_site,
    contract_version,
    coordinator,
    dispatch_call,
    event_for_call,
    inspector_headers,
    manager_headers,
    new_active_contract,
    new_club,
    new_contract,
    new_equipment,
    new_model,
    new_part,
    new_technician,
    open_call,
    place_hold,
    planner,
    read_assignment,
    read_call,
    read_club,
    read_contract,
    read_equipment,
    read_event,
    read_part,
    read_part_order,
    read_quote,
    read_technician,
    read_visit,
    record_usage,
    rows_of,
    schedule_visit,
    set_clock,
    start_visit,
    technician_headers,
)
from .test_users import (
    CONTRACT_ADMIN,
    PARTS_PLANNER,
    SERVICE_COORDINATOR,
    headers_for_role,
    make_club_manager_headers,
    make_contract_admin_headers,
    make_field_technician_headers,
    make_parts_planner_headers,
    make_safety_inspector_headers,
    make_service_coordinator_headers,
)
from .types import (
    ALL_ROLES,
    ENTITY_BACKED_ROLES,
    OPAQUE_ROLES,
    ROLE_CLUB_MANAGER,
    ROLE_CONTRACT_ADMINISTRATOR,
    ROLE_FIELD_TECHNICIAN,
    ROLE_PARTS_PLANNER,
    ROLE_SAFETY_INSPECTOR,
    ROLE_SERVICE_COORDINATOR,
)
