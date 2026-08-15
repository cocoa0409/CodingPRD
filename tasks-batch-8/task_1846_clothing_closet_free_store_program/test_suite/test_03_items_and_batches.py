"""Donation intake, sorting staffing, item grading, quarantine, and item
listing."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_donation_batch,
    assert_item,
    checkin_signup,
    create_donation_batch_payload,
    create_shift,
    create_zone,
    get_zone,
    grade_items,
    make_volunteer_lead_headers,
    open_batch_in_sort,
    quarantine_item,
    register_volunteer,
    release_quarantine,
    setup_sorting_staff,
    setup_stocked_items,
    signup_volunteer,
    stock_items,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["program_admin_headers"]

GOOD_TOPS = {"category": "ADULT_TOPS", "season": "ALL_SEASON", "quality_grade": "GOOD"}


class TestItemCreation:
    def test_item_create_system_fields_input_ignored(self, api):
        """PRD: "Each item record names its `donation_batch_id`, its `category`
        (`ADULT_TOPS`, `ADULT_BOTTOMS`, `CHILDRENS`, `COATS`, `INTERVIEW_ATTIRE`,
        or `ACCESSORIES`), its `season` (`WINTER`, `SUMMER`, or `ALL_SEASON`),
        and its `quality_grade` (`NEW_WITH_TAGS`, `GOOD`, `FAIR`, or `REJECT`),
        and may optionally dedicate the item to a drive pool via `drive_id`. The
        grader is recorded in `graded_by_user_id`. An item graded `REJECT` goes
        straight to `REJECTED` status and awaits the recycling channel; every
        other grade lands in `PENDING_STOCK`."

        Design: Corner/entities/item_create_system_fields_input_ignored
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="D",
                                   item_count_declared=1)

        resp = api.create_batch_item(
            batch["id"],
            {"category": "ADULT_TOPS", "season": "SUMMER", "quality_grade": "GOOD",
             "status": "RECYCLED",
             "storage_zone_id": "8a3e1c0b-2f4d-4a91-9c8b-12e7b6a0f1d2"},
            staff["headers"])
        item = validate_success(resp, 201)
        assert_item(item)
        assert item["status"] == "PENDING_STOCK", "a GOOD grade lands in PENDING_STOCK"
        assert item["storage_zone_id"] is None, "not shelved until stocking"
        assert item["graded_by_user_id"] == staff["volunteer"]["id"], (
            "the grader is the acting user's identifier")

    def test_item_create_invalid_enum_rejected(self, api):
        """PRD: "The cascade runs as follows: first, header presence and role
        recognition (`ERR_UNAUTHENTICATED`); second, role authorization on the
        endpoint (`ERR_FORBIDDEN`); third, ownership scoping for entity-backed
        roles (`ERR_FORBIDDEN`); fourth, existence of every referenced identifier
        (`ERR_NOT_FOUND`); fifth, request shape — required fields present, types
        and enum values valid, numeric ranges satisfied (`ERR_INVALID_REQUEST`)"

        Design: Corner/entities/item_create_invalid_enum_rejected
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="D",
                                   item_count_declared=1)

        resp = api.create_batch_item(
            batch["id"],
            {"category": "HATS", "season": "SUMMER", "quality_grade": "GOOD"},
            staff["headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestItemListing:
    def test_items_list_pagination_envelope(self, api):
        """PRD: "The `limit` parameter specifies the maximum number of items to
        return; it defaults to 10 when omitted, with a minimum of 1 and a maximum
        of 100. The `offset` parameter specifies the number of items to skip and
        defaults to 0."
        PRD: "Paginated list responses include the following fields in the `meta`
        object of the response envelope: `limit`, `offset`, `total_count`, and
        `has_more`."

        Design: Corner/entities/items_list_pagination_envelope
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="D",
                                   item_count_declared=3)
        grade_items(batch["id"], [dict(GOOD_TOPS) for _ in range(3)], staff["headers"])

        page1, meta1 = validate_paginated(
            api.list_items(ADMIN, params={"limit": 2, "offset": 0}))
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        assert len(page1) == 2

        page2, meta2 = validate_paginated(
            api.list_items(ADMIN, params={"limit": 2, "offset": 2}))
        assert meta2["has_more"] is False
        assert len(page2) == 1

    def test_items_filtered_by_zone_reverse_fk(self, api):
        """PRD: "Items can be listed with `donation_batch_id`, `storage_zone_id`,
        `drive_id`, `recycling_batch_id`, `status`, `season`, or `category`
        filters."

        Design: Corner/endpoints/items_filtered_by_zone_reverse_fk
        """
        staff = setup_sorting_staff()
        batch = open_batch_in_sort(staff["headers"], donor_name="D",
                                   item_count_declared=3)
        items = grade_items(batch["id"], [dict(GOOD_TOPS) for _ in range(3)],
                            staff["headers"])
        zone_a = create_zone("ZFA", "ALL_SEASON", 5)
        zone_b = create_zone("ZFB", "ALL_SEASON", 5)
        stock_items([items[0]["id"], items[1]["id"]], zone_a["id"], staff["headers"])
        stock_items([items[2]["id"]], zone_b["id"], staff["headers"])

        page, meta = validate_paginated(
            api.list_items(ADMIN, params={"storage_zone_id": zone_a["id"]}))
        assert meta["total_count"] == 2, "only the two items stocked into zone A"
        assert {row["id"] for row in page} == {items[0]["id"], items[1]["id"]}


class TestBatchLifecycle:
    def test_batch_auto_sorted_when_declared_reached(self, api):
        """PRD: "A new batch opens in `RECEIVED` status."
        PRD: "Starting the sort moves a batch from `RECEIVED` to `IN_SORT`"
        PRD: "The batch tracks how many items have been created in
        `items_created_count`, and the moment that count reaches
        `item_count_declared` the batch advances automatically from `IN_SORT` to
        `SORTED`."

        Design: Corner/state_machines/batch_auto_sorted_when_declared_reached
        """
        staff = setup_sorting_staff()
        created = validate_success(
            api.create_donation_batch(
                create_donation_batch_payload(donor_name="D", item_count_declared=2),
                staff["headers"]),
            201)
        assert_donation_batch(created)
        assert created["status"] == "RECEIVED"

        in_sort = validate_success(
            api.start_sorting(created["id"], staff["headers"]), 200)
        assert in_sort["status"] == "IN_SORT"

        grade_items(created["id"], [dict(GOOD_TOPS),
                                    {"category": "ADULT_TOPS", "season": "ALL_SEASON",
                                     "quality_grade": "FAIR"}],
                    staff["headers"])
        batch = validate_success(api.get_donation_batch(created["id"], ADMIN), 200)
        assert batch["status"] == "SORTED", "auto-advances when the count is reached"
        assert batch["items_created_count"] == 2

    def test_batch_item_create_rejected_when_not_in_sort(self, api):
        """PRD: "While a batch is `IN_SORT`, sorters create and grade items
        against it — the batch must be `IN_SORT` or item creation fails with
        `ERR_INVALID_STATE`."

        Design: Corner/state_machines/batch_item_create_rejected_when_not_in_sort
        """
        staff = setup_sorting_staff()
        batch = validate_success(
            api.create_donation_batch(
                create_donation_batch_payload(donor_name="D", item_count_declared=1),
                staff["headers"]),
            201)
        assert batch["status"] == "RECEIVED"

        resp = api.create_batch_item(batch["id"], dict(GOOD_TOPS), staff["headers"])
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_batch_close_sod_and_second_lead(self, api):
        """PRD: "A `VolunteerLead` or `ProgramAdmin` moves a `SORTED` batch to
        `CLOSED`, recording themselves in `closed_by_user_id`. Segregation of
        duties applies: the operator who started the sort may not close the same
        batch — if the acting user's identifier equals the batch's
        `sorted_by_user_id`, the close is rejected with
        `ERR_SOD_SORTER_CANNOT_CLOSE`."

        Design: Corner/state_machines/batch_close_sod_and_second_lead
        """
        lead_one = register_volunteer("Lead One", is_lead=True)
        lead_two = register_volunteer("Lead Two", is_lead=True)
        lead_one_headers = make_volunteer_lead_headers(lead_one["id"])
        lead_two_headers = make_volunteer_lead_headers(lead_two["id"])
        shift = create_shift("2026-07-31T22:00:00Z", "2026-08-01T04:00:00Z",
                             role_type="SORTING", capacity_volunteers=2)
        signup = signup_volunteer(shift["id"], lead_one)
        checkin_signup(shift["id"], signup["id"], lead_one)
        batch = open_batch_in_sort(lead_one_headers, donor_name="D",
                                   item_count_declared=1)
        grade_items(batch["id"], [dict(GOOD_TOPS)], lead_one_headers)

        resp = api.close_donation_batch(batch["id"], lead_one_headers)
        validate_error(resp, ApiErrorId.ERR_SOD_SORTER_CANNOT_CLOSE)

        closed = validate_success(
            api.close_donation_batch(batch["id"], lead_two_headers), 200)
        assert closed["status"] == "CLOSED"
        assert closed["closed_by_user_id"] == lead_two["id"]


class TestSortingStaffGuard:
    def test_start_sorting_without_checked_in_staff_rejected(self, api):
        """PRD: "Starting the sort moves a batch from `RECEIVED` to `IN_SORT` and
        records the operator in `sorted_by_user_id`; it requires at least one
        signup in `CHECKED_IN` status whose shift has `role_type` `SORTING`,
        whose shift status is `OPEN` or `LOCKED`, and whose shift window covers
        the current instant — otherwise the attempt is rejected with
        `ERR_NO_SORTING_STAFF`."

        Design: Difficulty/cross_entity_state_dependency/sorting_requires_checked_in_sorting_shift
        """
        staff = setup_sorting_staff(check_in=False)
        batch = validate_success(
            api.create_donation_batch(
                create_donation_batch_payload(donor_name="Donor J",
                                              item_count_declared=1),
                staff["headers"]),
            201)

        resp = api.start_sorting(batch["id"], staff["headers"])
        validate_error(resp, ApiErrorId.ERR_NO_SORTING_STAFF)

    def test_start_sorting_with_checked_in_staff_succeeds(self, api):
        """PRD: "Starting the sort moves a batch from `RECEIVED` to `IN_SORT` and
        records the operator in `sorted_by_user_id`; it requires at least one
        signup in `CHECKED_IN` status whose shift has `role_type` `SORTING`,
        whose shift status is `OPEN` or `LOCKED`, and whose shift window covers
        the current instant — otherwise the attempt is rejected with
        `ERR_NO_SORTING_STAFF`."

        Design: Difficulty/cross_entity_state_dependency/sorting_requires_checked_in_sorting_shift
        """
        staff = setup_sorting_staff(check_in=False)
        batch = validate_success(
            api.create_donation_batch(
                create_donation_batch_payload(donor_name="Donor J",
                                              item_count_declared=1),
                staff["headers"]),
            201)
        checkin_signup(staff["shift"]["id"], staff["signup"]["id"], staff["volunteer"])

        started = validate_success(api.start_sorting(batch["id"], staff["headers"]), 200)
        assert started["status"] == "IN_SORT"
        assert started["sorted_by_user_id"] == staff["volunteer"]["id"]


class TestQuarantineCycle:
    def test_quarantine_restock_cycle_restores_shelf(self, api):
        """PRD: "Quarantine pulls a stocked item off the shelf. A `VolunteerLead`
        or `ProgramAdmin` moves a `STOCKED` item to `QUARANTINED`; the item
        leaves the shelf, so the zone's `current_stock` is decremented and
        `posture` recomputed. Releasing quarantine takes an `outcome`: with
        `RESTOCK` the item returns to `STOCKED` in the same zone it was pulled
        from, bypassing the capacity check — a quarantined garment must never be
        stranded by a shelf that filled behind it — with `stocked_at` refreshed
        and the zone's stock and posture cascaded"

        Design: Difficulty/non_linear_state_machine/item_quarantine_cycle_and_reject_branch
        """
        env = setup_stocked_items(
            [dict(GOOD_TOPS),
             {"category": "ADULT_BOTTOMS", "season": "ALL_SEASON",
              "quality_grade": "GOOD"}],
            zone_code="ZQ", capacity_items=10)
        lead = register_volunteer("Lead One", is_lead=True)
        lead_headers = make_volunteer_lead_headers(lead["id"])
        zone_id = env["zone"]["id"]
        item_one = env["items"][0]
        assert get_zone(zone_id)["current_stock"] == 2

        quarantined = quarantine_item(item_one["id"], lead_headers)
        assert quarantined["status"] == "QUARANTINED"
        assert get_zone(zone_id)["current_stock"] == 1, (
            "a quarantined item leaves the shelf")

        restocked = release_quarantine(item_one["id"], "RESTOCK", lead_headers)
        assert restocked["status"] == "STOCKED", "the STOCKED -> QUARANTINED -> STOCKED loop"
        assert restocked["storage_zone_id"] == zone_id, "restocked into the same zone"
        assert get_zone(zone_id)["current_stock"] == 2

    def test_quarantine_reject_branch_leaves_shelf(self, api):
        """PRD: "with `REJECT` the item becomes `REJECTED`, its `storage_zone_id`
        is cleared, and it awaits the recycling sweep. Either release requires
        the item to be `QUARANTINED` (otherwise `ERR_INVALID_STATE`), and
        quarantine itself requires the item to be `STOCKED`."

        Design: Difficulty/non_linear_state_machine/item_quarantine_cycle_and_reject_branch
        """
        env = setup_stocked_items(
            [dict(GOOD_TOPS),
             {"category": "ADULT_BOTTOMS", "season": "ALL_SEASON",
              "quality_grade": "GOOD"}],
            zone_code="ZQ", capacity_items=10)
        lead = register_volunteer("Lead One", is_lead=True)
        lead_headers = make_volunteer_lead_headers(lead["id"])
        zone_id = env["zone"]["id"]
        item_two = env["items"][1]

        quarantine_item(item_two["id"], lead_headers)
        rejected = release_quarantine(item_two["id"], "REJECT", lead_headers)
        assert rejected["status"] == "REJECTED", "the branch out of QUARANTINED"
        assert rejected["storage_zone_id"] is None
        assert get_zone(zone_id)["current_stock"] == 1, (
            "only the untouched item remains on the shelf")
