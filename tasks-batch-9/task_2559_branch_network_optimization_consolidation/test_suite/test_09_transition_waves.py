"""Customer transition waves: half-open intervals, aggregate onboarding capacity and launch gates."""

from test_helpers import (
    COMPLIANCE,
    REAL_ESTATE,
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_transition_campaign,
    branch_payload,
    consolidation_case_payload,
    leased_property_disposition_payload,
    read_assessment,
    read_branch,
    read_campaign,
    read_case,
    read_notice,
    set_clock,
    setup_approved_case,
    setup_campaign,
    setup_market_with_branches,
    setup_notice_filed_case,
    transition_campaign_payload,
    validate_error,
    validate_paginated,
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


def _three_cases_on_one_survivor() -> dict:
    """Riverbend North where RB-101, RB-103 and RB-105 all close into RB-102's calendar."""
    ctx = setup_market_with_branches(
        market_overrides=RIVERBEND,
        closing_overrides={
            "monthly_transaction_count": 3600,
            "annual_revenue_cents": 140000000,
        },
        receiving_overrides={
            "monthly_transaction_count": 7200,
            "digital_adoption_bps": 6800,
            "annual_noninterest_expense_cents": 118000000,
            "annual_revenue_cents": 305000000,
            "opened_on": "1998-06-15",
            "onboarding_capacity_households_per_day": 60,
        },
    )
    survivor = ctx["receiving_branch"]
    assert survivor["onboarding_capacity_households_per_day"] == 60

    third = validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-103",
                monthly_transaction_count=3300,
                annual_revenue_cents=132000000,
                fte_count=8,
                atm_count=1,
                opened_on="2007-09-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    fifth = validate_success(
        api_client.create_branch(
            branch_payload(
                ctx["market"]["id"],
                branch_code="RB-105",
                branch_type="LIMITED_SERVICE",
                deposit_balance_cents=2400000000,
                monthly_transaction_count=1900,
                digital_adoption_bps=5800,
                annual_noninterest_expense_cents=26000000,
                annual_revenue_cents=74000000,
                fte_count=5,
                atm_count=1,
                opened_on="2013-06-03",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    cases = {}
    for key, branch, rationale in (
        ("a", ctx["closing_branch"], "LOW_PERFORMANCE"),
        ("b", third, "MARKET_OVERLAP"),
        ("c", fifth, "DIGITAL_MIGRATION"),
    ):
        cases[key] = validate_success(
            api_client.create_consolidation_case(
                consolidation_case_payload(
                    branch["id"],
                    branch["version"],
                    receiving_branch_id=survivor["id"],
                    rationale_code=rationale,
                ),
                STRATEGIST,
            ),
            expected_status=201,
        )
    return {"survivor": survivor, "cases": cases}


def _plan_wave(case_id: str, start: str, end: str, households: int, channel_mix: str):
    return api_client.create_transition_campaign(
        transition_campaign_payload(
            case_id,
            wave_start_date=start,
            wave_end_date=end,
            inbound_household_count=households,
            channel_mix=channel_mix,
        ),
        COMPLIANCE,
    )


def test_01_two_waves_may_overlap_while_their_summed_daily_load_sits_on_capacity():
    """Two closures pointing at the same survivor may run overlapping waves: on the five days both
    waves cover, the survivor takes thirty households from each, which is exactly its declared daily
    ceiling and therefore permitted.

    PRD: "The server copies `receiving_branch_id` from the case — the receiving branch is the resource whose calendar the wave occupies — and opens the campaign in `PLANNED` status."
    PRD: "`wave_days` is accordingly the whole calendar days from `wave_start_date` to `wave_end_date`, and `daily_onboarding_load` is the `inbound_household_count` divided by `wave_days` and rounded half up — the per-day burden charged against the receiving branch."
    PRD: "The test is a strict exceedance, so a peak day landing exactly on capacity is allowed."
    PRD: "Two campaigns may share a receiving branch and may even overlap in time, provided their summed daily load never exceeds capacity on any single day."
    Design: Difficulty/resource_temporal_overlap/campaign_waves_share_receiving_branch_until_aggregate_capacity_breaks
    """
    network = _three_cases_on_one_survivor()

    first = validate_success(
        _plan_wave(
            network["cases"]["a"]["id"], "2026-10-01", "2026-10-11", 300, "LETTER_EMAIL"
        ),
        expected_status=201,
    )
    assert_transition_campaign(first)
    assert first["wave_days"] == 10
    assert first["daily_onboarding_load"] == 30
    assert first["receiving_branch_id"] == network["survivor"]["id"]
    assert first["status"] == "PLANNED"

    second = validate_success(
        _plan_wave(
            network["cases"]["b"]["id"], "2026-10-06", "2026-10-16", 300, "LETTER_ONLY"
        ),
        expected_status=201,
    )
    assert second["wave_days"] == 10
    assert second["daily_onboarding_load"] == 30
    assert second["receiving_branch_id"] == network["survivor"]["id"]
    assert second["status"] == "PLANNED"

    _, meta = validate_paginated(
        api_client.list_transition_campaigns(
            COMPLIANCE, params={"receiving_branch_id": network["survivor"]["id"]}
        )
    )
    assert meta["total_count"] == 2


def test_02_one_more_household_a_day_breaks_the_survivor_while_a_touching_wave_does_not():
    """A third wave asking for a single household a day tips three shared days one over the ceiling
    and is refused, yet a fourth wave beginning on the day the second wave's excluded end date falls
    carries the survivor's whole capacity and is accepted.

    PRD: "If the highest such daily load exceeds the receiving branch's `onboarding_capacity_households_per_day`, the plan is rejected with `ERR_ABSORPTION_CAPACITY_EXCEEDED`."
    PRD: "Two half-open intervals overlap when the first starts strictly before the second ends and the second starts strictly before the first ends, so touching endpoints do **not** collide — a wave ending on the fifteenth and another starting on the fifteenth are independent."
    PRD: "The candidate set is every campaign on the same receiving branch in `PLANNED` or `LAUNCHED` status; `COMPLETED` and `CANCELLED` campaigns release their interval and are not counted."
    Design: Difficulty/resource_temporal_overlap/campaign_waves_share_receiving_branch_until_aggregate_capacity_breaks
    """
    network = _three_cases_on_one_survivor()
    validate_success(
        _plan_wave(
            network["cases"]["a"]["id"], "2026-10-01", "2026-10-11", 300, "LETTER_EMAIL"
        ),
        expected_status=201,
    )
    validate_success(
        _plan_wave(
            network["cases"]["b"]["id"], "2026-10-06", "2026-10-16", 300, "LETTER_ONLY"
        ),
        expected_status=201,
    )

    validate_error(
        _plan_wave(
            network["cases"]["c"]["id"], "2026-10-08", "2026-10-18", 10, "FULL_OMNI"
        ),
        ApiErrorId.ERR_ABSORPTION_CAPACITY_EXCEEDED.value,
        expected_status=409,
    )

    fourth = validate_success(
        _plan_wave(
            network["cases"]["c"]["id"], "2026-10-16", "2026-10-26", 600, "FULL_OMNI"
        ),
        expected_status=201,
    )
    assert fourth["wave_days"] == 10
    assert fourth["daily_onboarding_load"] == 60
    assert fourth["status"] == "PLANNED"

    rows, meta = validate_paginated(
        api_client.list_transition_campaigns(
            COMPLIANCE, params={"receiving_branch_id": network["survivor"]["id"]}
        )
    )
    assert meta["total_count"] == 3
    assert len(rows) == 3
    for case in network["cases"].values():
        assert read_case(case["id"])["status"] == "DRAFT"


def test_03_an_uneven_wave_rounds_its_daily_burden_up_rather_than_truncating_it():
    """Three hundred and five households across ten days is thirty and a half a day, and the burden
    charged against the survivor is the rounded-up thirty-one — still inside the survivor's default
    ceiling, so the plan stands.

    PRD: "`wave_days` is accordingly the whole calendar days from `wave_start_date` to `wave_end_date`, and `daily_onboarding_load` is the `inbound_household_count` divided by `wave_days` and rounded half up — the per-day burden charged against the receiving branch."
    PRD: "The wave interval is **half-open**: the `wave_start_date` is included and the `wave_end_date` is excluded."
    PRD: "If the highest such daily load exceeds the receiving branch's `onboarding_capacity_households_per_day`, the plan is rejected with `ERR_ABSORPTION_CAPACITY_EXCEEDED`."
    Design: Corner/calculations/campaign_daily_load_rounds_half_up_on_an_uneven_wave
    """
    ctx = setup_approved_case()
    survivor = read_branch(ctx["receiving_branch"]["id"])
    assert survivor["onboarding_capacity_households_per_day"] == 40

    campaign = validate_success(
        _plan_wave(ctx["case"]["id"], "2026-09-01", "2026-09-11", 305, "LETTER_EMAIL"),
        expected_status=201,
    )

    assert campaign["wave_days"] == 10
    assert campaign["daily_onboarding_load"] == 31
    assert campaign["daily_onboarding_load"] != 30
    assert campaign["status"] == "PLANNED"
    assert campaign["receiving_branch_id"] == survivor["id"]


def test_04_a_wave_must_start_a_fortnight_after_the_notice_and_must_have_a_length():
    """The customer-communication window is measured from the day the notice was filed: a wave nine
    days out cannot be launched, one exactly fourteen days out is accepted, and a wave whose end date
    is not strictly after its start is refused at creation for the same reason.

    PRD: "The current logical date must fall strictly before the `wave_start_date` — a wave cannot be launched after it was due to begin — and the `wave_start_date` must fall at least 14 days after the `filed_on` date of the case's regulatory notice, so that customers receive their statutory notice before onboarding begins."
    PRD: "At creation the `wave_end_date` must fall strictly after the `wave_start_date`, or the plan is rejected with `ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT`."
    PRD: "Either dating failure is `ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT`."
    Design: Corner/validations/campaign_wave_starting_inside_the_notice_lead_window_is_rejected
    """
    ctx = setup_notice_filed_case()
    assert read_notice(ctx["notice"]["id"])["filed_on"] == "2026-08-01"

    too_soon = validate_success(
        _plan_wave(ctx["case"]["id"], "2026-08-10", "2026-08-15", 100, "LETTER_EMAIL"),
        expected_status=201,
    )
    validate_error(
        api_client.launch_transition_campaign(too_soon["id"], COMPLIANCE),
        ApiErrorId.ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT.value,
        expected_status=422,
    )
    still_planned = read_campaign(too_soon["id"])
    assert still_planned["status"] == "PLANNED"
    assert still_planned["launched_on"] is None

    accepted = validate_success(
        _plan_wave(ctx["case"]["id"], "2026-08-15", "2026-09-14", 600, "LETTER_EMAIL"),
        expected_status=201,
    )
    assert accepted["status"] == "PLANNED"
    assert accepted["wave_days"] == 30

    validate_error(
        _plan_wave(ctx["case"]["id"], "2026-09-10", "2026-09-10", 600, "LETTER_EMAIL"),
        ApiErrorId.ERR_CAMPAIGN_LEAD_TIME_INSUFFICIENT.value,
        expected_status=422,
    )


def test_05_a_wave_cannot_be_launched_until_the_regulator_has_been_told():
    """The launch trigger is guarded by the state of a different record: with the closure approved but
    no filing on the regulator's desk the wave stays planned, unlaunched and untouched.

    PRD: "Launching a wave is what makes it real, and it is gated on both the case and the calendar."
    PRD: "The case must stand at `NOTICE_FILED`; the campaign must stand at `PLANNED`, and a launch against any other campaign status is `ERR_CAMPAIGN_STATE_INVALID`."
    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    Design: Corner/state_machines/launch_campaign_before_notice_filed_returns_case_state_invalid
    """
    ctx = setup_approved_case()
    campaign = validate_success(
        _plan_wave(ctx["case"]["id"], "2026-09-01", "2026-10-01", 600, "LETTER_EMAIL"),
        expected_status=201,
    )
    assert campaign["wave_days"] == 30
    assert campaign["daily_onboarding_load"] == 20

    validate_error(
        api_client.launch_transition_campaign(campaign["id"], COMPLIANCE),
        ApiErrorId.ERR_CASE_STATE_INVALID.value,
        expected_status=409,
    )

    reread = read_campaign(campaign["id"])
    assert reread["status"] == "PLANNED"
    assert reread["launched_on"] is None
    assert reread["version"] == campaign["version"]
    assert read_case(ctx["case"]["id"])["status"] == "APPROVED"


def test_06_a_live_wave_cannot_be_relaunched_and_a_withdrawn_notice_cannot_be_withdrawn_twice():
    """Two state errors on either side of one withdrawal: relaunching a live wave is refused, the
    withdrawal itself walks the closure back and cancels the wave, and the second withdrawal is
    refused with the record left exactly as the first withdrawal left it.

    PRD: "The case must stand at `NOTICE_FILED`; the campaign must stand at `PLANNED`, and a launch against any other campaign status is `ERR_CAMPAIGN_STATE_INVALID`."
    PRD: "A withdrawal aimed at a notice already `WITHDRAWN` is rejected with `ERR_NOTICE_NOT_OPEN`."
    PRD: "When the withdrawn notice is the case's `REGULATOR` notice and the case stands at `NOTICE_FILED`, the withdrawal cascades: the case transitions `NOTICE_FILED → APPROVED` with its `version` incremented, the closing branch transitions `CLOSURE_SCHEDULED → UNDER_REVIEW` with its `version` incremented, the case's impact assessment transitions `FINALIZED → REOPENED`, and every transition campaign of the case in `PLANNED` or `LAUNCHED` status transitions to `CANCELLED`, releasing its wave interval from the receiving branch's calendar."
    Design: Corner/validations/relaunching_a_campaign_and_double_withdrawing_a_notice_both_return_state_errors
    """
    ctx = setup_notice_filed_case(case_overrides={"rationale_code": "DIGITAL_MIGRATION"})
    setup_campaign(ctx, launch=True)
    campaign = ctx["campaign"]
    assert campaign["status"] == "LAUNCHED"

    validate_error(
        api_client.launch_transition_campaign(campaign["id"], COMPLIANCE),
        ApiErrorId.ERR_CAMPAIGN_STATE_INVALID.value,
        expected_status=409,
    )
    assert read_campaign(campaign["id"])["version"] == campaign["version"]

    withdrawn = validate_success(
        api_client.withdraw_closure_notice(
            ctx["notice"]["id"], {"withdrawn_reason_code": "REGULATOR_OBJECTION"}, COMPLIANCE
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason_code"] == "REGULATOR_OBJECTION"
    assert read_case(ctx["case"]["id"])["status"] == "APPROVED"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_assessment(ctx["assessment"]["id"])["status"] == "REOPENED"
    assert read_campaign(campaign["id"])["status"] == "CANCELLED"

    validate_error(
        api_client.withdraw_closure_notice(
            ctx["notice"]["id"], {"withdrawn_reason_code": "PLAN_REVISION"}, COMPLIANCE
        ),
        ApiErrorId.ERR_NOTICE_NOT_OPEN.value,
        expected_status=409,
    )
    settled = read_notice(ctx["notice"]["id"])
    assert settled["version"] == withdrawn["version"]
    assert settled["withdrawn_reason_code"] == "REGULATOR_OBJECTION"
    assert read_case(ctx["case"]["id"])["status"] == "APPROVED"


def test_07_a_closure_waits_for_a_launched_wave_and_a_merely_planned_one_will_not_do():
    """The notice period has elapsed and the premises is in hand, but no customer wave is running:
    the closure is refused, refused again while the wave is only planned, and goes through the moment
    the wave is launched — which retires the wave along with the branch.

    PRD: "The case must have at least one campaign in `LAUNCHED` status, or `ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED`."
    PRD: "On success the campaign transitions `PLANNED → LAUNCHED` and `launched_on` is stamped."
    PRD: "Every disposition of the case at `OFFER_ACCEPTED` transitions to `COMPLETED`, and every campaign of the case at `LAUNCHED` transitions to `COMPLETED`."
    Design: Corner/errors/execute_closure_without_a_launched_campaign_returns_campaign_not_launched
    """
    ctx = setup_notice_filed_case(case_overrides={"rationale_code": "MARKET_OVERLAP"})
    assert read_notice(ctx["notice"]["id"])["effective_closure_date"] == "2026-11-01"
    validate_success(
        api_client.create_property_disposition(
            leased_property_disposition_payload(ctx["closing_branch"]["id"], ctx["case"]["id"]),
            REAL_ESTATE,
        ),
        expected_status=201,
    )
    set_clock("2026-11-01T00:00:00Z")

    validate_error(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE),
        ApiErrorId.ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED.value,
        expected_status=409,
    )
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"

    campaign = validate_success(
        _plan_wave(ctx["case"]["id"], "2026-11-05", "2026-11-25", 600, "LETTER_EMAIL"),
        expected_status=201,
    )
    assert campaign["status"] == "PLANNED"
    assert campaign["daily_onboarding_load"] == 30

    validate_error(
        api_client.execute_closure(ctx["case"]["id"], COMPLIANCE),
        ApiErrorId.ERR_TRANSITION_CAMPAIGN_NOT_LAUNCHED.value,
        expected_status=409,
    )

    launched = validate_success(
        api_client.launch_transition_campaign(campaign["id"], COMPLIANCE)
    )
    assert launched["status"] == "LAUNCHED"
    assert launched["launched_on"] == "2026-11-01"

    executed = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    assert executed["status"] == "CLOSURE_EXECUTED"
    assert read_campaign(campaign["id"])["status"] == "COMPLETED"
