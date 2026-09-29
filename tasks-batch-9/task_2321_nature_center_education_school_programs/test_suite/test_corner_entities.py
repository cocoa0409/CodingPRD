"""Entity-surface behaviour of the Nature Center Education API.

Every test builds its preconditions through PRD-declared endpoints against an
empty database, with the logical clock pinned before anything is created so that
`created_at`, `updated_at` and `published_at` are reproducible.
"""

import pytest

from test_helpers import (
    BC,
    CS,
    CURRICULUM_SPECIALIST_ID,
    DEFAULT_CLOCK,
    ED,
    EDUCATION_DIRECTOR_ID,
    GO,
    SM,
    ApiErrorId,
    NON_EXISTENT_UUID,
    assert_program_offering,
    assert_school_partner,
    assert_standard_alignment,
    create_booking,
    create_booking_payload,
    create_draft_offering,
    create_offering_under_review,
    create_permit_payload,
    create_program_offering_payload,
    create_published_offering,
    create_published_offering_bundle,
    create_school,
    create_school_payload,
    refresh_offering,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

# The logical clock every scenario in this module pins before its creates, so a
# stamped instant is exactly this instant rendered with three fractional digits
# (PRD §2.4).
_PINNED_CLOCK_STAMP = "2026-09-28T07:00:00.000Z"


def _list_offerings(api, headers, **filters):
    """Read one page of the catalog listing and return ``(rows, meta)``."""
    params = {"limit": 50, "offset": 0}
    params.update(filters)
    return validate_paginated(api.list_program_offerings(headers, params=params))


class TestProgramOfferingCreation:
    def test_create_stores_every_declared_field_and_the_self_reference(
        self, api, curriculum_specialist_headers
    ):
        """PRD §3.1: "A fresh offering lands in `DRAFT` with `revision_round` at 0, `standard_alignment_count` at 0, `materials_ready` false, and `authored_by_user_id` stamped with the acting `X-User-ID`."

        Design: Corner/entities/program_offering_create_persists_every_declared_field
        """
        set_clock(DEFAULT_CLOCK)
        rain_plan_target = create_draft_offering(title="Meadow Pollinators")

        payload = create_program_offering_payload(
            title="Pond Ecology Field Study",
            requires_live_animal=True,
            requires_trail_segment=True,
            public_contact_required=True,
            rain_alternate_for_offering_id=rain_plan_target["id"],
        )
        created = validate_success(
            api.create_program_offering(payload, curriculum_specialist_headers), 201
        )

        assert_program_offering(created)
        assert created["status"] == "DRAFT"
        assert created["revision_round"] == 0
        assert created["standard_alignment_count"] == 0
        assert created["materials_ready"] is False
        assert created["authored_by_user_id"] == CURRICULUM_SPECIALIST_ID
        assert created["version"] == 1
        assert created.get("published_at") is None

    def test_create_keeps_the_declared_switches_and_pricing_inputs(
        self, api, curriculum_specialist_headers
    ):
        """PRD §3.1: "An offering may also name another offering through `rain_alternate_for_offering_id`, which declares this offering to be a rain-plan alternate for the offering named — the catalog is self-referential in exactly this one way."

        Design: Corner/entities/program_offering_create_persists_every_declared_field
        """
        set_clock(DEFAULT_CLOCK)
        rain_plan_target = create_draft_offering(title="Meadow Pollinators")

        payload = create_program_offering_payload(
            title="Pond Ecology Field Study",
            duration_minutes=120,
            base_fee_cents_per_student=1233,
            requires_live_animal=True,
            requires_trail_segment=True,
            public_contact_required=True,
            rain_alternate_for_offering_id=rain_plan_target["id"],
        )
        created = validate_success(
            api.create_program_offering(payload, curriculum_specialist_headers), 201
        )

        read_back = refresh_offering(created["id"])
        assert read_back["requires_live_animal"] is True
        assert read_back["requires_trail_segment"] is True
        assert read_back["public_contact_required"] is True
        assert read_back["rain_alternate_for_offering_id"] == rain_plan_target["id"]
        assert read_back["duration_minutes"] == 120
        assert read_back["base_fee_cents_per_student"] == 1233


class TestPublishedOfferingRetrieval:
    def test_read_back_reports_the_publish_stamp_and_the_deciding_actor(self, api):
        """PRD §3.1: "On success the offering moves `UNDER_REVIEW → PUBLISHED`, `published_at` is stamped with the logical clock, and `reviewed_by_user_id` records the deciding `X-User-ID`."

        Design: Corner/entities/published_offering_read_back_carries_its_derived_catalog_counters
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering(slug_prefix="off")

        read_back = validate_success(api.get_program_offering(offering["id"], BC))
        assert read_back["status"] == "PUBLISHED"
        assert read_back["published_at"] == _PINNED_CLOCK_STAMP
        assert read_back["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID
        assert read_back["authored_by_user_id"] == CURRICULUM_SPECIALIST_ID

    def test_read_back_reports_the_alignment_counter_maintained_by_child_writes(self, api):
        """PRD §3.1: "Every accepted claim increments the offering's `standard_alignment_count` by 1."

        Design: Corner/entities/published_offering_read_back_carries_its_derived_catalog_counters
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering(slug_prefix="off")

        read_back = validate_success(api.get_program_offering(offering["id"], BC))
        assert read_back["standard_alignment_count"] == 2

    def test_read_back_reports_materials_ready_after_both_phases_are_published(self, api):
        """PRD §3.1: "Every publish recomputes the parent's `materials_ready`, which is true precisely when the offering has at least one `PRE_VISIT` material in `PUBLISHED` **and** at least one `POST_VISIT` material in `PUBLISHED`."

        Design: Corner/entities/published_offering_read_back_carries_its_derived_catalog_counters
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering(slug_prefix="off")

        read_back = validate_success(api.get_program_offering(offering["id"], BC))
        assert read_back["materials_ready"] is True


class TestCatalogListing:
    def test_status_and_grade_band_filters_exclude_the_draft_row(self, api):
        """PRD §3.1: "Catalog browsing supports filters on `grade_band`, `delivery_mode`, `status` (`DRAFT`, `UNDER_REVIEW`, `REVISION_REQUESTED`, `PUBLISHED`, `RETIRED`) and `rain_alternate_for_offering_id`, the last of which lets a coordinator enumerate the declared rain plans for a given program."

        Design: Corner/entities/offering_listing_filters_by_status_and_grade_band_then_paginates
        """
        set_clock("2026-09-28T07:00:00Z")
        first = create_published_offering(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        set_clock("2026-09-28T08:00:00Z")
        second = create_published_offering(
            title="Forest Decomposers", slug_prefix="forest"
        )
        set_clock("2026-09-28T09:00:00Z")
        draft = create_draft_offering(title="Streamside Erosion")

        rows, meta = _list_offerings(api, BC, grade_band="G3_5", status="PUBLISHED")
        assert meta["total_count"] == 2
        assert meta["has_more"] is False
        assert len(rows) == 2
        assert all(row["status"] == "PUBLISHED" for row in rows)
        assert {row["id"] for row in rows} == {first["id"], second["id"]}
        assert draft["id"] not in {row["id"] for row in rows}

        draft_rows, draft_meta = _list_offerings(api, CS, status="DRAFT")
        assert draft_meta["total_count"] == 1
        assert [row["id"] for row in draft_rows] == [draft["id"]]

    def test_listing_is_ordered_by_created_at_ascending(self, api):
        """PRD §2.3: "Unless a specific endpoint says otherwise, list results are ordered by `created_at` ascending."

        Design: Corner/entities/offering_listing_filters_by_status_and_grade_band_then_paginates
        """
        set_clock("2026-09-28T07:00:00Z")
        first = create_published_offering(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        set_clock("2026-09-28T08:00:00Z")
        second = create_published_offering(
            title="Forest Decomposers", slug_prefix="forest"
        )

        rows, _ = _list_offerings(api, BC, grade_band="G3_5", status="PUBLISHED")
        assert [row["id"] for row in rows] == [first["id"], second["id"]]

    def test_offset_skips_rows_from_the_front_of_the_filtered_result_set(self, api):
        """PRD §2.3: "`offset` skips a number of rows from the front of the result set; it defaults to 0 and may not be negative."

        Design: Corner/entities/offering_listing_filters_by_status_and_grade_band_then_paginates
        """
        set_clock("2026-09-28T07:00:00Z")
        first = create_published_offering(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        set_clock("2026-09-28T08:00:00Z")
        second = create_published_offering(
            title="Forest Decomposers", slug_prefix="forest"
        )

        page_one, meta_one = _list_offerings(
            api, BC, grade_band="G3_5", status="PUBLISHED", limit=1, offset=0
        )
        page_two, meta_two = _list_offerings(
            api, BC, grade_band="G3_5", status="PUBLISHED", limit=1, offset=1
        )

        assert meta_one["total_count"] == 2
        assert meta_one["has_more"] is True
        assert [row["id"] for row in page_one] == [first["id"]]

        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert [row["id"] for row in page_two] == [second["id"]]


class TestOfferingNotFound:
    def test_reading_an_unknown_offering_answers_the_offering_not_found_code(self, api):
        """PRD §2.9: "Every identifier in the path resolves, left to right, to the corresponding not-found code (404) as described in §2.6."

        Design: Corner/entities/program_offering_get_returns_not_found_for_an_unknown_id
        """
        set_clock(DEFAULT_CLOCK)

        response = api.get_program_offering(NON_EXISTENT_UUID, BC)
        error = validate_error(response, ApiErrorId.ERR_OFFERING_NOT_FOUND.value)
        assert error["message"].strip()


class TestRequiredFieldValidation:
    @pytest.mark.parametrize(
        "case",
        ["booking_missing_student_count", "offering_missing_grade_band", "permit_missing_valid_to"],
    )
    def test_creates_missing_a_required_field_are_rejected(self, api, case):
        """PRD §2.9: "The request body and query string conform to the operation's input shape: every required field present, every type correct, every enum value inside its declared set, every number inside its declared range, `limit` between 1 and 100 inclusive, and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/creates_missing_a_required_field_are_rejected
        """
        set_clock(DEFAULT_CLOCK)

        if case == "booking_missing_student_count":
            offering = create_published_offering()
            school = create_school()
            payload = create_booking_payload(school["id"], offering["id"])
            payload.pop("student_count")
            response = api.create_booking(payload, BC)
        elif case == "offering_missing_grade_band":
            payload = create_program_offering_payload(title="Vernal Pools")
            payload.pop("grade_band")
            response = api.create_program_offering(payload, CS)
        else:
            payload = create_permit_payload(permit_number="MB-2026-900")
            payload.pop("valid_to")
            response = api.create_permit(payload, SM)

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_a_rejected_booking_create_leaves_no_booking_row_behind(self, api):
        """PRD §2.9: "The request body and query string conform to the operation's input shape: every required field present, every type correct, every enum value inside its declared set, every number inside its declared range, `limit` between 1 and 100 inclusive, and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/creates_missing_a_required_field_are_rejected
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        payload = create_booking_payload(school["id"], offering["id"])
        payload.pop("student_count")
        validate_error(
            api.create_booking(payload, BC), ApiErrorId.ERR_INVALID_REQUEST.value
        )

        rows, meta = validate_paginated(
            api.list_bookings(BC, params={"limit": 50, "offset": 0})
        )
        assert meta["total_count"] == 0
        assert rows == []


class TestDeclaredDefaults:
    def test_the_three_offering_switches_default_to_false(self, api):
        """PRD §3.1: "Three boolean switches are optional and each defaults to false: `requires_live_animal`, `requires_trail_segment` and `public_contact_required`."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_program_offering(
                {
                    "title": "Vernal Pools",
                    "grade_band": "G6_8",
                    "delivery_mode": "VIRTUAL",
                    "duration_minutes": 60,
                    "max_group_size": 40,
                    "min_chaperone_ratio_students_per_adult": 12,
                    "base_fee_cents_per_student": 800,
                },
                CS,
            ),
            201,
        )

        assert created["requires_live_animal"] is False
        assert created["requires_trail_segment"] is False
        assert created["public_contact_required"] is False
        assert created["status"] == "DRAFT"
        assert created.get("published_at") is None

    def test_an_omitted_recovery_buffer_defaults_to_thirty_minutes(self, api):
        """PRD §3.5: "A trail segment is registered with a `name`, a `capacity_persons` ceiling between 1 and 400 inclusive on how many people may occupy it at any single instant, a `habitat_sensitivity` classification of `LOW`, `MODERATE` or `HIGH`, a `weekly_visitor_budget_persons` resource-protection ceiling between 1 and 5000 inclusive on total persons routed through the segment in an ISO program week, and an optional `recovery_buffer_minutes` trailing recovery window between 0 and 240 inclusive that defaults to 30 minutes."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_trail_segment(
                {
                    "name": "Ridge Spur",
                    "capacity_persons": 40,
                    "habitat_sensitivity": "MODERATE",
                    "weekly_visitor_budget_persons": 200,
                },
                SM,
            ),
            201,
        )

        assert created["recovery_buffer_minutes"] == 30
        assert created["status"] == "OPEN"
        assert created["visitors_this_week"] == 0

    def test_an_omitted_transport_sublimit_defaults_to_a_quarter_of_the_pool(self, api):
        """PRD §2.7: "Ratios supplied by clients keep their input precision: `title_i_pct` is a number from 0 through 1 inclusive, and `transport_sublimit_pct` is a number from 0 through 1 inclusive that defaults to `0.25` when the funder pool is opened without one."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_scholarship_fund(
                {
                    "funder_name": "Riverbend Foundation",
                    "fiscal_year": 2027,
                    "total_cents": 5000000,
                },
                GO,
            ),
            201,
        )

        assert created["transport_sublimit_pct"] == pytest.approx(0.25, abs=0.01)

    def test_a_new_pool_opens_with_empty_ledger_counters(self, api):
        """PRD §3.8: "A new pool opens at `OPEN` with `pending_cents`, `committed_cents`, `disbursed_cents` and `transport_awarded_cents` all at 0 and `available_cents` equal to `total_cents`."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_scholarship_fund(
                {
                    "funder_name": "Riverbend Foundation",
                    "fiscal_year": 2027,
                    "total_cents": 5000000,
                },
                GO,
            ),
            201,
        )

        assert created["status"] == "OPEN"
        assert created["pending_cents"] == 0
        assert created["committed_cents"] == 0
        assert created["disbursed_cents"] == 0
        assert created["transport_awarded_cents"] == 0
        assert created["available_cents"] == 5000000

    def test_a_new_educator_opens_uncredentialled_with_no_weekly_load(self, api):
        """PRD §3.3: "A new educator sits at `APPLICANT` with `animal_handling_tier` of `NONE`, an empty `curriculum_certified_grade_bands` array, and `delivery_load_minutes_this_week` at 0."

        Design: Corner/entities/omitted_optional_fields_fall_back_to_their_declared_defaults
        """
        set_clock(DEFAULT_CLOCK)

        created = validate_success(
            api.create_educator(
                {"full_name": "Rae Alder", "employment_type": "STAFF_NATURALIST"}, ED
            ),
            201,
        )

        assert created["status"] == "APPLICANT"
        assert created["animal_handling_tier"] == "NONE"
        assert created["curriculum_certified_grade_bands"] == []
        assert created["delivery_load_minutes_this_week"] == 0
        assert created.get("season_end_date") is None


class TestBookingComputedFields:
    def test_booking_create_rounds_the_chaperone_requirement_up(self, api):
        """PRD §3.6: "`required_chaperones` is the `student_count` divided by the offering's `min_chaperone_ratio_students_per_adult`, rounded **up** to the next whole adult — a class of 61 students on a program written for one adult per 15 students needs 5 chaperones, not 4."

        Design: Corner/entities/booking_create_computes_chaperone_requirement_and_provisional_fee
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering(
            min_chaperone_ratio_students_per_adult=10, base_fee_cents_per_student=1233
        )
        school = create_school()

        booking = create_booking(
            school["id"], offering["id"], student_count=23, chaperone_count=4
        )
        assert booking["required_chaperones"] == 3

    def test_booking_create_prices_the_per_student_discount_before_multiplying(self, api):
        """PRD §3.8: "Step three applies the discount **per student and rounds before multiplying**: the offering's `base_fee_cents_per_student` is multiplied by one minus the discount fraction, that per-student amount is rounded half up to a whole cent, and only then is it multiplied by the billable headcount to give the programme fee."

        Design: Corner/entities/booking_create_computes_chaperone_requirement_and_provisional_fee
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering(
            delivery_mode="ONSITE_FIELD_TRIP",
            min_chaperone_ratio_students_per_adult=10,
            base_fee_cents_per_student=1233,
        )
        school = create_school()

        booking = create_booking(
            school["id"], offering["id"], student_count=23, chaperone_count=4
        )
        assert booking["provisional_gross_fee_cents"] == 26933
        assert booking["net_due_cents"] == 26933

    def test_booking_create_opens_requested_and_unfunded(self, api):
        """PRD §3.6: "A newly created booking opens at `delivery_status` of `REQUESTED` and `funding_status` of `UNFUNDED`, with `trail_segment_id`, `lead_educator_id`, `animal_id` and `rain_diverted_to_offering_id` all unset and `resource_release_reason` null."

        Design: Corner/entities/booking_create_computes_chaperone_requirement_and_provisional_fee
        """
        set_clock(DEFAULT_CLOCK)
        offering = create_published_offering()
        school = create_school()

        booking = create_booking(
            school["id"], offering["id"], student_count=23, chaperone_count=4
        )
        assert booking["delivery_status"] == "REQUESTED"
        assert booking["funding_status"] == "UNFUNDED"
        assert booking.get("trail_segment_id") is None
        assert booking.get("lead_educator_id") is None
        assert booking.get("animal_id") is None
        assert booking.get("rain_diverted_to_offering_id") is None
        assert booking.get("resource_release_reason") is None

    def test_the_schools_equity_tier_is_derived_from_its_title_i_share(self, api):
        """PRD §3.2: "A school's `equity_tier` is `TIER_1` when `title_i_pct` is at least 0.75, `TIER_2` when it is at least 0.50 but below 0.75, `TIER_3` when it is at least 0.25 but below 0.50, and `NONE` below 0.25."

        Design: Corner/entities/booking_create_computes_chaperone_requirement_and_provisional_fee
        """
        set_clock(DEFAULT_CLOCK)
        school = create_school(title_i_pct=0.82)

        read_back = validate_success(api.get_school(school["id"], BC))
        assert read_back["equity_tier"] == "TIER_1"
        assert read_back["no_show_strikes"] == 0


class TestSystemFields:
    def test_created_at_and_updated_at_are_stamped_from_the_logical_clock(self, api):
        """PRD §2.4: "Every resource also carries a `created_at` timestamp: an ISO 8601 UTC instant rendered with three fractional digits, stamped when the row is first written."

        Design: Corner/entities/server_stamps_id_timestamps_and_version_on_every_create
        """
        set_clock(DEFAULT_CLOCK)

        school = validate_success(
            api.create_school(create_school_payload(), BC), 201
        )
        permit = validate_success(
            api.create_permit(create_permit_payload(), SM), 201
        )

        assert school["created_at"] == _PINNED_CLOCK_STAMP
        assert school["updated_at"] == _PINNED_CLOCK_STAMP
        assert permit["created_at"] == _PINNED_CLOCK_STAMP
        assert permit["updated_at"] == _PINNED_CLOCK_STAMP

    def test_version_starts_at_one_and_ids_are_distinct_across_entities(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource."

        Design: Corner/entities/server_stamps_id_timestamps_and_version_on_every_create
        """
        set_clock(DEFAULT_CLOCK)

        school = validate_success(
            api.create_school(create_school_payload(), BC), 201
        )
        permit = validate_success(
            api.create_permit(create_permit_payload(), SM), 201
        )

        assert school["version"] == 1
        assert permit["version"] == 1
        assert isinstance(school["id"], str) and school["id"]
        assert school["id"] != permit["id"]

    def test_a_new_school_partner_opens_active_with_nothing_owing(self, api):
        """PRD §3.2: "New partners open at `ACTIVE` with `no_show_strikes` at 0 and `outstanding_balance_cents` at 0."

        Design: Corner/entities/server_stamps_id_timestamps_and_version_on_every_create
        """
        set_clock(DEFAULT_CLOCK)

        school = validate_success(
            api.create_school(create_school_payload(), BC), 201
        )
        assert_school_partner(school)
        assert school["status"] == "ACTIVE"
        assert school["no_show_strikes"] == 0
        assert school["outstanding_balance_cents"] == 0

    def test_a_new_permit_opens_active(self, api):
        """PRD §3.4: "Permits open at `ACTIVE`, and their standing moves through `SUSPENDED`, `LAPSED` and `REVOKED` by way of a status-setting operation that takes the target `status` and an optional `note`."

        Design: Corner/entities/server_stamps_id_timestamps_and_version_on_every_create
        """
        set_clock(DEFAULT_CLOCK)

        permit = validate_success(
            api.create_permit(create_permit_payload(), SM), 201
        )
        assert permit["status"] == "ACTIVE"


class TestValueDomainValidation:
    @pytest.mark.parametrize(
        "case",
        ["offering_enum_outside_set", "school_ratio_above_range", "booking_count_wrong_type"],
    )
    def test_creates_with_out_of_domain_values_are_rejected(self, api, case):
        """PRD §2.9: "The request body and query string conform to the operation's input shape: every required field present, every type correct, every enum value inside its declared set, every number inside its declared range, `limit` between 1 and 100 inclusive, and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/creates_with_out_of_set_enums_or_out_of_range_numbers_are_rejected
        """
        set_clock(DEFAULT_CLOCK)

        if case == "offering_enum_outside_set":
            response = api.create_program_offering(
                create_program_offering_payload(
                    title="Vernal Pools",
                    grade_band="G13_14",
                    duration_minutes=60,
                    max_group_size=40,
                    base_fee_cents_per_student=800,
                ),
                CS,
            )
        elif case == "school_ratio_above_range":
            response = api.create_school(
                create_school_payload(
                    name="Overflow Academy",
                    district_code="LEA-78",
                    title_i_pct=1.5,
                    distance_miles=4.0,
                ),
                BC,
            )
        else:
            offering = create_published_offering()
            school = create_school()
            response = api.create_booking(
                create_booking_payload(
                    school["id"], offering["id"], student_count="thirty"
                ),
                BC,
            )

        validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_an_offering_rejected_for_a_bad_enum_is_never_persisted(self, api):
        """PRD §2.9: "The request body and query string conform to the operation's input shape: every required field present, every type correct, every enum value inside its declared set, every number inside its declared range, `limit` between 1 and 100 inclusive, and `offset` at least 0 — otherwise `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/creates_with_out_of_set_enums_or_out_of_range_numbers_are_rejected
        """
        set_clock(DEFAULT_CLOCK)

        validate_error(
            api.create_program_offering(
                create_program_offering_payload(
                    title="Vernal Pools", grade_band="G13_14"
                ),
                CS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
        )

        rows, meta = _list_offerings(api, CS, status="DRAFT")
        assert meta["total_count"] == 0
        assert rows == []


class TestAuthorshipImmutability:
    def test_authorship_and_created_at_survive_the_publish_decision(self, api):
        """PRD §2.11: "A catalog review decision may not be recorded by the `X-User-ID` stored as the offering's `authored_by_user_id`."

        Design: Corner/entities/authorship_and_created_at_survive_the_review_transition_unchanged
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_offering_under_review(slug_prefix="off")
        offering_id = bundle["offering"]["id"]

        before = validate_success(api.get_program_offering(offering_id, CS))
        validate_success(
            api.review_program_offering(offering_id, {"decision": "PUBLISH"}, ED)
        )
        after = validate_success(api.get_program_offering(offering_id, ED))

        assert after["created_at"] == before["created_at"]
        assert after["authored_by_user_id"] == before["authored_by_user_id"]
        assert after["authored_by_user_id"] == CURRICULUM_SPECIALIST_ID
        assert after["reviewed_by_user_id"] == EDUCATION_DIRECTOR_ID
        assert after["status"] == "PUBLISHED"

    def test_the_publish_decision_is_a_mutation_that_moves_the_version(self, api):
        """PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC instant with three fractional digits refreshed on every mutation, and `version`, an integer that starts at 1 on creation and increments by one on every mutation of that resource."

        Design: Corner/entities/authorship_and_created_at_survive_the_review_transition_unchanged
        """
        set_clock(DEFAULT_CLOCK)
        bundle = create_offering_under_review(slug_prefix="off")
        offering_id = bundle["offering"]["id"]

        before = validate_success(api.get_program_offering(offering_id, CS))
        validate_success(
            api.review_program_offering(offering_id, {"decision": "PUBLISH"}, ED)
        )
        after = validate_success(api.get_program_offering(offering_id, ED))

        assert after["version"] > before["version"]


class TestParentScoping:
    def test_standard_alignments_stay_scoped_to_the_offering_in_the_path(self, api):
        """PRD §3.1: "Each claim records the `offering_id` it belongs to."

        Design: Corner/entities/materials_and_alignments_stay_scoped_to_their_parent_offering
        """
        set_clock(DEFAULT_CLOCK)
        first = create_published_offering_bundle(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        second = create_published_offering_bundle(
            title="Forest Decomposers", slug_prefix="forest"
        )

        rows, meta = validate_paginated(
            api.list_standard_alignments(
                first["offering"]["id"], CS, params={"limit": 50, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert_standard_alignment(row)
            assert row["offering_id"] == first["offering"]["id"]
        assert {row["standard_code"] for row in rows} == {"3-LS4-3", "3-LS4-4"}
        assert {row["id"] for row in rows} == {
            alignment["id"] for alignment in first["alignments"]
        }
        assert not {row["id"] for row in rows} & {
            alignment["id"] for alignment in second["alignments"]
        }

    def test_curriculum_materials_stay_scoped_to_the_offering_in_the_path(self, api):
        """PRD §3.1: "A material is created against an offering with a `phase` of either `PRE_VISIT` or `POST_VISIT` and a `url_slug` naming the downloadable packet, and it records its own `offering_id`."

        Design: Corner/entities/materials_and_alignments_stay_scoped_to_their_parent_offering
        """
        set_clock(DEFAULT_CLOCK)
        first = create_published_offering_bundle(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        second = create_published_offering_bundle(
            title="Forest Decomposers", slug_prefix="forest"
        )

        rows, meta = validate_paginated(
            api.list_curriculum_materials(
                second["offering"]["id"], CS, params={"limit": 50, "offset": 0}
            )
        )
        assert meta["total_count"] == 2
        assert len(rows) == 2
        for row in rows:
            assert row["offering_id"] == second["offering"]["id"]
        assert {row["phase"] for row in rows} == {"PRE_VISIT", "POST_VISIT"}
        assert {row["id"] for row in rows} == {
            second["pre_visit_material"]["id"],
            second["post_visit_material"]["id"],
        }
        assert first["pre_visit_material"]["id"] not in {row["id"] for row in rows}

    def test_each_offering_counts_only_its_own_standard_alignments(self, api):
        """PRD §3.1: "Every accepted claim increments the offering's `standard_alignment_count` by 1."

        Design: Corner/entities/materials_and_alignments_stay_scoped_to_their_parent_offering
        """
        set_clock(DEFAULT_CLOCK)
        create_published_offering_bundle(
            title="Pond Ecology Field Study", slug_prefix="pond"
        )
        second = create_published_offering_bundle(
            title="Forest Decomposers", slug_prefix="forest"
        )

        read_back = validate_success(
            api.get_program_offering(second["offering"]["id"], CS)
        )
        assert read_back["standard_alignment_count"] == 2
