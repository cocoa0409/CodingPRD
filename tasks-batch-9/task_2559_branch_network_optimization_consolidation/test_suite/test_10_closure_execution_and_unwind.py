"""Closure execution: the four-hop cascade, its gate ladder, and the unwind that reverses it."""

from test_helpers import (
    COMPLIANCE,
    HR,
    OPS_ADMIN,
    REAL_ESTATE,
    ApiErrorId,
    api_client,
    assert_headcount_conservation,
    assert_market_deposit_conservation,
    case_observation_payload,
    leased_property_disposition_payload,
    owned_property_disposition_payload,
    read_branch,
    read_campaign,
    read_case,
    read_market,
    read_notice,
    read_property_disposition,
    read_staff_disposition,
    set_clock,
    setup_campaign,
    setup_execution_ready_case,
    setup_executed_closure,
    setup_market_with_branches,
    setup_notice_filed_case,
    staff_disposition_payload,
    validate_error,
    validate_success,
)

RIVERBEND = {
    "name": "Riverbend North",
    "region_code": "MW-04",
    "population": 120000,
    "median_household_income_cents": 8500000,
    "deposit_market_total_cents": 240000000000,
    "competitor_branch_count": 24,
    "household_growth_pct_bps": 350,
    "digital_penetration_bps": 5200,
}

_CLOSING = {"monthly_transaction_count": 3600, "annual_revenue_cents": 140000000}
_RECEIVING = {
    "monthly_transaction_count": 7200,
    "digital_adoption_bps": 6800,
    "annual_noninterest_expense_cents": 118000000,
    "annual_revenue_cents": 305000000,
    "opened_on": "1998-06-15",
    "onboarding_capacity_households_per_day": 60,
}
DECAY_AT_3_4 = {
    "model_variant": "DISTANCE_DECAY",
    "distance_miles": 3.4,
    "retail_share_bps": 6000,
    "small_business_share_bps": 2500,
    "wealth_share_bps": 1500,
}
_LEASED_PREMISES = {"atm_disposition": "RELOCATE", "buyout_offer_cents": 500000}
_LATE_WAVE = {
    "wave_start_date": "2026-10-01",
    "wave_end_date": "2026-10-11",
    "inbound_household_count": 300,
}


def _riverbend_execution_ready():
    """Riverbend closure with every precondition met except the elapsed notice period."""
    ctx = setup_market_with_branches(
        market_overrides=RIVERBEND, closing_overrides=_CLOSING, receiving_overrides=_RECEIVING
    )
    return setup_execution_ready_case(
        ctx,
        case_overrides={"planned_closure_date": "2026-11-15"},
        forecast_overrides=DECAY_AT_3_4,
        campaign_overrides=_LATE_WAVE,
        property_overrides=_LEASED_PREMISES,
    )


def _riverbend_executed():
    """The same closure, executed on 2026-11-02 with the notice already swept to EFFECTIVE."""
    return setup_executed_closure(
        _riverbend_execution_ready(), execution_date="2026-11-02T00:00:00Z"
    )


def test_01_marketing_carry_landing_at_execution_pushes_the_case_under_the_savings_floor():
    """The closure the approver signed off cleared the governance floor by three hundred thousand
    cents; executing it markets the premises, the marketing charge lands on the carry, and the case
    the bank is left holding is flagged for the shortfall the approver never saw.

    PRD: "The **second hop** follows from the branch now being `CLOSED`: each premises disposition of the closing branch sitting at `PENDING` transitions to `MARKETED` and stamps `marketing_started_on`."
    PRD: "A marketing charge of 24,000 dollars a year (2,400,000 cents) applies while the premises is in `MARKETED`, `HOLDOVER`, `ASSIGNMENT_PENDING` or `SALE_PENDING` status."
    PRD: "The **fourth hop** follows from that: if the recomputed `net_annual_savings_cents` has fallen below the fifteen-million-cent governance floor, the case's `governance_flag` is set to `SAVINGS_WATCH` and the trade area's `flagged_case_count` increases by one."
    Design: Difficulty/transitive_cascade/execute_closure_four_hop_cascade_flips_case_to_savings_watch
    """
    ctx = _riverbend_execution_ready()
    before = read_case(ctx["case"]["id"])
    assert before["net_annual_savings_cents"] == 15320000
    assert before["governance_flag"] == "NONE"
    assert read_property_disposition(ctx["property"]["id"])["annual_carry_cents"] == 3000000
    set_clock("2026-11-02T00:00:00Z")

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))

    premises = read_property_disposition(ctx["property"]["id"])
    assert premises["status"] == "MARKETED"
    assert premises["marketing_started_on"] == "2026-11-02"
    assert premises["annual_carry_cents"] == 5400000
    assert executed["gross_annual_savings_cents"] == 23960000
    assert executed["transition_incentive_rate_bps"] == 25
    assert executed["transition_incentive_cents"] == 11040000
    assert executed["net_annual_savings_cents"] == 12920000
    assert executed["governance_flag"] == "SAVINGS_WATCH"
    assert read_market(ctx["market"]["id"])["flagged_case_count"] == 1


def test_02_the_same_execution_empties_the_closing_branch_and_resettles_the_trade_area():
    """One request moves the deposits, retires the branch, retires the customer wave and re-derives
    the trade area's footprint down to a single surviving branch.

    PRD: "In the **first hop** the closing branch transitions `CLOSURE_SCHEDULED → CLOSED`: its own `pre_close_deposits_cents` is stamped from its `deposit_balance_cents` and that balance is then set to zero, its `pre_close_fte_count` is stamped from its `fte_count` and that count is then set to zero, its `absorbing_branch_id` is set to the case's `receiving_branch_id`, and its `version` increments."
    PRD: "In the same movement the receiving branch's `deposit_balance_cents` and `transferred_in_deposits_cents` each increase by the case's `forecast_retained_deposits_cents` with that branch's `version` incremented, while the trade area's `absorbed_deposits_cents` increases by the same retained amount and its `cumulative_runoff_deposits_cents` increases by the case's `forecast_runoff_cents`."
    PRD: "Every disposition of the case at `OFFER_ACCEPTED` transitions to `COMPLETED`, and every campaign of the case at `LAUNCHED` transitions to `COMPLETED`."
    Design: Difficulty/transitive_cascade/execute_closure_four_hop_cascade_flips_case_to_savings_watch
    """
    ctx = _riverbend_execution_ready()
    set_clock("2026-11-02T00:00:00Z")

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    assert executed["status"] == "CLOSURE_EXECUTED"
    assert executed["executed_on"] == "2026-11-02"

    closing = read_branch(ctx["closing_branch"]["id"])
    assert closing["status"] == "CLOSED"
    assert closing["deposit_balance_cents"] == 0
    assert closing["pre_close_deposits_cents"] == 4800000000
    assert closing["absorbing_branch_id"] == ctx["receiving_branch"]["id"]

    receiving = read_branch(ctx["receiving_branch"]["id"])
    assert receiving["deposit_balance_cents"] == 14016000000
    assert receiving["transferred_in_deposits_cents"] == 4416000000

    market = read_market(ctx["market"]["id"])
    assert market["absorbed_deposits_cents"] == 4416000000
    assert market["cumulative_runoff_deposits_cents"] == 384000000
    assert market["own_branch_count"] == 1
    assert market["branch_density_per_100k"] == 21
    assert market["saturation_tier"] == "SATURATED"
    assert read_campaign(ctx["campaign"]["id"])["status"] == "COMPLETED"


def test_03_an_unsettled_employee_blocks_the_closure_and_the_waiting_period_blocks_the_employee():
    """The closure cannot proceed while one teller's fate is open, and the fate cannot be settled the
    day the notification goes out: the statutory waiting period stands between the two.

    PRD: "The case's `pending_disposition_count` must be exactly zero — every employee's fate settled — or `ERR_STAFF_DISPOSITIONS_PENDING`."
    PRD: "Recording notification transitions `notification_state` from `PENDING → NOTIFIED` and stamps `notified_on` from the logical clock while leaving `disposition_state` exactly where it stood — notification is legal whether the outcome axis reads `PROPOSED` or `OFFER_ACCEPTED`."
    PRD: "Severing an employee requires that the record's `proposed_disposition` be `SEVERANCE`, that its `notification_state` read `NOTIFIED`, and that the statutory waiting period have run: the current logical date must be at least 60 whole days after `notified_on`."
    Design: Difficulty/cross_entity_state_dependency/execute_closure_gated_by_pending_staff_disposition_and_warn_clock
    """
    ctx = _riverbend_execution_ready()
    disposition = validate_success(
        api_client.create_staff_disposition(
            staff_disposition_payload(
                ctx["case"]["id"], employee_ref="EMP-7741", role_title="Branch Manager"
            ),
            HR,
        ),
        expected_status=201,
    )
    set_clock("2026-11-02T00:00:00Z")
    assert read_case(ctx["case"]["id"])["pending_disposition_count"] == 1

    validate_error(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE),
        ApiErrorId.ERR_STAFF_DISPOSITIONS_PENDING.value,
        expected_status=409,
    )
    assert read_case(ctx["case"]["id"])["status"] == "NOTICE_FILED"

    notified = validate_success(
        api_client.notify_staff_disposition(disposition["id"], HR)
    )
    assert notified["notification_state"] == "NOTIFIED"
    assert notified["notified_on"] == "2026-11-02"
    assert notified["disposition_state"] == "PROPOSED"

    validate_error(
        api_client.sever_staff_disposition(disposition["id"], HR),
        ApiErrorId.ERR_WARN_PERIOD_NOT_ELAPSED.value,
        expected_status=409,
    )
    assert read_case(ctx["case"]["id"])["pending_disposition_count"] == 1


def test_04_on_the_sixtieth_day_the_severance_clears_and_the_closure_follows_it_through():
    """Sixty whole days after the notification the severance lands, the head leaves the network, the
    last open disposition closes, and the closure that was blocked now executes — leaving the
    terminal severance record untouched by the execution sweep.

    PRD: "On success `severed_on` is stamped, the `disposition_state` moves `PROPOSED → SEVERED`, the source branch's `fte_count` decreases by one with that branch's `version` incremented, the case's `severed_fte_count` increases by one and its `pending_disposition_count` decreases by one, and the case and disposition `version` values increment."
    PRD: "Note the asymmetry with acceptance: a severance removes a head from the network permanently, and the case's `severed_fte_count` is the third term of the headcount invariant precisely so that the removal is accounted for rather than lost."
    PRD: "Every disposition of the case at `OFFER_ACCEPTED` transitions to `COMPLETED`, and every campaign of the case at `LAUNCHED` transitions to `COMPLETED`."
    Design: Difficulty/cross_entity_state_dependency/execute_closure_gated_by_pending_staff_disposition_and_warn_clock
    """
    ctx = _riverbend_execution_ready()
    disposition = validate_success(
        api_client.create_staff_disposition(
            staff_disposition_payload(
                ctx["case"]["id"], employee_ref="EMP-7741", role_title="Branch Manager"
            ),
            HR,
        ),
        expected_status=201,
    )
    set_clock("2026-11-02T00:00:00Z")
    validate_success(api_client.notify_staff_disposition(disposition["id"], HR))
    set_clock("2027-01-01T00:00:00Z")

    severed = validate_success(api_client.sever_staff_disposition(disposition["id"], HR))
    assert severed["disposition_state"] == "SEVERED"
    assert severed["severed_on"] == "2027-01-01"
    assert severed["severance_amount_cents"] == 3720024

    case = read_case(ctx["case"]["id"])
    assert case["severed_fte_count"] == 1
    assert case["pending_disposition_count"] == 0
    assert case["severance_pool_cents"] == 3720024
    closing = read_branch(ctx["closing_branch"]["id"])
    assert closing["fte_count"] == 8
    assert_headcount_conservation(
        case, closing, read_branch(ctx["receiving_branch"]["id"]), 23
    )

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    assert executed["status"] == "CLOSURE_EXECUTED"
    assert executed["executed_on"] == "2027-01-01"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSED"
    assert read_staff_disposition(disposition["id"])["disposition_state"] == "SEVERED"


def test_05_unwinding_the_closure_puts_every_deposit_back_where_it_came_from():
    """The three-place ledger — closing branch, surviving branch, market runoff — reads the same total
    before the closure and after its rescission, and each place is back at its own opening figure.

    PRD: "For any market, take the sum of `deposit_balance_cents` across every branch of that market in `ACTIVE`, `UNDER_REVIEW`, `CLOSURE_SCHEDULED`, `CLOSED` or `DE_NOVO_RAMPING` status, and add that market's `cumulative_runoff_deposits_cents`."
    PRD: "Because no rounding takes place in either transfer, the invariant is exact and zero drift is tolerated."
    PRD: "The closing branch transitions `CLOSED → ACTIVE`: its `deposit_balance_cents` is restored from `pre_close_deposits_cents` and that stamp is cleared to null, its `fte_count` is restored verbatim from `pre_close_fte_count` and that stamp is cleared to null, its `absorbing_branch_id` is cleared to null, and its `version` increments."
    Design: Difficulty/compensating_invariant/unwind_closure_restores_market_deposit_ledger_exactly
    """
    ctx = _riverbend_executed()
    assert ctx["closing_branch"]["deposit_balance_cents"] == 0
    assert ctx["receiving_branch"]["deposit_balance_cents"] == 14016000000
    assert ctx["market"]["cumulative_runoff_deposits_cents"] == 384000000
    assert_market_deposit_conservation(
        ctx["market"], [ctx["closing_branch"], ctx["receiving_branch"]], 14400000000
    )

    unwound = validate_success(
        api_client.unwind_closure(
            ctx["case"]["id"], {"rescission_reason_code": "REGULATOR_OBJECTION"}, COMPLIANCE
        )
    )
    assert unwound["status"] == "UNWOUND"

    closing = read_branch(ctx["closing_branch"]["id"])
    assert closing["status"] == "ACTIVE"
    assert closing["deposit_balance_cents"] == 4800000000
    assert closing["pre_close_deposits_cents"] is None
    assert closing["absorbing_branch_id"] is None
    assert closing["fte_count"] == 9
    assert closing["pre_close_fte_count"] is None

    receiving = read_branch(ctx["receiving_branch"]["id"])
    assert receiving["deposit_balance_cents"] == 9600000000
    assert receiving["transferred_in_deposits_cents"] == 0

    market = read_market(ctx["market"]["id"])
    assert market["absorbed_deposits_cents"] == 0
    assert market["cumulative_runoff_deposits_cents"] == 0
    assert_market_deposit_conservation(market, [closing, receiving], 14400000000)


def test_06_the_rescission_also_walks_back_the_premises_and_the_savings_flag_but_not_the_wave():
    """Compensation reaches the premises, the notice, the savings chain and the governance counter,
    and stops exactly where the design says it stops: the customer wave that already ran stays
    completed, and no version counter is rolled back.

    PRD: "Every premises disposition of the closing branch at `MARKETED` reverts to `PENDING` with `marketing_started_on` cleared and `annual_carry_cents` recomputed without the marketing charge."
    PRD: "And if the case's `governance_flag` reads `SAVINGS_WATCH` it resets to `NONE` while the trade area's `flagged_case_count` decreases by one."
    PRD: "The case's regulatory notice transitions to `WITHDRAWN`."
    Design: Difficulty/compensating_invariant/unwind_closure_restores_market_deposit_ledger_exactly
    """
    ctx = _riverbend_executed()
    assert ctx["case"]["governance_flag"] == "SAVINGS_WATCH"
    assert read_market(ctx["market"]["id"])["flagged_case_count"] == 1
    executed_versions = {
        "case": ctx["case"]["version"],
        "premises": read_property_disposition(ctx["property"]["id"])["version"],
        "closing": read_branch(ctx["closing_branch"]["id"])["version"],
    }

    unwound = validate_success(
        api_client.unwind_closure(
            ctx["case"]["id"], {"rescission_reason_code": "REGULATOR_OBJECTION"}, COMPLIANCE
        )
    )

    premises = read_property_disposition(ctx["property"]["id"])
    assert premises["status"] == "PENDING"
    assert premises["marketing_started_on"] is None
    assert premises["annual_carry_cents"] == 3000000
    assert unwound["gross_annual_savings_cents"] == 26360000
    assert unwound["transition_incentive_cents"] == 11040000
    assert unwound["net_annual_savings_cents"] == 15320000
    assert unwound["governance_flag"] == "NONE"
    assert read_market(ctx["market"]["id"])["flagged_case_count"] == 0
    assert read_notice(ctx["notice"]["id"])["status"] == "WITHDRAWN"
    assert read_campaign(ctx["campaign"]["id"])["status"] == "COMPLETED"

    assert unwound["version"] > executed_versions["case"]
    assert premises["version"] > executed_versions["premises"]
    assert read_branch(ctx["closing_branch"]["id"])["version"] > executed_versions["closing"]


def test_07_only_the_premises_of_the_branch_that_actually_closed_goes_to_market():
    """Two premises records hang off one case, but the marketing cascade follows the branch that
    closed: the leased shop picks up the marketing charge while the survivor's own premises keeps its
    flat owned carry, so the case's recomputed carry is the sum of one raised figure and one untouched.

    PRD: "The **second hop** follows from the branch now being `CLOSED`: each premises disposition of the closing branch sitting at `PENDING` transitions to `MARKETED` and stamps `marketing_started_on`."
    PRD: "The base carry is zero once the premises is `DISPOSED`; for a `LEASED` premises in any other status it is twelve times the `monthly_rent_cents`; for an `OWNED` premises in any other status it is a flat 18,000 dollars a year (1,800,000 cents) of taxes, insurance and maintenance."
    PRD: "Third, the **property carry** is the sum of `annual_carry_cents` across every premises disposition attached to the case, regardless of that disposition's status."
    Design: Corner/state_machines/execute_closure_markets_only_pending_dispositions_of_closing_branch
    """
    ctx = setup_execution_ready_case()
    closing_premises = ctx["property"]
    survivor_premises = validate_success(
        api_client.create_property_disposition(
            owned_property_disposition_payload(
                ctx["receiving_branch"]["id"],
                ctx["case"]["id"],
                atm_disposition="DECOMMISSION",
                atm_monthly_surcharge_revenue_cents=0,
                book_value_cents=90000000,
                list_price_cents=150000000,
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert survivor_premises["tenure_class"] == "OWNED"
    assert survivor_premises["annual_carry_cents"] == 1800000
    set_clock("2026-11-01T00:00:00Z")

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))

    marketed = read_property_disposition(closing_premises["id"])
    assert marketed["status"] == "MARKETED"
    assert marketed["marketing_started_on"] == "2026-11-01"
    assert marketed["annual_carry_cents"] == 5400000
    untouched = read_property_disposition(survivor_premises["id"])
    assert untouched["status"] == "PENDING"
    assert untouched["marketing_started_on"] is None
    assert untouched["annual_carry_cents"] == 1800000

    assert executed["gross_annual_savings_cents"] == 22160000
    assert executed["transition_incentive_rate_bps"] == 25
    assert executed["transition_incentive_cents"] == 11040000
    assert executed["net_annual_savings_cents"] == 11120000
    assert executed["governance_flag"] == "SAVINGS_WATCH"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSED"
    assert read_branch(ctx["receiving_branch"]["id"])["status"] == "ACTIVE"


def test_08_the_execution_gate_ladder_reports_the_calendar_before_the_missing_premises():
    """Two preconditions are violated at once — the notice period has not run and no premises record
    exists — and the closure reports the calendar first. Only when the clock reaches the effective date
    does the missing premises surface, and the same call goes through once the record is filed.

    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    PRD: "The current logical date must have reached the notice's `effective_closure_date`, or the request fails with `ERR_NOTICE_PERIOD_NOT_ELAPSED`."
    PRD: "And at least one premises disposition must exist for the closing branch, or `ERR_PROPERTY_DISPOSITION_MISSING`."
    PRD: "Every closure notice in `FILED` status whose `effective_closure_date` is on or before the new logical date transitions to `EFFECTIVE`, and every leased premises in `MARKETED` status whose `lease_end_date` falls strictly before the new logical date transitions to `HOLDOVER` with its carrying cost recomputed and the owning case's savings chain refreshed."
    Design: Corner/validations/execute_closure_gate_ladder_returns_the_most_specific_error_first
    """
    ctx = setup_notice_filed_case()
    setup_campaign(ctx, launch=True)

    validate_error(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE),
        ApiErrorId.ERR_NOTICE_PERIOD_NOT_ELAPSED.value,
        expected_status=409,
    )

    swept = set_clock("2026-11-01T00:00:00Z")
    assert swept["notices_made_effective"] == 1
    assert read_notice(ctx["notice"]["id"])["status"] == "EFFECTIVE"

    validate_error(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE),
        ApiErrorId.ERR_PROPERTY_DISPOSITION_MISSING.value,
        expected_status=409,
    )

    premises = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"], ctx["case"]["id"]
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    assert executed["status"] == "CLOSURE_EXECUTED"
    assert executed["executed_on"] == "2026-11-01"
    closing = read_branch(ctx["closing_branch"]["id"])
    assert closing["deposit_balance_cents"] == 0
    assert closing["pre_close_deposits_cents"] == 4800000000
    assert closing["fte_count"] == 0
    assert closing["absorbing_branch_id"] == ctx["receiving_branch"]["id"]
    receiving = read_branch(ctx["receiving_branch"]["id"])
    assert receiving["deposit_balance_cents"] == 14016000000
    assert receiving["transferred_in_deposits_cents"] == 4416000000
    assert read_property_disposition(premises["id"])["annual_carry_cents"] == 5400000
    assert executed["net_annual_savings_cents"] == 12920000
    assert executed["governance_flag"] == "SAVINGS_WATCH"
    assert read_campaign(ctx["campaign"]["id"])["status"] == "COMPLETED"


def test_09_the_unwind_window_shuts_on_the_thirty_first_day_and_close_out_waits_a_full_year():
    """Two post-closure windows, each on its own clock: close-out asked of a freshly executed case is
    a state error rather than a monitoring one, the rescission window is gone by the thirty-first whole
    day, and close-out is refused until the twelfth month has actually been observed.

    PRD: "The case must stand at `CLOSURE_EXECUTED`, the case's `last_observed_month_index` must still be zero — once a single runoff observation has landed the closure is no longer reversible — and the current logical date must be no more than 30 whole days after `executed_on`."
    PRD: "The case's `last_observed_month_index` must have reached the full twelve-month monitoring horizon and its `monitoring_posture` must read `ON_TRACK` or `RESOLVED`; a case short of twelve months, or still in `REMEDIATION`, is rejected with `ERR_MONITORING_INCOMPLETE`."
    PRD: "The first observation also transitions the case `CLOSURE_EXECUTED → POST_CLOSE_MONITORING` and increments its `version`."
    Design: Corner/validations/unwind_window_closes_on_day_thirty_one_and_close_out_waits_for_month_twelve
    """
    ctx = setup_execution_ready_case(case_overrides={"rationale_code": "MARKET_OVERLAP"})
    set_clock("2026-11-01T00:00:00Z")
    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    assert executed["status"] == "CLOSURE_EXECUTED"
    assert executed["executed_on"] == "2026-11-01"
    assert executed["pre_close_deposits_cents"] == 4800000000

    validate_error(
        api_client.close_out_consolidation_case(ctx["case"]["id"], OPS_ADMIN),
        ApiErrorId.ERR_CASE_STATE_INVALID.value,
        expected_status=409,
    )

    set_clock("2026-12-02T00:00:00Z")
    validate_error(
        api_client.unwind_closure(
            ctx["case"]["id"], {"rescission_reason_code": "BOARD_REVERSAL"}, COMPLIANCE
        ),
        ApiErrorId.ERR_UNWIND_WINDOW_CLOSED.value,
        expected_status=409,
    )
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSED"
    assert read_branch(ctx["receiving_branch"]["id"])["deposit_balance_cents"] == 14016000000

    third_month = validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 3, 4569600000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert third_month["forecast_deposits_cents"] == 4569600000
    assert third_month["variance_bps"] == 0
    monitored = read_case(ctx["case"]["id"])
    assert monitored["status"] == "POST_CLOSE_MONITORING"
    assert monitored["last_observed_month_index"] == 3
    assert monitored["monitoring_posture"] == "ON_TRACK"

    validate_error(
        api_client.close_out_consolidation_case(ctx["case"]["id"], OPS_ADMIN),
        ApiErrorId.ERR_MONITORING_INCOMPLETE.value,
        expected_status=409,
    )

    twelfth_month = validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 12, 4416000000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert twelfth_month["forecast_deposits_cents"] == 4416000000
    assert twelfth_month["variance_bps"] == 0

    closed_out = validate_success(
        api_client.close_out_consolidation_case(ctx["case"]["id"], OPS_ADMIN)
    )
    assert closed_out["status"] == "CLOSED_OUT"
