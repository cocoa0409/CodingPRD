"""Community impact scoring, the regulatory lead clock, notice filing and withdrawal."""

from test_helpers import (
    COMPLIANCE,
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_impact_assessment,
    branch_payload,
    closure_notice_payload,
    consolidation_case_payload,
    impact_assessment_payload,
    read_assessment,
    read_branch,
    read_campaign,
    read_case,
    read_market,
    read_notice,
    set_clock,
    setup_approved_case,
    setup_campaign,
    setup_finalized_assessment,
    setup_market_with_branches,
    setup_notice_filed_case,
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

CEDAR_FLATS = {
    "name": "Cedar Flats",
    "region_code": "MW-07",
    "population": 90000,
    "median_household_income_cents": 6900000,
    "deposit_market_total_cents": 150000000000,
    "competitor_branch_count": 14,
    "household_growth_pct_bps": 180,
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

LOW_IMPACT_ASSESSMENT = {"senior_household_pct_bps": 1600}


def test_01_the_impact_score_is_clamped_up_to_zero_before_it_can_go_negative():
    """In an over-branched market a closure with no distance penalty, no senior concentration and
    the full access and transit reliefs computes to a negative total, which the scale's lower
    clamp must present as zero — still the lowest tier on the base notice period.

    PRD: "Add the base, the low-or-moderate-income component, the distance component, the senior component and the tier adjustment, subtract the access relief and the transit relief, then clamp the total to a minimum of 0 and finally to a maximum of 100; the clamps are applied in that written order."
    PRD: "Market saturation adjusts the score by a tier-dependent amount: an `UNDER_BRANCHED` market adds 10 points because the closure leaves a thin market thinner, an `OVER_BRANCHED` market subtracts 5 points, and a `SATURATED` market adjusts by zero."
    PRD: "At creation the server copies the closing branch's market `saturation_tier` onto the assessment as `market_saturation_tier_at_assessment`, freezing the conditional input of the impact formula at the moment of assessment rather than re-reading it later."
    Design: Corner/calculations/community_impact_score_clamps_at_zero_in_an_over_branched_market
    """
    ctx = setup_market_with_branches(
        market_overrides=CROWN_HEIGHTS,
        closing_overrides={"branch_code": "RB-501"},
        receiving_overrides={"branch_code": "RB-502"},
    )
    market = read_market(ctx["market"]["id"])
    assert market["branch_density_per_100k"] == 30
    assert market["competitor_density_index"] == 28
    assert market["saturation_tier"] == "OVER_BRANCHED"

    case = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
                rationale_code="MARKET_OVERLAP",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )

    assessment = validate_success(
        api_client.create_impact_assessment(
            case["id"],
            impact_assessment_payload(
                lmi_tract=False,
                distance_to_nearest_remaining_miles=0.0,
                alternative_access_count=4,
                senior_household_pct_bps=0,
                public_transit_access=True,
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )

    assert_impact_assessment(assessment)
    assert assessment["impact_score"] == 0
    assert assessment["impact_tier"] == "LOW"
    assert assessment["notice_required_days"] == 90
    assert assessment["requires_public_comment"] is False
    assert assessment["market_saturation_tier_at_assessment"] == "OVER_BRANCHED"
    assert assessment["status"] == "DRAFT"

    reread_case = read_case(case["id"])
    assert reread_case["impact_tier"] == "UNASSESSED"
    assert reread_case["notice_required_days"] == 0


def _cedar_flats_draft_case() -> dict:
    """Cedar Flats pair with a DRAFT case on RB-201 closing into RB-202."""
    ctx = setup_market_with_branches(
        market_overrides=CEDAR_FLATS,
        closing_overrides={
            "branch_code": "RB-201",
            "monthly_transaction_count": 3100,
            "annual_revenue_cents": 126000000,
            "fte_count": 7,
            "atm_count": 1,
            "opened_on": "2009-04-01",
        },
        receiving_overrides={
            "branch_code": "RB-202",
            "deposit_balance_cents": 8800000000,
            "monthly_transaction_count": 6900,
            "digital_adoption_bps": 6600,
            "annual_noninterest_expense_cents": 104000000,
            "annual_revenue_cents": 280000000,
            "fte_count": 13,
            "atm_count": 2,
            "opened_on": "2001-02-01",
            "onboarding_capacity_households_per_day": 45,
        },
    )
    ctx["case"] = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
                rationale_code="MARKET_OVERLAP",
                planned_closure_date="2027-01-15",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    return ctx


def _assess(case_id: str, **overrides) -> dict:
    """Record one impact assessment against a case with the Cedar Flats profile."""
    payload = impact_assessment_payload(
        senior_household_pct_bps=1600, alternative_access_count=3, public_transit_access=True,
        **overrides,
    )
    return validate_success(
        api_client.create_impact_assessment(case_id, payload, COMPLIANCE),
        expected_status=201,
    )


def test_02_five_miles_exactly_earns_the_lead_extension_and_four_point_nine_does_not():
    """One tenth of a mile changes two things at once: the distance points fall by one because
    the rounding lands lower, and the low-income extension switches off because the mileage gate
    is inclusive at five miles.

    PRD: "Distance adds 6 points per mile of `distance_to_nearest_remaining_miles`, rounded half up, capped at 30 points."
    PRD: "An extension of 30 days applies when the closure is in a low-or-moderate-income tract **and** the distance to the nearest remaining branch is at least 5.0 miles; both conditions must hold, and the distance threshold is inclusive, so exactly 5.0 miles adds the extension while 4.9 miles does not."
    PRD: "A separate flag, `requires_public_comment`, is true when either the tier is `HIGH` or `lmi_tract` is true — the two conditions are independent, so a low-scoring closure in a low-or-moderate-income tract still opens a comment period."
    Design: Difficulty/boundary_precision_check/notice_lead_extension_and_tier_thresholds_at_boundary
    """
    ctx = _cedar_flats_draft_case()

    at_floor = _assess(
        ctx["case"]["id"], lmi_tract=True, distance_to_nearest_remaining_miles=5.0
    )
    assert at_floor["impact_score"] == 59
    assert at_floor["impact_tier"] == "MODERATE"
    assert at_floor["notice_required_days"] == 120
    assert at_floor["requires_public_comment"] is True
    assert at_floor["market_saturation_tier_at_assessment"] == "SATURATED"

    below_floor = _assess(
        ctx["case"]["id"], lmi_tract=True, distance_to_nearest_remaining_miles=4.9
    )
    assert below_floor["impact_score"] == 58
    assert below_floor["impact_tier"] == "MODERATE"
    assert below_floor["notice_required_days"] == 90
    assert below_floor["requires_public_comment"] is True

    assert read_assessment(at_floor["id"])["status"] == "SUPERSEDED"


def test_03_dropping_the_low_income_tract_lands_one_point_under_the_middle_tier():
    """At the same five miles a tract that is not low-or-moderate-income scores 34 — one point
    below the middle tier's floor — opens no comment period, and each new assessment supersedes
    the last while the case itself stays unmirrored until a finalisation.

    PRD: "The score yields an `impact_tier`: 60 points or more is `HIGH`, from 35 up to but not including 60 is `MODERATE`, and below 35 is `LOW`."
    PRD: "Senior concentration adds one point per 800 basis points of `senior_household_pct_bps` — that is, one point per 8 percent of senior-headed households — with the division rounded **down** to a whole point and the result capped at 15 points."
    PRD: "Any prior assessment of the case that is not already `SUPERSEDED` transitions to `SUPERSEDED`, so a case has at most one live assessment; a superseded `FINALIZED` assessment also drags the case's `impact_tier` back to `UNASSESSED` and its `notice_required_days` back to zero until a newer assessment is finalised."
    Design: Difficulty/boundary_precision_check/notice_lead_extension_and_tier_thresholds_at_boundary
    """
    ctx = _cedar_flats_draft_case()
    case_id = ctx["case"]["id"]

    first = _assess(case_id, lmi_tract=True, distance_to_nearest_remaining_miles=5.0)
    second = _assess(case_id, lmi_tract=True, distance_to_nearest_remaining_miles=4.9)
    third = _assess(case_id, lmi_tract=False, distance_to_nearest_remaining_miles=5.0)

    assert third["impact_score"] == 34
    assert third["impact_tier"] == "LOW"
    assert third["notice_required_days"] == 90
    assert third["requires_public_comment"] is False
    assert third["status"] == "DRAFT"

    assert read_assessment(first["id"])["status"] == "SUPERSEDED"
    assert read_assessment(second["id"])["status"] == "SUPERSEDED"

    rows, meta = validate_paginated(
        api_client.list_case_impact_assessments(case_id, COMPLIANCE)
    )
    assert meta["total_count"] == 3
    assert rows[0]["id"] == third["id"]

    case = read_case(case_id)
    assert case["impact_tier"] == "UNASSESSED"
    assert case["notice_required_days"] == 0


def test_04_an_assessment_can_only_be_finalised_once_from_the_drafting_state():
    """Replaying the finalisation of an assessment that is already final is refused, its original
    stamp survives, and the figures it mirrored onto the case are written once and not twice.

    PRD: "Finalising an assessment is a `ComplianceOfficer` action available from `DRAFT` or from `REOPENED` status; a finalise request against an assessment already `FINALIZED`, or one already `SUPERSEDED`, is rejected with `ERR_ASSESSMENT_STATE_INVALID`."
    PRD: "Either way `finalized_on` is stamped from the logical clock, the assessment transitions to `FINALIZED`, the case's `impact_tier` and `notice_required_days` are refreshed from the assessment, and the case's `version` increments by one."
    Design: Corner/validations/finalizing_an_already_finalized_assessment_returns_assessment_state_invalid
    """
    ctx = setup_market_with_branches()
    ctx["case"] = validate_success(
        api_client.create_consolidation_case(
            consolidation_case_payload(
                ctx["closing_branch"]["id"],
                ctx["closing_branch"]["version"],
                receiving_branch_id=ctx["receiving_branch"]["id"],
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    ctx = setup_finalized_assessment(ctx)
    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "FINALIZED"
    assert assessment["impact_score"] == 19
    assert assessment["finalized_on"] == "2026-08-01"

    validate_error(
        api_client.finalize_impact_assessment(assessment["id"], COMPLIANCE),
        ApiErrorId.ERR_ASSESSMENT_STATE_INVALID.value,
        expected_status=409,
    )

    unchanged = read_assessment(assessment["id"])
    assert unchanged["status"] == "FINALIZED"
    assert unchanged["finalized_on"] == "2026-08-01"
    assert unchanged["version"] == assessment["version"]

    case = read_case(ctx["case"]["id"])
    assert case["impact_tier"] == "LOW"
    assert case["notice_required_days"] == 90


def _harbor_approved_with_assessment(case_overrides=None) -> dict:
    """Harbor Metro case carried to approval behind a finalised impact assessment."""
    ctx = setup_approved_case(case_overrides=case_overrides)
    return setup_finalized_assessment(ctx)


def test_05_a_notice_cannot_be_filed_behind_an_assessment_still_in_draft():
    """The regulatory posture gate is checked before the lead-time arithmetic, so a case whose
    assessment has never been finalised is refused on the assessment and files nothing.

    PRD: "The case's live, non-superseded assessment must exist and be `FINALIZED`, or the filing fails with `ERR_IMPACT_ASSESSMENT_NOT_FINALIZED`."
    PRD: "The same figure is written onto the assessment and, on finalisation, mirrored onto the case."
    Design: Corner/validations/filing_a_notice_with_a_draft_assessment_returns_impact_assessment_not_finalized
    """
    ctx = setup_approved_case()
    approved_version = ctx["case"]["version"]
    assessment = validate_success(
        api_client.create_impact_assessment(
            ctx["case"]["id"], impact_assessment_payload(), COMPLIANCE
        ),
        expected_status=201,
    )

    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(ctx["case"]["id"]), COMPLIANCE
        ),
        ApiErrorId.ERR_IMPACT_ASSESSMENT_NOT_FINALIZED.value,
        expected_status=409,
    )

    assert read_assessment(assessment["id"])["status"] == "DRAFT"
    case = read_case(ctx["case"]["id"])
    assert case["notice_required_days"] == 0
    assert case["status"] == "APPROVED"
    assert case["version"] == approved_version
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    _, meta = validate_paginated(
        api_client.list_case_closure_notices(ctx["case"]["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 0


def test_06_a_notice_may_not_schedule_a_closure_later_than_the_case_plans_one():
    """With a comfortable lead time the filing clears the notice-period rule and fails only on
    the case's own planned date — and re-filing on exactly that planned date is accepted, which
    shows the comparison allows equality.

    PRD: "The case's `planned_closure_date` must not fall earlier than the `effective_closure_date`, or the filing fails with `ERR_PLANNED_DATE_BEFORE_EFFECTIVE`."
    PRD: "It moves the case `APPROVED → NOTICE_FILED` and increments the case's `version`, and it moves the closing branch `UNDER_REVIEW → CLOSURE_SCHEDULED` with that branch's `version` incremented."
    Design: Corner/validations/notice_effective_date_after_planned_closure_returns_planned_date_before_effective
    """
    ctx = _harbor_approved_with_assessment()
    case_id = ctx["case"]["id"]
    assert read_case(case_id)["planned_closure_date"] == "2026-12-01"

    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(case_id, effective_closure_date="2026-12-15"),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_PLANNED_DATE_BEFORE_EFFECTIVE.value,
        expected_status=422,
    )
    assert read_case(case_id)["status"] == "APPROVED"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    _, meta = validate_paginated(api_client.list_case_closure_notices(case_id, COMPLIANCE))
    assert meta["total_count"] == 0

    notice = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(case_id, effective_closure_date="2026-12-01"),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert notice["status"] == "FILED"
    assert read_case(case_id)["status"] == "NOTICE_FILED"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"


def _riverbend_two_case_market(second_planned_closure_date: str) -> tuple:
    """Riverbend North holding two approved, assessed cases that share one survivor branch."""
    first = setup_market_with_branches(
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
    third_branch = validate_success(
        api_client.create_branch(
            branch_payload(
                first["market"]["id"],
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
    first = setup_approved_case(
        first, case_overrides={"planned_closure_date": "2026-11-15"}
    )
    first = setup_finalized_assessment(first, LOW_IMPACT_ASSESSMENT)

    second = {
        "market": first["market"],
        "closing_branch": third_branch,
        "receiving_branch": first["receiving_branch"],
    }
    second = setup_approved_case(
        second,
        case_overrides={
            "rationale_code": "MARKET_OVERLAP",
            "planned_closure_date": second_planned_closure_date,
        },
    )
    second = setup_finalized_assessment(second, LOW_IMPACT_ASSESSMENT)
    return first, second


def test_07_the_lead_time_failure_is_reported_ahead_of_the_market_window_clash():
    """A filing that is simultaneously too short-notice and inside another closure's occupied
    window reports the lead-time failure; lengthening only the notice reveals the window clash
    underneath it.

    PRD: "The whole calendar days from the current logical date to the `effective_closure_date` must be at least the case's `notice_required_days`, or the filing fails with `ERR_NOTICE_PERIOD_INSUFFICIENT`."
    PRD: "A collision is rejected with `ERR_NOTICE_WINDOW_CONFLICT`."
    PRD: "The server evaluates guards in one fixed global order and returns the first failure it encounters; it never masks an earlier-ranked failure behind a later-ranked one."
    Design: Difficulty/priority_pair_validation_conflict/notice_period_insufficient_outranks_market_window_conflict
    """
    first, second = _riverbend_two_case_market("2026-12-15")
    assert read_case(second["case"]["id"])["notice_required_days"] == 90

    blocking = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                first["case"]["id"], effective_closure_date="2026-11-01"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert blocking["buffer_end_date"] == "2026-12-01"

    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2026-09-15"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_NOTICE_PERIOD_INSUFFICIENT.value,
        expected_status=422,
    )
    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2026-11-20"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    assert read_case(second["case"]["id"])["status"] == "APPROVED"
    _, meta = validate_paginated(
        api_client.list_case_closure_notices(second["case"]["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 0


def test_08_withdrawing_the_blocking_notice_releases_the_window_for_its_neighbour():
    """Once the occupying notice is withdrawn the previously refused filing is accepted verbatim,
    and its own lead days, required lead days and buffered window end are all stamped.

    PRD: "The candidate set is every other notice of type `REGULATOR` in `FILED` or `EFFECTIVE` status whose case's closing branch sits in the same trade area; withdrawn notices are ignored entirely."
    PRD: "The notice transitions to `WITHDRAWN`, releasing its market window for other filings."
    PRD: "Filing stamps `filed_on` from the logical clock, copies the case's `notice_required_days` onto the notice as `required_lead_days` — the value the filing was actually validated against — computes `lead_days` as the whole calendar days from `filed_on` to `effective_closure_date` counting neither endpoint, sets `buffer_end_date` to the `effective_closure_date` plus a 30-day regulatory cooling buffer, and opens the notice in `FILED` status."
    Design: Difficulty/priority_pair_validation_conflict/notice_period_insufficient_outranks_market_window_conflict
    """
    first, second = _riverbend_two_case_market("2026-12-15")
    blocking = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                first["case"]["id"], effective_closure_date="2026-11-01"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2026-11-20"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    withdrawn = validate_success(
        api_client.withdraw_closure_notice(
            blocking["id"], {"withdrawn_reason_code": "PLAN_REVISION"}, COMPLIANCE
        )
    )
    assert withdrawn["status"] == "WITHDRAWN"
    assert read_case(first["case"]["id"])["status"] == "APPROVED"

    filed = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2026-11-20"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert filed["status"] == "FILED"
    assert filed["filed_on"] == "2026-08-01"
    assert filed["lead_days"] == 111
    assert filed["required_lead_days"] == 90
    assert filed["buffer_end_date"] == "2026-12-20"
    assert read_case(second["case"]["id"])["status"] == "NOTICE_FILED"

    _, meta = validate_paginated(
        api_client.list_case_closure_notices(second["case"]["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 1


def test_09_withdrawing_a_regulatory_notice_walks_the_whole_closure_back():
    """One withdrawal fans out across four records — the notice, the case, the closing branch and
    the assessment — and cancels the customer wave, while the impact figures the assessment
    mirrored onto the case are deliberately retained.

    PRD: "A `ComplianceOfficer` withdraws a notice in `FILED` or `EFFECTIVE` status by supplying a `withdrawn_reason_code` of `REGULATOR_OBJECTION`, `PLAN_REVISION` or `COMMUNITY_PROTEST`; the field is null while the notice has not been withdrawn."
    PRD: "When the withdrawn notice is the case's `REGULATOR` notice and the case stands at `NOTICE_FILED`, the withdrawal cascades: the case transitions `NOTICE_FILED → APPROVED` with its `version` incremented, the closing branch transitions `CLOSURE_SCHEDULED → UNDER_REVIEW` with its `version` incremented, the case's impact assessment transitions `FINALIZED → REOPENED`, and every transition campaign of the case in `PLANNED` or `LAUNCHED` status transitions to `CANCELLED`, releasing its wave interval from the receiving branch's calendar."
    PRD: "Withdrawal is thus the single lever that walks an in-flight closure all the way back to an approved-but-unscheduled plan."
    Design: Corner/state_machines/withdraw_notice_returns_case_to_approved_and_reopens_assessment
    """
    ctx = setup_notice_filed_case()
    ctx = setup_campaign(ctx, launch=True)
    assert read_case(ctx["case"]["id"])["status"] == "NOTICE_FILED"
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"

    withdrawn = validate_success(
        api_client.withdraw_closure_notice(
            ctx["notice"]["id"],
            {"withdrawn_reason_code": "COMMUNITY_PROTEST"},
            COMPLIANCE,
        )
    )

    assert withdrawn["status"] == "WITHDRAWN"
    assert withdrawn["withdrawn_reason_code"] == "COMMUNITY_PROTEST"
    assert read_notice(ctx["notice"]["id"])["status"] == "WITHDRAWN"

    case = read_case(ctx["case"]["id"])
    assert case["status"] == "APPROVED"
    assert case["impact_tier"] == "LOW"
    assert case["notice_required_days"] == 90
    assert case["net_annual_savings_cents"] == 18320000
    assert read_branch(ctx["closing_branch"]["id"])["status"] == "UNDER_REVIEW"

    assessment = read_assessment(ctx["assessment"]["id"])
    assert assessment["status"] == "REOPENED"
    assert assessment["finalized_on"] == "2026-08-01"

    assert read_campaign(ctx["campaign"]["id"])["status"] == "CANCELLED"


def _harbor_metro_two_case_market(second_planned_closure_date: str) -> dict:
    """Harbor Metro with RB-101 noticed, RB-102 receiving both closures and RB-103 idle."""
    first = setup_approved_case()
    first = setup_finalized_assessment(first)
    third_branch = validate_success(
        api_client.create_branch(
            branch_payload(
                first["market"]["id"],
                branch_code="RB-103",
                fte_count=7,
                atm_count=1,
                opened_on="2007-10-01",
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    first["notice"] = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(first["case"]["id"]), COMPLIANCE
        ),
        expected_status=201,
    )
    second = {
        "market": first["market"],
        "closing_branch": third_branch,
        "receiving_branch": first["receiving_branch"],
    }
    return {
        "first": first,
        "second": second,
        "second_planned_closure_date": second_planned_closure_date,
    }


def test_10_the_first_legal_filing_date_is_the_day_after_a_buffered_window_ends():
    """With one notice already effective in the trade area, a second closure files on the day
    after that notice's buffered end and is accepted, stamping its own lead days and its own
    buffered window.

    PRD: "Each regulatory notice occupies the market from its `filed_on` through its `buffer_end_date` — the `effective_closure_date` plus the 30 buffer days — and both ends of that interval are **closed**."
    PRD: "Every closure notice in `FILED` status whose `effective_closure_date` is on or before the new logical date transitions to `EFFECTIVE`, and every leased premises in `MARKETED` status whose `lease_end_date` falls strictly before the new logical date transitions to `HOLDOVER` with its carrying cost recomputed and the owning case's savings chain refreshed."
    PRD: "A `NetworkOpsAdmin` may move the clock by supplying a `to_iso8601` instant, and the response reports the resulting `current_utc` alongside two counters describing what the move triggered: `notices_made_effective` and `properties_moved_to_holdover`."
    Design: Corner/calculations/second_regulator_notice_one_day_after_buffered_end_is_accepted
    """
    market = _harbor_metro_two_case_market("2027-04-01")
    first = market["first"]
    assert first["notice"]["buffer_end_date"] == "2026-12-01"

    clock = set_clock("2026-12-02T00:00:00Z")
    assert clock["notices_made_effective"] == 1
    assert read_notice(first["notice"]["id"])["status"] == "EFFECTIVE"

    second = setup_approved_case(
        market["second"],
        case_overrides={
            "rationale_code": "MARKET_OVERLAP",
            "planned_closure_date": market["second_planned_closure_date"],
        },
    )
    second = setup_finalized_assessment(second)

    filed = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2027-03-15"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert filed["filed_on"] == "2026-12-02"
    assert filed["lead_days"] == 103
    assert filed["required_lead_days"] == 90
    assert filed["buffer_end_date"] == "2027-04-14"
    assert filed["status"] == "FILED"

    assert read_case(second["case"]["id"])["status"] == "NOTICE_FILED"
    assert read_branch(second["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"
    assert read_case(first["case"]["id"])["status"] == "NOTICE_FILED"
    assert read_branch(first["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"

    reread_market = read_market(first["market"]["id"])
    assert reread_market["own_branch_count"] == 3
    assert reread_market["branch_density_per_100k"] == 26


def test_11_a_filing_landing_exactly_on_a_buffered_end_date_collides():
    """The occupied window runs through the buffered end inclusively, so a filing whose own start
    date lands precisely on the neighbouring notice's buffered end is refused — and the neighbour
    blocks it from `EFFECTIVE`, not merely from `FILED`.

    PRD: "Each regulatory notice occupies the market from its `filed_on` through its `buffer_end_date` — the `effective_closure_date` plus the 30 buffer days — and both ends of that interval are **closed**."
    PRD: "The candidate set is every other notice of type `REGULATOR` in `FILED` or `EFFECTIVE` status whose case's closing branch sits in the same trade area; withdrawn notices are ignored entirely."
    PRD: "Because both intervals are closed, touching endpoints collide: a new filing whose `filed_on` equals an existing notice's `buffer_end_date` **is** a conflict."
    Design: Difficulty/resource_temporal_overlap/notice_window_touching_buffered_end_date_collides
    """
    first, second = _riverbend_two_case_market("2027-05-15")
    blocking = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                first["case"]["id"], effective_closure_date="2026-11-01"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert blocking["filed_on"] == "2026-08-01"
    assert blocking["buffer_end_date"] == "2026-12-01"

    set_clock("2026-12-01T00:00:00Z")
    assert read_notice(blocking["id"])["status"] == "EFFECTIVE"

    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2027-04-01"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    assert read_case(second["case"]["id"])["status"] == "APPROVED"
    assert read_branch(second["closing_branch"]["id"])["status"] == "UNDER_REVIEW"
    _, meta = validate_paginated(
        api_client.list_case_closure_notices(second["case"]["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 0


def test_12_one_further_clock_day_clears_the_touching_window():
    """The identical filing, differing only by a single day on the logical clock, is accepted and
    stamps its own lead days and buffered window; the refused attempt left nothing behind.

    PRD: "Two intervals collide when the new interval's start falls on or before the existing interval's end and the existing interval's start falls on or before the new interval's end."
    PRD: "Filing stamps `filed_on` from the logical clock, copies the case's `notice_required_days` onto the notice as `required_lead_days` — the value the filing was actually validated against — computes `lead_days` as the whole calendar days from `filed_on` to `effective_closure_date` counting neither endpoint, sets `buffer_end_date` to the `effective_closure_date` plus a 30-day regulatory cooling buffer, and opens the notice in `FILED` status."
    PRD: "It moves the case `APPROVED → NOTICE_FILED` and increments the case's `version`, and it moves the closing branch `UNDER_REVIEW → CLOSURE_SCHEDULED` with that branch's `version` incremented."
    Design: Difficulty/resource_temporal_overlap/notice_window_touching_buffered_end_date_collides
    """
    first, second = _riverbend_two_case_market("2027-05-15")
    blocking = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                first["case"]["id"], effective_closure_date="2026-11-01"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert blocking["buffer_end_date"] == "2026-12-01"

    set_clock("2026-12-01T00:00:00Z")
    validate_error(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2027-04-01"
            ),
            COMPLIANCE,
        ),
        ApiErrorId.ERR_NOTICE_WINDOW_CONFLICT.value,
        expected_status=409,
    )

    set_clock("2026-12-02T00:00:00Z")
    filed = validate_success(
        api_client.create_closure_notice(
            closure_notice_payload(
                second["case"]["id"], effective_closure_date="2027-04-01"
            ),
            COMPLIANCE,
        ),
        expected_status=201,
    )
    assert filed["filed_on"] == "2026-12-02"
    assert filed["lead_days"] == 120
    assert filed["required_lead_days"] == 90
    assert filed["buffer_end_date"] == "2027-05-01"
    assert filed["status"] == "FILED"

    assert read_case(second["case"]["id"])["status"] == "NOTICE_FILED"
    assert read_branch(second["closing_branch"]["id"])["status"] == "CLOSURE_SCHEDULED"
    rows, meta = validate_paginated(
        api_client.list_case_closure_notices(second["case"]["id"], COMPLIANCE)
    )
    assert meta["total_count"] == 1
    assert len(rows) == 1
    assert rows[0]["id"] == filed["id"]
