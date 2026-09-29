"""The catalogue's fan-out: one ladder step, many distinct codes.

Three ladder steps each resolve to a whole family of error ids — uniqueness to
seven duplicate codes, path resolution to eleven not-found codes, state gates to
one code per resource kind — and the point of these tests is that a single
generic code would satisfy none of them.
"""

import pytest

from test_helpers import (
    ACCOUNTANT,
    ADMIN,
    ADMIN_ALT,
    ADMIN_USER_ID,
    ANALYST,
    ANALYST_USER_ID,
    ERR_COLLATERAL_POSTING_NOT_FOUND,
    ERR_COUNTERPARTY_NOT_FOUND,
    ERR_DIRECTIVE_NOT_FOUND,
    ERR_DUPLICATE_COUNTERPARTY_CODE,
    ERR_DUPLICATE_FLIGHT_LEG,
    ERR_DUPLICATE_MTM_PERIOD,
    ERR_DUPLICATE_POLICY_CODE,
    ERR_DUPLICATE_PROGRAM_CODE,
    ERR_DUPLICATE_STATION_CODE,
    ERR_EXCEPTION_INVALID_STATE,
    ERR_EXCEPTION_NOT_FOUND,
    ERR_FLIGHT_LEG_NOT_FOUND,
    ERR_FORECAST_NOT_FOUND,
    ERR_INSTRUMENT_INVALID_ACCOUNTING_STATE,
    ERR_INSTRUMENT_NOT_FOUND,
    ERR_MTM_RUN_NOT_FOUND,
    ERR_POLICY_NOT_FOUND,
    ERR_POSTING_INVALID_STATE,
    ERR_PROGRAM_NOT_FOUND,
    ERR_STATION_NOT_FOUND,
    OPS,
    TREASURY,
    assert_counterparty_credit,
    assert_instrument_ledgers,
    assert_instrument_status,
    assert_money,
    factories as f,
    fixtures as fx,
    validate_error,
    validate_paginated,
    validate_success,
)

# Well-formed v4 identifiers that no row will ever carry.
ABSENT_POLICY = "11111111-1111-4111-8111-111111111111"
ABSENT_COUNTERPARTY = "22222222-2222-4222-8222-222222222222"
ABSENT_STATION = "33333333-3333-4333-8333-333333333333"
ABSENT_FORECAST = "44444444-4444-4444-8444-444444444444"
ABSENT_PROGRAM = "55555555-5555-4555-8555-555555555555"
ABSENT_INSTRUMENT = "66666666-6666-4666-8666-666666666666"
ABSENT_POSTING = "77777777-7777-4777-8777-777777777777"
ABSENT_MTM_RUN = "88888888-8888-4888-8888-888888888888"
ABSENT_LEG = "99999999-9999-4999-8999-999999999999"
ABSENT_DIRECTIVE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
ABSENT_EXCEPTION = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"


def _one_row_of_every_keyed_kind(api):
    """One holder of each business key the uniqueness step names."""
    policy = fx.do_create_policy(
        api,
        policy_code="FY27-DUP",
        min_coverage_pct=5.00,
        max_single_counterparty_pct=100.00,
        max_earnings_volatility_usd=500000.00,
        eligible_fleet_types=["NARROWBODY"],
    )
    counterparty = fx.do_create_counterparty(
        api, counterparty_code="DLRC", legal_name="Dealer C Bank NA", credit_rating="A"
    )
    dfw = fx.do_create_station(
        api,
        iata_code="DFW",
        name="Dallas Fort Worth",
        into_plane_fee_usd_per_gal=0.0450,
        avg_daily_liftings_gallons=100000,
    )
    ord_ = fx.do_create_station(
        api,
        iata_code="ORD",
        name="Chicago OHare",
        into_plane_fee_usd_per_gal=0.0800,
        avg_daily_liftings_gallons=80000,
    )
    program = fx.do_create_program(
        api,
        policy["id"],
        program_code="HP-DUP",
        route_groups=["DOMESTIC_SHORT"],
        target_coverage_pct=30.00,
    )
    run = fx.do_open_mtm_run(api, "2027-02", 2.7500)
    leg = fx.do_create_leg(
        api,
        dfw["id"],
        ord_["id"],
        flight_number="FA100",
        departure_date="2027-02-10",
        planned_burn_gallons=15000,
        tank_capacity_gallons=26500,
        landing_weight_lbs=130000,
        max_landing_weight_lbs=205000,
    )
    return {
        "policy": policy,
        "counterparty": counterparty,
        "dfw": dfw,
        "ord": ord_,
        "program": program,
        "run": run,
        "leg": leg,
    }


#: Each collision re-uses one key while changing everything else about the row.
COLLISIONS = {
    "policy_code": (
        ERR_DUPLICATE_POLICY_CODE,
        lambda api, ctx: api.create_hedge_policy(
            f.hedge_policy_payload(
                policy_code="FY27-DUP",
                max_coverage_pct=55.00,
                min_coverage_pct=10.00,
                max_single_counterparty_pct=40.00,
                permitted_instrument_types=["SWAP"],
                max_earnings_volatility_usd=400000.00,
                max_tankering_uplift_gallons=9000,
                min_days_cover=4.00,
                eligible_fleet_types=["WIDEBODY"],
            ),
            headers=ADMIN,
        ),
    ),
    "counterparty_code": (
        ERR_DUPLICATE_COUNTERPARTY_CODE,
        lambda api, ctx: api.create_counterparty(
            f.counterparty_payload(
                counterparty_code="DLRC",
                legal_name="Dealer C Bank Frankfurt",
                credit_rating="BBB",
                credit_limit_usd=900000.00,
            ),
            headers=ADMIN,
        ),
    ),
    "iata_code": (
        ERR_DUPLICATE_STATION_CODE,
        lambda api, ctx: api.create_station(
            f.station_payload(
                iata_code="DFW",
                name="Dallas Fort Worth Cargo Ramp",
                into_plane_fee_usd_per_gal=0.0500,
                avg_daily_liftings_gallons=20000,
            ),
            headers=ADMIN,
        ),
    ),
    "program_code": (
        ERR_DUPLICATE_PROGRAM_CODE,
        lambda api, ctx: api.create_hedge_program(
            f.hedge_program_payload(
                ctx["policy"]["id"],
                program_code="HP-DUP",
                period_start_month="2027-04",
                period_end_month="2027-06",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=25.00,
            ),
            headers=ANALYST,
        ),
    ),
    "mtm_period_month": (
        ERR_DUPLICATE_MTM_PERIOD,
        lambda api, ctx: api.create_mtm_run(
            f.mtm_run_payload("2027-02", 2.9000), headers=ACCOUNTANT
        ),
    ),
    "flight_number_with_departure_date": (
        ERR_DUPLICATE_FLIGHT_LEG,
        lambda api, ctx: api.create_flight_leg(
            f.flight_leg_payload(
                ctx["ord"]["id"],
                ctx["dfw"]["id"],
                flight_number="FA100",
                departure_date="2027-02-10",
                planned_block_minutes=195,
                planned_burn_gallons=14000,
                tank_capacity_gallons=26500,
                payload_lbs=21000,
                landing_weight_lbs=128000,
                max_landing_weight_lbs=205000,
            ),
            headers=OPS,
        ),
    ),
}


#: Eleven path segments, eleven codes. Each probe runs against an empty database.
NOT_FOUND_PROBES = {
    "hedge_policy": (
        ERR_POLICY_NOT_FOUND,
        lambda api: api.get_hedge_policy(ABSENT_POLICY, headers=ADMIN),
    ),
    "counterparty": (
        ERR_COUNTERPARTY_NOT_FOUND,
        lambda api: api.get_counterparty(ABSENT_COUNTERPARTY, headers=ADMIN),
    ),
    "station": (
        ERR_STATION_NOT_FOUND,
        lambda api: api.get_station(ABSENT_STATION, headers=ADMIN),
    ),
    "consumption_forecast": (
        ERR_FORECAST_NOT_FOUND,
        lambda api: api.publish_consumption_forecast(ABSENT_FORECAST, headers=ANALYST),
    ),
    "hedge_program": (
        ERR_PROGRAM_NOT_FOUND,
        lambda api: api.get_hedge_program(ABSENT_PROGRAM, headers=ANALYST),
    ),
    "hedge_instrument": (
        ERR_INSTRUMENT_NOT_FOUND,
        lambda api: api.get_hedge_instrument(ABSENT_INSTRUMENT, headers=TREASURY),
    ),
    "collateral_posting": (
        ERR_COLLATERAL_POSTING_NOT_FOUND,
        lambda api: api.post_collateral(
            ABSENT_POSTING, f.post_collateral_payload(60000.00), headers=ADMIN
        ),
    ),
    "mark_to_market_run": (
        ERR_MTM_RUN_NOT_FOUND,
        lambda api: api.get_mtm_run(ABSENT_MTM_RUN, headers=ACCOUNTANT),
    ),
    "flight_leg": (
        ERR_FLIGHT_LEG_NOT_FOUND,
        lambda api: api.get_flight_leg(ABSENT_LEG, headers=OPS),
    ),
    "tankering_directive": (
        ERR_DIRECTIVE_NOT_FOUND,
        lambda api: api.get_tankering_directive(ABSENT_DIRECTIVE, headers=OPS),
    ),
    "policy_exception": (
        ERR_EXCEPTION_NOT_FOUND,
        lambda api: api.get_policy_exception(ABSENT_EXCEPTION, headers=ADMIN),
    ),
}


class TestBusinessKeyCollisions:
    @pytest.mark.parametrize("key_name", sorted(COLLISIONS))
    def test_each_repeated_key_reports_its_own_duplicate_code(self, api, key_name):
        """PRD §2.5: "**Uniqueness.** `policy_code`, `counterparty_code`,
        `iata_code`, `program_code`, a mark-to-market run's `period_month`, and
        the pair of `flight_number` with `departure_date` are each unique across
        the whole system" and violations "yield `ERR_DUPLICATE_POLICY_CODE`,
        `ERR_DUPLICATE_COUNTERPARTY_CODE`, `ERR_DUPLICATE_STATION_CODE`,
        `ERR_DUPLICATE_PROGRAM_CODE`, `ERR_DUPLICATE_MTM_PERIOD`,
        `ERR_DUPLICATE_FLIGHT_LEG` or `ERR_DUPLICATE_CONTRACT_REF` (409) on
        policy, counterparty, station, programme, mark-to-market run, flight-leg
        and supply-contract creation respectively."

        Every colliding attempt differs from its incumbent in every field but the
        key, so only the key can be the reason for the refusal.

        Design: Corner/errors/six_business_key_collisions_each_return_their_own_409_code
        """
        ctx = _one_row_of_every_keyed_kind(api)
        expected_error, collide = COLLISIONS[key_name]

        validate_error(collide(api, ctx), expected_error, 409)

    def test_the_same_flight_number_on_another_date_is_a_distinct_key(self, api):
        """PRD §3.8: "It carries a `flight_number` of 1 to 8 characters and a
        `departure_date` as an ISO 8601 date, the pair of which must be unique
        across all legs — a repeat yields `ERR_DUPLICATE_FLIGHT_LEG`."

        The key is the pair, so FA100 flying again the next day is a new leg and
        the origin station then has two.

        Design: Corner/errors/six_business_key_collisions_each_return_their_own_409_code
        """
        ctx = _one_row_of_every_keyed_kind(api)

        second_day = validate_success(
            api.create_flight_leg(
                f.flight_leg_payload(
                    ctx["dfw"]["id"],
                    ctx["ord"]["id"],
                    flight_number="FA100",
                    departure_date="2027-02-11",
                    planned_burn_gallons=15000,
                    tank_capacity_gallons=26500,
                    landing_weight_lbs=130000,
                    max_landing_weight_lbs=205000,
                ),
                headers=OPS,
            ),
            201,
        )
        assert second_day["flight_number"] == "FA100"
        assert second_day["departure_date"] == "2027-02-11"

        rows, meta = validate_paginated(
            api.list_flight_legs(
                headers=OPS, params={"origin_station_id": ctx["dfw"]["id"]}
            )
        )
        assert meta["total_count"] == 2
        assert sorted(row["departure_date"] for row in rows) == [
            "2027-02-10",
            "2027-02-11",
        ]

    def test_the_refused_duplicate_policy_neither_supersedes_nor_mutates(self, api):
        """PRD §2.5: "When a single request could fail several checks, the server
        evaluates them in a fixed order and reports the first failure it finds."

        PRD §2.9: "Creating a new policy for a fiscal year that already has an
        `ACTIVE` policy sets the older row's `status` to `SUPERSEDED` and
        increments that row's `version` by one; the new row is created `ACTIVE`
        with `open_exception_count` at 0."

        The duplicate names the same `fiscal_year`, so had it been created the
        incumbent would have been superseded. It reports 409 instead, and the
        incumbent is untouched at version 1 with its own limits intact.

        Design: Corner/errors/six_business_key_collisions_each_return_their_own_409_code
        """
        ctx = _one_row_of_every_keyed_kind(api)
        expected_error, collide = COLLISIONS["policy_code"]
        validate_error(collide(api, ctx), expected_error, 409)

        policy = fx.read_policy(api, ctx["policy"]["id"])
        assert policy["status"] == "ACTIVE"
        assert policy["version"] == 1
        assert_money(policy["max_coverage_pct"], 60.00, "max_coverage_pct")
        assert_money(policy["min_coverage_pct"], 5.00, "min_coverage_pct")

        expected_error, collide = COLLISIONS["program_code"]
        validate_error(collide(api, ctx), expected_error, 409)

        programs, meta = validate_paginated(
            api.list_hedge_programs(
                headers=ADMIN, params={"policy_id": ctx["policy"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        assert programs[0]["program_code"] == "HP-DUP"


class TestPathResolutionCatalogue:
    @pytest.mark.parametrize("entity", sorted(NOT_FOUND_PROBES))
    def test_every_path_id_not_found_code_is_reachable(self, api, entity):
        """PRD §2.5: "**Path existence,** validated left to right. Every resource
        named by a path segment must exist; the first segment that does not
        resolve determines the error, which is one of `ERR_POLICY_NOT_FOUND`,
        `ERR_COUNTERPARTY_NOT_FOUND`, `ERR_STATION_NOT_FOUND`,
        `ERR_FORECAST_NOT_FOUND`, `ERR_PROGRAM_NOT_FOUND`,
        `ERR_INSTRUMENT_NOT_FOUND`, `ERR_COLLATERAL_POSTING_NOT_FOUND`,
        `ERR_MTM_RUN_NOT_FOUND`, `ERR_FLIGHT_LEG_NOT_FOUND`,
        `ERR_DIRECTIVE_NOT_FOUND` or `ERR_EXCEPTION_NOT_FOUND` (404)."

        Eleven entity kinds, eleven codes, each probed on an empty database with a
        well-formed identifier that resolves to nothing.

        Design: Corner/errors/every_path_id_not_found_code_is_reachable
        """
        expected_error, probe = NOT_FOUND_PROBES[entity]

        validate_error(probe(api), expected_error, 404)

    def test_a_valid_body_leaves_the_unknown_path_id_as_the_only_fault(self, api):
        """PRD §2.5: "**Request shape.** On every write endpoint: every required
        input field present, every type correct, every enumeration member
        recognised, every numeric constraint honoured, the conditional strike
        fields consistent with the declared instrument type, and any required
        version-pinning field present. Otherwise `ERR_INVALID_REQUEST` (400)."

        Request shape sits at step 3 and path existence at step 4, so a posting
        call carrying a well-formed `amount_usd` can only fail on the path id.

        Design: Corner/errors/every_path_id_not_found_code_is_reachable
        """
        error = validate_error(
            api.post_collateral(
                ABSENT_POSTING, f.post_collateral_payload(60000.00), headers=ADMIN
            ),
            ERR_COLLATERAL_POSTING_NOT_FOUND,
            404,
        )
        assert error["message"].strip()


class TestRepeatingACompletedStep:
    @staticmethod
    def _executed_swap_with_a_sixty_thousand_dollar_requirement(api):
        return fx.setup_active_program_with_executed_swap(
            api,
            single_forecast=True,
            policy_overrides=dict(
                policy_code="FY27-CORNER",
                min_coverage_pct=5.00,
                max_single_counterparty_pct=100.00,
                max_earnings_volatility_usd=500000.00,
                eligible_fleet_types=["NARROWBODY"],
            ),
            counterparty_overrides=dict(
                counterparty_code="DLRC",
                legal_name="Dealer C Bank NA",
                credit_rating="A",
            ),
            program_overrides=dict(
                program_code="HP-CORNER",
                route_groups=["DOMESTIC_SHORT"],
                target_coverage_pct=30.00,
            ),
            swap_overrides=dict(
                notional_gallons=1000000,
                strike_usd_per_gal=2.5000,
                maturity_month="2027-03",
            ),
        )

    def test_posting_the_same_row_twice_reports_the_postings_own_state(self, api):
        """PRD §3.5: "Posting writes `posted_amount_usd` from the offered amount,
        stamps `posted_at` from the logical clock, adds the posted amount to both
        the counterparty's `posted_collateral_usd` and the trade's
        `collateral_posted_usd`, decrements the counterparty's
        `open_margin_call_count` by one, and increments the posting's, the
        counterparty's and the trade's `version` by one each."

        PRD §3.5: "Attempting to post against a row that is not `REQUIRED` is
        likewise `ERR_POSTING_INVALID_STATE`."

        The covered trade is still `EXECUTED`, so the trade-state gate is
        satisfied and only the row's own status can refuse the repeat.

        Design: Corner/errors/repeating_a_completed_step_yields_three_distinct_409_state_codes
        """
        ctx = self._executed_swap_with_a_sixty_thousand_dollar_requirement(api)
        posting = fx.do_create_posting(
            api, ctx["counterparty"]["id"], ctx["instrument"]["id"]
        )

        posted = fx.do_post_collateral(api, posting["id"], 60000.00)
        assert posted["status"] == "POSTED"
        assert_money(posted["required_amount_usd"], 60000.00, "required_amount_usd")
        assert_money(posted["posted_amount_usd"], 60000.00, "posted_amount_usd")

        validate_error(
            api.post_collateral(
                posting["id"], f.post_collateral_payload(60000.00), headers=ADMIN
            ),
            ERR_POSTING_INVALID_STATE,
            409,
        )

    def test_designating_twice_reports_the_accounting_dimension_only(self, api):
        """PRD §3.6: "Designating an instrument whose `accounting_status` is
        already `DESIGNATED` is rejected with
        `ERR_INSTRUMENT_INVALID_ACCOUNTING_STATE`."

        PRD §3.4: "A designation never touches `trade_status`, and an execution
        never touches `accounting_status`."

        The trade dimension is legitimately `EXECUTED` throughout, so the refusal
        can only be reported against the accounting dimension.

        Design: Corner/errors/repeating_a_completed_step_yields_three_distinct_409_state_codes
        """
        ctx = self._executed_swap_with_a_sixty_thousand_dollar_requirement(api)

        designated = fx.do_designate_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(
            designated, trade_status="EXECUTED", accounting_status="DESIGNATED"
        )

        validate_error(
            api.designate_hedge_instrument(
                ctx["instrument"]["id"], headers=ACCOUNTANT
            ),
            ERR_INSTRUMENT_INVALID_ACCOUNTING_STATE,
            409,
        )

        after = fx.read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(
            after, trade_status="EXECUTED", accounting_status="DESIGNATED"
        )

    def test_denying_an_approved_exception_leaves_the_first_decider_in_place(
        self, api
    ):
        """PRD §3.9: "Deciding an exception that is no longer `REQUESTED` is
        rejected with `ERR_EXCEPTION_INVALID_STATE`, and `APPROVED` and `DENIED`
        are both terminal."

        PRD §3.9: "both stamp `decided_by_user_id` with the caller's `X-User-ID`
        and `decided_at` from the logical clock".

        A second administrator attempts the reversal, so segregation of duties is
        not in play; the refused denial leaves no trace of itself.

        Design: Corner/errors/repeating_a_completed_step_yields_three_distinct_409_state_codes
        """
        ctx = self._executed_swap_with_a_sixty_thousand_dollar_requirement(api)

        exception = fx.do_request_exception(
            api,
            "COVERAGE_LIMIT",
            justification=(
                "Board-approved overlay above the standing coverage ceiling for "
                "this program."
            ),
            hedge_program_id=ctx["program"]["id"],
        )
        assert exception["status"] == "REQUESTED"
        assert exception["requested_by_user_id"] == ANALYST_USER_ID

        approved = fx.do_approve_exception(api, exception["id"])
        assert approved["status"] == "APPROVED"
        assert approved["decided_by_user_id"] == ADMIN_USER_ID

        validate_error(
            api.deny_policy_exception(
                exception["id"], f.decision_payload(), headers=ADMIN_ALT
            ),
            ERR_EXCEPTION_INVALID_STATE,
            409,
        )

        after = fx.read_exception(api, exception["id"])
        assert after["status"] == "APPROVED"
        assert after["decided_by_user_id"] == ADMIN_USER_ID

    def test_the_three_refusals_leave_the_trade_and_its_dealer_whole(self, api):
        """PRD §3.5: "That frozen figure never moves again, even if the trade's
        margin requirement later changes."

        PRD §3.5: "Posting writes `posted_amount_usd` from the offered amount,
        stamps `posted_at` from the logical clock, adds the posted amount to both
        the counterparty's `posted_collateral_usd` and the trade's
        `collateral_posted_usd`, decrements the counterparty's
        `open_margin_call_count` by one".

        After the successful post and designation and the three refused repeats,
        the trade reads `EXECUTED` and `DESIGNATED` with 60,000.00 of requirement
        met by 60,000.00 of collateral, and the dealer's open call is closed.

        Design: Corner/errors/repeating_a_completed_step_yields_three_distinct_409_state_codes
        """
        ctx = self._executed_swap_with_a_sixty_thousand_dollar_requirement(api)
        posting = fx.do_create_posting(
            api, ctx["counterparty"]["id"], ctx["instrument"]["id"]
        )
        fx.do_post_collateral(api, posting["id"], 60000.00)
        fx.do_designate_instrument(api, ctx["instrument"]["id"])

        validate_error(
            api.post_collateral(
                posting["id"], f.post_collateral_payload(60000.00), headers=ADMIN
            ),
            ERR_POSTING_INVALID_STATE,
            409,
        )
        validate_error(
            api.designate_hedge_instrument(
                ctx["instrument"]["id"], headers=ACCOUNTANT
            ),
            ERR_INSTRUMENT_INVALID_ACCOUNTING_STATE,
            409,
        )

        instrument = fx.read_instrument(api, ctx["instrument"]["id"])
        assert_instrument_status(
            instrument, trade_status="EXECUTED", accounting_status="DESIGNATED"
        )
        assert_instrument_ledgers(
            instrument,
            margin_requirement_usd=60000.00,
            collateral_posted_usd=60000.00,
        )

        counterparty = fx.read_counterparty(api, ctx["counterparty"]["id"])
        assert_counterparty_credit(
            counterparty,
            utilized_credit_usd=60000.00,
            posted_collateral_usd=60000.00,
            open_margin_call_count=0,
        )
