"""Depth coverage for the re-entrant state loops and the multi-row cascades.

Each test walks a resource around a loop or through a cascade and then reads the
neighbouring rows, so a transition that forgets its counter or a cascade that
stops one link short is observable directly.
"""

from test_helpers import factories, fixtures, validate_paginated, validate_success
from test_helpers.assertions import (
    assert_fee_pricing_chain,
    assert_fund_inflow_composed,
    assert_fund_money_conserved,
    assert_obligation_equivalents_conserved,
    assert_waterfall_conserved,
    round_half_up,
    same_calendar_day,
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

TEN_UNIT_PROJECT = {
    "zoning_district": "R-2",
    "total_units": 10,
    "approval_date": "2026-01-15",
}

FIRST_WINDOW = {
    "lottery_open_at": "2026-09-01T00:00:00Z",
    "lottery_close_at": "2026-10-01T00:00:00Z",
    "preference_categories": ["LIVE_WORK", "DISPLACED"],
}

SECOND_WINDOW = {
    "lottery_open_at": "2026-10-01T00:00:00Z",
    "lottery_close_at": "2026-11-01T00:00:00Z",
    "preference_categories": ["LIVE_WORK", "DISPLACED"],
}


def build_plan_under_review(name: str, unit_number: str) -> dict:
    """One ten-unit development with a planned rental unit and a submitted plan."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number=unit_number),
        project_overrides=dict(TEN_UNIT_PROJECT, name=name),
    )
    return fixtures.submitted_marketing_plan(ctx=ctx, plan_overrides=dict(FIRST_WINDOW))


def test_requesting_a_revision_holds_the_loop_counter_and_leaves_units_planned(
    api, compliance_officer, developer
):
    """The revision branch moves no unit and only the resubmission counts a round.

    A revision request is recorded on the plan without touching the inventory,
    and it is the developer's resubmission — not the officer's decision — that
    lifts `revision_round` from 0 to 1.

    PRD: "On `REQUEST_REVISION` the plan moves `SUBMITTED → REVISION_REQUESTED` and **no unit changes occupancy at all**."

    PRD: "`revision_round` increases by one on every resubmission and is the loop counter for the review cycle."

    Design: Difficulty/non_linear_state_machine/marketing_plan_revision_loop_increments_round_then_releases_units
    """
    ctx = build_plan_under_review("Juniper Walk", "J-101")
    plan_id = ctx["marketing_plan"]["id"]
    assert ctx["marketing_plan"]["revision_round"] == 0

    revised = validate_success(
        api.review_marketing_plan(
            plan_id, "REQUEST_REVISION", review_note="Widen the outreach list.",
            headers=compliance_officer,
        )
    )

    assert revised["state"] == "REVISION_REQUESTED"
    assert revised["revision_round"] == 0
    assert revised["reviewed_by_user_id"] == compliance_officer["X-User-ID"]
    assert revised["review_note"] == "Widen the outreach list."
    held = fixtures.live_unit(ctx["unit"]["id"])
    assert held["occupancy_status"] == "PLANNED"

    resubmitted = validate_success(
        api.resubmit_marketing_plan(plan_id, dict(SECOND_WINDOW), headers=developer)
    )

    assert resubmitted["state"] == "SUBMITTED"
    assert resubmitted["revision_round"] == 1
    assert resubmitted["lottery_open_at"].startswith("2026-10-01")
    assert resubmitted["lottery_close_at"].startswith("2026-11-01")
    assert resubmitted["preference_categories"] == ["LIVE_WORK", "DISPLACED"]
    still_planned = fixtures.live_unit(ctx["unit"]["id"])
    assert still_planned["occupancy_status"] == "PLANNED"


def test_approving_the_second_submission_releases_units_without_recounting_rounds(
    api, compliance_officer, developer
):
    """Approval after one loop pass flips the unit and freezes the counter at 1.

    The plan reaches `APPROVED` from its resubmitted form, the planned unit is
    released into marketing by that approval alone, and `revision_round` stays at
    the single round the loop actually ran.

    PRD: "Approval then cascades into the inventory: every restricted unit of that project whose `occupancy_status` is `PLANNED` transitions `PLANNED → MARKETING`, and each such unit independently increments its own `version`."

    Design: Difficulty/non_linear_state_machine/marketing_plan_revision_loop_increments_round_then_releases_units
    """
    ctx = build_plan_under_review("Juniper Walk", "J-101")
    plan_id = ctx["marketing_plan"]["id"]
    validate_success(
        api.review_marketing_plan(plan_id, "REQUEST_REVISION", headers=compliance_officer)
    )
    validate_success(
        api.resubmit_marketing_plan(plan_id, dict(SECOND_WINDOW), headers=developer)
    )
    planned_version = fixtures.live_unit(ctx["unit"]["id"])["version"]

    approved = validate_success(
        api.review_marketing_plan(plan_id, "APPROVE", headers=compliance_officer)
    )

    assert approved["state"] == "APPROVED"
    assert approved["revision_round"] == 1
    assert approved["reviewed_by_user_id"] == compliance_officer["X-User-ID"]
    released = fixtures.live_unit(ctx["unit"]["id"])
    assert released["occupancy_status"] == "MARKETING"
    assert released["version"] == planned_version + 1


def build_escalated_review(api, officer_headers: dict, developer_headers: dict) -> dict:
    """A review already escalated by a cure that landed five days late."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.occupied_rental_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="S-101"),
        project_overrides=dict(TEN_UNIT_PROJECT, name="Sorrel Lane"),
        household_overrides={
            "applicant_name": "Grace Adeyemi",
            "household_size": 3,
            "gross_annual_income_cents": 6000000,
        },
        certification_overrides={
            "contract_rent_cents": 140000,
            "effective_date": "2026-08-01",
        },
    )
    fixtures.set_clock("2027-03-01T00:00:00Z")
    ctx["monitoring_review"] = validate_success(
        api.create_monitoring_review(
            factories.create_monitoring_review_payload(
                ctx["unit"]["id"], review_year=2027, reported_rent_cents=165000
            ),
            headers=officer_headers,
        ),
        201,
    )
    fixtures.set_clock("2027-04-05T00:00:00Z")
    ctx["monitoring_review"] = validate_success(
        api.submit_cure(ctx["monitoring_review"]["id"], 143872, headers=developer_headers)
    )
    return ctx


def test_a_second_cure_reenters_the_pipeline_and_grows_only_the_final_penalty(
    api, compliance_officer, developer
):
    """Curing again from ESCALATED re-enters CURE_SUBMITTED with the old deadline.

    Sixty-five elapsed days make three penalty months at 138384 cents, yet the
    deadline the lateness was measured against stays the 2027-03-31 frozen at
    issue and the unit climbs back out of enforcement.

    PRD: "`penalty_final_cents` is recomputed at the new `cure_submitted_at` and therefore keeps growing with each month of delay, while `cure_deadline` remains the figure frozen at issue."

    Design: Difficulty/non_linear_state_machine/escalated_review_reenters_cure_without_resetting_deadline
    """
    ctx = build_escalated_review(api, compliance_officer, developer)
    assert ctx["monitoring_review"]["state"] == "ESCALATED"
    assert ctx["monitoring_review"]["penalty_final_cents"] == 113384

    fixtures.set_clock("2027-05-05T00:00:00Z")
    review = validate_success(
        api.submit_cure(ctx["monitoring_review"]["id"], 143872, headers=developer)
    )

    assert review["state"] == "CURE_SUBMITTED"
    assert same_calendar_day(review["cure_submitted_at"], "2027-05-05T00:00:00Z")
    assert review["penalty_final_cents"] == 21128 * 3 + 3 * 25000 == 138384
    assert review["penalty_at_base_cents"] == 88384
    assert review["cure_extension_days"] == 0
    assert str(review["cure_deadline"]).startswith("2027-03-31")
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["compliance_status"] == "CURE_PENDING"
    assert unit["current_rent_cents"] == 143872
    project = fixtures.live_project(ctx["project"]["id"])
    assert project["compliance_posture"] == "COMPLIANT_ONSITE"


def test_clearing_the_reentered_cure_closes_the_loop_at_the_grown_penalty(
    api, compliance_officer, second_compliance_officer, developer
):
    """A second officer clears the cure and the penalty stops where it stood.

    Clearing is the review's terminal step: the unit returns to compliance, the
    clearing officer is recorded separately from the issuing one, and the 138384
    cents already earned are neither recomputed nor rolled back.

    PRD: "**Clearing the cure** moves the review `CURE_SUBMITTED → CURED`, storing `cleared_by_user_id`, and cascades the unit `CURE_PENDING → COMPLIANT` with the project's `compliance_posture` recomputed."

    Design: Difficulty/non_linear_state_machine/escalated_review_reenters_cure_without_resetting_deadline
    """
    ctx = build_escalated_review(api, compliance_officer, developer)
    review_id = ctx["monitoring_review"]["id"]
    fixtures.set_clock("2027-05-05T00:00:00Z")
    resubmitted = validate_success(api.submit_cure(review_id, 143872, headers=developer))
    assert resubmitted["issued_by_user_id"] == compliance_officer["X-User-ID"]

    review = validate_success(api.clear_cure(review_id, headers=second_compliance_officer))

    assert review["state"] == "CURED"
    assert review["cleared_by_user_id"] == second_compliance_officer["X-User-ID"]
    assert review["cleared_by_user_id"] != review["issued_by_user_id"]
    assert review["penalty_final_cents"] == 138384
    assert review["cure_extension_days"] == 0
    assert str(review["cure_deadline"]).startswith("2027-03-31")
    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["compliance_status"] == "COMPLIANT"
    project = fixtures.live_project(ctx["project"]["id"])
    assert project["compliance_posture"] == "COMPLIANT_ONSITE"


def build_withdrawn_unit(api, developer_headers: dict) -> dict:
    """A planned rental unit withdrawn by its own developer."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.project_with_unit(
        unit_overrides=dict(RENTAL_UNIT, unit_number="H-101"),
        project_overrides=dict(TEN_UNIT_PROJECT, name="Hawthorn Flats"),
    )
    ctx["unit"] = validate_success(
        api.withdraw_unit(
            ctx["unit"]["id"], "Structural redesign removed the stacked flat.",
            headers=developer_headers,
        )
    )
    return ctx


def test_withdrawing_a_unit_assesses_a_priced_substitution_on_the_projects_behalf(
    api, developer, program_admin
):
    """The withdrawal mints a substitution assessment nobody asked for.

    Losing the dwelling drives the posture deficient, which the system answers by
    pricing exactly one whole unit through the ordinary four-step pipeline: a
    24000000-cent base becomes 24467400 cents owed by 2026-09-15.

    PRD: "Because the posture has become `DEFICIENT` while the project's `compliance_path` is `ONSITE`, the system immediately assesses a substitution in-lieu fee on the project's behalf: a fresh assessment with `basis` `SUBSTITUTION`, `unit_equivalent_bps` of exactly 10000, `ordinance_id` copied from the project's pinned vintage, a `due_date` of the current logical date plus the vintage's `fee_due_days`, and `state` `ASSESSED`."

    Design: Difficulty/transitive_cascade/withdraw_unit_cascades_to_substitution_fee_and_posture_flip
    """
    ctx = build_withdrawn_unit(api, developer)

    assert ctx["unit"]["occupancy_status"] == "WITHDRAWN"
    assert ctx["unit"]["withdrawn_reason"] == "Structural redesign removed the stacked flat."

    fees, meta = validate_paginated(
        api.list_in_lieu_fees(project_id=ctx["project"]["id"], headers=program_admin)
    )
    assert meta["total_count"] == 1
    fee = fees[0]
    assert fee["basis"] == "SUBSTITUTION"
    assert fee["unit_equivalent_bps"] == 10000
    assert fee["base_amount_cents"] == 24000000
    assert fee["surcharge_cents"] == 840000
    assert fee["pre_discount_total_cents"] == 24840000
    assert fee["discount_bps_applied"] == 150
    assert fee["discount_cents"] == 372600
    assert fee["assessed_amount_cents"] == 24467400
    assert_fee_pricing_chain(fee)
    assert fee["state"] == "ASSESSED"
    assert fee["paid_amount_cents"] == 0
    assert fee["due_date"] == "2026-09-15"
    assert fee["ordinance_id"] == ctx["project"]["ordinance_id"]


def test_the_withdrawal_cascade_settles_the_posture_on_the_fee_leg(api, developer):
    """The two recomputations end at COMPLIANT_BY_FEE, not at DEFICIENT.

    The obligation itself never moves: ten thousand basis points leave the onsite
    term, the same ten thousand arrive on the fee term through the assessment the
    withdrawal created, and the posture settles on the money.

    PRD: "Because that assessment now exists, the project's `fee_covered_equivalents_bps` is recomputed and rises by exactly 10000 basis points, its `compliance_posture` is recomputed once more and settles at `COMPLIANT_BY_FEE`, and its `version` increments again."

    Design: Difficulty/transitive_cascade/withdraw_unit_cascades_to_substitution_fee_and_posture_flip
    """
    ctx = build_withdrawn_unit(api, developer)

    project = fixtures.live_project(ctx["project"]["id"])

    assert project["onsite_unit_equivalents_bps"] == 0
    assert project["fee_covered_equivalents_bps"] == 10000
    assert project["total_obligation_bps"] == 10000
    assert project["required_affordable_units"] == 1
    assert project["compliance_posture"] == "COMPLIANT_BY_FEE"
    assert_obligation_equivalents_conserved(project)


OWNERSHIP_AGREEMENT = {
    "term_years": 45,
    "resale_formula": "AMI_INDEXED",
    "owner_appreciation_share_bps": 2500,
    "max_refinance_ltv_bps": 9000,
}

SALE_TERMS = {
    "proposed_price_cents": 36872471,
    "appraised_value_cents": 41000000,
    "capital_improvements_cents": 2500000,
    "deferred_maintenance_cents": 400000,
    "broker_fee_cents": 1000000,
}


def build_resale_ready_to_close(
    api, officer_headers: dict, second_officer_headers: dict, admin_headers: dict
) -> dict:
    """An ownership resale carried all the way to BUYER_CERTIFIED."""
    fixtures.set_clock(CLOCK_STARTUP_DEFAULT)
    ctx = fixtures.restricted_ownership_unit(
        unit_overrides={
            "unit_number": "B-101",
            "bedrooms": 2,
            "sqft": 950,
            "market_comparable_sqft": 1100,
            "affordability_level_bps": 5000,
        },
        original_purchase_price_cents=32500000,
        project_overrides=dict(TEN_UNIT_PROJECT, name="Bellrose Court"),
        agreement_overrides=dict(OWNERSHIP_AGREEMENT),
    )
    ctx["seller"] = fixtures.register_household(
        applicant_name="Selma Hart", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["seller_certification"] = fixtures.certify_income(
        ctx["seller"]["id"],
        ctx["unit"]["id"],
        contract_rent_cents=0,
        effective_date="2026-08-01",
    )
    fixtures.publish_later_ami_schedule()

    unit = fixtures.live_unit(ctx["unit"]["id"])
    ctx["resale"] = validate_success(
        api.create_resale(
            factories.create_resale_payload(unit["id"], unit["version"], **SALE_TERMS),
            headers=officer_headers,
        ),
        201,
    )
    resale_id = ctx["resale"]["id"]
    ctx["resale"] = validate_success(
        api.approve_resale_price(resale_id, headers=officer_headers)
    )
    ctx["resale"] = validate_success(
        api.rofr_decision(resale_id, "WAIVE", headers=admin_headers)
    )
    ctx["buyer"] = fixtures.register_household(
        applicant_name="Ibrahim Sow", household_size=3, gross_annual_income_cents=6000000
    )
    ctx["buyer_certification"] = fixtures.certify_income(
        ctx["buyer"]["id"],
        ctx["unit"]["id"],
        contract_rent_cents=0,
        effective_date="2026-08-01",
        headers=second_officer_headers,
    )
    ctx["resale"] = validate_success(
        api.certify_buyer(
            resale_id,
            ctx["buyer"]["id"],
            ctx["buyer_certification"]["id"],
            headers=second_officer_headers,
        )
    )
    return ctx


def test_closing_the_resale_pours_the_net_proceeds_through_four_ordered_buckets(
    api, compliance_officer, second_compliance_officer, program_admin
):
    """Every cent of the 35872471-cent net lands in exactly one bucket.

    The seller recovers the 32500000-cent basis and the 2500000-cent improvement
    credit, takes a 25 percent share of the 872471-cent residual at 218118, and
    the remaining 654353 is recaptured by the city without a rounding of its own.

    PRD: "The four buckets always sum to `net_proceeds_cents` exactly, for every input including an underwater sale where buckets 2, 3 and 4 all collapse to 0, because bucket 4 absorbs the remainder rather than rounding on its own."

    Design: Difficulty/transitive_cascade/resale_close_cascades_to_unit_basis_seller_certification_and_fund
    """
    ctx = build_resale_ready_to_close(
        api, compliance_officer, second_compliance_officer, program_admin
    )
    assert ctx["resale"]["state"] == "BUYER_CERTIFIED"

    resale = validate_success(
        api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer)
    )

    assert resale["state"] == "CLOSED"
    assert same_calendar_day(resale["closed_at"], CLOCK_STARTUP_DEFAULT)
    assert resale["net_proceeds_cents"] == 36872471 - 1000000 == 35872471
    assert resale["seller_equity_cents"] == 32500000
    assert resale["seller_improvement_credit_cents"] == 2500000
    assert resale["seller_appreciation_share_cents"] == 218118
    assert resale["seller_appreciation_share_cents"] == round_half_up(872471 * 2500, 10000)
    assert resale["city_recapture_cents"] == 654353
    assert_waterfall_conserved(resale)


def test_the_close_cascade_rebases_the_unit_retires_the_seller_and_funds_the_city(
    api, compliance_officer, second_compliance_officer, program_admin
):
    """One close touches the unit, two certifications and the trust fund.

    The unit is rebased to the sale price against the 2028 median, the buyer takes
    occupancy while the seller's certification is retired, and the recaptured
    654353 cents appear as the fund's only inflow.

    PRD: "Because the unit's price basis changed, the seller's `CERTIFIED` certification for that unit moves `CERTIFIED → SUPERSEDED` on both branches."

    Design: Difficulty/transitive_cascade/resale_close_cascades_to_unit_basis_seller_certification_and_fund
    """
    ctx = build_resale_ready_to_close(
        api, compliance_officer, second_compliance_officer, program_admin
    )
    assert ctx["unit"]["ami_income_at_purchase_cents"] == AMI_2026_MEDIAN_INCOME_CENTS_BY_SIZE["3"]

    validate_success(api.close_resale(ctx["resale"]["id"], headers=second_compliance_officer))

    unit = fixtures.live_unit(ctx["unit"]["id"])
    assert unit["original_purchase_price_cents"] == 36872471
    assert unit["ami_income_at_purchase_cents"] == AMI_2028_MEDIAN_INCOME_CENTS_BY_SIZE["3"]
    assert unit["ami_income_at_purchase_cents"] == 13555700
    assert unit["occupant_household_id"] == ctx["buyer"]["id"]
    assert unit["occupancy_status"] == "OCCUPIED"

    seller_certification = validate_success(
        api.get_certification(ctx["seller_certification"]["id"], headers=compliance_officer)
    )
    buyer_certification = validate_success(
        api.get_certification(ctx["buyer_certification"]["id"], headers=compliance_officer)
    )
    assert seller_certification["state"] == "SUPERSEDED"
    assert buyer_certification["state"] == "CERTIFIED"

    summary = validate_success(api.get_trust_fund_summary(headers=program_admin))
    assert summary["total_recapture_cents"] == 654353
    assert summary["total_paid_fees_cents"] == 0
    assert summary["total_inflow_cents"] == 654353
    assert summary["unencumbered_balance_cents"] == 654353
    assert summary["admin_cap_cents"] == 65435
    assert_fund_inflow_composed(summary)
    assert_fund_money_conserved(summary)
