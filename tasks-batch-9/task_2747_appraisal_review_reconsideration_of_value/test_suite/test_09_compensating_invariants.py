"""
Compensating invariants: a reversal that restores one quantity and deliberately not others.

Cancelling an assigned escalation order subtracts its charge back out of the company's
escalation spend while the order keeps the priced figures as an audit record, and the
review work it interrupted is returned to the decision queue unscathed. Overturning a
dispute writes a compensating revision that nets the value ledger back to the originally
reported value, yet the authoring appraiser's standing does not unwind, because the
compensating row is excluded from the performance numerator.
"""

from test_helpers import (
    fixtures as fx,
    validate_paginated,
    DESK_REVIEWER_HEADERS,
)

POPLAR_GRID = [
    {
        "street_address": "101 Poplar Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "102 Poplar Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "103 Poplar Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _cancelled_after_assignment(api):
    """A field-review order priced at 45000 cents, assigned, and then cancelled."""
    env = fx.escalated_and_assigned(
        api,
        amc={"name": "Cascade Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-9001",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-9001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-9A1",
            "risk_tier": "HIGH",
            "borrower_display_name": "Pia Borrower",
        },
        appraisal={"exhibit_count": 1},
        comparables=POPLAR_GRID,
    )
    assert env["order"]["total_cost_cents"] == 45000
    assert env["amc"]["ytd_escalation_spend_cents"] == 45000

    env["order"] = fx.cancel_order(
        api, env["order"]["id"],
        cancel_reason="Lender withdrew the escalation request.",
    )
    return env


def test_cancelling_an_assigned_order_subtracts_its_charge_back_out(api):
    """The escalation ledger returns to zero while the order keeps its priced figures.

    The charge is compensated rather than forgotten: the company's year-to-date spend
    falls back by exactly the amount the assignment added, the order retains every cost
    field it was priced with, and the assignee's open assignment is released without
    being counted as completed work.

    PRD: "Cancelling from `ASSIGNED` or `REASSIGNMENT_REQUIRED` writes a compensating
    ledger entry: `total_cost_cents` is **subtracted** from the company's
    `ytd_escalation_spend_cents`, while the order itself retains `total_cost_cents` and
    `assigned_appraiser_id` for audit; the assignee's `open_assignment_count` is
    decremented and the inspection window is released."

    Design: Difficulty/compensating_invariant/escalation_spend_ledger_restored_on_order_cancel
    """
    env = _cancelled_after_assignment(api)

    order = fx.read_escalation_order(api, env["order"]["id"])
    assert order["status"] == "CANCELLED"
    assert order["total_cost_cents"] == 45000
    assert order["base_fee_cents"] == 45000
    assert order["rush_surcharge_cents"] == 0
    assert order["discount_pct_bps"] == 0
    assert order["assigned_appraiser_id"] == env["reviewer"]["id"]

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 0

    reviewer = fx.read_appraiser(api, env["reviewer"]["id"])
    assert reviewer["open_assignment_count"] == 0
    assert reviewer["completed_assignment_count"] == 0


def test_the_cancellation_returns_the_review_to_the_decision_queue(api):
    """The two review dimensions step back one state and the loan holds its own.

    Cancellation is a revert edge, so the desk review drops out of escalation back to
    submitted and the appraisal drops back into desk review, both of which are states
    they already held. The loan's collateral position was never advanced by the
    escalation and does not move now.

    PRD: "Whichever it is, cancellation is a **revert edge**, not a dead end: the desk
    review moves `ESCALATED → SUBMITTED` and the appraisal moves `ESCALATED →
    IN_DESK_REVIEW`, so the review returns to the chief appraiser's decision queue for a
    fresh decision on the same review, while the loan's `collateral_status` stays at
    `UNDER_REVIEW`."

    Design: Difficulty/compensating_invariant/escalation_spend_ledger_restored_on_order_cancel
    """
    env = _cancelled_after_assignment(api)

    review = fx.read_desk_review(api, env["desk_review"]["id"])
    assert review["status"] == "SUBMITTED"

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["review_status"] == "IN_DESK_REVIEW"

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "UNDER_REVIEW"


def test_the_returned_review_is_not_re_scored_by_the_cancellation(api):
    """Only the money and the counters are compensated; the review findings are not.

    The scores the submission computed survive the cancellation untouched, so the review
    goes back to the decision queue carrying the same final quality score and the same
    escalation requirement it carried before.

    PRD: "The review keeps its `final_quality_score_bps`, its `required_escalation`, and
    its `submitted_by_user_id` unchanged — it is not re-scored and the
    segregation-of-duties constraint still names the same original submitter."

    Design: Difficulty/compensating_invariant/escalation_spend_ledger_restored_on_order_cancel
    """
    env = _cancelled_after_assignment(api)
    review = fx.read_desk_review(api, env["desk_review"]["id"])

    assert review["preliminary_quality_score_bps"] == 8086
    assert review["final_quality_score_bps"] == 8086
    assert review["required_escalation"] == "FIELD_REVIEW"
    assert review["risk_tier_at_review"] == "HIGH"
    assert review["submitted_by_user_id"] == env["desk_review"]["submitted_by_user_id"]


def test_the_cancellation_moves_no_value_of_record(api):
    """No revision row is written and the appraisal's value of record stands still.

    A cancellation is not one of the moments that recompute the loan's value, so the
    ledger on the appraisal is still empty, the appraisal's current value is the figure
    the first receipt run seeded from the reported value, and the loan carries no derived
    collateral figures at all.

    PRD: "This whole recompute-and-cascade sequence runs at exactly five moments: a
    desk-review acceptance, an escalation-order completion, a reconsideration
    appraiser-response, a dispute resolved as overturned, and the lifting of a bias
    quarantine."

    Design: Difficulty/compensating_invariant/escalation_spend_ledger_restored_on_order_cancel
    """
    env = _cancelled_after_assignment(api)

    rows, meta = validate_paginated(
        api.list_value_revisions(
            env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 100},
        )
    )
    assert meta["total_count"] == 0
    assert rows == []

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 40000000

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["current_appraised_value_cents"] is None
    assert loan["ltv_bps"] is None


RIVER_ROAD_GRID = [
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


def _dispute_overturned_back_to_the_reported_value(api):
    """A field review that lifted the value of record to the contract price, then a
    dispute resolved as overturned that puts it back to the reported value."""
    env = fx.escalation_completed(
        api,
        50000000,
        purchase=True,
        amc={"name": "Ridgeline Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-9002",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-9002",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-9B1",
            "risk_tier": "HIGH",
            "borrower_display_name": "Quinn Borrower",
        },
        appraisal={"reported_value_cents": 48000000, "exhibit_count": 1},
        comparables=RIVER_ROAD_GRID,
    )
    assert env["loan"]["ltv_bps"] == 8000
    assert env["appraiser"]["panel_status"] == "SUSPENDED"

    dispute = fx.file_dispute(
        api, env["appraisal"]["id"], env["amc"]["id"], env["appraiser"]["id"],
        dispute_basis="VALUE_OPINION",
        slot_start="2026-08-06T10:00:00Z", slot_end="2026-08-06T11:00:00Z",
    )
    fx.dispute_respond(
        api, dispute["id"], env["amc"]["id"], "VALUE_AMENDED",
        response_summary=(
            "The original appraiser concedes the field review overstated the site value."
        ),
    )
    env["dispute"] = fx.resolve_dispute(
        api, dispute["id"], "OVERTURNED",
        resolved_value_cents=48000000,
        resolution_note="Field review value set aside; the reported value stands.",
    )
    return env


def test_the_compensating_revision_nets_the_value_ledger_back_to_zero(api):
    """Both revision rows survive and their deltas cancel, restoring the reported value.

    Nothing is deleted by the overturn: the ledger holds the original upward movement and
    the compensating downward one, their signed deltas sum to nothing, and the appraisal's
    value of record is once again exactly the value the appraiser originally reported.

    PRD: "`current_appraised_value_cents` is the value-of-record appraisal's original
    `reported_value_cents` plus the signed sum of `delta_cents` over **every** revision
    row on that appraisal, compensating rows included — the ledger is a running account,
    not a set of independent adjustments, so a downward revision followed by a
    compensating upward revision nets back out."

    Design: Difficulty/compensating_invariant/value_of_record_restored_on_dispute_overturn
    """
    env = _dispute_overturned_back_to_the_reported_value(api)

    rows, meta = validate_paginated(
        api.list_value_revisions(
            env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 100},
        )
    )
    assert meta["total_count"] == 2
    assert sum(row["delta_cents"] for row in rows) == 0

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 48000000
    assert appraisal["reported_value_cents"] == 48000000
    assert appraisal["review_status"] == "VALUE_REVISED"


def test_the_overturn_walks_the_ratio_band_back_one_step(api):
    """The compensating row is flagged as such and records the band moving back.

    The dispute row is sourced from the dispute channel, carries the compensating flag,
    and moves the value down 2000000 cents off a 50000000 cent base, which is 400 basis
    points. The loan's derived figures follow it back: the ratio returns to 8333 basis
    points and the impact band steps back from no impact to a pricing adjustment.

    PRD: "Overturning writes a **compensating** value revision — one whose
    `is_compensating` flag is true and whose `source_type` is `DISPUTE` — sets the
    appraisal's `current_value_cents` to the resolved value, and recomputes the loan
    file's `current_appraised_value_cents`, `effective_value_cents`, `ltv_bps`, and
    `decision_impact`."

    Design: Difficulty/compensating_invariant/value_of_record_restored_on_dispute_overturn
    """
    env = _dispute_overturned_back_to_the_reported_value(api)
    assert env["dispute"]["status"] == "RESOLVED_OVERTURNED"
    assert env["dispute"]["resolution"] == "OVERTURNED"

    rows = fx.list_value_revisions(api, env["appraisal"]["id"])
    compensating = [row for row in rows if row["is_compensating"] is True]
    assert len(compensating) == 1
    row = compensating[0]
    assert row["source_type"] == "DISPUTE"
    assert row["prior_value_cents"] == 50000000
    assert row["new_value_cents"] == 48000000
    assert row["delta_cents"] == -2000000
    assert row["delta_bps"] == 400
    assert row["ltv_bps_before"] == 8000
    assert row["ltv_bps_after"] == 8333
    assert row["decision_impact_before"] == "NO_IMPACT"
    assert row["decision_impact_after"] == "PRICING_ADJUSTMENT"

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["current_appraised_value_cents"] == 48000000
    assert loan["effective_value_cents"] == 48000000
    assert loan["ltv_bps"] == 8333
    assert loan["decision_impact"] == "PRICING_ADJUSTMENT"


def test_the_authors_standing_does_not_unwind_with_the_value(api):
    """The performance numerator ignores compensating rows, so the suspension stands.

    The value ledger has fully compensated itself, but the revision rate is computed only
    over non-compensating rows, so it is still one revision against one appraisal. The
    score stays at 4000 basis points and the appraiser stays suspended, while the money
    ledger for the escalation is likewise never touched by the overturn.

    PRD: "Take the appraisals authored by that appraiser whose `review_status` is not
    `SUPERSEDED` and whose `created_at` is at or after the window start, and take the
    revision-ledger rows on those appraisals whose `is_compensating` is false and whose
    `created_at` is at or after the same window start."

    Design: Difficulty/compensating_invariant/value_of_record_restored_on_dispute_overturn
    """
    env = _dispute_overturned_back_to_the_reported_value(api)

    author = fx.read_appraiser(api, env["appraiser"]["id"])
    assert author["revision_rate_bps"] == 10000
    assert author["performance_score_bps"] == 4000
    assert author["panel_status"] == "SUSPENDED"

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 45000
    assert amc["open_dispute_count"] == 0
