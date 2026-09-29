"""
The arithmetic the programme runs, pinned at the figures it is supposed to produce.

Every number here is written out in full rather than recomputed, so a formula that drifts
— compounded escalation instead of linear, an uncapped oversight share, the wrong phase's
contingency tier, the underwriting variant leaking onto the plan, a cumulative cap applied
at the boundary instead of strictly beyond it, an incremented streak instead of a replayed
one, a denied application still taking a share — shows up as a mismatch against a stated
constant.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import (
    add_award,
    add_event,
    add_tax_credit_award,
    assert_estimate_figures,
    assert_fields,
    assert_funding_conservation,
    assert_instant,
    assert_number,
    assert_placement_figures,
    assert_sweep_counters,
    assert_weight_conservation,
    cleanup_goal_payload,
    decide_award,
    file_result,
    impose_obligation,
    run_sweep,
    schedule_attainment_events,
    set_clock,
    stage_acquisition,
    stage_approved,
    stage_assessed,
    stage_bind,
    stage_control_operating,
    stage_enrolled,
    stage_goals,
    stage_inquiry,
    stage_obligations,
    stage_phase_i,
    stage_plan,
    stage_protection,
    stage_quote,
    stage_registry,
    stage_site,
    submit_plan,
)

# ─── design_estimate_correct_result_on_plan_submit ───────────────────────────────

# The five-step design-basis estimate over the six filed cost lines, with the
# construction start three years out and a fully delineated basis phase.
DESIGN_ESTIMATE = {
    "direct_cost_cents": 89787402,
    "escalation_cents": 11313213,
    "contingency_pct": "0.10",
    "contingency_cents": 10110062,
    "oversight_cents": 4000000,
    "total_cents": 115210677,
}

DESIGN_SUBTOTAL_CENTS = 111210677
DESIGN_TOTAL_CENTS = 115210677


def _a_draft_remedy_ready_to_submit(api):
    """An accepted enrollment carrying the six canonical cost lines in a draft remedy."""
    world = stage_enrolled(api)
    stage_plan(world)
    return world


def test_submitting_the_remedy_writes_the_whole_five_step_estimate(api):
    """
    One submit, and all four components plus their total land on the plan.

    "The total is `direct_cost_cents` plus `escalation_cents` plus `contingency_cents` plus
    `oversight_cents`."

    Design: Corner/calculations/design_estimate_correct_result_on_plan_submit
    """
    world = _a_draft_remedy_ready_to_submit(api)

    submitted = submit_plan(world)
    assert_estimate_figures(submitted, DESIGN_ESTIMATE)
    assert_fields(submitted, total_funding_need_cents=DESIGN_TOTAL_CENTS)


def test_escalation_runs_linearly_over_the_three_years(api):
    """
    Three years of 4.2 percent is a multiplication, not a compounded growth factor.

    "`escalation_cents` is the direct cost multiplied by 0.042 multiplied by the applicable
    number of years, rounded half up to whole cents."

    Design: Corner/calculations/design_estimate_correct_result_on_plan_submit
    """
    world = _a_draft_remedy_ready_to_submit(api)

    submitted = submit_plan(world)
    assert_fields(
        submitted,
        years_to_construction_start=3,
        direct_cost_cents=89787402,
        escalation_cents=11313213,
    )


def test_the_oversight_share_stops_at_the_hard_ceiling(api):
    """
    Six and a half percent of this subtotal is well past the cap, so the cap is the figure.

    "Oversight runs at 6.5 percent of that subtotal, rounded half up to whole cents, but it
    is capped: `oversight_cents` is the smaller of that rounded figure and 4,000,000 cents
    (a hard ceiling of 40,000.00 in agency oversight, however large the remedy)."

    Design: Corner/calculations/design_estimate_correct_result_on_plan_submit
    """
    world = _a_draft_remedy_ready_to_submit(api)

    submitted = submit_plan(world)
    subtotal = (
        submitted["direct_cost_cents"]
        + submitted["escalation_cents"]
        + submitted["contingency_cents"]
    )
    assert subtotal == DESIGN_SUBTOTAL_CENTS, (
        f"the subtotal the oversight share reads should be {DESIGN_SUBTOTAL_CENTS}, "
        f"got {subtotal}"
    )
    assert_fields(submitted, oversight_cents=4000000, total_estimate_cents=DESIGN_TOTAL_CENTS)


# ─── contingency_tier_reads_only_the_basis_assessment_phase ──────────────────────

# What the plan would have reported had the estimate read the screening-level phase's
# 0.35 tier plus its 0.05 adder instead of the basis phase's 0.10.
WRONG_PHASE_TOTAL_CENTS = 145540861


def test_the_contingency_tier_comes_from_the_named_basis_phase_alone(api):
    """
    Two approved phases sit on the parcel and only the one the plan names is read.

    "The contingency rate is read from the `delineation_confidence` of the **single**
    assessment phase named by the plan's `basis_assessment_phase_id` — never from any other
    phase on the parcel."

    Design: Corner/calculations/contingency_tier_reads_only_the_basis_assessment_phase
    """
    world = _a_draft_remedy_ready_to_submit(api)

    screening = get_success_data(
        api.get_assessment_phase(world.phase_i["id"], world.consult_headers)
    )
    assert_fields(screening, status="APPROVED", delineation_confidence="SCREENING")
    assert_number(screening["max_exceedance_factor"], "96.00", "max_exceedance_factor")

    basis = get_success_data(
        api.get_assessment_phase(world.phase_ii["id"], world.consult_headers)
    )
    assert_fields(basis, status="APPROVED", delineation_confidence="FULL")
    assert_number(basis["max_exceedance_factor"], "4.80", "max_exceedance_factor")

    submitted = submit_plan(world)
    assert_fields(submitted, basis_assessment_phase_id=world.phase_ii["id"])
    assert_number(submitted["contingency_pct"], "0.10", "contingency_pct")
    assert_fields(submitted, total_estimate_cents=DESIGN_TOTAL_CENTS)
    assert submitted["total_estimate_cents"] != WRONG_PHASE_TOTAL_CENTS, (
        "reading the screening phase's tier and adder would report "
        f"{WRONG_PHASE_TOTAL_CENTS}"
    )


# ─── underwriting_variant_is_selected_only_by_the_quote_endpoint ─────────────────

UNDERWRITING_ESTIMATE_CENTS = 139803445
UNDERWRITING_ESCALATION_CENTS = 18855354
UNDERWRITING_CONTINGENCY_CENTS = 27160689

PLACEMENT = {
    "attachment_point_cents": 153783790,
    "buffer_layer_cents": 13980345,
    "limit_cents": 50000000,
    "rate_applied": "0.055",
    "premium_cents": 2832500,
}

PREMIUM_CENTS = 2832500
BOUND_NEED_CENTS = 118043177


def _an_approved_remedy_with_a_priced_cap(api):
    """The approved remedy, then one cost cap priced against it on the same day."""
    world = stage_approved(api)
    stage_quote(world)
    return world


def test_the_quote_prices_the_underwriting_variant_of_the_same_lines(api):
    """
    Five years of escalation and a floored contingency, over the identical cost lines.

    "Under the underwriting basis, `contingency_pct` is the larger of that same sum and a
    25-percent floor."

    Design: Corner/calculations/underwriting_variant_is_selected_only_by_the_quote_endpoint
    """
    world = _an_approved_remedy_with_a_priced_cap(api)

    policy = world.read_policy()
    assert_fields(
        policy,
        underwriting_estimate_cents=UNDERWRITING_ESTIMATE_CENTS,
        status="QUOTED",
        bound_at=None,
    )
    assert (
        policy["underwriting_estimate_cents"]
        == DESIGN_ESTIMATE["direct_cost_cents"]
        + UNDERWRITING_ESCALATION_CENTS
        + UNDERWRITING_CONTINGENCY_CENTS
        + DESIGN_ESTIMATE["oversight_cents"]
    ), (
        "the underwriting estimate is the same four components with five years of "
        "escalation and the floored contingency"
    )


def test_the_plans_own_estimate_is_not_overwritten_by_the_quote(api):
    """
    The two bases are stored in two different places and neither is the other.

    "Under the design basis that total is stored on the plan as `total_estimate_cents`;
    under the underwriting basis it is stored on the cost-cap policy as
    `underwriting_estimate_cents`."

    Design: Corner/calculations/underwriting_variant_is_selected_only_by_the_quote_endpoint
    """
    world = _an_approved_remedy_with_a_priced_cap(api)

    plan = world.read_plan()
    assert_estimate_figures(plan, DESIGN_ESTIMATE)
    assert plan["total_estimate_cents"] != UNDERWRITING_ESTIMATE_CENTS, (
        "the plan must not be rewritten with the underwriting figure"
    )


def test_the_cap_limit_is_ceiled_to_the_carriers_granularity_and_picks_the_middle_rate(api):
    """
    Thirty percent of the estimate is an odd figure, and the ladder reads the exact ratio.

    "The cap limit starts as thirty percent of the underwriting estimate, rounded half up to
    whole cents, and is then rounded **up** to the next whole multiple of 10,000,000 cents —
    a 100,000.00 granularity, because carriers do not write odd limits; a value already
    exactly on a multiple stays where it is."

    Design: Corner/calculations/underwriting_variant_is_selected_only_by_the_quote_endpoint
    """
    world = _an_approved_remedy_with_a_priced_cap(api)

    policy = world.read_policy()
    assert_placement_figures(policy, PLACEMENT)
    assert_fields(policy, underwriting_estimate_cents=UNDERWRITING_ESTIMATE_CENTS)


def test_the_quoted_premium_stays_outside_the_funding_need(api):
    """
    A quote is not a commitment, so the money it would cost is not yet needed.

    "A plan's `total_funding_need_cents` is its `total_estimate_cents` plus the
    `premium_cents` of every cost-cap policy on that plan whose `status` is `BOUND` —
    quoted, superseded and cancelled policies contribute nothing."

    Design: Corner/calculations/underwriting_variant_is_selected_only_by_the_quote_endpoint
    """
    world = _an_approved_remedy_with_a_priced_cap(api)

    assert_fields(world.read_policy(), status="QUOTED", premium_cents=PREMIUM_CENTS)
    assert_fields(
        world.read_plan(),
        total_estimate_cents=DESIGN_TOTAL_CENTS,
        total_funding_need_cents=DESIGN_TOTAL_CENTS,
    )


# ─── bind_reconciles_funding_need_with_the_bound_premium ─────────────────────────


def test_binding_folds_exactly_the_premium_into_the_funding_need(api):
    """
    The need moves by the premium and by nothing else, and the design estimate stands.

    "It then cascades: at the first level the plan's `total_funding_need_cents` becomes its
    `total_estimate_cents` plus this policy's `premium_cents`, with the plan's `version`
    incremented by 1; at the second level every funding award on the parcel whose `status`
    is `AWARDED` has its `allocated_cents` re-derived against the new, larger need by the
    waterfall of §3.9, each changed award having its `version` incremented by 1."

    Design: Corner/calculations/bind_reconciles_funding_need_with_the_bound_premium
    """
    world = _an_approved_remedy_with_a_priced_cap(api)
    before = world.read_plan()

    stage_bind(world)
    bound = world.read_policy()
    assert_fields(bound, status="BOUND", premium_cents=PREMIUM_CENTS)
    assert_instant(bound["bound_at"], "2026-12-10T00:00:00Z", "bound_at")

    plan = world.read_plan()
    assert_fields(
        plan,
        total_estimate_cents=DESIGN_TOTAL_CENTS,
        total_funding_need_cents=BOUND_NEED_CENTS,
        version=before["version"] + 1,
    )
    assert plan["total_funding_need_cents"] - plan["total_estimate_cents"] == PREMIUM_CENTS, (
        "the whole movement in the need is this policy's premium"
    )


def test_the_premium_is_never_repriced_against_the_larger_need(api):
    """
    The limit and the premium were struck on the pre-premium estimate and stay there.

    "This is the part of the system that looks circular and is not: a plan's
    `total_funding_need_cents` includes the premium, and the cap limit looks like a function
    of the funding need — but the limit and the premium are derived from the **pre-premium**
    `underwriting_estimate_cents` alone, and `total_funding_need_cents` is written
    afterwards, at bind, and never re-enters the pricing."

    Design: Corner/calculations/bind_reconciles_funding_need_with_the_bound_premium
    """
    world = _an_approved_remedy_with_a_priced_cap(api)
    quoted = world.read_policy()

    stage_bind(world)
    bound = world.read_policy()
    assert_fields(
        bound,
        underwriting_estimate_cents=quoted["underwriting_estimate_cents"],
        attachment_point_cents=quoted["attachment_point_cents"],
        buffer_layer_cents=quoted["buffer_layer_cents"],
        limit_cents=quoted["limit_cents"],
        premium_cents=quoted["premium_cents"],
    )
    assert_number(bound["rate_applied"], quoted["rate_applied"], "rate_applied")
    assert_placement_figures(bound, PLACEMENT)


# ─── cleanup_goal_attenuated_exactly_at_cumulative_cap_is_not_capped ─────────────

# Three UNRESTRICTED derivations that bracket the shared risk budget: one landing exactly
# on the cap, one a hair above it, and one under the practical quantitation floor.
AT_THE_CAP = {"contaminant_code": "VINYL_CHLORIDE", "media": "SOIL_VAPOR", "screening": 7.5}
ABOVE_THE_CAP = {"contaminant_code": "NAPHTHALENE", "media": "SOIL_VAPOR", "screening": 7.51}
UNDER_THE_FLOOR = {"contaminant_code": "ARSENIC", "media": "GROUNDWATER", "screening": 0.4}


def _derive(world, spec):
    """Derive one unrestricted goal, which takes no control credit at all."""
    return get_success_data(
        world.api.derive_cleanup_goal(
            world.site["id"],
            cleanup_goal_payload(
                contaminant_code=spec["contaminant_code"],
                media=spec["media"],
                screening_level_ugl=spec["screening"],
                basis="UNRESTRICTED",
            ),
            world.consult_headers,
        ),
        201,
    )


def test_an_attenuated_value_exactly_at_the_shared_cap_is_not_capped(api):
    """
    Two vapour analytes drive the media, so the budget halves to exactly this target.

    "The boolean `cumulative_cap_applied` is set true exactly when the cumulative cap was
    strictly below the attenuated value **and** the cumulative cap was strictly above the
    practical quantitation floor — that is, when the shared risk budget, rather than the
    scenario-and-control arithmetic or the floor, is what actually determined the target."

    Design: Corner/calculations/cleanup_goal_attenuated_exactly_at_cumulative_cap_is_not_capped
    """
    world = stage_assessed(api)

    at_the_cap = _derive(world, AT_THE_CAP)
    assert_fields(
        at_the_cap,
        basis="UNRESTRICTED",
        control_credit_type=None,
        contaminant_count_in_media=2,
        cumulative_cap_applied=False,
        attainment_status="NOT_ATTAINED",
        compliant_streak=0,
    )
    assert_number(at_the_cap["goal_ugl"], "250.00", "goal_ugl")


def test_a_hair_above_the_cap_is_clamped_and_says_so(api):
    """
    The very next analyte's arithmetic runs past the budget and the budget wins.

    "The candidate target is the smaller of the attenuated value and the cumulative cap."

    Design: Corner/calculations/cleanup_goal_attenuated_exactly_at_cumulative_cap_is_not_capped
    """
    world = stage_assessed(api)
    _derive(world, AT_THE_CAP)

    above = _derive(world, ABOVE_THE_CAP)
    assert_fields(
        above,
        contaminant_count_in_media=2,
        cumulative_cap_applied=True,
        attainment_status="NOT_ATTAINED",
        compliant_streak=0,
    )
    assert_number(above["goal_ugl"], "250.00", "goal_ugl")


def test_a_target_raised_by_the_practical_floor_is_not_a_capped_one(api):
    """
    The groundwater budget was never the binding constraint, so the flag stays false.

    "The programme will not set a goal below the practical quantitation floor of 0.50
    micrograms per litre, so the selected value is the larger of that floor and the
    candidate."

    Design: Corner/calculations/cleanup_goal_attenuated_exactly_at_cumulative_cap_is_not_capped
    """
    world = stage_assessed(api)
    _derive(world, AT_THE_CAP)
    _derive(world, ABOVE_THE_CAP)

    floored = _derive(world, UNDER_THE_FLOOR)
    assert_fields(
        floored,
        media="GROUNDWATER",
        contaminant_count_in_media=1,
        cumulative_cap_applied=False,
        attainment_status="NOT_ATTAINED",
        compliant_streak=0,
    )
    assert_number(floored["goal_ugl"], "0.50", "goal_ugl")


# ─── funding_assembly_ignores_applied_and_denied_awards ──────────────────────────

DENIED_PROGRAM_CODE = "OH-VAP-TAXCREDIT"
DENIAL_NOTE = "Credit allocation exhausted for the biennium."


def _one_pending_and_one_refused_application(api):
    """An approved remedy with one application still pending and one already refused."""
    world = stage_approved(api)
    pending = add_award(world)
    refused = add_tax_credit_award(
        world,
        program_code=DENIED_PROGRAM_CODE,
        program_priority=2,
        max_award_cents=80000000,
        max_share_pct=1.00,
        match_requirement_pct=0.05,
        eligible_cost_categories=["GW_TREATMENT"],
        eligibility_documents=["BFPP_CERTIFICATION", "PHASE_II_REPORT", "COST_ESTIMATE"],
    )
    refused = decide_award(world, refused, "DENY", decision_note=DENIAL_NOTE)
    return world, pending, refused


def test_neither_a_pending_nor_a_refused_application_takes_a_share(api):
    """
    The waterfall visits the awarded set only, and here that set is empty.

    "The parcel's funding applications whose `status` is `AWARDED` are then visited in order
    of `program_priority` ascending, with `created_at` ascending as the **sole** tie-break —
    the UUID `id` is never a decision input, and applications in `APPLIED`, `DENIED` or
    `RESCINDED` are excluded entirely and carry `allocated_cents` zero."

    Design: Corner/calculations/funding_assembly_ignores_applied_and_denied_awards
    """
    world, _pending, _refused = _one_pending_and_one_refused_application(api)

    assembly = world.read_funding_assembly()
    assert_fields(
        assembly,
        site_id=world.site["id"],
        remedial_action_plan_id=world.plan["id"],
        total_funding_need_cents=DESIGN_TOTAL_CENTS,
        unfunded_gap_cents=DESIGN_TOTAL_CENTS,
        local_match_required_cents=0,
    )
    assert assembly["allocations"] == [], (
        "an empty allocations array, not an array of zero-allocated rows"
    )
    assert_funding_conservation(assembly)


def test_the_refusal_needed_no_preconditions_and_left_the_pending_one_alone(api):
    """
    A denial is terminal on its own, and the matching cost categories never mattered.

    "A `DENY` has no preconditions at all: it moves `APPLIED → DENIED`, which is terminal,
    and `allocated_cents` stays zero."

    Design: Corner/calculations/funding_assembly_ignores_applied_and_denied_awards
    """
    world, pending, refused = _one_pending_and_one_refused_application(api)

    assert_fields(
        world.read_award(refused),
        status="DENIED",
        allocated_cents=0,
        program_code=DENIED_PROGRAM_CODE,
        decided_by_user_id="reviewer-alpha",
    )
    assert_fields(
        world.read_award(pending),
        status="APPLIED",
        allocated_cents=0,
        decided_by_user_id=None,
    )


# ─── bfpp_compliance_is_one_with_no_obligations_and_after_full_imposition ─────────

FIRST_DUTY_DESCRIPTION = "Maintain fencing, signage and stormwater controls."
FIRST_DUTY_DUE_DATE = "2027-03-01"
FULL_WEIGHT = 20


def _an_established_defence_carrying_no_duties(api):
    """A purchaser whose diligence is accepted and whose title is taken, and nothing more."""
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(world)
    stage_inquiry(world)
    stage_acquisition(world)
    return world


def test_an_empty_duty_set_reports_full_compliance_rather_than_none(api):
    """
    The empty denominator is answered with the whole figure, not a division by zero.

    "When `obligations_total_weight` is zero, `compliance_pct` is exactly 1.0; otherwise
    `compliance_pct` is that numerator divided by `obligations_total_weight`, rounded half up
    to four decimal places."

    Design: Corner/calculations/bfpp_compliance_is_one_with_no_obligations_and_after_full_imposition
    """
    world = _an_established_defence_carrying_no_duties(api)

    protection = world.read_protection()
    assert_fields(
        protection,
        obligations_total_weight=0,
        current_weight=0,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=0,
        obligation_state="OBLIGATIONS_NONE",
        bfpp_status="ESTABLISHED",
    )
    assert_number(protection["compliance_pct"], "1.0", "compliance_pct")
    assert_weight_conservation(protection)


def test_the_first_duty_moves_the_dimension_off_the_empty_state(api):
    """
    One imposition is enough to switch the dimension, and it carries its own weight.

    "Imposing a duty requires the parcel not be `FROZEN`, recomputes the weight buckets and
    `compliance_pct`, moves the protection's obligation dimension `OBLIGATIONS_NONE →
    CURRENT`, recomputes `bfpp_status` and increments the protection's `version` by 1."

    Design: Corner/calculations/bfpp_compliance_is_one_with_no_obligations_and_after_full_imposition
    """
    world = _an_established_defence_carrying_no_duties(api)
    before = world.read_protection()

    duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=FIRST_DUTY_DESCRIPTION,
        due_date=FIRST_DUTY_DUE_DATE,
        recurrence_days=90,
    )
    assert_fields(duty, status="CURRENT", certification_count=0, prior_due_date=None)

    protection = world.read_protection()
    assert_fields(
        protection,
        obligations_total_weight=5,
        current_weight=5,
        obligation_state="CURRENT",
        bfpp_status="ESTABLISHED",
        version=before["version"] + 1,
    )
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")


def test_the_five_statutory_weights_sum_to_twenty_with_every_duty_current(api):
    """
    Five, five, four, three and three, all of it sitting in the current bucket.

    "Each category carries a statutory weight: `REASONABLE_STEPS` weighs 5,
    `LAND_USE_RESTRICTION_COMPLIANCE` weighs 5, `INSTITUTIONAL_CONTROL_MAINTENANCE` weighs 4,
    `ACCESS_AND_COOPERATION` weighs 3, and `NOTIFICATION` weighs 3."

    Design: Corner/calculations/bfpp_compliance_is_one_with_no_obligations_and_after_full_imposition
    """
    world = _an_established_defence_carrying_no_duties(api)
    stage_obligations(world)

    protection = world.read_protection()
    assert_fields(
        protection,
        obligations_total_weight=FULL_WEIGHT,
        current_weight=FULL_WEIGHT,
        satisfied_weight=0,
        at_risk_weight=0,
        lapsed_weight=0,
        obligation_state="CURRENT",
        bfpp_status="ESTABLISHED",
    )
    assert_number(protection["compliance_pct"], "1.0000", "compliance_pct")
    assert_weight_conservation(protection)

    assert len(world.obligations) == 5, "one duty in each declared category"
    for duty in world.obligations.values():
        assert_fields(
            world.read_obligation(duty),
            status="CURRENT",
            certification_count=0,
            prior_due_date=None,
            imposed_by_user_id="reviewer-alpha",
        )


# ─── attainment_replay_reorders_a_late_arriving_earlier_sample ───────────────────

LATE_PERIOD_CODE = "2027-M03B"
LATE_SAMPLE_DATE = "2027-03-20"
LATE_WINDOW_START = "2027-03-15T00:00:00Z"
LATE_WINDOW_END = "2027-03-25T00:00:00Z"

COMPLIANT_RESULT = 100.0
LATE_EXCEEDING_RESULT = 200.0


def _four_compliant_quarters_on_the_unrestricted_goal(api):
    """
    Four monthly samples on the vapour goal, all comfortably under its target.

    The goal takes no control credit, so its target is the strict one, and no control is
    named on any of the events — the replay is the only thing these results can move.
    """
    world = stage_assessed(api)
    stage_goals(world)
    events = schedule_attainment_events(world, world.goal_unrestricted)
    set_clock(world.api, "2027-06-01T00:00:00Z")
    for event in events:
        file_result(world, event, COMPLIANT_RESULT)
    return world, events


def _the_late_arriving_sample(world):
    """A fifth event scheduled last but sampled between the second and third quarters."""
    late = add_event(
        world,
        cleanup_goal_id=world.goal_unrestricted["id"],
        monitoring_period_code=LATE_PERIOD_CODE,
        sample_date=LATE_SAMPLE_DATE,
        window_start=LATE_WINDOW_START,
        window_end=LATE_WINDOW_END,
    )
    return late, file_result(world, late, LATE_EXCEEDING_RESULT)


def test_four_consecutive_compliant_samples_attain_the_goal(api):
    """
    The fourth compliant quarter in a row is the one that flips the status.

    "The final value of that running count is stored as `compliant_streak`, and
    `attainment_status` becomes `ATTAINED` when `compliant_streak` is at least 4 — four
    consecutive compliant sampling results — and `NOT_ATTAINED` otherwise."

    Design: Corner/calculations/attainment_replay_reorders_a_late_arriving_earlier_sample
    """
    world, _events = _four_compliant_quarters_on_the_unrestricted_goal(api)

    goal = world.read_goal(world.goal_unrestricted)
    assert_number(goal["goal_ugl"], "166.67", "goal_ugl")
    assert_fields(goal, compliant_streak=4, attainment_status="ATTAINED")


def test_a_late_exceedance_lands_in_the_middle_and_regresses_the_attainment(api):
    """
    Reported last, sampled third from the start, and the two quarters before it are lost.

    "If it exceeds the goal, it resets the streak at that point, and every compliant result
    after it is re-counted from zero."

    Design: Corner/calculations/attainment_replay_reorders_a_late_arriving_earlier_sample
    """
    world, _events = _four_compliant_quarters_on_the_unrestricted_goal(api)
    attained = world.read_goal(world.goal_unrestricted)

    _late, reported = _the_late_arriving_sample(world)
    assert_fields(
        reported,
        status="REPORTED",
        result_status="EXCEEDANCE",
        sample_date=LATE_SAMPLE_DATE,
    )
    assert_number(reported["result_value_ugl"], LATE_EXCEEDING_RESULT, "result_value_ugl")

    replayed = world.read_goal(world.goal_unrestricted)
    assert_fields(
        replayed,
        compliant_streak=2,
        attainment_status="NOT_ATTAINED",
        version=attained["version"] + 1,
    )


def test_an_exceedance_naming_no_control_impairs_nothing(api):
    """
    The same failing result leaves the parcel open, because it blames no installation.

    "When a filed result comes back as `EXCEEDANCE` and the event's `site_control_id` is not
    null, the exceedance is treated as evidence that the named control is not performing, and
    the cascade runs four levels deep inside the same request."

    Design: Corner/calculations/attainment_replay_reorders_a_late_arriving_earlier_sample
    """
    world, _events = _four_compliant_quarters_on_the_unrestricted_goal(api)

    _late, reported = _the_late_arriving_sample(world)
    assert_fields(reported, result_status="EXCEEDANCE", site_control_id=None)
    assert_fields(world.read_site(), cleanup_posture="OPEN", impaired_control_count=0)


# ─── forfeited_defence_dominates_an_impaired_control_in_site_posture ─────────────

CRITICAL_DUTY_DESCRIPTION = "Maintain fencing, signage and stormwater controls."
CRITICAL_DUTY_DUE_DATE = "2027-03-01"

CONTROL_EVENT_CODE = "2027-M02"
CONTROL_EVENT_SAMPLE_DATE = "2027-02-05"
CONTROL_EVENT_WINDOW = ("2027-02-01T00:00:00Z", "2027-02-10T00:00:00Z")
FAILING_RESULT = 900.0

SWEEP_DATE = "2027-03-02"


def _an_impaired_control_beside_a_defence_critical_duty(api):
    """
    A parcel already restricted by one failing installation, with one duty about to lapse.

    The control is in service and its inspection passed, so the impairment comes purely from
    the exceeding sample filed against it; the duty imposed alongside is one of the two
    defence-critical categories, and its deadline falls one day before the sweep date.
    """
    world = stage_approved(api)
    stage_control_operating(world)
    world.duty = impose_obligation(
        world,
        obligation_category="REASONABLE_STEPS",
        description=CRITICAL_DUTY_DESCRIPTION,
        due_date=CRITICAL_DUTY_DUE_DATE,
        recurrence_days=90,
    )
    event = add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        site_control_id=world.control["id"],
        monitoring_period_code=CONTROL_EVENT_CODE,
        sample_date=CONTROL_EVENT_SAMPLE_DATE,
        window_start=CONTROL_EVENT_WINDOW[0],
        window_end=CONTROL_EVENT_WINDOW[1],
    )
    set_clock(world.api, "2027-02-06T00:00:00Z")
    world.exceedance = file_result(world, event, FAILING_RESULT)
    return world


def _sweep_the_parcel(world):
    """Run the ops-run checkpoint on the day after the duty's deadline."""
    set_clock(world.api, "2027-03-02T00:00:00Z")
    return run_sweep(world, SWEEP_DATE, site_id=world.site["id"])


def test_the_failing_installation_restricts_the_parcel_first(api):
    """
    One exceeding sample against a named control is enough to close the parcel's gate.

    "At the third, the parcel's `impaired_control_count` increments and its `cleanup_posture`
    becomes `RESTRICTED` unless it is already `FROZEN`."

    Design: Corner/calculations/forfeited_defence_dominates_an_impaired_control_in_site_posture
    """
    world = _an_impaired_control_beside_a_defence_critical_duty(api)

    assert_fields(world.exceedance, result_status="EXCEEDANCE", status="REPORTED")
    assert_number(world.read_goal(world.goal_restricted)["goal_ugl"], "250.00", "goal_ugl")
    assert_fields(world.read_control(), status="IMPAIRED", impairment_count=1)
    assert_fields(world.read_site(), cleanup_posture="RESTRICTED", impaired_control_count=1)


def test_the_sweep_lapses_the_defence_critical_duty_and_forfeits_the_defence(api):
    """
    A deadline one day in the past takes the whole defence with it.

    "Where a lapsed duty's `obligation_category` is defence-critical, the cascade continues:
    the protection's `obligation_state` becomes `LAPSED`, its `bfpp_status` becomes
    `FORFEITED`, the parcel's `cleanup_posture` becomes `FROZEN`, every closure letter on the
    parcel in `ISSUED` or `ACCEPTED_BY_LENDER` becomes `REVOKED` with `revocation_reason`
    `BFPP_FORFEITED`, and every funding award on the parcel in `AWARDED` becomes `RESCINDED`."

    Design: Corner/calculations/forfeited_defence_dominates_an_impaired_control_in_site_posture
    """
    world = _an_impaired_control_beside_a_defence_critical_duty(api)

    result = _sweep_the_parcel(world)
    assert_sweep_counters(result, lapsed_count=1, frozen_site_count=1)

    assert_fields(world.read_obligation(world.duty), status="LAPSED", due_date=CRITICAL_DUTY_DUE_DATE)
    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="LAPSED",
        lapsed_weight=5,
        current_weight=0,
        bfpp_status="FORFEITED",
    )
    assert_number(protection["compliance_pct"], "0.0000", "compliance_pct")
    assert_weight_conservation(protection)


def test_the_forfeited_defence_outranks_the_still_impaired_installation(api):
    """
    Both conditions now hold at once, and the top of the ladder is the one that answers.

    "The derivation is evaluated top-down and the first matching condition wins: if a
    liability protection exists on the site and its `bfpp_status` is `FORFEITED`, the posture
    is `FROZEN`; otherwise, if `impaired_control_count` is greater than zero, the posture is
    `RESTRICTED`; otherwise the posture is `OPEN`."

    Design: Corner/calculations/forfeited_defence_dominates_an_impaired_control_in_site_posture
    """
    world = _an_impaired_control_beside_a_defence_critical_duty(api)
    _sweep_the_parcel(world)

    assert_fields(world.read_site(), cleanup_posture="FROZEN", impaired_control_count=1)
    assert_fields(world.read_control(), status="IMPAIRED", impairment_count=1)
