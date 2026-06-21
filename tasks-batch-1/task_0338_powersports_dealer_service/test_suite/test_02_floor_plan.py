"""Floor-plan loans: aging, interest accrual variants, curtailments, payoff, OCC.

Covers the simple-vs-declining interest divergence, the inclusive 90-day aging
boundary and its off-boundary partner, principal conservation under curtailment,
the scheduled-minimum and payoff-full guards, and the stale-loan-version OCC rule.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    create_curtailment_payload, TEST_USERS,
    create_floored_loan, create_curtailment_due_loan, set_clock,
    assert_floor_plan_loan_principal_conserved,
)

DP = TEST_USERS["dealer_principal_headers"]
SA = TEST_USERS["service_advisor_headers"]


def test_interest_simple_vs_declining_diverges(api):
    """PRD 3.2: "The simple variant ... computes a per-diem by taking
    original_advance_cents, multiplying by apr_bps, dividing by 10000 and then by
    365, and rounding that per-diem half up; the accrued interest is that per-diem
    multiplied by the number of elapsed days, and curtailments are ignored."
    PRD 3.2: "Because the declining basis charges per-diem on a falling balance,
    the same loan and payments always yield a smaller number under DECLINING than
    under SIMPLE."

    Design: Difficulty/dual_variant_calc/floor_plan_interest_simple_vs_declining_diverges
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-04-01T00:00:00.000Z")
    aged = validate_success(api.run_aging(loan["id"], DP), 200)
    validate_success(api.create_curtailment(
        create_curtailment_payload(loan["id"], 200_000, aged["version"],
                                   reason="SCHEDULED"), DP), 201)
    set_clock("2026-04-11T00:00:00.000Z")

    declining = validate_success(
        api.get_floor_plan_loan(loan["id"], DP, params={"interest_basis": "DECLINING"}), 200)
    assert declining["accrued_interest_cents"] == 24200, (
        f"declining interest expected 24200, got {declining['accrued_interest_cents']}")

    simple = validate_success(
        api.get_floor_plan_loan(loan["id"], DP, params={"interest_basis": "SIMPLE"}), 200)
    assert simple["accrued_interest_cents"] == 24700, (
        f"simple interest expected 24700, got {simple['accrued_interest_cents']}")
    assert declining["accrued_interest_cents"] < simple["accrued_interest_cents"]


def test_declining_interest_smaller_than_simple_after_curtailment(api):
    """PRD 3.2: "The declining variant, requested with an interest_basis of
    DECLINING, instead walks the loan's POSTED curtailments in created_at ascending
    order ... and accrues per-diem on the principal outstanding within each segment
    between curtailment boundaries."
    PRD 3.2: "Because the declining basis charges per-diem on a falling balance, the
    same loan and payments always yield a smaller number under DECLINING than under
    SIMPLE."

    Design: Difficulty/dual_variant_calc/floor_plan_interest_simple_vs_declining_diverges
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-04-01T00:00:00.000Z")
    aged = validate_success(api.run_aging(loan["id"], DP), 200)
    validate_success(api.create_curtailment(
        create_curtailment_payload(loan["id"], 200_000, aged["version"],
                                   reason="SCHEDULED"), DP), 201)
    set_clock("2026-04-11T00:00:00.000Z")
    declining = validate_success(
        api.get_floor_plan_loan(loan["id"], DP, params={"interest_basis": "DECLINING"}), 200)
    assert declining["accrued_interest_cents"] == 24200


def test_interest_default_basis_is_simple(api):
    """PRD 3.2: "The simple variant — the default presentation, and the basis used
    by the aging check — computes a per-diem by taking original_advance_cents,
    multiplying by apr_bps, dividing by 10000 and then by 365, and rounding that
    per-diem half up; the accrued interest is that per-diem multiplied by the
    number of elapsed days, and curtailments are ignored."

    Design: Corner/calculations/floorplan_interest_simple_default_basis
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-04-11T00:00:00.000Z")
    fetched = validate_success(api.get_floor_plan_loan(loan["id"], DP), 200)
    # per-diem round(1000000*900/10000/365)=247; 247*100 days = 24700
    assert fetched["accrued_interest_cents"] == 24700


def test_aging_due_at_exactly_90_days_inclusive(api):
    """PRD 3.2: "Running aging on a loan ... advances it from OPEN to
    CURTAILMENT_DUE once the number of whole days between its opened_on date and
    the current clock reaches the curtailment-due threshold, which is 90 days; the
    comparison is inclusive, so the loan becomes due at exactly 90 days, not 91."

    Design: Difficulty/boundary_precision_check/floorplan_aging_due_at_exactly_90_days_inclusive
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-04-01T00:00:00.000Z")  # exactly 90 days
    aged = validate_success(api.run_aging(loan["id"], DP), 200)
    assert aged["status"] == "CURTAILMENT_DUE"


def test_aging_below_90_days_stays_open(api):
    """PRD 3.2: "If fewer than 90 days have elapsed, the loan stays OPEN."

    Design: Difficulty/boundary_precision_check/floorplan_aging_due_at_exactly_90_days_inclusive
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-03-31T00:00:00.000Z")  # 89 days
    aged = validate_success(api.run_aging(loan["id"], DP), 200)
    assert aged["status"] == "OPEN"


def test_aging_below_90_days_stays_open_off_boundary(api):
    """PRD 3.2: "If fewer than 90 days have elapsed, the loan stays OPEN."

    Design: Corner/calculations/floorplan_aging_below_90_days_stays_open
    """
    unit, loan = create_floored_loan(opened_on="2026-01-01T00:00:00.000Z",
                                     apr_bps=900, dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    set_clock("2026-03-31T00:00:00.000Z")
    aged = validate_success(api.run_aging(loan["id"], DP), 200)
    assert aged["status"] == "OPEN"


def test_scheduled_curtailment_conserves_principal(api):
    """PRD 3.2: "Posting a curtailment reduces the loan's principal_outstanding_cents
    by the paid principal, increases cumulative_curtailment_cents by the same
    amount, and increments the loan's version by one."
    PRD 3.2: "A SCHEDULED curtailment that satisfies the required minimum brings a
    CURTAILMENT_DUE loan back to OPEN."

    Design: Difficulty/compensating_invariant/floorplan_principal_curtailment_conserves_advance
    """
    unit, aged = create_curtailment_due_loan(dealer_cost_cents=1_000_000)
    validate_success(api.create_curtailment(
        create_curtailment_payload(aged["id"], 100_000, aged["version"],
                                   reason="SCHEDULED"), DP), 201)
    loan = validate_success(api.get_floor_plan_loan(aged["id"], DP), 200)
    assert loan["principal_outstanding_cents"] == 900_000
    assert loan["cumulative_curtailment_cents"] == 100_000
    assert loan["status"] == "OPEN"


def test_curtailment_principal_plus_cumulative_equals_advance(api):
    """PRD 3.2: "Posting a curtailment reduces the loan's principal_outstanding_cents
    by the paid principal, increases cumulative_curtailment_cents by the same
    amount, and increments the loan's version by one."

    Design: Difficulty/compensating_invariant/floorplan_principal_curtailment_conserves_advance
    """
    unit, aged = create_curtailment_due_loan(dealer_cost_cents=1_000_000)
    validate_success(api.create_curtailment(
        create_curtailment_payload(aged["id"], 100_000, aged["version"],
                                   reason="SCHEDULED"), DP), 201)
    loan = validate_success(api.get_floor_plan_loan(aged["id"], DP), 200)
    assert_floor_plan_loan_principal_conserved(loan)
    assert (loan["principal_outstanding_cents"] + loan["cumulative_curtailment_cents"]
            == 1_000_000)


def test_scheduled_curtailment_below_required_rejected(api):
    """PRD 3.2: "The posted principal_cents must be at least that required amount;
    a SCHEDULED curtailment below it is rejected with ERR_CURTAILMENT_INSUFFICIENT
    (HTTP 422)."

    Design: Corner/validations/curtailment_scheduled_below_required_rejected
    """
    unit, aged = create_curtailment_due_loan(dealer_cost_cents=1_000_000)
    res = api.create_curtailment(
        create_curtailment_payload(aged["id"], 50_000, aged["version"],
                                   reason="SCHEDULED"), DP)
    validate_error(res, "ERR_CURTAILMENT_INSUFFICIENT")


def test_sale_payoff_not_full_rejected(api):
    """PRD 3.2: "A curtailment with reason SALE_PAYOFF pays the loan off entirely
    and requires that principal_cents exactly equal the loan's current
    principal_outstanding_cents; if the amount is not the full outstanding balance,
    the payoff is rejected with ERR_PAYOFF_NOT_FULL (HTTP 422)."

    Design: Corner/validations/sale_payoff_not_full_rejected
    """
    unit, loan = create_floored_loan(dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    res = api.create_curtailment(
        create_curtailment_payload(loan["id"], 500_000, loan["version"],
                                   reason="SALE_PAYOFF"), DP)
    validate_error(res, "ERR_PAYOFF_NOT_FULL")


def test_stale_loan_version_on_curtailment_rejected(api):
    """PRD 2.6: "If that value does not equal the loan's current version — because
    another writer has, for example, already posted a curtailment that reduced the
    principal and thereby changed the basis for this paydown — the request is
    rejected with ERR_STALE_LOAN_VERSION (HTTP 412), and no curtailment is created."

    Design: Corner/cross_cutting_complexity_layers/occ_stale_loan_version_on_curtailment_rejected
    """
    unit, loan = create_floored_loan(dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    stale_v = loan["version"]
    validate_success(api.create_curtailment(
        create_curtailment_payload(loan["id"], 100_000, stale_v,
                                   reason="VOLUNTARY"), DP), 201)
    res = api.create_curtailment(
        create_curtailment_payload(loan["id"], 100_000, stale_v,
                                   reason="VOLUNTARY"), DP)
    validate_error(res, "ERR_STALE_LOAN_VERSION")
    loan_after = validate_success(api.get_floor_plan_loan(loan["id"], DP), 200)
    assert loan_after["principal_outstanding_cents"] == 900_000


def test_curtailment_with_current_loan_version_succeeds(api):
    """PRD 2.6: "the client supplies the parent's last-observed version, and a
    mismatch with the parent's actual current version is rejected before any write
    occurs."
    PRD 3.2: "Posting a curtailment reduces the loan's principal_outstanding_cents
    by the paid principal, increases cumulative_curtailment_cents by the same
    amount, and increments the loan's version by one."

    Design: Corner/cross_cutting_complexity_layers/occ_correct_loan_version_succeeds
    """
    unit, loan = create_floored_loan(dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    validate_success(api.create_curtailment(
        create_curtailment_payload(loan["id"], 100_000, loan["version"],
                                   reason="VOLUNTARY"), DP), 201)
    loan_after = validate_success(api.get_floor_plan_loan(loan["id"], DP), 200)
    assert loan_after["principal_outstanding_cents"] == 900_000
    assert loan_after["version"] == 2


def test_filtered_list_curtailments_by_loan(api):
    """PRD 4: "GET /curtailments | List curtailments (filter by floor_plan_loan_id)."
    PRD 2.3: "Paginated list responses include the following fields in the meta
    object of the response envelope: limit, offset, total_count, and has_more."

    Design: Corner/endpoints/filtered_list_curtailments_by_loan
    """
    unit, aged = create_curtailment_due_loan(dealer_cost_cents=1_000_000)
    validate_success(api.create_curtailment(
        create_curtailment_payload(aged["id"], 100_000, aged["version"],
                                   reason="SCHEDULED"), DP), 201)
    from test_helpers import validate_paginated
    data, meta = validate_paginated(
        api.list_curtailments(DP, params={"floor_plan_loan_id": aged["id"]}))
    assert meta["total_count"] == 1
    assert all(c["floor_plan_loan_id"] == aged["id"] for c in data)


def test_filtered_list_floor_plan_loans_by_unit(api):
    """PRD 4: "GET /floor-plan-loans | List floor-plan loans (filter by unit_id, status)."

    Design: Corner/endpoints/filtered_list_floor_plan_loans_by_unit
    """
    unit, loan = create_floored_loan(dealer_cost_cents=1_000_000,
                                     clock="2026-01-01T00:00:00.000Z")
    from test_helpers import validate_paginated
    data, meta = validate_paginated(
        api.list_floor_plan_loans(DP, params={"unit_id": unit["id"]}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == loan["id"]
