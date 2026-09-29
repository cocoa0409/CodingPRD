"""Employee dispositions: severance economics, the two state axes and headcount conservation."""

from test_helpers import (
    APPROVER,
    HR,
    STRATEGIST,
    ApiErrorId,
    api_client,
    assert_headcount_conservation,
    assert_staff_disposition,
    branch_payload,
    read_branch,
    read_case,
    read_staff_disposition,
    setup_approved_case,
    setup_case_with_forecast,
    setup_draft_case,
    setup_market_with_branches,
    setup_submitted_case,
    staff_disposition_payload,
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

HARBOR_POINT = {
    "name": "Harbor Point",
    "region_code": "NE-02",
    "population": 140000,
    "median_household_income_cents": 9100000,
    "deposit_market_total_cents": 260000000000,
    "competitor_branch_count": 26,
    "household_growth_pct_bps": 300,
    "digital_penetration_bps": 5600,
}

DECAY_AT_3_4 = {
    "model_variant": "DISTANCE_DECAY",
    "distance_miles": 3.4,
    "retail_share_bps": 6000,
    "small_business_share_bps": 2500,
    "wealth_share_bps": 1500,
}

_RIVERBEND_RECEIVING = {
    "monthly_transaction_count": 7200,
    "digital_adoption_bps": 6800,
    "annual_noninterest_expense_cents": 118000000,
    "annual_revenue_cents": 305000000,
    "opened_on": "1998-06-15",
    "onboarding_capacity_households_per_day": 60,
}

_HARBOR_POINT_CLOSING = {
    "branch_code": "RB-501",
    "monthly_transaction_count": 3400,
    "annual_revenue_cents": 138000000,
    "opened_on": "2006-01-16",
}

_HARBOR_POINT_RECEIVING = {
    "branch_code": "RB-503",
    "monthly_transaction_count": 7200,
    "digital_adoption_bps": 6800,
    "annual_noninterest_expense_cents": 118000000,
    "annual_revenue_cents": 305000000,
    "opened_on": "1999-04-05",
    "onboarding_capacity_households_per_day": 60,
}


def _riverbend_pair() -> dict:
    """Riverbend North with RB-101 as the closing candidate and RB-102 as the survivor."""
    return setup_market_with_branches(
        market_overrides=RIVERBEND,
        closing_overrides={
            "monthly_transaction_count": 3600,
            "annual_revenue_cents": 140000000,
        },
        receiving_overrides=dict(_RIVERBEND_RECEIVING),
    )


def _riverbend_draft_case() -> dict:
    return setup_draft_case(
        _riverbend_pair(), case_overrides={"planned_closure_date": "2026-11-15"}
    )


def _riverbend_approved_case() -> dict:
    return setup_approved_case(
        _riverbend_pair(),
        case_overrides={"planned_closure_date": "2026-11-15"},
        forecast_overrides=dict(DECAY_AT_3_4),
    )


def _harbor_point_approved_case() -> dict:
    """Harbor Point RB-501 closing into RB-503, walked through to APPROVED."""
    return setup_approved_case(
        setup_market_with_branches(
            market_overrides=HARBOR_POINT,
            closing_overrides=dict(_HARBOR_POINT_CLOSING),
            receiving_overrides=dict(_HARBOR_POINT_RECEIVING),
        ),
        forecast_overrides=dict(DECAY_AT_3_4),
    )


def _propose(case_id: str, **overrides) -> dict:
    return validate_success(
        api_client.create_staff_disposition(
            staff_disposition_payload(case_id, **overrides), HR
        ),
        expected_status=201,
    )


def test_01_each_employees_weekly_pay_is_rounded_before_the_pool_is_summed():
    """Two salaries that do not divide evenly by 52 produce weekly figures the system must round to
    whole cents individually, and the redundancy pool is the sum of those already-rounded per-employee
    amounts rather than anything derived from the combined payroll.

    PRD: "`service_years` is the `tenure_months` divided by 12 and rounded **down** to a whole year."
    PRD: "`weekly_pay_cents` is the `annual_salary_cents` divided by 52 and rounded half up to whole cents."
    PRD: "`severance_amount_cents` is the `severance_weeks` multiplied by that `weekly_pay_cents`, plus a flat outplacement stipend of 1,200 dollars (120,000 cents)."
    PRD: "The rounding order is pinned: round each employee's weekly pay to whole cents **first**, multiply by that employee's weeks, then sum across employees."
    Design: Difficulty/combinatorial_formula/severance_pool_round_then_sum_across_two_employees
    """
    ctx = _riverbend_draft_case()

    manager = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-7741",
        role_title="Branch Manager",
        tenure_months=150,
        annual_salary_cents=7800050,
    )
    teller = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-8120",
        role_title="Teller",
        tenure_months=30,
        annual_salary_cents=5200030,
    )

    assert_staff_disposition(manager)
    assert manager["service_years"] == 12
    assert manager["severance_weeks"] == 24
    assert manager["weekly_pay_cents"] == 150001
    assert manager["severance_amount_cents"] == 3720024

    assert teller["service_years"] == 2
    assert teller["severance_weeks"] == 4
    assert teller["weekly_pay_cents"] == 100001
    assert teller["severance_amount_cents"] == 520004

    case = read_case(ctx["case"]["id"])
    assert case["severance_pool_cents"] == 4240028
    assert case["pending_disposition_count"] == 2
    assert case["severed_fte_count"] == 0
    assert case["redeployed_fte_count"] == 0


def test_02_the_pool_is_not_the_combined_payroll_divided_by_fifty_two():
    """Two employees on the same half-cent salary each round up before multiplication, so the pool
    lands four cents above the figure a single division of the combined payroll would produce — and
    resubmitting the case recomputes the same pinned total.

    PRD: "Summing annual salaries first and dividing the aggregate by 52 is explicitly not the rule and produces a different pool; the round-then-sum result is the one the system must reproduce."
    PRD: "The case's `severance_pool_cents` is the sum of `severance_amount_cents` over the case's dispositions whose `proposed_disposition` is `SEVERANCE` and whose `disposition_state` is `PROPOSED` or `SEVERED`."
    PRD: "Submission carries no request body of its own and moves the case `DRAFT → SUBMITTED`, recomputing `severance_pool_cents` and the entire savings chain on the way through and incrementing the case's `version` by one."
    Design: Difficulty/combinatorial_formula/severance_pool_round_then_sum_across_two_employees
    """
    ctx = setup_case_with_forecast(
        _riverbend_pair(),
        case_overrides={"planned_closure_date": "2026-11-15"},
        forecast_overrides=dict(DECAY_AT_3_4),
    )

    first = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-3301",
        role_title="Teller",
        tenure_months=30,
        annual_salary_cents=5200026,
    )
    second = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-3302",
        role_title="Teller",
        tenure_months=30,
        annual_salary_cents=5200026,
    )

    assert first["weekly_pay_cents"] == 100001
    assert second["weekly_pay_cents"] == 100001
    assert first["severance_amount_cents"] == 520004
    assert second["severance_amount_cents"] == 520004

    case = read_case(ctx["case"]["id"])
    assert case["severance_pool_cents"] == 1040008
    assert case["severance_pool_cents"] != 1040004

    submitted = validate_success(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST)
    )
    assert submitted["status"] == "SUBMITTED"
    assert submitted["severance_pool_cents"] == 1040008
    assert submitted["pending_disposition_count"] == 2


def _riverbend_redeployment_offer() -> tuple:
    """An APPROVED Riverbend case carrying one redeployment offer aimed at the survivor branch."""
    ctx = _riverbend_approved_case()
    offer = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-5510",
        role_title="Personal Banker",
        tenure_months=84,
        annual_salary_cents=6240000,
        proposed_disposition="REDEPLOYMENT",
        target_branch_id=ctx["receiving_branch"]["id"],
    )
    return ctx, offer


def test_03_serving_the_statutory_notice_leaves_the_employment_outcome_where_it_stood():
    """Notification is an axis of its own: it stamps the notice date and advances only the statutory
    axis, leaving the outcome axis at its proposal and moving no headcount at all.

    PRD: "A disposition carries **two independent state axes**, and this is the structural point of the record."
    PRD: "Recording notification transitions `notification_state` from `PENDING → NOTIFIED` and stamps `notified_on` from the logical clock while leaving `disposition_state` exactly where it stood — notification is legal whether the outcome axis reads `PROPOSED` or `OFFER_ACCEPTED`."
    PRD: "The two axes never move each other."
    Design: Difficulty/non_linear_state_machine/staff_disposition_notification_axis_independent_of_disposition_axis
    """
    ctx, offer = _riverbend_redeployment_offer()
    assert offer["disposition_state"] == "PROPOSED"
    assert offer["notification_state"] == "PENDING"
    assert offer["notified_on"] is None

    notified = validate_success(
        api_client.notify_staff_disposition(offer["id"], HR)
    )

    assert notified["notification_state"] == "NOTIFIED"
    assert notified["disposition_state"] == "PROPOSED"
    assert notified["notified_on"] == "2026-08-01"
    assert notified["version"] > offer["version"]

    assert read_branch(ctx["closing_branch"]["id"])["fte_count"] == 9
    assert read_branch(ctx["receiving_branch"]["id"])["fte_count"] == 14
    case = read_case(ctx["case"]["id"])
    assert case["redeployed_fte_count"] == 0
    assert case["pending_disposition_count"] == 1


def test_04_accepting_the_offer_moves_the_head_and_leaves_the_notice_axis_alone():
    """The combined state of a notified, accepted offer is reached by two independent moves: the
    acceptance walks the outcome axis forward and transfers one head between branches while the
    statutory axis and its notice date stay exactly as notification left them.

    PRD: "On success the `disposition_state` moves `PROPOSED → OFFER_ACCEPTED`, the source branch's `fte_count` decreases by one and the target branch's `fte_count` increases by one with both branch `version` values incremented, the case's `redeployed_fte_count` increases by one and its `pending_disposition_count` decreases by one with the case `version` incremented, and the disposition's own `version` increments."
    PRD: "The two axes never move each other."
    PRD: "Redeployment records carry `severance_weeks` of 0, `weekly_pay_cents` of 0 and `severance_amount_cents` of 0."
    Design: Difficulty/non_linear_state_machine/staff_disposition_notification_axis_independent_of_disposition_axis
    """
    ctx, offer = _riverbend_redeployment_offer()
    validate_success(api_client.notify_staff_disposition(offer["id"], HR))

    accepted = validate_success(api_client.accept_staff_disposition(offer["id"], HR))

    assert accepted["disposition_state"] == "OFFER_ACCEPTED"
    assert accepted["notification_state"] == "NOTIFIED"
    assert accepted["notified_on"] == "2026-08-01"
    assert accepted["severance_weeks"] == 0
    assert accepted["weekly_pay_cents"] == 0
    assert accepted["severance_amount_cents"] == 0

    assert read_branch(ctx["closing_branch"]["id"])["fte_count"] == 8
    assert read_branch(ctx["receiving_branch"]["id"])["fte_count"] == 15
    case = read_case(ctx["case"]["id"])
    assert case["redeployed_fte_count"] == 1
    assert case["pending_disposition_count"] == 0
    assert case["severance_pool_cents"] == 0


def _offer_blocked_by_a_second_case() -> tuple:
    """A notified redeployment aimed at RB-503 while a second case holds RB-503 under review."""
    first = _harbor_point_approved_case()
    fourth_branch = validate_success(
        api_client.create_branch(
            branch_payload(
                first["market"]["id"],
                branch_code="RB-504",
                tenure_class="OWNED",
                deposit_balance_cents=11200000000,
                monthly_transaction_count=8100,
                digital_adoption_bps=7000,
                annual_noninterest_expense_cents=132000000,
                annual_revenue_cents=348000000,
                fte_count=17,
                atm_count=4,
                opened_on="1994-07-11",
                onboarding_capacity_households_per_day=70,
            ),
            STRATEGIST,
        ),
        expected_status=201,
    )
    offer = _propose(
        first["case"]["id"],
        employee_ref="EMP-9002",
        role_title="Personal Banker",
        tenure_months=84,
        annual_salary_cents=6240000,
        proposed_disposition="REDEPLOYMENT",
        target_branch_id=first["receiving_branch"]["id"],
    )
    validate_success(api_client.notify_staff_disposition(offer["id"], HR))

    second = setup_submitted_case(
        {
            "market": first["market"],
            "closing_branch": first["receiving_branch"],
            "receiving_branch": fourth_branch,
        },
        case_overrides={
            "rationale_code": "MARKET_OVERLAP",
            "planned_closure_date": "2027-02-01",
        },
        forecast_overrides={
            "model_variant": "SEGMENT_MIX",
            "distance_miles": 2.5,
            "retail_share_bps": 6000,
            "small_business_share_bps": 2500,
            "wealth_share_bps": 1500,
        },
    )
    return first, second, offer


def test_05_a_redeployment_stalls_when_a_rival_case_takes_the_target_branch_under_review():
    """The blocking state belongs to neither the offer nor its own case but to the target branch,
    whose status is held by an unrelated closure; the acceptance is refused and nothing on the offer's
    side of the network moves.

    PRD: "Accepting a redeployment offer requires that the record's `proposed_disposition` be `REDEPLOYMENT`, that its `notification_state` already read `NOTIFIED`, and that its `target_branch_id` name a branch in `ACTIVE` status — a target that has drifted out of `ACTIVE` yields `ERR_RECEIVING_BRANCH_NOT_ACTIVE`."
    PRD: "When the create succeeds the branch transitions `ACTIVE → UNDER_REVIEW` and its `version` increments by one."
    Design: Difficulty/cross_entity_state_dependency/redeployment_accept_gated_by_target_branch_state_owned_by_another_case
    """
    first, second, offer = _offer_blocked_by_a_second_case()
    assert read_branch(first["receiving_branch"]["id"])["status"] == "UNDER_REVIEW"
    assert read_branch(first["closing_branch"]["id"])["status"] == "UNDER_REVIEW"

    validate_error(
        api_client.accept_staff_disposition(offer["id"], HR),
        ApiErrorId.ERR_RECEIVING_BRANCH_NOT_ACTIVE.value,
        expected_status=409,
    )

    reread = read_staff_disposition(offer["id"])
    assert reread["disposition_state"] == "PROPOSED"
    assert reread["notification_state"] == "NOTIFIED"
    assert read_branch(first["closing_branch"]["id"])["fte_count"] == 9
    assert read_branch(first["receiving_branch"]["id"])["fte_count"] == 14
    case = read_case(first["case"]["id"])
    assert case["status"] == "APPROVED"
    assert case["redeployed_fte_count"] == 0
    assert case["pending_disposition_count"] == 1
    assert read_case(second["case"]["id"])["status"] == "SUBMITTED"


def test_06_rejecting_the_rival_case_releases_the_branch_and_the_offer_then_completes():
    """Turning down the unrelated closure hands the target branch back to the network, and the very
    same acceptance call — unchanged in every respect — now transfers the head.

    PRD: "The closing branch transitions `UNDER_REVIEW → ACTIVE` and its `version` increments — released back into the network, provided the rejected case is the only case on that branch in `SUBMITTED`, `APPROVED` or `NOTICE_FILED` status."
    PRD: "On success the `disposition_state` moves `PROPOSED → OFFER_ACCEPTED`, the source branch's `fte_count` decreases by one and the target branch's `fte_count` increases by one with both branch `version` values incremented, the case's `redeployed_fte_count` increases by one and its `pending_disposition_count` decreases by one with the case `version` incremented, and the disposition's own `version` increments."
    Design: Difficulty/cross_entity_state_dependency/redeployment_accept_gated_by_target_branch_state_owned_by_another_case
    """
    first, second, offer = _offer_blocked_by_a_second_case()
    validate_error(
        api_client.accept_staff_disposition(offer["id"], HR),
        ApiErrorId.ERR_RECEIVING_BRANCH_NOT_ACTIVE.value,
        expected_status=409,
    )

    rejected = validate_success(
        api_client.decide_consolidation_case(
            second["case"]["id"],
            {
                "decision": "REJECT",
                "reason_code": "STRATEGY_CHANGE",
                "expected_case_version": second["case"]["version"],
            },
            APPROVER,
        )
    )
    assert rejected["status"] == "REJECTED"
    assert read_branch(first["receiving_branch"]["id"])["status"] == "ACTIVE"

    accepted = validate_success(api_client.accept_staff_disposition(offer["id"], HR))
    assert accepted["disposition_state"] == "OFFER_ACCEPTED"
    assert accepted["notification_state"] == "NOTIFIED"

    assert read_branch(first["closing_branch"]["id"])["fte_count"] == 8
    assert read_branch(first["receiving_branch"]["id"])["fte_count"] == 15
    case = read_case(first["case"]["id"])
    assert case["status"] == "APPROVED"
    assert case["redeployed_fte_count"] == 1
    assert case["pending_disposition_count"] == 0
    assert case["severance_pool_cents"] == 0


def _harbor_point_mixed_roster() -> tuple:
    """An APPROVED Harbor Point case with one notified redeployment and one untouched severance."""
    ctx = _harbor_point_approved_case()
    offer = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-9002",
        role_title="Personal Banker",
        tenure_months=84,
        annual_salary_cents=6240000,
        proposed_disposition="REDEPLOYMENT",
        target_branch_id=ctx["receiving_branch"]["id"],
    )
    severance = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-7741",
        role_title="Branch Manager",
        tenure_months=150,
        annual_salary_cents=7800050,
    )
    validate_success(api_client.notify_staff_disposition(offer["id"], HR))
    return ctx, offer, severance


def test_07_accepting_a_transfer_debits_one_branch_and_credits_the_other():
    """The transfer is a move, not a creation: the two branch rosters change in opposite directions
    by one, the pending and redeployed counters trade a unit, and the network total is untouched.

    PRD: "For any case, take the `fte_count` of its closing branch plus the `fte_count` of its receiving branch plus the case's `severed_fte_count`."
    PRD: "Acceptance debits the source branch by one and credits the target branch by one; rescission reverses exactly those two moves."
    PRD: "Redeployment records contribute nothing, and so do records whose `disposition_state` has reached `OFFER_ACCEPTED` or `COMPLETED`."
    Design: Difficulty/compensating_invariant/rescind_redeployment_restores_network_headcount_exactly
    """
    ctx, offer, severance = _harbor_point_mixed_roster()
    baseline_case = read_case(ctx["case"]["id"])
    assert baseline_case["severance_pool_cents"] == 3720024
    assert baseline_case["pending_disposition_count"] == 2
    assert baseline_case["redeployed_fte_count"] == 0
    assert_headcount_conservation(
        baseline_case,
        read_branch(ctx["closing_branch"]["id"]),
        read_branch(ctx["receiving_branch"]["id"]),
        23,
    )

    validate_success(api_client.accept_staff_disposition(offer["id"], HR))

    closing = read_branch(ctx["closing_branch"]["id"])
    receiving = read_branch(ctx["receiving_branch"]["id"])
    case = read_case(ctx["case"]["id"])
    assert closing["fte_count"] == 8
    assert receiving["fte_count"] == 15
    assert case["redeployed_fte_count"] == 1
    assert case["pending_disposition_count"] == 1
    assert case["severed_fte_count"] == 0
    assert case["severance_pool_cents"] == 3720024
    assert_headcount_conservation(case, closing, receiving, 23)
    assert read_staff_disposition(severance["id"])["disposition_state"] == "PROPOSED"


def test_08_rescinding_the_transfer_restores_every_roster_to_the_person():
    """The rescission is the exact inverse of the acceptance: both branch rosters return to their
    pre-acceptance counts, the counter pair returns to its opening split, the untouched redundancy
    pool never moves, and the statutory notice already served is not revoked.

    PRD: "Rescinding an accepted offer is the exact inverse."
    PRD: "The `HRPartner` supplies a `rescind_reason_code`, the `disposition_state` moves `OFFER_ACCEPTED → PROPOSED`, the source branch's `fte_count` increases by one and the target branch's `fte_count` decreases by one — restoring the pre-acceptance counts exactly — the case's `redeployed_fte_count` decreases by one and its `pending_disposition_count` increases by one, and every touched resource's `version` increments."
    PRD: "That total must be identical immediately before a redeployment offer is accepted and immediately after that same offer is rescinded, and the sum of the case's `redeployed_fte_count` and `pending_disposition_count` must likewise be identical across the pair."
    Design: Difficulty/compensating_invariant/rescind_redeployment_restores_network_headcount_exactly
    """
    ctx, offer, _severance = _harbor_point_mixed_roster()
    before_closing = read_branch(ctx["closing_branch"]["id"])
    before_receiving = read_branch(ctx["receiving_branch"]["id"])
    before_offer = read_staff_disposition(offer["id"])

    validate_success(api_client.accept_staff_disposition(offer["id"], HR))
    rescinded = validate_success(
        api_client.rescind_staff_disposition(
            offer["id"], {"rescind_reason_code": "EMPLOYEE_DECLINED"}, HR
        )
    )

    assert rescinded["disposition_state"] == "PROPOSED"
    assert rescinded["notification_state"] == "NOTIFIED"
    assert rescinded["notified_on"] == before_offer["notified_on"]
    assert rescinded["severance_amount_cents"] == 0
    assert rescinded["version"] > before_offer["version"]

    closing = read_branch(ctx["closing_branch"]["id"])
    receiving = read_branch(ctx["receiving_branch"]["id"])
    case = read_case(ctx["case"]["id"])
    assert closing["fte_count"] == before_closing["fte_count"] == 9
    assert receiving["fte_count"] == before_receiving["fte_count"] == 14
    assert closing["version"] > before_closing["version"]
    assert receiving["version"] > before_receiving["version"]
    assert case["redeployed_fte_count"] == 0
    assert case["pending_disposition_count"] == 2
    assert case["redeployed_fte_count"] + case["pending_disposition_count"] == 2
    assert case["severed_fte_count"] == 0
    assert case["severance_pool_cents"] == 3720024
    assert_headcount_conservation(case, closing, receiving, 23)


def test_09_one_redundancy_pool_can_span_both_ends_of_the_week_band():
    """A thirty-three-year veteran and a six-month hire sit in the same pool: the veteran's weeks are
    pulled down to the ceiling of the band and the new hire's are lifted to its floor, and the two
    already-rounded amounts add up to the pool the submission recomputes.

    PRD: "`severance_weeks` is twice the service years, raised to a floor of 4 weeks and then capped at 26 weeks — the floor is applied before the cap, so an employee with under two years of service still receives 4 weeks and an employee with 20 years receives 26 rather than 40."
    PRD: "`service_years` is the `tenure_months` divided by 12 and rounded **down** to a whole year."
    PRD: "The rounding order is pinned: round each employee's weekly pay to whole cents **first**, multiply by that employee's weeks, then sum across employees."
    Design: Corner/calculations/severance_weeks_hit_cap_and_floor_in_the_same_pool
    """
    ctx = setup_case_with_forecast()

    veteran = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-CAP",
        role_title="Branch Manager",
        tenure_months=400,
        annual_salary_cents=7800052,
    )
    newcomer = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-FLOOR",
        role_title="Teller",
        tenure_months=6,
        annual_salary_cents=5200000,
    )

    assert veteran["service_years"] == 33
    assert veteran["severance_weeks"] == 26
    assert veteran["weekly_pay_cents"] == 150001
    assert veteran["severance_amount_cents"] == 4020026

    assert newcomer["service_years"] == 0
    assert newcomer["severance_weeks"] == 4
    assert newcomer["weekly_pay_cents"] == 100000
    assert newcomer["severance_amount_cents"] == 520000

    submitted = validate_success(
        api_client.submit_consolidation_case(ctx["case"]["id"], STRATEGIST)
    )
    assert submitted["severance_pool_cents"] == 4540026
    assert submitted["severance_pool_cents"] != 4540025
    assert submitted["status"] == "SUBMITTED"
    assert submitted["pending_disposition_count"] == 2
    assert submitted["net_annual_savings_cents"] == 18320000


def test_10_the_source_branch_is_derived_while_the_destination_is_supplied():
    """Nobody tells the register which branch an employee is leaving — it is read off the case's
    closing branch — while the destination is an optional link only a transfer carries, and the two
    links are separately searchable afterwards.

    PRD: "The server copies `source_branch_id` from the case's `closing_branch_id`, opens the record with `disposition_state` at `PROPOSED` and `notification_state` at `PENDING`, increments the case's `pending_disposition_count` by one, recomputes the case's `severance_pool_cents` and savings chain, and increments the case's `version`."
    PRD: "Redeployment records carry `severance_weeks` of 0, `weekly_pay_cents` of 0 and `severance_amount_cents` of 0."
    PRD: "Dispositions may be read individually with both axes exposed, or listed with filters on `consolidation_case_id`, `source_branch_id`, `target_branch_id`, `disposition_state` and `notification_state`."
    Design: Corner/endpoints/staff_disposition_derives_its_source_branch_and_links_a_target_branch
    """
    ctx = setup_draft_case(case_overrides={"rationale_code": "DIGITAL_MIGRATION"})

    leaver = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-7001",
        role_title="Personal Banker",
        tenure_months=84,
        annual_salary_cents=9100000,
    )
    mover = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-7002",
        role_title="Branch Operations Lead",
        tenure_months=84,
        annual_salary_cents=9100000,
        proposed_disposition="REDEPLOYMENT",
        target_branch_id=ctx["receiving_branch"]["id"],
    )

    assert leaver["source_branch_id"] == ctx["closing_branch"]["id"]
    assert mover["source_branch_id"] == ctx["closing_branch"]["id"]
    assert leaver["target_branch_id"] is None
    assert mover["target_branch_id"] == ctx["receiving_branch"]["id"]

    assert leaver["severance_weeks"] == 14
    assert leaver["weekly_pay_cents"] == 175000
    assert leaver["severance_amount_cents"] == 2570000
    assert mover["severance_weeks"] == 0
    assert mover["weekly_pay_cents"] == 0
    assert mover["severance_amount_cents"] == 0

    for row in (leaver, mover):
        assert row["disposition_state"] == "PROPOSED"
        assert row["notification_state"] == "PENDING"

    case = read_case(ctx["case"]["id"])
    assert case["severance_pool_cents"] == 2570000
    assert case["pending_disposition_count"] == 2

    _, by_source = validate_paginated(
        api_client.list_staff_dispositions(
            HR, params={"source_branch_id": ctx["closing_branch"]["id"]}
        )
    )
    assert by_source["total_count"] == 2
    _, by_target = validate_paginated(
        api_client.list_staff_dispositions(
            HR, params={"target_branch_id": ctx["receiving_branch"]["id"]}
        )
    )
    assert by_target["total_count"] == 1


def test_11_a_redundancy_may_not_name_a_destination_and_a_transfer_may_not_omit_one():
    """The destination link is conditionally required, so naming a perfectly valid survivor branch on
    a redundancy is refused just as firmly as leaving it off a transfer, and neither refusal leaves a
    record behind.

    PRD: "A redeployment must name a `target_branch_id`, and that target may not be the closing branch itself; a severance must omit it."
    PRD: "Supplying a redeployment without a target, naming the source branch as the target, or attaching a target to a severance are all rejected with `ERR_DISPOSITION_TARGET_INVALID`, and the same check applies again when a redeployment offer is accepted."
    Design: Corner/validations/severance_disposition_supplying_a_target_branch_is_rejected
    """
    ctx = setup_draft_case()

    validate_error(
        api_client.create_staff_disposition(
            staff_disposition_payload(
                ctx["case"]["id"],
                employee_ref="EMP-009",
                tenure_months=84,
                annual_salary_cents=5200000,
                target_branch_id=ctx["receiving_branch"]["id"],
            ),
            HR,
        ),
        ApiErrorId.ERR_DISPOSITION_TARGET_INVALID.value,
        expected_status=422,
    )

    validate_error(
        api_client.create_staff_disposition(
            staff_disposition_payload(
                ctx["case"]["id"],
                employee_ref="EMP-010",
                tenure_months=84,
                annual_salary_cents=5200000,
                proposed_disposition="REDEPLOYMENT",
            ),
            HR,
        ),
        ApiErrorId.ERR_DISPOSITION_TARGET_INVALID.value,
        expected_status=422,
    )

    _, meta = validate_paginated(
        api_client.list_staff_dispositions(
            HR, params={"consolidation_case_id": ctx["case"]["id"]}
        )
    )
    assert meta["total_count"] == 0
    case = read_case(ctx["case"]["id"])
    assert case["pending_disposition_count"] == 0
    assert case["severance_pool_cents"] == 0


def test_12_the_statutory_notice_cannot_be_served_on_the_same_employee_twice():
    """Replaying the notification finds the statutory axis already advanced and is refused, and the
    original notice date survives the attempt untouched.

    PRD: "Notifying an already-notified record is rejected with `ERR_DISPOSITION_STATE_INVALID`, the same code that guards a wrong from-state on either axis."
    PRD: "Recording notification transitions `notification_state` from `PENDING → NOTIFIED` and stamps `notified_on` from the logical clock while leaving `disposition_state` exactly where it stood — notification is legal whether the outcome axis reads `PROPOSED` or `OFFER_ACCEPTED`."
    Design: Corner/state_machines/double_notify_staff_disposition_returns_disposition_state_invalid
    """
    ctx = setup_approved_case()
    disposition = _propose(
        ctx["case"]["id"],
        employee_ref="EMP-001",
        role_title="Teller",
        tenure_months=84,
        annual_salary_cents=5200000,
    )
    notified = validate_success(
        api_client.notify_staff_disposition(disposition["id"], HR)
    )
    assert notified["notified_on"] == "2026-08-01"

    validate_error(
        api_client.notify_staff_disposition(disposition["id"], HR),
        ApiErrorId.ERR_DISPOSITION_STATE_INVALID.value,
        expected_status=409,
    )

    reread = read_staff_disposition(disposition["id"])
    assert reread["notification_state"] == "NOTIFIED"
    assert reread["notified_on"] == "2026-08-01"
    assert reread["disposition_state"] == "PROPOSED"
    assert reread["version"] == notified["version"]
    assert read_case(ctx["case"]["id"])["pending_disposition_count"] == 1
