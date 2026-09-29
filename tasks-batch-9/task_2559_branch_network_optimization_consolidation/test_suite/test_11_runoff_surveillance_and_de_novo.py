"""Post-closure runoff surveillance and de novo growth: siting gates, ramp curves and the hold that
couples a market's runoff breach to its growth pipeline."""

from test_helpers import (
    APPROVER,
    COMPLIANCE,
    OPS_ADMIN,
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_de_novo_plan,
    assert_deposit_observation,
    case_observation_payload,
    de_novo_plan_payload,
    plan_observation_payload,
    read_branch,
    read_case,
    read_market,
    read_plan,
    set_clock,
    setup_approved_de_novo_plan,
    setup_de_novo_plan,
    setup_draft_case,
    setup_execution_ready_case,
    setup_market,
    setup_market_with_branches,
    validate_error,
    validate_paginated,
    validate_success,
)

NORTHGATE = {
    "name": "Northgate",
    "region_code": "MW-09",
    "population": 100000,
    "median_household_income_cents": 6000000,
    "deposit_market_total_cents": 400000000000,
    "competitor_branch_count": 28,
    "household_growth_pct_bps": 150,
    "digital_penetration_bps": 4800,
}

CROWN_HEIGHTS = {
    "name": "Crown Heights",
    "region_code": "MD-02",
    "population": 100000,
    "median_household_income_cents": 12000000,
    "deposit_market_total_cents": 435000000000,
    "competitor_branch_count": 28,
    "household_growth_pct_bps": 500,
    "digital_penetration_bps": 6000,
}

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

RIVERBEND_CROSSING = {
    "name": "Riverbend",
    "region_code": "MD-04",
    "population": 120000,
    "median_household_income_cents": 8520000,
    "deposit_market_total_cents": 240000000000,
    "competitor_branch_count": 24,
    "household_growth_pct_bps": 350,
    "digital_penetration_bps": 5000,
}

HARBOR_NORTH = {
    "name": "Harbor North",
    "region_code": "MD-07",
    "population": 240000,
    "median_household_income_cents": 12000000,
    "deposit_market_total_cents": 465000000000,
    "competitor_branch_count": 30,
    "household_growth_pct_bps": 5000,
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
_LATE_WAVE = {
    "wave_start_date": "2026-10-01",
    "wave_end_date": "2026-10-11",
    "inbound_household_count": 300,
}
LOW_IMPACT_ASSESSMENT = {"senior_household_pct_bps": 1600}


def _decide(plan_id, decision, **body):
    payload = {"decision": decision}
    payload.update(body)
    return api_client.decide_de_novo_plan(plan_id, payload, APPROVER)


def test_01_a_site_half_a_point_short_of_the_minimum_may_be_recorded_but_not_approved():
    """Northgate's thin household growth and modest incomes score the site at forty-five points once
    the dense competition is inverted to nothing. The record is accepted; only the approval refuses,
    and the rejection route stays open.

    PRD: "The **competition factor** is the market's `competitor_density_index` multiplied by 4 and rounded half up, then capped at 100 — and it enters the blend *inverted*, as 100 minus the factor, because dense competition is a penalty."
    PRD: "The four are blended at fixed weights of 3000, 2500, 2500 and 2000 basis points respectively: multiply growth by 3000, income by 2500, opportunity by 2500 and the inverted competition figure by 2000, sum the products, divide by 10000 and round half up."
    PRD: "An `APPROVE` carries three: the plan's `site_score` must be at least the siting minimum of 55 points, or `ERR_SITE_SCORE_BELOW_MINIMUM`; the market's `saturation_tier` must not be `OVER_BRANCHED`, or `ERR_MARKET_OVER_BRANCHED`; and the market's `de_novo_hold` must be false, or `ERR_MARKET_DE_NOVO_HOLD`."
    PRD: "A `REJECT` moves the plan to `REJECTED`, which is terminal, and carries no further precondition."
    Design: Corner/validations/de_novo_plan_below_site_score_minimum_is_rejected_at_approval
    """
    market = setup_market(**NORTHGATE)
    assert market["competitor_density_index"] == 28
    assert market["saturation_tier"] == "SATURATED"

    plan = validate_success(
        api_client.create_de_novo_plan(
            de_novo_plan_payload(
                market["id"], site_label="Northgate Commons", proposed_branch_code="NG-501"
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    assert_de_novo_plan(plan)
    assert plan["site_score"] == 45
    assert plan["status"] == "SITE_IDENTIFIED"

    validate_error(
        _decide(plan["id"], "APPROVE"),
        ApiErrorId.ERR_SITE_SCORE_BELOW_MINIMUM.value,
        expected_status=422,
    )
    refused = read_plan(plan["id"])
    assert refused["status"] == "SITE_IDENTIFIED"
    assert refused["opened_branch_id"] is None

    rejected = validate_success(_decide(plan["id"], "REJECT", reason_code="SCORE_TOO_LOW"))
    assert rejected["status"] == "REJECTED"


def test_02_a_perfect_site_is_still_refused_in_a_market_that_is_already_over_branched():
    """Crown Heights offers everything a site could want and the score clears the minimum outright,
    so the refusal comes from the market itself: two of the bank's own branches on top of twenty-eight
    rivals put the density exactly on the over-branched edge.

    PRD: "A `branch_density_per_100k` of 30 or more makes the market `OVER_BRANCHED`; from 15 up to but not including 30 it is `SATURATED`; below 15 it is `UNDER_BRANCHED`."
    PRD: "An `APPROVE` carries three: the plan's `site_score` must be at least the siting minimum of 55 points, or `ERR_SITE_SCORE_BELOW_MINIMUM`; the market's `saturation_tier` must not be `OVER_BRANCHED`, or `ERR_MARKET_OVER_BRANCHED`; and the market's `de_novo_hold` must be false, or `ERR_MARKET_DE_NOVO_HOLD`."
    Design: Corner/validations/de_novo_plan_in_an_over_branched_market_is_rejected_at_approval
    """
    ctx = setup_market_with_branches(market_overrides=CROWN_HEIGHTS)
    market = read_market(ctx["market"]["id"])
    assert market["branch_density_per_100k"] == 30
    assert market["saturation_tier"] == "OVER_BRANCHED"
    assert market["de_novo_hold"] is False

    plan = setup_de_novo_plan(
        market["id"], site_label="Crown Heights Pad", proposed_branch_code="CH-601"
    )
    assert plan["site_score"] == 80

    validate_error(
        _decide(plan["id"], "APPROVE"),
        ApiErrorId.ERR_MARKET_OVER_BRANCHED.value,
        expected_status=409,
    )
    assert read_plan(plan["id"])["status"] == "SITE_IDENTIFIED"


def test_03_an_approved_site_cannot_be_rejected_afterwards_and_survives_the_attempt_intact():
    """Both decision branches are declared from one state only, so a change of heart after the
    approval is refused — and the plan is still perfectly openable afterwards.

    PRD: "A `ConsolidationApprover` decides an identified site with a `decision` of `APPROVE` or `REJECT` and an optional `reason_code`; the decision is available only from `SITE_IDENTIFIED` status, and any other status is `ERR_PLAN_STATE_INVALID`."
    PRD: "The plan must be `APPROVED`, the market's `de_novo_hold` must still be false (otherwise `ERR_MARKET_DE_NOVO_HOLD`), and the `proposed_branch_code` must still be unused by any branch (otherwise `ERR_DUPLICATE_KEY`)."
    Design: Corner/validations/deciding_an_already_approved_plan_returns_plan_state_invalid
    """
    market = setup_market(**RIVERBEND)
    approved = setup_approved_de_novo_plan(
        market["id"], site_label="Northgate Pad B", proposed_branch_code="RB-701"
    )
    assert approved["site_score"] == 59
    assert approved["status"] == "APPROVED"

    validate_error(
        _decide(approved["id"], "REJECT", reason_code="BUDGET_PULLED"),
        ApiErrorId.ERR_PLAN_STATE_INVALID.value,
        expected_status=409,
    )
    untouched = read_plan(approved["id"])
    assert untouched["status"] == "APPROVED"
    assert untouched["version"] == approved["version"]

    opened = validate_success(
        api_client.open_de_novo_plan(
            approved["id"], {"branch_type": "FULL_SERVICE", "tenure_class": "LEASED"}, STRATEGIST
        )
    )
    assert opened["opened_branch_id"] is not None


def test_04_opening_an_approved_site_mints_a_ramping_branch_and_resyncs_the_trade_area():
    """One call walks the plan from approved to tracking, brings a branch into existence with entirely
    system-assigned financials, and re-derives the trade area's footprint around it.

    PRD: "The server mints a branch in the plan's trade area with `branch_code` set to the `proposed_branch_code`, `deposit_balance_cents` of zero, `fte_count` of zero, `atm_count` of 1 and `performance_band` of `UNSCORED`, and moves it `ACTIVE → DE_NOVO_RAMPING`; the plan's `opened_branch_id` is set to that branch and `opened_on` is stamped from the logical clock."
    PRD: "The market's `own_branch_count` increases by one with `branch_density_per_100k` and `saturation_tier` recomputed — a de novo opening is one of the events that can push a market into a higher saturation tier."
    PRD: "The plan itself transitions `APPROVED → OPENED` and immediately into `RAMP_TRACKING`, with `ramp_month_index` at zero and `ramp_status` set to `ON_TRACK`."
    Design: Corner/endpoints/opening_an_approved_de_novo_plan_mints_a_ramping_branch_and_resyncs_the_market
    """
    market = setup_market(**HARBOR_NORTH)
    assert market["own_branch_count"] == 0
    assert market["branch_density_per_100k"] == 13
    approved = setup_approved_de_novo_plan(market["id"])
    assert approved["site_score"] == 90
    assert approved["status"] == "APPROVED"

    opened = validate_success(
        api_client.open_de_novo_plan(
            approved["id"],
            {
                "branch_type": "LIMITED_SERVICE",
                "tenure_class": "LEASED",
                "onboarding_capacity_households_per_day": 40,
            },
            STRATEGIST,
        )
    )
    assert opened["status"] == "RAMP_TRACKING"
    assert opened["ramp_status"] == "ON_TRACK"
    assert opened["ramp_month_index"] == 0
    assert opened["opened_on"] == "2026-08-01"
    assert opened["opened_branch_id"] is not None

    minted = read_branch(opened["opened_branch_id"])
    assert minted["branch_code"] == "HN-301"
    assert minted["status"] == "DE_NOVO_RAMPING"
    assert minted["deposit_balance_cents"] == 0
    assert minted["fte_count"] == 0
    assert minted["atm_count"] == 1
    assert minted["performance_band"] == "UNSCORED"
    assert minted["snapshot_count"] == 0
    assert minted["branch_type"] == "LIMITED_SERVICE"
    assert minted["tenure_class"] == "LEASED"
    assert minted["onboarding_capacity_households_per_day"] == 40

    resynced = read_market(market["id"])
    assert resynced["own_branch_count"] == 1
    assert resynced["branch_density_per_100k"] == 13
    assert resynced["saturation_tier"] == "UNDER_BRANCHED"

    plans, meta = validate_paginated(
        api_client.list_de_novo_plans(
            STRATEGIST, params={"opened_branch_id": opened["opened_branch_id"]}
        )
    )
    assert meta["total_count"] == 1
    assert plans[0]["id"] == approved["id"]


def test_05_the_ramp_curve_only_reaches_the_year_one_target_in_the_twelfth_month():
    """A quadratic ramp expects a quarter of the year-one target at the half-year mark, so an exactly
    on-curve month six is on track but never "met"; only the twelfth month measures against the whole
    target, and clearing it graduates the branch out of its ramp.

    PRD: "For an observation at month index k, the cumulative target is the plan's `target_year1_deposits_cents` multiplied by k, multiplied by k again, divided by 144 and rounded half up — a curve that starts slowly and reaches exactly the year-one target at month 12."
    PRD: "The plan's `ramp_attainment_bps` is the `observed_deposits_cents` multiplied by 10000, divided by that cumulative target and rounded half up, and the observation's `variance_bps` is that attainment minus 10000, so an attainment exactly on curve records a variance of zero."
    PRD: "`ramp_status` is then derived in a fixed order of tests: `MET` when the month index is 12 and attainment is at least 9000 basis points; otherwise `AT_RISK` when attainment is below 7000 basis points; otherwise `ON_TRACK` when attainment is 10000 basis points or more; otherwise `BEHIND`."
    PRD: "and a month-12 observation attaining at least 9000 basis points moves a `RAMP_TRACKING` plan to `RAMP_MET`, which is terminal, sets `ramp_status` to `MET`, and graduates the branch itself from `DE_NOVO_RAMPING → ACTIVE` with that branch's `version` incremented."
    Design: Corner/calculations/de_novo_ramp_quadratic_curve_reaches_target_only_at_month_twelve
    """
    market = setup_market(**RIVERBEND_CROSSING)
    approved = setup_approved_de_novo_plan(
        market["id"],
        site_label="Riverbend Crossing",
        proposed_branch_code="RB-401",
        target_year1_deposits_cents=12000000000,
        capex_budget_cents=4000000000,
    )
    assert approved["site_score"] == 59
    opened = validate_success(
        api_client.open_de_novo_plan(
            approved["id"], {"branch_type": "FULL_SERVICE", "tenure_class": "LEASED"}, STRATEGIST
        )
    )

    half_year = validate_success(
        api_client.create_deposit_observation(
            plan_observation_payload(approved["id"], 6, 3000000000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert_deposit_observation(half_year)
    assert half_year["forecast_deposits_cents"] == 3000000000
    assert half_year["variance_bps"] == 0
    tracking = read_plan(approved["id"])
    assert tracking["ramp_attainment_bps"] == 10000
    assert tracking["ramp_status"] == "ON_TRACK"
    assert tracking["status"] == "RAMP_TRACKING"

    full_year = validate_success(
        api_client.create_deposit_observation(
            plan_observation_payload(approved["id"], 12, 11000000000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert full_year["forecast_deposits_cents"] == 12000000000
    assert full_year["variance_bps"] == -833
    assert full_year["breach"] is False

    met = read_plan(approved["id"])
    assert met["ramp_attainment_bps"] == 9167
    assert met["ramp_status"] == "MET"
    assert met["status"] == "RAMP_MET"
    assert met["ramp_month_index"] == 12
    assert read_branch(opened["opened_branch_id"])["status"] == "ACTIVE"


def test_06_a_case_that_has_not_closed_yet_is_not_a_trackable_subject():
    """Surveillance measures deposits against a stamped pre-close baseline, so a case still in draft is
    no subject at all — and naming two subjects at once is refused by the same rule.

    PRD: "Supplying the wrong key, supplying both, supplying neither, or naming a subject that is not in a trackable state — a case must be in `CLOSURE_EXECUTED` or `POST_CLOSE_MONITORING` status, a plan in `OPENED`, `RAMP_TRACKING` or `RAMP_REMEDIATION` status — is rejected with `ERR_OBSERVATION_SUBJECT_MISMATCH`."
    PRD: "Exactly one foreign key must accompany the subject type: `consolidation_case_id` for a consolidation case and `de_novo_plan_id` for a de novo plan, with the other **absent**."
    Design: Corner/validations/observation_for_a_draft_case_returns_observation_subject_mismatch
    """
    ctx = setup_draft_case()
    plan = setup_de_novo_plan(ctx["market"]["id"], proposed_branch_code="HN-901")

    validate_error(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 1, 4700000000), OPS_ADMIN
        ),
        ApiErrorId.ERR_OBSERVATION_SUBJECT_MISMATCH.value,
        expected_status=422,
    )
    _, meta = validate_paginated(
        api_client.list_deposit_observations(
            OPS_ADMIN, params={"consolidation_case_id": ctx["case"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    case = read_case(ctx["case"]["id"])
    assert case["last_observed_month_index"] == 0
    assert case["monitoring_posture"] == "NOT_STARTED"

    validate_error(
        api_client.create_deposit_observation(
            case_observation_payload(
                ctx["case"]["id"], 1, 4700000000, de_novo_plan_id=plan["id"]
            ),
            OPS_ADMIN,
        ),
        ApiErrorId.ERR_OBSERVATION_SUBJECT_MISMATCH.value,
        expected_status=422,
    )


def test_07_a_backfilled_month_is_refused_once_a_later_month_has_been_read():
    """The runoff curve has spent six thousand basis points of the projected attrition by the third
    month, and an exactly on-curve reading records no variance. Surveillance then only moves forward:
    the month behind it is refused and nothing is written.

    PRD: "For an observation at month index k, take the cumulative weight as the sum of the first k shares."
    PRD: "`forecast_deposits_cents` is then the case's stamped `pre_close_deposits_cents` minus the case's `forecast_runoff_cents` multiplied by that cumulative weight, divided by 10000 and rounded half up."
    PRD: "Observations must also arrive in strictly increasing month order: the `month_index` must be strictly greater than the subject's highest recorded month, or the post is rejected with `ERR_OBSERVATION_OUT_OF_SEQUENCE`."
    PRD: "Only the highest-indexed observation drives posture; earlier observations are never re-read."
    Design: Corner/calculations/runoff_observation_out_of_order_month_rejected_after_higher_index_recorded
    """
    ctx = setup_execution_ready_case()
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))

    third_month = validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 3, 4569600000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert third_month["forecast_deposits_cents"] == 4569600000
    assert third_month["variance_bps"] == 0
    assert third_month["breach"] is False

    validate_error(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 2, 4700000000), OPS_ADMIN
        ),
        ApiErrorId.ERR_OBSERVATION_OUT_OF_SEQUENCE.value,
        expected_status=409,
    )

    monitored = read_case(ctx["case"]["id"])
    assert monitored["status"] == "POST_CLOSE_MONITORING"
    assert monitored["last_observed_month_index"] == 3
    assert monitored["cumulative_variance_bps"] == 0
    assert monitored["monitoring_posture"] == "ON_TRACK"
    _, meta = validate_paginated(
        api_client.list_deposit_observations(
            OPS_ADMIN, params={"consolidation_case_id": ctx["case"]["id"]}
        )
    )
    assert meta["total_count"] == 1
    market = read_market(ctx["market"]["id"])
    assert market["remediation_case_count"] == 0
    assert market["de_novo_hold"] is False


def _riverbend_breach_ready():
    """An executed Riverbend closure sitting alongside an approved de novo site in the same market."""
    ctx = setup_market_with_branches(
        market_overrides=RIVERBEND, closing_overrides=_CLOSING, receiving_overrides=_RECEIVING
    )
    plan = setup_approved_de_novo_plan(
        ctx["market"]["id"],
        site_label="Northgate Pad B",
        proposed_branch_code="RB-701",
        target_year1_deposits_cents=12000000000,
        capex_budget_cents=45000000,
    )
    ctx = setup_execution_ready_case(
        ctx,
        case_overrides={"planned_closure_date": "2026-11-15"},
        forecast_overrides=DECAY_AT_3_4,
        assessment_overrides=LOW_IMPACT_ASSESSMENT,
        campaign_overrides=_LATE_WAVE,
    )
    set_clock("2026-11-02T00:00:00Z")
    ctx["case"] = validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))
    return ctx, plan


def test_08_a_first_month_reading_exactly_on_the_breach_threshold_puts_the_case_into_remediation():
    """A quarter of the projected runoff is expected to have gone by the first month; deposits three
    hundred basis points under that forecast are a breach on the inclusive edge, and the case's posture
    axis moves without waiting for a second reading.

    PRD: "`variance_bps` is the difference between `observed_deposits_cents` and that forecast, multiplied by 10000, divided by the forecast and rounded half up — a signed figure where a negative value means deposits came in worse than modelled."
    PRD: "The observation's `breach` flag is true when `variance_bps` is at or below -300 basis points; the threshold is inclusive, so exactly -300 basis points breaches while -299 does not."
    PRD: "The first observation also transitions the case `CLOSURE_EXECUTED → POST_CLOSE_MONITORING` and increments its `version`."
    PRD: "The case's `monitoring_posture` — an axis entirely independent of the case's `status`, running `NOT_STARTED`, `ON_TRACK`, `REMEDIATION` and `RESOLVED` — is then re-derived from the newest variance in a **first hop**: the posture becomes `REMEDIATION` if the observation breached; otherwise, if the posture was already `REMEDIATION` and the new `variance_bps` has recovered to at least -150 basis points, it becomes `RESOLVED`; otherwise it becomes `ON_TRACK`."
    Design: Difficulty/transitive_cascade/runoff_breach_cascade_holds_approved_de_novo_plan
    """
    ctx, _ = _riverbend_breach_ready()
    assert ctx["case"]["pre_close_deposits_cents"] == 4800000000
    assert ctx["case"]["monitoring_posture"] == "NOT_STARTED"
    assert ctx["case"]["last_observed_month_index"] == 0

    breach = validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 1, 4562880000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert_deposit_observation(breach)
    assert breach["forecast_deposits_cents"] == 4704000000
    assert breach["variance_bps"] == -300
    assert breach["breach"] is True

    case = read_case(ctx["case"]["id"])
    assert case["status"] == "POST_CLOSE_MONITORING"
    assert case["monitoring_posture"] == "REMEDIATION"
    assert case["last_observed_month_index"] == 1
    assert case["cumulative_variance_bps"] == -300
    assert case["version"] > ctx["case"]["version"]


def test_09_the_same_breach_puts_the_market_on_hold_and_demotes_its_approved_site():
    """One deposit reading on a closed branch reaches all the way into the growth pipeline: the trade
    area counts a case in remediation, the hold flips on, and the approved site next door is demoted
    while keeping the score it earned.

    PRD: "In a **second hop**, when the posture enters `REMEDIATION` in this request the trade area's `remediation_case_count` increases by one, and when it leaves `REMEDIATION` for `RESOLVED` the count decreases by one."
    PRD: "In a **third hop**, the trade area's `de_novo_hold` is re-derived within the same request as true whenever `remediation_case_count` is 1 or more and false otherwise."
    PRD: "In a **fourth hop**, when `de_novo_hold` flips from false to true, every de novo site plan of that market standing at `APPROVED` transitions to `HELD`; when it flips from true to false, every plan standing at `HELD` returns to `APPROVED`."
    Design: Difficulty/transitive_cascade/runoff_breach_cascade_holds_approved_de_novo_plan
    """
    ctx, plan = _riverbend_breach_ready()
    assert plan["status"] == "APPROVED"
    assert plan["site_score"] == 59
    before = read_market(ctx["market"]["id"])
    assert before["remediation_case_count"] == 0
    assert before["de_novo_hold"] is False
    assert before["flagged_case_count"] == 1

    validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 1, 4562880000), OPS_ADMIN
        ),
        expected_status=201,
    )

    market = read_market(ctx["market"]["id"])
    assert market["remediation_case_count"] == 1
    assert market["de_novo_hold"] is True
    assert market["flagged_case_count"] == 1

    held = read_plan(plan["id"])
    assert held["status"] == "HELD"
    assert held["site_score"] == 59
    assert held["version"] > plan["version"]


def test_10_a_site_that_passes_on_its_own_merits_is_still_held_by_a_sibling_closure_s_breach():
    """Nothing about the site or the market's density stands in the way — a ninety-point site in an
    under-branched market — yet the approval is refused, because a completely separate closure's runoff
    reading has put the whole trade area on hold. The plan is refused, not demoted.

    PRD: "An `APPROVE` carries three: the plan's `site_score` must be at least the siting minimum of 55 points, or `ERR_SITE_SCORE_BELOW_MINIMUM`; the market's `saturation_tier` must not be `OVER_BRANCHED`, or `ERR_MARKET_OVER_BRANCHED`; and the market's `de_novo_hold` must be false, or `ERR_MARKET_DE_NOVO_HOLD`."
    PRD: "In a **third hop**, the trade area's `de_novo_hold` is re-derived within the same request as true whenever `remediation_case_count` is 1 or more and false otherwise."
    PRD: "In a **fourth hop**, when `de_novo_hold` flips from false to true, every de novo site plan of that market standing at `APPROVED` transitions to `HELD`; when it flips from true to false, every plan standing at `HELD` returns to `APPROVED`."
    Design: Corner/validations/plan_approval_is_blocked_while_the_market_sits_on_a_de_novo_hold
    """
    ctx = setup_market_with_branches(
        market_overrides=HARBOR_NORTH,
        closing_overrides={"branch_code": "HN-201"},
        receiving_overrides={"branch_code": "HN-202"},
    )
    market = read_market(ctx["market"]["id"])
    assert market["competitor_density_index"] == 13
    assert market["saturation_tier"] == "UNDER_BRANCHED"
    plan = setup_de_novo_plan(ctx["market"]["id"])
    assert plan["site_score"] == 90
    assert plan["status"] == "SITE_IDENTIFIED"

    ctx = setup_execution_ready_case(ctx)
    assert ctx["assessment"]["impact_score"] == 29
    assert ctx["assessment"]["impact_tier"] == "LOW"
    assert ctx["assessment"]["notice_required_days"] == 90
    set_clock("2026-11-01T00:00:00Z")
    validate_success(api_client.execute_closure(ctx["case"]["id"], COMPLIANCE))

    breach = validate_success(
        api_client.create_deposit_observation(
            case_observation_payload(ctx["case"]["id"], 1, 4562880000), OPS_ADMIN
        ),
        expected_status=201,
    )
    assert breach["forecast_deposits_cents"] == 4704000000
    assert breach["variance_bps"] == -300
    assert breach["breach"] is True
    held_market = read_market(ctx["market"]["id"])
    assert held_market["remediation_case_count"] == 1
    assert held_market["de_novo_hold"] is True
    assert read_case(ctx["case"]["id"])["monitoring_posture"] == "REMEDIATION"

    validate_error(
        _decide(plan["id"], "APPROVE"),
        ApiErrorId.ERR_MARKET_DE_NOVO_HOLD.value,
        expected_status=409,
    )
    untouched = read_plan(plan["id"])
    assert untouched["status"] == "SITE_IDENTIFIED"
    assert untouched["version"] == plan["version"]
    assert read_market(ctx["market"]["id"])["saturation_tier"] == "UNDER_BRANCHED"
