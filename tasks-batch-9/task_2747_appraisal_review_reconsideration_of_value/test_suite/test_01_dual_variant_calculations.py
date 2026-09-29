"""
Dual-variant calculations: two named variants of one formula over the same inputs.

The desk-review quality score has a preliminary variant frozen at open time and a
final variant computed at submission from four penalty terms; the appraiser
performance score has a rolling 365-day variant that drives panel standing and a
lifetime variant that is audit-only. Each pair is exercised so that both variants
are observable side by side on one record and their divergence is pinned exactly.
"""

from test_helpers import fixtures as fx

# A narrative carrying prohibited terms at positions 1, 2 and 8 of the declared
# list, so the bias index is three twelve-point contributions.
BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)

# A grid that breaches the suburban distance ceiling on one row and the single
# gross-adjustment ceiling on another, so the final variant charges both the
# distance penalty and, with the narrative above, the bias penalty.
STRETCHED_GRID = [
    {
        "street_address": "11 Oak Street",
        "sale_price_cents": 38000000,
        "gross_adjustment_cents": 11400000,
        "net_adjustment_cents": 1900000,
        "distance_miles": 1.2,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "22 Elm Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 3900000,
        "net_adjustment_cents": -390000,
        "distance_miles": 3.5,
        "sale_date": "2026-04-10T00:00:00Z",
    },
    {
        "street_address": "33 Pine Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 2050000,
        "net_adjustment_cents": 410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-01T00:00:00Z",
    },
]


def _stretched_review(api):
    """A standard-tier report with a stretched grid and a biased narrative, screened
    and taken into a DRAFT desk review."""
    env = fx.screened_report(
        api,
        amc={"name": "Summit Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-1001",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-1A", "borrower_display_name": "Dana Borrower"},
        appraisal={"exhibit_count": 5, "narrative_text": BIASED_NARRATIVE},
        comparables=STRETCHED_GRID,
    )
    env["desk_review"] = fx.open_desk_review(
        api, env["appraisal"]["id"],
        reviewer_note="Desk intake of the Summit delivery.",
    )
    return env


def test_preliminary_variant_charges_only_the_rule_penalty(api):
    """The preliminary score is the completeness base less the rule penalty alone.

    A report scoring 9429 basis points for completeness with one FAIL row and one
    WARN row is opened for review. The preliminary variant subtracts 600 for the
    failure and 200 for the warning and stops, ignoring the stretched distance and
    the biased narrative entirely.

    PRD: "The **preliminary** variant stops there: it is the base minus the rule
    penalty, floored at zero, and it is computed exactly once at open time,
    persisted to `preliminary_quality_score_bps`, and never recomputed no matter
    what happens afterwards."

    Design: Difficulty/dual_variant_calc/desk_review_quality_score_preliminary_vs_final_on_desk_review
    """
    env = _stretched_review(api)
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])

    assert appraisal["completeness_score_bps"] == 9429
    assert appraisal["rule_check_fail_count"] == 1
    assert appraisal["rule_check_warn_count"] == 1

    review = fx.read_desk_review(api, env["desk_review"]["id"])
    assert review["preliminary_quality_score_bps"] == 8629
    assert review["risk_tier_at_review"] == "STANDARD"
    assert review["final_quality_score_bps"] is None

    submitted = fx.submit_desk_review(
        api, env["desk_review"]["id"],
        findings_note="Grid stretch and biased narrative language noted.",
    )
    assert submitted["preliminary_quality_score_bps"] == 8629


def test_final_variant_adds_the_distance_and_bias_penalties(api):
    """Submission charges the distance and bias terms the preliminary variant skips.

    The same report is submitted. One eligible comparable sits at 3.5 miles against
    a suburban ceiling of 3.00, and the bias screen reported INDICATED, so the final
    variant is the preliminary figure less 300 and less 1500 -- a gap of exactly
    1800 basis points -- and the bias override resolves the requirement.

    PRD: "For identical appraisal data the final score is therefore strictly lower
    than the preliminary score whenever a distance breach or a bias indication
    exists, and the gap is exactly the sum of the distance and bias penalties."

    Design: Difficulty/dual_variant_calc/desk_review_quality_score_preliminary_vs_final_on_desk_review
    """
    env = _stretched_review(api)
    review = fx.submit_desk_review(
        api, env["desk_review"]["id"],
        findings_note="Grid stretch and biased narrative language noted.",
    )

    assert review["status"] == "SUBMITTED"
    assert review["preliminary_quality_score_bps"] == 8629
    assert review["final_quality_score_bps"] == 6829
    assert (
        review["preliminary_quality_score_bps"] - review["final_quality_score_bps"]
    ) == 1800
    assert review["required_escalation"] == "SECOND_APPRAISAL"
    assert review["risk_tier_at_review"] == "STANDARD"


def test_both_variants_read_the_same_persisted_receipt_roll_ups(api):
    """The two variants share one base: the persisted completeness score and tallies.

    The stretched grid is pinned figure by figure -- the adjustment maxima, the
    reconciled value under per-comparable rounding, the variance, and the bias index
    of three twelve-point narrative hits -- so that the divergence between the two
    quality-score variants is attributable to the penalty terms and to nothing else.

    PRD: "Both start from the appraisal's persisted `completeness_score_bps`."

    Design: Difficulty/dual_variant_calc/desk_review_quality_score_preliminary_vs_final_on_desk_review
    """
    env = _stretched_review(api)
    appraisal = fx.read_appraisal(api, env["appraisal"]["id"])

    assert appraisal["max_gross_adjustment_bps"] == 3000
    assert appraisal["max_net_adjustment_bps"] == 500
    assert appraisal["indicated_value_cents"] == 39973333
    assert appraisal["variance_vs_reported_bps"] == 7
    assert appraisal["bias_risk_index"] == 36
    assert appraisal["bias_screen_status"] == "INDICATED"
    assert appraisal["completeness_score_bps"] == 9429

    review = fx.submit_desk_review(
        api, env["desk_review"]["id"],
        findings_note="Grid stretch and biased narrative language noted.",
    )
    assert review["preliminary_quality_score_bps"] == 8629
    assert review["final_quality_score_bps"] == 6829


# Three closed sales that clear every receipt check against a December 2024
# effective date, so the first report is accepted at its reported value.
DATED_GRID = [
    {
        "street_address": "101 Cedar Lane",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2024-10-01T00:00:00Z",
    },
    {
        "street_address": "202 Birch Road",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2024-09-15T00:00:00Z",
    },
    {
        "street_address": "303 Maple Avenue",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2024-11-01T00:00:00Z",
    },
]


def _appraiser_across_two_windows(api):
    """An appraiser carrying one revised report from January 2025 and one clean report
    delivered nineteen months later, so the rolling window holds only the second."""
    fx.set_clock(api, "2025-01-01T00:00:00Z")
    env = fx.screened_report(
        api,
        amc={"name": "Cascade Appraisal Management"},
        appraiser={
            "full_name": "Alice Author",
            "license_number": "CA-AL-1002",
            "license_state": "CA",
        },
        loan={"loan_number": "LN-2747-1B", "borrower_display_name": "Dana Borrower"},
        appraisal={
            "effective_date": "2024-12-01T00:00:00Z",
            "narrative_text": (
                "Well maintained subject in a stable market with typical marketability."
            ),
        },
        comparables=DATED_GRID,
    )
    review = fx.open_desk_review(api, env["appraisal"]["id"])
    fx.submit_desk_review(api, review["id"], findings_note="Clean delivery.")
    fx.decide_desk_review(api, review["id"], "ACCEPT", decision_note="Value supported.")

    rov = fx.open_rov(
        api, env["loan"]["id"], env["appraisal"]["id"],
        requested_value_cents=41000000,
        borrower_statement="Two recent closings support a higher value.",
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="404 Walnut Court",
        sale_price_cents=41000000, sale_date="2024-11-15T00:00:00Z",
        distance_miles=1.1,
    )
    fx.file_evidence(
        api, rov["id"], "CLOSED_SALE", street_address="505 Spruce Way",
        sale_price_cents=40500000, sale_date="2024-11-20T00:00:00Z",
        distance_miles=0.9,
    )
    fx.route_rov(api, rov["id"], intake_note="Two admissible closed sales on file.")
    fx.rov_respond(
        api, rov["id"], env["appraiser"]["id"], "VALUE_REVISED",
        revised_value_cents=40800000,
        response_note="Adopting the two supplied closings.",
    )

    fx.set_clock(api, "2026-08-01T00:00:00Z")
    env["second_loan"] = fx.create_loan_file(
        api, loan_number="LN-2747-1B2", loan_amount_cents=25000000,
        borrower_display_name="Evan Borrower",
    )
    env["second_appraisal"] = fx.deliver_appraisal(
        api, env["second_loan"]["id"], env["appraiser"]["id"], env["amc"]["id"],
        effective_date="2026-07-01T00:00:00Z", reported_value_cents=35000000,
        narrative_text="Average condition, typical marketability.",
    )
    return env


def test_rolling_variant_drops_the_out_of_window_revision(api):
    """The 365-day variant sees only the second report, so its revision rate is zero.

    A monitoring panel review recomputes both variants from the logical clock. With
    the clock at August 2026 the window opens in August 2025, which excludes the
    January 2025 report and its revision, so the rolling variant reports one
    appraisal, a zero revision rate and a perfect score.

    PRD: "The rolling variant sets the window start at the logical clock minus 365
    days and persists its answer to `performance_score_bps`, alongside
    `revision_rate_bps` and `total_appraisal_count`; this is the only variant the
    panel cascade reads."

    Design: Difficulty/dual_variant_calc/appraiser_performance_rolling_12m_vs_lifetime_on_appraiser
    """
    env = _appraiser_across_two_windows(api)
    appraiser = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR",
        note="Quarterly panel monitoring pass.",
    )

    assert appraiser["performance_score_bps"] == 10000
    assert appraiser["revision_rate_bps"] == 0
    assert appraiser["total_appraisal_count"] == 1
    assert appraiser["substantiated_bias_count"] == 0
    assert appraiser["sla_miss_count"] == 0


def test_lifetime_variant_keeps_the_out_of_window_revision(api):
    """The unfiltered variant keeps both reports, so the two answers diverge by 3000.

    The same monitoring review is the only way to read both variants side by side.
    The lifetime variant applies no date filter, so it sees two appraisals and one
    non-compensating revision -- a 5000 basis point revision rate costing 3000 basis
    points -- while the rolling variant stays perfect. Because the automatic cascade
    reads only the rolling variant and only ever degrades standing, the suspension
    the January revision caused survives the monitoring pass.

    PRD: "The lifetime variant applies no date filter at all — the window start is
    the beginning of time — and persists its answer to
    `lifetime_performance_score_bps`, which is audit-only and never moves anyone's
    standing."

    Design: Difficulty/dual_variant_calc/appraiser_performance_rolling_12m_vs_lifetime_on_appraiser
    """
    env = _appraiser_across_two_windows(api)
    appraiser = fx.panel_review(
        api, env["appraiser"]["id"], "MONITOR",
        note="Quarterly panel monitoring pass.",
    )

    assert appraiser["lifetime_performance_score_bps"] == 7000
    assert (
        appraiser["performance_score_bps"]
        - appraiser["lifetime_performance_score_bps"]
    ) == 3000
    assert appraiser["panel_status"] == "SUSPENDED"
