"""Box chartering, activation gates, capacity limits, and immediate reads."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_active_steward,
    create_box_payload,
    create_chartered_box,
    create_draft_box,
    create_steward_with_active_box,
    inspect_box,
    make_steward_headers,
    pin_clock,
    run_sweep,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
MOD1 = TEST_USERS["mod1_headers"]


class TestCharterNumbers:
    def test_box_charter_mints_sequential_charter_numbers(self, api):
        """PRD §3.3: "When a `NetworkAdmin` moves a `DRAFT` box to `CHARTERED`
        — again requiring the owning steward to be `ACTIVE`, failing with
        `ERR_STEWARD_NOT_ACTIVE` otherwise — the network mints the box's
        `charter_number`: the prefix `CH-` followed by a six-digit zero-padded
        sequence equal to one more than the count of previously chartered
        boxes, so the first charter ever issued is `CH-000001`."

        Design: Corner/state_machines/box_charter_mints_sequential_charter_numbers
        """
        pin_clock()
        steward1 = create_active_steward(full_name="Charter One",
                                         email="c1@example.org")
        steward2 = create_active_steward(full_name="Charter Two",
                                         email="c2@example.org")
        box1 = create_draft_box(steward1, name="First Box")
        box2 = create_draft_box(steward2, name="Second Box", capacity_books=8,
                                latitude=45.53, longitude=-122.69)

        chartered1 = validate_success(
            api.transition_box_status(box1["id"], "CHARTERED", ADMIN), 200
        )
        chartered2 = validate_success(
            api.transition_box_status(box2["id"], "CHARTERED", ADMIN), 200
        )
        assert chartered1["charter_number"] == "CH-000001"
        assert chartered2["charter_number"] == "CH-000002"


class TestActivationGates:
    def test_box_activation_rejected_without_inspection(self, api):
        """PRD §3.3: "Moving a `CHARTERED` box to `ACTIVE` demands at least one
        inspection record with `result` `CONFIRMED` for the box
        (`ERR_INSPECTION_REQUIRED` without one) and an owning steward in
        `ACTIVE` standing (`ERR_STEWARD_NOT_ACTIVE` otherwise)."

        Design: Corner/state_machines/box_activation_rejected_without_inspection
        """
        pin_clock()
        steward = create_active_steward(full_name="No Inspect",
                                        email="noinsp@example.org")
        box = create_chartered_box(steward, name="Uninspected Box")

        res = api.transition_box_status(box["id"], "ACTIVE", ADMIN)
        validate_error(res, ApiErrorId.ERR_INSPECTION_REQUIRED.value,
                       expected_status=409)

        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["charter_status"] == "CHARTERED"
        assert after["listing_posture"] == "UNLISTED"

    def test_box_reactivation_requires_post_suspension_inspection(self, api):
        """PRD §3.3: "Reactivation from `SUSPENDED` is available to the box's
        owner steward or a `NetworkAdmin`, but only on fresh evidence: a
        `CONFIRMED` inspection created strictly after `suspended_at` must exist
        (`ERR_INSPECTION_REQUIRED` otherwise), and a steward actor must own the
        box (`ERR_FORBIDDEN_OWNERSHIP`)."
        PRD §3.9: "`ACTIVE` boxes whose `days_since_activity` has reached 180
        days are suspended with `suspended_at` stamped".

        Design: Corner/state_machines/box_reactivation_requires_post_suspension_inspection
        """
        pin_clock()
        steward, box = create_steward_with_active_box(
            steward_name="Stale Box Owner", box_name="Dusty Box"
        )
        # 180 days after activation the sweep suspends the stale box.
        pin_clock("2027-01-28T00:00:00Z")
        run_sweep()
        suspended = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert suspended["charter_status"] == "SUSPENDED"

        # The pre-suspension inspection predates suspended_at: not qualifying.
        res = api.transition_box_status(
            box["id"], "ACTIVE", make_steward_headers(steward["id"])
        )
        validate_error(res, ApiErrorId.ERR_INSPECTION_REQUIRED.value,
                       expected_status=409)

        # A fresh CONFIRMED inspection qualifies the reactivation — PRD §3.3
        # requires it "strictly after `suspended_at`", so the clock must move
        # past the suspension instant before the inspection is filed.
        pin_clock("2027-01-29T00:00:00Z")
        inspect_box(box["id"], "CONFIRMED")
        reactivated = validate_success(
            api.transition_box_status(
                box["id"], "ACTIVE", make_steward_headers(steward["id"])
            ),
            200,
        )
        assert reactivated["charter_status"] == "ACTIVE"
        after = validate_success(api.get_box(box["id"], ADMIN), 200)
        assert after["listing_posture"] == "LISTED"
        assert after["days_since_activity"] == 0


class TestBoxCreationRules:
    def test_box_create_rejected_out_of_range_coordinates(self, api):
        """PRD §3.3: "Creation takes the owning `steward_id` — a steward caller
        may propose only for themselves, while a `NetworkAdmin` may act on any
        steward's behalf — plus a public display `name`, WGS84 coordinates
        (`latitude` between −90 and 90, `longitude` between −180 and 180), the
        integer `capacity_books` (at least 1), and the `region_code` where the
        box will stand."
        PRD §2.8: "Required fields are present, enum members are valid, and
        numeric ranges hold — failure is `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/box_create_rejected_out_of_range_coordinates
        """
        pin_clock()
        steward = create_active_steward(full_name="Coord Tester",
                                        email="coord@example.org")
        res = api.create_box(
            create_box_payload(
                steward["id"],
                name="Bad Coord Box",
                latitude=95.0,
                longitude=-122.68,
            ),
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value,
                       expected_status=400)

    def test_box_limit_enforced_for_none_tier(self, api):
        """PRD §3.2: "Box creation enforces a capacity keyed to the steward's
        current `recognition_tier` — a steward at `NONE` or `BRONZE` may hold
        one box, `SILVER` two, `GOLD` three, and `PLATINUM` five."
        PRD §3.2: "The boundary is inclusive of the limit, so a steward
        already holding exactly their allotment is rejected with
        `ERR_BOX_LIMIT_REACHED` on the next attempt."
        PRD §3.2: "The count against that limit includes every box the steward
        owns in `DRAFT`, `CHARTERED`, `ACTIVE`, or `SUSPENDED` charter states;
        decommissioned boxes no longer count."

        Design: Corner/validations/box_limit_enforced_for_none_tier
        """
        pin_clock()
        steward = create_active_steward(full_name="Limit Tester",
                                        email="limit@example.org")
        create_draft_box(steward, name="Only Box")

        res = api.create_box(
            create_box_payload(
                steward["id"],
                name="Second Box",
                latitude=45.53,
                longitude=-122.69,
                capacity_books=5,
            ),
            make_steward_headers(steward["id"]),
        )
        validate_error(res, ApiErrorId.ERR_BOX_LIMIT_REACHED.value,
                       expected_status=422)


class TestImmediateConsistency:
    def test_reads_reflect_writes_immediately(self, api):
        """PRD §3.3: "the network mints the box's `charter_number`: the prefix
        `CH-` followed by a six-digit zero-padded sequence equal to one more
        than the count of previously chartered boxes, so the first charter ever
        issued is `CH-000001`."
        PRD §2.5: "The `version` is an integer that starts low and increments
        by one on every mutation of the resource, including cascaded mutations
        driven by events elsewhere in the network."
        PRD §3.3: "A new box starts in `DRAFT` charter status with an
        `UNLISTED` posture: it exists, but the public map does not show it."

        Design: Corner/consistency_model/reads_reflect_writes_immediately
        """
        pin_clock()
        steward = create_active_steward(full_name="Consistency Owner",
                                        email="cons@example.org")
        box = create_draft_box(steward, name="Cons Box")
        assert box["version"] == 1

        chartered = validate_success(
            api.transition_box_status(box["id"], "CHARTERED", ADMIN), 200
        )
        assert chartered["charter_number"] == "CH-000001"
        assert chartered["version"] == 2

        # Public map read (Anonymous) in the very next request.
        fetched = validate_success(api.get_box(box["id"], {}), 200)
        assert fetched["charter_status"] == "CHARTERED"
        assert fetched["charter_number"] == "CH-000001"
        assert fetched["listing_posture"] == "UNLISTED"
        assert fetched["version"] == 2
