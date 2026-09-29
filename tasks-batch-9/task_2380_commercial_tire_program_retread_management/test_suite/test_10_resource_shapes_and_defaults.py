"""Declared shapes: echoes, defaults, server-owned fields and list windows."""

from test_helpers import (
    NON_EXISTENT_UUID,
    assert_append_only_fields,
    assert_bare_uuid,
    assert_common_fields,
    factories,
    fixtures,
    is_iso8601_timestamp,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestServiceLocationCreation:
    def test_creation_echoes_every_input_and_seeds_every_derived_field(self, api):
        """PRD §3.1: "A location that hosts retread production lines is flagged with
        `is_retread_plant`, which defaults to false. `casings_in_holding_count` starts
        at 0."
        PRD §2.4: "Every persisted resource carries a server-minted `id`. Identifiers
        are UUIDs and carry no type prefix — a casing id and an invoice id are
        indistinguishable by shape, so path resolution depends on the collection being
        addressed rather than on the identifier's spelling."

        Design: Corner/entities/service_location_creation_returns_declared_fields
        """
        payload = factories.service_location_payload(
            name="Corner Commercial",
            location_code="CRN",
            state_code="OH",
            road_service_response_minutes_committed=90,
            scrap_permit_number="OH-SCRAP-4001",
            scrap_permit_expires_on="2027-06-30",
        )

        data = validate_success(
            api.create_service_location(payload, fixtures.ADMIN), expected_status=201
        )

        assert data["name"] == "Corner Commercial"
        assert data["location_code"] == "CRN"
        assert data["state_code"] == "OH"
        assert data["road_service_response_minutes_committed"] == 90
        assert data["scrap_permit_number"] == "OH-SCRAP-4001"
        assert data["scrap_permit_expires_on"] == "2027-06-30"
        assert data["is_retread_plant"] is False, "the omitted flag defaults to false"
        assert data["casings_in_holding_count"] == 0
        assert data["version"] == 1
        assert_bare_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert_common_fields(data, "service location")


class TestRetreadLineRetrieval:
    def test_a_read_back_returns_the_stored_row_without_mutating_it(self, api):
        """PRD §3.1: "A new line is `AVAILABLE` with `booked_minutes` at 0."
        PRD §2.4: "Most resources additionally carry `updated_at`, an ISO 8601 UTC
        timestamp with three fractional digits refreshed on every mutation, and
        `version`, an integer that starts at 1 on creation and increases by exactly 1
        on every mutation of that row."

        Design: Corner/entities/retread_line_retrieval_returns_stored_row
        """
        location = fixtures.create_location(
            is_retread_plant=True, location_code="RBP2"
        )
        created = validate_success(
            api.create_retread_line(
                location["id"],
                factories.retread_line_payload(
                    line_code="LR", cure_cooldown_minutes=45
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )

        data = validate_success(api.get_retread_line(created["id"], fixtures.ADMIN))

        assert data["id"] == created["id"]
        assert data["service_location_id"] == location["id"]
        assert data["line_code"] == "LR"
        assert data["cure_cooldown_minutes"] == 45
        assert data["status"] == "AVAILABLE"
        assert data["booked_minutes"] == 0
        assert data["version"] == created["version"], "a read is not a mutation"


class TestCasingListing:
    def test_the_window_and_the_filtered_total_count_are_reported_separately(self, api):
        """PRD §2.3: "`total_count` is the number of rows matching the filters before
        the window is applied, and `has_more` is true when rows remain beyond the
        returned window."
        PRD §2.3: "Every collection read accepts `limit` and `offset` as query
        parameters."

        Design: Corner/entities/casing_listing_pagination_limit_offset_and_has_more
        """
        program = fixtures.setup_fleet_program()
        fleet_id = program["fleet"]["id"]
        fixtures.create_casing(fleet_id, casing_serial="CS-4001")
        fixtures.create_casing(fleet_id, casing_serial="CS-4002")
        fixtures.create_casing(
            fleet_id, casing_serial="CS-4003", intended_position="TRAILER"
        )

        first_page, first_meta = validate_paginated(
            api.list_casings(
                fixtures.ADMIN,
                params={"fleet_account_id": fleet_id, "limit": 2, "offset": 0},
            )
        )
        assert len(first_page) == 2
        assert first_meta["total_count"] == 3
        assert first_meta["limit"] == 2
        assert first_meta["offset"] == 0
        assert first_meta["has_more"] is True

        second_page, second_meta = validate_paginated(
            api.list_casings(
                fixtures.ADMIN,
                params={"fleet_account_id": fleet_id, "limit": 2, "offset": 2},
            )
        )
        assert len(second_page) == 1
        assert second_meta["total_count"] == 3
        assert second_meta["offset"] == 2
        assert second_meta["has_more"] is False

        filtered, filtered_meta = validate_paginated(
            api.list_casings(
                fixtures.ADMIN,
                params={"fleet_account_id": fleet_id, "intended_position": "TRAILER"},
            )
        )
        assert filtered_meta["total_count"] == 1, "the count follows the filter"
        assert [row["casing_serial"] for row in filtered] == ["CS-4003"]


class TestCasingNotFound:
    def test_an_unassigned_identifier_is_a_404_not_an_empty_success(self, api):
        """PRD §2.6: "When a path contains more than one identifier, identifiers are
        resolved strictly left to right, and the first one that fails to resolve
        determines the error."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error."

        Design: Corner/entities/get_casing_with_unknown_id_not_found
        """
        error = validate_error(
            api.get_casing(NON_EXISTENT_UUID, fixtures.ADMIN),
            "ERR_CASING_NOT_FOUND",
            expected_status=404,
        )

        assert isinstance(error["message"], str) and error["message"], (
            "the envelope carries a human-readable message alongside the code"
        )


class TestCasingRequiredFields:
    def test_omitting_the_casing_serial_is_a_malformed_request(self, api):
        """PRD §3.4: "A casing is registered by a `DealerAdmin` or a `TireTechnician`
        against a `fleet_account_id`, with a `casing_serial` that must be unique across
        every casing in the system — a repeat is rejected with
        `ERR_DUPLICATE_CASING_SERIAL` — a `brand`, a `casing_spec_code`, an
        `intended_position` of `STEER`, `DRIVE` or `TRAILER`, a `scrap_weight_lbs`
        between 1 and 500 inclusive that later drives manifest capacity and weight
        totals, and an optional `retread_count` recording retreads already on the
        carcass, which defaults to 0 and must be between 0 and 5 inclusive."
        PRD §2.11: "6. Request body and query shape: required fields present, enum
        members recognised, numbers inside their declared bounds, `labor_hours` a
        multiple of 0.25, dates and datetimes well-formed ISO 8601, `limit` between 1
        and 100 inclusive, `offset` zero or greater — otherwise `ERR_INVALID_REQUEST`."

        Design: Corner/entities/create_casing_missing_required_casing_serial_rejected
        """
        program = fixtures.setup_fleet_program()
        payload = factories.casing_payload(program["fleet"]["id"])
        payload.pop("casing_serial")

        validate_error(
            api.create_casing(payload, fixtures.ADMIN),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )

        _rows, meta = validate_paginated(
            api.list_casings(
                fixtures.ADMIN, params={"fleet_account_id": program["fleet"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "nothing was silently defaulted into existence"


class TestDeclaredDefaults:
    def test_the_three_declared_defaults_are_applied_when_omitted(self, api):
        """PRD §3.1: "Retread production lines are added to a plant with a `line_code`
        unique within that location — a repeat is rejected with
        `ERR_DUPLICATE_LINE_CODE` — and an optional `cure_cooldown_minutes` that
        defaults to 30 and must be between 0 and 240 inclusive."
        PRD §3.4: "A casing is registered by a `DealerAdmin` or a `TireTechnician`
        against a `fleet_account_id`, with a `casing_serial` that must be unique across
        every casing in the system — a repeat is rejected with
        `ERR_DUPLICATE_CASING_SERIAL` — a `brand`, a `casing_spec_code`, an
        `intended_position` of `STEER`, `DRIVE` or `TRAILER`, a `scrap_weight_lbs`
        between 1 and 500 inclusive that later drives manifest capacity and weight
        totals, and an optional `retread_count` recording retreads already on the
        carcass, which defaults to 0 and must be between 0 and 5 inclusive."
        PRD §3.1: "The policy carries `target_pressure_psi`, the cold inflation target,
        which must be greater than 0 and at most 150; `pressure_tolerance_pct`, the
        allowed absolute deviation fraction from that target before a survey raises a
        pressure finding, which must be greater than 0 and at most 0.50;
        `min_tread_depth_32nds`, the legal minimum tread depth in thirty-seconds of an
        inch, which must be at least 2 and strictly less than the pull point;
        `pull_point_32nds`, the fleet's own pull threshold in thirty-seconds, which must
        be strictly greater than the legal minimum and at most 20; `max_retread_count`,
        the maximum number of prior retreads a casing may already carry and still be
        booked for another retread at this position, which must be at least 0 and at
        most 5; `approved_brands`, a non-empty array of brand strings explicitly
        approved for the position; `new_tire_tread_depth_32nds`, the nominal as-new
        depth in thirty-seconds used as the mount-time baseline for a replacement, which
        must be strictly greater than the pull point and at most 32; and
        `casing_spec_code`, the required casing specification code, which defaults to
        the wildcard string `ANY`."

        Design: Corner/entities/retread_line_and_casing_defaults_applied_when_omitted
        """
        location = fixtures.create_location(is_retread_plant=True)
        fleet = fixtures.create_fleet(location["id"])

        line = validate_success(
            api.create_retread_line(
                location["id"], {"line_code": "LD"}, fixtures.ADMIN
            ),
            expected_status=201,
        )
        assert line["cure_cooldown_minutes"] == 30
        assert line["status"] == "AVAILABLE"
        assert line["booked_minutes"] == 0

        casing_payload = factories.casing_payload(fleet["id"])
        assert "retread_count" not in casing_payload
        casing = validate_success(
            api.create_casing(casing_payload, fixtures.ADMIN), expected_status=201
        )
        assert casing["retread_count"] == 0
        assert casing["status"] == "ON_WHEEL"

        policy_payload = factories.tire_policy_payload()
        policy_payload.pop("casing_spec_code")
        policy = validate_success(
            api.create_tire_policy(fleet["id"], policy_payload, fixtures.ADMIN),
            expected_status=201,
        )
        assert policy["casing_spec_code"] == "ANY", "the wildcard specification"

        # The defaulted cooldown is not merely stored: it lengthens the booking.
        graded = fixtures.create_inspected_casing(fleet["id"], location["id"], grade="B")
        fixtures.schedule_retread_job(graded["id"], line["id"])
        assert fixtures.read_line(line["id"])["booked_minutes"] == 270


class TestCasingSystemFields:
    def test_the_client_cannot_seed_a_casing_into_a_credited_state(self, api):
        """PRD §3.4: "A new casing starts `ON_WHEEL`, with `inspection_grade`,
        `inspected_by_user_id`, `collected_at_location_id`, `scrap_manifest_id` and
        `rejection_reason` all empty and `provisional_credit_cents` at 0."
        PRD §2.4: "Every resource also carries `created_at`, an ISO 8601 UTC timestamp
        with three fractional digits recorded at insert time."

        Design: Corner/entities/casing_system_fields_minted_by_server
        """
        program = fixtures.setup_fleet_program()

        data = validate_success(
            api.create_casing(
                factories.casing_payload(
                    program["fleet"]["id"],
                    casing_serial="CS-4006",
                    brand="Michelin",
                    casing_spec_code="R22.5",
                    intended_position="STEER",
                    scrap_weight_lbs=118,
                    retread_count=2,
                ),
                fixtures.ADMIN,
            ),
            expected_status=201,
        )

        assert data["status"] == "ON_WHEEL"
        assert data.get("inspection_grade") is None
        assert data.get("inspected_by_user_id") is None
        assert data.get("collected_at_location_id") is None
        assert data.get("scrap_manifest_id") is None
        assert data.get("rejection_reason") is None
        assert data["provisional_credit_cents"] == 0
        assert data["retread_count"] == 2, "this one really is a client input"
        assert data["version"] == 1
        assert is_iso8601_timestamp(data["created_at"])


class TestVehicleTypeEnum:
    def test_a_plausible_but_undeclared_vehicle_type_is_refused(self, api):
        """PRD §3.1: "Fleet units are registered under the fleet account by a
        `DealerAdmin` or the `FleetManager` itself, carrying a `unit_number` that must be
        unique within the fleet — a repeat is rejected with `ERR_DUPLICATE_VEHICLE_UNIT`
        — a `vehicle_type` of `TRACTOR`, `TRAILER` or `STRAIGHT_TRUCK` that later serves
        as a cost-per-mile grouping dimension, and a starting `current_odometer_miles` of
        0 or more."
        PRD §3.9: "Surviving assets are grouped by the triple of `brand`, `position`
        and the `vehicle_type` of the unit the asset is on, and the groups are emitted
        sorted by `brand` ascending, then `position` ascending, then `vehicle_type`
        ascending."

        Design: Corner/entities/create_vehicle_with_invalid_enum_vehicle_type_rejected
        """
        program = fixtures.setup_fleet_program()

        validate_error(
            api.create_vehicle(
                program["fleet"]["id"],
                factories.vehicle_payload(unit_number="T-99", vehicle_type="SEMI"),
                fixtures.ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )

        _rows, meta = validate_paginated(
            api.list_vehicles(
                fixtures.ADMIN, params={"fleet_account_id": program["fleet"]["id"]}
            )
        )
        assert meta["total_count"] == 0, "free text is never stored in an enum column"


class TestSurveyImmutability:
    def test_a_survey_is_append_only_and_carries_no_version(self, api):
        """PRD §2.4: "Two resources are deliberately append-only observations rather
        than mutable records, and they carry **only** `id` and `created_at` — both
        `updated_at` and `version` are absent from them entirely."
        PRD §2.4: "A survey records what a technician measured at one instant and is
        never edited; a ledger entry records a posting and is never edited."

        Design: Corner/entities/tire_survey_is_immutable_and_carries_no_version
        """
        program = fixtures.setup_fleet_program()
        vehicle = fixtures.create_vehicle(
            program["fleet"]["id"], current_odometer_miles=200000
        )
        casing = fixtures.create_casing(program["fleet"]["id"])
        asset = fixtures.create_mounted_asset(
            program["fleet"]["id"],
            casing["id"],
            vehicle["id"],
            mounted_at="2026-08-02T09:00:00Z",
            odometer_at_mount=200000,
        )

        first = fixtures.record_survey(
            asset["id"], "2026-08-10T09:00:00Z", 100, 20, 230000
        )
        assert_append_only_fields(first, "tire survey")
        fixtures.record_survey(asset["id"], "2026-08-20T09:00:00Z", 100, 18, 260000)

        read_back = validate_success(api.get_tire_survey(first["id"], fixtures.ADMIN))

        assert read_back["tread_depth_32nds"] == 20, "appending did not rewrite it"
        assert read_back["odometer_miles"] == 230000
        assert "version" not in read_back
        assert "updated_at" not in read_back

        rows, meta = fixtures.list_surveys_for(asset["id"])
        assert meta["total_count"] == 2, "correction is by appending, not editing"
        assert [row["tread_depth_32nds"] for row in rows] == [20, 18]
        assert fixtures.read_tire_asset(asset["id"])["current_tread_depth_32nds"] == 18


class TestNestedParentResolution:
    def test_a_nested_create_resolves_its_parent_before_reading_the_body(self, api):
        """PRD §2.6: "Creation of a resource whose natural owner is another resource is
        the one exception: tire policies, vehicles, retread lines, technicians and
        scrap manifests are created underneath their owning fleet account or service
        location."
        PRD §2.11: "3. Every identifier in the URL path resolves, checked left to
        right — otherwise the matching not-found code from §2.6."

        Design: Corner/entities/create_tire_policy_under_unknown_fleet_path_not_found
        """
        validate_error(
            api.create_tire_policy(
                NON_EXISTENT_UUID, factories.tire_policy_payload(), fixtures.ADMIN
            ),
            "ERR_FLEET_ACCOUNT_NOT_FOUND",
            expected_status=404,
        )

        _rows, meta = validate_paginated(api.list_tire_policies(fixtures.ADMIN))
        assert meta["total_count"] == 0


class TestBodyForeignKeyIntegrity:
    def test_a_dangling_body_reference_is_a_404_but_shape_is_checked_first(self, api):
        """PRD §2.6: "The same codes are used when an identifier supplied in a request
        body fails to resolve; body-supplied references that can fail this way are
        service locations, fleet accounts, vehicles, casings, tire assets, retread
        lines and technicians."
        PRD §2.11: "7. Every foreign key supplied in the request body resolves —
        otherwise the matching not-found code."

        Design: Corner/entities/casing_body_foreign_key_integrity_rejected
        """
        fixtures.create_location()

        validate_error(
            api.create_casing(
                factories.casing_payload(NON_EXISTENT_UUID, casing_serial="CS-4009"),
                fixtures.ADMIN,
            ),
            "ERR_FLEET_ACCOUNT_NOT_FOUND",
            expected_status=404,
        )

        validate_error(
            api.create_casing(
                factories.casing_payload(
                    NON_EXISTENT_UUID,
                    casing_serial="CS-4010",
                    intended_position="AXLE",
                ),
                fixtures.ADMIN,
            ),
            "ERR_INVALID_REQUEST",
            expected_status=400,
        )

        _rows, meta = validate_paginated(api.list_casings(fixtures.ADMIN))
        assert meta["total_count"] == 0, "neither rejection wrote a row"
