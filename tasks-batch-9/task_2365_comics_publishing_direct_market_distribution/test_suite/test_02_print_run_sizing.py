"""Print-run sizing: one database state, two bases, two different quantities."""

from test_helpers import (
    api_client,
    assert_field_sequence,
    assert_issue_unit_ledgers,
    assert_print_run_quantities,
    factories,
    fixtures,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

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


def build_on_sale_issue_with_open_reorder() -> dict:
    """One `ON_SALE` issue against which both printing bases are legal.

    The issue is camera-ready, its cut-off froze 1108 ordered units across two
    accounts, its first `ORDER_DRIVEN` printing of 1500 copies has been run, and
    a further 200-copy reorder sits `SUBMITTED` after release.
    """
    fixtures.set_clock("2026-08-01T00:00:00Z")
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
    issue = fixtures.schedule_issue(title["id"], target_on_sale_date="2026-10-14")

    # Every stage lands well inside its planned due date, so no slip cascade runs.
    fixtures.set_clock("2026-08-19T00:00:00Z")
    stages = {}
    for craft, _page_rate, _share_bps, _start, _end in CRAFT_TERMS:
        stages[craft] = fixtures.run_stage_to_approved(
            issue["id"],
            assignments[craft]["id"],
            creator["id"],
            craft=craft,
            planned_start_date="2026-08-05",
            planned_due_date="2026-09-20",
        )

    covers = fixtures.add_covers(issue["id"])
    catalog = fixtures.open_catalog()
    solicitation = fixtures.draft_solicitation(
        catalog["id"],
        issue["id"],
        variant_cover_ids=[covers[code]["id"] for code in ("A", "B", "C")],
    )
    fixtures.submit_solicitation(solicitation["id"])
    fixtures.set_clock("2026-08-21T12:00:00Z")
    fixtures.lock_catalog(catalog["id"])
    fixtures.accept_solicitation(solicitation["id"])
    fixtures.publish_catalog(catalog["id"])

    # 100 standard copies earn 10 + 4 incentive copies; 900 earn 90 + 4 (capped).
    retailers = [fixtures.open_retailer(), fixtures.open_retailer()]
    orders = [
        fixtures.draft_and_submit_order(
            retailers[0]["id"], issue["id"], standard_qty=100
        ),
        fixtures.draft_and_submit_order(
            retailers[1]["id"], issue["id"], standard_qty=900
        ),
    ]

    fixtures.set_clock("2026-09-23T00:00:00Z")
    fixtures.foc_lock(issue["id"])
    first_printing = fixtures.plan_and_complete_print_run(issue["id"], "ORDER_DRIVEN")

    fixtures.set_clock("2026-10-14T00:00:00Z")
    fixtures.release_issue(issue["id"])
    reorder = fixtures.draft_and_submit_order(
        retailers[1]["id"], issue["id"], standard_qty=200
    )

    return {
        "creator": creator,
        "title": fixtures.read_title(title["id"]),
        "assignments": assignments,
        "stages": stages,
        "covers": covers,
        "retailers": retailers,
        "orders": [fixtures.read_order(order["id"]) for order in orders],
        "first_printing": fixtures.read_print_run(first_printing["id"]),
        "reorder": fixtures.read_order(reorder["id"]),
        "issue": fixtures.read_issue(issue["id"]),
    }


def test_order_driven_and_demand_forecast_diverge_from_one_identical_state():
    """The same `ON_SALE` issue sizes at 1500 copies order-driven and 750 forecast.

    PRD: "The two bases answer different questions and are deliberately both legal against the same database state, from which they produce different quantities."

    Design: Difficulty/dual_variant_calc/print_run_quantity_order_driven_vs_demand_forecast_same_state
    """
    state = build_on_sale_issue_with_open_reorder()
    issue_id = state["issue"]["id"]
    editor = TEST_USERS["managing_editor_headers"]

    order_driven = validate_success(
        api_client.create_print_run(
            issue_id,
            factories.print_run_payload(
                fixtures.issue_version(issue_id), basis="ORDER_DRIVEN"
            ),
            editor,
        ),
        expected_status=201,
    )
    demand_forecast = validate_success(
        api_client.create_print_run(
            issue_id,
            factories.print_run_payload(
                fixtures.issue_version(issue_id), basis="DEMAND_FORECAST"
            ),
            editor,
        ),
        expected_status=201,
    )

    # 1108 locked units + 89 overprint + 150 reserve = 1347, one carton up to 1500.
    assert_print_run_quantities(
        order_driven, order_base_units=1108, overprint_units=89, quantity=1500
    )
    # 35% of the 1500 already printed + the 200-copy reorder = 725, up to 750.
    assert_print_run_quantities(
        demand_forecast, order_base_units=725, overprint_units=0, quantity=750
    )
    assert order_driven["quantity"] - demand_forecast["quantity"] == 750
    assert order_driven["status"] == "PLANNED"
    assert demand_forecast["status"] == "PLANNED"


def test_order_driven_base_ignores_the_submitted_reorder_outside_the_locked_book():
    """A `SUBMITTED` reorder of 200 copies never enters the order-driven base.

    PRD: "Under the `ORDER_DRIVEN` basis, `order_base_units` is the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; `DRAFT`, `SUBMITTED` and `CANCELLED` orders are excluded, and a base of zero means there is nothing to print, refused with `ERR_NO_QUALIFYING_ORDERS`."

    Design: Difficulty/dual_variant_calc/print_run_quantity_order_driven_vs_demand_forecast_same_state
    """
    state = build_on_sale_issue_with_open_reorder()
    issue_id = state["issue"]["id"]

    assert state["reorder"]["status"] == "SUBMITTED"
    assert state["reorder"]["standard_qty"] == 200
    assert_issue_unit_ledgers(state["issue"], total_ordered_units=1108)

    # The first printing was sized from the two locked orders alone.
    assert_print_run_quantities(
        state["first_printing"],
        order_base_units=1108,
        overprint_units=89,
        quantity=1500,
    )

    # A second order-driven run, planned while the reorder is open, reads the
    # very same locked book and so lands on the very same figures.
    reprint = fixtures.plan_print_run(issue_id, "ORDER_DRIVEN")
    assert_print_run_quantities(
        reprint, order_base_units=1108, overprint_units=89, quantity=1500
    )
    assert_issue_unit_ledgers(
        fixtures.read_issue(issue_id), total_ordered_units=1108, shipped_units=0
    )


def test_demand_forecast_base_reads_trailing_print_volume_plus_open_reorder_demand():
    """The forecast base is 35% of the 1500 printed copies plus the 200 reordered.

    PRD: "Prior print volume is the sum of `quantity` over that issue's runs whose status is `PRINTED`; reorder demand is the sum of `standard_qty` over that issue's orders that are still `SUBMITTED` and whose `is_reorder` is true."

    Design: Difficulty/dual_variant_calc/print_run_quantity_order_driven_vs_demand_forecast_same_state
    """
    state = build_on_sale_issue_with_open_reorder()
    issue_id = state["issue"]["id"]

    assert state["reorder"]["is_reorder"] is True
    assert state["reorder"]["status"] == "SUBMITTED"
    assert state["orders"][0]["is_reorder"] is False
    assert state["orders"][1]["is_reorder"] is False

    # A further PLANNED run contributes no prior print volume: only PRINTED runs do.
    fixtures.plan_print_run(issue_id, "ORDER_DRIVEN")
    forecast = fixtures.plan_print_run(issue_id, "DEMAND_FORECAST")

    # 35% of 1500 is 525 exactly, plus the 200 open reorder copies.
    assert_print_run_quantities(
        forecast, order_base_units=725, overprint_units=0, quantity=750
    )
    assert forecast["basis"] == "DEMAND_FORECAST"


def test_each_further_printing_numbers_above_the_planned_and_printed_runs():
    """A third printing takes number 3 over one printed and one planned run.

    PRD: "The run's `printing_number` is assigned by the server: one greater than the highest `printing_number` among that issue's runs whose status is `PLANNED` or `PRINTED`, or 1 when the issue has no such run."

    Design: Difficulty/dual_variant_calc/print_run_quantity_order_driven_vs_demand_forecast_same_state
    """
    state = build_on_sale_issue_with_open_reorder()
    issue_id = state["issue"]["id"]

    assert state["first_printing"]["printing_number"] == 1
    second = fixtures.plan_print_run(issue_id, "ORDER_DRIVEN")
    third = fixtures.plan_print_run(issue_id, "DEMAND_FORECAST")
    assert_print_run_quantities(second, printing_number=2, quantity=1500)
    assert_print_run_quantities(third, printing_number=3, quantity=750)

    rows, meta = validate_paginated(
        api_client.list_print_runs(issue_id, TEST_USERS["managing_editor_headers"])
    )
    assert meta["total_count"] == 3
    assert_field_sequence(rows, "printing_number", [1, 2, 3])
    assert_field_sequence(rows, "status", ["PRINTED", "PLANNED", "PLANNED"])

    # Only the completed run feeds the issue's printed-unit ledger.
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), printed_units=1500)
