"""Listing, filtering, pagination, and the test-driving clock / year-tick endpoints.

Corner queue B — Section: endpoints, Section: cross_cutting_complexity_layers
(pagination_with_filter_status).
"""
from test_helpers import (
    api_client,
    TEST_USERS,
    validate_success,
    validate_paginated,
    get_success_data,
    set_clock,
    create_and_activate_plan,
    create_and_enroll_participant,
    create_open_contribution_period,
    close_contribution_period,
    create_pending_participant,
    create_loan_payload,
    create_participant_payload,
    create_rmd_distribution_payload,
    setup_active_plan_with_enrolled_participant,
    setup_rmd_eligible_participant,
    setup_participant_with_seeded_balances,
)

_ADMIN = TEST_USERS["plan_admin_headers"]


def test_list_participants_filtered_by_plan_id_returns_only_that_plan(api):
    """PRD §3.2: "A participant is brought into a plan by creating a `Participant`
    resource scoped to a `plan_id`..."
    PRD §2.3: "List endpoints expose two query parameters that govern paging: `limit`, the maximum number of items returned, which defaults to 10 and is bounded by a minimum of 1 and a maximum of 100; and `offset`, the number of items to skip, which defaults to 0."

    The list endpoint's plan_id filter restricts results to the named plan.

    Design: Corner/endpoints/list_participants_filtered_by_plan_returns_only_that_plan
    """
    plan_a = create_and_activate_plan(name="PA", match_formula="TIERED",
                                      vesting_schedule="CLIFF_3")
    plan_b = create_and_activate_plan(name="PB", match_formula="TIERED",
                                      vesting_schedule="CLIFF_3")
    pa = create_pending_participant(plan_a["id"], full_name="PA1",
                                    date_of_birth="1980-01-01T00:00:00Z",
                                    hire_date="2024-01-01T00:00:00Z",
                                    annual_compensation_cents=12_000_000,
                                    deferral_rate_bps=400)
    pb = create_pending_participant(plan_b["id"], full_name="PB1",
                                    date_of_birth="1980-01-01T00:00:00Z",
                                    hire_date="2024-01-01T00:00:00Z",
                                    annual_compensation_cents=12_000_000,
                                    deferral_rate_bps=400)
    res = api.list_participants(_ADMIN, params={"plan_id": plan_a["id"]})
    data, _meta = validate_paginated(res)
    ids = {p["id"] for p in data}
    assert pa["id"] in ids
    assert pb["id"] not in ids


def test_list_loans_default_limit_is_10(api):
    """PRD §2.3: "List endpoints expose two query parameters that govern paging:
    `limit`, the maximum number of items returned, which defaults to 10..."
    PRD §2.3: "The pagination metadata fields — `limit`, `offset`, `total_count`,
    and `has_more` — appear in the `meta` block of every list response envelope."

    With 12 REQUESTED loans on a participant, a GET /loans?participant_id=...
    without limit returns at most 10 items; meta.has_more=true; total_count=12.

    Design: Corner/endpoints/list_loans_pagination_defaults
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="ManyLoans", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="PM",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2018-06-15T00:00:00Z",
        annual_compensation_cents=50_000_000,
        deferral_rate_bps=400,
    )
    for _ in range(12):
        get_success_data(api.create_loan(
            create_loan_payload(participant["id"], principal_cents=100,
                                term_months=12, annual_interest_rate_bps=700),
            _ADMIN,
        ))
    res = api.list_loans(_ADMIN, params={"participant_id": participant["id"]})
    data, meta = validate_paginated(res)
    assert len(data) == 10
    assert meta.get("has_more") is True
    assert meta.get("total_count") == 12


def test_set_clock_endpoint_advances_age_for_rmd_age_check(api):
    """PRD §3.8: "The first sets the system clock to a supplied `to_iso8601`
    instant — used for age calculations across RMD, hardship penalty, and vesting,
    and for the derivation of `years_of_service`..."
    PRD §3.6: "If that age is less than the age trigger of 73, the creation is
    rejected with `ERR_RMD_NOT_REQUIRED`..."

    Participant DOB 1954-06-30 (chosen so PRD §3.6 year-end age formula
    floor((Dec 31 of distribution_year - DOB).days / 365) yields exactly 73 at
    year-end 2027 — 1954-06-30 -> 26847 days / 365 = 73): age <73 at 2026-12-31
    (rejected with ERR_RMD_NOT_REQUIRED), age 73 at 2027-12-31 (accepted).
    Setting the clock to 2027-06-15 and creating an RMD for
    distribution_year=2027 succeeds.

    Design: Corner/endpoints/clock_set_endpoint_advances_age_computation
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="Clk", plan_year=2027,
                                    match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    participant = create_and_enroll_participant(
        plan["id"], full_name="C",
        date_of_birth="1954-06-30T00:00:00Z",
        hire_date="2010-01-01T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    # Advance the clock so that the RMD distribution_year=2027 age check passes.
    set_clock("2027-06-15T00:00:00Z")
    res = api.create_rmd_distribution(
        create_rmd_distribution_payload(
            participant["id"], distribution_year=2027,
            prior_year_end_balance_cents=1_000_000,
            rmd_variant="UNIFORM_LIFETIME",
        ),
        _ADMIN,
    )
    data = validate_success(res, expected_status=201)
    assert data["status"] == "PENDING"
    assert data["required_amount_cents"] == 37_735


def test_year_tick_marks_overdue_pending_rmd_as_missed(api):
    """PRD §3.8: "The second simulates the annual year-tick at a supplied `as_of_year`: for each enrolled or suspended participant whose `years_of_service` crosses a vesting boundary, the year-tick recomputes that participant's `vested_employer_balance_cents` and appends the corresponding `VestingEvent` per §3.7; and for each pending RMD whose `distribution_year` is strictly less than `as_of_year`, the RMD's status is set to `MISSED`."

    Year-tick at 2027 over a PENDING RMD with distribution_year=2026 -> MISSED.

    Design: Corner/endpoints/system_year_tick_marks_overdue_rmd_missed
    """
    set_clock("2026-12-31T00:00:00Z")
    plan = create_and_activate_plan(name="YT", match_formula="TIERED",
                                    vesting_schedule="CLIFF_3")
    participant = create_and_enroll_participant(
        plan["id"], full_name="Y",
        date_of_birth="1954-01-01T00:00:00Z",
        hire_date="2010-01-01T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    rmd = get_success_data(api.create_rmd_distribution(
        create_rmd_distribution_payload(participant["id"], distribution_year=2026,
                                        prior_year_end_balance_cents=1_000_000,
                                        rmd_variant="UNIFORM_LIFETIME"),
        _ADMIN,
    ))
    validate_success(api.year_tick({"as_of_year": 2027}, _ADMIN))
    final = validate_success(api.get_rmd_distribution(rmd["id"], _ADMIN))
    assert final["status"] == "MISSED"


def test_list_contribution_periods_filtered_by_participant_and_status(api):
    """PRD §2.3: "List endpoints expose two query parameters that govern paging: `limit`, the maximum number of items returned, which defaults to 10 and is bounded by a minimum of 1 and a maximum of 100; and `offset`, the number of items to skip, which defaults to 0."
    PRD §3.3: "The period is finalized by a plan administrator closing it, transitioning `OPEN → CLOSED`."

    GET /contribution-periods?participant_id=...&status=CLOSED returns only the
    CLOSED period and excludes the OPEN one.

    Design: Corner/cross_cutting_complexity_layers/pagination_with_filter_status
    """
    set_clock("2026-06-15T00:00:00Z")
    plan = create_and_activate_plan(name="PF", match_formula="TIERED",
                                    vesting_schedule="GRADED_6")
    participant = create_and_enroll_participant(
        plan["id"], full_name="PF",
        date_of_birth="1980-06-15T00:00:00Z",
        hire_date="2024-06-15T00:00:00Z",
        annual_compensation_cents=12_000_000,
        deferral_rate_bps=400,
    )
    closed_cp = create_open_contribution_period(participant["id"],
                                                period_end_date="2026-05-31T00:00:00Z",
                                                gross_compensation_cents=500_000)
    close_contribution_period(closed_cp["id"])
    open_cp = create_open_contribution_period(participant["id"],
                                              period_end_date="2026-06-15T00:00:00Z",
                                              gross_compensation_cents=500_000)
    res = api.list_contribution_periods(_ADMIN, params={
        "participant_id": participant["id"], "status": "CLOSED",
    })
    data, _meta = validate_paginated(res)
    ids = {cp["id"] for cp in data}
    assert closed_cp["id"] in ids
    assert open_cp["id"] not in ids
