"""Boundary instants, conditional requirements and the order the priority ladder
imposes when two rules both apply."""
from test_helpers import (
    NON_EXISTENT_UUID,
    STAFF_SECOND_ANALYST_ID,
    ApiErrorId,
    factories,
    fixtures,
    get_success_data,
    make_council_admin_headers,
    make_petitioner_headers,
    make_technical_staff_headers,
    validate_error,
    validate_paginated,
    validate_success,
)

# The order is published at 2026-10-05T14:00:00Z, so the inclusive 90-day local
# filing deadline falls on 2027-01-03T14:00:00Z.
DEADLINE_INSTANT = "2027-01-03T14:00:00Z"
ONE_SECOND_LATE = "2027-01-03T14:00:01Z"

BELOW_FLOOR_COST_BENEFIT = {"annual_cost_savings_cents": 14223000}

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

MECHANICAL_COST_BENEFIT = {
    "incremental_cost_by_occupancy": {"R3": 10000, "R2": 12000, "B": 15000, "A2": 18000},
    "affected_permit_count": 700,
    "annual_cost_savings_cents": 900000,
    "measure_life_years": 20,
}


def _filing_under_review_at(api, instant):
    """A local filing made with the clock standing at `instant` and carried as far
    as UNDER_REVIEW, so only the acceptance gate is left to run."""
    world = fixtures.setup_published_adoption_rule(api)
    fixtures.add_riverbend(api, world)
    fixtures.set_logical_clock(api, instant)
    fixtures.add_local_amendment(api, world)
    get_success_data(fixtures.review_local_amendment(api, world, "START_REVIEW"))
    return world


def test_01_a_filing_made_on_the_deadline_instant_is_accepted(api):
    """`filed_within_window` "is true when the filing's `created_at` is at or
    before the order's `published_at` plus 90 days, inclusive at the boundary",
    and acceptance requires that "`filed_within_window` must be true, or it is
    refused with `ERR_LOCAL_FILING_DEADLINE_PASSED`". A filing created at exactly
    2027-01-03T14:00:00Z sits on the boundary, so the acceptance succeeds and the
    jurisdiction's ledger moves to 1.

    Design: Corner/validations/local_amendment_filed_on_the_deadline_instant_is_accepted
    """
    world = _filing_under_review_at(api, DEADLINE_INSTANT)

    amendment = validate_success(fixtures.review_local_amendment(api, world, "ACCEPT"))
    assert amendment["filed_within_window"] is True
    assert amendment["status"] == "FILED_EFFECTIVE"

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["effective_local_amendment_count"] == 1


def test_02_a_filing_one_second_late_is_admitted_but_never_accepted(api):
    """The same boundary is exclusive one second later, so `filed_within_window`
    is false and the acceptance is refused because "`filed_within_window` must be
    true, or it is refused with `ERR_LOCAL_FILING_DEADLINE_PASSED`". The row was
    still admitted at intake, so it stays `UNDER_REVIEW` and the jurisdiction's
    `effective_local_amendment_count` never leaves 0.

    Design: Corner/validations/local_amendment_one_second_past_the_deadline_is_rejected_on_review
    """
    world = _filing_under_review_at(api, ONE_SECOND_LATE)

    response = fixtures.review_local_amendment(api, world, "ACCEPT")
    validate_error(response, ApiErrorId.ERR_LOCAL_FILING_DEADLINE_PASSED, 409)

    amendment = get_success_data(
        api.get_local_amendment(
            world["local_amendment_id"], make_council_admin_headers()
        )
    )
    assert amendment["filed_within_window"] is False
    assert amendment["status"] == "UNDER_REVIEW"

    riverbend = fixtures.read_jurisdiction(api, world["riverbend_id"])
    assert riverbend["effective_local_amendment_count"] == 0


def test_03_a_forbidden_role_is_reported_before_the_missing_path_row(api):
    """Role authorization asks whether "the declared role is authorized for the
    endpoint ... else `ERR_FORBIDDEN_ROLE` (403). Because this precedes every
    existence check, an unauthorized role probing a randomly invented identifier
    receives 403, never 404." A `Petitioner` driving a cycle's status is
    unauthorized, so the identifier that resolves to nothing is never reached.

    Design: Corner/validations/forbidden_role_outranks_missing_path_id_unauthorized
    """
    response = api.set_code_cycle_status(
        NON_EXISTENT_UUID,
        factories.code_cycle_status_payload("INTAKE_OPEN"),
        make_petitioner_headers(),
    )
    error = validate_error(response, ApiErrorId.ERR_FORBIDDEN_ROLE, 403)
    assert error["error_id"] != ApiErrorId.ERR_CODE_CYCLE_NOT_FOUND


def test_04_quorum_is_reported_before_the_benefit_cost_floor(api):
    """Quorum belongs to the business-safety rung, covering "the stringency floor
    on life-safety sections, the stringency limit on local amendments, and quorum,
    each yielding a 422", which the ladder places above the fiscal rung of
    "benefit-cost floor, statewide training readiness, and the approved-amendment
    gates, each yielding a 422". Three ballots on a six-seat committee fall short
    of the four that quorum demands, so the 0.99 ratio is never reached and "no
    vote record row is created at all".

    Design: Corner/validations/quorum_check_precedes_the_benefit_cost_floor
    """
    world = fixtures.setup_convened_hearing(
        api, cost_benefit_overrides=BELOW_FLOOR_COST_BENEFIT
    )
    members = world["members"]
    ballots = [
        factories.ballot(members["chair"]["id"], "YES"),
        factories.ballot(members["industry_two"]["id"], "YES"),
        factories.ballot(members["local"]["id"], "YES"),
    ]

    response = fixtures.record_vote(api, world, ballots=ballots)
    error = validate_error(response, ApiErrorId.ERR_QUORUM_NOT_MET, 422)
    assert error["error_id"] != ApiErrorId.ERR_BENEFIT_COST_BELOW_FLOOR

    committee = get_success_data(
        api.get_discipline_committee(
            world["committee_id"], make_council_admin_headers()
        )
    )
    assert committee["quorum_required"] == 4

    _, meta = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["review_status"] == "COMMENT_CLOSED"


def test_05_one_accepted_analysis_completes_a_proposal_that_owes_no_energy_study(api):
    """"The first accepted analysis moves the proposal `PENDING` → `PARTIAL`,
    except in one case: when `energy_analysis_required` is false and the accepted
    analysis is the `COST_BENEFIT` one, the proposal jumps straight to
    `COMPLETE`, because no energy analysis is owed." A `NEUTRAL` `MECHANICAL`
    amendment owes none, and on the same accept "the proposal absorbs its
    figures": 700 permits at the declared per-occupancy costs certify 8,120,000
    cents, giving a preliminary ratio of 900,000 × 15 ÷ 8,120,000 = 1.66.

    Design: Corner/validations/energy_analysis_is_not_required_for_a_neutral_mechanical_proposal
    """
    world = fixtures.setup_seated_energy_committee(api)
    fixtures.add_mechanical_committee(api, world)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_OPEN")
    fixtures.submit_proposal(api, world, **MECHANICAL_PROPOSAL)
    fixtures.set_cycle_status(api, world["cycle_id"], "INTAKE_CLOSED")
    fixtures.screen_proposal(api, world)
    analysis = fixtures.file_cost_benefit_analysis(
        api,
        world,
        headers=make_technical_staff_headers(STAFF_SECOND_ANALYST_ID),
        **MECHANICAL_COST_BENEFIT,
    )

    accepted = validate_success(fixtures.review_analysis(api, analysis["id"]))
    assert accepted["status"] == "ACCEPTED"

    proposal = fixtures.read_proposal(api, world["proposal_id"])
    assert proposal["energy_analysis_required"] is False
    assert proposal["analysis_status"] == "COMPLETE"
    assert proposal["statewide_incremental_cost_cents"] == 8120000
    assert proposal["affected_permit_count"] == 700
    assert proposal["preliminary_benefit_cost_ratio"] == 1.66
