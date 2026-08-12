"""Program, funding-pool, funder, and retailer creation rules (PRD §2.8, §3.1)."""
import pytest

from test_helpers import (
    validate_success, validate_error, NON_EXISTENT_UUID,
    assert_program, assert_funding_pool,
    create_program_payload, create_funder_payload, create_funding_pool_payload,
    create_retailer_payload,
    TEST_USERS,
    create_funder, create_program, get_pool,
)
from test_helpers import api_client

ADMIN = TEST_USERS["program_admin_headers"]


def test_program_creation_initializes_system_fields(api):
    """PRD §3.1: "At creation the program's `status` is DRAFT, its Double-Up
    ledger is untouched — `double_up_matched_cents` zero,
    `double_up_remaining_cents` equal to the full pool budget — and its
    `ops_run_index` starts at zero."

    Design: Corner/entities/c_program_creation_computed_defaults
    """
    res = api.create_program(create_program_payload(), ADMIN)
    program = validate_success(res, 201)
    assert_program(program)
    assert program["status"] == "DRAFT"
    assert program["ops_run_index"] == 0
    assert program["double_up_matched_cents"] == 0
    assert program["double_up_remaining_cents"] == 200000


def test_get_missing_program_returns_not_found(api):
    """PRD §2.10: "Third, existence: every referenced id must resolve — path
    parameters first, validated left to right, then body foreign keys in
    payload order — otherwise `ERR_NOT_FOUND`."

    Design: Corner/entities/c_get_missing_program_returns_not_found
    """
    res = api.get_program(NON_EXISTENT_UUID, ADMIN)
    validate_error(res, "ERR_NOT_FOUND")


def test_create_program_missing_required_name(api):
    """PRD §2.10: "Fourth, shape: required fields present, types correct, enum
    values within their declared sets, and integer ranges respected
    (`household_size` at least 1, session `capacity` at least 1, monetary
    amounts strictly positive), otherwise `ERR_VALIDATION`; this is also where
    a duplicate `npi_number` or a duplicate `period_index` within a program is
    rejected."

    Design: Corner/entities/c_create_program_missing_required_name
    """
    payload = create_program_payload()
    del payload["name"]
    res = api.create_program(payload, ADMIN)
    validate_error(res, "ERR_VALIDATION")


def test_create_retailer_invalid_kind_rejected(api):
    """PRD §3.1: "A retailer is registered with its `name`, its `kind` — one of
    GROCERY, FARMERS_MARKET, or MOBILE_MARKET — and a `double_up_eligible` flag
    governing whether the produce match applies at its tills."
    PRD §2.10: "Fourth, shape: required fields present, types correct, enum
    values within their declared sets, and integer ranges respected
    (`household_size` at least 1, session `capacity` at least 1, monetary
    amounts strictly positive), otherwise `ERR_VALIDATION`; this is also where
    a duplicate `npi_number` or a duplicate `period_index` within a program is
    rejected."

    Design: Corner/entities/c_create_retailer_invalid_enum_rejected
    """
    res = api.create_retailer(
        create_retailer_payload(name="R1", kind="BAKERY", double_up_eligible=True),
        ADMIN,
    )
    validate_error(res, "ERR_VALIDATION")


def test_pool_computed_fields_input_ignored(api):
    """PRD §3.1: "A funding pool is created in PENDING status against a
    `program_id` and a `funder_id` with a `committed_cents` amount; its ledger
    starts clean, with `disbursed_cents` and `reserved_cents` at zero and
    `available_cents` equal to the commitment."

    Design: Corner/entities/c_pool_computed_fields_input_ignored
    """
    funder = create_funder()
    program = create_program()
    payload = create_funding_pool_payload(program["id"], funder["id"],
                                          committed_cents=500000)
    payload["disbursed_cents"] = 999
    res = api.create_funding_pool(payload, ADMIN)
    pool = validate_success(res, 201)
    assert_funding_pool(pool)
    assert pool["disbursed_cents"] == 0, "client-supplied disbursed_cents must be ignored"
    assert pool["reserved_cents"] == 0
    assert pool["available_cents"] == 500000
    assert pool["status"] == "PENDING"


def test_funder_commitment_cap_exceeded_rejected(api):
    """PRD §2.8: "A funder's total exposure is capped: the sum of
    `committed_cents` across all of a funder's pools must never exceed that
    funder's `total_commitment_cents`, and a pool creation that would breach
    the cap is rejected with `ERR_COMMITMENT_EXCEEDED` (HTTP 422)."

    Design: Corner/errors/c_commitment_exceeded_rejected
    """
    funder = create_funder(total_commitment_cents=100000)
    program = create_program()
    pool1 = validate_success(api.create_funding_pool(
        create_funding_pool_payload(program["id"], funder["id"],
                                    committed_cents=60000), ADMIN), 201)
    assert pool1["status"] == "PENDING"

    res = api.create_funding_pool(
        create_funding_pool_payload(program["id"], funder["id"],
                                    committed_cents=50000), ADMIN)
    validate_error(res, "ERR_COMMITMENT_EXCEEDED")

    pool1_after = get_pool(pool1["id"])
    assert pool1_after["status"] == "PENDING"
    assert pool1_after["committed_cents"] == 60000
