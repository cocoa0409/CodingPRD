"""The arithmetic a residency runs on: the pinned session-fee ladder, the two
reimbursement constants, the portfolio composite, the reliability input set, and
the renormalised evaluation index."""
from test_helpers import (
    ApiErrorId,
    OBSERVER_USER_ID,
    TEST_USERS,
    advance_vetting,
    api_client,
    attach_observation_rubric,
    attach_student_work_sample,
    attach_teacher_survey,
    cancel_session_as_artist,
    cancel_session_as_liaison,
    create_artist_applicant,
    create_confirmed_session,
    create_deliver_payload,
    create_delivered_session,
    create_roster_status_payload,
    deliver_session,
    make_teaching_artist_headers,
    read_artist,
    read_residency,
    read_session,
    record_portfolio_review,
    schedule_session,
    set_clock_to_default,
    set_roster_status,
    setup_active_residency,
    validate_error,
)

PD = TEST_USERS["program_director_headers"]


# ==========================================================================
# The session fee for a bilingual lead on a graded dance residency
# ==========================================================================
def _bilingual_dance_residency_with_one_confirmed_session() -> dict:
    """An APPRENTICE lead teaching a G3_5 DANCE residency in Spanish, with one
    confirmed 60-minute session holding its full-length projection."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_confirmed_session(
        scenario, session_date="2026-09-15"
    )
    return scenario


def test_full_length_dance_delivery_prices_off_the_discipline_base_rate(api):
    """PRD §3.7: "Start from the base rate for the residency's `discipline`:
    11,000 cents for `VISUAL_ARTS`, 12,000 for `DANCE`, 12,500 for `MUSIC`,
    11,500 for `THEATER`, 13,000 for `MEDIA_ARTS`, and 10,500 for
    `LITERARY_ARTS`."
    PRD §3.7: "Multiply by the grade-band factor for the residency's
    `grade_band` and round: 1.00 for `K_2`, 1.05 for `G3_5`, 1.10 for `G6_8`, and
    1.15 for `G9_12`."
    PRD §3.7: "Multiply that graded amount by the factor for the artist's
    `roster_tier_effective` and round: 0.90 for `APPRENTICE`, 1.00 for
    `TEACHING_ARTIST`, and 1.20 for `MASTER`."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."

    Design: Corner/Calculations/session_fee_correct_result_for_lead_apprentice_bilingual_dance
    """
    scenario = _bilingual_dance_residency_with_one_confirmed_session()
    assert scenario["artist"]["roster_tier_effective"] == "APPRENTICE", (
        "an APPRENTICE assignment with no promotion in sight stays APPRENTICE, "
        f"got {scenario['artist']['roster_tier_effective']}"
    )

    delivered = deliver_session(
        scenario["session"]["id"],
        scenario["artist"]["id"],
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    assert delivered["fee_cents"] == 13974, (
        "DANCE 12000, graded by 1.05 to 12600, tiered by 0.90 to 11340, plus "
        f"the 1134 lead premium and the flat 1500 language premium, got "
        f"{delivered['fee_cents']}"
    )
    assert delivered["travel_reimbursement_cents"] == 0, (
        "0.0 miles is below the 10.0 absorbed miles, got "
        f"{delivered['travel_reimbursement_cents']}"
    )
    assert delivered["materials_reimbursement_cents"] == 0, (
        "no materials were bought, got "
        f"{delivered['materials_reimbursement_cents']}"
    )
    assert delivered["payable_cents"] == 13974, (
        f"expected 13974 + 0 + 0, got {delivered['payable_cents']}"
    )
    assert delivered["status"] == "DELIVERED"


def test_lead_and_language_premiums_ride_on_the_full_length_projection(api):
    """PRD §3.7: "Compute a lead premium of ten percent (a factor of 0.10) of
    that tiered amount, rounded, but only when the session's
    `assigned_artist_id` equals the residency's `lead_artist_id`; otherwise the
    premium is zero."
    PRD §3.7: "Compute a language premium of a flat 1,500 cents, but only when
    the residency's `instruction_language` is something other than `en` **and**
    that language appears in the artist's `languages`; otherwise it is zero."
    PRD §3.7: "Round `minutes_delivered` **up** to the next whole 5-minute block
    to get billed minutes, then form the proration factor as billed minutes
    divided by the residency's `session_length_minutes`, capped at 1.00 so
    overtime is never paid."
    PRD §2.12: "The **money ledger** partitions the budget across three
    accounts: `encumbered_cents`, the sum of the amounts currently held by this
    residency's sessions; `disbursed_cents`, the sum of `total_cents` over this
    residency's `APPROVED` vouchers; and `available_cents`, which is
    `budget_cents` less encumbered less disbursed."

    Design: Corner/Calculations/session_fee_correct_result_for_lead_apprentice_bilingual_dance
    """
    scenario = _bilingual_dance_residency_with_one_confirmed_session()
    assert scenario["session"]["encumbered_cents"] == 13974, (
        "the confirmation projection already carries both premiums, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    delivered = deliver_session(
        scenario["session"]["id"],
        scenario["artist"]["id"],
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    assert delivered["minutes_delivered"] == 60, (
        "60 minutes rounds up to 60 billed minutes, so the proration factor is "
        f"exactly 60/60, got {delivered['minutes_delivered']}"
    )
    assert delivered["fee_cents"] == 13974, (
        "11340 tiered plus 1134 lead plus 1500 language, unprorated, got "
        f"{delivered['fee_cents']}"
    )
    assert delivered["fee_cents"] != 11340, (
        "dropping both premiums leaves only the tiered amount"
    )
    assert delivered["encumbered_cents"] == 13974, (
        "a full-length delivery holds exactly what confirmation projected, got "
        f"{delivered['encumbered_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 13974, (
        f"one session holds its payable, got {residency['encumbered_cents']}"
    )
    assert residency["disbursed_cents"] == 0, (
        f"no voucher has been approved, got {residency['disbursed_cents']}"
    )
    assert residency["available_cents"] == 186026, (
        f"expected 200000 less 13974 less 0, got {residency['available_cents']}"
    )


# ==========================================================================
# The two reimbursement constants: absorbed mileage and the materials cap
# ==========================================================================
def _two_confirmed_sessions_for_reimbursement() -> dict:
    """Two confirmed 60-minute sessions of the same residency, ready to report
    different mileage and materials spend."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session_one"] = create_confirmed_session(
        scenario, session_date="2026-09-15"
    )
    scenario["session_two"] = create_confirmed_session(
        scenario, session_date="2026-09-22"
    )
    return scenario


def test_absorbed_mileage_is_subtracted_before_the_per_mile_rate(api):
    """PRD §3.7: "The first 10.0 miles of each session's travel are absorbed by
    the organization."
    PRD §3.7: "Billable miles are `travel_miles` less 10.0, floored at zero, and
    `travel_reimbursement_cents` is billable miles multiplied by 67 cents per
    mile, rounded half up."
    PRD §3.7: "Each session's reimbursement is rounded on its own before any
    voucher sums it."

    Design: Corner/Calculations/reimbursement_applies_free_mileage_then_materials_cap
    """
    scenario = _two_confirmed_sessions_for_reimbursement()
    artist_id = scenario["artist"]["id"]

    far = deliver_session(
        scenario["session_one"]["id"],
        artist_id,
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    assert far["travel_reimbursement_cents"] == 704, (
        "20.5 miles less the 10.0 absorbed leaves 10.5 billable, and 10.5 at 67 "
        f"cents is 703.5 which rounds half up to 704, got "
        f"{far['travel_reimbursement_cents']}"
    )

    near = deliver_session(
        scenario["session_two"]["id"],
        artist_id,
        students_present_count=24,
        minutes_delivered=60,
        travel_miles=8.0,
        materials_spend_cents=1200,
    )
    assert near["travel_reimbursement_cents"] == 0, (
        "8.0 miles less 10.0 floors at zero billable miles rather than becoming "
        f"a negative credit, got {near['travel_reimbursement_cents']}"
    )


def test_materials_cap_truncates_overspend_but_leaves_a_small_claim_alone(api):
    """PRD §3.7: "`materials_reimbursement_cents` is the lesser of the reported
    `materials_spend_cents` and a per-session cap of 2,500 cents — the
    residency's `materials_stipend_cents` earmark does not raise or lower that
    cap."
    PRD §3.7: "The session's `payable_cents` is the sum of `fee_cents`,
    `travel_reimbursement_cents`, and `materials_reimbursement_cents`."
    PRD §3.7: "The residency's `sessions_open_count` loses one,
    `sessions_delivered_count` gains one, and both `earned_to_date_cents` and
    `projected_cost_cents` are recomputed."
    PRD §2.12: "The **money ledger** partitions the budget across three
    accounts: `encumbered_cents`, the sum of the amounts currently held by this
    residency's sessions; `disbursed_cents`, the sum of `total_cents` over this
    residency's `APPROVED` vouchers; and `available_cents`, which is
    `budget_cents` less encumbered less disbursed."

    Design: Corner/Calculations/reimbursement_applies_free_mileage_then_materials_cap
    """
    scenario = _two_confirmed_sessions_for_reimbursement()
    artist_id = scenario["artist"]["id"]

    far = deliver_session(
        scenario["session_one"]["id"],
        artist_id,
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=20.5,
        materials_spend_cents=3000,
    )
    assert far["materials_reimbursement_cents"] == 2500, (
        "3000 cents of spend is truncated to the 2500 per-session cap even "
        "though the residency earmarked a 5000 stipend, got "
        f"{far['materials_reimbursement_cents']}"
    )
    assert far["payable_cents"] == 17178, (
        f"expected 13974 + 704 + 2500, got {far['payable_cents']}"
    )

    near = deliver_session(
        scenario["session_two"]["id"],
        artist_id,
        students_present_count=24,
        minutes_delivered=60,
        travel_miles=8.0,
        materials_spend_cents=1200,
    )
    assert near["materials_reimbursement_cents"] == 1200, (
        "1200 cents is under the cap and passes through untouched, got "
        f"{near['materials_reimbursement_cents']}"
    )
    assert near["payable_cents"] == 15174, (
        f"expected 13974 + 0 + 1200, got {near['payable_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["sessions_delivered_count"] == 2, (
        "both sessions moved out of the open bucket into the delivered one, got "
        f"{residency['sessions_delivered_count']}"
    )
    assert residency["encumbered_cents"] == 32352, (
        f"expected 17178 + 15174, got {residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 167648, (
        f"expected 200000 less 32352, got {residency['available_cents']}"
    )


# ==========================================================================
# The portfolio composite lands on a true halfway value
# ==========================================================================
def test_portfolio_composite_at_a_halfway_value_rounds_away_from_zero(api):
    """PRD §2.5: "Wherever rounding is required, the method is **round half up**
    — a value exactly halfway between two candidates rounds away from zero."
    PRD §3.1: "The panel weights artistic quality at forty percent (a factor of
    0.40), pedagogical clarity at thirty-five percent (0.35), and cultural
    responsiveness at twenty-five percent (0.25): the review's `composite_score`
    is the sum of each score multiplied by its weight, rounded half up to two
    decimal places."
    PRD §3.1: "That composite yields a `recommendation` of `ADVANCE` when it is
    at least 3.50, and `DECLINE` otherwise."
    PRD §3.1: "`portfolio_review_count` is the number of distinct
    `reviewer_user_id` values that have scored this artist, and
    `portfolio_mean_composite` is the arithmetic mean of `composite_score`
    across **all** of the artist's reviews, rounded half up to two decimal
    places; the mean is null while the artist has no reviews at all."

    Design: Corner/Calculations/portfolio_composite_rounds_half_up_not_half_even
    """
    set_clock_to_default()
    artist = create_artist_applicant()
    advance_vetting(artist["id"], "PORTFOLIO_REVIEW")

    review = record_portfolio_review(artist["id"], "panelist-1", 3.1, 3.2, 3.3)
    assert review["composite_score"] == 3.19, (
        "0.40*3.1 + 0.35*3.2 + 0.25*3.3 is exactly 3.185, which rounds half up "
        f"to 3.19, got {review['composite_score']}"
    )
    assert review["composite_score"] != 3.18, (
        "banker's rounding of 3.185 to the even neighbour is the wrong method"
    )
    assert review["recommendation"] == "DECLINE", (
        f"3.19 is below the 3.50 advance threshold, got "
        f"{review['recommendation']}"
    )

    scored = read_artist(artist["id"])
    assert scored["portfolio_review_count"] == 1, (
        "one distinct panelist has scored this artist, got "
        f"{scored['portfolio_review_count']}"
    )
    assert scored["portfolio_mean_composite"] == 3.19, (
        "the mean of a single already-rounded composite is that composite, got "
        f"{scored['portfolio_mean_composite']}"
    )


# ==========================================================================
# Reliability counts only the sessions the artist could have taught
# ==========================================================================
def _one_delivery_and_two_pending_sessions() -> dict:
    """One delivered session plus two still-planned sessions, so a school-caused
    and an artist-caused cancellation can be compared on the same artist."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["delivered"] = create_confirmed_session(
        scenario, session_date="2026-09-15"
    )
    deliver_session(
        scenario["delivered"]["id"],
        scenario["artist"]["id"],
        students_present_count=22,
        minutes_delivered=60,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    scenario["school_side"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-22",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    scenario["artist_side"] = schedule_session(
        scenario["residency"]["id"],
        scenario["artist"]["id"],
        session_date="2026-09-29",
        lesson_plan_id=scenario["lesson_plan"]["id"],
    )
    return scenario


def test_school_caused_cancellation_stays_out_of_the_reliability_denominator(api):
    """PRD §3.2: "The input set is the artist's *terminal, artist-attributable*
    sessions: rows where the artist is either the currently assigned artist or
    the recorded vacated artist, and whose status is `DELIVERED` or
    `CANCELLED_ARTIST`."
    PRD §3.2: "A `CANCELLED_SCHOOL` session is never the artist's fault and is
    excluded from both figures."
    PRD §3.2: "Each session in the set is credited one if it was delivered and
    zero otherwise; the figure in basis points is 10000 multiplied by the number
    of credited sessions, divided by the number of sessions in the set, rounded
    half up to a whole number — and it is defined as zero when the set is
    empty."
    PRD §3.7: "Link three, caused by the rolling figure falling below 8000 basis
    points once the artist has at least four terminal sessions on record, moves
    the artist's `roster_status` from `ACTIVE` to `PROBATION`."

    Design: Corner/Calculations/reliability_input_set_excludes_school_caused_cancellations
    """
    scenario = _one_delivery_and_two_pending_sessions()
    artist_id = scenario["artist"]["id"]

    snowed_out = cancel_session_as_liaison(
        scenario["school_side"]["id"],
        scenario["school"]["id"],
        "SCHOOL_CLOSURE",
        note="snow day",
    )
    assert snowed_out["status"] == "CANCELLED_SCHOOL"

    after_closure = read_artist(artist_id)
    assert after_closure["reliability_bps_rolling"] == 10000, (
        "the only attributable row is the single delivery, so the figure is "
        f"10000 rather than 5000, got {after_closure['reliability_bps_rolling']}"
    )
    assert after_closure["roster_status"] == "ACTIVE"

    fell_ill = cancel_session_as_artist(
        scenario["artist_side"]["id"], artist_id, "ARTIST_ILLNESS",
        note="artist unwell",
    )
    assert fell_ill["status"] == "CANCELLED_ARTIST"

    after_illness = read_artist(artist_id)
    assert after_illness["reliability_bps_rolling"] == 5000, (
        "one delivery credited out of two attributable rows is 5000; counting "
        "the school closure too would give 3333, got "
        f"{after_illness['reliability_bps_rolling']}"
    )
    assert after_illness["roster_status"] == "ACTIVE", (
        "only two terminal sessions exist, below the four the automatic "
        f"probation link requires, got {after_illness['roster_status']}"
    )


def test_reinstatement_from_probation_is_refused_below_the_reliability_floor(api):
    """PRD §3.2: "Moving `ACTIVE → PROBATION` — whether a director does it
    directly or Cascade B does it automatically — requires the artist to
    currently be `ACTIVE`, and it applies the probation tier cap described
    above, which in turn re-projects `projected_cost_cents` on every residency
    that holds an open session of this artist."
    PRD §3.2: "If the artist is on `PROBATION`, `roster_tier_effective` is the
    lower of `roster_tier_assigned` and `TEACHING_ARTIST`, comparing tiers by
    their rank in the ascending order `APPRENTICE`, then `TEACHING_ARTIST`, then
    `MASTER` — never by alphabetical string order."
    PRD §3.2: "Coming back the other way, `PROBATION → ACTIVE` is gated on two
    conditions: the rolling reliability figure must be at least 8000 basis
    points, or the request is refused with `ERR_RELIABILITY_BELOW_FLOOR`; and
    clearance must currently hold, or the refusal is `ERR_ARTIST_NOT_CLEARED`."

    Design: Corner/Calculations/reliability_input_set_excludes_school_caused_cancellations
    """
    scenario = _one_delivery_and_two_pending_sessions()
    artist_id = scenario["artist"]["id"]
    cancel_session_as_liaison(
        scenario["school_side"]["id"],
        scenario["school"]["id"],
        "SCHOOL_CLOSURE",
        note="snow day",
    )
    cancel_session_as_artist(
        scenario["artist_side"]["id"], artist_id, "ARTIST_ILLNESS",
        note="artist unwell",
    )

    on_probation = set_roster_status(
        artist_id, "PROBATION", reason="reliability review"
    )
    assert on_probation["roster_status"] == "PROBATION"
    assert on_probation["roster_tier_effective"] == "APPRENTICE", (
        "the probation cap is the lower of APPRENTICE and TEACHING_ARTIST by "
        f"rank, got {on_probation['roster_tier_effective']}"
    )

    refused = api_client.set_roster_status(
        artist_id,
        create_roster_status_payload("ACTIVE", reason="requesting reinstatement"),
        PD,
    )
    validate_error(
        refused, ApiErrorId.ERR_RELIABILITY_BELOW_FLOOR.value, expected_status=409
    )
    assert read_artist(artist_id)["roster_status"] == "PROBATION", (
        "a rolling figure of 5000 is below the 8000 floor, so the artist stays "
        "on probation"
    )


# ==========================================================================
# The evaluation index renormalises over whichever components exist
# ==========================================================================
def _two_evaluated_deliveries_with_known_headcounts() -> dict:
    """Two delivered sessions with 22 and 24 students present, so the artifact
    denominator is a known 46 encounters."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session_one"] = create_delivered_session(
        scenario, session_date="2026-09-15", students_present_count=22
    )
    scenario["session_two"] = create_delivered_session(
        scenario, session_date="2026-09-22", students_present_count=24
    )
    return scenario


def test_observation_only_index_renormalises_the_surviving_weight_to_one(api):
    """PRD §3.9: "The observation mean is the mean of `rubric_composite` across
    the observation-rubric records, rounded half up to two decimals; it is null
    when there are none."
    PRD §3.9: "**Missing components do not count as zero.**"
    PRD §3.9: "They drop out, and the weights of the surviving components are
    renormalized by dividing each by the sum of the surviving weights."
    PRD §3.9: "When no component survives at all, `evaluation_index` is null."

    Design: Corner/Calculations/evaluation_index_renormalises_weights_over_present_components
    """
    scenario = _two_evaluated_deliveries_with_known_headcounts()
    residency_id = scenario["residency"]["id"]
    assert read_residency(residency_id)["evaluation_index"] is None, (
        "two delivered sessions with no evaluation record leave no surviving "
        "component"
    )

    attach_observation_rubric(scenario["session_one"]["id"], OBSERVER_USER_ID, 4, 3, 4)
    attach_observation_rubric(scenario["session_two"]["id"], OBSERVER_USER_ID, 3, 3, 4)

    residency = read_residency(residency_id)
    assert residency["evaluation_index"] == 87.5, (
        "the observation mean of 3.67 and 3.33 is 3.50, normalized to 0.875, "
        "and its 0.50 weight renormalizes to 1.00, so the index is 87.5, got "
        f"{residency['evaluation_index']}"
    )
    assert residency["evaluation_index"] != 43.8, (
        "treating the absent survey and artifact components as zero would halve "
        "the index"
    )


def test_index_reweights_when_survey_and_artifact_components_arrive(api):
    """PRD §3.9: "For an observation rubric the server derives
    `rubric_composite` as the three rubric scores added together, divided by
    three, rounded half up to two decimal places; for the other two types
    `rubric_composite` stays null."
    PRD §3.9: "The artifact rate is the total `student_work_artifact_count`
    across the student-work-sample records divided by the total
    `students_present_count` across those delivered sessions, capped at 1, and
    kept at full precision rather than rounded; it is null when there is no
    student-work-sample record or when the summed headcount is zero."
    PRD §3.9: "Each surviving component is normalized to a zero-to-one scale —
    the observation mean by dividing by 4, the survey mean by dividing by 5, and
    the artifact rate as it already stands — and carries a nominal weight of
    0.50, 0.30, and 0.20 respectively."
    PRD §3.9: "`evaluation_index` is then 100 multiplied by the weighted sum of
    the surviving normalized values, rounded half up to one decimal place, on a
    scale from 0.0 to 100.0."

    Design: Corner/Calculations/evaluation_index_renormalises_weights_over_present_components
    """
    scenario = _two_evaluated_deliveries_with_known_headcounts()
    school_id = scenario["school"]["id"]
    first_id = scenario["session_one"]["id"]
    second_id = scenario["session_two"]["id"]

    first_rubric = attach_observation_rubric(first_id, OBSERVER_USER_ID, 4, 3, 4)
    second_rubric = attach_observation_rubric(second_id, OBSERVER_USER_ID, 3, 3, 4)
    assert first_rubric["rubric_composite"] == 3.67, (
        f"4 + 3 + 4 over three is 3.6667, got {first_rubric['rubric_composite']}"
    )
    assert second_rubric["rubric_composite"] == 3.33, (
        f"3 + 3 + 4 over three is 3.3333, got {second_rubric['rubric_composite']}"
    )

    attach_teacher_survey(first_id, school_id, "teacher-delgado", 5)
    attach_teacher_survey(second_id, school_id, "teacher-delgado", 4)
    attach_student_work_sample(first_id, school_id, "teacher-delgado", 10)
    attach_student_work_sample(second_id, school_id, "teacher-delgado", 12)

    residency = read_residency(scenario["residency"]["id"])
    assert residency["evaluation_index"] == 80.3, (
        "0.50*(3.50/4) + 0.30*(4.50/5) + 0.20*(22/46) is 0.803152, so the index "
        f"is 80.3, got {residency['evaluation_index']}"
    )


# ==========================================================================
# The projection at confirmation versus the recomputed fee at delivery
# ==========================================================================
def _planned_then_confirmed_session() -> dict:
    """One confirmed 60-minute session whose hold is the full-length
    projection, ready for an under-length delivery attempt."""
    set_clock_to_default()
    scenario = setup_active_residency()
    scenario["session"] = create_confirmed_session(
        scenario, session_date="2026-09-15"
    )
    return scenario


def test_confirmation_projects_full_length_and_an_under_half_report_is_refused(api):
    """PRD §3.6: "The server evaluates the session fee rules of §3.7 as though
    the artist had taught the full `session_length_minutes`, writes that amount
    into the session's own `encumbered_cents`, adds it to the residency's
    `encumbered_cents`, and recomputes `available_cents`."
    PRD §3.7: "At least half the scheduled length must have been taught —
    `minutes_delivered` must be at least the residency's
    `session_length_minutes` multiplied by one half and rounded **up** to a
    whole minute — or the refusal is `ERR_SESSION_UNDERDELIVERED` at HTTP 422."
    PRD §2.12: "The **money ledger** partitions the budget across three
    accounts: `encumbered_cents`, the sum of the amounts currently held by this
    residency's sessions; `disbursed_cents`, the sum of `total_cents` over this
    residency's `APPROVED` vouchers; and `available_cents`, which is
    `budget_cents` less encumbered less disbursed."

    Design: Corner/Calculations/fee_projection_at_confirmation_versus_actual_at_delivery
    """
    scenario = _planned_then_confirmed_session()
    assert scenario["session"]["encumbered_cents"] == 13974, (
        "the projection prices a full 60 minutes, got "
        f"{scenario['session']['encumbered_cents']}"
    )

    projected = read_residency(scenario["residency"]["id"])
    assert projected["encumbered_cents"] == 13974, (
        "the residency holds the one session's projection, got "
        f"{projected['encumbered_cents']}"
    )
    assert projected["available_cents"] == 186026, (
        f"expected 200000 less 13974, got {projected['available_cents']}"
    )

    refused = api_client.deliver_session(
        scenario["session"]["id"],
        create_deliver_payload(
            students_present_count=20,
            minutes_delivered=25,
            travel_miles=0.0,
            materials_spend_cents=0,
        ),
        make_teaching_artist_headers(scenario["artist"]["id"]),
    )
    validate_error(
        refused, ApiErrorId.ERR_SESSION_UNDERDELIVERED.value, expected_status=422
    )

    still_held = read_session(scenario["session"]["id"])
    assert still_held["status"] == "CONFIRMED", (
        "25 minutes is under the 30-minute floor, so nothing was delivered"
    )
    assert still_held["encumbered_cents"] == 13974, (
        "the refused report must leave the projection standing, got "
        f"{still_held['encumbered_cents']}"
    )
    unchanged = read_residency(scenario["residency"]["id"])
    assert unchanged["available_cents"] == 186026, (
        "a refusal moves no money, so 200000 less 13974 still stands, got "
        f"{unchanged['available_cents']}"
    )


def test_half_length_delivery_replaces_the_projection_with_the_prorated_fee(api):
    """PRD §3.7: "Round `minutes_delivered` **up** to the next whole 5-minute
    block to get billed minutes, then form the proration factor as billed
    minutes divided by the residency's `session_length_minutes`, capped at 1.00
    so overtime is never paid."
    PRD §3.7: "Multiply the clamped amount by the proration factor and round
    half up."
    PRD §3.7: "The money held by the session is swapped for the real figure: the
    residency's `encumbered_cents` gains the difference between `payable_cents`
    and what the session was holding, the session's `encumbered_cents` becomes
    `payable_cents`, and `available_cents` is recomputed."
    PRD §3.4: "`earned_to_date_cents` is the chronological, backward-looking
    figure: the sum of `payable_cents` over this residency's `DELIVERED`
    sessions, at the actual fees and reimbursements recorded at delivery, with
    real prorated minutes and real mileage."

    Design: Corner/Calculations/fee_projection_at_confirmation_versus_actual_at_delivery
    """
    scenario = _planned_then_confirmed_session()
    delivered = deliver_session(
        scenario["session"]["id"],
        scenario["artist"]["id"],
        students_present_count=20,
        minutes_delivered=30,
        travel_miles=0.0,
        materials_spend_cents=0,
    )
    assert delivered["minutes_delivered"] == 30, (
        "30 minutes is exactly half the scheduled length and is payable"
    )
    assert delivered["fee_cents"] == 6987, (
        "30 minutes rounds up to 30 billed minutes, a proration factor of "
        f"30/60 against the 13974 clamped amount, got {delivered['fee_cents']}"
    )
    assert delivered["payable_cents"] == 6987, (
        f"expected 6987 + 0 + 0, got {delivered['payable_cents']}"
    )
    assert delivered["status"] == "DELIVERED", (
        "a report at exactly the half-length floor is accepted"
    )
    assert delivered["encumbered_cents"] == 6987, (
        "the 13974 hold is swapped for the real payable, got "
        f"{delivered['encumbered_cents']}"
    )

    residency = read_residency(scenario["residency"]["id"])
    assert residency["encumbered_cents"] == 6987, (
        "the residency's hold follows the session's down from 13974, got "
        f"{residency['encumbered_cents']}"
    )
    assert residency["available_cents"] == 193013, (
        f"expected 200000 less 6987, got {residency['available_cents']}"
    )
    assert residency["earned_to_date_cents"] == 6987, (
        "the backward-looking figure reads the actual prorated payable, got "
        f"{residency['earned_to_date_cents']}"
    )
