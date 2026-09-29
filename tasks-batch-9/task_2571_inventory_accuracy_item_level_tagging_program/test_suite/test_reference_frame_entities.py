"""
The merchandise frame: what a create returns, what a read returns, how a
collection paginates, and how the declared defaults, enumerations, ranges and
foreign keys behave on the reference-data endpoints.
"""

from prd_bench_local_runner.testing import (
    NON_EXISTENT_UUID,
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import factories as f
from test_helpers import fixtures as fx
from test_helpers.api_errors import (
    ERR_CATEGORY_NOT_FOUND,
    ERR_INVALID_ENUM_VALUE,
    ERR_INVALID_REQUEST,
    ERR_STORE_NOT_FOUND,
    ERR_VENDOR_NOT_FOUND,
)
from test_helpers.assertions import (
    assert_clock_instant,
    assert_common_fields,
    assert_counter_firm_fields,
    assert_pct,
)
from test_helpers.constants import DEFAULT_CLOCK_UTC
from test_helpers.test_users import ADMIN, ANALYST, CONTROLLER


class TestCategoryRegistration:
    def test_a_create_returns_the_minted_row_with_every_declared_input(self, api):
        """
        The created resource comes back in the data field.

        "Every resource is minted with an `id`, which is a server-generated UUID
        carrying no type prefix. Every resource also carries a `created_at`, an ISO
        8601 UTC timestamp with three fractional digits recording the instant the
        row was minted."

        Design: Corner/entities/category_create_returns_201_with_declared_fields
        """
        response = api.create_category(f.apparel_category_payload(), ADMIN)
        data = validate_success(response, 201)

        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert body["meta"]["api_request_timestamp"]

        assert data["code"] == "APPAREL"
        assert data["name"] == "Apparel"
        assert data["count_cadence_days"] == 30
        assert data["variance_tolerance_units"] == 2
        assert data["variance_tolerance_value_cents"] == 20000
        assert_pct(data["min_accuracy_pct"], 97.00)
        assert data["landed_cost_uplift_bps"] == 750
        assert data["reader_mode_required"] == "EITHER"
        assert data["auto_correct_negative"] is True

        assert_common_fields(data)
        assert data["version"] == 1
        assert_clock_instant(data["created_at"], DEFAULT_CLOCK_UTC)
        assert_clock_instant(data["updated_at"], DEFAULT_CLOCK_UTC)

    def test_a_read_returns_the_row_as_stored_without_bumping_the_version(self, api):
        """
        A read is not a mutation.

        "All resources except one additionally carry `updated_at`, an ISO 8601 UTC
        timestamp with three fractional digits refreshed on every mutation of the
        row, and `version`, an integer that starts at 1 on creation and increments
        by exactly 1 on every mutation — including mutations the server performs on
        its own initiative, such as recomputing a derived accuracy figure or a store
        posture."

        Design: Corner/entities/category_get_by_id_returns_stored_row
        """
        created = fx.create_category(api, f.apparel_category_payload())

        first_read = validate_success(api.get_category(created["id"], ANALYST))
        assert first_read["id"] == created["id"]
        assert first_read["code"] == "APPAREL"
        assert_pct(first_read["min_accuracy_pct"], 97.00)
        assert first_read["landed_cost_uplift_bps"] == 750
        assert first_read["version"] == 1

        second_read = validate_success(api.get_category(created["id"], ANALYST))
        assert second_read["version"] == 1
        assert second_read["updated_at"] == first_read["updated_at"]

    def test_the_three_optional_inputs_take_their_declared_defaults(self, api):
        """
        Omitting the optional policy inputs seeds them.

        "`landed_cost_uplift_bps`, the basis-point freight-and-duty uplift applied
        to unit cost when a count variance is valued, which defaults to 0 and must
        be between 0 and 5000 inclusive; `min_accuracy_pct`, the minimum
        value-basis accuracy a position in this category must retain to stay
        promisable, expressed to 2 decimal places between 0.00 and 100.00
        inclusive; `reader_mode_required`, which is one of `HANDHELD`, `OVERHEAD`
        or `EITHER` and defaults to `EITHER`; and `auto_correct_negative`, a
        boolean defaulting to true that decides whether a small negative on-hand
        discovered by an integrity scan is corrected automatically or routed to a
        supervisor."

        Design: Corner/entities/category_defaults_applied_when_optional_inputs_omitted
        """
        sparse = validate_success(
            api.create_category(
                {
                    "code": "GROCERY",
                    "name": "Grocery",
                    "count_cadence_days": 21,
                    "variance_tolerance_units": 4,
                    "variance_tolerance_value_cents": 8000,
                    "min_accuracy_pct": 96.50,
                },
                ADMIN,
            ),
            201,
        )
        assert sparse["landed_cost_uplift_bps"] == 0
        assert sparse["reader_mode_required"] == "EITHER"
        assert sparse["auto_correct_negative"] is True
        assert_pct(sparse["min_accuracy_pct"], 96.50)


class TestCategoryListPagination:
    @staticmethod
    def _three_categories(api):
        fx.create_category(api, f.apparel_category_payload())
        fx.create_category(api, f.home_category_payload())
        fx.create_category(api, f.elec_category_payload())

    def test_a_page_reports_the_filtered_size_and_whether_rows_remain(self, api):
        """
        The envelope carries the collection's shape.

        "List responses carry `limit`, `offset`, `total_count` and `has_more`
        inside the `meta` object of the envelope, where `total_count` reflects the
        size of the filtered result set before pagination is applied and `has_more`
        states whether rows remain beyond the current page."

        Design: Corner/entities/categories_list_paginates_with_total_count_and_has_more
        """
        self._three_categories(api)

        response = api.list_categories(ANALYST, {"limit": 2, "offset": 0})
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert len(rows) == 2
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        tail_rows, tail_meta = validate_paginated(
            api.list_categories(ANALYST, {"limit": 2, "offset": 2})
        )
        assert len(tail_rows) == 1
        assert tail_meta["total_count"] == 3
        assert tail_meta["has_more"] is False

    def test_an_unqualified_list_applies_the_declared_defaults(self, api):
        """
        The two query parameters have defaults.

        "`limit` sets the maximum number of rows returned; when omitted it defaults
        to 10, and the accepted range is a minimum of 1 and a maximum of 100.
        `offset` sets the number of rows skipped before the page begins; when
        omitted it defaults to 0, and the accepted range is any integer of 0 or
        greater."

        Design: Corner/entities/categories_list_paginates_with_total_count_and_has_more
        """
        self._three_categories(api)

        rows, meta = validate_paginated(api.list_categories(ANALYST))
        assert len(rows) == 3
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False


class TestUnknownIdentifiers:
    def test_an_unknown_store_id_returns_the_error_envelope(self, api):
        """
        A path identifier that resolves to nothing ends the request.

        "Path identifiers are resolved strictly left to right, and the first
        identifier that resolves to nothing terminates the request with the 404
        belonging to that identifier's type: `ERR_CATEGORY_NOT_FOUND`,
        `ERR_STORE_NOT_FOUND`, `ERR_VENDOR_NOT_FOUND`,
        `ERR_COUNTER_FIRM_NOT_FOUND`, `ERR_ITEM_NOT_FOUND`,
        `ERR_STOCK_POSITION_NOT_FOUND`, `ERR_TAG_BATCH_NOT_FOUND`,
        `ERR_COUNT_SCHEDULE_NOT_FOUND`, `ERR_COUNT_TASK_NOT_FOUND`,
        `ERR_COUNT_LINE_NOT_FOUND`, `ERR_INVESTIGATION_NOT_FOUND`,
        `ERR_ADJUSTMENT_NOT_FOUND`, `ERR_SHRINK_PERIOD_NOT_FOUND`,
        `ERR_PHYSICAL_INVENTORY_NOT_FOUND` or
        `ERR_PHYSICAL_INVENTORY_LINE_NOT_FOUND`."

        Design: Corner/entities/store_get_with_unknown_id_returns_not_found
        """
        response = api.get_store(NON_EXISTENT_UUID, ANALYST)
        validate_error(response, ERR_STORE_NOT_FOUND, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert body["data"]["error_id"] == ERR_STORE_NOT_FOUND
        assert isinstance(body["data"]["message"], str)
        assert body["data"]["message"]

    def test_an_unresolvable_body_foreign_key_raises_the_type_it_names(self, api):
        """
        Body foreign keys carry the same 404 family.

        "Foreign keys supplied in a request body are resolved after path
        identifiers, in the order the endpoint's input list declares them, and an
        unresolvable body foreign key raises the same 404 for the type it names — a
        body `store_id` or `destination_store_id` that matches no store raises
        `ERR_STORE_NOT_FOUND`, a body `primary_vendor_id` or `vendor_id` that
        matches no vendor raises `ERR_VENDOR_NOT_FOUND`, a body `category_id`
        raises `ERR_CATEGORY_NOT_FOUND`, a body `item_id` raises
        `ERR_ITEM_NOT_FOUND`, a body `counter_firm_id` raises
        `ERR_COUNTER_FIRM_NOT_FOUND`, a body `count_schedule_id` raises
        `ERR_COUNT_SCHEDULE_NOT_FOUND`, a body `shrink_period_id` raises
        `ERR_SHRINK_PERIOD_NOT_FOUND`, and a body `investigation_id` raises
        `ERR_INVESTIGATION_NOT_FOUND`."

        Design: Corner/entities/item_create_with_unknown_category_id_returns_not_found
        """
        vendor = fx.create_vendor(api)

        validate_error(
            api.create_item(f.item_payload(NON_EXISTENT_UUID, vendor["id"]), ADMIN),
            ERR_CATEGORY_NOT_FOUND,
            404,
        )

        category = fx.create_category(api, f.apparel_category_payload())
        validate_error(
            api.create_item(f.item_payload(category["id"], NON_EXISTENT_UUID), ADMIN),
            ERR_VENDOR_NOT_FOUND,
            404,
        )

        rows, meta = validate_paginated(api.list_items(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0


class TestRequestShapeOnReferenceData:
    def test_an_item_without_a_unit_cost_is_rejected_and_writes_nothing(self, api):
        """
        The single cost basis is a required input.

        "It carries a `sku` code of 1 to 32 characters, unique across all SKUs and
        raising `ERR_DUPLICATE_SKU` on collision, a `description` of 1 to 240
        characters, a `unit_cost_cents` greater than 0 — the single cost basis
        behind every valuation in this domain — and a ticketed
        `retail_price_cents` greater than 0."

        Design: Corner/entities/item_create_missing_unit_cost_returns_invalid_request
        """
        category = fx.create_category(api, f.apparel_category_payload())
        vendor = fx.create_vendor(api)

        validate_error(
            api.create_item(
                f.item_payload(
                    category["id"],
                    vendor["id"],
                    unit_cost_cents=None,
                    epc_prefix_length=None,
                    tag_required=None,
                ),
                ADMIN,
            ),
            ERR_INVALID_REQUEST,
            422,
        )

        rows, meta = validate_paginated(api.list_items(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_reader_capability_outside_the_enumeration_is_rejected(self, api):
        """
        Enum membership is checked after the shape.

        "`reader_capability` declares the reader technology installed and is one of
        `HANDHELD_ONLY`, `OVERHEAD_ONLY` or `BOTH`."

        Design: Corner/entities/store_create_with_bad_reader_capability_returns_invalid_enum_value
        """
        validate_error(
            api.create_store(f.store_payload(reader_capability="RFID_ONLY"), ADMIN),
            ERR_INVALID_ENUM_VALUE,
            422,
        )

        rows, meta = validate_paginated(api.list_stores(ANALYST))
        assert rows == []
        assert meta["total_count"] == 0

    def test_a_negative_reserved_units_fails_the_numeric_range_branch(self, api):
        """
        The reserved quantity has a floor of zero.

        "Either a `SystemAdmin` or an `InventoryAnalyst` opens one by naming the
        `store_id` and the `item_id`, optionally declaring `baseline_on_hand_units`
        — the opening quantity, which must be 0 or greater and defaults to 0 — and
        optionally `reserved_units`, the quantity already committed to open
        omnichannel orders, which must be 0 or greater, defaults to 0, and is never
        mutated again by any operation in this domain."

        Design: Corner/entities/stock_position_negative_reserved_units_rejected
        """
        category = fx.create_category(api, f.apparel_category_payload())
        store = fx.create_store(api, f.store_payload())
        vendor = fx.create_vendor(api)
        item = fx.create_item(api, f.item_payload(category["id"], vendor["id"]))

        validate_error(
            api.create_stock_position(
                f.stock_position_payload(
                    store["id"],
                    item["id"],
                    baseline_on_hand_units=5,
                    reserved_units=-1,
                ),
                ANALYST,
            ),
            ERR_INVALID_REQUEST,
            422,
        )

        rows, meta = validate_paginated(
            api.list_stock_positions(ANALYST, {"store_id": store["id"]})
        )
        assert rows == []
        assert meta["total_count"] == 0


class TestServerOwnedLedgersAndImmutability:
    def test_a_fresh_vendor_starts_with_a_perfect_tag_record(self, api):
        """
        None of the vendor's six figures is a client input.

        "Every vendor begins with a perfect tag-quality record:
        `tag_compliance_score_bps` starts at 10000 and, because that score sits in
        the top band, `required_verification_sample_pct` starts at 5. The four
        ledger figures — `shortage_event_count`,
        `lifetime_chargeback_gross_cents`, `credited_cents` and
        `chargeback_balance_cents` — all start at 0. None of these six figures is
        ever supplied by a client; they move only as a consequence of tag
        verifications, closed shortage findings, chargebacks and credits."

        Design: Corner/entities/vendor_computed_ledger_starts_at_declared_defaults
        """
        created = validate_success(api.create_vendor(f.vendor_payload(), ADMIN), 201)
        assert created["tag_compliance_score_bps"] == 10000
        assert created["required_verification_sample_pct"] == 5
        assert created["shortage_event_count"] == 0
        assert created["lifetime_chargeback_gross_cents"] == 0
        assert created["credited_cents"] == 0
        assert created["chargeback_balance_cents"] == 0

        reread = validate_success(api.get_vendor(created["id"], CONTROLLER))
        assert reread["tag_compliance_score_bps"] == 10000
        assert reread["required_verification_sample_pct"] == 5
        assert reread["shortage_event_count"] == 0
        assert reread["lifetime_chargeback_gross_cents"] == 0
        assert reread["credited_cents"] == 0
        assert reread["chargeback_balance_cents"] == 0

    def test_a_counting_firm_carries_neither_version_nor_updated_at(self, api):
        """
        The counting firm is the declared exception to the common properties.

        "The single exception is `CounterFirm`, which is immutable after
        registration: a counting firm carries only `id` and `created_at`, has no
        `updated_at` and no `version`, and has no update endpoint at all."

        Design: Corner/entities/counter_firm_is_immutable_with_no_version_or_update_path
        """
        created = validate_success(
            api.create_counter_firm(f.counter_firm_payload(), ADMIN), 201
        )
        assert_counter_firm_fields(created)

        read = validate_success(api.get_counter_firm(created["id"], CONTROLLER))
        assert read["id"] == created["id"]
        assert read["code"] == "CF1"
        assert read["certification_level"] == "TIER_1"
        assert read["max_lines_per_pass"] == 500
        assert_counter_firm_fields(read)

    def test_an_omitted_recount_threshold_reads_one_hundred_and_fifty(self, api):
        """
        The physical inventory is born with a seeded threshold and zeroed rollups.

        "`recount_threshold_bps` defaults to 150 when omitted and must be at least
        1 and at most 10000. A new inventory starts in `PLANNED` with
        `recount_round` and `line_count` at 0, `book_value_cents`,
        `counted_value_cents`, `net_variance_cents` and `net_variance_bps` at 0,
        and `certified_at` null."

        Design: Corner/entities/physical_inventory_recount_threshold_defaults_to_one_fifty
        """
        store = fx.create_store(api, f.store_payload())
        firm = fx.create_counter_firm(api)

        created = validate_success(
            api.create_physical_inventory(
                f.physical_inventory_payload(
                    store["id"], firm["id"], recount_threshold_bps=None
                ),
                CONTROLLER,
            ),
            201,
        )
        assert created["recount_threshold_bps"] == 150
        assert created["status"] == "PLANNED"
        assert created["recount_round"] == 0
        assert created["line_count"] == 0
        assert created["book_value_cents"] == 0
        assert created["counted_value_cents"] == 0
        assert created["net_variance_cents"] == 0
        assert created["net_variance_bps"] == 0
        assert created["certified_at"] is None


class TestFlatCountLineTopology:
    def test_a_counted_line_resolves_its_position_from_the_task_and_the_sku(self, api):
        """
        The line's position is server-resolved, not client-supplied.

        "Recording a line resolves and freezes its context. The line's
        `stock_position_id` is resolved from the task's store together with the
        named SKU, and `system_units_snapshot` captures that position's
        `on_hand_units` at this instant and is frozen thereafter."

        Design: Corner/entities/count_line_flat_topology_resolves_both_foreign_keys
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_started_task(api, world)

        line = validate_success(
            api.create_count_line(
                world["task_id"], f.count_line_payload(world["item_id"], 100), ANALYST
            ),
            201,
        )
        assert line["count_task_id"] == world["task_id"]
        assert line["item_id"] == world["item_id"]
        assert line["stock_position_id"] == world["position_id"]
        assert line["system_units_snapshot"] == 100
        assert line["variance_units"] == 0
        assert line["variance_value_cents"] == 0
        assert line["within_tolerance"] is True

    def test_the_line_is_reachable_from_each_parent_through_its_own_list(self, api):
        """
        Each child is independently addressable and independently listed.

        "Although counted lines, variance investigations and physical-inventory
        lines are created in the context of a parent, each is independently
        addressable by its own identifier and each has its own list endpoint."

        Design: Corner/entities/count_line_flat_topology_resolves_both_foreign_keys
        """
        world = fx.apparel_reference_world(api, baseline=100)
        fx.with_started_task(api, world)
        line = fx.add_line(api, world["task_id"], world["item_id"], 100)

        by_task, task_meta = validate_paginated(
            api.list_count_lines(ANALYST, {"count_task_id": world["task_id"]})
        )
        assert task_meta["total_count"] == 1
        assert by_task[0]["id"] == line["id"]

        by_position, position_meta = validate_paginated(
            api.list_count_lines(ANALYST, {"stock_position_id": world["position_id"]})
        )
        assert position_meta["total_count"] == 1
        assert by_position[0]["id"] == line["id"]

        direct = validate_success(api.get_count_line(line["id"], ANALYST))
        assert direct["id"] == line["id"]
        assert direct["stock_position_id"] == world["position_id"]
