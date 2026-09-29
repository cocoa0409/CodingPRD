"""The surcharge factor is a step function, and six points is where a step falls."""
from test_helpers import (
    FIVE_POINT_VIOLATIONS,
    SENIOR_APPLICANT,
    SIX_POINT_VIOLATIONS,
    T02_SENIOR_FIVE_POINTS,
    T02_YOUTHFUL_SIX_POINTS,
    YOUTHFUL_APPLICANT,
    accept_assignment,
    api_client,
    assignment_for_application,
    bootstrap_plan,
    bring_application_to_certified,
    create_policy_payload,
    make_servicing_carrier_headers,
    run_cycle,
    schedule_cycle,
    set_clock,
    validate_success,
)

SIX_POINT_APPLICANT = dict(YOUTHFUL_APPLICANT, full_name="Rosa Vance",
                           driver_license_number="D-99001")
FIVE_POINT_APPLICANT = dict(SENIOR_APPLICANT, full_name="Glen Ashby",
                            driver_license_number="D-99002")


def _two_accepted_risks_one_either_side_of_the_step():
    """Certify a six-point risk and a five-point risk, place both and accept both."""
    env = bootstrap_plan()
    six = bring_application_to_certified(
        env,
        applicant_overrides=SIX_POINT_APPLICANT,
        vehicle_overrides={"vin": "1HGCM82633A004352"},
        application_overrides={"declared_violations": SIX_POINT_VIOLATIONS},
        document_prefix="DEC-20",
    )
    five = bring_application_to_certified(
        env,
        applicant_overrides=FIVE_POINT_APPLICANT,
        vehicle_overrides={"vin": "1HGCM82633A004353"},
        application_overrides={"declared_violations": FIVE_POINT_VIOLATIONS},
        document_prefix="DEC-21",
    )
    cycle = schedule_cycle(env["plan_period"]["id"])
    run_cycle(cycle["id"])
    six_assignment = assignment_for_application(six["application"]["id"])
    five_assignment = assignment_for_application(five["application"]["id"])
    accept_assignment(six_assignment["id"], six_assignment["carrier_id"])
    accept_assignment(five_assignment["id"], five_assignment["carrier_id"])
    set_clock("2026-09-15T00:00:00Z")
    return six_assignment, five_assignment


def test_exactly_six_surcharge_points_takes_the_higher_factor_band():
    """Six points sits at the bottom of the 1.60 band, not the top of the 1.35 band.

    A youthful operator carrying one major speeding conviction rates at three
    conviction points plus the three-point youthful adder, so the applied points
    are exactly six and the plan-approved factor is 1.60. The resulting premium
    of 237340 cents and term charge of 246834 cents follow from that factor.

    PRD: "and by a plan-approved surcharge factor selected as a step function of
    the applied surcharge points: 1.00 at exactly 0 points, 1.15 for 1 through 3
    points, 1.35 for 4 or 5 points, 1.60 for 6 through 9 points, and 1.90 at 10
    points or more."
    Design: Difficulty/boundary_precision_check/surcharge_factor_step_boundary_at_exactly_six_points
    """
    six_assignment, _ = _two_accepted_risks_one_either_side_of_the_step()

    policy = validate_success(api_client.create_policy(
        create_policy_payload(six_assignment["id"], policy_number="AR-100006"),
        make_servicing_carrier_headers(six_assignment["carrier_id"])), 201)

    assert policy["surcharge_points_applied"] == 6
    assert policy["surcharge_factor_applied"] == 1.60
    assert policy["final_premium_cents"] == T02_YOUTHFUL_SIX_POINTS["final_premium_cents"]
    assert policy["total_annual_charge_cents"] == 246834


def test_five_surcharge_points_stays_in_the_lower_factor_band():
    """One point below the step the factor is still 1.35, and the charge is 38570 lower.

    A senior operator carrying a minor and a major speeding conviction rates at
    one plus three conviction points plus the one-point senior adder, so the
    applied points are five and the factor is 1.35. That produces lines of 110140,
    60076 and 30038, a final premium of 200254, an expense charge of 8010 at the
    0.04 rate and a term charge of 208264 — 38570 cents below the term charge of
    the otherwise identical six-point risk.

    PRD: "and by a plan-approved surcharge factor selected as a step function of
    the applied surcharge points: 1.00 at exactly 0 points, 1.15 for 1 through 3
    points, 1.35 for 4 or 5 points, 1.60 for 6 through 9 points, and 1.90 at 10
    points or more."
    Design: Difficulty/boundary_precision_check/surcharge_factor_step_boundary_at_exactly_six_points
    """
    six_assignment, five_assignment = _two_accepted_risks_one_either_side_of_the_step()

    six_point_policy = validate_success(api_client.create_policy(
        create_policy_payload(six_assignment["id"], policy_number="AR-100006"),
        make_servicing_carrier_headers(six_assignment["carrier_id"])), 201)
    five_point_policy = validate_success(api_client.create_policy(
        create_policy_payload(five_assignment["id"], policy_number="AR-100007"),
        make_servicing_carrier_headers(five_assignment["carrier_id"])), 201)

    assert five_point_policy["surcharge_points_applied"] == 5
    assert five_point_policy["surcharge_factor_applied"] == 1.35
    assert five_point_policy["premium_lines"] == T02_SENIOR_FIVE_POINTS["premium_lines"]
    assert five_point_policy["final_premium_cents"] == 200254
    assert five_point_policy["plan_expense_charge_cents"] == 8010
    assert five_point_policy["total_annual_charge_cents"] == 208264
    assert (six_point_policy["total_annual_charge_cents"]
            - five_point_policy["total_annual_charge_cents"]) == 38570
