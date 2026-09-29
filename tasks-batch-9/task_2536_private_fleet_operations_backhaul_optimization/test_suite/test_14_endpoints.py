"""Endpoint surfaces: the expiry sweep, the two pure reads, the PM patch and re-linking."""

from test_helpers import (
    MAINTENANCE,
    MANAGER,
    PAYROLL,
    PLANNER,
    ApiErrorId,
    accept_offer,
    add_delivery_stop,
    add_other_stop,
    assign_resources,
    close_out_trip,
    dispatch_trip,
    link_offer,
    new_backhaul_offer,
    new_domicile,
    new_store,
    new_tractor,
    new_trip,
    plan_trip,
    read_offer,
    read_trip,
    review_offer,
    run_stop,
    set_clock,
    setup_base_fleet,
    validate_error,
    validate_paginated,
    validate_success,
)


# ----------------------------------------- the sweep retires the due and skips the rest ----


def _four_offers_and_one_linked_trip():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-E1")
    store = new_store(store_code="S-6001")
    trip = new_trip(domicile["id"], trip_code="TRIP-E1",
                    planned_start_at="2026-08-20T06:00:00Z")
    due_proposed = new_backhaul_offer(
        store["id"], shipper_name="Prairie Foods",
        pickup_window_start="2026-08-03T12:00:00Z",
        pickup_window_end="2026-08-03T20:00:00Z",
        offer_expires_at="2026-08-05T00:00:00Z",
    )
    due_reviewed = new_backhaul_offer(
        store["id"], origin_kind="THIRD_PARTY", shipper_name="Lakeshore Brokerage",
        revenue_cents=58000, cases=400, weight_lbs=9000, deadhead_miles=30,
        loaded_miles=150, pickup_window_start="2026-08-03T12:00:00Z",
        pickup_window_end="2026-08-03T20:00:00Z",
        offer_expires_at="2026-08-05T00:00:00Z",
    )
    not_due = new_backhaul_offer(
        store["id"], shipper_name="Northline Mills", revenue_cents=61000, cases=450,
        weight_lbs=9900, deadhead_miles=35, loaded_miles=165,
        pickup_window_start="2026-09-02T12:00:00Z",
        pickup_window_end="2026-09-02T20:00:00Z",
        offer_expires_at="2026-09-10T00:00:00Z",
    )
    rejected = new_backhaul_offer(
        store["id"], origin_kind="THIRD_PARTY", shipper_name="Cedar Freight",
        revenue_cents=45000, cases=300, weight_lbs=6600, deadhead_miles=60,
        loaded_miles=140, pickup_window_start="2026-08-03T12:00:00Z",
        pickup_window_end="2026-08-03T20:00:00Z",
        offer_expires_at="2026-08-05T00:00:00Z",
    )
    review_offer(due_reviewed["id"])
    review_offer(rejected["id"])
    return {"trip": trip, "trip_v0": trip["version"], "due_proposed": due_proposed,
            "due_reviewed": due_reviewed, "not_due": not_due, "rejected": rejected}


def _arm_the_sweep(api, ctx):
    validate_success(
        api.reject_offer(ctx["rejected"]["id"], {"reason_code": "MARGIN_TOO_THIN"}, MANAGER)
    )
    linked = link_offer(ctx["trip"]["id"], ctx["due_reviewed"]["id"], ctx["trip_v0"])
    assert linked["backhaul_offer_id"] == ctx["due_reviewed"]["id"]
    assert linked["backhaul_credit_cents"] == 0
    set_clock("2026-08-10T00:00:00Z")


def test_the_sweep_retires_both_live_statuses_and_ignores_the_terminal_one(api):
    """PRD §3.6: "Expiry is a bulk sweep run by a `TransportManager`: every offer in `PROPOSED`
    or `UNDER_REVIEW` whose `offer_expires_at` is at or before the logical clock moves to
    `EXPIRED`, and each swept offer is unlinked from its trip with that trip's
    `backhaul_offer_id` cleared to null and its `backhaul_credit_cents` zeroed. Offers not yet
    due are skipped, not failed, and the sweep reports what it did as an `expired_count`, an
    `expired_offer_ids` list and an `unlinked_trip_ids` list."

    Design: Corner/endpoints/the_expiration_sweep_skips_what_it_cannot_expire_and_unlinks_what_it_does
    """
    ctx = _four_offers_and_one_linked_trip()
    _arm_the_sweep(api, ctx)

    swept = validate_success(api.run_offer_expiration_sweep(MANAGER))
    assert swept["expired_count"] == 2
    assert set(swept["expired_offer_ids"]) == {ctx["due_proposed"]["id"],
                                              ctx["due_reviewed"]["id"]}
    assert swept["unlinked_trip_ids"] == [ctx["trip"]["id"]]

    assert read_offer(ctx["due_proposed"]["id"])["status"] == "EXPIRED"
    assert read_offer(ctx["due_reviewed"]["id"])["status"] == "EXPIRED"
    # An equally overdue offer that is already terminal is skipped, not re-terminated.
    assert read_offer(ctx["rejected"]["id"])["status"] == "REJECTED"
    assert read_offer(ctx["not_due"]["id"])["status"] == "PROPOSED"


def test_a_second_sweep_is_a_no_op_and_the_unlink_is_a_real_write(api):
    """PRD §3.6: "Offers not yet due are skipped, not failed, and the sweep reports what it did
    as an `expired_count`, an `expired_offer_ids` list and an `unlinked_trip_ids` list." And
    PRD §3.6: "Expiry is a bulk sweep run by a `TransportManager`: every offer in `PROPOSED` or
    `UNDER_REVIEW` whose `offer_expires_at` is at or before the logical clock moves to
    `EXPIRED`, and each swept offer is unlinked from its trip with that trip's
    `backhaul_offer_id` cleared to null and its `backhaul_credit_cents` zeroed."

    Design: Corner/endpoints/the_expiration_sweep_skips_what_it_cannot_expire_and_unlinks_what_it_does
    """
    ctx = _four_offers_and_one_linked_trip()
    _arm_the_sweep(api, ctx)
    validate_success(api.run_offer_expiration_sweep(MANAGER))

    again = validate_success(api.run_offer_expiration_sweep(MANAGER))
    assert again["expired_count"] == 0
    assert again["expired_offer_ids"] == []
    assert again["unlinked_trip_ids"] == []

    stripped = read_trip(ctx["trip"]["id"])
    assert stripped["backhaul_offer_id"] is None
    assert stripped["backhaul_credit_cents"] == 0
    assert stripped["version"] > ctx["trip_v0"]

    rows, meta = validate_paginated(
        api.list_backhaul_offers(PLANNER, {"status": "EXPIRED", "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 2
    assert {row["id"] for row in rows} == {ctx["due_proposed"]["id"],
                                          ctx["due_reviewed"]["id"]}


# --------------------------------------------------- the preview reconciles and mutates ----


def _trip_that_ran_exactly_to_plan(api):
    ctx = setup_base_fleet(
        "e2",
        pay_plan_overrides={"plan_code": "MILE-Z", "minimum_daily_cents": 0},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-E2",
                    planned_start_at="2026-08-20T06:00:00Z")
    delivery = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                                 "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    drop = add_other_stop(trip["id"], "DROP_OFF", 2, "2026-08-20T10:00:00Z",
                          "2026-08-20T10:20:00Z", 45, 30)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    committed = plan_trip(trip["id"])
    assert committed["total_miles"] == 130
    assert committed["planned_duty_minutes"] == 260
    assert committed["planned_pay_cents"] == 13800
    dispatch_trip(trip["id"])
    run_stop(delivery["id"], ctx["driver"]["id"], cases_handled=600)
    run_stop(drop["id"], ctx["driver"]["id"])
    closed = close_out_trip(trip["id"], 165, 260)
    assert closed["driver_pay_cents"] == 13800
    return ctx, trip, committed, closed


def test_the_preview_reports_the_pinned_plan_and_the_full_breakdown(api):
    """PRD §3.8: "Either variant may also be evaluated on demand, without persisting anything,
    by naming it in a `variant` parameter on the trip's pay preview; that read returns the
    `variant` it evaluated, the `pay_plan_id` and `pay_plan_version` it used, and the full
    breakdown as `mileage_cents`, `activity_cents`, `hourly_cents`, `bonus_cents`,
    `subtotal_cents`, `guarantee_makeup_cents` and `gross_cents`." And PRD §3.8: "Note the
    structural consequence: under `PLANNED_ACCRUAL` the duty basis *is* the planned duty figure,
    so detention is always zero and the hourly component is always zero."

    Design: Corner/endpoints/the_pay_preview_is_a_pure_read_that_reconciles_with_the_persisted_statement
    """
    ctx, trip, committed, _closed = _trip_that_ran_exactly_to_plan(api)
    preview = validate_success(api.get_pay_preview(trip["id"], PAYROLL,
                                        {"variant": "PLANNED_ACCRUAL"}))
    assert preview["variant"] == "PLANNED_ACCRUAL"
    assert preview["pay_plan_id"] == ctx["pay_plan"]["id"]
    assert preview["pay_plan_version"] == committed["pinned_pay_plan_version"]
    assert preview["mileage_cents"] == 10400
    assert preview["activity_cents"] == 3400  # one paid stop plus one drop-hook
    assert preview["hourly_cents"] == 0
    assert preview["bonus_cents"] == 0
    assert preview["subtotal_cents"] == 13800
    assert preview["guarantee_makeup_cents"] == 0
    assert preview["gross_cents"] == 13800


def test_three_previews_mint_nothing_and_agree_with_the_statement(api):
    """PRD §3.8: "`FINAL_SETTLEMENT` runs at close-out and at re-accrual, writes the trip's
    `driver_pay_cents`, and is the only variant ever persisted on a pay statement." And PRD
    §3.8: "Either variant may also be evaluated on demand, without persisting anything, by
    naming it in a `variant` parameter on the trip's pay preview; that read returns the
    `variant` it evaluated, the `pay_plan_id` and `pay_plan_version` it used, and the full
    breakdown as `mileage_cents`, `activity_cents`, `hourly_cents`, `bonus_cents`,
    `subtotal_cents`, `guarantee_makeup_cents` and `gross_cents`."

    Design: Corner/endpoints/the_pay_preview_is_a_pure_read_that_reconciles_with_the_persisted_statement
    """
    _ctx, trip, _committed, closed = _trip_that_ran_exactly_to_plan(api)
    first = validate_success(api.get_pay_preview(trip["id"], MANAGER,
                                        {"variant": "FINAL_SETTLEMENT"}))
    assert first["mileage_cents"] == 10400
    assert first["activity_cents"] == 3400
    assert first["hourly_cents"] == 0  # 260 - 260 - 30 grace is negative
    assert first["gross_cents"] == 13800

    second = validate_success(api.get_pay_preview(trip["id"], MANAGER,
                                        {"variant": "FINAL_SETTLEMENT"}))
    assert second["gross_cents"] == first["gross_cents"]
    assert read_trip(trip["id"])["version"] == closed["version"]

    rows, meta = validate_paginated(
        api.list_pay_statements(PAYROLL, {"trip_id": trip["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["gross_cents"] == 13800 == closed["driver_pay_cents"]


# ------------------------------------------------ the benchmark is driven by its window ----


def _one_completed_trip_of_a_domicile(api):
    ctx = setup_base_fleet(
        "e3",
        domicile_overrides={"domicile_code": "DOM-E3"},
        pay_plan_overrides={"plan_code": "MILE-Z", "minimum_daily_cents": 0},
    )
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-E3",
                    planned_start_at="2026-08-20T06:00:00Z")
    stop = add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                             "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    plan_trip(trip["id"])
    dispatch_trip(trip["id"])
    run_stop(stop["id"], ctx["driver"]["id"], cases_handled=600)
    closed = close_out_trip(trip["id"], 120, 195)
    assert closed["settlement_status"] == "ACCRUED"
    assert closed["driver_pay_cents"] == 10000
    return ctx, trip


def test_the_benchmark_reports_every_declared_field_of_the_incremental_variant(api):
    """PRD §3.8: "From that set: `total_miles` is the sum of the included trips' `total_miles`.
    `total_cases` is the sum of `cases` over those trips' stops whose status is `COMPLETED` and
    whose `stop_type` is `DELIVERY`. `driver_pay_cents` is the sum of `gross_cents` over those
    trips' pay statements whose own status is `ACCRUED` or `SETTLED`, so reversed statements
    contribute nothing. `fuel_cents` is `total_miles` multiplied by 62 cents per mile, rounded
    half up. `maintenance_cents` is `total_miles` multiplied by 19 cents per mile, rounded half
    up." And PRD §3.8: "Under the `INCREMENTAL_VARIABLE` variant — the comparison to make when
    deciding whether to take one more load on equipment already owned — `total_cost_cents` is
    `variable_cost_cents` alone, with all fixed and overhead cost excluded."

    Design: Corner/endpoints/the_cost_benchmark_read_reports_every_declared_field_on_a_half_open_window
    """
    ctx, _trip = _one_completed_trip_of_a_domicile(api)
    report = validate_success(
        api.get_cost_benchmark(ctx["domicile"]["id"], MANAGER,
                              {"variant": "INCREMENTAL_VARIABLE",
                               "window_start": "2026-08-20T00:00:00Z",
                               "window_end": "2026-08-21T00:00:00Z"})
    )
    assert report["variant"] == "INCREMENTAL_VARIABLE"
    assert report["window_days"] == 1
    assert report["trip_count"] == 1
    assert report["total_miles"] == 100
    assert report["total_cases"] == 600
    assert report["driver_pay_cents"] == 10000
    assert report["fuel_cents"] == 6200
    assert report["maintenance_cents"] == 1900
    assert report["backhaul_credit_cents"] == 0
    assert report["variable_cost_cents"] == 18100
    # The fixed pool is still reported even though this variant excludes it from the total.
    assert report["fixed_cost_cents"] == 13000
    assert report["total_cost_cents"] == 18100
    assert report["cost_per_case_cents"] == 30
    assert report["cost_per_mile_cents"] == 181
    assert report["dedicated_equivalent_cents_per_case"] == 205
    assert report["advantage_cents_per_case"] == 175


def test_the_window_is_half_open_and_a_part_day_still_counts_as_one_day(api):
    """PRD §3.8: "Three inclusion filters are all mandatory: a trip enters the benchmark only if
    its `domicile_id` is the domicile being examined, its `plan_status` is `COMPLETED`, its
    `settlement_status` is `ACCRUED` or `SETTLED`, and its `planned_start_at` falls at or after
    `window_start` and strictly before `window_end` — a half-open window." And PRD §3.8:
    "`window_days` is the number of whole 24-hour days between `window_start` and `window_end`,
    taking the floor and never reporting fewer than 1."

    Design: Corner/endpoints/the_cost_benchmark_read_reports_every_declared_field_on_a_half_open_window
    """
    ctx, _trip = _one_completed_trip_of_a_domicile(api)
    # An eighteen-hour window whose start equals planned_start_at: inclusive, and clamped to 1.
    part_day = validate_success(
        api.get_cost_benchmark(ctx["domicile"]["id"], PAYROLL,
                              {"variant": "INCREMENTAL_VARIABLE",
                               "window_start": "2026-08-20T06:00:00Z",
                               "window_end": "2026-08-21T00:00:00Z"})
    )
    assert part_day["window_days"] == 1
    assert part_day["trip_count"] == 1
    assert part_day["total_cost_cents"] == 18100
    assert part_day["fixed_cost_cents"] == 13000

    # window_end is exclusive, so the 06:00 trip falls outside the previous day entirely.
    validate_error(
        api.get_cost_benchmark(ctx["domicile"]["id"], MANAGER,
                              {"variant": "INCREMENTAL_VARIABLE",
                               "window_start": "2026-08-19T00:00:00Z",
                               "window_end": "2026-08-20T00:00:00Z"}),
        ApiErrorId.ERR_BENCHMARK_NO_VOLUME,
        422,
    )


# ------------------------------------- a correction re-derives but never projects PM work ----


def _tractor_ten_thousand_miles_into_its_interval():
    set_clock()
    domicile = new_domicile(domicile_code="DOM-E5")
    tractor = new_tractor(domicile["id"], unit_code="TR-E5")
    assert tractor["miles_since_pm"] == 10000
    assert tractor["pm_hold"] is False
    assert tractor["status"] == "AVAILABLE"
    return domicile, tractor


def test_a_correction_past_the_interval_still_books_no_shop_time(api):
    """PRD §3.2: "A coordinator may correct a tractor's `odometer_miles`, `pm_interval_miles` or
    `pm_last_service_odometer`, supplying any subset. Both `miles_since_pm` and `pm_hold` are
    re-derived from the corrected values and the tractor's `version` advances — but no work
    order is ever created by a correction. Preventive maintenance is projected in exactly one
    place, at trip close-out (§3.7), and nowhere else." And PRD §3.2: "Two derived fields follow
    immediately: `miles_since_pm` is the current odometer reading less the last-service reading,
    and `pm_hold` is set at creation when `miles_since_pm` has already reached or passed
    `pm_interval_miles`."

    Design: Corner/endpoints/patching_a_tractor_re_derives_its_pm_counter_without_running_the_projection
    """
    _domicile, tractor = _tractor_ten_thousand_miles_into_its_interval()
    stored = validate_success(api.get_tractor(tractor["id"], MAINTENANCE))
    assert stored["unit_code"] == "TR-E5"
    assert stored["miles_since_pm"] == 10000

    corrected = validate_success(api.patch_tractor(tractor["id"], {"odometer_miles": 68000},
                                      MAINTENANCE))
    # The counter is recomputed from the corrected reading, not incremented.
    assert corrected["miles_since_pm"] == 28000
    assert corrected["pm_interval_miles"] == 25000
    assert corrected["pm_last_service_odometer"] == 40000
    assert corrected["pm_hold"] is True
    assert corrected["version"] > tractor["version"]

    # Crossing the interval by correction projects nothing.
    _rows, meta = validate_paginated(
        api.list_work_orders(MAINTENANCE, {"tractor_id": tractor["id"], "limit": 10,
                                          "offset": 0})
    )
    assert meta["total_count"] == 0


def test_correcting_only_the_last_service_reading_clears_the_counter(api):
    """PRD §3.2: "A coordinator may correct a tractor's `odometer_miles`, `pm_interval_miles` or
    `pm_last_service_odometer`, supplying any subset. Both `miles_since_pm` and `pm_hold` are
    re-derived from the corrected values and the tractor's `version` advances — but no work
    order is ever created by a correction."

    Design: Corner/endpoints/patching_a_tractor_re_derives_its_pm_counter_without_running_the_projection
    """
    domicile, tractor = _tractor_ten_thousand_miles_into_its_interval()
    first = validate_success(api.patch_tractor(tractor["id"], {"odometer_miles": 68000},
                                      MAINTENANCE))
    second = validate_success(
        api.patch_tractor(tractor["id"], {"pm_last_service_odometer": 68000}, MAINTENANCE)
    )
    assert second["miles_since_pm"] == 0
    assert second["pm_hold"] is False
    assert second["odometer_miles"] == 68000
    assert second["version"] > first["version"] > tractor["version"]

    rows, meta = validate_paginated(
        api.list_tractors(MANAGER, {"domicile_id": domicile["id"], "limit": 10, "offset": 0})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == tractor["id"]


# ------------------------------------------- one trip, one offer, in two different ways ----


def _planned_trip_and_two_offers(api):
    ctx = setup_base_fleet("e6", store_overrides={"store_code": "S-6006"})
    trip = new_trip(ctx["domicile"]["id"], trip_code="TRIP-E6",
                    planned_start_at="2026-08-20T06:00:00Z")
    add_delivery_stop(trip["id"], ctx["store"]["id"], ctx["order"]["id"], 1,
                      "2026-08-20T08:00:00Z", "2026-08-20T09:15:00Z", 120, 100, 600)
    assign_resources(trip["id"], ctx["driver"]["id"], ctx["tractor"]["id"],
                     ctx["trailer"]["id"])
    committed = plan_trip(trip["id"])
    spare = new_trip(ctx["domicile"]["id"], trip_code="TRIP-E6B",
                     planned_start_at="2026-08-22T06:00:00Z")
    incumbent = new_backhaul_offer(ctx["store"]["id"], shipper_name="Prairie Foods")
    challenger = new_backhaul_offer(
        ctx["store"]["id"], origin_kind="THIRD_PARTY", shipper_name="Lakeshore Brokerage",
        revenue_cents=70000, cases=400, weight_lbs=9000, deadhead_miles=50, loaded_miles=150,
    )
    linked = link_offer(trip["id"], incumbent["id"], committed["version"])
    assert linked["backhaul_offer_id"] == incumbent["id"]
    assert linked["backhaul_credit_cents"] == 0  # a PROPOSED offer credits nothing
    priced = review_offer(incumbent["id"])
    assert priced["contribution_margin_cents"] == 14900
    assert priced["margin_pct"] == 0.2483
    assert accept_offer(incumbent["id"])["status"] == "ACCEPTED"
    rival_priced = review_offer(challenger["id"])
    assert rival_priced["tier_margin_pct"] == 0.42
    assert rival_priced["contribution_margin_cents"] == 25200
    carrying = read_trip(trip["id"])
    assert carrying["backhaul_credit_cents"] == 14900
    return {"trip": trip, "spare": spare, "incumbent": incumbent,
            "challenger": challenger, "carrying": carrying}


def test_a_second_trip_cannot_take_an_offer_another_trip_carries(api):
    """PRD §3.6: "An offer already linked to a *different* trip is `ERR_BACKHAUL_ALREADY_LINKED`;
    the trip's own current link is never a conflict, because re-linking is designed to supersede
    it." And PRD §3.6: "On success the offer's `margin_exception_approved` is set to the supplied
    flag, the offer moves `UNDER_REVIEW → ACCEPTED`, and the linked trip's `backhaul_credit_cents`
    becomes the offer's `contribution_margin_cents` with the trip's `version` advancing alongside
    the offer's."

    Design: Corner/endpoints/relinking_a_backhaul_offer_supersedes_the_previous_one_instead_of_failing
    """
    ctx = _planned_trip_and_two_offers(api)
    validate_error(
        api.link_backhaul_offer(
            ctx["spare"]["id"],
            {"backhaul_offer_id": ctx["incumbent"]["id"],
             "expected_trip_version": ctx["spare"]["version"]},
            MANAGER,
        ),
        ApiErrorId.ERR_BACKHAUL_ALREADY_LINKED,
        422,
    )
    untouched = read_trip(ctx["spare"]["id"])
    assert untouched["backhaul_offer_id"] is None
    assert untouched["backhaul_credit_cents"] == 0
    assert read_offer(ctx["incumbent"]["id"])["status"] == "ACCEPTED"


def test_the_trips_own_relink_demotes_the_incumbent_and_resets_the_credit(api):
    """PRD §3.6: "On success, any offer previously linked to this trip is unlinked and, if it had
    been `ACCEPTED`, returned to `PROPOSED`; the trip's `backhaul_offer_id` becomes the new offer;
    the trip's `backhaul_credit_cents` becomes the new offer's `contribution_margin_cents` when
    that offer is already `ACCEPTED` and zero otherwise; and the trip's `version` advances." And
    PRD §3.6: "All six computed fields — `variable_cost_cents`, `gross_margin_cents`,
    `tier_margin_pct`, `commission_cents`, `contribution_margin_cents` and `margin_pct` — are
    written by this calculation."

    Design: Corner/endpoints/relinking_a_backhaul_offer_supersedes_the_previous_one_instead_of_failing
    """
    ctx = _planned_trip_and_two_offers(api)
    relinked = link_offer(ctx["trip"]["id"], ctx["challenger"]["id"],
                          ctx["carrying"]["version"])
    assert relinked["backhaul_offer_id"] == ctx["challenger"]["id"]
    assert relinked["backhaul_credit_cents"] == 0  # the challenger is only UNDER_REVIEW
    assert relinked["version"] > ctx["carrying"]["version"]

    demoted = read_offer(ctx["incumbent"]["id"])
    assert demoted["status"] == "PROPOSED"
    assert demoted["review_round"] == 0
    assert demoted["margin_exception_approved"] is False
    assert demoted["contribution_margin_cents"] == 14900

    assert accept_offer(ctx["challenger"]["id"])["status"] == "ACCEPTED"
    final = read_trip(ctx["trip"]["id"])
    assert final["backhaul_offer_id"] == ctx["challenger"]["id"]
    assert final["backhaul_credit_cents"] == 25200
