"""Case intake and financial-eligibility screening.

Covers Corner queue (entities, state_machines, calculations, validations) and
Difficulty queue instances for the eligibility fork, income boundary, and
per-component contribution rounding.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId, TEST_USERS, NON_EXISTENT_UUID,
    assert_case, assert_courtroom, assert_attorney,
    create_office_payload, create_case_payload, create_attorney_payload,
    create_screening_payload,
)
from test_helpers import fixtures as fx

CLERK = TEST_USERS["intake_clerk_headers"]
OFFICER = TEST_USERS["screening_officer_headers"]
SUPER = TEST_USERS["supervising_attorney_headers"]


# ===========================================================================
# Corner: entities
# ===========================================================================

def test_create_case_returns_201_with_system_fields(api):
    """PRD 3.1: "A freshly referred case opens in `status` `REFERRED` with
    `eligibility_status` `PENDING`, `case_weight` 0, `weight_basis`
    `PROVISIONAL`, `complexity_tier` `STANDARD`, and `co_defendant_count` 0;
    its `disposition_type` and `disposition_date` are null and its
    `assigned_attorney_id` is null."
    PRD 2.4: "Most resources also carry an integer `version` that begins at 1
    when the resource is created and increments by one on every mutation that
    changes the resource, alongside a refresh of `updated_at`."

    Design: Corner/entities/create_case_returns_201_with_system_fields
    """
    office = fx.create_office()
    resp = api.create_case(create_case_payload(office["id"], defendant_name="New",
                                               charge_class="FELONY_B"), CLERK)
    data = validate_success(resp, 201)
    assert_case(data)
    assert data["status"] == "REFERRED"
    assert data["eligibility_status"] == "PENDING"
    assert data["case_weight"] == 0
    assert data["version"] == 1


def test_get_case_not_found_returns_404(api):
    """PRD 2.6: "path identifiers and every foreign key present in the body are
    checked for existence left to right, and the first one that does not resolve
    produces the matching not-found error — `ERR_OFFICE_NOT_FOUND`,
    `ERR_ATTORNEY_NOT_FOUND`, `ERR_COURTROOM_NOT_FOUND`, `ERR_CASE_NOT_FOUND`"

    Design: Corner/entities/get_case_not_found_returns_404
    """
    resp = api.get_case(NON_EXISTENT_UUID, CLERK)
    validate_error(resp, ApiErrorId.ERR_CASE_NOT_FOUND.value)


def test_list_cases_by_office_paginated(api):
    """PRD 2.3: "Each list response reports `limit`, `offset`, `total_count`
    (the count of records matching the filter before pagination), and `has_more`
    (true when records remain beyond the current page) inside `meta`."
    PRD 3.1: "Cases can be retrieved individually or listed, and the list may be
    filtered by `office_id` and by `status`."

    Design: Corner/entities/list_cases_by_office_paginated
    """
    office = fx.create_office()
    fx.create_case(office["id"], defendant_name="L1")
    fx.create_case(office["id"], defendant_name="L2")
    resp = api.list_cases(CLERK, params={"office_id": office["id"], "limit": 1, "offset": 0})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 2
    assert meta["has_more"] is True
    assert len(data) == 1


def test_create_case_missing_charge_class_returns_invalid_request(api):
    """PRD 2.6: "Only after all referenced resources exist does the server
    validate that the request body is well-formed — required fields present,
    enum values legal, and numeric constraints satisfied — rejecting violations
    with `ERR_VALIDATION`."

    Design: Corner/entities/create_case_missing_charge_class_returns_invalid_request
    """
    office = fx.create_office()
    resp = api.create_case({"office_id": office["id"], "defendant_name": "NoClass"}, CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_office_recoupment_basis_default_applied(api):
    """PRD 3.8: "An office declares its `recoupment_basis` (`SCHEDULE` or
    `ACTUAL`, defaulting to `SCHEDULE`) at creation"

    Design: Corner/entities/office_recoupment_basis_default_applied
    """
    resp = api.create_defender_office(
        {"name": "PD-Def", "annual_voucher_budget_cents": 100_000_000}, SUPER)
    data = validate_success(resp, 201)
    assert data["recoupment_basis"] == "SCHEDULE"


def test_attorney_computed_defaults_on_create(api):
    """PRD 3.3: "A new attorney opens with `current_weighted_load` 0 and
    `status` `ACTIVE`."

    Design: Corner/entities/attorney_computed_defaults_on_create
    """
    office = fx.create_office()
    resp = api.create_attorney(create_attorney_payload(office["id"], name="Zed",
                                                       bar_number="Z1",
                                                       max_weighted_caseload=8.0), SUPER)
    data = validate_success(resp, 201)
    assert_attorney(data)
    assert data["current_weighted_load"] == 0
    assert data["status"] == "ACTIVE"


def test_courtroom_immutable_has_no_version(api):
    """PRD 2.4: "Two resources are configuration or audit artifacts that are
    never mutated after creation and therefore carry only `id` and `created_at`
    — they have neither an `updated_at` nor a `version` field."

    Design: Corner/entities/courtroom_immutable_has_no_version
    """
    resp = api.create_courtroom({"name": "Dept 4", "courthouse": "Main"}, SUPER)
    data = validate_success(resp, 201)
    assert_courtroom(data)
    assert "version" not in data
    assert "updated_at" not in data


def test_create_attorney_unknown_office_returns_not_found(api):
    """PRD 2.6: "path identifiers and every foreign key present in the body are
    checked for existence left to right, and the first one that does not resolve
    produces the matching not-found error — `ERR_OFFICE_NOT_FOUND`,
    `ERR_ATTORNEY_NOT_FOUND`, `ERR_COURTROOM_NOT_FOUND`, `ERR_CASE_NOT_FOUND`"

    Design: Corner/entities/create_attorney_unknown_office_returns_not_found
    """
    resp = api.create_attorney(create_attorney_payload(NON_EXISTENT_UUID, name="Nul",
                                                       attorney_type="PANEL",
                                                       bar_number="N1",
                                                       max_weighted_caseload=5.0), SUPER)
    validate_error(resp, ApiErrorId.ERR_OFFICE_NOT_FOUND.value)


def test_create_case_invalid_charge_class_enum_rejected(api):
    """PRD 2.6: "Only after all referenced resources exist does the server
    validate that the request body is well-formed — required fields present,
    enum values legal, and numeric constraints satisfied — rejecting violations
    with `ERR_VALIDATION`."

    Design: Corner/entities/create_case_invalid_charge_class_enum_rejected
    """
    office = fx.create_office()
    resp = api.create_case(create_case_payload(office["id"], defendant_name="Bad",
                                               charge_class="TRAFFIC"), CLERK)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


# ===========================================================================
# Corner: state_machines / validations for screening
# ===========================================================================

def test_decide_screening_twice_returns_already_decided(api):
    """PRD 3.2: "Deciding is permitted only while the screening is `SUBMITTED`;
    deciding one that is already `DECIDED` is rejected with
    `ERR_SCREENING_ALREADY_DECIDED`."

    Design: Corner/state_machines/decide_screening_twice_returns_already_decided
    """
    office = fx.create_office()
    case = fx.create_case(office["id"])
    scr = fx.submit_screening(case["id"])
    validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    resp = api.decide_screening(scr["id"], OFFICER)
    validate_error(resp, ApiErrorId.ERR_SCREENING_ALREADY_DECIDED.value)


def test_duplicate_financial_screening_rejected(api):
    """PRD 3.2: "Exactly one screening may exist per case; a second submission
    for the same case is rejected with `ERR_SCREENING_ALREADY_EXISTS`."

    Design: Corner/validations/duplicate_financial_screening_rejected
    """
    office = fx.create_office()
    case = fx.create_case(office["id"])
    validate_success(api.create_financial_screening(create_screening_payload(case["id"]), CLERK), 201)
    resp = api.create_financial_screening(
        create_screening_payload(case["id"], household_income_cents=900_000), CLERK)
    validate_error(resp, ApiErrorId.ERR_SCREENING_ALREADY_EXISTS.value)


# ===========================================================================
# Difficulty: eligibility fork (SCREENED vs DENIED)
# ===========================================================================

def test_eligibility_eligible_advances_case_to_screened(api):
    """PRD 3.2: "When the result is `ELIGIBLE` or `PARTIAL`, the case advances
    from `REFERRED` to `SCREENED`, opening the path to counsel."
    PRD 3.2: "Deciding always sets the screening's `status` to `DECIDED`,
    records the deciding user's identifier into `decided_by_user_id`, and copies
    the computed `result` onto the parent case's `eligibility_status`."

    Design: Difficulty/non_linear_state_machine/case_eligibility_branch_screened_vs_denied
    """
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Eli")
    scr = fx.submit_screening(case["id"], household_income_cents=800_000,
                              household_size=2, asset_value_cents=0)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["result"] == "ELIGIBLE"
    got = validate_success(api.get_case(case["id"], CLERK), 200)
    assert got["status"] == "SCREENED"
    assert got["eligibility_status"] == "ELIGIBLE"


def test_eligibility_ineligible_forks_case_to_denied(api):
    """PRD 3.2: "If the countable `asset_value_cents` is strictly greater than
    the asset cap of $20,000 (2,000,000 cents), the result is `INELIGIBLE`
    regardless of income."
    PRD 3.2: "When the result is `INELIGIBLE`, the case moves to the terminal
    `DENIED` state, no counsel path opens, and no contribution is set."

    Design: Difficulty/non_linear_state_machine/case_eligibility_branch_screened_vs_denied
    """
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Ivy")
    scr = fx.submit_screening(case["id"], household_income_cents=800_000,
                              household_size=2, asset_value_cents=5_000_000)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["result"] == "INELIGIBLE"
    got = validate_success(api.get_case(case["id"], CLERK), 200)
    assert got["status"] == "DENIED"
    assert got["eligibility_status"] == "INELIGIBLE"


# ===========================================================================
# Difficulty: income eligibility threshold (inclusive boundary)
# ===========================================================================

def test_income_at_eligible_threshold_resolves_eligible(api):
    """PRD 3.2: "Both income comparisons are inclusive at their upper bound, so
    income exactly at 1.25 times the poverty line resolves to `ELIGIBLE`, and
    one cent above resolves to `PARTIAL`."

    Design: Difficulty/boundary_precision_check/income_eligibility_threshold_inclusive
    """
    # household_size 2 -> fpl = 2,000,000; fpl * 1.25 = 2,500,000.
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Ed")
    scr = fx.submit_screening(case["id"], household_income_cents=2_500_000,
                              household_size=2, asset_value_cents=0)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["result"] == "ELIGIBLE"
    assert decided["contribution_amount_cents"] == 0


def test_income_one_cent_above_threshold_resolves_partial(api):
    """PRD 3.2: "Both income comparisons are inclusive at their upper bound, so
    income exactly at 1.25 times the poverty line resolves to `ELIGIBLE`, and
    one cent above resolves to `PARTIAL`."

    Design: Difficulty/boundary_precision_check/income_eligibility_threshold_inclusive
    """
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Pi")
    scr = fx.submit_screening(case["id"], household_income_cents=2_500_001,
                              household_size=2, asset_value_cents=0)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["result"] == "PARTIAL"


# ===========================================================================
# Difficulty: per-component contribution rounding
# ===========================================================================

def test_partial_contribution_uses_per_component_rounding(api):
    """PRD 3.2: "Multiply the income excess by ten percent and round that
    product half up to whole cents to obtain the income component. Separately
    multiply the asset excess by five percent and round that product half up to
    whole cents to obtain the asset component. The contribution is the sum of
    the two already-rounded components — each component is rounded first, and
    only then are they added, because rounding each and then summing can differ
    from summing and then rounding by up to one cent."

    Design: Difficulty/combinatorial_formula/financial_contribution_per_component_rounding
    """
    # size 2 -> fpl 2,000,000; ceiling 2,500,000.
    # income_excess 833,333 -> *0.10 = 83,333.3 -> 83,333.
    # asset_excess 500,007 -> *0.05 = 25,000.35 -> 25,000. sum = 108,333 (not 108,334).
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Fin")
    scr = fx.submit_screening(case["id"], household_income_cents=3_333_333,
                              household_size=2, asset_value_cents=1_000_007)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["contribution_amount_cents"] == 108_333


def test_partial_contribution_sets_result_partial_and_case_screened(api):
    """PRD 3.2: "When and only when the result is `PARTIAL`, the server also
    computes the defendant's `contribution_amount_cents`, and the per-component
    rounding order here is deliberate."
    PRD 3.2: "When the result is `ELIGIBLE` or `PARTIAL`, the case advances from
    `REFERRED` to `SCREENED`, opening the path to counsel."

    Design: Difficulty/combinatorial_formula/financial_contribution_per_component_rounding
    """
    office = fx.create_office()
    case = fx.create_case(office["id"], defendant_name="Fin2")
    scr = fx.submit_screening(case["id"], household_income_cents=3_333_333,
                              household_size=2, asset_value_cents=1_000_007)
    decided = validate_success(api.decide_screening(scr["id"], OFFICER), 200)
    assert decided["result"] == "PARTIAL"
    got = validate_success(api.get_case(case["id"], CLERK), 200)
    assert got["status"] == "SCREENED"
