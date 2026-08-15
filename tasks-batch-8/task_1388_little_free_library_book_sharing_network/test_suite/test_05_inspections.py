"""Inspection cadence, map-accuracy enforcement, and spawned repairs."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_timestamp_equals,
    create_active_steward,
    create_chartered_box,
    create_steward_with_active_box,
    inspect_box,
    pin_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


class TestInspectionCadence:
    def test_inspection_at_29_days_rejected_too_soon(self, api):
        """PRD §3.3: "A `CONFIRMED` result refreshes the box's
        `last_activity_at` and triggers a posture recompute, but two
        confirmations may not crowd each other: a `CONFIRMED` inspection filed
        less than 30 days after the box's previous `CONFIRMED` inspection is
        rejected with `ERR_INSPECTION_TOO_SOON`."

        Design: Difficulty/resource_temporal_overlap/inspection_minimum_gap_buffer_30_days
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Priya Nair", box_name="Juniper Box"
        )
        # Activation-day CONFIRMED inspection was at 2026-08-01; +29 days.
        pin_clock("2026-08-30T00:00:00Z")
        res = api.create_inspection(
            box["id"], {"result": "CONFIRMED"}, TEST_USERS["mod1_headers"]
        )
        validate_error(res, ApiErrorId.ERR_INSPECTION_TOO_SOON.value,
                       expected_status=422)

    def test_inspection_at_exactly_30_days_accepted(self, api):
        """PRD §3.3: "a `CONFIRMED` inspection filed less than 30 days after
        the box's previous `CONFIRMED` inspection is rejected with
        `ERR_INSPECTION_TOO_SOON`."
        PRD §3.3: "A `CONFIRMED` result refreshes the box's `last_activity_at`
        and triggers a posture recompute."

        Design: Difficulty/resource_temporal_overlap/inspection_minimum_gap_buffer_30_days
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Priya Nair", box_name="Juniper Box"
        )
        # Exactly +30 days: outside the "less than 30 days" window.
        pin_clock("2026-08-31T00:00:00Z")
        inspection = validate_success(
            api.create_inspection(
                box["id"], {"result": "CONFIRMED"}, TEST_USERS["mod1_headers"]
            ),
            201,
        )
        assert inspection["result"] == "CONFIRMED"

        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert_timestamp_equals(after["last_activity_at"],
                                "2026-08-31T00:00:00Z")


class TestMapAccuracyEnforcement:
    def test_inspection_not_found_suspends_box_and_delists(self, api):
        """PRD §3.3: "A `NOT_FOUND` result on an `ACTIVE` box suspends it on
        the spot — `charter_status` drops to `SUSPENDED`, `suspended_at` is
        set, and the posture becomes `DELISTED` — while the same result on a
        `CHARTERED` or `SUSPENDED` box is simply stored without a charter
        change."

        Design: Corner/endpoints/inspection_not_found_suspends_box_and_delists
        """
        pin_clock()
        steward_a, box_active = create_steward_with_active_box(
            steward_name="Map Owner A", box_name="Active Map Box"
        )
        steward_b = create_active_steward(full_name="Map Owner B",
                                          email="mapb@example.org")
        box_chartered = create_chartered_box(steward_b, name="Chartered Map Box",
                                             capacity_books=8)

        inspect_box(box_active["id"], "NOT_FOUND",
                    notes="No box at listed coordinates")
        after_active = validate_success(api.get_box(box_active["id"], ADMIN),
                                        200)
        assert after_active["charter_status"] == "SUSPENDED"
        assert after_active["listing_posture"] == "DELISTED"
        assert_timestamp_equals(after_active["suspended_at"],
                                "2026-08-01T00:00:00Z")

        inspect_box(box_chartered["id"], "NOT_FOUND", notes="Site empty")
        after_chartered = validate_success(
            api.get_box(box_chartered["id"], ADMIN), 200
        )
        assert after_chartered["charter_status"] == "CHARTERED"
        assert after_chartered["listing_posture"] == "UNLISTED"

    def test_inspection_failed_condition_spawns_maintenance_request(self, api):
        """PRD §3.3: "A `FAILED_CONDITION` result spawns a maintenance request
        for the box in category `WEAR`, status `REPORTED`, severity still null,
        feeding §3.5."

        Design: Corner/endpoints/inspection_failed_condition_spawns_maintenance_request
        """
        pin_clock()
        _steward, box = create_steward_with_active_box(
            steward_name="Failed Cond", box_name="FC Box"
        )
        inspect_box(box["id"], "FAILED_CONDITION", notes="Shelf rotting")

        data, meta = validate_paginated(
            api.list_maintenance_requests(
                TEST_USERS["mod1_headers"], params={"box_id": box["id"]}
            )
        )
        assert meta["total_count"] == 1
        spawned = data[0]
        assert spawned["category"] == "WEAR"
        assert spawned["status"] == "REPORTED"
        assert spawned["severity"] is None
