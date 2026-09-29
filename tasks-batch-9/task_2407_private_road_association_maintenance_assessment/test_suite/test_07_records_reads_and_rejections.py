"""The record layer: what a create echoes, what a read repeats, what the server
owns outright, and which rejections a malformed or dangling reference earns."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_parcel,
    assert_share_units,
    create_assessment_roll_payload,
    create_contractor_bid_payload,
    create_maintenance_project_payload,
    create_member_payload,
    create_parcel_payload,
    create_road_segment_payload,
    is_valid_uuid,
    make_clerk_headers,
    make_commissioner_headers,
    make_contractor_headers,
    make_secretary_headers,
    make_treasurer_headers,
    read_association,
    read_bid,
    read_project,
    set_clock,
    setup_association,
    setup_parcel,
    setup_road_segment,
    validate_error,
    validate_paginated,
    validate_success,
)

SECRETARY = make_secretary_headers("sec-1")
CLERK = make_clerk_headers("clerk-1")
TREASURER = make_treasurer_headers("bt-1")
COMMISSIONER = make_commissioner_headers("rc-1")
SECOND_COMMISSIONER = make_commissioner_headers("rc-2")
CONTRACTOR = make_contractor_headers("c-1")

MAIN_SEGMENT = {
    "length_feet": 1600,
    "width_feet": 22,
    "max_grade_pct": 8,
    "surface_type": "GRAVEL",
    "turnout_count": 1,
    "turnaround_present": True,
    "bridge_present": False,
    "culvert_count": 2,
}


class TestWhatACreateEchoesAndAReadRepeats:
    """The created row, its computed companions, and the same row read back."""

    def test_parcel_creation_computes_both_share_units_and_the_read_agrees(self, api):
        """PRD §3.2: "`frontage_share_units` is the parcel's `frontage_feet`
        multiplied by the multiplier for its `usage_class`. `trip_share_units` is the
        parcel's `trips_per_day` multiplied by twenty-five, plus its `frontage_feet`
        multiplied by two tenths."
        PRD §3.2: "A newly enrolled parcel has `status` `ACTIVE` and a null
        `parent_parcel_id`."

        Design: Corner/entities/parcel_creation_returns_computed_share_units_and_is_readable_by_id
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Ridge Hollow Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(
            association["id"], name="Ridge Hollow Main", **MAIN_SEGMENT
        )

        response = api.create_parcel(
            create_parcel_payload(
                segment["id"],
                deed_book_page="DB120-P41",
                frontage_feet=290,
                usage_class="RESIDENTIAL_YEAR_ROUND",
                trips_per_day=6,
                covenant_recorded=True,
            ),
            SECRETARY,
        )
        created = validate_success(response, 201)
        body = response.json()
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert isinstance(body["meta"]["api_request_timestamp"], str)

        assert created["road_segment_id"] == segment["id"]
        assert created["deed_book_page"] == "DB120-P41"
        assert created["frontage_feet"] == pytest.approx(290, abs=0.01)
        assert created["usage_class"] == "RESIDENTIAL_YEAR_ROUND"
        assert created["trips_per_day"] == 6
        assert created["covenant_recorded"] is True
        assert created["frontage_share_units"] == pytest.approx(290.0, abs=0.0001)
        assert created["trip_share_units"] == pytest.approx(208.0, abs=0.0001)
        assert created["status"] == "ACTIVE"
        assert created["parent_parcel_id"] is None
        assert_parcel(created)
        assert_share_units(created)

        fetched = validate_success(api.get_parcel(created["id"], CLERK))
        assert fetched["id"] == created["id"]
        assert fetched["frontage_share_units"] == pytest.approx(290.0, abs=0.0001)
        assert fetched["trip_share_units"] == pytest.approx(208.0, abs=0.0001)
        assert fetched["version"] == 1

    def test_the_parcel_listing_pages_with_a_prepagination_total_count(self, api):
        """PRD §2.3: "Every list response carries `limit`, `offset`, `total_count`,
        and `has_more` inside the `meta` object of the envelope, where `total_count`
        is the number of rows matching the filters before pagination is applied and
        `has_more` indicates whether rows remain beyond the current page."
        PRD §2.3: "`limit` caps the number of rows returned; it defaults to 10, may
        not be smaller than 1, and may not be larger than 100."

        Design: Corner/entities/parcel_listing_paginates_with_total_count_and_has_more
        """
        association = setup_association(
            name="Cedar Draw Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Cedar Draw Main", **MAIN_SEGMENT)
        first = setup_parcel(
            segment["id"], deed_book_page="DB121-P01", frontage_feet=290, trips_per_day=6
        )
        second = setup_parcel(
            segment["id"],
            deed_book_page="DB121-P02",
            frontage_feet=240,
            usage_class="SEASONAL",
            trips_per_day=2,
        )
        third = setup_parcel(
            segment["id"],
            deed_book_page="DB121-P03",
            frontage_feet=200,
            usage_class="AGRICULTURAL",
            trips_per_day=1,
        )

        page_one, meta_one = validate_paginated(
            api.list_parcels(
                CLERK, params={"road_segment_id": segment["id"], "limit": 2, "offset": 0}
            )
        )
        assert len(page_one) == 2
        assert meta_one["total_count"] == 3
        assert meta_one["has_more"] is True
        assert meta_one["limit"] == 2
        assert meta_one["offset"] == 0

        page_two, meta_two = validate_paginated(
            api.list_parcels(
                CLERK, params={"road_segment_id": segment["id"], "limit": 2, "offset": 2}
            )
        )
        assert len(page_two) == 1
        assert meta_two["total_count"] == 3
        assert meta_two["has_more"] is False
        assert meta_two["offset"] == 2

        seen = [row["id"] for row in page_one] + [row["id"] for row in page_two]
        assert sorted(seen) == sorted([first["id"], second["id"], third["id"]])
        assert len(set(seen)) == 3, "no row may repeat across pages"

        validate_error(
            api.list_parcels(CLERK, params={"road_segment_id": segment["id"], "limit": 101}),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

    def test_association_defaults_are_persisted_not_merely_rendered(self, api):
        """PRD §3.1: "`default_voting_basis` is either `PER_PARCEL` or
        `ASSESSED_SHARE` and defaults to `PER_PARCEL`; it is inherited by any new
        proposal that does not name a basis of its own. `delinquency_interest_basis`
        is either `STATUTORY` or `ASSOCIATION_POLICY` and defaults to `STATUTORY`"
        PRD §3.1: "`quorum_bps` is the participation quorum in basis points, must lie
        between 1 and 10000, and defaults to 5000 — a bare majority of eligible
        weight. The freshly created association starts with an empty reserve, as
        described in §2.6."

        Design: Corner/entities/association_create_omitting_optional_inputs_applies_declared_defaults
        """
        set_clock("2026-08-01T00:00:00Z")

        created = validate_success(
            api.create_association(
                {"name": "Quarry Lane Road Association", "reserve_target_cents": 1_000_000},
                SECRETARY,
            ),
            201,
        )
        assert created["default_voting_basis"] == "PER_PARCEL"
        assert created["delinquency_interest_basis"] == "STATUTORY"
        assert created["quorum_bps"] == 5000
        assert created["reserve_balance_cents"] == 0
        assert created["reserve_funding_ratio"] == pytest.approx(0, abs=0.0001)
        assert created["reserve_posture"] == "UNDERFUNDED"
        assert created["version"] == 1

        fetched = validate_success(api.get_association(created["id"], TREASURER))
        assert fetched["default_voting_basis"] == "PER_PARCEL"
        assert fetched["delinquency_interest_basis"] == "STATUTORY"
        assert fetched["quorum_bps"] == 5000
        assert fetched["reserve_balance_cents"] == 0
        assert fetched["reserve_funding_ratio"] == pytest.approx(0, abs=0.0001)
        assert fetched["reserve_posture"] == "UNDERFUNDED"


class TestFieldsTheServerOwnsOutright:
    """Derived and system-managed fields ignore whatever the client sends."""

    def test_supplied_standing_and_encumbrance_values_are_ignored(self, api):
        """PRD §3.3: "A new member starts with `standing_status`
        `PENDING_DEED_VERIFICATION`, `access_status` `UNRESTRICTED`, a null
        `deed_verified_at`, an `encumbered_principal_cents` of zero, and a
        `restricted_days_used` of zero."

        Design: Corner/entities/member_create_computed_fields_input_ignored
        """
        association = setup_association(
            name="Hollis Spur Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Hollis Spur", **MAIN_SEGMENT)
        parcel = setup_parcel(
            segment["id"], deed_book_page="DB123-P11", frontage_feet=290, trips_per_day=6
        )

        created = validate_success(
            api.create_member(
                create_member_payload(
                    parcel["id"],
                    owner_name="R. Mireles",
                    deed_book_page="DB123-P11",
                    deed_recorded_date="2019-04-11",
                    standing_status="GOOD_STANDING",
                    encumbered_principal_cents=999_999,
                    restricted_days_used=40,
                ),
                SECRETARY,
            ),
            201,
        )

        assert created["standing_status"] == "PENDING_DEED_VERIFICATION"
        assert created["access_status"] == "UNRESTRICTED"
        assert created["encumbered_principal_cents"] == 0
        assert created["restricted_days_used"] == 0
        assert created["deed_verified_at"] is None

    def test_identity_and_lineage_fields_are_minted_by_the_server(self, api):
        """PRD §2.4: "`id` (string): a server-minted UUID with no type prefix."
        PRD §2.4: "`version` (integer): an integer that starts at 1 and increments by
        one on every mutation of the row."
        PRD §3.2: "A newly enrolled parcel has `status` `ACTIVE` and a null
        `parent_parcel_id`."

        Design: Corner/entities/parcel_create_system_fields_are_server_generated_extra_field_ignored
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Fox Run Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Fox Run Main", **MAIN_SEGMENT)
        existing = setup_parcel(
            segment["id"], deed_book_page="DB124-P01", frontage_feet=200, trips_per_day=2
        )

        created = validate_success(
            api.create_parcel(
                create_parcel_payload(
                    segment["id"],
                    deed_book_page="DB124-P02",
                    frontage_feet=240,
                    usage_class="SEASONAL",
                    trips_per_day=2,
                    parent_parcel_id=existing["id"],
                    status="SUBDIVIDED",
                    version=9,
                ),
                SECRETARY,
            ),
            201,
        )

        assert is_valid_uuid(created["id"])
        assert created["id"] != existing["id"]
        assert created["parent_parcel_id"] is None
        assert created["status"] == "ACTIVE"
        assert created["version"] == 1
        assert created["created_at"] == created["updated_at"]
        assert created["created_at"].startswith("2026-08-01T00:00:00")


class TestShapeAndReferenceRejections:
    """A 400 for a malformed body, a 404 for a reference that resolves to nothing."""

    def test_a_missing_required_field_persists_nothing(self, api):
        """PRD §2.10: "Request body and query shape: required fields are present,
        enum members are recognised, numeric fields are non-negative, integer fields
        are integral, dates are ISO 8601, `limit` sits between 1 and 100 inclusive,
        `offset` is at least 0, and a subdivision `children` array carries at least
        two entries — otherwise `ERR_INVALID_REQUEST` (400)."
        PRD §3.3: "The `AssociationSecretary` adds a roll entry by supplying the
        `parcel_id`, the `owner_name` of record, the `deed_book_page` the owner
        asserts, and the `deed_recorded_date` as an ISO 8601 calendar date."

        Design: Corner/entities/member_create_missing_required_deed_recorded_date_returns_invalid_request
        """
        association = setup_association(
            name="Bell Hollow Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Bell Hollow Main", **MAIN_SEGMENT)
        parcel = setup_parcel(
            segment["id"], deed_book_page="DB122-P07", frontage_feet=290, trips_per_day=6
        )

        validate_error(
            api.create_member(
                {
                    "parcel_id": parcel["id"],
                    "owner_name": "A. Whitcomb",
                    "deed_book_page": "DB122-P07",
                },
                SECRETARY,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        members, meta = validate_paginated(
            api.list_members(SECRETARY, params={"parcel_id": parcel["id"]})
        )
        assert meta["total_count"] == 0
        assert members == []

    def test_unknown_enum_members_and_out_of_range_numbers_are_all_shape_errors(self, api):
        """PRD §2.7: "The segment's `culvert_count` and `surface_type` — one of
        `GRAVEL`, `CHIP_SEAL`, or `PAVED` — are recorded for reserve planning and
        work scoping but do not enter the compliance test."
        PRD §3.2: "the recorded `deed_book_page` that carries the road-maintenance
        covenant, the deeded `frontage_feet` (strictly greater than zero), the
        `usage_class`, the average daily `trips_per_day` attributed to the parcel (not
        negative), and the `covenant_recorded` flag."
        PRD §3.4: "The `AssessmentClerk` opens a roll for a fiscal year by supplying
        the `association_id`, the `fiscal_year` label (between 2020 and 2100), the
        inclusive `fy_start_date` and inclusive `fy_end_date`"

        Design: Corner/entities/road_segment_and_roll_create_with_invalid_enum_and_range_values_rejected
        """
        association = setup_association(
            name="Miller Ridge Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(
            association["id"], name="Miller Ridge Main", **MAIN_SEGMENT
        )

        validate_error(
            api.create_road_segment(
                create_road_segment_payload(
                    association["id"],
                    name="Miller Ridge Spur",
                    length_feet=900,
                    surface_type="ASPHALT",
                    culvert_count=1,
                ),
                COMMISSIONER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_parcel(
                create_parcel_payload(
                    segment["id"], deed_book_page="DB125-P01", frontage_feet=0, trips_per_day=2
                ),
                SECRETARY,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )
        validate_error(
            api.create_assessment_roll(
                create_assessment_roll_payload(
                    association["id"],
                    fiscal_year=2019,
                    fy_start_date="2019-01-01",
                    fy_end_date="2019-12-31",
                ),
                CLERK,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            400,
        )

        segments, meta = validate_paginated(
            api.list_road_segments(COMMISSIONER, params={"association_id": association["id"]})
        )
        assert meta["total_count"] == 1
        assert [row["id"] for row in segments] == [segment["id"]]

    def test_a_body_foreign_key_that_resolves_to_nothing_is_a_not_found(self, api):
        """PRD §2.10: "Foreign keys supplied in the body resolve — `association_id`,
        `road_segment_id`, `parcel_id`, `member_id`, `proposal_id`, and `bid_id` —
        otherwise `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_PROPOSAL_NOT_FOUND`, or
        `ERR_BID_NOT_FOUND` respectively."

        Design: Corner/entities/parcel_create_with_an_unknown_road_segment_returns_not_found
        """
        association = setup_association(
            name="Pine Bench Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Pine Bench Main", **MAIN_SEGMENT)

        validate_error(
            api.create_parcel(
                create_parcel_payload(
                    NON_EXISTENT_UUID,
                    deed_book_page="DB126-P01",
                    frontage_feet=240,
                    trips_per_day=3,
                ),
                SECRETARY,
            ),
            ApiErrorId.ERR_ROAD_SEGMENT_NOT_FOUND.value,
            404,
        )

        _parcels, meta = validate_paginated(
            api.list_parcels(SECRETARY, params={"road_segment_id": segment["id"]})
        )
        assert meta["total_count"] == 0, "nothing was attached to the real segment either"

    def test_reading_an_unknown_charge_id_is_a_not_found_not_an_empty_body(self, api):
        """PRD §2.10: "Path-templated identifiers resolve, left to right — otherwise
        the matching 404: `ERR_ASSOCIATION_NOT_FOUND`, `ERR_ROAD_SEGMENT_NOT_FOUND`,
        `ERR_PARCEL_NOT_FOUND`, `ERR_MEMBER_NOT_FOUND`, `ERR_ROLL_NOT_FOUND`,
        `ERR_CHARGE_NOT_FOUND`"
        PRD §2.2: "The `message` provides a human-readable explanation of what went
        wrong."

        Design: Corner/entities/assessment_charge_get_with_an_unknown_id_returns_charge_not_found
        """
        set_clock("2026-08-01T00:00:00Z")

        response = api.get_assessment_charge(NON_EXISTENT_UUID, CLERK)
        error = validate_error(response, ApiErrorId.ERR_CHARGE_NOT_FOUND.value, 404)

        assert response.json()["response_type"] == "error"
        assert error["message"].strip() != ""
        _charges, meta = validate_paginated(api.list_assessment_charges(CLERK))
        assert meta["total_count"] == 0, "the failed read created nothing"

    def test_awarding_a_sibling_projects_bid_is_a_pairwise_mismatch(self, api):
        """PRD §2.10: "The awarded bid's `project_id` equals the project identifier
        in the path — otherwise `ERR_BID_PROJECT_MISMATCH` (409)."

        Design: Corner/entities/award_with_a_bid_from_another_project_returns_bid_project_mismatch
        """
        set_clock("2026-08-01T00:00:00Z")
        association = setup_association(
            name="Tanner Gap Road Association", reserve_target_cents=1_000_000
        )
        segment = setup_road_segment(association["id"], name="Tanner Gap Main", **MAIN_SEGMENT)
        project_a = validate_success(
            api.create_maintenance_project(
                create_maintenance_project_payload(
                    segment["id"],
                    category="GRADING",
                    window_start_date="2026-08-05",
                    window_end_date="2026-08-08",
                ),
                COMMISSIONER,
            ),
            201,
        )
        project_b = validate_success(
            api.create_maintenance_project(
                create_maintenance_project_payload(
                    segment["id"],
                    category="GRADING",
                    window_start_date="2026-08-20",
                    window_end_date="2026-08-23",
                ),
                COMMISSIONER,
            ),
            201,
        )
        bid_a = validate_success(
            api.create_contractor_bid(
                project_a["id"],
                create_contractor_bid_payload(
                    project_a["version"],
                    contractor_name="Basin Grading LLC",
                    amount_cents=400_000,
                ),
                CONTRACTOR,
            ),
            201,
        )
        bid_b = validate_success(
            api.create_contractor_bid(
                project_b["id"],
                create_contractor_bid_payload(
                    project_b["version"],
                    contractor_name="Basin Grading LLC",
                    amount_cents=350_000,
                ),
                CONTRACTOR,
            ),
            201,
        )

        validate_error(
            api.award_project(project_a["id"], {"bid_id": bid_b["id"]}, SECOND_COMMISSIONER),
            ApiErrorId.ERR_BID_PROJECT_MISMATCH.value,
            409,
        )

        still_open = read_project(project_a["id"])
        assert still_open["status"] == "BID_SOLICITATION"
        assert still_open["awarded_bid_id"] is None
        assert still_open["awarded_amount_cents"] == 0
        assert still_open["reserve_draw_cents"] == 0
        assert read_bid(bid_a["id"])["status"] == "SUBMITTED"
        assert read_bid(bid_b["id"])["status"] == "SUBMITTED"
        association_after = read_association(association["id"])
        assert association_after["reserve_balance_cents"] == 0
        assert association_after["reserve_posture"] == "UNDERFUNDED"
