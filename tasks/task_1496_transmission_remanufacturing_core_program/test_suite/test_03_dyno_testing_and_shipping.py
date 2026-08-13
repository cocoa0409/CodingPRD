"""Dyno scheduling, shift-quality scoring, the rework cycle, the attempt
budget, the third-fail cascade, and shipping."""
import pytest

from test_helpers import (
    ADJUSTER,  # noqa: F401
    ANY_H,
    CAL_A,
    CAL_B,
    DEFAULT_CLOCK_UTC,
    DYNO_OP,
    FAIL_PRESSURES,
    MARGINAL_PRESSURES,
    PASS_PRESSURES,
    PLANNER,
    TECH,
    ApiErrorId,
    assert_dyno_booking,
    assert_dyno_test_run,
    assert_hard_part_availability,
    book_dyno_window,
    complete_assembly,
    create_dyno_booking_payload,
    create_dyno_run_payload,
    create_full_pump_model,
    create_hard_part_record,
    create_mapping,
    create_min_model,
    create_order,
    draft_calibration,
    drive_order_to_dyno_queue,
    get_invoice_for_order,
    get_order,
    get_part,
    kit_reserve,
    record_dyno_run,
    setup_attempt_budget_order,
    setup_third_fail_cascade,
    verify_calibration,
    api_client,
    validate_error,
    validate_success,
)


class TestShipConsumption:

    def test_ship_consumes_reserved_parts(self):
        """PRD §3.5: "The ship cascade stamps `shipped_at` from the logical clock, consumes the kit reservations line by line — each reserved part's `qty_reserved` and `qty_on_hand` both decrease by the reserved quantity — and opens the core deposit invoice in a single atomic act."
        PRD §2.5: "The server maintains a logical clock whose startup default, before any call adjusts it, is exactly 2026-08-01T00:00:00Z".

        Design: Corner/state_machines/ship_consumes_reserved_parts
        """
        model = create_full_pump_model(required_qty=2)
        part = create_hard_part_record(qty_on_hand=5)
        create_mapping(part["id"], model["id"], "DIRECT")
        order = create_order(model["id"], "BUYER-1")
        kit_reserve(order["id"])
        order = complete_assembly(order["id"])
        draft_calibration(order["id"])
        order = verify_calibration(order["id"])
        book_dyno_window(order["id"], "DYNO-1")
        record_dyno_run(order["id"], PASS_PRESSURES)

        resp = api_client.ship_order(order["id"], PLANNER)
        shipped = validate_success(resp)
        assert shipped["status"] == "SHIPPED"
        assert shipped["shipped_at"].startswith("2026-08-01T00:00:00"), (
            f"shipped_at must read the logical clock startup default, "
            f"got {shipped['shipped_at']}"
        )

        after = get_part(part["id"])
        assert after["qty_on_hand"] == 3, \
            f"ship must consume 2 on-hand units (5 -> 3), got {after['qty_on_hand']}"
        assert after["qty_reserved"] == 0, \
            f"ship must consume the reservation (2 -> 0), got {after['qty_reserved']}"
        assert after["availability"] == 3, \
            "consumption shrinks both sides equally, so availability is unchanged"
        assert_hard_part_availability(after)

        invoice = get_invoice_for_order(order["id"])
        assert invoice["status"] == "OPEN", "ship must open the core deposit invoice"


class TestDynoScoringAndVerdicts:

    def test_marginal_verdict_keeps_state_and_calibration(self):
        """PRD §3.4: "`MARGINAL` leaves the order in `DYNO_QUEUE` with `cal_status` still `VERIFIED`, free to book another run while attempts remain."
        PRD §3.4: "The `verdict` bands are `PASS` for a score of at least 90.00, `MARGINAL` for at least 80.00 but below 90.00, and `FAIL` below 80.00."

        Design: Corner/state_machines/marginal_verdict_keeps_state_and_calibration
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        book_dyno_window(order["id"], "DYNO-1")

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], MARGINAL_PRESSURES), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert_dyno_test_run(run)
        assert run["shift_quality_score"] == pytest.approx(80.0, abs=0.01), \
            f"10 kPa low on one gear => penalty 20.00 => score 80.00, got {run['shift_quality_score']}"
        assert run["verdict"] == "MARGINAL"

        after = get_order(order["id"])
        assert after["status"] == "DYNO_QUEUE"
        assert after["cal_status"] == "VERIFIED", \
            "a MARGINAL verdict must not supersede the calibration"
        assert after["dyno_attempts_used"] == 1
        assert after["last_shift_quality_score"] == pytest.approx(80.0, abs=0.01)

    def test_dyno_score_per_gear_rounding_marginal(self):
        """PRD §3.4: "the per-gear penalty is the absolute difference between the measured pressure and that gear's `target_pressure_kpa`, multiplied by 2.0, with the penalty itself rounded half-up to two decimal places."
        PRD §3.4: "The rounding order is pinned: each per-gear penalty is rounded before the summation, and summing raw penalties before rounding is forbidden because it yields different cents."

        Design: Difficulty/combinatorial_formula/dyno_score_per_gear_rounding_pinned
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        book_dyno_window(order["id"], "DYNO-1")

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], [194.99, 220, 240, 260]), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["shift_quality_score"] == pytest.approx(89.98, abs=0.005), (
            f"5.01 kPa deviation => per-gear penalty rounds to 10.02 before "
            f"summation => score 89.98, got {run['shift_quality_score']}"
        )
        assert run["verdict"] == "MARGINAL", "89.98 is below the 90.00 PASS band"
        after = get_order(order["id"])
        assert after["status"] == "DYNO_QUEUE"
        assert after["dyno_attempts_used"] == 1

    def test_dyno_score_exact_pass_boundary(self):
        """PRD §3.4: "The `verdict` bands are `PASS` for a score of at least 90.00, `MARGINAL` for at least 80.00 but below 90.00, and `FAIL` below 80.00."
        PRD §3.4: "`PASS` moves the order `DYNO_QUEUE` → `DYNO_PASSED`."

        Design: Difficulty/combinatorial_formula/dyno_score_per_gear_rounding_pinned
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        book_dyno_window(order["id"], "DYNO-1")

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], [195.00, 220, 240, 260]), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["shift_quality_score"] == pytest.approx(90.0, abs=0.005), (
            f"exactly 5.00 kPa deviation => penalty 10.00 => score exactly 90.00, "
            f"got {run['shift_quality_score']}"
        )
        assert run["verdict"] == "PASS", "90.00 meets the inclusive PASS threshold"
        after = get_order(order["id"])
        assert after["status"] == "DYNO_PASSED"


class TestReworkCycle:

    def _order_in_dyno_queue_with_booking(self):
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        book_dyno_window(order["id"], "DYNO-1", "2026-08-01T00:00:00Z",
                         "2026-08-05T00:00:00Z")
        return order

    def test_fail_run_sends_order_to_rework(self):
        """PRD §3.4: "A `FAIL` with attempts remaining — the run's `attempt_number` below 3 — sends the order to `REWORK` and supersedes the calibration (`VERIFIED` → `SUPERSEDED`), forcing a fresh draft and a fresh verification; the kit reservations are kept through rework."

        Design: Difficulty/non_linear_state_machine/reman_order_rework_recycle_to_dyno_queue
        """
        order = self._order_in_dyno_queue_with_booking()
        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], FAIL_PRESSURES), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["verdict"] == "FAIL"
        assert run["shift_quality_score"] == pytest.approx(70.0, abs=0.01)
        assert run["attempt_number"] == 1

        after = get_order(order["id"])
        assert after["status"] == "REWORK"
        assert after["cal_status"] == "SUPERSEDED", \
            "a FAIL must supersede the verified calibration"
        assert after["dyno_attempts_used"] == 1
        assert after["last_shift_quality_score"] == pytest.approx(70.0, abs=0.01)

    def test_rework_recalibration_returns_to_dyno_queue(self):
        """PRD §3.3: "Valve-body calibration is drafted by a `Calibrator` and is permitted only while the order is `CALIBRATION` or `REWORK`".
        PRD §3.3: "A successful verification flips `cal_status` from `DRAFT` to `VERIFIED`, applies the TCM flash by copying `tcm_flash_version` into `tcm_flash_version_applied` — a field that stays null until the first verification — and advances the order to `DYNO_QUEUE`."

        Design: Difficulty/non_linear_state_machine/reman_order_rework_recycle_to_dyno_queue
        """
        order = self._order_in_dyno_queue_with_booking()
        assert order["cal_generation"] == 1
        record_dyno_run(order["id"], FAIL_PRESSURES)  # -> REWORK, cal SUPERSEDED

        resp = api_client.put_calibration(
            order["id"],
            {"solenoid_trims": [0.2, -0.1, 0.2, 0.1],
             "tcm_flash_version": "TF-2026.08b"},
            CAL_A,
        )
        redrafted = validate_success(resp)
        assert redrafted["cal_status"] == "DRAFT"
        assert redrafted["cal_generation"] == 2, \
            "each draft write increments cal_generation by 1"

        resp = api_client.verify_calibration(order["id"], CAL_B)
        verified = validate_success(resp)
        assert verified["status"] == "DYNO_QUEUE"
        assert verified["cal_status"] == "VERIFIED"
        assert verified["tcm_flash_version_applied"] == "TF-2026.08b", \
            "verify applies the current draft's TCM flash version"
        assert verified["dyno_attempts_used"] == 1


class TestAttemptBudget:

    def test_third_run_marginal_allowed(self):
        """PRD §3.4: "The order's `dyno_attempts_used` must still be below the budget of 3 attempts, otherwise `ERR_DYNO_ATTEMPT_EXHAUSTED`."
        PRD §3.4: "`MARGINAL` leaves the order in `DYNO_QUEUE` with `cal_status` still `VERIFIED`, free to book another run while attempts remain."

        Design: Difficulty/boundary_precision_check/dyno_attempt_budget_third_run_allowed_fourth_rejected
        """
        order = setup_attempt_budget_order()  # 2 FAIL runs consumed, back in DYNO_QUEUE
        assert order["dyno_attempts_used"] == 2

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], MARGINAL_PRESSURES), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["attempt_number"] == 3, "the third run is allowed while attempts remain"
        assert run["shift_quality_score"] == pytest.approx(80.0, abs=0.01)
        assert run["verdict"] == "MARGINAL"

        after = get_order(order["id"])
        assert after["dyno_attempts_used"] == 3
        assert after["status"] == "DYNO_QUEUE"
        assert after["cal_status"] == "VERIFIED"

    def test_fourth_run_rejected_budget_exhausted(self):
        """PRD §3.4: "The order's `dyno_attempts_used` must still be below the budget of 3 attempts, otherwise `ERR_DYNO_ATTEMPT_EXHAUSTED`."

        Design: Difficulty/boundary_precision_check/dyno_attempt_budget_third_run_allowed_fourth_rejected
        """
        order = setup_attempt_budget_order()
        record_dyno_run(order["id"], MARGINAL_PRESSURES)  # attempt 3, stays DYNO_QUEUE

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], PASS_PRESSURES), DYNO_OP)
        validate_error(resp, ApiErrorId.ERR_DYNO_ATTEMPT_EXHAUSTED)

        after = get_order(order["id"])
        assert after["dyno_attempts_used"] == 3, \
            "the rejected fourth run must not consume an attempt"
        assert after["status"] == "DYNO_QUEUE"


class TestCoveringBookingGate:

    def test_run_without_covering_booking_rejected(self):
        """PRD §3.4: "a `BOOKED` booking for the order must cover the current logical time — its `start_utc` at or before now and its `end_utc` after now — otherwise `ERR_NO_ACTIVE_DYNO_BOOKING`."

        Design: Difficulty/cross_entity_state_dependency/dyno_run_requires_covering_booking
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], PASS_PRESSURES), DYNO_OP)
        validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_DYNO_BOOKING)
        after = get_order(order["id"])
        assert after["dyno_attempts_used"] == 0, \
            "a run rejected for missing coverage must not consume an attempt"
        assert after["status"] == "DYNO_QUEUE"

    def test_run_with_covering_booking_succeeds(self):
        """PRD §3.4: "On acceptance the server resolves the covering booking into `dyno_booking_id`, sets `attempt_number` to the count of prior runs for the order plus one, increments `dyno_attempts_used` by 1, and stores the run's score in `last_shift_quality_score`, which stays null before the first run."
        PRD §3.4: "`PASS` moves the order `DYNO_QUEUE` → `DYNO_PASSED`."

        Design: Difficulty/cross_entity_state_dependency/dyno_run_requires_covering_booking
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        booking = book_dyno_window(order["id"], "DYNO-1")
        assert_dyno_booking(booking)

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(order["id"], PASS_PRESSURES), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["verdict"] == "PASS"
        assert run["dyno_booking_id"] == booking["id"], \
            "the run must reference the covering booking resolved by the server"
        assert run["attempt_number"] == 1

        after = get_order(order["id"])
        assert after["status"] == "DYNO_PASSED"
        assert after["dyno_attempts_used"] == 1


class TestDynoCellHalfOpenOverlap:

    def _order_in_dyno_queue(self):
        model = create_min_model()
        return drive_order_to_dyno_queue(model["id"])

    def test_adjacent_dyno_window_allowed(self):
        """PRD §3.4: "A window occupies the half-open interval that includes `start_utc` and excludes `end_utc`, so back-to-back windows on the same cell are permitted, but any true overlap with an existing window on the same cell is rejected with `ERR_DYNO_CELL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dyno_cell_half_open_adjacency
        """
        order = self._order_in_dyno_queue()
        first = book_dyno_window(order["id"], "DYNO-7",
                                 "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")
        assert first["status"] == "BOOKED"

        resp = api_client.create_dyno_booking(
            create_dyno_booking_payload(order["id"], "DYNO-7",
                                        "2026-08-01T11:00:00Z",
                                        "2026-08-01T12:00:00Z"),
            TECH,
        )
        adjacent = validate_success(resp, expected_status=201)
        assert adjacent["status"] == "BOOKED", \
            "a window starting exactly when the prior one ends is adjacent, not overlapping"

    def test_overlapping_dyno_window_rejected(self):
        """PRD §3.4: "any true overlap with an existing window on the same cell is rejected with `ERR_DYNO_CELL_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/dyno_cell_half_open_adjacency
        """
        order = self._order_in_dyno_queue()
        book_dyno_window(order["id"], "DYNO-7",
                         "2026-08-01T10:00:00Z", "2026-08-01T11:00:00Z")

        resp = api_client.create_dyno_booking(
            create_dyno_booking_payload(order["id"], "DYNO-7",
                                        "2026-08-01T10:30:00Z",
                                        "2026-08-01T11:30:00Z"),
            TECH,
        )
        validate_error(resp, ApiErrorId.ERR_DYNO_CELL_OVERLAP)


class TestThirdFailCascade:

    def test_third_fail_terminal_effects_on_order(self):
        """PRD §3.4: "A `FAIL` on the third attempt — `attempt_number` exactly 3 — is terminal for the build: the order moves to `ENGINEERING_REVIEW`, the verified calibration is likewise superseded, every reserved line is released back with `qty_reserved` decremented per line and `reserved_parts` emptied, and the resulting availability increase fires the promotion scan".

        Design: Difficulty/transitive_cascade/dyno_final_fail_release_restock_promotion_chain
        """
        ctx = setup_third_fail_cascade()
        o1, p1 = ctx["o1"], ctx["p1"]

        resp = api_client.create_dyno_test_run(
            create_dyno_run_payload(o1["id"], FAIL_PRESSURES), DYNO_OP)
        run = validate_success(resp, expected_status=201)
        assert run["attempt_number"] == 3
        assert run["verdict"] == "FAIL"
        assert run["shift_quality_score"] == pytest.approx(70.0, abs=0.01)

        after = get_order(o1["id"])
        assert after["status"] == "ENGINEERING_REVIEW"
        assert after["cal_status"] == "SUPERSEDED"
        assert after["reserved_parts"] == [], \
            "the terminal FAIL must release every reserved line"
        assert after["dyno_attempts_used"] == 3

    def test_third_fail_promotes_waiting_order(self):
        """PRD §3.4: "the resulting availability increase fires the promotion scan, so the oldest resolvable `PART_HOLD` orders auto-promote to `ASSEMBLY` with fresh reservations."
        PRD §2.9: "After any availability-increasing event — a positive stock adjustment, a reservation release (from a cancellation or a third dyno failure), or a salvage restock — the promotion scan walks all `PART_HOLD` orders in `created_at` ascending order".

        Design: Difficulty/transitive_cascade/dyno_final_fail_release_restock_promotion_chain
        """
        ctx = setup_third_fail_cascade()
        o1, o2, p1 = ctx["o1"], ctx["o2"], ctx["p1"]
        record_dyno_run(o1["id"], FAIL_PRESSURES)  # third FAIL -> cascade

        promoted = get_order(o2["id"])
        assert promoted["status"] == "ASSEMBLY", \
            f"the waiting order must auto-promote, got {promoted['status']}"
        assert promoted["shortage_parts"] == []
        assert len(promoted["reserved_parts"]) == 1
        line = promoted["reserved_parts"][0]
        assert line["hard_part_id"] == p1["id"]
        assert line["qty"] == 2
        assert line["tier"] == "DIRECT"
        assert promoted["surcharge_labor_minutes"] == 0

        part = get_part(p1["id"])
        assert part["qty_on_hand"] == 3, \
            "release returns reservations; nothing was consumed"
        assert part["qty_reserved"] == 2, \
            "the promoted order re-reserves 2 units in the same cascade"
        assert_hard_part_availability(part)


class TestBookingValidationGates:

    def test_booking_state_gate_beats_past_window(self):
        """PRD §2.8: "Every request is evaluated against a fixed pipeline of check families, in the order below, and the first failing family determines the error returned" — state gates (family 6) precede temporal guards (family 8).
        PRD §3.4: "A `RemanTechnician` books a cell window for an order that must already sit in `DYNO_QUEUE` (`ERR_ORDER_NOT_IN_DYNO_QUEUE`)".

        Design: Corner/validations/booking_state_beats_past_window
        """
        model = create_min_model()
        order = create_order(model["id"], "BUYER-1")
        kit_reserve(order["id"])
        order = complete_assembly(order["id"])  # CALIBRATION, not DYNO_QUEUE
        resp = api_client.create_dyno_booking(
            create_dyno_booking_payload(order["id"], "DYNO-1",
                                        "2026-07-01T10:00:00Z",
                                        "2026-07-01T11:00:00Z"),
            TECH,
        )
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_IN_DYNO_QUEUE)

    def test_booking_in_past_rejected(self):
        """PRD §3.4: "The end must be strictly after the start and strictly after the current logical time, failing with `ERR_INVALID_REQUEST` and `ERR_BOOKING_IN_PAST` respectively."

        Design: Corner/errors/booking_in_past_rejected
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        resp = api_client.create_dyno_booking(
            create_dyno_booking_payload(order["id"], "DYNO-1",
                                        "2026-07-01T10:00:00Z",
                                        "2026-07-01T11:00:00Z"),
            TECH,
        )
        validate_error(resp, ApiErrorId.ERR_BOOKING_IN_PAST)

    def test_ship_from_dyno_queue_rejected(self):
        """PRD §3.5: "only a `RemanPlanner` may do it, only from `DYNO_PASSED` (`ERR_ORDER_NOT_SHIPPABLE`)."

        Design: Corner/errors/ship_from_dyno_queue_rejected
        """
        model = create_min_model()
        order = drive_order_to_dyno_queue(model["id"])
        book_dyno_window(order["id"], "DYNO-1")
        resp = api_client.ship_order(order["id"], PLANNER)
        validate_error(resp, ApiErrorId.ERR_ORDER_NOT_SHIPPABLE)

        after = get_order(order["id"])
        assert after["status"] == "DYNO_QUEUE"
        lst = api_client.list_core_deposit_invoices(
            ANY_H, params={"reman_order_id": order["id"]})
        invoices = validate_success(lst)
        assert invoices == [], "a rejected ship must not open any invoice"
