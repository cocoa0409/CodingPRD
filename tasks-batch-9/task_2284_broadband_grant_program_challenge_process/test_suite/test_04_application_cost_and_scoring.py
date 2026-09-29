"""The two cost-per-location variants and the score sheet's nested caps."""

from test_helpers import (
    advance_program_to_scoring,
    claim_location,
    create_application,
    read_application,
    score_application,
    setup_challenge_open_program,
    setup_qualified_subgrantee,
    setup_submitted_application,
    submit_application,
)


def test_cost_per_location_variants_use_different_denominators():
    """The preliminary variant divides the whole project cost by every claim,
    the final variant divides only the eligible cost by the confirmed claims, so
    one claim set yields two different per-location figures.

    PRD 3.5: "The **preliminary** variant divides `total_project_cost_cents` by
    `claim_count` and lands in `preliminary_cost_per_location_cents`; its
    denominator counts every claim regardless of the claimed location's
    classification, and the figure is shown on the application but used for
    nothing else."
    PRD 3.5: "The **final** variant divides `eligible_project_cost_cents` by
    `confirmed_location_count` and lands in `final_cost_per_location_cents`; its
    denominator counts only claims on locations that are `UNSERVED` or
    `UNDERSERVED`, so the very same claim set yields a different per-location
    cost, and this is the figure that drives both the scoring cost tier and the
    award obligation."

    Design: Difficulty/dual_variant_calc/application_cost_per_location_preliminary_vs_final
    """
    ctx = setup_challenge_open_program(("L1", "L2", "L3"))
    subgrantee = setup_qualified_subgrantee(ctx["program_id"])

    application, _ = setup_submitted_application(
        ctx["program_id"],
        subgrantee["id"],
        [
            (ctx["location_ids"]["L1"], 600000),
            (ctx["location_ids"]["L2"], 900002),
            (ctx["location_ids"]["L3"], 900002),
        ],
    )

    assert application["claim_count"] == 3
    assert application["confirmed_location_count"] == 2, (
        "The SERVED location's claim is CLAIMED_INELIGIBLE and so is outside "
        "the narrower set"
    )
    assert application["total_project_cost_cents"] == 2400004
    assert application["eligible_project_cost_cents"] == 1800004
    assert application["preliminary_cost_per_location_cents"] == 800001, (
        "2400004 over three claims is 800001.33, rounded half up to a whole cent"
    )
    assert application["final_cost_per_location_cents"] == 900002, (
        "1800004 over two confirmed locations is exactly 900002"
    )
    assert (
        application["preliminary_cost_per_location_cents"]
        != application["final_cost_per_location_cents"]
    )


def test_final_cost_per_location_is_null_until_submission_stamps_both():
    """A draft carries its claim aggregates but no final per-location cost; both
    variants are stamped by the submission itself.

    PRD 3.5: "The preliminary denominator can never be zero at submission
    because at least one claim is required to submit; the final figure stays
    null while the application is unsubmitted, and a final denominator of zero
    at scoring time is refused with `ERR_NO_ELIGIBLE_LOCATIONS`."
    PRD 3.5: "Submission stamps both cost-per-location variants."

    Design: Difficulty/dual_variant_calc/application_cost_per_location_preliminary_vs_final
    """
    ctx = setup_challenge_open_program(("L1", "L2"))
    subgrantee = setup_qualified_subgrantee(ctx["program_id"])

    draft = create_application(ctx["program_id"], subgrantee["id"])
    claim_location(draft["id"], ctx["location_ids"]["L1"], subgrantee["id"],
                   claimed_cost_cents=600000)
    claim_location(draft["id"], ctx["location_ids"]["L2"], subgrantee["id"],
                   claimed_cost_cents=900002)

    unsubmitted = read_application(draft["id"])
    assert unsubmitted["application_state"] == "DRAFT"
    assert unsubmitted["claim_count"] == 2
    assert unsubmitted["confirmed_location_count"] == 1
    assert unsubmitted["final_cost_per_location_cents"] is None

    submitted = submit_application(draft["id"], subgrantee["id"])
    assert submitted["application_state"] == "SUBMITTED"
    assert submitted["preliminary_cost_per_location_cents"] == 750001, (
        "1500002 over two claims is exactly 750001"
    )
    assert submitted["final_cost_per_location_cents"] == 900002


def _score_one_claim_application(claimed_cost_cents, **application_overrides):
    """A SCORED application carrying a single eligible claim, so the final cost
    per location is exactly the claimed cost."""
    ctx = setup_challenge_open_program(("L3",))
    subgrantee = setup_qualified_subgrantee(ctx["program_id"])
    application, _ = setup_submitted_application(
        ctx["program_id"],
        subgrantee["id"],
        [(ctx["location_ids"]["L3"], claimed_cost_cents)],
        application_overrides=application_overrides,
    )
    advance_program_to_scoring(ctx["program_id"])
    return score_application(application["id"])


def test_component_caps_bite_before_the_multiplier_and_the_total_is_capped_last():
    """Each component is clipped to its own cap first, the capability multiplier
    then lifts the subtotal past 100.00, and the 100.00 ceiling is applied last.

    PRD 3.6: "The total is built from four independently capped components, so a
    component's raw sum may exceed its cap and be clipped before anything else
    happens to it."
    PRD 3.6: "An applicant offering symmetrical gigabit at 50 milliseconds
    therefore raises 32.00 raw and is clipped to 30.00."
    PRD 3.6: "The multiplier is applied once, to the unrounded subtotal, and the
    cap is applied last."

    Design: Difficulty/combinatorial_formula/application_total_score_nested_cap_interaction
    """
    sheet = _score_one_claim_application(
        100000,
        committed_down_mbps=1000,
        committed_up_mbps=1000,
        committed_latency_ms=50,
        low_cost_plan_price_cents=3000,
        participates_in_state_affordability_program=True,
        has_dbe_plan=True,
        has_union_agreement=True,
        local_hire_pct=100,
    )

    assert sheet["cost_points"] == 30.00
    assert sheet["speed_points"] == 30.00, "25.00 plus 5.00 plus 2.00 clipped to 30.00"
    assert sheet["affordability_points"] == 20.00, "20.00 plus 5.00 clipped to 20.00"
    assert sheet["workforce_points"] == 20.00, "5.00 plus 5.00 plus 10.00 is the cap"
    assert sheet["total_score"] == 100.00, (
        "A subtotal of 100.00 lifted by 1.05 is 105.00 before the final cap"
    )


def test_capability_multiplier_is_applied_once_and_rounded_half_up():
    """With no component clipped, the multiplier is applied a single time to the
    subtotal of the four stored figures and the product is rounded half up to
    two decimals.

    PRD 3.6: "The subtotal is the sum of the four component figures as stored;
    `total_score` is that subtotal multiplied by `capability_multiplier`,
    rounded half up to 2 decimals, and then capped at 100.00."
    PRD 3.6: "It adds 5.00 when `has_dbe_plan` is true, 5.00 when
    `has_union_agreement` is true, and a local-hire contribution of 10.00
    multiplied by `local_hire_pct` divided by 100, rounded half up to 2 decimals
    — so a full local-hire commitment earns the whole 10.00 and a half
    commitment earns 5.00."

    Design: Difficulty/combinatorial_formula/application_total_score_nested_cap_interaction
    """
    sheet = _score_one_claim_application(
        100000,
        committed_down_mbps=1000,
        committed_up_mbps=1000,
        committed_latency_ms=50,
        low_cost_plan_price_cents=3000,
        participates_in_state_affordability_program=True,
        has_dbe_plan=True,
        has_union_agreement=False,
        local_hire_pct=25,
    )

    assert sheet["cost_points"] == 30.00
    assert sheet["speed_points"] == 30.00
    assert sheet["affordability_points"] == 20.00
    assert sheet["workforce_points"] == 7.50, "5.00 for the plan plus 2.50 local hire"
    assert sheet["total_score"] == 91.88, (
        "87.50 times 1.05 is 91.875, rounded half up to 91.88"
    )
