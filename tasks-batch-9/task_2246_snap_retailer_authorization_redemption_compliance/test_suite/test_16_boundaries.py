"""Constants approached from both sides, one unit apart.

The anomaly flag band, the strict staple-sales share and the rounding order of
the ineligible sales tax are all pinned by values that differ by a single point,
a single basis point or a single cent.
"""
from test_helpers import (
    ADMIN,
    BASKET_SPLIT,
    INV_PASS,
    ApiErrorId,
    active_equipment,
    api_client,
    assert_fields,
    assert_no_rows,
    assert_row_count,
    authorized_store,
    application_payload,
    close_period,
    create_owner,
    create_period,
    create_store,
    created,
    import_settlement,
    ok,
    owner_headers,
    pos_transaction_payload,
    refresh_application,
    refresh_store,
    validate_error,
)

GROCERY_PROFILE = {
    "state_code": "TX",
    "store_type": "GROCERY",
    "checkout_lane_count": 3,
    "staple_shelf_linear_feet": 60,
    "annual_gross_sales_cents": 36000000,
    "max_terminal_slots": 2,
    "tax_rate_bps": None,
    "hardship_designated": None,
}


def _scored_period(store_id, period_index, start, end, **settlement):
    period = create_period(
        store_id, period_index=period_index, period_start=start, period_end=end
    )
    import_settlement(period["id"], **settlement)
    return period


def test_anomaly_score_of_sixty_nine_stays_in_the_second_flag_band():
    """A period scoring exactly 69 lands on FLAG_L2 and opens nothing.

    The specification makes the bands inclusive at their lower bound: "All four
    bands are inclusive at their lower bound -- 69 is `FLAG_L2` and 70 is
    `FLAG_L3`." A 69 therefore leaves the store's sanction dimension alone.

    Design: Difficulty/boundary_precision_check/anomaly_flag_l3_boundary_sixty_nine_versus_exactly_seventy
    """
    context = authorized_store()
    period = _scored_period(
        context.store_id,
        1,
        "2026-05-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        imported_total_cents=4375000,
        imported_transaction_count=100,
        imported_large_transaction_cents=1093750,
        imported_even_dollar_transaction_count=13,
    )

    closed = close_period(period["id"])

    assert_fields(closed, {"anomaly_score": 69, "flag_level": "FLAG_L2"}, "period at 69")
    assert_fields(
        refresh_store(context.store_id),
        {"redemption_flag_level": "FLAG_L2", "sanction_status": "NONE"},
        "store below the band",
    )
    assert_no_rows(
        api_client.list_investigations(ADMIN, {"store_id": context.store_id})
    )


def test_anomaly_score_of_exactly_seventy_crosses_into_the_third_flag_band():
    """One more point -- reached only by changing the even-dollar count -- pushes
    the identical redemption total into FLAG_L3 and opens an investigation.

    Both periods carry the same `redemption_total_cents` and the same large-
    transaction figure, so only the even-dollar component moves, and 70 is the
    inclusive floor of `FLAG_L3`.

    Design: Difficulty/boundary_precision_check/anomaly_flag_l3_boundary_sixty_nine_versus_exactly_seventy
    """
    context = authorized_store()
    low = _scored_period(
        context.store_id,
        1,
        "2026-05-01T00:00:00Z",
        "2026-06-01T00:00:00Z",
        imported_total_cents=4375000,
        imported_transaction_count=100,
        imported_large_transaction_cents=1093750,
        imported_even_dollar_transaction_count=13,
    )
    high = _scored_period(
        context.store_id,
        2,
        "2026-06-01T00:00:00Z",
        "2026-07-01T00:00:00Z",
        imported_total_cents=4375000,
        imported_transaction_count=20,
        imported_large_transaction_cents=1093750,
        imported_even_dollar_transaction_count=3,
    )
    low_closed = close_period(low["id"])

    high_closed = close_period(high["id"])

    assert low_closed["redemption_total_cents"] == high_closed["redemption_total_cents"]
    assert_fields(
        high_closed, {"anomaly_score": 70, "flag_level": "FLAG_L3"}, "period at 70"
    )
    assert_fields(
        refresh_store(context.store_id),
        {"redemption_flag_level": "FLAG_L3", "sanction_status": "UNDER_INVESTIGATION"},
        "store on the band",
    )
    opened = assert_row_count(
        api_client.list_investigations(ADMIN, {"store_id": context.store_id}), 1
    )
    assert opened[0]["trigger_period_id"] == high["id"]


def _grocery_criterion_b_application(annual_staple_sales_cents, store_name):
    owner = create_owner()
    store = create_store(
        owner,
        store_name=store_name,
        annual_staple_sales_cents=annual_staple_sales_cents,
        **GROCERY_PROFILE,
    )
    application = created(
        api_client.create_application(
            application_payload(
                store["id"],
                store["version"],
                claimed_criterion="CRITERION_B",
                reported_inventory_lines=INV_PASS,
            ),
            owner_headers(owner),
        )
    )
    return owner, store, application


def test_staple_share_of_exactly_five_thousand_basis_points_fails_criterion_b():
    """A store whose staple sales are exactly half its gross is refused, because
    the comparison is strict.

    The specification says so twice: "`criterion_b_pass` is true exactly when
    `staple_sales_bps` is strictly greater than 5,000", and "A store sitting at
    exactly 5,000 basis points fails". The refused submission leaves the
    application in DRAFT with no submission timestamp.

    Design: Difficulty/boundary_precision_check/criterion_b_strict_boundary_at_exactly_five_thousand_bps
    """
    owner, store, application = _grocery_criterion_b_application(
        18000000, "Rio Grocery Even"
    )
    assert_fields(
        store,
        {"staple_sales_bps": 5000, "criterion_b_pass": False},
        "store at the midpoint",
    )

    response = api_client.submit_application(application["id"], owner_headers(owner))

    validate_error(response, ApiErrorId.ERR_CRITERION_B_NOT_MET.value, 422)
    assert_fields(
        refresh_application(application["id"]),
        {"status": "DRAFT", "submitted_at": None},
        "unsubmitted application",
    )


def test_staple_share_of_five_thousand_and_one_basis_points_passes_criterion_b():
    """One basis point more -- 18,003,600c of the same 36,000,000c gross -- clears
    the strict comparison and the submission is accepted.

    The two stores differ only in `annual_staple_sales_cents`, so any inclusive
    reading of the 5,000 basis-point floor or any rounding slip in the basis-point
    derivation would make the pair agree instead of disagree.

    Design: Difficulty/boundary_precision_check/criterion_b_strict_boundary_at_exactly_five_thousand_bps
    """
    owner, store, application = _grocery_criterion_b_application(
        18003600, "Rio Grocery Over"
    )
    assert_fields(
        store,
        {"staple_sales_bps": 5001, "criterion_b_pass": True},
        "store one basis point over",
    )

    submitted = ok(
        api_client.submit_application(application["id"], owner_headers(owner))
    )

    assert_fields(
        submitted,
        {"status": "SUBMITTED", "submitted_at": "2026-08-01T00:00:00Z"},
        "submitted application",
    )


def _split_tender_sale():
    context = authorized_store()
    equipment = active_equipment(context.store)
    return created(
        api_client.create_pos_transaction(
            pos_transaction_payload(
                context.store_id,
                equipment.deployment_id,
                line_items=BASKET_SPLIT,
                snap_benefit_available_cents=1000,
                other_tender_offered_cents=5000,
                household_ebt_card_last4="8821",
            ),
            context.clerk_h,
        )
    )


def test_ineligible_sales_tax_is_summed_before_the_rate_is_applied_once():
    """The 825-basis-point tax on a 2,597c ineligible subtotal is 214c, not the
    213c that per-line taxing produces.

    The specification pins the order: "the ineligible extended amounts are summed
    first and the rate is applied once to that sum, never per line." Taxing the
    three ineligible lines separately and summing the rounded results loses a
    cent.

    Design: Difficulty/boundary_precision_check/pos_ineligible_tax_summed_before_rate_applied_once
    """
    sale = _split_tender_sale()

    assert_fields(
        sale,
        {
            "eligible_subtotal_cents": 1296,
            "ineligible_subtotal_cents": 2597,
            "tax_cents": 214,
        },
        "taxed basket",
    )
    assert sale["tax_cents"] != 213, (
        "213c is the per-line-then-sum figure, which is the wrong order"
    )


def test_the_extra_cent_propagates_into_the_required_other_tender():
    """The one-cent rounding difference lands in `other_tender_cents`, which is
    3,107c: the ineligible total with tax plus the 296c eligible shortfall.

    The specification takes only what is needed -- "`other_tender_cents` is set to
    the required amount, not to the amount offered" -- so the 5,000c on offer is
    not drawn down in full, the sale is a split tender, and the three ineligible
    lines are flagged in request order.

    Design: Difficulty/boundary_precision_check/pos_ineligible_tax_summed_before_rate_applied_once
    """
    sale = _split_tender_sale()

    assert_fields(
        sale,
        {
            "ebt_tender_cents": 1000,
            "other_tender_cents": 3107,
            "split_tender_applied": True,
            "status": "AUTHORIZED",
            "flagged_line_skus": ["BEER-6PK", "HOTDELI", "PAPERTWL"],
            "decline_reason_code": None,
        },
        "split-tender sale",
    )
