"""The invoice waterfall, the dispute service level and the pacing recomputation.

Every test here stands on one shared delivery chain: a 2,000,000-cent 2026-Q3 plan with a
200,000-cent trade fund share drawn against a 500,000-cent pool, one campaign allocated
1,000,000 cents over the ten days from 2026-08-01, and one settled cost-per-click auction
worth exactly 284 cents. Holding the spend at 284 keeps every waterfall figure small
enough to check by hand while still exercising the two half-up roundings inside the
deduction ceiling, and it keeps the billable figure inside the lowest trade-fund tier.

The self-serve and managed cases differ in exactly one field — `managed_service_fee_pct` —
and the 43-cent fee it introduces moves the tier amount from 57 to 65 cents, which is the
whole point of keying step seven and step eight on the post-fee billable figure.
"""

from test_helpers import (
    ACCOUNT_MANAGER,
    AUCTION_SERVICE,
    BILLING_OPS,
    MEASUREMENT_ANALYST,
    NETWORK_ADMIN,
    api_client,
    build_awarded_auction,
    build_campaign_ready_world,
    build_catalog_product,
    build_completed_campaign,
    build_delivering_campaign,
    build_dispute_under_review,
    build_draft_invoice,
    build_eligible_line_item,
    build_engagement_event,
    build_issued_invoice,
    factories,
    parse_utc,
    request_dispute_info,
    reread_advertiser,
    reread_campaign,
    reread_dispute,
    reread_invoice,
    reread_line_item,
    reread_plan,
    reread_pool,
    set_clock,
    validate_success,
)

FLIGHT_START = "2026-08-01T00:00:00Z"
FLIGHT_END = "2026-08-11T00:00:00Z"
BILLING_PERIOD = "2026-08"

QUERY = "red shoes sale"
SEGMENT = "RETURNING"
SHOPPER = "sh_billing_1"

PREMIUM = "premium_line_item"
THIN = "thin_margin_line_item"
THIN_PRODUCT = "thin_margin_product"

CHECKPOINT_DATE = "2026-08-05"
CHECKPOINT_MOMENT = "2026-08-05T00:00:00Z"


def _settled_billing_world(managed=False):
    """One 284-cent settled on-site auction inside billing period 2026-08.

    The premium line item bids 200 against a 0.40-margin hero product and wins over a 150
    bid against a 0.20-margin one; the runner-up's score divided by the winner's multiplier
    plus a cent ceils to 142, and two clicks make 284 cents of settled spend.
    """
    world = build_campaign_ready_world(
        accrual_cents=500000,
        managed=managed,
        advertiser={"managed_service_fee_pct": 0.15} if managed else None,
        plan={
            "committed_total_cents": 2000000,
            "trade_fund_share_cents": 200000,
        },
        slot={
            "max_concurrent_line_items": 2,
            "floor_cpc_cents": 50,
            "relevance_weight": 1.0,
        },
        product={
            "category_code": "FOOTWEAR",
            "title": "red running shoes",
            "margin_pct": 0.4,
        },
        campaign={
            "channel_mix": "ONSITE_ONLY",
            "flight_start_at": FLIGHT_START,
            "flight_end_at": FLIGHT_END,
            "allocated_budget_cents": 1000000,
            "pacing_mode": "EVEN",
            "daily_cap_cents": 200000,
            "attribution_model": "LAST_TOUCH",
            "attribution_window_days": 14,
        },
    )
    build_catalog_product(
        world,
        key=THIN_PRODUCT,
        category_code="FOOTWEAR",
        title="red canvas shoes",
        margin_pct=0.2,
    )
    for key, product_key, bid_cents, terms in (
        (PREMIUM, "product", 200, ["red", "shoes"]),
        (THIN, THIN_PRODUCT, 150, ["red"]),
    ):
        build_eligible_line_item(
            world,
            key=key,
            product_key=product_key,
            bid_cents=bid_cents,
            bid_type="CPC",
            keyword_match_terms=terms,
            category_code="FOOTWEAR",
            flight_start_at=FLIGHT_START,
            flight_end_at=FLIGHT_END,
            daily_budget_cents=100000,
        )
    build_delivering_campaign(world, with_line_item=False)
    build_awarded_auction(
        world, request_context_query=QUERY, shopper_segment=SEGMENT
    )
    for event_type in ("IMPRESSION", "CLICK", "CLICK"):
        build_engagement_event(
            world,
            event_type=event_type,
            line_item_key=PREMIUM,
            shopper_hash=SHOPPER,
        )
    world["auction"] = validate_success(
        api_client.settle_auction_event(world["auction"]["id"], None, AUCTION_SERVICE)
    )
    assert world["auction"]["settled_spend_cents"] == 284
    return world


def _billable_draft_world(managed=False):
    """Complete the campaign early and open the draft invoice, clock still at 08-01."""
    world = _settled_billing_world(managed=managed)
    build_completed_campaign(world, at_flight_end=False)
    build_draft_invoice(world, billing_period_code=BILLING_PERIOD)
    return world


def _dispute_ready_world():
    """Take the self-serve chain all the way to an ISSUED 2026-08 invoice."""
    world = _settled_billing_world()
    build_completed_campaign(world, at_flight_end=False)
    build_issued_invoice(world, billing_period_code=BILLING_PERIOD)
    assert world["invoice"]["net_cash_due_cents"] == 227
    assert world["invoice"]["trade_fund_deduction_cents"] == 57
    return world


def test_self_serve_invoice_deducts_the_lowest_tier_share_of_the_billable_figure():
    """284 gross with no fee yields a 57-cent deduction and 227 cents of cash due.

    PRD 3.8: "Step eight computes the deduction ceiling as the smallest of four quantities:
    `gross_spend_cents` multiplied by the pool's `deduction_cap_pct` rounded half-up to
    whole cents; the billable-before-funds figure multiplied by the tier rate rounded
    half-up to whole cents; the pool's `available_cents`; and the plan's
    `trade_fund_share_cents` less the sum of `trade_fund_deduction_cents` already taken by
    the plan's other invoices whose `invoice_status` is `ISSUED`, `DISPUTED`, `ADJUSTED` or
    `SETTLED`."

    PRD 3.8: "Step seven selects the trade-fund tier rate from that billable-before-funds
    figure: 0.20 when it is strictly below 1,000,000 cents, 0.35 when it is at least
    1,000,000 and strictly below 5,000,000, and 0.50 when it is at or above 5,000,000."

    PRD 3.8: "It stamps `issued_at` with the current logical time, `due_at` thirty days
    later, and `issued_by_user_id` with the acting `X-User-ID`, and it moves every campaign
    on the plan whose `billing_status` is `PENDING_INVOICE` to `INVOICED`."

    PRD 3.8: "`trade_fund_deduction_cents` moves out of the pool's `available_cents` and
    into its `deducted_cents`."

    Design: Corner/calculations/invoice_waterfall_self_serve_deducts_tier_one_share_of_billable
    """
    world = _billable_draft_world()

    issued = validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "August close"}, BILLING_OPS
        )
    )

    assert issued["invoice_status"] == "ISSUED"
    assert issued["onsite_spend_cents"] == 284
    assert issued["offsite_spend_cents"] == 0
    assert issued["gross_spend_cents"] == 284
    # A self-serve advertiser carries a 0.0 fee percentage, so step four is necessarily 0.
    assert issued["managed_service_fee_cents"] == 0
    assert issued["dispute_credit_cents"] == 0
    # min(round_half_up(284 * 0.6) = 170, round_half_up(284 * 0.20) = 57, 300000, 200000).
    assert issued["trade_fund_deduction_cents"] == 57
    assert issued["net_cash_due_cents"] == 227
    assert parse_utc(issued["issued_at"]) == parse_utc("2026-08-01T00:00:00Z")
    assert parse_utc(issued["due_at"]) == parse_utc("2026-08-31T00:00:00Z")

    pool = reread_pool(world)
    assert pool["deducted_cents"] == 57
    # 500000 accrued less 200000 reserved by the plan's share less the 57 just taken.
    assert pool["available_cents"] == 299943

    assert reread_advertiser(world)["credit_exposure_cents"] == 2000227
    assert reread_campaign(world)["billing_status"] == "INVOICED"


def test_managed_fee_raises_the_billable_figure_and_the_tier_amount_with_it():
    """The 43-cent managed fee lifts the deduction from 57 to 65 and cash due to 262.

    PRD 3.8: "Step four computes `managed_service_fee_cents` as `gross_spend_cents`
    multiplied by the advertiser's `managed_service_fee_pct`, rounded half-up to whole
    cents; for a self-serve advertiser this is necessarily 0."

    PRD 3.8: "Step six computes the billable-before-funds figure as `gross_spend_cents`
    plus `managed_service_fee_cents` less `dispute_credit_cents`, floored at 0."

    PRD 3.8: "Step ten sets `net_cash_due_cents` to the billable-before-funds figure less
    `trade_fund_deduction_cents`, floored at 0."

    PRD 3.4: "When the advertiser's `service_model` is `MANAGED` **and** the remaining
    ratio is at least 0.50, the tier is `TIER_1`."

    Design: Corner/calculations/invoice_waterfall_managed_fee_raises_billable_and_tier_amount
    """
    world = _billable_draft_world(managed=True)
    # Plan headroom is 1,000,000 of 2,000,000 committed, so the ratio is exactly 0.50.
    assert reread_line_item(world, PREMIUM)["priority_tier"] == "TIER_1"
    # The tier multiplier cancels out of the second-price ratio, so the clearing figure is
    # the same 142 the self-serve chain produced.
    assert world["auction"]["clearing_price_cents"] == 142

    issued = validate_success(
        api_client.issue_invoice(
            world["invoice"]["id"], {"issue_note": "August close"}, BILLING_OPS
        )
    )

    assert issued["gross_spend_cents"] == 284
    # 284 * 0.15 is 42.6, which rounds half-up to 43 rather than truncating to 42.
    assert issued["managed_service_fee_cents"] == 43
    # min(170, round_half_up(327 * 0.20) = 65, 300000, 200000) — the fee moved the tier
    # amount, not the tier rate, because 327 is still far below 1,000,000.
    assert issued["trade_fund_deduction_cents"] == 65
    assert issued["net_cash_due_cents"] == 262

    assert reread_pool(world)["available_cents"] == 299935
    assert reread_advertiser(world)["credit_exposure_cents"] == 2000262


def test_impression_discrepancy_dispute_opens_a_seventy_two_hour_service_level():
    """A self-serve impression claim is born with 72 hours and a 08-04 deadline.

    PRD 3.9: "The base hours come from `dispute_category`: 72 for
    `IMPRESSION_DISCREPANCY`, 120 for `ATTRIBUTION_WINDOW`, 96 for
    `OFFSITE_SPEND_VARIANCE` and 240 for `INCREMENTALITY_RESTATEMENT`."

    PRD 3.9: "`sla_response_hours` is the base hours less the managed reduction plus 48
    hours for each information request already made, with the whole result floored at 24
    hours — so no dispute ever carries a service level tighter than a single day."

    PRD 3.9: "The dispute is born `SUBMITTED` with `filed_at` stamped at the current
    logical time, `info_request_count` 0, `review_rounds` 0, `escalation_level` 0,
    `sla_breached` false, `approved_credit_cents` 0, and `first_response_at`,
    `assigned_analyst_user_id` and `resolved_by_user_id` all null."

    PRD 3.8: "Filing a measurement dispute moves the invoice to `DISPUTED`, from `ISSUED`
    or from `ADJUSTED`, and moves every covered campaign's `billing_status` from `INVOICED`
    to `DISPUTED`."

    Design: Corner/calculations/dispute_sla_clock_sets_seventy_two_hour_window_for_impression_discrepancy
    """
    world = _dispute_ready_world()

    dispute = validate_success(
        api_client.create_measurement_dispute(
            factories.measurement_dispute_payload(
                world["invoice"]["id"],
                world["invoice"]["version"],
                dispute_category="IMPRESSION_DISCREPANCY",
                claimed_amount_cents=100,
                line_item_id=world[PREMIUM]["id"],
                evidence_note="Third-party counter shows fewer impressions",
            ),
            ACCOUNT_MANAGER,
        ),
        expected_status=201,
    )

    assert dispute["dispute_status"] == "SUBMITTED"
    assert parse_utc(dispute["filed_at"]) == parse_utc("2026-08-01T00:00:00Z")
    # A self-serve advertiser earns no managed reduction and has made no info request.
    assert dispute["sla_response_hours"] == 72
    assert parse_utc(dispute["sla_due_at"]) == parse_utc("2026-08-04T00:00:00Z")
    assert dispute["sla_breached"] is False
    assert dispute["info_request_count"] == 0
    assert dispute["review_rounds"] == 0
    assert dispute["escalation_level"] == 0
    assert dispute["approved_credit_cents"] == 0
    assert dispute["first_response_at"] is None
    assert dispute["assigned_analyst_user_id"] is None
    assert dispute["resolved_by_user_id"] is None

    assert reread_invoice(world)["invoice_status"] == "DISPUTED"
    assert reread_campaign(world)["billing_status"] == "DISPUTED"


def test_information_request_pushes_the_service_level_out_by_forty_eight_hours():
    """One request takes 72 hours to 120 and the deadline from 08-04 to 08-06.

    PRD 3.9: "An information request moves an `UNDER_REVIEW` dispute to `INFO_REQUESTED`,
    is available to `NetworkAdmin` and `MeasurementAnalyst`, and requires an
    `information_request_note`."

    PRD 3.9: "It requires `info_request_count` to be strictly below 2, raises that count by
    1, and extends `sla_due_at` by 48 hours with `sla_response_hours` recomputed
    accordingly."

    PRD 3.9: "It stamps `first_response_at` with the current logical time when that field
    is still null, sets `assigned_analyst_user_id` to the acting `X-User-ID`, raises
    `review_rounds` by 1, and recomputes `sla_breached` under the strict-after rule."

    Design: Corner/calculations/information_request_extends_sla_window_by_forty_eight_hours
    """
    world = _dispute_ready_world()
    build_dispute_under_review(
        world,
        dispute_category="IMPRESSION_DISCREPANCY",
        claimed_amount_cents=100,
        line_item_id=world[PREMIUM]["id"],
    )
    assert world["dispute"]["review_rounds"] == 1

    requested = request_dispute_info(
        world, note="Send the third-party impression log"
    )["dispute"]

    assert requested["dispute_status"] == "INFO_REQUESTED"
    assert requested["info_request_count"] == 1
    # The review round was earned by the assignment; the request itself adds none.
    assert requested["review_rounds"] == 1
    # 72 base hours, no managed reduction, plus 48 for the one request already made.
    assert requested["sla_response_hours"] == 120
    assert parse_utc(requested["sla_due_at"]) == parse_utc("2026-08-06T00:00:00Z")
    assert parse_utc(requested["first_response_at"]) == parse_utc(
        "2026-08-01T00:00:00Z"
    )
    assert requested["sla_breached"] is False


def test_upheld_credit_is_bounded_by_the_impression_evidence_cap():
    """A 90-cent award against a 100-cent claim is cut to the 71-cent evidence cap.

    PRD 3.9: "For `IMPRESSION_DISCREPANCY` the cap is the invoice's `onsite_spend_cents`
    multiplied by 0.25, rounded half-up to whole cents."

    PRD 3.9: "`approved_credit_cents` is then the smallest of four quantities: the supplied
    `approved_credit_amount_cents`; `claimed_amount_cents`; the evidence cap multiplied by
    the uplift and rounded half-up to whole cents; and the invoice's `net_cash_due_cents`
    plus its `trade_fund_deduction_cents`, which is the total the invoice can give back."

    PRD 3.9: "An uplift of 1.10 is applied to the cap when, and only when, `sla_breached`
    is true **and** `escalation_level` is exactly 1; a level-2 escalation earns no uplift
    even if the service level was also breached, and a breach without escalation earns none
    either."

    PRD 3.9: "`UPHOLD` lands the dispute in `UPHELD`, computes `approved_credit_cents`, and
    runs a depth-three unwind. Level one recomputes the invoice's `dispute_credit_cents`
    and moves the invoice from `DISPUTED` to `ADJUSTED` with `trade_fund_deduction_cents`
    and `net_cash_due_cents` recomputed through the waterfall."

    Design: Corner/calculations/dispute_credit_is_capped_by_the_impression_evidence_share
    """
    world = _dispute_ready_world()
    build_dispute_under_review(
        world,
        dispute_category="IMPRESSION_DISCREPANCY",
        claimed_amount_cents=100,
        line_item_id=world[PREMIUM]["id"],
    )

    resolved = validate_success(
        api_client.resolve_measurement_dispute(
            world["dispute"]["id"],
            factories.dispute_resolution_payload(
                decision="UPHOLD",
                approved_credit_amount_cents=90,
                resolution_note="Partial credit on evidence cap",
            ),
            MEASUREMENT_ANALYST,
        )
    )

    assert resolved["dispute_status"] == "UPHELD"
    # 284 * 0.25 = 71, and no uplift applies because the service level was met.
    assert resolved["sla_breached"] is False
    assert resolved["approved_credit_cents"] == 71
    assert resolved["resolved_by_user_id"] == MEASUREMENT_ANALYST["X-User-ID"]

    # The unwind moves the invoice on to ADJUSTED, while the campaign stays disputed
    # because an upheld dispute never returns the billing dimension to INVOICED.
    assert reread_invoice(world)["invoice_status"] == "ADJUSTED"
    assert reread_campaign(world)["billing_status"] == "DISPUTED"
    assert reread_dispute(world)["approved_credit_cents"] == 71


def test_checkpoint_recomputes_the_pacing_index_four_days_into_the_flight():
    """284 delivered against a 400,000-cent ideal indexes at 0.0007, not 0.0.

    PRD 3.3: "Let the total flight length be the number of whole twenty-four-hour periods
    between `flight_start_at` inclusive and `flight_end_at` exclusive, and let the elapsed
    length be the number of whole twenty-four-hour periods from `flight_start_at` up to the
    current logical time, floored at 0 and clipped above at the total."

    PRD 3.3: "The ideal spend is 0 when the total is 0, and otherwise
    `allocated_budget_cents` multiplied by the elapsed count divided by the total count,
    rounded half-up to whole cents. `pacing_index` is 0.0000 when the ideal spend is 0, and
    otherwise `delivered_spend_cents` divided by the ideal spend, rounded half-up to four
    decimal places."

    PRD 2.5: "Re-evaluation is the job of a separate `NetworkAdmin`-only sweep, the daily
    checkpoint, which accepts an optional `as_of_date`; when `as_of_date` is omitted the
    sweep evaluates at the current logical time, and when it is supplied the sweep
    evaluates as of that date."

    Design: Corner/calculations/pacing_index_recomputes_at_checkpoint_and_allowance_clamps_to_daily_cap
    """
    world = _settled_billing_world()
    set_clock(world, CHECKPOINT_MOMENT)

    validate_success(
        api_client.run_daily_checkpoint(
            {"as_of_date": CHECKPOINT_DATE}, NETWORK_ADMIN
        )
    )

    campaign = reread_campaign(world)
    # Four of the ten flight days have elapsed and the flight has not run out, so the
    # sweep leaves the delivery dimension alone.
    assert campaign["delivery_status"] == "DELIVERING"
    assert campaign["delivered_spend_cents"] == 284
    # 284 / round_half_up(1000000 * 4 / 10) = 284 / 400000 = 0.00071, to four places.
    assert campaign["pacing_index"] == 0.0007

    # 2,000,000 committed less the 1,000,000 reservation less the 284 consumed.
    assert reread_plan(world)["available_cents"] == 999716
    assert reread_line_item(world, PREMIUM)["line_item_status"] == "SERVING"
