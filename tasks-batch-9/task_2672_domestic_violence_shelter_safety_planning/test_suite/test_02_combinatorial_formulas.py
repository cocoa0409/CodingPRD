"""Two formulas whose evaluation ORDER changes the answer: per-component rounding
before summing a coverage score, and reading a landlord's tier before the
commitment it is about to record.
"""

from test_helpers import (
    MODERATE_FACTORS,
    api_client,
    assert_component_scoring,
    assert_landlord_ledger_invariant,
    assert_plan_component,
    client_version,
    create_plan_component_payload,
    create_safety_plan_payload,
    get_success_data,
    match_referral,
    read_partner,
    read_plan,
    seed_client_with_assessed_call,
    seed_draft_plan_by_disposition,
    seed_hotline_advocate,
    seed_housing_specialist,
    seed_referral_on_active_plan,
    submit_referral,
    validate_success,
)


def _superseding_draft_plan(advocate, client_code="C-3001"):
    """Dispose SAFETY_PLAN_ONLY, then author the plan this test will score."""
    client, call, assessment = seed_client_with_assessed_call(
        advocate,
        client_overrides={"client_code": client_code, "legal_name": "Nora Beck"},
        assessment_overrides=dict(MODERATE_FACTORS),
    )
    seed_draft_plan_by_disposition(advocate, client["id"], call["id"])
    plan = get_success_data(
        api_client.create_safety_plan(
            create_safety_plan_payload(
                client["id"],
                assessment["id"],
                client_version(client["id"], advocate.headers),
            ),
            advocate.headers,
        )
    )
    return client, plan


def test_single_draft_communication_component_rounds_its_own_subscore_to_0_88():
    """A DRAFT COMMUNICATION component's raw 0.875 must round half up to 0.88.

    PRD: "Each component's `subscore` is its `weight_effective` multiplied by its
    status factor, divided by 10, and rounded half up to two decimal places."

    Design: Difficulty/combinatorial_formula/coverage_score_rounds_per_component_then_sums
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    _client, plan = _superseding_draft_plan(advocate)

    response = api_client.create_plan_component(
        plan["id"],
        create_plan_component_payload("COMMUNICATION", target_completion_date="2026-08-15"),
        advocate.headers,
    )

    component = validate_success(response, 201)
    assert_plan_component(component)
    assert_component_scoring(component, weight_effective=25, subscore=0.88, status="DRAFT")
    assert read_plan(plan["id"], advocate.headers)["coverage_score"] == 0.88


def test_two_draft_components_score_1_76_not_1_75():
    """Rounding each component before summing yields 1.76; summing first would give 1.75.

    PRD: "Rounding each component before summing is not the same as summing before
    rounding, and the specification requires the former: two `DRAFT` components, one
    `COMMUNICATION` and one `TECHNOLOGY`, on a client who is not `IMMINENT`, each
    produce a raw 0.875 which rounds to 0.88, and the plan scores 0.88 plus 0.88, which
    is 1.76 — not the 1.75 that would result from summing 0.875 twice and rounding once."

    Design: Difficulty/combinatorial_formula/coverage_score_rounds_per_component_then_sums
    """
    advocate = seed_hotline_advocate("Rosa Marin")
    _client, plan = _superseding_draft_plan(advocate)
    communication = get_success_data(
        api_client.create_plan_component(
            plan["id"],
            create_plan_component_payload("COMMUNICATION", target_completion_date="2026-08-15"),
            advocate.headers,
        )
    )

    response = api_client.create_plan_component(
        plan["id"],
        create_plan_component_payload("TECHNOLOGY", target_completion_date="2026-08-16"),
        advocate.headers,
    )

    technology = validate_success(response, 201)
    assert_component_scoring(communication, weight_effective=25, subscore=0.88, status="DRAFT")
    assert_component_scoring(technology, weight_effective=25, subscore=0.88, status="DRAFT")
    scored_plan = read_plan(plan["id"], advocate.headers)
    assert scored_plan["coverage_score"] == 1.76
    assert scored_plan["coverage_score"] != 1.75
    assert scored_plan["status"] == "DRAFT"


def _housing_scene():
    """A survivor on an ACTIVE plan plus a fresh Vista Rentals partner."""
    advocate = seed_hotline_advocate("Rosa Marin")
    specialist = seed_housing_specialist("Omar Diaz")
    client, _plan, partner, referral = seed_referral_on_active_plan(
        specialist,
        advocate,
        partner_overrides={
            "name": "Vista Rentals",
            "units_pledged": 4,
            "accepts_subsidy_type": "RAPID_REHOUSING_SUBSIDY",
            "base_incentive_cents": 40000,
        },
        referral_overrides={"program_type": "TRANSITIONAL_HOUSING"},
        client_overrides={"client_code": "C-4001", "legal_name": "Mira Sol"},
        assessment_overrides=dict(MODERATE_FACTORS),
    )
    return advocate, specialist, client, partner, referral


def test_first_match_prices_off_a_zero_engagement_score_at_the_base_tier():
    """With no commitments yet the pre-commitment score is 0.0, so the fee is the plain base.

    PRD: "Take a partner with `units_pledged` 4 and `base_incentive_cents` 40000. Their
    first match, of a `TRANSITIONAL_HOUSING` referral, is priced off a pre-commitment
    score of 0.0, which is `BASE`, so the locked fee is 40000; afterwards their
    `engagement_score` reads 25.0."

    Design: Difficulty/combinatorial_formula/landlord_incentive_tier_pinned_to_pre_commit_score
    """
    _advocate, specialist, _client, partner, referral = _housing_scene()

    response = match_referral(
        specialist, referral["id"], partner["id"], monthly_rent_cents=145000
    )

    matched = validate_success(response, 200)
    assert matched["status"] == "MATCHED"
    assert matched["incentive_tier_applied"] == "BASE"
    assert matched["incentive_fee_cents"] == 40000
    after = read_partner(specialist, partner["id"])
    assert after["engagement_score"] == 25.0
    assert after["units_committed"] == 1
    assert after["units_available"] == 3
    assert after["incentive_accrued_cents"] == 40000
    assert_landlord_ledger_invariant(after)


def test_second_match_locks_silver_at_59000_rather_than_gold_at_65000():
    """The tier is read before the commitment, so the second match stays SILVER.

    PRD: "A second match, this time of a `RAPID_REHOUSING` referral, is priced off that
    25.0, which is `SILVER`, so the locked fee is 40000 multiplied by 1.10 — 44000 —
    plus the 15000-cent bonus, for 59000; afterwards the score reads 50.0."

    Design: Difficulty/combinatorial_formula/landlord_incentive_tier_pinned_to_pre_commit_score
    """
    _advocate, specialist, client, partner, first_referral = _housing_scene()
    first = get_success_data(
        match_referral(specialist, first_referral["id"], partner["id"], monthly_rent_cents=145000)
    )
    second_referral = submit_referral(
        specialist,
        client["id"],
        partner["id"],
        program_type="RAPID_REHOUSING",
        subsidy_type="RAPID_REHOUSING_SUBSIDY",
    )

    response = match_referral(
        specialist, second_referral["id"], partner["id"], monthly_rent_cents=152000
    )

    second = validate_success(response, 200)
    assert first["incentive_fee_cents"] == 40000
    assert second["incentive_tier_applied"] == "SILVER"
    assert second["incentive_fee_cents"] == 59000
    assert second["incentive_fee_cents"] != 65000
    assert second["status"] == "MATCHED"
    after = read_partner(specialist, partner["id"])
    assert after["units_committed"] == 2
    assert after["units_available"] == 2
    assert after["engagement_score"] == 50.0
    assert after["incentive_tier"] == "GOLD"
    assert after["incentive_accrued_cents"] == 99000
    assert_landlord_ledger_invariant(after)
