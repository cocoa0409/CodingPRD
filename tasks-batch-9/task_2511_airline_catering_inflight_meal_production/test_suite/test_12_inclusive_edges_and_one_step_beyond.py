"""The inclusive edge of each threshold, and the single smallest step that crosses it."""

from test_helpers import (
    CLOCK_CART,
    CLOCK_DISPATCH,
    CLOCK_PRODUCTION,
    CLOCK_QA,
    CLOCK_UPLIFT,
    COMPLIANCE,
    EVENT_ARRIVE,
    EVENT_DELIVER,
    EVENT_DISPATCH,
    QA,
    SPEC_AN_Y,
    SUPERVISOR,
    WINDOW_END,
    add_flight,
    advance_to_departed,
    advance_to_issued,
    advance_to_locked,
    advance_to_planned,
    advance_to_sealed,
    assert_decimal_equals,
    assert_total_count,
    build_base,
    cabin_cost_per_pax_cents,
    factories as f,
    finding_penalty_cents,
    handling_fee_cents,
    item_gross_cents,
    lateness_penalty_cents,
    load_item,
    produce_and_release,
    read_cart,
    read_flight,
    reconcile,
    register_cart,
    reserve_run,
    run_event,
    set_clock,
    sign_off_build,
    spec_deviation_pct,
    start_batch,
    record_check,
    validate_paginated,
    validate_success,
)

SECOND_WINDOW_START = "2026-09-15T08:20:00Z"
SECOND_WINDOW_END = "2026-09-15T08:50:00Z"
ARRIVE_FIRST = "2026-09-15T08:05:00Z"
DELIVER_TEN_LATE = "2026-09-15T08:10:00Z"
DISPATCH_SECOND = "2026-09-15T08:15:00Z"
ARRIVE_SECOND = "2026-09-15T08:55:00Z"
DELIVER_ELEVEN_LATE = "2026-09-15T09:01:00Z"
DELIVER_AT_WINDOW_END = "2026-09-15T08:00:00Z"
ARRIVE_SECOND_EARLY = "2026-09-15T08:45:00Z"
DELIVER_ONE_LATE = "2026-09-15T08:51:00Z"
ARRIVE_FIRST_EARLY = "2026-09-15T07:50:00Z"


def _read_batch(api, batch_id):
    return validate_success(api.get_production_batch(batch_id, SUPERVISOR), 200)


def _batch_in_production(env):
    """The canonical CHILL batch, started and awaiting its readings."""
    api = env.api
    set_clock(api, CLOCK_PRODUCTION)
    start_batch(api, env.batch["id"])
    set_clock(api, CLOCK_QA)
    return env.batch["id"]


def _two_runs(env):
    """Two runs of the one issued manifest, the truck buffer exactly satisfied."""
    api = env.api
    first = reserve_run(api, env.manifest["id"], env.truck["id"], env.stand["id"])
    second = reserve_run(
        api,
        env.manifest["id"],
        env.truck["id"],
        env.stand["id"],
        window_start_utc=SECOND_WINDOW_START,
        window_end_utc=SECOND_WINDOW_END,
    )
    return first, second


def _issued_flight_for(api, **airline_overrides):
    """One airline of our choosing, walked to a `LOADED` flight with an issued manifest."""
    env = build_base(api, **airline_overrides)
    add_flight(env)
    advance_to_locked(env)
    advance_to_planned(env)
    for batch in list(env.batches):
        produce_and_release(api, batch, list(SPEC_AN_Y["required_haccp_steps"]))
    env.reload_batches()
    set_clock(api, CLOCK_CART)
    cart = register_cart(api, env.flight_id)
    env.carts.append(cart)
    env.items.append(load_item(api, cart["id"], env.batch["id"], 180))
    env.carts[0] = sign_off_build(api, cart["id"])
    advance_to_sealed(env)
    advance_to_issued(env)
    return env


def _reconcile_after_producing(env, produced_qty, consumed_units, returned_units):
    """Produce and deliver exactly `produced_qty` trays, then reconcile the uplift."""
    api = env.api
    produce_and_release(
        api,
        env.batch,
        list(SPEC_AN_Y["required_haccp_steps"]),
        produced_qty=produced_qty,
    )
    env.reload_batches()
    set_clock(api, CLOCK_CART)
    cart = register_cart(api, env.flight_id)
    env.carts.append(cart)
    env.items.append(load_item(api, cart["id"], env.batch["id"], produced_qty))
    env.carts[0] = sign_off_build(api, cart["id"])
    advance_to_sealed(env)
    advance_to_issued(env)
    advance_to_departed(env)
    set_clock(api, CLOCK_UPLIFT)
    return reconcile(
        api,
        env.flight_id,
        [f.uplift_line(env.specs["Y"]["id"], consumed_units, returned_units)],
    )


class TestTheTemperatureConstants:
    """Five degrees exactly, and the one representable tenth above it."""

    def test_five_degrees_exactly_passes_and_five_point_one_fails(self, planned_env):
        """The same step, read twice, one tenth apart, decides the batch's state.

        PRD §3.5: "The `verdict` is never client-supplied: a cook-temperature reading passes when it is at or above 75.0 degrees; a chill-down reading passes when it is at or below 8.0 degrees; a hold-temperature reading passes when it is at or below 5.0 degrees; and a blast-chill reading passes when it is at or below 3.0 degrees."

        PRD §3.5: "Every comparison is inclusive at the constant, so a cook reading of exactly 75.0 is `PASS` while 74.9 is `FAIL`."

        PRD §3.5: "A `PASS` verdict never changes `production_status` at all."

        Design: Difficulty/boundary_precision_check/hold_temp_exactly_at_the_maximum_passes_and_one_tenth_above_fails
        """
        env = planned_env
        api = env.api
        batch_id = _batch_in_production(env)

        at_maximum = record_check(api, batch_id, "HOLD_TEMP", 5.0)
        assert at_maximum["verdict"] == "PASS"
        assert at_maximum["sequence_no"] == 1
        unmoved = _read_batch(api, batch_id)
        assert unmoved["production_status"] == "IN_PRODUCTION"
        assert_decimal_equals(unmoved["haccp_risk_score"], "0.00")

        above = record_check(api, batch_id, "HOLD_TEMP", 5.1)
        assert above["verdict"] == "FAIL"
        assert above["sequence_no"] == 2
        held = _read_batch(api, batch_id)
        assert held["production_status"] == "HACCP_HOLD"
        # One failure at 40.00 and no completed rework round yet.
        assert_decimal_equals(held["haccp_risk_score"], "40.00")
        # Entering the hold is not itself a rework round.
        assert held["haccp_rework_rounds"] == 0

        rows, meta = validate_paginated(
            api.list_haccp_checks(QA, {"production_batch_id": batch_id})
        )
        assert_total_count(meta, 2)
        assert [row["step_code"] for row in rows] == ["HOLD_TEMP", "HOLD_TEMP"]

    def test_each_of_the_four_constants_is_inclusive_and_its_own_series(
        self, planned_env
    ):
        """Four readings sit exactly on their limits; the fifth misses one by a tenth.

        PRD §3.5: "The `verdict` is never client-supplied: a cook-temperature reading passes when it is at or above 75.0 degrees; a chill-down reading passes when it is at or below 8.0 degrees; a hold-temperature reading passes when it is at or below 5.0 degrees; and a blast-chill reading passes when it is at or below 3.0 degrees."

        PRD §3.5: "When the batch is `IN_PRODUCTION` and the resulting failure count for the batch is two or fewer, the batch moves `IN_PRODUCTION → HACCP_HOLD` and its `haccp_risk_score` is recomputed."

        PRD §3.5: "A restart is the same operation applied to a batch sitting in `HACCP_HOLD`, moving it `HACCP_HOLD → IN_PRODUCTION`; a restart requires only that the batch is in `HACCP_HOLD` and that the logical clock is strictly before `release_deadline_utc`, and it additionally increments `haccp_rework_rounds` by one and recomputes `haccp_risk_score`."

        Design: Difficulty/boundary_precision_check/hold_temp_exactly_at_the_maximum_passes_and_one_tenth_above_fails
        """
        env = planned_env
        api = env.api
        batch_id = _batch_in_production(env)

        edges = (
            ("COOK_TEMP", 75.0),
            ("CHILL_DOWN", 8.0),
            ("HOLD_TEMP", 5.0),
            ("BLAST_CHILL", 3.0),
        )
        for step_code, temperature in edges:
            check = record_check(api, batch_id, step_code, temperature)
            assert check["verdict"] == "PASS"
            # Each step keeps its own ascending series.
            assert check["sequence_no"] == 1
            assert_decimal_equals(check["measured_temp_c"], "%.1f" % temperature)

        clean = _read_batch(api, batch_id)
        assert clean["production_status"] == "IN_PRODUCTION"
        assert_decimal_equals(clean["haccp_risk_score"], "0.00")
        assert clean["haccp_rework_rounds"] == 0

        below_cook = record_check(api, batch_id, "COOK_TEMP", 74.9)
        assert below_cook["verdict"] == "FAIL"
        assert below_cook["sequence_no"] == 2
        held = _read_batch(api, batch_id)
        assert held["production_status"] == "HACCP_HOLD"
        assert_decimal_equals(held["haccp_risk_score"], "40.00")

        restarted = start_batch(api, batch_id)
        assert restarted["production_status"] == "IN_PRODUCTION"
        assert restarted["haccp_rework_rounds"] == 1
        # One failure at 40.00 plus one completed rework round at 15.00.
        assert_decimal_equals(restarted["haccp_risk_score"], "55.00")

        _, meta = validate_paginated(
            api.list_haccp_checks(QA, {"production_batch_id": batch_id})
        )
        assert_total_count(meta, 5)


class TestTheLatenessGrace:
    """The last free minute of the allowance, and the first billable one after it."""

    def test_ten_minutes_late_is_free_and_eleven_minutes_is_billable(self, issued_env):
        """Two sibling runs of one manifest, one minute apart in lateness.

        PRD §3.7: "`lateness_minutes` is the elapsed time from `window_end_utc` to `delivered_at_utc` converted to whole minutes and rounded **up**, floored at zero — so a run delivered inside its window records 0, and a run delivered one second past its window records 1."

        PRD §3.7: "Billable minutes are `lateness_minutes` less the airline's `late_delivery_grace_minutes`, again floored at zero."

        PRD §3.7: "When the resulting `penalty_cents` is at least 1, a `LATE_DELIVERY` finding of `MINOR` severity is raised with `source` `SYSTEM`, incrementing the airline's `open_finding_count`."

        Design: Difficulty/boundary_precision_check/lateness_one_minute_past_the_grace_window_becomes_billable
        """
        env = issued_env
        api = env.api
        # The default contractual allowance is ten minutes.
        assert env.airline["late_delivery_grace_minutes"] == 10
        first, second = _two_runs(env)

        set_clock(api, CLOCK_DISPATCH)
        run_event(api, first["id"], EVENT_DISPATCH)
        set_clock(api, ARRIVE_FIRST)
        run_event(api, first["id"], EVENT_ARRIVE)
        set_clock(api, DELIVER_TEN_LATE)
        free = run_event(api, first["id"], EVENT_DELIVER)
        assert free["status"] == "DELIVERED"
        assert free["lateness_minutes"] == 10
        assert free["penalty_cents"] == 0 == lateness_penalty_cents(0)

        # Nothing was raised, and the join is still open.
        _, quiet = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(quiet, 0)
        assert read_flight(api, env.flight_id)["status"] == "LOADED"

        set_clock(api, DISPATCH_SECOND)
        run_event(api, second["id"], EVENT_DISPATCH)
        set_clock(api, ARRIVE_SECOND)
        run_event(api, second["id"], EVENT_ARRIVE)
        set_clock(api, DELIVER_ELEVEN_LATE)
        billed = run_event(api, second["id"], EVENT_DELIVER)
        assert billed["status"] == "DELIVERED"
        assert billed["lateness_minutes"] == 11
        # A single billable minute in the first band, at 250 cents.
        assert billed["penalty_cents"] == 250 == lateness_penalty_cents(1)

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        only = findings[0]
        assert only["finding_type"] == "LATE_DELIVERY"
        assert only["severity"] == "MINOR"
        assert only["source"] == "SYSTEM"
        assert only["status"] == "OPEN"
        assert only["penalty_cents"] == finding_penalty_cents(
            "LATE_DELIVERY", "MINOR"
        ) == 80000

        airline = env.reload_airline()
        assert airline["open_finding_count"] == 1
        assert airline["penalty_accrued_cents"] == 0
        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"
        assert read_cart(api, env.cart["id"])["build_status"] == "LOADED"

    def test_a_zero_grace_contract_bills_the_first_minute_and_the_edge_stays_free(
        self, api
    ):
        """With no allowance at all, the free case is delivery exactly at the edge.

        PRD §3.7: "Billable minutes are `lateness_minutes` less the airline's `late_delivery_grace_minutes`, again floored at zero."

        PRD §3.7: "`penalty_cents` then prices those billable minutes **marginally** across three bands: the first thirty billable minutes at 250 cents each, the next thirty — those from the thirty-first up to and including the sixtieth — at 400 cents each, and every billable minute beyond the sixtieth at 600 cents each."

        Design: Difficulty/boundary_precision_check/lateness_one_minute_past_the_grace_window_becomes_billable
        """
        env = _issued_flight_for(
            api,
            name="Sunbridge Airways",
            iata_code="SB",
            waste_regime="DOMESTIC",
            cost_cap_per_pax_cents=6000,
            late_delivery_grace_minutes=0,
        )
        assert env.airline["late_delivery_grace_minutes"] == 0
        first, second = _two_runs(env)

        set_clock(api, CLOCK_DISPATCH)
        run_event(api, first["id"], EVENT_DISPATCH)
        set_clock(api, ARRIVE_FIRST_EARLY)
        run_event(api, first["id"], EVENT_ARRIVE)
        # Delivered exactly at `window_end_utc`, which is not yet late at all.
        set_clock(api, DELIVER_AT_WINDOW_END)
        assert DELIVER_AT_WINDOW_END == WINDOW_END
        edge = run_event(api, first["id"], EVENT_DELIVER)
        assert edge["lateness_minutes"] == 0
        assert edge["penalty_cents"] == 0
        _, quiet = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(quiet, 0)

        set_clock(api, DISPATCH_SECOND)
        run_event(api, second["id"], EVENT_DISPATCH)
        set_clock(api, ARRIVE_SECOND_EARLY)
        run_event(api, second["id"], EVENT_ARRIVE)
        set_clock(api, DELIVER_ONE_LATE)
        billed = run_event(api, second["id"], EVENT_DELIVER)
        assert billed["lateness_minutes"] == 1
        # No grace to subtract, so the very first minute is priced.
        assert billed["penalty_cents"] == 250 == lateness_penalty_cents(1)

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        assert findings[0]["finding_type"] == "LATE_DELIVERY"
        assert findings[0]["severity"] == "MINOR"
        assert env.reload_airline()["open_finding_count"] == 1
        assert read_flight(api, env.flight_id)["status"] == "DEPARTED"


class TestTheDeviationTolerance:
    """Five percent exactly raises a finding; one tray more raises nothing."""

    def test_a_deviation_of_exactly_five_percent_raises_a_minor_finding(
        self, planned_env
    ):
        """Nine trays short of 180 is the inclusive lower edge of both the tolerance and the band.

        PRD §3.9: "The severity band is inclusive at its lower bound: a deviation from 5.00 up to and including 9.99 is `MINOR`, from 10.00 up to and including 19.99 is `MAJOR`, and 20.00 or above is `CRITICAL`."

        PRD §3.9: "A deviation of exactly 5.00 against the default tolerance of 5.00 therefore *does* raise a `MINOR` finding, while 4.44 raises nothing."

        Design: Difficulty/boundary_precision_check/spec_deviation_exactly_at_the_tolerance_raises_a_minor_finding
        """
        env = planned_env
        api = env.api
        record = _reconcile_after_producing(env, 171, 160, 11)

        assert_decimal_equals(record["spec_deviation_pct"], "5.00")
        assert_decimal_equals(
            record["spec_deviation_pct"], spec_deviation_pct(171, 180)
        )
        assert record["uplifted_units"] == 171
        assert record["consumed_units"] == 160
        assert record["returned_units"] == 11
        assert record["unused_units"] == 11
        # 171 trays at 1450 cents plus the twelve percent overhead.
        assert record["gross_cost_cents"] == 277704 == item_gross_cents(171, 1450)
        assert record["net_cost_cents"] == 277704
        assert record["handling_fee_cents"] == 19439 == handling_fee_cents(277704)
        assert record["billing_total_cents"] == 297143
        assert record["late_penalty_cents"] == 0
        assert record["seal_mismatch_count"] == 0
        assert record["cost_per_pax_cents"] == 1543 == cabin_cost_per_pax_cents(
            277704, 180
        )

        findings, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 1)
        only = findings[0]
        assert only["finding_type"] == "SPEC_DEVIATION"
        assert only["severity"] == "MINOR"
        assert only["source"] == "SYSTEM"
        assert only["status"] == "OPEN"
        assert only["penalty_cents"] == 120000 == finding_penalty_cents(
            "SPEC_DEVIATION", "MINOR"
        )

        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "RECONCILED"
        assert flight["units_planned"] == 180
        assert flight["units_produced"] == 171
        assert flight["units_scrapped"] == 9
        assert flight["units_loaded"] == 171
        airline = env.reload_airline()
        assert airline["open_finding_count"] == 1
        assert airline["status"] == "ACTIVE"

    def test_a_deviation_of_four_point_four_four_percent_raises_nothing(
        self, planned_env
    ):
        """One tray more than the edge case, and the docket stays completely empty.

        PRD §3.9: "The specification's deviation is the absolute difference between delivered and required, divided by required, multiplied by one hundred, and rounded half up to two decimals."

        PRD §3.9: "Two audit consequences may follow immediately: when `spec_deviation_pct` is at or above the airline's `spec_deviation_tolerance_pct`, a `SPEC_DEVIATION` finding is raised with `source` `SYSTEM` and severity taken from the deviation bands; and when `seal_mismatch_count` is at least 1, a `SEAL_MISMATCH` finding of `MAJOR` severity is raised with `source` `SYSTEM`."

        Design: Difficulty/boundary_precision_check/spec_deviation_exactly_at_the_tolerance_raises_a_minor_finding
        """
        env = planned_env
        api = env.api
        assert_decimal_equals(env.airline["spec_deviation_tolerance_pct"], "5.00")
        record = _reconcile_after_producing(env, 172, 161, 11)

        # Eight trays short of 180 is 4.4444..., which rounds to 4.44.
        assert_decimal_equals(record["spec_deviation_pct"], "4.44")
        assert record["uplifted_units"] == 172
        assert record["gross_cost_cents"] == 279328 == item_gross_cents(172, 1450)
        assert record["net_cost_cents"] == 279328
        assert record["handling_fee_cents"] == 19553 == handling_fee_cents(279328)
        assert record["billing_total_cents"] == 298881
        assert record["cost_per_pax_cents"] == 1552 == cabin_cost_per_pax_cents(
            279328, 180
        )

        _, meta = validate_paginated(
            api.list_audit_findings(COMPLIANCE, {"flight_id": env.flight_id})
        )
        assert_total_count(meta, 0)
        airline = env.reload_airline()
        assert airline["open_finding_count"] == 0
        assert airline["penalty_accrued_cents"] == 0

        flight = read_flight(api, env.flight_id)
        assert flight["status"] == "RECONCILED"
        assert flight["units_produced"] == 172
        assert flight["units_scrapped"] == 8
        assert flight["units_loaded"] == 172
