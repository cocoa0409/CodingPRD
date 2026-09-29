"""Preventive maintenance: the annual-hours formula, capacity and the spare ledger."""
from test_helpers import (
    abort_install_payload,
    add_order_line,
    add_partner_ctx,
    arrive_ctx,
    complete_install_ctx,
    complete_maintenance_visit,
    complete_production,
    complete_production_ctx,
    complete_visit_payload,
    confirm_ctx,
    confirm_order,
    cancel_maintenance_visit,
    list_all,
    maintenance_visit_payload,
    make_service_partner_tech_headers,
    new_facility,
    new_install_job,
    new_maintenance_visit,
    new_order,
    new_order_line,
    new_pm_program,
    new_service_partner,
    quote_ctx,
    quote_order,
    read_install_job,
    read_maintenance_visit,
    read_order,
    read_pm_program,
    read_serialized_asset,
    read_service_partner,
    receive_parts,
    report_usage,
    schedule_install_ctx,
    set_logical_clock,
    setup_active_pm_program,
    setup_configured_order,
    setup_installed_order,
    setup_released_revision,
    terminate_program_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

FIRST_VISIT_DATE = "2026-09-20T09:00:00Z"
SECOND_VISIT_DATE = "2026-09-27T09:00:00Z"
LATER_WINDOW = ("2026-09-15T08:00:00Z", "2026-09-15T11:00:00Z")


def _s500_platinum_estate():
    """One institutional press in service under a PLATINUM 180-day programme."""
    ctx = setup_installed_order(
        preset="S500", quantity=1,
        facility_overrides={"account_name": "Ironworks Institute",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    ctx["program"] = setup_active_pm_program(
        ctx["facility"]["id"], ctx["partner"]["id"], tier="PLATINUM",
        visit_interval_days=180,
    )
    return ctx


def test_a_light_user_is_floored_at_the_nominal_service_burden(api):
    """An asset reporting no usage still costs the full nominal visit hours.

    The PRD states that a usage factor is derived from the reported
    `annual_usage_hours` "divided by the nominal norm of 2,000 hours per year, then
    clamped by a nested pair of bounds: the inner bound raises anything below one up
    to one, and the outer bound lowers anything above two down to two."

    Design: Difficulty/combinatorial_formula/pm_annual_hours_nested_usage_clamp_both_arms
    """
    ctx = _s500_platinum_estate()
    assert read_order(ctx["order"]["id"])["quoted_total_cents"] == 443_846
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["status"] == "IN_SERVICE"
    assert asset["annual_usage_hours"] == 0

    program = read_pm_program(ctx["program"]["id"])

    assert program["status"] == "ACTIVE"
    assert program["tier"] == "PLATINUM"
    assert program["visit_interval_days"] == 180
    assert program["covered_asset_count"] == 1
    assert program["annual_labor_hours_committed"] == 2.88, (
        "0.6 strength hours at the floored factor 1.0, times 1.6, times 3 visits"
    )
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 2.88
    assert partner["coverage_status"] == "ACTIVE"


def test_an_interior_usage_ratio_is_capped_by_the_outer_bound(api):
    """Five thousand hours a year yields a ratio of 2.5 that is lowered to two.

    The PRD states that the per-asset hours are "the per-visit base hours for its
    model `category` — 1.0 hour for `CARDIO`, 0.6 hour for `STRENGTH`, 1.4 hours for
    `CONNECTED` — multiplied by its usage factor, multiplied by the tier multiplier
    (1.0 for `BASIC`, 1.25 for `PRO`, 1.6 for `PLATINUM`), multiplied by the visits
    per year."

    Design: Difficulty/combinatorial_formula/pm_annual_hours_nested_usage_clamp_both_arms
    """
    ctx = _s500_platinum_estate()
    assert read_pm_program(ctx["program"]["id"])["annual_labor_hours_committed"] == 2.88

    asset = report_usage(ctx["asset"]["id"], ctx["partner"]["id"],
                        annual_usage_hours=5000.0)

    assert asset["annual_usage_hours"] == 5000
    program = read_pm_program(ctx["program"]["id"])
    assert program["covered_asset_count"] == 1
    assert program["annual_labor_hours_committed"] == 5.76, (
        "the ratio 2.5 is lowered to the outer bound of two"
    )
    assert program["status"] == "ACTIVE"
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 5.76
    assert partner["coverage_status"] == "ACTIVE"


def test_a_heavier_user_does_not_push_the_commitment_past_the_cap(api):
    """Twelve thousand hours a year buys no more service than five thousand does.

    The PRD states that "usage below 2,000 hours and usage above 4,000 hours are both
    flat" and that "The asset contributions are summed exactly, and only the sum is
    rounded, half up, to two decimal places".

    Design: Difficulty/combinatorial_formula/pm_annual_hours_nested_usage_clamp_both_arms
    """
    ctx = _s500_platinum_estate()
    report_usage(ctx["asset"]["id"], ctx["partner"]["id"], annual_usage_hours=5000.0)
    assert read_pm_program(ctx["program"]["id"])["annual_labor_hours_committed"] == 5.76

    asset = report_usage(ctx["asset"]["id"], ctx["partner"]["id"],
                        annual_usage_hours=12000.0)

    assert asset["annual_usage_hours"] == 12000
    program = read_pm_program(ctx["program"]["id"])
    assert program["annual_labor_hours_committed"] == 5.76
    assert program["annual_labor_hours_committed"] != 17.28, (
        "an unclamped factor of six would have tripled the commitment"
    )
    assert read_service_partner(ctx["partner"]["id"])["committed_hours"] == 5.76


def _capped_partner_and_two_facilities():
    """Two installed facilities plus a spare crew certified for only 12.50 hours."""
    first = setup_installed_order(
        preset="T900", quantity=2,
        facility_overrides={"account_name": "Ashgrove Athletic Club",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Northwind Service Co"},
    )
    second = setup_installed_order(
        revision_ctx=first, quantity=1,
        facility_overrides={"account_name": "Brookside Athletic Club",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Southwind Service Co"},
    )
    capped = new_service_partner(name="Ridgeline Service Co",
                                 certified_categories=["CARDIO"],
                                 certified_hours_capacity=12.50)
    return {"first": first, "second": second, "capped": capped}


def test_activation_landing_exactly_on_the_certified_capacity_succeeds(
    api, service_ops_admin_headers
):
    """Two treadmills ask for 12.50 hours from a crew certified for 12.50.

    The PRD states that `coverage_status` "is `OVER_COMMITTED` exactly when
    `committed_hours` is strictly greater than `certified_hours_capacity`, and
    `ACTIVE` otherwise. Equality is not over-commitment."

    Design: Difficulty/boundary_precision_check/partner_capacity_equality_allowed_then_exceeded
    """
    estate = _capped_partner_and_two_facilities()
    capped = estate["capped"]
    assert capped["certified_hours_capacity"] == 12.50
    assert read_service_partner(capped["id"])["committed_hours"] == 0
    program = new_pm_program(estate["first"]["facility"]["id"], capped["id"],
                             tier="PRO", visit_interval_days=90)

    activated = validate_success(
        api.activate_pm_program(program["id"], service_ops_admin_headers)
    )

    assert activated["status"] == "ACTIVE"
    assert activated["covered_asset_count"] == 2
    assert activated["annual_labor_hours_committed"] == 12.50
    partner = read_service_partner(capped["id"])
    assert partner["committed_hours"] == 12.50
    assert partner["committed_hours"] == partner["certified_hours_capacity"]
    assert partner["coverage_status"] == "ACTIVE"
    assert read_service_partner(estate["first"]["partner"]["id"])[
        "committed_hours"
    ] == 0, "a completed install job consumes no capacity"


def test_a_second_programme_that_would_exceed_the_capacity_is_refused(
    api, service_ops_admin_headers
):
    """Six and a quarter hours more than the exact capacity is over-commitment.

    The PRD states that activation requires "the partner's existing
    `committed_hours` plus this program's `annual_labor_hours_committed` must be less
    than or equal to its `certified_hours_capacity`, equality allowed
    (`ERR_PARTNER_CAPACITY_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/partner_capacity_equality_allowed_then_exceeded
    """
    estate = _capped_partner_and_two_facilities()
    capped = estate["capped"]
    setup_active_pm_program(estate["first"]["facility"]["id"], capped["id"],
                            tier="PRO", visit_interval_days=90)
    assert read_service_partner(capped["id"])["committed_hours"] == 12.50
    second = new_pm_program(estate["second"]["facility"]["id"], capped["id"],
                            tier="PRO", visit_interval_days=90)
    assert second["status"] == "DRAFT"

    response = api.activate_pm_program(second["id"], service_ops_admin_headers)

    validate_error(response, "ERR_PARTNER_CAPACITY_EXCEEDED", 409)
    refused = read_pm_program(second["id"])
    assert refused["status"] == "DRAFT"
    assert refused["annual_labor_hours_committed"] == 0
    assert refused["covered_asset_count"] == 0
    partner = read_service_partner(capped["id"])
    assert partner["committed_hours"] == 12.50, "the rejection changed nothing"
    assert partner["coverage_status"] == "ACTIVE"
    assert 12.50 + 6.25 == 18.75 > partner["certified_hours_capacity"]


def _visit_holding_three_units():
    """A crew whose training lapses on 1 October, holding three spare units."""
    ctx = setup_installed_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Harbourview Gym", "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co",
                           "training_current_until": "2026-10-01T00:00:00Z"},
    )
    ctx["program"] = setup_active_pm_program(ctx["facility"]["id"],
                                             ctx["partner"]["id"], tier="PRO",
                                             visit_interval_days=90)
    receive_parts(ctx["partner"]["id"], 8)
    ctx["visit"] = new_maintenance_visit(ctx["program"]["id"], ctx["asset"]["id"],
                                         ctx["partner"]["id"],
                                         scheduled_date=FIRST_VISIT_DATE,
                                         reserved_units=3)
    return ctx


def test_visit_completion_is_refused_once_the_partner_training_has_lapsed(api):
    """A day past the training date the visit cannot be closed and holds its units.

    The PRD states that completing a visit "requires the owning program to be
    `ACTIVE` and the partner's `training_current_until` to be strictly after the
    logical clock."

    Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_lapsed_partner_training
    """
    ctx = _visit_holding_three_units()
    assert ctx["visit"]["status"] == "SCHEDULED"
    assert ctx["visit"]["reserved_units"] == 3
    set_logical_clock("2026-10-02T00:00:00Z")

    response = api.complete_maintenance_visit(
        ctx["visit"]["id"], complete_visit_payload(labor_hours=2.0),
        make_service_partner_tech_headers(ctx["partner"]["id"]),
    )

    validate_error(response, "ERR_PARTNER_TRAINING_EXPIRED", 409)
    visit = read_maintenance_visit(ctx["visit"]["id"])
    assert visit["status"] == "SCHEDULED"
    assert visit["labor_hours"] is None
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["spare_stock_received_units"] == 8
    assert partner["spare_stock_reserved_units"] == 3
    assert partner["spare_stock_consumed_units"] == 0
    assert partner["spare_stock_on_hand_units"] == 5
    assert partner["training_current_until"] == "2026-10-01T00:00:00Z"
    assert partner["committed_hours"] == 6.25
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["service_history_count"] == 0
    assert asset["accrued_service_labor_hours"] == 0
    program = read_pm_program(ctx["program"]["id"])
    assert program["status"] == "ACTIVE"
    assert program["annual_labor_hours_committed"] == 6.25


def test_the_same_completion_succeeds_while_the_training_is_still_current(api):
    """One day earlier the identical call closes the visit and consumes the units.

    The PRD states that on completion "the visit's `reserved_units` shift from the
    partner's `spare_stock_reserved_units` into `spare_stock_consumed_units`, and the
    serviced asset's `service_history_count` and `accrued_service_labor_hours` are
    recomputed".

    Design: Difficulty/cross_entity_state_dependency/visit_completion_blocked_by_lapsed_partner_training
    """
    ctx = _visit_holding_three_units()
    set_logical_clock("2026-09-30T00:00:00Z")

    visit = complete_maintenance_visit(ctx["visit"]["id"], ctx["partner"]["id"],
                                       labor_hours=2.0)

    assert visit["status"] == "COMPLETED"
    assert visit["labor_hours"] == 2.0
    assert visit["reserved_units"] == 3
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["spare_stock_received_units"] == 8
    assert partner["spare_stock_reserved_units"] == 0
    assert partner["spare_stock_consumed_units"] == 3
    assert partner["spare_stock_on_hand_units"] == 5
    asset = read_serialized_asset(ctx["asset"]["id"])
    assert asset["service_history_count"] == 1
    assert asset["accrued_service_labor_hours"] == 2.0
    assert read_pm_program(ctx["program"]["id"])["status"] == "ACTIVE"


def _two_visit_estate(first_units=5, second_units=12, received=20):
    """Two in-service treadmills, a stocked crew and two visits holding units."""
    ctx = setup_installed_order(
        preset="T900", quantity=2,
        facility_overrides={"account_name": "Lakeside Fitness Collective",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    ctx["program"] = setup_active_pm_program(ctx["facility"]["id"],
                                             ctx["partner"]["id"], tier="PRO",
                                             visit_interval_days=90)
    receive_parts(ctx["partner"]["id"], received)
    assets = sorted(ctx["assets"], key=lambda asset: asset["sequence_no"])
    ctx["first_asset"], ctx["second_asset"] = assets[0], assets[1]
    ctx["first_visit"] = new_maintenance_visit(
        ctx["program"]["id"], ctx["first_asset"]["id"], ctx["partner"]["id"],
        scheduled_date=FIRST_VISIT_DATE, reserved_units=first_units,
    )
    ctx["second_visit"] = new_maintenance_visit(
        ctx["program"]["id"], ctx["second_asset"]["id"], ctx["partner"]["id"],
        scheduled_date=SECOND_VISIT_DATE, reserved_units=second_units,
    )
    return ctx


def _assert_stock(partner, received, reserved, consumed, on_hand):
    assert partner["spare_stock_received_units"] == received
    assert partner["spare_stock_reserved_units"] == reserved
    assert partner["spare_stock_consumed_units"] == consumed
    assert partner["spare_stock_on_hand_units"] == on_hand
    assert received == on_hand + reserved + consumed


def test_no_spare_unit_is_created_or_destroyed_across_the_whole_ledger(api):
    """A refusal, a completion and a cancellation all keep the four buckets balanced.

    The PRD states that after every mutation of the spare stock ledger "the on-hand
    figure must be greater than or equal to zero, and the received total must equal
    the on-hand total plus the reserved total plus the consumed total."

    Design: Difficulty/compensating_invariant/spare_stock_ledger_conserved_across_reserve_consume_release
    """
    ctx = _two_visit_estate()
    partner_id = ctx["partner"]["id"]
    _assert_stock(read_service_partner(partner_id), 20, 17, 0, 3)

    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(ctx["program"]["id"], ctx["first_asset"]["id"],
                                      scheduled_date="2026-10-04T09:00:00Z",
                                      reserved_units=5),
            make_service_partner_tech_headers(partner_id),
        ),
        "ERR_INSUFFICIENT_PART_STOCK", 409,
    )
    _assert_stock(read_service_partner(partner_id), 20, 17, 0, 3)

    completed = complete_maintenance_visit(ctx["first_visit"]["id"], partner_id,
                                           labor_hours=2.0)
    assert completed["status"] == "COMPLETED"
    assert completed["labor_hours"] == 2.0
    _assert_stock(read_service_partner(partner_id), 20, 12, 5, 3)

    cancelled = cancel_maintenance_visit(ctx["second_visit"]["id"])

    assert cancelled["status"] == "CANCELLED"
    _assert_stock(read_service_partner(partner_id), 20, 0, 5, 15)
    first_asset = read_serialized_asset(ctx["first_asset"]["id"])
    assert first_asset["service_history_count"] == 1
    assert first_asset["accrued_service_labor_hours"] == 2.0
    second_asset = read_serialized_asset(ctx["second_asset"]["id"])
    assert second_asset["service_history_count"] == 0
    assert second_asset["accrued_service_labor_hours"] == 0
    assert read_pm_program(ctx["program"]["id"])[
        "annual_labor_hours_committed"
    ] == 12.50
    assert read_service_partner(partner_id)["committed_hours"] == 12.50


def test_a_reservation_may_take_the_last_unit_but_not_one_more(api):
    """Three on hand accepts a request for three and refuses a request for four.

    The PRD states that when a visit is booked "the partner's
    `spare_stock_on_hand_units` must be at least the requested `reserved_units`,
    otherwise `ERR_INSUFFICIENT_PART_STOCK`."

    Design: Difficulty/compensating_invariant/spare_stock_ledger_conserved_across_reserve_consume_release
    """
    ctx = _two_visit_estate()
    partner_id = ctx["partner"]["id"]
    tech_headers = make_service_partner_tech_headers(partner_id)

    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(ctx["program"]["id"], ctx["second_asset"]["id"],
                                      scheduled_date="2026-10-04T09:00:00Z",
                                      reserved_units=4),
            tech_headers,
        ),
        "ERR_INSUFFICIENT_PART_STOCK", 409,
    )
    accepted = validate_success(
        api.create_maintenance_visit(
            maintenance_visit_payload(ctx["program"]["id"], ctx["second_asset"]["id"],
                                      scheduled_date="2026-10-04T09:00:00Z",
                                      reserved_units=3),
            tech_headers,
        ),
        201,
    )

    assert accepted["status"] == "SCHEDULED"
    assert accepted["reserved_units"] == 3
    assert accepted["labor_hours"] is None
    assert accepted["held_reason"] is None
    _assert_stock(read_service_partner(partner_id), 20, 20, 0, 0)

    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(ctx["program"]["id"], ctx["second_asset"]["id"],
                                      scheduled_date="2026-10-11T09:00:00Z",
                                      reserved_units=1),
            tech_headers,
        ),
        "ERR_INSUFFICIENT_PART_STOCK", 409,
    )

    _assert_stock(read_service_partner(partner_id), 20, 20, 0, 0)


def test_terminating_a_programme_cancels_its_visits_and_returns_their_units(
    api, service_ops_admin_headers
):
    """One terminate call empties the reservation book and the commitment together.

    The PRD states that "Terminating an `ACTIVE` or a `NEEDS_REVISION` program moves
    every one of its visits in `SCHEDULED` or `ON_HOLD` to `CANCELLED`, releasing
    their held spare units, and then recomputes the partner's `committed_hours` and
    `coverage_status`".

    Design: Corner/state_machines/pm_program_terminate_cascades_visit_cancellation_and_stock_release
    """
    ctx = _two_visit_estate(first_units=5, second_units=6)
    partner_id = ctx["partner"]["id"]
    _assert_stock(read_service_partner(partner_id), 20, 11, 0, 9)
    assert read_service_partner(partner_id)["committed_hours"] == 12.50

    response = api.terminate_pm_program(
        ctx["program"]["id"],
        terminate_program_payload(
            terminate_reason="facility consolidated its service book"),
        service_ops_admin_headers,
    )

    program = validate_success(response)
    assert program["status"] == "TERMINATED"
    first = read_maintenance_visit(ctx["first_visit"]["id"])
    second = read_maintenance_visit(ctx["second_visit"]["id"])
    assert first["status"] == "CANCELLED"
    assert second["status"] == "CANCELLED"
    assert first["reserved_units"] == 5, "the recorded intent survives the release"
    assert second["reserved_units"] == 6
    partner = read_service_partner(partner_id)
    _assert_stock(partner, 20, 0, 0, 20)
    assert partner["committed_hours"] == 0
    assert partner["coverage_status"] == "ACTIVE"


def test_the_visits_per_year_ceiling_applies_across_two_equipment_categories(api):
    """A hundred-day interval buys four visits, not three and two thirds.

    The PRD states that "the number of visits per year is 365 divided by
    `visit_interval_days`" rounded up to a whole number of visits, and that "The
    asset contributions are summed exactly, and only the sum is rounded, half up, to
    two decimal places".

    Design: Corner/calculations/pm_hours_apply_the_visits_per_year_ceiling_across_mixed_categories
    """
    ctx = setup_configured_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Summit Athletic Club",
                            "freight_zone": "Z1"},
    )
    console = setup_released_revision(
        "C700", rig_overrides={"name": "RIG-B", "parallel_station_count": 2,
                               "supported_duty_classes": ["FULL_COMMERCIAL"]},
    )
    add_order_line(ctx, revision=console["revision"], model=console["model"],
                   quantity=1, layout_zone_label="Connected Row")
    quote_ctx(ctx)
    assert ctx["order"]["quoted_total_cents"] == 1_199_310
    confirm_ctx(ctx)
    complete_production_ctx(ctx)
    add_partner_ctx(ctx, name="Meridian Service Co")
    schedule_install_ctx(ctx)
    arrive_ctx(ctx)
    complete_install_ctx(ctx, actual_labor_hours=4.5, punch_list_open_count=0)

    program = setup_active_pm_program(ctx["facility"]["id"], ctx["partner"]["id"],
                                      tier="PLATINUM", visit_interval_days=100)

    assert program["status"] == "ACTIVE"
    assert program["tier"] == "PLATINUM"
    assert program["visit_interval_days"] == 100
    assert program["covered_asset_count"] == 2
    assert program["annual_labor_hours_committed"] == 15.36, (
        "6.40 cardio hours plus 8.96 connected hours over four visits"
    )
    for asset in ctx["assets"]:
        assert asset["status"] == "IN_SERVICE"
        assert asset["annual_usage_hours"] == 0
    partner = read_service_partner(ctx["partner"]["id"])
    assert partner["committed_hours"] == 15.36
    assert partner["coverage_status"] == "ACTIVE"


def test_committed_hours_counts_open_jobs_and_live_programmes_only(
    api, service_ops_admin_headers, order_planner_headers
):
    """A completed job, an aborted job and a terminated programme all drop out.

    The PRD states that `committed_hours` "is the sum of `estimated_labor_hours` over
    that partner's install jobs whose `status` is `SCHEDULED`, `ON_SITE` or
    `PUNCH_LIST`, plus the sum of `annual_labor_hours_committed` over that partner's
    maintenance programs whose `status` is `ACTIVE` or `NEEDS_REVISION`."

    Design: Corner/calculations/partner_committed_hours_count_only_open_jobs_and_live_programs
    """
    ctx = setup_installed_order(
        preset="T900", quantity=1,
        facility_overrides={"account_name": "Riverbend Fitness Collective",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    partner_id = ctx["partner"]["id"]
    assert read_install_job(ctx["install_job"]["id"])["status"] == "COMPLETED"
    program = setup_active_pm_program(ctx["facility"]["id"], partner_id, tier="PRO",
                                      visit_interval_days=90)
    assert program["annual_labor_hours_committed"] == 6.25
    assert read_service_partner(partner_id)["committed_hours"] == 6.25

    second_order = new_order(ctx["facility"]["id"])
    new_order_line(second_order["id"], ctx["revision"]["id"], quantity=1,
                   layout_zone_label="Cardio Zone B")
    quote_order(second_order["id"])
    confirm_order(second_order["id"])
    complete_production(second_order["id"])
    second_job = new_install_job(second_order["id"], partner_id, *LATER_WINDOW,
                                 estimated_labor_hours=1.5)
    assert read_service_partner(partner_id)["committed_hours"] == 7.75

    aborted = validate_success(
        api.abort_install_job(second_job["id"],
                              abort_install_payload(
                                  abort_reason="crew reassigned to a storm callout"),
                              order_planner_headers)
    )
    assert aborted["status"] == "ABORTED"
    assert read_service_partner(partner_id)["committed_hours"] == 6.25
    assert read_order(second_order["id"])["fulfillment_status"] == "STAGED"

    terminated = validate_success(
        api.terminate_pm_program(
            program["id"],
            terminate_program_payload(
                terminate_reason="facility consolidated its service book"),
            service_ops_admin_headers)
    )

    assert terminated["status"] == "TERMINATED"
    partner = read_service_partner(partner_id)
    assert partner["committed_hours"] == 0
    assert partner["coverage_status"] == "ACTIVE"


def test_a_parts_receipt_adds_to_stock_without_touching_the_reservations(api):
    """Two receipts accumulate on hand and leave reserved and consumed at zero.

    The PRD states that "`spare_stock_received_units` is the total of the `units`
    figures across every parts receipt posted to that partner" and that
    "`spare_stock_on_hand_units` is the received total minus the reserved total minus
    the consumed total."

    Design: Corner/endpoints/parts_receipt_accumulates_stock_without_touching_reservations
    """
    partner = new_service_partner(name="Meridian Service Co",
                                  certified_categories=["CARDIO"])
    _assert_stock(partner, 0, 0, 0, 0)

    first = receive_parts(partner["id"], 12)

    _assert_stock(first, 12, 0, 0, 12)

    second = receive_parts(partner["id"], 8)

    _assert_stock(second, 20, 0, 0, 20)
    reread = read_service_partner(partner["id"])
    _assert_stock(reread, 20, 0, 0, 20)
    assert reread["committed_hours"] == 0, "stock does not touch capacity"
    assert reread["coverage_status"] == "ACTIVE"


def test_a_visit_covers_only_an_in_service_asset_of_its_own_facility(
    api, service_ops_admin_headers
):
    """A built unit and another facility's unit are both outside the programme.

    The PRD states that when a visit is booked "the asset's `facility_id` must equal
    the program's `facility_id` and the asset's `status` must be `IN_SERVICE`,
    otherwise `ERR_ASSET_NOT_COVERED`".

    Design: Corner/validations/maintenance_visit_asset_must_be_in_service_at_the_program_facility
    """
    ctx = setup_installed_order(
        preset="T900", quantity=2,
        facility_overrides={"account_name": "Lakeside Fitness Collective",
                            "freight_zone": "Z1"},
        partner_overrides={"name": "Meridian Service Co"},
    )
    partner_id = ctx["partner"]["id"]
    tech_headers = make_service_partner_tech_headers(partner_id)
    program = setup_active_pm_program(ctx["facility"]["id"], partner_id, tier="PRO",
                                      visit_interval_days=90)
    in_service = sorted(ctx["assets"], key=lambda asset: asset["sequence_no"])[0]
    staged_order = new_order(ctx["facility"]["id"])
    new_order_line(staged_order["id"], ctx["revision"]["id"], quantity=1,
                   layout_zone_label="Cardio Zone B")
    quote_order(staged_order["id"])
    confirm_order(staged_order["id"])
    complete_production(staged_order["id"])
    built = [asset for asset
             in list_all(api.list_serialized_assets,
                         {"facility_id": ctx["facility"]["id"]})
             if asset["status"] == "BUILT"]
    assert len(built) == 1
    other_facility = new_facility(account_name="Brookside Athletic Club",
                                  freight_zone="Z1")
    other_program = setup_active_pm_program(other_facility["id"], partner_id,
                                            tier="PRO", visit_interval_days=90)

    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(program["id"], built[0]["id"],
                                      scheduled_date="2026-10-04T09:00:00Z",
                                      reserved_units=0),
            tech_headers,
        ),
        "ERR_ASSET_NOT_COVERED", 422,
    )
    validate_error(
        api.create_maintenance_visit(
            maintenance_visit_payload(other_program["id"], in_service["id"],
                                      scheduled_date="2026-10-04T09:00:00Z",
                                      reserved_units=0),
            tech_headers,
        ),
        "ERR_ASSET_NOT_COVERED", 422,
    )
    accepted = validate_success(
        api.create_maintenance_visit(
            maintenance_visit_payload(program["id"], in_service["id"],
                                      scheduled_date="2026-10-11T09:00:00Z",
                                      reserved_units=0),
            tech_headers,
        ),
        201,
    )

    assert accepted["status"] == "SCHEDULED"
    assert accepted["serialized_asset_id"] == in_service["id"]
    _, meta = validate_paginated(
        api.list_maintenance_visits(service_ops_admin_headers)
    )
    assert meta["total_count"] == 1
    assert read_pm_program(program["id"])["covered_asset_count"] == 2
    assert read_pm_program(other_program["id"])["covered_asset_count"] == 0
    unbuilt = read_serialized_asset(built[0]["id"])
    assert unbuilt["status"] == "BUILT"
    assert unbuilt["warranty_starts_at"] is None
