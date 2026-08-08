"""The regulatory program cap, the wellness budget and payroll settlement."""

from test_helpers import (
    ApiErrorId,
    api_client,
    assert_incentive_award,
    assert_period_money_conservation,
    new_award,
    new_clinic_assessment,
    participant_version,
    read_period,
    setup_checked_in_visit,
    setup_clinic,
    validate_error,
    validate_paginated,
    validate_success,
)


def _cap_world(code, name, tobacco_enabled, member, participant_name):
    """One employer whose annual cost of coverage is 200000 cents, with a
    MET_DIRECT clinic assessment and an OPEN June reporting period."""
    world = setup_checked_in_visit(
        visit_type="PRIMARY_CARE",
        scheduled_start="2026-06-08T09:00:00Z",
        visit_clock="2026-06-08T11:00:00Z",
        employer={
            "legal_name": name,
            "employer_code": code,
            "annual_total_cost_of_coverage_cents": 200000,
            "wellness_budget_cents": 500000,
            "tobacco_program_enabled": tobacco_enabled,
        },
        site={"site_name": f"{code} Clinic", "daily_slot_capacity": 8},
        contract={"quota_visits_total": 20},
        eligibility={
            "subscriber_external_id": f"S-{member}",
            "member_external_id": f"M-{member}",
        },
        participant={"display_name": participant_name},
        reporting_period={},
    )
    world.assessment = new_clinic_assessment(
        world.participant_id,
        world.clinician_id,
        world.visit_id,
        measurement_date="2026-06-08",
        systolic_mmhg=132,
        diastolic_mmhg=78,
        bmi=27.4,
        a1c_pct=5.7,
        ldl_mg_dl=118,
        cotinine_ng_ml=2.0,
    )
    assert world.assessment["outcome_credit_status"] == "MET_DIRECT"
    return world


def test_standard_program_cap_rejects_the_second_award():
    """PRD §3.8: "**The program cap** is the regulatory ceiling on health-contingent
    incentives and it is dual-variant on the employer's own configuration. When the
    employer's `tobacco_program_enabled` is false the cap is thirty percent of
    `annual_total_cost_of_coverage_cents`; when it is true the cap rises to fifty
    percent of that same base, so an award set that breaches the standard cap is
    accepted unchanged under the tobacco-inclusive one."
    PRD §3.8: "The candidate award is accepted when the committed cents plus the
    candidate amount is less than or equal to the cap, the bound being **inclusive** —
    an award that lands exactly on the cap is allowed — and is refused with
    `ERR_INCENTIVE_CAP_EXCEEDED` only when the sum is strictly greater."
    PRD §3.8: "An `OUTCOME_BASED` award is 60000 cents. A `PARTICIPATORY` award is
    15000 cents. A `TOBACCO_CESSATION` award is 45000 cents."

    Design: Difficulty/dual_variant_calc/incentive_cap_standard_tier_rejects_what_tobacco_tier_accepts
    """
    world = _cap_world("STD", "Standard Cap Co", False, "2001", "Sam Standard")

    first = new_award(
        world.participant_id,
        world.employer_id,
        world.period_id,
        award_type="OUTCOME_BASED",
        health_assessment_id=world.assessment["id"],
    )
    assert_incentive_award(first)
    assert first["award_amount_cents"] == 60000

    response = api_client.create_incentive_award(
        {
            "participant_id": world.participant_id,
            "reporting_period_id": world.period_id,
            "award_type": "PARTICIPATORY",
            "expected_participant_version": participant_version(
                world.participant_id, world.employer_id
            ),
        },
        world.employer_headers,
    )
    validate_error(response, ApiErrorId.ERR_INCENTIVE_CAP_EXCEEDED.value, 422)

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 60000
    assert_period_money_conservation(period)


def test_tobacco_program_cap_accepts_the_identical_award_pair():
    """PRD §3.8: "**The program cap** is the regulatory ceiling on health-contingent
    incentives and it is dual-variant on the employer's own configuration. When the
    employer's `tobacco_program_enabled` is false the cap is thirty percent of
    `annual_total_cost_of_coverage_cents`; when it is true the cap rises to fifty
    percent of that same base, so an award set that breaches the standard cap is
    accepted unchanged under the tobacco-inclusive one."
    PRD §3.8: "Against that ceiling the server measures the participant's committed
    cents — the sum of `award_amount_cents` across awards for **the same participant
    and the same reporting period** whose `status` is `PENDING`, `APPROVED`,
    `EXPORTED` or `PAID`."

    Design: Difficulty/dual_variant_calc/incentive_cap_standard_tier_rejects_what_tobacco_tier_accepts
    """
    world = _cap_world("TOB", "Tobacco Cap Co", True, "3001", "Tia Tobacco")

    first = new_award(
        world.participant_id,
        world.employer_id,
        world.period_id,
        award_type="OUTCOME_BASED",
        health_assessment_id=world.assessment["id"],
    )
    assert first["award_amount_cents"] == 60000

    second = validate_success(
        api_client.create_incentive_award(
            {
                "participant_id": world.participant_id,
                "reporting_period_id": world.period_id,
                "award_type": "PARTICIPATORY",
                "expected_participant_version": participant_version(
                    world.participant_id, world.employer_id
                ),
            },
            world.employer_headers,
        ),
        201,
    )
    assert second["award_amount_cents"] == 15000
    assert second["status"] == "PENDING"

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 75000
    assert period["incentive_pending_cents"] == 75000
    assert_period_money_conservation(period)


def test_wellness_budget_rung_fires_below_the_program_cap_rung():
    """PRD §3.8: "**The wellness budget** is the employer's own funding ceiling and is
    tested immediately after the program cap. The employer's
    `wellness_budget_committed_cents` plus the candidate amount must be less than or
    equal to `wellness_budget_cents`, again inclusively; a strictly greater sum is
    refused with `ERR_WELLNESS_BUDGET_EXCEEDED`. Because the cap rung sits above the
    budget rung, an award that breaches both reports the cap error."

    Design: Corner/validations/wellness_budget_rung_fires_after_the_program_cap_rung
    """
    world = setup_clinic(
        employer={
            "legal_name": "Budget Co",
            "employer_code": "BUD",
            "annual_total_cost_of_coverage_cents": 1200000,
            "wellness_budget_cents": 10000,
        },
        contract=False,
        shift=False,
        eligibility={"subscriber_external_id": "S-4901", "member_external_id": "M-4901"},
        participant={"display_name": "Bud Tester"},
        reporting_period={},
    )

    response = api_client.create_incentive_award(
        {
            "participant_id": world.participant_id,
            "reporting_period_id": world.period_id,
            "award_type": "PARTICIPATORY",
            "expected_participant_version": participant_version(
                world.participant_id, world.employer_id
            ),
        },
        world.employer_headers,
    )
    error = validate_error(response, ApiErrorId.ERR_WELLNESS_BUDGET_EXCEEDED.value, 422)
    assert error["error_id"] != ApiErrorId.ERR_INCENTIVE_CAP_EXCEEDED.value, (
        "15000 cents clears the 360000-cent program cap at rung 24"
    )

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 0
    employer = validate_success(
        api_client.get_employer(world.employer_id, world.employer_headers)
    )
    assert employer["wellness_budget_committed_cents"] == 0


def _settlement_world():
    world = setup_clinic(
        employer={
            "legal_name": "Conserve Co",
            "employer_code": "CNS",
            "wellness_budget_cents": 500000,
        },
        contract=False,
        shift=False,
        eligibility={"subscriber_external_id": "S-2201", "member_external_id": "M-2201"},
        participant={"display_name": "Money Tester"},
        reporting_period={},
    )
    world.award = new_award(
        world.participant_id,
        world.employer_id,
        world.period_id,
        award_type="PARTICIPATORY",
    )
    return world


def test_settlement_moves_money_between_buckets_without_changing_the_total():
    """PRD §3.8: "Approval by an `EmployerBenefitsAdmin` moves the award
    `PENDING → APPROVED` and stamps `approved_by_user_id` with the acting
    `X-User-ID`; it is available only while the award's reporting period stands at
    `OPEN` or `RESTATING`, and an approval against a period at `FINALIZED` or `CLOSED`
    is refused with `ERR_INVALID_STATE`."
    PRD §3.8: "Marking paid, also by a `PayrollProcessor`, moves the award
    `EXPORTED → PAID` and is the first transition that actually moves money: the
    amount leaves `incentive_pending_cents` and enters `incentive_paid_cents`, while
    `incentive_awarded_cents` stays exactly where it was."

    Design: Difficulty/compensating_invariant/award_paid_then_reversed_conserves_period_incentive_money
    """
    world = _settlement_world()
    award_id = world.award["id"]

    approved = validate_success(
        api_client.approve_incentive_award(award_id, world.employer_headers)
    )
    assert approved["status"] == "APPROVED"
    assert approved["approved_by_user_id"] == world.employer_id
    after_approve = read_period(world.period_id)
    assert after_approve["incentive_pending_cents"] == 15000
    assert_period_money_conservation(after_approve)

    exported = validate_success(
        api_client.export_incentive_award(
            award_id, {"payroll_reference": "PR-2026-06-001"}, world.payroll_headers
        )
    )
    assert exported["status"] == "EXPORTED"
    after_export = read_period(world.period_id)
    assert after_export["incentive_pending_cents"] == 15000
    assert_period_money_conservation(after_export)

    validate_success(api_client.mark_incentive_award_paid(award_id, world.payroll_headers))
    after_paid = read_period(world.period_id)
    assert after_paid["incentive_awarded_cents"] == 15000
    assert after_paid["incentive_pending_cents"] == 0
    assert after_paid["incentive_paid_cents"] == 15000
    assert after_paid["incentive_reversed_cents"] == 0
    assert after_paid["incentive_forfeited_cents"] == 0
    assert_period_money_conservation(after_paid)


def test_reversal_releases_the_employer_commitment():
    """PRD §3.8: "From `PAID` it moves the award to `REVERSED` and shifts the amount
    out of `incentive_paid_cents` into `incentive_reversed_cents`. In both cases
    `incentive_awarded_cents` is unchanged, and in both cases the employer recomputes
    `wellness_budget_committed_cents`, because a reversed award no longer commits
    budget and its cap headroom is released for a later award."
    PRD §3.3: "`incentive_awarded_cents` — the sum of `award_amount_cents` across this
    participant's awards in any status"

    Design: Difficulty/compensating_invariant/award_paid_then_reversed_conserves_period_incentive_money
    """
    world = _settlement_world()
    award_id = world.award["id"]

    api_client.approve_incentive_award(award_id, world.employer_headers)
    api_client.export_incentive_award(
        award_id, {"payroll_reference": "PR-2026-06-001"}, world.payroll_headers
    )
    api_client.mark_incentive_award_paid(award_id, world.payroll_headers)

    reversed_award = validate_success(
        api_client.reverse_incentive_award(award_id, world.employer_headers)
    )
    assert reversed_award["status"] == "REVERSED"
    assert reversed_award["payroll_reference"] == "PR-2026-06-001"

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 15000
    assert period["incentive_pending_cents"] == 0
    assert period["incentive_paid_cents"] == 0
    assert period["incentive_reversed_cents"] == 15000
    assert period["incentive_forfeited_cents"] == 0
    assert_period_money_conservation(period)

    employer = validate_success(
        api_client.get_employer(world.employer_id, world.employer_headers)
    )
    assert employer["wellness_budget_committed_cents"] == 0
    assert employer["wellness_budget_remaining_cents"] == 500000

    participant = validate_success(
        api_client.get_participant(world.participant_id, world.employer_headers)
    )
    assert participant["incentive_awarded_cents"] == 15000


def test_second_award_with_stale_participant_version_rejected():
    """PRD §2.9: "**Creating an incentive award** — `POST /incentive-awards` —
    requires `expected_participant_version`, carrying the client's last observed
    `version` of the target `Participant`. A new award legitimately adds to that
    participant's `incentive_awarded_cents` and consumes program-cap headroom, so a
    create carrying an earlier value has priced the headroom from a stale view and is
    rejected with `ERR_STALE_VERSION`."
    PRD §3.8: "The server copies `employer_id` from the participant, sets
    `retroactive` to false on a directly created award, starts `status` at `PENDING`,
    leaves `approved_by_user_id`, `exported_by_user_id` and `payroll_reference` null,
    and raises the participant's `version` by one."

    Design: Corner/cross_cutting_complexity_layers/stale_participant_version_on_second_award_returns_conflict
    """
    world = setup_clinic(
        employer={
            "legal_name": "OCC Award Co",
            "employer_code": "OCA",
            "wellness_budget_cents": 500000,
        },
        contract=False,
        shift=False,
        eligibility={"subscriber_external_id": "S-5401", "member_external_id": "M-5401"},
        participant={"display_name": "OCC Award Tester"},
        reporting_period={},
    )
    stale_version = participant_version(world.participant_id, world.employer_id)

    first = new_award(
        world.participant_id,
        world.employer_id,
        world.period_id,
        award_type="PARTICIPATORY",
        expected_participant_version=stale_version,
    )
    assert first["award_amount_cents"] == 15000
    assert first["retroactive"] is False

    response = api_client.create_incentive_award(
        {
            "participant_id": world.participant_id,
            "reporting_period_id": world.period_id,
            "award_type": "TOBACCO_CESSATION",
            "expected_participant_version": stale_version,
        },
        world.employer_headers,
    )
    validate_error(response, ApiErrorId.ERR_STALE_VERSION.value, 412)

    _, meta = validate_paginated(
        api_client.list_incentive_awards(
            world.employer_headers, params={"participant_id": world.participant_id}
        )
    )
    assert meta["total_count"] == 1

    period = read_period(world.period_id)
    assert period["incentive_awarded_cents"] == 15000
    assert (
        participant_version(world.participant_id, world.employer_id) == stale_version + 1
    )
