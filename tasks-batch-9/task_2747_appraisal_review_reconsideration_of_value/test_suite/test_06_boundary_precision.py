"""
Boundary precision: metrics landing exactly on a declared bound or on a degenerate set.

The loan-to-value banding uses inclusive upper bounds, so a ratio of exactly 8000 basis
points must read as no impact rather than as a pricing adjustment, and the purchase-money
rule is exercised at its tie point where the appraised value equals the contract price.
The receipt battery is separately driven over an empty comparable grid, where one weighted
component collapses to zero, two maxima must report zero rather than null, and the
reconciliation metrics must report null rather than zero.
"""

from test_helpers import (
    DESK_REVIEWER_HEADERS,
    fixtures as fx,
    validate_paginated,
)

# Three closed sales whose adjusted prices are 47000000, 48000000 and 49000000, so
# the per-comparable division by three sums back to exactly the reported value.
CONTRACT_TIE_GRID = [
    {
        "street_address": "41 River Road",
        "sale_price_cents": 46600000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 400000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "42 River Road",
        "sale_price_cents": 48000000,
        "gross_adjustment_cents": 480000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "43 River Road",
        "sale_price_cents": 49400000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": -400000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _field_review_completed_at_the_contract_price(api):
    """A high-tier purchase loan whose field review lands the value of record on the
    contract price, so the ratio comes to rest on the inclusive no-impact bound."""
    return fx.escalation_completed(
        api,
        50000000,
        purchase=True,
        amc={"name": "Summit Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-6001",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-6001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-6A1",
            "risk_tier": "HIGH",
            "borrower_display_name": "Ivan Borrower",
        },
        appraisal={"reported_value_cents": 48000000, "exhibit_count": 1},
        comparables=CONTRACT_TIE_GRID,
    )


def test_a_ratio_of_exactly_eight_thousand_basis_points_reads_as_no_impact(api):
    """The ratio settles on 8000 basis points and bands as no impact, not as pricing.

    A 40000000 cent loan against an effective value of 50000000 cents is exactly 8000
    basis points. The upper bound of the first band is inclusive, so this loan sits in
    the benign band and the underwriting dimension is left where it was.

    PRD: "A loan sitting at exactly 8000 basis points is `NO_IMPACT`, not
    `PRICING_ADJUSTMENT`; one at exactly 9500 is `PRICING_ADJUSTMENT`; one at exactly
    9700 is `CONDITION_REQUIRED`."

    Design: Difficulty/boundary_precision_check/escalation_completion_lands_ltv_exactly_on_no_impact_bound
    """
    env = _field_review_completed_at_the_contract_price(api)
    loan = env["loan"]

    assert loan["ltv_bps"] == 8000
    assert loan["decision_impact"] == "NO_IMPACT"
    assert loan["underwriting_status"] == "SUBMITTED"
    assert loan["collateral_status"] == "VALUE_REVISED"


def test_the_purchase_money_rule_ties_at_the_contract_price(api):
    """The lesser-of rule is exercised where the two candidates are equal.

    The completed field review puts 50000000 cents of appraised value against a
    50000000 cent contract price, so the purchase-money minimum has no strict winner
    and the effective value must be that shared figure.

    PRD: "`effective_value_cents` then applies the purchase-money rule: when the loan's
    `loan_purpose` is `PURCHASE`, it is the lesser of `current_appraised_value_cents`
    and the loan's `contract_price_cents`; for every other purpose it is simply
    `current_appraised_value_cents`, and the contract price is ignored even when it is
    present."

    Design: Difficulty/boundary_precision_check/escalation_completion_lands_ltv_exactly_on_no_impact_bound
    """
    env = _field_review_completed_at_the_contract_price(api)
    loan = env["loan"]

    assert loan["current_appraised_value_cents"] == 50000000
    assert loan["effective_value_cents"] == 50000000
    assert loan["value_of_record_appraisal_id"] == env["appraisal"]["id"]
    assert env["appraisal"]["current_value_cents"] == 50000000
    assert env["appraisal"]["review_status"] == "VALUE_REVISED"


def test_the_ledger_row_records_the_boundary_crossing_arithmetic(api):
    """The single revision row carries the movement and the impact it produced.

    The value moved up 2000000 cents off a 48000000 cent base, which is 417 basis
    points once the half-up rounding is applied, and the row is not a compensating one
    because no dispute was overturned.

    PRD: "`delta_bps` is 10000 multiplied by the absolute value of `delta_cents`,
    divided by `prior_value_cents`, rounded half up — an absolute magnitude, always
    non-negative, so the direction of the movement lives only in the sign of
    `delta_cents`."

    Design: Difficulty/boundary_precision_check/escalation_completion_lands_ltv_exactly_on_no_impact_bound
    """
    env = _field_review_completed_at_the_contract_price(api)

    assert env["order"]["status"] == "COMPLETED"
    assert env["order"]["total_cost_cents"] == 45000
    assert env["amc"]["ytd_escalation_spend_cents"] == 45000

    revisions = fx.list_value_revisions(api, env["appraisal"]["id"])
    assert len(revisions) == 1
    row = revisions[0]
    assert row["source_type"] == "FIELD_REVIEW"
    assert row["prior_value_cents"] == 48000000
    assert row["new_value_cents"] == 50000000
    assert row["delta_cents"] == 2000000
    assert row["delta_bps"] == 417
    assert row["is_compensating"] is False
    assert row["ltv_bps_after"] == 8000
    assert row["decision_impact_after"] == "NO_IMPACT"


def _report_with_no_grid(api):
    """A complete report on all eight sections with seven exhibits and no comparables
    at all, taken through the receipt battery."""
    return fx.graded_report(
        api,
        amc={"name": "Harbour Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-6002",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-6B1",
            "borrower_display_name": "Jo Borrower",
        },
        comparables=[],
    )


def test_an_empty_grid_zeroes_only_the_comparable_component_of_completeness(api):
    """Completeness lands on 7000: full marks on sections and exhibits, nothing on comps.

    With eight of eight sections and seven of seven exhibits both components are a full
    10000, while the comparable component takes the lesser of a zero closed count and
    the three-comparable target and so scores nothing. Half the weight plus two tenths
    of the weight survive, which is exactly 7000 basis points, and that lands the
    completeness check in the warning band.

    PRD: "The comparable component takes the lesser of `closed_comp_count` and the
    three-closed-comparable target, multiplies by 10000, divides by 3, and rounds
    half-up — so three or more closed in-grid comparables score a full 10000 and there
    is no credit beyond three."

    Design: Difficulty/boundary_precision_check/rule_check_battery_on_empty_comparable_grid
    """
    env = _report_with_no_grid(api)
    appraisal = env["appraisal"]

    assert appraisal["completeness_score_bps"] == 7000
    assert appraisal["eligible_comp_count"] == 0
    assert appraisal["closed_comp_count"] == 0

    rows = fx.list_rule_checks(api, appraisal["id"])
    by_code = {row["check_code"]: row for row in rows}
    assert by_code["CHK_COMPLETENESS"]["outcome"] == "WARN"


def test_an_empty_grid_reports_zero_maxima_but_null_reconciliation(api):
    """The two degenerate conventions differ: maxima are zero, reconciliation is null.

    On the empty eligible set the adjustment maxima are defined figures rather than
    absent ones, so both read zero and both magnitude checks pass, while the reconciled
    value and its variance are genuinely absent and the reconciliation check passes for
    want of anything to compare.

    PRD: "When there are no eligible comparables, `indicated_value_cents` and
    `variance_vs_reported_bps` are both set to null and this check passes — there is
    nothing to reconcile."

    Design: Difficulty/boundary_precision_check/rule_check_battery_on_empty_comparable_grid
    """
    env = _report_with_no_grid(api)
    appraisal = env["appraisal"]

    assert appraisal["max_gross_adjustment_bps"] == 0
    assert appraisal["max_net_adjustment_bps"] == 0
    assert appraisal["indicated_value_cents"] is None
    assert appraisal["variance_vs_reported_bps"] is None

    by_code = {
        row["check_code"]: row for row in fx.list_rule_checks(api, appraisal["id"])
    }
    assert by_code["CHK_GROSS_ADJUSTMENT"]["outcome"] == "PASS"
    assert by_code["CHK_NET_ADJUSTMENT"]["outcome"] == "PASS"
    assert by_code["CHK_VALUE_RECONCILIATION"]["outcome"] == "PASS"


def test_the_empty_grid_still_writes_all_eight_rows_in_sequence(api):
    """All eight rows are emitted, and only the closed-count row fails.

    The battery is not shortened by the absent grid. Every position is written in its
    declared order, the distance and age rows report their empty-set placeholders and
    pass, and the single failure on the closed-comparable count is what flags the
    report while the completeness warning alone would not have.

    PRD: "The fixed sequence is `CHK_COMPLETENESS` at position 1, `CHK_COMP_COUNT` at 2,
    `CHK_COMP_DISTANCE` at 3, `CHK_COMP_AGE` at 4, `CHK_GROSS_ADJUSTMENT` at 5,
    `CHK_NET_ADJUSTMENT` at 6, `CHK_VALUE_RECONCILIATION` at 7, and `CHK_FORM_TYPE` at
    8."

    Design: Difficulty/boundary_precision_check/rule_check_battery_on_empty_comparable_grid
    """
    env = _report_with_no_grid(api)
    appraisal = env["appraisal"]

    assert appraisal["rule_check_fail_count"] == 1
    assert appraisal["rule_check_warn_count"] == 1
    assert appraisal["review_status"] == "RULES_FLAGGED"

    rows, meta = validate_paginated(
        api.list_rule_checks(appraisal["id"], DESK_REVIEWER_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 8
    assert [row["sequence_no"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8]
    assert [row["check_code"] for row in rows] == [
        "CHK_COMPLETENESS",
        "CHK_COMP_COUNT",
        "CHK_COMP_DISTANCE",
        "CHK_COMP_AGE",
        "CHK_GROSS_ADJUSTMENT",
        "CHK_NET_ADJUSTMENT",
        "CHK_VALUE_RECONCILIATION",
        "CHK_FORM_TYPE",
    ]
    assert [row["outcome"] for row in rows] == [
        "WARN", "FAIL", "PASS", "PASS", "PASS", "PASS", "PASS", "PASS",
    ]
    assert rows[1]["observed_value"] == "0"
    assert rows[2]["observed_value"] == "0.00"
    assert rows[3]["observed_value"] == "0"
    assert rows[7]["observed_value"] == "FORM_1004"
