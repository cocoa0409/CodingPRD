"""Entity shapes: declared fields, omitted-input defaults and system-managed values."""

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    api_client,
    assert_date_equals,
    assert_field_sequence,
    assert_ids_in_order,
    assert_immutable_record,
    assert_instant_equals,
    assert_issue_dimensions,
    assert_issue_unit_ledgers,
    assert_retailer_ledgers,
    assert_versioned_record,
    factories,
    fixtures,
    is_valid_uuid,
    make_retailer_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS


def test_pitching_a_title_returns_it_pitched_with_zeroed_ledgers():
    """A pitch returns 201 with the four declared inputs echoed and every ledger at 0.

    PRD: "A newly pitched title arrives in status `PITCHED` with `committed_share_bps`, `production_cost_cents` and `royalty_accrued_cents` all at 0, and with `greenlit_at` and `cancel_reason` both null."

    Design: Corner/entities/creation_of_a_title_returns_all_declared_fields_at_pitched
    """
    fixtures.set_clock()

    title = validate_success(
        api_client.create_title(
            factories.title_payload(
                name="Nebula Knights",
                planned_issue_count=6,
                royalty_pool_bps=1200,
                cover_participation_bps=1500,
            ),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )

    assert title["name"] == "Nebula Knights"
    assert title["planned_issue_count"] == 6
    assert title["royalty_pool_bps"] == 1200
    assert title["cover_participation_bps"] == 1500
    assert title["status"] == "PITCHED"
    assert title["greenlit_at"] is None
    assert title["cancel_reason"] is None
    assert title["committed_share_bps"] == 0
    assert title["production_cost_cents"] == 0
    assert title["royalty_accrued_cents"] == 0
    assert_versioned_record(title, expected_version=1)


def test_a_fresh_issue_reports_a_foc_date_three_weeks_before_its_on_sale_date():
    """An issue targeted at 2026-11-11 carries a `foc_date` of 2026-10-21 at midnight UTC.

    PRD: "The service derives the issue's Final Order Cut-off, `foc_date`, as the `target_on_sale_date` less three calendar weeks — twenty-one calendar days earlier."

    Design: Corner/entities/retrieval_of_an_issue_exposes_the_computed_foc_date_and_health_defaults
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(
        state["title"]["id"], target_on_sale_date="2026-11-11"
    )

    read = validate_success(
        api_client.get_issue(issue["id"], TEST_USERS["managing_editor_headers"])
    )

    assert_date_equals(read["target_on_sale_date"], "2026-11-11")
    assert_date_equals(read["foc_date"], "2026-10-21")
    assert_instant_equals(read["foc_date"], "2026-10-21T00:00:00Z")


def test_a_fresh_issue_starts_planned_unsolicited_and_on_track_with_no_units():
    """A newly scheduled issue carries both starting dimensions, zero slip and zero units.

    PRD: "A new issue starts with `production_status` `PLANNED`, `commercial_status` `UNSOLICITED`, `schedule_health` `ON_TRACK`, `total_slip_days`, `total_ordered_units`, `printed_units` and `shipped_units` all 0, and `on_sale_date` null."

    Design: Corner/entities/retrieval_of_an_issue_exposes_the_computed_foc_date_and_health_defaults
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(
        state["title"]["id"],
        page_count=22,
        cover_price_cents=399,
        target_on_sale_date="2026-11-11",
    )

    read = validate_success(
        api_client.get_issue(issue["id"], TEST_USERS["managing_editor_headers"])
    )

    assert_issue_dimensions(
        read,
        production_status="PLANNED",
        commercial_status="UNSOLICITED",
        schedule_health="ON_TRACK",
    )
    assert read["total_slip_days"] == 0
    assert_issue_unit_ledgers(
        read, total_ordered_units=0, printed_units=0, shipped_units=0
    )
    assert read["on_sale_date"] is None
    assert read["page_count"] == 22
    assert read["cover_price_cents"] == 399
    assert_versioned_record(read, expected_version=1)


def test_retailer_pages_report_total_count_and_has_more_across_the_page_boundary():
    """With three accounts, `limit` 2 pages report total_count 3 and flip `has_more`.

    PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more` inside the `meta` object of the envelope, where `total_count` is the number of rows matching the filters before pagination is applied and `has_more` states whether further rows exist beyond the current page."

    Design: Corner/entities/listing_retailers_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock()
    first = fixtures.open_retailer(
        account_no="DM-2001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    second = fixtures.open_retailer(
        account_no="DM-2002", name="Splash Page Comics", credit_limit_cents=5_000_000
    )
    third = fixtures.open_retailer(
        account_no="DM-2003", name="Gutter Books", credit_limit_cents=5_000_000
    )

    page_one, meta_one = validate_paginated(
        api_client.list_retailers(
            TEST_USERS["sales_director_headers"], {"limit": 2, "offset": 0}
        )
    )
    page_two, meta_two = validate_paginated(
        api_client.list_retailers(
            TEST_USERS["sales_director_headers"], {"limit": 2, "offset": 2}
        )
    )

    assert len(page_one) == 2
    assert meta_one["limit"] == 2
    assert meta_one["offset"] == 0
    assert meta_one["total_count"] == 3
    assert meta_one["has_more"] is True
    assert_ids_in_order(page_one, [first["id"], second["id"]])

    assert len(page_two) == 1
    assert meta_two["offset"] == 2
    assert meta_two["total_count"] == 3
    assert meta_two["has_more"] is False
    assert_ids_in_order(page_two, [third["id"]])


def test_retailer_listing_returns_new_accounts_in_creation_order_at_entry_tier():
    """A filtered full page lists all three accounts oldest-first, each `ENTRY` at zero units.

    PRD: "Unless a subsection states otherwise, list endpoints return rows sorted by their creation timestamp in ascending order."

    Design: Corner/entities/listing_retailers_paginates_with_total_count_and_has_more
    """
    fixtures.set_clock()
    first = fixtures.open_retailer(
        account_no="DM-2001", name="Panel Palace", credit_limit_cents=5_000_000
    )
    second = fixtures.open_retailer(
        account_no="DM-2002", name="Splash Page Comics", credit_limit_cents=5_000_000
    )
    third = fixtures.open_retailer(
        account_no="DM-2003", name="Gutter Books", credit_limit_cents=5_000_000
    )

    rows, meta = validate_paginated(
        api_client.list_retailers(
            TEST_USERS["sales_director_headers"],
            {"status": "ACTIVE", "limit": 100, "offset": 0},
        )
    )

    assert meta["total_count"] == 3
    assert meta["has_more"] is False
    assert_ids_in_order(rows, [first["id"], second["id"], third["id"]])
    assert_field_sequence(rows, "account_no", ["DM-2001", "DM-2002", "DM-2003"])
    assert_field_sequence(rows, "discount_tier", ["ENTRY", "ENTRY", "ENTRY"])
    assert_field_sequence(rows, "cumulative_units_ytd", [0, 0, 0])


def test_reading_an_absent_solicitation_reports_the_solicitation_not_found_code():
    """A well-formed but unknown solicitation id reads back as a 404 error envelope.

    PRD: "Each identifier has its own 404 code — `ERR_TITLE_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_CREATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND` — and the code reported is the one belonging to the leftmost missing segment."

    Design: Corner/entities/get_unknown_solicitation_id_returns_err_solicitation_not_found
    """
    fixtures.set_clock()

    response = api_client.get_solicitation(
        NON_EXISTENT_UUID, TEST_USERS["sales_director_headers"]
    )

    error = validate_error(response, ApiErrorId.ERR_SOLICITATION_NOT_FOUND.value)
    assert response.json()["response_type"] == "error"
    assert error["message"].strip() != ""


def test_scheduling_an_issue_without_a_page_count_is_refused_and_writes_nothing():
    """Omitting the required `page_count` is a 400 that leaves the slate and the title alone.

    PRD: "Required fields present, types correct, enum members legal, integers inside their declared ranges, `YYYY-MM` month strings well formed, `booking_end_date` strictly after `booking_start_date`, `planned_due_date` on or after `planned_start_date`, `on_sale_month` strictly after `solicitation_month`, `net_receipts_cents` no greater than `gross_receipts_cents`, `limit` between 1 and 100 and `offset` not negative — otherwise `ERR_INVALID_REQUEST` (400)."

    Design: Corner/entities/issue_creation_missing_required_page_count_is_rejected
    """
    fixtures.set_clock()
    title = fixtures.pitch_and_greenlight_title()

    response = api_client.create_issue(
        title["id"],
        {
            "issue_number": 1,
            "cover_price_cents": 399,
            "target_on_sale_date": "2026-10-14",
        },
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api_client.list_title_issues(
            title["id"],
            TEST_USERS["managing_editor_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fixtures.read_title(title["id"])["status"] == "GREENLIT"


def test_a_retailer_opened_without_opening_units_starts_at_zero_and_entry_tier():
    """An omitted `opening_units_ytd` defaults to 0, so the account opens `ENTRY` at zero.

    PRD: "Retailer accounts are opened by a `SalesDirector` with a unique `account_no`, a store `name`, a `credit_limit_cents` of at least 0 bounding the open balance the account may carry, the `non_returnable_ack` acknowledgement flag of §2.11, and an optional `opening_units_ytd` of at least 0 recording units already billed this year before this system took over the account (defaulting to 0)."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fixtures.set_clock()

    retailer = validate_success(
        api_client.create_retailer(
            {
                "account_no": "DM-2001",
                "name": "Panel Palace",
                "credit_limit_cents": 5_000_000,
                "non_returnable_ack": True,
            },
            TEST_USERS["sales_director_headers"],
        ),
        expected_status=201,
    )

    assert retailer["opening_units_ytd"] == 0
    assert_retailer_ledgers(
        retailer,
        cumulative_units_ytd=0,
        open_balance_cents=0,
        discount_tier="ENTRY",
    )
    assert retailer["status"] == "ACTIVE"
    assert retailer["suspension_reason"] is None
    assert_versioned_record(retailer, expected_version=1)


def test_an_offer_without_an_advance_carries_a_zero_unrecouped_advance():
    """An omitted `advance_cents` defaults to 0 and initialises the unrecouped balance to 0.

    PRD: "The offer names the `creator_id` of the person being hired, the `craft` slot being filled (one of the same six craft values), the `page_rate_cents` offered per delivered page (at least 0), the `royalty_share_bps` offered out of the post-cover remainder (from 0 to 10000 basis points), the half-open studio booking window `booking_start_date` (inclusive) and `booking_end_date` (exclusive, and strictly later than the start), an optional recoupable `advance_cents` that defaults to 0, and the `expected_title_version` demanded by §2.9."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    fixtures.set_clock()
    creator = fixtures.register_creator()
    title = fixtures.pitch_and_greenlight_title()

    payload = factories.assignment_payload(
        creator["id"], fixtures.title_version(title["id"]), craft="SCRIPT"
    )
    del payload["advance_cents"]

    assignment = validate_success(
        api_client.create_creative_assignment(
            title["id"], payload, TEST_USERS["editor_in_chief_headers"]
        ),
        expected_status=201,
    )

    assert assignment["advance_cents"] == 0
    assert assignment["unrecouped_advance_cents"] == 0
    assert assignment["status"] == "PROPOSED"
    assert assignment["negotiation_round"] == 1
    assert assignment["counter_page_rate_cents"] is None
    assert assignment["counter_royalty_share_bps"] is None
    assert assignment["terminated_reason"] is None


def test_a_drafted_order_carries_no_allocations_and_no_invoice_figures():
    """A drafted order arrives with an empty allocation array and every money figure at 0.

    PRD: "The draft arrives `DRAFT` with `total_units` 0, `earned_variant_allocations` empty, `discount_tier_applied` null, `merchandise_net_cents`, `handling_fee_cents` and `invoice_total_cents` all 0, and `cancel_reason` null."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])
    retailer = fixtures.open_retailer()

    order = validate_success(
        api_client.create_retailer_order(
            {
                "retailer_id": retailer["id"],
                "issue_id": issue["id"],
                "standard_qty": 100,
            },
            make_retailer_headers(retailer["id"]),
        ),
        expected_status=201,
    )

    assert order["status"] == "DRAFT"
    assert order["total_units"] == 0
    assert order["earned_variant_allocations"] == []
    assert order["discount_tier_applied"] is None
    assert order["merchandise_net_cents"] == 0
    assert order["handling_fee_cents"] == 0
    assert order["invoice_total_cents"] == 0
    assert order["cancel_reason"] is None


def test_an_order_omitting_the_exclusive_request_defaults_it_to_zero_and_is_not_a_reorder():
    """An omitted `exclusive_variant_qty` defaults to 0 against an issue that is not on sale.

    PRD: "A `Retailer` drafts an order for itself, naming the `retailer_id` (which must equal `X-User-ID`), the `issue_id` ordered, the `standard_qty` of standard-cover copies wanted (at least 1 — this is the only quantity that earns incentive covers), and optionally an `exclusive_variant_qty` of retailer-exclusive copies requested, defaulting to 0."

    Design: Corner/entities/omitted_optional_inputs_fall_back_to_their_declared_defaults
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(state["title"]["id"])
    retailer = fixtures.open_retailer()

    order = validate_success(
        api_client.create_retailer_order(
            {
                "retailer_id": retailer["id"],
                "issue_id": issue["id"],
                "standard_qty": 100,
            },
            make_retailer_headers(retailer["id"]),
        ),
        expected_status=201,
    )

    assert order["exclusive_variant_qty"] == 0
    assert order["standard_qty"] == 100
    assert order["is_reorder"] is False
    assert order["retailer_id"] == retailer["id"]
    assert order["issue_id"] == issue["id"]


def test_active_assignment_count_counts_the_proposed_row_beside_the_accepted_one():
    """One `ACCEPTED` and one `PROPOSED` assignment put the creator's open count at 2.

    PRD: "The creator's `active_assignment_count`, which starts at 0, is a derived count of that creator's assignments whose status is `PROPOSED`, `COUNTERED`, `ACCEPTED` or `ACTIVE`."

    Design: Corner/entities/computed_creator_active_assignment_count_counts_only_open_assignments
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 0

    script = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-08-05",
    )
    fixtures.accept_assignment(script["id"], creator["id"])
    fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-08-05",
        booking_end_date="2026-08-10",
    )

    read = validate_success(
        api_client.get_creator(
            creator["id"], TEST_USERS["editor_in_chief_headers"]
        )
    )
    assert read["active_assignment_count"] == 2


def test_terminating_the_proposed_offer_drops_the_creator_s_open_assignment_count():
    """Terminating the `PROPOSED` row leaves the count at 1 and the committed share at 5000.

    PRD: "Termination captures the supplied `reason` into `terminated_reason`, moves the assignment to `TERMINATED`, and refreshes both the title's `committed_share_bps` and the creator's `active_assignment_count`."

    Design: Corner/entities/computed_creator_active_assignment_count_counts_only_open_assignments
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()
    title = fixtures.pitch_and_greenlight_title()

    script = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "SCRIPT",
        page_rate_cents=12000,
        royalty_share_bps=5000,
        booking_start_date="2026-08-01",
        booking_end_date="2026-08-05",
    )
    fixtures.accept_assignment(script["id"], creator["id"])
    pencils = fixtures.offer_assignment(
        title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-08-05",
        booking_end_date="2026-08-10",
    )

    terminated = validate_success(
        api_client.terminate_creative_assignment(
            pencils["id"],
            factories.terminate_payload(reason="artist unavailable"),
            TEST_USERS["editor_in_chief_headers"],
        )
    )

    assert terminated["status"] == "TERMINATED"
    assert terminated["terminated_reason"] == "artist unavailable"
    assert fixtures.read_creator(creator["id"])["active_assignment_count"] == 1
    assert fixtures.read_title(title["id"])["committed_share_bps"] == 5000


def test_supplied_status_and_greenlit_stamp_on_a_pitch_are_discarded():
    """Client-sent `status`, `greenlit_at` and `committed_share_bps` never reach the row.

    PRD: "A newly pitched title arrives in status `PITCHED` with `committed_share_bps`, `production_cost_cents` and `royalty_accrued_cents` all at 0, and with `greenlit_at` and `cancel_reason` both null."

    Design: Corner/entities/title_creation_extra_field_status_input_ignored
    """
    fixtures.set_clock()

    title = validate_success(
        api_client.create_title(
            factories.title_payload(
                name="Nebula Knights",
                planned_issue_count=6,
                royalty_pool_bps=1200,
                cover_participation_bps=1500,
                status="PUBLISHING",
                greenlit_at="2020-01-01T00:00:00Z",
                committed_share_bps=9999,
            ),
            TEST_USERS["editor_in_chief_headers"],
        ),
        expected_status=201,
    )

    assert title["status"] == "PITCHED"
    assert title["greenlit_at"] is None
    assert title["committed_share_bps"] == 0
    assert is_valid_uuid(title["id"])
    assert title["id"] not in ("PUBLISHING", "2020-01-01T00:00:00Z", "9999")
    assert_versioned_record(title, expected_version=1)


def test_a_planned_issue_count_or_pool_share_out_of_range_is_refused():
    """A `planned_issue_count` of 25 and a `royalty_pool_bps` of 3001 both breach their ranges.

    PRD: "An `EditorInChief` pitches one by supplying its `name` (1 to 160 characters, and unique across all titles), the `planned_issue_count` of the greenlit run (at least 1 and at most 24), the `royalty_pool_bps` share of channel net receipts that will form the creator royalty pool (from 1 to 3000 basis points), and the `cover_participation_bps` share of each channel pool that cover artists take before the pro-rata split (from 0 to 3000 basis points)."

    Design: Corner/entities/out_of_range_and_empty_enum_array_inputs_are_rejected
    """
    fixtures.set_clock()

    too_many_issues = api_client.create_title(
        factories.title_payload(
            name="Overrun",
            planned_issue_count=25,
            royalty_pool_bps=1200,
            cover_participation_bps=1500,
        ),
        TEST_USERS["editor_in_chief_headers"],
    )
    validate_error(too_many_issues, ApiErrorId.ERR_INVALID_REQUEST.value)

    too_large_pool = api_client.create_title(
        factories.title_payload(
            name="Overrun",
            planned_issue_count=24,
            royalty_pool_bps=3001,
            cover_participation_bps=1500,
        ),
        TEST_USERS["editor_in_chief_headers"],
    )
    validate_error(too_large_pool, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api_client.list_titles(
            TEST_USERS["editor_in_chief_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_registering_a_creator_with_an_empty_craft_array_is_refused():
    """An empty `crafts` array breaches the non-empty constraint and writes no creator.

    PRD: "A `Creator` record carries a `full_name` of 1 to 120 characters as it will appear on the credits page, a non-empty `crafts` array of distinct values drawn from `SCRIPT`, `PENCILS`, `INKS`, `COLORS`, `LETTERS` and `COVER`, and a `default_page_rate_cents` of at least 0 that serves as the fallback rate quoted when a title does not override it."

    Design: Corner/entities/out_of_range_and_empty_enum_array_inputs_are_rejected
    """
    fixtures.set_clock()

    response = api_client.create_creator(
        factories.creator_payload(
            full_name="Nobody", crafts=[], default_page_rate_cents=1000
        ),
        TEST_USERS["editor_in_chief_headers"],
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    rows, meta = validate_paginated(
        api_client.list_creators(
            TEST_USERS["editor_in_chief_headers"], {"limit": 100, "offset": 0}
        )
    )
    assert rows == []
    assert meta["total_count"] == 0


def test_variant_cover_rows_expose_no_version_or_updated_at():
    """A variant cover carries only `id` and `created_at`, on creation and when listed.

    PRD: "Three record types are immutable once written and therefore carry only `id` and `created_at`: a variant cover, a release window and a revenue event."

    Design: Corner/entities/immutable_variant_cover_and_release_window_rows_carry_no_version_field
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(
        state["title"]["id"], target_on_sale_date="2026-10-14"
    )

    cover = validate_success(
        api_client.create_variant_cover(
            issue["id"],
            {"code": "A", "kind": "STANDARD", "cover_price_cents": 399},
            TEST_USERS["sales_director_headers"],
        ),
        expected_status=201,
    )

    assert_immutable_record(cover)
    assert cover["code"] == "A"
    assert cover["kind"] == "STANDARD"
    assert cover.get("incentive_ratio") is None
    assert cover["issue_id"] == issue["id"]

    rows, meta = validate_paginated(
        api_client.list_variant_covers(
            issue["id"],
            TEST_USERS["sales_director_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert_ids_in_order(rows, [cover["id"]])
    for row in rows:
        assert_immutable_record(row)


def test_release_window_rows_expose_no_version_or_updated_at():
    """A digital release window carries only `id` and `created_at`, with no version counter.

    PRD: "For those three, both `updated_at` and `version` are absent from the resource entirely."

    Design: Corner/entities/immutable_variant_cover_and_release_window_rows_carry_no_version_field
    """
    state = fixtures.setup_greenlit_title_with_script_assignment()
    issue = fixtures.schedule_issue(
        state["title"]["id"], target_on_sale_date="2026-10-14"
    )

    window = validate_success(
        api_client.create_release_window(
            issue["id"],
            {
                "channel": "DIGITAL",
                "release_date": "2026-11-13",
                "expected_net_receipts_cents": 120000,
            },
            TEST_USERS["sales_director_headers"],
        ),
        expected_status=201,
    )

    assert_immutable_record(window)
    assert window["channel"] == "DIGITAL"
    assert_date_equals(window["release_date"], "2026-11-13")
    assert window["expected_net_receipts_cents"] == 120000

    rows, meta = validate_paginated(
        api_client.list_release_windows(
            issue["id"],
            TEST_USERS["sales_director_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert meta["total_count"] == 1
    assert_ids_in_order(rows, [window["id"]])
    for row in rows:
        assert_immutable_record(row)


def test_scheduling_an_issue_under_an_absent_title_reports_title_not_found():
    """An issue posted under an unknown title id is refused as a missing title.

    PRD: "Each identifier has its own 404 code — `ERR_TITLE_NOT_FOUND`, `ERR_ISSUE_NOT_FOUND`, `ERR_CREATOR_NOT_FOUND`, `ERR_ASSIGNMENT_NOT_FOUND`, `ERR_STAGE_NOT_FOUND`, `ERR_CATALOG_NOT_FOUND`, `ERR_SOLICITATION_NOT_FOUND`, `ERR_RETAILER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_PRINT_RUN_NOT_FOUND` and `ERR_STATEMENT_NOT_FOUND` — and the code reported is the one belonging to the leftmost missing segment."

    Design: Corner/entities/issue_creation_under_an_unknown_title_id_returns_not_found
    """
    fixtures.set_clock()

    response = api_client.create_issue(
        NON_EXISTENT_UUID,
        factories.issue_payload(target_on_sale_date="2026-10-14"),
        TEST_USERS["managing_editor_headers"],
    )

    validate_error(response, ApiErrorId.ERR_TITLE_NOT_FOUND.value)


def test_booking_a_stage_against_another_title_s_assignment_is_refused():
    """A stage naming an assignment from a different title is a scope mismatch.

    PRD: "Two coherence rules bind the booking: the stage's `craft` must equal the craft on the referenced assignment, or the booking is refused with `ERR_CRAFT_MISMATCH`; and the referenced assignment must belong to the same title as the issue, or it is refused with `ERR_TITLE_SCOPE_MISMATCH`."

    Design: Corner/entities/stage_creation_with_an_assignment_from_another_title_is_rejected
    """
    fixtures.set_clock()
    creator = fixtures.register_all_craft_creator()

    first_title = fixtures.pitch_and_greenlight_title()
    own_assignment = fixtures.offer_assignment(
        first_title["id"],
        creator["id"],
        "SCRIPT",
        booking_start_date="2026-08-01",
        booking_end_date="2026-08-05",
    )
    fixtures.accept_assignment(own_assignment["id"], creator["id"])
    issue = fixtures.schedule_issue(
        first_title["id"], target_on_sale_date="2026-10-14"
    )

    other_title = fixtures.pitch_and_greenlight_title()
    foreign_assignment = fixtures.offer_assignment(
        other_title["id"],
        creator["id"],
        "PENCILS",
        page_rate_cents=9000,
        royalty_share_bps=1500,
        booking_start_date="2026-08-05",
        booking_end_date="2026-08-10",
    )
    fixtures.accept_assignment(foreign_assignment["id"], creator["id"])

    response = api_client.create_production_stage(
        issue["id"],
        factories.stage_payload(
            foreign_assignment["id"],
            craft="PENCILS",
            planned_start_date="2026-08-05",
            planned_due_date="2026-09-20",
        ),
        TEST_USERS["managing_editor_headers"],
    )
    validate_error(response, ApiErrorId.ERR_TITLE_SCOPE_MISMATCH.value)

    rows, meta = validate_paginated(
        api_client.list_issue_stages(
            issue["id"],
            TEST_USERS["managing_editor_headers"],
            {"limit": 100, "offset": 0},
        )
    )
    assert rows == []
    assert meta["total_count"] == 0
    assert fixtures.read_issue(issue["id"])["production_status"] == "PLANNED"
