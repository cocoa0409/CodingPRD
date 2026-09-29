"""Lifecycles that are not a single forward line: parallel dimensions, a bounded
negotiation loop with a backward edge, and one trigger that forks to two states."""

from test_helpers import (
    MANAGER,
    PAYROLL,
    PLANNER,
    ApiErrorId,
    accept_offer,
    api_client,
    get_success_data,
    link_offer,
    make_fleet_planner_headers,
    make_transport_manager_headers,
    new_backhaul_offer,
    new_domicile,
    new_driver,
    new_pay_plan,
    new_route_posting,
    place_bid,
    read_driver,
    read_offer,
    read_posting,
    read_trip,
    review_offer,
    set_clock,
    setup_f1,
    validate_error,
    validate_paginated,
    validate_success,
)


def _accrued_trip():
    """TRIP-1 COMPLETED / ACCRUED with one 28244-cent statement against it."""
    ctx = setup_f1(stage="completed", actual_drive_minutes=340, actual_duty_minutes=560)
    rows, meta = validate_paginated(
        api_client.list_pay_statements(PAYROLL, {"trip_id": ctx["trip"]["id"]})
    )
    assert meta["total_count"] == 1
    ctx["statement"] = rows[0]
    return ctx


def test_the_settlement_dimension_cycles_while_plan_status_stays_completed(api):
    """PRD §3.8: "Because the payroll dimension has no terminal state, a trip whose
    operations dimension reached `COMPLETED` long ago can keep cycling `ACCRUED →
    SETTLED → DISPUTED → ADJUSTED → ACCRUED` indefinitely."

    Design: Difficulty/non_linear_state_machine/trip_settlement_dimension_cycles_while_plan_dimension_stays_terminal
    """
    ctx = _accrued_trip()
    trip_id = ctx["trip"]["id"]
    statement_id = ctx["statement"]["id"]
    assert ctx["statement"]["gross_cents"] == 28244
    assert ctx["trip"]["plan_status"] == "COMPLETED"
    assert ctx["trip"]["settlement_status"] == "ACCRUED"

    get_success_data(
        api.settle_pay_statement(statement_id, {"settlement_reference": "ACH-2026-0001"}, PAYROLL)
    )
    after_settle = read_trip(trip_id)
    assert after_settle["settlement_status"] == "SETTLED"
    assert after_settle["plan_status"] == "COMPLETED"

    get_success_data(
        api.dispute_settlement(
            trip_id, {"dispute_note": "driver contests 25 detention minutes"}, PAYROLL
        )
    )
    after_dispute = read_trip(trip_id)
    assert after_dispute["settlement_status"] == "DISPUTED"
    assert after_dispute["plan_status"] == "COMPLETED"

    get_success_data(
        api.reverse_pay_statement(statement_id, {"reason_code": "DISPUTE_UPHELD"}, PAYROLL)
    )
    after_reverse = read_trip(trip_id)
    assert after_reverse["settlement_status"] == "ADJUSTED"
    assert after_reverse["plan_status"] == "COMPLETED"
    assert after_reverse["driver_pay_cents"] == 0
    reversed_statement = get_success_data(api.get_pay_statement(statement_id, PAYROLL))
    assert reversed_statement["status"] == "REVERSED"

    re_accrued = get_success_data(
        api.re_accrue_trip(
            trip_id, {"actual_drive_minutes": 340, "actual_duty_minutes": 600}, PAYROLL
        )
    )
    assert re_accrued["settlement_status"] == "ACCRUED"
    assert re_accrued["plan_status"] == "COMPLETED"
    # 600 - 505 - 30 = 65 detention minutes at 42 cents: 21294 + 5900 + 2730.
    assert re_accrued["driver_pay_cents"] == 29924


def test_re_accrual_prices_the_correction_on_the_original_pinned_plan_version(api):
    """PRD §3.8: "The pin is deliberately not refreshed, so a superseded pay plan still
    governs the corrected settlement."

    Design: Difficulty/non_linear_state_machine/trip_settlement_dimension_cycles_while_plan_dimension_stays_terminal
    """
    ctx = _accrued_trip()
    trip_id = ctx["trip"]["id"]
    statement_id = ctx["statement"]["id"]
    get_success_data(
        api.settle_pay_statement(statement_id, {"settlement_reference": "ACH-2026-0001"}, PAYROLL)
    )
    get_success_data(api.dispute_settlement(trip_id, {"dispute_note": "contested"}, PAYROLL))
    get_success_data(api.reverse_pay_statement(statement_id, {}, PAYROLL))
    get_success_data(
        api.re_accrue_trip(
            trip_id, {"actual_drive_minutes": 340, "actual_duty_minutes": 600}, PAYROLL
        )
    )

    rows, meta = validate_paginated(api.list_pay_statements(PAYROLL, {"trip_id": trip_id}))
    assert meta["total_count"] == 2
    by_status = {row["status"]: row for row in rows}
    assert by_status["REVERSED"]["gross_cents"] == 28244
    assert by_status["ACCRUED"]["gross_cents"] == 29924
    assert by_status["ACCRUED"]["pay_plan_version"] == by_status["REVERSED"]["pay_plan_version"]
    assert by_status["ACCRUED"]["pay_plan_id"] == by_status["REVERSED"]["pay_plan_id"]
    assert by_status["ACCRUED"]["variant"] == "FINAL_SETTLEMENT"


def test_the_pay_ledgers_end_the_cycle_holding_the_re_accrued_amount(api):
    """PRD §3.8: "a *new* statement is created in `ACCRUED` status raising both the
    domicile `accrued_pay_cents` and the driver `ytd_gross_cents` by its `gross_cents`,
    the payroll dimension returns to `ACCRUED`, and the trip's `version` advances."

    Design: Difficulty/non_linear_state_machine/trip_settlement_dimension_cycles_while_plan_dimension_stays_terminal
    """
    ctx = _accrued_trip()
    trip_id = ctx["trip"]["id"]
    statement_id = ctx["statement"]["id"]
    get_success_data(
        api.settle_pay_statement(statement_id, {"settlement_reference": "ACH-2026-0002"}, PAYROLL)
    )
    get_success_data(api.dispute_settlement(trip_id, {}, PAYROLL))
    get_success_data(api.reverse_pay_statement(statement_id, {}, PAYROLL))
    get_success_data(
        api.re_accrue_trip(
            trip_id, {"actual_drive_minutes": 340, "actual_duty_minutes": 600}, PAYROLL
        )
    )
    domicile = get_success_data(api.get_domicile(ctx["domicile"]["id"], MANAGER))
    assert domicile["accrued_pay_cents"] == 29924
    assert read_driver(ctx["driver"]["id"])["ytd_gross_cents"] == 29924


# 210 incremental miles of DRY freight, opened at 54000 cents and negotiated upward.
B1_LONG = {
    "origin_kind": "VENDOR_PICKUP",
    "shipper_name": "ACME MILLS",
    "origin_region_code": "MIDWEST",
    "revenue_cents": 54000,
    "cases": 400,
    "weight_lbs": 9000,
    "deadhead_miles": 42,
    "loaded_miles": 168,
    "temperature_mode": "DRY",
    "pickup_window_start": "2026-08-03T11:30:00Z",
    "pickup_window_end": "2026-08-03T13:00:00Z",
    "offer_expires_at": "2026-08-20T00:00:00Z",
}


def _negotiated_offer():
    """Three full review rounds against a planned trip that can take the offer."""
    ctx = setup_f1(stage="planned")
    planner = make_fleet_planner_headers("user-fp-1")
    offer = new_backhaul_offer(ctx["store"]["id"], headers=planner, **B1_LONG)
    rounds = []
    review_offer(offer["id"], planner)
    for revenue in (56000, 58000, 60000):
        rounds.append(
            get_success_data(api_client.revise_offer(offer["id"], {"revenue_cents": revenue}, planner))
        )
        review_offer(offer["id"], planner)
    ctx["planner_headers"] = planner
    ctx["offer"] = offer
    ctx["rounds"] = rounds
    return ctx


def _accept_onto_the_planned_trip(ctx):
    """Link the negotiated offer to the planned trip and then accept it."""
    link_offer(ctx["trip"]["id"], ctx["offer"]["id"], ctx["planned_trip"]["version"])
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 0
    return accept_offer(ctx["offer"]["id"], make_transport_manager_headers("user-tm-1"))


def test_the_negotiation_loop_is_bounded_at_three_review_rounds(api):
    """PRD §3.6: "Sending an offer back to the shipper takes it `UNDER_REVIEW →
    PROPOSED`, and it is permitted only while `review_round` is below 3; a fourth attempt
    is `ERR_REVIEW_ROUND_LIMIT`, and an offer that is not `UNDER_REVIEW` is
    `ERR_OFFER_NOT_UNDER_REVIEW`."

    Design: Difficulty/non_linear_state_machine/backhaul_offer_review_loop_bounded_and_accepted_state_reverts_on_cancel
    """
    ctx = _negotiated_offer()
    first, second, third = ctx["rounds"]
    assert first["review_round"] == 1
    assert first["status"] == "PROPOSED"
    # Revenue 56000 over an unchanged 42450 variable cost: tier 0.2420, commission 3360.
    assert first["contribution_margin_cents"] == 10190
    assert second["review_round"] == 2
    assert third["review_round"] == 3
    assert third["tier_margin_pct"] == 0.2925
    assert third["contribution_margin_cents"] == 13950

    validate_error(
        api.revise_offer(ctx["offer"]["id"], {"revenue_cents": 62000}, ctx["planner_headers"]),
        ApiErrorId.ERR_REVIEW_ROUND_LIMIT,
        409,
    )
    refused = read_offer(ctx["offer"]["id"])
    assert refused["status"] == "UNDER_REVIEW"
    assert refused["review_round"] == 3
    assert refused["revenue_cents"] == 60000


def test_accepted_is_not_terminal_because_a_trip_cancel_returns_the_offer_to_market(api):
    """PRD §3.6: "When a trip that links an `ACCEPTED` offer is cancelled, the offer
    returns `ACCEPTED → PROPOSED` rather than dying with the trip: its
    `margin_exception_approved` flag resets to false, its `review_round` is left exactly
    where it was, and its computed margin fields are untouched."

    Design: Difficulty/non_linear_state_machine/backhaul_offer_review_loop_bounded_and_accepted_state_reverts_on_cancel
    """
    ctx = _negotiated_offer()
    accepted = _accept_onto_the_planned_trip(ctx)
    assert accepted["status"] == "ACCEPTED"
    assert read_trip(ctx["trip"]["id"])["backhaul_credit_cents"] == 13950

    cancelled = get_success_data(
        api.cancel_trip(ctx["trip"]["id"], {"reason_code": "SHIPPER_PULLED"}, PLANNER)
    )
    assert cancelled["backhaul_offer_id"] is None
    assert cancelled["backhaul_credit_cents"] == 0

    back_on_market = read_offer(ctx["offer"]["id"])
    assert back_on_market["status"] == "PROPOSED"
    assert back_on_market["review_round"] == 3
    assert back_on_market["revenue_cents"] == 60000
    assert back_on_market["contribution_margin_cents"] == 13950
    assert back_on_market["margin_exception_approved"] is False


def test_the_backward_edge_does_not_reset_the_exhausted_round_counter(api):
    """PRD §3.6: "its `review_round` is left exactly where it was, and its computed margin
    fields are untouched."

    Design: Difficulty/non_linear_state_machine/backhaul_offer_review_loop_bounded_and_accepted_state_reverts_on_cancel
    """
    ctx = _negotiated_offer()
    _accept_onto_the_planned_trip(ctx)
    get_success_data(api.cancel_trip(ctx["trip"]["id"], {"reason_code": "SHIPPER_PULLED"}, PLANNER))

    reopened = review_offer(ctx["offer"]["id"], ctx["planner_headers"])
    assert reopened["status"] == "UNDER_REVIEW"
    assert reopened["review_round"] == 3
    validate_error(
        api.revise_offer(ctx["offer"]["id"], {"revenue_cents": 62000}, ctx["planner_headers"]),
        ApiErrorId.ERR_REVIEW_ROUND_LIMIT,
        409,
    )


def _closed_bid_board():
    """Two postings on one domicile: RT-100 drew two bids, RT-101 drew none."""
    set_clock()
    domicile = new_domicile(
        domicile_code="DOM-CHI",
        region_code="MIDWEST",
        tractor_capacity=40,
        driver_headcount_target=20,
        fixed_ownership_cents_per_day=12000,
        overhead_cents_per_day=4000,
        dedicated_rate_cents_per_mile=285,
        dedicated_rate_cents_per_case=210,
    )
    pay_plan = new_pay_plan(
        plan_code="MILE-A",
        mileage_cents_per_mile=78,
        stop_cents_per_stop=2200,
        drop_hook_cents=1500,
        hourly_cents_per_minute=42,
        minimum_daily_cents=24000,
        backhaul_bonus_pct=0.05,
    )
    junior = new_driver(domicile["id"], pay_plan["id"], driver_code="D-77",
                        seniority_date="2019-03-04")
    senior = new_driver(domicile["id"], pay_plan["id"], driver_code="D-64",
                        seniority_date="2017-06-01")
    publisher = make_transport_manager_headers("user-tm-1")
    contested = new_route_posting(
        domicile["id"], headers=publisher, route_code="RT-100", weekly_miles=2200,
        weekly_stops=18, start_effective_date="2026-09-01",
        bid_close_at="2026-08-10T00:00:00Z",
    )
    empty = new_route_posting(
        domicile["id"], headers=publisher, route_code="RT-101", weekly_miles=1800,
        weekly_stops=12, start_effective_date="2026-09-01",
        bid_close_at="2026-08-10T00:00:00Z",
    )
    junior_bid = place_bid(junior["id"], contested["id"], contested["version"])
    after_first = read_posting(contested["id"])
    senior_bid = place_bid(senior["id"], contested["id"], after_first["version"])
    set_clock("2026-08-11T00:00:00Z")
    return {
        "junior": junior,
        "senior": senior,
        "contested": contested,
        "empty": empty,
        "junior_bid": junior_bid,
        "senior_bid": senior_bid,
        "after_first": after_first,
        "awarder": make_transport_manager_headers("user-tm-2"),
    }


def test_the_award_fork_resolves_to_awarded_on_the_most_senior_live_candidate(api):
    """PRD §3.9: "Candidates are then ranked by `seniority_date` ascending, the earlier
    date being the more senior claim."

    Design: Difficulty/non_linear_state_machine/route_posting_award_trigger_forks_to_awarded_or_vacant_then_locks_down
    """
    board = _closed_bid_board()
    assert board["after_first"]["bid_count"] == 1
    assert board["after_first"]["version"] != board["contested"]["version"]

    awarded = validate_success(api.award_route_posting(board["contested"]["id"], board["awarder"]), 200)
    assert awarded["status"] == "AWARDED"
    # 2017-06-01 outranks 2019-03-04 even though the junior driver bid first.
    assert awarded["awarded_driver_id"] == board["senior"]["id"]
    assert awarded["bid_count"] == 0
    assert get_success_data(api.get_route_bid(board["senior_bid"]["id"], MANAGER))["status"] == "AWARDED"
    assert get_success_data(api.get_route_bid(board["junior_bid"]["id"], MANAGER))["status"] == "PASSED_OVER"


def test_the_same_trigger_forks_to_vacant_when_the_candidate_pool_is_empty(api):
    """PRD §3.9: "If the posting drew no bids at all, or if every bid it drew is ineligible
    on the live driver's standing, the posting moves `OPEN → VACANT` and the request
    succeeds with HTTP 200."

    Design: Difficulty/non_linear_state_machine/route_posting_award_trigger_forks_to_awarded_or_vacant_then_locks_down
    """
    board = _closed_bid_board()
    vacant = validate_success(api.award_route_posting(board["empty"]["id"], board["awarder"]), 200)
    assert vacant["status"] == "VACANT"
    assert vacant["awarded_driver_id"] is None
    assert vacant["bid_count"] == 0


def test_both_fork_targets_lock_the_posting_against_a_second_award(api):
    """PRD §3.9: "The posting must be `OPEN`, or `ERR_POSTING_NOT_OPEN`."

    Design: Difficulty/non_linear_state_machine/route_posting_award_trigger_forks_to_awarded_or_vacant_then_locks_down
    """
    board = _closed_bid_board()
    get_success_data(api.award_route_posting(board["contested"]["id"], board["awarder"]))
    get_success_data(api.award_route_posting(board["empty"]["id"], board["awarder"]))

    validate_error(
        api.award_route_posting(board["contested"]["id"], board["awarder"]),
        ApiErrorId.ERR_POSTING_NOT_OPEN,
        409,
    )
    validate_error(
        api.award_route_posting(board["empty"]["id"], board["awarder"]),
        ApiErrorId.ERR_POSTING_NOT_OPEN,
        409,
    )
    still_awarded = get_success_data(api.get_route_bid(board["senior_bid"]["id"], MANAGER))
    assert still_awarded["status"] == "AWARDED"
