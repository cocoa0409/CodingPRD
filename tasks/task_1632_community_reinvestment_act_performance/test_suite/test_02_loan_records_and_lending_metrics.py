"""Loan recording, derived flags, confirmation guards, the derived
confirmed_loan_count counter, and the lending-metrics / register-total reads."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_loan_record,
    create_active_area,
    create_area,
    create_confirmed_loan,
    create_loan,
    create_loan_record_payload,
    create_reported_loan,
    create_scheduled_exam,
    get_area,
    validate_error,
    validate_paginated,
    validate_success,
)


# ---------------------------------------------------------------------------
# Queue B — Corner/entities
# ---------------------------------------------------------------------------

def test_loan_record_computed_flags_and_reporting_year(api, compliance_analyst_headers):
    """PRD §3.3: "`reporting_year` is the four-digit calendar year of
    `action_date`. `small_revenue_flag` is true exactly when
    `borrower_gross_annual_revenue_cents` is at or below one million dollars of
    gross annual revenue, the threshold being inclusive. `lmi_geography_flag` is
    true exactly when `tract_income_level` is `LOW` or `MODERATE`.
    `inside_assessment_area` is live-derived at read time — it reflects whether
    the record's `census_tract` is currently an element of the referenced area's
    `census_tracts`".

    Design: Corner/entities/loan_record_computed_flags_and_reporting_year
    """
    area = create_active_area(
        area_code="AA-E4", msa_code="19100", state_code="TX", census_tracts=["T1", "T2"],
    )
    l1 = create_loan(
        area["id"], loan_type="SMALL_FARM", loan_amount_cents=9000000,
        borrower_gross_annual_revenue_cents=100000000, action_date="2024-07-04",
        census_tract="T1", tract_income_level="MODERATE",
    )
    assert_loan_record(l1)
    assert l1["small_revenue_flag"] is True
    assert l1["lmi_geography_flag"] is True
    assert l1["inside_assessment_area"] is True
    assert l1["reporting_year"] == 2024
    assert l1["status"] == "DRAFT"

    l2 = create_loan(
        area["id"], loan_type="SMALL_FARM", loan_amount_cents=9000000,
        borrower_gross_annual_revenue_cents=100000001, action_date="2024-07-05",
        census_tract="T2", tract_income_level="MIDDLE",
    )
    assert l2["small_revenue_flag"] is False
    assert l2["lmi_geography_flag"] is False


def test_loan_record_list_pagination_and_status_filter(api, compliance_analyst_headers):
    """PRD §2.3: "The `limit` parameter caps how many items a response returns;
    it defaults to 10 when omitted, accepts a minimum of 1, and is clamped at a
    maximum of 100. The `offset` parameter states how many items to skip and
    defaults to 0."
    PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
    and `has_more` in the `meta` object of the response envelope."
    PRD §3.3: "An area's loan list may be filtered by `status`,
    `reporting_year`, and `loan_type`."

    Design: Corner/entities/loan_record_list_pagination_and_status_filter
    """
    area = create_active_area(
        area_code="AA-E5", msa_code="16980", state_code="IL", census_tracts=["T1"],
    )
    for i, loan_type in enumerate(["SMALL_BUSINESS", "SMALL_BUSINESS", "SMALL_FARM"]):
        create_loan(
            area["id"], loan_type=loan_type, action_date=f"2025-01-{10 + i}",
        )

    page1, meta1 = validate_paginated(
        api.list_area_loan_records(
            area["id"], compliance_analyst_headers, params={"limit": 2, "offset": 0}
        )
    )
    assert len(page1) == 2
    assert meta1["total_count"] == 3
    assert meta1["has_more"] is True

    page2, meta2 = validate_paginated(
        api.list_area_loan_records(
            area["id"], compliance_analyst_headers, params={"limit": 2, "offset": 2}
        )
    )
    assert len(page2) == 1
    assert meta2["total_count"] == 3
    assert meta2["has_more"] is False

    filtered, meta3 = validate_paginated(
        api.list_area_loan_records(
            area["id"], compliance_analyst_headers, params={"status": "CONFIRMED"}
        )
    )
    assert filtered == []
    assert meta3["total_count"] == 0
    assert meta3["has_more"] is False


def test_loan_record_invalid_enum_returns_400(api, compliance_analyst_headers):
    """PRD §3.3: "a `loan_type` of `SMALL_BUSINESS` or `SMALL_FARM`".
    PRD §2.11: "at the same tier malformed bodies, missing required fields,
    invalid enum values, non-positive amounts, an `lmi_benefit_pct` outside the
    inclusive range 0 to 1, or an `lmi_population` exceeding `total_population`
    yield `ERR_VALIDATION`."

    Design: Corner/entities/loan_record_invalid_enum_returns_400
    """
    area = create_active_area(
        area_code="AA-E6", msa_code="16980", state_code="IL", census_tracts=["T1"],
    )
    payload = create_loan_record_payload(area["id"], loan_type="BIG_BUSINESS")
    resp = api.create_loan_record(payload, compliance_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


# ---------------------------------------------------------------------------
# Queue B — Corner/state_machines
# ---------------------------------------------------------------------------

def test_mark_reported_from_draft_returns_invalid_state(api, compliance_analyst_headers):
    """PRD §3.3: "Marking a `CONFIRMED` record as reported moves it to
    `REPORTED`".
    PRD §2.11: "State legality — a trigger that does not match the resource's
    current state, or any action on a terminal-state resource, yields
    `ERR_INVALID_STATE`."

    Design: Corner/state_machines/mark_reported_from_draft_returns_invalid_state
    """
    area = create_active_area(
        area_code="AA-SM3", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    loan = create_loan(area["id"], census_tract="T1")
    resp = api.mark_loan_reported(loan["id"], compliance_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
    current = validate_success(api.get_loan_record(loan["id"], compliance_analyst_headers))
    assert current["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B — Corner/validations
# ---------------------------------------------------------------------------

def test_confirm_loan_tract_not_in_area(api, compliance_analyst_headers):
    """PRD §3.3: "Confirmation moves a record from `DRAFT` to `CONFIRMED` and is
    guarded by two referential checks, evaluated in this order: the referenced
    area must be `ACTIVE` (else `ERR_AREA_NOT_ACTIVE`), and the record's
    `census_tract` must be an element of that area's `census_tracts` (else
    `ERR_TRACT_NOT_IN_AREA`)."

    Design: Corner/validations/confirm_loan_tract_not_in_area
    """
    area = create_active_area(
        area_code="AA-V3", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    loan = create_loan(area["id"], census_tract="T9", tract_income_level="LOW")
    resp = api.confirm_loan_record(loan["id"], compliance_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_TRACT_NOT_IN_AREA)
    current = validate_success(api.get_loan_record(loan["id"], compliance_analyst_headers))
    assert current["status"] == "DRAFT"


def test_confirm_loan_area_not_active(api, compliance_analyst_headers):
    """PRD §3.3: "Confirmation moves a record from `DRAFT` to `CONFIRMED` and is
    guarded by two referential checks, evaluated in this order: the referenced
    area must be `ACTIVE` (else `ERR_AREA_NOT_ACTIVE`), and the record's
    `census_tract` must be an element of that area's `census_tracts` (else
    `ERR_TRACT_NOT_IN_AREA`)."

    Design: Corner/validations/confirm_loan_area_not_active
    """
    area = create_area(
        area_code="AA-V4", msa_code="19100", state_code="TX", census_tracts=["T1"],
    )
    loan = create_loan(
        area["id"], loan_type="SMALL_FARM", census_tract="T1", tract_income_level="LOW",
    )
    resp = api.confirm_loan_record(loan["id"], compliance_analyst_headers)
    validate_error(resp, ApiErrorId.ERR_AREA_NOT_ACTIVE)
    current = validate_success(api.get_loan_record(loan["id"], compliance_analyst_headers))
    assert current["status"] == "DRAFT"


# ---------------------------------------------------------------------------
# Queue B — Corner/cross_cutting_complexity_layers
# ---------------------------------------------------------------------------

def test_confirmed_loan_count_reconciles_across_corrections(
    api, compliance_analyst_headers, cra_officer_headers,
):
    """PRD §3.3: "Confirming raises the area's `confirmed_loan_count` by one;
    the count covers loans in `CONFIRMED` and `REPORTED` alike. Returning a
    record from `CONFIRMED` to `DRAFT` lowers the count by one, and the
    correction loop `CONFIRMED → DRAFT → CONFIRMED` may repeat as often as
    needed. Marking a `CONFIRMED` record as reported moves it to `REPORTED` —
    the terminal state that places the loan on the CRA register — and leaves the
    count unchanged, since a reported loan still counts."

    Design: Corner/cross_cutting_complexity_layers/confirmed_loan_count_reconciles_across_corrections
    """
    area = create_active_area(
        area_code="AA-CC3", msa_code="19100", state_code="TX", census_tracts=["T1"],
    )
    loan = create_loan(area["id"], census_tract="T1")

    validate_success(api.confirm_loan_record(loan["id"], compliance_analyst_headers))
    assert get_area(area["id"])["confirmed_loan_count"] == 1

    validate_success(api.return_loan_to_draft(loan["id"], compliance_analyst_headers))
    assert get_area(area["id"])["confirmed_loan_count"] == 0

    validate_success(api.confirm_loan_record(loan["id"], compliance_analyst_headers))
    assert get_area(area["id"])["confirmed_loan_count"] == 1

    validate_success(api.mark_loan_reported(loan["id"], compliance_analyst_headers))
    assert get_area(area["id"])["confirmed_loan_count"] == 1


# ---------------------------------------------------------------------------
# Queue B — Corner/endpoints
# ---------------------------------------------------------------------------

def test_lending_metrics_computed_read_default_basis(api, compliance_analyst_headers):
    """PRD §3.9: "an optional `basis` selector chooses the population:
    `CURRENT`, the default and the examiner's working view, includes loans in
    `CONFIRMED` and `REPORTED`; `SNAPSHOT`, the as-reported register view used
    for the official submission, includes only `REPORTED`."
    PRD §3.9: "For each `REPORTED` loan in the window, grouped by `loan_type`:
    first cap the loan's `loan_amount_cents` at one million dollars; then round
    each capped amount half up to the nearest multiple of one thousand dollars;
    then sum the per-loan rounded amounts within each type."

    Design: Corner/endpoints/lending_metrics_computed_read_default_basis
    """
    area = create_active_area(
        area_code="AA-EP1", census_tracts=["T1"],
    )
    create_confirmed_loan(
        area["id"], loan_amount_cents=100000,
        borrower_gross_annual_revenue_cents=50000000, action_date="2024-04-01",
        census_tract="T1", tract_income_level="LOW",
    )
    exam = create_scheduled_exam("2024-01-01", "2024-12-31")

    data = validate_success(
        api.get_lending_metrics(exam["id"], compliance_analyst_headers)
    )
    assert data["loan_count"] == 1
    assert data["inside_aa_pct"] == pytest.approx(1.0, abs=1e-9)
    assert data["lmi_geography_pct"] == pytest.approx(1.0, abs=1e-9)
    assert data["small_business_register_total_cents"] == 0


# ---------------------------------------------------------------------------
# Queue B — Corner/calculations
# ---------------------------------------------------------------------------

def test_lending_metrics_empty_window_yields_zeros(api, bank_examiner_headers):
    """PRD §3.9: "The response reports `loan_count` plus three penetration
    ratios — `inside_aa_pct` counting loans whose `inside_assessment_area` is
    true, `lmi_geography_pct` counting `lmi_geography_flag`, and
    `lmi_borrower_pct` counting `small_revenue_flag` — each computed as its
    count divided by `loan_count`, rounded half up to four decimal places, and
    defined as 0 when `loan_count` is zero."

    Design: Corner/calculations/lending_metrics_empty_window_yields_zeros
    """
    exam = create_scheduled_exam(
        "2026-01-01", "2026-12-31", exam_type="INTERMEDIATE_SMALL_BANK"
    )
    data = validate_success(api.get_lending_metrics(exam["id"], bank_examiner_headers))
    assert data["loan_count"] == 0
    assert data["inside_aa_pct"] == 0
    assert data["lmi_geography_pct"] == 0
    assert data["lmi_borrower_pct"] == 0
    assert data["small_business_register_total_cents"] == 0
    assert data["small_farm_register_total_cents"] == 0


def test_register_total_applies_reportable_cap(api, bank_examiner_headers):
    """PRD §3.9: "For each `REPORTED` loan in the window, grouped by
    `loan_type`: first cap the loan's `loan_amount_cents` at one million
    dollars; then round each capped amount half up to the nearest multiple of
    one thousand dollars; then sum the per-loan rounded amounts within each
    type."

    Design: Corner/calculations/register_total_applies_reportable_cap
    """
    area = create_active_area(
        area_code="AA-C4", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    create_reported_loan(
        area["id"], loan_amount_cents=250000000,
        borrower_gross_annual_revenue_cents=300000000, action_date="2025-05-01",
        census_tract="T1", tract_income_level="UPPER",
    )
    exam = create_scheduled_exam("2025-01-01", "2025-12-31")

    data = validate_success(api.get_lending_metrics(exam["id"], bank_examiner_headers))
    assert data["small_business_register_total_cents"] == 100000000
    assert data["loan_count"] == 1
    assert data["lmi_borrower_pct"] == 0


# ---------------------------------------------------------------------------
# Queue A — Difficulty/dual_variant_calc/lending_metrics_snapshot_vs_current_basis
# ---------------------------------------------------------------------------

def test_lending_metrics_snapshot_vs_current_basis(api, bank_examiner_headers):
    """PRD §3.9: "an optional `basis` selector chooses the population:
    `CURRENT`, the default and the examiner's working view, includes loans in
    `CONFIRMED` and `REPORTED`; `SNAPSHOT`, the as-reported register view used
    for the official submission, includes only `REPORTED`. Whenever any
    in-window loan is `CONFIRMED` but not yet `REPORTED`, the two bases yield
    different denominators and different percentages."

    Design: Difficulty/dual_variant_calc/lending_metrics_snapshot_vs_current_basis
    """
    area = create_active_area(
        area_code="AA-DV2", msa_code="12060", state_code="GA", census_tracts=["T1", "T2"],
    )
    create_reported_loan(
        area["id"], loan_amount_cents=25000000,
        borrower_gross_annual_revenue_cents=50000000, action_date="2024-03-01",
        census_tract="T1", tract_income_level="MODERATE",
    )
    create_confirmed_loan(
        area["id"], loan_amount_cents=10000000,
        borrower_gross_annual_revenue_cents=200000000, action_date="2024-06-01",
        census_tract="T2", tract_income_level="UPPER",
    )
    exam = create_scheduled_exam("2024-01-01", "2024-12-31")

    snapshot = validate_success(
        api.get_lending_metrics(exam["id"], bank_examiner_headers,
                                params={"basis": "SNAPSHOT"})
    )
    assert snapshot["loan_count"] == 1
    assert snapshot["inside_aa_pct"] == pytest.approx(1.0, abs=1e-9)
    assert snapshot["lmi_geography_pct"] == pytest.approx(1.0, abs=1e-9)
    assert snapshot["lmi_borrower_pct"] == pytest.approx(1.0, abs=1e-9)

    current = validate_success(
        api.get_lending_metrics(exam["id"], bank_examiner_headers,
                                params={"basis": "CURRENT"})
    )
    assert current["loan_count"] == 2
    assert current["inside_aa_pct"] == pytest.approx(1.0, abs=1e-9)
    assert current["lmi_geography_pct"] == pytest.approx(0.5, abs=1e-9)
    assert current["lmi_borrower_pct"] == pytest.approx(0.5, abs=1e-9)

    # Register totals include REPORTED loans only under either basis.
    for data in (snapshot, current):
        assert data["small_business_register_total_cents"] == 25000000
        assert data["small_farm_register_total_cents"] == 0


def test_lending_metrics_bases_identical_when_nothing_unreported(api, bank_examiner_headers):
    """PRD §3.9: "Whenever any in-window loan is `CONFIRMED` but not yet
    `REPORTED`, the two bases yield different denominators and different
    percentages."

    Design: Difficulty/dual_variant_calc/lending_metrics_snapshot_vs_current_basis
    """
    area = create_active_area(
        area_code="AA-DV2B", msa_code="12060", state_code="GA", census_tracts=["T1"],
    )
    create_reported_loan(
        area["id"], loan_amount_cents=25000000,
        borrower_gross_annual_revenue_cents=50000000, action_date="2024-03-01",
        census_tract="T1", tract_income_level="MODERATE",
    )
    exam = create_scheduled_exam("2024-01-01", "2024-12-31")

    snapshot = validate_success(
        api.get_lending_metrics(exam["id"], bank_examiner_headers,
                                params={"basis": "SNAPSHOT"})
    )
    current = validate_success(
        api.get_lending_metrics(exam["id"], bank_examiner_headers,
                                params={"basis": "CURRENT"})
    )
    # With no CONFIRMED-but-unreported loan in the window, the inclusion sets
    # coincide, so every population figure matches across the two bases.
    assert snapshot["loan_count"] == current["loan_count"] == 1
    assert snapshot["inside_aa_pct"] == current["inside_aa_pct"]
    assert snapshot["lmi_geography_pct"] == current["lmi_geography_pct"]
    assert snapshot["lmi_borrower_pct"] == current["lmi_borrower_pct"]


# ---------------------------------------------------------------------------
# Queue A — Difficulty/combinatorial_formula/loan_register_per_loan_rounding_order
# ---------------------------------------------------------------------------

def test_loan_register_per_loan_rounding_order(api, bank_examiner_headers):
    """PRD §3.9: "first cap the loan's `loan_amount_cents` at one million
    dollars; then round each capped amount half up to the nearest multiple of
    one thousand dollars; then sum the per-loan rounded amounts within each
    type. Summing first and rounding the aggregate is expressly not permitted —
    the per-loan rounding happens before any addition."

    Design: Difficulty/combinatorial_formula/loan_register_per_loan_rounding_order
    """
    area = create_active_area(
        area_code="AA-CF2", msa_code="19100", state_code="TX", census_tracts=["T1"],
    )
    for action_date in ("2025-02-01", "2025-03-01"):
        create_reported_loan(
            area["id"], loan_amount_cents=150000,
            borrower_gross_annual_revenue_cents=50000000, action_date=action_date,
            census_tract="T1", tract_income_level="MIDDLE",
        )
    exam = create_scheduled_exam("2025-01-01", "2025-12-31")

    data = validate_success(api.get_lending_metrics(exam["id"], bank_examiner_headers))
    # Per-loan: round_half_up(150000/100000)=2 -> 200000 each; sum = 400000.
    # The forbidden sum-then-round order would give 300000.
    assert data["small_business_register_total_cents"] == 400000
    assert data["small_farm_register_total_cents"] == 0
    assert data["loan_count"] == 2


def test_loan_register_totals_grouped_by_loan_type(api, bank_examiner_headers):
    """PRD §3.9: "For each `REPORTED` loan in the window, grouped by
    `loan_type`: first cap the loan's `loan_amount_cents` at one million
    dollars; then round each capped amount half up to the nearest multiple of
    one thousand dollars; then sum the per-loan rounded amounts within each
    type."

    Design: Difficulty/combinatorial_formula/loan_register_per_loan_rounding_order
    """
    area = create_active_area(
        area_code="AA-CF2B", msa_code="19100", state_code="TX", census_tracts=["T1"],
    )
    create_reported_loan(
        area["id"], loan_type="SMALL_BUSINESS", loan_amount_cents=150000,
        borrower_gross_annual_revenue_cents=50000000, action_date="2025-02-01",
        census_tract="T1", tract_income_level="MIDDLE",
    )
    create_reported_loan(
        area["id"], loan_type="SMALL_FARM", loan_amount_cents=150000,
        borrower_gross_annual_revenue_cents=50000000, action_date="2025-03-01",
        census_tract="T1", tract_income_level="MIDDLE",
    )
    exam = create_scheduled_exam("2025-01-01", "2025-12-31")

    data = validate_success(api.get_lending_metrics(exam["id"], bank_examiner_headers))
    assert data["small_business_register_total_cents"] == 200000
    assert data["small_farm_register_total_cents"] == 200000
    assert data["loan_count"] == 2
