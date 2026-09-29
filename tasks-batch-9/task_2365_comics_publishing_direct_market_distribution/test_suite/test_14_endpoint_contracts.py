"""Endpoint contracts: create/read/list round trips, action endpoints and filters."""

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_allocation_entries,
    assert_field_sequence,
    assert_ids_in_order,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    assert_versioned_record,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

STANDARD_COVER_ONLY = fixtures.DEFAULT_COVER_SPECS[:1]
STANDARD_AND_RATIO_TEN = fixtures.DEFAULT_COVER_SPECS[:2]


# ─── Catalog create / read / filtered list ────────────

def test_catalog_creation_reads_back_as_an_open_row_with_no_accepted_slots():
    """A created catalog reads back field for field as an `OPEN`, unpublished row.

    PRD: "A new catalog is `OPEN` with `accepted_slot_count` 0 and `published_at` null."

    Design: Corner/endpoints/standard_crud_catalog_create_read_and_filtered_list_round_trip
    """
    fixtures.set_clock()

    created = validate_success(
        api_client.create_catalog(
            factories.catalog_payload(
                solicitation_month="2026-08",
                submission_deadline="2026-08-20",
                on_sale_month="2026-10",
                max_slots=5,
            ),
            TEST_USERS["sales_director_headers"],
        ),
        expected_status=201,
    )
    assert_versioned_record(created, expected_version=1)
    assert created["status"] == "OPEN"
    assert created["accepted_slot_count"] == 0
    assert created["published_at"] is None

    read_back = validate_success(
        api_client.get_catalog(created["id"], TEST_USERS["sales_director_headers"])
    )
    assert read_back["id"] == created["id"]
    assert read_back["solicitation_month"] == "2026-08"
    assert read_back["on_sale_month"] == "2026-10"
    assert read_back["max_slots"] == 5
    assert read_back["status"] == "OPEN"
    assert read_back["accepted_slot_count"] == 0
    assert read_back["published_at"] is None
    assert read_back["version"] == 1


def test_catalog_list_filtered_by_status_counts_only_the_matching_rows():
    """The `status=OPEN` page reports one matching row and no further pages.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether further rows exist beyond the current page."

    Design: Corner/endpoints/standard_crud_catalog_create_read_and_filtered_list_round_trip
    """
    fixtures.set_clock()
    catalog = fixtures.open_catalog(solicitation_month="2026-08")

    rows, meta = validate_paginated(
        api_client.list_catalogs(
            TEST_USERS["sales_director_headers"],
            params={"status": "OPEN", "limit": 100, "offset": 0},
        )
    )
    assert_ids_in_order(rows, [catalog["id"]])
    assert_field_sequence(rows, "status", ["OPEN"])
    assert meta["total_count"] == 1
    assert meta["has_more"] is False
    assert meta["limit"] == 100
    assert meta["offset"] == 0


def test_catalog_list_filtered_by_another_solicitation_month_returns_no_rows():
    """`solicitation_month` filters catalogs on the field of the same name.

    PRD: "Beyond `limit` and `offset`, the list endpoints accept the following filters, each matching the field of the same name on the listed resource: `status` on creators' assignments, title assignments, issues' stages, an assignment's stages, print runs, solicitations, catalogs, retailers, orders, titles and statements; `craft` on creators, title assignments and an issue's stages; `commercial_status` and `production_status` on a title's issues; `kind` on an issue's covers; `basis` on print runs and statements; `channel` on release windows and revenue events; `basis_status` and `period` on revenue events; `period` on statements; `solicitation_month` on catalogs; `discount_tier` on retailers; and `retailer_id`, `issue_id` and `is_reorder` on orders, plus `title_id` and `creator_id` on statements."

    Design: Corner/endpoints/standard_crud_catalog_create_read_and_filtered_list_round_trip
    """
    fixtures.set_clock()
    catalog = fixtures.open_catalog(solicitation_month="2026-08")

    empty_rows, empty_meta = validate_paginated(
        api_client.list_catalogs(
            TEST_USERS["sales_director_headers"],
            params={"solicitation_month": "2026-09", "limit": 100, "offset": 0},
        )
    )
    assert empty_rows == []
    assert empty_meta["total_count"] == 0
    assert empty_meta["has_more"] is False

    matching_rows, matching_meta = validate_paginated(
        api_client.list_catalogs(
            TEST_USERS["sales_director_headers"],
            params={"solicitation_month": "2026-08", "limit": 100, "offset": 0},
        )
    )
    assert_ids_in_order(matching_rows, [catalog["id"]])
    assert matching_meta["total_count"] == 1


# ─── Print-run cancellation as an action endpoint ─────

def test_cancelling_a_planned_printing_stores_the_reason_and_leaves_printed_units_alone():
    """A `PLANNED` run cancels with its reason while the issue's printed units stand.

    PRD: "A `PLANNED` run may instead be cancelled by a `ManagingEditor`, capturing the supplied `reason` into `cancel_reason` and refreshing the issue's `printed_units` — a recompute that cannot change the figure, since a run that never printed contributed nothing to it."

    Design: Corner/endpoints/action_endpoint_print_run_cancel_takes_a_reason_and_refuses_a_printed_run
    """
    state = fixtures.setup_printed_issue(cover_specs=STANDARD_COVER_ONLY)
    issue_id = state["issue"]["id"]

    second_run = fixtures.plan_print_run(issue_id, basis="ORDER_DRIVEN")
    assert second_run["printing_number"] == 2
    assert second_run["quantity"] == 500

    cancelled = validate_success(
        api_client.cancel_print_run(
            second_run["id"],
            factories.print_run_cancel_payload(reason="plate damage at the printer"),
            TEST_USERS["managing_editor_headers"],
        )
    )
    assert cancelled["status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "plate damage at the printer"
    assert cancelled["printed_at"] is None
    # The figures stay on the cancelled row for the audit trail.
    assert cancelled["quantity"] == 500
    assert cancelled["printing_number"] == 2

    issue = fixtures.read_issue(issue_id)
    assert_issue_unit_ledgers(issue, printed_units=500)
    assert_issue_dimensions(issue, commercial_status="PRINTED")


def test_cancelling_a_printing_that_already_ran_is_refused():
    """`PRINTED` is terminal, so the presses cannot be un-run.

    PRD: "`PRINTED` and `CANCELLED` are both terminal for a run."

    Design: Corner/endpoints/action_endpoint_print_run_cancel_takes_a_reason_and_refuses_a_printed_run
    """
    state = fixtures.setup_printed_issue(cover_specs=STANDARD_COVER_ONLY)
    printed_run = state["print_run"]

    response = api_client.cancel_print_run(
        printed_run["id"],
        factories.print_run_cancel_payload(reason="too late"),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    unchanged = fixtures.read_print_run(printed_run["id"])
    assert unchanged["status"] == "PRINTED"
    assert unchanged["cancel_reason"] is None
    assert unchanged["printing_number"] == 1
    assert_issue_unit_ledgers(
        fixtures.read_issue(state["issue"]["id"]), printed_units=500
    )


# ─── The cut-off lock as a bulk action ────────────────

def test_the_cut_off_freezes_each_submitted_order_on_its_own_standard_quantity():
    """One lock computes each order's incentive earning separately, never an average.

    PRD: "It then walks that issue's `SUBMITTED` orders in ascending `created_at` order and, for each one, computes and freezes the earned incentive allocations and the order's `total_units`, then moves the order `SUBMITTED → FOC_LOCKED`."

    Design: Corner/endpoints/bulk_action_foc_lock_freezes_each_submitted_order_on_its_own_figures
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_AND_RATIO_TEN,
        order_overrides={"standard_qty": 100},
        extra_orders=(({}, {"standard_qty": 45}),),
    )
    ratio_cover_id = state["covers"]["B"]["id"]
    first_order, second_order = state["orders"]

    # 100 copies earn floor(100/10) == 10 of the 1-in-10 cover.
    assert_allocation_entries(first_order, [(ratio_cover_id, 10)])
    assert first_order["total_units"] == 110
    assert first_order["status"] == "FOC_LOCKED"

    # 45 copies earn floor(45/10) == 4 of the very same cover.
    assert_allocation_entries(second_order, [(ratio_cover_id, 4)])
    assert second_order["total_units"] == 49
    assert second_order["status"] == "FOC_LOCKED"

    rows, meta = validate_paginated(
        api_client.list_retailer_orders(
            TEST_USERS["sales_director_headers"],
            params={
                "issue_id": state["issue"]["id"],
                "status": "FOC_LOCKED",
                "limit": 100,
                "offset": 0,
            },
        )
    )
    assert_ids_in_order(rows, [first_order["id"], second_order["id"]])
    assert meta["total_count"] == 2


def test_the_cut_off_rolls_every_locked_order_into_the_issue_and_retailer_ledgers():
    """The issue totals both frozen orders while each retailer counts only its own.

    PRD: "An issue's `total_ordered_units` equals the sum of `total_units` over that issue's orders whose status is `FOC_LOCKED`, `INVOICED` or `SHIPPED`; its `shipped_units` equals the same sum restricted to orders whose status is `SHIPPED`; and its `printed_units` equals the sum of `quantity` over that issue's print runs whose status is `PRINTED`."

    Design: Corner/endpoints/bulk_action_foc_lock_freezes_each_submitted_order_on_its_own_figures
    """
    state = fixtures.setup_locked_order_book(
        cover_specs=STANDARD_AND_RATIO_TEN,
        order_overrides={"standard_qty": 100},
        extra_orders=(({}, {"standard_qty": 45}),),
    )
    first_retailer, second_retailer = state["retailers"]

    issue = fixtures.read_issue(state["issue"]["id"])
    # 110 + 49 = 159 units across the two locked rows.
    assert_issue_unit_ledgers(
        issue, total_ordered_units=159, printed_units=0, shipped_units=0
    )
    assert_issue_dimensions(issue, commercial_status="FOC_LOCKED")

    assert_retailer_ledgers(
        fixtures.read_retailer(first_retailer["id"]),
        cumulative_units_ytd=110,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(second_retailer["id"]),
        cumulative_units_ytd=49,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )


# ─── The title read as a computed resource ────────────

def test_title_read_reconciles_the_committed_share_production_cost_and_accrued_royalty():
    """One title read exposes three ledgers, each summed over its own input set.

    PRD: "An issue's production dimension is re-derived from the statuses of its production stages after every change to that stage set; a retailer's cumulative units and open balance are re-summed from that retailer's orders; an issue's ordered, printed and shipped unit counters are re-summed from its orders and print runs; a catalog's accepted slot count is re-counted from its solicitations; a title's committed royalty share, production cost and accrued royalty are re-summed from its assignments, stages and statements respectively."

    Design: Corner/endpoints/computed_read_title_read_reconciles_three_derived_ledgers_at_once
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    script = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    issue = fixtures.schedule_issue(title["id"])
    fixtures.run_stage_to_approved(
        issue["id"],
        script["id"],
        creator["id"],
        craft="SCRIPT",
        delivered_pages=22,
        planned_start_date="2026-08-05",
        planned_due_date="2026-09-20",
    )
    fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-12-01",
        booking_end_date="2026-12-20",
    )

    read_back = validate_success(
        api_client.get_title(title["id"], TEST_USERS["editor_in_chief_headers"])
    )
    assert read_back["committed_share_bps"] == 5000
    # 12000 cents per page over the 22 approved pages.
    assert read_back["production_cost_cents"] == 264000
    assert read_back["royalty_accrued_cents"] == 0
    assert read_back["status"] == "IN_PRODUCTION"


def test_committed_share_ignores_an_assignment_still_out_for_offer():
    """The 1500 bps of a `PROPOSED` offer never reach the title's committed share.

    PRD: "On success the assignment becomes `ACCEPTED` and the title's `committed_share_bps` — the sum of `royalty_share_bps` over its non-`COVER` assignments whose status is `ACCEPTED`, `ACTIVE` or `COMPLETED` — is recomputed."

    Design: Corner/endpoints/computed_read_title_read_reconciles_three_derived_ledgers_at_once
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    script = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    assert fixtures.read_title(title["id"])["committed_share_bps"] == 5000

    issue = fixtures.schedule_issue(title["id"])
    fixtures.run_stage_to_approved(
        issue["id"],
        script["id"],
        creator["id"],
        craft="SCRIPT",
        delivered_pages=22,
        planned_start_date="2026-08-05",
        planned_due_date="2026-09-20",
    )
    pencils = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-12-01",
        booking_end_date="2026-12-20",
    )
    assert pencils["status"] == "PROPOSED"

    # The script engagement is COMPLETED, which still qualifies; the offer does not.
    assert fixtures.read_assignment(script["id"])["status"] == "COMPLETED"
    assert fixtures.read_title(title["id"])["committed_share_bps"] == 5000


def test_title_assignment_list_returns_the_completed_offer_before_the_proposed_one():
    """The roster lists both assignments in the order they were created.

    PRD: "Unless a subsection states otherwise, list endpoints return rows sorted by their creation timestamp in ascending order."

    Design: Corner/endpoints/computed_read_title_read_reconciles_three_derived_ledgers_at_once
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    script = fixtures.offer_and_accept_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-12-01",
    )
    issue = fixtures.schedule_issue(title["id"])
    fixtures.run_stage_to_approved(
        issue["id"],
        script["id"],
        creator["id"],
        craft="SCRIPT",
        delivered_pages=22,
        planned_start_date="2026-08-05",
        planned_due_date="2026-09-20",
    )
    pencils = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-12-01",
        booking_end_date="2026-12-20",
    )

    rows, meta = validate_paginated(
        api_client.list_title_assignments(
            title["id"],
            TEST_USERS["editor_in_chief_headers"],
            params={"limit": 100, "offset": 0},
        )
    )
    assert_ids_in_order(rows, [script["id"], pencils["id"]])
    assert_field_sequence(rows, "status", ["COMPLETED", "PROPOSED"])
    assert meta["total_count"] == 2


# ─── Variant covers as a scoped cross-reference ───────

def test_solicitation_naming_a_cover_from_a_sibling_issue_is_refused():
    """A cover belonging to another issue of the same title cannot be advertised.

    PRD: "Identifiers named in a request body must resolve, each reporting its own code: `creator_id` yields `ERR_CREATOR_NOT_FOUND`, `assignment_id` yields `ERR_ASSIGNMENT_NOT_FOUND`, `issue_id` yields `ERR_ISSUE_NOT_FOUND`, `retailer_id` yields `ERR_RETAILER_NOT_FOUND`, `title_id` yields `ERR_TITLE_NOT_FOUND`, and a member of `variant_cover_ids` that does not exist, or that belongs to a different issue than the one being solicited, yields `ERR_VARIANT_COVER_NOT_FOUND`."

    Design: Corner/endpoints/cross_reference_link_solicitation_rejects_a_cover_from_another_issue
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    title_id = state["title"]["id"]
    first_issue = fixtures.schedule_issue(
        title_id, issue_number=1, target_on_sale_date="2026-10-14"
    )
    second_issue = fixtures.schedule_issue(
        title_id, issue_number=2, target_on_sale_date="2026-11-11"
    )
    own_cover = fixtures.add_cover(
        first_issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )
    foreign_cover = fixtures.add_cover(
        second_issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )
    catalog = fixtures.open_catalog()

    foreign_response = api_client.create_solicitation(
        catalog["id"],
        factories.solicitation_payload(
            first_issue["id"],
            variant_cover_ids=[own_cover["id"], foreign_cover["id"]],
        ),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(foreign_response, ApiErrorId.ERR_VARIANT_COVER_NOT_FOUND.value)

    stray_response = api_client.create_solicitation(
        catalog["id"],
        factories.solicitation_payload(
            first_issue["id"],
            variant_cover_ids=[own_cover["id"], NON_EXISTENT_UUID],
        ),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(stray_response, ApiErrorId.ERR_VARIANT_COVER_NOT_FOUND.value)

    rows, meta = validate_paginated(
        api_client.list_catalog_solicitations(
            catalog["id"],
            TEST_USERS["sales_director_headers"],
            params={"limit": 100, "offset": 0},
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_solicitation_listing_only_its_own_issue_cover_is_drafted():
    """With every named cover belonging to the solicited issue the listing is drafted.

    PRD: "A drafted listing is `DRAFT` with `submitted_at` and `withdrawn_reason` null."

    Design: Corner/endpoints/cross_reference_link_solicitation_rejects_a_cover_from_another_issue
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    title_id = state["title"]["id"]
    first_issue = fixtures.schedule_issue(
        title_id, issue_number=1, target_on_sale_date="2026-10-14"
    )
    second_issue = fixtures.schedule_issue(
        title_id, issue_number=2, target_on_sale_date="2026-11-11"
    )
    own_cover = fixtures.add_cover(
        first_issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )
    fixtures.add_cover(
        second_issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )
    catalog = fixtures.open_catalog()

    drafted = validate_success(
        api_client.create_solicitation(
            catalog["id"],
            factories.solicitation_payload(
                first_issue["id"], variant_cover_ids=[own_cover["id"]]
            ),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )
    assert drafted["status"] == "DRAFT"
    assert drafted["submitted_at"] is None
    assert drafted["withdrawn_reason"] is None
    assert drafted["issue_id"] == first_issue["id"]
    assert drafted["catalog_id"] == catalog["id"]
    assert drafted["variant_cover_ids"] == [own_cover["id"]]


def test_a_drafted_listing_occupies_no_catalog_slot():
    """A `DRAFT` solicitation leaves the catalog's accepted slot count at zero.

    PRD: "A catalog's `accepted_slot_count` equals the count of that catalog's solicitations whose status is `ACCEPTED`; `DRAFT`, `SUBMITTED` and `WITHDRAWN` rows never occupy a slot."

    Design: Corner/endpoints/cross_reference_link_solicitation_rejects_a_cover_from_another_issue
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    title_id = state["title"]["id"]
    first_issue = fixtures.schedule_issue(
        title_id, issue_number=1, target_on_sale_date="2026-10-14"
    )
    own_cover = fixtures.add_cover(
        first_issue["id"], code="A", kind="STANDARD", cover_price_cents=399
    )
    catalog = fixtures.open_catalog()

    drafted = fixtures.draft_solicitation(
        catalog["id"], first_issue["id"], variant_cover_ids=[own_cover["id"]]
    )
    assert drafted["status"] == "DRAFT"

    read_back = validate_success(
        api_client.get_catalog(catalog["id"], TEST_USERS["sales_director_headers"])
    )
    assert read_back["accepted_slot_count"] == 0
    assert read_back["status"] == "OPEN"


# ─── Shipping conditional on the printing ─────────────

def test_shipping_before_the_printing_covers_the_order_book_is_refused():
    """An `INVOICED` order cannot ship while the printing is still only planned.

    PRD: "A `SalesDirector` moves an `INVOICED` order to `SHIPPED`, which is permitted only when the issue's `printed_units` is at least its `total_ordered_units` — an under-printed issue cannot ship, and the refusal is `ERR_PRINT_NOT_COMPLETE`."

    Design: Corner/endpoints/conditional_action_ship_is_allowed_only_once_the_print_run_covers_the_order_book
    """
    state = fixtures.setup_locked_order_book(
        camera_ready=True,
        cover_specs=STANDARD_COVER_ONLY,
        order_overrides={"standard_qty": 100},
    )
    issue_id = state["issue"]["id"]
    order_id = state["order"]["id"]

    planned_run = fixtures.plan_print_run(issue_id, basis="ORDER_DRIVEN")
    assert planned_run["status"] == "PLANNED"
    fixtures.invoice_order(order_id)
    assert_issue_unit_ledgers(
        fixtures.read_issue(issue_id), total_ordered_units=100, printed_units=0
    )

    response = api_client.ship_retailer_order(
        order_id, TEST_USERS["sales_director_headers"]
    )
    validate_error(response, ApiErrorId.ERR_PRINT_NOT_COMPLETE.value)

    unchanged = fixtures.read_order(order_id)
    assert unchanged["status"] == "INVOICED"
    assert_issue_unit_ledgers(fixtures.read_issue(issue_id), shipped_units=0)


def test_shipping_a_printed_issue_recognises_print_revenue_for_the_clock_month():
    """The shipment writes one `PRINT_DM` `SHIPMENT` event on the order's own figures.

    PRD: "Shipment appends one immutable revenue event for that issue with `channel` `PRINT_DM`, `basis_status` `ACTUAL`, `source` `SHIPMENT`, `gross_receipts_cents` equal to the sum of the ordered lines' gross amounts (before any discount), `net_receipts_cents` equal to the order's `merchandise_net_cents`, `units` equal to the order's `total_units`, and `period` set to the `YYYY-MM` month of the logical clock."

    Design: Corner/endpoints/conditional_action_ship_is_allowed_only_once_the_print_run_covers_the_order_book
    """
    state = fixtures.setup_locked_order_book(
        camera_ready=True,
        cover_specs=STANDARD_COVER_ONLY,
        order_overrides={"standard_qty": 100},
    )
    issue_id = state["issue"]["id"]
    order_id = state["order"]["id"]

    fixtures.plan_and_complete_print_run(issue_id, basis="ORDER_DRIVEN")
    invoiced = fixtures.invoice_order(order_id)
    assert invoiced["merchandise_net_cents"] == 23940

    shipped = validate_success(
        api_client.ship_retailer_order(order_id, TEST_USERS["sales_director_headers"])
    )
    assert shipped["status"] == "SHIPPED"

    rows, meta = validate_paginated(
        api_client.list_issue_revenue_events(
            issue_id,
            TEST_USERS["sales_director_headers"],
            params={"limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    event = rows[0]
    assert event["channel"] == "PRINT_DM"
    assert event["basis_status"] == "ACTUAL"
    assert event["source"] == "SHIPMENT"
    # 100 standard copies at 399 gross, discounted 40% to 23940 net.
    assert event["gross_receipts_cents"] == 39900
    assert event["net_receipts_cents"] == 23940
    assert event["units"] == 100
    assert event["period"] == "2026-09"

    issue = fixtures.read_issue(issue_id)
    assert_issue_unit_ledgers(issue, shipped_units=100, printed_units=500)
    assert_issue_dimensions(issue, commercial_status="PRINTED")


def test_a_shipped_order_keeps_its_invoice_on_the_retailer_open_balance():
    """Shipping does not clear the balance: an `INVOICED` or `SHIPPED` order still counts.

    PRD: "A retailer's `open_balance_cents` equals the sum of `invoice_total_cents` over that retailer's orders whose status is `INVOICED` or `SHIPPED`."

    Design: Corner/endpoints/conditional_action_ship_is_allowed_only_once_the_print_run_covers_the_order_book
    """
    state = fixtures.setup_locked_order_book(
        camera_ready=True,
        cover_specs=STANDARD_COVER_ONLY,
        order_overrides={"standard_qty": 100},
    )
    issue_id = state["issue"]["id"]
    order_id = state["order"]["id"]
    retailer_id = state["retailer"]["id"]

    fixtures.plan_and_complete_print_run(issue_id, basis="ORDER_DRIVEN")
    fixtures.invoice_order(order_id)
    # 23940 merchandise plus the 995 handling fee.
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_id), open_balance_cents=24935
    )

    fixtures.ship_order(order_id)
    assert fixtures.read_order(order_id)["invoice_total_cents"] == 24935
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer_id),
        cumulative_units_ytd=100,
        open_balance_cents=24935,
        discount_tier="ENTRY",
    )
