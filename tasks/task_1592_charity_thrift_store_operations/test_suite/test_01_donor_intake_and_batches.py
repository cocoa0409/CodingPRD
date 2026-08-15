"""Donor registration, batch intake, item valuation, revalue OCC, and listings."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_item,
    assert_batch,
    assert_donor,
    assert_item,
    begin_sort,
    complete_sort,
    create_batch,
    create_batch_with_items,
    create_donor,
    create_guideline,
    create_sorted_batch,
    deactivate_donor,
    get_success_data,
    price_item,
    sort_batch_all,
    triage_item,
    validate_error,
    validate_paginated,
    validate_success,
    INTAKE,
    MGR,
    PRICER,
)


class TestDonorRegistration:
    def test_donor_create_applies_defaults(self, api):
        """PRD 3.1: "A new donor starts with `status` `ACTIVE`, `tier` `STANDARD`,
        and a `lifetime_donation_count` of zero."
        PRD 2.4: "The `version` is an integer starting at 1 that increments by one
        on every mutation of the resource"

        Design: Corner/entities/donor_create_applies_defaults
        """
        created = validate_success(
            api.create_donor({"full_name": "D Min"}, INTAKE), 201
        )
        assert_donor(created)
        donor = validate_success(api.get_donor(created["id"], MGR))
        assert donor["status"] == "ACTIVE"
        assert donor["tier"] == "STANDARD"
        assert donor["lifetime_donation_count"] == 0
        assert donor["version"] == 1


class TestBatchIntakeValidation:
    def test_batch_create_rejects_system_only_enum(self, api):
        """PRD 3.1: "Opening a batch takes the `donor_id`, a `source` of `WALK_IN`
        or `DONATION_DRIVE`, and an optional `receipt_requested` flag (default false)
        recording whether the donor wants a tax receipt; the third source value,
        `PICKUP_STOP`, is system-set only and marks the batches a truck route
        creates automatically (§3.7)."
        PRD 2.9: "required fields present, types valid, enum values within their
        declared domains, unknown fields rejected, required arrays non-empty
        (`item_ids` on a sale, `allocations` on a transfer, `adjustments` on a
        revalue), time windows ordered (`window_end` strictly after `window_start`,
        `ends_at` strictly after `starts_at`), and amounts non-negative — violations
        yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/batch_create_rejects_system_only_enum
        """
        donor = create_donor("D Enum")
        resp = api.create_batch(
            {"donor_id": donor["id"], "source": "PICKUP_STOP"}, INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_item_create_rejects_computed_field_input(self, api):
        """PRD 3.1: "the attendant adds items to it one call at a time, supplying a
        `category` ..., a `condition` ..., and optionally a free-text `description`
        and a `weight_lbs`."
        PRD 2.9: "required fields present, types valid, enum values within their
        declared domains, unknown fields rejected, required arrays non-empty
        (`item_ids` on a sale, `allocations` on a transfer, `adjustments` on a
        revalue), time windows ordered (`window_end` strictly after `window_start`,
        `ends_at` strictly after `starts_at`), and amounts non-negative — violations
        yield `ERR_INVALID_REQUEST`."

        Design: Corner/entities/item_create_rejects_computed_field_input
        """
        donor = create_donor("D Comp")
        batch = create_batch(donor["id"])
        resp = api.add_item(
            batch["id"],
            {"category": "CLOTHING", "condition": "GOOD", "provisional_value_cents": 1},
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        batch_after = validate_success(api.get_batch(batch["id"], MGR))
        assert batch_after["item_count"] == 0, "rejected item must not persist"

    def test_batch_create_missing_donor_returns_not_found(self, api):
        """PRD 2.9: "path identifiers resolve left to right, then body references
        (`donor_id`, `worker_id`, `till_session_id`, every element of `item_ids`,
        `vendor_id`, `target_route_id`, every adjustment's `item_id`); the first
        unresolvable identifier yields `ERR_NOT_FOUND`."

        Design: Corner/entities/batch_create_missing_donor_returns_not_found
        """
        resp = api.create_batch(
            {"donor_id": NON_EXISTENT_UUID, "source": "WALK_IN"}, INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_donor_inactive_blocks_batch(self, api):
        """PRD 3.1: "An `INACTIVE` donor cannot open a donation batch and cannot be
        scheduled onto a pickup stop — both attempts are rejected with
        `ERR_DONOR_INACTIVE`."

        Design: Corner/validations/donor_inactive_blocks_batch
        """
        donor = create_donor("D Off")
        deactivate_donor(donor["id"])
        resp = api.create_batch(
            {"donor_id": donor["id"], "source": "WALK_IN"}, INTAKE
        )
        validate_error(resp, ApiErrorId.ERR_DONOR_INACTIVE)


class TestBatchComputedTotals:
    def test_batch_computed_totals_track_items(self, api):
        """PRD 3.1: "Each item is born in `RECEIVED` status, stamped with its owning
        batch's `batch_id`, and immediately carries a `provisional_value_cents`: the
        fair-market figure for its category — 800 cents for CLOTHING, 4500 for
        FURNITURE, 3000 for ELECTRONICS, 1200 for HOUSEWARES, 300 for BOOKS_MEDIA,
        600 for TOYS, 5000 for COLLECTIBLES — multiplied by the condition's value
        factor (1.0 for NEW_WITH_TAGS, 0.7 for GOOD, 0.4 for FAIR, 0.15 for POOR),
        rounded half up to whole cents."
        PRD 3.1: "Every added item recomputes the batch's `item_count`,
        `untriaged_count`, and `provisional_value_cents` — the last being the sum
        over all of the batch's items — and bumps the batch's `version`."

        Design: Corner/entities/batch_computed_totals_track_items
        """
        donor, batch, items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "FURNITURE", "condition": "FAIR"},
            ]
        )
        # CLOTHING/GOOD = 800 x 0.7 = 560; FURNITURE/FAIR = 4500 x 0.4 = 1800.
        mid = validate_success(api.get_batch(batch["id"], MGR))
        assert_batch(mid)
        assert mid["item_count"] == 2
        assert mid["untriaged_count"] == 2
        assert mid["provisional_value_cents"] == 2360

        begin_sort(batch["id"])
        for item in items:
            triage_item(item["id"], "SALVAGE")

        done = validate_success(api.get_batch(batch["id"], MGR))
        assert done["untriaged_count"] == 0, "triage drains the untriaged count"
        assert done["provisional_value_cents"] == 2360, (
            "disposition does not change the fair-market valuation"
        )
        first = validate_success(api.get_item(items[0]["id"], MGR))
        second = validate_success(api.get_item(items[1]["id"], MGR))
        assert first["provisional_value_cents"] == 560
        assert second["provisional_value_cents"] == 1800

    def test_immediate_consistency_reads(self, api):
        """PRD 3.1: "Every added item recomputes the batch's `item_count`,
        `untriaged_count`, and `provisional_value_cents` — the last being the sum
        over all of the batch's items — and bumps the batch's `version`."

        Design: Corner/consistency_model/immediate_consistency_reads
        """
        donor = create_donor("D Imm")
        batch = create_batch(donor["id"])
        created = validate_success(
            api.add_item(batch["id"], {"category": "CLOTHING", "condition": "GOOD"},
                         INTAKE),
            201,
        )
        assert_item(created)
        assert created["provisional_value_cents"] == 560
        assert created["status"] == "RECEIVED"

        batch_now = validate_success(api.get_batch(batch["id"], PRICER))
        assert batch_now["item_count"] == 1
        assert batch_now["untriaged_count"] == 1
        assert batch_now["provisional_value_cents"] == 560

        item_now = validate_success(api.get_item(created["id"], PRICER))
        assert item_now["provisional_value_cents"] == created["provisional_value_cents"]
        assert item_now["status"] == "RECEIVED"


class TestItemListing:
    def test_items_list_pagination_and_filters(self, api):
        """PRD 2.3: "The `limit` parameter sets the maximum number of items returned:
        it defaults to 10 when omitted, with a minimum of 1 and a maximum of 100."
        PRD 2.3: "Paginated list responses carry four pagination fields in the `meta`
        object of the envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD 3.3: "The item list supports filtering by `batch_id`, `sale_id`,
        `bale_id`, `floor_cycle_id`, `shrunk_cycle_id`, `status`, or `category`."

        Design: Corner/entities/items_list_pagination_and_filters
        """
        donor, batch, _items = create_batch_with_items(
            [
                {"category": "CLOTHING", "condition": "GOOD"},
                {"category": "CLOTHING", "condition": "FAIR"},
                {"category": "FURNITURE", "condition": "GOOD"},
            ]
        )
        page, meta = validate_paginated(
            api.list_items(MGR, params={"batch_id": batch["id"], "limit": 2, "offset": 0})
        )
        assert len(page) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True

        filtered, meta2 = validate_paginated(
            api.list_items(MGR, params={"batch_id": batch["id"], "category": "FURNITURE"})
        )
        assert len(filtered) == 1
        assert meta2["total_count"] == 1
        assert meta2["has_more"] is False
        assert filtered[0]["category"] == "FURNITURE"


class TestSortStateMachine:
    def test_complete_sort_with_untriaged_item_rejected(self, api):
        """PRD 3.2: "Completing while any item is still untriaged — while
        `untriaged_count` is above zero — fails with
        `ERR_BATCH_HAS_UNTRIAGED_ITEMS`."

        Design: Corner/state_machines/complete_sort_with_untriaged_item_rejected
        """
        donor, batch, _items = create_batch_with_items(
            [{"category": "TOYS", "condition": "GOOD"}]
        )
        begin_sort(batch["id"])
        resp = api.complete_sort(batch["id"], INTAKE)
        validate_error(resp, ApiErrorId.ERR_BATCH_HAS_UNTRIAGED_ITEMS)
        batch_after = validate_success(api.get_batch(batch["id"], MGR))
        assert batch_after["status"] == "SORTING"

    def test_triage_after_priced_returns_invalid_state(self, api):
        """PRD 3.2: "Sorting is where every item meets its fork. Triage takes a
        `decision` of `SALABLE`, `RECYCLE`, or `SALVAGE` and is accepted only while
        the owning batch is `SORTING`"
        PRD 3.3: "Attempting any of these item actions from the wrong state fails
        with `ERR_ITEM_INVALID_STATE`."

        Design: Corner/state_machines/triage_after_priced_returns_invalid_state
        """
        create_guideline("CLOTHING", 2000)
        donor, batch, items = create_batch_with_items(
            [{"category": "CLOTHING", "condition": "GOOD"}]
        )
        begin_sort(batch["id"])
        triage_item(items[0]["id"], "SALABLE")
        priced = price_item(items[0]["id"])
        assert priced["status"] == "PRICED"

        resp = api.triage_item(items[0]["id"], {"decision": "SALVAGE"}, INTAKE)
        validate_error(resp, ApiErrorId.ERR_ITEM_INVALID_STATE)
        item_after = validate_success(api.get_item(items[0]["id"], MGR))
        assert item_after["status"] == "PRICED", "rejected triage must not move the item"


class TestBatchRevalue:
    def test_occ_revalue_stale_version(self, api):
        """PRD 2.8: "A revalue request must carry `expected_batch_version` holding
        the batch `version` the client last observed. If the batch's current
        `version` has advanced beyond that value — because items were added, triaged,
        repriced, or otherwise mutated since — the revalue is rejected with
        `ERR_STALE_BATCH_VERSION` (HTTP 412)."
        PRD 3.1: "The latest revalue supersedes prior ones, overwriting the named
        items' provisional values and recomputing the batch total."

        Design: Corner/complexity_layers/occ_revalue_stale_version
        """
        donor = create_donor("D Occ")
        batch = create_batch(donor["id"])
        stale_version = batch["version"]
        item = add_item(batch["id"], "TOYS", "GOOD")
        assert stale_version == 1

        # The item add bumped the batch version to 2, so the observed version 1
        # is stale.
        resp = api.revalue_batch(
            batch["id"],
            {
                "expected_batch_version": stale_version,
                "adjustments": [
                    {"item_id": item["id"], "provisional_value_cents": 900}
                ],
            },
            INTAKE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_BATCH_VERSION)

        fresh = validate_success(api.get_batch(batch["id"], INTAKE))
        assert fresh["version"] == 2, "rejected revalue must not bump the version"
        assert fresh["provisional_value_cents"] == 420, "TOYS/GOOD = 600 x 0.7"

        retried = validate_success(
            api.revalue_batch(
                batch["id"],
                {
                    "expected_batch_version": fresh["version"],
                    "adjustments": [
                        {"item_id": item["id"], "provisional_value_cents": 900}
                    ],
                },
                INTAKE,
            )
        )
        assert_batch(retried)
        assert retried["provisional_value_cents"] == 900
        assert retried["version"] == 3, "successful revalue bumps the version once"

    def test_revalue_after_receipt_blocked(self, api):
        """PRD 3.1: "Revalue is forbidden once the batch is `CLOSED` or `CANCELLED`
        (`ERR_BATCH_INVALID_STATE`), and forbidden while an ISSUED tax receipt exists
        for the batch (`ERR_REVALUE_BLOCKED_BY_RECEIPT`)."

        Design: Corner/state_machines/revalue_after_receipt_blocked
        """
        donor, batch, items = create_sorted_batch(
            [{"category": "TOYS", "condition": "GOOD"}],
            donor_kwargs={"full_name": "D Rv", "address_line": "5 Main St"},
            receipt_requested=True,
        )
        receipt = validate_success(api.issue_receipt(batch["id"], INTAKE), 201)
        assert receipt["status"] == "ISSUED"

        current = validate_success(api.get_batch(batch["id"], INTAKE))
        resp = api.revalue_batch(
            batch["id"],
            {
                "expected_batch_version": current["version"],
                "adjustments": [
                    {"item_id": items[0]["id"], "provisional_value_cents": 900}
                ],
            },
            INTAKE,
        )
        # The OCC version is current, so the rejection is the receipt state
        # precondition, not a stale version.
        validate_error(resp, ApiErrorId.ERR_REVALUE_BLOCKED_BY_RECEIPT)
        after = validate_success(api.get_batch(batch["id"], INTAKE))
        assert after["provisional_value_cents"] == 420, (
            "rejected revalue leaves the batch total unchanged"
        )
