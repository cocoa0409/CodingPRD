"""Derived calculations: allocations, invoice rounding, tiers, page fees and pools."""

from test_helpers import (
    api_client,
    assert_allocation_entries,
    assert_invoice_figures,
    assert_issue_unit_ledgers,
    assert_print_run_quantities,
    assert_retailer_ledgers,
    assert_statement_channels,
    assert_statement_line,
    assert_statement_money,
    factories,
    fixtures,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

# The issue's Final Order Cut-off: 2026-10-14 less twenty-one calendar days.
FOC_INSTANT = "2026-09-23T00:00:00Z"

# Only the cover the catalog prints, so an order's units are its standard copies.
STANDARD_ONLY_COVERS = (fixtures.DEFAULT_COVER_SPECS[0],)

# A 1-in-10 cover, a capped 1-in-25 cover and an uncapped exclusive cover.
CAPPED_INCENTIVE_COVERS = (
    {"code": "A", "kind": "STANDARD", "cover_price_cents": 399},
    {
        "code": "B",
        "kind": "RATIO_INCENTIVE",
        "incentive_ratio": 10,
        "cover_price_cents": 399,
    },
    {
        "code": "C",
        "kind": "RATIO_INCENTIVE",
        "incentive_ratio": 25,
        "cover_price_cents": 599,
        "allocation_cap": 2,
    },
    {"code": "D", "kind": "RETAILER_EXCLUSIVE", "cover_price_cents": 799},
)

# Five back-to-back craft bookings for one all-craft creator. The royalty shares
# sum to 5000 + 1500 + 800 + 700 + 500 = 8500 bps, exactly the non-cover budget
# left by the title's default 1500 bps cover participation.
CRAFT_TERMS = (
    ("SCRIPT", 12000, 5000, "2026-08-01", "2026-08-05"),
    ("PENCILS", 9000, 1500, "2026-08-05", "2026-08-10"),
    ("INKS", 7000, 800, "2026-08-10", "2026-08-15"),
    ("COLORS", 8000, 700, "2026-08-15", "2026-08-20"),
    ("LETTERS", 5000, 500, "2026-08-20", "2026-08-25"),
)


def staff_five_craft_board() -> dict:
    """A greenlit title whose issue carries a booked stage for all five required crafts.

    Every stage is planned to 2026-09-20, far beyond the 2026-08-01 logical clock,
    so no delivery in these tests scores any slip.
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    assignments = {}
    for craft, page_rate, share_bps, booking_start, booking_end in CRAFT_TERMS:
        assignments[craft] = fixtures.offer_and_accept_assignment(
            title["id"],
            creator["id"],
            craft,
            page_rate_cents=page_rate,
            royalty_share_bps=share_bps,
            booking_start_date=booking_start,
            booking_end_date=booking_end,
        )
    issue = fixtures.schedule_issue(title["id"])
    stages = {}
    for craft, _rate, _bps, _start, _end in CRAFT_TERMS:
        stages[craft] = fixtures.book_stage(
            issue["id"],
            assignments[craft]["id"],
            craft,
            planned_start_date="2026-08-05",
            planned_due_date="2026-09-20",
        )
    return {
        "creator": creator,
        "title": title,
        "assignments": assignments,
        "issue": issue,
        "stages": stages,
    }


def solicited_board_with_one_locked_and_one_draft_order() -> dict:
    """A solicited issue whose cut-off locks 100 copies while 40 more sit `DRAFT`."""
    board = staff_five_craft_board()
    issue_id = board["issue"]["id"]
    creator_id = board["creator"]["id"]

    script_stage = board["stages"]["SCRIPT"]
    fixtures.start_stage(script_stage["id"], creator_id)
    fixtures.deliver_stage(script_stage["id"], creator_id)
    fixtures.approve_stage(script_stage["id"])

    board.update(fixtures.solicit_issue(issue_id, cover_specs=STANDARD_ONLY_COVERS))

    locked_buyer = fixtures.open_retailer(name="Panel Palace")
    locked_order = fixtures.draft_and_submit_order(
        locked_buyer["id"], issue_id, standard_qty=100
    )
    browsing_buyer = fixtures.open_retailer(name="Splash Page Comics")
    draft_order = fixtures.draft_order(
        browsing_buyer["id"], issue_id, standard_qty=40
    )

    fixtures.set_clock(FOC_INSTANT)
    locked_issue = validate_success(
        api_client.foc_lock_issue(issue_id, TEST_USERS["sales_director_headers"])
    )

    board.update(
        {
            "locked_buyer": locked_buyer,
            "locked_order": fixtures.read_order(locked_order["id"]),
            "browsing_buyer": browsing_buyer,
            "draft_order": fixtures.read_order(draft_order["id"]),
            "issue": fixtures.read_issue(locked_issue["id"]),
        }
    )
    return board


def test_ratio_covers_earn_the_floored_quotient_of_the_standard_quantity():
    """60 standard copies earn 6 of the 1-in-10 cover and 2 of the capped 1-in-25.

    PRD: "A `RATIO_INCENTIVE` cover earns the order's `standard_qty` divided by that cover's `incentive_ratio`, with the division floored to a whole copy, and the result then capped at the cover's `allocation_cap` when one is present."

    Design: Corner/calculations/correct_result_ratio_incentive_allocations_use_floor_division_caps_and_eligibility
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=CAPPED_INCENTIVE_COVERS,
        order_overrides={"standard_qty": 60, "exclusive_variant_qty": 1},
    )
    covers = state["covers"]
    order = state["order"]

    assert order["status"] == "FOC_LOCKED"
    # Ratio covers walk first, by ascending incentive_ratio: B before C.
    assert_allocation_entries(
        order, [(covers["B"]["id"], 6), (covers["C"]["id"], 2)]
    )
    assert order["total_units"] == 68
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=68
    )


def test_the_exclusive_cover_earns_nothing_below_the_ten_thousand_unit_gate():
    """An account with no unit history earns no exclusive copy even having asked for one.

    PRD: "A `RETAILER_EXCLUSIVE` cover earns nothing at all unless the ordering retailer is eligible, and eligibility means the retailer's `cumulative_units_ytd` — measured as it stands before this cut-off adds this order's own units — is at least 10,000 units."

    Design: Corner/calculations/correct_result_ratio_incentive_allocations_use_floor_division_caps_and_eligibility
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=CAPPED_INCENTIVE_COVERS,
        order_overrides={"standard_qty": 60, "exclusive_variant_qty": 1},
    )
    order = state["order"]

    assert order["exclusive_variant_qty"] == 1
    earned_ids = [
        entry["variant_cover_id"] for entry in order["earned_variant_allocations"]
    ]
    # The exclusive row is omitted from the allocations, not zero-filled.
    assert state["covers"]["D"]["id"] not in earned_ids
    assert len(order["earned_variant_allocations"]) == 2
    assert order["total_units"] == 68
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]),
        cumulative_units_ytd=68,
        discount_tier="ENTRY",
    )


def test_each_invoice_line_is_rounded_before_the_merchandise_net_is_summed():
    """The standard line plus the two earned lines round to 14364 + 1436 + 719 cents.

    PRD: "For each line, the gross is the quantity multiplied by the unit price, and the line's net is that gross multiplied by the billed fraction and then rounded half up to a whole cent."

    Design: Corner/calculations/correct_result_ratio_incentive_allocations_use_floor_division_caps_and_eligibility
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=CAPPED_INCENTIVE_COVERS,
        order_overrides={"standard_qty": 60, "exclusive_variant_qty": 1},
    )

    invoiced = validate_success(
        api_client.invoice_retailer_order(
            state["order"]["id"], TEST_USERS["sales_director_headers"]
        )
    )

    assert invoiced["status"] == "INVOICED"
    # 60 x 399 x 0.60 = 14364; 6 x 399 x 0.60 = 1436.4 -> 1436; 2 x 599 x 0.60 = 718.8 -> 719.
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="ENTRY",
        merchandise_net_cents=16519,
        handling_fee_cents=995,
        invoice_total_cents=17514,
    )
    assert 14364 + 1436 + 719 == 16519
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]), open_balance_cents=17514
    )


def test_a_draft_order_never_reaches_the_locked_book_or_the_unit_ledgers():
    """The 40-copy `DRAFT` order is left alone by the cut-off and counts nowhere.

    PRD: "Orders in `DRAFT`, `SUBMITTED` or `CANCELLED` contribute nothing to any of these figures, which is exactly what makes order cancellation an exact compensating action rather than an approximate one."

    Design: Corner/calculations/input_set_filtering_a_draft_order_is_invisible_to_the_lock_and_the_print_run
    """
    state = solicited_board_with_one_locked_and_one_draft_order()

    assert state["locked_order"]["status"] == "FOC_LOCKED"
    assert state["locked_order"]["total_units"] == 100
    assert state["draft_order"]["status"] == "DRAFT"
    assert state["draft_order"]["total_units"] == 0
    assert_issue_unit_ledgers(state["issue"], total_ordered_units=100)
    assert_retailer_ledgers(
        fixtures.read_retailer(state["browsing_buyer"]["id"]),
        cumulative_units_ytd=0,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(state["locked_buyer"]["id"]),
        cumulative_units_ytd=100,
        discount_tier="ENTRY",
    )


def test_the_order_driven_run_sizes_itself_on_the_locked_units_alone():
    """100 locked units, 8 overprint copies and the 150 reserve round up to 500.

    PRD: "Under the `ORDER_DRIVEN` basis, `order_base_units` is the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; `DRAFT`, `SUBMITTED` and `CANCELLED` orders are excluded, and a base of zero means there is nothing to print, refused with `ERR_NO_QUALIFYING_ORDERS`."

    Design: Corner/calculations/input_set_filtering_a_draft_order_is_invisible_to_the_lock_and_the_print_run
    """
    state = solicited_board_with_one_locked_and_one_draft_order()
    issue_id = state["issue"]["id"]

    print_run = validate_success(
        api_client.create_print_run(
            issue_id,
            factories.print_run_payload(
                fixtures.issue_version(issue_id), basis="ORDER_DRIVEN"
            ),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )

    # 100 + ceil(100 * 0.08) + 150 = 258, whose carton rounding is the 500 minimum.
    assert_print_run_quantities(
        print_run,
        order_base_units=100,
        overprint_units=8,
        quantity=500,
        printing_number=1,
    )
    assert print_run["basis"] == "ORDER_DRIVEN"
    assert print_run["status"] == "PLANNED"
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), printed_units=0)


def test_handling_is_waived_once_the_merchandise_net_reaches_five_hundred_dollars():
    """A 71820-cent merchandise net carries no handling fee, so the total equals it.

    PRD: "`handling_fee_cents` is then a flat $9.95 — 995 cents — except that it is waived to 0 when `merchandise_net_cents` reaches $500.00, that is 50,000 cents, or more."

    Design: Corner/calculations/constants_applied_handling_fee_is_waived_at_the_free_handling_threshold
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_ONLY_COVERS,
        order_overrides={"standard_qty": 300},
    )

    invoiced = validate_success(
        api_client.invoice_retailer_order(
            state["order"]["id"], TEST_USERS["sales_director_headers"]
        )
    )

    # 300 x 399 = 119700 gross, billed at 0.60 for an exact 71820 cents.
    assert invoiced["status"] == "INVOICED"
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="ENTRY",
        merchandise_net_cents=71820,
        handling_fee_cents=0,
        invoice_total_cents=71820,
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(state["retailer"]["id"]), open_balance_cents=71820
    )


def test_twenty_five_hundred_cumulative_units_earns_basic_while_one_fewer_stays_entry():
    """Two accounts straddling the tier threshold by a single unit land on either side.

    PRD: "So 2,500 cumulative units is already `BASIC` while 2,499 is still `ENTRY`."

    Design: Corner/calculations/threshold_2500_cumulative_units_is_basic_while_2499_is_still_entry
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_ONLY_COVERS,
        retailer_overrides={"name": "Panel Palace", "opening_units_ytd": 2400},
        order_overrides={"standard_qty": 100},
        extra_orders=[
            (
                {"name": "Splash Page Comics", "opening_units_ytd": 2399},
                {"standard_qty": 100},
            )
        ],
    )
    promoted, held_back = state["retailers"]

    assert_retailer_ledgers(
        fixtures.read_retailer(promoted["id"]),
        cumulative_units_ytd=2500,
        discount_tier="BASIC",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(held_back["id"]),
        cumulative_units_ytd=2499,
        discount_tier="ENTRY",
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), total_ordered_units=200
    )


def test_the_entry_tier_account_is_billed_more_than_its_basic_tier_neighbour():
    """The same 100 copies cost 24935 cents at `ENTRY` and 22940 at `BASIC`.

    PRD: "The discount attached to each tier is 40 percent at `ENTRY`, 45 percent at `BASIC`, 50 percent at `CORE` and 55 percent at `PREMIER`, so the fraction actually billed is one minus that discount."

    Design: Corner/calculations/threshold_2500_cumulative_units_is_basic_while_2499_is_still_entry
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_ONLY_COVERS,
        retailer_overrides={"name": "Panel Palace", "opening_units_ytd": 2400},
        order_overrides={"standard_qty": 100},
        extra_orders=[
            (
                {"name": "Splash Page Comics", "opening_units_ytd": 2399},
                {"standard_qty": 100},
            )
        ],
    )
    basic_order, entry_order = state["orders"]
    sales_director = TEST_USERS["sales_director_headers"]

    basic_invoice = validate_success(
        api_client.invoice_retailer_order(basic_order["id"], sales_director)
    )
    entry_invoice = validate_success(
        api_client.invoice_retailer_order(entry_order["id"], sales_director)
    )

    # 39900 gross billed at 0.55 is 21945; billed at 0.60 it is 23940.
    assert_invoice_figures(
        basic_invoice,
        discount_tier_applied="BASIC",
        merchandise_net_cents=21945,
        handling_fee_cents=995,
        invoice_total_cents=22940,
    )
    assert_invoice_figures(
        entry_invoice,
        discount_tier_applied="ENTRY",
        merchandise_net_cents=23940,
        handling_fee_cents=995,
        invoice_total_cents=24935,
    )
    assert entry_invoice["invoice_total_cents"] - basic_invoice["invoice_total_cents"] == 1995


def test_the_invoice_freezes_the_tier_the_cut_off_lock_had_already_promoted():
    """`discount_tier_applied` is `BASIC` because the lock already counted this order.

    PRD: "The tier is taken from the retailer's `discount_tier` as it stands at invoice time and frozen onto the order as `discount_tier_applied`; because the cut-off lock has already added this order's units to `cumulative_units_ytd`, the tier is inclusive of the very order being invoiced."

    Design: Corner/calculations/tiered_pricing_basic_tier_invoice_adds_the_handling_fee_below_the_threshold
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_ONLY_COVERS,
        retailer_overrides={"name": "Panel Palace", "opening_units_ytd": 2400},
        order_overrides={"standard_qty": 100},
    )
    retailer_id = state["retailer"]["id"]

    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_id),
        cumulative_units_ytd=2500,
        open_balance_cents=0,
        discount_tier="BASIC",
    )

    invoiced = validate_success(
        api_client.invoice_retailer_order(
            state["order"]["id"], TEST_USERS["sales_director_headers"]
        )
    )

    # 100 x 399 x 0.55 = 21945, below the 50000-cent waiver, so 995 is added.
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=21945,
        handling_fee_cents=995,
        invoice_total_cents=22940,
    )
    refreshed = fixtures.read_retailer(retailer_id)
    assert_retailer_ledgers(refreshed, open_balance_cents=22940)
    assert refreshed["status"] == "ACTIVE"


def test_production_cost_counts_only_approved_stage_page_fees():
    """The ledger reads 264000 with the script alone approved and 462000 with the pencils.

    PRD: "The title's `production_cost_cents` is then refreshed as the sum of `page_fee_cents` over the approved stages of all that title's issues."

    Design: Corner/calculations/aggregation_production_cost_sums_approved_stages_only
    """
    board = staff_five_craft_board()
    title_id = board["title"]["id"]
    creator_id = board["creator"]["id"]
    stages = board["stages"]

    fixtures.start_stage(stages["SCRIPT"]["id"], creator_id)
    fixtures.deliver_stage(stages["SCRIPT"]["id"], creator_id)
    fixtures.approve_stage(stages["SCRIPT"]["id"])
    fixtures.start_stage(stages["INKS"]["id"], creator_id)
    fixtures.deliver_stage(stages["INKS"]["id"], creator_id)

    # 12000 x 22 for the script; the delivered inks stage is not in the sum.
    assert fixtures.read_title(title_id)["production_cost_cents"] == 264000

    fixtures.start_stage(stages["PENCILS"]["id"], creator_id)
    fixtures.deliver_stage(stages["PENCILS"]["id"], creator_id)
    validate_success(
        api_client.approve_production_stage(
            stages["PENCILS"]["id"], TEST_USERS["managing_editor_headers"]
        )
    )

    # 264000 + 9000 x 22 = 462000, still without the inks stage's 154000.
    assert fixtures.read_title(title_id)["production_cost_cents"] == 462000


def test_approval_freezes_the_page_fee_while_a_delivered_stage_keeps_zero():
    """The approved pencils stage carries 198000 cents; the delivered inks stage carries 0.

    PRD: "A title's `production_cost_cents` equals the sum of `page_fee_cents` over the production stages whose status is `APPROVED` on that title's issues; because an approved stage is terminal and is never cancelled, this ledger only ever grows."

    Design: Corner/calculations/aggregation_production_cost_sums_approved_stages_only
    """
    board = staff_five_craft_board()
    creator_id = board["creator"]["id"]
    stages = board["stages"]

    fixtures.start_stage(stages["SCRIPT"]["id"], creator_id)
    fixtures.deliver_stage(stages["SCRIPT"]["id"], creator_id)
    fixtures.approve_stage(stages["SCRIPT"]["id"])
    fixtures.start_stage(stages["INKS"]["id"], creator_id)
    fixtures.deliver_stage(stages["INKS"]["id"], creator_id)
    fixtures.start_stage(stages["PENCILS"]["id"], creator_id)
    fixtures.deliver_stage(stages["PENCILS"]["id"], creator_id)
    fixtures.approve_stage(stages["PENCILS"]["id"])

    pencils = fixtures.read_stage(stages["PENCILS"]["id"])
    inks = fixtures.read_stage(stages["INKS"]["id"])
    assert pencils["status"] == "APPROVED"
    assert pencils["page_fee_cents"] == 198000
    assert inks["status"] == "DELIVERED"
    assert inks["page_fee_cents"] == 0
    # Every delivery lands far inside the 2026-09-20 due date, so nothing slipped.
    assert fixtures.read_issue(board["issue"]["id"])["total_slip_days"] == 0


def test_the_penciller_settled_statement_floors_each_channel_pool_share():
    """The 3000-bps penciller takes 12565, 4284 and 30600 cents of three pools.

    PRD: "Non-cover participants normalise over their **own** basis-point total rather than over 10000: each receives the remainder multiplied by their own `royalty_share_bps`, divided by the sum of `royalty_share_bps` across all non-`COVER` participants, floored to a whole cent."

    Design: Corner/calculations/precision_the_leftover_cent_lands_on_the_earlier_created_participant
    """
    state = fixtures.setup_royalty_revenue_ledger()
    penciller = state["creators"]["PENCILS"]

    statement = validate_success(
        api_client.create_royalty_statement(
            factories.statement_payload(
                state["title"]["id"], penciller["id"], period="2026-12", basis="SETTLED"
            ),
            TEST_USERS["royalty_accountant_headers"],
        ),
        expected_status=201,
    )

    # The COLLECTED channel is fed only by an ESTIMATED row, so it emits no line.
    assert_statement_channels(statement, ["PRINT_DM", "DIGITAL", "SUBSIDIARY"])
    assert_statement_line(
        statement,
        "PRINT_DM",
        included_net_cents=328500,
        channel_pool_cents=39420,
        creator_share_cents=12565,
    )
    assert_statement_line(
        statement,
        "DIGITAL",
        included_net_cents=56000,
        channel_pool_cents=13440,
        creator_share_cents=4284,
    )
    assert_statement_line(
        statement,
        "SUBSIDIARY",
        included_net_cents=200000,
        channel_pool_cents=96000,
        creator_share_cents=30600,
    )
    assert_statement_money(
        statement,
        gross_royalty_cents=47449,
        recoupment_applied_cents=0,
        payable_cents=47449,
    )
    assert statement["status"] == "DRAFT"
    assert fixtures.read_title(state["title"]["id"])["royalty_accrued_cents"] == 0


def test_the_leftover_cent_of_the_print_pool_lands_on_the_earlier_script_row():
    """The 33507-cent remainder pays 20942 to the writer and 12565 to the penciller.

    PRD: "Finally the floored shares are topped up: the difference between the remainder and the sum of the floored shares is distributed one cent at a time to the non-cover participants in ascending `created_at` order until it is exhausted, so the distributed shares add up to the remainder exactly."

    Design: Corner/calculations/precision_the_leftover_cent_lands_on_the_earlier_created_participant
    """
    state = fixtures.setup_royalty_revenue_ledger()
    title_id = state["title"]["id"]

    writer_statement = fixtures.create_statement(
        title_id, state["creators"]["SCRIPT"]["id"], period="2026-12", basis="SETTLED"
    )
    penciller_statement = fixtures.create_statement(
        title_id, state["creators"]["PENCILS"]["id"], period="2026-12", basis="SETTLED"
    )

    # Flooring gives 20941 + 12565 = 33506, so the odd cent tops up the writer.
    assert_statement_line(
        writer_statement,
        "PRINT_DM",
        channel_pool_cents=39420,
        creator_share_cents=20942,
    )
    assert_statement_line(
        penciller_statement,
        "PRINT_DM",
        channel_pool_cents=39420,
        creator_share_cents=12565,
    )
    assert 20942 + 12565 == 33507
    # 5913 was struck for the cover participant before the remainder was shared.
    assert 5913 + 33507 == 39420
