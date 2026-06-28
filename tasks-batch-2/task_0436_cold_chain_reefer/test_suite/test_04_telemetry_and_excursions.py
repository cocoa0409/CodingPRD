"""Sensor telemetry, degree-minutes integration, impairment, and posture cascade.

Translates difficulty instances (dual_variant_calc degree-minutes, transitive_cascade
deliver, boundary_precision_check impairment, resource_temporal_overlap reading
collision) and corner calculation / validation instances.
"""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    ApiErrorId,
    fixtures as fx,
    factories as F,
)


def test_degree_minutes_provisional_extends_to_clock_now(api):
    """PRD §3.6: "The **provisional** variant, exposed as a live computed read while the
    shipment is `IN_TRANSIT`, ends the last reading's open trailing interval at the
    current logical-clock offset (now) — so as wall-time advances under a fixed clock,
    that trailing interval, and thus the provisional figure, grows."

    Design: Difficulty/dual_variant_calc/degree_minutes_provisional_vs_final_diverge_on_compartment
    """
    # FROZEN [-25,-15]; readings (0,-20),(60,-12),(80,-12). Out-of-band magnitude of
    # -12 is 3 (above -15). 60->80 dur 20 * 3 = 60; 80->140 (clock 02:20 = 140 min)
    # dur 60 * 3 = 180; provisional = 240.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-1",
                              shipper_op="shipper-op-1", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -20), (60, -12), (80, -12)])
    fx.set_clock("2026-03-01T02:20:00Z")
    resp = api.get_excursion_report(comp["id"], ctx["carrier_headers"])
    data = validate_success(resp)
    assert data["provisional_degree_minutes_out"] == pytest.approx(240, abs=0.01), \
        f"provisional must extend last reading to clock-now (240), got {data['provisional_degree_minutes_out']}"


def test_degree_minutes_final_closes_series_at_last_reading(api):
    """PRD §3.6: "The **final** variant, computed at delivery, ends the last reading's
    interval at that last reading's own `offset_min`, closing the series with no open
    trailing interval so the result is fixed and replay-stable."

    Design: Difficulty/dual_variant_calc/degree_minutes_provisional_vs_final_diverge_on_compartment
    """
    # Same series as provisional; FINAL closes at offset 80 so only the 60->80 interval
    # (dur 20 * mag 3 = 60) contributes. FINAL = 60, strictly less than provisional 240.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-1b",
                              shipper_op="shipper-op-1b", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -20), (60, -12), (80, -12)])
    validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    final = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final["degree_minutes_out"] == pytest.approx(60, abs=0.01), \
        f"FINAL degree_minutes must close at last reading offset (60), got {final['degree_minutes_out']}"
    assert final["degree_minutes_out"] < 240, "FINAL must be strictly less than provisional 240"


def test_deliver_cascade_degree_minutes_to_impairment_to_posture(api):
    """PRD §3.8: "On delivery the platform finalizes `degree_minutes_out` for every compartment using the final variant, recomputes each compartment's `impairment` and the shipment's `load_integrity_posture` from those finalized figures".
    PRD §2.8: "If they exceed the tolerance plus 90 degree-minutes, the impairment is `TOTAL_LOSS` (spoiled)."
    PRD §2.9: "If any compartment's `impairment` is `TOTAL_LOSS`, the posture is `COMPROMISED`."

    Design: Difficulty/transitive_cascade/deliver_cascade_degree_minutes_to_impairment_to_posture
    """
    # FROZEN [-25,-15]; readings (0,-10),(60,-20). -10 is 5 above max; 0->60 dur 60 *
    # mag 5 = 300. FINAL = 300 > tol+90 (120) -> TOTAL_LOSS -> COMPROMISED.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-7",
                              shipper_op="shipper-op-7", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -10), (60, -20)])
    delivered = validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    assert delivered["load_integrity_posture"] == "COMPROMISED"
    final_comp = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final_comp["degree_minutes_out"] == pytest.approx(300, abs=0.01)
    assert final_comp["impairment"] == "TOTAL_LOSS"


def test_deliver_cascade_partial_impairment_drives_at_risk(api):
    """PRD §2.8: "If they exceed the tolerance but are at most the tolerance plus a fixed partial span of 90 degree-minutes, the impairment is `PARTIAL` (impaired)."
    PRD §2.9: "Otherwise, if any compartment's `impairment` is `PARTIAL`, the posture is `AT_RISK`."

    Design: Difficulty/transitive_cascade/deliver_cascade_degree_minutes_to_impairment_to_posture
    """
    # FROZEN tol 30; (0,-12),(60,-20) -> 0->60 dur 60 * mag 3 = 180 -> exceeds tol but
    # within tol+90? 180 > 120 -> TOTAL_LOSS. Use (0,-12),(20,-20) instead: dur 20 *3=60
    # -> PARTIAL -> AT_RISK.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-7b",
                              shipper_op="shipper-op-7b", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -12), (20, -20)])
    delivered = validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    assert delivered["load_integrity_posture"] == "AT_RISK"
    final_comp = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final_comp["degree_minutes_out"] == pytest.approx(60, abs=0.01)
    assert final_comp["impairment"] == "PARTIAL", \
        "the finalized degree-minutes must reclassify the compartment to PARTIAL, driving AT_RISK"


def test_impairment_at_tolerance_boundary_is_none(api):
    """PRD §2.8: "If the accumulated degree-minutes are at most the tolerance, the impairment is `NONE` (the cargo is sound)."
    PRD §2.8: "a compartment whose total lands exactly on the tolerance is `NONE`".
    PRD §2.9: "Otherwise — when every compartment is `NONE` — the posture is `INTACT`."

    Design: Difficulty/boundary_precision_check/impairment_tolerance_boundary_30_degree_minutes_empty_excursion
    """
    # FROZEN tol 30; readings (0,-20),(60,-12),(70,-18). 60->70 dur 10 * mag 3 = 30.
    # FINAL = 30 == tol -> NONE -> INTACT.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-12",
                              shipper_op="shipper-op-12", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(0, -20), (60, -12), (70, -18)])
    delivered = validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    assert delivered["load_integrity_posture"] == "INTACT"
    final_comp = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final_comp["degree_minutes_out"] == pytest.approx(30, abs=0.01)
    assert final_comp["impairment"] == "NONE", "degree_minutes exactly at tolerance must be NONE"


def test_empty_excursion_set_classifies_none(api):
    """PRD §2.8: "If the accumulated degree-minutes are at most the tolerance, the impairment is `NONE` (the cargo is sound)."

    Design: Difficulty/boundary_precision_check/impairment_tolerance_boundary_30_degree_minutes_empty_excursion
    """
    # A compartment with no TEMP readings has degree_minutes_out 0 (<= tol) -> NONE.
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-12b",
                              shipper_op="shipper-op-12b", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    delivered = validate_success(api.deliver_shipment(ctx["shipment"]["id"], fx.DRIVER))
    assert delivered["load_integrity_posture"] == "INTACT"
    final_comp = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert final_comp["degree_minutes_out"] == pytest.approx(0, abs=0.01)
    assert final_comp["impairment"] == "NONE"


def test_temp_reading_offset_equal_to_latest_same_kind_collides(api):
    """PRD §3.5: "When a reading is appended, its `offset_min` must be strictly greater than the maximum `offset_min` among that compartment's existing readings of the same `kind`; a reading whose offset is equal to or earlier than the latest same-kind offset collides and is rejected with `ERR_READING_OFFSET_DUPLICATE`."

    Design: Difficulty/resource_temporal_overlap/sensor_reading_offset_point_collision_on_compartment
    """
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-16",
                              shipper_op="shipper-op-16", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(60, -20)])
    resp = api.create_reading(comp["id"], F.create_reading_payload("TEMP", 60, temp_c=-18), fx.DRIVER)
    validate_error(resp, ApiErrorId.ERR_READING_OFFSET_DUPLICATE.value)


def test_temp_reading_offset_strictly_greater_succeeds(api):
    """PRD §3.5: "its `offset_min` must be strictly greater than the maximum `offset_min` among that compartment's existing readings of the same `kind".

    Design: Difficulty/resource_temporal_overlap/sensor_reading_offset_point_collision_on_compartment
    """
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-op-16b",
                              shipper_op="shipper-op-16b", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    fx.add_temp_readings(comp["id"], [(60, -20)])
    resp = api.create_reading(comp["id"], F.create_reading_payload("TEMP", 61, temp_c=-18), fx.DRIVER)
    validate_success(resp, expected_status=201)


def test_temp_reading_without_temp_c_returns_reading_shape(api):
    """PRD §3.5: "The shape rule is strict: a `TEMP` or `PRECOOL` reading must carry a `temp_c`, and a `DOOR_OPEN` reading must omit `temp_c`; a violation of either half is rejected with `ERR_READING_SHAPE`."

    Design: Corner/validations/temp_reading_without_temp_c_returns_reading_shape
    """
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-c17",
                              shipper_op="shipper-c17", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    resp = api.create_reading(comp["id"], F.create_reading_payload("TEMP", 10), fx.DRIVER)
    validate_error(resp, ApiErrorId.ERR_READING_SHAPE.value)


def test_door_open_event_increments_compartment_counter(api):
    """PRD §3.5: "A `DOOR_OPEN` reading increments the compartment's `door_open_events` count and recomputes posture."

    Design: Corner/calculations/door_open_event_increments_compartment_counter
    """
    ctx = fx.setup_in_transit(num_compartments=1, carrier_op="carrier-c16",
                              shipper_op="shipper-c16", clock="2026-03-01T00:00:00Z")
    comp = ctx["compartments"][0]
    validate_success(
        api.create_reading(comp["id"], F.create_reading_payload("DOOR_OPEN", 10), fx.DRIVER),
        expected_status=201,
    )
    data = validate_success(api.get_compartment(comp["id"], ctx["carrier_headers"]))
    assert data["door_open_events"] == 1
