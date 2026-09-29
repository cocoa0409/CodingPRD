"""
Transitive cascades: chains where each link is caused by the link before it.

A reconsideration response writes a ledger row, which moves the report's current
value, which re-derives the loan's effective value and ratio, which re-bands the
decision impact, which reinstates a suspended loan. A bias substantiation increments
a lifetime tally, which recomputes a rolling score, which degrades panel standing,
which releases an unrelated order that appraiser was holding.
"""

from test_helpers import (
    COMPLIANCE_USER_1,
    DESK_REVIEWER_HEADERS,
    fixtures as fx,
    validate_paginated,
)

RIVER_ROAD_GRID = [
    {
        "street_address": "41 River Road",
        "sale_price_cents": 47000000,
        "gross_adjustment_cents": 470000,
        "net_adjustment_cents": 470000,
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
        "sale_price_cents": 49000000,
        "gross_adjustment_cents": 490000,
        "net_adjustment_cents": -490000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
    },
]


def _suspended_purchase_loan(api):
    """A purchase loan whose field review dropped the value far enough to push the
    ratio past the denial band, suspending the loan, with a reconsideration routed to
    the authoring appraiser."""
    env = fx.escalation_completed(
        api, 41000000,
        window_start="2026-08-01T09:00:00Z",
        window_end="2026-08-01T12:00:00Z",
        purchase=True,
        amc={"name": "Ironwood Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-4001",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-4001",
            "license_state": "CA",
        },
        loan={
            "loan_number": "LN-2747-4A",
            "risk_tier": "HIGH",
            "borrower_display_name": "Dana Borrower",
        },
        appraisal={"reported_value_cents": 48000000, "exhibit_count": 1},
        comparables=RIVER_ROAD_GRID,
    )
    assert env["loan"]["ltv_bps"] == 9756
    assert env["loan"]["decision_impact"] == "DENIAL_RECOMMENDED"
    assert env["loan"]["underwriting_status"] == "SUSPENDED"
    return fx.rov_awaiting_appraiser(api, env, requested_value_cents=42000000,
                                     prefix="Brook")


def test_reconsideration_ledger_row_walks_up_to_the_loan_value_and_ratio(api):
    """Links one to three: a ledger row moves the report value, then the loan figures.

    The appraiser adopts the borrower's closings at 41800000. That writes a second
    non-compensating ledger row of 800000 cents, 195 basis points against the value
    currently of record. The report's current value follows the running ledger account,
    and the loan's derived value, purchase-money effective value and ratio all follow
    the report.

    PRD: "`current_appraised_value_cents` is the value-of-record appraisal's original
    `reported_value_cents` plus the signed sum of `delta_cents` over **every** revision
    row on that appraisal, compensating rows included — the ledger is a running account,
    not a set of independent adjustments, so a downward revision followed by a
    compensating upward revision nets back out."

    Design: Difficulty/transitive_cascade/rov_revision_cascade_reinstates_suspended_loan
    """
    env = _suspended_purchase_loan(api)
    rov = fx.rov_respond(
        api, env["rov"]["id"], env["appraiser"]["id"], "VALUE_REVISED",
        revised_value_cents=41800000,
        response_note="Adopting the two borrower closings.",
    )
    assert rov["status"] == "RESPONDED"
    assert rov["outcome"] == "VALUE_REVISED"
    assert rov["responded_late"] is False

    revisions_body = api.list_value_revisions(
        env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 100}
    )
    revisions, meta = validate_paginated(revisions_body)
    assert meta["total_count"] == 2
    newest = revisions[-1]
    assert newest["source_type"] == "ROV"
    assert newest["delta_cents"] == 800000
    assert newest["delta_bps"] == 195
    assert newest["is_compensating"] is False

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["current_value_cents"] == 41800000
    assert appraisal["review_status"] == "VALUE_REVISED"

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["current_appraised_value_cents"] == 41800000
    assert loan["effective_value_cents"] == 41800000
    assert loan["ltv_bps"] == 9569


def test_the_re_banded_ratio_reinstates_the_suspended_loan(api):
    """Links four and five: the new band lifts the suspension and moves panel standing.

    A ratio of 9569 basis points is at most 9700, so the impact leaves the denial band
    for CONDITION_REQUIRED, and a recompute landing on any tier other than denial
    reinstates a suspended loan as conditionally approved. Two non-compensating
    revisions against a single in-window appraisal also take the author's rolling
    revision rate to 20000 basis points, clamping the score to zero and suspending her.

    PRD: "When a recompute lands on any other tier while the loan is suspended, the loan
    auto-reinstates `SUSPENDED → CONDITIONALLY_APPROVED` — and it returns to
    `CONDITIONALLY_APPROVED` regardless of which status it was suspended from, so a loan
    suspended out of `SUBMITTED` comes back as conditionally approved rather than as
    submitted."

    Design: Difficulty/transitive_cascade/rov_revision_cascade_reinstates_suspended_loan
    """
    env = _suspended_purchase_loan(api)
    fx.rov_respond(
        api, env["rov"]["id"], env["appraiser"]["id"], "VALUE_REVISED",
        revised_value_cents=41800000,
        response_note="Adopting the two borrower closings.",
    )

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["decision_impact"] == "CONDITION_REQUIRED"
    assert loan["underwriting_status"] == "CONDITIONALLY_APPROVED"
    assert loan["collateral_status"] == "VALUE_REVISED"

    author = fx.read_appraiser(api, env["appraiser"]["id"])
    assert author["revision_rate_bps"] == 20000
    assert author["performance_score_bps"] == 0
    assert author["panel_status"] == "SUSPENDED"


BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)


def _grid(prefix):
    """Three benign closed comparables addressed under one street name."""
    return [
        {
            "street_address": f"61 {prefix}",
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": f"62 {prefix}",
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": f"63 {prefix}",
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def _escalate_and_order(api, env, appraisal_id, assignee_id, window_start, window_end):
    """Carry a screened report through review to an assigned second-appraisal order."""
    review = fx.open_desk_review(api, appraisal_id)
    fx.submit_desk_review(api, review["id"],
                          findings_note="Narrative language and thin exhibits.")
    fx.decide_desk_review(api, review["id"], "ESCALATE",
                          decision_note="Second appraisal ordered.")
    order = fx.escalation_order_for(api, review["id"])
    return fx.assign_order(api, order["id"], assignee_id, window_start, window_end)


def _panel_on_the_probation_edge(api):
    """Two panel appraisers where the author's rolling score sits exactly on the
    probation cut-off, and where she is holding an unrelated second-appraisal order."""
    env = fx.panel_and_loan(
        api,
        with_reviewer=True,
        amc={"name": "Keystone Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-4002",
            "license_state": "CA",
        },
        reviewer={
            "full_name": "Bob Reviewer",
            "license_number": "CA-BR-4002",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-4B1", "borrower_display_name": "Dana Borrower"},
    )
    author, second = env["appraiser"], env["reviewer"]
    amc_id = env["amc"]["id"]

    env["appraisal"] = fx.deliver_appraisal(
        api, env["loan"]["id"], author["id"], amc_id,
        exhibit_count=1, narrative_text=BIASED_NARRATIVE,
    )
    fx.add_comparables(api, env["appraisal"]["id"], amc_id, _grid("Vine Street"))

    # A second report by the same author, delivered before any revision lands, so her
    # rolling appraisal denominator is two.
    env["second_loan"] = fx.create_loan_file(
        api, loan_number="LN-2747-4B2", loan_amount_cents=25000000,
        borrower_display_name="Evan Borrower",
    )
    env["second_appraisal"] = fx.deliver_appraisal(
        api, env["second_loan"]["id"], author["id"], amc_id,
        effective_date="2026-07-01T00:00:00Z", reported_value_cents=35000000,
    )

    fx.run_rule_checks(api, env["appraisal"]["id"])
    fx.run_bias_screen(api, env["appraisal"]["id"])
    env["order"] = _escalate_and_order(
        api, env, env["appraisal"]["id"], second["id"],
        "2026-08-01T09:00:00Z", "2026-08-01T12:00:00Z",
    )
    env["order"] = fx.complete_order(
        api, env["order"]["id"], amc_id, 43000000,
        documentation_note="Second appraisal supports a higher value.",
    )

    # An unrelated report authored by the second appraiser, whose own escalation order
    # is then staffed with the first author.
    env["third_loan"] = fx.create_loan_file(
        api, loan_number="LN-2747-4B3", borrower_display_name="Fay Borrower",
    )
    env["third_appraisal"] = fx.deliver_appraisal(
        api, env["third_loan"]["id"], second["id"], amc_id,
        exhibit_count=1, narrative_text=BIASED_NARRATIVE,
    )
    fx.add_comparables(api, env["third_appraisal"]["id"], amc_id, _grid("Laurel Street"))
    fx.run_rule_checks(api, env["third_appraisal"]["id"])
    fx.run_bias_screen(api, env["third_appraisal"]["id"])
    env["unrelated_order"] = _escalate_and_order(
        api, env, env["third_appraisal"]["id"], author["id"],
        "2026-08-03T09:00:00Z", "2026-08-03T12:00:00Z",
    )

    env["flags"] = fx.list_bias_flags(api, env["appraisal"]["id"])
    return env


def test_substantiation_walks_from_the_flag_to_the_authors_panel_standing(api):
    """Links one to four: the flag, the lifetime tally, the rolling score, the standing.

    Before adjudication the author's rolling score is exactly 7000 basis points, which
    the strictly-less-than cut-off leaves at ACTIVE. Substantiating one narrative flag
    increments her lifetime bias tally, which adds a 1200 basis point penalty to the
    same rolling formula, taking the score to 5800 and pushing her onto probation.

    PRD: "The score then starts at 10000 and subtracts three penalties: 0.60 multiplied
    by `revision_rate_bps` and rounded half up, plus 1200 for each entry in
    `substantiated_bias_count`, plus 400 for each entry in `sla_miss_count`."

    Design: Difficulty/transitive_cascade/bias_substantiation_cascade_forces_order_reassignment
    """
    env = _panel_on_the_probation_edge(api)
    author_before = fx.read_appraiser(api, env["appraiser"]["id"])
    assert author_before["performance_score_bps"] == 7000
    assert author_before["panel_status"] == "ACTIVE"

    flag = fx.adjudicate_flag(
        api, env["flags"][0]["id"], "SUBSTANTIATE",
        rationale=(
            "Prohibited neighbourhood language materially influenced the value opinion."
        ),
    )
    assert flag["status"] == "SUBSTANTIATED"
    assert flag["adjudicated_by_user_id"] == COMPLIANCE_USER_1

    author = fx.read_appraiser(api, env["appraiser"]["id"])
    assert author["substantiated_bias_count"] == 1
    assert author["total_appraisal_count"] == 2
    assert author["revision_rate_bps"] == 5000
    assert author["performance_score_bps"] == 5800
    assert author["panel_status"] == "PROBATION"


def test_degraded_standing_releases_an_unrelated_second_appraisal_order(api):
    """Link five: the order the author was holding on another file is released.

    The order that moves belongs to a different loan, a different report and a different
    author; the only connection is that the degraded appraiser was staffed on it. It
    keeps its priced total and its assignee for the audit trail, so the company's
    year-to-date spend still carries both orders at 61750 cents each, and the other
    appraiser's standing is untouched.

    PRD: "Whenever an assigned appraiser's `panel_status` leaves `ACTIVE` — by the
    automatic performance cascade of §3.9, by a bias substantiation, or by an explicit
    removal — every order currently `ASSIGNED` to that appraiser whose `escalation_type`
    is `SECOND_APPRAISAL` moves `ASSIGNED → REASSIGNMENT_REQUIRED`."

    Design: Difficulty/transitive_cascade/bias_substantiation_cascade_forces_order_reassignment
    """
    env = _panel_on_the_probation_edge(api)
    fx.adjudicate_flag(
        api, env["flags"][0]["id"], "SUBSTANTIATE",
        rationale=(
            "Prohibited neighbourhood language materially influenced the value opinion."
        ),
    )

    released = fx.read_escalation_order(api, env["unrelated_order"]["id"])
    assert released["status"] == "REASSIGNMENT_REQUIRED"
    assert released["assigned_appraiser_id"] == env["appraiser"]["id"]
    assert released["total_cost_cents"] == 61750

    completed = fx.read_escalation_order(api, env["order"]["id"])
    assert completed["total_cost_cents"] == 61750

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 123500

    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])
    assert appraisal["bias_screen_status"] == "SUBSTANTIATED"
    assert appraisal["review_status"] == "QUARANTINED"
    assert appraisal["quarantine_return_status"] == "VALUE_REVISED"

    loan = fx.read_loan_file(api, env["loan"]["id"])
    assert loan["collateral_status"] == "QUARANTINED"

    second = fx.read_appraiser(api, env["reviewer"]["id"])
    assert second["panel_status"] == "ACTIVE"
