"""Aging-room posture, wheel placement gates, clock-driven age/turn
projections, turns, moves-adjacent occupancy accounting, and room
decommissioning."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_aging_unit,
    batch_id_for_make,
    complete_make,
    create_aging_room,
    create_aging_room_payload,
    create_aging_unit_payload,
    create_intake,
    create_make_sheet,
    create_plant,
    create_released_additive_pair,
    create_vat,
    get_room,
    get_vat,
    grade_batch,
    make_completed_batch,
    make_released_batch,
    place_wheels,
    release_batch,
    set_clock,
    sign_steps_through_curd_ready,
    start_make,
    validate_error,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["plant_admin_headers"]
CELLAR = TEST_USERS["aging_room_operator_headers"]
QA = TEST_USERS["qa_grader_headers"]


class TestAgeAndTurnProjection:
    def test_age_days_floors_partial_days_and_turn_due_waits_for_interval(self, api):
        """PRD §3.6: "An `IN_ROOM` unit's `age_days` is the elapsed time from
        `entered_at` to the current logical time, divided into whole days of
        86,400 seconds and floored — never rounded up. Its `turns_due` flag is
        true exactly when the whole days since `last_turned_at`, floored the
        same way, reach or exceed the variety's turn interval: seven days for
        `CHEDDAR`, five for `COLBY`, three each for `BRICK` and `MUENSTER`."

        Design: Difficulty/dual_variant_calc/aging_unit_age_days_floor_vs_turn_due_projection_variants
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=5,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        set_clock("2026-08-01T12:00:00Z")
        unit = place_wheels(ctx["batch_id"], room, 5)
        set_clock("2026-08-04T11:59:59Z")
        before = validate_success(api.get_aging_unit(unit["id"], CELLAR))
        assert before["age_days"] == 2, (
            f"2 days 23:59:59 must floor to 2, got {before['age_days']}"
        )
        assert before["turns_due"] is False, (
            "2 floored days is below the 3-day MUENSTER interval"
        )

    def test_age_days_and_turn_due_at_exact_interval_boundary(self, api):
        """PRD §3.6: "A unit exactly at its interval is due."
        PRD §3.6: "An `IN_ROOM` unit's `age_days` is the elapsed time from
        `entered_at` to the current logical time, divided into whole days of
        86,400 seconds and floored — never rounded up."

        Design: Difficulty/dual_variant_calc/aging_unit_age_days_floor_vs_turn_due_projection_variants
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=5,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        set_clock("2026-08-01T12:00:00Z")
        unit = place_wheels(ctx["batch_id"], room, 5)
        set_clock("2026-08-04T12:00:00Z")
        after = validate_success(api.get_aging_unit(unit["id"], CELLAR))
        assert after["age_days"] == 3, (
            f"exactly 3 days must read age_days 3, got {after['age_days']}"
        )
        assert after["turns_due"] is True, (
            "a MUENSTER unit exactly at its 3-day interval is due"
        )

    def test_clock_endpoint_default_time(self, api):
        """PRD §2.4: "Before any clock call has been made, the logical clock
        reads exactly `2026-08-01T00:00:00Z`, and the server must not fall back
        to wall-clock time under any circumstance."

        Design: Corner/endpoints/clock_endpoint_default_time
        """
        # No set_current_utc call anywhere in this test.
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0, set_initial_clock=False)
        room = create_aging_room(ctx["plant"]["id"])
        unit = place_wheels(ctx["batch_id"], room, 4)
        assert_aging_unit(unit)
        assert unit["entered_at"].startswith("2026-08-01T00:00:00"), (
            f"entered_at must come from the default logical clock, got {unit['entered_at']}"
        )
        assert unit["age_days"] == 0
        assert unit["turns_due"] is False

    def test_aging_unit_turn_resets_turns_due(self, api):
        """PRD §3.6: "Recording a turn sets `last_turned_at` to the current
        logical time and recomputes `turns_due`, which will read false until
        the interval elapses again."

        Design: Corner/state_machines/aging_unit_turn_resets_turns_due
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        unit = place_wheels(ctx["batch_id"], room, 4)
        set_clock("2026-08-05T00:00:00Z")
        pre = validate_success(api.get_aging_unit(unit["id"], CELLAR))
        assert pre["turns_due"] is True, (
            "4 days since the last turn reaches the 3-day MUENSTER interval"
        )
        turned = validate_success(api.turn_aging_unit(unit["id"], CELLAR))
        assert turned["turns_due"] is False, "a turn resets the interval"
        assert turned["last_turned_at"].startswith("2026-08-05T00:00:00"), (
            f"last_turned_at must stamp the logical now, got {turned['last_turned_at']}"
        )


class TestRoomPostureAndPlacementGates:
    def test_aging_room_posture_deviation_outranks_full(self, api):
        """PRD §3.1: "Room posture follows a pinned evaluation order, because
        environment outranks capacity. Whenever `wheels_present`,
        `capacity_wheels`, or the environment readings change, posture is
        re-derived: first the environment band is checked, and a `temp_c`
        strictly below 7.0 or strictly above 13.0 Celsius, or a `humidity_pct`
        strictly below 80.0 or strictly above 90.0 percent, forces `DEVIATION`
        no matter how empty the room is"

        Design: Corner/calculations/aging_room_posture_deviation_outranks_full
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"], capacity_wheels=4)
        place_wheels(ctx["batch_id"], room, 4)
        updated = validate_success(
            api.update_aging_room(room["id"], {"temp_c": 20.0}, CELLAR)
        )
        assert updated["posture"] == "DEVIATION", (
            f"environment outranks capacity: a full room out of band reads DEVIATION, "
            f"got {updated['posture']}"
        )

    def test_error_room_deviation_blocks_placement(self, api):
        """PRD §3.6: "The room's environment must be in band, since a
        `DEVIATION` posture fails the placement with `ERR_ROOM_DEVIATION`."

        Design: Corner/errors/error_room_deviation_blocks_placement
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        validate_success(api.update_aging_room(room["id"], {"humidity_pct": 95.0}, CELLAR))
        room_now = get_room(room["id"])
        assert room_now["posture"] == "DEVIATION"
        resp = api.create_aging_unit(
            create_aging_unit_payload(
                cheese_batch_id=ctx["batch_id"],
                aging_room_id=room["id"],
                wheel_count=4,
                expected_aging_room_version=room_now["version"],
            ),
            CELLAR,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_DEVIATION, 409)

    def test_error_wheels_exhausted_on_overplacement(self, api):
        """PRD §3.6: "The batch must have wheels left to place: `wheel_count`
        must not exceed the batch's `wheels_produced` minus its
        `wheels_placed`, failing `ERR_WHEELS_EXHAUSTED`, with exact equality
        permitted."

        Design: Corner/errors/error_wheels_exhausted_on_overplacement
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        room_now = get_room(room["id"])
        resp = api.create_aging_unit(
            create_aging_unit_payload(
                cheese_batch_id=ctx["batch_id"],
                aging_room_id=room["id"],
                wheel_count=5,
                expected_aging_room_version=room_now["version"],
            ),
            CELLAR,
        )
        validate_error(resp, ApiErrorId.ERR_WHEELS_EXHAUSTED, 409)

    def test_aging_room_decommission_blocked_when_nonempty(self, api):
        """PRD §3.1: "Decommissioning a room requires it to be completely empty
        — a `wheels_present` above zero fails with `ERR_ROOM_NOT_EMPTY` — and
        drops the plant's total aging capacity by the room's
        `capacity_wheels`; a decommissioned room's `posture` is frozen and
        never re-derived."

        Design: Corner/state_machines/aging_room_decommission_blocked_when_nonempty
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        place_wheels(ctx["batch_id"], room, 4)
        resp = api.decommission_aging_room(room["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ROOM_NOT_EMPTY, 409)
        room_now = get_room(room["id"])
        assert room_now["status"] == "ACTIVE", "a blocked decommission leaves the room ACTIVE"


class TestRoomCapacityBoundary:
    def _two_batches_one_vat(self, license_number, wheels_a, wheels_b):
        """Two completed MUENSTER batches on one plant/vat (CIP between makes)."""
        ctx = make_completed_batch(variety="MUENSTER", volume_liters=20000.0,
                                   liters_committed=5000.0, green_weight_kg=500.0,
                                   wheels_produced=wheels_a)
        plant = ctx["plant"]
        vat = get_vat(ctx["vat"]["id"])
        validate_success(api_client.cip_vat(vat["id"], TEST_USERS["cheesemaker_headers"]))
        vat = get_vat(vat["id"])
        make_b = create_make_sheet(
            vat["id"], vat["version"], ctx["intake"]["id"],
            ctx["culture"]["id"], ctx["coagulant"]["id"],
            scheduled_start="2026-08-01T06:00:00Z", scheduled_end="2026-08-01T08:00:00Z",
        )
        start_make(make_b["id"])
        sign_steps_through_curd_ready(make_b["id"], "MUENSTER")
        complete_make(make_b["id"], green_weight_kg=500.0, wheels_produced=wheels_b)
        ctx["batch_b_id"] = batch_id_for_make(make_b["id"])
        return ctx

    def test_exact_capacity_fill_then_overflow_rejected(self, api):
        """PRD §3.6: "Capacity must hold after the placement: `wheels_present`
        plus `wheel_count` must not exceed `capacity_wheels`, failing
        `ERR_ROOM_FULL`; landing exactly at capacity passes and flips the room
        to `FULL`."
        PRD §3.1: "a room whose `wheels_present` exactly equals its
        `capacity_wheels` is `FULL`, and anything short of that is
        `AVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/aging_room_capacity_aggregate_overlap
        """
        ctx = self._two_batches_one_vat("WI-115", 8, 5)
        room = create_aging_room(ctx["plant"]["id"], capacity_wheels=12)
        place_wheels(ctx["batch_id"], room, 8)
        place_wheels(ctx["batch_b_id"], room, 4)
        room_now = get_room(room["id"])
        assert room_now["wheels_present"] == 12
        assert room_now["posture"] == "FULL", (
            f"wheels_present 12 == capacity 12 must read FULL, got {room_now['posture']}"
        )
        resp = api.create_aging_unit(
            create_aging_unit_payload(
                cheese_batch_id=ctx["batch_b_id"],
                aging_room_id=room["id"],
                wheel_count=1,
                expected_aging_room_version=room_now["version"],
            ),
            CELLAR,
        )
        validate_error(resp, ApiErrorId.ERR_ROOM_FULL, 409)
        room_after = get_room(room["id"])
        assert room_after["wheels_present"] == 12, "a rejected placement changes nothing"

    def test_landing_exactly_at_capacity_passes(self, api):
        """PRD §3.6: "Capacity must hold after the placement: `wheels_present`
        plus `wheel_count` must not exceed `capacity_wheels`, failing
        `ERR_ROOM_FULL`; landing exactly at capacity passes and flips the room
        to `FULL`."

        Design: Difficulty/resource_temporal_overlap/aging_room_capacity_aggregate_overlap
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"], capacity_wheels=4)
        unit = place_wheels(ctx["batch_id"], room, 4)
        assert unit["status"] == "IN_ROOM", (
            "landing exactly at capacity passes the placement gate"
        )
        room_now = get_room(room["id"])
        assert room_now["posture"] == "FULL"
        assert room_now["wheels_present"] == 4


class TestOccupancyConservation:
    def test_occupancy_restored_after_place_and_remove(self, api):
        """PRD §3.6: "Removal moves the unit `IN_ROOM` → terminal `REMOVED`,
        drops the room's `wheels_present` by `wheel_count`, and re-derives the
        posture."
        PRD §3.6: "The room's `wheels_present` rises by `wheel_count`, its
        `posture` is re-derived per §3.1, and its `version` increments by one."

        Design: Difficulty/compensating_invariant/aging_room_occupancy_conserved_across_place_and_remove
        """
        ctx = make_released_batch(variety="MUENSTER", wheels_produced=4,
                                  green_weight_kg=500.0, room_capacity=10,
                                  age_to="2026-08-25T00:00:00Z")
        removed = validate_success(api.remove_aging_unit(ctx["unit"]["id"], CELLAR))
        assert removed["status"] == "REMOVED"
        room_now = get_room(ctx["room"]["id"])
        assert room_now["wheels_present"] == 0, (
            "place(+4) + remove(-4) must restore pre-placement occupancy"
        )
        assert room_now["posture"] == "AVAILABLE"

    def test_placement_and_removal_each_move_the_ledger_once(self, api):
        """PRD §3.6: "A successful placement is born `IN_ROOM` with
        `entered_at` and `last_turned_at` both set to the current logical time.
        The batch's `wheels_placed` rises by `wheel_count`, and the batch's
        first placement moves it `GREEN` → `AGING`. The room's
        `wheels_present` rises by `wheel_count`, its `posture` is re-derived
        per §3.1, and its `version` increments by one."
        PRD §3.6: "Removal moves the unit `IN_ROOM` → terminal `REMOVED`, drops
        the room's `wheels_present` by `wheel_count`, and re-derives the
        posture."

        Design: Difficulty/compensating_invariant/aging_room_occupancy_conserved_across_place_and_remove
        """
        ctx = make_released_batch(variety="MUENSTER", wheels_produced=4,
                                  green_weight_kg=500.0, room_capacity=10,
                                  age_to="2026-08-25T00:00:00Z")
        room_mid = get_room(ctx["room"]["id"])
        assert room_mid["wheels_present"] == 4, (
            f"placement must raise occupancy by wheel_count, got {room_mid['wheels_present']}"
        )
        assert room_mid["posture"] == "AVAILABLE"
        validate_success(api.remove_aging_unit(ctx["unit"]["id"], CELLAR))
        room_end = get_room(ctx["room"]["id"])
        assert room_end["wheels_present"] == 0
        assert room_end["posture"] == "AVAILABLE"


class TestPlacementOcc:
    def test_stale_version_beats_state_on_occ_endpoints(self, api):
        """PRD §2.9: "The optimistic-concurrency check is fourth: on the two
        endpoints of §2.8, a stale expected version fails with
        `ERR_STALE_VERSION` before any state or business rule is consulted."
        PRD §2.8: "Placing an aging unit (`POST /plant/aging-units`) likewise
        requires a non-optional `expected_aging_room_version` carrying the
        room's last-observed `version`; a mismatch — for example because
        another operator has since placed or removed wheels, advancing the
        room's version and possibly flipping its posture — is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/validations/stale_version_beats_state_on_occ_endpoints
        """
        ctx = make_completed_batch(variety="MUENSTER", wheels_produced=4,
                                   green_weight_kg=500.0)
        room = create_aging_room(ctx["plant"]["id"])
        stale_version = room["version"]
        # A room environment update advances the room's version.
        validate_success(api.update_aging_room(room["id"], {"humidity_pct": 86.0}, CELLAR))
        resp = api.create_aging_unit(
            create_aging_unit_payload(
                cheese_batch_id=ctx["batch_id"],
                aging_room_id=room["id"],
                wheel_count=4,
                expected_aging_room_version=stale_version,
            ),
            CELLAR,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION, 412)
