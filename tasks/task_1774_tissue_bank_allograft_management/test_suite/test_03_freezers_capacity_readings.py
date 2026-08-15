"""Cold storage: freezer registration, derived capacity fields, temperature
readings, occupancy reconciliation, and optimistic concurrency."""
import pytest

from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_freezer,
    assert_temperature_reading,
    create_freezer_payload,
    create_shipment,
    issue_unit,
    make_manifest_item,
    setup_available_units,
    setup_freezer,
    setup_supplier_and_freezer,
    validate_error,
    validate_success,
)

COORD = TEST_USERS["coordinator_headers"]
QM = TEST_USERS["quality_headers"]
ADMIN = TEST_USERS["admin_headers"]


class TestFreezerCreation:
    def test_freezer_computed_capacity_fields_on_create(self, api):
        """PRD §3.3: "First, `occupied_count` counts the units stored in the
        freezer — those in `QUARANTINED`, `AVAILABLE`, or `RESERVED`. Second,
        `utilization_pct` is `occupied_count` divided by `nominal_capacity`,
        multiplied by 100, at two decimal places. Third,
        `quarantine_reserve_slots` is 2 when `utilization_pct` reaches at least
        80.0, and 0 otherwise. Fourth, `effective_capacity` is
        `nominal_capacity` minus `quarantine_reserve_slots`."
        PRD §3.3: "New freezers begin `OPERATIONAL`."

        Design: Corner/entities/freezer_computed_capacity_fields_on_create
        """
        freezer = validate_success(
            api.create_freezer(
                create_freezer_payload(name="FZ-ULT-1", nominal_capacity=10), ADMIN
            ),
            201,
        )
        assert_freezer(freezer)
        assert freezer["status"] == "OPERATIONAL"
        assert freezer["occupied_count"] == 0
        assert freezer["utilization_pct"] == pytest.approx(0.0, abs=0.005)
        assert freezer["quarantine_reserve_slots"] == 0
        assert freezer["effective_capacity"] == 10
        assert freezer["current_excursion_id"] is None

    def test_freezer_invalid_temp_range_rejected(self, api):
        """PRD §3.3: "A band whose lower bound is not strictly below its upper
        bound is rejected with `ERR_INVALID_TEMP_RANGE`; a capacity below one
        fails with `ERR_INVALID_REQUEST`."

        Design: Corner/errors/error_invalid_temp_range
        """
        resp = api.create_freezer(
            create_freezer_payload(
                name="FZ-BAD", min_celsius=-50.0, max_celsius=-60.0,
                nominal_capacity=10,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_TEMP_RANGE)


class TestReadings:
    def test_temperature_reading_is_immutable_event(self, api):
        """PRD §2.5: "One resource type is deliberately lighter: a
        `TemperatureReading` is an immutable observation and carries only `id`
        and `created_at` — both `updated_at` and `version` are absent from
        it."
        PRD §3.3: "The platform computes `in_range` by comparing the
        observation against the freezer's `min_celsius` and `max_celsius` as
        they stand at record time — the bounds snapshot lives on the reading —
        and stamps `recorded_by_user_id` with the acting operator."

        Design: Corner/entities/temperature_reading_is_immutable_event
        """
        freezer = setup_freezer()
        reading = validate_success(
            api.create_reading(freezer["id"], {"temp_celsius": -70.0}, COORD), 201
        )
        assert_temperature_reading(reading)
        assert reading["in_range"] is True
        assert reading["excursion_id"] is None
        assert reading["recorded_by_user_id"] == "tbc-1"

    def test_reading_exactly_at_max_is_in_range(self, api):
        """PRD §3.3: "An out-of-range reading — strictly above `max_celsius` or
        strictly below `min_celsius` — opens a `TemperatureExcursion` of
        `origin` `AUTO_READING` in `OPEN` status while the freezer is
        `OPERATIONAL`"
        PRD §3.3: "An in-range reading is a plain observation with
        `excursion_id` null."

        Design: Difficulty/boundary_precision_check/temperature_reading_exactly_at_max_in_range
        """
        freezer = setup_freezer()
        reading = validate_success(
            api.create_reading(freezer["id"], {"temp_celsius": -60.0}, COORD), 201
        )
        assert reading["in_range"] is True
        assert reading["excursion_id"] is None
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["status"] == "OPERATIONAL"

    def test_reading_one_tenth_above_max_opens_excursion(self, api):
        """PRD §3.3: "An out-of-range reading — strictly above `max_celsius` or
        strictly below `min_celsius` — opens a `TemperatureExcursion` of
        `origin` `AUTO_READING` in `OPEN` status while the freezer is
        `OPERATIONAL`"
        PRD §3.3: "The excursion's own bookkeeping tracks `opened_at`, the
        `max_deviation_celsius` observed across its linked readings — for each
        reading the largest of zero, the amount by which the temperature
        exceeded `max_celsius`, and the amount by which it fell below
        `min_celsius`, taking the maximum over all linked readings"

        Design: Difficulty/boundary_precision_check/temperature_reading_exactly_at_max_in_range
        """
        freezer = setup_freezer()
        reading = validate_success(
            api.create_reading(freezer["id"], {"temp_celsius": -59.9}, COORD), 201
        )
        assert reading["in_range"] is False
        assert reading["excursion_id"] is not None
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["status"] == "EXCURSION_ACTIVE"
        excursion = validate_success(api.get_excursion(reading["excursion_id"], QM))
        assert excursion["max_deviation_celsius"] == pytest.approx(0.1, abs=1e-6)
        assert excursion["origin"] == "AUTO_READING"
        assert excursion["status"] == "OPEN"


class TestCapacityGating:
    def test_capacity_reserve_engages_at_eighty_percent(self, api):
        """PRD §3.3: "Third, `quarantine_reserve_slots` is 2 when
        `utilization_pct` reaches at least 80.0, and 0 otherwise. Fourth,
        `effective_capacity` is `nominal_capacity` minus
        `quarantine_reserve_slots`. Admission follows: storing N additional
        units requires `occupied_count` plus N to stay at or below
        `effective_capacity` — equality is admitted — otherwise the operation
        fails with `ERR_FREEZER_CAPACITY_EXCEEDED`. The evaluation is performed
        strictly in this numbered order and never iterated to a fixed point."

        Design: Corner/calculations/capacity_reserve_engages_at_eighty_percent
        """
        supplier, freezer = setup_supplier_and_freezer(
            freezer_name="FZ-SMALL", nominal_capacity=5
        )
        items_a = [make_manifest_item(serial_number=f"U-00{i}", unit_cost_cents=1000)
                   for i in (1, 2, 3)]
        shipment_a = create_shipment(supplier["id"], freezer["id"], items_a)
        assert shipment_a["unit_count"] == 3
        # 3/5 = 60%: reserve still 0, so a 4th unit is admitted.
        shipment_b = create_shipment(
            supplier["id"],
            freezer["id"],
            [make_manifest_item(lot_number="L2", serial_number="U-004",
                                unit_cost_cents=1000)],
        )
        assert shipment_b["unit_count"] == 1
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["occupied_count"] == 4
        assert freezer_after["utilization_pct"] == pytest.approx(80.0, abs=0.005)
        assert freezer_after["quarantine_reserve_slots"] == 2
        assert freezer_after["effective_capacity"] == 3
        # 4 + 1 > 3 under the engaged reserve.
        resp = api.create_shipment(
            {
                "supplier_id": supplier["id"],
                "freezer_id": freezer["id"],
                "items": [make_manifest_item(lot_number="L3", serial_number="U-005",
                                             unit_cost_cents=1000)],
            },
            COORD,
        )
        validate_error(resp, ApiErrorId.ERR_FREEZER_CAPACITY_EXCEEDED)

    def test_capacity_below_occupied_on_reconfigure(self, api):
        """PRD §3.3: "the new `nominal_capacity` must leave `occupied_count` no
        greater than the new capacity minus the reserve computed from the new
        utilization, and a configuration that strands existing stock is
        rejected with `ERR_CAPACITY_BELOW_OCCUPIED`."

        Design: Corner/errors/error_capacity_below_occupied_on_reconfigure
        """
        supplier, freezer = setup_supplier_and_freezer(
            freezer_name="FZ-SMALL", nominal_capacity=3
        )
        create_shipment(
            supplier["id"],
            freezer["id"],
            [make_manifest_item(serial_number=f"U-00{i}", unit_cost_cents=1000)
             for i in (1, 2, 3)],
        )
        resp = api.update_freezer(
            freezer["id"],
            {"nominal_capacity": 2,
             "expected_freezer_version": freezer["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_CAPACITY_BELOW_OCCUPIED)
        after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert after["nominal_capacity"] == 3
        assert after["version"] == freezer["version"]


class TestOccupancyReconciliation:
    def test_freezer_occupancy_reconciles_across_issue_and_return(self, api):
        """PRD §3.3: "First, `occupied_count` counts the units stored in the
        freezer — those in `QUARANTINED`, `AVAILABLE`, or `RESERVED`."
        PRD §3.4: "A successful issue moves the unit to `ISSUED`, fulfills the
        reservation when one was used (its status becomes `FULFILLED`), and
        decrements the freezer's `occupied_count`."
        PRD §3.4: "A successful return moves the unit back to `AVAILABLE`,
        clears `recall_flag` to false, and increments `occupied_count`."

        Design: Corner/complexity_layers/freezer_occupancy_reconciles_across_issue_and_return
        """
        _, freezer, _, units = setup_available_units()
        before = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert before["occupied_count"] == 1
        issue_unit(units[0]["id"])
        after_issue = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert after_issue["occupied_count"] == 0
        returned = validate_success(api.return_unit_to_stock(units[0]["id"], COORD))
        assert returned["status"] == "AVAILABLE"
        after_return = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert after_return["occupied_count"] == 1


class TestImmediateConsistency:
    def test_reading_response_and_reads_reflect_excursion_immediately(self, api):
        """PRD §3.3: "either way the reading's `excursion_id` links it to that
        excursion, and the excursion's `last_reading_at` advances to the
        reading's clock time."
        PRD §3.3: "Opening an excursion flips the freezer from `OPERATIONAL` to
        `EXCURSION_ACTIVE`, records the new excursion as the freezer's
        `current_excursion_id`, increments the freezer's `version` by one, and
        fires the quarantine cascade: every unit stored there in `AVAILABLE`
        moves to `QUARANTINED` with `hold_reason` `EXCURSION`"

        Design: Corner/consistency_model/immediate_consistency_read_your_writes
        """
        _, freezer, _, units = setup_available_units()
        reading = validate_success(
            api.create_reading(freezer["id"], {"temp_celsius": -50.0}, COORD), 201
        )
        assert reading["in_range"] is False
        assert reading["excursion_id"] is not None
        freezer_after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert freezer_after["status"] == "EXCURSION_ACTIVE"
        assert freezer_after["current_excursion_id"] == reading["excursion_id"]
        unit_after = validate_success(api.get_tissue_unit(units[0]["id"], QM))
        assert unit_after["status"] == "QUARANTINED"
        assert unit_after["hold_reason"] == "EXCURSION"


class TestFreezerOcc:
    def test_freezer_update_stale_version_rejected(self, api):
        """PRD §2.7: "Reconfiguring a freezer (`PUT /tissue-bank/freezers/{id}`)
        requires the request to carry `expected_freezer_version` holding the
        freezer `version` the client last observed. If the freezer's current
        `version` has moved past that value — whether because another writer
        reconfigured it or because a temperature-reading cascade bumped it —
        the update is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.3: "A successful reconfiguration increments the freezer's
        `version` by one."

        Design: Corner/validations/occ_freezer_update_stale_version
        """
        freezer = setup_freezer()
        updated = validate_success(
            api.update_freezer(
                freezer["id"],
                {"max_celsius": -59.0,
                 "expected_freezer_version": freezer["version"]},
                ADMIN,
            )
        )
        assert updated["version"] == freezer["version"] + 1
        assert updated["max_celsius"] == pytest.approx(-59.0)
        resp = api.update_freezer(
            freezer["id"],
            {"max_celsius": -58.0,
             "expected_freezer_version": freezer["version"]},
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = validate_success(api.get_freezer(freezer["id"], ADMIN))
        assert after["max_celsius"] == pytest.approx(-59.0)
