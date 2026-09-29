"""Calculation corners: the band edges, the pinned rounding order and the constants that the
PRD fixes so that two implementations produce byte-identical numbers from identical inputs."""
from datetime import datetime

import pytest

from test_helpers import (
    WORK_DATE,
    ApiErrorId,
    add_scoped_request,
    api_client,
    assert_cycle_slot_conservation,
    assert_valuation_record,
    deliverable_scores_payload,
    drive_review_to_outcome,
    handoff_payload,
    make_program_manager_headers,
    milestone_payload,
    partner_org_payload,
    post_valuation,
    read_cycle,
    read_deliverables,
    read_engagement,
    read_milestones,
    read_partner,
    read_request,
    read_time_logs,
    read_volunteer,
    read_window,
    satisfaction_survey_payload,
    scope_change_request_payload,
    set_clock,
    setup_handed_off_engagement,
    setup_held_milestone_engagement,
    setup_in_progress_engagement,
    setup_scoped_request,
    setup_world,
    time_log_payload,
    validate_error,
    validate_paginated,
    validate_success,
)

# Two-decimal money and hour fields; four-decimal ratio and score fields.
CENT = 0.005
RATIO = 0.00005

CLOCK_STARTUP_INSTANT = "2026-08-01T00:00:00Z"


def _instant(value):
    """Parse an ISO 8601 UTC timestamp into a comparable datetime.

    The PRD fixes the instants themselves, not the number of fractional digits a
    serializer prints, so instants are compared as moments in time.
    """
    assert isinstance(value, str) and value, (
        f"Expected an ISO 8601 UTC timestamp, got {value!r}"
    )
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _same_instant(actual, expected) -> bool:
    return _instant(actual) == _instant(expected)


# ---------------------------------------------------------------------------
# Partner capacity bands (PRD §3.1)
# ---------------------------------------------------------------------------
def test_01_a_budget_one_cent_below_the_small_floor_is_still_micro(api):
    """PRD §3.1: "The partner's `capacity_class` is `MICRO` for a budget below 250000.00,
    `SMALL` from 250000.00 up to but not including 2000000.00, `MID` from 2000000.00 up to but
    not including 10000000.00, and `LARGE` at 10000000.00 and above — each band floor is
    inclusive and each ceiling exclusive."
    PRD §3.1: "The class implies the partner's `max_concurrent_engagements` ceiling directly:
    one for `MICRO`, two for `SMALL`, four for `MID` and six for `LARGE`."

    Design: Corner/calculations/calc_capacity_class_just_below_small_floor_stays_micro
    """
    pm = make_program_manager_headers()

    partner = validate_success(
        api_client.create_partner_org(
            partner_org_payload(
                name="Nearly Small Trust", sector="HEALTH", annual_budget_usd=249999.99
            ),
            pm,
        ),
        201,
    )

    assert partner["capacity_class"] == "MICRO", (
        f"A budget of 249999.99 sits below the inclusive 250000.00 SMALL floor, so "
        f"capacity_class must read MICRO, got {partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 1, (
        f"Expected the MICRO ceiling of 1 concurrent engagement, got "
        f"{partner['max_concurrent_engagements']}"
    )
    assert partner["annual_budget_usd"] == pytest.approx(249999.99, abs=CENT), (
        f"Expected the budget to be stored to the cent, got {partner['annual_budget_usd']}"
    )


def test_02_a_budget_exactly_on_the_small_floor_flips_to_small(api):
    """PRD §3.1: "The partner's `capacity_class` is `MICRO` for a budget below 250000.00,
    `SMALL` from 250000.00 up to but not including 2000000.00, `MID` from 2000000.00 up to but
    not including 10000000.00, and `LARGE` at 10000000.00 and above — each band floor is
    inclusive and each ceiling exclusive."
    PRD §3.1: "The class implies the partner's `max_concurrent_engagements` ceiling directly:
    one for `MICRO`, two for `SMALL`, four for `MID` and six for `LARGE`."

    Design: Corner/calculations/calc_capacity_class_at_exact_small_floor_is_small
    """
    pm = make_program_manager_headers()

    partner = validate_success(
        api_client.create_partner_org(
            partner_org_payload(
                name="Exactly Small Trust", sector="HEALTH", annual_budget_usd=250000.00
            ),
            pm,
        ),
        201,
    )

    assert partner["capacity_class"] == "SMALL", (
        f"A budget landing exactly on the inclusive 250000.00 floor belongs to SMALL, got "
        f"{partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 2, (
        f"Expected the SMALL ceiling of 2 concurrent engagements, got "
        f"{partner['max_concurrent_engagements']}"
    )


def test_03_a_budget_exactly_on_the_large_floor_is_large(api):
    """PRD §3.1: "The partner's `capacity_class` is `MICRO` for a budget below 250000.00,
    `SMALL` from 250000.00 up to but not including 2000000.00, `MID` from 2000000.00 up to but
    not including 10000000.00, and `LARGE` at 10000000.00 and above — each band floor is
    inclusive and each ceiling exclusive."
    PRD §3.1: "The class implies the partner's `max_concurrent_engagements` ceiling directly:
    one for `MICRO`, two for `SMALL`, four for `MID` and six for `LARGE`."

    Design: Corner/calculations/calc_capacity_class_at_exact_large_floor_is_large
    """
    pm = make_program_manager_headers()

    partner = validate_success(
        api_client.create_partner_org(
            partner_org_payload(
                name="Metro Health Foundation",
                sector="HEALTH",
                annual_budget_usd=10000000.00,
            ),
            pm,
        ),
        201,
    )

    assert partner["capacity_class"] == "LARGE", (
        f"The top band has no ceiling, so exactly 10000000.00 already reads LARGE, got "
        f"{partner['capacity_class']}"
    )
    assert partner["max_concurrent_engagements"] == 6, (
        f"Expected the LARGE ceiling of 6 concurrent engagements, got "
        f"{partner['max_concurrent_engagements']}"
    )


# ---------------------------------------------------------------------------
# The matching selector's score and the offer's time-to-live (PRD §3.4)
# ---------------------------------------------------------------------------
def test_04_a_critical_request_shifts_the_availability_weight_and_shortens_the_ttl(api):
    """PRD §3.4: "The weight on availability is chosen by the request's `urgency` — 0.20 for
    `ROUTINE`, 0.30 for `ELEVATED` and 0.45 for `CRITICAL` — while the weight on reliability is
    always 0.25, and the weight on skill is whatever remains: 1.00 less the availability weight
    less 0.25, rounded to four decimals."
    PRD §3.4: "The raw score is the skill weight times the skill component, plus the
    availability weight times the availability component, plus 0.25 times the volunteer's
    `reliability_score`, rounded to six decimals."
    PRD §3.4: "Its `reserved_hours` is the required-hours figure computed above, its
    `offered_at` is the logical clock, and its `expires_at` is `offered_at` plus a time-to-live
    chosen by the request's `urgency`: five days for a `ROUTINE` request, three days for an
    `ELEVATED` one, and a single day for a `CRITICAL` one."

    Design: Corner/calculations/calc_match_score_urgency_weights_switch_on_critical_request
    """
    # skill 0.88 (proficiency 4) + 0.05 verified bonus = 0.93; availability 200.00/40.00
    # capped at 1.00; no shortfall so no penalty; CRITICAL weights 0.30/0.45/0.25.
    # raw = 0.30*0.93 + 0.45*1.00 + 0.25*0.7500 = 0.916500; SENIOR multiplier 1.00.
    expected_score = 0.9165
    world = setup_scoped_request(
        urgency="CRITICAL",
        min_proficiency=3,
        proficiency=4,
        verify_skill=True,
        volunteer_seniority="SENIOR",
        window_hours=200.00,
        estimated_hours=40.00,
        complexity_factor=1.00,
    )

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )

    assert offer["match_score"] == pytest.approx(expected_score, abs=RATIO), (
        f"Expected match_score {expected_score} for a CRITICAL request, got "
        f"{offer['match_score']}"
    )
    assert offer["reserved_hours"] == pytest.approx(40.00, abs=CENT), (
        f"Expected reserved_hours 40.00 (estimated_hours 40.00 times complexity 1.00), got "
        f"{offer['reserved_hours']}"
    )
    assert _same_instant(offer["offered_at"], CLOCK_STARTUP_INSTANT), (
        f"Expected offered_at to be the logical clock {CLOCK_STARTUP_INSTANT}, got "
        f"{offer['offered_at']}"
    )
    assert _same_instant(offer["expires_at"], "2026-08-02T00:00:00Z"), (
        f"Expected a one-day CRITICAL time-to-live ending 2026-08-02T00:00:00Z, got "
        f"{offer['expires_at']}"
    )
    assert offer["status"] == "OFFERED", (
        f"Expected status OFFERED, got {offer['status']}"
    )
    assert offer["round_no"] == 1, (
        f"Expected round_no 1 on the first offer of a request, got {offer['round_no']}"
    )


def test_05_a_vetting_run_that_names_no_skill_code_withholds_the_verified_bonus(api):
    """PRD §3.2: "Vetting is a single `ProgramManager` action that stamps
    `credential_verified_at` from the logical clock, flips `status` from `PENDING_VETTING` to
    `ACTIVE`, and optionally accepts a `verify_skill_codes` list; each skill claim whose
    `skill_code` appears on that list has its `verified` flag set to true and its `verified_at`
    stamped, which is what later earns that claim a bonus in the matching score."
    PRD §3.2: "`verified` defaults to false until a vetting run names that code."
    PRD §3.4: "The skill component starts from a tiered lookup on the claim's `proficiency` —
    0.20 at proficiency 1, 0.45 at 2, 0.70 at 3, 0.88 at 4 and 1.00 at 5 — plus a flat bonus of
    0.05 when the claim's `verified` flag is true and nothing when it is false, with the sum
    capped at 1.00."

    Design: Corner/calculations/calc_match_score_without_verified_skill_bonus
    """
    # skill 0.88 with no verified bonus; availability capped at 1.00; ROUTINE weights
    # 0.55/0.20/0.25. raw = 0.55*0.88 + 0.20*1.00 + 0.25*0.7500 = 0.871500; SENIOR 1.00.
    expected_score = 0.8715
    world = setup_scoped_request(
        urgency="ROUTINE",
        min_proficiency=3,
        proficiency=4,
        verify_skill=False,
        volunteer_seniority="SENIOR",
        window_hours=200.00,
        estimated_hours=40.00,
        complexity_factor=1.00,
    )

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )

    assert offer["match_score"] == pytest.approx(expected_score, abs=RATIO), (
        f"An unnamed skill claim earns no 0.05 bonus, so match_score must read "
        f"{expected_score}, got {offer['match_score']}"
    )
    assert _same_instant(offer["expires_at"], "2026-08-06T00:00:00Z"), (
        f"Expected a five-day ROUTINE time-to-live ending 2026-08-06T00:00:00Z, got "
        f"{offer['expires_at']}"
    )

    claims, _meta = validate_paginated(
        api_client.list_skill_profiles(world["volunteer"]["id"], world["pm_headers"])
    )
    assert len(claims) == 1, f"Expected exactly one declared skill claim, got {len(claims)}"
    assert claims[0]["verified"] is False, (
        f"A vetting run that named no skill code leaves verified false, got "
        f"{claims[0]['verified']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["status"] == "ACTIVE", (
        f"Vetting activates the volunteer whether or not it names a skill code, got "
        f"{volunteer['status']}"
    )
    assert _same_instant(volunteer["credential_verified_at"], CLOCK_STARTUP_INSTANT), (
        f"Expected credential_verified_at stamped from the logical clock "
        f"{CLOCK_STARTUP_INSTANT}, got {volunteer['credential_verified_at']}"
    )


def test_06_the_seniority_multiplier_can_carry_a_score_above_one(api):
    """PRD §3.4: "Subtract the penalty from that raw score, floor the result at 0.0000, multiply
    by a seniority multiplier — 0.90 for `ASSOCIATE`, 1.00 for `SENIOR`, 1.08 for `PRINCIPAL`
    and 1.12 for `PARTNER` — and round to four decimals. That final figure is the candidate's
    score, and it therefore lives between 0.0000 and 1.2000."
    PRD §2.6: "the raw match score to six decimals before the seniority multiplier and the final
    four-decimal rounding are applied."

    Design: Corner/calculations/calc_match_score_seniority_multiplier_can_exceed_one
    """
    # raw = 0.55*0.93 + 0.20*1.00 + 0.25*0.7500 = 0.899000; 0.899000 * 1.12 = 1.006880,
    # which rounds to 1.0069 — the multiplier is applied last and is not clamped at 1.0000.
    expected_score = 1.0069
    world = setup_scoped_request(
        urgency="ROUTINE",
        min_proficiency=3,
        proficiency=4,
        verify_skill=True,
        volunteer_seniority="PARTNER",
        window_hours=200.00,
        estimated_hours=40.00,
        complexity_factor=1.00,
    )

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )

    assert offer["match_score"] == pytest.approx(expected_score, abs=RATIO), (
        f"Expected match_score {expected_score} from a raw 0.899000 times the PARTNER "
        f"multiplier 1.12, got {offer['match_score']}"
    )
    assert offer["reserved_hours"] == pytest.approx(40.00, abs=CENT), (
        f"Expected reserved_hours 40.00, got {offer['reserved_hours']}"
    )
    assert read_volunteer(world)["seniority"] == "PARTNER", (
        "Expected the scored volunteer to carry PARTNER seniority"
    )


def test_07_a_proficiency_gate_that_no_claim_meets_empties_the_candidate_pool(api):
    """PRD §3.4: "The claim's `proficiency` must be greater than or equal to the request's
    `min_proficiency`."
    PRD §3.4: "If nothing survives this filter, no offer is created: the request stays in
    `SCOPED`, its `failed_match_rounds` rises by one, and the call answers
    `ERR_NO_ELIGIBLE_VOLUNTEER`."
    PRD §3.1: "a `utilization_ratio` equal to the sum of committed and reserved slots divided by
    `capacity_slot_total` and rounded to four decimals"

    Design: Corner/calculations/calc_match_score_empty_candidate_set_returns_no_eligible_volunteer
    """
    world = setup_scoped_request(min_proficiency=5, proficiency=4)

    validate_error(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        ApiErrorId.ERR_NO_ELIGIBLE_VOLUNTEER,
        422,
    )

    request = read_request(world)
    assert request["status"] == "SCOPED", (
        f"A failed match round leaves the request in SCOPED, got {request['status']}"
    )
    assert request["failed_match_rounds"] == 1, (
        f"Expected failed_match_rounds to rise to 1, got {request['failed_match_rounds']}"
    )
    assert request["rescope_count"] == 0, (
        f"A single failed round does not re-scope, so rescope_count stays 0, got "
        f"{request['rescope_count']}"
    )

    offers, meta = validate_paginated(
        api_client.list_match_offers(
            world["pm_headers"], params={"project_request_id": world["request"]["id"]}
        )
    )
    assert meta["total_count"] == 0, (
        f"No offer may be written when the candidate pool is empty, got "
        f"{meta['total_count']}"
    )
    assert offers == [], f"Expected no offer rows, got {offers}"

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 0, (
        f"No slot may be reserved by a failed round, got {cycle['slots_reserved']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=RATIO), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(0.00, abs=CENT), (
        f"No window hours may be committed by a failed round, got "
        f"{window['hours_committed']}"
    )


def test_08_a_one_slot_cycle_freezes_at_exactly_full_utilization(api):
    """PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from
    0.8000 up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band floors
    are inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly 1.0000 is
    `FROZEN`."
    PRD §3.4: "the cycle's `slots_reserved` rises by one, after which the posture calculation
    reruns and may carry the cycle from `OPEN` to `RESTRICTED` or on to `FROZEN`."
    PRD §2.8: "slots_committed plus slots_reserved plus slots_available always equals
    capacity_slot_total"

    Design: Corner/calculations/calc_cycle_posture_frozen_at_exactly_full_utilization
    """
    world = setup_scoped_request(cycle_slots=1)

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        201,
    )

    assert offer["status"] == "OFFERED", (
        f"Expected the offer to be written in OFFERED, got {offer['status']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"The single slot is now held in reserve, got slots_reserved "
        f"{cycle['slots_reserved']}"
    )
    assert cycle["slots_committed"] == 0, (
        f"Nothing is committed until the offer is accepted, got slots_committed "
        f"{cycle['slots_committed']}"
    )
    assert cycle["slots_available"] == 0, (
        f"A one-slot cycle holding one reservation has no slot left, got slots_available "
        f"{cycle['slots_available']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(1.0000, abs=RATIO), (
        f"Expected utilization_ratio exactly 1.0000 from (0 + 1) / 1, got "
        f"{cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "FROZEN", (
        f"1.0000 sits on the inclusive FROZEN floor, so posture must read FROZEN, got "
        f"{cycle['posture']}"
    )
    assert_cycle_slot_conservation(cycle)


# ---------------------------------------------------------------------------
# Partner satisfaction (PRD §3.9)
# ---------------------------------------------------------------------------
def test_09_a_lone_qualifying_survey_normalises_to_its_own_composite(api):
    """PRD §3.9: "Its `composite_score` is a weighted 0-to-100 figure: 0.40 times
    `score_expertise`, plus 0.35 times `score_deliverable_fit`, plus 0.25 times
    `score_responsiveness`, that sum multiplied by 20 and rounded to two decimals."
    PRD §3.9: "Otherwise the used rows are weighted by recency from a fixed ladder — 0.34 for
    the newest, then 0.26, 0.18, 0.13 and 0.09 — of which only the first as many entries as
    there are used rows participate: sum those entries and round to four decimals, divide each
    entry by that sum and round to six decimals, multiply each normalised weight by its survey's
    `composite_score` and round each product to four decimals, then sum the products and round
    to two decimals."
    PRD §3.9: "Both evaluations run at the end of survey submission, and neither fires below a
    sample size of 3."

    Design: Corner/calculations/calc_satisfaction_index_single_survey_normalises_to_its_composite
    """
    # composite = (0.40*5 + 0.35*4 + 0.25*3) * 20 = 4.15 * 20 = 83.00.
    # With one used row the ladder sum is 0.34, so the sole normalised weight is
    # 0.34/0.34 = 1.000000 and the index collapses onto the composite itself.
    expected_composite = 83.00
    world = setup_handed_off_engagement()

    survey = validate_success(
        api_client.create_satisfaction_survey(
            world["engagement"]["id"],
            satisfaction_survey_payload(
                score_expertise=5, score_responsiveness=3, score_deliverable_fit=4
            ),
            world["partner_headers"],
        ),
        201,
    )

    assert survey["composite_score"] == pytest.approx(expected_composite, abs=CENT), (
        f"Expected composite_score {expected_composite}, got {survey['composite_score']}"
    )
    assert survey["counted_in_index"] is True, (
        f"A survey on a HANDED_OFF engagement qualifies for the pool, so counted_in_index "
        f"must be true, got {survey['counted_in_index']}"
    )

    partner = read_partner(world)
    assert partner["satisfaction_index"] == pytest.approx(expected_composite, abs=CENT), (
        f"A single used row normalises to weight 1.000000, so satisfaction_index must equal "
        f"the composite {expected_composite}, got {partner['satisfaction_index']}"
    )
    assert partner["satisfaction_sample_size"] == 1, (
        f"Expected satisfaction_sample_size 1, got {partner['satisfaction_sample_size']}"
    )
    assert partner["status"] == "ACTIVE", (
        f"A sample size of 1 is below the minimum of 3, so partner standing must not move "
        f"from ACTIVE, got {partner['status']}"
    )
    assert partner["probation_reason"] is None, (
        f"Expected probation_reason to stay null, got {partner['probation_reason']}"
    )

    surveys, meta = validate_paginated(
        api_client.list_partner_org_satisfaction_surveys(
            world["partner"]["id"], world["pm_headers"]
        )
    )
    assert meta["total_count"] == 1, (
        f"Expected exactly one survey attributed to the partner, got {meta['total_count']}"
    )
    assert surveys[0]["counted_in_index"] is True, (
        f"Expected the stored row to read counted_in_index true, got {surveys[0]}"
    )


def test_10_a_survey_on_a_terminated_engagement_is_stored_but_never_counted(api):
    """PRD §3.9: "The eligible pool is every survey of that partner whose linked engagement
    reached `work_status` `HANDED_OFF`; a survey filed against a terminated engagement is still
    stored, but with `counted_in_index` false, and it never moves the index."
    PRD §3.9: "The partner's `satisfaction_sample_size` is the number of rows actually used, so
    it ranges from 0 to 5. With no qualifying survey the `satisfaction_index` is null."

    Design: Corner/calculations/calc_satisfaction_survey_on_terminated_engagement_stays_out_of_index
    """
    expected_composite = 83.00
    world = setup_in_progress_engagement()
    validate_success(
        api_client.terminate_engagement(
            world["engagement"]["id"],
            world["pm_headers"],
            {"termination_reason": "ADMIN"},
        ),
        200,
    )

    survey = validate_success(
        api_client.create_satisfaction_survey(
            world["engagement"]["id"],
            satisfaction_survey_payload(
                score_expertise=5, score_responsiveness=3, score_deliverable_fit=4
            ),
            world["partner_headers"],
        ),
        201,
    )

    assert survey["composite_score"] == pytest.approx(expected_composite, abs=CENT), (
        f"The composite is computed for every stored survey, so it must read "
        f"{expected_composite}, got {survey['composite_score']}"
    )
    assert survey["counted_in_index"] is False, (
        f"The pool admits only surveys whose engagement reached HANDED_OFF, so "
        f"counted_in_index must be false, got {survey['counted_in_index']}"
    )

    partner = read_partner(world)
    assert partner["satisfaction_index"] is None, (
        f"With no qualifying survey satisfaction_index stays null, got "
        f"{partner['satisfaction_index']}"
    )
    assert partner["satisfaction_sample_size"] == 0, (
        f"Expected satisfaction_sample_size 0, got {partner['satisfaction_sample_size']}"
    )
    assert partner["status"] == "ACTIVE", (
        f"An uncounted survey cannot move partner standing, got {partner['status']}"
    )

    surveys, meta = validate_paginated(
        api_client.list_engagement_satisfaction_surveys(
            world["engagement"]["id"], world["pm_headers"]
        )
    )
    assert meta["total_count"] == 1, (
        f"The survey is still stored against the engagement, got {meta['total_count']}"
    )
    assert len(surveys) == 1, f"Expected one stored survey row, got {len(surveys)}"


# ---------------------------------------------------------------------------
# Hour valuation and program overhead (PRD §3.9)
# ---------------------------------------------------------------------------
def _mixed_class_logs():
    """Thirty DELIVERY, eight ADMIN and two TRAVEL hours on one engagement."""
    return [
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"},
        {"work_date": WORK_DATE, "hours": 8.00, "activity_class": "ADMIN"},
        {"work_date": WORK_DATE, "hours": 2.00, "activity_class": "TRAVEL"},
    ]


def test_11_market_rate_drops_travel_hours_and_halves_admin_money(api):
    """PRD §3.9: "It admits only logs whose `activity_class` is `DELIVERY` or `ADMIN`, dropping
    every `TRAVEL` log from both the hours and the money. For each admitted log it multiplies the
    log's `hours` by the lesser of that log's `rate_basis_usd` and the seniority ceiling, then by
    a class factor of 1.00 for `DELIVERY` and 0.50 for `ADMIN` ... and rounds that line to two
    decimals."
    PRD §3.9: "`hours_included` is the sum of `hours` over the admitted logs, rounded to two
    decimals, and `rate_applied_usd` is the lesser of the volunteer's
    `professional_rate_usd_per_hour` and the seniority ceiling."
    PRD §3.9: "the overhead tier is selected from `base_amount_usd` and never from the total: a
    base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to but not including 10000.00
    takes 0.09, and a base of 10000.00 or more takes 0.06."
    PRD §3.9: "it recomputes the volunteer's `lifetime_valued_usd` from her non-superseded
    `INDEPENDENT_SECTOR` records"

    Design: Corner/calculations/calc_valuation_market_rate_drops_travel_and_halves_admin
    """
    # SENIOR ceiling 320.00 exceeds the 200.00 personal rate, so the rate applied is 200.00.
    # Lines: 10*200*1.00 = 2000.00 three times, plus 8*200*0.50 = 800.00 => 6800.00.
    # Hours admitted: 30.00 DELIVERY + 8.00 ADMIN = 38.00; the 2.00 TRAVEL hours are dropped.
    # Tier from base 6800.00 => 0.09 => 612.00 of overhead => total 7412.00.
    world = setup_world(
        "held",
        volunteer_seniority="SENIOR",
        volunteer_rate=200.00,
        time_logs=_mixed_class_logs(),
        reported_cumulative_hours=40.00,
    )

    record = validate_success(post_valuation(world, "MARKET_RATE"), 201)

    assert_valuation_record(record)
    assert record["method"] == "MARKET_RATE", (
        f"Expected the requested method MARKET_RATE, got {record['method']}"
    )
    assert record["hours_included"] == pytest.approx(38.00, abs=CENT), (
        f"TRAVEL hours are dropped from the hours too, so hours_included must read 38.00, got "
        f"{record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(200.00, abs=CENT), (
        f"Expected rate_applied_usd 200.00, the lesser of the 200.00 personal rate and the "
        f"320.00 SENIOR ceiling, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(6800.00, abs=CENT), (
        f"Expected base_amount_usd 6800.00 from 2000.00 + 2000.00 + 2000.00 + 800.00, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(612.00, abs=CENT), (
        f"A base of 6800.00 takes the 0.09 tier, so admin_overhead_usd must read 612.00, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(7412.00, abs=CENT), (
        f"Expected total_amount_usd 7412.00, got {record['total_amount_usd']}"
    )
    assert record["variant_label"] == "PROVISIONAL", (
        f"A post against an IN_PROGRESS engagement reaches PROVISIONAL, got "
        f"{record['variant_label']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(0.00, abs=CENT), (
        f"Only INDEPENDENT_SECTOR records feed lifetime_valued_usd, so it must stay 0.00, got "
        f"{volunteer['lifetime_valued_usd']}"
    )


def test_12_independent_sector_admits_every_activity_class_at_the_flat_rate(api):
    """PRD §3.9: "It admits every approved log regardless of class — `DELIVERY`, `ADMIN` and
    `TRAVEL` alike — sets `hours_included` to the sum of their `hours` rounded to two decimals,
    sets `rate_applied_usd` to the flat national rate of 34.79 dollars an hour, and sets
    `base_amount_usd` to those hours multiplied by that rate, rounded once at the end. Seniority
    ceilings and personal rates play no part."
    PRD §3.9: "`admin_overhead_usd` is the greater of a 45.00-dollar floor and the base
    multiplied by that tier rate rounded to two decimals"
    PRD §3.9: "it recomputes the volunteer's `lifetime_valued_usd` from her non-superseded
    `INDEPENDENT_SECTOR` records"

    Design: Corner/calculations/calc_valuation_independent_sector_admits_every_activity_class
    """
    # Every class counts: 30.00 + 8.00 + 2.00 = 40.00 hours, rounded once at the end as
    # 40.00 * 34.79 = 1391.60. That base is below 2500.00, so the tier is 0.12:
    # 1391.60 * 0.12 = 166.992 -> 166.99, above the 45.00 floor, for a total of 1558.59.
    world = setup_world(
        "held",
        volunteer_seniority="SENIOR",
        volunteer_rate=200.00,
        time_logs=_mixed_class_logs(),
        reported_cumulative_hours=40.00,
    )

    record = validate_success(post_valuation(world, "INDEPENDENT_SECTOR"), 201)

    assert_valuation_record(record)
    assert record["hours_included"] == pytest.approx(40.00, abs=CENT), (
        f"Every activity class counts here, so hours_included must read 40.00, got "
        f"{record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(34.79, abs=CENT), (
        f"Expected the flat national rate 34.79, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(1391.60, abs=CENT), (
        f"Expected base_amount_usd 1391.60 from a single rounding of 40.00 * 34.79, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(166.99, abs=CENT), (
        f"A base of 1391.60 takes the 0.12 tier, so admin_overhead_usd must read 166.99, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(1558.59, abs=CENT), (
        f"Expected total_amount_usd 1558.59, got {record['total_amount_usd']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(1558.59, abs=CENT), (
        f"Expected lifetime_valued_usd 1558.59 from the one non-superseded INDEPENDENT_SECTOR "
        f"record, got {volunteer['lifetime_valued_usd']}"
    )


def test_13_the_seniority_ceiling_clamps_an_associate_billing_above_it(api):
    """PRD §3.9: "Both also consult a seniority-keyed rate ceiling: 180.00 dollars an hour for an
    `ASSOCIATE`, 320.00 for a `SENIOR`, 480.00 for a `PRINCIPAL` and 650.00 for a `PARTNER`."
    PRD §3.9: "For each admitted log it multiplies the log's `hours` by the lesser of that log's
    `rate_basis_usd` and the seniority ceiling"
    PRD §3.7: "a `rate_basis_usd` snapshotting the volunteer's `professional_rate_usd_per_hour`
    as it stood at log creation"

    Design: Corner/calculations/calc_valuation_market_rate_cap_clamps_associate_rate
    """
    # min(200.00, 180.00 ASSOCIATE ceiling) = 180.00, so each 10.00-hour DELIVERY line is
    # 1800.00 and the base is 7200.00 rather than 8000.00. Tier 0.09 => 648.00 => 7848.00.
    world = setup_world(
        "held",
        volunteer_seniority="ASSOCIATE",
        volunteer_rate=200.00,
        reported_cumulative_hours=40.00,
    )

    record = validate_success(post_valuation(world, "MARKET_RATE"), 201)

    assert_valuation_record(record)
    assert record["rate_applied_usd"] == pytest.approx(180.00, abs=CENT), (
        f"rate_applied_usd reports the 180.00 ASSOCIATE ceiling, not the volunteer's own "
        f"200.00, got {record['rate_applied_usd']}"
    )
    assert record["base_amount_usd"] == pytest.approx(7200.00, abs=CENT), (
        f"Expected base_amount_usd 7200.00 from four capped 1800.00 lines, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(648.00, abs=CENT), (
        f"A base of 7200.00 takes the 0.09 tier, so admin_overhead_usd must read 648.00, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(7848.00, abs=CENT), (
        f"Expected total_amount_usd 7848.00, got {record['total_amount_usd']}"
    )

    logs = read_time_logs(world)
    assert len(logs) == 4, f"Expected the four logged lines, got {len(logs)}"
    for log in logs:
        assert log["rate_basis_usd"] == pytest.approx(200.00, abs=CENT), (
            f"The log's snapshot keeps the uncapped 200.00 rate; the cap is applied only at "
            f"valuation time, got rate_basis_usd {log['rate_basis_usd']}"
        )


def test_14_the_overhead_tier_is_keyed_off_the_base_and_never_off_the_total(api):
    """PRD §3.9: "Second, the overhead tier is selected from `base_amount_usd` and never from the
    total: a base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to but not including
    10000.00 takes 0.09, and a base of 10000.00 or more takes 0.06."
    PRD §3.9: "A base of 2380.00 therefore takes the 0.12 rate, yielding 285.60 of overhead and a
    total of 2665.60, even though the resulting total sits inside the 0.09 band."

    Design: Corner/calculations/calc_admin_overhead_tier_keyed_off_base_not_total
    """
    # 11.90 DELIVERY hours at 200.00 give a base of 2380.00, which is below 2500.00 and so
    # takes 0.12: 2380.00 * 0.12 = 285.60 and the total is 2665.60. Keying the tier off the
    # 2594.20 that 0.09 would produce is the mistake this pins down.
    world = setup_world(
        "held",
        volunteer_seniority="SENIOR",
        volunteer_rate=200.00,
        time_logs=[
            {"work_date": WORK_DATE, "hours": 11.90, "activity_class": "DELIVERY"},
        ],
        reported_cumulative_hours=11.90,
    )

    record = validate_success(post_valuation(world, "MARKET_RATE"), 201)

    assert_valuation_record(record)
    assert record["hours_included"] == pytest.approx(11.90, abs=CENT), (
        f"Expected hours_included 11.90, got {record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(2380.00, abs=CENT), (
        f"Expected base_amount_usd 2380.00 from 11.90 * 200.00, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(285.60, abs=CENT), (
        f"The base sits below 2500.00, so the 0.12 rate applies for 285.60 of overhead, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(2665.60, abs=CENT), (
        f"Expected total_amount_usd 2665.60, got {record['total_amount_usd']}"
    )


def test_15_the_forty_five_dollar_overhead_floor_beats_a_small_tier_product(api):
    """PRD §3.9: "Third, `admin_overhead_usd` is the greater of a 45.00-dollar floor and the base
    multiplied by that tier rate rounded to two decimals — so even a base of 0.00 still carries
    45.00 of overhead."
    PRD §3.9: "then by a class factor of 1.00 for `DELIVERY` and 0.50 for `ADMIN`"
    PRD §3.9: "Fourth, `total_amount_usd` is the base plus the overhead, rounded to two
    decimals."

    Design: Corner/calculations/calc_admin_overhead_floor_dominates_a_small_base
    """
    # One ADMIN hour: 1.00 * 200.00 * 0.50 = 100.00 of base. The 0.12 tier product is only
    # 12.00, so the 45.00 floor wins and the total is 100.00 + 45.00 = 145.00.
    world = setup_world(
        "held",
        volunteer_seniority="SENIOR",
        volunteer_rate=200.00,
        time_logs=[
            {"work_date": WORK_DATE, "hours": 1.00, "activity_class": "ADMIN"},
        ],
        reported_cumulative_hours=1.00,
    )

    record = validate_success(post_valuation(world, "MARKET_RATE"), 201)

    assert_valuation_record(record)
    assert record["hours_included"] == pytest.approx(1.00, abs=CENT), (
        f"Expected hours_included 1.00, got {record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(100.00, abs=CENT), (
        f"Expected base_amount_usd 100.00 from the halved ADMIN class factor, got "
        f"{record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(45.00, abs=CENT), (
        f"The 0.12 product of 12.00 loses to the 45.00 floor, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(145.00, abs=CENT), (
        f"Expected total_amount_usd 145.00, got {record['total_amount_usd']}"
    )


def test_16_a_base_of_exactly_ten_thousand_takes_the_high_overhead_tier(api):
    """PRD §3.9: "a base from 2500.00 up to but not including 10000.00 takes 0.09, and a base of
    10000.00 or more takes 0.06."
    PRD §3.7: "The engagement's `approved_hours` is the sum of `hours` over its child logs whose
    `approved` flag is true, across every activity class without exception, rounded to two
    decimals."
    PRD §3.7: "The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH` from
    0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not including
    0.5000, and `BREACH` at 0.5000 and above."

    Design: Corner/calculations/calc_admin_overhead_high_tier_at_exact_ten_thousand_base
    """
    # Fifty DELIVERY hours at 200.00 give a base of exactly 10000.00, which sits on the
    # inclusive high-tier floor: 10000.00 * 0.06 = 600.00 rather than the 900.00 that 0.09
    # would give, for a total of 10600.00.
    world = setup_world(
        "held",
        volunteer_seniority="SENIOR",
        volunteer_rate=200.00,
        time_logs=[
            {"work_date": WORK_DATE, "hours": 10.00, "activity_class": "DELIVERY"}
            for _ in range(5)
        ],
        reported_cumulative_hours=50.00,
    )

    record = validate_success(post_valuation(world, "MARKET_RATE"), 201)

    assert_valuation_record(record)
    assert record["hours_included"] == pytest.approx(50.00, abs=CENT), (
        f"Expected hours_included 50.00, got {record['hours_included']}"
    )
    assert record["base_amount_usd"] == pytest.approx(10000.00, abs=CENT), (
        f"Expected base_amount_usd 10000.00, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(600.00, abs=CENT), (
        f"Exactly 10000.00 takes the inclusive 0.06 tier, so admin_overhead_usd must read "
        f"600.00, got {record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(10600.00, abs=CENT), (
        f"Expected total_amount_usd 10600.00, got {record['total_amount_usd']}"
    )

    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(50.00, abs=CENT), (
        f"Expected approved_hours 50.00 after the hold, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(0.2500, abs=RATIO), (
        f"Expected scope_creep_pct 0.2500 from (50.00 - 40.00) / 40.00, got "
        f"{engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "WATCH", (
        f"0.2500 sits in the WATCH band, got {engagement['creep_escalation_level']}"
    )


# ---------------------------------------------------------------------------
# The quality rubric (PRD §3.8)
# ---------------------------------------------------------------------------
def _open_review(world):
    return validate_success(
        api_client.create_quality_review(
            world["engagement"]["id"], world["reviewer_headers"]
        ),
        201,
    )


def test_17_each_deliverable_contribution_is_rounded_before_the_sum(api):
    """PRD §3.8: "For each deliverable in the pinned order, divide its `weight_pct` by that active
    total and round to six decimals, then multiply that normalised weight by the deliverable's
    `review_score` and by a scale factor of 20, rounding each deliverable's contribution to two
    decimals *before* summing. The review's `weighted_score` is the sum of those per-deliverable
    contributions, rounded to two decimals; summing normalised weights first and rounding once at
    the end is not equivalent and is not permitted."
    PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above, `CONDITIONAL`
    from 60.00 up to but not including 78.00, and `FAIL` below 60.00."
    PRD §3.8: "Scoring also recomputes `scored_deliverable_count`, the number of non-`WAIVED`
    deliverables on the pinned revision now carrying a non-null `review_score`, and moves the
    review `OPEN → SCORED`."

    Design: Corner/calculations/calc_quality_score_rounds_per_deliverable_then_sums
    """
    # Active weight total 33.33 + 33.33 + 33.34 = 100.00. Normalised 0.333300 / 0.333300 /
    # 0.333400. Contributions rounded per line: 0.333300*5*20 = 33.33, 0.333300*4*20 = 26.664
    # -> 26.66, 0.333400*3*20 = 20.004 -> 20.00. Sum 79.99 — summing the normalised weights
    # first would have produced 80.00.
    world = setup_world(
        "submitted",
        deliverables=[
            {
                "title": "Findings memo",
                "sequence_no": 1,
                "weight_pct": 33.33,
                "hours_estimate": 13.33,
                "acceptance_criteria": "Board-ready memo.",
            },
            {
                "title": "Control matrix",
                "sequence_no": 2,
                "weight_pct": 33.33,
                "hours_estimate": 13.33,
                "acceptance_criteria": "Matrix mapped to the trial balance.",
            },
            {
                "title": "Filing checklist",
                "sequence_no": 3,
                "weight_pct": 33.34,
                "hours_estimate": 13.34,
                "acceptance_criteria": "Checklist signed off by the treasurer.",
            },
        ],
        time_logs=[
            {"work_date": WORK_DATE, "hours": hours, "activity_class": "DELIVERY"}
            for hours in (6.67, 6.66, 6.67, 6.66, 6.67, 6.67)
        ],
        reported_cumulative_hours=40.00,
    )
    review = _open_review(world)
    awarded = dict(zip([d["id"] for d in world["deliverables"]], (5, 4, 3)))

    scored = validate_success(
        api_client.score_quality_review(
            review["id"], deliverable_scores_payload(awarded), world["reviewer_headers"]
        ),
        200,
    )

    assert scored["weighted_score"] == pytest.approx(79.99, abs=CENT), (
        f"Expected weighted_score 79.99 from 33.33 + 26.66 + 20.00, got "
        f"{scored['weighted_score']}"
    )
    assert scored["outcome"] == "PASS", (
        f"79.99 clears the inclusive 78.00 PASS floor, got {scored['outcome']}"
    )
    assert scored["scored_deliverable_count"] == 3, (
        f"Expected scored_deliverable_count 3, got {scored['scored_deliverable_count']}"
    )

    rows = sorted(read_deliverables(world), key=lambda d: d["sequence_no"])
    assert [row["review_score"] for row in rows] == [5, 4, 3], (
        f"Expected review_score 5, 4, 3 in sequence_no order, got "
        f"{[(row['sequence_no'], row['review_score']) for row in rows]}"
    )


def test_18_a_score_between_the_two_floors_settles_as_conditional(api):
    """PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above, `CONDITIONAL`
    from 60.00 up to but not including 78.00, and `FAIL` below 60.00."
    PRD §3.8: "A decision on a `PASS` or `CONDITIONAL` outcome without rework moves the review
    `SCORED → DECIDED` with `decided_at` stamped, sets the engagement's `quality_gate` to
    `PASSED` when the outcome was `PASS` and to `CONDITIONAL` when it was `CONDITIONAL`, moves
    the engagement `SUBMITTED → ACCEPTED`, and settles each deliverable: every non-`WAIVED`
    deliverable whose `review_score` is 3 or higher moves to `review_status` `ACCEPTED`, and
    every remaining one moves to `REJECTED`."

    Design: Corner/calculations/calc_quality_score_just_below_pass_threshold_is_conditional
    """
    # Weights 60.00 / 40.00 over an active total of 100.00 give normalised 0.600000 and
    # 0.400000: 0.600000*4*20 = 48.00 and 0.400000*3*20 = 24.00, summing to 72.00 — above the
    # inclusive 60.00 CONDITIONAL floor and below the 78.00 PASS floor.
    world = setup_world(
        "submitted",
        time_logs=[
            {"work_date": WORK_DATE, "hours": hours, "activity_class": "DELIVERY"}
            for hours in (12.00, 12.00, 8.00, 8.00)
        ],
        reported_cumulative_hours=40.00,
    )
    review = _open_review(world)
    awarded = dict(zip([d["id"] for d in world["deliverables"]], (4, 3)))
    scored = validate_success(
        api_client.score_quality_review(
            review["id"], deliverable_scores_payload(awarded), world["reviewer_headers"]
        ),
        200,
    )
    assert scored["weighted_score"] == pytest.approx(72.00, abs=CENT), (
        f"Expected weighted_score 72.00 from 48.00 + 24.00, got {scored['weighted_score']}"
    )

    decided = validate_success(
        api_client.decide_quality_review(review["id"], world["reviewer_headers"], {}),
        200,
    )

    assert decided["weighted_score"] == pytest.approx(72.00, abs=CENT), (
        f"The decision leaves the score alone, got {decided['weighted_score']}"
    )
    assert decided["outcome"] == "CONDITIONAL", (
        f"72.00 sits in the CONDITIONAL band, got {decided['outcome']}"
    )
    assert decided["status"] == "DECIDED", (
        f"Expected the review to reach DECIDED, got {decided['status']}"
    )

    engagement = read_engagement(world)
    assert engagement["work_status"] == "ACCEPTED", (
        f"A CONDITIONAL decision without rework still accepts the work, got "
        f"{engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "CONDITIONAL", (
        f"Expected quality_gate CONDITIONAL, got {engagement['quality_gate']}"
    )

    rows = sorted(read_deliverables(world), key=lambda d: d["sequence_no"])
    assert len(rows) == 2, f"Expected two deliverable rows, got {len(rows)}"
    for row in rows:
        assert row["review_status"] == "ACCEPTED", (
            f"A review_score of 3 or higher settles as ACCEPTED, so deliverable "
            f"{row['sequence_no']} scored {row['review_score']} must read ACCEPTED, got "
            f"{row['review_status']}"
        )


# ---------------------------------------------------------------------------
# Volunteer reliability, decay-weighted against lifetime (PRD §3.2)
# ---------------------------------------------------------------------------
def test_19_the_two_reliability_variants_diverge_on_two_unlike_outcomes(api):
    """PRD §3.2: "Each terminal engagement earns a point value before penalties: 1.00 when it was
    `HANDED_OFF` with a `quality_gate` of `PASSED`; ... 0.25 when it was `TERMINATED` for
    `SCOPE_BREACH` or `ADMIN`"
    PRD §3.2: "it takes only the eight most recent terminal engagements in that order (or all of
    them when the volunteer has fewer), gives the engagement at rank zero a weight of 1, the next
    a weight of 0.85, the next 0.85 multiplied by itself, and so on — each rank's weight is 0.85
    raised to that zero-based rank and rounded to six decimals — then divides the weighted sum of
    point values by the sum of the weights actually used and rounds to four decimals."
    PRD §3.2: "The reporting figure, `reliability_score_lifetime`, uses the unweighted lifetime
    variant: it averages the point values of every terminal engagement ever, however many there
    are, and rounds to four decimals."
    PRD §3.2: "if `reliability_score` falls strictly below 0.4000 while the volunteer's `status`
    is `ACTIVE`, the volunteer moves to `PAUSED` with `pause_reason` `RELIABILITY_FLOOR`"

    Design: Corner/calculations/calc_reliability_decay_weighted_diverges_from_lifetime_average
    """
    # Ranked most-recent-first: the ADMIN termination (0.25) at rank 0 with weight 1, the older
    # PASSED handoff (1.00) at rank 1 with weight 0.85.
    # reliability_score = (1*0.25 + 0.85*1.00) / (1 + 0.85) = 1.10 / 1.85 = 0.594594... -> 0.5946
    # reliability_score_lifetime = (0.25 + 1.00) / 2 = 0.6250
    later_terminal_instant = "2026-08-25T00:00:00Z"
    world = setup_handed_off_engagement()
    set_clock(later_terminal_instant, world["pm_headers"])

    second = add_scoped_request(world, title="Grant compliance review")
    offer = validate_success(
        api_client.match_project_request(second["request"]["id"], world["spec_headers"]),
        201,
    )
    engagement2 = validate_success(
        api_client.accept_match_offer(offer["id"], world["volunteer_headers"]), 201
    )

    terminated = validate_success(
        api_client.terminate_engagement(
            engagement2["id"], world["pm_headers"], {"termination_reason": "ADMIN"}
        ),
        200,
    )

    assert terminated["work_status"] == "TERMINATED", (
        f"Expected the second engagement to reach TERMINATED, got "
        f"{terminated['work_status']}"
    )
    assert _same_instant(terminated["terminated_at"], later_terminal_instant), (
        f"Expected terminated_at stamped from the clock {later_terminal_instant}, got "
        f"{terminated['terminated_at']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.5946, abs=RATIO), (
        f"Expected the decay-weighted reliability_score 0.5946 from 1.10 / 1.85, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.6250, abs=RATIO), (
        f"Expected the unweighted reliability_score_lifetime 0.6250 from (0.25 + 1.00) / 2, "
        f"got {volunteer['reliability_score_lifetime']}"
    )
    assert volunteer["terminal_engagement_count"] == 2, (
        f"Expected terminal_engagement_count 2, got "
        f"{volunteer['terminal_engagement_count']}"
    )
    assert volunteer["open_engagement_count"] == 0, (
        f"Both engagements have left the live states, so open_engagement_count must read 0, "
        f"got {volunteer['open_engagement_count']}"
    )
    assert volunteer["status"] == "ACTIVE", (
        f"0.5946 is above the 0.4000 floor, so no auto-pause fires, got {volunteer['status']}"
    )
    assert volunteer["pause_reason"] is None, (
        f"Expected pause_reason to stay null, got {volunteer['pause_reason']}"
    )

    cycle = read_cycle(world)
    assert cycle["slots_committed"] == 0, (
        f"Both engagements released their slot, got slots_committed "
        f"{cycle['slots_committed']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.0000, abs=RATIO), (
        f"Expected utilization_ratio 0.0000, got {cycle['utilization_ratio']}"
    )


def test_20_a_missed_check_in_docks_a_tenth_from_a_passed_handoff(api):
    """PRD §3.2: "From that value the program subtracts one tenth for each missed check-in the
    engagement recorded — the engagement's `missed_checkin_count` multiplied by 0.10 — rounds the
    result to four decimals, and floors it at zero so no single engagement can contribute a
    negative amount."
    PRD §3.6: "During the cycle checkpoint, a milestone still `SCHEDULED` on an `IN_PROGRESS`
    engagement whose `due_at` plus twenty-four hours has fallen strictly behind the logical clock
    moves `SCHEDULED → MISSED`, raising the engagement's `missed_checkin_count` by one and
    rerunning both of the volunteer's reliability figures."
    PRD §3.6: "It must sit at least three days away from the `due_at` of every sibling milestone
    whose `checkin_status` is `SCHEDULED` or `HELD` — the buffer is 72 hours and its geometry is
    closed, so a separation of exactly 72 hours is accepted while anything strictly closer is
    refused"

    Design: Corner/calculations/calc_reliability_missed_checkin_penalty_reduces_handoff_points
    """
    # One terminal engagement: HANDED_OFF with PASSED is worth 1.00, less 1 * 0.10 for the
    # single missed check-in, so both variants read 0.9000 — the decay-weighted figure has a
    # single rank-0 weight of 1 and the lifetime figure averages a single value.
    hold_instant = "2026-08-04T12:00:00Z"
    world = setup_in_progress_engagement(volunteer_rate=200.00)
    engagement_id = world["engagement"]["id"]
    for _ in range(4):
        validate_success(
            api_client.create_time_log(
                engagement_id,
                time_log_payload(
                    work_date="2026-08-01T09:00:00Z", hours=10.00, activity_class="DELIVERY"
                ),
                world["volunteer_headers"],
            ),
            201,
        )

    first = validate_success(
        api_client.create_milestone(
            engagement_id,
            milestone_payload(due_at="2026-08-02T00:00:00Z"),
            world["pm_headers"],
        ),
        201,
    )
    set_clock("2026-08-03T00:00:01Z", world["pm_headers"])
    validate_success(
        api_client.recalculate_program_cycle(world["cycle"]["id"], world["pm_headers"]),
        200,
    )

    second = validate_success(
        api_client.create_milestone(
            engagement_id,
            milestone_payload(due_at="2026-08-05T00:00:00Z"),
            world["pm_headers"],
        ),
        201,
    )
    set_clock(hold_instant, world["pm_headers"])
    validate_success(
        api_client.hold_milestone(
            second["id"], {"reported_cumulative_hours": 40.00}, world["pm_headers"]
        ),
        200,
    )
    validate_success(
        api_client.submit_engagement(engagement_id, world["volunteer_headers"]), 200
    )
    review = drive_review_to_outcome(
        world, {d["id"]: 5 for d in world["deliverables"]}
    )
    validate_success(
        api_client.decide_quality_review(review["id"], world["reviewer_headers"], {}), 200
    )

    handed_off = validate_success(
        api_client.handoff_engagement(engagement_id, handoff_payload(), world["pm_headers"]),
        200,
    )

    assert handed_off["work_status"] == "HANDED_OFF", (
        f"Expected the engagement to reach HANDED_OFF, got {handed_off['work_status']}"
    )
    assert handed_off["quality_gate"] == "PASSED", (
        f"Expected quality_gate PASSED, got {handed_off['quality_gate']}"
    )
    assert handed_off["missed_checkin_count"] == 1, (
        f"Expected exactly one missed check-in on the record, got "
        f"{handed_off['missed_checkin_count']}"
    )
    assert _same_instant(handed_off["handoff_at"], hold_instant), (
        f"Expected handoff_at stamped from the clock {hold_instant}, got "
        f"{handed_off['handoff_at']}"
    )

    volunteer = read_volunteer(world)
    assert volunteer["reliability_score"] == pytest.approx(0.9000, abs=RATIO), (
        f"Expected reliability_score 0.9000 from 1.00 less one 0.10 penalty, got "
        f"{volunteer['reliability_score']}"
    )
    assert volunteer["reliability_score_lifetime"] == pytest.approx(0.9000, abs=RATIO), (
        f"With one terminal engagement the lifetime average is the same 0.9000, got "
        f"{volunteer['reliability_score_lifetime']}"
    )

    milestones = sorted(read_milestones(world), key=lambda m: m["sequence_no"])
    assert [m["sequence_no"] for m in milestones] == [1, 2], (
        f"Expected two milestones numbered 1 and 2, got "
        f"{[m['sequence_no'] for m in milestones]}"
    )
    assert milestones[0]["id"] == first["id"], (
        "Expected the first-scheduled milestone to hold sequence_no 1"
    )
    assert milestones[0]["checkin_status"] == "MISSED", (
        f"The checkpoint swept the unheld first check-in, so it must read MISSED, got "
        f"{milestones[0]['checkin_status']}"
    )
    assert milestones[1]["checkin_status"] == "HELD", (
        f"The second check-in was held, got {milestones[1]['checkin_status']}"
    )


# ---------------------------------------------------------------------------
# Scope creep and the scope-change projection (PRD §3.7)
# ---------------------------------------------------------------------------
def test_21_creep_landing_exactly_on_the_watch_floor_belongs_to_watch(api):
    """PRD §3.7: "Subtract the baseline from that total, divide by the baseline, and round to four
    decimals. The result drives `creep_escalation_level`: `NONE` below 0.1500, `WATCH` from
    0.1500 up to but not including 0.3000, `ESCALATED` from 0.3000 up to but not including
    0.5000, and `BREACH` at 0.5000 and above. The band floors are inclusive, so exactly 0.1500 is
    `WATCH`"
    PRD §3.8: "On success every remaining unapproved child log flips `approved` to true with
    `approved_at` stamped, and the engagement's `approved_hours` and creep figures are recomputed
    one final time before review."

    Design: Corner/calculations/calc_scope_creep_at_exact_watch_floor
    """
    # The hold approved 40.00 hours against a 40.00 baseline for a creep of 0.0000. Submission
    # approves the trailing 6.00-hour log: (46.00 - 40.00) / 40.00 = 0.1500 exactly, the
    # inclusive WATCH floor, and still short of the BREACH level that would block the submit.
    world = setup_held_milestone_engagement()
    validate_success(
        api_client.create_time_log(
            world["engagement"]["id"],
            time_log_payload(
                work_date="2026-08-19T09:00:00Z", hours=6.00, activity_class="DELIVERY"
            ),
            world["volunteer_headers"],
        ),
        201,
    )

    submitted = validate_success(
        api_client.submit_engagement(
            world["engagement"]["id"], world["volunteer_headers"]
        ),
        200,
    )

    assert submitted["work_status"] == "SUBMITTED", (
        f"Expected the engagement to reach SUBMITTED, got {submitted['work_status']}"
    )
    assert submitted["committed_hours"] == pytest.approx(40.00, abs=CENT), (
        f"The baseline is untouched by logging, so committed_hours must stay 40.00, got "
        f"{submitted['committed_hours']}"
    )
    assert submitted["approved_hours"] == pytest.approx(46.00, abs=CENT), (
        f"Submission approves the trailing log, so approved_hours must read 46.00, got "
        f"{submitted['approved_hours']}"
    )
    assert submitted["scope_creep_pct"] == pytest.approx(0.1500, abs=RATIO), (
        f"Expected scope_creep_pct 0.1500 from (46.00 - 40.00) / 40.00, got "
        f"{submitted['scope_creep_pct']}"
    )
    assert submitted["creep_escalation_level"] == "WATCH", (
        f"0.1500 sits on the inclusive WATCH floor, got "
        f"{submitted['creep_escalation_level']}"
    )


def test_22_one_extra_deliverable_blocks_the_automatic_scope_change_branch(api):
    """PRD §3.7: "Before the row is persisted the program projects its effect: take the
    engagement's `approved_hours`, add the sum of `additional_hours` over sibling change requests
    whose `status` is `PENDING` or `ESCALATED` — excluding the incoming row — add the incoming
    row's own `additional_hours`, subtract the engagement's `committed_hours` baseline, divide by
    that baseline and round to four decimals."
    PRD §3.7: "the `decision_tier` is chosen from it by tests applied in exactly this order: a
    projection at or above 0.5000 is `RESCOPE_REQUIRED`; otherwise a projection strictly below
    0.1500 that also carries an `additional_deliverable_count` of exactly zero is
    `AUTO_APPROVABLE`; everything else is `MANAGER_REVIEW`. The order matters — a modest
    projection below 0.1500 that nevertheless asks for at least one extra deliverable falls to
    `MANAGER_REVIEW`, not to automatic approval."
    PRD §3.7: "A `MANAGER_REVIEW` change is stored in `PENDING` with a null
    `decided_by_user_id` and a null `decided_at`, and its pending hours immediately raise the
    engagement's `scope_creep_pct` even though no work has been done against them."

    Design: Corner/calculations/calc_scope_change_projection_deliverable_count_forces_manager_review
    """
    # Projection: (0.00 approved + 0.00 sibling + 4.00 incoming - 40.00) / 40.00 = -0.9000.
    # That is far below the 0.1500 auto floor, but the one extra deliverable disqualifies the
    # AUTO_APPROVABLE branch, so the row falls through to MANAGER_REVIEW and stays PENDING.
    world = setup_in_progress_engagement()

    change = validate_success(
        api_client.create_scope_change_request(
            world["engagement"]["id"],
            scope_change_request_payload(
                additional_hours=4.00,
                additional_deliverable_count=1,
                justification="Board wants a separate one-page summary.",
            ),
            world["partner_headers"],
        ),
        201,
    )

    assert change["projected_creep_pct"] == pytest.approx(-0.9000, abs=RATIO), (
        f"Expected projected_creep_pct -0.9000 from (4.00 - 40.00) / 40.00, got "
        f"{change['projected_creep_pct']}"
    )
    assert change["decision_tier"] == "MANAGER_REVIEW", (
        f"An additional_deliverable_count above zero rules out AUTO_APPROVABLE, got "
        f"{change['decision_tier']}"
    )
    assert change["status"] == "PENDING", (
        f"A MANAGER_REVIEW change is stored in PENDING, got {change['status']}"
    )
    assert change["additional_deliverable_count"] == 1, (
        f"Expected additional_deliverable_count 1, got "
        f"{change['additional_deliverable_count']}"
    )

    engagement = read_engagement(world)
    assert engagement["committed_hours"] == pytest.approx(40.00, abs=CENT), (
        f"An undecided change moves no hours, so committed_hours must stay 40.00, got "
        f"{engagement['committed_hours']}"
    )
    assert engagement["approved_hours"] == pytest.approx(0.00, abs=CENT), (
        f"No hours have been approved, got {engagement['approved_hours']}"
    )
    assert engagement["scope_creep_pct"] == pytest.approx(-0.9000, abs=RATIO), (
        f"The pending hours enter the creep numerator at once, so scope_creep_pct must read "
        f"-0.9000, got {engagement['scope_creep_pct']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"A negative ratio sits below the 0.1500 floor, got "
        f"{engagement['creep_escalation_level']}"
    )

    window = read_window(world)
    assert window["hours_committed"] == pytest.approx(40.00, abs=CENT), (
        f"The window still holds only the engagement's committed 40.00 hours, got "
        f"{window['hours_committed']}"
    )
