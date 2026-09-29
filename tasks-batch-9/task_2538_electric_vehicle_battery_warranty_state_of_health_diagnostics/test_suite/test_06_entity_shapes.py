"""Creation shapes, cascades, defaults, computed mirrors and listing envelopes.

These probe the resource surface itself: what a create writes, what it ignores,
what children it mints, what a list page reports and what an unknown id returns.
"""

import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_battery_module,
    assert_battery_pack,
    assert_common_fields,
    assert_created_at_ascending,
    assert_error_envelope,
    assert_event_fields,
    assert_modules_ascending_by_position,
    assert_pagination_meta,
    assert_retention_schedule_ascending,
    assert_same_instant,
    assert_service_center,
    assert_technician,
    assert_warranty_program,
    battery_pack_payload,
    campaign_payload,
    consent_payload,
    is_iso8601_timestamp,
    is_valid_uuid,
    list_assessments,
    list_consents,
    list_packs,
    list_snapshots,
    list_technicians,
    make_technician_headers,
    read_vehicle,
    read_vehicle_version,
    release_campaign,
    setup_center,
    setup_installed_pack,
    setup_program,
    setup_technician,
    setup_vehicle,
    snapshot_payload,
    validate_error,
    validate_paginated,
    validate_success,
    vehicle_payload,
    warranty_program_payload,
)


def _meta_of(response) -> dict:
    """The envelope's meta block, which every response carries."""
    return response.json()["meta"]


class TestWarrantyProgramCreation:
    """The programme is the configuration record every later rule reads."""

    def test_the_retention_schedule_is_stored_ascending_however_it_was_submitted(
        self, api, admin_headers
    ):
        """Two tiers posted newest-first come back oldest-first.

        PRD 3.1: "The server sorts the supplied rows ascending by `through_months` at
        write time and persists them in that order, so downstream tier selection can
        rely on the stored order."

        PRD 3.1: "A new program's two mirrors both start at zero —
        `accrued_liability_cents` at zero and `reman_available_count` at zero — and
        `reman_stock_state` therefore reads `DEPLETED`."

        Design: Corner/entities/warranty_program_creation_sorts_retention_schedule_ascending
        """
        response = api.create_warranty_program(
            warranty_program_payload(
                retention_schedule=[
                    {"through_months": 96, "through_miles": 100000, "min_retention_pct": 70.00},
                    {"through_months": 48, "through_miles": 50000, "min_retention_pct": 80.00},
                ]
            ),
            admin_headers,
        )
        program = validate_success(response, expected_status=201)
        body = response.json()
        assert body["response_type"] == "object"
        meta = body["meta"]
        assert isinstance(meta["api_request_id"], str) and meta["api_request_id"]
        assert is_iso8601_timestamp(meta["api_request_timestamp"])

        assert_warranty_program(program)
        assert_retention_schedule_ascending(program)
        assert program["retention_schedule"][0]["through_months"] == 48
        assert program["retention_schedule"][0]["through_miles"] == 50000
        assert program["retention_schedule"][0]["min_retention_pct"] == pytest.approx(
            80.00, abs=0.01
        )
        assert program["retention_schedule"][1]["min_retention_pct"] == pytest.approx(
            70.00, abs=0.01
        )
        assert program["accrued_liability_cents"] == 0
        assert program["reman_available_count"] == 0
        assert program["reman_stock_state"] == "DEPLETED"
        assert program["version"] == 1
        assert is_valid_uuid(program["id"])

    def test_client_supplied_system_fields_are_ignored_rather_than_honoured(
        self, api, admin_headers
    ):
        """An id, a version, an accrual and a created_at in the body all count for nothing.

        PRD 2.4: "Each stored record carries an `id`, which is a server-minted UUID
        with no type prefix and no client-supplied component."

        PRD 2.4: "`version`, an integer that starts at 1 and increments by one on
        every mutation of that record."

        Design: Corner/entities/warranty_program_system_fields_generated_and_extra_field_input_ignored
        """
        program = validate_success(
            api.create_warranty_program(
                warranty_program_payload(
                    id="prog_client_supplied",
                    version=99,
                    accrued_liability_cents=5000000,
                    created_at="2000-01-01T00:00:00Z",
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert program["id"] != "prog_client_supplied"
        assert is_valid_uuid(program["id"])
        assert program["version"] == 1
        assert program["accrued_liability_cents"] == 0
        assert_same_instant(program["created_at"], program["updated_at"], "created_at")
        assert_same_instant(program["created_at"], "2026-08-01T00:00:00Z", "created_at")


class TestBatteryPackRoster:
    """A pack create is really a pack plus a full module roster."""

    def test_one_pack_create_mints_sixteen_positioned_healthy_modules(
        self, api, admin_headers
    ):
        """The children are only visible through the pack's own module listing.

        PRD 3.1: "registration cascade-creates the pack's children: exactly
        `module_count` **battery modules**, minted with `position_index` running 1
        through `module_count` in ascending order, each carrying `pack_id` back to its
        parent, each starting `HEALTHY` with `cell_delta_mv` at 0,
        `thermal_runaway_flag` false and `replaced_at` null."

        PRD 3.1: "Each module's `module_capacity_kwh` is its parent's
        `nominal_capacity_kwh` divided by its `module_count`, rounded half up to three
        decimals."

        Design: Corner/entities/battery_pack_creation_cascades_module_roster_with_positions
        """
        setup_program(api)
        pack = validate_success(
            api.create_battery_pack(battery_pack_payload("PK-C001"), admin_headers),
            expected_status=201,
        )
        assert_battery_pack(pack)
        assert pack["status"] == "STOCK"
        assert pack["pack_type"] == "NEW"
        assert pack["module_count"] == 16
        assert pack["nominal_capacity_kwh"] == pytest.approx(80.000, abs=0.001)
        assert pack["faulted_module_count"] == 0
        assert pack["module_replacements_to_date"] == 0
        assert pack["damaged_defective"] is False

        response = api.list_battery_modules(pack["id"], admin_headers, params={"limit": 20})
        rows, meta = validate_paginated(response)
        assert response.json()["response_type"] == "array"
        assert_pagination_meta(meta, 16, expected_has_more=False)
        assert_modules_ascending_by_position(rows)
        assert rows[0]["position_index"] == 1
        assert rows[15]["position_index"] == 16
        for row in rows:
            assert_battery_module(row)
            assert row["pack_id"] == pack["id"]
            assert row["status"] == "HEALTHY"
            assert row["cell_delta_mv"] == 0
            assert row["thermal_runaway_flag"] is False
            assert row["replaced_at"] is None
            assert row["module_capacity_kwh"] == pytest.approx(5.000, abs=0.001)

    def test_the_module_page_reports_has_more_from_the_total_not_from_fullness(
        self, api, admin_headers
    ):
        """Ten of sixteen, then the last six, then a filter that matches nothing.

        PRD 2.3: "`limit` caps the number of records returned; when omitted it
        defaults to 10, and a supplied value must be at least 1 and at most 100.
        `offset` is the number of records to skip and defaults to 0."

        PRD 2.3: "Every list response repeats `limit` and `offset` in the `meta`
        object alongside `total_count` (the number of records matching the filter
        before pagination) and `has_more` (true when records remain beyond the current
        page)."

        Design: Corner/entities/battery_module_listing_paginates_with_total_count_and_has_more
        """
        setup_program(api)
        pack = validate_success(
            api.create_battery_pack(battery_pack_payload("PK-C002"), admin_headers),
            expected_status=201,
        )

        first_page, first_meta = validate_paginated(
            api.list_battery_modules(pack["id"], admin_headers)
        )
        assert len(first_page) == 10
        assert_pagination_meta(first_meta, 16, 10, 0, True)
        assert [row["position_index"] for row in first_page] == list(range(1, 11))

        second_page, second_meta = validate_paginated(
            api.list_battery_modules(
                pack["id"], admin_headers, params={"limit": 10, "offset": 10}
            )
        )
        assert len(second_page) == 6
        assert_pagination_meta(second_meta, 16, 10, 10, False)
        assert [row["position_index"] for row in second_page] == list(range(11, 17))

        filtered, filtered_meta = validate_paginated(
            api.list_battery_modules(pack["id"], admin_headers, params={"status": "FAULTED"})
        )
        assert filtered == []
        assert_pagination_meta(filtered_meta, 0, expected_has_more=False)


class TestUnknownAndInvalidWrites:
    """A rejected read or write returns the error envelope and persists nothing."""

    def test_an_unknown_vehicle_id_is_a_404_in_the_error_envelope(self, api, admin_headers):
        """Not an empty object, not a 500.

        PRD 2.7: "The ten path-and-body existence failures are
        `ERR_PROGRAM_NOT_FOUND`, `ERR_VEHICLE_NOT_FOUND`, `ERR_PACK_NOT_FOUND`,
        `ERR_CENTER_NOT_FOUND`, `ERR_TECHNICIAN_NOT_FOUND`,
        `ERR_ASSESSMENT_NOT_FOUND`, `ERR_CLAIM_NOT_FOUND`, `ERR_EVENT_NOT_FOUND`,
        `ERR_CAMPAIGN_NOT_FOUND`, `ERR_CONSENT_NOT_FOUND`, `ERR_DISPUTE_NOT_FOUND` and
        `ERR_SHIPMENT_NOT_FOUND`, each HTTP 404."

        PRD 2.2: "The `error_id` is a unique, machine-readable string that identifies
        the specific error. The `message` provides a human-readable explanation of what
        went wrong."

        Design: Corner/entities/vehicle_read_with_unknown_id_returns_vehicle_not_found
        """
        response = api.get_vehicle(NON_EXISTENT_UUID, admin_headers)
        assert response.status_code == 404, response.text
        error = assert_error_envelope(response)
        assert error["error_id"] == ApiErrorId.ERR_VEHICLE_NOT_FOUND.value
        assert error["message"].strip()
        assert isinstance(_meta_of(response)["api_request_id"], str)

    def test_a_missing_required_variant_outranks_a_dangling_pack_reference(self, api):
        """Request shape is checked at rung four; body foreign keys only at rung seven.

        PRD 2.7: "4. Request shape on every write: required inputs present and
        non-null, enum values inside their declared sets, integers non-negative where
        constrained, decimals within their declared scale, arrays carrying the declared
        element type — `ERR_INVALID_REQUEST`."

        PRD 2.7: "7. Existence of every foreign key carried in a request body."

        Design: Corner/entities/soh_assessment_missing_required_variant_returns_invalid_request
        """
        program = setup_program(api)
        center = setup_center(api)
        technician = setup_technician(api, center["id"], full_name="Tech A")
        vehicle = setup_vehicle(api, program["id"], vin="5YJ3E1EA7KF000201")
        installed = setup_installed_pack(api, vehicle["id"], serial_number="PK-C003")
        assert installed["status"] == "IN_SERVICE"
        version = read_vehicle_version(api, vehicle["id"], technician["id"])

        payload = {
            "vehicle_id": vehicle["id"],
            "pack_id": NON_EXISTENT_UUID,
            "technician_id": technician["id"],
            "expected_vehicle_version": version,
        }
        validate_error(
            api.create_assessment(payload, make_technician_headers(technician["id"])),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            expected_status=400,
        )
        _, meta = list_assessments(api, vehicle_id=vehicle["id"])
        assert_pagination_meta(meta, 0)
        assert read_vehicle_version(api, vehicle["id"], technician["id"]) == version

    def test_a_technician_under_an_unknown_center_is_refused_on_the_path_segment(
        self, api, admin_headers
    ):
        """The body is valid; the path is not, and nothing is orphaned.

        PRD 2.7: "Requests that address a resource through a URL path are resolved
        strictly left to right, and the outermost unresolved segment wins. A request
        naming a technician under a service center that does not exist is refused with
        `ERR_CENTER_NOT_FOUND` before the technician segment is examined at all."

        Design: Corner/entities/technician_creation_under_unknown_center_returns_center_not_found
        """
        center = setup_center(api)
        validate_error(
            api.create_technician(
                NON_EXISTENT_UUID, {"full_name": "Ghost Tech"}, admin_headers
            ),
            ApiErrorId.ERR_CENTER_NOT_FOUND.value,
            expected_status=404,
        )
        _, meta = list_technicians(api, center["id"])
        assert_pagination_meta(meta, 0)

    def test_every_declared_pack_constraint_rejects_without_persisting_a_row(
        self, api, admin_headers
    ):
        """An enum outside its set, a count outside its range, and the conditional field both ways.

        PRD 3.1: "Its `module_count` must lie between 8 and 24 and defaults to 16."

        PRD 3.1: "`refurb_soh_pct` records post-refurbishment state of health: it is
        required when `pack_type` is `REMANUFACTURED` and must be omitted when
        `pack_type` is `NEW`."

        Design: Corner/entities/battery_pack_invalid_enum_and_out_of_range_module_count_rejected
        """
        setup_program(api)
        rejected = [
            battery_pack_payload("PK-C005", pack_type="REFURBISHED"),
            battery_pack_payload("PK-C006", module_count=30),
            battery_pack_payload("PK-C007", pack_type="REMANUFACTURED"),
            battery_pack_payload("PK-C008", pack_type="NEW", refurb_soh_pct=90.00),
        ]
        for payload in rejected:
            validate_error(
                api.create_battery_pack(payload, admin_headers),
                ApiErrorId.ERR_INVALID_REQUEST.value,
                expected_status=400,
            )
        _, meta = list_packs(api)
        assert_pagination_meta(meta, 0)


class TestReferenceDefaultsAndComputedMirrors:
    """What the server writes when the client says nothing at all."""

    def test_a_center_named_and_nothing_else_materialises_the_whole_default_set(
        self, api, admin_headers
    ):
        """Six declared defaults, four counters at zero and a full compliance score.

        PRD 3.1: "A center needs a `name`; `region_code` defaults to "US-WEST",
        `hv_certification_level` to `L3`, `has_pack_lift` to false,
        `insulation_tester_cal_due_at` to `2027-01-01T00:00:00Z`, `hv_bay_count` to 2
        within an allowed range of 1 to 6, and `labor_rate_cents_per_hour` to 18,333
        cents."

        PRD 3.1: "A technician is registered against a center, which sets their
        `service_center_id` from the path; they need a `full_name`, and their
        `hv_cert_level` defaults to `L3` with `cert_expires_at` defaulting to
        `2027-06-01T00:00:00Z`."

        Design: Corner/entities/service_center_defaults_applied_when_optionals_omitted
        """
        center = validate_success(
            api.create_service_center({"name": "West HV Center"}, admin_headers),
            expected_status=201,
        )
        assert_service_center(center)
        assert center["region_code"] == "US-WEST"
        assert center["hv_certification_level"] == "L3"
        assert center["has_pack_lift"] is False
        assert center["hv_bay_count"] == 2
        assert center["labor_rate_cents_per_hour"] == 18333
        assert_same_instant(
            center["insulation_tester_cal_due_at"],
            "2027-01-01T00:00:00Z",
            "insulation_tester_cal_due_at",
        )
        assert center["status"] == "ACTIVE"
        assert center["open_hazmat_holds"] == 0
        assert center["rejected_shipment_count"] == 0
        assert center["late_notification_count"] == 0
        assert center["compliance_score"] == 100

        technician = validate_success(
            api.create_technician(center["id"], {"full_name": "Tech A"}, admin_headers),
            expected_status=201,
        )
        assert_technician(technician)
        assert technician["hv_cert_level"] == "L3"
        assert_same_instant(
            technician["cert_expires_at"], "2027-06-01T00:00:00Z", "cert_expires_at"
        )
        assert technician["status"] == "ACTIVE"
        assert technician["last_hv_window_end_at"] is None
        assert technician["service_center_id"] == center["id"]

    def test_the_odometer_mirror_tracks_valid_rows_only_and_ignores_client_input(
        self, api, admin_headers, gateway_headers
    ):
        """999999 at registration counts for nothing, and an implausible row cannot raise it.

        PRD 3.1: "An `odometer_miles` figure may also be supplied at registration, but
        the field is thereafter derived: it holds the highest `odometer_miles` seen
        across that vehicle's snapshots whose validity flag reads `VALID`, and reads 0
        while the vehicle has no valid snapshot at all."

        PRD 3.2: "a `reported_capacity_kwh` at or below zero, or one exceeding the
        installed pack's `nominal_capacity_kwh` multiplied by 1.05 — the five-percent
        plausibility headroom that allows for benign measurement optimism — flags the
        row `INVALID_CAPACITY_RANGE`."

        Design: Corner/entities/vehicle_odometer_computed_from_valid_snapshots_only
        """
        program = setup_program(api)
        vehicle = validate_success(
            api.create_vehicle(
                vehicle_payload(
                    program["id"], vin="5YJ3E1EA7KF000202", odometer_miles=999999
                ),
                admin_headers,
            ),
            expected_status=201,
        )
        assert vehicle["odometer_miles"] == 0
        setup_installed_pack(api, vehicle["id"], serial_number="PK-C004")

        first = validate_success(
            api.ingest_snapshot(
                vehicle["id"],
                snapshot_payload("2026-07-20T00:00:00Z", 71000, 55.000),
                gateway_headers,
            ),
            expected_status=201,
        )
        second = validate_success(
            api.ingest_snapshot(
                vehicle["id"],
                snapshot_payload("2026-07-22T00:00:00Z", 71200, 56.000),
                gateway_headers,
            ),
            expected_status=201,
        )
        # 90.000 exceeds 80.000 * 1.05 == 84.000, so the row is stored but not valid.
        third = validate_success(
            api.ingest_snapshot(
                vehicle["id"],
                snapshot_payload("2026-07-24T00:00:00Z", 90000, 90.000),
                gateway_headers,
            ),
            expected_status=201,
        )
        assert first["validity_flag"] == "VALID"
        assert first["corrected_capacity_kwh"] == pytest.approx(55.000, abs=0.001)
        assert second["validity_flag"] == "VALID"
        assert second["corrected_capacity_kwh"] == pytest.approx(56.000, abs=0.001)
        assert third["validity_flag"] == "INVALID_CAPACITY_RANGE"
        assert third["corrected_capacity_kwh"] == pytest.approx(90.000, abs=0.001)

        assert read_vehicle(api, vehicle["id"])["odometer_miles"] == 71200
        _, meta = list_snapshots(api, vehicle["id"], validity_flag="VALID")
        assert_pagination_meta(meta, 2)

    def test_a_snapshot_is_an_event_row_with_no_version_and_no_updated_at(
        self, api, gateway_headers
    ):
        """The one entity outside the common-field quartet.

        PRD 2.4: "`TelematicsSnapshot` is the one exception. A snapshot is an immutable
        event row: it carries `id` and `created_at` only. It has no `updated_at`, no
        `version`, and no operation that modifies it after ingestion."

        PRD 3.2: "Four further readings are optional and carry defaults:
        `charge_cycles`, the cumulative count of equivalent full charge cycles,
        defaulting to 400 and never negative; `max_cell_delta_mv`, the worst-cell
        voltage spread across the pack in millivolts, defaulting to 40 and never
        negative; `coolant_temp_c`, the coolant temperature in Celsius at capture,
        defaulting to 20.0; and `dcfc_session_count`, the cumulative count of DC
        fast-charge sessions, defaulting to 0 and never negative."

        Design: Corner/entities/telematics_snapshot_is_immutable_event_without_version_field
        """
        program = setup_program(api)
        vehicle = setup_vehicle(api, program["id"], vin="5YJ3E1EA7KF000203")
        setup_installed_pack(api, vehicle["id"], serial_number="PK-C009")

        snapshot = validate_success(
            api.ingest_snapshot(
                vehicle["id"],
                snapshot_payload("2026-07-20T00:00:00Z", 71000, 56.000),
                gateway_headers,
            ),
            expected_status=201,
        )
        assert_event_fields(snapshot, "telematics_snapshot")
        assert "version" not in snapshot
        assert "updated_at" not in snapshot
        # vehicle_id is never supplied in the body; it comes from the path.
        assert snapshot["vehicle_id"] == vehicle["id"]
        assert snapshot["charge_cycles"] == 400
        assert snapshot["max_cell_delta_mv"] == 40
        assert snapshot["coolant_temp_c"] == pytest.approx(20.0, abs=0.01)
        assert snapshot["dcfc_session_count"] == 0

        rows, meta = list_snapshots(api, vehicle["id"])
        assert_pagination_meta(meta, 1)
        assert rows[0]["id"] == snapshot["id"]
        assert "version" not in rows[0]


class TestConsentJunctionOnRelease:
    """The consent row is the campaign-to-vehicle junction, minted one per eligible car."""

    def test_a_field_release_mints_one_pending_row_per_targeted_vehicle_only(
        self, api, admin_headers
    ):
        """Two of three vehicles are targeted, and the untargeted one cannot be added by hand.

        PRD 3.8: "both create one `PENDING` consent per eligible vehicle in ascending
        vehicle `created_at` order, then set both `solicited_consent_count` and
        `open_consent_count` to the number of consents created."

        PRD 3.8: "The vehicle must satisfy the campaign's targeting filter —
        `model_code` matching `applies_to_model_code`, the installed pack's `pack_type`
        matching `applies_to_pack_type` with `ANY` matching both, and under a `LIMITED`
        release the vehicle's `region_code` being a member of `pilot_region_codes` — or
        the request is refused with `ERR_VEHICLE_NOT_TARGETED`."

        Design: Corner/entities/field_release_creates_one_consent_junction_row_per_eligible_vehicle
        """
        program = setup_program(api)
        vehicle_a = setup_vehicle(api, program["id"], vin="5YJ3E1EA7KF000211")
        vehicle_b = setup_vehicle(api, program["id"], vin="5YJ3E1EA7KF000212")
        vehicle_c = setup_vehicle(
            api, program["id"], vin="5YJ3E1EA7KF000213", model_code="MX-70"
        )
        setup_installed_pack(api, vehicle_a["id"], serial_number="PK-C011")
        setup_installed_pack(api, vehicle_b["id"], serial_number="PK-C012")

        campaign = validate_success(
            api.create_campaign(
                campaign_payload(applies_to_model_code="MX-90"), admin_headers
            ),
            expected_status=201,
        )
        assert campaign["status"] == "DRAFT"

        released = release_campaign(api, campaign["id"], "FIELD")
        assert released["status"] == "FIELD_RELEASE"
        assert released["release_scope"] == "FIELD"
        assert released["solicited_consent_count"] == 2
        assert released["open_consent_count"] == 2

        rows, meta = list_consents(api, campaign_id=campaign["id"])
        assert_pagination_meta(meta, 2)
        assert_created_at_ascending(rows)
        assert rows[0]["vehicle_id"] == vehicle_a["id"]
        assert rows[1]["vehicle_id"] == vehicle_b["id"]
        for row in rows:
            assert_common_fields(row, "remediation_consent")
            assert row["consent_status"] == "PENDING"
            assert row["solicitation_round"] == 1
            assert row["superseded_consent_id"] is None
            assert_same_instant(row["expires_at"], "2026-08-15T00:00:00Z", "expires_at")

        validate_error(
            api.create_consent(
                consent_payload(campaign["id"], vehicle_c["id"], released["version"]),
                admin_headers,
            ),
            ApiErrorId.ERR_VEHICLE_NOT_TARGETED.value,
            expected_status=422,
        )
        _, after = list_consents(api, campaign_id=campaign["id"])
        assert_pagination_meta(after, 2)
        assert validate_success(
            api.get_campaign(campaign["id"], admin_headers)
        )["solicited_consent_count"] == 2
