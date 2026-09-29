"""Derived figures: shelf measurements, period aggregates, decayed evidence,
penalty money, tender arithmetic and equipment pricing.

Each scenario pins an exact integer the specification's arithmetic produces, and
pins the branch that integer then selects, so an implementation that rounds in
the wrong place or filters the wrong input set fails on the number itself.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    ANALYST_ALT,
    INV_PASS,
    ApiErrorId,
    active_equipment,
    add_evidence,
    advance_clock,
    api_client,
    assert_fields,
    assert_inspector_minutes,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    close_period,
    cmp_payment_payload,
    conclude_payload,
    create_application,
    create_owner,
    create_period,
    create_store,
    created,
    elect_cmp,
    equipment_order_payload,
    file_reply,
    four_closed_periods,
    import_settlement,
    issue_charge_letter,
    issue_determination,
    ledger_entries,
    line_item,
    ok,
    open_case,
    open_investigation,
    order_line,
    pending_visit_application,
    pos_transaction_payload,
    refresh_application,
    refresh_case,
    refresh_inspector,
    refresh_investigation,
    refresh_owner,
    refresh_period,
    refresh_store,
    refresh_transaction,
    refresh_visit,
    rows,
    schedule_visit,
    start_visit,
    store_patch_payload,
    submit_application,
    submit_findings,
    substantiated_ineligible_investigation,
    validate_error,
    void_payload,
)

# --------------------------------------------------------------------------
# Shelf measurements
# --------------------------------------------------------------------------


def test_twenty_four_feet_clears_the_convenience_floor_and_the_gap_does_not_flag():
    """An inspector who measures exactly 24 feet against a self-reported 30 passes
    the shelf floor and raises no discrepancy flag, so the application advances.

    The specification makes the floor comparison inclusive -- "`depth_of_stock_pass`
    compares `observed_staple_shelf_linear_feet` against a floor that depends on the
    store's format, and the comparison is **inclusive**" -- and settles the case in
    words: "Twenty-four feet therefore passes for a convenience store and
    twenty-three fails." The same measurement diverges by 6 feet from the store's
    own 30, which floors to 2,000 basis points and stays under the strict 2,500
    flag, so both derived figures point the application at UNDER_REVIEW. Findings
    also release the visit's minutes from the inspector.

    Design: Corner/calculations/depth_of_stock_passes_at_exactly_the_convenience_floor_of_twenty_four_feet
    """
    context = pending_visit_application()

    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_PASS,
        observed_staple_shelf_linear_feet=24,
    )

    assert_fields(
        refresh_visit(context.visit_id),
        {
            "status": "FINDINGS_SUBMITTED",
            "depth_of_stock_pass": True,
            "shelf_discrepancy_bps": 2000,
            "shelf_discrepancy_flag": False,
            "verified_criterion_a_pass": True,
        },
        "visit at the floor",
    )
    assert_fields(
        refresh_application(context.application_id),
        {"status": "UNDER_REVIEW", "deficiency_cycle_count": 0},
        "application after passing findings",
    )
    assert_inspector_minutes(refresh_inspector(context.inspector_id), 0)


def test_a_better_stocked_store_is_still_held_by_the_discrepancy_flag():
    """Sixty observed feet against a self-reported thirty is a 10,000 basis point
    divergence, and the application is held even though the store is better stocked
    than it claimed.

    The discrepancy is measured on the absolute difference -- "take the absolute
    difference between `observed_staple_shelf_linear_feet` and the store's own
    `staple_shelf_linear_feet`" -- so understating the shelving flags exactly as
    overstating it does. The flag alone drives the hold: "`hold_reason_code` is set
    to name the check that failed -- ... `SHELF_DISCREPANCY` when the criterion held
    but the discrepancy flag was raised", and the deficiency cycle count moves to 1
    while the store stays unauthorized.

    Design: Corner/calculations/shelf_discrepancy_above_twenty_five_hundred_bps_holds_the_application
    """
    context = pending_visit_application()

    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_PASS,
        observed_staple_shelf_linear_feet=60,
    )

    assert_fields(
        refresh_visit(context.visit_id),
        {
            "shelf_discrepancy_bps": 10000,
            "shelf_discrepancy_flag": True,
            "depth_of_stock_pass": True,
            "verified_criterion_a_pass": True,
        },
        "visit measuring double the shelving",
    )
    assert_fields(
        refresh_application(context.application_id),
        {
            "status": "PENDING_DOCUMENTS",
            "hold_reason_code": "SHELF_DISCREPANCY",
            "deficiency_cycle_count": 1,
        },
        "held application",
    )
    assert refresh_store(context.store_id)["authorization_status"] == "NOT_AUTHORIZED"


def _two_stores_each_with_a_started_visit():
    """Two convenience stores of one owner, each self-reporting 30 feet, each with
    its own in-progress visit run by the same inspector."""
    context = pending_visit_application()
    store_b = create_store(
        context.owner,
        store_name="Rio Corner Market",
        checkout_lane_count=1,
        annual_gross_sales_cents=24000000,
        annual_staple_sales_cents=14000000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    application_b = create_application(context.owner, store_b, inventory_lines=INV_PASS)
    submit_application(application_b, context.owner)
    visit_b = schedule_visit(
        application_b,
        context.inspector,
        window_start="2026-08-01T04:00:00Z",
        window_end="2026-08-01T05:00:00Z",
    )
    advance_clock("2026-08-01T04:00:00Z")
    start_visit(visit_b, context.inspector)
    return context, application_b, visit_b


def test_shelf_discrepancy_floors_in_both_directions():
    """Thirty-seven feet against thirty floors to 2,333 basis points and stays
    silent; twenty-two feet against thirty floors to 2,666 and flags.

    The specification pins the last step of the arithmetic -- "multiply by 10,000,
    divide by the store's self-reported figure ... and take the floor" -- so 7/30
    yields 2,333 rather than 2,334 and 8/30 yields 2,666 rather than 2,667. The
    second store's 22 feet is also below the convenience floor, which the findings
    step records but does not act on, because "`depth_of_stock_pass` is deliberately
    **not** consulted at this point".

    Design: Corner/calculations/shelf_discrepancy_bps_floors_rather_than_rounds
    """
    context, application_b, visit_b = _two_stores_each_with_a_started_visit()

    submit_findings(
        context.visit,
        context.inspector,
        observed_inventory_lines=INV_PASS,
        observed_staple_shelf_linear_feet=37,
    )
    submit_findings(
        visit_b,
        context.inspector,
        observed_inventory_lines=INV_PASS,
        observed_staple_shelf_linear_feet=22,
    )

    assert_fields(
        refresh_visit(context.visit_id),
        {"shelf_discrepancy_bps": 2333, "shelf_discrepancy_flag": False},
        "visit measuring 37 feet",
    )
    assert_fields(
        refresh_visit(visit_b["id"]),
        {
            "shelf_discrepancy_bps": 2666,
            "shelf_discrepancy_flag": True,
            "depth_of_stock_pass": False,
        },
        "visit measuring 22 feet",
    )
    assert refresh_application(context.application_id)["status"] == "UNDER_REVIEW"
    assert_fields(
        refresh_application(application_b["id"]),
        {"status": "PENDING_DOCUMENTS", "hold_reason_code": "SHELF_DISCREPANCY"},
        "held second application",
    )


# --------------------------------------------------------------------------
# Period aggregates
# --------------------------------------------------------------------------

SALE_KEEP = [line_item("RICE-1", "STAPLE_FOOD", 500, 2)]
SALE_VOID = [line_item("BEEF-1", "STAPLE_FOOD", 5000, 2)]
SALE_DECLINE = [line_item("CIG-2", "TOBACCO", 900, 1)]
SALE_LATE = [line_item("TUNA-1", "STAPLE_FOOD", 700, 10)]


def _trading_store_with_an_open_august_period():
    context = authorized_store()
    equipment = active_equipment(context.store)
    period = create_period(
        context.store_id,
        period_index=8,
        period_start="2026-08-01T00:00:00Z",
        period_end="2026-08-02T00:00:00Z",
    )
    return context, equipment, period


def _ring(context, equipment, line_items, snap=500000, other=0):
    return api_client.create_pos_transaction(
        pos_transaction_payload(
            context.store_id,
            equipment.deployment_id,
            line_items=line_items,
            snap_benefit_available_cents=snap,
            other_tender_offered_cents=other,
            household_ebt_card_last4="4417",
        ),
        context.clerk_h,
    )


def test_closing_a_period_counts_only_authorized_rows_inside_the_window():
    """Four sales exist and only one reaches the period: the voided row, the
    declined row and the row rung at exactly `period_end` are all filtered out.

    The specification fixes the input set precisely -- "transactions belonging to
    that store, whose `status` is `AUTHORIZED` -- declined and voided rows are
    excluded outright -- and whose `created_at` falls at or after `period_start` and
    strictly before `period_end`." The single surviving 1,000c sale therefore fixes
    every frozen figure, and because it is a non-zero whole multiple of $10.00 it is
    the one even-dollar transaction while falling short of the $100.00
    large-transaction floor.

    Design: Corner/calculations/period_pos_aggregates_exclude_declined_voided_and_out_of_window_rows
    """
    context, equipment, period = _trading_store_with_an_open_august_period()
    kept = created(_ring(context, equipment, SALE_KEEP))
    voided = created(_ring(context, equipment, SALE_VOID))
    ok(api_client.void_pos_transaction(voided["id"], void_payload(), context.clerk_h))
    validate_error(
        _ring(context, equipment, SALE_DECLINE, other=100000),
        ApiErrorId.ERR_NO_ELIGIBLE_ITEMS.value,
        422,
    )
    advance_clock("2026-08-02T00:00:00Z")
    late = created(_ring(context, equipment, SALE_LATE))

    close_period(period["id"])

    assert kept["ebt_tender_cents"] == 1000
    assert_fields(
        refresh_period(period["id"]),
        {
            "status": "CLOSED",
            "pos_derived_total_cents": 1000,
            "redemption_total_cents": 1000,
            "transaction_count": 1,
            "large_transaction_cents": 0,
            "even_dollar_transaction_count": 1,
            "reconciliation_status": "NOT_IMPORTED",
            "reconciliation_variance_cents": None,
            "anomaly_score": 20,
            "flag_level": "FLAG_L0",
        },
        "closed august period",
    )
    assert refresh_transaction(voided["id"])["status"] == "VOIDED"
    assert_fields(
        refresh_transaction(late["id"]),
        {"created_at": "2026-08-02T00:00:00Z", "status": "AUTHORIZED"},
        "sale rung at period_end",
    )


def test_settlement_import_replaces_all_four_aggregates_and_five_dollars_still_matches():
    """The processor file overwrites every reported figure, a variance of exactly
    500c reads MATCHED and one cent more flips to VARIANCE.

    The switch is all-or-nothing: "When `imported_total_cents` is non-null,
    `redemption_total_cents` takes `imported_total_cents`, `transaction_count` takes
    `imported_transaction_count`, `large_transaction_cents` takes
    `imported_large_transaction_cents`, and `imported_even_dollar_transaction_count`
    ... The switch is all-or-nothing". The tolerance is strict -- "`VARIANCE` when
    the absolute value of the variance is **strictly greater** than $5.00, and
    `MATCHED` otherwise" -- and the point-of-sale truth survives underneath for the
    variance itself, while importing never closes the period.

    Design: Corner/calculations/settlement_import_overrides_all_four_aggregates_and_the_tolerance_is_inclusive
    """
    context, equipment, period = _trading_store_with_an_open_august_period()
    created(_ring(context, equipment, SALE_KEEP))
    advance_clock("2026-08-02T00:00:00Z")

    import_settlement(
        period["id"],
        imported_total_cents=1500,
        imported_transaction_count=9,
        imported_large_transaction_cents=120000,
        imported_even_dollar_transaction_count=3,
    )

    assert_fields(
        refresh_period(period["id"]),
        {"reconciliation_variance_cents": 500, "reconciliation_status": "MATCHED"},
        "period at the tolerance",
    )

    import_settlement(
        period["id"],
        imported_total_cents=1501,
        imported_transaction_count=9,
        imported_large_transaction_cents=120000,
        imported_even_dollar_transaction_count=3,
    )

    assert_fields(
        refresh_period(period["id"]),
        {
            "reconciliation_variance_cents": 501,
            "reconciliation_status": "VARIANCE",
            "redemption_total_cents": 1501,
            "transaction_count": 9,
            "large_transaction_cents": 120000,
            "even_dollar_transaction_count": 3,
            "pos_derived_total_cents": 1000,
            "status": "OPEN",
        },
        "period one cent past the tolerance",
    )


def test_store_flag_level_reads_the_highest_period_index_not_the_latest_close():
    """Period 2 is closed first and period 1 second, and the store still reports
    period 2's band.

    The selector is the index, not the clock: "Closing a period also refreshes the
    store's own `redemption_flag_level`, which mirrors the `flag_level` of the
    store's `CLOSED` period bearing the highest `period_index`". Period 2's
    3,000,000c against a 1,250,000c expectation is a ratio of 24,000 basis points,
    an excess component of 0.7, and 45 times 0.7 rounds half up once to 32 --
    FLAG_L1, which opens nothing at all.

    Design: Corner/calculations/store_flag_level_reads_the_highest_period_index_not_the_latest_close
    """
    owner = create_owner()
    store = create_store(owner)
    first = create_period(
        store["id"],
        period_index=1,
        period_start="2026-02-01T00:00:00Z",
        period_end="2026-03-01T00:00:00Z",
    )
    import_settlement(
        first["id"], imported_total_cents=1234567, imported_transaction_count=40
    )
    second = create_period(
        store["id"],
        period_index=2,
        period_start="2026-03-01T00:00:00Z",
        period_end="2026-04-01T00:00:00Z",
    )
    import_settlement(
        second["id"], imported_total_cents=3000000, imported_transaction_count=30
    )

    close_period(second["id"])
    close_period(first["id"])

    assert_fields(
        refresh_period(second["id"]),
        {"anomaly_score": 32, "flag_level": "FLAG_L1"},
        "period two",
    )
    assert_fields(
        refresh_period(first["id"]),
        {"anomaly_score": 0, "flag_level": "FLAG_L0"},
        "period one",
    )
    assert_fields(
        refresh_store(store["id"]),
        {"redemption_flag_level": "FLAG_L1", "sanction_status": "NONE"},
        "store after both closes",
    )
    assert_no_rows(api_client.list_investigations(ANALYST, {"store_id": store["id"]}))


def test_farmers_market_weights_and_the_size_expectation_floor():
    """A one-lane farmers' market's 50,000c sales estimate is lifted to the
    100,000c floor, and its own weight set scores 63 instead of 75.

    The floor is stated as a hard minimum -- "`size_expectation_cents` is the lesser
    of those two, but never below $1,000.00" -- and the format decides the blend: "A
    `FARMERS_MARKET` inverts the emphasis, weighting excess at 20, large
    transactions at 30 and even dollars at 50, because round-number benefit
    conversions are the characteristic pattern there." Against the floor the excess
    component saturates at 1, concentration reads 0.4 and round baskets 0.625, so 20
    plus 12 plus 31.25 rounds once to 63 and lands in FLAG_L2 rather than the
    FLAG_L3 the default weights would have produced.

    Design: Corner/calculations/farmers_market_weights_and_the_minimum_size_expectation_floor
    """
    owner = create_owner()
    market = create_store(
        owner,
        store_name="Rio Saturday Market",
        store_type="FARMERS_MARKET",
        checkout_lane_count=1,
        staple_shelf_linear_feet=0,
        annual_gross_sales_cents=600000,
        annual_staple_sales_cents=400000,
        max_terminal_slots=1,
        tax_rate_bps=None,
        hardship_designated=None,
    )
    period = create_period(
        market["id"],
        period_index=1,
        period_start="2026-06-01T00:00:00Z",
        period_end="2026-07-01T00:00:00Z",
    )
    import_settlement(
        period["id"],
        imported_total_cents=300000,
        imported_transaction_count=4,
        imported_large_transaction_cents=60000,
        imported_even_dollar_transaction_count=1,
    )

    close_period(period["id"])

    assert_fields(
        refresh_period(period["id"]),
        {
            "size_expectation_cents": 100000,
            "anomaly_score": 63,
            "flag_level": "FLAG_L2",
        },
        "farmers market period",
    )
    assert_fields(
        refresh_store(market["id"]),
        {"redemption_flag_level": "FLAG_L2", "sanction_status": "NONE"},
        "farmers market store",
    )
    assert_no_rows(api_client.list_investigations(ANALYST, {"store_id": market["id"]}))


# --------------------------------------------------------------------------
# Decayed evidence
# --------------------------------------------------------------------------


def test_evidence_older_than_two_years_contributes_exactly_nothing():
    """Two items observed in early 2024 leave the score at zero and cannot support
    even the lighter ineligible-items conclusion.

    The decay curve zeroes them -- "0.00 for an age beyond 730 days" -- and the
    specification draws the consequence itself: "Evidence older than two years
    contributes exactly nothing, so a case holding five stale items still scores 0."
    The lighter branch needs a live item rather than a score: "Concluding for
    `INELIGIBLE_ITEM_SALES` likewise moves the investigation from `EVIDENCE_REVIEW`
    to `SUBSTANTIATED` and requires at least one evidence item -- of any type --
    whose decay multiplier is still greater than zero, regardless of the score." No
    such item exists, so the conclusion is refused and the investigation stays open
    for business with the store still under investigation.

    Design: Corner/calculations/evidence_older_than_two_years_contributes_exactly_nothing
    """
    owner = create_owner()
    store = create_store(owner)
    investigation = open_investigation(store["id"], opened_reason="TIP")
    add_evidence(
        investigation["id"],
        evidence_type="UNDERCOVER_BUY",
        observed_at="2024-01-01T00:00:00Z",
    )
    add_evidence(
        investigation["id"],
        evidence_type="INFORMANT_STATEMENT",
        observed_at="2024-02-01T00:00:00Z",
    )

    response = api_client.conclude_investigation(
        investigation["id"], conclude_payload("INELIGIBLE_ITEM_SALES"), ANALYST_ALT
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVIDENCE.value, 422)
    assert_fields(
        refresh_investigation(investigation["id"]),
        {
            "trafficking_confidence_score": 0,
            "status": "EVIDENCE_REVIEW",
            "concluded_at": None,
        },
        "fully decayed investigation",
    )
    assert refresh_store(store["id"])["sanction_status"] == "UNDER_INVESTIGATION"


def test_a_single_rounding_lands_on_fifty_eight_and_misses_the_sixty_gate():
    """Three items in three decay tiers sum to exactly 57.5, which is rounded once
    to 58 and falls short of the trafficking floor.

    The multipliers are 0.75 at 212 days, 0.50 at 426 days and 1.00 at 31 days, so
    the contributions are 30, 12.5 and 15, and the specification allows only one
    rounding: "the contributions stay exact and a **single** half-up rounding is
    applied to their sum". Trafficking then needs "a `trafficking_confidence_score`
    of at least 60", which 58 is not, even though the live undercover buy satisfies
    the direct-evidence anchor. The lighter branch, which asks only for a live item,
    succeeds on the very same evidence.

    Design: Corner/calculations/decayed_evidence_sum_rounds_once_to_fifty_eight_and_misses_the_sixty_gate
    """
    owner = create_owner()
    store = create_store(owner)
    investigation = open_investigation(store["id"], opened_reason="TIP")
    for evidence_type, observed_at in (
        ("UNDERCOVER_BUY", "2026-01-01T00:00:00Z"),
        ("INVENTORY_PURCHASE_MISMATCH", "2025-06-01T00:00:00Z"),
        ("INFORMANT_STATEMENT", "2026-07-01T00:00:00Z"),
    ):
        add_evidence(
            investigation["id"], evidence_type=evidence_type, observed_at=observed_at
        )

    response = api_client.conclude_investigation(
        investigation["id"], conclude_payload("TRAFFICKING"), ANALYST_ALT
    )

    validate_error(response, ApiErrorId.ERR_INSUFFICIENT_EVIDENCE.value, 422)
    assert_fields(
        refresh_investigation(investigation["id"]),
        {"trafficking_confidence_score": 58, "status": "EVIDENCE_REVIEW"},
        "investigation two points short",
    )

    ok(
        api_client.conclude_investigation(
            investigation["id"], conclude_payload("INELIGIBLE_ITEM_SALES"), ANALYST_ALT
        )
    )

    assert_fields(
        refresh_investigation(investigation["id"]),
        {"status": "SUBSTANTIATED", "substantiated_violation": "INELIGIBLE_ITEM_SALES"},
        "investigation substantiated on the lighter branch",
    )


# --------------------------------------------------------------------------
# Penalty money
# --------------------------------------------------------------------------


def _determined_cmp_of_423456():
    """The hardship chain that lands a 423,456c civil money penalty: four closed
    periods, a substantiated case, a timely election and a CMP_IN_LIEU
    determination whose assessment is the ledger's only row."""
    context = authorized_store()
    four_closed_periods(context.store_id)
    investigation = substantiated_ineligible_investigation(context.store_id)
    case = open_case(investigation["id"], "INELIGIBLE_ITEMS_HARDSHIP")
    case = issue_charge_letter(case["id"])
    election = elect_cmp(case, context.owner)
    file_reply(case["id"], context.owner)
    issue_determination(case["id"], "CMP_IN_LIEU")
    return context, refresh_case(case["id"]), election


def test_overpayment_is_refused_and_the_exact_payment_closes_the_election():
    """One cent over the balance is refused and writes nothing; the exact amount
    drives the balance to zero, moves the election to PAID and clears the owner.

    The specification forbids a negative balance -- "A remittance greater than the
    outstanding balance is refused with `ERR_CMP_OVERPAYMENT`; the balance may never
    go negative." -- so the 423,457c attempt leaves the ledger at its single
    assessment row. The exact remittance then triggers the closing cascade: "When a
    payment brings the case's outstanding balance to exactly 0, the `APPROVED`
    election on the case moves to `PAID`, and the owner's `cmp_outstanding_cents` and
    `sanction_flag` are re-derived accordingly -- an owner whose only debt has just
    been cleared drops from `HAS_ACTIVE_CMP_DEBT` back to `CLEAR`."

    Design: Corner/calculations/cmp_payment_may_not_exceed_the_balance_and_an_exact_payment_closes_the_election
    """
    context, case, election = _determined_cmp_of_423456()
    assessment = ledger_entries(case["id"])[0]

    refused = api_client.create_cmp_payment(
        case["id"], cmp_payment_payload(423457), context.owner_h
    )

    validate_error(refused, ApiErrorId.ERR_CMP_OVERPAYMENT.value, 422)
    assert_row_count(api_client.list_penalty_ledger(case["id"], ADMIN), 1)

    payment = created(
        api_client.create_cmp_payment(
            case["id"], cmp_payment_payload(423456), context.owner_h
        )
    )

    assert_fields(
        payment,
        {
            "entry_type": "CMP_PAYMENT",
            "amount_cents": -423456,
            "reason_code": "RETAILER_REMITTANCE",
            "balance_after_cents": 0,
        },
        "settling payment",
    )
    entries = ledger_entries(case["id"])
    assert len(entries) == 2, f"expected two ledger rows, got {len(entries)}"
    assert entries[0] == assessment, "the assessment row was rewritten by the payment"
    assert_fields(
        refresh_case(case["id"]),
        {"cmp_amount_cents": 423456, "cmp_capped": False, "cmp_outstanding_cents": 0},
        "settled case",
    )
    paid = [row for row in rows(api_client.list_cmp_elections(case["id"], ADMIN))
            if row["id"] == election["id"]]
    assert paid and paid[0]["status"] == "PAID", f"election did not reach PAID: {paid}"
    assert_fields(
        refresh_owner(context.owner_id),
        {"cmp_outstanding_cents": 0, "sanction_flag": "CLEAR", "status": "ACTIVE"},
        "owner after settling",
    )


# --------------------------------------------------------------------------
# Tender arithmetic and equipment pricing
# --------------------------------------------------------------------------

BASKET_SHORTFALL = [
    line_item("RICE-5", "STAPLE_FOOD", 2500, 2),
    line_item("SOAP-1", "NONFOOD", 1000, 1),
]


def test_split_tender_charges_the_required_amount_and_not_the_offer():
    """Benefits cover 3,000c of a 5,000c eligible bucket, so the household's own
    money is charged 3,083c of the 4,000c it offered.

    Benefits fill only the eligible bucket -- "`ebt_tender_cents` is the **lesser**
    of `eligible_subtotal_cents` and `snap_benefit_available_cents`" -- and the
    remainder is composed of three parts: "The household's own money must therefore
    cover three things: the ineligible subtotal, the tax on that subtotal, and the
    eligible shortfall." Tax on the 1,000c ineligible bucket at 825 basis points is
    82.5c rounded half up to 83c, so the requirement is 1,000 plus 83 plus 2,000, and
    the register takes exactly that: "`other_tender_cents` is set to the **required**
    amount, not to the amount offered".

    Design: Corner/calculations/split_tender_takes_only_the_required_amount_including_the_eligible_shortfall
    """
    context = authorized_store()
    equipment = active_equipment(context.store)

    sale = created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=BASKET_SHORTFALL,
                snap_benefit_available_cents=3000,
                other_tender_offered_cents=4000,
                household_ebt_card_last4="4417",
            ),
            context.clerk_h,
        )
    )

    assert_fields(
        sale,
        {
            "status": "AUTHORIZED",
            "eligible_subtotal_cents": 5000,
            "ineligible_subtotal_cents": 1000,
            "tax_cents": 83,
            "ebt_tender_cents": 3000,
            "other_tender_cents": 3083,
            "split_tender_applied": True,
            "flagged_line_skus": ["SOAP-1"],
            "decline_reason_code": None,
        },
        "split tender sale",
    )


def test_unsubsidized_codes_and_the_sales_ceiling_both_price_at_full_cost():
    """A commercial integration plus receipt paper draws no subsidy at all, and once
    the store's sales are patched above the ceiling neither does a wireless terminal
    with signage.

    The subsidy list is closed -- "`subsidy_cents` is the sum of unit price
    multiplied by `qty` over only those lines whose `item_code` is one of the four
    subsidized codes ... Commercial point-of-sale integration and receipt paper are
    never subsidized." -- so 185,000c plus 4,000c is payable in full, and with a net
    far above the fee threshold no handling fee is added. The second conjunct then
    fails after the edit, since the subsidy requires that "its
    `annual_gross_sales_cents` must be at or below $5,000,000.00", and the edit
    itself "recomputes `staple_sales_bps` and `criterion_b_pass` from the new sales
    figures and advances the store's `version` by one".

    Design: Corner/calculations/subsidy_covers_only_listed_item_codes_and_dies_above_the_sales_ceiling
    """
    context = authorized_store()
    before = refresh_store(context.store_id)

    unsubsidized = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id,
                lines=[
                    order_line("COMMERCIAL_POS_INTEGRATION", 1),
                    order_line("RECEIPT_PAPER_CASE", 1),
                ],
            ),
            context.owner_h,
        )
    )

    assert_fields(
        unsubsidized,
        {
            "subtotal_cents": 189000,
            "subsidy_cents": 0,
            "net_equipment_cents": 189000,
            "handling_fee_cents": 0,
            "total_due_cents": 189000,
        },
        "order of unsubsidized codes",
    )

    patched = ok(
        api_client.update_store(
            context.store_id,
            store_patch_payload(
                before["version"], annual_gross_sales_cents=600000000
            ),
            ADMIN,
        )
    )

    assert_fields(
        patched,
        {
            "annual_gross_sales_cents": 600000000,
            "staple_sales_bps": 333,
            "criterion_b_pass": False,
        },
        "store above the ceiling",
    )
    assert patched["version"] > before["version"], (
        f"the edit did not advance the version: {before['version']} to "
        f"{patched['version']}"
    )

    over_ceiling = created(
        api_client.create_equipment_order(
            equipment_order_payload(
                context.store_id,
                lines=[
                    order_line("EBT_ONLY_WIRELESS_TERMINAL", 1),
                    order_line("SIGNAGE_PACK", 1),
                ],
            ),
            context.owner_h,
        )
    )

    assert_fields(
        over_ceiling,
        {
            "subtotal_cents": 44700,
            "subsidy_cents": 0,
            "net_equipment_cents": 44700,
            "handling_fee_cents": 0,
            "total_due_cents": 44700,
        },
        "order above the sales ceiling",
    )
