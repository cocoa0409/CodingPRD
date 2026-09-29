"""The two benefit-cost ratios and the statutory floor they are tested against."""
from test_helpers import (
    ApiErrorId,
    fixtures,
    get_success_data,
    validate_error,
    validate_paginated,
    validate_success,
    make_council_admin_headers,
)
from test_helpers.factories import ballot


def test_01_preliminary_and_final_ratios_diverge_on_identical_stored_data(api):
    """"Both ratios are computed over the same stored data and differ only in
    how future savings are valued." The preliminary ratio "uses a flat statutory
    horizon of 15 years with no discounting: it is `annual_cost_savings_cents`
    multiplied by 15, divided by the proposal's certified
    `statewide_incremental_cost_cents`, rounded half up to 2 decimal places",
    which on 14,500,000 cents of annual saving against 143,002,800 cents of
    certified cost is 1.52. The final ratio "discounts the savings stream over
    the analyst's own `measure_life_years` at the state discount rate of 3
    percent per year", which over 12 years is 1.01.

    Design: Difficulty/dual_variant_calc/amendment_bcr_preliminary_vs_final_diverge
    """
    world = fixtures.setup_approved_proposal(api)

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["statewide_incremental_cost_cents"] == 143002800
    assert proposal["preliminary_benefit_cost_ratio"] == 1.52
    assert proposal["final_benefit_cost_ratio"] == 1.01
    assert round(
        proposal["preliminary_benefit_cost_ratio"]
        - proposal["final_benefit_cost_ratio"],
        2,
    ) == 0.51


def test_02_vote_record_snapshots_the_final_ratio_recomputed_at_the_vote(api):
    """"The final ratio is recomputed fresh at the moment of the committee
    vote", and "the value that results is written both to the proposal's
    `final_benefit_cost_ratio` and to the vote record's
    `final_benefit_cost_ratio_at_vote`". With four YES against two NO the
    "`outcome` is `APPROVED` with `outcome_reason` `MAJORITY_APPROVED`" and the
    approval "advances the proposal `COMMENT_CLOSED` → `APPROVED`".

    Design: Difficulty/dual_variant_calc/amendment_bcr_preliminary_vs_final_diverge
    """
    world = fixtures.setup_approved_proposal(api)

    vote = get_success_data(
        api.get_vote_record(world["vote_id"], make_council_admin_headers())
    )
    assert vote["final_benefit_cost_ratio_at_vote"] == 1.01
    assert vote["outcome"] == "APPROVED"
    assert vote["outcome_reason"] == "MAJORITY_APPROVED"

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["review_status"] == "APPROVED"
    assert proposal["statewide_incremental_cost_cents"] == 143002800


def test_03_final_ratio_rounding_half_up_to_exactly_the_floor_passes(api):
    """"Only the final ratio is ever tested against the statutory floor of 1.00,
    and the comparison is made on the rounded 2-decimal value, so a raw result
    of 0.995032 rounds to 1.00 and passes while 0.990021 rounds to 0.99 and
    fails." On 14,295,000 cents of annual saving the preliminary ratio reads
    1.50 while the discounted final ratio rounds up to exactly 1.00, and the
    ballot is accepted.

    Design: Difficulty/boundary_precision_check/benefit_cost_ratio_rounds_up_to_exactly_floor_and_passes
    """
    world = fixtures.setup_convened_hearing(
        api, cost_benefit_overrides={"annual_cost_savings_cents": 14295000}
    )

    response = fixtures.record_vote(api, world)
    validate_success(response, 201)

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["preliminary_benefit_cost_ratio"] == 1.50
    assert proposal["final_benefit_cost_ratio"] == 1.00
    assert proposal["review_status"] == "APPROVED"


def test_04_ratio_at_exactly_the_floor_is_recorded_and_ledgered(api):
    """An approving vote at the inclusive floor still "synchronises the cycle
    ledger: the proposal's `statewide_incremental_cost_cents` is added to the
    cycle's `approved_incremental_cost_cents`, its `affected_permit_count` is
    added to the cycle's `approved_permit_backlog_count`, and the cycle's
    `approved_proposal_count` increases by one".

    Design: Difficulty/boundary_precision_check/benefit_cost_ratio_rounds_up_to_exactly_floor_and_passes
    """
    world = fixtures.setup_convened_hearing(
        api, cost_benefit_overrides={"annual_cost_savings_cents": 14295000}
    )

    vote = get_success_data(fixtures.record_vote(api, world), 201)
    assert vote["final_benefit_cost_ratio_at_vote"] == 1.00
    assert vote["outcome"] == "APPROVED"

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_proposal_count"] == 1
    assert cycle["approved_incremental_cost_cents"] == 143002800
    assert cycle["approved_permit_backlog_count"] == 2410


def _life_safety_relaxation_world(api):
    """A LESS_STRINGENT proposal on life-safety section 907.5.2 whose final
    ratio also falls below the floor, convened for its ballot."""
    committee_world = fixtures.setup_seated_fire_safety_committee(api)
    return fixtures.setup_convened_hearing(
        api,
        world=committee_world,
        proposal_overrides={
            "code_section": "907.5.2",
            "discipline": "FIRE_AND_LIFE_SAFETY",
            "title": "Relax audible alarm coverage in small assembly",
            "proposed_text": (
                "Permit reduced audible notification coverage in assembly spaces "
                "under 300 occupants."
            ),
            "stringency_direction": "LESS_STRINGENT",
        },
        cost_benefit_overrides={
            "incremental_cost_by_occupancy": {
                "R3": 10000,
                "R2": 12000,
                "B": 15000,
                "A2": 18000,
            },
            "affected_permit_count": 700,
            "annual_cost_savings_cents": 807500,
        },
        energy_impact=False,
        with_comments=False,
    )


def _relaxation_ballots(world):
    return [
        ballot(world["members"]["chair"]["id"], "YES"),
        ballot(world["members"]["fire"]["id"], "YES"),
        ballot(world["members"]["local"]["id"], "YES"),
    ]


def test_05_life_safety_relaxation_outranks_the_benefit_cost_floor(api):
    """"Two substantive gates then apply, in this order. First, an approving
    vote may not relax a life-safety section: if the proposal's
    `stringency_direction` is `LESS_STRINGENT` and its `code_section` begins with
    either `9` or `10`, the call is refused with
    `ERR_STRINGENCY_FLOOR_VIOLATION`. Second, the final benefit-cost ratio is
    recomputed from scratch ... and if the rounded 2-decimal result is below 1.00
    the call is refused with `ERR_BENEFIT_COST_BELOW_FLOOR`. When both apply, the
    life-safety refusal is the one reported."

    Design: Difficulty/priority_pair_validation_conflict/stringency_floor_outranks_benefit_cost_floor_on_vote
    """
    world = _life_safety_relaxation_world(api)

    response = fixtures.record_vote(api, world, ballots=_relaxation_ballots(world))
    error = validate_error(response, ApiErrorId.ERR_STRINGENCY_FLOOR_VIOLATION, 422)
    assert error["error_id"] != ApiErrorId.ERR_BENEFIT_COST_BELOW_FLOOR


def test_06_refused_life_safety_ballot_writes_no_vote_record(api):
    """A refusal leaves the proposal where it was: closing the window had
    already advanced "`review_status` `COMMENT_OPEN` → `COMMENT_CLOSED`", the
    preliminary ratio frozen at acceptance stands at 1.49, and no approval means
    the cycle's `approved_proposal_count` never leaves 0.

    Design: Difficulty/priority_pair_validation_conflict/stringency_floor_outranks_benefit_cost_floor_on_vote
    """
    world = _life_safety_relaxation_world(api)

    fixtures.record_vote(api, world, ballots=_relaxation_ballots(world))

    proposal = get_success_data(
        api.get_amendment_proposal(world["proposal_id"], make_council_admin_headers())
    )
    assert proposal["review_status"] == "COMMENT_CLOSED"
    assert proposal["preliminary_benefit_cost_ratio"] == 1.49

    _, meta = validate_paginated(
        api.list_hearing_votes(world["hearing_id"], make_council_admin_headers())
    )
    assert meta["total_count"] == 0

    cycle = get_success_data(
        api.get_code_cycle(world["cycle_id"], make_council_admin_headers())
    )
    assert cycle["approved_proposal_count"] == 0
