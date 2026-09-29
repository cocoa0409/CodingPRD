"""Gates that read another entity's state, and the two scheduling resources.

A claim's fulfilment and a shipment's creation each wait on a record they do not
own; the high-voltage bay is an aggregate over half-open intervals; and the
technician cooldown is a per-person high-water mark with a closed lower bound.
"""

import pytest

from test_helpers import (
    assert_same_instant,
    CANONICAL_SNAPSHOTS,
    ApiErrorId,
    add_assessment,
    add_claim,
    add_sibling_vehicle,
    adjudicate,
    advance_containment,
    assert_pack_shipment,
    assert_packaging_requirement_follows_classification,
    file_notification,
    fulfil_payload,
    list_modules,
    make_technician_headers,
    read_center,
    read_claim,
    read_event,
    read_pack,
    read_program,
    read_technician,
    read_vehicle,
    report_thermal_event,
    setup_adjudicated_claim_world,
    setup_base_world,
    setup_technician,
    shipment_payload,
    tender_payload,
    validate_error,
    validate_success,
)

# The centre every hardware remedy in this file runs at: L3, lifted, insulation
# tester in date and the reference labour rate.
HARDWARE_CENTER = {
    "name": "West HV Center",
    "hv_certification_level": "L3",
    "has_pack_lift": True,
    "insulation_tester_cal_due_at": "2027-01-01T00:00:00Z",
    "labor_rate_cents_per_hour": 18333,
}


class TestFulfilmentGatedOnContainment:
    """An approved claim becomes unfulfillable the instant an S3 lands on its pack."""

    def test_both_intermediate_containment_states_refuse_the_same_fulfil_request(self, api):
        """DETECTED and PACK_QUARANTINED refuse; only the closed state admits.

        PRD 3.6: "A safety interlock then blocks fulfilment while a serious thermal
        condition is still open: if any thermal event on the claim's pack has
        `severity` `S3` or `S4` and a `containment_status` other than
        `CONTAINMENT_CLOSED`, the request is refused with
        `ERR_THERMAL_CONTAINMENT_OPEN`."

        Design: Difficulty/cross_entity_state_dependency/claim_fulfilment_gated_on_thermal_event_containment_state
        """
        world = setup_adjudicated_claim_world(
            api,
            center_overrides=HARDWARE_CENTER,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["claim"]["adjudication_status"] == "APPROVED_MODULE"
        assert world["claim"]["remedy_cost_cents"] == 363092

        report_thermal_event(
            api,
            world,
            severity="S3",
            detected_at="2026-07-31T00:00:00Z",
            affected_module_positions=[9],
            source="SERVICE_CENTER",
            headers=world["tech_headers"],
        )
        assert read_pack(api, world["pack_id"])["status"] == "QUARANTINED"
        assert read_vehicle(api, world["vehicle_id"])["status"] == "IMMOBILIZED"

        booking = fulfil_payload(
            world["technician_id"],
            hv_bay_window_start="2026-08-01T10:00:00Z",
            hv_bay_window_end="2026-08-01T14:00:00Z",
        )

        # Attempt one, at containment_status DETECTED.
        validate_error(
            api.fulfil_claim(world["claim_id"], booking, world["tech_headers"]),
            ApiErrorId.ERR_THERMAL_CONTAINMENT_OPEN.value,
            expected_status=409,
        )
        advance_containment(api, world, 1)
        advance_containment(api, world, 2)
        assert read_event(api, world["event_id"])["containment_status"] == "PACK_QUARANTINED"

        # Attempt two, at containment_status PACK_QUARANTINED.
        validate_error(
            api.fulfil_claim(world["claim_id"], booking, world["tech_headers"]),
            ApiErrorId.ERR_THERMAL_CONTAINMENT_OPEN.value,
            expected_status=409,
        )

        refused = read_claim(api, world["claim_id"])
        assert refused["adjudication_status"] == "APPROVED_MODULE"
        assert refused["fulfilment_technician_id"] is None
        assert refused["hv_bay_window_start"] is None
        assert (
            read_technician(api, world["center_id"], world["technician_id"])[
                "last_hv_window_end_at"
            ]
            is None
        )

        file_notification(api, world, regulator_reference="NHTSA-2026-0102")
        closed = advance_containment(api, world, 3)
        assert closed["containment_status"] == "CONTAINMENT_CLOSED"

        # The very same request now succeeds.
        fulfilled = validate_success(
            api.fulfil_claim(world["claim_id"], booking, world["tech_headers"])
        )
        assert fulfilled["adjudication_status"] == "FULFILLED"
        assert_same_instant(fulfilled["hv_bay_window_end"], "2026-08-01T14:00:00Z", "hv_bay_window_end")
        assert fulfilled["pack_shipment_required"] is True
        assert_same_instant(
            read_technician(api, world["center_id"], world["technician_id"])[
                "last_hv_window_end_at"
            ],
            "2026-08-01T14:00:00Z",
            "technician.last_hv_window_end_at",
        )

    def test_module_fulfilment_replaces_the_faulted_roster_and_redirives_the_counters(
        self, api
    ):
        """Every FAULTED module is replaced and stamped, and DEGRADED rows are not.

        PRD 3.6: "A **module replacement** moves every module of the pack whose
        `status` is `FAULTED` to `REPLACED` and stamps each one's `replaced_at` with
        the current logical clock; because those rows changed status, the pack's
        `module_replacements_to_date` rises by the number of modules just replaced
        and its `faulted_module_count` is re-derived, which leaves it at zero.
        Modules in `DEGRADED` are untouched by fulfilment."

        Design: Difficulty/cross_entity_state_dependency/claim_fulfilment_gated_on_thermal_event_containment_state
        """
        world = setup_base_world(
            api,
            center_overrides=HARDWARE_CENTER,
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        add_assessment(
            api,
            world,
            module_fault_positions=[3, 7],
            module_degraded_positions=[9],
        )
        add_claim(api, world)
        adjudicate(api, world, "MODULE_REPLACEMENT")

        fulfilled = validate_success(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(world["technician_id"]),
                world["tech_headers"],
            )
        )
        assert fulfilled["adjudication_status"] == "FULFILLED"

        modules, _ = list_modules(api, world["pack_id"], limit=100)
        by_position = {row["position_index"]: row for row in modules}
        assert by_position[3]["status"] == "REPLACED"
        assert by_position[7]["status"] == "REPLACED"
        assert_same_instant(by_position[3]["replaced_at"], "2026-08-01T00:00:00Z", "module.replaced_at")
        assert_same_instant(by_position[7]["replaced_at"], "2026-08-01T00:00:00Z", "module.replaced_at")
        assert by_position[9]["status"] == "DEGRADED"
        assert by_position[9]["replaced_at"] is None

        pack = read_pack(api, world["pack_id"])
        assert pack["module_replacements_to_date"] == 2
        assert pack["faulted_module_count"] == 0


class TestShipmentGatedOnPackStatus:
    """A shipment cannot be created at all until its pack has left service."""

    def test_only_containment_step_two_frees_the_pack_and_it_ships_as_un3536(self, api):
        """Two refusals, then a quarantine, then a UN3536 declaration on a full pack.

        PRD 3.10: "The pack's `status` must be `REMOVED` or `QUARANTINED`; a pack
        still `IN_SERVICE`, or in `STOCK`, `RESERVED` or `SCRAPPED`, is refused with
        `ERR_SHIPMENT_PACK_NOT_REMOVED`."

        PRD 3.10: "`hazmat_classification` is `UN3536` whenever the pack's
        `damaged_defective` flag is true, whatever `shipment_contents` says."

        Design: Difficulty/cross_entity_state_dependency/pack_shipment_creation_gated_on_battery_pack_status
        """
        world = setup_base_world(api, center_overrides=HARDWARE_CENTER, snapshots=None)

        # An S1 event opens no regulatory dimension and quarantines nothing yet.
        event = report_thermal_event(
            api,
            world,
            severity="S1",
            detected_at="2026-07-31T06:00:00Z",
            affected_module_positions=None,
            source="TELEMATICS",
        )
        assert event["notification_status"] == "NOT_REQUIRED"
        assert event["notification_deadline_at"] is None
        pack = read_pack(api, world["pack_id"])
        assert pack["status"] == "IN_SERVICE"
        assert pack["damaged_defective"] is False

        booking = shipment_payload(
            world["pack_id"],
            world["center_id"],
            world["technician_id"],
            shipment_contents="FULL_PACK",
            packaging_spec="SP376_STRONG_OUTER",
            state_of_charge_pct=25.00,
            transport_mode="GROUND",
            destination="REMAN_CENTER",
        )

        # Attempt one: the pack is still IN_SERVICE.
        validate_error(
            api.create_shipment(booking, world["tech_headers"]),
            ApiErrorId.ERR_SHIPMENT_PACK_NOT_REMOVED.value,
            expected_status=409,
        )

        # Isolating high voltage is not the same as removing the pack.
        advance_containment(api, world, 1, step_note="HV isolated")
        assert read_pack(api, world["pack_id"])["status"] == "IN_SERVICE"
        validate_error(
            api.create_shipment(booking, world["tech_headers"]),
            ApiErrorId.ERR_SHIPMENT_PACK_NOT_REMOVED.value,
            expected_status=409,
        )

        # Step two is where an S1 pack is quarantined, and damage is what classifies.
        advance_containment(api, world, 2, step_note="pack quarantined")
        quarantined = read_pack(api, world["pack_id"])
        assert quarantined["status"] == "QUARANTINED"
        assert quarantined["damaged_defective"] is True

        shipment = validate_success(
            api.create_shipment(booking, world["tech_headers"]), expected_status=201
        )
        assert_pack_shipment(shipment)
        assert shipment["hazmat_classification"] == "UN3536"
        assert_packaging_requirement_follows_classification(shipment)
        assert shipment["required_packaging_spec"] == "SP376_STRONG_OUTER"
        assert shipment["soc_limit_pct"] == pytest.approx(30.00, abs=0.01)
        assert shipment["gross_weight_kg"] == pytest.approx(483.296, abs=0.001)
        # ROUND_HALF_UP(18000 * 483.296 / 100) == 86993
        assert shipment["hazmat_fee_cents"] == 86993
        assert shipment["status"] == "DRAFT"
        assert shipment["tendered_at"] is None

        tendered = validate_success(
            api.tender_shipment(
                shipment["id"], tender_payload("CAR-77120"), world["tech_headers"]
            )
        )
        assert tendered["status"] == "TENDERED"
        assert_same_instant(tendered["tendered_at"], "2026-08-01T00:00:00Z", "tendered_at")

        # The pack carries no origin centre of record, so no hold was ever raised.
        center = read_center(api, world["center_id"])
        assert center["open_hazmat_holds"] == 0
        assert center["compliance_score"] == 100


# A single-bay centre isolates the aggregate occupancy rule from everything else.
SINGLE_BAY_CENTER = dict(HARDWARE_CENTER, hv_bay_count=1)

# Three bays can never bind, which isolates the per-technician cooldown.
THREE_BAY_CENTER = dict(HARDWARE_CENTER, hv_bay_count=3)


def _adjudicated_sibling(api, world, vin: str, serial_number: str) -> dict:
    """A second vehicle in the same programme, carried to an approved module claim."""
    sibling = add_sibling_vehicle(
        api,
        world,
        vin=vin,
        serial_number=serial_number,
        snapshots=CANONICAL_SNAPSHOTS,
        snapshot_overrides={"coolant_temp_c": 20.0},
    )
    add_assessment(api, sibling, module_fault_positions=[3, 7])
    add_claim(api, sibling)
    adjudicate(api, sibling, "MODULE_REPLACEMENT")
    return sibling


class TestHvBayAggregateOccupancy:
    """One bay, three technicians: only the interval arithmetic can refuse anything."""

    def test_back_to_back_windows_share_a_bay_but_a_straddling_one_cannot(self, api):
        """[14:00, 18:00) fits behind [10:00, 14:00); [13:00, 15:00) does not.

        PRD 3.6: "Count the claims at the same center whose `adjudication_status` is
        `FULFILLED` or `CLOSED` and whose own half-open window overlaps the requested
        one; if that count is not strictly less than the center's `hv_bay_count`, the
        request is refused with `ERR_HV_BAY_CAPACITY_EXCEEDED`."

        PRD 3.6: "Because the interval is half-open, a window that begins exactly when
        another ends does not overlap it, and two back-to-back bookings are always
        admissible however many bays the center has."

        Design: Difficulty/resource_temporal_overlap/hv_bay_aggregate_capacity_with_half_open_adjacent_windows
        """
        world = setup_adjudicated_claim_world(
            api,
            center_overrides=SINGLE_BAY_CENTER,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000071"},
            pack_overrides={"serial_number": "PK-0071"},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["center"]["hv_bay_count"] == 1
        tech_a = world["technician_id"]
        tech_b = setup_technician(api, world["center_id"], full_name="Tech B")["id"]
        tech_c = setup_technician(api, world["center_id"], full_name="Tech C")["id"]

        second = _adjudicated_sibling(api, world, "5YJ3E1EA7KF000072", "PK-0072")
        third = _adjudicated_sibling(api, world, "5YJ3E1EA7KF000073", "PK-0073")

        first_booked = validate_success(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(tech_a, "2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z"),
                make_technician_headers(tech_a),
            )
        )
        assert first_booked["adjudication_status"] == "FULFILLED"

        # Starts exactly where the first window ends: a shared instant is no overlap.
        second_booked = validate_success(
            api.fulfil_claim(
                second["claim_id"],
                fulfil_payload(tech_b, "2026-08-01T14:00:00Z", "2026-08-01T18:00:00Z"),
                make_technician_headers(tech_b),
            )
        )
        assert second_booked["adjudication_status"] == "FULFILLED"

        # Straddles both booked windows, and one bay cannot hold a second occupant.
        validate_error(
            api.fulfil_claim(
                third["claim_id"],
                fulfil_payload(tech_c, "2026-08-01T13:00:00Z", "2026-08-01T15:00:00Z"),
                make_technician_headers(tech_c),
            ),
            ApiErrorId.ERR_HV_BAY_CAPACITY_EXCEEDED.value,
            expected_status=409,
        )
        refused = read_claim(api, third["claim_id"])
        assert refused["adjudication_status"] == "APPROVED_MODULE"
        assert refused["hv_bay_window_start"] is None
        assert refused["fulfilment_technician_id"] is None
        assert read_technician(api, world["center_id"], tech_c)["last_hv_window_end_at"] is None

        # The very same claim and technician, moved clear of both windows.
        third_booked = validate_success(
            api.fulfil_claim(
                third["claim_id"],
                fulfil_payload(tech_c, "2026-08-01T18:00:00Z", "2026-08-01T20:00:00Z"),
                make_technician_headers(tech_c),
            )
        )
        assert third_booked["adjudication_status"] == "FULFILLED"

        for claim_id in (world["claim_id"], second["claim_id"], third["claim_id"]):
            settled = read_claim(api, claim_id)
            assert settled["remedy_cost_cents"] == 363092
            assert settled["oem_total_cents"] == 370592
        assert read_program(api, world["program_id"])["accrued_liability_cents"] == 1111776


class TestTechnicianCooldownBuffer:
    """Three bays, one technician: only the sixty-minute rest buffer can refuse."""

    def test_a_fifty_nine_minute_gap_is_refused_and_exactly_sixty_is_accepted(self, api):
        """Nothing overlaps, yet the buffered high-water mark still decides.

        PRD 3.6: "The requested `hv_bay_window_start` must be at or later than the
        technician's `last_hv_window_end_at` plus sixty minutes, or the request is
        refused with `ERR_TECHNICIAN_COOLDOWN_CONFLICT`. The lower bound is closed: a
        start exactly sixty minutes after the previous window's end is accepted, while
        fifty-nine minutes is refused."

        PRD 3.6: "The technician's `last_hv_window_end_at` is raised to the later of
        its current value and the submitted `hv_bay_window_end`."

        Design: Difficulty/resource_temporal_overlap/technician_cooldown_buffered_high_water_mark_boundary
        """
        world = setup_adjudicated_claim_world(
            api,
            center_overrides=THREE_BAY_CENTER,
            vehicle_overrides={"vin": "5YJ3E1EA7KF000081"},
            pack_overrides={"serial_number": "PK-0081"},
            snapshot_overrides={"coolant_temp_c": 20.0},
        )
        assert world["center"]["hv_bay_count"] == 3
        tech_a = world["technician_id"]
        headers = make_technician_headers(tech_a)
        second = _adjudicated_sibling(api, world, "5YJ3E1EA7KF000082", "PK-0082")

        first_booked = validate_success(
            api.fulfil_claim(
                world["claim_id"],
                fulfil_payload(tech_a, "2026-08-01T10:00:00Z", "2026-08-01T14:00:00Z"),
                headers,
            )
        )
        assert first_booked["adjudication_status"] == "FULFILLED"
        assert_same_instant(
            read_technician(api, world["center_id"], tech_a)["last_hv_window_end_at"],
            "2026-08-01T14:00:00Z",
            "technician.last_hv_window_end_at",
        )

        # 14:59 is fifty-nine minutes past the mark: one minute short of the buffer,
        # and it overlaps nothing at a centre with three bays.
        validate_error(
            api.fulfil_claim(
                second["claim_id"],
                fulfil_payload(tech_a, "2026-08-01T14:59:00Z", "2026-08-01T16:00:00Z"),
                headers,
            ),
            ApiErrorId.ERR_TECHNICIAN_COOLDOWN_CONFLICT.value,
            expected_status=409,
        )
        refused = read_claim(api, second["claim_id"])
        assert refused["adjudication_status"] == "APPROVED_MODULE"
        assert refused["hv_bay_window_start"] is None
        assert_same_instant(
            read_technician(api, world["center_id"], tech_a)["last_hv_window_end_at"],
            "2026-08-01T14:00:00Z",
            "technician.last_hv_window_end_at",
        )

        # Exactly sixty minutes past the mark: the lower bound is closed.
        second_booked = validate_success(
            api.fulfil_claim(
                second["claim_id"],
                fulfil_payload(tech_a, "2026-08-01T15:00:00Z", "2026-08-01T16:00:00Z"),
                headers,
            )
        )
        assert second_booked["adjudication_status"] == "FULFILLED"
        assert_same_instant(second_booked["hv_bay_window_start"], "2026-08-01T15:00:00Z", "hv_bay_window_start")
        assert_same_instant(
            read_technician(api, world["center_id"], tech_a)["last_hv_window_end_at"],
            "2026-08-01T16:00:00Z",
            "technician.last_hv_window_end_at",
        )
