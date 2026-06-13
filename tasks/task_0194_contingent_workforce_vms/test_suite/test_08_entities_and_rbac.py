"""Entity creation, field validity, eligibility gates, RBAC, and filtered
listing (§3.1, §2.9, §2.1, §2.5).
"""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated, ApiErrorId,
    get_success_data, build_user_headers, make_supplier_headers, TEST_USERS,
    create_program, create_supplier, create_worker, create_requisition,
    distribute, create_submittal, setup_distributed_requisition,
)
from test_helpers import factories as F

PM = TEST_USERS["program_manager_headers"]
HM = TEST_USERS["hiring_manager_headers"]
FIN = TEST_USERS["finance_headers"]
NON_EXISTENT = "00000000-0000-4000-8000-000000000000"


# ===========================================================================
# Queue B: entities / create_program_returns_201_with_all_fields
# ===========================================================================

def test_create_program_returns_201_active_with_clock(api):
    """PRD §3.1: "On creation the program's `status` is `ACTIVE` and its
    `current_clock` is set to `1970-01-01T00:00:00.000Z`."
    PRD §2.4: "a `version`, an integer that starts at its initial value and
    increments by one on each mutation."

    Design: Corner/entities/create_program_returns_201_with_all_fields
    """
    data = validate_success(api.create_program(F.create_program_payload(), PM),
                            expected_status=201)
    assert data["status"] == "ACTIVE", f"got {data['status']}"
    assert data["version"] == 1, f"got {data['version']}"
    assert data["current_clock"] == "1970-01-01T00:00:00.000Z", f"got {data['current_clock']}"


# ===========================================================================
# Queue B: entities / get_program_not_found_returns_404
# ===========================================================================

def test_get_nonexistent_program_returns_not_found(api):
    """PRD §2.5: "any referenced resource that does not exist yields
    `ERR_NOT_FOUND`."

    Design: Corner/entities/get_program_not_found_returns_404
    """
    validate_error(api.get_program(NON_EXISTENT, PM), ApiErrorId.ERR_NOT_FOUND.value)


# ===========================================================================
# Queue B: entities / create_supplier_missing_required_field_returns_invalid_request
# ===========================================================================

def test_create_supplier_missing_tier_rejected(api):
    """PRD §3.11: "every write endpoint validates the shape of its request body:
    ... required fields must be present ... A body that violates any of these
    field-level rules is rejected with `ERR_INVALID_REQUEST`."

    Omitting the required `tier` field -> ERR_INVALID_REQUEST.

    Design: Corner/entities/create_supplier_missing_required_field_returns_invalid_request
    """
    program = create_program()
    validate_error(
        api.create_supplier({"program_id": program["id"], "name": "Acme"}, PM),
        ApiErrorId.ERR_INVALID_REQUEST.value,
    )


# ===========================================================================
# Queue B: entities / program_threshold_warning_not_less_than_limit_rejected
# ===========================================================================

def test_program_warning_threshold_not_below_limit_rejected(api):
    """PRD §3.1: "If `tenure_warning_threshold_days` is not strictly less than
    `coemployment_tenure_limit_days`, creation is rejected with
    `ERR_THRESHOLD_INVALID`."

    Design: Corner/entities/program_threshold_warning_not_less_than_limit_rejected
    """
    validate_error(
        api.create_program(F.create_program_payload(
            coemployment_tenure_limit_days=100, tenure_warning_threshold_days=100), PM),
        ApiErrorId.ERR_THRESHOLD_INVALID.value,
    )


# ===========================================================================
# Queue B: entities / supplier_tier_below_one_rejected
# ===========================================================================

def test_supplier_tier_zero_rejected(api):
    """PRD §3.1: "A supplier registered with a `tier` below 1 is rejected with
    `ERR_TIER_INVALID`."

    Design: Corner/entities/supplier_tier_below_one_rejected
    """
    program = create_program()
    validate_error(
        api.create_supplier(F.create_supplier_payload(program["id"], tier=0), PM),
        ApiErrorId.ERR_TIER_INVALID.value,
    )


# ===========================================================================
# Queue B: entities / worker_computed_fields_initialized_input_ignored
# ===========================================================================

def test_new_worker_computed_fields_initialized(api):
    """PRD §3.1: "A new profile starts with `cumulative_engaged_days` of 0 and a
    `tenure_status` of `CLEAR`; both of those are computed fields that the system
    maintains as assignments accrue, never client inputs."

    Design: Corner/entities/worker_computed_fields_initialized_input_ignored
    """
    program = create_program()
    data = validate_success(api.create_worker(
        F.create_worker_payload(program["id"]), PM), expected_status=201)
    assert data["cumulative_engaged_days"] == 0, f"got {data['cumulative_engaged_days']}"
    assert data["tenure_status"] == "CLEAR", f"got {data['tenure_status']}"


# ===========================================================================
# Queue B: entities / duplicate_national_id_hash_rejected
# ===========================================================================

def test_duplicate_national_id_hash_in_program_rejected(api):
    """PRD §2.9: "A `WorkerProfile` is unique within its program by
    `national_id_hash`: attempting to register a second worker with a
    `national_id_hash` already used in the same program is rejected with
    `ERR_DUPLICATE_WORKER`."

    Design: Corner/entities/duplicate_national_id_hash_rejected
    """
    program = create_program()
    create_worker(program["id"], full_name="W1", national_id_hash="h1")
    validate_error(
        api.create_worker(F.create_worker_payload(
            program["id"], full_name="W2", national_id_hash="h1"), PM),
        ApiErrorId.ERR_DUPLICATE_WORKER.value,
    )


# ===========================================================================
# Queue B: validations / distribute_to_suspended_supplier_rejected
# ===========================================================================

def test_distribute_to_suspended_supplier_rejected(api):
    """PRD §3.2: "every listed supplier must be `ACTIVE` and belong to this
    program, or the request fails with `ERR_SUPPLIER_NOT_ELIGIBLE`."
    PRD §2.9: "a `SUSPENDED` supplier may neither receive a distribution nor
    create submittals"

    Design: Corner/validations/distribute_to_suspended_supplier_rejected
    """
    program = create_program()
    supplier = create_supplier(program["id"])
    get_success_data(api.suspend_supplier(supplier["id"], PM))
    req = create_requisition(program["id"])
    validate_error(
        api.distribute_requisition(req["id"], {"supplier_ids": [supplier["id"]]}, PM),
        ApiErrorId.ERR_SUPPLIER_NOT_ELIGIBLE.value,
    )


# ===========================================================================
# Queue B: errors / program_not_active_blocks_distribute
# ===========================================================================

def test_distribute_when_program_suspended_rejected(api):
    """PRD §3.2: "The program must be `ACTIVE`, or the request fails with
    `ERR_PROGRAM_NOT_ACTIVE`"
    PRD §2.9: "Operations that require an active program — distributing a
    requisition and activating a statement of work — are rejected with
    `ERR_PROGRAM_NOT_ACTIVE` when the program is not `ACTIVE`."

    Design: Corner/errors/program_not_active_blocks_distribute
    """
    program = create_program()
    supplier = create_supplier(program["id"])
    req = create_requisition(program["id"])
    get_success_data(api.suspend_program(program["id"], PM))
    validate_error(
        api.distribute_requisition(req["id"], {"supplier_ids": [supplier["id"]]}, PM),
        ApiErrorId.ERR_PROGRAM_NOT_ACTIVE.value,
    )


# ===========================================================================
# Queue B: rbac / supplier_cannot_approve_timesheet
# ===========================================================================

def test_supplier_cannot_approve_timesheet(api):
    """PRD §4: timesheet approve is authorized for `HiringManager` only.
    PRD §2.1: "When a caller's role is well-formed but not permitted to perform
    the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    A Supplier calling the HiringManager-only approve -> ERR_FORBIDDEN_FOR_ROLE.

    Design: Corner/rbac/supplier_cannot_approve_timesheet
    """
    from test_helpers import setup_submitted_timesheet
    base = setup_submitted_timesheet(
        program_overrides={"coemployment_tenure_limit_days": 3650,
                           "tenure_warning_threshold_days": 3000})
    validate_error(api.approve_timesheet(base["timesheet"]["id"], base["supplier_headers"]),
                   ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Queue B: rbac / finance_cannot_create_program
# ===========================================================================

def test_finance_cannot_create_program(api):
    """PRD §4: program creation is authorized for `ProgramManager` only.
    PRD §2.1: "When a caller's role is well-formed but not permitted to perform
    the requested operation, the request is rejected with
    `ERR_FORBIDDEN_FOR_ROLE`."

    Design: Corner/rbac/finance_cannot_create_program
    """
    validate_error(api.create_program(F.create_program_payload(), FIN),
                   ApiErrorId.ERR_FORBIDDEN_FOR_ROLE.value)


# ===========================================================================
# Queue B: rbac / missing_user_context_header_rejected
# ===========================================================================

def test_missing_user_role_header_rejected(api):
    """PRD §2.1: "Every request to the API must carry two mandatory headers:
    `X-User-ID`, identifying the acting user, and `X-User-Role`, declaring the
    capacity in which they act. A request missing either header, or carrying a
    malformed value, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    Design: Corner/rbac/missing_user_context_header_rejected
    """
    headers = {"X-User-ID": "someone", "Content-Type": "application/json"}
    validate_error(api.get_program(NON_EXISTENT, headers),
                   ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER.value)


# ===========================================================================
# Queue B: endpoints / list_submittals_filtered_by_requisition
# ===========================================================================

def test_list_submittals_filtered_by_requisition(api):
    """PRD §2.5: "distributions and submittals [can be filtered] by
    `requisition_id` and `supplier_id`"
    PRD §2.3: "List responses carry the pagination fields `limit`, `offset`,
    `total_count`, and `has_more` in the `meta` object of the envelope."

    Design: Corner/endpoints/list_submittals_filtered_by_requisition
    """
    base = setup_distributed_requisition()
    sub = create_submittal(base["requisition"]["id"], base["supplier"]["id"],
                           base["worker"]["id"], pay_rate_cents=8000)
    data, meta = validate_paginated(
        api.list_submittals(PM, params={"requisition_id": base["requisition"]["id"]}))
    assert meta["total_count"] == 1, f"got {meta['total_count']}"
    assert data[0]["id"] == sub["id"]
