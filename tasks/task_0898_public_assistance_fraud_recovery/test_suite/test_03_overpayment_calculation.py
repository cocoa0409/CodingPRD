"""Overpayment claim construction: months, dual-variant calculation, and input guards."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    create_open_case,
    add_draft_overpayment,
    setup_calculated_overpayment,
    create_month_payload,
    create_overpayment_payload,
    assert_overpayment,
)

INVESTIGATOR = TEST_USERS["investigator_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]


# --------------------------------------------------------------------------- #
# Dual-variant calculation: provisional (reported) vs final (verified)
# --------------------------------------------------------------------------- #
def test_calculate_produces_distinct_provisional_and_final(api):
    """PRD 3.3: "The provisional figure, `provisional_amount_cents`, is the sum across
    all of the claim's months of each month's `over_issuance_reported_cents` — the
    reported-income variant, which excludes adjustments."
    PRD 3.3: "The final figure, `final_amount_cents`, is the sum across all months of
    each month's `over_issuance_verified_cents` plus the running `total_adjustments_cents`
    — the verified-income variant."

    Design: Difficulty/dual_variant_calc/overpayment_provisional_vs_final
    """
    ctx = setup_calculated_overpayment(api, claim_type="IHE")
    op = ctx["overpayment"]
    assert_overpayment(op)
    assert op["provisional_amount_cents"] == 35050, (
        f"expected provisional 35050, got {op['provisional_amount_cents']}"
    )
    assert op["final_amount_cents"] == 45050, (
        f"expected final 45050, got {op['final_amount_cents']}"
    )
    assert op["status"] == "CALCULATED", f"expected CALCULATED, got {op['status']}"


def test_calculate_single_month_variants_diverge(api):
    """PRD 3.3: "The provisional figure, `provisional_amount_cents`, is the sum across
    all of the claim's months of each month's `over_issuance_reported_cents` — the
    reported-income variant, which excludes adjustments."
    PRD 3.3: "The final figure, `final_amount_cents`, is the sum across all months of
    each month's `over_issuance_verified_cents` plus the running `total_adjustments_cents`
    — the verified-income variant."

    Design: Difficulty/dual_variant_calc/overpayment_provisional_vs_final
    """
    months = [{
        "benefit_month": "2025-06",
        "benefits_issued_cents": 30000,
        "benefits_entitled_reported_cents": 20000,   # over_reported = 10000
        "benefits_entitled_verified_cents": 17500,   # over_verified = 12500
    }]
    ctx = setup_calculated_overpayment(api, claim_type="IHE", months=months)
    op = ctx["overpayment"]
    assert op["provisional_amount_cents"] == 10000, (
        f"expected provisional 10000, got {op['provisional_amount_cents']}"
    )
    assert op["final_amount_cents"] == 12500, (
        f"expected final 12500, got {op['final_amount_cents']}"
    )


# --------------------------------------------------------------------------- #
# Calculate boundary: >= 1 month required
# --------------------------------------------------------------------------- #
def test_calculate_with_zero_months_rejected(api):
    """PRD 3.3: "Calculating the claim advances it from `DRAFT` to `CALCULATED` and
    requires at least one month line item; a calculate attempt with zero months is
    rejected with `ERR_NO_OVERPAYMENT_MONTHS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/calculate_empty_months_boundary
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="IHE")
    op_id = ctx["overpayment"]["id"]
    resp = api.calculate_overpayment(op_id, INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_NO_OVERPAYMENT_MONTHS.value)
    after = validate_success(api.get_overpayment(op_id, SUPERVISOR))
    assert after["status"] == "DRAFT", f"expected claim to stay DRAFT, got {after['status']}"


def test_calculate_with_one_month_succeeds(api):
    """PRD 3.3: "Calculating the claim advances it from `DRAFT` to `CALCULATED` and
    requires at least one month line item; a calculate attempt with zero months is
    rejected with `ERR_NO_OVERPAYMENT_MONTHS` (HTTP 422)."

    Design: Difficulty/boundary_precision_check/calculate_empty_months_boundary
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="IHE", months=[create_month_payload()])
    op_id = ctx["overpayment"]["id"]
    resp = api.calculate_overpayment(op_id, INVESTIGATOR)
    data = validate_success(resp)
    assert data["status"] == "CALCULATED", f"expected CALCULATED, got {data['status']}"


# --------------------------------------------------------------------------- #
# Duplicate benefit_month collision
# --------------------------------------------------------------------------- #
def test_duplicate_benefit_month_rejected(api):
    """PRD 3.3: "A given `benefit_month` may appear only once per claim; a duplicate is
    rejected with `ERR_DUPLICATE_MONTH` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_benefit_month_point_collision
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="IHE",
                          months=[create_month_payload(benefit_month="2025-01")])
    op_id = ctx["overpayment"]["id"]
    resp = api.create_month(
        op_id,
        create_month_payload(benefit_month="2025-01", benefits_issued_cents=10000,
                             benefits_entitled_reported_cents=5000,
                             benefits_entitled_verified_cents=5000),
        INVESTIGATOR,
    )
    validate_error(resp, ApiErrorId.ERR_DUPLICATE_MONTH.value)


def test_distinct_benefit_month_accepted(api):
    """PRD 3.3: "A given `benefit_month` may appear only once per claim; a duplicate is
    rejected with `ERR_DUPLICATE_MONTH` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/duplicate_benefit_month_point_collision
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="IHE",
                          months=[create_month_payload(benefit_month="2025-01")])
    op_id = ctx["overpayment"]["id"]
    resp = api.create_month(op_id, create_month_payload(benefit_month="2025-02"), INVESTIGATOR)
    validate_success(resp, expected_status=201)


# --------------------------------------------------------------------------- #
# Input guards on month / overpayment creation
# --------------------------------------------------------------------------- #
def test_invalid_month_format_rejected(api):
    """PRD 2.6: "A value that does not match the expected pattern is rejected with
    `ERR_INVALID_MONTH_FORMAT` (HTTP 422); this format check applies to the creation of
    overpayment month line items, recovery plans, recovery transactions, and hearings."

    Design: Corner/validations/invalid_month_format
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="IHE")
    op_id = ctx["overpayment"]["id"]
    resp = api.create_month(op_id, create_month_payload(benefit_month="2025/01"), INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_MONTH_FORMAT.value)


def test_invalid_claim_type_enum_rejected(api):
    """PRD 2.9: "followed by enum-membership checks (`ERR_INVALID_ENUM`, HTTP 422)."
    PRD 3.3: "An `Investigator` opens an **Overpayment** claim against a case by
    supplying `case_id` and a `claim_type` of `IPV` (intentional program violation),
    `IHE` (inadvertent household error), or `AE` (agency error)."

    Design: Corner/validations/invalid_enum_claim_type
    """
    ctx = create_open_case(api)
    resp = api.create_overpayment(
        create_overpayment_payload(ctx["case"]["id"], claim_type="BOGUS"), INVESTIGATOR
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_ENUM.value)


def test_missing_claim_type_rejected(api):
    """PRD 2.9: "Next comes body well-formedness — required fields present and correctly
    typed (`ERR_VALIDATION`, HTTP 400)."
    PRD 3.3: "An `Investigator` opens an **Overpayment** claim against a case by
    supplying `case_id` and a `claim_type` of `IPV` (intentional program violation),
    `IHE` (inadvertent household error), or `AE` (agency error)."

    Design: Corner/validations/missing_required_field_on_overpayment
    """
    ctx = create_open_case(api)
    resp = api.create_overpayment({"case_id": ctx["case"]["id"]}, INVESTIGATOR)
    validate_error(resp, ApiErrorId.ERR_VALIDATION.value)


def test_get_missing_overpayment_returns_not_found(api):
    """PRD 2.4: "the first identifier that does not resolve to an existing resource
    yields `ERR_NOT_FOUND` (HTTP 404) before any later reference or business rule is
    evaluated."

    Design: Corner/validations/not_found_overpayment
    """
    resp = api.get_overpayment(NON_EXISTENT_UUID, SUPERVISOR)
    validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)


def test_list_overpayments_filtered_by_case_id(api):
    """PRD 3.3: "Overpayments can be listed and filtered by `case_id`, `status`, and
    `claim_type`."

    Design: Corner/entities/list_overpayments_by_case_id
    """
    ctx = create_open_case(api)
    add_draft_overpayment(api, ctx, claim_type="AE")
    op_id = ctx["overpayment"]["id"]
    resp = api.list_overpayments(SUPERVISOR, params={"case_id": ctx["case"]["id"]})
    data, meta = validate_paginated(resp)
    assert meta["total_count"] == 1, f"expected total_count 1, got {meta['total_count']}"
    assert len(data) == 1 and data[0]["id"] == op_id, "expected exactly the created overpayment"
