"""Multi-step money and scoring pipelines whose intermediate order is the point.

Three formulas are pinned here: the civil-money-penalty rounding order, the
equipment handling-fee threshold, and the three-component redemption anomaly
score with its small-format weights.
"""
from test_helpers import (
    ADMIN,
    advance_clock,
    api_client,
    assert_fields,
    assert_ledger_conservation,
    authorized_store,
    created,
    elect_cmp,
    file_reply,
    four_closed_periods,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    open_case,
    open_flagged_period,
    order_line,
    close_period,
    equipment_order_payload,
    refresh_case,
    refresh_investigation,
    refresh_owner,
    refresh_store,
    rows,
    substantiated_trafficking_investigation,
)


def _trafficking_case_charged_after_a_year():
    """An authorized store with four closed periods and a TRAFFICKING case whose
    charge letter issues 396 days after authorization, ready for determination."""
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_trafficking_investigation(context.store_id)
    case = open_case(investigation["id"], "TRAFFICKING")
    advance_clock("2027-09-01T00:00:00Z")
    case = issue_charge_letter(case["id"])
    elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    return context, investigation, case


def test_monthly_penalty_is_rounded_before_the_month_multiplier():
    """The ten-month trafficking multiplier is applied to an already-rounded
    monthly figure, so the penalty is 1,283,640c and not 1,283,642c.

    The specification pins the order explicitly: "the monthly ten-percent figure
    is rounded to whole cents before the multiplication by the month count", and
    "The month multiplier is 10 months flat for a `TRAFFICKING` case". Ten percent
    of the 1,283,642c average rounds to 128,364c, and ten of those are
    1,283,640c; rounding once at the end would have produced 1,283,642c instead.

    Design: Difficulty/combinatorial_formula/cmp_rounding_order_monthly_penalty_rounded_before_month_multiplier
    """
    context, investigation, case = _trafficking_case_charged_after_a_year()
    assert refresh_investigation(investigation["id"])["trafficking_confidence_score"] == 60

    issue_determination(case["id"], "CMP_IN_LIEU")

    case = refresh_case(case["id"])
    assert_fields(
        case,
        {
            "cmp_basis_variant": "TRAILING_12_PERIOD_AVERAGE",
            "avg_monthly_redemption_cents": 1283642,
            "monthly_penalty_cents": 128364,
            "cmp_amount_cents": 1283640,
            "cmp_capped": False,
        },
        "trafficking penalty",
    )
    assert case["cmp_amount_cents"] != 1283642, (
        "1,283,642c is the round-once-at-the-end figure; the specification rounds "
        "the monthly penalty first"
    )


def test_rounded_monthly_penalty_is_what_reaches_the_ledger_and_the_owner():
    """The two-cent difference produced by the rounding order is carried all the
    way through the ledger entry and the owner rollup, not just reported on the
    case.

    The specification makes the ledger the record of the assessed amount and the
    owner's `cmp_outstanding_cents` the sum of its cases' balances, so the same
    1,283,640c must appear at all three levels.

    Design: Difficulty/combinatorial_formula/cmp_rounding_order_monthly_penalty_rounded_before_month_multiplier
    """
    context, _investigation, case = _trafficking_case_charged_after_a_year()

    issue_determination(case["id"], "CMP_IN_LIEU")

    case = refresh_case(case["id"])
    entries = ledger_entries(case["id"])
    assert len(entries) == 1, f"expected exactly one ledger entry, got {entries}"
    assert_fields(
        entries[0],
        {"amount_cents": 1283640, "balance_after_cents": 1283640},
        "assessment entry",
    )
    assert_ledger_conservation(entries, case)
    assert refresh_owner(context.owner_id)["cmp_outstanding_cents"] == 1283640


def _draft_order(store_id, owner_headers, lines):
    return created(
        api_client.create_equipment_order(
            equipment_order_payload(store_id, lines=lines), owner_headers
        )
    )


def test_handling_fee_threshold_is_read_off_the_post_subsidy_net():
    """A six-case paper order with a signage pack nets exactly 24,000c and pays
    the handling fee, while a seven-case order nets 28,000c and pays nothing.

    The specification is explicit about which figure decides the fee:
    "`handling_fee_cents` is 0 when `net_equipment_cents` is 0, 0 when
    `net_equipment_cents` is at least $250.00, and $15.00 otherwise.", and "The
    threshold is read off `net_equipment_cents` and never off `total_due_cents`".
    The fee-paying order therefore settles at 25,500c, above the threshold its
    own net figure sits below.

    Design: Difficulty/combinatorial_formula/equipment_handling_fee_threshold_read_off_net_not_total
    """
    context = authorized_store()

    fee_order = _draft_order(
        context.store_id,
        context.owner_h,
        [order_line("RECEIPT_PAPER_CASE", 6), order_line("SIGNAGE_PACK", 1)],
    )
    assert_fields(
        fee_order,
        {
            "subtotal_cents": 26200,
            "subsidy_cents": 2200,
            "net_equipment_cents": 24000,
            "handling_fee_cents": 1500,
            "total_due_cents": 25500,
            "status": "DRAFT",
        },
        "fee-paying order",
    )

    free_order = _draft_order(
        context.store_id, context.owner_h, [order_line("RECEIPT_PAPER_CASE", 7)]
    )
    assert_fields(
        free_order,
        {
            "subtotal_cents": 28000,
            "subsidy_cents": 0,
            "net_equipment_cents": 28000,
            "handling_fee_cents": 0,
            "total_due_cents": 28000,
        },
        "free-handling order",
    )


def test_a_fully_subsidized_order_nets_zero_and_pays_no_fee():
    """A single EBT-only wireless terminal is subsidized in full, so the net is
    zero, the fee is zero and nothing is due.

    The specification gives the zero-net case its own clause -- handling is 0
    "when `net_equipment_cents` is 0" -- so a fully subsidized order is not
    charged the small-order fee that a 24,000c net attracts.

    Design: Difficulty/combinatorial_formula/equipment_handling_fee_threshold_read_off_net_not_total
    """
    context = authorized_store()

    order = _draft_order(
        context.store_id,
        context.owner_h,
        [order_line("EBT_ONLY_WIRELESS_TERMINAL", 1)],
    )
    assert_fields(
        order,
        {
            "subtotal_cents": 42500,
            "subsidy_cents": 42500,
            "net_equipment_cents": 0,
            "handling_fee_cents": 0,
            "total_due_cents": 0,
        },
        "fully subsidized order",
    )


def test_anomaly_score_uses_small_format_weights_over_the_footprint_expectation():
    """Closing a convenience store's period scores it at exactly 92 on the
    small-format weights and lands it on the highest flag band.

    The size expectation takes the footprint branch -- two lanes at $4,000.00 and
    thirty shelf feet at $150.00 is 1,250,000c, below a twelfth of the annual
    gross -- and the convenience store type swaps in the small-format weights of
    45, 35 and 20. Both the excess and large-share components clamp at 1 while
    the even-dollar component lands at 0.6, so 45 + 35 + 12 rounds once to 92,
    and the specification's bands make 70 the floor of `FLAG_L3`.

    Design: Difficulty/combinatorial_formula/redemption_anomaly_weighted_three_component_score_with_small_format_weights
    """
    context = authorized_store()
    period = open_flagged_period(context.store_id)

    period = close_period(period["id"])

    assert_fields(
        period,
        {
            "size_expectation_cents": 1250000,
            "redemption_total_cents": 4375000,
            "transaction_count": 25,
            "anomaly_score": 92,
            "flag_level": "FLAG_L3",
            "status": "CLOSED",
            "reconciliation_status": "VARIANCE",
            "reconciliation_variance_cents": 4375000,
        },
        "closed period",
    )


def test_flag_l3_close_reflects_onto_the_store_and_opens_an_investigation():
    """The scored close is not a private figure: the store picks up the flag
    level and the under-investigation dimension, and one anomaly investigation is
    opened against the period that caused it.

    The store's `redemption_flag_level` is derived from its closed periods, and
    the specification opens an investigation when a period closes at `FLAG_L3`,
    recording the triggering period on it.

    Design: Difficulty/combinatorial_formula/redemption_anomaly_weighted_three_component_score_with_small_format_weights
    """
    context = authorized_store()
    period = open_flagged_period(context.store_id)

    close_period(period["id"])

    store = refresh_store(context.store_id)
    assert_fields(
        store,
        {"redemption_flag_level": "FLAG_L3", "sanction_status": "UNDER_INVESTIGATION"},
        "flagged store",
    )

    investigations = rows(
        api_client.list_investigations(ADMIN, {"store_id": context.store_id})
    )
    assert len(investigations) == 1, (
        f"expected exactly one anomaly investigation, got {investigations}"
    )
    assert_fields(
        investigations[0],
        {"opened_reason": "ANOMALY_FLAG_L3", "trigger_period_id": period["id"]},
        "anomaly investigation",
    )
