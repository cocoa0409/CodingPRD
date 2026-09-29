"""Formulas whose intermediate caps and per-term rounding are load-bearing.

Each derivation here has a plausible-but-wrong shortcut: capping once at the
end instead of at each term, rounding the raw line figure before splitting it
across the four post functions, or multiplying by the vendor markup before the
base and night components have each been rounded to whole cents. The pinned
order and the shortcut give different answers, so the numbers separate them.
"""

from test_helpers import (
    ANALYST_HEADERS,
    AUDITOR_HEADERS,
    COORDINATOR_HEADERS,
    ApiClient,
    AssignmentStatus,
    CrowdProfile,
    DutyStatus,
    EventType,
    PayBasis,
    PostType,
    ProtestLikelihood,
    RiskTier,
    SubcontractorStatus,
    ThreatLevel,
    action,
    assert_assignment_cost,
    assert_decimal,
    assert_ledger,
    build_event_world,
    build_plan_world,
    create_assignment,
    post_payload,
    risk_assessment_payload,
    subcontracted_guard_payload,
    subcontractor_payload,
    validate_success,
)

NIGHT_POST_START = "2026-09-12T22:00:00Z"
NIGHT_POST_END = "2026-09-13T09:00:00Z"
NIGHT_SHIFT_END = "2026-09-13T08:30:00Z"


def _submitted(api: ApiClient, event_overrides: dict, ra_inputs: dict) -> dict:
    """Author one assessment revision against a fresh event and submit it."""
    world = build_event_world(api, **event_overrides)
    assessment = validate_success(
        api.create_risk_assessment(
            world.event_id, risk_assessment_payload(**ra_inputs), ANALYST_HEADERS
        ),
        expected_status=201,
    )
    return validate_success(
        api.risk_assessment_decision(assessment["id"], action("SUBMIT"), ANALYST_HEADERS)
    )


SELLOUT_EVENT = dict(event_name="Sellout Night", expected_attendance=8000)
SELLOUT_INPUTS = dict(
    threat_level_input=ThreatLevel.LOW,
    protest_likelihood=ProtestLikelihood.NONE,
    crowd_profile=CrowdProfile.SEATED,
    ingress_door_count=1,
    layout_complexity_score=1,
    history_incident_rate=12.0,
)

DERBY_EVENT = dict(
    event_name="Derby Match", event_type=EventType.SPORTING, expected_attendance=2625
)
DERBY_INPUTS = dict(
    threat_level_input=ThreatLevel.ELEVATED,
    protest_likelihood=ProtestLikelihood.LIKELY,
    crowd_profile=CrowdProfile.GENERAL_ADMISSION,
    ingress_door_count=1,
    layout_complexity_score=2,
    history_incident_rate=0,
)


def test_density_pressure_and_crowd_factor_are_capped_before_multiplication():
    """A full house with a heavy incident history scores 37.80, not the uncapped 48.84.

    The load ratio of 1.00 pushes the density pressure term to 30.00, which is
    capped down to 25 before it enters the base points, and an incident rate of
    12.0 pushes the crowd factor to 1.48, which is capped down to 1.35 before it
    multiplies anything. Capped base points of 28 times 1.35 is 37.80; leaving
    both caps off gives 33 times 1.48, which is 48.84.

    PRD: "The **density pressure** is that load ratio multiplied by 30 points-at-full-house, rounded half-up to two decimal places, and then capped at 25 — the rounding and the cap both happen here, before the term is used anywhere else."
    Design: Difficulty/combinatorial_formula/threat_score_density_and_history_caps_applied_before_multiplication
    """
    api = ApiClient()
    assessment = _submitted(api, SELLOUT_EVENT, SELLOUT_INPUTS)

    assert_decimal(assessment["composite_threat_score"], 37.80, "composite_threat_score")
    assert assessment["risk_tier"] == RiskTier.T2


def test_capped_score_drives_the_whole_staffing_matrix_for_a_full_house():
    """The tier that survives both caps sizes the roster at 22 staff and 18 lanes.

    T2 buys 2.5 guards per thousand, so 8000 patrons give a raw line figure of
    20 that splits into 6 perimeter, 5 ingress, 7 floor and 2 exit guards. Two
    first-line supervisors cover 20 line guards, and 22 staff at a four-hour
    minimum call on 1800 cents an hour is a floor of 158400 cents.

    PRD: "Then the **crowd factor** is one plus four hundredths for each unit of `history_incident_rate`, capped at 1.35 — again, the cap is applied to the factor itself before it is used."
    Design: Difficulty/combinatorial_formula/threat_score_density_and_history_caps_applied_before_multiplication
    """
    api = ApiClient()
    assessment = _submitted(api, SELLOUT_EVENT, SELLOUT_INPUTS)

    assert assessment["required_perimeter_guards"] == 6
    assert assessment["required_ingress_guards"] == 5
    assert assessment["required_floor_guards"] == 7
    assert assessment["required_exit_guards"] == 2
    assert assessment["required_line_guards"] == 20
    assert assessment["required_supervisors"] == 2
    assert assessment["required_total_staff"] == 22
    assert assessment["required_screening_lanes"] == 18
    assert assessment["minimum_staffing_cost_floor_cents"] == 158400


def test_each_post_function_share_is_rounded_up_before_the_shares_are_summed():
    """A raw line figure of 10.5 yields 13 line guards, not the 11 a single ceiling gives.

    2625 patrons at four guards per thousand is a raw figure of 10.5. Taken
    share by share that is ceil(3.15) perimeter, ceil(2.625) ingress and
    ceil(3.675) floor guards, with the exit requirement lifted to 2 by the
    ceiling of 1.05 — four independently rounded integers that sum to 13.

    PRD: "`required_line_guards` is the sum of those four already-rounded integers."
    Design: Difficulty/combinatorial_formula/required_staff_matrix_ceil_per_share_before_summation
    """
    api = ApiClient()
    assessment = _submitted(api, DERBY_EVENT, DERBY_INPUTS)

    assert assessment["required_perimeter_guards"] == 4
    assert assessment["required_ingress_guards"] == 3
    assert assessment["required_floor_guards"] == 4
    assert assessment["required_exit_guards"] == 2
    assert assessment["required_line_guards"] == 13
    assert assessment["required_supervisors"] == 2
    assert assessment["required_total_staff"] == 15


def test_score_and_lane_requirement_follow_the_two_decimal_density_pressure():
    """A load ratio of 0.328125 rounds to a 9.84 pressure term and a 58.84 composite.

    Both screening streams are rounded up on their own before being added, so
    867 bag-carrying patrons need 5 bag lanes and 577 no-bag patrons need 2 —
    seven lanes in total — and 15 staff put the cost floor at 108000 cents.

    PRD: "`required_screening_lanes` is the ceiling of the bag-carrying population divided by 195, plus the ceiling of the no-bag population divided by 455 — each stream is rounded up separately and only then are the two integers added."
    Design: Difficulty/combinatorial_formula/required_staff_matrix_ceil_per_share_before_summation
    """
    api = ApiClient()
    assessment = _submitted(api, DERBY_EVENT, DERBY_INPUTS)

    assert_decimal(assessment["composite_threat_score"], 58.84, "composite_threat_score")
    assert assessment["risk_tier"] == RiskTier.T3
    assert assessment["required_screening_lanes"] == 7
    assert assessment["minimum_staffing_cost_floor_cents"] == 108000


def _night_subcontract_world(api: ApiClient):
    """Overnight perimeter post plus an approved vendor and one of its verified guards."""
    world = build_plan_world(api)
    post = validate_success(
        api.create_post(
            world.plan_id,
            post_payload(
                world.zf_id,
                "NIGHT1",
                PostType.PERIMETER,
                required_guard_count=1,
                window_start=NIGHT_POST_START,
                window_end=NIGHT_POST_END,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.night_post_id = post["id"]

    vendor = validate_success(
        api.create_subcontractor(
            subcontractor_payload(
                company_name="Nightwatch Labour",
                license_number="SC-9001",
                insurance_expires_on="2026-12-31T00:00:00Z",
                markup_pct=0.6,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.vendor_id = vendor["id"]
    approved = validate_success(
        api.subcontractor_decision(world.vendor_id, action("APPROVE"), AUDITOR_HEADERS)
    )
    assert approved["status"] == SubcontractorStatus.APPROVED

    guard = validate_success(
        api.create_guard(
            subcontracted_guard_payload(
                "GC-9001",
                world.vendor_id,
                full_name="Nils Owl",
                credential_level=1,
                base_hourly_rate_cents=2333,
            ),
            COORDINATOR_HEADERS,
        ),
        expected_status=201,
    )
    world.g1_id = guard["id"]
    validate_success(
        api.guard_credential_verification(world.g1_id, action("VERIFY"), AUDITOR_HEADERS)
    )
    return world


def test_subcontract_line_cost_rounds_at_all_three_levels_in_the_pinned_order():
    """A 10.50 hour night shift at 2333 cents an hour bills 47581 cents, not 47580.

    Straight pay of 18664 cents and overtime of 8749 cents are each rounded on
    their own before being added, the night differential of 1575 cents is
    rounded on its own, and only then does the 0.6 markup apply to the 28988
    cent subtotal — 46381 cents after its own rounding — before the flat 1200
    cent admin fee lands on top.

    PRD: "For a guard whose `employment_type` is `SUBCONTRACTED`, `line_cost_cents` is the already-rounded sum of base and night multiplied by one plus the vendor's `markup_pct`, rounded again to a whole cent, and only then is a flat subcontract admin fee of 1200 cents added; `pay_basis` is `SUBCONTRACT`."
    Design: Difficulty/combinatorial_formula/subcontract_assignment_cost_three_level_rounding
    """
    api = ApiClient()
    world = _night_subcontract_world(api)

    assignment_id = create_assignment(
        api,
        world.night_post_id,
        world.g1_id,
        window_start=NIGHT_POST_START,
        window_end=NIGHT_SHIFT_END,
    )
    assignment = validate_success(api.get_post_assignment(assignment_id, COORDINATOR_HEADERS))

    assert_assignment_cost(assignment, 10.50, 47581, PayBasis.SUBCONTRACT)
    assert assignment["night_differential_applies"] is True
    assert assignment["assignment_status"] == AssignmentStatus.TENTATIVE
    assert assignment["duty_status"] == DutyStatus.PENDING_BRIEF


def test_pencilled_in_night_shift_leaves_the_plan_ledger_at_zero():
    """The 47581 cent line cost sits on the row and nowhere near the plan ledger.

    A TENTATIVE row is outside the committed set, so the plan still shows no
    committed money and no committed hours while its full 500000 cent budget
    remains available.

    PRD: "Creating an assignment moves no money."
    Design: Difficulty/combinatorial_formula/subcontract_assignment_cost_three_level_rounding
    """
    api = ApiClient()
    world = _night_subcontract_world(api)

    create_assignment(
        api,
        world.night_post_id,
        world.g1_id,
        window_start=NIGHT_POST_START,
        window_end=NIGHT_SHIFT_END,
    )

    plan = validate_success(api.get_staffing_plan(world.plan_id, COORDINATOR_HEADERS))
    assert_ledger(plan, 0, 0.00, budget_remaining_cents=500000)
