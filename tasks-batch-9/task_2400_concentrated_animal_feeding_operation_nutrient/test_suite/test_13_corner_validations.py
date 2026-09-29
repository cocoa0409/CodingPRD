"""Corner cases of the refusal rules: which check reports first when several
apply, where each dated gate lives, and what a request sitting on every
boundary at once is entitled to.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers.api_client import api_client
from test_helpers.api_errors import ApiErrorId
from test_helpers.assertions import (
    assert_budget_ledger,
    assert_null,
    assert_posture,
    assert_quantity,
    assert_state,
    assert_storage_balance,
    assert_storage_capacities,
)
from test_helpers.factories import (
    application_event_payload,
    budget_payload,
    incident_payload,
    intake_payload,
    soil_test_payload,
    storage_inspection_payload,
    transfer_payload,
)
from test_helpers.fixtures import (
    add_budget,
    approve_plan,
    certify_plan,
    conduct_inspection,
    create_plan,
    file_soil_test,
    initiate_transfer,
    record_application,
    record_intake,
    register_storage,
    schedule_inspection,
    set_clock,
    setup_scenario,
    submit_plan,
)
from test_helpers.test_users import (
    ADMIN_HEADERS,
    PLANNER_HEADERS,
    REVIEWER_HEADERS,
    make_hauler_headers,
)

SMALL_POND = {
    "structure_name": "Small Pond",
    "structure_type": "EARTHEN_LAGOON",
    "surface_area_sqft": 6000,
    "total_depth_in": 144,
    "required_freeboard_in": 24,
}


def _assert_instant(actual, prefix, label="instant"):
    """The instant echoed by the server carries the expected UTC calendar time."""
    assert actual is not None, f"{label} is missing"
    assert str(actual).startswith(prefix), (
        f"{label}: expected an instant at {prefix}, got {actual}"
    )


# ---------------------------------------------------------------------------
# Ground condition against precipitation risk
# ---------------------------------------------------------------------------
def test_saturated_ground_outranks_the_precipitation_forecast():
    """A saturated field with a 0.6 in forecast fails both weather checks; the
    ground condition is the one reported.

    PRD: "The agronomic and weather safeguards follow, and they are evaluated in a fixed order so that the most serious hazard is always the one reported."
    PRD: "Ground condition is checked first: a `soil_condition` of `FROZEN` is refused with `ERR_FROZEN_GROUND_APPLICATION`, and then a `soil_condition` of `SATURATED` with `ERR_SATURATED_SOIL_APPLICATION`."
    Design: Corner/validations/saturated_soil_outranks_precipitation_risk_and_half_inch_is_rejected
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                ctx["storage"]["id"],
                applied_on="2026-07-10T00:00:00Z",
                gallons_applied=100000,
                acres_treated=20,
                soil_condition="SATURATED",
                precipitation_forecast_in_24h=0.6,
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ERR_SATURATED_SOIL_APPLICATION,
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], ctx["operator_headers"])
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)


def test_the_forecast_limit_excludes_exactly_half_an_inch():
    """0.50 in is refused and 0.49 in is accepted on otherwise identical dry
    ground.

    PRD: "Next the forecast: `precipitation_forecast_in_24h` must be strictly less than 0.50 inches, so a forecast of exactly 0.50 inches is rejected with `ERR_PRECIPITATION_RISK`."
    Design: Corner/validations/saturated_soil_outranks_precipitation_risk_and_half_inch_is_rejected
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)
    operator_headers = ctx["operator_headers"]

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                ctx["storage"]["id"],
                applied_on="2026-07-10T00:00:00Z",
                gallons_applied=100000,
                acres_treated=20,
                soil_condition="DRY",
                precipitation_forecast_in_24h=0.5,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_PRECIPITATION_RISK,
    )

    event = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-07-10T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
        soil_condition="DRY",
        precipitation_forecast_in_24h=0.49,
    )
    assert_state(event, "event_status", "RECORDED")
    assert_quantity(event["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    assert_quantity(event["n_applied_lbs"], 1560.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 1000.00, "p2o5_applied_lbs")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=100000.00, remaining=314396, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], operator_headers)
    )
    assert_storage_balance(
        storage, intake=1000000.00, outflow=100000.00, current=900000.00, committed=0.00
    )


# ---------------------------------------------------------------------------
# The winter window follows the governing plan
# ---------------------------------------------------------------------------
def test_a_december_application_is_blocked_by_the_plans_winter_flag():
    """The same December date that a permissive plan would allow is refused while
    the governing plan forbids winter application.

    PRD: "Next comes the calendar: when the UTC month of `applied_on` is December, January or February, the owning plan's `winter_application_allowed` must be true, or the record is refused with `ERR_WINTER_WINDOW_APPLICATION`."
    Design: Corner/validations/winter_window_depends_on_the_plan_flag_of_the_governing_plan
    """
    ctx = setup_scenario(
        "APPROVED",
        plan={"allowed_application_methods": ["INJECTION"]},
        intake_gallons=1000000,
    )
    set_clock("2026-12-15T00:00:00Z")

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                ctx["storage"]["id"],
                applied_on="2026-12-10T00:00:00Z",
                gallons_applied=100000,
                acres_treated=20,
            ),
            ctx["operator_headers"],
        ),
        ApiErrorId.ERR_WINTER_WINDOW_APPLICATION,
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], ctx["operator_headers"])
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)


def test_a_successor_plan_that_permits_winter_admits_the_same_date():
    """Approving a revision that allows winter application supersedes the
    predecessor and lets the December record through; the December seasonal
    factor also shortens the storage runway.

    PRD: "Approval advances `SUBMITTED → APPROVED`, requires the operation's posture to be exactly `OPEN`, stamps `approved_at` from the logical clock, sets `budget_status` to `ACTIVE` on every field nutrient budget of the plan, and — when the plan names a `supersedes_plan_id` — transitions that referenced predecessor `APPROVED → SUPERSEDED`, which in turn sets `budget_status` to `LOCKED` on every budget of the predecessor."
    PRD: "That seasonal factor is 1.35 when the structure is an `EARTHEN_LAGOON` or a `STACKING_PAD` and the logical clock's UTC month is November, December, January, February or March — the months in which neither type can be emptied and both keep catching precipitation — and 1.0 in every other case; a `CONCRETE_TANK` never carries the seasonal factor."
    Design: Corner/validations/winter_window_depends_on_the_plan_flag_of_the_governing_plan
    """
    ctx = setup_scenario(
        "APPROVED",
        plan={"allowed_application_methods": ["INJECTION"]},
        intake_gallons=1000000,
    )
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]
    set_clock("2026-12-15T00:00:00Z")

    revision = create_plan(
        operation_id,
        ctx["permit"]["id"],
        PLANNER_HEADERS,
        allowed_application_methods=["INJECTION"],
        winter_application_allowed=True,
        supersedes_plan_id=ctx["plan"]["id"],
    )
    revision_budget = add_budget(
        revision["id"], ctx["field"]["id"], ctx["soil_test"]["id"], PLANNER_HEADERS
    )
    certify_plan(revision["id"], PLANNER_HEADERS)
    submit_plan(operation_id, revision["id"], operator_headers)
    approve_plan(revision["id"], REVIEWER_HEADERS)

    event = record_application(
        operation_id,
        revision["id"],
        revision_budget["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-12-10T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
    )
    assert_state(event, "event_status", "RECORDED")
    assert_quantity(event["n_applied_lbs"], 1560.00, "n_applied_lbs")

    predecessor = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], operator_headers)
    )
    assert_state(predecessor, "plan_status", "SUPERSEDED")
    old_budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_state(old_budget, "budget_status", "LOCKED")
    assert_budget_ledger(old_budget, applied=0.00, remaining=414396, total=414396)

    new_budget = validate_success(
        api_client.get_field_budget(revision_budget["id"], operator_headers)
    )
    assert_state(new_budget, "budget_status", "ACTIVE")
    assert_budget_ledger(new_budget, applied=100000.00, remaining=314396, total=414396)

    # 9244.65 x 1.35 = 12480.2775 gallons a day against 3588300 available.
    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], operator_headers)
    )
    assert_storage_balance(
        storage,
        outflow=100000.00,
        current=900000.00,
        available=3588300.00,
        days=287,
    )


# ---------------------------------------------------------------------------
# Setback against method membership
# ---------------------------------------------------------------------------
def test_a_setback_shortfall_outranks_an_unauthorised_method():
    """Irrigation demands 300 ft on a 200 ft field, so a 60 ft strip is reported
    as the setback failure even though irrigation is not in the plan at all;
    widening the strip then surfaces the method failure.

    PRD: "Then the setback: `setback_maintained_ft` must be at least the field's `required_setback_ft` scaled by a method multiplier, which is 1.0 for `SURFACE_BROADCAST`, 1.5 for `IRRIGATION`, 0.5 for `INCORPORATED_24H` and 0.25 for `INJECTION` — irrigation throws droplets further and so demands half again the base strip, while injection places manure below the surface and so needs only a quarter of it."
    PRD: "And the `application_method` must be a member of the owning plan's `allowed_application_methods`, or the record is refused with `ERR_APPLICATION_METHOD_NOT_IN_PLAN`."
    Design: Corner/validations/setback_priority_outranks_method_membership_then_both_are_satisfied
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)
    operator_headers = ctx["operator_headers"]

    def irrigation_event(setback):
        return api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                ctx["storage"]["id"],
                applied_on="2026-07-10T00:00:00Z",
                gallons_applied=100000,
                acres_treated=20,
                application_method="IRRIGATION",
                setback_maintained_ft=setback,
            ),
            operator_headers,
        )

    validate_error(irrigation_event(60), ApiErrorId.ERR_SETBACK_VIOLATION)
    validate_error(
        irrigation_event(300), ApiErrorId.ERR_APPLICATION_METHOD_NOT_IN_PLAN
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)


def test_incorporation_at_exactly_half_the_setback_is_accepted():
    """100 ft is exactly half of the field's 200 ft strip, and INCORPORATED_24H is
    an authorised method, so the record stands with the 0.55 availability load.

    PRD: "A shortfall is refused with `ERR_SETBACK_VIOLATION`."
    PRD: "`n_applied_lbs`, the plant-available nitrogen, is `gallons_applied` divided by 1,000, multiplied by the manure nitrogen concentration for the group — 24 pounds per thousand gallons for dairy, 32 for beef, 40 for swine, 60 for layer — multiplied by the availability factor for the `application_method` actually used — 0.65 for `INJECTION`, 0.55 for `INCORPORATED_24H`, 0.40 for `SURFACE_BROADCAST`, 0.35 for `IRRIGATION` — and rounded half up to 2 decimal places."
    Design: Corner/validations/setback_priority_outranks_method_membership_then_both_are_satisfied
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)
    operator_headers = ctx["operator_headers"]

    event = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-07-10T00:00:00Z",
        gallons_applied=100000,
        acres_treated=20,
        application_method="INCORPORATED_24H",
        setback_maintained_ft=100,
    )
    assert_state(event, "event_status", "RECORDED")
    assert_quantity(event["rate_gal_per_acre"], 5000.00, "rate_gal_per_acre")
    # 100 thousand gallons x 24 lb N x 0.55 availability.
    assert_quantity(event["n_applied_lbs"], 1320.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 1000.00, "p2o5_applied_lbs")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=100000.00, remaining=314396, total=414396)


# ---------------------------------------------------------------------------
# The future-dated gate lives on every dated record endpoint
# ---------------------------------------------------------------------------
def test_every_dated_record_endpoint_refuses_a_date_past_the_clock():
    """Land applications, transfers, storage inspections, soil tests and incident
    reports each carry the same gate, and none of them leaves a row behind.

    PRD: "`applied_on` may not be later than the logical clock, or the record is refused with `ERR_FUTURE_DATED_RECORD`."
    PRD: "Initiation requires that the operation's permit is not `EXPIRED` (`ERR_PERMIT_COVERAGE_EXPIRED`), that the referenced hauler's `hauler_status` is `ACTIVE` (`ERR_HAULER_LICENSE_LAPSED`), that `transferred_on` is not later than the logical clock (`ERR_FUTURE_DATED_RECORD`), that the operation's posture is not `SUSPENDED` (`ERR_OPERATION_SUSPENDED`) and is in fact `OPEN` (`ERR_OPERATION_RESTRICTED`), and that `gallons_transferred` does not exceed the source structure's `current_volume_gallons` less its `committed_outflow_gallons` (`ERR_INSUFFICIENT_STORAGE_VOLUME`)."
    PRD: "Each records `inspected_on`, the instant of the inspection, which may not be later than the logical clock; `inspector_name`, the person who performed it; `measured_freeboard_in`, the vertical distance from the liquid surface to the top of the structure, which may not be negative and may not exceed the structure's `total_depth_in`; and `visual_condition`, the recorded state of berms, liner and outlets, being one of `NORMAL`, `SEEPAGE`, `EROSION` or `CRACKING`."
    PRD: "None of the three measurements may be negative, and `sampled_on` may not be later than the logical clock — a future-dated sample is refused with `ERR_FUTURE_DATED_RECORD`."
    PRD: "An `Operator` files a report against its `operation_id` with `discovered_at`, the instant of discovery, which may not be later than the logical clock, and a `description` narrating the event and the immediate actions taken."
    Design: Corner/validations/every_dated_record_endpoint_rejects_a_date_after_the_clock
    """
    ctx = setup_scenario("APPROVED", with_hauler=True, intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]
    tomorrow = "2026-08-02T00:00:00Z"

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                storage_id,
                applied_on=tomorrow,
                gallons_applied=100000,
                acres_treated=20,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_FUTURE_DATED_RECORD,
    )
    validate_error(
        api_client.create_manure_transfer(
            transfer_payload(
                operation_id, storage_id, ctx["hauler"]["id"], transferred_on=tomorrow
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_FUTURE_DATED_RECORD,
    )
    validate_error(
        api_client.create_storage_inspection(
            storage_inspection_payload(storage_id, inspected_on=tomorrow),
            operator_headers,
        ),
        ApiErrorId.ERR_FUTURE_DATED_RECORD,
    )
    validate_error(
        api_client.create_soil_test(
            soil_test_payload(ctx["field"]["id"], sampled_on="2026-09-01T00:00:00Z"),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_FUTURE_DATED_RECORD,
    )
    validate_error(
        api_client.create_incident_report(
            incident_payload(
                operation_id, subject_storage_id=storage_id, discovered_at=tomorrow
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_FUTURE_DATED_RECORD,
    )

    for lister, params in (
        (api_client.list_application_events, {"plan_id": ctx["plan"]["id"]}),
        (api_client.list_manure_transfers, {"operation_id": operation_id}),
        (api_client.list_storage_inspections, {"storage_id": storage_id}),
        (api_client.list_incident_reports, {"operation_id": operation_id}),
    ):
        _, meta = validate_paginated(lister(ADMIN_HEADERS, params))
        assert meta["total_count"] == 0, (
            f"expected no rows, got {meta['total_count']} from {lister.__name__}"
        )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)
    storage = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_storage_balance(
        storage, intake=1000000.00, outflow=0.00, current=1000000.00, committed=0.00
    )


def test_a_record_stamped_exactly_at_the_clock_is_accepted():
    """The gate is "later than", so a sample taken at the clock's own instant
    stands and is still within its four-year validity.

    PRD: "A soil test also carries `is_valid`, which is true while the logical clock is strictly earlier than four years after `sampled_on`."
    Design: Corner/validations/every_dated_record_endpoint_rejects_a_date_after_the_clock
    """
    ctx = setup_scenario("LAND_BASE")

    sample = file_soil_test(
        ctx["field"]["id"], PLANNER_HEADERS, sampled_on="2026-08-01T00:00:00Z"
    )
    _assert_instant(sample["sampled_on"], "2026-08-01T00:00:00", "sampled_on")
    assert sample["is_valid"] is True
    assert_quantity(sample["p_index"], 43.68, "p_index")


# ---------------------------------------------------------------------------
# The budget depends on the soil test row it names
# ---------------------------------------------------------------------------
def test_a_very_high_index_zeroes_the_rate_and_blocks_the_budget():
    """A VERY_HIGH index zeroes the phosphate allowance, so the smaller of the two
    limits is 0 and no budget is created.

    PRD: "The multiplier is 4.0 for `LOW`, 2.0 for `MEDIUM`, 1.0 for `HIGH` and 0.0 for `VERY_HIGH` — soil already saturated with phosphorus gets no phosphate allowance at all."
    PRD: "If the selection in step 8 yields a rate of 0 — a `VERY_HIGH` phosphorus index zeroes the phosphate allowance, and a legume crop can zero the nitrogen need — the budget is not created; the request is refused with `ERR_ZERO_ALLOWABLE_RATE`, because a budget that authorises nothing is not a budget."
    Design: Corner/validations/budget_creation_depends_on_the_referenced_soil_test_row
    """
    ctx = setup_scenario("DRAFT_PLAN")

    # 100 ppm on a 4 % slope indexes at 104.00, which is VERY_HIGH.
    saturated = file_soil_test(
        ctx["field"]["id"], PLANNER_HEADERS, soil_test_p_ppm=100
    )
    assert_quantity(saturated["p_index"], 104.00, "p_index")
    assert_state(saturated, "p_index_category", "VERY_HIGH")

    validate_error(
        api_client.create_field_budget(
            budget_payload(ctx["plan"]["id"], ctx["field"]["id"], saturated["id"]),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_ZERO_ALLOWABLE_RATE,
    )

    _, meta = validate_paginated(
        api_client.list_field_budgets(PLANNER_HEADERS, {"plan_id": ctx["plan"]["id"]})
    )
    assert meta["total_count"] == 0, f"expected no budgets, got {meta['total_count']}"


def test_a_stale_soil_test_is_refused_before_any_rate_is_computed():
    """A sample from 2021 is more than four years old, so it is rejected on
    validity rather than on the agronomy it would have supported.

    PRD: "Only the named soil test participates — other tests on the same field are ignored entirely — and that test must have `is_valid` true and must belong to the same field as the budget, or the request is refused with `ERR_NO_VALID_SOIL_TEST`."
    PRD: "When a single request could fail several checks, the outcome must be the error belonging to the **earliest** applicable check in the ordering below."
    Design: Corner/validations/budget_creation_depends_on_the_referenced_soil_test_row
    """
    ctx = setup_scenario("DRAFT_PLAN")

    stale = file_soil_test(
        ctx["field"]["id"], PLANNER_HEADERS, sampled_on="2021-06-01T00:00:00Z"
    )
    assert stale["is_valid"] is False

    validate_error(
        api_client.create_field_budget(
            budget_payload(ctx["plan"]["id"], ctx["field"]["id"], stale["id"]),
            PLANNER_HEADERS,
        ),
        ApiErrorId.ERR_NO_VALID_SOIL_TEST,
    )

    _, meta = validate_paginated(
        api_client.list_field_budgets(PLANNER_HEADERS, {"plan_id": ctx["plan"]["id"]})
    )
    assert meta["total_count"] == 0, f"expected no budgets, got {meta['total_count']}"


def test_the_valid_medium_index_test_yields_the_budget():
    """The current 42 ppm sample indexes MEDIUM and produces the nitrogen-bound
    budget, and it is the only budget row on the plan.

    PRD: "Only the named soil test participates — other tests on the same field are ignored entirely — and that test must have `is_valid` true and must belong to the same field as the budget, or the request is refused with `ERR_NO_VALID_SOIL_TEST`."
    Design: Corner/validations/budget_creation_depends_on_the_referenced_soil_test_row
    """
    ctx = setup_scenario("DRAFT_PLAN")

    file_soil_test(ctx["field"]["id"], PLANNER_HEADERS, soil_test_p_ppm=100)
    file_soil_test(
        ctx["field"]["id"], PLANNER_HEADERS, sampled_on="2021-06-01T00:00:00Z"
    )

    budget = add_budget(
        ctx["plan"]["id"],
        ctx["field"]["id"],
        ctx["soil_test"]["id"],
        PLANNER_HEADERS,
    )
    assert_quantity(
        budget["allowable_rate_gal_per_acre"], 10800, "allowable_rate_gal_per_acre"
    )
    assert_state(budget, "binding_basis", "NITROGEN")
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    _, meta = validate_paginated(
        api_client.list_field_budgets(PLANNER_HEADERS, {"plan_id": ctx["plan"]["id"]})
    )
    assert meta["total_count"] == 1, f"expected one budget, got {meta['total_count']}"


# ---------------------------------------------------------------------------
# The ceilings are aggregate checks, not per-call checks
# ---------------------------------------------------------------------------
def test_intake_stops_at_the_operating_capacity_not_at_the_design_capacity():
    """An intake filling the structure to exactly its operating capacity is
    accepted; one more gallon is refused.

    PRD: "An intake is refused with `ERR_STORAGE_OPERATING_CAPACITY_EXCEEDED` when the resulting `current_volume_gallons` would exceed `operating_capacity_gallons`, and is refused with `ERR_OPERATION_SUSPENDED` when the operation's posture is `SUSPENDED`."
    PRD: "`operating_capacity_gallons` is `design_capacity_gallons` less `freeboard_reserve_gallons` — the volume the structure may lawfully hold."
    Design: Corner/validations/capacity_and_acreage_ceilings_are_aggregate_not_per_call_checks
    """
    ctx = setup_scenario("APPROVED")
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    filled = record_intake(
        ctx["operation"]["id"], storage_id, 4488300, operator_headers
    )
    assert_storage_capacities(
        filled, design=5385960.00, reserve=897660.00, operating=4488300.00
    )
    assert_storage_balance(
        filled,
        intake=4488300.00,
        current=4488300.00,
        available=0.00,
        committed=0.00,
        days=0,
    )

    validate_error(
        api_client.record_storage_intake(
            storage_id, intake_payload(1), operator_headers
        ),
        ApiErrorId.ERR_STORAGE_OPERATING_CAPACITY_EXCEEDED,
    )

    unchanged = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_storage_balance(
        unchanged, intake=4488300.00, current=4488300.00, available=0.00
    )


def test_the_draw_is_checked_against_the_named_structure_alone():
    """A full lagoon elsewhere on the operation does not help an event drawn from
    an empty second structure.

    PRD: "Finally `gallons_applied` may not exceed the source structure's `current_volume_gallons` less its `committed_outflow_gallons` — you cannot spread manure you do not have, nor manure you have already promised to a hauler — or the record is refused with `ERR_INSUFFICIENT_STORAGE_VOLUME`."
    Design: Corner/validations/capacity_and_acreage_ceilings_are_aggregate_not_per_call_checks
    """
    ctx = setup_scenario("APPROVED")
    operation_id = ctx["operation"]["id"]
    operator_headers = ctx["operator_headers"]

    record_intake(operation_id, ctx["storage"]["id"], 4488300, operator_headers)
    second = register_storage(
        operation_id, operator_headers, structure_name="Lagoon 2"
    )

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                ctx["budget"]["id"],
                second["id"],
                applied_on="2026-07-01T00:00:00Z",
                gallons_applied=300000,
                acres_treated=30,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_INSUFFICIENT_STORAGE_VOLUME,
    )

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)
    empty = validate_success(
        api_client.get_manure_storage(second["id"], operator_headers)
    )
    assert_storage_balance(empty, intake=0.00, outflow=0.00, current=0.00)


def test_the_acreage_ceiling_and_the_running_allowance_bound_the_event():
    """38.38 acres overruns the field's 38.37 net acres; the event at exactly
    38.37 acres is accepted and leaves only 14396 gallons, which a later 20000
    gallon event cannot draw on.

    PRD: "`acres_treated` may not exceed the field's `net_applicable_acres`, or the record is refused with `ERR_ACRES_EXCEED_NET_APPLICABLE`."
    PRD: "`gallons_applied` may not exceed the budget's `remaining_gallons`, or the record is refused with `ERR_FIELD_ALLOWANCE_EXCEEDED`."
    Design: Corner/validations/capacity_and_acreage_ceilings_are_aggregate_not_per_call_checks
    """
    ctx = setup_scenario("APPROVED")
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    budget_id = ctx["budget"]["id"]
    operator_headers = ctx["operator_headers"]

    record_intake(operation_id, storage_id, 4488300, operator_headers)

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                budget_id,
                storage_id,
                applied_on="2026-07-01T00:00:00Z",
                gallons_applied=100000,
                acres_treated=38.38,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_ACRES_EXCEED_NET_APPLICABLE,
    )

    event = record_application(
        operation_id,
        ctx["plan"]["id"],
        budget_id,
        storage_id,
        operator_headers,
        applied_on="2026-07-01T00:00:00Z",
        gallons_applied=400000,
        acres_treated=38.37,
    )
    # 400000 / 38.37 = 10424.81 gallons an acre, inside the 10800 limit.
    assert_quantity(event["rate_gal_per_acre"], 10424.81, "rate_gal_per_acre")
    assert_quantity(event["n_applied_lbs"], 6240.00, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 4000.00, "p2o5_applied_lbs")

    budget = validate_success(api_client.get_field_budget(budget_id, operator_headers))
    assert_budget_ledger(budget, applied=400000.00, remaining=14396, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_storage_balance(
        storage,
        outflow=400000.00,
        current=4088300.00,
        available=400000.00,
        days=43,
    )

    validate_error(
        api_client.create_application_event(
            application_event_payload(
                ctx["plan"]["id"],
                budget_id,
                storage_id,
                applied_on="2026-07-25T00:00:00Z",
                gallons_applied=20000,
                acres_treated=5,
            ),
            operator_headers,
        ),
        ApiErrorId.ERR_FIELD_ALLOWANCE_EXCEEDED,
    )

    still = validate_success(api_client.get_field_budget(budget_id, operator_headers))
    assert_budget_ledger(still, applied=400000.00, remaining=14396, total=414396)

    field = validate_success(
        api_client.get_field(ctx["field"]["id"], operator_headers)
    )
    _assert_instant(
        field["last_application_on"], "2026-07-01T00:00:00", "last_application_on"
    )


# ---------------------------------------------------------------------------
# Endpoint-specific gates
# ---------------------------------------------------------------------------
def test_acknowledgement_requires_the_recipient_documentation():
    """A transfer initiated without the nutrient analysis cannot be acknowledged,
    and nothing about it moves.

    PRD: "Acknowledgement is the recipient-documentation gate: `nutrient_analysis_provided` must be true and both `recipient_name` and `recipient_address` must be non-empty, or the request is refused with `ERR_RECIPIENT_DOCUMENTATION_MISSING`; and the hauler's own `hauler_status` must still be `ACTIVE`, or it is refused with `ERR_HAULER_LICENSE_LAPSED`."
    Design: Corner/validations/nov_and_recipient_documentation_gates_fire_on_their_own_endpoints
    """
    ctx = setup_scenario("APPROVED", with_hauler=True, intake_gallons=1000000)
    hauler_id = ctx["hauler"]["id"]

    transfer = initiate_transfer(
        ctx["operation"]["id"],
        ctx["storage"]["id"],
        hauler_id,
        ctx["operator_headers"],
        nutrient_analysis_provided=False,
    )

    validate_error(
        api_client.acknowledge_manure_transfer(
            transfer["id"], make_hauler_headers(hauler_id)
        ),
        ApiErrorId.ERR_RECIPIENT_DOCUMENTATION_MISSING,
    )

    unchanged = validate_success(
        api_client.get_manure_transfer(transfer["id"], ctx["operator_headers"])
    )
    assert_state(unchanged, "transfer_status", "INITIATED")
    assert_null(unchanged, "recipient_ack_signed_at")

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], ctx["operator_headers"])
    )
    assert_storage_balance(
        storage, outflow=0.00, current=1000000.00, committed=200000.00
    )


def test_a_notice_of_violation_is_not_warranted_without_findings():
    """An inspection conducted with no findings cannot carry a notice, and the
    operation stays open.

    PRD: "When `findings_count` is at least 1, a `StateReviewer` issues a notice of violation, advancing `CONDUCTED → NOV_ISSUED`; issuing on an inspection with `findings_count` of 0 is refused with `ERR_NOV_NOT_WARRANTED`."
    Design: Corner/validations/nov_and_recipient_documentation_gates_fire_on_their_own_endpoints
    """
    ctx = setup_scenario("APPROVED", intake_gallons=1000000)

    inspection = schedule_inspection(
        ctx["operation"]["id"], ctx["permit"]["id"], REVIEWER_HEADERS
    )
    conducted = conduct_inspection(inspection["id"], 0, REVIEWER_HEADERS)
    assert_state(conducted, "inspection_status", "CONDUCTED")

    validate_error(
        api_client.issue_nov(inspection["id"], REVIEWER_HEADERS),
        ApiErrorId.ERR_NOV_NOT_WARRANTED,
    )

    after = validate_success(
        api_client.get_inspection(inspection["id"], REVIEWER_HEADERS)
    )
    assert_state(after, "inspection_status", "CONDUCTED")
    assert_null(after, "response_due_on")

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], ADMIN_HEADERS)
    )
    assert_posture(operation, "OPEN", findings=0)


def test_a_warranted_notice_starts_the_compliance_cascade():
    """With one finding the notice issues, dates the response 30 days out, and
    drives the posture, the approved plan and the open transfer downstream.

    PRD: "Issuance stamps `response_due_on` as `conducted_on` plus 30 days — so an inspection conducted at the start of 1 August 2026 and served with a notice is due a response by the start of 31 August 2026 — increments the operation's `open_finding_count`, and starts the compliance cascade."
    PRD: "And that in turn suspends every `INITIATED` transfer of the operation in ascending `created_at` order, releasing each transfer's committed volume back to its source structure and recomputing that structure's `available_capacity_gallons` and `days_of_storage_available`."
    Design: Corner/validations/nov_and_recipient_documentation_gates_fire_on_their_own_endpoints
    """
    ctx = setup_scenario("APPROVED", with_hauler=True, intake_gallons=1000000)
    operation_id = ctx["operation"]["id"]
    storage_id = ctx["storage"]["id"]
    operator_headers = ctx["operator_headers"]

    transfer = initiate_transfer(
        operation_id, storage_id, ctx["hauler"]["id"], operator_headers
    )

    inspection = schedule_inspection(operation_id, ctx["permit"]["id"], REVIEWER_HEADERS)
    conduct_inspection(inspection["id"], 2, REVIEWER_HEADERS)
    served = validate_success(
        api_client.issue_nov(inspection["id"], REVIEWER_HEADERS)
    )
    assert_state(served, "inspection_status", "NOV_ISSUED")
    _assert_instant(served["response_due_on"], "2026-08-31T00:00:00", "response_due_on")

    operation = validate_success(api_client.get_operation(operation_id, ADMIN_HEADERS))
    assert_posture(operation, "RESTRICTED", findings=1)

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], operator_headers)
    )
    assert_state(plan, "plan_status", "REVISION_REQUIRED")
    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_state(budget, "budget_status", "LOCKED")
    assert_budget_ledger(budget, applied=0.00, remaining=414396, total=414396)

    suspended = validate_success(
        api_client.get_manure_transfer(transfer["id"], operator_headers)
    )
    assert_state(suspended, "transfer_status", "SUSPENDED")

    storage = validate_success(
        api_client.get_manure_storage(storage_id, operator_headers)
    )
    assert_storage_balance(
        storage, outflow=0.00, current=1000000.00, committed=0.00, available=3488300.00
    )


# ---------------------------------------------------------------------------
# Every boundary at once
# ---------------------------------------------------------------------------
def test_an_application_on_every_boundary_at_once_is_accepted():
    """Applied at the clock instant, on exactly the net acres, at exactly the
    allowable rate, on exactly a quarter of the setback, one hundredth under
    the forecast limit: the record stands and empties the allowance exactly.

    PRD: "The per-acre rate, `rate_gal_per_acre`, computed as `gallons_applied` divided by `acres_treated` and rounded half up to 2 decimal places, may not exceed the budget's `allowable_rate_gal_per_acre`, or the record is refused with `ERR_RATE_EXCEEDS_LIMIT`."
    PRD: "A structure's own `days_of_storage_available` is the greater of zero and its `available_capacity_gallons`, divided by that effective daily production and floored to a whole day, so the figure shrinks as the structure fills and grows again when a transfer is suspended or cancelled."
    Design: Corner/validations/an_application_sitting_on_every_boundary_at_once_is_accepted
    """
    ctx = setup_scenario(
        "APPROVED",
        plan={"allowed_application_methods": ["INJECTION"]},
        intake_gallons=1000000,
    )
    operator_headers = ctx["operator_headers"]

    event = record_application(
        ctx["operation"]["id"],
        ctx["plan"]["id"],
        ctx["budget"]["id"],
        ctx["storage"]["id"],
        operator_headers,
        applied_on="2026-08-01T00:00:00Z",
        gallons_applied=414396,
        acres_treated=38.37,
        application_method="INJECTION",
        setback_maintained_ft=50,
        soil_condition="DRY",
        precipitation_forecast_in_24h=0.49,
    )
    assert_state(event, "event_status", "RECORDED")
    assert_quantity(event["rate_gal_per_acre"], 10800.00, "rate_gal_per_acre")
    assert_quantity(event["n_applied_lbs"], 6464.58, "n_applied_lbs")
    assert_quantity(event["p2o5_applied_lbs"], 4143.96, "p2o5_applied_lbs")

    budget = validate_success(
        api_client.get_field_budget(ctx["budget"]["id"], operator_headers)
    )
    assert_state(budget, "budget_status", "ACTIVE")
    assert_budget_ledger(budget, applied=414396.00, remaining=0.00, total=414396)

    storage = validate_success(
        api_client.get_manure_storage(ctx["storage"]["id"], operator_headers)
    )
    assert_storage_balance(
        storage,
        intake=1000000.00,
        outflow=414396.00,
        current=585604.00,
        committed=0.00,
        available=3902696.00,
        days=422,
    )

    field = validate_success(
        api_client.get_field(ctx["field"]["id"], operator_headers)
    )
    _assert_instant(
        field["last_application_on"], "2026-08-01T00:00:00", "last_application_on"
    )

    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], ADMIN_HEADERS)
    )
    assert_quantity(
        operation["recorded_annual_manure_gallons"], 414396.00, "records total"
    )


# ---------------------------------------------------------------------------
# Certification order
# ---------------------------------------------------------------------------
def test_certification_reports_short_storage_before_the_missing_budget():
    """A plan with no budgets on an operation with only 48 days of storage fails
    on the storage aggregate, which is the earlier check.

    PRD: "When a single request could fail several checks, the outcome must be the error belonging to the **earliest** applicable check in the ordering below."
    PRD: "And the operation's `design_storage_days` must be at least 180 — a full winter-plus of storage — or the request is refused with `ERR_INSUFFICIENT_STORAGE_DAYS`."
    PRD: "At least one field nutrient budget must exist for the plan, or the request is refused with `ERR_NO_FIELD_BUDGETS`."
    Design: Corner/validations/certification_evaluates_the_storage_aggregate_before_the_budget_check
    """
    ctx = setup_scenario("DRAFT_PLAN", storage=SMALL_POND)

    # 6000 sq ft x 12 ft x 7.4805 gives 538596.00, less an 89766.00 reserve.
    assert_storage_capacities(
        ctx["storage"], design=538596.00, reserve=89766.00, operating=448830.00
    )
    operation = validate_success(
        api_client.get_operation(ctx["operation"]["id"], ADMIN_HEADERS)
    )
    assert operation["design_storage_days"] == 48, (
        f"design_storage_days: expected 48, got {operation['design_storage_days']}"
    )

    validate_error(
        api_client.certify_nutrient_plan(ctx["plan"]["id"], PLANNER_HEADERS),
        ApiErrorId.ERR_INSUFFICIENT_STORAGE_DAYS,
    )

    plan = validate_success(
        api_client.get_nutrient_plan(ctx["plan"]["id"], PLANNER_HEADERS)
    )
    assert_state(plan, "plan_status", "DRAFT")
    assert_null(plan, "certified_at", "certifying_planner_user_id")


def test_a_renewal_before_the_window_opens_is_refused():
    """Coverage effective 2026-01-01 expires 2031-01-01 and its window opens
    2030-07-05, so a renewal on 2026-08-01 is far too early.

    PRD: "It is admissible only once the logical clock has reached or passed `renewal_window_opens_on`; an earlier attempt is refused with `ERR_RENEWAL_WINDOW_NOT_OPEN`."
    Design: Corner/validations/certification_evaluates_the_storage_aggregate_before_the_budget_check
    """
    ctx = setup_scenario("DRAFT_PLAN", storage=SMALL_POND)
    permit_id = ctx["permit"]["id"]
    operator_headers = ctx["operator_headers"]

    _assert_instant(
        ctx["permit"]["renewal_window_opens_on"],
        "2030-07-05T00:00:00",
        "renewal_window_opens_on",
    )

    validate_error(
        api_client.initiate_permit_renewal(permit_id, operator_headers),
        ApiErrorId.ERR_RENEWAL_WINDOW_NOT_OPEN,
    )

    permit = validate_success(api_client.get_permit(permit_id, operator_headers))
    assert_state(permit, "coverage_status", "COVERED")
    assert_null(permit, "renewal_submitted_at")
