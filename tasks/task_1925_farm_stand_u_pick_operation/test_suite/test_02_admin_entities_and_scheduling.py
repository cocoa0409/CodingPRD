"""Season/crop/field administration, scheduling constraints, and policy OCC."""
from test_helpers import (
    TEST_USERS,
    activate_season,
    assert_season,
    create_crop,
    create_crop_payload,
    create_field,
    create_sales_day,
    create_sales_day_payload,
    create_season,
    create_season_payload,
    create_window,
    is_iso8601_timestamp,
    is_valid_uuid,
    validate_error,
    validate_paginated,
    validate_success,
)

MANAGER = TEST_USERS["farm_manager_headers"]


class TestSeasonCreation:
    def test_season_create_applies_defaults_and_system_fields(self, api):
        """PRD §3.1: "A new season is born in `DRAFT` status with
        `current_waiver_version` set to 1."
        PRD §2.5: "`id` is a server-minted UUID with no type prefix"
        PRD §3.1: "a `start_date` and an `end_date` (both ISO calendar dates,
        both inclusive, and `end_date` must not fall before `start_date`)"
        PRD §2.7: "Violations yield `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/season_create_applies_defaults_and_system_fields
        """
        season = create_season()
        assert_season(season)
        assert season["status"] == "DRAFT", "A new season is born DRAFT"
        assert season["current_waiver_version"] == 1
        assert is_valid_uuid(season["id"]), "id is a bare server-minted UUID"
        assert is_iso8601_timestamp(season["created_at"])

        resp = api.create_season(
            create_season_payload(name="Bad", start_date="2026-08-31",
                                  end_date="2026-08-01", waiver_text="X"),
            MANAGER)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)


class TestCropCreation:
    def test_crop_create_unknown_field_input_ignored_rejected(self, api):
        """PRD §2.7: "required fields are present, types are correct, enum
        values are in range, no undeclared fields appear"
        PRD §3.2: "its `season_picked_oz` tally starts at zero."

        Design: Corner/entities/crop_create_unknown_field_input_ignored_rejected
        """
        season = create_season()
        payload = create_crop_payload(season["id"])
        payload["season_picked_oz"] = 5  # computed field is server-owned
        resp = api.create_crop(payload, MANAGER)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

        crop = create_crop(season["id"], name="Strawberry", price_per_lb_cents=480)
        assert crop["season_picked_oz"] == 0, "the tally starts at zero"

    def test_crop_missing_required_price_rejected(self, api):
        """PRD §3.2: "A crop is registered with `season_id`, `name` (for example
        \"Strawberry\"), and `price_per_lb_cents`, a strictly positive integer
        number of cents per pound"
        PRD §2.7: "required fields are present, types are correct, enum values
        are in range, no undeclared fields appear"

        Design: Corner/entities/crop_missing_required_price_rejected
        """
        season = create_season()
        payload = {"season_id": season["id"], "name": "Strawberry"}
        resp = api.create_crop(payload, MANAGER)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)


class TestSalesDayCreation:
    def test_sales_day_invalid_enum_rejected(self, api):
        """PRD §3.3: "a `day_type` of `WEEKDAY` or `WEEKEND` that drives surge
        pricing"
        PRD §2.7: "required fields are present, types are correct, enum values
        are in range, no undeclared fields appear"

        Design: Corner/entities/sales_day_invalid_enum_rejected
        """
        season = create_season()
        resp = api.create_sales_day(
            create_sales_day_payload(season["id"], day_type="FUNDAY"), MANAGER)
        validate_error(resp, "ERR_INVALID_REQUEST", 400)

    def test_sales_day_duplicate_date_rejected(self, api):
        """PRD §3.3: "a `date` that must be unique within the season
        (`ERR_SALES_DAY_EXISTS`, 409) and must fall inside the season's
        inclusive range (`ERR_DATE_OUTSIDE_SEASON`, 422)"

        Design: Corner/validations/sales_day_duplicate_date_rejected
        """
        season = create_season()
        activate_season(season["id"])
        create_sales_day(season["id"], date="2026-08-04")
        resp = api.create_sales_day(
            create_sales_day_payload(season["id"], date="2026-08-04",
                                     parking_capacity=99, staff_on_duty=9),
            MANAGER)
        validate_error(resp, "ERR_SALES_DAY_EXISTS", 409)


class TestFieldListing:
    def test_fields_list_pagination_envelope(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit`,
        which defaults to 10 and must be at least 1 and at most 100, and
        `offset`, which defaults to 0. List responses are always sorted by
        `created_at` in ascending order, oldest first."

        Design: Corner/entities/fields_list_pagination_envelope
        """
        season = create_season()
        f1 = create_field(season["id"], name="North", rotation_order=1)
        f2 = create_field(season["id"], name="South", rotation_order=2,
                          estimated_harvest_oz=500)

        page1, meta1 = validate_paginated(
            api.list_fields(MANAGER, params={"season_id": season["id"],
                                             "limit": 1, "offset": 0}))
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert len(page1) == 1
        assert page1[0]["id"] == f1["id"], "oldest first by created_at"

        page2, meta2 = validate_paginated(
            api.list_fields(MANAGER, params={"season_id": season["id"],
                                             "limit": 1, "offset": 1}))
        assert meta2["has_more"] is False
        assert page2[0]["id"] == f2["id"]
        assert page1[0]["id"] != page2[0]["id"]


class TestWindowScheduling:
    def test_window_date_outside_season_rejected(self, api):
        """PRD §3.3: "Scheduling a window takes `field_id`, a `date` within the
        field's season range (`ERR_DATE_OUTSIDE_SEASON`)"

        Design: Corner/validations/window_date_outside_season_rejected
        """
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        resp = api.create_window(
            {"field_id": field["id"], "date": "2026-09-05",
             "open_time": "09:00", "close_time": "17:00",
             "picking_capacity_slots": 30},
            MANAGER)
        validate_error(resp, "ERR_DATE_OUTSIDE_SEASON", 422)

    def test_staffing_ceiling_exact_multiple_then_overflow(self, api):
        """PRD §3.3: "the required staff for a date is the total
        `picking_capacity_slots` over all non-`CANCELLED` windows of that date —
        including the window being created — divided by 25 slots per staff
        member and rounded up to a whole number, and creation is rejected with
        `ERR_INSUFFICIENT_STAFFING` (422) when the sales day's `staff_on_duty`
        is below that requirement."
        PRD §3.3: "The boundary divides evenly: a date carrying exactly 50
        slots requires exactly 2 staff."

        Design: Corner/calculations/staffing_ceiling_exact_multiple_then_overflow
        """
        season = create_season()
        activate_season(season["id"])
        field = create_field(season["id"])
        create_sales_day(season["id"], date="2026-08-04", staff_on_duty=2)

        create_window(field["id"], date="2026-08-04", open_time="09:00",
                      close_time="12:00", picking_capacity_slots=25)
        # Total 50 slots: exactly divisible, 2 staff required and available.
        create_window(field["id"], date="2026-08-04", open_time="13:00",
                      close_time="16:00", picking_capacity_slots=25)
        # Total 51 slots: ceil(51/25) = 3 > 2 staff on duty.
        resp = api.create_window(
            {"field_id": field["id"], "date": "2026-08-04",
             "open_time": "16:00", "close_time": "18:00",
             "picking_capacity_slots": 1},
            MANAGER)
        validate_error(resp, "ERR_INSUFFICIENT_STAFFING", 422)


class TestPricingPolicyOcc:
    def test_occ_policy_create_stale_version_rejected(self, api):
        """PRD §2.6: "A policy-creation request must therefore carry
        `expected_season_version` equal to the target season's current
        `version`; since versions only ever increase, the observable mismatch
        is a value below the current one, meaning the caller priced against a
        policy configuration it never observed. A mismatch is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.1: "The first policy created for a season takes `policy_version`
        1 and status `ACTIVE`."

        Design: Corner/cross_cutting_layers/occ_policy_create_stale_version_rejected
        """
        season = create_season()
        season = activate_season(season["id"])
        observed_version = season["version"]

        first = validate_success(api.create_pricing_policy(
            {"season_id": season["id"],
             "expected_season_version": observed_version,
             "admission_per_person_cents": 650, "container_fee_cents": 200,
             "weekend_surge_bps": 12500, "bundle_discount_bps": 1000,
             "bundle_cap_cents": 1500},
            MANAGER), 201)
        assert first["policy_version"] == 1
        assert first["status"] == "ACTIVE"

        version_after_first = validate_success(
            api.get_season(season["id"], MANAGER))["version"]

        resp = api.create_pricing_policy(
            {"season_id": season["id"],
             "expected_season_version": observed_version,
             "admission_per_person_cents": 700, "container_fee_cents": 250,
             "weekend_surge_bps": 10000, "bundle_discount_bps": 0,
             "bundle_cap_cents": 0},
            MANAGER)
        validate_error(resp, "ERR_STALE_VERSION", 412)

        version_after_reject = validate_success(
            api.get_season(season["id"], MANAGER))["version"]
        assert version_after_reject == version_after_first, (
            "The rejected create bumped nothing on the season")
