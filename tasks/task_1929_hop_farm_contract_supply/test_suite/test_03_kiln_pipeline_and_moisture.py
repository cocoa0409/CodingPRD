"""Harvest lots and the kiln pipeline: buffer rule, moisture gate, redry loop."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, ApiErrorId,
    create_load_kiln_payload, create_redry_payload, create_finish_drying_payload,
    setup_harvesting_plan_with_kiln, create_harvested_lot, create_in_kiln_lot,
    create_moisture_check_lot, WINDOW_DAY1_AM, WINDOW_DAY1_PM,
)


def _instant(iso: str) -> datetime:
    """Parse an ISO 8601 timestamp to an aware instant for format-agnostic
    comparison (PRD §3.2 pins the window's value, not its echo formatting)."""
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)


class TestKilnWindowBufferRule:
    def test_twenty_minute_gap_rejected(self, api, farm_manager_headers):
        """PRD §3.2: "A proposed window conflicts with an occupying window on the
        same kiln unless the two are separated by at least thirty minutes on one
        side or the other: the proposed window must start at or after the
        occupying window's end plus thirty minutes, or end at or before the
        occupying window's start minus thirty minutes." and "A violation is
        rejected with `ERR_KILN_WINDOW_OVERLAP`".

        Design: Difficulty/resource_temporal_overlap/kiln_window_buffer_overlap
        """
        ctx = setup_harvesting_plan_with_kiln()
        create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000,
                           window_start="2026-08-20T08:00:00Z",
                           window_end="2026-08-20T12:00:00Z")
        lot_b = create_harvested_lot(ctx["plan"]["id"], wet_lbs=1000)
        res = api.load_kiln(
            lot_b["id"],
            create_load_kiln_payload(ctx["kiln"]["id"], "2026-08-20T12:20:00Z",
                                     "2026-08-20T16:00:00Z"),
            farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_KILN_WINDOW_OVERLAP)

    def test_exact_thirty_minute_gap_allowed(self, api, farm_manager_headers):
        """PRD §3.2: "Adjacency with exactly thirty minutes of clearance is
        allowed on both sides."

        Design: Difficulty/resource_temporal_overlap/kiln_window_buffer_overlap
        """
        ctx = setup_harvesting_plan_with_kiln()
        create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000,
                           window_start="2026-08-20T08:00:00Z",
                           window_end="2026-08-20T12:00:00Z")
        lot_b = create_harvested_lot(ctx["plan"]["id"], wet_lbs=1000)
        loaded = validate_success(api.load_kiln(
            lot_b["id"],
            create_load_kiln_payload(ctx["kiln"]["id"], "2026-08-20T12:30:00Z",
                                     "2026-08-20T16:00:00Z"),
            farm_manager_headers), 200)
        assert loaded["status"] == "IN_KILN"


class TestMoistureComputationAndGates:
    def test_moisture_computed_at_finish(self, api, farm_manager_headers):
        """PRD §3.2: "A valid finish computes the lot's `moisture_pct`: the dried
        weight minus 24 percent of the wet weight, that difference divided by the
        dried weight, expressed as a percentage, rounded half-up to one decimal
        place." Wet 1000, dried 280: (280 - 240) / 280 = 14.285... -> 14.3.

        Design: Corner/calculations/kiln_moisture_correct_result
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000)
        finished = validate_success(api.finish_drying(
            lot["id"], create_finish_drying_payload(280), farm_manager_headers), 200)
        assert finished["moisture_pct"] == 14.3
        assert finished["status"] == "MOISTURE_CHECK"

    def test_release_at_exactly_ten_percent_allowed(self, api, farm_manager_headers):
        """PRD §3.2: "Release moves a lot from `MOISTURE_CHECK` to `DRIED` and is
        permitted only when `moisture_pct` is at most 10.0 percent, otherwise
        `ERR_MOISTURE_UNSAFE`." Wet 900, dried 240: (240 - 216) / 240 = 10.0
        exactly, and the at-most gate admits it.

        Design: Corner/calculations/moisture_exactly_at_threshold_release_allowed
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_moisture_check_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                        wet_lbs=900, dried_lbs=240)
        assert lot["moisture_pct"] == 10.0
        released = validate_success(api.release_lot(lot["id"], farm_manager_headers), 200)
        assert released["status"] == "DRIED"

    def test_release_above_ten_percent_rejected(self, api, farm_manager_headers):
        """PRD §3.2: "Release moves a lot from `MOISTURE_CHECK` to `DRIED` and is
        permitted only when `moisture_pct` is at most 10.0 percent, otherwise
        `ERR_MOISTURE_UNSAFE`."

        Design: Corner/calculations/release_blocked_above_moisture_threshold
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_moisture_check_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                        wet_lbs=1000, dried_lbs=280)
        assert lot["moisture_pct"] == 14.3
        res = api.release_lot(lot["id"], farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_MOISTURE_UNSAFE)

    def test_finish_below_bone_dry_floor_rejected(self, api, farm_manager_headers):
        """PRD §3.2: "the recorded `dried_lbs` must be at least the wet weight
        times 0.24 rounded up to a whole pound, and no more than the wet weight
        itself. A weight outside that envelope is rejected with
        `ERR_WEIGHT_IMPOSSIBLE`." Dried 200 is below ceil(0.24 x 1000) = 240.

        Design: Corner/validations/finish_drying_weight_impossible
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000)
        res = api.finish_drying(lot["id"], create_finish_drying_payload(200),
                                farm_manager_headers)
        validate_error(res, ApiErrorId.ERR_WEIGHT_IMPOSSIBLE)


class TestRedryLoop:
    def test_redry_returns_lot_to_kiln(self, api, farm_manager_headers):
        """PRD §3.2: "A lot whose `moisture_pct` is above 10.0 percent is not safe
        to store and may be sent back into the kiln: redrying moves it from
        `MOISTURE_CHECK` back to `IN_KILN` under a fresh window — supplied again
        as `kiln_window_start` and `kiln_window_end` and subject to the same
        thirty-minute buffer rule — and updates the recorded window on the lot."

        Design: Difficulty/non_linear_state_machine/harvest_lot_redry_cycle
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000,
                                 window_start=WINDOW_DAY1_AM[0],
                                 window_end=WINDOW_DAY1_AM[1])
        finished = validate_success(api.finish_drying(
            lot["id"], create_finish_drying_payload(280), farm_manager_headers), 200)
        assert finished["moisture_pct"] == 14.3
        assert finished["status"] == "MOISTURE_CHECK"
        redried = validate_success(api.redry(
            lot["id"],
            create_redry_payload(WINDOW_DAY1_PM[0], WINDOW_DAY1_PM[1]),
            farm_manager_headers), 200)
        assert redried["status"] == "IN_KILN"
        assert _instant(redried["kiln_window_start"]) == _instant(WINDOW_DAY1_PM[0])

    def test_second_finish_recomputes_moisture_then_release(self, api, farm_manager_headers):
        """PRD §3.2: "The redry loop may repeat, and each pass through
        finish-drying recomputes `moisture_pct`." Wet 1000: first finish at 280
        reads 14.3 (sent back), second finish at 263 reads (263 - 240) / 263 =
        8.7, and 8.7 is at most 10.0 so release moves the lot to `DRIED`.

        Design: Difficulty/non_linear_state_machine/harvest_lot_redry_cycle
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot = create_in_kiln_lot(ctx["plan"]["id"], ctx["kiln"]["id"], wet_lbs=1000,
                                 window_start=WINDOW_DAY1_AM[0],
                                 window_end=WINDOW_DAY1_AM[1])
        validate_success(api.finish_drying(
            lot["id"], create_finish_drying_payload(280), farm_manager_headers), 200)
        validate_success(api.redry(
            lot["id"], create_redry_payload(WINDOW_DAY1_PM[0], WINDOW_DAY1_PM[1]),
            farm_manager_headers), 200)
        refinish = validate_success(api.finish_drying(
            lot["id"], create_finish_drying_payload(263), farm_manager_headers), 200)
        assert refinish["moisture_pct"] == 8.7
        assert refinish["status"] == "MOISTURE_CHECK"
        released = validate_success(api.release_lot(lot["id"], farm_manager_headers), 200)
        assert released["status"] == "DRIED"


class TestReleaseFreesWindow:
    def test_identical_window_accepted_after_release(self, api, farm_manager_headers):
        """PRD §3.2: "A released lot stops occupying its kiln: its window no
        longer participates in the buffer rule."

        Design: Corner/state_machines/kiln_release_frees_window
        """
        ctx = setup_harvesting_plan_with_kiln()
        lot_a = create_moisture_check_lot(ctx["plan"]["id"], ctx["kiln"]["id"],
                                          wet_lbs=1000, dried_lbs=263,
                                          window_start="2026-08-20T08:00:00Z",
                                          window_end="2026-08-20T12:00:00Z")
        validate_success(api.release_lot(lot_a["id"], farm_manager_headers), 200)
        lot_b = create_harvested_lot(ctx["plan"]["id"], wet_lbs=1000)
        loaded = validate_success(api.load_kiln(
            lot_b["id"],
            create_load_kiln_payload(ctx["kiln"]["id"], "2026-08-20T08:00:00Z",
                                     "2026-08-20T12:00:00Z"),
            farm_manager_headers), 200)
        assert loaded["status"] == "IN_KILN"
