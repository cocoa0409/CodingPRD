"""Depth coverage for refusal priority, inclusive boundaries and cross-entity gates.

Each pair of tests here drives one request that breaks two rules at once, or sits
one cent or one unit either side of an inclusive threshold, or is refused until a
neighbouring resource reaches the state it depends on.
"""

from test_helpers import (
    factories,
    fixtures,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.assertions import (
    assert_fund_inflow_composed,
    assert_fund_money_conserved,
    assert_obligation_equivalents_conserved,
    round_half_up,
)
from test_helpers.constants import (
    AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE,
    AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE,
    CLOCK_STARTUP_DEFAULT,
)

RENTAL_UNIT = {
    "bedrooms": 2,
    "sqft": 900,
    "market_comparable_sqft": 1000,
    "tenure": "RENTAL",
    "affordability_level_bps": 5000,
}

OWNERSHIP_UNIT = {
    "bedrooms": 2,
    "sqft": 950,
    "market_comparable_sqft": 1100,
    "affordability_level_bps": 5000,
}

OWNERSHIP_AGREEMENT = {
    "term_years": 45,
    "resale_formula": "AMI_INDEXED",
    "owner_appreciation_share_bps": 2500,
    "max_refinance_ltv_bps": 9000,
}

TEN_UNIT_PROJECT = {
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-01-15",
}


def build_superseded_substitution_fee(api, developer_headers: dict, admin_headers: dict) -> dict:
    """A substitution assessment unwound by a reinstatement, so no longer payable."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="Q-101"),
        project_overrides=dict(TEN_UNIT_PROJECT, name="Quarry Bend"),
    )
    validate_success(
        api.withdraw_unit(ctx["unit"]["id"], "Podium redesign.", headers=developer_headers)
    )
    fees, _meta = validate_paginated(
        api.list_in_lieu_fees(project_id=ctx["project"]["id"], headers=admin_headers)
    )
    ctx["fee"] = fees[0]
    validate_success(api.reinstate_unit(ctx["unit"]["id"], headers=developer_headers))
    ctx["fee"] = validate_success(api.get_in_lieu_fee(ctx["fee"]["id"], headers=admin_headers))
    return ctx


def test_paying_an_over_balance_amount_into_a_superseded_assessment_cites_the_state(
    api, developer, program_admin
):
    """The unpayable-state refusal masks the over-balance one deliberately.

    A payment of 999999999 cents into an assessment that a reinstatement already
    unwound breaks both the state rule and the balance rule, and the contract
    pins which of the two the caller is told about.

    PRD: "First, rung 19 outranks rung 43: paying an over-balance amount into a `SUPERSEDED` assessment violates both rules, and the response must be `ERR_FEE_NOT_PAYABLE`, not `ERR_PAYMENT_EXCEEDS_BALANCE`."

    Design: Difficulty/priority_pair_validation_conflict/superseded_fee_payment_state_beats_fiscal_overpayment
    """
    ctx = build_superseded_substitution_fee(api, developer, program_admin)
    assert ctx["fee"]["state"] == "SUPERSEDED"
    assert ctx["fee"]["assessed_amount_cents"] == 24467400

    response = api.pay_in_lieu_fee(ctx["fee"]["id"], 999999999, headers=developer)

    validate_error(response, "ERR_FEE_NOT_PAYABLE", 409)


def test_the_masked_over_balance_payment_moves_neither_the_fee_nor_the_project(
    api, developer, program_admin
):
    """A refused payment is inert on both the assessment and its parent.

    The assessment stays superseded with nothing paid into it, and the project's
    obligation stays entirely on the onsite leg the reinstatement returned it to.

    PRD: "The in-lieu assessment being paid is in state `ASSESSED`, `PARTIALLY_PAID` or `DELINQUENT`; a `PAID` or `SUPERSEDED` assessment accepts no further payment and yields `ERR_FEE_NOT_PAYABLE`."

    Design: Difficulty/priority_pair_validation_conflict/superseded_fee_payment_state_beats_fiscal_overpayment
    """
    ctx = build_superseded_substitution_fee(api, developer, program_admin)

    validate_error(
        api.pay_in_lieu_fee(ctx["fee"]["id"], 999999999, headers=developer),
        "ERR_FEE_NOT_PAYABLE",
        409,
    )

    fee = validate_success(api.get_in_lieu_fee(ctx["fee"]["id"], headers=program_admin))
    assert fee["state"] == "SUPERSEDED"
    assert fee["paid_amount_cents"] == 0
    project = fixtures.live_project(ctx["project"]["id"])
    assert project["onsite_unit_equivalents_bps"] == 10000
    assert project["fee_covered_equivalents_bps"] == 0
    assert_obligation_equivalents_conserved(project)


def build_out_of_compliance_ownership_unit(
    api, officer_headers: dict, developer_headers: dict
) -> dict:
    """An ownership unit dragged out of compliance, carrying one open resale."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides=dict(OWNERSHIP_UNIT, unit_number="K-101"),
        original_purchase_price_cents=32500000,
        project_overrides=dict(TEN_UNIT_PROJECT, name="Kestrel Green"),
        agreement_overrides=dict(OWNERSHIP_AGREEMENT),
    )
    ctx["household"] = fixtures.register_household(
        applicant_name="Owen Marsh", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["certification"] = fixtures.certify_income(
        ctx["household"]["id"],
        ctx["unit"]["id"],
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )

    unit = fixtures.live_unit(ctx["unit"]["id"])
    ctx["first_resale"] = validate_success(
        api.create_resale(
            factories.create_resale_payload(
                unit["id"], unit["version"], proposed_price_cents=32000000
            ),
            headers=officer_headers,
        ),
        201,
    )

    fixtures.set_clock("2027-03-01T00:00:00Z")
    # The owner of a deed-restricted OWNERSHIP unit charges no rent at all: the
    # PRD fixes `contract_rent_cents` at "exactly 0 when the certified unit's
    # `tenure` is `OWNERSHIP`" and its ceiling with "For an `OWNERSHIP` unit it
    # is 0".  The review therefore reports a rent of 0, and the sole finding is
    # the unverified occupancy this builder exists to produce.
    ctx["monitoring_review"] = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["unit"]["id"],
                review_year=2027,
                reported_rent_cents=0,
                occupancy_verified=False,
            ),
            headers=officer_headers,
        ),
        201,
    )
    fixtures.set_clock("2027-04-05T00:00:00Z")
    ctx["monitoring_review"] = validate_success(
        api.submit_cure(ctx["monitoring_review"]["id"], 0, headers=developer_headers)
    )
    ctx["unit"] = fixtures.live_unit(ctx["unit"]["id"])
    return ctx


def test_the_enforcement_refusal_outranks_the_prior_transaction_link_check(
    api, compliance_officer, developer
):
    """Two broken rules on one submission resolve to the safety one.

    The unit is out of compliance and the named prior link is not a closed resale
    of that unit, so the ladder — not the payload's order — decides that the
    enforcement refusal is what comes back.

    PRD: "When a single request violates more than one rule, the response is decided by the **first** violated rule in the ordering below, and only that rule's error is returned."

    PRD: "Second, rung 22 outranks rung 39: submitting a resale on an `OUT_OF_COMPLIANCE` unit while also naming another unit's closed transaction as the prior link violates both, and the response must be `ERR_UNIT_OUT_OF_COMPLIANCE`, not `ERR_PRIOR_TRANSACTION_MISMATCH`."

    Design: Difficulty/priority_pair_validation_conflict/out_of_compliance_safety_beats_prior_transaction_referential
    """
    ctx = build_out_of_compliance_ownership_unit(api, compliance_officer, developer)
    assert ctx["monitoring_review"]["state"] == "ESCALATED"
    assert ctx["monitoring_review"]["finding_types"] == ["OCCUPANCY_UNVERIFIED"]
    assert ctx["unit"]["compliance_status"] == "OUT_OF_COMPLIANCE"

    payload = factories.create_resale_payload(
        ctx["unit"]["id"],
        ctx["unit"]["version"],
        proposed_price_cents=32000000,
        prior_transaction_id=ctx["first_resale"]["id"],
    )
    response = api.create_resale(payload, headers=compliance_officer)

    validate_error(response, "ERR_UNIT_OUT_OF_COMPLIANCE", 422)


def test_the_penalty_and_deadline_that_carried_the_unit_into_enforcement_stand(
    api, compliance_officer, developer
):
    """The unverified-occupancy finding earns the flat penalty and no extension.

    An occupancy failure carries no rent overcharge, so the base penalty is the
    bare 25000-cent monthly charge, the extension is 0, and the earlier open
    transaction the refused submission named is left untouched at SUBMITTED.

    PRD: "`penalty_at_base_cents` is `overcharge_monthly_cents` multiplied by 3, plus 25000 cents for exactly one month."

    Design: Difficulty/priority_pair_validation_conflict/out_of_compliance_safety_beats_prior_transaction_referential
    """
    ctx = build_out_of_compliance_ownership_unit(api, compliance_officer, developer)
    review = ctx["monitoring_review"]

    assert review["overcharge_monthly_cents"] == 0
    assert review["penalty_at_base_cents"] == 25000
    assert review["cure_extension_days"] == 0
    assert str(review["cure_deadline"]).startswith("2027-03-31")

    validate_error(
        api.create_resale(
            factories.create_resale_payload(
                ctx["unit"]["id"],
                ctx["unit"]["version"],
                proposed_price_cents=32000000,
                prior_transaction_id=ctx["first_resale"]["id"],
            ),
            headers=compliance_officer,
        ),
        "ERR_UNIT_OUT_OF_COMPLIANCE",
        422,
    )

    first = validate_success(
        api.get_resale(ctx["first_resale"]["id"], headers=compliance_officer)
    )
    assert first["state"] == "SUBMITTED"
    assert first["proposed_price_cents"] == 32000000


def build_threshold_pair(developer_headers: dict, rival_headers: dict) -> dict:
    """Two identically zoned developments, one at ten units and one at nine."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    program = fixtures.bootstrap_program()
    program["at_threshold"] = fixtures.register_project(
        headers=developer_headers,
        name="Threshold House A",
        zoning_district="R-2",
        total_units=10,
        approval_date="2026-01-15",
    )
    program["below_threshold"] = fixtures.register_project(
        headers=rival_headers,
        name="Threshold House B",
        zoning_district="R-2",
        total_units=9,
        approval_date="2026-01-15",
    )
    return program


def test_a_development_of_exactly_ten_units_reaches_the_size_trigger(
    api, program_admin, developer, rival_developer
):
    """The project-size trigger is inclusive, so ten units is subject.

    Screening pins the vintage, sizes a whole dwelling with no priceable residual,
    and leaves the development deficient because it has delivered nothing yet.

    PRD: "`min_project_units_threshold`, an integer of at least 1, is the project-size trigger: a development is subject to the ordinance only when its unit count reaches this value."

    PRD: "A project fresh from a subject screening has no units and no assessments, so its posture is `DEFICIENT`."

    Design: Difficulty/boundary_precision_check/project_size_threshold_inclusive_at_ten_units
    """
    ctx = build_threshold_pair(developer, rival_developer)

    project = validate_success(
        api.screen_project(ctx["at_threshold"]["id"], headers=program_admin)
    )

    assert project["state"] == "SCREENED_SUBJECT"
    assert project["applicability"] == "SUBJECT"
    assert project["required_affordable_units"] == 1
    assert project["fractional_obligation_bps"] == 0
    assert project["total_obligation_bps"] == 10000
    assert project["compliance_posture"] == "DEFICIENT"
    assert project["ordinance_id"] == ctx["ordinance"]["id"]
    assert project["screen_count"] == 1


def test_a_development_one_unit_below_the_trigger_screens_exempt(
    api, program_admin, developer, rival_developer
):
    """Nine units is strictly below the trigger, so the whole obligation is zero.

    The exempt verdict zeroes all three obligation figures at once and parks the
    posture outside the compliance vocabulary entirely, while still recording that
    the development has been screened once.

    PRD: "If the district is absent from that map, **or** the project's `total_units` is strictly below the vintage's `min_project_units_threshold`, the verdict is exemption: `applicability` becomes `EXEMPT`, `required_affordable_units`, `fractional_obligation_bps` and `total_obligation_bps` are all set to 0, `compliance_posture` becomes `NOT_APPLICABLE`, and the project lands in `SCREENED_EXEMPT`."

    Design: Difficulty/boundary_precision_check/project_size_threshold_inclusive_at_ten_units
    """
    ctx = build_threshold_pair(developer, rival_developer)
    subject = validate_success(
        api.screen_project(ctx["at_threshold"]["id"], headers=program_admin)
    )

    project = validate_success(
        api.screen_project(ctx["below_threshold"]["id"], headers=program_admin)
    )

    assert project["state"] == "SCREENED_EXEMPT"
    assert project["applicability"] == "EXEMPT"
    assert project["required_affordable_units"] == 0
    assert project["fractional_obligation_bps"] == 0
    assert project["total_obligation_bps"] == 0
    assert project["compliance_posture"] == "NOT_APPLICABLE"
    assert project["screen_count"] == 1
    assert subject["total_obligation_bps"] == 10000
    assert subject["screen_count"] == 1


def build_refinance_candidate() -> dict:
    """A restricted ownership unit whose cap is set by the 2028 schedule."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides=dict(OWNERSHIP_UNIT, unit_number="LR-101"),
        original_purchase_price_cents=32500000,
        project_overrides=dict(TEN_UNIT_PROJECT, name="Loanwright Row"),
        agreement_overrides=dict(OWNERSHIP_AGREEMENT),
    )
    fixtures.publish_later_ami_schedule()
    return ctx


def test_a_refinance_one_cent_over_the_ceiling_is_refused(api, compliance_officer):
    """The ceiling is 31295224 cents and the cent above it is not lendable.

    The restricted value today is 34772471 cents, ninety percent of which rounds
    half up to 31295224, and a request for one cent more is refused with nothing
    recorded on the unit.

    PRD: "If `requested_balance_cents` exceeds the cap the review is refused with `ERR_REFINANCE_EXCEEDS_CAP`; the cap is inclusive, so a request exactly equal to it is approved and the cap plus one cent is not."

    Design: Difficulty/boundary_precision_check/refinance_cap_inclusive_at_exact_ltv_ceiling
    """
    ctx = build_refinance_candidate()
    restricted_value = round_half_up(
        32500000 * AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE["3"],
        AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"],
    )
    assert restricted_value == 34772471
    assert round_half_up(restricted_value * 9000, 10000) == 31295224

    before = fixtures.live_unit(ctx["unit"]["id"])
    response = api.refinance_review(ctx["unit"]["id"], 31295225, headers=compliance_officer)

    validate_error(response, "ERR_REFINANCE_EXCEEDS_CAP", 422)
    # The refusal is inert: the borrowed balance the unit carried before the
    # request is exactly what it carries after it.  The PRD names the value only
    # for the approval branch ("On approval `last_refinance_balance_cents`
    # records the requested balance"), so the refusal branch is checked for
    # non-movement rather than against a specific unset sentinel.
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["last_refinance_balance_cents"] == before["last_refinance_balance_cents"]
    assert unit["version"] == before["version"]


def test_a_refinance_at_exactly_the_ceiling_is_approved(api, compliance_officer):
    """A request equal to the cap clears it and is recorded on the unit.

    Approval stores both the computed ceiling and the borrowed balance without
    disturbing the frozen basis the ceiling was derived from.

    PRD: "On approval `last_refinance_balance_cents` records the requested balance."

    Design: Difficulty/boundary_precision_check/refinance_cap_inclusive_at_exact_ltv_ceiling
    """
    ctx = build_refinance_candidate()

    unit = validate_success(
        api.refinance_review(ctx["unit"]["id"], 31295224, headers=compliance_officer)
    )

    assert unit["approved_refinance_cap_cents"] == 31295224
    assert unit["last_refinance_balance_cents"] == 31295224
    assert unit["original_purchase_price_cents"] == 32500000
    assert unit["ami_income_at_purchase_cents"] == AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]
    assert unit["restriction_state"] == "RECORDED"


MARKETING_WINDOW = {
    "lottery_open_at": "2026-09-01T00:00:00Z",
    "lottery_close_at": "2026-10-01T00:00:00Z",
    "preference_categories": ["LIVE_WORK", "DISPLACED"],
}


def build_plan_awaiting_recording() -> dict:
    """A submitted plan on a project whose agreement is still only drafted."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.path_elected_project(
        "ONSITE", project_overrides=dict(TEN_UNIT_PROJECT, name="Fernbank Lofts")
    )
    ctx["agreement"] = fixtures.draft_agreement(ctx["project"]["id"])
    ctx["unit"] = fixtures.add_unit(
        ctx["project"]["id"],
        ctx["agreement"]["id"],
        unit_number="F-101",
        **RENTAL_UNIT,
    )
    return fixtures.submitted_marketing_plan(ctx=ctx, plan_overrides=dict(MARKETING_WINDOW))


def test_marketing_approval_is_refused_while_the_agreement_is_only_drafted(
    api, compliance_officer
):
    """The plan cannot be approved until the neighbouring agreement is recorded.

    Nothing about the plan itself is wrong, but the project has not reached
    `AGREEMENT_RECORDED`, so the approval is refused and the inventory it would
    have released stays exactly where it was.

    PRD: "Approval is gated on the project: the project must be in `state` `AGREEMENT_RECORDED`, and its `compliance_posture` must be anything other than `UNDER_ENFORCEMENT`; either failure is refused with `ERR_PROJECT_NOT_READY_FOR_MARKETING`."

    Design: Difficulty/cross_entity_state_dependency/marketing_plan_approval_requires_project_agreement_recorded
    """
    ctx = build_plan_awaiting_recording()
    assert ctx["project"]["state"] == "PATH_ELECTED"
    assert ctx["agreement"]["state"] == "DRAFT"

    response = api.review_marketing_plan(
        ctx["marketing_plan"]["id"], "APPROVE", headers=compliance_officer
    )

    validate_error(response, "ERR_PROJECT_NOT_READY_FOR_MARKETING", 409)
    plan = validate_success(
        api.get_marketing_plan(ctx["marketing_plan"]["id"], headers=compliance_officer)
    )
    assert plan["state"] == "SUBMITTED"
    assert plan["revision_round"] == 0
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["occupancy_status"] == "PLANNED"


def test_recording_the_agreement_lets_the_identical_approval_through(
    api, compliance_officer
):
    """The recording cascade satisfies the gate and the same request now succeeds.

    Recording moves the agreement and, through it, the project into the state the
    approval was waiting for, and the byte-identical approval then releases the
    planned unit into marketing.

    PRD: "On success the agreement moves `DRAFT → RECORDED` with `doc_number` and `recorded_at` stored and its `version` incremented, and the recording cascades into the project: the project moves `PATH_ELECTED → AGREEMENT_RECORDED` and its `version` increments too."

    Design: Difficulty/cross_entity_state_dependency/marketing_plan_approval_requires_project_agreement_recorded
    """
    ctx = build_plan_awaiting_recording()
    validate_error(
        api.review_marketing_plan(
            ctx["marketing_plan"]["id"], "APPROVE", headers=compliance_officer
        ),
        "ERR_PROJECT_NOT_READY_FOR_MARKETING",
        409,
    )

    agreement = validate_success(
        api.record_agreement(
            ctx["agreement"]["id"],
            doc_number="DOC-FL-0001",
            recorded_at="2026-08-01",
            headers=compliance_officer,
        )
    )
    assert agreement["state"] == "RECORDED"
    assert agreement["doc_number"] == "DOC-FL-0001"
    project = fixtures.live_project(ctx["project"]["id"])
    assert project["state"] == "AGREEMENT_RECORDED"

    plan = validate_success(
        api.review_marketing_plan(
            ctx["marketing_plan"]["id"], "APPROVE", headers=compliance_officer
        )
    )

    assert plan["state"] == "APPROVED"
    assert plan["revision_round"] == 0
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["occupancy_status"] == "MARKETING"


def build_draw_against_unpaid_fee(api, admin_headers: dict, developer_headers: dict) -> dict:
    """Two fee-path developments: the first assessment paid, the second not."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.bootstrap_program()
    for key, name, headers in (
        ("first", "Ironworks One", developer_headers),
        ("second", "Ironworks Two", fixtures.DEV2),
    ):
        project = fixtures.register_project(
            headers=headers,
            name=name,
            zoning_district="C-2",
            total_units=40,
            approval_date="2026-01-15",
        )
        fixtures.screen_project(project["id"])
        project = fixtures.elect_path(project["id"], "IN_LIEU_FEE", headers=headers)
        ctx[key + "_project"] = project
        ctx[key + "_fee"] = validate_success(
            api.create_in_lieu_fee(
                factories.create_in_lieu_fee_payload(
                    project["id"], project["version"], basis="FULL"
                ),
                headers=admin_headers,
            ),
            201,
        )
    ctx["first_fee"] = fixtures.pay_fee(ctx["first_fee"]["id"], headers=developer_headers)
    ctx["disbursement"] = fixtures.request_draw(ctx["second_fee"]["id"], 5000000)
    return ctx


def test_a_draw_cannot_leave_the_fund_while_its_source_assessment_is_unpaid(
    api, program_admin, developer
):
    """The earmarked assessment must have been settled, not merely assessed.

    The fund holds plenty of money from the neighbouring development, but the draw
    is earmarked against an assessment nobody has paid, so it stays requested with
    nothing stamped on it.

    PRD: "It requires the earmarked assessment to be in `state` `PAID`: drawing against an assessment that is still `ASSESSED`, `PARTIALLY_PAID`, `DELINQUENT` or `SUPERSEDED` is refused with `ERR_SOURCE_FEE_NOT_PAID`."

    Design: Difficulty/cross_entity_state_dependency/disbursement_disburse_requires_source_fee_paid
    """
    ctx = build_draw_against_unpaid_fee(api, program_admin, developer)
    assert ctx["first_fee"]["state"] == "PAID"
    assert ctx["second_fee"]["state"] == "ASSESSED"
    assert ctx["second_fee"]["assessed_amount_cents"] == 189120000

    response = api.disburse(ctx["disbursement"]["id"], headers=program_admin)

    validate_error(response, "ERR_SOURCE_FEE_NOT_PAID", 409)
    draw = validate_success(
        api.get_disbursement(ctx["disbursement"]["id"], headers=program_admin)
    )
    assert draw["state"] == "REQUESTED"
    assert draw["disbursed_at"] is None
    assert draw["amount_cents"] == 5000000


def test_settling_the_source_assessment_lets_the_identical_disbursement_through(
    api, program_admin, developer, rival_developer
):
    """Paying the second assessment satisfies the gate and moves the buckets.

    Once the source is `PAID` the same draw disburses, and the cents move from the
    encumbered bucket to the disbursed one while the unencumbered balance — now
    resting on 378240000 cents of paid fees — is left alone.

    PRD: "Disbursement moves the cents from the encumbered bucket to the disbursed bucket and therefore leaves `unencumbered_balance_cents` completely unchanged."

    Design: Difficulty/cross_entity_state_dependency/disbursement_disburse_requires_source_fee_paid
    """
    ctx = build_draw_against_unpaid_fee(api, program_admin, developer)
    validate_error(
        api.disburse(ctx["disbursement"]["id"], headers=program_admin),
        "ERR_SOURCE_FEE_NOT_PAID",
        409,
    )

    settled = fixtures.pay_fee(ctx["second_fee"]["id"], headers=rival_developer)
    assert settled["state"] == "PAID"
    before = validate_success(api.get_trust_fund_summary(headers=program_admin))

    draw = validate_success(api.disburse(ctx["disbursement"]["id"], headers=program_admin))

    assert draw["state"] == "DISBURSED"
    assert draw["disbursed_at"] is not None
    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["total_paid_fees_cents"] == 378240000
    assert summary["total_recapture_cents"] == 0
    assert summary["encumbered_cents"] == 0
    assert summary["disbursed_cents"] == 5000000
    assert summary["unencumbered_balance_cents"] == 373240000
    assert summary["unencumbered_balance_cents"] == before["unencumbered_balance_cents"]
    assert_fund_inflow_composed(summary)
    assert_fund_money_conserved(summary)
