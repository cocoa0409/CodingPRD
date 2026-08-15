"""Pour-slot booking semantics (half-open + buffer), furnace maintenance windows
(closed), slot completion gates, mold creation guards, posture gating, and
daily line capacity."""
import pytest

from test_helpers import (
    TEST_USERS,
    book_slot,
    complete_slot,
    cool_and_shakeout,
    create_active_pattern,
    create_certified_heat,
    create_customer,
    create_foundry,
    create_furnace,
    create_mold,
    create_order,
    create_pattern_payload,
    create_sand_batch_in_service,
    get_foundry,
    get_heat,
    get_mold,
    get_pour_slot,
    get_sand_batch,
    list_castings,
    pour_molds,
    set_clock,
    setup_shop,
    tap,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["foundry_admin_headers"]
PM = TEST_USERS["pattern_maker_headers"]
MELT = TEST_USERS["melt_supervisor_headers"]
LINE = TEST_USERS["line_operator_headers"]
QI = TEST_USERS["qi_1_headers"]


class TestPourSlotBufferSemantics:
    def _three_molds_booked(self, api):
        """Line (buffer 30), CERTIFIED+TAPPED heat, three ASSEMBLED molds, and
        slot1 BOOKED [10:00, 11:00)."""
        ctx = setup_shop(order_quantity=3)
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        heat = tap(heat, 1000)
        molds = [create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                             ctx["order"]["id"], sand_weight_kg=50,
                             metal_weight_kg=200, cooling_hours=2)
                 for _ in range(3)]
        slot1 = book_slot(ctx["line"]["id"], heat["id"], [molds[0]["id"]],
                          "2026-08-10T10:00:00Z", "2026-08-10T11:00:00Z")
        return ctx, heat, molds, slot1

    def test_slot_at_previous_end_conflicts_within_buffer(self, api):
        """PRD §3.5: "overlap with an existing `BOOKED` or `COMPLETED` slot on
        the same line is judged with the line's cleanup buffer appended after
        each slot — the new slot conflicts unless its `start_at` is at or after
        the existing slot's `end_at` plus `cleanup_buffer_minutes`, or its own
        `end_at` plus the buffer is at or before the existing slot's `start_at`,
        with equality at the buffer boundary permitted — and a conflict is
        `ERR_SLOT_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/pour_slot_half_open_buffer_semantics
        """
        ctx, heat, molds, slot1 = self._three_molds_booked(api)
        # 11:00 == slot1 end, but the 30-minute buffer has not elapsed.
        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [molds[1]["id"]],
             "start_at": "2026-08-10T11:00:00Z", "end_at": "2026-08-10T12:00:00Z"},
            LINE)
        validate_error(res, "ERR_SLOT_WINDOW_CONFLICT", expected_status=409)

    def test_slot_at_end_plus_buffer_allowed(self, api):
        """PRD §3.5: "overlap with an existing `BOOKED` or `COMPLETED` slot on
        the same line is judged with the line's cleanup buffer appended after
        each slot — the new slot conflicts unless its `start_at` is at or after
        the existing slot's `end_at` plus `cleanup_buffer_minutes`, or its own
        `end_at` plus the buffer is at or before the existing slot's `start_at`,
        with equality at the buffer boundary permitted — and a conflict is
        `ERR_SLOT_WINDOW_CONFLICT`"

        Design: Difficulty/resource_temporal_overlap/pour_slot_half_open_buffer_semantics
        """
        ctx, heat, molds, slot1 = self._three_molds_booked(api)
        # 11:30 == 11:00 + 30 min: buffer-boundary equality is permitted.
        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [molds[2]["id"]],
             "start_at": "2026-08-10T11:30:00Z", "end_at": "2026-08-10T12:30:00Z"},
            LINE)
        slot3 = validate_success(res, expected_status=201)
        assert slot3["status"] == "BOOKED"
        assert get_pour_slot(slot3["id"])["status"] == "BOOKED"


class TestFurnaceWindowClosedInterval:
    def test_touching_window_conflicts(self, api):
        """PRD §3.1: "the window is a closed interval, so a new window conflicts
        with an existing one whenever the new start falls at or before the
        existing end and the existing start falls at or before the new end —
        windows that merely touch at an endpoint do conflict, and the attempt is
        rejected with `ERR_FURNACE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_closed_interval_touch_conflicts
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        validate_success(api.add_equipment_window(
            furnace["id"],
            {"start_iso": "2026-08-20T10:00:00Z", "end_iso": "2026-08-20T11:00:00Z"},
            ADMIN), expected_status=201)
        # Closed interval: touching endpoint 11:00 overlaps.
        res = api.add_equipment_window(
            furnace["id"],
            {"start_iso": "2026-08-20T11:00:00Z", "end_iso": "2026-08-20T12:00:00Z"},
            ADMIN)
        validate_error(res, "ERR_FURNACE_WINDOW_CONFLICT", expected_status=409)

    def test_one_second_past_window_end_allowed(self, api):
        """PRD §3.1: "the window is a closed interval, so a new window conflicts
        with an existing one whenever the new start falls at or before the
        existing end and the existing start falls at or before the new end" and
        "Validated windows are appended to `maintenance_windows`."

        Design: Difficulty/resource_temporal_overlap/furnace_window_closed_interval_touch_conflicts
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        furnace = create_furnace(foundry["id"])
        validate_success(api.add_equipment_window(
            furnace["id"],
            {"start_iso": "2026-08-20T10:00:00Z", "end_iso": "2026-08-20T11:00:00Z"},
            ADMIN), expected_status=201)
        # One second past the closed end does not overlap.
        res = api.add_equipment_window(
            furnace["id"],
            {"start_iso": "2026-08-20T11:00:01Z", "end_iso": "2026-08-20T12:00:00Z"},
            ADMIN)
        validate_success(res, expected_status=201)
        equip = validate_success(api.get_equipment(furnace["id"], ADMIN))
        assert len(equip["maintenance_windows"]) == 2


class TestSlotCompleteHeatGate:
    def _certified_untapped_scenario(self, api):
        """Heat CERTIFIED (never tapped); mold ASSEMBLED; slot BOOKED
        [10:00,11:00); clock inside the window at 10:30."""
        ctx = setup_shop()
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold["id"]])
        set_clock("2026-08-10T10:30:00Z")
        return ctx, heat, mold, slot

    def test_slot_complete_requires_heat_tapped_rejected(self, api):
        """PRD §3.5: "Five preconditions guard it: the heat must be `TAPPED`
        (`ERR_HEAT_NOT_TAPPED`); the logical now must lie within the half-open
        window from `start_at` to `end_at` (`ERR_SLOT_NOT_IN_WINDOW`); every
        mold on the slot must still be `ASSEMBLED` (`ERR_INVALID_STATE`); every
        mold's sand batch must be `IN_SERVICE` (`ERR_SAND_BATCH_INACTIVE`); and
        the heat's `remaining_metal_kg` must be at least the sum of the slot
        molds' `metal_weight_kg` (`ERR_METAL_INSUFFICIENT`)."

        Design: Difficulty/cross_entity_state_dependency/slot_complete_requires_heat_tapped
        """
        ctx, heat, mold, slot = self._certified_untapped_scenario(api)
        res = api.complete_pour_slot(slot["id"], LINE)
        validate_error(res, "ERR_HEAT_NOT_TAPPED", expected_status=409)
        assert get_pour_slot(slot["id"])["status"] == "BOOKED"
        assert get_mold(mold["id"])["status"] == "ASSEMBLED"

    def test_slot_complete_succeeds_after_tap(self, api):
        """PRD §3.5: "On success the slot becomes `COMPLETED`; each mold
        transitions `ASSEMBLED → POURED` with `poured_at` stamped to the logical
        now; the heat's `remaining_metal_kg` is debited by the summed mold
        metal; and the casting population is born — for each mold, exactly its
        pattern's `impressions` castings are created, each carrying the
        `mold_id`, the `order_id` copied from the mold, and a 1-based
        `cavity_index`, starting life at routing `SHAKEOUT` with quality
        `PENDING`."

        Design: Difficulty/cross_entity_state_dependency/slot_complete_requires_heat_tapped
        """
        ctx, heat, mold, slot = self._certified_untapped_scenario(api)
        # First attempt fails while CERTIFIED.
        validate_error(api.complete_pour_slot(slot["id"], LINE),
                       "ERR_HEAT_NOT_TAPPED", expected_status=409)
        tap(heat, 1000)
        completed = complete_slot(slot["id"])
        assert completed["status"] == "COMPLETED"
        assert get_mold(mold["id"])["status"] == "POURED"
        castings = list_castings({"mold_id": mold["id"]})
        assert len(castings) == 1
        assert castings[0]["routing_status"] == "SHAKEOUT"
        assert castings[0]["quality_status"] == "PENDING"
        assert castings[0]["cavity_index"] == 1


class TestSlotCompleteSafetyBeatsTemporal:
    def _setup_both_violations(self, api):
        """Heat CERTIFIED-but-not-TAPPED and the clock outside the slot window."""
        ctx = setup_shop()
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold["id"]])
        set_clock("2026-08-10T12:00:00Z")  # outside [10:00, 11:00)
        return ctx, heat, mold, slot

    def test_safety_error_surfaces_over_temporal(self, api):
        """PRD §2.10: "Fifth, metallurgical and quality safety gates:
        certification before tap, tapped metal before pour completion,
        segregation of duties, and sand-batch readiness at the pour
        (`ERR_HEAT_NOT_CERTIFIED`, `ERR_HEAT_NOT_TAPPED`,
        `ERR_SEGREGATION_OF_DUTIES`, `ERR_SAND_BATCH_INACTIVE`)."
        PRD §2.10: "Eighth, temporal rules against the logical clock
        (`ERR_SLOT_IN_PAST`, `ERR_SLOT_NOT_IN_WINDOW`,
        `ERR_CLAIM_WINDOW_EXPIRED`)."

        Design: Difficulty/priority_pair_validation_conflict/slot_complete_safety_beats_temporal
        """
        ctx, heat, mold, slot = self._setup_both_violations(api)
        res = api.complete_pour_slot(slot["id"], LINE)
        validate_error(res, "ERR_HEAT_NOT_TAPPED", expected_status=409)

    def test_rejected_completion_leaves_no_side_effects(self, api):
        """PRD §2.10: "When several checks could reject the same request, the
        server evaluates them in a fixed priority order and surfaces the first
        failure."

        Design: Difficulty/priority_pair_validation_conflict/slot_complete_safety_beats_temporal
        """
        ctx, heat, mold, slot = self._setup_both_violations(api)
        validate_error(api.complete_pour_slot(slot["id"], LINE),
                       "ERR_HEAT_NOT_TAPPED", expected_status=409)
        assert get_pour_slot(slot["id"])["status"] == "BOOKED"
        assert get_mold(mold["id"])["status"] == "ASSEMBLED"


class TestMoldCreationGuards:
    def test_metal_insufficient_on_slot_complete(self, api):
        """PRD §3.5: "and the heat's `remaining_metal_kg` must be at least the
        sum of the slot molds' `metal_weight_kg` (`ERR_METAL_INSUFFICIENT`)."

        Design: Corner/errors/metal_insufficient_on_slot_complete
        """
        ctx = setup_shop()
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        heat = tap(heat, 300)
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=400, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold["id"]])
        set_clock("2026-08-10T10:30:00Z")
        res = api.complete_pour_slot(slot["id"], LINE)
        validate_error(res, "ERR_METAL_INSUFFICIENT", expected_status=422)
        assert get_pour_slot(slot["id"])["status"] == "BOOKED"
        assert get_mold(mold["id"])["status"] == "ASSEMBLED"
        assert get_heat(heat["id"])["remaining_metal_kg"] == pytest.approx(
            300, abs=1e-9)

    def test_sand_insufficient_on_mold_create(self, api):
        """PRD §3.5: "an `IN_SERVICE` `sand_batch_id` whose `current_weight_kg`
        covers the requested `sand_weight_kg` (shortfall is
        `ERR_SAND_INSUFFICIENT`)"

        Design: Corner/errors/sand_insufficient_on_mold_create
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        customer = create_customer(foundry["id"])
        batch = create_sand_batch_in_service(foundry["id"], virgin_weight_kg=100)
        pattern = create_active_pattern(foundry["id"], dimensions=[100.0])
        order = create_order(foundry["id"], customer["id"], pattern["id"])
        res = api.create_mold(
            {"pattern_id": pattern["id"], "sand_batch_id": batch["id"],
             "order_id": order["id"], "sand_weight_kg": 150,
             "metal_weight_kg": 200, "cooling_hours": 2},
            LINE)
        validate_error(res, "ERR_SAND_INSUFFICIENT", expected_status=422)
        assert get_sand_batch(batch["id"])["current_weight_kg"] == pytest.approx(
            100.0, abs=1e-9)

    def test_mold_create_with_draft_pattern_rejected(self, api):
        """PRD §3.5: "A `LineOperator` assembles a mold by naming an `ACTIVE`
        `pattern_id` (anything else is `ERR_PATTERN_NOT_ACTIVE`)"

        Design: Corner/errors/mold_create_with_draft_pattern_rejected
        """
        set_clock("2026-08-10T08:00:00Z")
        foundry = create_foundry()
        customer = create_customer(foundry["id"])
        batch = create_sand_batch_in_service(foundry["id"])
        pattern = validate_success(api.create_pattern(
            create_pattern_payload(foundry["id"]), PM), expected_status=201)
        assert pattern["status"] == "DRAFT"
        order = create_order(foundry["id"], customer["id"], pattern["id"])
        res = api.create_mold(
            {"pattern_id": pattern["id"], "sand_batch_id": batch["id"],
             "order_id": order["id"], "sand_weight_kg": 50,
             "metal_weight_kg": 200, "cooling_hours": 2},
            LINE)
        validate_error(res, "ERR_PATTERN_NOT_ACTIVE", expected_status=409)

    def test_mold_shakeout_before_cooling_rejected(self, api):
        """PRD §3.6: "a `LineOperator` shakes out a `COOLED` mold, moving its
        `sand_weight_kg` in the batch ledger from `committed_weight_kg` to
        `spent_weight_kg`" — the mold state machine offers no shakeout from
        `ASSEMBLED`, so the generic state error applies per PRD §2.10: "Fourth,
        state feasibility: the target resource must be in a state from which the
        requested transition exists, with terminal resources rejected as
        `ERR_ALREADY_TERMINAL` and other mismatches as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/mold_shakeout_before_cooling_rejected
        """
        ctx = setup_shop()
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        res = api.shakeout_mold(mold["id"], LINE)
        validate_error(res, "ERR_INVALID_STATE", expected_status=409)
        assert get_mold(mold["id"])["status"] == "ASSEMBLED"
        assert get_sand_batch(ctx["batch"]["id"])["committed_weight_kg"] == pytest.approx(
            50.0, abs=1e-9)


class TestSlotCompleteSandGate:
    def test_slot_complete_with_reclaiming_batch_rejected(self, api):
        """PRD §3.5: "every mold's sand batch must be `IN_SERVICE`
        (`ERR_SAND_BATCH_INACTIVE`)"

        Design: Corner/errors/slot_complete_with_reclaiming_batch_rejected
        """
        ctx = setup_shop(order_quantity=2)
        # mold1 pours and shakes out so the batch holds spent sand.
        pour_molds(ctx, [{"sand_weight_kg": 120, "metal_weight_kg": 200,
                          "cooling_hours": 2}], tap_weight_kg=500)
        cool_and_shakeout(ctx)
        mold2 = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                            ctx["order"]["id"], sand_weight_kg=50,
                            metal_weight_kg=200, cooling_hours=2)
        # A second, still-TAPPED heat keeps the pour-completion safety gate
        # satisfied so only the sand-batch gate can fail.
        heat2 = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        tap(heat2, 500)
        slot2 = book_slot(ctx["line"]["id"], heat2["id"], [mold2["id"]],
                          "2026-08-10T14:00:00Z", "2026-08-10T15:00:00Z")
        # Reclaiming the spent sand moves the batch IN_SERVICE -> RECLAIMING.
        validate_success(api.reclaim_sand_batch(
            ctx["batch"]["id"],
            {"reclaimed_weight_kg": 110.0, "loss_weight_kg": 10.0}, LINE))
        assert get_sand_batch(ctx["batch"]["id"])["status"] == "RECLAIMING"

        set_clock("2026-08-10T14:30:00Z")  # inside slot2's window
        res = api.complete_pour_slot(slot2["id"], LINE)
        validate_error(res, "ERR_SAND_BATCH_INACTIVE", expected_status=409)


class TestSlotBookingTemporalAndCapacity:
    def test_slot_complete_outside_window_rejected(self, api):
        """PRD §3.5: "the logical now must lie within the half-open window from
        `start_at` to `end_at` (`ERR_SLOT_NOT_IN_WINDOW`)"

        Design: Corner/errors/slot_complete_outside_window_rejected
        """
        ctx = setup_shop()
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        tap(heat, 500)
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        slot = book_slot(ctx["line"]["id"], heat["id"], [mold["id"]])
        set_clock("2026-08-10T09:30:00Z")  # before start 10:00
        res = api.complete_pour_slot(slot["id"], LINE)
        validate_error(res, "ERR_SLOT_NOT_IN_WINDOW", expected_status=409)

    def test_slot_in_past_rejected(self, api):
        """PRD §3.5: "a `start_at` before the logical now is
        `ERR_SLOT_IN_PAST`"

        Design: Corner/validations/slot_in_past_rejected
        """
        ctx = setup_shop(clock="2026-08-10T09:00:00Z")
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=50,
                           metal_weight_kg=200, cooling_hours=2)
        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [mold["id"]],
             "start_at": "2026-08-10T08:00:00Z", "end_at": "2026-08-10T09:30:00Z"},
            LINE)
        validate_error(res, "ERR_SLOT_IN_PAST", expected_status=409)

    def test_line_minutes_equality_then_exceeded(self, api):
        """PRD §3.5: "the sum of whole-minute durations (each the difference
        between `end_at` and `start_at`) over the line's `BOOKED` and
        `COMPLETED` slots on the same UTC date, plus the new duration, must not
        exceed `daily_minute_capacity`, with equality allowed and overflow
        `ERR_LINE_MINUTES_EXCEEDED`."

        Design: Corner/validations/line_minutes_equality_then_exceeded
        """
        ctx = setup_shop(clock="2026-08-10T06:00:00Z", order_quantity=4,
                         line_minute_capacity=240, line_buffer=0)
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        molds = [create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                             ctx["order"]["id"], sand_weight_kg=40,
                             metal_weight_kg=100, cooling_hours=2)
                 for _ in range(4)]
        # Two 120-minute slots fill the day to exactly 240 == capacity.
        book_slot(ctx["line"]["id"], heat["id"], [molds[0]["id"]],
                  "2026-08-10T08:00:00Z", "2026-08-10T10:00:00Z")
        book_slot(ctx["line"]["id"], heat["id"], [molds[1]["id"]],
                  "2026-08-10T10:00:00Z", "2026-08-10T12:00:00Z")
        # One more same-date minute overflows (241 > 240).
        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [molds[2]["id"]],
             "start_at": "2026-08-10T12:00:00Z", "end_at": "2026-08-10T12:01:00Z"},
            LINE)
        validate_error(res, "ERR_LINE_MINUTES_EXCEEDED", expected_status=422)
        # The daily tally resets per UTC date.
        next_day = validate_success(api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [molds[3]["id"]],
             "start_at": "2026-08-11T08:00:00Z", "end_at": "2026-08-11T09:00:00Z"},
            LINE), expected_status=201)
        assert next_day["status"] == "BOOKED"


class TestPostureGating:
    def test_curtailed_posture_blocks_slot_but_not_mold(self, api):
        """PRD §2.9: "Posture gates pour-slot booking only — mold creation is
        governed by the per-batch sand sufficiency check, not by posture.
        Booking a slot while the foundry is `EMBARGO` is rejected with
        `ERR_FOUNDRY_EMBARGO` (HTTP 409); booking while `CURTAILED` is rejected
        with `ERR_FOUNDRY_CURTAILED` (HTTP 409)."

        Design: Corner/validations/curtailed_posture_blocks_slot_but_not_mold
        """
        ctx = setup_shop(sand_virgin_kg=600, order_quantity=5)
        create_mold(ctx["pattern"]["id"], ctx["batch"]["id"], ctx["order"]["id"],
                    sand_weight_kg=250, metal_weight_kg=200, cooling_hours=2)
        # sand_available 600 - 250 = 350 -> 0 < 350 <= 500 -> CURTAILED
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        # Mold creation is governed by per-batch sufficiency, not posture.
        m2 = validate_success(api.create_mold(
            {"pattern_id": ctx["pattern"]["id"],
             "sand_batch_id": ctx["batch"]["id"], "order_id": ctx["order"]["id"],
             "sand_weight_kg": 50, "metal_weight_kg": 200, "cooling_hours": 2},
            LINE), expected_status=201)
        assert m2["status"] == "ASSEMBLED"

        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [m2["id"]],
             "start_at": "2026-08-10T10:00:00Z", "end_at": "2026-08-10T11:00:00Z"},
            LINE)
        validate_error(res, "ERR_FOUNDRY_CURTAILED", expected_status=409)

    def test_embargo_posture_blocks_slot_booking(self, api):
        """PRD §2.9: "When `sand_available_kg` is exactly zero the posture is
        `EMBARGO`" and "Booking a slot while the foundry is `EMBARGO` is
        rejected with `ERR_FOUNDRY_EMBARGO` (HTTP 409)".

        Design: Corner/validations/embargo_posture_blocks_slot_booking
        """
        ctx = setup_shop(sand_virgin_kg=300)
        mold = create_mold(ctx["pattern"]["id"], ctx["batch"]["id"],
                           ctx["order"]["id"], sand_weight_kg=300,
                           metal_weight_kg=200, cooling_hours=2)
        # sand_available 300 - 300 = 0 -> EMBARGO
        assert get_foundry(ctx["foundry"]["id"])["posture"] == "EMBARGO"
        heat = create_certified_heat(ctx["foundry"]["id"], ctx["furnace"]["id"])
        res = api.create_pour_slot(
            {"molding_line_id": ctx["line"]["id"], "heat_id": heat["id"],
             "mold_ids": [mold["id"]],
             "start_at": "2026-08-10T10:00:00Z", "end_at": "2026-08-10T11:00:00Z"},
            LINE)
        validate_error(res, "ERR_FOUNDRY_EMBARGO", expected_status=409)


class TestCrossFoundryScoping:
    def test_cross_foundry_reference_resolves_not_found(self, api):
        """PRD §2.11: "a reference that crosses foundry boundaries resolves as
        not found and is rejected with `ERR_NOT_FOUND` (HTTP 404),
        indistinguishable from a reference to a nonexistent resource."

        Design: Corner/validations/cross_foundry_reference_resolves_not_found
        """
        foundry_a = create_foundry(name="FA")
        foundry_b = create_foundry(name="FB")
        customer_b = create_customer(foundry_b["id"], company_name="AcmeB")
        batch_a = create_sand_batch_in_service(foundry_a["id"])
        pattern_a = create_active_pattern(foundry_a["id"], part_number="PN-A",
                                          dimensions=[100.0])
        pattern_b = create_active_pattern(foundry_b["id"], part_number="PN-B",
                                          dimensions=[100.0])
        order_b = create_order(foundry_b["id"], customer_b["id"], pattern_b["id"])
        # Pattern and batch belong to foundry A; the order belongs to foundry B.
        res = api.create_mold(
            {"pattern_id": pattern_a["id"], "sand_batch_id": batch_a["id"],
             "order_id": order_b["id"], "sand_weight_kg": 50,
             "metal_weight_kg": 200, "cooling_hours": 2},
            LINE)
        validate_error(res, "ERR_NOT_FOUND", expected_status=404)


class TestPipelineCap:
    def test_pipeline_cap_ceil_boundary(self, api):
        """PRD §3.3: "An optional `overage_pct` defaults to 0.10 and sets the
        allowed production overage: the order's pipeline cap is its `quantity`
        multiplied by one plus `overage_pct`, rounded up to a whole casting
        count." and PRD §3.5: "the order's `pipeline_count` plus the pattern's
        `impressions` must not exceed the cap of §3.3 — `quantity` multiplied by
        one plus `overage_pct`, rounded up — or creation is rejected with
        `ERR_ORDER_QUANTITY_EXCEEDED`."

        Design: Corner/calculations/pipeline_cap_ceil_boundary
        """
        ctx = setup_shop(order_quantity=3, impressions=2, overage_pct=0.10,
                         part_number="PN-2C")
        # cap = ceil(3 * 1.10) = 4; impressions 2 per mold.
        validate_success(api.create_mold(
            {"pattern_id": ctx["pattern"]["id"],
             "sand_batch_id": ctx["batch"]["id"], "order_id": ctx["order"]["id"],
             "sand_weight_kg": 50, "metal_weight_kg": 200, "cooling_hours": 2},
            LINE), expected_status=201)
        validate_success(api.create_mold(
            {"pattern_id": ctx["pattern"]["id"],
             "sand_batch_id": ctx["batch"]["id"], "order_id": ctx["order"]["id"],
             "sand_weight_kg": 50, "metal_weight_kg": 200, "cooling_hours": 2},
            LINE), expected_status=201)
        # pipeline_count now 4 == cap; a third mold would reach 6 > 4.
        res = api.create_mold(
            {"pattern_id": ctx["pattern"]["id"],
             "sand_batch_id": ctx["batch"]["id"], "order_id": ctx["order"]["id"],
             "sand_weight_kg": 50, "metal_weight_kg": 200, "cooling_hours": 2},
            LINE)
        validate_error(res, "ERR_ORDER_QUANTITY_EXCEEDED", expected_status=422)


class TestCastingWeights:
    def test_casting_weight_remainder_goes_to_last_cavity(self, api):
        """PRD §3.5: "The per-cavity base is the mold's `metal_weight_kg`
        divided by `impressions`, rounded half-up to two decimal places;
        cavities one through the second-to-last receive that base, and the last
        cavity — the highest `cavity_index`, never selected by identifier —
        receives the mold's full `metal_weight_kg` minus the base multiplied by
        the remaining cavity count, itself rounded half-up to two decimals.
        Per-mold casting weights therefore sum exactly to `metal_weight_kg`."

        Design: Corner/calculations/casting_weight_remainder_goes_to_last_cavity
        """
        ctx = setup_shop(order_quantity=3, impressions=3, part_number="PN-3C")
        pour_molds(ctx, [{"sand_weight_kg": 50, "metal_weight_kg": 100.0,
                          "cooling_hours": 2}], tap_weight_kg=500)
        castings = list_castings({"mold_id": ctx["molds"][0]["id"]})
        assert len(castings) == 3
        by_cavity = {c["cavity_index"]: c["casting_weight_kg"] for c in castings}
        assert sorted(by_cavity.keys()) == [1, 2, 3]
        # base = round(100/3, 2) = 33.33; last = 100 - 2*33.33 = 33.34
        assert by_cavity[1] == pytest.approx(33.33, abs=1e-9)
        assert by_cavity[2] == pytest.approx(33.33, abs=1e-9)
        assert by_cavity[3] == pytest.approx(33.34, abs=1e-9)
        assert sum(by_cavity.values()) == pytest.approx(100.0, abs=1e-9)
