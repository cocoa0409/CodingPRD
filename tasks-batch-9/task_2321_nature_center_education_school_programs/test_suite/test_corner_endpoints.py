"""Endpoint-surface behaviour of the Nature Center Education API.

Round trips through the single-resource reads, the read-only funder projection,
the link-column filters on the collection reads, the manifest return branches,
the logical clock, and the parent-scoped child collections.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    ED,
    SM,
    ApiErrorId,
    DEFAULT_CLOCK,
    apply_for_aid,
    attach_alignments,
    create_booking,
    create_cleared_educator,
    create_curriculum_material_payload,
    create_draft_offering,
    create_educator_payload,
    create_equipment_manifest_payload,
    create_fund,
    create_permit,
    create_permitted_animal,
    create_published_offering,
    create_school,
    create_school_payload,
    find_manifest,
    refresh_booking,
    refresh_offering,
    set_clock,
    setup_outreach_booking_with_manifest,
    setup_trail_booking_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

# --- Local setup chains no shared helper provides ------------------------------------

FOUR_ALIGNMENTS = (
    {"standard_code": "3-LS4-3", "dimension": "DISCIPLINARY_CORE_IDEA"},
    {"standard_code": "3-LS4-4", "dimension": "SCIENCE_PRACTICE"},
    {"standard_code": "3-ESS2-1", "dimension": "CROSSCUTTING_CONCEPT"},
    {"standard_code": "3-LS2-1", "dimension": "SCIENCE_PRACTICE"},
)


def _offering_with_four_alignments_and_one_published_material(api) -> dict:
    """A DRAFT offering carrying four standard alignments, a PUBLISHED PRE_VISIT
    material and a DRAFT POST_VISIT material."""
    offering = create_draft_offering()
    attach_alignments(offering["id"], FOUR_ALIGNMENTS)
    pre = validate_success(
        api.create_curriculum_material(
            offering["id"],
            create_curriculum_material_payload(phase="PRE_VISIT", url_slug="pond-pre"),
            CS,
        ),
        expected_status=201,
    )
    validate_success(api.publish_curriculum_material(pre["id"], CS))
    post = validate_success(
        api.create_curriculum_material(
            offering["id"],
            create_curriculum_material_payload(phase="POST_VISIT", url_slug="pond-post"),
            CS,
        ),
        expected_status=201,
    )
    return {"offering": offering, "pre_visit_material": pre, "post_visit_material": post}


class TestRootResourceRoundTrips:
    def test_school_create_reads_back_with_its_derived_tier_and_opening_standing(self, api):
        """PRD §3.2: "New partners open at `ACTIVE` with `no_show_strikes` at 0 and `outstanding_balance_cents` at 0."

        Design: Corner/endpoints/school_and_educator_creates_read_back_through_their_own_get
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_school(
                create_school_payload(contact_email="office@cedargrove.example"), BC
            ),
            expected_status=201,
        )
        read_back = validate_success(api.get_school(created["id"], ED))

        assert read_back["id"] == created["id"]
        assert read_back["name"] == "Cedar Grove Elementary"
        assert read_back["district_code"] == "LEA-77"
        assert read_back["status"] == "ACTIVE"
        assert read_back["no_show_strikes"] == 0
        assert read_back["outstanding_balance_cents"] == 0

    def test_school_at_eighty_two_percent_title_i_reads_back_as_tier_1(self, api):
        """PRD §3.2: "A school's `equity_tier` is `TIER_1` when `title_i_pct` is at least 0.75, `TIER_2` when it is at least 0.50 but below 0.75, `TIER_3` when it is at least 0.25 but below 0.50, and `NONE` below 0.25."

        Design: Corner/endpoints/school_and_educator_creates_read_back_through_their_own_get
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_school(create_school_payload(title_i_pct=0.82), BC),
            expected_status=201,
        )
        read_back = validate_success(api.get_school(created["id"], ED))

        assert read_back["equity_tier"] == "TIER_1"

    def test_educator_create_reads_back_at_the_front_of_the_hiring_pipeline(self, api):
        """PRD §3.3: "A new educator sits at `APPLICANT` with `animal_handling_tier` of `NONE`, an empty `curriculum_certified_grade_bands` array, and `delivery_load_minutes_this_week` at 0."

        Design: Corner/endpoints/school_and_educator_creates_read_back_through_their_own_get
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_educator(create_educator_payload(), ED), expected_status=201
        )
        read_back = validate_success(api.get_educator(created["id"], BC))

        assert read_back["id"] == created["id"]
        assert read_back["full_name"] == "Rae Alder"
        assert read_back["employment_type"] == "STAFF_NATURALIST"
        assert read_back["status"] == "APPLICANT"
        assert read_back["animal_handling_tier"] == "NONE"
        assert read_back["curriculum_certified_grade_bands"] == []
        assert read_back["delivery_load_minutes_this_week"] == 0


class TestFreshFundOutcomeReport:
    def test_rollup_echoes_the_untouched_ledger_of_a_fund_with_no_applications(self, api):
        """PRD §3.8: "A new pool opens at `OPEN` with `pending_cents`, `committed_cents`, `disbursed_cents` and `transport_awarded_cents` all at 0 and `available_cents` equal to `total_cents`."

        Design: Corner/endpoints/a_fresh_fund_outcome_report_answers_every_key_at_zero
        """
        set_clock(DEFAULT_CLOCK)
        fund = create_fund()

        report = validate_success(api.get_fund_outcome_report(fund["id"], ED))

        assert report["fund_id"] == fund["id"]
        assert report["total_cents"] == 5000000
        assert report["committed_cents"] == 0
        assert report["disbursed_cents"] == 0
        assert report["available_cents"] == 5000000

    def test_rollup_counts_no_awarded_applications_and_no_students_served(self, api):
        """PRD §3.9: "`awarded_application_count` is the number of applications on this pool whose status is `APPROVED`, `PARTIALLY_APPROVED` or `DISBURSED`."

        Design: Corner/endpoints/a_fresh_fund_outcome_report_answers_every_key_at_zero
        """
        set_clock(DEFAULT_CLOCK)
        fund = create_fund()

        report = validate_success(api.get_fund_outcome_report(fund["id"], ED))

        assert report["awarded_application_count"] == 0
        assert report["students_served_count"] == 0

    def test_weighted_learning_gain_index_reports_zero_on_an_empty_denominator(self, api):
        """PRD §3.9: "`weighted_learning_gain_index` is each qualifying report's `learning_gain_index` multiplied by its booking's `actual_student_count`, those products summed, divided by `students_served_count`, rounded half up to three decimal places — and reported as `0.000` when `students_served_count` is zero."

        Design: Corner/endpoints/a_fresh_fund_outcome_report_answers_every_key_at_zero
        """
        set_clock(DEFAULT_CLOCK)
        fund = create_fund()

        report = validate_success(api.get_fund_outcome_report(fund["id"], ED))

        assert report["students_served_count"] == 0
        assert float(report["weighted_learning_gain_index"]) == pytest.approx(
            0.000, abs=0.01
        )

    def test_tier_1_student_share_reports_zero_on_an_empty_denominator(self, api):
        """PRD §3.9: "`tier_1_student_share_pct` is the sum of `actual_student_count` over those qualifying bookings whose school's `equity_tier` is `TIER_1`, divided by `students_served_count`, rounded half up to three decimal places — likewise `0.000` when the denominator is zero."

        Design: Corner/endpoints/a_fresh_fund_outcome_report_answers_every_key_at_zero
        """
        set_clock(DEFAULT_CLOCK)
        fund = create_fund()

        report = validate_success(api.get_fund_outcome_report(fund["id"], ED))

        assert float(report["tier_1_student_share_pct"]) == pytest.approx(0.000, abs=0.01)


class TestCollectionFiltersFollowTheLinkColumn:
    def test_booking_list_filters_on_the_attached_trail_segment(self, api):
        """PRD §3.6: "Coordinators can find work by filtering the booking list on `school_id`, `offering_id`, `trail_segment_id`, `lead_educator_id`, `animal_id`, `rain_diverted_to_offering_id`, `delivery_status` and `funding_status`."

        Design: Corner/endpoints/collection_reads_filter_by_the_foreign_key_that_links_them
        """
        scenario = setup_trail_booking_scenario(confirm=True)
        linked = scenario["booking"]
        unlinked = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=20,
            chaperone_count=2,
        )

        rows, meta = validate_paginated(
            api.list_bookings(
                ED,
                {
                    "trail_segment_id": scenario["trail_segment"]["id"],
                    "limit": 10,
                    "offset": 0,
                },
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [linked["id"]]
        assert unlinked["id"] not in [row["id"] for row in rows]

    def test_booking_list_filters_on_the_lead_educator_and_the_delivery_state_together(
        self, api
    ):
        """PRD §3.6: "Coordinators can find work by filtering the booking list on `school_id`, `offering_id`, `trail_segment_id`, `lead_educator_id`, `animal_id`, `rain_diverted_to_offering_id`, `delivery_status` and `funding_status`."

        Design: Corner/endpoints/collection_reads_filter_by_the_foreign_key_that_links_them
        """
        scenario = setup_trail_booking_scenario(confirm=True)
        confirmed = scenario["booking"]
        create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=20,
            chaperone_count=2,
        )

        rows, meta = validate_paginated(
            api.list_bookings(
                ED,
                {
                    "lead_educator_id": scenario["educator"]["id"],
                    "delivery_status": "CONFIRMED",
                },
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [confirmed["id"]]

    def test_animal_list_filters_on_the_permit_that_authorises_the_ambassador(self, api):
        """PRD §3.4: "Ambassador lists may be filtered by `permit_id`, by care `status` and by `welfare_posture`."

        Design: Corner/endpoints/collection_reads_filter_by_the_foreign_key_that_links_them
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_permitted_animal()
        empty_permit = create_permit(
            agency="STATE_DNR", permit_number="DNR-2026-77"
        )

        rows, meta = validate_paginated(
            api.list_animals(SM, {"permit_id": bundle["permit"]["id"]})
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [bundle["animal"]["id"]]

        empty, empty_meta = validate_paginated(
            api.list_animals(SM, {"permit_id": empty_permit["id"]})
        )
        assert empty_meta["total_count"] == 0
        assert empty == []

    def test_aid_application_list_filters_on_the_fund_and_the_status(self, api):
        """PRD §3.8: "Aid application lists can be filtered by `booking_id`, by `fund_id` and by `status`."

        Design: Corner/endpoints/collection_reads_filter_by_the_foreign_key_that_links_them
        """
        scenario = setup_trail_booking_scenario(confirm=True)
        unfunded_booking = create_booking(
            scenario["school"]["id"],
            scenario["offering"]["id"],
            start_utc="2026-09-30T14:00:00Z",
            end_utc="2026-09-30T16:00:00Z",
            student_count=20,
            chaperone_count=2,
        )
        fund = create_fund()
        application = apply_for_aid(unfunded_booking["id"], fund["id"], 9000, 0)

        rows, meta = validate_paginated(
            api.list_aid_applications(
                ED, {"fund_id": fund["id"], "status": "SUBMITTED"}
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == application["id"]
        assert rows[0]["booking_id"] == unfunded_booking["id"]


class TestManifestReturnBranches:
    def test_return_naming_a_code_that_was_never_loaded_is_refused(self, api):
        """PRD §3.9: "When `shortage_kit_codes` is non-empty, every code in it must also appear in the manifest's `kit_codes` — a code that was never loaded cannot come back missing, and the mismatch is rejected with `ERR_SHORTAGE_CODE_UNKNOWN` — and the manifest moves `LOADED → SHORTAGE_REPORTED` with the reported codes persisted on `shortage_kit_codes`."

        Design: Corner/endpoints/manifest_return_branches_on_the_shortage_list_it_is_given
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=100.0, kit_codes=("KIT-A", "KIT-B", "KIT-C"), load=True
        )
        manifest = scenario["manifest"]

        validate_error(
            api.advance_equipment_manifest(
                manifest["id"],
                {"action": "RETURN", "shortage_kit_codes": ["KIT-Z"]},
                BC,
            ),
            ApiErrorId.ERR_SHORTAGE_CODE_UNKNOWN.value,
        )

        assert (
            find_manifest(scenario["booking"]["id"], manifest["id"])["status"] == "LOADED"
        )

    def test_return_naming_a_loaded_code_reaches_shortage_reported(self, api):
        """PRD §3.9: "When `shortage_kit_codes` is non-empty, every code in it must also appear in the manifest's `kit_codes` — a code that was never loaded cannot come back missing, and the mismatch is rejected with `ERR_SHORTAGE_CODE_UNKNOWN` — and the manifest moves `LOADED → SHORTAGE_REPORTED` with the reported codes persisted on `shortage_kit_codes`."

        Design: Corner/endpoints/manifest_return_branches_on_the_shortage_list_it_is_given
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=100.0, kit_codes=("KIT-A", "KIT-B", "KIT-C"), load=True
        )

        returned = validate_success(
            api.advance_equipment_manifest(
                scenario["manifest"]["id"],
                {"action": "RETURN", "shortage_kit_codes": ["KIT-B"]},
                BC,
            )
        )

        assert returned["status"] == "SHORTAGE_REPORTED"
        assert returned["shortage_kit_codes"] == ["KIT-B"]

    def test_return_without_a_shortage_list_reaches_returned_on_the_same_booking(
        self, api
    ):
        """PRD §3.9: "When `shortage_kit_codes` is omitted or empty, the manifest moves `LOADED → RETURNED`."

        Design: Corner/endpoints/manifest_return_branches_on_the_shortage_list_it_is_given
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=100.0, kit_codes=("KIT-A", "KIT-B", "KIT-C"), load=True
        )
        second = validate_success(
            api.create_equipment_manifest(
                scenario["booking"]["id"],
                create_equipment_manifest_payload(
                    kit_codes=["KIT-D"], total_weight_kg=100.0
                ),
                BC,
            ),
            expected_status=201,
        )
        validate_success(api.advance_equipment_manifest(second["id"], {"action": "LOAD"}, BC))

        validate_success(
            api.advance_equipment_manifest(
                scenario["manifest"]["id"],
                {"action": "RETURN", "shortage_kit_codes": ["KIT-B"]},
                BC,
            )
        )
        clean = validate_success(
            api.advance_equipment_manifest(second["id"], {"action": "RETURN"}, BC)
        )

        assert clean["status"] == "RETURNED"
        assert clean["shortage_kit_codes"] == []

    def test_manifest_list_filters_on_the_terminal_state_each_manifest_reached(self, api):
        """PRD §3.9: "Manifest lists can be filtered by `status`."

        Design: Corner/endpoints/manifest_return_branches_on_the_shortage_list_it_is_given
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=100.0, kit_codes=("KIT-A", "KIT-B", "KIT-C"), load=True
        )
        second = validate_success(
            api.create_equipment_manifest(
                scenario["booking"]["id"],
                create_equipment_manifest_payload(
                    kit_codes=["KIT-D"], total_weight_kg=100.0
                ),
                BC,
            ),
            expected_status=201,
        )
        validate_success(api.advance_equipment_manifest(second["id"], {"action": "LOAD"}, BC))
        validate_success(
            api.advance_equipment_manifest(
                scenario["manifest"]["id"],
                {"action": "RETURN", "shortage_kit_codes": ["KIT-B"]},
                BC,
            )
        )
        validate_success(api.advance_equipment_manifest(second["id"], {"action": "RETURN"}, BC))

        rows, meta = validate_paginated(
            api.list_equipment_manifests(
                scenario["booking"]["id"],
                ED,
                {"status": "SHORTAGE_REPORTED", "limit": 10, "offset": 0},
            )
        )

        assert meta["total_count"] == 1
        assert [row["id"] for row in rows] == [scenario["manifest"]["id"]]

    def test_two_van_manifests_leave_the_outreach_travel_fee_at_the_single_rate(self, api):
        """PRD §3.8: "When the booked offering's `delivery_mode` is `OUTREACH_AT_SCHOOL`, the travel fee is a flat base of 4,000 cents plus 175 cents for every mile of the school's one-way `distance_miles`, with the per-mile component multiplied by a vehicle factor, the whole sum rounded half up to a whole cent."

        Design: Corner/endpoints/manifest_return_branches_on_the_shortage_list_it_is_given
        """
        scenario = setup_outreach_booking_with_manifest(
            total_weight_kg=100.0, kit_codes=("KIT-A", "KIT-B", "KIT-C"), load=True
        )
        second = validate_success(
            api.create_equipment_manifest(
                scenario["booking"]["id"],
                create_equipment_manifest_payload(
                    kit_codes=["KIT-D"], total_weight_kg=100.0
                ),
                BC,
            ),
            expected_status=201,
        )
        validate_success(api.advance_equipment_manifest(second["id"], {"action": "LOAD"}, BC))

        booking = refresh_booking(scenario["booking"]["id"])

        assert booking["provisional_gross_fee_cents"] == 39488


class TestLogicalClockGovernsWhatIsStillBookable:
    def test_a_slot_before_the_advanced_clock_is_refused(self, api):
        """PRD §2.9: "A new booking's `start_utc` is strictly after the logical clock — otherwise `ERR_BOOKING_START_IN_PAST` (409)."

        Design: Corner/endpoints/moving_the_logical_clock_forward_puts_yesterday_s_slots_out_of_reach
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        set_clock("2026-10-05T09:00:00Z")

        validate_error(
            api.create_booking(
                {
                    "school_id": school["id"],
                    "offering_id": offering["id"],
                    "start_utc": "2026-09-29T14:00:00Z",
                    "end_utc": "2026-09-29T16:00:00Z",
                    "student_count": 30,
                    "chaperone_count": 3,
                },
                BC,
            ),
            ApiErrorId.ERR_BOOKING_START_IN_PAST.value,
        )

    def test_a_slot_after_the_advanced_clock_is_accepted(self, api):
        """PRD §2.5: "An `EducationDirector` may move the clock by supplying `to_iso8601`, and the response reports the new instant as `current_utc`."

        Design: Corner/endpoints/moving_the_logical_clock_forward_puts_yesterday_s_slots_out_of_reach
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        moved = validate_success(
            api.set_current_utc({"to_iso8601": "2026-10-05T09:00:00Z"}, ED)
        )
        assert "current_utc" in moved

        booking = validate_success(
            api.create_booking(
                {
                    "school_id": school["id"],
                    "offering_id": offering["id"],
                    "start_utc": "2026-10-06T14:00:00Z",
                    "end_utc": "2026-10-06T16:00:00Z",
                    "student_count": 30,
                    "chaperone_count": 3,
                },
                BC,
            ),
            expected_status=201,
        )

        assert booking["delivery_status"] == "REQUESTED"
        assert booking["start_utc"].startswith("2026-10-06T14:00:00")


class TestParentScopedChildCollections:
    def test_alignment_pages_serve_distinct_rows_across_the_offset(self, api):
        """PRD §2.3: "`offset` skips a number of rows from the front of the result set; it defaults to 0 and may not be negative."

        Design: Corner/endpoints/child_rows_are_reachable_only_through_their_parent_scoped_collections
        """
        set_clock(DEFAULT_CLOCK)
        bundle = _offering_with_four_alignments_and_one_published_material(api)
        offering_id = bundle["offering"]["id"]

        page_one, meta_one = validate_paginated(
            api.list_standard_alignments(offering_id, CS, {"limit": 2, "offset": 0})
        )
        page_two, meta_two = validate_paginated(
            api.list_standard_alignments(offering_id, CS, {"limit": 2, "offset": 2})
        )

        assert meta_one["total_count"] == 4
        assert meta_two["total_count"] == 4
        assert len(page_one) == 2
        first_ids = [row["id"] for row in page_one]
        second_ids = [row["id"] for row in page_two]
        assert first_ids[0] != first_ids[1]
        assert set(first_ids).isdisjoint(set(second_ids))

    def test_every_accepted_alignment_claim_lifts_the_parent_count(self, api):
        """PRD §3.1: "Every accepted claim increments the offering's `standard_alignment_count` by 1."

        Design: Corner/endpoints/child_rows_are_reachable_only_through_their_parent_scoped_collections
        """
        set_clock(DEFAULT_CLOCK)
        bundle = _offering_with_four_alignments_and_one_published_material(api)

        assert refresh_offering(bundle["offering"]["id"])["standard_alignment_count"] == 4

    def test_material_list_filters_on_the_status_of_the_child_row(self, api):
        """PRD §3.1: "Material lists can be filtered by `phase` and by `status`, whose full set is `DRAFT`, `PUBLISHED` and `ARCHIVED`."

        Design: Corner/endpoints/child_rows_are_reachable_only_through_their_parent_scoped_collections
        """
        set_clock(DEFAULT_CLOCK)
        bundle = _offering_with_four_alignments_and_one_published_material(api)

        rows, meta = validate_paginated(
            api.list_curriculum_materials(
                bundle["offering"]["id"], ED, {"status": "DRAFT", "limit": 10, "offset": 0}
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == bundle["post_visit_material"]["id"]
        assert rows[0]["phase"] == "POST_VISIT"

    def test_one_published_phase_is_not_enough_to_make_the_parent_materials_ready(
        self, api
    ):
        """PRD §3.1: "Every publish recomputes the parent's `materials_ready`, which is true precisely when the offering has at least one `PRE_VISIT` material in `PUBLISHED` **and** at least one `POST_VISIT` material in `PUBLISHED`."

        Design: Corner/endpoints/child_rows_are_reachable_only_through_their_parent_scoped_collections
        """
        set_clock(DEFAULT_CLOCK)
        bundle = _offering_with_four_alignments_and_one_published_material(api)

        assert refresh_offering(bundle["offering"]["id"])["materials_ready"] is False

    def test_training_record_list_filters_on_the_track(self, api):
        """PRD §3.3: "Training lists can be filtered by `track` and by `status`, whose full set is `ENROLLED`, `ASSESSED_PASS`, `ASSESSED_FAIL` and `EXPIRED`."

        Design: Corner/endpoints/child_rows_are_reachable_only_through_their_parent_scoped_collections
        """
        set_clock(DEFAULT_CLOCK)
        staffing = create_cleared_educator(handling_tier="TIER_1")

        rows, meta = validate_paginated(
            api.list_training_records(
                staffing["educator"]["id"],
                CS,
                {"track": "LIVE_ANIMAL_HANDLING", "limit": 10, "offset": 0},
            )
        )

        assert meta["total_count"] == 1
        assert rows[0]["id"] == staffing["handling_record"]["id"]
        assert rows[0]["handling_tier"] == "TIER_1"
