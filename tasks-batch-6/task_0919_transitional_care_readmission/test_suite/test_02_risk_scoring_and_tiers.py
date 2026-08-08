"""Readmission risk scoring, the tier fork and the re-assessment cascade."""
from test_helpers import (
    ADMIN,
    assert_risk_assessment,
    assert_risk_components,
    assert_same_instant,
    book_visit,
    connect_contact,
    current_assessment,
    read_episode,
    setup_episode,
    setup_program,
    setup_program_with_episode,
    validate_paginated,
    validate_success,
)

# Held identical across the two length-of-stay variants so only the fork moves.
_SHARED_LOS_INPUTS = dict(
    admission_acuity="URGENT",
    comorbidity_count=2,
    prior_ed_visits_6mo=1,
    prior_admissions_6mo=3,
    social_risk_flags_count=0,
)


def test_inpatient_length_of_stay_variant_scores_thirty_five_and_bands_high(api):
    """PRD §3.2: "For an inpatient stay, `los_variant` is recorded as
    `INPATIENT_DAYS` and `los_points` is one and a half points for every whole
    day of stay — the number of days multiplied by 1.5, rounded half up to a
    whole number, and then capped at 12 points."
    PRD §3.2: "From the required complexity follows the face-to-face deadline: a
    high-complexity episode's `visit_due_date` is the discharge date plus 7
    calendar days, and a moderate-complexity episode's is the discharge date
    plus 14 calendar days — exactly twice the window from the same discharge
    date."

    Design: Difficulty/dual_variant_calc/risk_los_inpatient_days_vs_observation_hours_flips_tier
    """
    ctx = setup_program()
    ep = setup_episode(
        ctx, stay_type="INPATIENT", length_of_stay_days=4, **_SHARED_LOS_INPUTS
    )
    assessment = current_assessment(ctx, ep["episode_id"])
    assert_risk_assessment(assessment)
    assert assessment["los_variant"] == "INPATIENT_DAYS"
    assert_risk_components(
        assessment,
        los_points=6,
        acuity_points=6,
        comorbidity_points=5,
        utilization_points=18,
        social_modifier_points=0,
        risk_score=35,
    )
    assert assessment["risk_tier"] == "HIGH"
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_score"] == 35
    assert episode["risk_tier"] == "HIGH"
    assert episode["required_visit_complexity"] == "HIGH_COMPLEXITY"
    assert episode["visit_due_date"] == "2026-05-08"


def test_observation_length_of_stay_variant_scores_thirty_one_and_bands_moderate(api):
    """PRD §3.2: "For an observation stay, `los_variant` is recorded as
    `OBSERVATION_HOURS` and `los_points` is one point for every twelve hours —
    the number of hours divided by 12, rounded half up to a whole number, and
    then capped at 6 points."
    PRD §3.2: "`required_visit_complexity` is `HIGH_COMPLEXITY` for `HIGH` and
    `SEVERE` episodes and `MODERATE_COMPLEXITY` for `LOW` and `MODERATE`
    episodes."

    Design: Difficulty/dual_variant_calc/risk_los_inpatient_days_vs_observation_hours_flips_tier
    """
    ctx = setup_program()
    ep = setup_episode(
        ctx, stay_type="OBSERVATION", length_of_stay_hours=24, **_SHARED_LOS_INPUTS
    )
    assessment = current_assessment(ctx, ep["episode_id"])
    assert assessment["los_variant"] == "OBSERVATION_HOURS"
    assert_risk_components(
        assessment,
        los_points=2,
        acuity_points=6,
        comorbidity_points=5,
        utilization_points=18,
        social_modifier_points=0,
        risk_score=31,
    )
    assert assessment["risk_tier"] == "MODERATE"
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_score"] == 31
    assert episode["risk_tier"] == "MODERATE"
    assert episode["required_visit_complexity"] == "MODERATE_COMPLEXITY"
    assert episode["visit_due_date"] == "2026-05-15"


def test_each_risk_component_is_rounded_half_up_on_its_own(api):
    """PRD §2.8: "Risk points are whole integers. The rounding is applied **per
    component, before the components are summed**: each of the five risk
    components is rounded to a whole number on its own, and only then are the
    five whole numbers added together."
    PRD §3.2: "`comorbidity_points` is two and a half points per active chronic
    condition on the discharge problem list — the `comorbidity_count` multiplied
    by 2.5, rounded half up to a whole number — capped at 20 points."

    Design: Difficulty/combinatorial_formula/risk_score_rounds_each_component_before_summing
    """
    ctx, ep = setup_program_with_episode()
    assessment = current_assessment(ctx, ep["episode_id"])
    # comorbidity_count 5 -> raw 12.5 -> 13, social_risk_flags_count 3 -> 7.5 -> 8.
    assert assessment["comorbidity_points"] == 13
    assert assessment["social_modifier_points"] == 8
    assert assessment["los_points"] == 6
    assert assessment["acuity_points"] == 6
    assert assessment["utilization_points"] == 11


def test_risk_score_sums_the_rounded_components_never_the_raw_products(api):
    """PRD §2.8: "Summing the raw products first and rounding the total once is
    a different calculation that produces a different score for the same inputs,
    and it is not what this system does."
    PRD §3.2: "Only once all five components are whole numbers are they added,
    and the sum is then capped at 60 to yield `risk_score`."

    Design: Difficulty/combinatorial_formula/risk_score_rounds_each_component_before_summing
    """
    ctx, ep = setup_program_with_episode()
    assessment = current_assessment(ctx, ep["episode_id"])
    assert assessment["risk_score"] == 44, (
        "6 + 6 + 13 + 11 + 8 = 44; summing the raw products first would give 43"
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_score"] == 44
    assert episode["risk_tier"] == "HIGH"
    assert episode["required_visit_complexity"] == "HIGH_COMPLEXITY"


def test_score_of_thirty_two_bands_into_the_high_tier(api):
    """PRD §3.2: "The boundaries are worth stating exactly: 17 is `LOW`, 18 is
    `MODERATE`, 31 is `MODERATE`, 32 is `HIGH`, 44 is `HIGH` and 45 is
    `SEVERE`."

    Design: Difficulty/boundary_precision_check/risk_tier_boundary_31_moderate_vs_32_high
    """
    ctx = setup_program()
    ep = setup_episode(
        ctx,
        stay_type="INPATIENT",
        length_of_stay_days=2,
        admission_acuity="URGENT",
        comorbidity_count=2,
        prior_ed_visits_6mo=1,
        prior_admissions_6mo=3,
        social_risk_flags_count=0,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_score"] == 32
    assert episode["risk_tier"] == "HIGH"
    assert episode["required_visit_complexity"] == "HIGH_COMPLEXITY"
    assert episode["visit_due_date"] == "2026-05-08"
    assert episode["contact_sla_business_days"] == 2
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )


def test_score_of_thirty_one_stays_in_the_moderate_tier(api):
    """PRD §3.2: "A score of 45 or more is `SEVERE`; a score from 32 through 44
    is `HIGH`; a score from 18 through 31 is `MODERATE`; anything below 18 is
    `LOW`."
    PRD §3.2: "From the required complexity follows the face-to-face deadline: a
    high-complexity episode's `visit_due_date` is the discharge date plus 7
    calendar days, and a moderate-complexity episode's is the discharge date
    plus 14 calendar days — exactly twice the window from the same discharge
    date."

    Design: Difficulty/boundary_precision_check/risk_tier_boundary_31_moderate_vs_32_high
    """
    ctx = setup_program()
    ep = setup_episode(ctx, tier="MODERATE")
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_score"] == 31
    assert episode["risk_tier"] == "MODERATE"
    assert episode["required_visit_complexity"] == "MODERATE_COMPLEXITY"
    assert episode["visit_due_date"] == "2026-05-15"
    assert episode["contact_sla_business_days"] == 2
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-05T23:59:59.999Z", "contact_deadline_at"
    )


def test_reassessment_supersedes_its_predecessor_and_retunes_the_episode(api):
    """PRD §3.2: "The first hop creates a new `RiskAssessment` with `is_current`
    true and `supersedes_id` pointing at the assessment it replaces, and flips
    that predecessor's `is_current` to false; exactly one assessment per episode
    is ever current, and the superseded rows remain readable."
    PRD §3.2: "The second hop rewrites the episode's `risk_score`, `risk_tier`,
    `current_risk_assessment_id`, `contact_sla_business_days`,
    `required_visit_complexity`, `contact_deadline_at` and `visit_due_date` from
    the new assessment."

    Design: Difficulty/transitive_cascade/risk_reassessment_four_hop_cascade
    """
    ctx = setup_program()
    ep = setup_episode(ctx, tier="MODERATE")
    original = current_assessment(ctx, ep["episode_id"])
    before = read_episode(ctx, ep["episode_id"])
    assert before["risk_score"] == 31
    assert before["risk_tier"] == "MODERATE"
    assert before["visit_due_date"] == "2026-05-15"

    connect_contact(ctx, ep)
    new_assessment = validate_success(
        api.create_risk_assessment(
            ep["episode_id"],
            {
                "comorbidity_count": 5,
                "prior_ed_visits_6mo": 2,
                "prior_admissions_6mo": 1,
                "social_risk_flags_count": 3,
            },
            ep["nav_headers"],
        ),
        201,
    )
    assert new_assessment["risk_score"] == 41
    assert new_assessment["risk_tier"] == "HIGH"
    assert new_assessment["is_current"] is True
    assert new_assessment["supersedes_id"] == original["id"]
    assert_risk_components(
        new_assessment,
        los_points=3,
        comorbidity_points=13,
        utilization_points=11,
        social_modifier_points=8,
    )

    predecessor = validate_success(api.get_risk_assessment(original["id"], ADMIN))
    assert predecessor["is_current"] is False

    after = read_episode(ctx, ep["episode_id"])
    assert after["risk_score"] == 41
    assert after["risk_tier"] == "HIGH"
    assert after["current_risk_assessment_id"] == new_assessment["id"]
    assert after["required_visit_complexity"] == "HIGH_COMPLEXITY"
    assert after["visit_due_date"] == "2026-05-08"


def test_reassessment_flips_a_late_visit_and_spawns_a_window_red_flag(api):
    """PRD §3.2: "The third hop pushes the new figures down onto every
    non-terminal visit of the episode, refreshing each visit's
    `required_complexity`, `visit_due_date` and `deadline_status`; a visit still
    in `SCHEDULED` whose `scheduled_start` now falls past the newly tightened
    due instant flips its `deadline_status` from `SCHEDULED_IN_WINDOW` to
    `SCHEDULED_LATE`."
    PRD §3.2: "The fourth hop reacts to that: **each** visit that flipped to
    `SCHEDULED_LATE` spawns a red flag with `category` `VISIT_WINDOW_AT_RISK`
    and tier `TIER_2`, increasing the episode's `open_red_flag_count` and
    setting its `escalation_state` to `ACTIVE`."

    Design: Difficulty/transitive_cascade/risk_reassessment_four_hop_cascade
    """
    ctx = setup_program()
    ep = setup_episode(ctx, tier="MODERATE")
    connect_contact(ctx, ep)
    visit = book_visit(
        ctx, ep, start="2026-05-12T09:00:00Z", end="2026-05-12T10:00:00Z"
    )
    assert visit["deadline_status"] == "SCHEDULED_IN_WINDOW"

    validate_success(
        api.create_risk_assessment(
            ep["episode_id"],
            {
                "comorbidity_count": 5,
                "prior_ed_visits_6mo": 2,
                "prior_admissions_6mo": 1,
                "social_risk_flags_count": 3,
            },
            ep["nav_headers"],
        ),
        201,
    )

    updated = validate_success(api.get_visit(visit["id"], ADMIN))
    assert updated["required_complexity"] == "HIGH_COMPLEXITY"
    assert updated["visit_due_date"] == "2026-05-08"
    assert updated["deadline_status"] == "SCHEDULED_LATE"

    flags, meta = validate_paginated(
        api.list_red_flags(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert meta["total_count"] == 1
    assert flags[0]["category"] == "VISIT_WINDOW_AT_RISK"
    assert flags[0]["tier"] == "TIER_2"
    assert flags[0]["status"] == "RAISED"

    episode = read_episode(ctx, ep["episode_id"])
    assert episode["open_red_flag_count"] == 1
    assert episode["escalation_state"] == "ACTIVE"


def test_severe_tier_compresses_the_contact_window_to_one_business_day(api):
    """PRD §3.2: "`contact_sla_business_days` is 1 for a `SEVERE` episode and 2
    for `LOW`, `MODERATE` and `HIGH` alike — the severe tier is the only one
    that compresses the follow-up window."
    PRD §3.3: "When N business days have been consumed, the deadline is the end
    of the day reached, that is that date with `T23:59:59.999Z` appended."

    Design: Corner/calculations/severe_tier_uses_one_business_day_contact_sla
    """
    ctx = setup_program()
    ep = setup_episode(ctx, tier="SEVERE", discharge_disposition="HOME_HEALTH")
    assessment = current_assessment(ctx, ep["episode_id"])
    assert_risk_components(
        assessment,
        los_points=12,
        acuity_points=10,
        comorbidity_points=20,
        utilization_points=24,
        social_modifier_points=10,
        risk_score=60,
    )
    episode = read_episode(ctx, ep["episode_id"])
    assert episode["risk_tier"] == "SEVERE"
    assert episode["contact_sla_business_days"] == 1
    assert episode["required_visit_complexity"] == "HIGH_COMPLEXITY"
    assert_same_instant(
        episode["contact_deadline_at"], "2026-05-04T23:59:59.999Z", "contact_deadline_at"
    )
    assert episode["visit_due_date"] == "2026-05-08"


def test_successor_assessment_is_reachable_through_the_supersedes_filter(api):
    """PRD §3.2: "Risk assessments may be read individually — showing all five
    component scores — or listed filtered by `episode_id`, by `supersedes_id`
    and by `is_current`."
    PRD §2.5: "An episode records `current_risk_assessment_id` and `claim_id`,
    and risk assessments can be listed filtered by `episode_id`, by
    `supersedes_id` and by `is_current`, while claims can be listed filtered by
    `episode_id`, `patient_id`, `visit_id`, `payer_id` and `status`."

    Design: Corner/entities/risk_assessment_self_reference_discoverable_via_supersedes_filter
    """
    ctx = setup_program()
    ep = setup_episode(ctx, tier="MODERATE")
    original = current_assessment(ctx, ep["episode_id"])
    successor = validate_success(
        api.create_risk_assessment(
            ep["episode_id"],
            {
                "comorbidity_count": 5,
                "prior_ed_visits_6mo": 2,
                "prior_admissions_6mo": 1,
                "social_risk_flags_count": 3,
            },
            ep["nav_headers"],
        ),
        201,
    )
    rows, meta = validate_paginated(
        api.list_risk_assessments(ADMIN, params={"supersedes_id": original["id"]})
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == successor["id"]
    assert rows[0]["supersedes_id"] == original["id"]

    _, all_meta = validate_paginated(
        api.list_risk_assessments(ADMIN, params={"episode_id": ep["episode_id"]})
    )
    assert all_meta["total_count"] == 2
    assert validate_success(api.get_risk_assessment(original["id"], ADMIN))["is_current"] is False
    assert validate_success(api.get_risk_assessment(successor["id"], ADMIN))["is_current"] is True
