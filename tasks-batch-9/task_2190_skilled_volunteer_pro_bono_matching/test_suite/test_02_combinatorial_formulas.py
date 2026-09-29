"""Multi-input formulas: the selector score, the quality rubric and the overhead tier."""
import pytest

from test_helpers import (
    api_client,
    current_engagement_version,
    drive_review_to_outcome,
    read_cycle,
    read_deliverables,
    read_engagement,
    read_scope,
    read_volunteer,
    read_window,
    setup_held_milestone_engagement,
    setup_selector_world,
    setup_submitted_engagement,
    validate_success,
)

WINDOW_2026_08_05 = {
    "starts_at": "2026-08-05T00:00:00Z",
    "ends_at": "2026-10-01T00:00:00Z",
    "window_kind": "HARD",
}

CONTRACT_PACK = [
    {
        "title": "Contract pack",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 30.00,
        "acceptance_criteria": "All shelter contracts executed",
    }
]

GOVERNANCE_DELIVERABLES = [
    {
        "title": "Bylaw memo",
        "sequence_no": 1,
        "weight_pct": 5.00,
        "hours_estimate": 2.00,
        "acceptance_criteria": "Memo accepted by board chair",
    },
    {
        "title": "Conflict policy",
        "sequence_no": 2,
        "weight_pct": 15.02,
        "hours_estimate": 6.00,
        "acceptance_criteria": "Policy adopted",
    },
    {
        "title": "Restated bylaws",
        "sequence_no": 3,
        "weight_pct": 79.98,
        "hours_estimate": 32.00,
        "acceptance_criteria": "Bylaws filed",
    },
]

FORTY_DELIVERY_HOURS = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 10.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-15T00:00:00Z", "hours": 6.00, "activity_class": "DELIVERY"},
]

COMPLIANCE_DELIVERABLE = [
    {
        "title": "Compliance manual",
        "sequence_no": 1,
        "weight_pct": 100.00,
        "hours_estimate": 40.00,
        "acceptance_criteria": "Manual adopted",
    }
]

MIXED_LOGS_2380 = [
    {"work_date": "2026-08-12T00:00:00Z", "hours": 12.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-13T00:00:00Z", "hours": 11.00, "activity_class": "DELIVERY"},
    {"work_date": "2026-08-14T00:00:00Z", "hours": 1.60, "activity_class": "ADMIN"},
]


def _two_candidate_critical_request():
    """A CRITICAL request needing 30.00 hours, with a short-window ASSOCIATE holding a
    verified proficiency-5 claim against a covering-window SENIOR holding an unverified
    proficiency-3 claim."""
    return setup_selector_world(
        [
            {
                "seniority": "ASSOCIATE",
                "professional_rate_usd_per_hour": 120.00,
                "weekly_hours_cap": 20,
                "proficiency": 5,
                "verify_skill": True,
                "years_experience": 12.0,
                "window_overrides": dict(WINDOW_2026_08_05, hours_offered=24.00),
            },
            {
                "seniority": "SENIOR",
                "professional_rate_usd_per_hour": 150.00,
                "weekly_hours_cap": 40,
                "proficiency": 3,
                "verify_skill": False,
                "years_experience": 6.0,
                "window_overrides": dict(WINDOW_2026_08_05, hours_offered=45.00),
            },
        ],
        clock="2026-08-10T00:00:00Z",
        urgency="CRITICAL",
        requested_hours=25.00,
        estimated_hours=25.00,
        complexity_factor=1.20,
        deliverables=CONTRACT_PACK,
        title="Emergency shelter contracts",
    )


def test_selector_applies_the_shortfall_penalty_before_the_seniority_multiplier(api):
    """PRD §3.4: "The penalty is that shortfall multiplied by 0.004 per hour, rounded to
    four decimals, and capped at 0.30."
    PRD §3.4: "Subtract the penalty from that raw score, floor the result at 0.0000,
    multiply by a seniority multiplier — 0.90 for `ASSOCIATE`, 1.00 for `SENIOR`, 1.08 for
    `PRINCIPAL` and 1.12 for `PARTNER` — and round to four decimals."
    PRD §3.4: "The top-ranked candidate wins, and her score is persisted on the resulting
    offer as `match_score`."

    Design: Difficulty/combinatorial_formula/match_score_mode_a_nonlinear_selector_ranking
    """
    world = _two_candidate_critical_request()
    short_window_associate, covering_senior = world["candidates"]

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        expected_status=201,
    )

    assert offer["volunteer_id"] == covering_senior["volunteer"]["id"], (
        "The covering SENIOR window must outrank the penalised ASSOCIATE, got offer for "
        f"{offer['volunteer_id']}"
    )
    assert offer["volunteer_id"] != short_window_associate["volunteer"]["id"], (
        "The 6.00-hour shortfall plus the 0.90 multiplier must lose the ranking"
    )
    assert offer["match_score"] == pytest.approx(0.8475, abs=1e-4), (
        f"Expected match_score 0.8475, got {offer['match_score']}"
    )
    assert offer["availability_window_id"] == covering_senior["window"]["id"], (
        f"Expected the winning volunteer's own window, got "
        f"{offer['availability_window_id']}"
    )


def test_offer_reserves_the_complexity_adjusted_hours_and_expires_in_one_day(api):
    """PRD §3.4: "The hours the engagement would need — call them the required hours — are
    the pinned revision's `estimated_hours` multiplied by its `complexity_factor`, rounded
    to two decimals."
    PRD §3.4: "Its `reserved_hours` is the required-hours figure computed above, its
    `offered_at` is the logical clock, and its `expires_at` is `offered_at` plus a
    time-to-live chosen by the request's `urgency`: five days for a `ROUTINE` request,
    three days for an `ELEVATED` one, and a single day for a `CRITICAL` one."
    PRD §3.4: "A winning selection writes a match offer in `status` `OFFERED` against the
    request, recording the winning `volunteer_id`, the `scope_definition_id` of the
    `APPROVED` revision pinned at this instant, the `availability_window_id` of the chosen
    window, and a `round_no` equal to the request's `failed_match_rounds` plus one at offer
    time — so the first offer on a request is round 1."

    Design: Difficulty/combinatorial_formula/match_score_mode_a_nonlinear_selector_ranking
    """
    world = _two_candidate_critical_request()

    offer = validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        expected_status=201,
    )

    assert offer["reserved_hours"] == pytest.approx(30.00, abs=0.01), (
        f"Expected reserved_hours 30.00 from 25.00 x 1.20, got {offer['reserved_hours']}"
    )
    assert offer["round_no"] == 1, f"Expected round_no 1, got {offer['round_no']}"
    assert offer["status"] == "OFFERED", f"Expected status OFFERED, got {offer['status']}"
    assert offer["expires_at"].startswith("2026-08-11T00:00:00"), (
        f"Expected a CRITICAL one-day expiry at 2026-08-11T00:00:00Z, got "
        f"{offer['expires_at']}"
    )
    assert offer["scope_definition_id"] == world["scope"]["id"], (
        f"Expected the approved revision to be pinned, got {offer['scope_definition_id']}"
    )


def test_offer_holds_hours_on_the_winning_window_only(api):
    """PRD §3.4: "Two ledger movements accompany the offer: the chosen window's
    `hours_committed` rises by the offer's `reserved_hours`, and the cycle's
    `slots_reserved` rises by one, after which the posture calculation reruns and may carry
    the cycle from `OPEN` to `RESTRICTED` or on to `FROZEN`."
    PRD §3.1: "`posture` is `OPEN` while utilization is below 0.8000, `RESTRICTED` from
    0.8000 up to but not including 1.0000, and `FROZEN` at 1.0000 and above; both band
    floors are inclusive, so a utilization of exactly 0.8000 is `RESTRICTED` and exactly
    1.0000 is `FROZEN`."

    Design: Difficulty/combinatorial_formula/match_score_mode_a_nonlinear_selector_ranking
    """
    world = _two_candidate_critical_request()
    losing_candidate, winning_candidate = world["candidates"]

    validate_success(
        api_client.match_project_request(world["request"]["id"], world["spec_headers"]),
        expected_status=201,
    )

    winner_window = read_window(
        world,
        window_id=winning_candidate["window"]["id"],
        volunteer_id=winning_candidate["volunteer"]["id"],
    )
    assert winner_window["hours_committed"] == pytest.approx(30.00, abs=0.01), (
        f"Expected hours_committed 30.00, got {winner_window['hours_committed']}"
    )
    assert winner_window["hours_remaining"] == pytest.approx(15.00, abs=0.01), (
        f"Expected hours_remaining 15.00, got {winner_window['hours_remaining']}"
    )
    loser_window = read_window(
        world,
        window_id=losing_candidate["window"]["id"],
        volunteer_id=losing_candidate["volunteer"]["id"],
    )
    assert loser_window["hours_committed"] == pytest.approx(0.00, abs=0.01), (
        f"The unselected window must hold nothing, got {loser_window['hours_committed']}"
    )
    cycle = read_cycle(world)
    assert cycle["slots_reserved"] == 1, (
        f"Expected slots_reserved 1, got {cycle['slots_reserved']}"
    )
    assert cycle["utilization_ratio"] == pytest.approx(0.1000, abs=1e-4), (
        f"Expected utilization_ratio 0.1000, got {cycle['utilization_ratio']}"
    )
    assert cycle["posture"] == "OPEN", f"Expected posture OPEN, got {cycle['posture']}"


# ---------------------------------------------------------------------------
# The quality rubric: rounding each contribution before summing
# ---------------------------------------------------------------------------
def _scored_governance_review():
    world = setup_submitted_engagement(
        skill_code="LEGAL_CONTRACTS",
        deliverables=GOVERNANCE_DELIVERABLES,
        time_logs=FORTY_DELIVERY_HOURS,
        reported_cumulative_hours=40.00,
        title="Governance overhaul",
    )
    first, second, third = world["deliverables"]
    review = drive_review_to_outcome(
        world,
        {first["id"]: 5, second["id"]: 3, third["id"]: 4},
    )
    return world, review


def test_weighted_quality_score_rounds_each_contribution_before_summing(api):
    """PRD §3.8: "For each deliverable in the pinned order, divide its `weight_pct` by that
    active total and round to six decimals, then multiply that normalised weight by the
    deliverable's `review_score` and by a scale factor of 20, rounding each deliverable's
    contribution to two decimals *before* summing."
    PRD §3.8: "The review's `weighted_score` is the sum of those per-deliverable
    contributions, rounded to two decimals; summing normalised weights first and rounding
    once at the end is not equivalent and is not permitted."

    Design: Difficulty/combinatorial_formula/deliverable_quality_mode_b_per_item_rounding_flips_band
    """
    world, review = _scored_governance_review()

    scope = read_scope(world)
    assert scope["deliverable_weight_total_pct"] == pytest.approx(100.00, abs=0.01), (
        f"Expected an active weight total of 100.00, got "
        f"{scope['deliverable_weight_total_pct']}"
    )
    assert review["weighted_score"] == pytest.approx(77.99, abs=0.01), (
        f"Expected weighted_score 77.99 from contributions 5.00 + 9.01 + 63.98, got "
        f"{review['weighted_score']}"
    )
    assert review["weighted_score"] != pytest.approx(78.00, abs=0.001), (
        "Summing the products before rounding would yield 78.00, which is not permitted"
    )


def test_quality_outcome_lands_conditional_one_cent_below_the_pass_floor(api):
    """PRD §3.8: "The `outcome` follows from the score: `PASS` at 78.00 and above,
    `CONDITIONAL` from 60.00 up to but not including 78.00, and `FAIL` below 60.00."
    PRD §3.8: "Scoring also recomputes `scored_deliverable_count`, the number of
    non-`WAIVED` deliverables on the pinned revision now carrying a non-null
    `review_score`, and moves the review `OPEN → SCORED`."

    Design: Difficulty/combinatorial_formula/deliverable_quality_mode_b_per_item_rounding_flips_band
    """
    world, review = _scored_governance_review()

    assert review["outcome"] == "CONDITIONAL", (
        f"A weighted_score of 77.99 is below the 78.00 pass floor, so the outcome must be "
        f"CONDITIONAL; got {review['outcome']}"
    )
    assert review["status"] == "SCORED", f"Expected status SCORED, got {review['status']}"
    assert review["scored_deliverable_count"] == 3, (
        f"Expected scored_deliverable_count 3, got {review['scored_deliverable_count']}"
    )
    deliverables = {d["sequence_no"]: d for d in read_deliverables(world)}
    assert deliverables[2]["review_score"] == 3, (
        f"Expected the second deliverable to carry review_score 3, got "
        f"{deliverables[2]['review_score']}"
    )
    engagement = read_engagement(world)
    assert engagement["work_status"] == "SUBMITTED", (
        f"Scoring alone must not move the engagement, got {engagement['work_status']}"
    )
    assert engagement["quality_gate"] == "PENDING", (
        f"Expected quality_gate PENDING before the decision, got "
        f"{engagement['quality_gate']}"
    )


# ---------------------------------------------------------------------------
# Overhead: the tier reads the base, never the total
# ---------------------------------------------------------------------------
def _valuation_with_base_2380():
    world = setup_held_milestone_engagement(
        skill_code="LEGAL_CONTRACTS",
        volunteer_seniority="SENIOR",
        volunteer_rate=100.00,
        deliverables=COMPLIANCE_DELIVERABLE,
        time_logs=MIXED_LOGS_2380,
        reported_cumulative_hours=24.60,
        title="Grant compliance rebuild",
    )
    record = validate_success(
        api_client.create_valuation(
            world["engagement"]["id"],
            {
                "expected_engagement_version": current_engagement_version(world),
                "method": "MARKET_RATE",
            },
            world["pm_headers"],
        ),
        expected_status=201,
    )
    return world, record


def test_overhead_tier_is_keyed_on_the_base_even_when_the_total_crosses_a_band(api):
    """PRD §3.9: "Second, the overhead tier is selected from `base_amount_usd` and never
    from the total: a base below 2500.00 takes a rate of 0.12, a base from 2500.00 up to
    but not including 10000.00 takes 0.09, and a base of 10000.00 or more takes 0.06."
    PRD §3.9: "A base of 2380.00 therefore takes the 0.12 rate, yielding 285.60 of overhead
    and a total of 2665.60, even though the resulting total sits inside the 0.09 band."

    Design: Difficulty/combinatorial_formula/admin_overhead_mode_c_tier_keyed_on_base_not_total
    """
    _world, record = _valuation_with_base_2380()

    assert record["base_amount_usd"] == pytest.approx(2380.00, abs=0.01), (
        f"Expected base_amount_usd 2380.00, got {record['base_amount_usd']}"
    )
    assert record["admin_overhead_usd"] == pytest.approx(285.60, abs=0.01), (
        f"Expected admin_overhead_usd 285.60 at the 0.12 tier, got "
        f"{record['admin_overhead_usd']}"
    )
    assert record["total_amount_usd"] == pytest.approx(2665.60, abs=0.01), (
        f"Expected total_amount_usd 2665.60, got {record['total_amount_usd']}"
    )
    assert record["admin_overhead_usd"] != pytest.approx(239.90, abs=0.001), (
        "Keying the tier off the total would produce 239.90 of overhead"
    )
    assert record["total_amount_usd"] != pytest.approx(2905.50, abs=0.001), (
        "Keying the tier off the total would produce a 2905.50 total"
    )


def test_market_rate_base_is_summed_per_line_across_delivery_and_admin(api):
    """PRD §3.9: "The record's `base_amount_usd` is the sum of those per-line figures,
    rounded to two decimals; it must be computed per line and then summed, never by summing
    hours first and multiplying once."
    PRD §3.7: "The engagement's `approved_hours` is the sum of `hours` over its child logs
    whose `approved` flag is true, across every activity class without exception, rounded to
    two decimals."
    PRD §2.10: "records of the `MARKET_RATE` method never enter this total, and superseded
    records leave it the moment they are stamped."

    Design: Difficulty/combinatorial_formula/admin_overhead_mode_c_tier_keyed_on_base_not_total
    """
    world, record = _valuation_with_base_2380()

    assert record["hours_included"] == pytest.approx(24.60, abs=0.01), (
        f"Expected hours_included 24.60, got {record['hours_included']}"
    )
    assert record["rate_applied_usd"] == pytest.approx(100.00, abs=0.01), (
        f"Expected rate_applied_usd 100.00, got {record['rate_applied_usd']}"
    )
    engagement = read_engagement(world)
    assert engagement["approved_hours"] == pytest.approx(24.60, abs=0.01), (
        f"Expected approved_hours 24.60, got {engagement['approved_hours']}"
    )
    assert engagement["creep_escalation_level"] == "NONE", (
        f"24.60 approved against 40.00 committed is negative creep, so the level stays "
        f"NONE; got {engagement['creep_escalation_level']}"
    )
    volunteer = read_volunteer(world)
    assert volunteer["lifetime_valued_usd"] == pytest.approx(0.00, abs=0.01), (
        f"A MARKET_RATE record must not enter lifetime_valued_usd, got "
        f"{volunteer['lifetime_valued_usd']}"
    )
