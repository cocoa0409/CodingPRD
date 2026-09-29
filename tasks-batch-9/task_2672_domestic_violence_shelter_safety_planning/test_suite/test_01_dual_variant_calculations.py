"""Two calculations that keep two variants of the same figure side by side:
lethality scoring on a risk assessment, and stay cost on a shelter admission.
"""

from test_helpers import (
    advance_clock,
    api_client,
    assert_risk_assessment,
    assert_risk_scoring,
    assert_shelter_admission,
    create_risk_assessment_payload,
    exit_household,
    read_admission,
    read_client,
    read_shelter,
    seed_checked_in_admission,
    seed_client,
    seed_filed_case,
    seed_hotline_advocate,
    seed_hotline_call,
    seed_legal_advocate,
    seed_reserved_admission,
    seed_risk_assessment,
    seed_shelter_scene,
    validate_success,
)

MODERATE_FACTOR_INPUTS = dict(
    weapon_access=True,
    strangulation_history=False,
    separation_recent=True,
    threats_to_kill=False,
    stalking_frequency_per_week=2,
)

FAMILY_HOUSEHOLD = dict(household_size=3, minor_children_count=2)


def _client_with_one_corroborating_fact():
    """Open a survivor whose only corroborating fact is a FILED protective order."""
    advocate = seed_hotline_advocate("Rosa Marin")
    legal = seed_legal_advocate("Iris Vale")
    client = seed_client(
        advocate,
        client_code="C-1001",
        legal_name="Alina Ford",
        household_size=1,
        hmis_disclosure_consent="GRANTED",
    )
    seed_filed_case(
        legal,
        client["id"],
        legal.id,
        hearing_start_utc="2026-08-20T09:00:00Z",
        hearing_end_utc="2026-08-20T10:00:00Z",
    )
    return advocate, client


def test_intake_snapshot_scores_48_4_and_stores_no_corroborating_facts():
    """The snapshot variant must ignore the survivor's FILED protective order.

    PRD: "Under `INTAKE_SNAPSHOT` the bonus is zero **and** `corroborating_fact_count`
    is stored as 0 even when corroborating rows plainly exist — the snapshot variant
    does not look at history at all, and its stored count must reflect that."

    Design: Difficulty/dual_variant_calc/risk_scoring_variant_divergence_on_risk_assessment
    """
    advocate, client = _client_with_one_corroborating_fact()
    call = seed_hotline_call(
        advocate,
        client["id"],
        presenting_concerns=(
            "Partner has a handgun and blocked the door after she said she was leaving."
        ),
    )

    response = api_client.create_risk_assessment(
        call["id"],
        create_risk_assessment_payload(corroborate_with_history=False, **MODERATE_FACTOR_INPUTS),
        advocate.headers,
    )

    assessment = validate_success(response, 201)
    assert_risk_assessment(assessment)
    assert_risk_scoring(
        assessment,
        base_subtotal=44.0,
        escalation_multiplier=1.1,
        danger_score=48.4,
        risk_band="MODERATE",
        variant_applied="INTAKE_SNAPSHOT",
        corroborating_fact_count=0,
    )
    survivor = read_client(client["id"], advocate.headers)
    assert survivor["current_danger_score"] == 48.4
    assert survivor["current_risk_band"] == "MODERATE"


def test_corroborated_review_lifts_the_same_factors_to_55_0_and_elevated():
    """Identical factor inputs diverge by exactly the 6-point corroboration bonus.

    PRD: "Under `INTAKE_SNAPSHOT` the score is 48.4 and the band is `MODERATE`; under
    `CORROBORATED_REVIEW` the 6-point bonus lifts the subtotal to 50 and the score to
    55.0, landing in `ELEVATED`."

    Design: Difficulty/dual_variant_calc/risk_scoring_variant_divergence_on_risk_assessment
    """
    advocate, client = _client_with_one_corroborating_fact()
    first_call = seed_hotline_call(
        advocate,
        client["id"],
        presenting_concerns=(
            "Partner has a handgun and blocked the door after she said she was leaving."
        ),
    )
    snapshot = seed_risk_assessment(
        advocate, first_call["id"], corroborate_with_history=False, **MODERATE_FACTOR_INPUTS
    )
    second_call = seed_hotline_call(
        advocate,
        client["id"],
        presenting_concerns="Supervisory call-back to re-read the same factors against her file.",
    )

    response = api_client.create_risk_assessment(
        second_call["id"],
        create_risk_assessment_payload(corroborate_with_history=True, **MODERATE_FACTOR_INPUTS),
        advocate.headers,
    )

    review = validate_success(response, 201)
    assert_risk_assessment(review)
    assert_risk_scoring(
        review,
        base_subtotal=50.0,
        escalation_multiplier=1.1,
        danger_score=55.0,
        risk_band="ELEVATED",
        variant_applied="CORROBORATED_REVIEW",
        corroborating_fact_count=1,
    )
    assert review["escalation_multiplier"] == snapshot["escalation_multiplier"]
    assert round(review["danger_score"] - snapshot["danger_score"], 1) == 6.6
    survivor = read_client(client["id"], advocate.headers)
    assert survivor["current_danger_score"] == 55.0
    assert survivor["current_risk_band"] == "ELEVATED"


def test_projected_stay_cost_estimates_one_surcharge_night_at_reservation():
    """The projected variant estimates weekend nights statistically, reaching 57000.

    PRD: "The `PROJECTED` variant is computed once at reservation, stored in
    `projected_stay_cost_cents`, and never revised afterwards."

    Design: Difficulty/dual_variant_calc/stay_cost_projected_vs_settled_on_shelter_admission
    """
    scene = seed_shelter_scene(unit_overrides={"unit_type": "FAMILY_SUITE"})

    _scene, _client, _request, admission = seed_reserved_admission(
        scene=scene,
        client_overrides=dict(client_code="C-2001", legal_name="Alina Ford", **FAMILY_HOUSEHOLD),
    )

    assert_shelter_admission(admission)
    assert admission["projected_stay_cost_cents"] == 57000
    assert admission["settled_stay_cost_cents"] is None
    assert admission["occupancy_status"] == "RESERVED"
    assert admission["school_enrollment_status"] == "PENDING"


def test_settled_walk_charges_two_real_surcharge_nights_and_banks_59500():
    """The settled walk finds the genuine Friday and Saturday nights the estimate missed.

    PRD: "But the projected estimate rounds five times two divided by seven to a single
    surcharge night and reports 57000, whereas the settled walk finds two genuine
    surcharge nights — Friday the 7th and Saturday the 8th — and reports 59500."

    Design: Difficulty/dual_variant_calc/stay_cost_projected_vs_settled_on_shelter_admission
    """
    scene = seed_shelter_scene(unit_overrides={"unit_type": "FAMILY_SUITE"})
    _scene, _client, _request, admission = seed_checked_in_admission(
        scene=scene,
        client_overrides=dict(client_code="C-2001", legal_name="Alina Ford", **FAMILY_HOUSEHOLD),
        check_in_overrides={"school_enrollment_confirmed": True},
        entry_clock="2026-08-07T09:00:00Z",
    )
    projected_at_reservation = admission["projected_stay_cost_cents"]
    advance_clock("2026-08-12T09:00:00Z")

    response = exit_household(
        scene, admission["id"], "2026-08-12", exit_destination="FAMILY_FRIENDS"
    )

    exited = validate_success(response, 200)
    assert exited["occupancy_status"] == "EXITED"
    assert exited["settled_stay_cost_cents"] == 59500
    assert exited["projected_stay_cost_cents"] == projected_at_reservation == 57000
    assert exited["settled_stay_cost_cents"] - exited["projected_stay_cost_cents"] == 2500
    assert exited["school_enrollment_status"] == "ENROLLED"
    assert read_admission(scene.manager, admission["id"])["settled_stay_cost_cents"] == 59500
    assert read_shelter(scene.manager, scene.shelter["id"])["settled_revenue_cents"] == 59500
