"""Sling tension, gear derate, wind envelope, standby merge, capacity ceilings,
ground bearing, volume discounts and the two recomputed ledgers."""

import pytest

from test_helpers import (
    ApiErrorId,
    BILLING_CLERK,
    DISPATCHER,
    SAFETY_MANAGER,
    approve_permit,
    approve_plan,
    build_critical_world,
    build_standard_world,
    close_standby,
    configure_body,
    configure_plan,
    inspect_gear,
    open_permit,
    open_plan,
    read_assignment,
    read_crane,
    read_customer,
    read_gear,
    read_plan,
    setup_closed_standard_job,
    setup_configured_plan,
    setup_surveyed_plan_with_gear,
    submit_permit,
    survey_plan,
    validate_error,
    validate_paginated,
    validate_success,
)


def test_leg_tension_uses_the_tabulated_forty_five_degree_factor(api):
    """PRD 3.4: "The angle factor table is fixed and has exactly four entries: an
    angle of 90 degrees gives a factor of 1.000, 60 degrees gives 1.155, 45 degrees
    gives 1.414, and 30 degrees gives 2.000 — a shallow sling doubles what each leg
    carries."
    PRD 3.4: "A new commitment is created `ACTIVE`. It permanently snapshots the
    gear's current derated limit into its own `effective_wll_lb`, resolves its
    `load_angle_factor` from the sling angle, and leaves `leg_tension_lb` at 0 until
    the owning plan is next configured."
    PRD 3.4: "Each commitment's `leg_tension_lb` is the plan's `total_load_lb` divided
    by that commitment's `leg_count`, multiplied by its `load_angle_factor`, rounded
    half up to a whole pound."
    PRD 3.4: "When every leg passes, the plan's `rigging_verified` becomes true, which
    it remains only while the plan holds at least one active commitment and every one
    of them passed this check at the most recent configure."

    Design: Corner/calculations/sling_leg_tension_uses_the_tabulated_forty_five_degree_factor
    """
    world = build_standard_world()
    ctx = setup_surveyed_plan_with_gear(
        world, plan_overrides={"job_reference": "JOB-9300"},
        assignment_overrides={"sling_angle_deg": 45})

    assert ctx["assignment"]["effective_wll_lb"] == 30_000
    assert ctx["assignment"]["leg_tension_lb"] == 0

    plan = configure_plan(world, ctx["plan_id"], ctx["plan_version"])
    assignment = read_assignment(ctx["ga_id"])

    assert assignment["load_angle_factor"] == pytest.approx(1.414, abs=0.0005)
    assert assignment["leg_tension_lb"] == 21_387
    assert plan["rigging_verified"] is True


def test_a_thirty_degree_sling_over_its_limit_condemns_the_whole_configure(api):
    """PRD 3.4: "If any single commitment's resulting `leg_tension_lb` is **strictly
    greater** than that commitment's snapshotted `effective_wll_lb`, the whole
    configure fails with `ERR_SLING_WLL_EXCEEDED` — the check is aggregate, one
    violating leg condemns the entire request, and **no field on the plan is
    persisted** when it fails."

    Design: Corner/calculations/sling_wll_exceeded_at_thirty_degrees_rejects_the_configure
    """
    world = build_standard_world()
    ctx = setup_surveyed_plan_with_gear(
        world, plan_overrides={"job_reference": "JOB-9301"},
        assignment_overrides={"sling_angle_deg": 30})

    body = configure_body(world, ctx["plan_version"])
    validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                   ApiErrorId.ERR_SLING_WLL_EXCEEDED.value, 422)

    plan = read_plan(ctx["plan_id"])
    assert plan["plan_status"] == "SURVEYED"
    assert plan["crane_id"] is None
    assert plan["net_capacity_lb"] == 0
    assert plan["rigging_verified"] is False
    assert read_crane(world["crane_id"])["reserved_hours_total"] == pytest.approx(0.0)


def test_the_derate_decays_five_percent_per_repair_and_floors_at_seventy(api):
    """PRD 3.2: "The derate is a decay function, recomputed every time `repair_count`
    moves. The derate multiplier is one minus five hundredths for each recorded
    repair, but never allowed to fall below seventy hundredths — that is, the greater
    of the two. The gear's `effective_wll_lb` is then the manufacturer's
    `rated_wll_lb` multiplied by that multiplier, **floored** to a whole pound."
    PRD 3.2: "Only `REPAIR_PASS` inspections count toward `repair_count`; a `PASS`, a
    `FAIL` and a `RETIRE` never move it. Because the derate loses five percent per
    repair and stops at seventy percent, the floor is reached at the sixth repair and
    the rating never moves again after that."

    Design: Corner/calculations/gear_effective_wll_decays_then_floors_at_seventy_percent
    """
    gear = validate_success(api.create_rigging_gear(
        {"gear_tag": "SL-5001", "gear_type": "SLING", "rated_wll_lb": 30_000,
         "weight_lb": 500, "inspection_interval_days": 90}, SAFETY_MANAGER), 201)
    assert gear["effective_wll_lb"] == 30_000
    inspect_gear(gear["id"], "PASS")

    inspect_gear(gear["id"], "REPAIR_PASS", "repair 1")
    assert read_gear(gear["id"])["effective_wll_lb"] == 28_500
    inspect_gear(gear["id"], "REPAIR_PASS", "repair 2")
    assert read_gear(gear["id"])["effective_wll_lb"] == 27_000

    for n in range(3, 7):
        inspect_gear(gear["id"], "REPAIR_PASS", f"repair {n}")
    at_floor = read_gear(gear["id"])
    assert at_floor["repair_count"] == 6
    assert at_floor["effective_wll_lb"] == 21_000

    inspect_gear(gear["id"], "REPAIR_PASS", "repair 7")
    beyond = read_gear(gear["id"])
    assert beyond["repair_count"] == 7
    assert beyond["effective_wll_lb"] == 21_000, "the 0.70 floor holds"
    assert beyond["rated_wll_lb"] == 30_000, "the rated limit never changes"


def test_the_wind_derate_tier_is_selected_from_the_rounded_sail_area_ratio(api):
    """PRD 3.5: "At configure time, the system computes a sail-area ratio from the
    plan's own numbers: it is the plan's `sail_area_sqft` multiplied by 1000 and
    divided by its `load_weight_lb`, rounded half up to two decimal places."
    PRD 3.5: "That ratio selects one of four derate factors: a ratio at or below 1.00
    keeps the full rating with a factor of 1.00; a ratio above 1.00 but at or below
    2.00 takes 0.85; a ratio above 2.00 but at or below 3.00 takes 0.70; and anything
    above 3.00 takes 0.55."
    PRD 3.5: "Tier selection reads the rounded ratio, so a raw ratio of 2.004 rounds
    to 2.00 and stays in the 0.85 band."
    PRD 3.8: "A `WIND` event is accepted only when its `wind_speed_mph` is at or above
    the plan's `allowable_wind_mph` as derived in §3.5 — reporting a breeze below the
    plan's own derated envelope is refused with `ERR_WIND_BELOW_HOLD_THRESHOLD`, while
    every other cause skips this check entirely."

    Design: Corner/calculations/allowable_wind_tier_is_selected_from_the_rounded_ratio
    """
    world = build_standard_world()
    ctx = setup_configured_plan(
        world, plan_overrides={"job_reference": "JOB-9302", "sail_area_sqft": 120.24})

    assert ctx["plan"]["allowable_wind_mph"] == 25, "the 0.85 tier, not the 0.70 tier's 21"

    validate_error(api.create_standby_event(
        {"lift_plan_id": ctx["plan_id"], "cause": "WIND", "wind_speed_mph": 24.9,
         "started_at": "2026-09-10T09:00:00Z"}, SAFETY_MANAGER),
        ApiErrorId.ERR_WIND_BELOW_HOLD_THRESHOLD.value, 422)

    _, meta = validate_paginated(
        api.list_standby_events(SAFETY_MANAGER, params={"lift_plan_id": ctx["plan_id"]}))
    assert meta["total_count"] == 0


def test_disjoint_standby_windows_are_billed_separately(api):
    """PRD 3.8: "Closing a standby window supplies the `ended_at` instant, which must
    be strictly after `started_at`. The event moves `OPEN → CLOSED` and its
    `raw_duration_hours` is computed as the elapsed time from `started_at` to
    `ended_at` expressed in hours, rounded half up to four decimal places."
    PRD 3.8: "Every closed event on the plan is taken as a half-open interval that
    includes its start and excludes its end; the intervals are sorted by `started_at`
    ascending with the earlier `created_at` breaking ties; and two neighbours are
    merged whenever the later one starts at or before the earlier one ends — so a
    zero-gap, perfectly adjacent pair merges into one."
    PRD 3.8: "Opening an event against a plan that is currently `LIFTING` drives that
    plan `LIFTING → WIND_HOLD` and increments the plan's `version`; when the cause was
    `WIND`, the event's `forced_wind_hold` is set true to record that this particular
    event is what stopped the pick."

    Design: Corner/calculations/disjoint_standby_windows_are_not_merged
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9303"})

    first = validate_success(api.create_standby_event(
        {"lift_plan_id": ctx["plan_id"], "cause": "WEATHER",
         "started_at": "2026-09-10T09:00:00Z"}, SAFETY_MANAGER), 201)
    closed_first = close_standby(first["id"], "2026-09-10T10:00:00Z")
    second = validate_success(api.create_standby_event(
        {"lift_plan_id": ctx["plan_id"], "cause": "WEATHER",
         "started_at": "2026-09-10T11:00:00Z"}, SAFETY_MANAGER), 201)
    closed_second = close_standby(second["id"], "2026-09-10T12:00:00Z")

    assert closed_first["raw_duration_hours"] == pytest.approx(1.0, abs=0.0001)
    assert closed_second["raw_duration_hours"] == pytest.approx(1.0, abs=0.0001)

    plan = read_plan(ctx["plan_id"])
    assert plan["standby_hours_billable"] == pytest.approx(2.0, abs=0.0001), (
        "the 1.0 hour gap between the two windows is not billable"
    )
    assert plan["field_status"] == "NOT_MOBILIZED"
    assert closed_first["forced_wind_hold"] is False
    assert closed_second["forced_wind_hold"] is False


def test_a_radius_beyond_the_chart_leaves_the_candidate_set_empty(api):
    """PRD 3.4: "The candidate rows are those belonging to the chosen crane, charted
    for the chosen `configuration`, whose `boom_length_ft` matches the requested boom
    length **exactly** — there is no interpolation between charted boom lengths — and
    whose charted `radius_ft` is greater than or equal to the requested radius."
    PRD 3.4: "If no candidate exists at all, the configure fails with
    `ERR_LOAD_CHART_NO_ROW`."

    Design: Corner/calculations/load_chart_lookup_with_radius_beyond_the_chart_returns_no_row
    """
    world = build_critical_world(with_engineers=False,
                                 gear={"gear_tag": "SL-4001", "rated_wll_lb": 45_000})
    ctx = setup_surveyed_plan_with_gear(
        world, plan_overrides={"job_reference": "JOB-9304", "load_weight_lb": 40_000})

    body = configure_body(world, ctx["plan_version"], radius_ft=60)
    validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                   ApiErrorId.ERR_LOAD_CHART_NO_ROW.value, 422)

    plan = read_plan(ctx["plan_id"])
    assert plan["plan_status"] == "SURVEYED"
    assert plan["chart_gross_capacity_lb"] == 0


def test_utilization_above_the_ceiling_returns_capacity_exceeded(api):
    """PRD 3.4: "The plan's `utilization_pct` is `total_load_lb` divided by
    `net_capacity_lb`, multiplied by 100, rounded half up to two decimal places. A
    utilization above 100.00 percent fails with `ERR_CAPACITY_EXCEEDED`; exactly
    100.00 percent is permitted."

    Design: Corner/calculations/utilization_above_one_hundred_pct_returns_capacity_exceeded
    """
    world = build_critical_world(with_engineers=False,
                                 gear={"gear_tag": "SL-4001", "rated_wll_lb": 60_000})
    ctx = setup_surveyed_plan_with_gear(
        world, plan_overrides={"job_reference": "JOB-9305", "load_weight_lb": 98_000},
        assignment_overrides={"sling_angle_deg": 90})

    body = configure_body(world, ctx["plan_version"])
    error = validate_error(api.configure_lift_plan(ctx["plan_id"], body, DISPATCHER),
                           ApiErrorId.ERR_CAPACITY_EXCEEDED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_SLING_WLL_EXCEEDED.value

    plan = read_plan(ctx["plan_id"])
    assert plan["plan_status"] == "SURVEYED"
    assert plan["utilization_pct"] == pytest.approx(0, abs=0.0001)


def test_matting_is_not_required_when_pressure_exactly_equals_soil_capacity(api):
    """PRD 3.5: "The plan's `matting_required` is true when that
    `bearing_pressure_psf` is **strictly greater** than the site's
    `soil_bearing_capacity_psf` as most recently confirmed by a survey; equal pressure
    needs no mats."
    PRD 3.5: "When matting is not required, both `mat_area_required_sqft` and
    `mat_count` are 0."
    PRD 3.5: "Both variants begin from the same total vertical load: the crane's
    `gross_weight_lb`, plus its `counterweight_lb`, plus the plan's `total_load_lb` as
    computed in §3.4."

    Design: Corner/calculations/matting_not_required_when_bearing_pressure_equals_soil_capacity
    """
    world = build_standard_world(
        crane={"outrigger_pad_area_sqft": 25.0},
        site={"soil_bearing_capacity_psf": 1905},
    )
    ctx = setup_configured_plan(
        world,
        plan_overrides={"job_reference": "JOB-9306"},
        assignment_overrides=None,
    )
    plan = ctx["plan"]

    assert plan["bearing_variant"] == "PROVISIONAL_SURVEY"
    assert plan["per_outrigger_load_lb"] == pytest.approx(47_625.00, abs=0.005)
    assert plan["bearing_pressure_psf"] == pytest.approx(1_905.00, abs=0.005)
    assert plan["matting_required"] is False
    assert plan["mat_area_required_sqft"] == 0
    assert plan["mat_count"] == 0


def test_a_subtotal_past_two_and_a_half_million_takes_the_five_percent_tier(api):
    """PRD 3.9: "Step two selects `discount_pct` from a volume tier keyed on that
    **pre-surcharge** subtotal: a subtotal at or above 6,000,000 cents takes eight
    hundredths; failing that, one at or above 2,500,000 cents takes five hundredths;
    failing that, one at or above 1,000,000 cents takes two hundredths; anything below
    takes zero."
    PRD 3.9: "Step three sets `discount_cents` to `subtotal_cents` multiplied by
    `discount_pct`, rounded half up to whole cents."
    PRD 3.9: "`line_travel_cents` is `travel_miles` multiplied by 285 cents per mile,
    rounded half up, and applies under both modes."

    Design: Corner/calculations/discount_tier_two_applies_once_subtotal_passes_2500000
    """
    world = build_standard_world()
    ctx = setup_closed_standard_job(world, with_standby=False,
                                    plan_overrides={"job_reference": "JOB-9307"})

    invoice = validate_success(api.create_invoice(
        {"lift_plan_id": ctx["plan_id"], "billing_mode": "HOURLY",
         "on_site_hours": 40.0, "travel_hours": 4.0, "travel_miles": 200.0,
         "expected_lift_plan_version": ctx["plan_version"]}, BILLING_CLERK), 201)

    assert invoice["line_regular_cents"] == 363_000
    assert invoice["line_overtime_cents"] == 2_450_250
    assert invoice["line_travel_cents"] == 57_000
    assert invoice["line_mobdemob_cents"] == 250_000
    assert invoice["subtotal_cents"] == 3_120_250
    assert invoice["discount_pct"] == pytest.approx(0.05, abs=0.0001)
    assert invoice["discount_cents"] == 156_013
    assert invoice["fuel_surcharge_cents"] == 207_497
    assert invoice["total_cents"] == 3_171_734


def test_the_reservation_ledger_ignores_a_plan_that_is_only_surveyed(api):
    """PRD 3.4: "A crane's `reserved_hours_total` is the sum, over every plan on that
    crane whose readiness dimension is `CONFIGURED`, `PENDING_ENGINEERING`, `APPROVED`
    or `RELEASED`, of the plan's window length — `window_end` minus `window_start`,
    expressed in hours — rounded half up to two decimal places, and its
    `active_plan_count` is the number of plans in that same set."
    PRD 3.4: "Plans sitting at `DRAFT` or `SURVEYED`, and plans that have reached
    `CLOSED` or `CANCELLED`, are excluded."

    Design: Corner/calculations/crane_reserved_hours_ignore_plans_that_are_only_surveyed
    """
    world = build_standard_world()
    ctx_a = setup_surveyed_plan_with_gear(world, plan_overrides={"job_reference": "JOB-A"})
    configure_plan(world, ctx_a["plan_id"], ctx_a["plan_version"])

    plan_b = open_plan(world, job_reference="JOB-B",
                       window_start="2026-09-20T06:00:00Z",
                       window_end="2026-09-20T11:00:00Z")
    survey_plan(world, plan_b["id"])

    crane = read_crane(world["crane_id"])
    assert crane["reserved_hours_total"] == pytest.approx(10.0), "not 15.0"
    assert crane["active_plan_count"] == 1, "not 2"
    assert crane["status"] == "RESERVED"

    stored_b = read_plan(plan_b["id"])
    assert stored_b["plan_status"] == "SURVEYED"
    assert stored_b["crane_id"] is None


def test_paying_the_cancellation_invoice_empties_the_open_receivable(api):
    """PRD 3.9: "`open_receivable_cents` is the sum of `total_cents` across every
    invoice belonging to that customer whose status is `ISSUED` **or** `DISPUTED`;
    drafts, paid invoices and voided invoices are excluded. `invoice_count` is the
    number of that customer's invoices in any status whatsoever."
    PRD 3.9: "Payment is recorded from either `ISSUED` or `DISPUTED` and moves the
    invoice to `PAID`, which is terminal."
    PRD 3.9: "**Hop three** fires only because at least one voided permit now carries
    a `cancellation_fee_cents` greater than zero: the system mints exactly one invoice
    against the plan, with `system_generated` true, `billing_mode` `LUMP_SUM`,
    `lump_sum_cents` at 0 and `line_permit_cancellation_cents` set to the sum of those
    fees, and moves that invoice straight to `ISSUED` without anyone drafting it."

    Design: Corner/calculations/open_receivable_drops_to_zero_once_the_invoice_is_paid
    """
    world = build_standard_world()
    ctx = setup_configured_plan(world, plan_overrides={"job_reference": "JOB-9308",
                                                       "road_closure_requested": True})
    permit = open_permit(ctx["plan_id"], "ROAD_CLOSURE", world=world)
    assert permit["permit_fee_cents"] == 85_000, "a 150 ton crane draws no escort"
    submit_permit(permit["id"])
    approve_permit(permit["id"], "NJH-2026-0077")
    approve_plan(ctx["plan_id"])
    validate_success(api.cancel_lift_plan(
        ctx["plan_id"], {"reason": "customer cancelled the outage"}, DISPATCHER))

    invoices, _ = validate_paginated(
        api.list_invoices(BILLING_CLERK, params={"lift_plan_id": ctx["plan_id"]}))
    auto = invoices[0]
    assert auto["status"] == "ISSUED"
    assert auto["total_cents"] == 36_380
    assert read_customer(world["cust_id"])["open_receivable_cents"] == 36_380

    paid = validate_success(api.pay_invoice(auto["id"], BILLING_CLERK))
    assert paid["status"] == "PAID"

    after = read_customer(world["cust_id"])
    assert after["open_receivable_cents"] == 0, "PAID sits outside the open set"
    assert after["invoice_count"] == 1
