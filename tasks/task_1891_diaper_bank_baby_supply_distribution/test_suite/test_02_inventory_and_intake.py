"""Inventory initialization, donation intake, and the count-post-recount cycle."""
from test_helpers import (
    ApiErrorId,
    SIZE_CODES,
    TEST_USERS,
    assert_intake_batch,
    assert_inventory,
    create_donation_batch,
    get_inventory,
    init_inventory,
    post_donation,
    size_entry,
    supply_line,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["bank_admin_headers"]
WAREHOUSE = TEST_USERS["warehouse_manager_headers"]


class TestInventoryInitialization:
    def test_inventory_initialize_materializes_all_sizes(self, api):
        """PRD §2.8: "Inventory is a singleton, created exactly once through an initialization step that establishes one ledger entry for each of the eight size codes the bank recognizes: `NEWBORN`, `SIZE_1`, `SIZE_2`, `SIZE_3`, `SIZE_4`, `SIZE_5`, `SIZE_6`, and `TRAINING_PANTS`."
        PRD §2.8: "The last two are derived and must always agree with the first three: `available_units` is `on_hand_units` minus `reserved_units`, and `restock_needed` is true exactly when `on_hand_units` is less than or equal to `reorder_threshold_units`."
        PRD §3.2: "Initialization creates all eight size entries with zero on hand and zero reserved and flips `initialized` to true."
        PRD §3.2: "any size omitted from `thresholds` starts with a `reorder_threshold_units` of zero."

        Design: Corner/entities/inventory_initialize_materializes_all_sizes
        """
        resp = api.initialize_inventory({"thresholds": {"SIZE_1": 200}}, WAREHOUSE)
        inventory = validate_success(resp, 201)
        assert_inventory(inventory)

        sizes = inventory["sizes"]
        assert set(sizes.keys()) == set(SIZE_CODES)
        for code in SIZE_CODES:
            entry = sizes[code]
            assert entry["on_hand_units"] == 0, f"sizes.{code} on_hand must start at 0"
            assert entry["reserved_units"] == 0, f"sizes.{code} reserved must start at 0"
            assert entry["available_units"] == 0, f"sizes.{code} available must start at 0"
        assert sizes["SIZE_1"]["reorder_threshold_units"] == 200
        assert sizes["SIZE_2"]["reorder_threshold_units"] == 0, (
            "Sizes omitted from thresholds start with a reorder threshold of zero"
        )
        # restock_needed is on_hand <= threshold: 0 <= 200 and 0 <= 0 both hold.
        assert sizes["SIZE_1"]["restock_needed"] is True
        assert sizes["SIZE_2"]["restock_needed"] is True
        assert inventory["total_on_hand_units"] == 0
        assert inventory["initialized"] is True


class TestIntakeBatches:
    def test_intake_batch_invalid_size_code_rejected(self, api):
        """PRD §2.6: "Tenth and last, request-body validation: malformed fields, bad enumerations, unknown size codes, an `ends_at` that does not fall after `starts_at`, empty line arrays, quantities below one, unresolvable foreign references in the body, and a second attempt to initialize the inventory are all rejected with `ERR_VALIDATION`."

        Design: Corner/entities/intake_batch_invalid_size_code_rejected
        """
        resp = api.create_intake_batch(
            {"donor_name": "Donor Bad",
             "lines": [{"size_code": "SIZE_9", "quantity": 5}]},
            WAREHOUSE,
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)

        _data, meta = validate_paginated(api.list_intake_batches(WAREHOUSE))
        assert meta["total_count"] == 0, "A rejected batch must not be persisted"

    def test_intake_list_pagination_envelope(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."

        Design: Corner/entities/intake_list_pagination_envelope
        """
        create_donation_batch([supply_line("SIZE_1", 10)], donor_name="Donor P1")
        create_donation_batch([supply_line("SIZE_2", 20)], donor_name="Donor P2")

        data, meta = validate_paginated(
            api.list_intake_batches(WAREHOUSE, params={"limit": 1}))
        assert len(data) == 1, "limit=1 returns exactly one item"
        assert meta["total_count"] == 2
        assert meta["has_more"] is True
        assert meta["limit"] == 1
        assert meta["offset"] == 0

        data2, meta2 = validate_paginated(
            api.list_intake_batches(WAREHOUSE, params={"limit": 1, "offset": 1}))
        assert len(data2) == 1
        assert meta2["has_more"] is False, "Second page of two items has no successor"

    def test_batch_initial_state_is_counted(self, api):
        """PRD §3.2: "A `WarehouseManager` records a donation with a `donor_name` and an array of `lines`, each line pairing a `size_code` with a `quantity` of one or more; the batch is born `COUNTED` with `source_type` `DONATION` and a null `purchase_order_id`."
        PRD §3.2: "Posting is the moment counted product becomes stock."

        Design: Corner/state_machines/batch_initial_state_is_counted
        """
        init_inventory()
        resp = api.create_intake_batch(
            {"donor_name": "Donor I",
             "lines": [{"size_code": "SIZE_1", "quantity": 100}]},
            WAREHOUSE,
        )
        batch = validate_success(resp, 201)
        assert_intake_batch(batch)
        assert batch["status"] == "COUNTED", "A donation batch is born COUNTED"
        assert batch["source_type"] == "DONATION"
        assert batch["purchase_order_id"] is None

        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_1")["on_hand_units"] == 0, (
            "Nothing moves into stock until the batch is posted"
        )


class TestIntakeRecountCycle:
    def test_recount_withdraws_posted_stock(self, api):
        """PRD §3.2: "Recounting a `POSTED` batch moves it back to `COUNTED` with replacement `lines` supplied in the request: the system first verifies that every current line can be withdrawn — for each line, the size's `on_hand_units` minus the line's `quantity` must not be negative, otherwise the recount is rejected with `ERR_INSUFFICIENT_STOCK` — then withdraws each old line's contribution from `on_hand_units`, replaces the batch's `lines` with the request's, and recomputes `total_units` and `valued_total_cents`."

        Design: Difficulty/non_linear_state_machine/intake_batch_post_recount_repost_cycle
        """
        init_inventory()
        batch = post_donation([supply_line("SIZE_1", 500)], donor_name="Donor C")
        assert batch["status"] == "POSTED"
        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_1")["on_hand_units"] == 500, (
            "Posting added the line quantity to on-hand stock"
        )

        recounted = validate_success(
            api.recount_intake_batch(
                batch["id"], {"lines": [{"size_code": "SIZE_1", "quantity": 480}]},
                WAREHOUSE),
            200,
        )
        assert recounted["status"] == "COUNTED"
        assert recounted["total_units"] == 480
        assert recounted["valued_total_cents"] == 480 * 32, (
            "Recount recomputes the fair-market valuation: 480 SIZE_1 at 32 cents"
        )
        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_1")["on_hand_units"] == 0, (
            "Recount withdraws the old lines' contribution from on-hand stock"
        )

    def test_repost_after_recount_redeposits_stock(self, api):
        """PRD §3.2: "The round trip `COUNTED` → `POSTED` → `COUNTED` → `POSTED` is a compensating pair for on-hand stock: recount withdraws, reposting redeposits."
        PRD §3.2: "A `WarehouseManager` posts a batch — `COUNTED` → `POSTED` — and each line's `quantity` is added to the inventory's `on_hand_units` for that size; the batch's `posted_at` is stamped from the logical clock, and both the batch's and the inventory's `version` increment."

        Design: Difficulty/non_linear_state_machine/intake_batch_post_recount_repost_cycle
        """
        init_inventory()
        batch = post_donation([supply_line("SIZE_1", 500)], donor_name="Donor C")
        validate_success(
            api.recount_intake_batch(
                batch["id"], {"lines": [{"size_code": "SIZE_1", "quantity": 480}]},
                WAREHOUSE),
            200,
        )

        reposted = validate_success(api.post_intake_batch(batch["id"], WAREHOUSE), 200)
        assert reposted["status"] == "POSTED", "The cycle loops legally back to POSTED"
        assert reposted["valued_total_cents"] == 15360, "480 SIZE_1 at 32 cents each"
        assert reposted["posted_at"] is not None

        inventory = get_inventory()
        entry = size_entry(inventory, "SIZE_1")
        assert entry["on_hand_units"] == 480, (
            "The corrected recount quantity is what lands in stock after reposting"
        )
        assert inventory["total_on_hand_units"] == 480


class TestIntakePostVoidRoundTrip:
    def test_posted_void_reverses_stock_exactly(self, api):
        """PRD §3.2: "Voiding from `POSTED` requires the same per-line stock check as a recount (a shortfall yields `ERR_INSUFFICIENT_STOCK`) and subtracts each line's `quantity` from `on_hand_units`, an exact reversal of the post transition; both versions increment."

        Design: Difficulty/compensating_invariant/intake_post_void_round_trip_conserves_on_hand
        """
        init_inventory()
        post_donation([supply_line("SIZE_4", 1000)], donor_name="Donor K")
        batch2 = create_donation_batch([supply_line("SIZE_4", 300)],
                                       donor_name="Donor L")

        validate_success(api.post_intake_batch(batch2["id"], WAREHOUSE), 200)
        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_4")["on_hand_units"] == 1300, (
            "Posting batch2 adds its 300 units to the 1000 already on hand"
        )

        validate_success(
            api.void_intake_batch(batch2["id"], {"reason": "duplicate delivery"},
                                  WAREHOUSE),
            200,
        )
        inventory = get_inventory()
        assert size_entry(inventory, "SIZE_4")["on_hand_units"] == 1000, (
            "Voiding a POSTED batch is an exact reversal: stock returns to 1000"
        )

    def test_void_marks_only_the_voided_batch(self, api):
        """PRD §3.2: "Voiding retires a batch into the terminal `VOIDED` state, with an optional `reason`."
        PRD §3.2: "Voiding from `POSTED` requires the same per-line stock check as a recount (a shortfall yields `ERR_INSUFFICIENT_STOCK`) and subtracts each line's `quantity` from `on_hand_units`, an exact reversal of the post transition; both versions increment."

        Design: Difficulty/compensating_invariant/intake_post_void_round_trip_conserves_on_hand
        """
        init_inventory()
        batch1 = post_donation([supply_line("SIZE_4", 1000)], donor_name="Donor K")
        batch2 = post_donation([supply_line("SIZE_4", 300)], donor_name="Donor L")

        voided = validate_success(
            api.void_intake_batch(batch2["id"], {"reason": "duplicate delivery"},
                                  WAREHOUSE),
            200,
        )
        assert voided["status"] == "VOIDED"

        batch1_after = validate_success(api.get_intake_batch(batch1["id"], WAREHOUSE), 200)
        assert batch1_after["status"] == "POSTED", "The other batch is untouched"

        inventory = get_inventory()
        assert inventory["total_on_hand_units"] == 1000
        assert size_entry(inventory, "SIZE_4")["on_hand_units"] == 1000
