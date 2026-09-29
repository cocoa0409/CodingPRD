"""Stale-parent protection, the top tier boundary and in-request cascade visibility."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_invoice_figures,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_print_run_quantities,
    assert_retailer_ledgers,
    assert_version_unchanged,
    assert_versioned_record,
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

# One STANDARD cover only, so an order's `total_units` is exactly its `standard_qty`.
STANDARD_COVER_ONLY = (fixtures.DEFAULT_COVER_SPECS[0],)

# A second booking for the same all-craft creator whose half-open window merely
# touches the first one, so nothing but the version check can refuse it.
PENCILS_OFFER = {
    "craft": "PENCILS",
    "page_rate_cents": 9000,
    "royalty_share_bps": 1500,
    "booking_start_date": "2026-09-01",
    "booking_end_date": "2026-10-01",
}


def build_title_with_one_accepted_script_booking() -> dict:
    """A greenlit title whose first booking has already moved the title's `version`.

    `observed_version` is the version the client read from the greenlight
    response and spent on the `SCRIPT` offer.
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    observed_version = title["version"]

    assignment = validate_success(
        api_client.create_creative_assignment(
            title["id"],
            factories.assignment_payload(
                creator["id"],
                observed_version,
                craft="SCRIPT",
                page_rate_cents=12000,
                royalty_share_bps=5000,
                booking_start_date="2026-08-01",
                booking_end_date="2026-09-01",
            ),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )
    fixtures.accept_assignment(assignment["id"], creator["id"])

    return {
        "creator": creator,
        "title": title,
        "observed_version": observed_version,
        "assignment": assignment,
    }


def build_locked_order_book_observed_before_the_cut_off() -> dict:
    """A camera-ready issue read while its order book was still open, then locked.

    `observed_version` is the issue version a production planner captured while
    the issue was `SOLICITED` and its 100-copy order was still only `SUBMITTED`.
    """
    state = fixtures.setup_camera_ready_issue(delivery_clock="2026-08-19T00:00:00Z")
    issue_id = state["issue"]["id"]
    state.update(fixtures.solicit_issue(issue_id, cover_specs=STANDARD_COVER_ONLY))

    retailer = fixtures.open_retailer()
    order = fixtures.draft_and_submit_order(retailer["id"], issue_id, standard_qty=100)
    observed_version = fixtures.issue_version(issue_id)

    fixtures.set_clock("2026-09-23T00:00:00Z")
    locked_issue = fixtures.foc_lock(issue_id)

    state.update(
        {
            "retailer": retailer,
            "order": fixtures.read_order(order["id"]),
            "observed_version": observed_version,
            "issue": locked_issue,
        }
    )
    return state


def build_two_accounts_astride_the_premier_boundary() -> dict:
    """Two accounts whose locked orders land one on 25,000 units and one on 24,999."""
    return fixtures.setup_locked_order_book(
        cover_specs=STANDARD_COVER_ONLY,
        retailer_overrides={"opening_units_ytd": 24900, "credit_limit_cents": 90_000_000},
        extra_orders=(
            ({"opening_units_ytd": 24899, "credit_limit_cents": 90_000_000}, {}),
        ),
    )


def build_submitted_order_at_the_cut_off_instant() -> dict:
    """A solicited issue with one submitted 100-copy order, the clock on its FOC date."""
    state = fixtures.setup_solicited_issue_in_scripting(cover_specs=STANDARD_COVER_ONLY)
    retailer = fixtures.open_retailer(opening_units_ytd=2400)
    order = fixtures.draft_and_submit_order(
        retailer["id"], state["issue"]["id"], standard_qty=100
    )
    fixtures.set_clock("2026-09-23T00:00:00Z")
    state.update({"retailer": retailer, "order": order})
    return state


def test_replaying_the_title_version_the_first_booking_spent_is_refused_for_free():
    """A second offer carrying the already-consumed title version is refused at 412.

    PRD: "If that number does not equal the title's current `version`, the request is rejected with `ERR_STALE_TITLE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_a_replayed_title_version_is_refused_and_the_refreshed_one_is_accepted
    """
    state = build_title_with_one_accepted_script_booking()
    title_id = state["title"]["id"]
    before = fixtures.read_title(title_id)

    response = api_client.create_creative_assignment(
        title_id,
        factories.assignment_payload(
            state["creator"]["id"], state["observed_version"], **PENCILS_OFFER
        ),
        TEST_USERS["editor_in_chief_headers"],
    )
    validate_error(response, ApiErrorId.ERR_STALE_TITLE_VERSION.value)

    # The refusal costs nothing: no row, no counter bump, no further version bump.
    after = fixtures.read_title(title_id)
    assert_version_unchanged(before, after)
    assert after["committed_share_bps"] == 5000
    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 1

    rows, meta = validate_paginated(
        api_client.list_title_assignments(
            title_id, TEST_USERS["editor_in_chief_headers"]
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == state["assignment"]["id"]


def test_the_refreshed_title_version_lets_the_identical_booking_through_as_proposed():
    """Re-reading the title yields the version that the same offer body needs.

    PRD: "Creating a creative assignment under a title requires `expected_title_version` in the request body, carrying the client's last observed `version` of that `Title`."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_a_replayed_title_version_is_refused_and_the_refreshed_one_is_accepted
    """
    state = build_title_with_one_accepted_script_booking()
    title_id = state["title"]["id"]

    refreshed_version = fixtures.title_version(title_id)
    assert refreshed_version != state["observed_version"]

    created = validate_success(
        api_client.create_creative_assignment(
            title_id,
            factories.assignment_payload(
                state["creator"]["id"], refreshed_version, **PENCILS_OFFER
            ),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )
    assert_versioned_record(created)
    assert created["craft"] == "PENCILS"
    assert created["status"] == "PROPOSED"
    assert created["negotiation_round"] == 1

    assert fixtures.read_creator(state["creator"]["id"])["active_assignment_count"] == 2
    # A PROPOSED share is not committed, so the royalty pool has not moved.
    assert fixtures.read_title(title_id)["committed_share_bps"] == 5000


def test_a_pre_cut_off_issue_version_no_longer_authorises_a_printing():
    """The cut-off lock invalidates the issue version a planner read before it.

    PRD: "If that number does not equal the issue's current `version`, the request is rejected with `ERR_STALE_ISSUE_VERSION` and HTTP 412."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_the_foc_lock_invalidates_a_pre_lock_issue_version
    """
    state = build_locked_order_book_observed_before_the_cut_off()
    issue_id = state["issue"]["id"]
    editor = TEST_USERS["managing_editor_headers"]
    before = fixtures.read_issue(issue_id)

    response = api_client.create_print_run(
        issue_id,
        factories.print_run_payload(state["observed_version"], basis="ORDER_DRIVEN"),
        editor,
    )
    validate_error(response, ApiErrorId.ERR_STALE_ISSUE_VERSION.value)

    after = fixtures.read_issue(issue_id)
    assert_version_unchanged(before, after)
    assert_issue_dimensions(
        after, production_status="CAMERA_READY", commercial_status="FOC_LOCKED"
    )
    assert_issue_unit_ledgers(after, total_ordered_units=100, printed_units=0)

    rows, meta = validate_paginated(api_client.list_print_runs(issue_id, editor))
    assert meta["total_count"] == 0
    assert rows == []


def test_the_post_lock_issue_version_prints_five_hundred_copies_from_the_locked_book():
    """With the version re-read, the identical body sizes the run from 100 locked units.

    PRD: "Second printings and reprints legitimately stack on top of earlier runs, so a repeat creation is not blocked by state; the stale-version check ensures the ordering figures the run quantity is derived from are the ones the client actually observed."

    Design: Corner/cross_cutting_complexity_layers/optimistic_concurrency_the_foc_lock_invalidates_a_pre_lock_issue_version
    """
    state = build_locked_order_book_observed_before_the_cut_off()
    issue_id = state["issue"]["id"]

    refreshed_version = fixtures.issue_version(issue_id)
    assert refreshed_version != state["observed_version"]

    # 100 locked units + 8 overprint + 150 reserve = 258, lifted to the 500 minimum.
    print_run = validate_success(
        api_client.create_print_run(
            issue_id,
            factories.print_run_payload(refreshed_version, basis="ORDER_DRIVEN"),
            TEST_USERS["managing_editor_headers"],
        ),
        expected_status=201,
    )
    assert_print_run_quantities(
        print_run,
        order_base_units=100,
        overprint_units=8,
        quantity=500,
        printing_number=1,
    )
    assert print_run["status"] == "PLANNED"
    assert print_run["printed_at"] is None
    assert_issue_unit_ledgers(
        fixtures.read_issue(issue_id), total_ordered_units=100, printed_units=0
    )


def test_the_twenty_five_thousandth_unit_promotes_to_premier_while_one_short_stays_core():
    """25,000 cumulative units is already `PREMIER`; 24,999 is still `CORE`.

    PRD: "Volume earns discount, and the tier is a pure function of `cumulative_units_ytd` with inclusive thresholds: from 25,000 cumulative units upwards the account is `PREMIER`; from 10,000 up to but not reaching 25,000 it is `CORE`; from 2,500 up to but not reaching 10,000 it is `BASIC`; and below 2,500 it is `ENTRY`."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_triggers_premier_at_25000_units_versus_core_at_24999
    """
    state = build_two_accounts_astride_the_premier_boundary()
    promoted, held_back = state["retailers"]

    # Both accounts opened below the boundary, on their opening units alone.
    assert promoted["discount_tier"] == "CORE"
    assert held_back["discount_tier"] == "CORE"

    assert_retailer_ledgers(
        fixtures.read_retailer(promoted["id"]),
        cumulative_units_ytd=25000,
        discount_tier="PREMIER",
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(held_back["id"]),
        cumulative_units_ytd=24999,
        discount_tier="CORE",
    )

    for order in state["orders"]:
        assert order["status"] == "FOC_LOCKED"
        assert order["standard_qty"] == 100
        assert order["total_units"] == 100
        assert order["earned_variant_allocations"] == []
    assert_issue_unit_ledgers(state["issue"], total_ordered_units=200)


def test_one_unit_of_volume_rebills_the_identical_hundred_copy_order():
    """The same 100 copies bill at 17955 cents on `PREMIER` and 19950 on `CORE`.

    PRD: "The discount attached to each tier is 40 percent at `ENTRY`, 45 percent at `BASIC`, 50 percent at `CORE` and 55 percent at `PREMIER`, so the fraction actually billed is one minus that discount."

    Design: Corner/cross_cutting_complexity_layers/rate_threshold_triggers_premier_at_25000_units_versus_core_at_24999
    """
    state = build_two_accounts_astride_the_premier_boundary()
    promoted, held_back = state["retailers"]
    sales_director = TEST_USERS["sales_director_headers"]

    # 100 copies at 399 gross 39900: 45% of it is 17955, 50% of it is 19950.
    premier_invoice = validate_success(
        api_client.invoice_retailer_order(state["orders"][0]["id"], sales_director)
    )
    core_invoice = validate_success(
        api_client.invoice_retailer_order(state["orders"][1]["id"], sales_director)
    )

    assert_invoice_figures(
        premier_invoice,
        discount_tier_applied="PREMIER",
        merchandise_net_cents=17955,
        handling_fee_cents=995,
        invoice_total_cents=18950,
    )
    assert_invoice_figures(
        core_invoice,
        discount_tier_applied="CORE",
        merchandise_net_cents=19950,
        handling_fee_cents=995,
        invoice_total_cents=20945,
    )
    assert core_invoice["merchandise_net_cents"] - premier_invoice["merchandise_net_cents"] == 1995

    assert_retailer_ledgers(
        fixtures.read_retailer(promoted["id"]), open_balance_cents=18950
    )
    assert_retailer_ledgers(
        fixtures.read_retailer(held_back["id"]), open_balance_cents=20945
    )


def test_the_cut_off_response_body_already_carries_the_recomputed_roll_ups():
    """The lock's own response, and the very next reads, already show every hop.

    PRD: "Downstream in the same request, each affected retailer's `cumulative_units_ytd` is refreshed and its `discount_tier` re-derived, and the issue's `total_ordered_units` is refreshed."

    Design: Corner/consistency_model/immediate_every_cascade_is_readable_in_the_same_request_with_no_polling
    """
    state = build_submitted_order_at_the_cut_off_instant()
    retailer = state["retailer"]
    assert_retailer_ledgers(
        retailer, cumulative_units_ytd=2400, discount_tier="ENTRY", open_balance_cents=0
    )

    locked_issue = validate_success(
        api_client.foc_lock_issue(
            state["issue"]["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert_issue_dimensions(locked_issue, commercial_status="FOC_LOCKED")
    assert_issue_unit_ledgers(locked_issue, total_ordered_units=100, printed_units=0)

    # No second call is needed for the retailer and order ledgers to settle.
    assert_retailer_ledgers(
        fixtures.read_retailer(retailer["id"]),
        cumulative_units_ytd=2500,
        discount_tier="BASIC",
    )
    locked_order = fixtures.read_order(state["order"]["id"])
    assert locked_order["status"] == "FOC_LOCKED"
    assert locked_order["total_units"] == 100


def test_the_invoice_response_body_already_carries_the_refreshed_open_balance():
    """The invoice figures and the balance they feed are readable with no re-settling.

    PRD: "Once the invoice is written, the retailer's `open_balance_cents` is refreshed from its invoiced and shipped orders."

    Design: Corner/consistency_model/immediate_every_cascade_is_readable_in_the_same_request_with_no_polling
    """
    state = build_submitted_order_at_the_cut_off_instant()
    retailer_id = state["retailer"]["id"]
    fixtures.foc_lock(state["issue"]["id"])

    # 100 copies at 399 gross 39900; the BASIC tier bills 55% of it, 21945 cents.
    invoiced = validate_success(
        api_client.invoice_retailer_order(
            state["order"]["id"], TEST_USERS["sales_director_headers"]
        )
    )
    assert invoiced["status"] == "INVOICED"
    assert_invoice_figures(
        invoiced,
        discount_tier_applied="BASIC",
        merchandise_net_cents=21945,
        handling_fee_cents=995,
        invoice_total_cents=22940,
    )

    first_read = fixtures.read_retailer(retailer_id)
    assert_retailer_ledgers(
        first_read,
        cumulative_units_ytd=2500,
        discount_tier="BASIC",
        open_balance_cents=22940,
    )
    # Re-reading changes nothing: there is no queue behind these figures.
    second_read = fixtures.read_retailer(retailer_id)
    assert second_read == first_read
    assert fixtures.read_order(state["order"]["id"]) == fixtures.read_order(
        state["order"]["id"]
    )
