"""Declared transitions, refused transitions, and the moves the server makes
on its own initiative."""
from test_helpers import (
    ADMIN_EFFECTIVE_ID,
    ADMIN_LOCAL_REVIEWER_ID,
    ADMIN_OPS_ID,
    ADMIN_PUBLISHER_ID,
    ADMIN_SECOND_REVIEWER_ID,
    STAFF_SECOND_ANALYST_ID,
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

REPLACEMENT_COST_BENEFIT = {
    "incremental_cost_by_occupancy": {"R3": 10000, "R2": 12000, "B": 15000, "A2": 18000},
    "affected_permit_count": 700,
    "annual_cost_savings_cents": 900000,
    "measure_life_years": 20,
}

RECUSALS = (
    ("public", "Employer submitted a competing proposal."),
    ("design", "Firm of record on an affected project."),
    ("industry_two", "Direct financial interest in the assembly."),
)


def _recuse(api, world, key, reason):
    return api.act_on_committee_member_recusal(
        world["members"][key]["id"],
        factories.recusal_payload("RECUSE", recusal_reason=reason),
        make_council_admin_headers(),
    )


def _agenda_filled_hearing(api):
    """A COMMENT_CLOSED proposal on the agenda of a SCHEDULED hearing, with the
    clock still standing at the comment window's closing instant."""
    world = fixtures.setup_proposal_comment_closed(api)
    fixtures.add_scheduled_hearing(api, world)
    fixtures.fill_agenda(api, world)
    return world


def test_01_a_freshly_filed_local_amendment_starts_in_submitted(api):
    """"The filing starts in `SUBMITTED` with `revision_round` at 0,
    `reviewed_by_user_id` null, and `filed_within_window` evaluated on the spot:
    it is true when the filing's `created_at` is at or before the order's
    `published_at` plus 90 days, inclusive at the boundary." Only acceptance
    increments `effective_local_amendment_count`, so the jurisdiction's ledger
    still reads 0.

    Design: Corner/state_machines/new_local_amendment_starts_in_submitted
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)

    response = fixtures.file_local_amendment(api, world)
    amendment = validate_success(response, 201)
    assert amendment["status"] == "SUBMITTED"
    assert amendment["revision_round"] == 0
    assert amendment["filed_within_window"] is True
    assert amendment["reviewed_by_user_id"] is None
    assert amendment["jurisdiction_id"] == world["riverbend_id"]
    assert amendment["adoption_rule_id"] == world["rule_id"]

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["effective_local_amendment_count"] == 0


def test_02_convening_at_the_scheduled_start_records_the_roll_call(api):
    """"On success the hearing moves `SCHEDULED` → `CONVENED`,
    `present_voting_count` and a snapshot of the committee's `quorum_required` in
    `quorum_required_at_convene` are stored, `convened_at` is stamped from the
    clock". Six active voting seats put `quorum_required` at "two thirds of
    `active_voting_member_count`, rounded up to the next whole member" — four.

    Design: Corner/state_machines/hearing_convene_moves_scheduled_to_convened
    """
    world = _agenda_filled_hearing(api)
    fixtures.set_logical_clock(api, fixtures.CLOCK_HEARING_START)

    hearing = validate_success(fixtures.convene_hearing(api, world))
    assert hearing["status"] == "CONVENED"
    assert hearing["convened_at"] == "2026-10-05T14:00:00Z"
    assert hearing["present_voting_count"] == 6
    assert hearing["quorum_required_at_convene"] == 4
    assert len(hearing["present_member_ids"]) == 6


def test_03_convening_before_the_scheduled_start_is_refused(api):
    """"The clock must stand at or after `scheduled_start`, or the attempt is
    refused with `ERR_HEARING_NOT_STARTED`." With the clock still at the comment
    window's closing instant of 2026-09-09, a sitting scheduled for 2026-10-05
    has not begun, and the refusal leaves the hearing `SCHEDULED` with
    `convened_at` null.

    Design: Corner/state_machines/convene_before_scheduled_start_is_rejected
    """
    world = _agenda_filled_hearing(api)

    response = fixtures.convene_hearing(api, world)
    validate_error(response, ApiErrorId.ERR_HEARING_NOT_STARTED, 409)

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "SCHEDULED"
    assert hearing["convened_at"] is None


def test_04_accepting_at_screening_seeds_the_second_dimension(api):
    """"Accepting a `SUBMITTED` proposal for analysis advances `review_status`
    `SUBMITTED` → `SCREENED` and, in the same call, advances the second dimension
    `NOT_STARTED` → `PENDING`. The same call also fixes
    `energy_analysis_required`, which is true when the proposal's `discipline` is
    `ENERGY` or its `stringency_direction` is `MORE_STRINGENT`", and "every
    screening decision increments the proposal's `version` by one". No analysis
    row exists yet.

    Design: Corner/state_machines/screening_accept_seeds_analysis_dimension_and_energy_flag
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")

    proposal = validate_success(
        api.screen_amendment_proposal(
            world["proposal_id"],
            factories.screening_payload("ACCEPT_FOR_ANALYSIS"),
            make_technical_staff_headers(),
        )
    )
    assert proposal["review_status"] == "SCREENED"
    assert proposal["analysis_status"] == "PENDING"
    assert proposal["energy_analysis_required"] is True
    assert proposal["version"] == 2

    _, meta = validate_paginated(
        api.list_proposal_impact_analyses(
            world["proposal_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 0


def test_05_a_draft_cycle_may_not_jump_to_deliberation(api):
    """"A cycle's `status` walks the sequence `DRAFT` → `INTAKE_OPEN` →
    `INTAKE_CLOSED` → `DELIBERATION` → `RULEMAKING` → `ADOPTED`, with
    `ABANDONED` available as an early exit." Skipping two steps is not a declared
    move, so the eleventh rung reports the record family's own state error and
    nothing changes.

    Design: Corner/state_machines/code_cycle_draft_to_deliberation_is_rejected
    """
    world = fixtures.setup_cycle(api)

    response = fixtures.set_cycle_status(api, world["cycle_id"], "DELIBERATION")
    validate_error(response, ApiErrorId.ERR_CYCLE_STATE_INVALID, 409)

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "DRAFT"
    assert cycle["version"] == 1


def test_06_a_withdrawn_order_can_never_be_published(api):
    """"An order may be withdrawn from `FILED` or from `PUBLISHED`, with the
    reason captured in `withdrawal_reason`", and `WITHDRAWN` is terminal. A later
    publication attempt is therefore refused on the order's own state, leaving
    `published_at` and `published_by_user_id` null and the recorded reason
    intact.

    Design: Corner/state_machines/withdrawn_adoption_rule_cannot_be_republished_returns_4xx
    """
    world = fixtures.setup_filed_adoption_rule(api)
    get_success_data(
        fixtures.advance_rule(
            api,
            world,
            "WITHDRAWN",
            make_council_admin_headers(ADMIN_OPS_ID),
            withdrawal_reason="Council reconsidered the package before publication.",
        )
    )

    response = fixtures.advance_rule(
        api, world, "PUBLISHED", make_council_admin_headers(ADMIN_PUBLISHER_ID)
    )
    validate_error(response, ApiErrorId.ERR_ADOPTION_RULE_STATE_INVALID, 409)

    rule = get_success_data(
        api.get_adoption_rule(world["rule_id"], make_council_admin_headers())
    )
    assert rule["status"] == "WITHDRAWN"
    assert rule["published_at"] is None
    assert rule["published_by_user_id"] is None
    assert (
        rule["withdrawal_reason"]
        == "Council reconsidered the package before publication."
    )


def test_07_closing_an_already_closed_comment_window_is_refused(api):
    """"Closing the window advances `review_status` `COMMENT_OPEN` →
    `COMMENT_CLOSED`", and the own-state rung "covers terminal-state lockdown and
    repeated attempts at an action that has already been taken". The frozen
    figures survive the refusal: three supporting and one opposing comment over a
    143,002,800-cent amendment fix `base_docket_score` at 74.45.

    Design: Corner/state_machines/second_comment_window_close_is_rejected
    """
    world = fixtures.setup_proposal_comment_closed(api)

    response = fixtures.act_on_comment_window(api, world, "CLOSE")
    validate_error(response, ApiErrorId.ERR_PROPOSAL_STATE_INVALID, 409)

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "COMMENT_CLOSED"
    assert proposal["comment_window_status"] == "CLOSED"
    assert proposal["comment_round"] == 1
    assert proposal["base_docket_score"] == 74.45
    assert proposal["support_comment_count"] == 3
    assert proposal["oppose_comment_count"] == 1


def test_08_the_third_recusal_unseats_the_committee_and_cancels_its_hearing(api):
    """"If, after a recusal, `active_voting_member_count` has fallen below two
    thirds of `voting_seat_count` rounded up ... the committee un-seats `SEATED` →
    `FORMING`", and "any hearing of that committee still in `SCHEDULED` is
    automatically `CANCELLED`, its `agenda_proposal_ids` emptied". Three of six
    seats left active is below the four that seating demands, while quorum falls
    with the denominator to two.

    Design: Corner/state_machines/committee_recusal_unseats_and_cancels_the_pending_hearing
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_scheduled_hearing(api, world)
    for key, reason in RECUSALS[:2]:
        get_success_data(_recuse(api, world, key, reason))

    key, reason = RECUSALS[2]
    member = validate_success(_recuse(api, world, key, reason))
    assert member["status"] == "RECUSED"
    assert member["recusal_reason"] == reason

    committee = get_success_data(
        api.get_discipline_committee(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert committee["active_voting_member_count"] == 3
    assert committee["quorum_required"] == 2
    assert committee["status"] == "FORMING"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["seated_committee_count"] == 0

    hearing = get_success_data(
        api.get_hearing(world["hearing_id"], make_council_admin_headers())
    )
    assert hearing["status"] == "CANCELLED"


def test_09_an_order_reaching_enforcement_adopts_its_cycle(api):
    """Going effective "bubbles up to the cycle, taking it `RULEMAKING` →
    `ADOPTED`", once "statewide training readiness must have reached the threshold
    of 80.00 percent". Riverbend's 1,200,000 residents at 80.00 and Harborview's
    300,000 at 100.00 give a population-weighted 84.00, which is snapshotted onto
    `statewide_readiness_pct_at_effective`.

    Design: Corner/state_machines/cycle_auto_adopts_when_its_rule_reaches_effective
    """
    world = fixtures.setup_delivered_session_two_jurisdictions(api)
    fixtures.set_logical_clock(api, fixtures.CLOCK_EFFECTIVE_DATE)

    rule = validate_success(
        fixtures.advance_rule(
            api,
            world,
            "EFFECTIVE",
            make_council_admin_headers(ADMIN_EFFECTIVE_ID),
        )
    )
    assert rule["status"] == "EFFECTIVE"
    assert rule["statewide_readiness_pct_at_effective"] == 84.00
    assert rule["effective_date"] == "2027-02-02T00:00:00Z"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["status"] == "ADOPTED"

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["compliance_pct_attendance_basis"] == 80.00
    assert riverbend["enforcement_readiness"] == "READY"

    harborview = fixtures.read_jurisdiction(api, world["harborview_id"])
    assert harborview["compliance_pct_attendance_basis"] == 100.00
    assert harborview["enforcement_readiness"] == "READY"

    session = get_success_data(
        api.get_training_session(world["session_id"], make_council_admin_headers())
    )
    assert session["status"] == "DELIVERED"
    assert session["attended_count"] == 8
    assert session["no_show_count"] == 1


def test_10_accepting_a_replacement_cost_benefit_supersedes_the_first(api):
    """"Accepting moves it `SUBMITTED` → `ACCEPTED`, and any *other* analysis of
    the same proposal with the same `analysis_type` that was `ACCEPTED` moves
    `ACCEPTED` → `SUPERSEDED`", and "the proposal absorbs its figures". The
    replacement's 700 permits certify 8,120,000 cents, so the preliminary ratio
    becomes 900,000 × 15 ÷ 8,120,000 = 1.66 while the final ratio stays null
    until the vote.

    Design: Corner/state_machines/accepting_a_replacement_analysis_supersedes_the_prior_accepted_one
    """
    world = fixtures.setup_proposal_with_accepted_cost_benefit(api)
    first_id = world["cost_benefit_id"]

    version_now = fixtures.read_proposal(api, world["proposal_id"])["version"]
    replacement = fixtures.file_cost_benefit_analysis(
        api,
        world,
        expected_version=version_now,
        headers=make_technical_staff_headers(STAFF_SECOND_ANALYST_ID),
        **REPLACEMENT_COST_BENEFIT,
    )

    accepted = validate_success(
        fixtures.review_analysis(
            api,
            replacement["id"],
            headers=make_council_admin_headers(ADMIN_SECOND_REVIEWER_ID),
        )
    )
    assert accepted["status"] == "ACCEPTED"
    assert accepted["statewide_incremental_cost_cents"] == 8120000

    superseded = get_success_data(
        api.get_impact_analysis(first_id, make_council_admin_headers())
    )
    assert superseded["status"] == "SUPERSEDED"

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["statewide_incremental_cost_cents"] == 8120000
    assert proposal["affected_permit_count"] == 700
    assert proposal["preliminary_benefit_cost_ratio"] == 1.66
    assert proposal["final_benefit_cost_ratio"] is None
    assert proposal["analysis_status"] == "PARTIAL"

    _, meta = validate_paginated(
        api.list_proposal_impact_analyses(
            world["proposal_id"], make_council_admin_headers()
        )
    )
    assert meta["total_count"] == 2


def test_11_accepting_a_local_filing_increments_the_jurisdiction_ledger(api):
    """"Starting review moves the filing `SUBMITTED` → `UNDER_REVIEW`, stores
    `reviewed_by_user_id`", and "accepting moves the filing `UNDER_REVIEW` →
    `FILED_EFFECTIVE` and increments the jurisdiction's
    `effective_local_amendment_count` by one along with the jurisdiction's
    `version`". The one filing is readable from both the jurisdiction's and the
    order's collections.

    Design: Corner/state_machines/accepting_a_local_amendment_increments_the_jurisdiction_ledger
    """
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.add_local_amendment(api, world)
    get_success_data(fixtures.review_local_amendment(api, world, "START_REVIEW"))

    amendment = validate_success(
        fixtures.review_local_amendment(api, world, "ACCEPT")
    )
    assert amendment["status"] == "FILED_EFFECTIVE"
    assert amendment["reviewed_by_user_id"] == ADMIN_LOCAL_REVIEWER_ID

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["effective_local_amendment_count"] == 1

    _, by_jurisdiction = validate_paginated(
        api.list_jurisdiction_local_amendments(
            world["riverbend_id"], make_council_admin_headers()
        )
    )
    assert by_jurisdiction["total_count"] == 1

    _, by_rule = validate_paginated(
        api.list_rule_local_amendments(world["rule_id"], make_council_admin_headers())
    )
    assert by_rule["total_count"] == 1
