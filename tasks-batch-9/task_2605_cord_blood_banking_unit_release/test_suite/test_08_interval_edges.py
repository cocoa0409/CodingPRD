"""Two contended resources with deliberately different interval semantics."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_created_at_ascending,
    build_bank_scenario,
    build_listed_public_scenario,
    expected_pre_cryo_dose,
    make_facilities_engineer_headers,
    make_platform_admin_headers,
    make_technologist_headers,
    make_transplant_center_headers,
    place_reservation,
    read_listing,
    read_reservation,
    read_tank,
    read_unit,
    set_clock,
    unit_version,
    validate_error,
    validate_success,
)


def _unit_with_an_incumbent_hold():
    """A listed public unit holding the closed interval 1 September to 5 September."""
    scenario = build_listed_public_scenario(
        tank_code="TANK-K",
        capacity_slots=5,
        primary_parent_name="Overlap Parent",
        collection_site_code="SITE-13",
        consent_document_hash="hash-ov-v1",
        kit_lot_code="LOT-2026-O",
        courier_tracking_code="TRK-1300",
        slot_code="K-01",
        hla_a="A*02:01",
        hla_b="B*08:01",
        hla_drb1="DRB1*03:01",
    )
    set_clock("2026-08-11T03:00:00Z")
    scenario["incumbent"] = place_reservation(
        scenario["unit"]["id"],
        center_user_id="tc-001",
        requesting_center_name="Center Incumbent",
        patient_weight_kg=35.0,
        patient_hla_match_count=6,
        hold_from="2026-09-01T00:00:00Z",
        hold_until="2026-09-05T00:00:00Z",
    )
    scenario["version"] = unit_version(
        scenario["unit"]["id"], make_transplant_center_headers("tc-002")
    )
    return scenario


def _second_hold_payload(unit_id, version, *, center_name, hold_from):
    return {
        "unit_id": unit_id,
        "requesting_center_name": center_name,
        "patient_weight_kg": 30.0,
        "patient_hla_match_count": 5,
        "hold_from": hold_from,
        "hold_until": "2026-09-09T00:00:00Z",
        "expected_unit_version": version,
    }


class TestHoldWindowBuffer:
    def test_a_gap_one_second_short_of_the_buffer_conflicts(self):
        """A 23-hour-59-minute-59-second gap crosses the buffered edge.

        "Because both comparisons are strict, a gap of exactly 24 hours between two windows
        touches the buffered edge without crossing it and is accepted, while a gap of 23 hours
        59 minutes 59 seconds is rejected."

        Design: Difficulty/resource_temporal_overlap/unit_hold_windows_closed_intervals_with_symmetric_24h_buffer
        """
        scenario = _unit_with_an_incumbent_hold()

        response = api_client.create_reservation(
            _second_hold_payload(
                scenario["unit"]["id"],
                scenario["version"],
                center_name="Center Gap 23h59m59s",
                hold_from="2026-09-05T23:59:59Z",
            ),
            make_transplant_center_headers("tc-002"),
        )

        validate_error(response, ApiErrorId.ERR_HOLD_WINDOW_CONFLICT.value, 409)

    def test_the_rejected_placement_does_not_consume_the_units_version(self):
        """The next centre may reuse the version the refused attempt quoted.

        "The row is created in `PENDING_CONFIRMATORY`, `requesting_center_user_id` is set from the
        acting centre's `X-User-ID`, `pre_cryo_dose_x1e7_per_kg` is computed and
        `dose_variant_applied` is set to `PRE_CRYO`, and the unit's `version` is incremented by
        one."

        Design: Difficulty/resource_temporal_overlap/unit_hold_windows_closed_intervals_with_symmetric_24h_buffer
        """
        scenario = _unit_with_an_incumbent_hold()

        api_client.create_reservation(
            _second_hold_payload(
                scenario["unit"]["id"],
                scenario["version"],
                center_name="Center Gap 23h59m59s",
                hold_from="2026-09-05T23:59:59Z",
            ),
            make_transplant_center_headers("tc-002"),
        )

        assert read_unit(scenario["unit"]["id"])["version"] == scenario["version"]

    def test_a_gap_of_exactly_twenty_four_hours_is_accepted(self):
        """Touching the buffered edge is permitted; crossing it is not.

        "Each incumbent hold on the same unit in status `PENDING_CONFIRMATORY` or `CONFIRMED`
        occupies a closed interval from its `hold_from` to its `hold_until`, and that interval
        is widened by 24 hours on **both** sides before comparison."

        Design: Difficulty/resource_temporal_overlap/unit_hold_windows_closed_intervals_with_symmetric_24h_buffer
        """
        scenario = _unit_with_an_incumbent_hold()
        api_client.create_reservation(
            _second_hold_payload(
                scenario["unit"]["id"],
                scenario["version"],
                center_name="Center Gap 23h59m59s",
                hold_from="2026-09-05T23:59:59Z",
            ),
            make_transplant_center_headers("tc-002"),
        )

        response = api_client.create_reservation(
            _second_hold_payload(
                scenario["unit"]["id"],
                scenario["version"],
                center_name="Center Gap 24h",
                hold_from="2026-09-06T00:00:00Z",
            ),
            make_transplant_center_headers("tc-003"),
        )

        accepted = validate_success(response, 201)
        assert accepted["status"] == "PENDING_CONFIRMATORY"
        assert accepted["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(5.00, abs=0.01)
        assert accepted["pre_cryo_dose_x1e7_per_kg"] == pytest.approx(
            expected_pre_cryo_dose(1500, 30.0), abs=0.01
        )

    def test_placing_a_second_hold_disturbs_neither_the_incumbent_nor_the_listing(self):
        """A hold is not a match: only a confirmation moves the listing.

        "A listing moves `ACTIVE → MATCHED` when a hold on its unit is confirmed, and back
        `MATCHED → ACTIVE` when that confirmed hold is cancelled."

        Design: Difficulty/resource_temporal_overlap/unit_hold_windows_closed_intervals_with_symmetric_24h_buffer
        """
        scenario = _unit_with_an_incumbent_hold()
        validate_success(
            api_client.create_reservation(
                _second_hold_payload(
                    scenario["unit"]["id"],
                    scenario["version"],
                    center_name="Center Gap 24h",
                    hold_from="2026-09-06T00:00:00Z",
                ),
                make_transplant_center_headers("tc-003"),
            ),
            201,
        )

        holds = validate_success(
            api_client.list_reservations(
                make_platform_admin_headers(), {"unit_id": scenario["unit"]["id"]}
            )
        )
        assert len(holds) == 2
        assert_created_at_ascending(holds)

        assert (
            read_reservation(scenario["incumbent"]["id"], center_user_id="tc-001")["status"]
            == "PENDING_CONFIRMATORY"
        )
        assert read_unit(scenario["unit"]["id"])["availability_status"] == "LISTED"
        assert read_listing(scenario["listing"]["id"])["listing_status"] == "ACTIVE"


def _eligible_unit_and_a_tank_with_a_window():
    """An eligible, unfrozen private unit and a tank whose window opens in September."""
    return build_bank_scenario(
        stage="determined",
        tank_code="TANK-L",
        capacity_slots=5,
        maintenance_window_start="2026-09-10T00:00:00Z",
        maintenance_window_end="2026-09-11T00:00:00Z",
        program_type="PRIVATE_FAMILY",
        primary_parent_name="Window Parent",
        collection_site_code="SITE-14",
        consent_document_hash="hash-wn-v1",
        kit_lot_code="LOT-2026-W",
        courier_tracking_code="TRK-1400",
    )


def _attempt_freeze(unit_id, tank_id, freeze_at):
    return api_client.cryopreserve_unit(
        unit_id,
        {"tank_id": tank_id, "slot_code": "L-01", "freeze_at": freeze_at},
        make_technologist_headers(),
    )


class TestMaintenanceWindowEdges:
    def test_a_freeze_exactly_at_the_window_start_is_inside_the_window(self):
        """The maintenance window is closed at its start.

        "a `freeze_at` exactly equal to `maintenance_window_start` is inside the window and
        refused with `ERR_MAINTENANCE_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/tank_maintenance_window_half_open_on_freeze_instant
        """
        scenario = _eligible_unit_and_a_tank_with_a_window()

        response = _attempt_freeze(
            scenario["unit"]["id"], scenario["tank"]["id"], "2026-09-10T00:00:00Z"
        )

        validate_error(response, ApiErrorId.ERR_MAINTENANCE_WINDOW_CONFLICT.value, 409)

    def test_the_refused_freeze_stores_nothing_anywhere(self):
        """The unit stays out of storage and the tank stays empty.

        "It drives the unit `VOLUME_REDUCED → CRYOPRESERVED` and is guarded by five conditions
        beyond consent currency"

        Design: Difficulty/resource_temporal_overlap/tank_maintenance_window_half_open_on_freeze_instant
        """
        scenario = _eligible_unit_and_a_tank_with_a_window()

        _attempt_freeze(scenario["unit"]["id"], scenario["tank"]["id"], "2026-09-10T00:00:00Z")

        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "VOLUME_REDUCED"
        assert unit["tank_id"] is None
        assert unit["slot_code"] is None
        assert unit["cryopreserved_at"] is None
        assert read_tank(scenario["tank"]["id"])["occupied_slots"] == 0

    def test_a_freeze_exactly_at_the_window_end_is_outside_the_window(self):
        """The maintenance window is open at its end.

        "while a `freeze_at` exactly equal to `maintenance_window_end` is outside it and
        accepted."

        Design: Difficulty/resource_temporal_overlap/tank_maintenance_window_half_open_on_freeze_instant
        """
        scenario = _eligible_unit_and_a_tank_with_a_window()
        _attempt_freeze(scenario["unit"]["id"], scenario["tank"]["id"], "2026-09-10T00:00:00Z")

        response = _attempt_freeze(
            scenario["unit"]["id"], scenario["tank"]["id"], "2026-09-11T00:00:00Z"
        )

        validate_success(response, 200)
        unit = read_unit(scenario["unit"]["id"])
        assert unit["processing_status"] == "CRYOPRESERVED"
        assert unit["availability_status"] == "PRIVATE_STORED"
        assert unit["cryopreserved_at"].startswith("2026-09-11T00:00:00")
        assert unit["tank_id"] == scenario["tank"]["id"]
        assert unit["slot_code"] == "L-01"

    def test_the_accepted_freeze_fills_one_slot_and_leaves_the_tank_online(self):
        """Only the nightly batch moves a tank into maintenance, and it never ran here.

        "Independently of alarms, the nightly batch walks tanks into and out of maintenance."

        Design: Difficulty/resource_temporal_overlap/tank_maintenance_window_half_open_on_freeze_instant
        """
        scenario = _eligible_unit_and_a_tank_with_a_window()

        _attempt_freeze(scenario["unit"]["id"], scenario["tank"]["id"], "2026-09-11T00:00:00Z")

        tank = read_tank(scenario["tank"]["id"])
        assert tank["occupied_slots"] == 1
        assert tank["status"] == "ONLINE"

        held = validate_success(
            api_client.list_tank_units(tank["id"], make_facilities_engineer_headers())
        )
        assert len(held) == 1
