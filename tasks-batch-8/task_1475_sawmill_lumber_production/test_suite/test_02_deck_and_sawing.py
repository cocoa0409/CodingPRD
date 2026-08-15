"""Log deck capacity/undeck compensation, deck degrade boundaries, and saw-line booking."""
import pytest
from test_helpers import (
    validate_success, validate_error, validate_paginated,
    api_client, ApiErrorId,
    create_log_load, scale_load, deck_load, create_decked_load, get_load,
    create_planned_run, create_completed_run, list_run_packages,
    create_kiln_charge, publish_price_list, create_contract, place_order,
    set_clock, run_ops_checkpoint,
    create_log_load_payload, create_sawing_run_payload,
    make_scaler_headers, make_sawyer_headers, make_mill_manager_headers,
    make_sales_rep_headers, make_kiln_operator_headers,
)


class TestDeckCapacityConservation:
    def test_deck_over_capacity_rejected(self, api):
        """PRD Section 3.2: "A decking that would push the aggregate over 500 is rejected with `ERR_DECK_CAPACITY_EXCEEDED` (HTTP 422)."

        Design: Difficulty/compensating_invariant/deck_undeck_occupancy_conservation
        """
        l1 = create_decked_load(scaled_mbf=100)
        l2 = create_log_load(supplier_name="Cedar Rim LLC", log_grade="SAWLOG_2")
        scale_load(l2["id"], scaled_mbf=500, price_per_mbf_cents=22000)
        res = api.deck_log_load(l2["id"], make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_DECK_CAPACITY_EXCEEDED)
        after = get_load(l2["id"])
        assert after["status"] == "SCALED", f"rejected deck leaves the load SCALED, got {after['status']}"
        assert after.get("decked_at") is None

    def test_undeck_then_deck_at_exact_capacity_admitted(self, api):
        """PRD Section 3.2: "Undecking pulls a `DECKED` load back to `SCALED`, clearing `decked_at` and resetting both `degrade_pct` and `days_in_deck` to 0, and increments `version`."
        PRD Section 3.2: "The deck has a hard aggregate capacity of 500 thousand board feet: decking a load is allowed only when the sum of `scaled_mbf` across all loads currently `DECKED`, plus the decking load's own `scaled_mbf`, does not exceed 500 — sitting exactly at capacity is permitted."

        Design: Difficulty/compensating_invariant/deck_undeck_occupancy_conservation
        """
        l1 = create_decked_load(scaled_mbf=100)
        l2 = create_log_load(supplier_name="Cedar Rim LLC", log_grade="SAWLOG_2")
        scale_load(l2["id"], scaled_mbf=500, price_per_mbf_cents=22000)
        # 100 + 500 > 500: occupancy must be conserved by the compensating pair.
        validate_error(api.deck_log_load(l2["id"], make_scaler_headers()),
                       ApiErrorId.ERR_DECK_CAPACITY_EXCEEDED)
        undecked = validate_success(api.undeck_log_load(l1["id"], make_scaler_headers()), 200)
        assert undecked["status"] == "SCALED"
        assert undecked.get("decked_at") is None, "undeck clears decked_at"
        assert undecked["degrade_pct"] == 0 and undecked["days_in_deck"] == 0
        redecked = validate_success(api.deck_log_load(l2["id"], make_scaler_headers()), 200)
        assert redecked["status"] == "DECKED", (
            f"occupancy back to 0 after undeck; 500 <= 500 admitted, got {redecked['status']}"
        )


class TestUndeckPrecondition:
    def test_undeck_attached_load_returns_invalid_state(self, api):
        """PRD Section 3.2: "Undecking is the compensating action for the deck-occupancy invariant, and it is blocked precisely when compensation would be unsafe: a load already attached to a planned sawing run — its `sawing_run_id` set — cannot be undecked, and the attempt is rejected as `ERR_INVALID_STATE`."

        Design: Corner/state_machines/undeck_attached_load_returns_invalid_state
        """
        load = create_decked_load(scaled_mbf=100)
        create_planned_run([load["id"]])
        res = api.undeck_log_load(load["id"], make_scaler_headers())
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        after = get_load(load["id"])
        assert after["status"] == "DECKED", f"attached load cannot leave the deck, got {after['status']}"


class TestDeckDegrade:
    def test_degrade_free_through_day_14(self, api):
        """PRD Section 3.2: "The first 14 days in the deck are free: while `days_in_deck` is at most 14, `degrade_pct` stays at 0."
        PRD Section 3.9: "Second, degrade refresh: every `DECKED` log load has its `days_in_deck` and `degrade_pct` recomputed from the logical clock per the accrual rule of §3.2, so deck aging becomes visible mill-wide at checkpoint cadence rather than continuously."

        Design: Difficulty/boundary_precision_check/degrade_boundary_exactly_14_days
        """
        load = create_decked_load(scaled_mbf=100)  # decked at 2026-08-01T00:00:00Z
        set_clock("2026-08-15T00:00:00Z")
        run_ops_checkpoint()
        after = get_load(load["id"])
        assert after["days_in_deck"] == 14, f"14 whole days elapsed, got {after['days_in_deck']}"
        assert after["degrade_pct"] == 0, f"day 14 is the inclusive free boundary, got {after['degrade_pct']}"
        assert after["effective_mbf"] == pytest.approx(100.0, abs=1e-6)

    def test_degrade_accrues_one_week_past_window(self, api):
        """PRD Section 3.2: "Beyond the free window, degrade accrues at 3 percent per whole additional week: take the number of days past the 14-day window, divide by 7 truncating to a whole number, multiply by 3, and cap the result at 15 — degrade never exceeds 15 percent no matter how long the load sits."
        PRD Section 3.2: "The degrade feeds the load's effective volume: `effective_mbf` is the load's `scaled_mbf` multiplied by one minus `degrade_pct` expressed as a fraction, rounded half-up to 3 decimal places, and it remains null until the load has been scaled."

        Design: Difficulty/boundary_precision_check/degrade_boundary_exactly_14_days
        """
        load = create_decked_load(scaled_mbf=100)  # decked at 2026-08-01T00:00:00Z
        set_clock("2026-08-22T00:00:00Z")
        run_ops_checkpoint()
        after = get_load(load["id"])
        assert after["days_in_deck"] == 21
        assert after["degrade_pct"] == 3, (
            f"floor((21-14)/7) = 1 degrade week x 3 percent, got {after['degrade_pct']}"
        )
        assert after["effective_mbf"] == pytest.approx(97.0, abs=1e-6), (
            f"round(100 * (1 - 3/100), 3) = 97.0, got {after['effective_mbf']}"
        )


class TestSawLineBooking:
    def test_same_line_same_date_booked(self, api):
        """PRD Section 3.3: "The date occupies the whole calendar day: no other `PLANNED` run may share the same `saw_line` on the same `scheduled_date`, and a conflicting plan is rejected with `ERR_SAW_LINE_BOOKED` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/saw_line_daily_booking_adjacency
        """
        l1 = create_decked_load(scaled_mbf=100)
        l2 = create_decked_load(scaled_mbf=100)
        create_planned_run([l1["id"]], scheduled_date="2026-08-05")
        res = api.create_sawing_run(
            create_sawing_run_payload([l2["id"]], saw_line="LINE_A", scheduled_date="2026-08-05",
                                      sawing_pattern="STUD_MIX"),
            make_sawyer_headers(),
        )
        validate_error(res, ApiErrorId.ERR_SAW_LINE_BOOKED)
        assert get_load(l2["id"])["sawing_run_id"] is None, (
            "rejected plan must not attach the load"
        )

    def test_adjacent_day_free_and_attaches_load(self, api):
        """PRD Section 3.3: "Adjacent days are free, and the other line on the same day is free — occupation is per line per day, nothing more."
        PRD Section 3.3: "At creation the run enters at `PLANNED`, and each listed load is attached: its `sawing_run_id` is set to the new run's id, which is also why such a load can no longer be undecked."

        Design: Difficulty/resource_temporal_overlap/saw_line_daily_booking_adjacency
        """
        l1 = create_decked_load(scaled_mbf=100)
        l2 = create_decked_load(scaled_mbf=100)
        create_planned_run([l1["id"]], scheduled_date="2026-08-05")
        r3 = create_planned_run([l2["id"]], saw_line="LINE_A", scheduled_date="2026-08-06",
                                sawing_pattern="STUD_MIX")
        assert r3["status"] == "PLANNED"
        assert get_load(l2["id"])["sawing_run_id"] == r3["id"], (
            "the load attaches to the successful adjacent-day run only"
        )


class TestRunLogSet:
    def test_duplicate_load_in_run_rejected(self, api):
        """PRD Section 3.3: "Every id in `log_load_ids` must reference a load that is currently `DECKED` and not already attached to another planned run, the array must not be empty, and it must contain no duplicates; a duplicate id or a load already promised to another `PLANNED` run yields `ERR_DUPLICATE_LOAD_IN_RUN` (HTTP 422), while a load in the wrong state yields `ERR_INVALID_STATE`."

        Design: Corner/validations/duplicate_load_in_run_rejected
        """
        l1 = create_decked_load(scaled_mbf=100)
        l2 = create_decked_load(scaled_mbf=100)
        dup = api.create_sawing_run(
            create_sawing_run_payload([l1["id"], l1["id"]], scheduled_date="2026-08-03"),
            make_sawyer_headers(),
        )
        validate_error(dup, ApiErrorId.ERR_DUPLICATE_LOAD_IN_RUN)
        create_planned_run([l1["id"]], scheduled_date="2026-08-03")
        reattached = api.create_sawing_run(
            create_sawing_run_payload([l1["id"]], saw_line="LINE_B", scheduled_date="2026-08-04"),
            make_sawyer_headers(),
        )
        validate_error(reattached, ApiErrorId.ERR_DUPLICATE_LOAD_IN_RUN)


class TestInitialStates:
    def test_initial_states_on_create(self, api):
        """PRD Section 3.3: "Planning returns 201 with the new run; `input_mbf`, `output_green_mbf`, both recovery figures, and `completed_at` remain null, and the byproduct tonnage fields are unset until completion."
        PRD Section 3.4: "A successfully created charge enters at `SCHEDULED`, returns 201, and immediately moves every charged package from `GREEN` to `IN_KILN`, stamping each package's `kiln_charge_id` with the new charge's id and incrementing each package's `version`."
        PRD Section 3.7: "A new contract enters at `DRAFT` with `reserved_mbf` and `shipped_mbf` at zero, and returns 201."
        PRD Section 3.7: "Placement pins the commercial terms immediately — `unit_price_cents` is fixed at placement and never re-quoted afterward — and the new order enters at `PLACED` with `allocated_mbf` and `total_cents` at zero, returning 201."

        Design: Corner/entities/initial_states_on_create
        """
        load_res = validate_success(
            api.create_log_load(create_log_load_payload(), make_scaler_headers()), 201
        )
        assert load_res["status"] == "RECEIVED"
        scale_load(load_res["id"])
        deck_load(load_res["id"])
        run_res = validate_success(api.create_sawing_run(
            create_sawing_run_payload([load_res["id"]]), make_sawyer_headers()
        ), 201)
        assert run_res["status"] == "PLANNED"
        completed = validate_success(api.complete_sawing_run(
            run_res["id"],
            {"packages": [{"species": "DOUGLAS_FIR", "dimension": "2X4", "length_ft": 12,
                           "pieces": 100, "green_mbf": 20.0}],
             "chip_tons": 5, "sawdust_tons": 2, "bark_tons": 2},
            make_sawyer_headers(),
        ), 200)
        assert completed["status"] == "COMPLETED"
        pkg = list_run_packages(run_res["id"])[0]
        assert pkg["status"] == "GREEN"
        charge_res = validate_success(api.create_kiln_charge(
            {"chamber": "KILN_1", "species": "DOUGLAS_FIR", "package_ids": [pkg["id"]],
             "scheduled_start": "2026-08-02T00:00:00Z", "scheduled_end": "2026-08-05T00:00:00Z",
             "target_moisture_pct": 15.0},
            make_kiln_operator_headers(),
        ), 201)
        assert charge_res["status"] == "SCHEDULED"
        contract_res = validate_success(
            api.create_sales_contract(
                {"customer_name": "Acme Builders", "species": "DOUGLAS_FIR", "grade": "NO_2",
                 "committed_mbf": 100, "contract_price_per_mbf_cents": 60000,
                 "start_date": "2026-08-01", "end_date": "2026-09-01"},
                make_mill_manager_headers(),
            ), 201
        )
        assert contract_res["status"] == "DRAFT"
        publish_price_list()
        order_res = validate_success(api.create_sales_order(
            {"customer_name": "Spot Buyer", "species": "DOUGLAS_FIR", "grade": "NO_2",
             "length_spec": 12, "volume_mbf": 5},
            make_sales_rep_headers(),
        ), 201)
        assert order_res["status"] == "PLACED"
