"""
Calculations: pinned arithmetic, eligibility filtering, thresholds and tiered pricing.

The receipt battery is driven over a report that is complete on every component so the
weighted blend lands on a round 10000, and again over a report whose components each
round before weighting so that the blend lands on a half cent that must round up. A row
excluded from the grid is shown to keep its own ratios while moving no roll-up at all.
The distance ceiling is driven from both sides of the market-type constant, the bias
index is driven onto and one point below its indicated bound, escalation pricing is
driven into the top discount tier that only the post-surcharge subtotal reaches, and the
reconsideration evidence clauses are driven one clause at a time in their pinned order.
"""

from test_helpers import (
    COMPLIANCE_HEADERS,
    DESK_REVIEWER_HEADERS,
    assert_instant,
    fixtures as fx,
    validate_paginated,
)


def _author(license_number):
    return {
        "full_name": "Alice Author",
        "license_number": license_number,
        "license_state": "CA",
    }


def _reviewer(license_number):
    return {
        "full_name": "Bruno Backup",
        "license_number": license_number,
        "license_state": "CA",
    }


def _grid(street):
    """Three closed sales, each adjusted by one percent of its own sale price."""
    return [
        {
            "street_address": "1 %s" % street,
            "sale_price_cents": 39000000,
            "gross_adjustment_cents": 390000,
            "net_adjustment_cents": 390000,
            "distance_miles": 1.0,
            "sale_date": "2026-05-01T00:00:00Z",
        },
        {
            "street_address": "2 %s" % street,
            "sale_price_cents": 40000000,
            "gross_adjustment_cents": 400000,
            "net_adjustment_cents": 0,
            "distance_miles": 1.5,
            "sale_date": "2026-06-01T00:00:00Z",
        },
        {
            "street_address": "3 %s" % street,
            "sale_price_cents": 41000000,
            "gross_adjustment_cents": 410000,
            "net_adjustment_cents": -410000,
            "distance_miles": 2.0,
            "sale_date": "2026-06-15T00:00:00Z",
        },
    ]


def _complete_report(api):
    """A report complete on all three completeness components, graded once."""
    return fx.graded_report(
        api,
        amc={"name": "Complete Report AMC"},
        appraiser=_author("CA-AL-C201"),
        loan={"loan_number": "LN-2747-C201", "borrower_display_name": "Sami Borrower"},
        comparables=_grid("Alder Street"),
    )


def test_a_report_complete_on_every_component_scores_a_full_ten_thousand(api):
    """All three completeness components cap out, so the weighted blend is exact.

    Eight of eight required sections, three closed in-grid comparables against a
    three-comparable target and seven exhibits against a seven-exhibit target each
    produce a component of 10000, and a blend of three identical components is that
    same figure whatever the weights. The reconciled value follows the per-comparable
    rounding order and the first grading run seeds the value of record.

    PRD: "Count how many of those eight required sections appear in `sections_present`,
    multiply that count by 10000, divide by 8, and round half-up: that is the section
    component in basis points. The comparable component takes the lesser of
    `closed_comp_count` and the three-closed-comparable target, multiplies by 10000,
    divides by 3, and rounds half-up — so three or more closed in-grid comparables score
    a full 10000 and there is no credit beyond three. The exhibit component takes the
    lesser of `exhibit_count` and the seven-exhibit target, multiplies by 10000, divides
    by 7, and rounds half-up — again capped, so an eighth photograph earns nothing."

    PRD: "Each accepted run increments the appraisal's `version` by 1, and the very first
    run on an appraisal also seeds `current_value_cents` from `reported_value_cents`,
    establishing the baseline that every later value revision moves off."

    Design: Corner/calculations/correct_result_completeness_score_on_a_complete_report
    """
    appraisal = _complete_report(api)["appraisal"]

    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["eligible_comp_count"] == 3
    assert appraisal["closed_comp_count"] == 3
    assert appraisal["max_gross_adjustment_bps"] == 100
    assert appraisal["max_net_adjustment_bps"] == 100
    assert appraisal["indicated_value_cents"] == 39993333
    assert appraisal["variance_vs_reported_bps"] == 2
    assert appraisal["rule_check_fail_count"] == 0
    assert appraisal["rule_check_warn_count"] == 0
    assert appraisal["review_status"] == "RULES_CLEARED"
    assert appraisal["current_value_cents"] == 40000000


def test_the_clean_battery_writes_eight_passing_rows_with_their_metrics(api):
    """Every position passes, and three of them report the figure that decided them.

    The listing returns the whole battery in its declared sequence with no failures and
    no warnings. The closed count is reported as the count itself, the distance as the
    greatest eligible distance to two decimals, and the age as the greatest whole number
    of days from a comparable's sale date to the report's effective date.

    PRD: "The observed value is the greatest `distance_miles` among eligible comparables,
    or the string `0.00` when there are none."

    PRD: "A comparable's age in days is the whole number of days from its `sale_date` to
    the parent appraisal's `effective_date`. The observed value is the greatest such age
    among eligible comparables, or the string `0` when there are none."

    Design: Corner/calculations/correct_result_completeness_score_on_a_complete_report
    """
    env = _complete_report(api)
    rows, meta = validate_paginated(
        api.list_rule_checks(
            env["appraisal"]["id"], DESK_REVIEWER_HEADERS, {"limit": 100}
        )
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
    assert [row["outcome"] for row in rows] == ["PASS"] * 8

    by_code = {row["check_code"]: row for row in rows}
    assert by_code["CHK_COMP_COUNT"]["observed_value"] == "3"
    assert by_code["CHK_COMP_DISTANCE"]["observed_value"] == "2.00"
    assert by_code["CHK_COMP_AGE"]["observed_value"] == "75"
    assert by_code["CHK_FORM_TYPE"]["observed_value"] == "FORM_1004"


def _report_with_an_excluded_row(api):
    """A clean three-row grid plus one row explicitly kept out of the grid, whose every
    figure is extreme enough to move any roll-up that mistakenly counted it."""
    env = fx.delivered_report(
        api,
        amc={"name": "Filter AMC"},
        appraiser=_author("CA-AL-C202"),
        loan={"loan_number": "LN-2747-C202", "borrower_display_name": "Tor Borrower"},
        comparables=_grid("Alder Street"),
    )
    env["excluded"] = fx.add_comparable(
        api, env["appraisal"]["id"], env["amc"]["id"], "99 Excluded Street",
        sale_price_cents=30000000,
        gross_adjustment_cents=9000000,
        net_adjustment_cents=-9000000,
        distance_miles=9.0,
        sale_date="2026-06-01T00:00:00Z",
        sale_status="PENDING",
        dwelling_type="CONDO",
        census_tract_band="B",
        included_in_grid=False,
    )
    env["appraisal"] = fx.run_rule_checks(api, env["appraisal"]["id"])
    return env


def test_an_out_of_grid_row_keeps_its_own_ratios_and_moves_no_roll_up(api):
    """The excluded row is computed like any other and then ignored by everything.

    Its own three figures are written at filing from its own sale price and signed net
    adjustment, so it carries a thirty percent gross ratio, the same thirty percent net
    ratio taken from the absolute adjustment, and an adjusted price nine million cents
    below its sale price. None of that reaches the parent: the counts, the completeness
    blend, both maxima and the reconciliation all read exactly as they would on the
    three-row grid alone.

    PRD: "Rows excluded from the grid are ignored by all eight checks — they keep their
    own per-row ratio fields but never move a roll-up."

    PRD: "The `net_adjustment_bps` is computed the same way but from the **absolute
    value** of the net adjustment, so a comparable adjusted downward by the same
    magnitude as one adjusted upward carries the same net-adjustment ratio."

    Design: Corner/calculations/input_set_filtering_out_of_grid_comparable_never_moves_the_metrics
    """
    env = _report_with_an_excluded_row(api)
    excluded = env["excluded"]

    assert excluded["included_in_grid"] is False
    assert excluded["gross_adjustment_bps"] == 3000
    assert excluded["net_adjustment_bps"] == 3000
    assert excluded["adjusted_price_cents"] == 21000000

    appraisal = env["appraisal"]
    assert appraisal["eligible_comp_count"] == 3
    assert appraisal["closed_comp_count"] == 3
    assert appraisal["completeness_score_bps"] == 10000
    assert appraisal["max_gross_adjustment_bps"] == 100
    assert appraisal["max_net_adjustment_bps"] == 100
    assert appraisal["indicated_value_cents"] == 39993333
    assert appraisal["variance_vs_reported_bps"] == 2
    assert appraisal["rule_check_fail_count"] == 0
    assert appraisal["rule_check_warn_count"] == 0
    assert appraisal["review_status"] == "RULES_CLEARED"


def test_the_selection_channel_also_ignores_the_out_of_grid_row(api):
    """Band skew counts off-band rows only among eligible ones, so it stays at zero.

    The excluded row is the only one whose census tract band differs from the subject's,
    and it is not eligible, so the off-band count is zero out of three and the selection
    channel contributes nothing. With a benign narrative the index is zero and the
    compliance dimension clears. The nine-mile distance is likewise invisible to the
    distance check, which still reports the two-mile grid maximum.

    PRD: "The **comparable-selection channel** measures band skew: among eligible
    comparables — those with `included_in_grid` true — count how many carry a
    `census_tract_band` different from the appraisal's own `subject_census_tract_band`,
    multiply that off-band count by 10000, divide by the number of eligible comparables,
    and round half-up to whole basis points."

    Design: Corner/calculations/input_set_filtering_out_of_grid_comparable_never_moves_the_metrics
    """
    env = _report_with_an_excluded_row(api)
    screened = fx.run_bias_screen(api, env["appraisal"]["id"])

    assert screened["bias_risk_index"] == 0
    assert screened["bias_screen_status"] == "CLEAR"

    flags, meta = validate_paginated(
        api.list_bias_flags(env["appraisal"]["id"], COMPLIANCE_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 0
    assert flags == []

    by_code = {
        row["check_code"]: row
        for row in fx.list_rule_checks(api, env["appraisal"]["id"])
    }
    assert by_code["CHK_COMP_DISTANCE"]["outcome"] == "PASS"
    assert by_code["CHK_COMP_DISTANCE"]["observed_value"] == "2.00"


def _one_grid_two_market_types(api):
    """One appraiser delivers the same three-row grid against an urban loan and a
    suburban loan, so the only difference between the two reports is the ceiling."""
    amc = fx.create_amc(api, name="Ceiling AMC")
    appraiser = fx.create_appraiser(api, **_author("CA-AL-C203"))
    fx.enroll_on_panel(api, appraiser["id"], amc["id"])

    urban_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C203U", market_type="URBAN",
        borrower_display_name="Uma Borrower",
    )
    suburban_loan = fx.create_loan_file(
        api, loan_number="LN-2747-C203S", borrower_display_name="Sven Borrower",
    )
    urban = fx.deliver_appraisal(api, urban_loan["id"], appraiser["id"], amc["id"])
    suburban = fx.deliver_appraisal(
        api, suburban_loan["id"], appraiser["id"], amc["id"]
    )
    fx.add_comparables(api, urban["id"], amc["id"], _grid("Alder Street"))
    fx.add_comparables(api, suburban["id"], amc["id"], _grid("Alder Street"))
    return {
        "amc": amc,
        "appraiser": appraiser,
        "urban": fx.run_rule_checks(api, urban["id"]),
        "suburban": fx.run_rule_checks(api, suburban["id"]),
    }


def test_the_same_grid_warns_on_an_urban_ceiling_and_passes_on_a_suburban_one(api):
    """Identical distances, two ceilings, two different outcomes.

    A two-mile comparable is strictly greater than the one-mile urban ceiling but not
    greater than twice it, so the urban report warns; the same row is inside the
    three-mile suburban ceiling, so the suburban report passes. The warning does not
    block, and every other metric is identical across the two reports, which is what
    shows the market type reaching only the distance check.

    PRD: "The distance ceiling is selected by the loan file's `market_type`: 1.00 mile
    for `URBAN`, 3.00 miles for `SUBURBAN`, and 5.00 miles for `RURAL`."

    PRD: "Warnings alone never block — a run with zero failures and any number of
    warnings still clears, which is why a `RULES_CLEARED` appraisal can still carry a
    non-zero warn count into the desk-review scoring."

    Design: Corner/calculations/constants_applied_distance_ceiling_differs_by_market_type
    """
    env = _one_grid_two_market_types(api)

    urban_rows = {
        row["check_code"]: row for row in fx.list_rule_checks(api, env["urban"]["id"])
    }
    assert urban_rows["CHK_COMP_DISTANCE"]["outcome"] == "WARN"
    assert urban_rows["CHK_COMP_DISTANCE"]["observed_value"] == "2.00"
    assert env["urban"]["rule_check_fail_count"] == 0
    assert env["urban"]["rule_check_warn_count"] == 1
    assert env["urban"]["review_status"] == "RULES_CLEARED"

    suburban_rows = {
        row["check_code"]: row
        for row in fx.list_rule_checks(api, env["suburban"]["id"])
    }
    assert suburban_rows["CHK_COMP_DISTANCE"]["outcome"] == "PASS"
    assert suburban_rows["CHK_COMP_DISTANCE"]["observed_value"] == "2.00"
    assert env["suburban"]["rule_check_warn_count"] == 0
    assert env["suburban"]["review_status"] == "RULES_CLEARED"

    assert env["urban"]["completeness_score_bps"] == 10000
    assert env["suburban"]["completeness_score_bps"] == 10000
    assert env["urban"]["indicated_value_cents"] == 39993333
    assert env["suburban"]["indicated_value_cents"] == 39993333


def test_a_row_past_twice_the_urban_ceiling_turns_the_warning_into_a_failure(api):
    """Half a mile further and the same check fails, flagging the report.

    A fourth comparable at two and a half miles is strictly greater than twice the
    one-mile urban ceiling, so the re-run reports the new grid maximum and fails. The
    failure is what moves the report out of cleared, while the completeness blend is
    unchanged because the comparable component was already capped at three.

    PRD: "The outcome is `FAIL` when any eligible comparable's distance is strictly
    greater than twice the ceiling; `WARN` when no comparable breaches twice the ceiling
    but at least one is strictly greater than the ceiling itself; and `PASS` otherwise,
    including when the eligible set is empty."

    PRD: "The run then lands the review dimension: the appraisal moves to
    `RULES_CLEARED` when the fail count is zero, and to `RULES_FLAGGED` otherwise."

    Design: Corner/calculations/constants_applied_distance_ceiling_differs_by_market_type
    """
    env = _one_grid_two_market_types(api)
    fx.add_comparable(
        api, env["urban"]["id"], env["amc"]["id"], "4 Alder Street",
        sale_price_cents=40500000,
        gross_adjustment_cents=405000,
        net_adjustment_cents=0,
        distance_miles=2.5,
        sale_date="2026-06-20T00:00:00Z",
    )
    rerun = fx.run_rule_checks(api, env["urban"]["id"])

    by_code = {row["check_code"]: row for row in fx.list_rule_checks(api, rerun["id"])}
    assert by_code["CHK_COMP_DISTANCE"]["outcome"] == "FAIL"
    assert by_code["CHK_COMP_DISTANCE"]["observed_value"] == "2.50"
    assert rerun["rule_check_fail_count"] == 1
    assert rerun["review_status"] == "RULES_FLAGGED"
    assert rerun["eligible_comp_count"] == 4
    assert rerun["completeness_score_bps"] == 10000


# Two of the four rows sit outside the subject's own census tract band, so exactly half
# the eligible grid is off-band.
HALF_OFF_BAND_GRID = [
    {
        "street_address": "1 Holly Street",
        "sale_price_cents": 39000000,
        "gross_adjustment_cents": 390000,
        "net_adjustment_cents": 390000,
        "distance_miles": 1.0,
        "sale_date": "2026-05-01T00:00:00Z",
    },
    {
        "street_address": "2 Holly Street",
        "sale_price_cents": 40000000,
        "gross_adjustment_cents": 400000,
        "net_adjustment_cents": 0,
        "distance_miles": 1.5,
        "sale_date": "2026-06-01T00:00:00Z",
    },
    {
        "street_address": "3 Holly Street",
        "sale_price_cents": 41000000,
        "gross_adjustment_cents": 410000,
        "net_adjustment_cents": -410000,
        "distance_miles": 2.0,
        "sale_date": "2026-06-15T00:00:00Z",
        "census_tract_band": "B",
    },
    {
        "street_address": "4 Holly Street",
        "sale_price_cents": 40500000,
        "gross_adjustment_cents": 405000,
        "net_adjustment_cents": 0,
        "distance_miles": 2.5,
        "sale_date": "2026-06-20T00:00:00Z",
        "census_tract_band": "B",
    },
]


def test_an_index_of_exactly_twenty_five_indicates(api):
    """A half off-band grid scores the threshold itself, and the threshold indicates.

    Two of four eligible comparables carry a band other than the subject's, which is a
    skew of 5000 basis points and a selection contribution of exactly 25. The narrative
    is benign so nothing is added to it, and the test against the threshold is
    inclusive, so the index comes to rest on the bound and still indicates. One
    selection flag is written and no narrative flag is, and the screen leaves the review
    dimension exactly where delivery left it.

    PRD: "The selection channel contributes the skew in basis points divided by 200 and
    rounded half-up — so a grid where every single comparable is off-band, a skew of
    10000 basis points, contributes 50 points, and a grid where exactly half are off-band
    contributes 25."

    PRD: "The screen then lands the compliance dimension: `bias_screen_status` becomes
    `INDICATED` when the index is 25 or higher, and `CLEAR` when it is below 25."

    PRD: "Then, and only when the band skew is at least 5000 basis points, comes a single
    selection flag with `source` `COMP_SELECTION`, `indicator_code` `COMP_BAND_SKEW`, a
    null `matched_text`, and a `severity_weight` equal to the skew in basis points
    divided by 200 and rounded half-up."

    Design: Corner/calculations/threshold_bias_index_exactly_on_the_indicated_bound
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Skew Bound AMC"},
        appraiser=_author("CA-AL-C204"),
        loan={"loan_number": "LN-2747-C204", "borrower_display_name": "Vera Borrower"},
        comparables=HALF_OFF_BAND_GRID,
    )
    screened = fx.run_bias_screen(api, env["appraisal"]["id"])

    assert screened["eligible_comp_count"] == 4
    assert screened["bias_risk_index"] == 25
    assert screened["bias_screen_status"] == "INDICATED"
    assert screened["review_status"] == "RECEIVED"

    flags, meta = validate_paginated(
        api.list_bias_flags(env["appraisal"]["id"], COMPLIANCE_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 1
    flag = flags[0]
    assert flag["source"] == "COMP_SELECTION"
    assert flag["indicator_code"] == "COMP_BAND_SKEW"
    assert flag["severity_weight"] == 25
    assert flag["matched_text"] is None
    assert flag["status"] == "OPEN"


def test_an_index_of_twenty_four_clears_and_still_writes_its_flags(api):
    """One point below the bound the dimension clears, but the flags are still written.

    Two prohibited terms are twelve points each and the eligible grid is empty, so the
    selection channel contributes nothing and the index is 24 — one point short. The
    dimension therefore clears, yet both narrative flags exist, in the order the terms
    appear in the prohibited list, and no selection flag is written because a zero skew
    is below the flagging floor.

    PRD: "Flags are emitted in a fixed order, and a `CLEAR` outcome does not mean no
    flags — a single matched term scores only 12 and still writes a flag."

    PRD: "First come the narrative flags, one per matched term, ordered by that term's
    position in the prohibited list: each carries `source` `NARRATIVE`, an
    `indicator_code` of the form `TERM_` followed by the term's one-based position (so a
    hit on "crime-ridden" is `TERM_3`), a `matched_text` holding the prohibited term
    exactly as declared in the list, and a `severity_weight` of 12."

    Design: Corner/calculations/threshold_bias_index_one_step_below_the_indicated_bound
    """
    env = fx.delivered_report(
        api,
        amc={"name": "Below Bound AMC"},
        appraiser=_author("CA-AL-C205"),
        loan={"loan_number": "LN-2747-C205", "borrower_display_name": "Wes Borrower"},
        appraisal={
            "narrative_text": (
                "Subject sits in a desirable neighborhood with strong pride of ownership."
            ),
        },
        comparables=[],
    )
    screened = fx.run_bias_screen(api, env["appraisal"]["id"])

    assert screened["eligible_comp_count"] == 0
    assert screened["bias_risk_index"] == 24
    assert screened["bias_screen_status"] == "CLEAR"

    flags, meta = validate_paginated(
        api.list_bias_flags(env["appraisal"]["id"], COMPLIANCE_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 2
    assert [row["indicator_code"] for row in flags] == ["TERM_1", "TERM_2"]
    assert [row["matched_text"] for row in flags] == [
        "desirable neighborhood", "pride of ownership",
    ]
    for row in flags:
        assert row["source"] == "NARRATIVE"
        assert row["severity_weight"] == 12
        assert row["status"] == "OPEN"


# Prohibited terms at positions 1, 2 and 8, so the index is 36 and the bias override
# fires at escalation-requirement time.
BIASED_NARRATIVE = (
    "Subject sits in a desirable neighborhood with strong pride of ownership "
    "and a family-oriented character."
)


def _top_tier_order(api):
    """A second-appraisal order staffed with 71 hours of its turnaround left, so it is
    rush and its post-surcharge subtotal lands above the top tier floor."""
    env = fx.escalated_report(
        api,
        with_reviewer=True,
        amc={"name": "Top Tier AMC"},
        appraiser=_author("CA-AL-C206"),
        reviewer=_reviewer("CA-BR-C206"),
        loan={"loan_number": "LN-2747-C206", "borrower_display_name": "Xan Borrower"},
        appraisal={"narrative_text": BIASED_NARRATIVE},
        comparables=_grid("Alder Street"),
    )
    fx.set_clock(api, "2026-08-05T01:00:00Z")
    env["order"] = fx.assign_order(
        api, env["order"]["id"], env["reviewer"]["id"],
        "2026-08-06T09:00:00Z", "2026-08-06T12:00:00Z",
    )
    return env


def test_the_surcharge_carries_the_subtotal_into_the_top_discount_tier(api):
    """Only the post-surcharge subtotal is above the tier ceiling, and it decides.

    A bias indication makes this a second appraisal, whose base fee is 65000 and whose
    turnaround is a full week, and staffing it with 71 hours left is inside the rush
    window. Thirty percent of the base is 19500, and the resulting 84500 subtotal is
    strictly above the 80000 tier ceiling, so the top rate applies even though the bare
    base fee would have earned only the middle rate.

    PRD: "A rush order's `rush_surcharge_cents` is 30 percent of the base fee, rounded
    half-up to whole cents; a non-rush order's surcharge is 0."

    PRD: "Step three picks the volume discount tier from the **post-surcharge subtotal**,
    being base fee plus surcharge: a subtotal below 50000 cents earns `discount_pct_bps`
    of 0; a subtotal from 50000 cents up to and including 80000 cents earns 500 basis
    points; a subtotal above 80000 cents earns 1000 basis points."

    Design: Corner/calculations/tiered_pricing_second_appraisal_rush_enters_the_top_discount_tier
    """
    order = _top_tier_order(api)["order"]

    assert order["escalation_type"] == "SECOND_APPRAISAL"
    assert_instant(order["due_at"], "2026-08-08T00:00:00Z", "due_at")
    assert order["base_fee_cents"] == 65000
    assert order["rush_surcharge_cents"] == 19500
    assert order["discount_pct_bps"] == 1000
    assert order["total_cost_cents"] == 76050


def test_the_discounted_total_is_what_the_company_is_charged(api):
    """Steps four and five reach the ledger, not the subtotal.

    Ten percent of 84500 is 8450, so the order costs 76050, and that is exactly what is
    added to the company's year-to-date spend — comfortably inside the default budget, so
    the fiscal ceiling does not intervene. The named assignee takes the open assignment
    and the order is staffed.

    PRD: "Step four computes the discount in cents by multiplying the subtotal by the
    discount rate in basis points, dividing by 10000, and rounding half-up to whole
    cents. Step five sets `total_cost_cents` to the subtotal minus that discount."

    PRD: "A successful assignment writes all four cost fields, adds `total_cost_cents` to
    the management company's `ytd_escalation_spend_cents`, increments the assignee's
    `open_assignment_count`, and reserves the inspection window on that appraiser so it
    participates in future conflict checks."

    Design: Corner/calculations/tiered_pricing_second_appraisal_rush_enters_the_top_discount_tier
    """
    env = _top_tier_order(api)

    assert env["order"]["status"] == "ASSIGNED"
    assert env["order"]["assigned_appraiser_id"] == env["reviewer"]["id"]

    amc = fx.read_amc(api, env["amc"]["id"])
    assert amc["ytd_escalation_spend_cents"] == 76050
    assert amc["escalation_budget_cents"] == 500000
    assert fx.read_appraiser(api, env["reviewer"]["id"])["open_assignment_count"] == 1


def _two_row_report(api, name, license_number, loan_number, borrower, **appraisal):
    """A report carrying only two of the three closed comparables the target wants."""
    return fx.delivered_report(
        api,
        amc={"name": name},
        appraiser=_author(license_number),
        loan={"loan_number": loan_number, "borrower_display_name": borrower},
        appraisal=appraisal or None,
        comparables=_grid("Alder Street")[:2],
    )


def test_the_first_run_scores_a_short_grid_and_flags_the_count(api):
    """Two closed comparables cost the comparable component a third of its marks.

    The comparable component is two thirds of 10000 rounded half-up, which is 6667, and
    blending it against two full components gives 9000 — high enough for the completeness
    check itself to pass. The count check has no warning band, so a short grid fails
    outright and the report is flagged even though its score is comfortable.

    PRD: "The observed value is `closed_comp_count`. The outcome is `FAIL` when fewer than
    three in-grid comparables are in `CLOSED` sale status, and `PASS` otherwise. This
    check never yields `WARN`."

    Design: Corner/calculations/chronological_rule_check_battery_replaced_wholesale_on_rerun
    """
    env = _two_row_report(
        api, "Rerun AMC", "CA-AL-C207", "LN-2747-C207", "Yuki Borrower",
    )
    first = fx.run_rule_checks(api, env["appraisal"]["id"])

    assert first["closed_comp_count"] == 2
    assert first["completeness_score_bps"] == 9000
    assert first["indicated_value_cents"] == 39695000
    assert first["variance_vs_reported_bps"] == 76
    assert first["rule_check_fail_count"] == 1
    assert first["rule_check_warn_count"] == 0
    assert first["review_status"] == "RULES_FLAGGED"

    rows, meta = validate_paginated(
        api.list_rule_checks(first["id"], DESK_REVIEWER_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 8
    by_code = {row["check_code"]: row for row in rows}
    assert by_code["CHK_COMPLETENESS"]["outcome"] == "PASS"
    assert by_code["CHK_COMP_COUNT"]["outcome"] == "FAIL"
    assert by_code["CHK_COMP_COUNT"]["observed_value"] == "2"
    assert by_code["CHK_VALUE_RECONCILIATION"]["outcome"] == "PASS"


def test_a_second_run_replaces_the_battery_instead_of_appending_to_it(api):
    """The listing still holds eight rows, and they are the new generation.

    Correcting the grid and re-running rehabilitates the report: the count passes, the
    completeness blend reaches a full 10000 and the report clears. The listing returns
    eight rows rather than sixteen and their sequence numbers still run one through
    eight, so the first generation was discarded rather than kept alongside. The value of
    record is not re-seeded by the second run.

    PRD: "Every run emits **exactly eight** rule-check result rows, in one fixed emission
    order, and a re-run deletes the previous eight rows and writes a fresh eight — there
    is never a mixed generation on an appraisal."

    PRD: "Stated as edges, a first run produces either `RECEIVED → RULES_CLEARED` or
    `RECEIVED → RULES_FLAGGED`; a re-run that comes back with zero failures produces
    `RULES_CLEARED → RULES_CLEARED` or `RULES_FLAGGED → RULES_CLEARED`, the second of
    which is how a flagged report is rehabilitated after its grid is corrected."

    Design: Corner/calculations/chronological_rule_check_battery_replaced_wholesale_on_rerun
    """
    env = _two_row_report(
        api, "Rerun AMC", "CA-AL-C207", "LN-2747-C207", "Yuki Borrower",
    )
    first = fx.run_rule_checks(api, env["appraisal"]["id"])
    assert first["current_value_cents"] == 40000000

    fx.add_comparables(
        api, env["appraisal"]["id"], env["amc"]["id"], _grid("Alder Street")[2:],
    )
    second = fx.run_rule_checks(api, env["appraisal"]["id"])

    assert second["completeness_score_bps"] == 10000
    assert second["rule_check_fail_count"] == 0
    assert second["review_status"] == "RULES_CLEARED"
    assert second["indicated_value_cents"] == 39993333
    assert second["variance_vs_reported_bps"] == 2
    assert second["current_value_cents"] == 40000000

    rows, meta = validate_paginated(
        api.list_rule_checks(second["id"], DESK_REVIEWER_HEADERS, {"limit": 100})
    )
    assert meta["total_count"] == 8
    assert [row["sequence_no"] for row in rows] == [1, 2, 3, 4, 5, 6, 7, 8]
    by_code = {row["check_code"]: row for row in rows}
    assert by_code["CHK_COMP_COUNT"]["outcome"] == "PASS"
    assert by_code["CHK_COMP_COUNT"]["observed_value"] == "3"


def test_the_blend_rounds_its_components_first_and_the_sum_once(api):
    """A half-basis-point sum proves the rounding happens after the weighting.

    Eight sections score 10000, two closed comparables round to 6667 and two exhibits
    round to 2857. Weighting those rounded figures gives 5000 plus 2000.1 plus 571.4,
    which is 7571.5, and the single final half-up rounding takes it to 7572. Weighting the
    unrounded components instead would land a basis point lower.

    PRD: "The three components are then weighted: half the weight, 0.50, on sections;
    three-tenths, 0.30, on comparables; and two-tenths, 0.20, on exhibits. Multiply each
    rounded component by its weight, add the three products, and round the sum half-up
    once more; the result is `completeness_score_bps`. Weighting the *unrounded*
    components is forbidden — the per-component rounding happens first, then the
    weighting, then a single final rounding."

    PRD: "The check outcome reads that score: `FAIL` when the score is below 6000 basis
    points, `WARN` when the score is at least 6000 but still below 8500, and `PASS` when
    the score is 8500 or higher."

    Design: Corner/calculations/weighted_scoring_components_rounded_before_weighting
    """
    env = _two_row_report(
        api, "Rounding AMC", "CA-AL-C208", "LN-2747-C208", "Zoe Borrower",
        exhibit_count=2,
    )
    graded = fx.run_rule_checks(api, env["appraisal"]["id"])

    assert graded["completeness_score_bps"] == 7572
    assert graded["completeness_score_bps"] != 7571
    assert graded["rule_check_fail_count"] == 1
    assert graded["rule_check_warn_count"] == 1
    assert graded["review_status"] == "RULES_FLAGGED"
    assert graded["indicated_value_cents"] == 39695000

    by_code = {row["check_code"]: row for row in fx.list_rule_checks(api, graded["id"])}
    assert by_code["CHK_COMPLETENESS"]["outcome"] == "WARN"
    assert by_code["CHK_COMPLETENESS"]["observed_value"] == "7572"
    assert by_code["CHK_COMP_COUNT"]["outcome"] == "FAIL"
    assert by_code["CHK_VALUE_RECONCILIATION"]["outcome"] == "PASS"


def _contested_report(api):
    """A graded report with a reconsideration request open in intake against it."""
    env = fx.graded_report(
        api,
        amc={"name": "Evidence AMC"},
        appraiser=_author("CA-AL-C209"),
        loan={"loan_number": "LN-2747-C209", "borrower_display_name": "Ada Borrower"},
        comparables=_grid("Alder Street"),
    )
    env["rov"] = fx.open_rov(
        api, env["loan"]["id"], env["appraisal"]["id"],
        requested_value_cents=40600000,
        borrower_statement="Two better sales were omitted from the grid.",
    )
    return env


def test_the_type_clause_and_the_attribute_clause_fire_before_anything_else(api):
    """An opinion is refused on its type alone, and a gap is refused before any metric.

    The opinion carries a price, a date and a distance that would all survive the later
    clauses, and it is still inadmissible on the first clause. A closed sale missing only
    its distance stops on the second clause rather than reaching the third, and a data
    error citation without its note stops there too — the attribute clause applies to
    every type, it is only the attributes it demands that differ. All three are accepted
    as filings and simply carry the verdict.

    PRD: "Clause one: an `OPINION_STATEMENT` is never admissible, and yields
    `TYPE_NOT_ADMISSIBLE`."

    PRD: "Clause two checks required attributes by type — a `CLOSED_SALE` and an
    `ACTIVE_LISTING_WITH_CONTRACT` each require all three of `sale_price_cents`,
    `sale_date`, and `distance_miles`, while a `DATA_ERROR_CITATION` requires a
    `citation_note` — and a missing attribute yields `MISSING_REQUIRED_ATTRIBUTE`."

    Design: Corner/calculations/constraint_propagation_evidence_admissibility_clause_order
    """
    env = _contested_report(api)
    rov_id = env["rov"]["id"]

    opinion = fx.file_evidence(
        api, rov_id, "OPINION_STATEMENT",
        street_address="10 Birch Street",
        sale_price_cents=41000000,
        sale_date="2026-06-20T00:00:00Z",
        distance_miles=0.5,
        citation_note="Neighbour says the house is worth more.",
    )
    assert opinion["admissible"] is False
    assert opinion["inadmissible_reason"] == "TYPE_NOT_ADMISSIBLE"

    no_distance = fx.file_evidence(
        api, rov_id, "CLOSED_SALE",
        drop=("distance_miles",),
        street_address="11 Birch Street",
        sale_price_cents=41000000,
        sale_date="2026-06-20T00:00:00Z",
    )
    assert no_distance["admissible"] is False
    assert no_distance["inadmissible_reason"] == "MISSING_REQUIRED_ATTRIBUTE"

    no_note = fx.file_evidence(
        api, rov_id, "DATA_ERROR_CITATION",
        drop=("citation_note",),
        street_address="15 Birch Street",
    )
    assert no_note["admissible"] is False
    assert no_note["inadmissible_reason"] == "MISSING_REQUIRED_ATTRIBUTE"

    assert fx.read_rov_request(api, rov_id)["admissible_evidence_count"] == 0


def test_staleness_is_tested_before_distance_and_distance_before_duplication(api):
    """Each of the three sale-like clauses is reached only when its predecessors pass.

    A sale a year and two weeks before the effective date stops on staleness even though
    its distance is fine. A listing three and a half miles out stops on distance, which it
    only reaches because its date is fresh. And a fresh, close sale whose address is the
    grid's own first comparable — differing only in case and in runs of whitespace — stops
    on the redundancy clause, which is last.

    PRD: "Clause three applies only to the two sale-like types: when the whole number of
    days from the item's `sale_date` to the contested appraisal's `effective_date` exceeds
    365, the reason is `STALE_SALE_DATE`."

    PRD: "Clause four also applies only to the two sale-like types: when `distance_miles`
    is strictly greater than the ceiling selected by the loan file's `market_type` — 1.00
    mile urban, 3.00 miles suburban, 5.00 miles rural — the reason is
    `DISTANCE_EXCEEDED`."

    PRD: "Clause five catches redundancy: when the item's `street_address`, compared
    case-folded with whitespace runs collapsed, already appears on a comparable of the
    contested appraisal that has `included_in_grid` true, the reason is
    `DUPLICATE_OF_GRID_COMP`."

    Design: Corner/calculations/constraint_propagation_evidence_admissibility_clause_order
    """
    env = _contested_report(api)
    rov_id = env["rov"]["id"]

    stale = fx.file_evidence(
        api, rov_id, "CLOSED_SALE",
        street_address="12 Birch Street",
        sale_price_cents=41000000,
        sale_date="2025-07-01T00:00:00Z",
        distance_miles=0.5,
    )
    assert stale["inadmissible_reason"] == "STALE_SALE_DATE"

    far = fx.file_evidence(
        api, rov_id, "ACTIVE_LISTING_WITH_CONTRACT",
        street_address="13 Birch Street",
        sale_price_cents=41500000,
        sale_date="2026-06-25T00:00:00Z",
        distance_miles=3.5,
    )
    assert far["inadmissible_reason"] == "DISTANCE_EXCEEDED"

    duplicate = fx.file_evidence(
        api, rov_id, "CLOSED_SALE",
        street_address="  1   alder   street  ",
        sale_price_cents=39000000,
        sale_date="2026-05-01T00:00:00Z",
        distance_miles=1.0,
    )
    assert duplicate["inadmissible_reason"] == "DUPLICATE_OF_GRID_COMP"

    for item in (stale, far, duplicate):
        assert item["admissible"] is False
        assert item["round_number"] == 1
        assert item["rov_request_id"] == rov_id
    assert fx.read_rov_request(api, rov_id)["admissible_evidence_count"] == 0


def test_a_citation_skips_the_sale_clauses_and_routes_at_the_floor(api):
    """A data error citation survives figures that would sink a sale, and two is enough.

    The citation carries a 2024 date, a nine-mile distance and a price well below the
    grid, and none of that is consulted because its type skips the last three clauses. It
    and one ordinary closed sale are the only two admissible items on file, which is
    exactly the routing floor, so the reconsideration reaches the appraiser and its
    deadline is stamped five days out from the logical clock.

    PRD: "A `DATA_ERROR_CITATION` skips clauses three, four, and five entirely — it has no
    sale date, no distance, and no address to collide. An item that survives all
    applicable clauses is marked admissible with a null `inadmissible_reason`."

    PRD: "Only admissible items filed **in the request's current round** count toward
    `admissible_evidence_count`, and routing the reconsideration to the appraiser requires
    at least two of them."

    PRD: "Routing moves the request `INTAKE → AWAITING_APPRAISER` and stamps
    `response_deadline_at` as the logical clock plus 120 hours — five days for the
    appraiser to answer."

    Design: Corner/calculations/constraint_propagation_evidence_admissibility_clause_order
    """
    env = _contested_report(api)
    rov_id = env["rov"]["id"]

    citation = fx.file_evidence(
        api, rov_id, "DATA_ERROR_CITATION",
        street_address="14 Birch Street",
        sale_price_cents=30000000,
        sale_date="2024-01-01T00:00:00Z",
        distance_miles=9.0,
        citation_note="Public record shows 2400 sq ft, the report used 1900.",
    )
    assert citation["admissible"] is True
    assert citation["inadmissible_reason"] is None

    sale = fx.file_evidence(
        api, rov_id, "CLOSED_SALE",
        street_address="16 Birch Street",
        sale_price_cents=40800000,
        sale_date="2026-06-10T00:00:00Z",
        distance_miles=1.2,
    )
    assert sale["admissible"] is True
    assert sale["inadmissible_reason"] is None

    assert fx.read_rov_request(api, rov_id)["admissible_evidence_count"] == 2

    routed = fx.route_rov(api, rov_id, intake_note="Two admissible sales on file.")
    assert routed["status"] == "AWAITING_APPRAISER"
    assert routed["round_number"] == 1
    assert_instant(
        routed["response_deadline_at"], "2026-08-06T00:00:00Z", "response_deadline_at",
    )
    assert fx.read_appraisal(api, env["appraisal"]["id"])["review_status"] == (
        "VALUE_CONTESTED"
    )
