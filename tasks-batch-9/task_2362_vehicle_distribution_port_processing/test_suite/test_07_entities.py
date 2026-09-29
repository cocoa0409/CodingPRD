"""Record shape: what a create call materialises, what a read gives back, which
fields the server owns, and which references it refuses.
"""

from __future__ import annotations

from test_helpers import (
    CARRIER_ACTIVE,
    CENTER_DAILY_STORAGE_RATE_CENTS,
    CENTER_FUEL_SURCHARGE_PCT,
    CENTER_LABOR_RATE_CENTS_PER_HOUR,
    CENTER_NAME,
    CENTER_PORT_CODE,
    CENTER_YARD_CAPACITY_SLOTS,
    DAMAGE_NONE,
    DAMAGE_ZONE_INTERIOR,
    DEFAULT_FREE_STORAGE_DAYS,
    DEFAULT_PAGE_LIMIT,
    DEFAULT_PAGE_OFFSET,
    DEFAULT_TURNAROUND_BUFFER_MINUTES,
    ERR_INVALID_REQUEST,
    ERR_REFERENCE_NOT_FOUND,
    ERR_VEHICLE_NOT_FOUND,
    MANAGER,
    MISSING_BERTH_UUID,
    MISSING_KIT_UUID,
    MISSING_UUID,
    MODEL_LINE_EV900,
    MODEL_LINE_LX500,
    MODEL_LINE_TX300,
    PLANNER,
    POSTURE_OPEN,
    PROC_DISCHARGED,
    PROC_SURVEYED,
    SHORT_VIN,
    SURVEYOR,
    SURVEY_DRAFT,
    TECHNICIAN,
    YARD_IN_YARD,
    Vpc,
    assert_center_ledgers,
    assert_fields_absent,
    assert_iso_instant,
    assert_pagination_meta,
    assert_subset,
    assert_vehicle_dimensions,
    assert_versioned_record,
    assert_yard_state,
    factories as f,
    ids_of,
    ok,
    open_port,
    validate_error,
    validate_paginated,
    vin,
)

CLEAN_LINE = f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 0)


class TestProcessingCenterCreation:
    def test_a_new_center_echoes_its_rate_card_and_opens_an_empty_yard(self, flow: Vpc):
        """The occupancy counters and the three ledgers all start at rest.

        PRD: "A newly registered center starts with zero occupied slots, free
        slots equal to its capacity, and a posture of `OPEN`."

        Design: Corner/entities/corner_processing_center_creation_returns_defaults_and_zeroed_computed_fields
        """
        center = flow.create_center(free_storage_days=5)

        assert_versioned_record(center, expected_version=1)
        assert_subset(
            center,
            {
                "name": CENTER_NAME,
                "port_code": CENTER_PORT_CODE,
                "yard_capacity_slots": CENTER_YARD_CAPACITY_SLOTS,
                "daily_storage_rate_cents": CENTER_DAILY_STORAGE_RATE_CENTS,
                "labor_rate_cents_per_hour": CENTER_LABOR_RATE_CENTS_PER_HOUR,
                "fuel_surcharge_pct": CENTER_FUEL_SURCHARGE_PCT,
                "free_storage_days": 5,
            },
        )
        assert_yard_state(center, occupied_slots=0, free_slots=50, posture=POSTURE_OPEN)
        assert_center_ledgers(
            center,
            provisional_storage_accrued_cents=0,
            realized_storage_revenue_cents=0,
            repair_spend_cents=0,
        )


class TestVehicleRetrieval:
    def test_reading_a_unit_back_returns_exactly_what_discharge_stamped(self, flow: Vpc):
        """The read model carries the arrival state written at intake.

        PRD: "The new unit lands with `yard_presence` of `IN_YARD`, `yard_in_at`
        stamped from the logical clock as the origin of its dwell clock,
        `gate_out_at` null, `processing_status` of `DISCHARGED`, `damage_status` of
        `NONE`, `damage_opened_at` and `damage_cleared_at` null, `severity_index`
        0, `claim_mandatory` false, `stop_ship_blocked` false with a null
        `blocking_hold_order_id`, `rework_cycle_count` 0, `blocked_credit_days` 0,
        and `storage_charge_provisional_cents`, `storage_charge_final_cents` and
        `accessory_billed_cents` all 0."

        Design: Corner/entities/corner_vehicle_retrieval_by_id_returns_the_stored_row
        """
        port = open_port(flow)
        created = port.discharge("000101", model_line=MODEL_LINE_LX500)

        unit = port.get_vehicle(created["id"])

        assert_subset(
            unit,
            {
                "vin": vin("000101"),
                "model_line": MODEL_LINE_LX500,
                "gate_out_at": None,
                "damage_opened_at": None,
                "damage_cleared_at": None,
                "severity_index": 0,
                "claim_mandatory": False,
                "stop_ship_blocked": False,
                "blocking_hold_order_id": None,
                "rework_cycle_count": 0,
                "blocked_credit_days": 0,
                "storage_charge_provisional_cents": 0,
                "storage_charge_final_cents": 0,
                "accessory_billed_cents": 0,
            },
        )
        assert_vehicle_dimensions(
            unit,
            processing_status=PROC_DISCHARGED,
            damage_status=DAMAGE_NONE,
            yard_presence=YARD_IN_YARD,
        )
        assert_iso_instant(unit["yard_in_at"])
        assert unit["yard_in_at"].startswith("2026-08-02T00:00:00")
        assert_versioned_record(unit, expected_version=1)


class TestVehicleListing:
    def test_the_unit_collection_filters_then_pages_over_the_filtered_total(self, flow: Vpc):
        """total_count counts the filter matches, not the page.

        PRD: "List responses carry `limit`, `offset`, `total_count` and `has_more`
        in the envelope's `meta` object, where `total_count` counts every record
        matching the filters before pagination is applied and `has_more` indicates
        whether records remain beyond the current window."

        Design: Corner/entities/corner_vehicle_listing_paginates_and_filters_by_processing_status
        """
        port = open_port(flow)
        port.discharge("000102", model_line=MODEL_LINE_LX500)
        port.discharge("000103", model_line=MODEL_LINE_LX500)
        port.discharge("000104", model_line=MODEL_LINE_TX300)
        surveyed = port.discharge("000105", model_line=MODEL_LINE_EV900)
        port.surveyed(surveyed["id"], [CLEAN_LINE])

        first_page, first_meta = validate_paginated(
            port.api.list_vehicles(
                PLANNER, params={"processing_status": PROC_DISCHARGED, "limit": 2, "offset": 0}
            )
        )
        second_page, second_meta = validate_paginated(
            port.api.list_vehicles(
                PLANNER, params={"processing_status": PROC_DISCHARGED, "limit": 2, "offset": 2}
            )
        )
        by_state, state_meta = validate_paginated(
            port.api.list_vehicles(PLANNER, params={"processing_status": PROC_SURVEYED})
        )
        default_page, default_meta = validate_paginated(port.api.list_vehicles(PLANNER))

        assert len(first_page) == 2
        assert_pagination_meta(first_meta, limit=2, offset=0, total_count=3, has_more=True)
        assert len(second_page) == 1
        assert_pagination_meta(second_meta, limit=2, offset=2, total_count=3, has_more=False)
        assert surveyed["id"] not in ids_of(first_page) + ids_of(second_page)

        assert ids_of(by_state) == [surveyed["id"]]
        assert_pagination_meta(state_meta, total_count=1)
        assert port.get_vehicle(surveyed["id"])["processing_status"] == PROC_SURVEYED

        assert_pagination_meta(
            default_meta, limit=DEFAULT_PAGE_LIMIT, offset=DEFAULT_PAGE_OFFSET, total_count=4
        )
        assert len(default_page) == 4


class TestUnknownIdentifier:
    def test_an_unknown_unit_id_answers_with_its_own_not_found_code(self, flow: Vpc):
        """A well-formed but unminted UUID is a 404, not an empty 200.

        PRD: "Each identifier has its own dedicated not-found code: `centerId`
        yields `ERR_CENTER_NOT_FOUND`, `berthId` yields `ERR_BERTH_NOT_FOUND`,
        `vesselId` yields `ERR_VESSEL_NOT_FOUND`, `vehicleId` yields
        `ERR_VEHICLE_NOT_FOUND`, `surveyId` yields `ERR_SURVEY_NOT_FOUND`,
        `claimId` yields `ERR_CLAIM_NOT_FOUND`, `repairOrderId` yields
        `ERR_REPAIR_ORDER_NOT_FOUND`, `kitId` yields `ERR_KIT_NOT_FOUND`,
        `workOrderId` yields `ERR_WORK_ORDER_NOT_FOUND`, `inspectionId` yields
        `ERR_INSPECTION_NOT_FOUND`, `holdOrderId` yields
        `ERR_HOLD_ORDER_NOT_FOUND`, `dealerId` yields `ERR_DEALER_NOT_FOUND`,
        `carrierId` yields `ERR_CARRIER_NOT_FOUND`, and `releaseOrderId` yields
        `ERR_RELEASE_ORDER_NOT_FOUND`."

        Design: Corner/entities/corner_unknown_vehicle_id_returns_vehicle_not_found
        """
        flow.create_center()

        response = flow.api.get_vehicle(MISSING_UUID, PLANNER)
        validate_error(response, ERR_VEHICLE_NOT_FOUND, 404)

        body = response.json()
        assert body["response_type"] == "error"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"]
        assert "id" not in body["data"]


class TestRequiredFields:
    def test_a_voyage_without_its_manifest_count_is_rejected(self, flow: Vpc):
        """declared_unit_count has no default, so omitting it is a schema violation.

        PRD: "The planner supplies the destination `processing_center_id`, the
        reserved `berth_id`, a `voyage_code`, the ocean carrier's `carrier_scac`
        (which becomes the respondent on any damage claim raised against that
        voyage), the `berth_window_start` and `berth_window_end` bounding the
        occupation, and `declared_unit_count`, the number of units the manifest
        declares, which must be at least 1."

        Design: Corner/entities/corner_missing_required_field_on_vessel_create_is_rejected
        """
        center = flow.create_center()
        berth = flow.create_berth(center["id"])

        payload = f.vessel_payload(center["id"], berth["id"])
        del payload["declared_unit_count"]
        response = flow.api.create_vessel(payload, PLANNER)
        validate_error(response, ERR_INVALID_REQUEST, 400)

        _, meta = validate_paginated(
            flow.api.list_vessels(PLANNER, params={"processing_center_id": center["id"]})
        )
        assert_pagination_meta(meta, total_count=0)


class TestDeclaredDefaults:
    def test_the_three_optional_inputs_fall_back_to_their_declared_values(self, flow: Vpc):
        """A center's free days, a berth's buffer and a carrier's status.

        PRD: "A carrier's `status` is optional on registration and defaults to
        `ACTIVE`; the alternative is `SUSPENDED`."

        Design: Corner/entities/corner_omitted_optional_inputs_take_their_declared_defaults
        """
        center = flow.create_center(name="Default VPC", port_code="USDFT", yard_capacity_slots=20)
        berth = flow.create_berth(center["id"])
        carrier = flow.create_carrier(
            carrier_code="TC-DEF",
            name="Default Transport",
            served_route_zones=["A"],
            linehaul_rate_cents_per_mile=400,
            slot_capacity=2,
            concurrent_load_capacity=1,
        )

        assert center["free_storage_days"] == DEFAULT_FREE_STORAGE_DAYS
        assert berth["turnaround_buffer_minutes"] == DEFAULT_TURNAROUND_BUFFER_MINUTES
        assert_subset(
            carrier, {"status": CARRIER_ACTIVE, "committed_slots": 0, "available_slots": 2}
        )


class TestComputedFields:
    def test_derived_survey_and_unit_figures_are_server_owned(self, flow: Vpc):
        """A draft survey counts its lines; the unit's own copies stay at zero.

        PRD: "The survey is created in `DRAFT` with `line_count` set to the number
        of lines supplied and `surveyed_by_user_id` recorded from the acting
        `X-User-ID`; its `severity_index` and `claimed_amount_cents` stay unset
        until submission."

        Design: Corner/entities/corner_computed_fields_are_server_owned_and_client_values_ignored
        """
        port = open_port(flow)
        unit = port.discharge("000106", model_line=MODEL_LINE_LX500)
        assert_subset(unit, {"severity_index": 0, "claim_mandatory": False})

        survey = port.survey(unit["id"], [f.damage_line(DAMAGE_ZONE_INTERIOR, 20, 15_000)])

        assert_subset(survey, {"line_count": 1, "status": SURVEY_DRAFT})
        assert survey["vehicle_id"] == unit["id"]
        assert_subset(
            port.get_vehicle(unit["id"]), {"severity_index": 0, "claim_mandatory": False}
        )


class TestSystemFields:
    def test_ownership_and_actor_fields_come_from_the_path_and_the_headers(self, flow: Vpc):
        """The discharge body carries no ownership, and no survey body an actor.

        PRD: "Both `processing_center_id` and `vessel_id` are copied from the
        voyage by the server and cannot be set by the client."

        Design: Corner/entities/corner_system_fields_are_generated_and_never_client_supplied
        """
        port = open_port(flow)
        unit = port.discharge("000107", model_line=MODEL_LINE_TX300)

        assert_subset(
            unit,
            {
                "processing_center_id": port.center["id"],
                "vessel_id": port.vessel["id"],
                "yard_presence": YARD_IN_YARD,
                "processing_status": PROC_DISCHARGED,
                "version": 1,
            },
        )

        survey = port.survey(unit["id"], [CLEAN_LINE], SURVEYOR)
        assert survey["surveyed_by_user_id"] == SURVEYOR.user_id
        assert survey["vehicle_id"] == unit["id"]


class TestTypeConstraints:
    def test_four_independent_schema_violations_are_each_a_bad_request(self, flow: Vpc):
        """An out-of-enum line, a short VIN, an empty interval and a bad zone.

        PRD: "5. Request body schema: required fields present, enum members valid,
        numeric ranges honored, a `vin` of exactly 17 characters, and every
        interval's end strictly after its start — `ERR_INVALID_REQUEST` (400)."

        Design: Corner/entities/corner_type_constraints_reject_bad_enum_short_vin_and_inverted_interval
        """
        port = open_port(flow)

        bad_enum = port.api.discharge_vehicle(
            port.vessel["id"], f.vehicle_payload(vin("000108"), model_line="SX999"), PLANNER
        )
        validate_error(bad_enum, ERR_INVALID_REQUEST, 400)

        short_vin = port.api.discharge_vehicle(
            port.vessel["id"], f.vehicle_payload(SHORT_VIN, model_line=MODEL_LINE_LX500), PLANNER
        )
        validate_error(short_vin, ERR_INVALID_REQUEST, 400)

        empty_window = port.api.create_vessel(
            f.vessel_payload(
                port.center["id"],
                port.berth["id"],
                voyage_code="V002",
                berth_window_start="2026-08-09T06:00:00Z",
                berth_window_end="2026-08-09T06:00:00Z",
                declared_unit_count=3,
            ),
            PLANNER,
        )
        validate_error(empty_window, ERR_INVALID_REQUEST, 400)

        bad_zone = port.api.create_dealer(
            f.dealer_payload(
                dealer_code="D-BAD",
                name="Bad Zone Motors",
                route_zone="D",
                distance_miles=100,
                allocation_quota=1,
            ),
            MANAGER,
        )
        validate_error(bad_zone, ERR_INVALID_REQUEST, 400)

        assert port.get_vessel()["discharged_unit_count"] == 0
        _, dealer_meta = validate_paginated(port.api.list_dealers(MANAGER))
        assert_pagination_meta(dealer_meta, total_count=0)


class TestBerthImmutability:
    def test_a_berth_carries_no_version_and_no_updated_at(self, flow: Vpc):
        """The one record in the system without the mutation triple.

        PRD: "A berth has no `updated_at` field, no `version` field, and no update
        operation."

        Design: Corner/entities/corner_berth_is_immutable_and_carries_no_version_field
        """
        center = flow.create_center()
        berth = flow.create_berth(center["id"], berth_code="B1", turnaround_buffer_minutes=90)

        read_back = ok(flow.api.get_berth(berth["id"], PLANNER))

        assert_subset(read_back, {"berth_code": "B1", "turnaround_buffer_minutes": 90})
        assert read_back["processing_center_id"] == center["id"]
        assert_fields_absent(read_back, ["version", "updated_at"])

        _, meta = validate_paginated(
            flow.api.list_berths(PLANNER, params={"processing_center_id": center["id"]})
        )
        assert_pagination_meta(meta, total_count=1)


class TestBodyForeignKeys:
    def test_an_unresolvable_body_reference_is_its_own_shared_not_found(self, flow: Vpc):
        """A kit that does not exist and a berth that does not exist agree.

        PRD: "Foreign keys supplied in a request *body* are resolved separately
        and share a single code, `ERR_REFERENCE_NOT_FOUND` (HTTP 404)."

        Design: Corner/entities/corner_flat_topology_body_foreign_keys_are_validated_across_aggregates
        """
        port = open_port(flow)
        unit = port.discharge(
            "000109", model_line=MODEL_LINE_LX500, pio_program_code="PIO-ALLOY"
        )
        port.surveyed(unit["id"], [CLEAN_LINE])

        bad_kit = port.api.create_work_order(
            unit["id"], f.work_order_payload(MISSING_KIT_UUID, qty=1), TECHNICIAN
        )
        validate_error(bad_kit, ERR_REFERENCE_NOT_FOUND, 404)

        bad_berth = port.api.create_vessel(
            f.vessel_payload(
                port.center["id"],
                MISSING_BERTH_UUID,
                voyage_code="V002",
                berth_window_start="2026-08-20T06:00:00Z",
                berth_window_end="2026-08-20T18:00:00Z",
                declared_unit_count=2,
            ),
            PLANNER,
        )
        validate_error(bad_berth, ERR_REFERENCE_NOT_FOUND, 404)

        _, wo_meta = validate_paginated(
            port.api.list_work_orders(TECHNICIAN, params={"vehicle_id": unit["id"]})
        )
        assert_pagination_meta(wo_meta, total_count=0)
        _, vessel_meta = validate_paginated(
            port.api.list_vessels(PLANNER, params={"processing_center_id": port.center["id"]})
        )
        assert_pagination_meta(vessel_meta, total_count=1)
