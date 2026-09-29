"""The registry surface: persisted fields, computed defaults, filters and shape errors."""
import pytest

from test_helpers import (
    ADMIN_HEADERS,
    CLOCK_EPOCH,
    INTEGRATOR_HEADERS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    advance_clock,
    api_client,
    assert_brand,
    assert_evidence_photo,
    assert_instant,
    assert_light_record,
    assert_location,
    assert_risk_tier_matches_index,
    attach_action_photo,
    audit_visit_payload,
    brand_payload,
    create_brand,
    create_franchisee,
    health_inspection_payload,
    location_payload,
    rubric_item_payload,
    setup_brand_program,
    setup_finalized_visit,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestBrandRegistration:
    def test_brand_create_returns_its_persisted_and_computed_fields(self):
        """A freshly registered brand starts at the empty end of every derived field.

        PRD: "A freshly registered brand starts with `brand_risk_index` at 0.00,
        `brand_risk_tier` at `BASELINE`, `location_count` at 0, and `default_location_count`
        at 0."

        Design: Corner/entities/brand_create_returns_persisted_and_computed_fields
        """
        advance_clock(CLOCK_EPOCH)
        brand = validate_success(
            api_client.create_brand(
                brand_payload(name="Skewer House", brand_code="SKWR",
                              unannounced_min_ratio_pct=55),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert_brand(brand)
        assert brand["name"] == "Skewer House"
        assert brand["brand_code"] == "SKWR"
        assert brand["unannounced_min_ratio_pct"] == 55
        assert brand["brand_risk_index"] == pytest.approx(0.00, abs=0.01)
        assert brand["brand_risk_tier"] == "BASELINE"
        assert brand["location_count"] == 0
        assert brand["default_location_count"] == 0
        assert brand["version"] == 1, "the first write of a record leaves it at version 1"
        assert_instant(brand["created_at"], CLOCK_EPOCH, "created_at")
        assert_risk_tier_matches_index(brand)

    def test_brand_and_rubric_item_defaults_apply_when_the_fields_are_omitted(self):
        """The two optional inputs adopt their declared defaults.

        PRD: "The registration may also set `unannounced_min_ratio_pct`, the minimum share of
        a location's rolling audit calendar that must consist of unannounced visits, expressed
        as an integer percentage from 0 through 100; when the caller omits it, the brand adopts
        40."

        Design: Corner/entities/brand_and_rubric_item_defaults_apply_when_fields_are_omitted
        """
        advance_clock(CLOCK_EPOCH)
        payload = brand_payload()
        payload.pop("unannounced_min_ratio_pct")
        brand = validate_success(
            api_client.create_brand(payload, ADMIN_HEADERS), expected_status=201,
        )
        assert brand["unannounced_min_ratio_pct"] == 40

        draft = validate_success(
            api_client.create_rubric_version(
                {
                    "brand_id": brand["id"],
                    "version_label": "RV-2026.1",
                    "effective_from": "2026-07-01T00:00:00Z",
                    "total_points": 100,
                    "expected_brand_version": brand["version"],
                },
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        item = validate_success(
            api_client.create_rubric_item(
                draft["id"], rubric_item_payload("FS-1", "FOOD_SAFETY", 30, 1), ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert item["is_critical"] is False, "is_critical defaults to false"

        rubric = validate_success(api_client.get_rubric_version(draft["id"], ADMIN_HEADERS))
        assert rubric["item_count"] == 1
        assert rubric["critical_item_count"] == 0


class TestLocationRegistry:
    def test_location_retrieval_returns_its_stored_and_computed_fields(self):
        """Locations start out unrated and in good standing.

        PRD: "Locations start out unrated and in good standing: `standing_score` is 0.00,
        `latest_grade` is null, `open_corrective_action_count` is 0, `repeat_violation_count`
        is 0, `escalation_level` is 0, `franchise_agreement_status` is `GOOD_STANDING`, and
        `cure_period_started_at` is null."

        Design: Corner/entities/location_retrieval_returns_stored_and_computed_fields
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        franchisee = create_franchisee(brand["id"])
        created = validate_success(
            api_client.create_location(
                location_payload(brand["id"], franchisee["id"],
                                 store_number="SKWR-014", region_code="MIDWEST"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        location = validate_success(api_client.get_location(created["id"], ADMIN_HEADERS))
        assert_location(location)
        assert location["brand_id"] == brand["id"]
        assert location["franchisee_id"] == franchisee["id"]
        assert location["store_number"] == "SKWR-014"
        assert location["region_code"] == "MIDWEST"
        assert location["standing_score"] == pytest.approx(0.00, abs=0.01)
        assert location["latest_grade"] is None
        assert location["open_corrective_action_count"] == 0
        assert location["repeat_violation_count"] == 0
        assert location["escalation_level"] == 0
        assert location["franchise_agreement_status"] == "GOOD_STANDING"
        assert location["cure_period_started_at"] is None

        brand_after = validate_success(api_client.get_brand(brand["id"], ADMIN_HEADERS))
        assert brand_after["location_count"] == 1, \
            "each accepted location raises its brand's location_count by one"

    def test_location_listing_filters_by_region_and_paginates(self):
        """The location collection is narrowed by region and ordered oldest first.

        PRD: "Unless a specific collection states otherwise, list results are ordered by
        `created_at` ascending."

        Design: Corner/entities/location_listing_filters_by_region_and_paginates
        """
        advance_clock(CLOCK_EPOCH)
        brand = create_brand()
        franchisee = create_franchisee(brand["id"])
        first = validate_success(
            api_client.create_location(
                location_payload(brand["id"], franchisee["id"],
                                 store_number="SKWR-014", region_code="MIDWEST"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        second = validate_success(
            api_client.create_location(
                location_payload(brand["id"], franchisee["id"],
                                 store_number="SKWR-015", region_code="MIDWEST"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        west = validate_success(
            api_client.create_location(
                location_payload(brand["id"], franchisee["id"],
                                 store_number="SKWR-016", region_code="WEST"),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )

        filters = {"brand_id": brand["id"], "region_code": "MIDWEST"}
        page_one, meta_one = validate_paginated(
            api_client.list_locations(
                ADMIN_HEADERS, params={**filters, "limit": 1, "offset": 0}
            )
        )
        assert meta_one["total_count"] == 2, "the WEST location is filtered out"
        assert meta_one["limit"] == 1
        assert meta_one["offset"] == 0
        assert meta_one["has_more"] is True
        assert [row["id"] for row in page_one] == [first["id"]]

        page_two, meta_two = validate_paginated(
            api_client.list_locations(
                ADMIN_HEADERS, params={**filters, "limit": 1, "offset": 1}
            )
        )
        assert meta_two["total_count"] == 2
        assert meta_two["has_more"] is False
        assert [row["id"] for row in page_two] == [second["id"]]
        assert west["id"] not in [row["id"] for row in page_one + page_two], \
            "the WEST location appears in neither page"

    def test_location_create_with_a_franchisee_of_another_brand_is_rejected(self):
        """The named franchisee must belong to the location's own brand.

        PRD: "Registration enforces a referential rule that is easy to get wrong: the named
        franchisee must itself belong to the same brand as the location, and a cross-brand
        pairing is rejected with `ERR_FRANCHISEE_BRAND_MISMATCH`."

        Design: Corner/entities/location_create_with_franchisee_of_another_brand_is_rejected
        """
        advance_clock(CLOCK_EPOCH)
        first_brand = create_brand(name="Skewer House", brand_code="SKWR")
        second_brand = create_brand(name="Grill Line", brand_code="GRLL")
        foreign_franchisee = create_franchisee(first_brand["id"])

        validate_error(
            api_client.create_location(
                location_payload(second_brand["id"], foreign_franchisee["id"]), ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_FRANCHISEE_BRAND_MISMATCH,
            expected_status=422,
        )

        _, meta = validate_paginated(api_client.list_locations(ADMIN_HEADERS))
        assert meta["total_count"] == 0
        brand = validate_success(api_client.get_brand(second_brand["id"], ADMIN_HEADERS))
        assert brand["location_count"] == 0


class TestNotFoundAndShapeErrors:
    def test_unknown_path_ids_return_the_matching_not_found_error(self):
        """Path identifiers resolve left to right, each with its own 404.

        PRD: "Path identifiers are resolved strictly left to right, and the first identifier
        that does not resolve determines the 404 that is returned: `ERR_BRAND_NOT_FOUND`,
        `ERR_FRANCHISEE_NOT_FOUND`, `ERR_AUDITOR_NOT_FOUND`, `ERR_LOCATION_NOT_FOUND`,
        `ERR_RUBRIC_VERSION_NOT_FOUND`, `ERR_VISIT_NOT_FOUND`, `ERR_SCORED_ITEM_NOT_FOUND`,
        `ERR_CORRECTIVE_ACTION_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND`, or
        `ERR_HEALTH_INSPECTION_NOT_FOUND`."

        Design: Corner/entities/unknown_path_ids_return_the_matching_not_found_error
        """
        reads = (
            (api_client.get_brand, ApiErrorId.ERR_BRAND_NOT_FOUND),
            (api_client.get_franchisee, ApiErrorId.ERR_FRANCHISEE_NOT_FOUND),
            (api_client.get_auditor, ApiErrorId.ERR_AUDITOR_NOT_FOUND),
            (api_client.get_location, ApiErrorId.ERR_LOCATION_NOT_FOUND),
            (api_client.get_rubric_version, ApiErrorId.ERR_RUBRIC_VERSION_NOT_FOUND),
            (api_client.get_audit_visit, ApiErrorId.ERR_VISIT_NOT_FOUND),
            (api_client.get_scored_item, ApiErrorId.ERR_SCORED_ITEM_NOT_FOUND),
            (api_client.get_corrective_action, ApiErrorId.ERR_CORRECTIVE_ACTION_NOT_FOUND),
            (api_client.get_dispute, ApiErrorId.ERR_DISPUTE_NOT_FOUND),
            (api_client.get_health_inspection, ApiErrorId.ERR_HEALTH_INSPECTION_NOT_FOUND),
        )
        for read, expected_error in reads:
            validate_error(
                read(NON_EXISTENT_UUID, ADMIN_HEADERS), expected_error, expected_status=404,
            )

    def test_rubric_item_create_missing_required_fields_returns_invalid_request(self):
        """Every omitted required field is a malformed body.

        PRD: "Request-body well-formedness — required fields present, types correct, enum
        values in range, integers inside their declared bounds, `limit` between 1 and 100 and
        `offset` at least 0 — `ERR_INVALID_REQUEST`, on every endpoint."

        Design: Corner/entities/rubric_item_create_missing_required_fields_returns_invalid_request
        """
        program = setup_brand_program(publish_rubric=False, rubric_items=[])
        rubric_id = program["rubric_version"]["id"]

        incomplete_bodies = (
            {"section": "FOOD_SAFETY", "max_points": 30, "display_order": 1},
            {"item_code": "FS-1", "max_points": 30, "display_order": 1},
            {"item_code": "FS-1", "section": "FOOD_SAFETY", "display_order": 1},
        )
        for body in incomplete_bodies:
            validate_error(
                api_client.create_rubric_item(rubric_id, body, ADMIN_HEADERS),
                ApiErrorId.ERR_INVALID_REQUEST,
                expected_status=400,
            )

        _, meta = validate_paginated(api_client.list_rubric_items(rubric_id, ADMIN_HEADERS))
        assert meta["total_count"] == 0
        rubric = validate_success(api_client.get_rubric_version(rubric_id, ADMIN_HEADERS))
        assert rubric["item_count"] == 0

    def test_rubric_item_create_under_an_unknown_rubric_version_is_not_found(self):
        """The path identifier is resolved before the body is even considered.

        PRD: "Existence of every path identifier, left to right — the matching not-found
        error, on every endpoint that has path parameters."

        Design: Corner/entities/rubric_item_create_under_unknown_rubric_version_returns_not_found
        """
        validate_error(
            api_client.create_rubric_item(
                NON_EXISTENT_UUID, rubric_item_payload("FS-1", "FOOD_SAFETY", 30, 1),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_RUBRIC_VERSION_NOT_FOUND,
            expected_status=404,
        )

    def test_out_of_enum_and_out_of_range_values_are_rejected(self):
        """Enum values outside their declared set and integers outside their bounds are 400s.

        PRD: "A **Location** is a single restaurant. Its payload names the `brand_id`, the
        `franchisee_id` of the operator, a `store_number` of 3 to 16 characters that must be
        unique within its brand, and a `region_code` drawn from `NORTHEAST`, `SOUTHEAST`,
        `MIDWEST`, and `WEST` for trend reporting."

        Design: Corner/entities/out_of_enum_and_out_of_range_values_are_rejected
        """
        advance_clock(CLOCK_EPOCH)
        program = setup_brand_program(publish_rubric=False, rubric_items=[])

        validate_error(
            api_client.create_location(
                location_payload(program["brand"]["id"], program["franchisee"]["id"],
                                 store_number="SKWR-777", region_code="SOUTHWEST"),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api_client.create_health_inspection(
                health_inspection_payload(
                    program["location"]["id"], "2026-07-20T00:00:00Z", 90, "D",
                ),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api_client.create_brand(
                brand_payload(name="Other Brand", brand_code="OTHR",
                              unannounced_min_ratio_pct=120),
                ADMIN_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )
        validate_error(
            api_client.create_health_inspection(
                health_inspection_payload(
                    program["location"]["id"], "2026-07-20T00:00:00Z", 120, "A",
                    points_possible=100,
                ),
                INTEGRATOR_HEADERS,
            ),
            ApiErrorId.ERR_INVALID_REQUEST,
            expected_status=400,
        )

        _, meta = validate_paginated(
            api_client.list_locations(
                ADMIN_HEADERS, params={"brand_id": program["brand"]["id"]}
            )
        )
        assert meta["total_count"] == 1, "only the pre-existing location survives"


class TestEvidencePhotoShape:
    def test_evidence_photo_uploaded_by_role_is_assigned_by_the_server(self):
        """The acting role, not the payload, decides who uploaded the photo.

        PRD: "The server records `uploaded_by_role` from the acting role, which is therefore
        either `Franchisee` or `Auditor`."

        Design: Corner/entities/evidence_photo_uploaded_by_role_is_assigned_by_the_server
        """
        program = setup_finalized_visit()
        action_id = program["actions"]["BS-1"]["id"]

        by_franchisee = attach_action_photo(program, action_id)
        assert_evidence_photo(by_franchisee)
        assert by_franchisee["uploaded_by_role"] == "Franchisee"

        by_auditor = validate_success(
            api_client.create_evidence_photo(
                {
                    "file_uri": "s3://evidence/brand-standards/auditor-check.jpg",
                    "captured_at": "2026-08-05T12:50:00Z",
                    "corrective_action_id": action_id,
                },
                program["auditor_headers"],
            ),
            expected_status=201,
        )
        assert_evidence_photo(by_auditor)
        assert by_auditor["uploaded_by_role"] == "Auditor"

        action = validate_success(api_client.get_corrective_action(action_id, ADMIN_HEADERS))
        assert action["evidence_photo_count"] == 2

    def test_evidence_photo_carries_no_version_and_is_written_once(self):
        """A photo is one of the four write-once record types.

        PRD: "`RubricItem`, `EvidencePhoto`, `CalibrationRecord`, and `EscalationEvent` records
        carry only `id` and `created_at`: both `updated_at` and `version` are absent from these
        four, because a rubric line item, a photo, a calibration measurement, and a ledger entry
        are each written once and never revised."

        Design: Corner/entities/evidence_photo_is_immutable_with_no_version_and_no_update_route
        """
        program = setup_finalized_visit()
        action_id = program["actions"]["BS-1"]["id"]

        photo = attach_action_photo(program, action_id)
        assert_light_record(photo)
        assert "updated_at" not in photo
        assert "version" not in photo

        items, meta = validate_paginated(
            api_client.list_rubric_items(
                program["rubric_version"]["id"], ADMIN_HEADERS,
                params={"limit": 10, "offset": 0},
            )
        )
        assert meta["total_count"] == 6
        for row in items:
            assert_light_record(row)
            assert "updated_at" not in row
            assert "version" not in row


class TestComputedNoticeHours:
    def test_announced_notice_hours_is_computed_once_at_creation(self):
        """The notice figure is pinned at creation and does not follow the clock.

        PRD: "For an `ANNOUNCED` visit the system records `announced_notice_hours`, the number
        of hours between the logical clock at creation time and `scheduled_start_at`."

        Design: Corner/entities/announced_notice_hours_is_computed_at_creation_from_the_logical_clock
        """
        program = setup_brand_program(brand_overrides={"unannounced_min_ratio_pct": 0})
        assert program["brand"]["unannounced_min_ratio_pct"] == 0

        created = validate_success(
            api_client.create_audit_visit(
                audit_visit_payload(
                    program["location"]["id"], program["auditor"]["id"],
                    program["rubric_version"]["id"],
                    "2026-08-06T09:00:00Z", "2026-08-06T13:00:00Z", visit_type="ANNOUNCED",
                ),
                ADMIN_HEADERS,
            ),
            expected_status=201,
        )
        assert created["announced_notice_hours"] == pytest.approx(129.00, abs=0.01), \
            "five days and nine hours after the epoch reading of the logical clock"

        assert created["status"] == "SCHEDULED"

        advance_clock("2026-08-04T00:00:00Z")
        reread = validate_success(api_client.get_audit_visit(created["id"], ADMIN_HEADERS))
        assert reread["announced_notice_hours"] == pytest.approx(129.00, abs=0.01), \
            "moving the clock does not recompute a figure recorded at creation"
