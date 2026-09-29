"""One-unit boundary probes on inclusive comparisons and on floor-versus-round choices."""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# The tier's lower bound is inclusive and its upper bound is not
# ---------------------------------------------------------------------------


def _reports_straddling_the_tier_boundary():
    """Two quarters one cent apart across the 5 000 000 tier boundary."""
    context = setup_licensed_operation(
        minimum_guarantee_cents=1000000, required_advance_cents=250000
    )
    licensee_id = context["licensee"]["id"]
    filed = {}
    for quarter, gross in (("2026Q1", 5000000), ("2026Q2", 4999999)):
        lines = simple_report_lines(context["authorization"]["id"], gross, units=10000)
        report = create_report(context["agreement"]["id"], quarter, lines, licensee_id)
        filed[quarter] = file_report(report["id"], licensee_id)
    context["at_boundary"] = filed["2026Q1"]
    context["below_boundary"] = filed["2026Q2"]
    return context


def test_a_basis_exactly_on_the_boundary_takes_the_higher_tier(api):
    """PRD §3.7: "the applicable tier is the single entry of the category's `tier_schedule`
    whose `from_cents` is at or below the basis and whose `to_cents` is either null — the
    unbounded top tier — or strictly above the basis."

    Design: Difficulty/boundary_precision_check/tier_lower_bound_is_inclusive_lower_basis_higher_royalty
    """
    context = _reports_straddling_the_tier_boundary()
    report = context["at_boundary"]

    assert report["status"] == "FILED"
    assert report["net_regular_total_cents"] == 5000000
    # 5 000 000 is at the top band's from_cents, so the 800 bps rate governs.
    assert report["applied_tier_rate_bps"] == 800
    assert report["royalty_due_cents"] == 400000
    assert report["recoupment_applied_cents"] == 250000


def test_one_cent_below_the_boundary_stays_in_the_lower_tier_and_pays_more(api):
    """PRD §3.7: "That entry's `rate_bps` is written to the report's
    `applied_tier_rate_bps` and is applied to every line."

    Design: Difficulty/boundary_precision_check/tier_lower_bound_is_inclusive_lower_basis_higher_royalty
    """
    context = _reports_straddling_the_tier_boundary()
    below = context["below_boundary"]

    assert below["status"] == "FILED"
    assert below["net_regular_total_cents"] == 4999999
    assert below["applied_tier_rate_bps"] == 1000
    assert below["royalty_due_cents"] == 500000
    assert below["recoupment_applied_cents"] == 250000
    # One cent less revenue costs 100 000 cents more royalty.
    assert below["royalty_due_cents"] > context["at_boundary"]["royalty_due_cents"]


# ---------------------------------------------------------------------------
# The cost-shift threshold is inclusive and the rate itself is floored
# ---------------------------------------------------------------------------


def _engagement_in_fieldwork():
    """A 2026Q2 quarter reported at 500 000 of royalty and pulled into audit."""
    context = setup_accepted_report(
        period_quarter="2026Q2",
        gross_sales_cents=6250000,
        units=12500,
        minimum_guarantee_cents=4000000,
        required_advance_cents=1000000,
    )
    assert context["report"]["royalty_due_cents"] == 500000
    engagement = create_audit_engagement(context["agreement"]["id"], ["2026Q2"])
    context["engagement"] = begin_fieldwork(engagement["id"])
    return context


def test_a_rate_of_exactly_five_hundred_basis_points_shifts_the_audit_cost(api):
    """PRD §3.8: "`cost_shift_applied` becomes true when `underreport_rate_bps` is at least
    500 basis points — the boundary is inclusive, so a rate of exactly 500 shifts the cost —
    and `audit_cost_recovery_cents` is then a flat seven hundred and fifty thousand cents,
    or zero when the cost does not shift."

    Design: Difficulty/boundary_precision_check/underreport_rate_cost_shift_threshold_inclusive_at_500_bps
    """
    context = _engagement_in_fieldwork()

    issued = issue_findings(
        context["engagement"]["id"], [audited_quarter("2026Q2", 6562500)]
    )

    assert issued["status"] == "FINDINGS_ISSUED"
    assert issued["findings_round"] == 1
    assert issued["recomputed_royalty_cents"] == 525000
    assert issued["reported_royalty_cents"] == 500000
    assert issued["underreported_royalty_cents"] == 25000
    # 25 000 * 10000 / 500 000 lands exactly on the threshold.
    assert issued["underreport_rate_bps"] == 500
    assert issued["cost_shift_applied"] is True
    assert issued["audit_cost_recovery_cents"] == 750000
    assert issued["interest_cents"] == 375
    assert issued["recovery_assessed_cents"] == 775375


def test_a_floored_rate_one_point_below_the_threshold_drops_the_cost_recovery(api):
    """PRD §3.8: "`underreport_rate_bps` is 0 when `reported_royalty_cents` is 0, and
    otherwise is `underreported_royalty_cents` multiplied by 10000 divided by
    `reported_royalty_cents` and floored."

    Design: Difficulty/boundary_precision_check/underreport_rate_cost_shift_threshold_inclusive_at_500_bps
    """
    context = _engagement_in_fieldwork()
    engagement_id = context["engagement"]["id"]

    issue_findings(engagement_id, [audited_quarter("2026Q2", 6562500)])
    disputed = dispute_engagement(
        engagement_id,
        context["licensee"]["id"],
        dispute_note="Returns credit memos were omitted from the restatement",
    )
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_note"] == "Returns credit memos were omitted from the restatement"
    assert get_report(context["report"]["id"])["status"] == "UNDER_AUDIT"

    reissued = issue_findings(engagement_id, [audited_quarter("2026Q2", 6561875)])

    assert reissued["status"] == "FINDINGS_ISSUED"
    assert reissued["findings_round"] == 2
    assert reissued["recomputed_royalty_cents"] == 524950
    assert reissued["underreported_royalty_cents"] == 24950
    # 24 950 * 10000 / 500 000 is 499.0, and flooring keeps it below the threshold.
    assert reissued["underreport_rate_bps"] == 499
    assert reissued["cost_shift_applied"] is False
    assert reissued["audit_cost_recovery_cents"] == 0
    assert reissued["interest_cents"] == 374
    # The whole block is overwritten rather than accumulated.
    assert reissued["recovery_assessed_cents"] == 25324

    assert get_agreement(context["agreement"]["id"])["cumulative_royalty_cents"] == 500000


# ---------------------------------------------------------------------------
# The administration-fee waiver floor across a return and a re-file
# ---------------------------------------------------------------------------


def _report_at_the_waiver_floor():
    """A 2026Q2 report whose pre-fee cash lands exactly on the waiver floor."""
    context = setup_licensed_operation(
        minimum_guarantee_cents=4000000, required_advance_cents=1000000
    )
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(context["authorization"]["id"], 13750000, units=27500)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    context["report"] = file_report(report["id"], licensee_id)
    return context


def test_pre_fee_cash_exactly_at_the_floor_waives_the_administration_fee(api):
    """PRD §3.7: "`admin_fee_cents` is 0 when `cash_due_pre_fee_cents` is at least one
    hundred thousand cents — a thousand currency units — and otherwise is
    `cash_due_pre_fee_cents` multiplied by 150 basis points divided by 10000 and rounded
    half up."

    Design: Difficulty/boundary_precision_check/admin_fee_waiver_floor_exact_boundary_across_refile
    """
    context = _report_at_the_waiver_floor()
    report = context["report"]

    assert report["royalty_due_cents"] == 1100000
    assert report["recoupment_applied_cents"] == 1000000
    assert report["cash_due_pre_fee_cents"] == 100000
    assert report["late_days"] == 0
    assert report["late_filing_interest_cents"] == 0
    assert report["admin_fee_cents"] == 0
    assert report["total_payable_cents"] == 100000
    assert get_agreement(context["agreement"]["id"])["unrecouped_advance_cents"] == 1000000


def test_one_cent_below_the_floor_attracts_the_rounded_fee_on_the_refile(api):
    """PRD §3.7: "A licensee may correct a `DRAFT` or `RETURNED` report by replacing its
    `channel_lines`. Correction is permitted only in those two states, clears every computed
    money field back to 0 until the next filing recomputes them, and increments the report's
    `version` by 1."

    Design: Difficulty/boundary_precision_check/admin_fee_waiver_floor_exact_boundary_across_refile
    """
    context = _report_at_the_waiver_floor()
    report_id = context["report"]["id"]
    licensee_id = context["licensee"]["id"]

    returned = return_report(report_id, reason="Restate one channel line")
    assert returned["status"] == "RETURNED"
    assert returned["return_count"] == 1

    corrected_lines = simple_report_lines(
        context["authorization"]["id"], 13749988, units=27499
    )
    corrected = validate_success(
        api.patch_royalty_report(
            report_id, {"channel_lines": corrected_lines}, make_licensee_headers(licensee_id)
        ),
        200,
    )
    assert corrected["royalty_due_cents"] == 0
    assert corrected["cash_due_pre_fee_cents"] == 0
    assert corrected["admin_fee_cents"] == 0
    assert corrected["total_payable_cents"] == 0

    refiled = file_report(report_id, licensee_id)
    assert refiled["royalty_due_cents"] == 1099999
    assert refiled["recoupment_applied_cents"] == 1000000
    assert refiled["cash_due_pre_fee_cents"] == 99999
    # 99 999 * 150 / 10000 is 1499.985, which rounds half up to 1500.
    assert refiled["admin_fee_cents"] == 1500
    assert refiled["total_payable_cents"] == 101499
    assert refiled["return_count"] == 1
    assert get_agreement(context["agreement"]["id"])["unrecouped_advance_cents"] == 1000000
