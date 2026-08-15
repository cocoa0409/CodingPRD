"""Distribution lines: availability, per-visit allowance, category caps, the
rolling 30-day item cap, drive pools, and the checkout cascade."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    add_line,
    add_lines,
    assert_distribution_line,
    checkin_visit,
    create_drive,
    create_zone,
    get_client,
    get_item,
    get_zone,
    grade_items,
    open_batch_in_sort,
    register_client,
    set_clock,
    setup_sorting_staff,
    setup_stocked_items,
    stock_items,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}
GOOD_COATS_WINTER = {"category": "COATS", "season": "WINTER", "quality_grade": "GOOD"}


class TestLineAvailability:
    def test_line_add_unstocked_item_rejected(self, api):
        """PRD: "The request names an `item_id`; the visit must be `CHECKED_IN`
        and the item must be `STOCKED`, or the attempt fails with
        `ERR_ITEM_NOT_AVAILABLE`."

        Design: Corner/validations/line_add_unstocked_item_rejected
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="D",
                                   item_count_declared=1)
        items = grade_items(batch["id"], [dict(GOOD_TOPS)], staff["headers"])
        assert items[0]["status"] == "PENDING_STOCK"
        client = register_client("C", 2, None, staff["headers"])
        visit = checkin_visit(client["id"], staff["headers"])

        resp = api.add_line(visit["id"], {"item_id": items[0]["id"]}, staff["headers"])
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_AVAILABLE)


class TestCategoryCaps:
    def test_category_cap_coats_third_rejected(self, api):
        """PRD: "Second the category caps: a general line is rejected with
        `ERR_CATEGORY_LIMIT_EXCEEDED` when adding it would push the visit's
        `ACTIVE` general lines sharing its `category_snapshot` past the
        category's cap — `COATS` allows 2 per visit, `INTERVIEW_ATTIRE` allows 1,
        and all other categories are uncapped; drive lines are exempt from
        category caps because the drive pool already bounds them."

        Design: Corner/calculations/category_cap_coats_third_rejected
        """
        env = setup_stocked_items([dict(GOOD_COATS_WINTER) for _ in range(3)],
                                  zone_code="ZC1", capacity_items=10)
        headers = env["staff"]["headers"]
        client = register_client("C", 3, None, headers)
        visit = checkin_visit(client["id"], headers)

        line1 = add_line(visit["id"], env["items"][0]["id"], headers)
        line2 = add_line(visit["id"], env["items"][1]["id"], headers)
        assert_distribution_line(line1)
        assert line1["status"] == "ACTIVE"
        assert line1["category_snapshot"] == "COATS"
        assert line2["status"] == "ACTIVE", "cap 2 allows exactly two COATS lines"

        resp = api.add_line(visit["id"], {"item_id": env["items"][2]["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_CATEGORY_LIMIT_EXCEEDED)


class TestGeneralAllowanceLimit:
    def test_general_allowance_breach_rejected(self, api):
        """PRD: "First the per-visit allowance: the number of `ACTIVE` general
        (non-drive) lines on the visit must stay below `general_allowance`, and
        the number of `ACTIVE` drive lines drawn from any single drive must stay
        below that drive's per-client pool; a line that would exhaust either
        budget is rejected with `ERR_ITEM_LIMIT_EXCEEDED`."

        Design: Corner/validations/general_allowance_breach_rejected
        """
        env = setup_stocked_items([dict(GOOD_TOPS) for _ in range(9)],
                                  zone_code="ZGA", capacity_items=12)
        headers = env["staff"]["headers"]
        client = register_client("C", 1, None, headers)
        visit = checkin_visit(client["id"], headers)
        assert visit["general_allowance"] == 8

        lines = add_lines(visit["id"], [item["id"] for item in env["items"][:8]],
                          headers)
        assert lines[-1]["status"] == "ACTIVE", "exactly at the allowance"

        resp = api.add_line(visit["id"], {"item_id": env["items"][8]["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_LIMIT_EXCEEDED)


class TestRollingItemCap:
    def test_rolling_item_cap_boundary(self, api):
        """PRD: "Third the rolling item cap: when the client's `items_in_30d`
        plus the `ACTIVE` lines already on this visit plus the new line would
        exceed 30, the addition is rejected with
        `ERR_ROLLING_ITEM_CAP_EXCEEDED`."

        Design: Corner/calculations/rolling_item_cap_boundary
        """
        staff = setup_sorting_staff()
        headers = staff["headers"]
        zone = create_zone("ZRC", "ALL_SEASON", 40)
        batch1 = open_batch_in_sort(headers, donor_name="D", item_count_declared=16)
        items1 = grade_items(batch1["id"], [dict(GOOD_TOPS) for _ in range(16)],
                             headers)
        stock_items([item["id"] for item in items1], zone["id"], headers)
        batch2 = open_batch_in_sort(headers, donor_name="D2", item_count_declared=15)
        items2 = grade_items(batch2["id"], [dict(GOOD_TOPS) for _ in range(15)],
                             headers)
        stock_items([item["id"] for item in items2], zone["id"], headers)

        client = register_client("C", 10, None, headers)
        visit1 = checkin_visit(client["id"], headers)
        assert visit1["general_allowance"] == 16, "min(24, min(16, 8 + 2*9))"
        add_lines(visit1["id"], [item["id"] for item in items1], headers)
        validate_success(api.checkout_visit(visit1["id"], headers), 200)
        assert get_client(client["id"])["items_in_30d"] == 16

        set_clock("2026-08-15T00:00:00Z")
        visit2 = checkin_visit(client["id"], headers)
        lines = add_lines(visit2["id"], [item["id"] for item in items2[:14]], headers)
        assert lines[-1]["status"] == "ACTIVE", (
            "16 + 14 = 30 in-window items: exactly at the cap, allowed")

        resp = api.add_line(visit2["id"], {"item_id": items2[14]["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_ROLLING_ITEM_CAP_EXCEEDED)


class TestDrivePools:
    def test_drive_bonus_pool_and_category_exemption(self, api):
        """PRD: "At check-in, every `ACTIVE` drive grants the visit up to
        `bonus_items_per_client` additional lines, provided each such line's item
        is dedicated to that drive's pool. Drive lines never consume
        `general_allowance`, and general items never consume drive pools; the two
        budgets are accounted separately."
        PRD: "drive lines are exempt from category caps because the drive pool
        already bounds them."
        PRD: "First the per-visit allowance: the number of `ACTIVE` general
        (non-drive) lines on the visit must stay below `general_allowance`, and
        the number of `ACTIVE` drive lines drawn from any single drive must stay
        below that drive's per-client pool; a line that would exhaust either
        budget is rejected with `ERR_ITEM_LIMIT_EXCEEDED`."

        Design: Corner/calculations/drive_bonus_pool_and_category_exemption
        """
        staff = setup_sorting_staff()
        headers = staff["headers"]
        drive = create_drive("INTERVIEW_ATTIRE", "INTERVIEW_ATTIRE",
                             "2026-08-01T00:00:00Z", "2026-08-20T00:00:00Z",
                             bonus_items_per_client=2)
        drive_item = {"category": "INTERVIEW_ATTIRE", "season": "ALL_SEASON",
                      "quality_grade": "GOOD", "drive_id": drive["id"]}
        batch = open_batch_in_sort(headers, donor_name="D", item_count_declared=4)
        items = grade_items(batch["id"],
                            [dict(drive_item), dict(drive_item), dict(drive_item),
                             {"category": "INTERVIEW_ATTIRE", "season": "ALL_SEASON",
                              "quality_grade": "GOOD"}],
                            headers)
        zone = create_zone("ZDR", "ALL_SEASON", 10)
        stock_items([item["id"] for item in items], zone["id"], headers)

        client = register_client("C", 2, None, headers)
        # Check-in evaluates the drive pools available to the visit.
        visit = checkin_visit(client["id"], headers)

        line1 = add_line(visit["id"], items[0]["id"], headers)
        line2 = add_line(visit["id"], items[1]["id"], headers)
        assert line1["is_drive_line"] is True and line2["is_drive_line"] is True, (
            "two drive lines exceed the category cap 1 but are exempt")

        resp = api.add_line(visit["id"], {"item_id": items[2]["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_LIMIT_EXCEEDED)

        general = add_line(visit["id"], items[3]["id"], headers)
        assert general["is_drive_line"] is False
        assert general["drive_id"] is None
        assert general["status"] == "ACTIVE", (
            "first general INTERVIEW_ATTIRE line against category cap 1")

    def test_drive_item_stockable_while_upcoming_but_line_blocked(self, api):
        """PRD: "when the item is dedicated to a drive pool, that drive must be
        `UPCOMING` or `ACTIVE` (`ERR_DRIVE_NOT_ACTIVE`)."
        PRD: "Fourth, for an item dedicated to a drive, the drive must be
        `ACTIVE` at line-add time, or the addition fails with
        `ERR_DRIVE_NOT_ACTIVE`."

        Design: Difficulty/cross_entity_state_dependency/drive_line_requires_drive_active
        """
        staff = setup_sorting_staff()
        headers = staff["headers"]
        drive = create_drive("INTERVIEW_ATTIRE", "INTERVIEW_ATTIRE",
                             "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
                             bonus_items_per_client=2)
        batch = open_batch_in_sort(headers, donor_name="Donor K",
                                   item_count_declared=1)
        items = grade_items(batch["id"],
                            [{"category": "INTERVIEW_ATTIRE", "season": "ALL_SEASON",
                              "quality_grade": "NEW_WITH_TAGS",
                              "drive_id": drive["id"]}],
                            headers)
        zone = create_zone("ZE", "ALL_SEASON", 10)
        stocked = stock_items([items[0]["id"]], zone["id"], headers)[0]
        assert stocked["status"] == "STOCKED", "stocking allowed while UPCOMING"

        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        resp = api.add_line(visit["id"], {"item_id": items[0]["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_DRIVE_NOT_ACTIVE)

    def test_drive_line_added_once_drive_active(self, api):
        """PRD: "Fourth, for an item dedicated to a drive, the drive must be
        `ACTIVE` at line-add time, or the addition fails with
        `ERR_DRIVE_NOT_ACTIVE`."
        PRD: "When the item is dedicated to a drive pool and its drive is
        `ACTIVE`, the line is flagged `is_drive_line` and its `drive_id` names
        the drive whose bonus pool it consumes; otherwise the flag is false and
        `drive_id` is null."
        PRD: "A special drive moves from `UPCOMING` to `ACTIVE` when the clock
        stands within its window, and from `ACTIVE` to `CLOSED` once the window
        has passed; these advancements occur whenever the drive is read and
        whenever a check-in evaluates the drive pools available to a visit."

        Design: Difficulty/cross_entity_state_dependency/drive_line_requires_drive_active
        """
        staff = setup_sorting_staff()
        headers = staff["headers"]
        drive = create_drive("INTERVIEW_ATTIRE", "INTERVIEW_ATTIRE",
                             "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
                             bonus_items_per_client=2)
        batch = open_batch_in_sort(headers, donor_name="Donor K",
                                   item_count_declared=1)
        items = grade_items(batch["id"],
                            [{"category": "INTERVIEW_ATTIRE", "season": "ALL_SEASON",
                              "quality_grade": "NEW_WITH_TAGS",
                              "drive_id": drive["id"]}],
                            headers)
        zone = create_zone("ZE", "ALL_SEASON", 10)
        stock_items([items[0]["id"]], zone["id"], headers)
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)

        set_clock("2026-08-10T00:00:00Z")
        drive = validate_success(api.get_drive(drive["id"], ADMIN), 200)
        assert drive["status"] == "ACTIVE", "window reached: lazily advanced on read"

        line = validate_success(
            api.add_line(visit["id"], {"item_id": items[0]["id"]}, headers), 201)
        assert line["is_drive_line"] is True
        assert line["drive_id"] == drive["id"]
        assert line["status"] == "ACTIVE"


class TestCheckout:
    def test_checkout_empty_visit_rejected(self, api):
        """PRD: "Checkout finalizes a visit. The visit must be `CHECKED_IN`
        (otherwise `ERR_INVALID_STATE`) and must hold at least one `ACTIVE` line
        (otherwise `ERR_EMPTY_VISIT_CHECKOUT`)."

        Design: Corner/state_machines/checkout_empty_visit_rejected
        """
        staff = setup_sorting_staff()
        client = register_client("C", 2, None, staff["headers"])
        visit = checkin_visit(client["id"], staff["headers"])

        resp = api.checkout_visit(visit["id"], staff["headers"])
        validate_error(resp, ApiErrorId.ERR_EMPTY_VISIT_CHECKOUT)
        reread = validate_success(api.get_visit(visit["id"], ADMIN), 200)
        assert reread["status"] == "CHECKED_IN"

    def test_checkout_cascades_item_distribution_and_zone_posture(self, api):
        """PRD: "On checkout every `ACTIVE` line becomes `DISTRIBUTED`, and each
        reserved item moves from `RESERVED` to `DISTRIBUTED`: the item's
        `distributed_at` is stamped, the zone it left is remembered in
        `distributed_from_zone_id`, its `storage_zone_id` and `reserved_visit_id`
        are cleared, the zone's `current_stock` is decremented, and the zone's
        `posture` is recomputed."
        PRD: "When `current_stock` has reached `capacity_items`, the posture is
        `FULL`"

        Design: Difficulty/transitive_cascade/checkout_item_zone_posture_cascade
        """
        env = setup_stocked_items([dict(GOOD_TOPS), dict(GOOD_TOPS)],
                                  zone_code="ZC", capacity_items=2)
        headers = env["staff"]["headers"]
        zone_id = env["zone"]["id"]
        assert get_zone(zone_id)["posture"] == "FULL", "2 >= 2"

        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        add_line(visit["id"], env["items"][0]["id"], headers)
        checked_out = validate_success(api.checkout_visit(visit["id"], headers), 200)
        assert checked_out["status"] == "CHECKED_OUT"

        item = get_item(env["items"][0]["id"])
        assert item["status"] == "DISTRIBUTED"
        zone = get_zone(zone_id)
        assert zone["current_stock"] == 1
        assert zone["posture"] == "AVAILABLE", "1 < ceil(0.8 * 2) = 2"

    def test_checkout_stamps_distribution_fields(self, api):
        """PRD: "On checkout every `ACTIVE` line becomes `DISTRIBUTED`, and each
        reserved item moves from `RESERVED` to `DISTRIBUTED`: the item's
        `distributed_at` is stamped, the zone it left is remembered in
        `distributed_from_zone_id`, its `storage_zone_id` and `reserved_visit_id`
        are cleared, the zone's `current_stock` is decremented, and the zone's
        `posture` is recomputed. The visit stamps `checked_out_at`, the client's
        `last_checkout_at` is set to the same instant, and the client's rolling
        counters are recomputed."

        Design: Difficulty/transitive_cascade/checkout_item_zone_posture_cascade
        """
        env = setup_stocked_items([dict(GOOD_TOPS), dict(GOOD_TOPS)],
                                  zone_code="ZC", capacity_items=2)
        headers = env["staff"]["headers"]
        zone_id = env["zone"]["id"]
        client = register_client("C", 2, None, headers)
        visit = checkin_visit(client["id"], headers)
        line = add_line(visit["id"], env["items"][0]["id"], headers)

        checked_out = validate_success(api.checkout_visit(visit["id"], headers), 200)
        assert checked_out["checked_out_at"] is not None

        line = validate_success(api.get_distribution_line(line["id"], ADMIN), 200)
        assert line["status"] == "DISTRIBUTED"
        item = get_item(env["items"][0]["id"])
        assert item["distributed_at"] is not None
        assert item["distributed_from_zone_id"] == zone_id
        assert item["storage_zone_id"] is None
        assert item["reserved_visit_id"] is None
        client = get_client(client["id"])
        assert client["last_checkout_at"] == checked_out["checked_out_at"]
        assert client["visits_in_30d"] == 1
        assert client["items_in_30d"] == 1
