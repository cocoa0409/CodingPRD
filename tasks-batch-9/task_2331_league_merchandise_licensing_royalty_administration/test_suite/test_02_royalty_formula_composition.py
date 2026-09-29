"""Money formulas whose composed pieces each have to be honoured separately.

These cover the pinned rounding order, the fee waiver's base, and the closeout soft cap.
"""

from test_helpers import *  # noqa: F401,F403


# ---------------------------------------------------------------------------
# Rounding order: each line rounded, then the lines summed
# ---------------------------------------------------------------------------


def _two_channel_operation():
    """One agreement with two authorized retail accounts on two channel classes."""
    context = setup_licensed_operation(retailer_name="Metro Sports", channel_class="DEPARTMENT")
    context["specialty_authorization"] = create_authorized_retailer_authorization(
        context["licensee"]["id"],
        retailer_name="Court Specialty",
        channel_class="SPECIALTY",
    )
    return context


def _two_line_report_filed(context, gross_per_line: int):
    lines = [
        channel_line(
            context["authorization"]["id"], gross_per_line, units=2000, channel_class="DEPARTMENT"
        ),
        channel_line(
            context["specialty_authorization"]["id"],
            gross_per_line,
            units=2000,
            channel_class="SPECIALTY",
        ),
    ]
    licensee_id = context["licensee"]["id"]
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    return file_report(report["id"], licensee_id)


def test_each_line_is_rounded_before_the_lines_are_summed(api):
    """PRD §3.7: "Rounding the report total instead of rounding each line is wrong and
    can differ from the correct answer by one cent per line."

    Design: Difficulty/combinatorial_formula/royalty_rounding_pinned_per_line_then_summed
    """
    context = _two_channel_operation()
    report = _two_line_report_filed(context, 2500005)

    assert report["status"] == "FILED"
    assert report["net_regular_total_cents"] == 5000010
    assert report["closeout_eligible_total_cents"] == 0
    # 5 000 010 sits above the 5 000 000 boundary, so the unbounded top tier governs.
    assert report["applied_tier_rate_bps"] == 800
    # Each line is 200 000.4 rounded half up to 200 000; rounding the total would give 400 001.
    assert report["royalty_due_cents"] == 400000
    assert report["royalty_due_cents"] != 400001


def test_the_payable_waterfall_runs_on_the_per_line_royalty(api):
    """PRD §3.7: "Step six sets `total_payable_cents` to `cash_due_pre_fee_cents` plus
    `late_filing_interest_cents` plus `admin_fee_cents`, with no further rounding applied
    to that sum."

    Design: Difficulty/combinatorial_formula/royalty_rounding_pinned_per_line_then_summed
    """
    context = _two_channel_operation()
    report = _two_line_report_filed(context, 2500005)

    # The whole 250 000 advance is still unrecouped and the cap is the full 10000 bps.
    assert report["recoupment_applied_cents"] == 250000
    assert report["cash_due_pre_fee_cents"] == 150000
    assert report["late_days"] == 0
    assert report["late_filing_interest_cents"] == 0
    assert report["admin_fee_cents"] == 0
    assert report["total_payable_cents"] == 150000
    assert_payable_total(report)

    # Filing stores the six values but leaves the ledger completely untouched.
    agreement = get_agreement(context["agreement"]["id"])
    assert agreement["unrecouped_advance_cents"] == 250000
    assert agreement["recouped_advance_cents"] == 0
    assert agreement["cumulative_royalty_cents"] == 0


# ---------------------------------------------------------------------------
# The administration fee waiver reads the pre-fee figure
# ---------------------------------------------------------------------------


def _single_line_report_filed(gross_sales_cents: int, context=None):
    context = context or setup_licensed_operation()
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(context["authorization"]["id"], gross_sales_cents, units=3000)
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    return context, file_report(report["id"], licensee_id)


def test_admin_fee_is_charged_when_the_pre_fee_cash_falls_below_the_threshold(api):
    """PRD §3.7: "The waiver test reads `cash_due_pre_fee_cents` and never the post-fee
    total; testing the waiver against the total would be self-referential and is wrong."

    Design: Difficulty/combinatorial_formula/admin_fee_waiver_pinned_on_pre_fee_base
    """
    _, report = _single_line_report_filed(3490000)

    assert report["net_regular_total_cents"] == 3490000
    assert report["applied_tier_rate_bps"] == 1000
    assert report["royalty_due_cents"] == 349000
    assert report["recoupment_applied_cents"] == 250000
    assert report["cash_due_pre_fee_cents"] == 99000
    assert report["admin_fee_cents"] == 1485
    assert report["total_payable_cents"] == 100485
    # The total is above the threshold, yet the fee was still charged.
    assert report["total_payable_cents"] > 100000


def test_admin_fee_is_waived_when_the_pre_fee_cash_reaches_the_threshold_exactly(api):
    """PRD §3.7: "`admin_fee_cents` is 0 when `cash_due_pre_fee_cents` is at least one
    hundred thousand cents — a thousand currency units — and otherwise is
    `cash_due_pre_fee_cents` multiplied by 150 basis points divided by 10000 and rounded
    half up."

    Design: Difficulty/combinatorial_formula/admin_fee_waiver_pinned_on_pre_fee_base
    """
    _, report = _single_line_report_filed(3500000)

    assert report["applied_tier_rate_bps"] == 1000
    assert report["royalty_due_cents"] == 350000
    assert report["recoupment_applied_cents"] == 250000
    assert report["cash_due_pre_fee_cents"] == 100000
    assert report["admin_fee_cents"] == 0
    assert report["total_payable_cents"] == 100000


# ---------------------------------------------------------------------------
# The closeout soft cap kink
# ---------------------------------------------------------------------------


def _closeout_report_filed(closeout_sales_cents: int):
    context = setup_licensed_operation(closeout_allowed=True)
    licensee_id = context["licensee"]["id"]
    lines = simple_report_lines(
        context["authorization"]["id"],
        4000000,
        units=8000,
        closeout_sales_cents=closeout_sales_cents,
    )
    report = create_report(context["agreement"]["id"], "2026Q2", lines, licensee_id)
    return file_report(report["id"], licensee_id)


def test_closeout_volume_above_the_soft_cap_stays_in_the_regular_basis(api):
    """PRD §3.7: "any closeout volume above that soft cap is a closeout excess that
    remains inside the regular basis and is rated at the regular tier rate rather than at
    the reduced closeout rate."

    Design: Difficulty/combinatorial_formula/closeout_cap_kink_royalty_flat_above_cap
    """
    report = _closeout_report_filed(800000)

    # The soft cap is 1500 bps of the line's gross: 600 000 of the 800 000 reported.
    assert report["closeout_eligible_total_cents"] == 600000
    assert report["net_regular_total_cents"] == 3400000
    assert report["applied_tier_rate_bps"] == 1000
    # 340 000 at the tier rate plus 30 000 at the reduced closeout rate.
    assert report["royalty_due_cents"] == 370000


def test_closeout_volume_exactly_at_the_soft_cap_gives_the_same_royalty(api):
    """PRD §3.7: "the closeout-eligible amount is the smaller of that line's
    `closeout_sales_cents` and the line's `gross_sales_cents` multiplied by the
    category's `closeout_cap_pct_bps` divided by 10000 and floored to a whole cent"

    Design: Difficulty/combinatorial_formula/closeout_cap_kink_royalty_flat_above_cap
    """
    report = _closeout_report_filed(600000)

    assert report["closeout_eligible_total_cents"] == 600000
    assert report["net_regular_total_cents"] == 3400000
    assert report["applied_tier_rate_bps"] == 1000
    assert report["royalty_due_cents"] == 370000


def test_closeout_volume_below_the_soft_cap_rates_less_at_the_reduced_rate(api):
    """PRD §3.7: "The line's net regular sales are then its `gross_sales_cents` minus its
    closeout-eligible amount minus its allowed deduction."

    Design: Difficulty/combinatorial_formula/closeout_cap_kink_royalty_flat_above_cap
    """
    report = _closeout_report_filed(400000)

    assert report["closeout_eligible_total_cents"] == 400000
    assert report["net_regular_total_cents"] == 3600000
    assert report["applied_tier_rate_bps"] == 1000
    # 360 000 at the tier rate plus 20 000 at the closeout rate.
    assert report["royalty_due_cents"] == 380000
