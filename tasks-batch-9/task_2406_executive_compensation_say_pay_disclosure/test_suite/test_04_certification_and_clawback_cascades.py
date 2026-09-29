"""Multi-level propagation out of a metric certification and out of a clawback recovery.

Certifying the last metric of a vehicle re-derives the vehicle's awards, then the
program's realized and realizable totals and alignment verdict, and finally
withdraws every current proxy-advisor screen's claim to currency. Executing a
clawback recovery propagates through a different chain — the determination, the
award it targets, the restatement event's recovered total, the program's totals
and again the program's screens — and reversing it puts every dollar back.
"""

from test_helpers import (
    assert_alignment_band,
    assert_money,
    assert_program_pay_totals,
    assert_recovery_conserves_realized_dollars,
    assert_screen_stale_keeps_last_scores,
    certify_metric,
    create_screen,
    read_award,
    read_determination,
    read_metric,
    read_pay_program,
    read_restatement_event,
    read_screen,
    recover_determination,
    rerun_screen,
    reverse_recovery,
    setup_award,
    setup_pay_program,
    setup_restatement_with_determination,
    setup_vested_annual_incentive_award,
    submit_metric_result,
)


# ===========================================================================
# Certifying the last metric of a vehicle
# ===========================================================================
def _program_one_certification_from_a_full_vehicle():
    """Two ANNUAL_INCENTIVE metrics, two GRANTED awards, two current screens.

    ADJ_EPS is already certified at an achievement of 5.50 and COST_RATIO has
    submitted 0.63, so a single certification completes the vehicle.
    """
    env = setup_pay_program(metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"))
    program_id = env["program"]["id"]
    env = setup_award(env, "annual_incentive", "ANNUAL_INCENTIVE")
    env = setup_award(env, "psu", "LONG_TERM_PSU")
    env["screens"]["ISS"] = create_screen(program_id, "ISS")
    env["screens"]["GLASS_LEWIS"] = create_screen(program_id, "GLASS_LEWIS")
    first, second = env["metrics"]
    submit_metric_result(first["id"], 5.50)
    certify_metric(first["id"])
    submit_metric_result(second["id"], 0.63)
    return env


def test_certifying_the_last_vehicle_metric_cascades_through_to_screen_staleness():
    """One certification re-derives the award, the program and both screens.

    "At the first level the factor is computed as above, snapshotted into `original_payout_factor_pct` — which is immutable thereafter — the certifying chair is recorded as `certified_by_user_id`, the status becomes `CERTIFIED` and the metric's `version` increments."

    "At the second level, caused by the first: if *every* metric of this program sharing this metric's `vehicle` is now certified, each award of that program with the same vehicle recomputes its `certified_factor_pct` and `earned_amount_usd`, then its `realized_value_usd` and `realizable_value_usd`."

    "At the third level, caused by the second, the owning program recomputes `realized_pay_total_usd`, `realizable_pay_total_usd`, `pay_percentile_rank`, `degree_of_alignment` and `alignment_status`."

    "Whenever anything the proxy advisors care about changes on a pay program — its `realized_pay_total_usd`, `realizable_pay_total_usd`, `pay_percentile_rank`, `degree_of_alignment`, `alignment_status`, `target_tdc_usd`, `performance_based_pct`, `outreach_coverage_pct` or `vote_status` is recomputed to a new value — every `ProxyAdvisorScreen` of that program that is currently `SCREENED` moves to `STALE`."

    Design: Difficulty/transitive_cascade/certify_last_metric_cascades_five_levels_to_screen_staleness
    """
    env = _program_one_certification_from_a_full_vehicle()
    program_id = env["program"]["id"]
    annual_id = env["awards"]["annual_incentive"]["id"]
    psu_id = env["awards"]["psu"]["id"]
    iss_id = env["screens"]["ISS"]["id"]
    glass_lewis_id = env["screens"]["GLASS_LEWIS"]["id"]
    pending_metric = env["metrics"][1]

    # Nothing downstream has moved yet: the vehicle is not fully certified, so
    # the award carries no factor and both screens are still current.
    assert read_award(annual_id)["certified_factor_pct"] is None
    assert read_screen(program_id, iss_id)["status"] == "SCREENED"
    assert read_screen(program_id, glass_lewis_id)["status"] == "SCREENED"
    assert_program_pay_totals(read_pay_program(program_id), 0.00, 6800000.00)

    certified = certify_metric(pending_metric["id"])

    # The metric itself: 0.63 sits at or below the 0.65 target of a
    # LOWER_IS_BETTER / STEP curve, so the target payout percentage applies.
    assert certified["status"] == "CERTIFIED"
    assert_money(certified["payout_factor_pct"], 100.00, "payout_factor_pct")
    assert_money(
        certified["original_payout_factor_pct"], 100.00, "original_payout_factor_pct"
    )

    # The awards of the now-complete ANNUAL_INCENTIVE vehicle: 150.00 at weight
    # 60.00 contributes 90.00 and 100.00 at weight 40.00 contributes 40.00.
    annual = read_award(annual_id)
    assert_money(annual["certified_factor_pct"], 130.00, "certified_factor_pct")
    assert_money(annual["earned_amount_usd"], 2340000.00, "earned_amount_usd")
    assert_money(annual["realized_value_usd"], 0.00, "realized_value_usd")
    assert_money(annual["realizable_value_usd"], 2340000.00, "realizable_value_usd")

    # The LONG_TERM_PSU award has no metric of its own vehicle, so it keeps a
    # null factor and marks 100,000 units to the 50.00 share price at target.
    psu = read_award(psu_id)
    assert psu["certified_factor_pct"] is None
    assert_money(psu["realizable_value_usd"], 5000000.00, "realizable_value_usd")

    program = read_pay_program(program_id)
    assert_program_pay_totals(program, 0.00, 7340000.00)
    assert_money(program["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(program["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert program["alignment_status"] == "ALIGNED"
    assert_alignment_band(program)

    assert read_screen(program_id, iss_id)["status"] == "STALE"
    assert read_screen(program_id, glass_lewis_id)["status"] == "STALE"


def test_screens_staled_by_a_certification_keep_their_last_computed_scores():
    """Going STALE withdraws currency without erasing the advisor's numbers.

    "A screen going `STALE` keeps its last computed `concern_score`, `concern_level` and `recommendation` verbatim: the numbers are preserved as a historical record, only their claim to currency is withdrawn."

    Design: Difficulty/transitive_cascade/certify_last_metric_cascades_five_levels_to_screen_staleness
    """
    env = _program_one_certification_from_a_full_vehicle()
    program_id = env["program"]["id"]
    pending_metric = env["metrics"][1]

    iss_before = read_screen(program_id, env["screens"]["ISS"]["id"])
    glass_lewis_before = read_screen(program_id, env["screens"]["GLASS_LEWIS"]["id"])
    assert iss_before["status"] == "SCREENED"
    assert glass_lewis_before["status"] == "SCREENED"

    certify_metric(pending_metric["id"])

    assert_screen_stale_keeps_last_scores(
        iss_before, read_screen(program_id, iss_before["id"])
    )
    assert_screen_stale_keeps_last_scores(
        glass_lewis_before, read_screen(program_id, glass_lewis_before["id"])
    )


def test_partly_certified_vehicle_leaves_the_award_factor_null_and_the_screen_current():
    """Until every metric of the vehicle is certified the chain does not start.

    "If the set is non-empty but not every member of it is in `CERTIFIED` or `RESTATED`, the factor is likewise null and the computation stops."

    Design: Difficulty/transitive_cascade/certify_last_metric_cascades_five_levels_to_screen_staleness
    """
    env = setup_pay_program(metric_curves=("ADJ_EPS_LINEAR", "COST_RATIO_STEP"))
    program_id = env["program"]["id"]
    env = setup_award(env, "annual_incentive", "ANNUAL_INCENTIVE")
    annual_id = env["awards"]["annual_incentive"]["id"]
    env["screens"]["ISS"] = create_screen(program_id, "ISS")
    iss_id = env["screens"]["ISS"]["id"]
    first, second = env["metrics"]
    submit_metric_result(first["id"], 5.50)
    submit_metric_result(second["id"], 0.63)

    certify_metric(first["id"])

    assert_money(
        read_metric(program_id, first["id"])["payout_factor_pct"],
        150.00,
        "payout_factor_pct",
    )
    assert read_metric(program_id, second["id"])["status"] == "RESULT_SUBMITTED"

    annual = read_award(annual_id)
    assert annual["certified_factor_pct"] is None, (
        "one uncertified sibling metric leaves the vehicle factor null"
    )
    assert annual["earned_amount_usd"] is None
    # The forward-looking valuation falls back to assumed target performance.
    assert_money(annual["realizable_value_usd"], 1800000.00, "realizable_value_usd")

    assert read_screen(program_id, iss_id)["status"] == "SCREENED", (
        "no program number was recomputed to a new value, so the screen stays current"
    )


# ===========================================================================
# Executing and reversing a clawback recovery
# ===========================================================================
def _noticed_determination_with_a_current_screen():
    """A VESTED annual-incentive award, a current ISS screen and a NOTICED row.

    Restating ADJ_EPS from 5.50 down to 5.00 drops the metric factor to 100.00
    and the award's vehicle factor from 130.00 to 100.00, so the determination
    seeks 540,000.00 of the 2,340,000.00 already delivered.
    """
    env = setup_vested_annual_incentive_award()
    env["screens"]["ISS"] = create_screen(env["program"]["id"], "ISS")
    env = setup_restatement_with_determination(env=env)
    # Re-run the screen so it is current again immediately before the recovery.
    env["screens"]["ISS"] = rerun_screen(env["screens"]["ISS"]["id"])
    return env


def test_executing_clawback_recovery_cascades_from_determination_to_screen():
    """Recovery moves the determination, the award, the event, the program, the screen.

    "First, the determination moves `NOTICED → RECOVERED`, `recovered_at` is stamped with the current logical time, the owning event recomputes `recovered_total_usd` as the sum of the recoverable amounts of its `RECOVERED` determinations, and — when every determination of the event has reached `RECOVERED` — the event itself moves `RECOVERY_ORDERED → CLOSED`."

    "Second, caused by the first, the linked award moves `VESTED → CLAWED_BACK` with its `realized_value_usd` reduced by the determination's `recoverable_amount_usd` and its `realizable_value_usd` set equal to the new realized figure."

    "Third, caused by the second, the award's program recomputes `realized_pay_total_usd`, `realizable_pay_total_usd`, `pay_percentile_rank`, `degree_of_alignment` and `alignment_status`."

    "Fourth, caused by the third, every `SCREENED` screen of that program becomes `STALE`."

    Design: Difficulty/transitive_cascade/clawback_recovery_cascades_five_levels_from_determination_to_screen
    """
    env = _noticed_determination_with_a_current_screen()
    issuer_id = env["issuer"]["id"]
    program_id = env["program"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    event_id = env["restatement_event"]["id"]
    determination_id = env["determination"]["id"]
    iss_id = env["screens"]["ISS"]["id"]

    before_determination = read_determination(determination_id)
    assert before_determination["status"] == "NOTICED"
    assert_money(before_determination["original_factor_pct"], 130.00, "original_factor_pct")
    assert_money(before_determination["restated_factor_pct"], 100.00, "restated_factor_pct")
    assert_money(before_determination["restated_amount_usd"], 1800000.00, "restated_amount_usd")
    assert_money(
        before_determination["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd"
    )

    before_event = read_restatement_event(issuer_id, event_id)
    assert before_event["status"] == "RECOVERY_ORDERED"
    assert before_event["determination_count"] == 1
    assert_money(before_event["recoverable_total_usd"], 540000.00, "recoverable_total_usd")
    assert_money(before_event["recovered_total_usd"], 0.00, "recovered_total_usd")

    assert_money(read_award(award_id)["realized_value_usd"], 2340000.00, "realized_value_usd")
    assert read_screen(program_id, iss_id)["status"] == "SCREENED"

    recovered = recover_determination(determination_id)

    assert recovered["status"] == "RECOVERED"
    assert recovered["recovered_at"] is not None

    award = read_award(award_id)
    assert award["status"] == "CLAWED_BACK"
    assert_money(award["realized_value_usd"], 1800000.00, "realized_value_usd")
    assert_money(award["realizable_value_usd"], 1800000.00, "realizable_value_usd")

    event = read_restatement_event(issuer_id, event_id)
    assert_money(event["recovered_total_usd"], 540000.00, "recovered_total_usd")
    assert event["status"] == "CLOSED"

    program = read_pay_program(program_id)
    assert_program_pay_totals(program, 1800000.00, 1800000.00)
    assert_money(program["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(program["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert program["alignment_status"] == "ALIGNED"
    assert_alignment_band(program)

    assert read_screen(program_id, iss_id)["status"] == "STALE"

    # The audit trail keeps both readings of the restated metric.
    restated_metric = read_metric(program_id, env["metrics"][0]["id"])
    assert restated_metric["status"] == "RESTATED"
    assert_money(
        restated_metric["restated_payout_factor_pct"], 100.00, "restated_payout_factor_pct"
    )
    assert_money(
        restated_metric["original_payout_factor_pct"], 150.00, "original_payout_factor_pct"
    )


def test_reversing_the_recovery_restores_every_value_the_cascade_moved():
    """The compensating action puts the award, the event and the program back.

    "The determination moves `RECOVERED → NOTICED` with `recovered_at` cleared; the owning event recomputes `recovered_total_usd` and, if it had already closed, reverts `CLOSED → RECOVERY_ORDERED`; the linked award moves `CLAWED_BACK → VESTED` with its `realized_value_usd` increased by the same `recoverable_amount_usd`, restoring exactly the pre-recovery figure; and the award's program recomputes `realized_pay_total_usd`, `realizable_pay_total_usd`, `pay_percentile_rank`, `degree_of_alignment` and `alignment_status`."

    "The pair of actions conserves dollars: for every determination, the award's `realized_value_usd` added to the event's `recovered_total_usd` is identical before the recovery and after its reversal."

    Design: Difficulty/transitive_cascade/clawback_recovery_cascades_five_levels_from_determination_to_screen
    """
    env = setup_vested_annual_incentive_award()
    env = setup_restatement_with_determination(env=env, recover=True)
    issuer_id = env["issuer"]["id"]
    program_id = env["program"]["id"]
    award_id = env["awards"]["annual_incentive"]["id"]
    event_id = env["restatement_event"]["id"]
    determination_id = env["determination"]["id"]

    recovered_award = read_award(award_id)
    recovered_event = read_restatement_event(issuer_id, event_id)
    assert recovered_award["status"] == "CLAWED_BACK"
    assert recovered_event["status"] == "CLOSED"
    assert_recovery_conserves_realized_dollars(
        recovered_award, recovered_event, 2340000.00
    )

    reversed_determination = reverse_recovery(determination_id)

    assert reversed_determination["status"] == "NOTICED"
    assert reversed_determination["recovered_at"] is None
    assert_money(
        reversed_determination["recoverable_amount_usd"], 540000.00, "recoverable_amount_usd"
    )

    award = read_award(award_id)
    assert award["status"] == "VESTED"
    assert_money(award["realized_value_usd"], 2340000.00, "realized_value_usd")
    assert_money(award["realizable_value_usd"], 2340000.00, "realizable_value_usd")

    event = read_restatement_event(issuer_id, event_id)
    assert event["status"] == "RECOVERY_ORDERED"
    assert_money(event["recovered_total_usd"], 0.00, "recovered_total_usd")
    assert_money(event["recoverable_total_usd"], 540000.00, "recoverable_total_usd")

    assert_recovery_conserves_realized_dollars(award, event, 2340000.00)

    program = read_pay_program(program_id)
    assert_program_pay_totals(program, 2340000.00, 2340000.00)
    assert_money(program["pay_percentile_rank"], 0.00, "pay_percentile_rank")
    assert_money(program["degree_of_alignment"], 30.00, "degree_of_alignment")
    assert program["alignment_status"] == "ALIGNED"

    assert read_determination(determination_id)["status"] == "NOTICED"
