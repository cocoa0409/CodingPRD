"""
Inputs placed exactly on a declared threshold, and one step either side of it.

Four boundaries are pinned here: the inclusive 0.85 compliance edge, the contingency
adder that fires at an exceedance factor of exactly 10.0, the inclusive comparison that
makes a result equal to its goal compliant, and the 180-day recency limit on an
all-appropriate-inquiries report.
"""

from prd_bench_local_runner.testing import get_success_data, validate_error

from test_helpers import (
    ERR_AAI_REPORT_STALE,
    add_assessment_phase,
    add_event,
    add_finding,
    add_plan,
    add_site,
    assert_fields,
    assert_number,
    assert_weight_conservation,
    certify_obligation,
    file_result,
    impose_obligation,
    inquiry_completion_payload,
    review_phase,
    run_sweep,
    schedule_attainment_events,
    set_clock,
    stage_assessed,
    stage_enrolled,
    stage_goals,
    stage_phase_i,
    stage_protection,
    stage_registry,
    stage_site,
    submit_phase,
    submit_plan,
)

# ─── compliance_pct_exactly_at_threshold_returns_to_current ─────────────────────

THRESHOLD_DUTIES = (
    ("REASONABLE_STEPS", "Maintain fencing, signage and stormwater controls.", "2027-06-30"),
    (
        "LAND_USE_RESTRICTION_COMPLIANCE",
        "Comply with the recorded environmental covenant.",
        "2027-06-30",
    ),
    (
        "INSTITUTIONAL_CONTROL_MAINTENANCE",
        "Inspect and maintain the sub-slab depressurisation system.",
        "2027-02-05",
    ),
    ("ACCESS_AND_COOPERATION", "Provide agency access on 48 hours notice.", "2027-02-05"),
    ("NOTIFICATION", "Report newly discovered releases within 10 days.", "2027-02-05"),
)

WEIGHTED_DUTY = "INSTITUTIONAL_CONTROL_MAINTENANCE"


def _protection_at_three_quarters(api):
    """
    Five duties, three of them inside the grace window, giving exactly 0.7500.

    The two heavier duties sit months out and stay ``CURRENT``, so the sweep drops the
    figure below the warning threshold without lapsing anything.
    """
    world = stage_assessed(api)
    for category, description, due_date in THRESHOLD_DUTIES:
        world.obligations[category] = impose_obligation(
            world,
            obligation_category=category,
            description=description,
            due_date=due_date,
            recurrence_days=90,
        )
    set_clock(world.api, "2027-01-10T00:00:00Z")
    run_sweep(world, "2027-01-10")
    return world


def test_three_duties_inside_the_grace_window_count_half(api):
    """
    Half of the at-risk weight lands in the numerator, giving fifteen twentieths.

    "The numerator of the compliance figure counts `current_weight` in full,
    `satisfied_weight` in full, half of `at_risk_weight`, and none of `lapsed_weight`."

    Design: Difficulty/boundary_precision_check/compliance_pct_exactly_at_threshold_returns_to_current
    """
    world = _protection_at_three_quarters(api)

    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="AT_RISK",
        bfpp_status="ESTABLISHED",
        obligations_total_weight=20,
        current_weight=10,
        satisfied_weight=0,
        at_risk_weight=10,
        lapsed_weight=0,
    )
    assert_number(protection["compliance_pct"], "0.7500", "compliance_pct")
    assert_weight_conservation(protection)


def test_certifying_the_four_weight_duty_lands_exactly_on_the_threshold(api):
    """
    One certification moves four of the ten at-risk points into satisfied weight.

    "The reverse edge exists too: when a certification restores `compliance_pct` to 0.85
    or above and no defence-critical duty has lapsed, the protection moves `AT_RISK →
    CURRENT`, recomputing the buckets and `compliance_pct` and incrementing `version` by
    1."

    Design: Difficulty/boundary_precision_check/compliance_pct_exactly_at_threshold_returns_to_current
    """
    world = _protection_at_three_quarters(api)

    certified = certify_obligation(world, world.obligations[WEIGHTED_DUTY])
    assert_fields(
        certified,
        status="SATISFIED",
        certification_count=1,
        prior_due_date="2027-02-05",
        due_date="2027-05-06",
    )

    protection = world.read_protection()
    assert_fields(
        protection,
        obligation_state="CURRENT",
        current_weight=10,
        satisfied_weight=4,
        at_risk_weight=6,
        lapsed_weight=0,
    )
    assert_number(protection["compliance_pct"], "0.8500", "compliance_pct")


def test_the_threshold_comparison_is_inclusive_at_exactly_zero_point_eight_five(api):
    """
    Seventeen twentieths is not below the threshold, so the warning state is left.

    "Otherwise, if `compliance_pct` is greater than or equal to 0.85 the dimension is
    `CURRENT` — the comparison is inclusive, so a `compliance_pct` of exactly 0.8500 stays
    `CURRENT`."

    Design: Difficulty/boundary_precision_check/compliance_pct_exactly_at_threshold_returns_to_current
    """
    world = _protection_at_three_quarters(api)
    certify_obligation(world, world.obligations[WEIGHTED_DUTY])

    protection = world.read_protection()
    assert_number(protection["compliance_pct"], "0.8500", "compliance_pct")
    assert_fields(
        protection,
        obligation_state="CURRENT",
        bfpp_status="ESTABLISHED",
        obligations_total_weight=20,
    )
    assert_weight_conservation(protection)

    expected = {
        "REASONABLE_STEPS": "CURRENT",
        "LAND_USE_RESTRICTION_COMPLIANCE": "CURRENT",
        "INSTITUTIONAL_CONTROL_MAINTENANCE": "SATISFIED",
        "ACCESS_AND_COOPERATION": "AT_RISK",
        "NOTIFICATION": "AT_RISK",
    }
    for category, status in expected.items():
        assert_fields(world.read_obligation(world.obligations[category]), status=status)
    assert_fields(world.read_site(), cleanup_posture="OPEN")


# ─── contingency_adder_at_exactly_ten_exceedance_factor ─────────────────────────

DIRECT_COST_CENTS = 89787402
ESCALATION_CENTS = 11313213
OVERSIGHT_CENTS = 4000000

ADDER_CONTINGENCY_CENTS = 25275154
ADDER_TOTAL_CENTS = 130375769
PLAIN_CONTINGENCY_CENTS = 20220123
PLAIN_TOTAL_CENTS = 125320738
ADDER_DELTA_CENTS = 5055031


def _partial_basis_phase(world, location_code, max_concentration_ugl):
    """Approve one PARTIAL-confidence delineation carrying a single arsenic finding."""
    phase = add_assessment_phase(
        world,
        phase_type="PHASE_II",
        field_start_date="2026-11-10",
        field_end_date="2026-12-06",
        delineation_confidence="PARTIAL",
        delineation_complete=True,
    )
    finding = add_finding(
        world,
        phase,
        contaminant_code="ARSENIC",
        media="GROUNDWATER",
        sample_location_code=location_code,
        max_concentration_ugl=max_concentration_ugl,
        screening_level_ugl=5.0,
        delineated=True,
    )
    submit_phase(world, phase)
    review_phase(world, phase, "APPROVE")
    return phase, finding


def _plan_on(world, phase):
    """File the canonical six cost lines against one specific basis phase."""
    enrollment = world.read_enrollment()
    return add_plan(
        world,
        basis_assessment_phase_id=phase["id"],
        expected_vcp_enrollment_version=enrollment["version"],
    )


def _two_plans_across_the_adder_threshold(api):
    """Two identical remedies whose basis phases differ by one hundredth of a factor."""
    world = stage_enrolled(api)
    phase_high, finding_high = _partial_basis_phase(world, "MW-07", 50.0)
    phase_low, finding_low = _partial_basis_phase(world, "MW-08", 49.95)
    plan_high = _plan_on(world, phase_high)
    plan_low = _plan_on(world, phase_low)
    return world, (plan_high, finding_high), (plan_low, finding_low)


def test_an_exceedance_factor_of_exactly_ten_earns_the_five_point_adder(api):
    """
    A plume exactly an order of magnitude above screening reserves the extra five points.

    "A five-percentage-point adder is applied on top when that same basis phase's
    `max_exceedance_factor` is greater than or equal to 10.0, and no adder is applied when
    it is below 10.0 — a plume an order of magnitude above screening levels earns extra
    reserve."

    Design: Difficulty/boundary_precision_check/contingency_adder_at_exactly_ten_exceedance_factor
    """
    world, (plan_high, finding_high), _low = _two_plans_across_the_adder_threshold(api)
    assert_number(finding_high["exceedance_factor"], "10.00", "exceedance_factor")

    plan = world.read_plan(plan_high)
    assert_number(plan["contingency_pct"], "0.25", "contingency_pct")
    assert_fields(
        plan,
        direct_cost_cents=DIRECT_COST_CENTS,
        escalation_cents=ESCALATION_CENTS,
        contingency_cents=ADDER_CONTINGENCY_CENTS,
        oversight_cents=OVERSIGHT_CENTS,
        total_estimate_cents=ADDER_TOTAL_CENTS,
        total_funding_need_cents=ADDER_TOTAL_CENTS,
    )


def test_an_exceedance_factor_one_hundredth_below_ten_earns_nothing(api):
    """
    Nine point nine nine takes the bare twenty percent the confidence tier allows.

    "A `SCREENING` confidence sets the base rate at 35 percent, `PARTIAL` at 20 percent,
    and `FULL` at 10 percent."

    Design: Difficulty/boundary_precision_check/contingency_adder_at_exactly_ten_exceedance_factor
    """
    world, _high, (plan_low, finding_low) = _two_plans_across_the_adder_threshold(api)
    assert_number(finding_low["exceedance_factor"], "9.99", "exceedance_factor")

    plan = world.read_plan(plan_low)
    assert_number(plan["contingency_pct"], "0.20", "contingency_pct")
    assert_fields(
        plan,
        direct_cost_cents=DIRECT_COST_CENTS,
        escalation_cents=ESCALATION_CENTS,
        contingency_cents=PLAIN_CONTINGENCY_CENTS,
        oversight_cents=OVERSIGHT_CENTS,
        total_estimate_cents=PLAIN_TOTAL_CENTS,
        total_funding_need_cents=PLAIN_TOTAL_CENTS,
    )


def test_the_two_remedies_differ_only_by_the_adder_and_survive_resubmission(api):
    """
    Identical lines, identical escalation and oversight, and the whole gap is contingency.

    "`contingency_cents` is the sum of `direct_cost_cents` and `escalation_cents`,
    multiplied by `contingency_pct`, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/contingency_adder_at_exactly_ten_exceedance_factor
    """
    world, (plan_high, _fh), (plan_low, _fl) = _two_plans_across_the_adder_threshold(api)

    high = world.read_plan(plan_high)
    low = world.read_plan(plan_low)
    assert high["direct_cost_cents"] == low["direct_cost_cents"]
    assert high["escalation_cents"] == low["escalation_cents"]
    assert high["oversight_cents"] == low["oversight_cents"]
    assert (
        high["contingency_cents"] - low["contingency_cents"] == ADDER_DELTA_CENTS
    ), "the adder is the only difference between the two contingency reserves"
    assert (
        high["total_estimate_cents"] - low["total_estimate_cents"] == ADDER_DELTA_CENTS
    ), "and it carries straight through to the two totals"

    resubmitted = submit_plan(world, plan_high)
    assert_number(resubmitted["contingency_pct"], "0.25", "contingency_pct")
    assert_fields(
        resubmitted,
        contingency_cents=ADDER_CONTINGENCY_CENTS,
        total_estimate_cents=ADDER_TOTAL_CENTS,
    )


# ─── monitoring_result_equal_to_goal_extends_streak_one_cent_over_resets ─────────

RESTRICTED_GOAL_UGL = "250.00"


def _three_of_four_results_filed(api):
    """
    Four scheduled quarters with the first, third and fourth reported compliant.

    The second quarter is deliberately left open, so the boundary result has to be
    inserted into the middle of the chronological sequence rather than appended to it.
    """
    world = stage_assessed(api)
    stage_goals(world)
    events = schedule_attainment_events(world, world.goal_restricted)
    set_clock(world.api, "2027-06-01T00:00:00Z")
    file_result(world, events[0], 240.0)
    file_result(world, events[2], 245.0)
    file_result(world, events[3], 200.0)
    return world, events


def _late_boundary_event(world):
    """A fifth quarter sampled after the four, reserved on a window of its own."""
    return add_event(
        world,
        cleanup_goal_id=world.goal_restricted["id"],
        monitoring_period_code="2027-M05B",
        sample_date="2027-05-20",
        window_start="2027-05-16T00:00:00Z",
        window_end="2027-05-30T00:00:00Z",
    )


def test_a_result_exactly_equal_to_the_goal_is_compliant(api):
    """
    Two hundred and fifty against a goal of two hundred and fifty passes.

    "On filing, `result_status` is derived: it becomes `COMPLIANT` when the reported
    `result_value_ugl` is less than or equal to the referenced goal's `goal_ugl` — the
    comparison is inclusive, so a result exactly equal to the goal is compliant — and
    `EXCEEDANCE` otherwise."

    Design: Difficulty/boundary_precision_check/monitoring_result_equal_to_goal_extends_streak_one_cent_over_resets
    """
    world, events = _three_of_four_results_filed(api)
    goal = world.read_goal(world.goal_restricted)
    assert_number(goal["goal_ugl"], RESTRICTED_GOAL_UGL, "goal_ugl")
    assert_fields(goal, compliant_streak=3, attainment_status="NOT_ATTAINED")

    reported = file_result(world, events[1], 250.0)
    assert_fields(reported, status="REPORTED", result_status="COMPLIANT")
    assert_number(reported["result_value_ugl"], 250.0, "result_value_ugl")


def test_the_boundary_result_completes_the_four_quarter_streak(api):
    """
    Inserted in the middle of the sequence, it takes the running count to four.

    "The final value of that running count is stored as `compliant_streak`, and
    `attainment_status` becomes `ATTAINED` when `compliant_streak` is at least 4 — four
    consecutive compliant sampling results — and `NOT_ATTAINED` otherwise."

    Design: Difficulty/boundary_precision_check/monitoring_result_equal_to_goal_extends_streak_one_cent_over_resets
    """
    world, events = _three_of_four_results_filed(api)

    file_result(world, events[1], 250.0)

    goal = world.read_goal(world.goal_restricted)
    assert_fields(goal, compliant_streak=4, attainment_status="ATTAINED")
    assert_number(goal["goal_ugl"], RESTRICTED_GOAL_UGL, "goal_ugl")
    assert_fields(
        world.read_goal(world.goal_unrestricted),
        compliant_streak=0,
        attainment_status="NOT_ATTAINED",
    )


def test_one_hundredth_above_the_same_goal_resets_the_streak_to_zero(api):
    """
    A single cent over the target undoes four quarters of compliance.

    "Walking that sequence from the beginning, a running count is incremented by 1 for each
    event whose `result_value_ugl` is less than or equal to the goal's `goal_ugl`, and reset
    to zero for each event that exceeds it."

    Design: Difficulty/boundary_precision_check/monitoring_result_equal_to_goal_extends_streak_one_cent_over_resets
    """
    world, events = _three_of_four_results_filed(api)
    file_result(world, events[1], 250.0)

    late = _late_boundary_event(world)
    reported = file_result(world, late, 250.01)
    assert_fields(reported, status="REPORTED", result_status="EXCEEDANCE")

    goal = world.read_goal(world.goal_restricted)
    assert_fields(goal, compliant_streak=0, attainment_status="NOT_ATTAINED")
    assert_number(goal["goal_ugl"], RESTRICTED_GOAL_UGL, "goal_ugl")


# ─── aai_report_exactly_one_hundred_eighty_days_old_is_accepted ──────────────────

REFERENCE_DATE = "2026-10-15"
REPORT_AT_THE_LIMIT = "2026-04-18"
REPORT_ONE_DAY_TOO_OLD = "2026-04-17"
EXPIRY_AT_THE_LIMIT = "2027-04-18"


def _two_parcels_across_the_lookback_limit(api):
    """
    Two sibling parcels whose inquiry reports differ by exactly one day.

    Both are still under contract against the same planned closing date, so the reference
    date the recency window is measured from is identical on each.
    """
    world = stage_registry(api)
    stage_site(world)
    stage_protection(world)
    stage_phase_i(
        world,
        field_start_date="2026-03-01",
        field_end_date="2026-04-10",
        aai_report_date=REPORT_AT_THE_LIMIT,
    )
    protection_a, phase_a = world.protection, world.phase_i

    site_b = add_site(world, site_name="Menomonee Foundry Parcel", acreage=6.8)
    stage_protection(world, site=site_b)
    protection_b = world.protection
    phase_b = add_assessment_phase(
        world,
        site_id=site_b["id"],
        phase_type="PHASE_I",
        field_start_date="2026-03-01",
        field_end_date="2026-04-10",
        aai_report_date=REPORT_ONE_DAY_TOO_OLD,
    )
    add_finding(
        world,
        phase_b,
        contaminant_code="LEAD",
        media="SOIL",
        sample_location_code="SB-04",
        max_concentration_ugl=900.0,
        screening_level_ugl=400.0,
    )
    submit_phase(world, phase_b)
    review_phase(world, phase_b, "APPROVE")
    return world, (protection_a, phase_a), (protection_b, phase_b), site_b


def _complete_inquiry(world, protection, phase):
    """Nominate one approved phase as a protection's inquiry record."""
    return world.api.complete_inquiry(
        protection["id"], inquiry_completion_payload(phase["id"]), world.consult_headers
    )


def test_a_report_exactly_one_hundred_eighty_days_old_is_accepted(api):
    """
    The inquiry lands on the last day the lookback window allows.

    "On acceptance the server stores `aai_phase_id` and `aai_report_date`, derives
    `aai_expires_on` as the `aai_report_date` advanced by 365 days, recomputes
    `bfpp_status`, and increments the protection's `version` by 1."

    Design: Difficulty/boundary_precision_check/aai_report_exactly_one_hundred_eighty_days_old_is_accepted
    """
    world, (protection_a, phase_a), _b, _site_b = _two_parcels_across_the_lookback_limit(api)

    accepted = get_success_data(_complete_inquiry(world, protection_a, phase_a))
    assert_fields(
        accepted,
        inquiry_state="AAI_COMPLETE",
        aai_phase_id=phase_a["id"],
        aai_report_date=REPORT_AT_THE_LIMIT,
        aai_expires_on=EXPIRY_AT_THE_LIMIT,
        bfpp_status="NOT_ESTABLISHED",
        obligation_state="OBLIGATIONS_NONE",
        obligations_total_weight=0,
    )
    assert_number(accepted["compliance_pct"], "1.0000", "compliance_pct")


def test_a_report_one_hundred_eighty_one_days_old_is_refused(api):
    """
    One day further back is outside the window and the completion is refused.

    "And the report must be recent: the number of days between the reference date and the
    `aai_report_date` must be at most 180, counted inclusively, so a report exactly 180
    days old is accepted and one 181 days old is refused with `ERR_AAI_REPORT_STALE`."

    Design: Difficulty/boundary_precision_check/aai_report_exactly_one_hundred_eighty_days_old_is_accepted
    """
    world, (protection_a, phase_a), (protection_b, phase_b), _site_b = (
        _two_parcels_across_the_lookback_limit(api)
    )
    get_success_data(_complete_inquiry(world, protection_a, phase_a))

    response = _complete_inquiry(world, protection_b, phase_b)
    validate_error(response, ERR_AAI_REPORT_STALE, 422)


def test_the_stale_report_still_precedes_the_planned_closing_date(api):
    """
    The refusal is the recency rule's, not the after-acquisition rule's, and B is untouched.

    "The `aai_report_date` must fall on or before the acquisition reference date — the
    actual `acquisition_date` when the parcel is `ACQUIRED`, otherwise the
    `planned_acquisition_date` — because an inquiry completed after taking title cannot
    support the defence; a later date is `ERR_AAI_AFTER_ACQUISITION`."

    Design: Difficulty/boundary_precision_check/aai_report_exactly_one_hundred_eighty_days_old_is_accepted
    """
    world, _a, (protection_b, phase_b), site_b = _two_parcels_across_the_lookback_limit(api)
    assert_fields(site_b, acquisition_status="UNDER_CONTRACT")
    assert_fields(site_b, planned_acquisition_date=REFERENCE_DATE)
    assert phase_b["aai_report_date"] < REFERENCE_DATE, (
        "the report predates the reference date, so only the recency rule can refuse it"
    )

    _complete_inquiry(world, protection_b, phase_b)

    unchanged = get_success_data(
        world.api.get_liability_protection(protection_b["id"], world.redev_headers)
    )
    assert_fields(
        unchanged,
        inquiry_state="AAI_PENDING",
        aai_phase_id=None,
        aai_report_date=None,
        aai_expires_on=None,
        bfpp_status="NOT_ESTABLISHED",
    )
