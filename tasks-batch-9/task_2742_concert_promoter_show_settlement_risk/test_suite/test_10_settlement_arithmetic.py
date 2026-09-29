"""Settlement arithmetic: the receipts waterfall, expense recognition, the
artist legs, the promoter and venue split, the two projection variants and the
portfolio performance index.

Every precondition here is built from scratch through the declared endpoints,
because each test starts against an empty database.
"""

from test_helpers import (
    api_errors as E,
    assert_coop_is_lesser_leg,
    assert_integer_cents,
    assert_market_exposure,
    assert_tier_inventory_conserved,
    assert_timestamp_equals,
    assert_two_decimal_percent,
    assert_waterfall_buckets,
    card_fee_on,
    comp_allowance_for,
    expected_adjusted_gross,
    expected_posture,
    make_tour_accountant_headers,
    pct_of,
    validate_error,
    validate_paginated,
    validate_success,
    whole_percent_of,
)

# The logical clock reads exactly this instant on startup.
CLOCK = "2026-08-01T00:00:00.000Z"

# A RENTAL show's rental_fee_cents is required and must be greater than 0.
RENTAL_FEE_CENTS = 500_000


def _open_and_calculate(build, show_id, calculating_user_id):
    """Open the settlement book and calculate it as a named accountant."""
    book = validate_success(
        build.api.create_settlement({"show_id": show_id}, build.accountant), 201
    )
    calculated = validate_success(
        build.api.calculate_settlement(
            book["id"], make_tour_accountant_headers(calculating_user_id)
        )
    )
    return book, calculated


# ---------------------------------------------------------------------------
# One CO_PROMOTE settlement computed end to end
# ---------------------------------------------------------------------------


def _copromote_split_show(build):
    """A CO_PROMOTE show on a zero-tax, zero-facility-fee building.

    Two fully invoiced budget lines (PRODUCTION 200001 not deductible,
    MARKETING 100001 deductible), a FLAT_GUARANTEE deal of 500000 with a 50000
    deposit and a 300000 expense cap, and 400 of 500 GA seats sold at 5000.
    """
    market = build.market(
        name="Split Market",
        region_code="SP",
        guarantee_exposure_limit_cents=10_000_000,
    )
    artist = build.artist(
        name="Split Act",
        agency="Split Talent",
        tier="THEATER",
        historical_sellthrough_pct=60.00,
        withholding_pct=0,
    )
    venue = build.venue(
        market["id"],
        name="Split Pavilion",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-10-24T02:00:00.000Z",
        load_in_at="2026-10-23T14:00:00.000Z",
        load_out_at="2026-10-24T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="CO_PROMOTE",
        copromote_venue_share_pct=15.00,
        venue_expense_pct_production=40.00,
        venue_expense_pct_marketing=50.00,
        venue_expense_pct_staffing=0,
        venue_expense_pct_hospitality=0,
    )
    offer = build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=50_000,
        expense_cap_cents=300_000,
    )
    production = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="Stage build",
        budgeted_cents=200_001,
        is_artist_deductible=False,
    )
    marketing = build.budget_line(
        show["id"],
        category="MARKETING",
        description="Radio flight",
        budgeted_cents=100_001,
        is_artist_deductible=True,
    )
    build.approved_invoice(
        show["id"], production["id"], 200_001, vendor_name="Riser Rentals"
    )
    build.approved_invoice(
        show["id"], marketing["id"], 100_001, vendor_name="Signal Radio"
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=500
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], 400)
    build.set_clock("2026-10-24T02:00:00.000Z")
    validate_success(build.api.perform_show(show["id"], build.accountant))
    return {
        "market": build.read_market(market["id"]),
        "artist": build.read_artist(artist["id"]),
        "venue": build.read_venue(venue["id"]),
        "show": build.read_show(show["id"]),
        "offer": build.read_offer(offer["id"]),
        "ga": build.read_tier(ga["id"]),
        "production": build.read_budget_line(production["id"]),
        "marketing": build.read_budget_line(marketing["id"]),
    }


def test_co_promote_settlement_receipt_expense_and_artist_legs(build):
    """PRD §3.7: "**Stage one — receipts.** `gross_receipts_cents` is the show's
    accumulated `gross_sold_cents` at calculate time, valued at time-of-sale
    prices, plus its `transferred_in_gross_cents`." And §3.7 stage two: "take
    the sum of `settlement_expense_cents` across the participating lines whose
    `is_artist_deductible` is true, and if the accepted offer carries an
    `expense_cap_cents`, use the lesser of that sum and the cap". And §3.7
    stage three: "`artist_coop_contribution_cents` is the **lesser** of the two
    legs, and each leg is rounded independently **before** the comparison,
    never after."

    Design: Corner/calculations/co_promote_settlement_split_closes_the_identity_on_a_known_fixture
    """
    world = _copromote_split_show(build)
    _, settlement = _open_and_calculate(build, world["show"]["id"], "u-sp-calc")

    # Receipts: 400 seats sold at 5000 on a zero-tax, zero-facility building.
    assert_waterfall_buckets(
        settlement,
        expected_adjusted_gross(2_000_000, 0, 400, 0),
    )
    assert settlement["credit_card_fee_cents"] == 50_000
    assert settlement["adjusted_gross_cents"] == 1_950_000

    # Expense recognition: both lines came in exactly on budget.
    assert settlement["total_settlement_expense_cents"] == 300_002
    assert settlement["allowed_expense_cents"] == 100_001
    assert settlement["breakeven_cents"] == 600_001

    # The artist legs: a flat guarantee, then the lesser co-op leg.
    assert settlement["artist_base_earnings_cents"] == 500_000
    assert_coop_is_lesser_leg(
        settlement["artist_coop_contribution_cents"],
        recognised_marketing_cents=100_001,
        base_earnings_cents=500_000,
    )
    # The share leg is 50001 (half of 100001, rounded half up); the cap leg is
    # 25000 (5 percent of 500000) and therefore binds.
    assert settlement["artist_coop_contribution_cents"] == 25_000
    assert settlement["artist_earnings_cents"] == 475_000
    assert settlement["withholding_cents"] == 0
    assert settlement["deposit_credit_cents"] == 50_000
    assert settlement["payment_due_cents"] == 425_000


def test_co_promote_settlement_split_closes_the_closing_identity(build):
    """PRD §3.7: "Under `CO_PROMOTE`, `venue_expense_reimbursement_cents` is
    computed **per line and rounded per line, then summed**". And: "One closing
    invariant must hold on every `CALCULATED` settlement, under either
    arrangement: `adjusted_gross_cents` equals `artist_earnings_cents` plus
    `promoter_borne_expense_cents` plus `venue_share_cents` plus
    `promoter_net_cents`."

    Design: Corner/calculations/co_promote_settlement_split_closes_the_identity_on_a_known_fixture
    """
    world = _copromote_split_show(build)
    book, settlement = _open_and_calculate(build, world["show"]["id"], "u-sp-calc")

    # Per line: 40 percent of 200001 rounds to 80000, 50 percent of 100001
    # rounds to 50001. Summed after rounding, that is 130001; rounding the
    # 300002 category total once would not land there.
    assert settlement["venue_expense_reimbursement_cents"] == 130_001
    assert settlement["promoter_borne_expense_cents"] == 170_001

    # Net-before-venue is 1950000 - 475000 - 170001 = 1304999; 15 percent of
    # that is 195749.85, which rounds half up to 195750.
    assert settlement["venue_share_cents"] == 195_750
    assert settlement["promoter_net_cents"] == 1_109_249

    assert (
        settlement["artist_earnings_cents"]
        + settlement["promoter_borne_expense_cents"]
        + settlement["venue_share_cents"]
        + settlement["promoter_net_cents"]
        == settlement["adjusted_gross_cents"]
    )
    assert settlement["status"] == "CALCULATED"
    assert settlement["calculated_by_user_id"] == "u-sp-calc"
    assert settlement["id"] == book["id"]
    assert_integer_cents(
        settlement,
        "gross_receipts_cents",
        "ticket_tax_cents",
        "facility_fee_cents",
        "credit_card_fee_cents",
        "adjusted_gross_cents",
        "total_settlement_expense_cents",
        "allowed_expense_cents",
        "breakeven_cents",
        "artist_base_earnings_cents",
        "artist_coop_contribution_cents",
        "artist_earnings_cents",
        "withholding_cents",
        "deposit_credit_cents",
        "payment_due_cents",
        "venue_expense_reimbursement_cents",
        "promoter_borne_expense_cents",
        "venue_share_cents",
        "promoter_net_cents",
    )


# ---------------------------------------------------------------------------
# Only APPROVED invoices feed a line's actual_cents
# ---------------------------------------------------------------------------


def _line_with_one_invoice_per_status(build):
    """One PRODUCTION line budgeted at 500000 carrying five invoices, one in
    each of `SUBMITTED`, `VERIFIED`, `DISPUTED`, `REJECTED` and `APPROVED`."""
    market = build.market(
        name="Filter Market",
        region_code="FI",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist = build.artist(name="Filter Act", agency="Filter Talent", withholding_pct=0)
    other_artist = build.artist(
        name="Filter Support", agency="Filter Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Filter Hall",
        gross_capacity=500,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-10-26T02:00:00.000Z",
        load_in_at="2026-10-25T14:00:00.000Z",
        load_out_at="2026-10-26T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="Trucking and rigging",
        budgeted_cents=500_000,
        is_artist_deductible=False,
    )
    submitted = build.submitted_invoice(
        show["id"], line["id"], 10_000, vendor_name="Still Pending Freight"
    )
    verified = build.verified_invoice(
        show["id"], line["id"], 20_000, vendor_name="Papered Rigging"
    )
    disputed = build.verified_invoice(
        show["id"], line["id"], 40_000, vendor_name="Contested Catering"
    )
    validate_success(
        build.api.dispute_vendor_invoice(
            disputed["id"],
            build.accountant,
            dispute_reason="the rider quantities do not match the invoice",
        )
    )
    rejected = build.submitted_invoice(
        show["id"], line["id"], 80_000, vendor_name="Refused Backline"
    )
    validate_success(
        build.api.dispute_vendor_invoice(
            rejected["id"],
            build.accountant,
            dispute_reason="no purchase order was ever raised",
        )
    )
    validate_success(
        build.api.resolve_vendor_invoice_dispute(
            rejected["id"],
            build.accountant,
            outcome="REJECT",
            reason="the vendor never performed the work",
        )
    )
    approved = build.approved_invoice(
        show["id"], line["id"], 160_000, vendor_name="Cleared Staging"
    )
    planned = build.show(
        other_artist["id"],
        venue["id"],
        event_at="2026-11-26T02:00:00.000Z",
        load_in_at="2026-11-25T14:00:00.000Z",
        load_out_at="2026-11-26T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.submitted_offer(
        planned["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=900_000,
        deposit_cents=0,
    )
    return {
        "market": market,
        "show": show,
        "planned_show": planned,
        "line": line,
        "invoices": {
            "SUBMITTED": submitted,
            "VERIFIED": verified,
            "DISPUTED": disputed,
            "REJECTED": rejected,
            "APPROVED": approved,
        },
    }


def test_budget_line_actual_cents_counts_only_approved_invoices(build):
    """PRD §3.6: "the line's `actual_cents` is refreshed to the total
    `amount_cents` of the line's invoices whose status is `APPROVED` — only
    `APPROVED` invoices count, so `SUBMITTED`, `VERIFIED`, `DISPUTED` and
    `REJECTED` amounts are all excluded, which is exactly why approving and
    then rejecting an invoice returns the line to its prior recognition."

    Design: Corner/calculations/budget_line_actual_cents_counts_only_approved_invoices
    """
    world = _line_with_one_invoice_per_status(build)
    line = build.read_budget_line(world["line"]["id"])

    # 10000 + 20000 + 40000 + 80000 + 160000 is 310000 on the row set, but only
    # the single APPROVED row's 160000 is recognised.
    assert line["actual_cents"] == 160_000
    assert line["variance_cents"] == -340_000
    assert line["variance_pct"] == pct_of(-340_000, 500_000)
    assert line["variance_pct"] == -68.00
    assert line["variance_status"] == "WITHIN_TOLERANCE"
    assert line["required_approver_role"] == "NONE"
    assert line["settlement_expense_cents"] == 160_000

    show = build.read_show(world["show"]["id"])
    assert show["total_actual_expense_cents"] == 160_000
    assert show["budget_posture"] == "ON_BUDGET"


def test_excluded_invoice_statuses_keep_their_amounts_without_being_recognised(build):
    """PRD §3.6: "only `APPROVED` invoices count, so `SUBMITTED`, `VERIFIED`,
    `DISPUTED` and `REJECTED` amounts are all excluded". PRD §3.6 on rejection:
    "the invoice moves `DISPUTED → REJECTED`, which is terminal; the target
    line's `actual_cents` is refreshed (a rejected invoice never counts)".

    Design: Corner/calculations/budget_line_actual_cents_counts_only_approved_invoices
    """
    world = _line_with_one_invoice_per_status(build)

    expected_amounts = {
        "SUBMITTED": 10_000,
        "VERIFIED": 20_000,
        "DISPUTED": 40_000,
        "REJECTED": 80_000,
        "APPROVED": 160_000,
    }
    for status, invoice in world["invoices"].items():
        row = build.read_invoice(invoice["id"])
        assert row["status"] == status
        # The excluded row is still there with its amount intact: exclusion is
        # a filter on recognition, not a deletion.
        assert row["amount_cents"] == expected_amounts[status]
        assert row["budget_line_id"] == world["line"]["id"]

    line = build.read_budget_line(world["line"]["id"])
    assert line["actual_cents"] == expected_amounts["APPROVED"]


# ---------------------------------------------------------------------------
# The declared constants, applied at their declared values
# ---------------------------------------------------------------------------


def _constants_world(build):
    """A market, an act, a zero-tax building and one PLANNED show on it."""
    market = build.market(
        name="Constant Market",
        region_code="CT",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist = build.artist(
        name="Constant Act", agency="Constant Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Constant Room",
        gross_capacity=200,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-10-28T02:00:00.000Z",
        load_in_at="2026-10-27T14:00:00.000Z",
        load_out_at="2026-10-28T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    return {"market": market, "artist": artist, "venue": venue, "show": show}


def test_offer_expiry_constant_is_seventy_two_hours_after_submission(build):
    """PRD §3.2: "The submission stamps `submitted_at` with the current logical
    clock and sets `expires_at` to exactly 72 hours — three days — after that
    instant."

    Design: Corner/calculations/declared_constants_are_applied_at_their_declared_values
    """
    world = _constants_world(build)
    offer = build.submitted_offer(
        world["show"]["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )

    assert_timestamp_equals(offer["submitted_at"], CLOCK)
    assert_timestamp_equals(offer["expires_at"], "2026-08-04T00:00:00.000Z")


def test_card_fee_constant_is_two_and_a_half_percent(build):
    """PRD §3.4: "A card-processing charge of 2.5 percent, applied to a base
    that is the gross receipts figure **less the ticket tax** — that is,
    post-tax but **before** the facility fee has been taken out — divided by 100
    and rounded half up to whole cents. This is `credit_card_fee_cents`."

    Design: Corner/calculations/declared_constants_are_applied_at_their_declared_values
    """
    world = _constants_world(build)
    build.accepted_offer(
        world["show"]["id"],
        world["artist"]["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(
        world["show"]["id"], tier_name="GA", price_cents=5_000, allocation_qty=100
    )
    validate_success(build.api.put_show_on_sale(world["show"]["id"], build.buyer))
    build.sell(ga["id"], 80)

    show = build.read_show(world["show"]["id"])
    assert show["gross_sold_cents"] == 400_000
    # The building charges no tax and no facility fee, so the card fee is the
    # only deduction: 2.5 percent of 400000 is exactly 10000.
    assert card_fee_on(400_000) == 10_000
    assert show["adjusted_gross_cents"] == 390_000


def test_variance_escalation_constant_is_twenty_five_percent(build):
    """PRD §3.6: "Anything above 10.00 percent puts the line in
    `PENDING_APPROVAL`, sets `settlement_expense_cents` to `budgeted_cents`
    while the variance is unresolved, and sets `required_approver_role` to
    `TOUR_ACCOUNTANT` when the variance is at most 25.00 percent and
    `RISK_OFFICER` when it is above 25.00 percent." And: "a line budgeted at
    200,000 with actual 260,000 lands on 30.00 and goes to `PENDING_APPROVAL`
    needing a `RISK_OFFICER`."

    Design: Corner/calculations/declared_constants_are_applied_at_their_declared_values
    """
    world = _constants_world(build)
    build.accepted_offer(
        world["show"]["id"],
        world["artist"]["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    line = build.budget_line(
        world["show"]["id"],
        category="PRODUCTION",
        description="Overrun risers",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    build.approved_invoice(
        world["show"]["id"], line["id"], 260_000, vendor_name="Overrun Staging"
    )

    line = build.read_budget_line(line["id"])
    assert line["actual_cents"] == 260_000
    assert line["variance_cents"] == 60_000
    assert line["variance_pct"] == 30.00
    assert line["variance_status"] == "PENDING_APPROVAL"
    assert line["required_approver_role"] == "RISK_OFFICER"
    assert line["settlement_expense_cents"] == 200_000

    show = build.read_show(world["show"]["id"])
    assert show["total_actual_expense_cents"] == 260_000
    assert show["budget_posture"] == "VARIANCE_PENDING"


# ---------------------------------------------------------------------------
# Half-up rounding on every independently rounded bucket
# ---------------------------------------------------------------------------


def _half_cent_world(build):
    """Every rounded quantity here lands on an exact half.

    A 2.50 percent tax on 20020 is 500.5; the card base 19519 gives 487.975; a
    1000050 guarantee against a 3000000 limit gives 33.335 percent; a 200050
    actual against a 200000 budget gives 0.025 percent.
    """
    market = build.market(
        name="Precision Market",
        region_code="PR",
        guarantee_exposure_limit_cents=3_000_000,
    )
    artist = build.artist(
        name="Precision Act", agency="Precision Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Precision Club",
        gross_capacity=100,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=2.50,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-10-30T02:00:00.000Z",
        load_in_at="2026-10-29T14:00:00.000Z",
        load_out_at="2026-10-30T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=1_000_050,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="Half-cent rigging",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    build.approved_invoice(
        show["id"], line["id"], 200_050, vendor_name="Half Cent Rigging"
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_005, allocation_qty=10
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], 4)
    build.set_clock("2026-10-30T02:00:00.000Z")
    validate_success(build.api.perform_show(show["id"], build.accountant))
    return {"market": market, "show": show, "line": line, "ga": ga}


def test_money_rounding_is_half_up_on_each_receipt_bucket(build):
    """PRD §2.6: "multiply the amount by the percentage, divide by 100, and
    round the result **half up** to a whole cent — a value of exactly one-half
    cent rounds away from zero, upward in magnitude." And PRD §3.4: "Each
    bucket is rounded independently and no bucket is ever re-derived from the
    net."

    Design: Corner/calculations/money_and_percent_rounding_is_half_up_on_every_independent_bucket
    """
    world = _half_cent_world(build)
    _, settlement = _open_and_calculate(build, world["show"]["id"], "u-pr-calc")

    assert settlement["gross_receipts_cents"] == 20_020
    # 2.50 percent of 20020 is 500.5, which rounds up to 501.
    assert settlement["ticket_tax_cents"] == 501
    assert settlement["facility_fee_cents"] == 0
    # 2.5 percent of the post-tax base 19519 is 487.975, which rounds to 488 —
    # a card fee taken on the raw 20020 would have been 501 instead.
    assert settlement["credit_card_fee_cents"] == 488
    assert settlement["adjusted_gross_cents"] == 19_031
    assert_waterfall_buckets(
        settlement, expected_adjusted_gross(20_020, 2.50, 4, 0)
    )
    assert_integer_cents(
        settlement,
        "ticket_tax_cents",
        "facility_fee_cents",
        "credit_card_fee_cents",
        "adjusted_gross_cents",
    )


def test_exposure_utilization_percent_rounds_half_up_to_two_decimals(build):
    """PRD §3.3: "`exposure_utilization_pct` is the market's
    `committed_guarantee_cents` multiplied by 100, divided by its
    `guarantee_exposure_limit_cents`, rounded half up to two decimal places."

    Design: Corner/calculations/money_and_percent_rounding_is_half_up_on_every_independent_bucket
    """
    world = _half_cent_world(build)
    market = build.read_market(world["market"]["id"])

    # 1000050 * 100 / 3000000 is 33.335, which rounds half up to 33.34.
    assert pct_of(1_000_050, 3_000_000) == 33.34
    assert_two_decimal_percent(market["exposure_utilization_pct"])
    assert_market_exposure(market, 1_000_050, 33.34, expected_posture(33.34))
    assert market["risk_posture"] == "OPEN"


def test_variance_percent_rounds_half_up_to_two_decimals(build):
    """PRD §2.6: "Two derived percentages, `exposure_utilization_pct` on a
    market and `variance_pct` on a budget line, are themselves rounded half up
    to two decimal places, and every threshold comparison in this document
    reads the **rounded** value, never the raw ratio."

    Design: Corner/calculations/money_and_percent_rounding_is_half_up_on_every_independent_bucket
    """
    world = _half_cent_world(build)
    line = build.read_budget_line(world["line"]["id"])

    assert line["actual_cents"] == 200_050
    assert line["variance_cents"] == 50
    # 50 * 100 / 200000 is 0.025, which rounds half up to 0.03.
    assert pct_of(50, 200_000) == 0.03
    assert_two_decimal_percent(line["variance_pct"])
    assert line["variance_pct"] == 0.03
    assert line["variance_status"] == "WITHIN_TOLERANCE"
    assert line["settlement_expense_cents"] == 200_050


# ---------------------------------------------------------------------------
# The comp allowance admits exactly thirty comps on a thousand seats
# ---------------------------------------------------------------------------


def _thousand_seat_on_sale_show(build):
    """A single 1000-seat GA tier on sale, with nothing papered yet."""
    market = build.market(
        name="Comp Market",
        region_code="CP",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist = build.artist(name="Comp Act", agency="Comp Talent", withholding_pct=0)
    venue = build.venue(
        market["id"],
        name="Comp Theatre",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-02T02:00:00.000Z",
        load_in_at="2026-11-01T14:00:00.000Z",
        load_out_at="2026-11-02T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=1_000
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    return {"market": market, "artist": artist, "venue": venue, "show": show, "ga": ga}


def _comp_hold(build, tier_id, qty, holder):
    return build.api.create_ticket_hold(
        {"ticket_tier_id": tier_id, "kind": "COMP", "qty": qty, "holder": holder},
        build.buyer,
    )


def test_comp_allowance_admits_exactly_thirty_comps_and_refuses_the_thirty_first(build):
    """PRD §3.5: "The show's comp allowance in whole tickets is 3 percent of
    that total allocation, rounded half up. The show's current
    `comp_tickets_issued` plus the requested quantity must not exceed that
    allowance, or the request is rejected with `ERR_COMP_ALLOWANCE_EXCEEDED`
    (HTTP 422). A 1,000-seat show therefore allows 30 comps and refuses the
    31st; a 2,000-seat show allows 60."

    Design: Corner/calculations/comp_allowance_threshold_admits_exactly_thirty_comps_and_refuses_the_thirty_first
    """
    world = _thousand_seat_on_sale_show(build)
    assert comp_allowance_for(1_000) == 30

    validate_success(
        _comp_hold(build, world["ga"]["id"], 29, "press and radio winners"), 201
    )
    assert build.read_tier(world["ga"]["id"])["comp_qty"] == 29

    # The thirtieth comp sits exactly on the allowance and is admitted.
    validate_success(
        _comp_hold(build, world["ga"]["id"], 1, "the thirtieth guest"), 201
    )
    assert build.read_tier(world["ga"]["id"])["comp_qty"] == 30

    # The thirty-first is refused on allowance, not on inventory: 965 seats are
    # still available in the tier.
    refused = _comp_hold(build, world["ga"]["id"], 1, "one guest too many")
    validate_error(refused, E.ERR_COMP_ALLOWANCE_EXCEEDED)

    tier = build.read_tier(world["ga"]["id"])
    assert tier["comp_qty"] == 30
    assert tier["available_qty"] == 970
    show = build.read_show(world["show"]["id"])
    assert show["comp_tickets_issued"] == 30


def test_converting_a_hold_past_the_comp_allowance_is_refused_and_seats_conserve(build):
    """PRD §3.5: "The comp allowance is re-checked against the show's total
    allocation exactly as above, and a conversion that would push the show past
    its allowance is rejected with `ERR_COMP_ALLOWANCE_EXCEEDED`." And PRD §3.5:
    "a tier's `allocation_qty` always equals its `sold_qty` plus its `comp_qty`
    plus its `held_qty` plus its `available_qty`".

    Design: Corner/calculations/comp_allowance_threshold_admits_exactly_thirty_comps_and_refuses_the_thirty_first
    """
    world = _thousand_seat_on_sale_show(build)
    validate_success(
        _comp_hold(build, world["ga"]["id"], 30, "the full comp list"), 201
    )
    artist_hold = validate_success(
        build.api.create_ticket_hold(
            {
                "ticket_tier_id": world["ga"]["id"],
                "kind": "ARTIST_HOLD",
                "qty": 5,
                "holder": "artist guest list",
            },
            build.buyer,
        ),
        201,
    )

    # 30 comps already issued plus 5 converted seats would be 35 against an
    # allowance of 30.
    validate_error(
        build.api.convert_hold_to_comp(artist_hold["id"], build.buyer),
        E.ERR_COMP_ALLOWANCE_EXCEEDED,
    )

    tier = build.read_tier(world["ga"]["id"])
    assert tier["sold_qty"] == 0
    assert tier["comp_qty"] == 30
    assert tier["held_qty"] == 5
    assert tier["available_qty"] == 965
    assert_tier_inventory_conserved(tier)
    assert build.read_hold(artist_hold["id"])["status"] == "HELD"

    show = build.read_show(world["show"]["id"])
    assert show["comp_tickets_issued"] == 30
    assert show["held_tickets"] == 5


def test_releasing_a_comp_hold_frees_the_allowance_for_a_fresh_comp(build):
    """PRD §3.5: "the tier's `held_qty` — or its `comp_qty`, when the hold's
    kind is `COMP` — decreases by the hold's `qty` and its `available_qty`
    increases by the same amount." And PRD §3.5: "The show's current
    `comp_tickets_issued` plus the requested quantity must not exceed that
    allowance".

    Design: Corner/calculations/comp_allowance_threshold_admits_exactly_thirty_comps_and_refuses_the_thirty_first
    """
    world = _thousand_seat_on_sale_show(build)
    validate_success(
        _comp_hold(build, world["ga"]["id"], 29, "press and radio winners"), 201
    )
    thirtieth = validate_success(
        _comp_hold(build, world["ga"]["id"], 1, "the thirtieth guest"), 201
    )
    validate_error(
        _comp_hold(build, world["ga"]["id"], 1, "one guest too many"),
        E.ERR_COMP_ALLOWANCE_EXCEEDED,
    )

    released = validate_success(
        build.api.release_ticket_hold(thirtieth["id"], build.buyer)
    )
    assert released["status"] == "RELEASED"
    assert build.read_tier(world["ga"]["id"])["comp_qty"] == 29

    # The allowance is recounted live, so a replacement comp now fits.
    validate_success(
        _comp_hold(build, world["ga"]["id"], 1, "the replacement guest"), 201
    )
    tier = build.read_tier(world["ga"]["id"])
    assert tier["comp_qty"] == 30
    assert_tier_inventory_conserved(tier)
    assert build.read_show(world["show"]["id"])["comp_tickets_issued"] == 30


# ---------------------------------------------------------------------------
# The provisional projection re-evaluates on every read
# ---------------------------------------------------------------------------


def _projection_show(build):
    """A 200-seat GA tier on sale at 5000 with one 200000 PRODUCTION line."""
    market = build.market(
        name="Forward Market",
        region_code="FW",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist = build.artist(
        name="Forward Act", agency="Forward Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Forward Room",
        gross_capacity=300,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-06T02:00:00.000Z",
        load_in_at="2026-11-05T14:00:00.000Z",
        load_out_at="2026-11-06T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=200
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    production = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="Forward production",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    return {
        "market": market,
        "show": show,
        "ga": ga,
        "production": production,
    }


def _projection(build, show_id):
    return validate_success(
        build.api.get_settlement_projection(show_id, build.accountant)
    )


def test_settlement_projection_re_evaluates_when_the_pending_inventory_and_budget_change(build):
    """PRD §3.7: "The **provisional** variant values the entire sellable
    allocation at the **current** price: for each tier, take its
    `allocation_qty` less its `comp_qty` less its `held_qty`, multiply by that
    tier's current `price_cents`, and sum across tiers to get a projected gross;
    the projected paid ticket count is the sum of those same per-tier sellable
    quantities." And: "Sales history is deliberately ignored. On the expense
    side the provisional variant uses **budgeted** amounts rather than
    recognised ones: the deductible base is the sum of `budgeted_cents` across
    the artist-deductible lines (still subject to the offer's
    `expense_cap_cents`), the marketing co-op share leg is computed against
    budgeted marketing expense". And PRD §3.7 on
    the show's own forward figure: "it is the show's
    `projected_adjusted_gross_cents` less its `committed_guarantee_cents` less
    its `total_budgeted_expense_cents`, and it may be negative."

    Design: Corner/calculations/settlement_projection_re_evaluates_when_the_pending_inventory_and_budget_change
    """
    world = _projection_show(build)
    show_id = world["show"]["id"]
    tier_id = world["ga"]["id"]

    # Reading one: 200 sellable seats at 5000 is a 1000000 projected gross; the
    # only deduction is the 25000 card fee.
    projection = _projection(build, show_id)
    assert projection["gross_receipts_cents"] == 1_000_000
    assert projection["adjusted_gross_cents"] == 975_000
    show = build.read_show(show_id)
    assert show["projected_adjusted_gross_cents"] == 975_000
    assert show["projected_promoter_net_cents"] == 275_000

    # Reading two: 20 real sales change nothing, because sellable allocation is
    # allocation less comps less holds and never subtracts sold seats.
    build.sell(tier_id, 20)
    assert _projection(build, show_id)["adjusted_gross_cents"] == 975_000
    show = build.read_show(show_id)
    assert show["gross_sold_cents"] == 100_000
    assert show["projected_adjusted_gross_cents"] == 975_000
    assert show["projected_promoter_net_cents"] == 275_000

    # Reading three: six comps take six seats out of the sellable pool.
    validate_success(
        _comp_hold(build, tier_id, 6, "six papered seats"), 201
    )
    assert _projection(build, show_id)["adjusted_gross_cents"] == 945_750
    assert build.read_show(show_id)["projected_promoter_net_cents"] == 245_750

    # Reading four: an artist hold of ten takes ten more out.
    artist_hold = validate_success(
        build.api.create_ticket_hold(
            {
                "ticket_tier_id": tier_id,
                "kind": "ARTIST_HOLD",
                "qty": 10,
                "holder": "artist guest list",
            },
            build.buyer,
        ),
        201,
    )
    assert _projection(build, show_id)["adjusted_gross_cents"] == 897_000
    assert build.read_show(show_id)["projected_promoter_net_cents"] == 197_000

    # Reading five: a deductible marketing line moves the expense side only.
    build.budget_line(
        show_id,
        category="MARKETING",
        description="Forward marketing",
        budgeted_cents=100_000,
        is_artist_deductible=True,
    )
    projection = _projection(build, show_id)
    assert projection["adjusted_gross_cents"] == 897_000
    assert projection["allowed_expense_cents"] == 100_000
    assert projection["breakeven_cents"] == 600_000
    assert projection["artist_base_earnings_cents"] == 500_000
    assert projection["artist_coop_contribution_cents"] == 25_000
    assert projection["artist_earnings_cents"] == 475_000
    show = build.read_show(show_id)
    assert show["total_budgeted_expense_cents"] == 300_000
    assert show["projected_promoter_net_cents"] == 97_000

    # Reading six: releasing the artist hold puts its ten seats back.
    validate_success(build.api.release_ticket_hold(artist_hold["id"], build.buyer))
    assert _projection(build, show_id)["adjusted_gross_cents"] == 945_750
    assert build.read_show(show_id)["projected_promoter_net_cents"] == 145_750


def test_settlement_projection_persists_nothing(build):
    """PRD §3.7: "it neither creates, reads nor mutates any settlement row. Its
    result is a settlement-shaped transient object in which `id`, `created_at`,
    `updated_at` and `version` are all null, `status` is reported as `DRAFT`,
    and `show_id` echoes the show whose projection was requested."

    Design: Corner/calculations/settlement_projection_re_evaluates_when_the_pending_inventory_and_budget_change
    """
    world = _projection_show(build)
    show_id = world["show"]["id"]

    projection = _projection(build, show_id)
    assert projection["id"] is None
    assert projection["created_at"] is None
    assert projection["updated_at"] is None
    assert projection["version"] is None
    assert projection["status"] == "DRAFT"
    assert projection["show_id"] == show_id

    # Three more reads still leave no settlement row behind.
    _projection(build, show_id)
    _projection(build, show_id)
    _projection(build, show_id)
    rows, meta = validate_paginated(
        build.api.list_settlements(build.accountant, show_id=show_id)
    )
    assert meta["total_count"] == 0
    assert rows == []


# ---------------------------------------------------------------------------
# Tier gross accumulates at as-sold prices across two price moves
# ---------------------------------------------------------------------------


def _two_tier_on_sale_show(build):
    """A GA tier at 5000 with 30 seats and a BALCONY tier at 3000 with 10."""
    market = build.market(
        name="History Market",
        region_code="HS",
        guarantee_exposure_limit_cents=5_000_000,
    )
    artist = build.artist(
        name="History Act", agency="History Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="History Hall",
        gross_capacity=100,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-09T02:00:00.000Z",
        load_in_at="2026-11-08T14:00:00.000Z",
        load_out_at="2026-11-09T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=1_000_000,
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=30
    )
    balcony = build.tier(
        show["id"], tier_name="BALCONY", price_cents=3_000, allocation_qty=10
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    return {"market": market, "show": show, "ga": ga, "balcony": balcony}


def test_tier_gross_accumulates_at_as_sold_prices_across_two_price_moves(build):
    """PRD §3.4: "Sales are applied in `created_at` order, and each sale
    contributes its own quantity multiplied by the price the tier carried when
    that sale was recorded. `gross_sold_cents` is therefore an accumulator,
    never a recomputation of `sold_qty` multiplied by the tier's current
    `price_cents`: a later revision never revalues history."

    Design: Corner/calculations/tier_gross_accumulates_at_as_sold_prices_across_two_price_moves
    """
    world = _two_tier_on_sale_show(build)
    show_id = world["show"]["id"]
    ga_id = world["ga"]["id"]

    build.sell(ga_id, 10)
    build.sell(world["balcony"]["id"], 10)
    assert build.read_tier(ga_id)["gross_sold_cents"] == 50_000

    # First move: 5000 to 6000. History is not revalued.
    build.reprice(ga_id, show_id, 6_000)
    ga = build.read_tier(ga_id)
    assert ga["price_cents"] == 6_000
    assert ga["last_price_cents"] == 5_000
    assert ga["price_revision_count"] == 1
    assert ga["gross_sold_cents"] == 50_000
    assert ga["sold_qty"] == 10

    build.sell(ga_id, 10)
    assert build.read_tier(ga_id)["gross_sold_cents"] == 110_000

    # Second move: 6000 down to 4000, then five more seats at the new price.
    build.reprice(ga_id, show_id, 4_000)
    ga = build.read_tier(ga_id)
    assert ga["price_cents"] == 4_000
    assert ga["last_price_cents"] == 6_000
    assert ga["price_revision_count"] == 2
    assert ga["gross_sold_cents"] == 110_000

    build.sell(ga_id, 5)
    ga = build.read_tier(ga_id)
    # 10 at 5000 plus 10 at 6000 plus 5 at 4000 is 130000; 25 seats at the
    # current 4000 would have been 100000.
    assert ga["gross_sold_cents"] == 130_000
    assert ga["sold_qty"] == 25
    assert ga["price_cents"] == 4_000
    assert ga["last_price_cents"] == 6_000
    assert ga["price_revision_count"] == 2
    assert_tier_inventory_conserved(ga)

    balcony = build.read_tier(world["balcony"]["id"])
    assert balcony["gross_sold_cents"] == 30_000
    assert balcony["price_cents"] == 3_000
    assert balcony["price_revision_count"] == 0
    assert balcony["last_price_cents"] is None


def test_show_gross_rolls_up_its_tiers_and_a_third_move_leaves_history_alone(build):
    """PRD §3.4: "The show's `gross_sold_cents` is the sum of `gross_sold_cents`
    across **its own** tiers, and its `paid_tickets_sold` is the sum of
    `sold_qty` across its own tiers". And PRD §3.4 on a revision: "Its
    `gross_sold_cents` and `sold_qty` are explicitly **unchanged** — history
    keeps its as-sold prices."

    Design: Corner/calculations/tier_gross_accumulates_at_as_sold_prices_across_two_price_moves
    """
    world = _two_tier_on_sale_show(build)
    show_id = world["show"]["id"]
    ga_id = world["ga"]["id"]

    build.sell(ga_id, 10)
    build.sell(world["balcony"]["id"], 10)
    build.reprice(ga_id, show_id, 6_000)
    build.sell(ga_id, 10)
    build.reprice(ga_id, show_id, 4_000)
    build.sell(ga_id, 5)

    show = build.read_show(show_id)
    # 130000 from GA plus 30000 from the balcony, over 35 paid tickets.
    assert show["gross_sold_cents"] == 160_000
    assert show["paid_tickets_sold"] == 35
    assert show["adjusted_gross_cents"] == 156_000

    # A third move with no sale after it moves the price but not the money.
    build.reprice(ga_id, show_id, 9_000)
    ga = build.read_tier(ga_id)
    assert ga["price_cents"] == 9_000
    assert ga["last_price_cents"] == 4_000
    assert ga["price_revision_count"] == 3
    assert ga["gross_sold_cents"] == 130_000
    assert ga["sold_qty"] == 25

    show = build.read_show(show_id)
    assert show["gross_sold_cents"] == 160_000
    assert show["paid_tickets_sold"] == 35
    assert show["adjusted_gross_cents"] == 156_000


# ---------------------------------------------------------------------------
# The three receipt deductions, taken in the declared order
# ---------------------------------------------------------------------------


def _waterfall_show(build):
    """A taxed, facility-fee building with 1800 paid tickets and 11400000 gross.

    GA sells 800 at 5000, is repriced to 6000 and sells 600 more; PIT sells its
    whole 400-seat allocation at 9500.
    """
    market = build.market(
        name="Waterfall Market",
        region_code="WF",
        guarantee_exposure_limit_cents=20_000_000,
    )
    artist = build.artist(
        name="Waterfall Act", agency="Waterfall Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Waterfall Coliseum",
        gross_capacity=2_500,
        facility_fee_cents_per_ticket=350,
        ticket_tax_pct=8.00,
    )
    show = build.show(
        artist["id"],
        venue["id"],
        event_at="2026-11-12T02:00:00.000Z",
        load_in_at="2026-11-11T14:00:00.000Z",
        load_out_at="2026-11-12T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        show["id"],
        artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=5_000_000,
        deposit_cents=0,
        expense_cap_cents=2_500_000,
    )
    line = build.budget_line(
        show["id"],
        category="PRODUCTION",
        description="Never invoiced production",
        budgeted_cents=100_000,
        is_artist_deductible=False,
    )
    ga = build.tier(
        show["id"], tier_name="GA", price_cents=5_000, allocation_qty=1_400
    )
    pit = build.tier(
        show["id"], tier_name="PIT", price_cents=9_500, allocation_qty=400
    )
    validate_success(build.api.put_show_on_sale(show["id"], build.buyer))
    build.sell(ga["id"], 800)
    build.reprice(ga["id"], show["id"], 6_000)
    build.sell(ga["id"], 600)
    build.sell(pit["id"], 400)
    build.set_clock("2026-11-12T02:00:00.000Z")
    validate_success(build.api.perform_show(show["id"], build.accountant))
    return {"market": market, "show": show, "ga": ga, "pit": pit, "line": line}


def test_adjusted_gross_buckets_are_taken_in_the_declared_order(build):
    """PRD §3.4: "1. **Ticket tax.** The gross receipts figure multiplied by the
    venue's `ticket_tax_pct`, divided by 100, rounded half up to whole cents."
    And: "2. **Facility fee.** The venue's `facility_fee_cents_per_ticket`
    multiplied by the paid ticket count. This is a flat unit charge on paid
    tickets only and involves no rounding." And: "3. **Card fees.** A
    card-processing charge of 2.5 percent,
    applied to a base that is the gross receipts figure **less the ticket tax**
    — that is, post-tax but **before** the facility fee has been taken out —
    divided by 100 and rounded half up to whole cents." And: "`adjusted_gross_cents`
    is then the gross receipts figure less all three deductions. Each bucket is
    rounded independently and no bucket is ever re-derived from the net."

    Design: Corner/calculations/adjusted_gross_buckets_are_taken_in_the_declared_order_on_the_canonical_fixture
    """
    world = _waterfall_show(build)
    _, settlement = _open_and_calculate(build, world["show"]["id"], "u-wf-calc")

    # 800 at 5000 plus 600 at 6000 plus 400 at 9500 is 11400000 over 1800 seats.
    assert settlement["gross_receipts_cents"] == 11_400_000
    assert_waterfall_buckets(
        settlement, expected_adjusted_gross(11_400_000, 8.00, 1_800, 350)
    )
    # 8.00 percent of the gross.
    assert settlement["ticket_tax_cents"] == 912_000
    # A flat 350 per paid ticket, with no rounding involved.
    assert settlement["facility_fee_cents"] == 630_000
    # 2.5 percent of 10488000 — the post-tax, pre-facility base. On the raw
    # gross it would be 285000; on the fully netted amount 246450.
    assert settlement["credit_card_fee_cents"] == 262_200
    assert card_fee_on(11_400_000 - 912_000) == 262_200
    assert settlement["adjusted_gross_cents"] == 9_595_800

    # No bucket is re-derived from the net, so the four figures still add back
    # to the gross exactly.
    assert (
        settlement["ticket_tax_cents"]
        + settlement["facility_fee_cents"]
        + settlement["credit_card_fee_cents"]
        + settlement["adjusted_gross_cents"]
        == settlement["gross_receipts_cents"]
    )


def test_rental_settlement_splits_the_declared_buckets_without_reimbursement(build):
    """PRD §3.7: "Under `RENTAL`, `venue_expense_reimbursement_cents` is 0 — the
    promoter bears every expense — so `promoter_borne_expense_cents` equals
    `total_settlement_expense_cents`, and `venue_share_cents` is the show's flat
    `rental_fee_cents`, paid regardless of outcome." And: "One closing invariant
    must hold on every `CALCULATED` settlement, under either arrangement:
    `adjusted_gross_cents` equals `artist_earnings_cents` plus
    `promoter_borne_expense_cents` plus `venue_share_cents` plus
    `promoter_net_cents`."

    Design: Corner/calculations/adjusted_gross_buckets_are_taken_in_the_declared_order_on_the_canonical_fixture
    """
    world = _waterfall_show(build)
    _, settlement = _open_and_calculate(build, world["show"]["id"], "u-wf-calc")

    # The single production line was never invoiced, so nothing is recognised.
    assert settlement["total_settlement_expense_cents"] == 0
    assert settlement["venue_expense_reimbursement_cents"] == 0
    assert settlement["promoter_borne_expense_cents"] == 0

    # No marketing expense means a zero co-op share leg, and the lesser leg wins.
    assert settlement["artist_base_earnings_cents"] == 5_000_000
    assert settlement["artist_coop_contribution_cents"] == 0
    assert settlement["artist_earnings_cents"] == 5_000_000

    # The building takes its flat rental fee regardless of outcome.
    assert settlement["venue_share_cents"] == RENTAL_FEE_CENTS
    assert settlement["promoter_net_cents"] == (
        9_595_800 - 5_000_000 - 0 - RENTAL_FEE_CENTS
    )
    assert (
        settlement["artist_earnings_cents"]
        + settlement["promoter_borne_expense_cents"]
        + settlement["venue_share_cents"]
        + settlement["promoter_net_cents"]
        == settlement["adjusted_gross_cents"]
    )


# ---------------------------------------------------------------------------
# The portfolio index defaults to the trailing valuation
# ---------------------------------------------------------------------------


def _portfolio_market(build):
    """One market with an ON_SALE show at 400 of 1000 seats sold and one
    CONFIRMED show that has an allocation but has not opened."""
    market = build.market(
        name="Index Market",
        region_code="IX",
        guarantee_exposure_limit_cents=5_000_000,
    )
    live_artist = build.artist(
        name="Index Headliner", agency="Index Talent", withholding_pct=0
    )
    confirmed_artist = build.artist(
        name="Index Support", agency="Index Talent", withholding_pct=0
    )
    venue = build.venue(
        market["id"],
        name="Index Arena",
        gross_capacity=1_000,
        facility_fee_cents_per_ticket=0,
        ticket_tax_pct=0,
    )
    live_show = build.show(
        live_artist["id"],
        venue["id"],
        event_at="2026-11-14T02:00:00.000Z",
        load_in_at="2026-11-13T14:00:00.000Z",
        load_out_at="2026-11-14T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        live_show["id"],
        live_artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    build.budget_line(
        live_show["id"],
        category="PRODUCTION",
        description="Index production",
        budgeted_cents=200_000,
        is_artist_deductible=False,
    )
    live_ga = build.tier(
        live_show["id"], tier_name="GA", price_cents=5_000, allocation_qty=1_000
    )
    validate_success(build.api.put_show_on_sale(live_show["id"], build.buyer))
    build.sell(live_ga["id"], 400)

    confirmed_show = build.show(
        confirmed_artist["id"],
        venue["id"],
        event_at="2026-11-20T02:00:00.000Z",
        load_in_at="2026-11-19T14:00:00.000Z",
        load_out_at="2026-11-20T08:00:00.000Z",
        announce_at=CLOCK,
        venue_arrangement="RENTAL",
        rental_fee_cents=RENTAL_FEE_CENTS,
    )
    build.accepted_offer(
        confirmed_show["id"],
        confirmed_artist["id"],
        deal_structure="FLAT_GUARANTEE",
        guarantee_cents=500_000,
        deposit_cents=0,
        expense_cap_cents=500_000,
    )
    confirmed_ga = build.tier(
        confirmed_show["id"],
        tier_name="GA",
        price_cents=5_000,
        allocation_qty=1_000,
    )
    return {
        "market": market,
        "live_show": live_show,
        "live_ga": live_ga,
        "confirmed_show": confirmed_show,
        "confirmed_ga": confirmed_ga,
    }


def test_portfolio_risk_defaults_to_trailing_settled_and_never_marks_the_stored_index(build):
    """PRD §3.3: "It takes an optional `valuation` query parameter whose value is
    `TRAILING_SETTLED` or `MARK_TO_MARKET`, defaulting to `TRAILING_SETTLED`."
    And: "a `MARK_TO_MARKET` valuation is returned in the response body only and
    never overwrites the stored `Market.performance_index`, which is always the
    `TRAILING_SETTLED` figure." And PRD §3.3: "Backward-looking by design: a
    market with no settled show reports 0."

    Design: Corner/calculations/portfolio_risk_defaults_to_trailing_settled_while_the_persisted_index_never_marks_to_market
    """
    world = _portfolio_market(build)
    market_id = world["market"]["id"]

    defaulted = validate_success(build.api.get_portfolio_risk(market_id, build.risk))
    explicit = validate_success(
        build.api.get_portfolio_risk(market_id, build.risk, valuation="TRAILING_SETTLED")
    )
    # No show has settled, so the trailing denominator is zero and the index is 0.
    assert defaulted["performance_index"] == 0
    assert explicit["performance_index"] == defaulted["performance_index"]
    assert defaulted["settled_show_count"] == 0

    marked = validate_success(
        build.api.get_portfolio_risk(market_id, build.risk, valuation="MARK_TO_MARKET")
    )
    assert marked["performance_index"] == 40

    # The mark lives in the response body only.
    assert build.read_market(market_id)["performance_index"] == 0
    assert (
        validate_success(build.api.get_portfolio_risk(market_id, build.risk))[
            "performance_index"
        ]
        == 0
    )

    # Both acceptances are on the book; the valuation never touches exposure.
    for body in (defaulted, explicit, marked):
        assert_market_exposure(body, 1_000_000, 20.00, "OPEN")


def test_mark_to_market_marks_only_the_live_show(build):
    """PRD §3.3: "Each live show's contribution to the numerator is its
    `projected_promoter_net_cents` multiplied by its `paid_tickets_sold`, divided
    by the total `allocation_qty` across that show's tiers, rounded half up to
    whole cents — each show's mark is rounded individually **before** the marks
    are summed." And: "Shows that are `CANCELLED`, `RESCHEDULED`, `PLANNED` or
    `CONFIRMED` appear in neither valuation."

    Design: Corner/calculations/portfolio_risk_defaults_to_trailing_settled_while_the_persisted_index_never_marks_to_market
    """
    world = _portfolio_market(build)

    live = build.read_show(world["live_show"]["id"])
    assert live["show_status"] == "ON_SALE"
    assert live["paid_tickets_sold"] == 400
    assert live["projected_adjusted_gross_cents"] == 4_875_000
    assert live["projected_promoter_net_cents"] == 4_175_000

    confirmed = build.read_show(world["confirmed_show"]["id"])
    assert confirmed["show_status"] == "CONFIRMED"
    assert confirmed["projected_adjusted_gross_cents"] == 4_875_000
    assert confirmed["projected_promoter_net_cents"] == 4_375_000

    marked = validate_success(
        build.api.get_portfolio_risk(
            world["market"]["id"], build.risk, valuation="MARK_TO_MARKET"
        )
    )
    # The live show marks in at 4175000 * 400 / 1000 = 1670000 against a
    # denominator of its own 4175000, which is 40 percent. Folding the
    # CONFIRMED show into the denominator would have produced 20 instead.
    assert whole_percent_of(1_670_000, 4_175_000) == 40
    assert marked["performance_index"] == 40
