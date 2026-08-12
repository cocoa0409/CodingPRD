"""Program defaults, household required fields, not-found, pagination envelope."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_household_payload,
    create_program_payload,
    get_success_data,
    setup_program,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pa():
    return TEST_USERS["platform_admin_headers"]


def _is():
    return TEST_USERS["intake_specialist_headers"]


def _lm():
    return TEST_USERS["lease_manager_headers"]


def test_create_program_with_defaults_applied():
    """PRD §3.1: "`ground_lease_term_years` defaults to 99.
    `low_income_fee_reduction_pct` defaults to `0.5` ...
    `indexed_annual_appreciation_pct` defaults to `0.015` ...
    `appraisal_seller_share_pct` defaults to `0.25` ...
    `max_refi_ltv_pct` defaults to `0.95` ... `max_equity_withdrawal_cents`
    defaults to `0` ... `default_cure_window_days` defaults to 30.
    `inspection_cycle_months` defaults to 24."
    PRD §3.1: "A newly created program lands in `ACTIVE` status."

    Design: Corner/entities/create_program_with_defaults_applied
    """
    prog = get_success_data(
        api_client.create_program(
            {
                "name": "P-def",
                "ami_table_effective_date": "2026-05-01T00:00:00Z",
                "area_median_income_cents": 10_000_000,
                "max_eligibility_ami_pct": 0.80,
                "ground_lease_base_fee_cents": 50_000,
                "resale_formula_kind": "INDEXED",
            },
            _pa(),
        )
    )
    assert prog["status"] == "ACTIVE"
    assert prog["ground_lease_term_years"] == 99
    assert prog["low_income_fee_reduction_pct"] == pytest.approx(0.5)
    assert prog["indexed_annual_appreciation_pct"] == pytest.approx(0.015)
    assert prog["appraisal_seller_share_pct"] == pytest.approx(0.25)
    assert prog["max_refi_ltv_pct"] == pytest.approx(0.95)
    assert prog["max_equity_withdrawal_cents"] == 0
    assert prog["default_cure_window_days"] == 30
    assert prog["inspection_cycle_months"] == 24
    assert prog["version"] == 1


def test_create_household_missing_required_field_returns_invalid_request():
    """PRD §3.2: "An `IntakeSpecialist` registers a new applicant household by
    supplying `legal_name`, `household_size`, `annual_gross_income_cents`,
    and optionally a free-form `notes` string."
    PRD §5: "`ERR_INVALID_REQUEST` | 400"

    Omitting required `household_size` must yield ERR_INVALID_REQUEST.

    Design: Corner/entities/create_household_missing_required_field_returns_invalid_request
    """
    prog = setup_program(name="P-req")
    resp = api_client.create_household(
        prog["id"],
        {"legal_name": "No Size", "annual_gross_income_cents": 5_000_000},
        _is(),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST.value)


def test_get_nonexistent_household_returns_not_found():
    """PRD §2.5: "Path parameters are validated strictly from left to right:
    each segment identifier must resolve to an existing resource that is a
    descendant of the resource identified by the segment before it, all
    within the same program scope. A mismatch at any level — for example, a
    `certId` that names a certification belonging to a different
    `householdId` — returns `ERR_NOT_FOUND`."

    Design: Corner/entities/get_nonexistent_household_returns_not_found
    """
    prog = setup_program(name="P-404")
    resp = api_client.get_household(prog["id"], NON_EXISTENT_UUID, _lm())
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_households_returns_pagination_envelope():
    """PRD §2.2: "Pagination-related fields in `meta` (`limit`, `offset`,
    `total_count`, `has_more`) are included for list endpoints."
    PRD §2.3: "List endpoints accept two query-string parameters, `limit`
    and `offset`. `limit` defaults to 10, has a minimum of 1, and a maximum
    of 100. `offset` defaults to 0 and has a minimum of 0."

    Design: Corner/entities/list_households_pagination_envelope
    """
    prog = setup_program(name="P-pg")
    for name, size, income in (("A", 1, 1_000_000), ("B", 2, 2_000_000), ("C", 3, 3_000_000)):
        get_success_data(
            api_client.create_household(
                prog["id"],
                create_household_payload(
                    legal_name=name,
                    household_size=size,
                    annual_gross_income_cents=income,
                ),
                _is(),
            )
        )
    resp = api_client.list_households(prog["id"], _lm())
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 3
    assert len(data) == 3
    assert meta["has_more"] is False
