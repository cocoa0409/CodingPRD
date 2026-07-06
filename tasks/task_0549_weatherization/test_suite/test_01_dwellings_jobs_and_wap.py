"""Dwelling / Job creation, referential integrity, listing, and WAP eligibility.

Every test translates exactly one design-index instance (queue A difficulty or
queue B corner); the final docstring line records which one.
"""
import pytest
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    create_dwelling_payload,
    create_job_payload,
    create_wap_application_payload,
    create_diagnostic_test_payload,
    assert_job,
    new_dwelling,
    new_job,
    new_audit,
    new_scope,
)

NONEXISTENT = "00000000-0000-4000-8000-000000000000"


def test_create_job_returns_201_with_initial_fields(api, program_admin_headers):
    """PRD 3.2: "A newly created job starts with `job_status` = `ACTIVE`,
    `install_status` = `PLANNED`, and `verification_status` = `PENDING`, its
    `version` at 1, and all of its computed money and savings fields initialized
    (`total_estimated_cost_cents`, `approved_rebate_total_cents`,
    `tax_credit_cents`, and `estimated_out_of_pocket_cents` at 0,
    `estimated_annual_savings_kwh` at 0, and `verified_annual_savings_kwh` left
    null until verification)."

    Design: Corner/entities/create_job_returns_201_with_initial_fields
    """
    dwelling = new_dwelling()
    res = api.create_job(
        create_job_payload(dwelling["id"], program_track="UTILITY", rebate_budget_cap_cents=100_000),
        program_admin_headers,
    )
    job = validate_success(res, 201)
    assert_job(job)
    assert job["job_status"] == "ACTIVE"
    assert job["install_status"] == "PLANNED"
    assert job["verification_status"] == "PENDING"
    assert job["version"] == 1
    assert job["approved_rebate_total_cents"] == 0


def test_create_job_missing_program_track_rejected(api, program_admin_headers):
    """PRD 2.5: "**Body well-formedness** — required fields must be present,
    enums must hold legal values, numeric fields must be within their declared
    ranges, and pagination parameters must be in range; otherwise
    `ERR_VALIDATION` (400)."

    Design: Corner/entities/create_job_missing_required_program_track_returns_validation
    """
    dwelling = new_dwelling()
    payload = {"dwelling_id": dwelling["id"], "rebate_budget_cap_cents": 100_000}
    res = api.create_job(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_create_dwelling_invalid_foundation_enum_rejected(api, program_admin_headers):
    """PRD 3.1: "The `foundation_type` is one of `SLAB`, `CRAWLSPACE`, or
    `BASEMENT`; the `heating_fuel_type` is one of `GAS`, `ELECTRIC`, `OIL`, or
    `PROPANE`. Any other value for either enum is a malformed body
    (`ERR_VALIDATION`)."

    Design: Corner/entities/create_dwelling_invalid_enum_foundation_returns_validation
    """
    res = api.create_dwelling(create_dwelling_payload(foundation_type="PIER"), program_admin_headers)
    validate_error(res, ApiErrorId.ERR_VALIDATION)


def test_get_nonexistent_job_returns_not_found(api, program_admin_headers):
    """PRD 2.6: "When a path carries an identifier that does not resolve, the
    request fails with `ERR_NOT_FOUND` (404) before any state or business rule
    is considered".

    Design: Corner/entities/get_job_nonexistent_returns_not_found
    """
    res = api.get_job(NONEXISTENT, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_create_job_unknown_dwelling_fk_returns_not_found(api, program_admin_headers):
    """PRD 2.5: "**Foreign-key existence** — every foreign key carried in the
    request body (for example `dwelling_id`, `job_id`, `crew_id`, `audit_id`,
    `scope_item_id`, `baseline_test_id`, or `post_test_id`) must resolve to an
    existing resource, or `ERR_NOT_FOUND` (404)."

    Design: Corner/entities/create_job_unknown_dwelling_fk_returns_not_found
    """
    payload = create_job_payload("11111111-1111-4111-8111-111111111111")
    res = api.create_job(payload, program_admin_headers)
    validate_error(res, ApiErrorId.ERR_NOT_FOUND)


def test_diagnostic_test_is_append_only_id_and_created_at(api, program_admin_headers, auditor_headers):
    """PRD 2.4: "a diagnostic test is an immutable, append-only measurement
    event. It carries only `id` and `created_at`; it has no `updated_at` and no
    `version` field, because it is never modified after creation."

    Design: Corner/entities/diagnostic_test_is_immutable_id_only
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"])
    res = api.create_diagnostic_test(
        create_diagnostic_test_payload(job["id"], kind="BLOWER_DOOR", stage="BASELINE", cfm_measured=3000),
        auditor_headers,
    )
    test = validate_success(res, 201)
    assert isinstance(test["id"], str) and len(test["id"]) > 0
    assert test["cfm_measured"] == 3000
    assert "version" not in test, "append-only diagnostic test must not expose version"
    assert "updated_at" not in test, "append-only diagnostic test must not expose updated_at"


def test_list_jobs_by_dwelling_pagination_envelope(api, program_admin_headers):
    """PRD 2.3: "Each list response includes `limit`, `offset`, `total_count`,
    and `has_more` in the envelope's `meta` object, where `total_count` reflects
    the number of matching resources before pagination and `has_more` indicates
    whether further pages remain."

    Design: Corner/entities/list_jobs_pagination_envelope
    """
    dwelling = new_dwelling()
    new_job(dwelling["id"])
    new_job(dwelling["id"])
    data, meta = validate_paginated(
        api.list_jobs(program_admin_headers, params={"dwelling_id": dwelling["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert meta["has_more"] is False


def test_list_scope_items_by_job_reverse_lookup(api, program_admin_headers):
    """PRD 3.4: "Scope items may be listed with optional filters on `job_id`,
    `audit_id`, `status`, and `category`."

    Design: Corner/entities/fk_reverse_lookup_scope_items_by_job
    """
    dwelling = new_dwelling()
    job = new_job(dwelling["id"])
    audit = new_audit(job["id"])
    scope = new_scope(
        job["id"], audit["id"], category="DUCT_SEALING", area_sqft=500, target_r_value=0,
        estimated_cost_cents=40_000, estimated_savings_kwh=200,
    )
    data, meta = validate_paginated(api.list_scope_items(program_admin_headers, params={"job_id": job["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == scope["id"]


def test_wap_income_at_exact_limit_is_eligible(api, homeowner_headers):
    """PRD 3.1: "The application's `status` is then set to `ELIGIBLE` when
    `annual_gross_income_cents` is less than or equal to `income_limit_cents`,
    and to `INELIGIBLE` otherwise; the boundary is inclusive, so an income
    exactly equal to the limit is `ELIGIBLE`."

    Design: Difficulty/boundary_precision_check/wap_income_at_exact_limit_eligible
    """
    dwelling = new_dwelling()
    res = api.create_wap_application(
        create_wap_application_payload(dwelling["id"], household_size=3, annual_gross_income_cents=5_000_000),
        homeowner_headers,
    )
    wap = validate_success(res, 201)
    assert wap["status"] == "ELIGIBLE"


def test_wap_income_limit_computed_for_household(api, homeowner_headers):
    """PRD 3.1: "Concretely, `income_limit_cents` equals 2 × (1,500,000 +
    (`household_size` − 1) × 500,000)."

    Design: Difficulty/boundary_precision_check/wap_income_at_exact_limit_eligible
    """
    dwelling = new_dwelling()
    res = api.create_wap_application(
        create_wap_application_payload(dwelling["id"], household_size=3, annual_gross_income_cents=5_000_000),
        homeowner_headers,
    )
    wap = validate_success(res, 201)
    assert wap["income_limit_cents"] == 5_000_000


def test_wap_income_above_limit_is_ineligible(api, homeowner_headers):
    """PRD 3.1: "The application's `status` is then set to `ELIGIBLE` when
    `annual_gross_income_cents` is less than or equal to `income_limit_cents`,
    and to `INELIGIBLE` otherwise; the boundary is inclusive, so an income
    exactly equal to the limit is `ELIGIBLE`."

    Design: Corner/calculations/wap_income_above_limit_is_ineligible
    """
    dwelling = new_dwelling()
    res = api.create_wap_application(
        create_wap_application_payload(dwelling["id"], household_size=3, annual_gross_income_cents=5_000_001),
        homeowner_headers,
    )
    wap = validate_success(res, 201)
    assert wap["income_limit_cents"] == 5_000_000
    assert wap["status"] == "INELIGIBLE"
