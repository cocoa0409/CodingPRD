"""Storage zones: posture thresholds, capacity boundaries, season
compatibility, zone-code uniqueness, zone OCC, and validation ordering on
the stocking endpoint."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_storage_zone,
    assert_zone_posture_invariants,
    create_zone,
    get_zone,
    grade_items,
    open_batch_in_sort,
    patch_storage_zone_payload,
    setup_sorting_staff,
    setup_stocked_items,
    stock_items,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}


class TestZoneConsistency:
    def test_read_after_write_immediate_consistency(self, api):
        """PRD: "A `ProgramAdmin` creates a zone with a globally unique
        `zone_code` (a duplicate is rejected with `ERR_ZONE_CODE_TAKEN`), a
        `season_policy` of `WINTER`, `SUMMER`, or `ALL_SEASON`, and a
        `capacity_items` of at least 1. A new zone starts with `current_stock` 0
        and posture `AVAILABLE`."

        Design: Corner/consistency_model/read_after_write_immediate_consistency
        """
        created = validate_success(
            api.create_storage_zone(
                {"zone_code": "ZIC", "season_policy": "WINTER", "capacity_items": 7},
                ADMIN),
            201)
        assert_storage_zone(created)
        assert created["current_stock"] == 0
        assert created["posture"] == "AVAILABLE"

        reread = validate_success(api.get_storage_zone(created["id"], ADMIN), 200)
        assert reread["current_stock"] == 0
        assert reread["posture"] == "AVAILABLE"
        assert reread["capacity_items"] == 7

    def test_zone_code_duplicate_rejected(self, api):
        """PRD: "A `ProgramAdmin` creates a zone with a globally unique
        `zone_code` (a duplicate is rejected with `ERR_ZONE_CODE_TAKEN`)"

        Design: Corner/validations/zone_code_duplicate_rejected
        """
        create_zone("ZDUP", "ALL_SEASON", 5)

        resp = api.create_storage_zone(
            {"zone_code": "ZDUP", "season_policy": "WINTER", "capacity_items": 3}, ADMIN)
        validate_error(resp, ApiErrorId.ERR_ZONE_CODE_TAKEN)


class TestZoneCapacityBoundary:
    def test_stocking_exactly_to_capacity_allowed_and_flips_full(self, api):
        """PRD: "When `current_stock` has reached `capacity_items`, the posture
        is `FULL`, and a zone that is `FULL` refuses any further stocking — the
        boundary is inclusive, so a zone holding exactly its capacity rejects
        the next item with `ERR_ZONE_FULL`."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_boundary
        """
        env = setup_stocked_items([dict(GOOD_TOPS), dict(GOOD_TOPS)],
                                  zone_code="ZD", capacity_items=2)
        zone = get_zone(env["zone"]["id"])
        assert zone["current_stock"] == 2, "landing exactly on capacity is allowed"
        assert zone["posture"] == "FULL", "2 >= 2 is FULL at the inclusive boundary"
        assert env["items"][1]["status"] == "STOCKED"

    def test_stocking_beyond_capacity_rejected(self, api):
        """PRD: "When `current_stock` has reached `capacity_items`, the posture
        is `FULL`, and a zone that is `FULL` refuses any further stocking — the
        boundary is inclusive, so a zone holding exactly its capacity rejects
        the next item with `ERR_ZONE_FULL`."

        Design: Difficulty/boundary_precision_check/zone_capacity_exact_boundary
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], item_count_declared=3)
        items = grade_items(batch["id"], [dict(GOOD_TOPS) for _ in range(3)],
                            staff["headers"])
        zone = create_zone("ZD", "ALL_SEASON", 2)
        stock_items([items[0]["id"], items[1]["id"]], zone["id"], staff["headers"])

        resp = api.stock_item(items[2]["id"], {"storage_zone_id": zone["id"]},
                              staff["headers"])
        validate_error(resp, ApiErrorId.ERR_ZONE_FULL)
        assert get_zone(zone["id"])["current_stock"] == 2


class TestZonePostureThreshold:
    def test_zone_posture_near_full_threshold(self, api):
        """PRD: "Below that, when `current_stock` is at least the result of
        multiplying `capacity_items` by 0.8 and rounding up to a whole number,
        the posture is `NEAR_FULL`. Otherwise the posture is `AVAILABLE`."

        Design: Corner/calculations/zone_posture_near_full_threshold
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], item_count_declared=4)
        items = grade_items(batch["id"], [dict(GOOD_TOPS) for _ in range(4)],
                            staff["headers"])
        zone = create_zone("ZNF", "ALL_SEASON", 5)

        stock_items([items[0]["id"], items[1]["id"], items[2]["id"]], zone["id"],
                    staff["headers"])
        zone = get_zone(zone["id"])
        assert zone["current_stock"] == 3
        assert zone["posture"] == "AVAILABLE", "3 < ceil(0.8 * 5) = 4"
        assert_zone_posture_invariants(zone)

        stock_items([items[3]["id"]], zone["id"], staff["headers"])
        zone = get_zone(zone["id"])
        assert zone["current_stock"] == 4
        assert zone["posture"] == "NEAR_FULL", "4 >= ceil(0.8 * 5) = 4 and 4 < 5"
        assert_zone_posture_invariants(zone)


class TestSeasonCompatibility:
    def test_season_incompatible_stocking(self, api):
        """PRD: "An item whose `season` is `ALL_SEASON` is compatible with every
        zone; a zone whose `season_policy` is `ALL_SEASON` accepts every item;
        otherwise the item's `season` must equal the zone's `season_policy`. A
        stocking attempt that breaks this rule is rejected with
        `ERR_SEASON_INCOMPATIBLE`."

        Design: Corner/validations/season_incompatible_stocking
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], item_count_declared=1)
        items = grade_items(batch["id"],
                            [{"category": "COATS", "season": "WINTER",
                              "quality_grade": "GOOD"}],
                            staff["headers"])
        summer_zone = create_zone("ZSUM", "SUMMER", 5)
        all_season_zone = create_zone("ZALL", "ALL_SEASON", 5)

        resp = api.stock_item(items[0]["id"], {"storage_zone_id": summer_zone["id"]},
                              staff["headers"])
        validate_error(resp, ApiErrorId.ERR_SEASON_INCOMPATIBLE)

        stocked = validate_success(
            api.stock_item(items[0]["id"], {"storage_zone_id": all_season_zone["id"]},
                           staff["headers"]),
            200)
        assert stocked["status"] == "STOCKED", "an ALL_SEASON zone accepts any season"
        assert stocked["storage_zone_id"] == all_season_zone["id"]


class TestZonePatch:
    def test_zone_patch_capacity_below_stock(self, api):
        """PRD: "The new capacity may not be set below the zone's live
        `current_stock` — such an update is rejected with
        `ERR_CAPACITY_BELOW_STOCK`."

        Design: Corner/validations/zone_patch_capacity_below_stock
        """
        env = setup_stocked_items([dict(GOOD_TOPS), dict(GOOD_TOPS)],
                                  zone_code="ZCS", capacity_items=3)
        zone = get_zone(env["zone"]["id"])
        assert zone["current_stock"] == 2

        resp = api.patch_storage_zone(
            zone["id"],
            patch_storage_zone_payload(zone["version"], capacity_items=1),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_STOCK)

    def test_occ_zone_stale_version(self, api):
        """PRD: "Updating a storage zone likewise requires `expected_zone_version`.
        Capacity changes interact with live stock counts and with the rotation
        placement selector, so a writer holding a stale zone snapshot must
        re-read before reapplying; a mismatch with the zone's current `version`
        is rejected with `ERR_STALE_VERSION`."

        Design: Corner/cross_cutting_layers/occ_zone_stale_version
        """
        zone = create_zone("ZOC", "ALL_SEASON", 4)
        observed_version = zone["version"]

        first = validate_success(
            api.patch_storage_zone(
                zone["id"],
                patch_storage_zone_payload(observed_version, capacity_items=6),
                ADMIN),
            200)
        assert first["capacity_items"] == 6
        assert first["version"] == observed_version + 1, (
            "version increments by one with every modification")

        resp = api.patch_storage_zone(
            zone["id"],
            patch_storage_zone_payload(observed_version, capacity_items=8),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)


class TestStockingValidationOrder:
    def test_stocking_stocked_item_into_full_zone_reports_state_error(self, api):
        """PRD: "Stocking shelves an item. The checks run in order: the item must
        be `PENDING_STOCK` (`ERR_INVALID_STATE`); the target zone must not be
        `FULL` — its `current_stock` must still be below `capacity_items`, an
        inclusive boundary per §2.8 (`ERR_ZONE_FULL`)"

        Design: Difficulty/priority_pair_validation_conflict/item_restock_state_beats_zone_full_constraint
        """
        env = setup_stocked_items([dict(GOOD_TOPS)], zone_code="Z1", capacity_items=1)
        item = env["items"][0]
        zone = get_zone(env["zone"]["id"])
        assert zone["posture"] == "FULL", "zone holds exactly its capacity"
        assert item["status"] == "STOCKED"

        resp = api.stock_item(item["id"], {"storage_zone_id": zone["id"]},
                              env["staff"]["headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_stocking_pending_item_into_full_zone_reports_zone_full(self, api):
        """PRD: "Stocking shelves an item. The checks run in order: the item must
        be `PENDING_STOCK` (`ERR_INVALID_STATE`); the target zone must not be
        `FULL` — its `current_stock` must still be below `capacity_items`, an
        inclusive boundary per §2.8 (`ERR_ZONE_FULL`)"

        Design: Difficulty/priority_pair_validation_conflict/item_restock_state_beats_zone_full_constraint
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], item_count_declared=2)
        items = grade_items(batch["id"], [dict(GOOD_TOPS), dict(GOOD_TOPS)],
                            staff["headers"])
        zone = create_zone("Z1", "ALL_SEASON", 1)
        stock_items([items[0]["id"]], zone["id"], staff["headers"])
        assert get_zone(zone["id"])["posture"] == "FULL"

        resp = api.stock_item(items[1]["id"], {"storage_zone_id": zone["id"]},
                              staff["headers"])
        validate_error(resp, ApiErrorId.ERR_ZONE_FULL)
