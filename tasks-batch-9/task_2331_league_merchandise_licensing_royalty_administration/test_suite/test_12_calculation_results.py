"""Single-answer arithmetic: the tier lookup, the two soft caps and the central pool basis."""

from test_helpers import *  # noqa: F401,F403


def test_one_plain_line_is_rated_at_the_first_tier(api):
    """PRD §3.7: "The line's net regular sales are then its `gross_sales_cents` minus its
    closeout-eligible amount minus its allowed deduction." And: "That entry's `rate_bps` is
    written to the report's `applied_tier_rate_bps` and is applied to every line."

    Design: Corner/calculations/royalty_single_line_first_tier_correct_result
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(context["authorization"]["id"], 1000000, units=4000)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)

    filed = file_report(report["id"], licensee_id)

    assert filed["status"] == "FILED"
    assert filed["net_regular_total_cents"] == 1000000
    assert filed["closeout_eligible_total_cents"] == 0
    # The basis sits inside the first band, which happens to carry the headline rate too.
    assert filed["applied_tier_rate_bps"] == 1200
    assert filed["royalty_due_cents"] == 120000
    assert filed["recoupment_applied_cents"] == 120000
    assert filed["cash_due_pre_fee_cents"] == 0
    assert filed["admin_fee_cents"] == 0
    assert filed["total_payable_cents"] == 0


def test_only_the_capped_share_of_a_claimed_deduction_reaches_the_basis(api):
    """PRD §3.7: "The allowed deduction is the smaller of that line's `deductions_cents` and
    the line's `gross_sales_cents` multiplied by the category's `deduction_cap_pct_bps` divided
    by 10000 and floored."

    Design: Corner/calculations/deduction_cap_constant_limits_the_allowed_deduction
    """
    context = setup_licensed_operation(central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    # 80 000 of 1 000 000 is 800 basis points: under the 2000 bps hard limit, so the
    # report stands, but over the 500 bps soft cap, so only 50 000 is allowed.
    lines = simple_report_lines(
        context["authorization"]["id"], 1000000, units=4000, deductions_cents=80000
    )
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)

    filed = file_report(report["id"], licensee_id)

    assert filed["status"] == "FILED"
    assert filed["net_regular_total_cents"] == 950000
    assert filed["applied_tier_rate_bps"] == 1200
    assert filed["royalty_due_cents"] == 114000
    # Subtracting the whole claim would have produced 110 400.
    assert filed["royalty_due_cents"] != 110400


def test_a_closeout_line_pays_two_rates_over_two_bases(api):
    """PRD §3.7: "For a line, the closeout-eligible amount is the smaller of that line's
    `closeout_sales_cents` and the line's `gross_sales_cents` multiplied by the category's
    `closeout_cap_pct_bps` divided by 10000 and floored to a whole cent; any closeout volume
    above that soft cap is a closeout excess that remains inside the regular basis and is rated
    at the regular tier rate rather than at the reduced closeout rate."

    Design: Corner/calculations/closeout_line_within_cap_rates_two_bases_at_two_rates
    """
    context = setup_licensed_operation(closeout_allowed=True, central_licensing_flag=False)
    licensee_id = context["licensee"]["id"]
    # 300 000 of closeout on a 1 000 000 gross: inside the 4000 bps hard limit, but only
    # 150 000 of it is inside the 1500 bps soft cap.
    lines = simple_report_lines(
        context["authorization"]["id"], 1000000, units=4000, closeout_sales_cents=300000
    )
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)

    filed = file_report(report["id"], licensee_id)

    assert filed["status"] == "FILED"
    assert filed["closeout_eligible_total_cents"] == 150000
    assert filed["net_regular_total_cents"] == 850000
    assert filed["applied_tier_rate_bps"] == 1200
    # 102 000 on the regular basis plus 7 500 on the eligible closeout.
    assert filed["royalty_due_cents"] == 109500
    # Neither 114 000 (one rate over 950 000) nor 117 000 (the reduced rate over the
    # whole 300 000 of closeout volume).
    assert filed["royalty_due_cents"] not in (114000, 117000)


def test_the_central_pool_ignores_an_accepted_non_central_report(api):
    """PRD §3.9: "The eligible report set is every royalty report whose `period_quarter` equals
    the run's `period_quarter`, whose `status` is `ACCEPTED`, `ADJUSTED` or `CLOSED`, and whose
    agreement has `central_licensing_flag` true; reports in `DRAFT`, `FILED`, `RETURNED` or
    `UNDER_AUDIT` are excluded, and a `FILED` or `RETURNED` one blocks the transition
    outright."

    Design: Corner/calculations/central_pool_counts_only_central_licensing_reports
    """
    create_club(club_code="ATL", market_name="Atlanta", revenue_share_units=100)
    category = create_jersey_category()
    run = create_distribution_run("2026Q2", league_admin_rate_bps=800)

    specs = (("Foxglove Apparel", True, 1000000, 120000), ("Granite Outfitters", False, 2500000, 250000))
    for index, spec in enumerate(specs):
        legal_name, central, gross_sales_cents, expected_royalty = spec
        licensee = create_active_licensee(
            legal_name=legal_name, contact_email="royalties%d@pool.example" % index
        )
        agreement_context = setup_active_agreement(
            category=category, licensee=licensee, central_licensing_flag=central
        )
        authorization = create_authorized_retailer_authorization(
            licensee["id"], retailer_name="Metro Sports %d" % index
        )
        lines = simple_report_lines(authorization["id"], gross_sales_cents, units=5000)
        report = create_report(
            agreement_context["agreement"]["id"], "2026Q2", lines, licensee["id"]
        )
        file_report(report["id"], licensee["id"])
        accepted = accept_report(report["id"])
        assert accepted["royalty_due_cents"] == expected_royalty

    locked = lock_run(run["id"])
    # Only the central report was ever pooled.
    assert locked["projected_pool_cents"] == 120000
    assert locked["report_count"] == 1

    distributed = distribute_run(locked["id"])
    assert distributed["status"] == "DISTRIBUTED"
    assert distributed["report_count"] == 1
    assert distributed["pool_gross_cents"] == 120000
    assert distributed["league_admin_cents"] == 9600
    assert distributed["player_pool_cents"] == 30000
    assert distributed["club_pool_cents"] == 80400

    rows, meta = validate_paginated(list_club_distributions({"run_id": run["id"]}))
    assert meta["total_count"] == 1
    row = rows[0]
    assert row["club_code"] == "ATL"
    assert row["equal_component_cents"] == 60300
    assert row["weighted_component_cents"] == 20100
    assert row["remainder_cent_applied"] == 0
    assert row["amount_cents"] == 80400
    assert_distribution_pool_conserved(distributed, rows)
