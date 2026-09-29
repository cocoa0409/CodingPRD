"""Premises disposition: the ATM retention margin, carrying cost and the settlement forks."""

from test_helpers import (
    COMPLIANCE,
    REAL_ESTATE,
    ApiErrorId,
    api_client,
    assert_property_disposition,
    leased_property_disposition_payload,
    owned_property_disposition_payload,
    read_case,
    read_market,
    read_property_disposition,
    set_clock,
    setup_campaign,
    setup_draft_case,
    setup_market_with_branches,
    setup_notice_filed_case,
    setup_owned_property_disposition,
    validate_error,
    validate_paginated,
    validate_success,
)

LAKESHORE_WEST = {
    "name": "Lakeshore West",
    "region_code": "MW-11",
    "population": 110000,
    "median_household_income_cents": 7400000,
    "deposit_market_total_cents": 170000000000,
    "competitor_branch_count": 19,
    "household_growth_pct_bps": 240,
    "digital_penetration_bps": 5000,
}

_LAKESHORE_CLOSING = {
    "branch_code": "RB-401",
    "deposit_balance_cents": 3600000000,
    "monthly_transaction_count": 2600,
    "digital_adoption_bps": 5100,
    "annual_noninterest_expense_cents": 34000000,
    "annual_revenue_cents": 108000000,
    "fte_count": 6,
    "atm_count": 2,
    "opened_on": "2010-05-01",
}

_LAKESHORE_RECEIVING = {
    "branch_code": "RB-403",
    "deposit_balance_cents": 9200000000,
    "monthly_transaction_count": 7000,
    "digital_adoption_bps": 6500,
    "annual_noninterest_expense_cents": 110000000,
    "annual_revenue_cents": 292000000,
    "fte_count": 13,
    "atm_count": 3,
    "opened_on": "1996-11-01",
    "onboarding_capacity_households_per_day": 50,
}

_LAKESHORE_TERMS = {
    "atm_disposition": "RETAIN_OFFSITE",
    "atm_monthly_cost_cents": 30000,
    "monthly_rent_cents": 200000,
    "lease_end_date": "2028-01-31",
    "buyout_offer_cents": 400000,
}


def _lakeshore_draft_case() -> dict:
    """Lakeshore West with a DRAFT case closing the leased RB-401 into RB-403."""
    return setup_draft_case(
        setup_market_with_branches(
            market_overrides=LAKESHORE_WEST,
            closing_overrides=dict(_LAKESHORE_CLOSING),
            receiving_overrides=dict(_LAKESHORE_RECEIVING),
        )
    )


def _open_premises(ctx, surcharge_revenue_cents: int) -> dict:
    return validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"],
                ctx["case"]["id"],
                atm_monthly_surcharge_revenue_cents=surcharge_revenue_cents,
                **_LAKESHORE_TERMS,
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )


def test_01_a_cash_fleet_whose_margin_lands_exactly_on_the_floor_is_kept():
    """Fifty thousand cents of monthly headroom is twelve times six hundred thousand a year, which
    is precisely the retention floor; because the floor is inclusive the requested off-site retention
    survives adjudication untouched.

    PRD: "The fleet's annual margin is twelve times the difference between `atm_monthly_surcharge_revenue_cents` and `atm_monthly_cost_cents`, and `atm_breakeven_met` is true when that annual margin reaches a retention margin floor of 6,000 dollars — 600,000 cents."
    PRD: "The threshold is inclusive, so an annual margin of exactly 600,000 cents clears it."
    PRD: "A `RELOCATE` or `DECOMMISSION` request is never altered, and a `RETAIN_OFFSITE` request that clears the floor is honoured."
    Design: Difficulty/boundary_precision_check/atm_retention_margin_exactly_at_inclusive_floor
    """
    ctx = _lakeshore_draft_case()

    premises = _open_premises(ctx, 80000)

    assert_property_disposition(premises)
    assert premises["atm_breakeven_met"] is True
    assert premises["atm_disposition"] == "RETAIN_OFFSITE"
    assert premises["atm_decision_final"] == "RETAIN_OFFSITE"
    assert premises["status"] == "PENDING"
    assert premises["tenure_class"] == "LEASED"
    assert premises["annual_carry_cents"] == 2400000


def test_02_one_cent_of_monthly_income_less_quietly_decommissions_the_fleet():
    """A single cent shaved off monthly surcharge income costs twelve cents a year, leaving the
    margin twelve cents under the floor; the request is still recorded as made but the adjudicated
    outcome is silently downgraded.

    PRD: "`atm_decision_final` then equals the requested `atm_disposition` in every case except one: a requested `RETAIN_OFFSITE` whose fleet fails breakeven is downgraded to `DECOMMISSION`."
    PRD: "The ATM decision is adjudicated by the server rather than accepted at face value."
    PRD: "for a `LEASED` premises in any other status it is twelve times the `monthly_rent_cents`"
    Design: Difficulty/boundary_precision_check/atm_retention_margin_exactly_at_inclusive_floor
    """
    ctx = _lakeshore_draft_case()

    premises = _open_premises(ctx, 79999)

    assert premises["atm_breakeven_met"] is False
    assert premises["atm_disposition"] == "RETAIN_OFFSITE"
    assert premises["atm_decision_final"] == "DECOMMISSION"
    assert premises["status"] == "PENDING"
    assert premises["tenure_class"] == "LEASED"
    assert premises["annual_carry_cents"] == 2400000

    reread = read_property_disposition(premises["id"])
    assert reread["atm_breakeven_met"] is False
    assert reread["atm_decision_final"] == "DECOMMISSION"


def test_03_selling_an_owned_building_nets_out_the_book_value_and_clears_the_carry():
    """The freehold fork of settlement never touches the landlord buyout figure — it takes the
    agreed price, removes the brokerage and then the value carried on the books — and disposal drops
    the carrying cost to nothing, lifting the case's savings back above the governance floor without
    lifting the watch flag the execution raised.

    PRD: "On the owned fork, settling from `SALE_PENDING`, `net_disposition_cents` is the `agreed_amount_cents` minus the `selling_costs_cents` minus the `book_value_cents` carried on the books."
    PRD: "Both forks converge on `DISPOSED`, stamp `settled_on` from the logical clock, drop `annual_carry_cents` to zero and refresh the case savings chain — but they compute different money."
    PRD: "The `list_price_cents` recorded for an owned premises is the asking price on file and does not enter the settlement arithmetic — the `agreed_amount_cents` does."
    PRD: "And if the case's `governance_flag` reads `SAVINGS_WATCH` it resets to `NONE` while the trade area's `flagged_case_count` decreases by one."
    Design: Corner/calculations/property_disposition_net_owned_fork_subtracts_book_value_and_zeroes_carry
    """
    ctx = setup_notice_filed_case(
        setup_market_with_branches(
            closing_overrides={"branch_code": "RB-301", "tenure_class": "OWNED"},
            receiving_overrides={"branch_code": "RB-302"},
        )
    )
    ctx = setup_owned_property_disposition(
        ctx,
        atm_disposition="DECOMMISSION",
        atm_monthly_surcharge_revenue_cents=0,
        book_value_cents=90000000,
        list_price_cents=150000000,
    )
    ctx = setup_campaign(ctx, launch=True)
    assert ctx["property"]["annual_carry_cents"] == 1800000

    set_clock("2026-11-01T00:00:00Z")
    executed = validate_success(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE)
    )
    assert executed["net_annual_savings_cents"] == 14120000
    assert executed["governance_flag"] == "SAVINGS_WATCH"
    marketed = read_property_disposition(ctx["property"]["id"])
    assert marketed["status"] == "MARKETED"
    assert marketed["annual_carry_cents"] == 4200000

    contracted = validate_success(
        api_client.contract_property_disposition(
            ctx["property"]["id"],
            {
                "counterparty_ref": "BUYER-CH-77",
                "agreed_amount_cents": 140000000,
                "selling_costs_cents": 6000000,
            },
            REAL_ESTATE,
        )
    )
    assert contracted["status"] == "SALE_PENDING"

    settled = validate_success(
        api_client.settle_property_disposition(ctx["property"]["id"], REAL_ESTATE)
    )
    assert settled["status"] == "DISPOSED"
    assert settled["settled_on"] == "2026-11-01"
    assert settled["net_disposition_cents"] == 44000000
    assert settled["annual_carry_cents"] == 0
    assert settled["atm_breakeven_met"] is False
    assert settled["atm_decision_final"] == "DECOMMISSION"

    case = read_case(ctx["case"]["id"])
    assert case["gross_annual_savings_cents"] == 29360000
    assert case["transition_incentive_rate_bps"] == 25
    assert case["transition_incentive_cents"] == 11040000
    assert case["net_annual_savings_cents"] == 18320000
    assert case["governance_flag"] == "SAVINGS_WATCH"
    assert read_market(ctx["market"]["id"])["flagged_case_count"] == 1


def test_04_a_leased_premises_must_state_when_its_lease_runs_out():
    """Which commercial terms are mandatory is decided by the building's tenure, not by the request:
    the identical body that is incomplete for a leased premises is complete for a freehold one, and
    the refusal records nothing.

    PRD: "A `LEASED` premises must supply `monthly_rent_cents`, the `lease_end_date` on which the lease expires, and the landlord's `buyout_offer_cents` ask."
    PRD: "An `OWNED` premises must supply the `book_value_cents` carrying value and the `list_price_cents` asking price."
    PRD: "A missing term on either fork is rejected with `ERR_PROPERTY_TERMS_INCOMPLETE`."
    Design: Corner/validations/leased_property_disposition_missing_lease_end_date_is_rejected
    """
    ctx = setup_draft_case(case_overrides={"rationale_code": "LEASE_EXPIRY"})
    gross_before = read_case(ctx["case"]["id"])["gross_annual_savings_cents"]

    validate_error(
        api_client.create_property_disposition(
            {
                "branch_id": ctx["closing_branch"]["id"],
                "consolidation_case_id": ctx["case"]["id"],
                "atm_disposition": "RELOCATE",
                "atm_monthly_cost_cents": 30000,
                "atm_monthly_surcharge_revenue_cents": 80000,
                "monthly_rent_cents": 250000,
                "buyout_offer_cents": 3000000,
            },
            REAL_ESTATE,
        ),
        ApiErrorId.ERR_PROPERTY_TERMS_INCOMPLETE.value,
        expected_status=422,
    )

    _, meta = validate_paginated(
        api_client.list_property_dispositions(
            REAL_ESTATE, params={"consolidation_case_id": ctx["case"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    assert read_case(ctx["case"]["id"])["gross_annual_savings_cents"] == gross_before

    freehold = validate_success(
        api_client.create_property_disposition(
            owned_property_disposition_payload(
                ctx["receiving_branch"]["id"], ctx["case"]["id"]
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert freehold["tenure_class"] == "OWNED"
    assert freehold["status"] == "PENDING"


def test_05_a_premises_still_awaiting_the_closure_can_be_neither_contracted_nor_settled():
    """Both commercial exits are declared only from the marketed side of the diamond, so a freshly
    opened record refuses each of them and keeps its pre-marketing carrying cost, its null settlement
    figure and its opening version.

    PRD: "A premises leaves `PENDING` only as a cascade of closure execution: when the branch it belongs to becomes `CLOSED`, the disposition transitions `PENDING → MARKETED`, stamps `marketing_started_on` from the logical clock, and picks up the marketing charge."
    PRD: "Contracting requires the owning case to stand in `NOTICE_FILED`, `CLOSURE_EXECUTED` or `POST_CLOSE_MONITORING` status, and a from-state or tenure-fork mismatch — attempting a sale contract on a leased premises, or contracting a premises still `PENDING` — is rejected with `ERR_PROPERTY_STATE_INVALID`."
    PRD: "A marketing charge of 24,000 dollars a year (2,400,000 cents) applies while the premises is in `MARKETED`, `HOLDOVER`, `ASSIGNMENT_PENDING` or `SALE_PENDING` status."
    Design: Corner/validations/settling_a_pending_property_disposition_returns_property_state_invalid
    """
    ctx = setup_draft_case(case_overrides={"rationale_code": "LEASE_EXPIRY"})
    premises = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"], ctx["case"]["id"]
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert premises["annual_carry_cents"] == 3000000
    assert premises["atm_breakeven_met"] is True
    assert premises["atm_decision_final"] == "RETAIN_OFFSITE"

    validate_error(
        api_client.settle_property_disposition(premises["id"], REAL_ESTATE),
        ApiErrorId.ERR_PROPERTY_STATE_INVALID.value,
        expected_status=409,
    )
    validate_error(
        api_client.contract_property_disposition(
            premises["id"],
            {
                "counterparty_ref": "ASSIGNEE-11",
                "agreed_amount_cents": 1000000,
                "selling_costs_cents": 200000,
            },
            REAL_ESTATE,
        ),
        ApiErrorId.ERR_PROPERTY_STATE_INVALID.value,
        expected_status=409,
    )

    reread = read_property_disposition(premises["id"])
    assert reread["status"] == "PENDING"
    assert reread["settled_on"] is None
    assert reread["net_disposition_cents"] is None
    assert reread["annual_carry_cents"] == 3000000
    assert reread["version"] == premises["version"]


def test_06_the_clock_sweeps_the_notice_first_and_the_expired_lease_much_later():
    """Advancing the logical date is two bulk sweeps in one call, and its counters report exactly what
    moved: the first advance makes the regulatory notice effective and leaves the premises alone
    because it has not been marketed yet, while the later advance finds the expired lease and pushes
    it into holdover, adding the premium and re-running the case's savings chain behind it.

    PRD: "Every closure notice in `FILED` status whose `effective_closure_date` is on or before the new logical date transitions to `EFFECTIVE`, and every leased premises in `MARKETED` status whose `lease_end_date` falls strictly before the new logical date transitions to `HOLDOVER` with its carrying cost recomputed and the owning case's savings chain refreshed."
    PRD: "A holdover premium applies only in `HOLDOVER` status and adds 50 percent of the base carry — the base multiplied by 5000 basis points, divided by 10000 and rounded half up."
    PRD: "`annual_carry_cents` is the base plus the holdover premium plus the marketing charge, and it is recomputed at creation and on every status change, each recomputation forcing a refresh of the owning case's `gross_annual_savings_cents`, `transition_incentive_rate_bps`, `transition_incentive_cents` and `net_annual_savings_cents`."
    Design: Corner/endpoints/clock_sweep_makes_the_notice_effective_and_later_moves_the_lease_to_holdover
    """
    ctx = setup_notice_filed_case(case_overrides={"rationale_code": "LEASE_EXPIRY"})
    premises = validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(
                ctx["closing_branch"]["id"],
                ctx["case"]["id"],
                lease_end_date="2026-11-30",
            ),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    assert premises["annual_carry_cents"] == 3000000
    ctx = setup_campaign(ctx, launch=True)

    first_sweep = set_clock("2026-11-01T00:00:00Z")
    assert first_sweep["notices_made_effective"] == 1
    assert first_sweep["properties_moved_to_holdover"] == 0
    assert first_sweep["current_utc"] == "2026-11-01T00:00:00Z"
    assert read_property_disposition(premises["id"])["status"] == "PENDING"

    executed = validate_success(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE)
    )
    assert executed["net_annual_savings_cents"] == 12920000
    assert read_property_disposition(premises["id"])["annual_carry_cents"] == 5400000

    second_sweep = set_clock("2026-12-05T00:00:00Z")
    assert second_sweep["notices_made_effective"] == 0
    assert second_sweep["properties_moved_to_holdover"] == 1

    holdover = read_property_disposition(premises["id"])
    assert holdover["status"] == "HOLDOVER"
    assert holdover["annual_carry_cents"] == 6900000

    case = read_case(ctx["case"]["id"])
    assert case["gross_annual_savings_cents"] == 22460000
    assert case["net_annual_savings_cents"] == 11420000
    assert case["transition_incentive_rate_bps"] == 25
    assert case["governance_flag"] == "SAVINGS_WATCH"
    assert read_market(ctx["market"]["id"])["flagged_case_count"] == 1
