"""Compensating actions and the quantities they conserve: the hundred-point pay
mix restored by an exactly reversed reallocation, and the realized dollars of a
clawed-back award restored by reversing its recovery.
"""

from test_helpers import (
    CONSULTANT,
    ApiErrorId,
    api_client,
    assert_mix_components_in_bounds,
    assert_money,
    assert_pay_mix_totals_one_hundred,
    assert_program_pay_totals,
    assert_ratio,
    assert_recovery_conserves_realized_dollars,
    assert_screen_stale_keeps_last_scores,
    assert_version_incremented,
    create_screen,
    mix_reallocation_payload,
    read_award,
    read_determination,
    read_metric,
    read_pay_program,
    read_restatement_event,
    read_screen,
    reallocate_mix,
    recover_determination,
    reverse_recovery,
    setup_pay_program,
    setup_restatement_with_determination,
    validate_error,
)


# ---------------------------------------------------------------------------
# Fixtures built from scratch inside each test
# ---------------------------------------------------------------------------
def _draft_program_with_a_current_iss_screen():
    """A DRAFT program on the 15/25/60 mix, with one SCREENED ISS screen.

    Reallocation is only available while the program is DRAFT. The screen is run
    while the program has no awards, so its alignment gap is null: the ISS score
    is 0.50 of 50.00 plus 0.30 of the 39.00 mix component, i.e. 36.70.
    """
    env = setup_pay_program(approve=False)
    env["screens"]["ISS"] = create_screen(env["program"]["id"], "ISS")
    return env


# ===========================================================================
# The hundred-point mix and its six derived fields
# ===========================================================================
def test_reversed_reallocation_restores_every_component_and_derived_field():
    """Ten points out of salary and back again returns the program to its prior sizing.

    "The hundred-point total is a conserved quantity: it holds before and after
    every reallocation, and applying a reallocation and then its exact reverse
    restores each component to its prior value."

    Design: Difficulty/compensating_invariant/mix_reallocation_round_trip_conserves_hundred_points_and_restores_every_derived_field
    """
    env = _draft_program_with_a_current_iss_screen()
    program_id = env["program"]["id"]

    baseline = read_pay_program(program_id)
    assert_pay_mix_totals_one_hundred(baseline)
    assert_mix_components_in_bounds(baseline)
    assert_money(baseline["salary_pct"], 15.00, "salary_pct")
    assert_money(baseline["sti_pct"], 25.00, "sti_pct")
    assert_money(baseline["lti_pct"], 60.00, "lti_pct")
    assert_money(baseline["performance_based_pct"], 61.00, "performance_based_pct")
    assert_ratio(baseline["benchmark_ratio"], 0.6250, "benchmark_ratio")
    assert baseline["lti_multiple"] == 4.0
    assert_money(baseline["lti_target_usd"], 12000000.00, "lti_target_usd")
    assert_money(baseline["target_tdc_usd"], 15000000.00, "target_tdc_usd")
    assert baseline["benchmark_posture"] == "ABOVE_MARKET"
    assert_money(baseline["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")

    forward = reallocate_mix(program_id, "SALARY", "LTI", 10.00, baseline["version"])
    assert_pay_mix_totals_one_hundred(forward)
    assert_mix_components_in_bounds(forward)
    assert_money(forward["salary_pct"], 5.00, "salary_pct")
    assert_money(forward["sti_pct"], 25.00, "sti_pct")
    assert_money(forward["lti_pct"], 70.00, "lti_pct")
    assert_money(forward["performance_based_pct"], 67.00, "performance_based_pct")
    assert_ratio(forward["benchmark_ratio"], 0.8333, "benchmark_ratio")
    assert forward["lti_multiple"] == 3.0
    assert_money(forward["lti_target_usd"], 9000000.00, "lti_target_usd")
    assert_money(forward["target_tdc_usd"], 12000000.00, "target_tdc_usd")
    assert forward["benchmark_posture"] == "ALIGNED"
    assert_money(forward["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")

    reverse = reallocate_mix(program_id, "LTI", "SALARY", 10.00, forward["version"])
    assert_pay_mix_totals_one_hundred(reverse)
    assert_mix_components_in_bounds(reverse)
    assert_money(reverse["salary_pct"], 15.00, "salary_pct")
    assert_money(reverse["sti_pct"], 25.00, "sti_pct")
    assert_money(reverse["lti_pct"], 60.00, "lti_pct")
    assert_money(reverse["performance_based_pct"], 61.00, "performance_based_pct")
    assert_ratio(reverse["benchmark_ratio"], 0.6250, "benchmark_ratio")
    assert reverse["lti_multiple"] == 4.0
    assert_money(reverse["lti_target_usd"], 12000000.00, "lti_target_usd")
    assert_money(reverse["target_tdc_usd"], 15000000.00, "target_tdc_usd")
    assert reverse["benchmark_posture"] == "ABOVE_MARKET"
    assert_money(reverse["fixed_leg_usd"], 3000000.00, "fixed_leg_usd")


def test_reversed_reallocation_neither_rewinds_the_version_nor_refreshes_the_screen():
    """The compensating leg is itself a reallocation, with a reallocation's side effects.

    "A successful reallocation re-runs the whole five-step target computation,
    increments the program's `version`, and marks every `SCREENED` screen of the
    program `STALE`."

    Design: Difficulty/compensating_invariant/mix_reallocation_round_trip_conserves_hundred_points_and_restores_every_derived_field
    """
    env = _draft_program_with_a_current_iss_screen()
    program_id = env["program"]["id"]
    screen_id = env["screens"]["ISS"]["id"]

    screen_before = read_screen(program_id, screen_id)
    assert screen_before["status"] == "SCREENED"
    assert_money(screen_before["concern_score"], 36.70, "concern_score")
    assert screen_before["concern_level"] == "MEDIUM"
    assert screen_before["recommendation"] == "FOR"

    baseline_version = env["program"]["version"]
    forward = reallocate_mix(program_id, "SALARY", "LTI", 10.00, baseline_version)
    assert_version_incremented(forward["version"], baseline_version)
    assert read_screen(program_id, screen_id)["status"] == "STALE"

    reverse = reallocate_mix(program_id, "LTI", "SALARY", 10.00, forward["version"])
    assert reverse["version"] == baseline_version + 2

    screen_after = read_screen(program_id, screen_id)
    assert_screen_stale_keeps_last_scores(screen_before, screen_after)
    assert_money(screen_after["concern_score"], 36.70, "concern_score")
    assert screen_after["concern_level"] == "MEDIUM"
    assert screen_after["recommendation"] == "FOR"


def test_replaying_the_reverse_leg_on_a_superseded_version_is_refused():
    """The version the reverse leg consumed cannot be used a second time.

    "Reallocating pay-mix points requires `expected_pay_program_version` to equal
    that `PayProgram` row's current `version`, failing with
    `ERR_STALE_PAY_PROGRAM_VERSION` (HTTP 412), because each reallocation
    supersedes the prior mix and a delta derived from a stale mix would shift
    different components than the client intended."

    Design: Difficulty/compensating_invariant/mix_reallocation_round_trip_conserves_hundred_points_and_restores_every_derived_field
    """
    env = _draft_program_with_a_current_iss_screen()
    program_id = env["program"]["id"]

    forward = reallocate_mix(program_id, "SALARY", "LTI", 10.00, env["program"]["version"])
    stale_version = forward["version"]
    reallocate_mix(program_id, "LTI", "SALARY", 10.00, stale_version)

    response = api_client.reallocate_pay_mix(
        program_id,
        mix_reallocation_payload("LTI", "SALARY", 10.00, stale_version),
        CONSULTANT,
    )
    validate_error(response, ApiErrorId.ERR_STALE_PAY_PROGRAM_VERSION, 412)

    unchanged = read_pay_program(program_id)
    assert_money(unchanged["salary_pct"], 15.00, "salary_pct")
    assert_money(unchanged["lti_pct"], 60.00, "lti_pct")
    assert_money(unchanged["target_tdc_usd"], 15000000.00, "target_tdc_usd")
    assert unchanged["version"] == stale_version + 1


# ===========================================================================
# Recovered dollars across the award, the event and the program
# ===========================================================================
def test_recovery_and_its_reversal_conserve_the_awards_realized_dollars():
    """Realized pay plus recovered pay is the same figure before, during and after.

    "The pair of actions conserves dollars: for every determination, the award's
    `realized_value_usd` added to the event's `recovered_total_usd` is identical
    before the recovery and after its reversal."

    Design: Difficulty/compensating_invariant/recovery_and_reversal_conserve_realized_dollars_across_award_event_and_program
    """
    env = setup_restatement_with_determination()
    company_id = env["issuer"]["id"]
    program_id = env["program"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    determination_id = env["determination"]["id"]

    award_before = read_award(award_id)
    event_before = read_restatement_event(company_id, env["restatement_event"]["id"])
    assert award_before["status"] == "VESTED"
    assert_money(award_before["realized_value_usd"], 2340000.00, "realized_value_usd")
    assert_money(event_before["recovered_total_usd"], 0.00, "recovered_total_usd")
    assert_recovery_conserves_realized_dollars(award_before, event_before, 2340000.00)
    assert_money(
        env["determination"]["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd"
    )

    recover_determination(determination_id)
    award_during = read_award(award_id)
    event_during = read_restatement_event(company_id, event_before["id"])
    assert award_during["status"] == "CLAWED_BACK"
    assert_money(award_during["realized_value_usd"], 1800000.00, "realized_value_usd")
    assert_money(event_during["recovered_total_usd"], 540000.00, "recovered_total_usd")
    assert event_during["status"] == "CLOSED"
    assert_recovery_conserves_realized_dollars(award_during, event_during, 2340000.00)

    reverse_recovery(determination_id)
    award_after = read_award(award_id)
    event_after = read_restatement_event(company_id, event_before["id"])
    assert award_after["status"] == "VESTED"
    assert_money(award_after["realized_value_usd"], 2340000.00, "realized_value_usd")
    assert_money(award_after["realizable_value_usd"], 2340000.00, "realizable_value_usd")
    assert_money(event_after["recovered_total_usd"], 0.00, "recovered_total_usd")
    assert_recovery_conserves_realized_dollars(award_after, event_after, 2340000.00)

    assert_program_pay_totals(read_pay_program(program_id), 2340000.00, 2340000.00)


def test_reversal_un_bubbles_the_event_out_of_closed_and_recovery_can_run_again():
    """Reversing the only child walks the parent back out of its terminal state.

    "The determination moves `RECOVERED → NOTICED` with `recovered_at` cleared;
    the owning event recomputes `recovered_total_usd` and, if it had already
    closed, reverts `CLOSED → RECOVERY_ORDERED`; the linked award moves
    `CLAWED_BACK → VESTED` with its `realized_value_usd` increased by the same
    `recoverable_amount_usd`, restoring exactly the pre-recovery figure; and the
    award's program recomputes `realized_pay_total_usd`,
    `realizable_pay_total_usd`, `pay_percentile_rank`, `degree_of_alignment` and
    `alignment_status`."

    Design: Difficulty/compensating_invariant/recovery_and_reversal_conserve_realized_dollars_across_award_event_and_program
    """
    env = setup_restatement_with_determination()
    company_id = env["issuer"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    event_id = env["restatement_event"]["id"]
    determination_id = env["determination"]["id"]

    recovered = recover_determination(determination_id)
    assert recovered["status"] == "RECOVERED"
    assert recovered["recovered_at"] is not None
    assert read_restatement_event(company_id, event_id)["status"] == "CLOSED"

    reversed_row = reverse_recovery(determination_id)
    assert reversed_row["status"] == "NOTICED"
    assert reversed_row["recovered_at"] is None
    assert reversed_row["acknowledged_at"] is not None
    assert reversed_row["acknowledged_by_user_id"] == env["executives"]["CEO"]["id"]
    assert_version_incremented(reversed_row["version"], recovered["version"])

    event_after = read_restatement_event(company_id, event_id)
    assert event_after["status"] == "RECOVERY_ORDERED"
    assert event_after["determination_count"] == 1
    assert_money(event_after["recoverable_total_usd"], 540000.00, "recoverable_total_usd")
    assert_money(event_after["recovered_total_usd"], 0.00, "recovered_total_usd")

    re_recovered = recover_determination(determination_id)
    assert re_recovered["status"] == "RECOVERED"
    event_final = read_restatement_event(company_id, event_id)
    assert event_final["status"] == "CLOSED"
    assert_recovery_conserves_realized_dollars(read_award(award_id), event_final, 2340000.00)


def test_reversing_a_recovery_leaves_the_restated_metric_restated():
    """The reversal undoes the money, not the audit trail the analysis wrote.

    "Each referenced metric is re-run through the payout curve of §3.4 using its
    restated achievement, and the result is stored as `restated_payout_factor_pct`
    while the metric moves `CERTIFIED → RESTATED`; the metric's original
    `payout_factor_pct` and `original_payout_factor_pct` are left untouched,
    because the audit trail must keep both readings."

    Design: Difficulty/compensating_invariant/recovery_and_reversal_conserve_realized_dollars_across_award_event_and_program
    """
    env = setup_restatement_with_determination()
    program_id = env["program"]["id"]
    determination_id = env["determination"]["id"]
    restated_metric_id = env["metrics"][0]["id"]
    untouched_metric_id = env["metrics"][1]["id"]

    recover_determination(determination_id)
    reverse_recovery(determination_id)

    restated = read_metric(program_id, restated_metric_id)
    assert restated["status"] == "RESTATED"
    assert_money(restated["payout_factor_pct"], 150.00, "payout_factor_pct")
    assert_money(restated["original_payout_factor_pct"], 150.00, "original_payout_factor_pct")
    assert_money(restated["restated_payout_factor_pct"], 100.00, "restated_payout_factor_pct")

    unnamed = read_metric(program_id, untouched_metric_id)
    assert unnamed["status"] == "CERTIFIED"
    assert unnamed["restated_payout_factor_pct"] is None

    determination = read_determination(determination_id)
    assert_money(determination["original_factor_pct"], 130.00, "original_factor_pct")
    assert_money(determination["restated_factor_pct"], 100.00, "restated_factor_pct")
    assert_money(determination["restated_amount_usd"], 1800000.00, "restated_amount_usd")
    assert_money(determination["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd")
