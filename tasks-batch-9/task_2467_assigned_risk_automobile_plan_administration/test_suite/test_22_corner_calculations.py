"""Corner calculations: rounding order, apportionment remainders and ledger deltas.

Every figure asserted here is re-derived from the PRD's own arithmetic — per-line
rounding before summation, the expense rate read from the pre-charge premium,
car-year exposure rounded to 4 decimal places per policy before aggregation, and
credit and variance carried to 1 decimal place.
"""
from test_helpers import (
    ATLAS,
    BEACON,
    DEPOSIT_FLOOR_CENTS,
    T02_ADULT_CLEAN,
    accept_assignment,
    acknowledge_claim,
    api_client,
    assert_deposit_ledger_conserved,
    assert_posture_ladder,
    assert_premium_lines_sum_to_final_premium,
    assert_quota_reconciliation,
    assert_quota_variance,
    assert_targets_sum_to_assignable_total,
    assert_total_annual_charge,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    certify_application,
    create_applicant_with_vehicle,
    create_claim_closure_payload,
    create_quota_reconciliation_payload,
    create_reclassification_payload,
    create_voluntary_exit_payload,
    file_two_market_rejections,
    issue_policy,
    make_plan_administrator_headers,
    make_servicing_carrier_headers,
    place_and_accept,
    read_applicant,
    read_application,
    read_assignment,
    read_assignment_cycle,
    read_carrier,
    read_plan_period,
    read_policy,
    read_quota_reconciliation,
    record_deposit,
    report_claim,
    run_cycle,
    schedule_cycle,
    set_clock,
    setup_policy_in_force,
    submit_application,
    validate_error,
    validate_success,
    verify_mvr,
)

ADMIN_HEADERS = make_plan_administrator_headers()

# Atlas writes T02 only and Beacon T03 only, so the garaging territory of the
# vehicle — not the ranking — decides which carrier a risk can reach.
ATLAS_T02_ONLY = dict(ATLAS, licensed_territories=["T02"])
BEACON_T03_ONLY = dict(BEACON, licensed_territories=["T03"])

# The PRD's own tie-break illustration: 500 against 1500 basis points.
SMALL_SHARE_CARRIER = dict(ATLAS, voluntary_market_share_bps=500, licensed_territories=["T02"])
LARGE_SHARE_CARRIER = dict(BEACON, voluntary_market_share_bps=1500, licensed_territories=["T02"])

# A single conviction that sits 1081 days before the 2026-09-01 certification
# clock and exactly 1095 days before the 2026-09-15 effective date.
AGEING_MAJOR_CONVICTION = [{"code": "SPEEDING_MAJOR", "conviction_date": "2023-09-16T00:00:00Z"}]

# A self-declared DUI the motor-vehicle record does not carry.
DECLARED_DUI = [{"code": "DUI", "conviction_date": "2025-03-10T00:00:00Z"}]

SECOND_APPLICANT = {"full_name": "Nadia Frost", "driver_license_number": "D-99012"}
SECOND_VEHICLE = {"vin": "1HGCM82633A004361"}


def _two_policies_spanning_the_period_window():
    """Two T02 risks, one policy effective on the period's window_start and one
    six days before its window_end, with the period then closed at 2026-11-30.

    Atlas holds 6000 basis points and Beacon 4000, and both are licensed in T02,
    so the two certifications hand one risk to each carrier. Returns
    ``(env, early_policy_id, late_policy_id)``.
    """
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    early = bring_application_to_certified(env, document_prefix="DEC-40")
    late = bring_application_to_certified(
        env,
        applicant_overrides=SECOND_APPLICANT,
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-41",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    early_assignment = assignment_for_application(early["application"]["id"])
    late_assignment = assignment_for_application(late["application"]["id"])
    accept_assignment(early_assignment["id"], early_assignment["carrier_id"])
    accept_assignment(late_assignment["id"], late_assignment["carrier_id"])

    early_policy = issue_policy(early_assignment["id"], early_assignment["carrier_id"],
                               policy_number="AR-100014",
                               effective_date="2026-09-01T00:00:00Z",
                               expiration_date="2027-09-01T00:00:00Z")
    set_clock("2026-11-24T00:00:00Z")
    late_policy = issue_policy(late_assignment["id"], late_assignment["carrier_id"],
                               policy_number="AR-100015",
                               effective_date="2026-11-24T00:00:00Z",
                               expiration_date="2027-11-24T00:00:00Z")
    set_clock("2026-11-30T00:00:00Z")
    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    return env, early_policy["id"], late_policy["id"]


def test_each_policy_exposure_is_rounded_to_four_decimals_and_capped_by_the_clock():
    """Per-policy car-year exposure rounds to 4 decimals before anything is summed.

    The period runs 2026-09-01 through 2026-11-30 and is read at a clock of
    2026-11-30. The early policy's interval starts at the later of its effective
    date and window_start and ends at the earliest of its expiration date, the day
    after window_end and the clock — so the clock binds at 90 days, not the 91 the
    day-after-window_end bound would allow, and 90/365 rounds half up to 0.2466.
    The late policy contributes 6 days, or 0.0164, not the 7 days that ignoring the
    clock would give.

    PRD: "To make the layering concrete: for a period running 2026-09-01 through
    2026-11-30 read at a clock of 2026-11-30, a policy effective 2026-11-24
    contributes 6 days, or 0.0164, and a policy effective 2026-09-01 contributes
    90 days, or 0.2466, for a total of 0.2630."
    Design: Corner/calculations/each_policy_rounds_to_four_decimals_before_the_carrier_total_sums
    """
    env, early_policy_id, late_policy_id = _two_policies_spanning_the_period_window()

    early_policy = read_policy(early_policy_id)
    late_policy = read_policy(late_policy_id)
    period = read_plan_period(env["plan_period"]["id"])

    assert period["status"] == "RECONCILING"
    assert early_policy["exposure_car_years_current_period"] == 0.2466
    assert early_policy["exposure_car_years_current_period"] != 0.2493, (
        "0.2493 is the 91-day figure the running clock forbids"
    )
    assert late_policy["exposure_car_years_current_period"] == 0.0164
    assert late_policy["exposure_car_years_current_period"] != 0.0192, (
        "0.0192 is the 7-day figure the running clock forbids"
    )
    assert period["total_assignable_car_years"] == 0.2630
    assert (early_policy["exposure_car_years_current_period"]
            + late_policy["exposure_car_years_current_period"]) == 0.2630


def test_closure_freezes_the_summed_car_year_total_against_a_later_clock():
    """The period total is the sum of already-rounded figures, frozen at closure.

    0.2466 plus 0.0164 is exactly 0.2630, and once the period has moved into
    reconciliation the figure no longer answers to the clock: advancing the clock
    two weeks past window_end leaves both frozen totals exactly where closure left
    them, at 0.2630 car-years across 2 assignable units.

    PRD: "Closure moves the period `OPEN → RECONCILING` and freezes both
    `total_assignable_units` and `total_assignable_car_years` at the closure
    instant."
    Design: Corner/calculations/each_policy_rounds_to_four_decimals_before_the_carrier_total_sums
    """
    env, _, _ = _two_policies_spanning_the_period_window()

    at_closure = read_plan_period(env["plan_period"]["id"])
    assert at_closure["total_assignable_car_years"] == 0.2630
    assert at_closure["total_assignable_units"] == 2

    set_clock("2026-12-15T00:00:00Z")
    later = read_plan_period(env["plan_period"]["id"])

    assert later["status"] == "RECONCILING"
    assert later["total_assignable_car_years"] == 0.2630
    assert later["total_assignable_units"] == 2


def test_the_required_deposit_rounds_a_half_cent_up_and_certification_accepts_it_exactly():
    """One quarter of 155754 is exactly 38938.5, which rounds half up to 38939.

    A clean adult T02 PLEASURE risk rates to 148337 cents of premium plus a 0.05
    expense charge of 7417, for a term charge of 155754. A quarter of that is a
    dead-centre half cent, so the plan must round up to 38939 rather than truncate
    to 38938, and paying exactly 38939 satisfies the inclusive certification gate.

    PRD: "How much the plan requires before it will certify the risk is
    `required_deposit_cents`: one quarter of `estimated_total_charge_cents`,
    rounded half up to whole cents, but never less than a fifteen-thousand-cent
    floor — so a small risk still posts a minimum deposit of 150 dollars."
    Design: Corner/calculations/deposit_rounds_half_up_and_the_fifteen_thousand_floor_never_binds
    """
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    file_two_market_rejections(application["id"], env["producer"]["id"], document_prefix="DEC-42")
    verify_mvr(application["id"], [])

    priced = read_application(application["id"])
    assert priced["surcharge_points_estimated"] == 0
    assert priced["estimated_annual_premium_cents"] == 148337
    assert priced["estimated_expense_charge_cents"] == 7417
    assert priced["estimated_total_charge_cents"] == 155754
    assert priced["required_deposit_cents"] == 38939
    assert priced["required_deposit_cents"] != 38938, (
        "38938 is the truncated figure the half-up rule forbids"
    )

    record_deposit(application["id"], env["producer"]["id"], 38939)
    funded = read_application(application["id"])
    assert funded["deposit_paid_total_cents"] == 38939
    assert funded["deposit_balance_cents"] == 38939
    assert_deposit_ledger_conserved(funded)

    certify_application(application["id"])
    certified = read_application(application["id"])
    assert certified["status"] == "CERTIFIED_AWAITING_ASSIGNMENT"
    assert certified["required_deposit_cents"] == 38939
    assert certified["deposit_paid_total_cents"] == 38939


def test_the_cheapest_reachable_risk_still_owes_far_more_than_the_deposit_floor():
    """Even the T01 PLEASURE zero-point risk sits well above the 15000-cent floor.

    The T01 territory base of 96475 cents splits into per-line premiums of 53061,
    28943 and 14471, which sum back to 96475. That figure is at least 75000 and
    below 150000, so the 0.05 rate gives 4823.75, rounding half up to 4824, for a
    term charge of 101299. A quarter of that is 25324.75, which rounds half up to
    25325 — six times the floor, so the floor never binds on any reachable risk.

    PRD: "0.06 when `final_premium_cents` is below 75000 cents, 0.05 when it is at
    least 75000 but below 150000 cents, and 0.04 when it is 150000 cents or more."
    Design: Corner/calculations/deposit_rounds_half_up_and_the_fifteen_thousand_floor_never_binds
    """
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle({"territory_code": "T01"})
    assert vehicle["garaging_territory_code"] == "T01"
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"])
    verify_mvr(application["id"], [])

    priced = read_application(application["id"])
    assert priced["surcharge_points_estimated"] == 0
    assert priced["estimated_annual_premium_cents"] == 96475
    assert priced["estimated_expense_charge_cents"] == 4824
    assert priced["estimated_expense_charge_cents"] != 5789, (
        "5789 is the 0.06 charge the plan levies only below 75000 cents"
    )
    assert priced["estimated_total_charge_cents"] == 101299
    assert priced["required_deposit_cents"] == 25325
    assert priced["required_deposit_cents"] != 25324, (
        "25324 is the truncated figure the half-up rule forbids"
    )
    assert priced["required_deposit_cents"] > DEPOSIT_FLOOR_CENTS


def test_the_verified_record_replaces_the_declared_record_in_the_premium_estimate():
    """A declared DUI the motor-vehicle record omits is dropped wholesale.

    The declared DUI is worth 8 points, which selects the 1.60 factor: the T02 base
    of 148337 becomes 237339.2, whose per-line shares round to 130537, 71202 and
    35601 for 237340, a 0.04 charge of 9494, a term charge of 246834 and a deposit
    of 61709. Verifying an empty record re-rates the estimate at 0 points, so the
    estimate falls to 148337 / 7417 / 155754 with a deposit of 38939 — the arrays
    are never merged, and the declared input is still on the row.

    PRD: "The source array is `verified_violations` when `mvr_verified_at` is not
    null, and `declared_violations` otherwise — the plan never blends the two."
    Design: Corner/calculations/the_verified_record_supersedes_the_declared_record_entirely
    """
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"],
                                     declared_violations=DECLARED_DUI)

    assert application["surcharge_points_estimated"] == 8
    assert application["estimated_annual_premium_cents"] == 237340
    assert application["estimated_expense_charge_cents"] == 9494
    assert application["estimated_total_charge_cents"] == 246834
    assert application["required_deposit_cents"] == 61709

    verify_mvr(application["id"], [])
    verified = read_application(application["id"])

    assert verified["verified_violations"] == []
    assert verified["mvr_verified_at"] is not None
    assert [v["code"] for v in verified["declared_violations"]] == ["DUI"]
    assert verified["surcharge_points_estimated"] == 0
    assert verified["estimated_annual_premium_cents"] == 148337
    assert verified["estimated_expense_charge_cents"] == 7417
    assert verified["estimated_total_charge_cents"] == 155754
    assert verified["required_deposit_cents"] == 38939


def test_an_unverified_declaration_is_not_a_chargeable_event_for_clean_years():
    """The clean-years clock counts verified convictions only.

    The applicant declared a DUI convicted 2025-03-10 but the motor-vehicle record
    carries nothing, so the only event date available is the applicant's own
    first_licensed_date of 2010-06-01. The whole days from there to the 2026-09-01
    clock divided by 365 and truncated is far above the cap, so the credit reads
    exactly the 5-year cap rather than the single year the declared conviction
    would have allowed.

    PRD: "The plan gathers two kinds of chargeable event: the `conviction_date` of
    every *verified* violation on any of the applicant's applications, and the
    `loss_date` of every claim of the applicant whose `at_fault` flag is true.
    Declared-but-unverified violations are ignored entirely."
    Design: Corner/calculations/the_verified_record_supersedes_the_declared_record_entirely
    """
    env = bootstrap_plan()
    applicant, vehicle = create_applicant_with_vehicle()
    application = submit_application(env["producer"]["id"], applicant["id"], vehicle["id"],
                                     declared_violations=DECLARED_DUI)

    declared_only = read_applicant(applicant["id"])
    assert declared_only["last_chargeable_event_date"].startswith("2010-06-01")
    assert declared_only["clean_years_credited"] == 5

    verify_mvr(application["id"], [])
    after_verification = read_applicant(applicant["id"])

    assert after_verification["last_chargeable_event_date"].startswith("2010-06-01")
    assert after_verification["clean_years_credited"] == 5


def test_an_underserved_garaging_territory_pays_one_and_a_half_credit_units():
    """Voluntary-exit credit is keyed on the vehicle's garaging territory.

    The period lists T03 as its only underserved territory. Atlas services the
    T02-garaged risk and earns 1.0 credit units on exit; Beacon services the
    T03-garaged risk and earns 1.5. Both carriers shed the headcount, so each
    reports an assigned_risk_count of 0 with its credit carried to one decimal.

    PRD: "`voluntary_credit_units` rises by 1.5 when the vehicle's
    `garaging_territory_code` appears in that period's `underserved_territories`,
    and by 1.0 otherwise."
    Design: Corner/calculations/underserved_territory_exits_pay_one_and_a_half_credit_units
    """
    env = bootstrap_plan(carriers=[ATLAS_T02_ONLY, BEACON_T03_ONLY])
    atlas, beacon = env["carriers"]
    assert env["plan_period"]["underserved_territories"] == ["T03"]

    standard = bring_application_to_certified(env, document_prefix="DEC-50")
    underserved = bring_application_to_certified(
        env,
        applicant_overrides=dict(SECOND_APPLICANT, territory_code="T03"),
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-51",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    standard_assignment = assignment_for_application(standard["application"]["id"])
    underserved_assignment = assignment_for_application(underserved["application"]["id"])
    assert standard_assignment["carrier_id"] == atlas["id"]
    assert underserved_assignment["carrier_id"] == beacon["id"]
    accept_assignment(standard_assignment["id"], atlas["id"])
    accept_assignment(underserved_assignment["id"], beacon["id"])

    set_clock("2026-09-15T00:00:00Z")
    standard_policy = issue_policy(standard_assignment["id"], atlas["id"],
                                   policy_number="AR-100014",
                                   effective_date="2026-09-15T00:00:00Z",
                                   expiration_date="2027-09-15T00:00:00Z")
    underserved_policy = issue_policy(underserved_assignment["id"], beacon["id"],
                                      policy_number="AR-100015",
                                      effective_date="2026-09-15T00:00:00Z",
                                      expiration_date="2027-09-15T00:00:00Z")

    validate_success(api_client.exit_policy_to_voluntary(
        standard_policy["id"], create_voluntary_exit_payload(), ADMIN_HEADERS))
    validate_success(api_client.exit_policy_to_voluntary(
        underserved_policy["id"], create_voluntary_exit_payload(), ADMIN_HEADERS))

    assert read_policy(standard_policy["id"])["policy_status"] == "EXITED_TO_VOLUNTARY"
    assert read_policy(underserved_policy["id"])["policy_status"] == "EXITED_TO_VOLUNTARY"
    assert read_application(standard["application"]["id"])["status"] == "CLOSED_EXITED"
    assert read_application(underserved["application"]["id"])["status"] == "CLOSED_EXITED"
    assert read_assignment(standard_assignment["id"])["status"] == "CLOSED"
    assert read_assignment(underserved_assignment["id"])["status"] == "CLOSED"

    atlas_after = read_carrier(atlas["id"])
    beacon_after = read_carrier(beacon["id"])
    assert atlas_after["voluntary_credit_units"] == 1.0
    assert beacon_after["voluntary_credit_units"] == 1.5
    assert atlas_after["assigned_risk_count"] == 0
    assert beacon_after["assigned_risk_count"] == 0
    assert read_applicant(standard["applicant"]["id"])["voluntary_market_eligible"] is True
    assert read_applicant(underserved["applicant"]["id"])["voluntary_market_eligible"] is True


def test_largest_remainder_hands_the_second_leftover_to_the_smaller_share():
    """Recomputed on every certification, the whole-unit targets always sum exactly.

    With 6000 and 4000 basis points the first certification makes the exact
    entitlements 0.6 and 0.4: both floors are 0, one leftover unit remains, and the
    0.6 remainder takes it, giving targets of 1 and 0. The second certification
    makes them 1.2 and 0.8: the floors are 1 and 0, one leftover remains, and now
    the 0.8 remainder beats the 0.2, so the leftover crosses to the smaller-share
    carrier for targets of 1 and 1. Nothing is assigned yet, so each carrier's
    variance is 0 plus 0 credit less its target of 1, exactly -1.0.

    PRD: "Exact entitlements are held unrounded for the purpose of the remainder
    comparison, and the resulting targets always sum to exactly
    `total_assignable_units`."
    Design: Corner/calculations/largest_remainder_targets_always_sum_to_the_assignable_total
    """
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    atlas, beacon = env["carriers"]

    bring_application_to_certified(env, document_prefix="DEC-60")
    period_after_one = read_plan_period(env["plan_period"]["id"])
    atlas_after_one = read_carrier(atlas["id"])
    beacon_after_one = read_carrier(beacon["id"])
    assert period_after_one["total_assignable_units"] == 1
    assert atlas_after_one["quota_target_units"] == 1
    assert beacon_after_one["quota_target_units"] == 0
    assert_targets_sum_to_assignable_total([atlas_after_one, beacon_after_one], period_after_one)

    bring_application_to_certified(
        env,
        applicant_overrides=SECOND_APPLICANT,
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-61",
    )
    period = read_plan_period(env["plan_period"]["id"])
    atlas_final = read_carrier(atlas["id"])
    beacon_final = read_carrier(beacon["id"])

    assert period["total_assignable_units"] == 2
    assert atlas_final["quota_target_units"] == 1
    assert beacon_final["quota_target_units"] == 1
    assert_targets_sum_to_assignable_total([atlas_final, beacon_final], period)
    assert atlas_final["quota_variance_units"] == -1.0
    assert beacon_final["quota_variance_units"] == -1.0
    for carrier in (atlas_final, beacon_final):
        assert carrier["overallocated"] is False
        assert carrier["posture"] == "OPEN"
        assert_quota_variance(carrier)
        assert_posture_ladder(carrier)


def test_a_remainder_tie_is_broken_by_market_share_and_gives_one_carrier_both_units():
    """Tied remainders of 0.5 send both leftover-eligible units to the larger share.

    With a total of 2 units and shares of 500 and 1500 basis points the exact
    entitlements are 0.5 and 1.5, the floors are 0 and 1, and one leftover unit
    remains against remainders that tie at 0.5. Market share descending breaks the
    tie, so the 1500-basis-point carrier takes the leftover for targets of 0 and 2,
    which still sum to the assignable total of 2.

    PRD: "with a total of 2 units and two active carriers holding 500 and 1500
    basis points, the exact entitlements are 0.5 and 1.5, the floors are 0 and 1,
    one leftover unit remains, and the remainders tie at 0.5 each — so the tie is
    broken by market share and the 1500-basis-point carrier takes the leftover,
    giving targets of 0 and 2."
    Design: Corner/calculations/largest_remainder_targets_always_sum_to_the_assignable_total
    """
    env = bootstrap_plan(carriers=[SMALL_SHARE_CARRIER, LARGE_SHARE_CARRIER])
    small, large = env["carriers"]

    bring_application_to_certified(env, document_prefix="DEC-62")
    bring_application_to_certified(
        env,
        applicant_overrides=SECOND_APPLICANT,
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-63",
    )

    period = read_plan_period(env["plan_period"]["id"])
    small_final = read_carrier(small["id"])
    large_final = read_carrier(large["id"])

    assert period["total_assignable_units"] == 2
    assert small_final["quota_target_units"] == 0
    assert large_final["quota_target_units"] == 2
    assert_targets_sum_to_assignable_total([small_final, large_final], period)
    assert small_final["quota_variance_units"] == 0.0
    assert large_final["quota_variance_units"] == -2.0
    assert small_final["overallocated"] is False
    assert large_final["overallocated"] is False


def test_the_ranking_is_recomputed_between_placements_inside_one_run():
    """Two applications certified at the same instant land on different carriers.

    Both risks were certified at a frozen clock of 2026-09-01, so certified_at ties
    and intake_sequence orders the queue. Each carrier holds a target of 1 against
    an assigned_risk_count of 0, so both deficits are 1.0 and the 6000-basis-point
    carrier wins the first risk. Its headcount is written before the second risk is
    ranked, collapsing its deficit to 0 and handing the second risk to the
    4000-basis-point carrier, again at a recorded deficit of 1.0.

    PRD: "The winning carrier's `assigned_risk_count` rises by 1 and its
    `quota_variance_units`, `overallocated` and `posture` are recomputed *before
    the next queued application is ranked*, so the ordering of the queue is
    observable in the outcome — two applications in a single run can land on
    different carriers even though the candidate set never changed."
    Design: Corner/calculations/the_queue_is_ordered_and_the_ranking_is_recomputed_between_placements
    """
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    atlas, beacon = env["carriers"]
    first = bring_application_to_certified(env, document_prefix="DEC-70")
    second = bring_application_to_certified(
        env,
        applicant_overrides=SECOND_APPLICANT,
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-71",
    )
    assert first["application"]["intake_sequence"] < second["application"]["intake_sequence"]

    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])

    ran = read_assignment_cycle(cycle["id"])
    assert ran["status"] == "COMPLETED"
    assert ran["assigned_count"] == 2
    assert ran["deferred_count"] == 0

    first_assignment = assignment_for_application(first["application"]["id"])
    second_assignment = assignment_for_application(second["application"]["id"])
    assert first_assignment["carrier_id"] == atlas["id"]
    assert first_assignment["batch_sequence"] == 1
    assert first_assignment["deficit_score_at_selection"] == 1.0
    assert second_assignment["carrier_id"] == beacon["id"]
    assert second_assignment["batch_sequence"] == 2
    assert second_assignment["deficit_score_at_selection"] == 1.0
    assert first_assignment["status"] == "PENDING_ACCEPTANCE"
    assert second_assignment["status"] == "PENDING_ACCEPTANCE"

    for carrier_id in (atlas["id"], beacon["id"]):
        carrier = read_carrier(carrier_id)
        assert carrier["assigned_risk_count"] == 1
        assert carrier["quota_variance_units"] == 0.0
        assert carrier["overallocated"] is False
        assert carrier["posture"] == "OPEN"
    assert read_application(first["application"]["id"])["status"] == "ASSIGNED"
    assert read_application(second["application"]["id"])["status"] == "ASSIGNED"


def test_closing_an_at_fault_claim_resets_the_clean_years_clock_to_zero():
    """The loss date, not the closure date, restarts the clean-years curve.

    The applicant was first licensed in 2010 and has no verified conviction, so the
    curve sits at the 5-year cap. Closing an at-fault claim whose loss_date is
    2026-09-16 moves last_chargeable_event_date to that loss date, and at a clock
    of 2026-09-20 only 4 whole days have elapsed: 4 divided by 365 and truncated
    downward is 0. The voluntary exit that was lawful a moment earlier is now
    refused for want of the third clean year.

    PRD: "`clean_years_credited` is then the lesser of 5 and the number of whole
    365-day years between `last_chargeable_event_date` and the current clock,
    computed by taking the whole days elapsed, dividing by 365, and truncating
    downward."
    Design: Corner/calculations/an_at_fault_closure_restarts_the_clean_years_curve
    """
    env = setup_policy_in_force()
    carrier_id = env["carriers"][0]["id"]
    applicant_id = env["applicant"]["id"]
    assert read_applicant(applicant_id)["clean_years_credited"] == 5

    set_clock("2026-09-20T00:00:00Z")
    claim = report_claim(env["policy"]["id"], carrier_id,
                         loss_date="2026-09-16T00:00:00Z", at_fault=True,
                         coverage_line="PD", reserve_cents=90000)
    acknowledge_claim(claim["id"], carrier_id)
    closed = validate_success(api_client.close_claim(
        claim["id"], create_claim_closure_payload("PAID", paid_cents=90000),
        make_servicing_carrier_headers(carrier_id)))

    assert closed["status"] == "CLOSED_PAID"
    assert closed["paid_cents"] == 90000

    applicant = read_applicant(applicant_id)
    assert applicant["last_chargeable_event_date"].startswith("2026-09-16")
    assert applicant["clean_years_credited"] == 0

    refused = api_client.exit_policy_to_voluntary(
        env["policy"]["id"], create_voluntary_exit_payload(), ADMIN_HEADERS)
    validate_error(refused, "ERR_CLEAN_YEARS_INSUFFICIENT", 422)

    assert read_policy(env["policy"]["id"])["policy_status"] == "IN_FORCE"
    assert read_applicant(applicant_id)["voluntary_market_eligible"] is False
    carrier = read_carrier(carrier_id)
    assert carrier["assigned_risk_count"] == 1
    assert carrier["voluntary_credit_units"] == 0.0


def _period_reconciling_with_one_carrier_shut_out():
    """Two T02 risks placed with Atlas while Beacon, licensed only in T03, gets none.

    Atlas holds 6000 basis points and Beacon 4000, so a total of 2 assignable units
    apportions to a target of 1 each; the selector can only ever reach Atlas.
    Returns ``(env, atlas, beacon)`` with the period in RECONCILING at 2026-11-30.
    """
    env = bootstrap_plan(carriers=[ATLAS_T02_ONLY, BEACON_T03_ONLY])
    atlas, beacon = env["carriers"]
    bring_application_to_certified(env, document_prefix="DEC-80")
    bring_application_to_certified(
        env,
        applicant_overrides=SECOND_APPLICANT,
        vehicle_overrides=SECOND_VEHICLE,
        document_prefix="DEC-81",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    set_clock("2026-11-30T00:00:00Z")
    validate_success(api_client.close_plan_period(env["plan_period"]["id"], ADMIN_HEADERS))
    return env, atlas, beacon


def test_a_carrier_that_could_never_be_a_candidate_still_pays_the_per_unit_penalty():
    """Obligation is share-based: a 1-unit target unmet costs a full 25000 cents.

    Beacon writes only T03, so neither T02 risk could ever have reached it, yet the
    apportionment still gives it 1 of the 2 assignable units. Its headcount is 0
    and it holds no voluntary credit, so credited units are 0.0 against an
    obligation of 1, a variance of -1.0, and a shortfall of 1.0 deficient unit at
    25000 cents per unit — exactly 25000 cents, which becomes its whole penalty
    balance.

    PRD: "`penalty_cents` is then the shortfall — that is, the negation of
    `variance_units` when the variance is negative, and 0 when it is zero or
    positive — multiplied by 25000 cents per deficient unit and rounded half up to
    whole cents."
    Design: Corner/calculations/a_carrier_that_wrote_nothing_pays_the_per_unit_deficiency_penalty
    """
    env, _, beacon = _period_reconciling_with_one_carrier_shut_out()
    before = read_carrier(beacon["id"])
    assert before["quota_target_units"] == 1
    assert before["assigned_risk_count"] == 0
    assert before["voluntary_credit_units"] == 0.0

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(beacon["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", before["version"]),
        ADMIN_HEADERS), 201)

    assert_quota_reconciliation(filing)
    assert filing["basis"] == "POLICY_COUNT"
    assert filing["obligation_units"] == 1
    assert filing["credited_units"] == 0.0
    assert filing["variance_units"] == -1.0
    assert filing["voluntary_credit_units_applied"] == 0.0
    assert filing["penalty_cents"] == 25000
    assert filing["status"] == "FINAL"

    after = read_carrier(beacon["id"])
    assert after["penalty_balance_cents"] == 25000
    assert after["version"] == before["version"] + 1
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"


def test_the_deficiency_penalty_is_one_sided_and_never_charges_an_over_served_carrier():
    """A positive variance costs nothing, however far above target it runs.

    Atlas absorbed both T02 risks against a target of 1, so its credited units are
    2 assigned plus 0.0 credit against an obligation of 1: a variance of exactly
    +1.0. The shortfall is 0 whenever the variance is zero or positive, so the
    penalty is 0 cents and the penalty balance stays empty — while the same +1.0
    variance leaves the carrier overallocated and therefore RESTRICTED on the
    posture ladder.

    PRD: "Whichever basis applies, `variance_units` is `credited_units` less
    `obligation_units`, so a negative variance means the carrier fell short of its
    obligation. `penalty_cents` is then the shortfall — that is, the negation of
    `variance_units` when the variance is negative, and 0 when it is zero or
    positive — multiplied by 25000 cents per deficient unit and rounded half up to
    whole cents."
    Design: Corner/calculations/a_carrier_that_wrote_nothing_pays_the_per_unit_deficiency_penalty
    """
    env, atlas, _ = _period_reconciling_with_one_carrier_shut_out()
    before = read_carrier(atlas["id"])
    assert before["quota_target_units"] == 1
    assert before["assigned_risk_count"] == 2
    assert before["quota_variance_units"] == 1.0
    assert before["overallocated"] is True
    assert before["posture"] == "RESTRICTED"
    assert_posture_ladder(before)

    filing = validate_success(api_client.create_quota_reconciliation(
        create_quota_reconciliation_payload(atlas["id"], env["plan_period"]["id"],
                                            "POLICY_COUNT", before["version"]),
        ADMIN_HEADERS), 201)

    assert filing["obligation_units"] == 1
    assert filing["credited_units"] == 2.0
    assert filing["variance_units"] == 1.0
    assert filing["penalty_cents"] == 0
    assert filing["status"] == "FINAL"
    assert read_quota_reconciliation(filing["id"])["penalty_cents"] == 0
    assert read_carrier(atlas["id"])["penalty_balance_cents"] == 0
    assert read_plan_period(env["plan_period"]["id"])["status"] == "RECONCILING"


def _policy_whose_conviction_ages_out_at_the_effective_date():
    """A verified SPEEDING_MAJOR convicted 2023-09-16, certified at 2026-09-01 and
    issued effective 2026-09-15.

    The conviction is 1081 days before the certification clock and exactly 1095
    days before the effective date, so it counts for the estimate and not for the
    policy. Returns ``(env, application_id, policy)``.
    """
    env = bootstrap_plan(carriers=[ATLAS, BEACON])
    risk = bring_application_to_certified(
        env,
        application_overrides={"declared_violations": AGEING_MAJOR_CONVICTION},
        verified_violations=AGEING_MAJOR_CONVICTION,
        document_prefix="DEC-90",
    )
    placed = place_and_accept(env, risk["application"]["id"], env["carriers"][0]["id"])
    set_clock("2026-09-15T00:00:00Z")
    policy = issue_policy(placed["assignment"]["id"], env["carriers"][0]["id"],
                          policy_number="AR-100014",
                          effective_date="2026-09-15T00:00:00Z",
                          expiration_date="2027-09-15T00:00:00Z")
    env.update(risk)
    return env, risk["application"]["id"], policy


def test_the_applied_points_window_anchors_on_the_effective_date_and_rates_lower():
    """The conviction counts at certification and is excluded at issuance.

    At the 2026-09-01 certification clock the conviction is 1081 days old, so it
    contributes 3 points and the 1.15 factor: 148337 times 1.15 is 170587.55,
    whose per-line shares round to 93823, 51176 and 25588 for 170587, a 0.04 charge
    of 6823, a term charge of 177410 and a required deposit of 44353. At the
    2026-09-15 effective date the same conviction is exactly 1095 days old and the
    strict lower bound excludes it, so the policy rates at 0 points and factor 1.00
    for 148337 / 7417 / 155754, leaving 155754 less the 44353 already credited,
    or 111401, still due.

    PRD: "Because the applied variant anchors its 1095-day window to the effective
    date rather than to the certification instant, a conviction can age out of the
    window between certification and issuance, and the policy will then rate lower
    than the application estimated."
    Design: Corner/calculations/the_lookback_anchor_moves_from_certification_to_the_effective_date
    """
    env, application_id, policy = _policy_whose_conviction_ages_out_at_the_effective_date()

    estimate = read_application(application_id)
    assert estimate["surcharge_points_estimated"] == 3
    assert estimate["estimated_annual_premium_cents"] == 170587
    assert estimate["estimated_expense_charge_cents"] == 6823
    assert estimate["estimated_total_charge_cents"] == 177410
    assert estimate["required_deposit_cents"] == 44353
    assert estimate["deposit_paid_total_cents"] == 44353

    assert policy["surcharge_points_applied"] == 0
    assert policy["surcharge_factor_applied"] == 1.00
    assert policy["premium_lines"] == T02_ADULT_CLEAN["premium_lines"]
    assert policy["final_premium_cents"] == 148337
    assert policy["plan_expense_charge_cents"] == 7417
    assert policy["total_annual_charge_cents"] == 155754
    assert_premium_lines_sum_to_final_premium(policy)
    assert_total_annual_charge(policy)
    assert policy["premium_credited_cents"] == 44353
    assert policy["additional_premium_due_cents"] == 111401
    assert policy["premium_settlement_status"] == "PREMIUM_OUTSTANDING"

    settled = read_application(application_id)
    assert settled["deposit_balance_cents"] == 0
    assert_deposit_ledger_conserved(settled, [read_policy(policy["id"])])


def test_the_event_that_ages_out_of_the_points_window_grants_the_third_clean_year():
    """One instant, two opposite effects on the same verified conviction.

    Read at a clock of 2026-09-15, the conviction of 2023-09-16 is exactly 1095
    whole days back: 1095 divided by 365 and truncated is 3, so the applicant is
    credited the third clean year, while the strictly-greater-than bound of the
    points window excludes the very same event from the policy's applied points.

    PRD: "Note the deliberate interaction with surcharge rating: an event exactly
    1095 days old grants the third clean year and at the same instant falls outside
    the strict points window described in §3.2."
    Design: Corner/calculations/the_lookback_anchor_moves_from_certification_to_the_effective_date
    """
    env, _, policy = _policy_whose_conviction_ages_out_at_the_effective_date()

    applicant = read_applicant(env["applicant"]["id"])
    assert applicant["last_chargeable_event_date"].startswith("2023-09-16")
    assert applicant["clean_years_credited"] == 3
    assert policy["surcharge_points_applied"] == 0
    assert policy["surcharge_factor_applied"] == 1.00


def test_reclassification_restates_the_ledger_by_the_exact_charge_delta():
    """A re-rate moves the money axis by the delta and never re-sweeps the deposit.

    The policy was issued clean at 148337 / 7417 / 155754 with 38939 credited and
    116815 outstanding. Reclassifying the driver to YOUTHFUL_OPERATOR adds 3 class
    points for 3 applied points and the 1.15 factor, so 148337 times 1.15 is
    170587.55 and the per-line shares round to 93823, 51176 and 25588 for 170587.
    That premium is at or above 150000, so the expense rate drops to 0.04 for 6823
    and a term charge of 177410. The credited deposit is untouched at 38939 and the
    amount due is restated to 177410 less 38939, or 138471 — exactly the 21656-cent
    increase in the term charge added to the previous 116815.

    PRD: "otherwise `additional_premium_due_cents` is restated as
    `total_annual_charge_cents` less `premium_credited_cents`."
    Design: Corner/calculations/reclassification_restates_the_premium_ledger_by_the_exact_delta
    """
    env = setup_policy_in_force()
    before = read_policy(env["policy"]["id"])
    assert before["final_premium_cents"] == 148337
    assert before["plan_expense_charge_cents"] == 7417
    assert before["total_annual_charge_cents"] == 155754
    assert before["premium_credited_cents"] == 38939
    assert before["additional_premium_due_cents"] == 116815
    assert before["rating_revision"] == 1

    after = validate_success(api_client.reclassify_policy(
        env["policy"]["id"],
        create_reclassification_payload(before["version"], "YOUTHFUL_OPERATOR",
                                        "2026-10-01T00:00:00Z"),
        ADMIN_HEADERS))

    assert after["surcharge_points_applied"] == 3
    assert after["surcharge_factor_applied"] == 1.15
    assert after["premium_lines"] == {"BI": 93823, "PD": 51176, "UM": 25588}
    assert after["final_premium_cents"] == 170587
    assert after["plan_expense_charge_cents"] == 6823
    assert after["total_annual_charge_cents"] == 177410
    assert_premium_lines_sum_to_final_premium(after)
    assert_total_annual_charge(after)
    assert after["premium_credited_cents"] == 38939
    assert after["additional_premium_due_cents"] == 138471
    assert (after["additional_premium_due_cents"]
            - before["additional_premium_due_cents"]) == 21656
    assert (after["total_annual_charge_cents"]
            - before["total_annual_charge_cents"]) == 21656
    assert after["refund_paid_cents"] == 0
    assert after["premium_settlement_status"] == "PREMIUM_OUTSTANDING"
    assert after["policy_status"] == "IN_FORCE"
    assert after["rating_revision"] == 2
    assert after["version"] == before["version"] + 1
    assert read_applicant(env["applicant"]["id"])["driver_class"] == "YOUTHFUL_OPERATOR"
