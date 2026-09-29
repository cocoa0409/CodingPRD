"""Derived numbers: routing, eligible pools, weighted scores, tier lookups and
the two benefit-cost ratios."""
from test_helpers import (
    ADMIN_RULE_DRAFTER_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_technical_staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

MECHANICAL_PROPOSAL = {
    "code_section": "M403.3.1",
    "discipline": "MECHANICAL",
    "title": "Ventilation rate table cleanup",
    "proposed_text": (
        "Restate the outdoor air rate table without changing required rates."
    ),
    "stringency_direction": "NEUTRAL",
    "proposer_sector": "DESIGN_PROFESSIONAL",
}

# One hundredth of a point below the statutory floor once the savings stream is
# discounted over its 12-year measure life.
BELOW_FLOOR_COST_BENEFIT = {"annual_cost_savings_cents": 14223000}

# 3042 permits annualise to exactly 500, the first backlog on the medium tier.
TIER_BOUNDARY_COST_BENEFIT = {
    "incremental_cost_by_occupancy": {"R3": 10000, "R2": 12000, "B": 15000, "A2": 18000},
    "affected_permit_count": 3042,
    "annual_cost_savings_cents": 3000000,
    "measure_life_years": 20,
}

NORTHGATE_OUTCOMES = {
    "northgate_1": "ATTENDED",
    "northgate_2": "ATTENDED",
    "northgate_3": "NO_SHOW",
    "northgate_4": "NO_SHOW",
}


def _northgate_session(api):
    """A 60-seat session hosted by Riverbend whose only four enrollments are
    Northgate building officials, with enrollment closed and the clock standing
    at the session's end."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_northgate(api, world)
    fixtures.setup_enrollment_open_session(api, world=world)
    for index in range(1, 5):
        fixtures.add_enrollment(
            api,
            world,
            f"northgate_{index}",
            "northgate",
            f"Northgate Official {index}",
        )
    fixtures.set_session_status(api, world, "ENROLLMENT_CLOSED")
    fixtures.set_logical_clock(api, fixtures.CLOCK_SESSION_ENDS)
    return world


def test_01_a_mechanical_proposal_routes_to_the_mechanical_committee(api):
    """"The proposal's `committee_id` is resolved by finding the discipline
    committees of the named cycle whose own `discipline` equals the proposal's
    `discipline` and whose `status` is anything other than `DISSOLVED`", and
    "because a cycle holds at most one live committee per discipline, that search
    yields at most one candidate, and its `id` becomes the proposal's
    `committee_id`". With both an energy and a mechanical committee on one cycle,
    the mechanical proposal reaches the mechanical docket and the energy docket
    stays empty.

    Design: Corner/calculations/committee_assignment_routes_the_proposal_by_discipline
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")

    response = api.create_amendment_proposal(
        factories.create_amendment_proposal_payload(
            world["cycle_id"], **MECHANICAL_PROPOSAL
        ),
        make_technical_staff_headers(),
    )
    proposal = validate_success(response, 201)
    assert proposal["committee_id"] == world["mechanical_committee_id"]
    assert proposal["committee_id"] != world["committee_id"]
    assert proposal["discipline"] == "MECHANICAL"

    _, mechanical = validate_paginated(
        api.list_committee_amendment_proposals(
            world["mechanical_committee_id"], make_council_admin_headers()
        )
    )
    assert mechanical["total_count"] == 1

    _, energy = validate_paginated(
        api.list_committee_amendment_proposals(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert energy["total_count"] == 0


def test_02_the_agenda_pool_excludes_a_merely_screened_sibling(api):
    """The pool holds only the committee's proposals "whose `review_status` is
    `COMMENT_CLOSED` and whose `analysis_status` is `COMPLETE`", and the rank
    bonus "is then applied over the selected items only, setting each one's
    `docket_queue_rank` and `docket_priority_score`". The sibling is still
    `SCREENED`, so it is left off the agenda and keeps both docket fields null,
    while the single selected item takes 74.45 plus the rank-1 award of 5.00.

    Design: Corner/calculations/agenda_selection_excludes_proposals_not_yet_comment_closed
    """
    world = fixtures.setup_comment_closed_with_screened_sibling(api)
    fixtures.add_scheduled_hearing(api, world)

    hearing = validate_success(fixtures.fill_agenda(api, world))
    assert hearing["agenda_proposal_ids"] == [world["proposal_id"]]

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["docket_queue_rank"] == 1
    assert proposal["docket_priority_score"] == 79.45

    sibling = fixtures.read_proposal(api, world["sibling_id"])
    assert sibling["review_status"] == "SCREENED"
    assert sibling["analysis_status"] == "PENDING"
    assert sibling["docket_queue_rank"] is None
    assert sibling["docket_priority_score"] is None


def test_03_the_base_score_blends_the_three_declared_weights(api):
    """"`base_docket_score` is then 0.45 times the support ratio plus 0.35 times
    the stringency award plus 0.20 times the cost points, the whole sum multiplied
    by 100 and rounded half up to 2 decimal places", where the cost points are
    "1 minus that ratio" against "the two-million-dollar cost cap of 200,000,000
    cents". Three supporting and one opposing comment give 0.7500, a
    `MORE_STRINGENT` amendment awards 1.00, and 143,002,800 cents leaves cost
    points of 0.284986, so the frozen score is 74.45 and the rank bonus is not
    yet applied.

    Design: Corner/calculations/docket_base_score_applies_declared_weights_and_cost_cap
    """
    world = fixtures.setup_proposal_comment_open(api)
    fixtures.submit_golden_comments(api, world)
    fixtures.set_logical_clock(api, fixtures.CLOCK_COMMENT_CLOSES)

    proposal = validate_success(fixtures.act_on_comment_window(api, world, "CLOSE"))
    assert proposal["support_comment_count"] == 3
    assert proposal["oppose_comment_count"] == 1
    assert proposal["total_comment_count"] == 4
    assert proposal["base_docket_score"] == 74.45
    assert proposal["review_status"] == "COMMENT_CLOSED"
    assert proposal["comment_window_status"] == "CLOSED"
    assert proposal["docket_queue_rank"] is None


def test_04_compliance_rounds_half_up_on_one_basis_and_caps_on_the_other(api):
    """"`compliance_pct_enrollment_basis` is 100 multiplied by the
    enrollment-basis numerator, divided by `official_headcount`, rounded half up
    to 2 decimal places and then capped at 100.00", and the attendance basis "is
    the same arithmetic on the attendance-basis numerator". Northgate's three
    officials against four distinct seats give 133.33 capped to 100.00, while two
    attenders give 66.67 — below the 80.00 that `enforcement_readiness` demands.
    Riverbend, which sent nobody, reads 0.00.

    Design: Corner/calculations/training_compliance_rounds_half_up_and_caps_at_one_hundred
    """
    world = _northgate_session(api)

    session = validate_success(
        fixtures.record_attendance(
            api, world, fixtures.attendance_for(world, NORTHGATE_OUTCOMES)
        )
    )
    assert session["status"] == "DELIVERED"
    assert session["attended_count"] == 2
    assert session["no_show_count"] == 2
    assert session["enrolled_count"] == 0
    assert session["seats_available"] == 56

    northgate = fixtures.read_jurisdiction(api, world["northgate_id"])
    assert northgate["compliance_pct_enrollment_basis"] == 100.00
    assert northgate["compliance_pct_attendance_basis"] == 66.67
    assert northgate["enforcement_readiness"] == "NOT_READY"

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_enrollment_basis"] == 0.00
    assert riverbend["enforcement_readiness"] == "NOT_READY"


def test_05_a_final_ratio_of_zero_point_nine_nine_blocks_the_approving_vote(api):
    """"The final benefit-cost ratio is recomputed from scratch ... and if the
    rounded 2-decimal result is below 1.00 the call is refused with
    `ERR_BENEFIT_COST_BELOW_FLOOR`", and the comparison "is made on the rounded
    2-decimal value, so a raw result of 0.995032 rounds to 1.00 and passes while
    0.990021 rounds to 0.99 and fails". Annual savings of 14,223,000 cents
    discounted over 12 years against 143,002,800 cents land on 0.99, even though
    the undiscounted preliminary ratio of 1.49 "is never used as a gate".

    Design: Corner/calculations/benefit_cost_ratio_one_notch_below_floor_blocks_the_vote
    """
    world = fixtures.setup_convened_hearing(
        api, cost_benefit_overrides=BELOW_FLOOR_COST_BENEFIT
    )

    response = fixtures.record_vote(api, world)
    validate_error(response, ApiErrorId.ERR_BENEFIT_COST_BELOW_FLOOR, 422)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["preliminary_benefit_cost_ratio"] == 1.49
    assert proposal["statewide_incremental_cost_cents"] == 143002800
    assert proposal["review_status"] == "COMMENT_CLOSED"

    _, hearing_votes = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing_votes["total_count"] == 0

    _, proposal_votes = validate_paginated(
        api.list_proposal_vote_records(
            world["proposal_id"], make_council_admin_headers()
        )
    )
    assert proposal_votes["total_count"] == 0

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_proposal_count"] == 0

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "CONVENED"


def test_06_a_projected_backlog_of_exactly_five_hundred_takes_the_medium_tier(api):
    """"`projected_permit_backlog` is the approved backlog multiplied by 60 and
    divided by 365, with the result taken down to the next lower whole permit by
    floor division", then "`transition_grace_days` is 90 days when the projected
    backlog is below 500, 180 days when it is below 5,000", and "`notice_days`
    ... is the greater of 120 and `transition_grace_days`". 3,042 permits
    annualise to exactly 500, which is not below 500, so the grace tier is 180
    days and the notice period stays at 180; `effective_date` is `base_date`
    advanced by 180 days and `prior_code_expiry_date` a further 365 beyond it.

    Design: Corner/calculations/adoption_schedule_backlog_tier_boundary_at_exactly_five_hundred
    """
    world = fixtures.setup_rulemaking_cycle(
        api, cost_benefit_overrides=TIER_BOUNDARY_COST_BENEFIT
    )

    response = api.create_adoption_rule(
        factories.create_adoption_rule_payload(world["cycle_id"]),
        make_council_admin_headers(ADMIN_RULE_DRAFTER_ID),
    )
    rule = validate_success(response, 201)
    assert rule["status"] == "DRAFT"
    assert rule["base_date"] == "2026-10-05T00:00:00Z"
    assert rule["projected_permit_backlog"] == 500
    assert rule["transition_grace_days"] == 180
    assert rule["notice_days"] == 180
    assert rule["effective_date"] == "2027-04-03T00:00:00Z"
    assert rule["transition_cutoff_date"] == "2027-04-03T00:00:00Z"
    assert rule["prior_code_expiry_date"] == "2028-04-02T00:00:00Z"

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["statewide_incremental_cost_cents"] == 35285000
    assert proposal["final_benefit_cost_ratio"] == 1.26

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_permit_backlog_count"] == 3042


def test_07_the_rank_award_follows_position_not_the_score_gap(api):
    """"The eligible pool is ordered by `base_docket_score` descending", and "the
    rank adjustment is 5.00 for rank 1, 2.00 for rank 2, and 0.00 for every other
    rank". The commented `MORE_STRINGENT` amendment scores 74.45 and the
    uncommented `NEUTRAL` one 62.69 — a comment-free proposal takes "the neutral
    default of 0.5000" — so the agenda lists them in that order and the awards
    give 79.45 and 64.69.

    Design: Corner/calculations/docket_rank_bonuses_apply_to_first_and_second_agenda_items
    """
    world = fixtures.setup_two_comment_closed_proposals(api)
    fixtures.add_scheduled_hearing(api, world)

    hearing = validate_success(fixtures.fill_agenda(api, world))
    assert hearing["agenda_proposal_ids"] == [world["proposal_id"], world["sibling_id"]]

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["base_docket_score"] == 74.45
    assert proposal["docket_queue_rank"] == 1
    assert proposal["docket_priority_score"] == 79.45

    sibling = fixtures.read_proposal(api, world["sibling_id"])
    assert sibling["base_docket_score"] == 62.69
    assert sibling["docket_queue_rank"] == 2
    assert sibling["docket_priority_score"] == 64.69
    assert sibling["total_comment_count"] == 0
