"""Precinct voter variants, split fork, block-reassignment recompute, retire, split partition.

Difficulty queue A: dual_variant_calc/precinct_voters_provisional_vs_certified,
non_linear_state_machine/precinct_split_branch,
transitive_cascade/precinct_split_reassign_recompute.
Corner queue B: state_machines/retire_nonempty_precinct_rejected,
state_machines/split_non_partitioning_groups_rejected.
"""
from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data,
    create_jurisdiction, add_block, create_precinct, get_precinct_of_block,
    ApiErrorId, TEST_USERS,
)
from test_helpers.factories import split_payload

CLERK = TEST_USERS["clerk_headers"]


def _setup_split_precinct(api, jname):
    """Jurisdiction with precinct PR holding S1(VAP400) and S2(VAP600)."""
    j = create_jurisdiction(api, name=jname, target_district_count=1)
    jid = j["id"]
    s1 = add_block(api, jid, geoid="S1", population=500, voting_age_population=400, minority_vap=100, registered_voters=350)
    s2 = add_block(api, jid, geoid="S2", population=700, voting_age_population=600, minority_vap=200, registered_voters=500)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[s1["id"], s2["id"]])
    return jid, s1, s2, pr


# ----------------------------------- dual_variant: provisional vs certified voters
def test_precinct_provisional_voter_estimate(api):
    """PRD §3.6: "Under the PROVISIONAL basis the count is an estimate: the sum of
    voting_age_population over the precinct's blocks multiplied by a registration
    rate of 0.85, rounded to the nearest whole number - a precinct holding 1,000
    VAP estimates 850 voters."

    Design: Difficulty/dual_variant_calc/precinct_voters_provisional_vs_certified
    """
    j = create_jurisdiction(api, name="Jp", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="G1", population=1200, voting_age_population=1000, minority_vap=300, registered_voters=812)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    assert pr["voter_count_basis"] == "PROVISIONAL"
    assert pr["registered_voters"] == 850, f"provisional estimate must be 850, got {pr['registered_voters']}"


def test_precinct_certified_voter_count(api):
    """PRD §3.6: "Under the CERTIFIED basis the count is the sum of the blocks'
    actual registered_voters - the same precinct might certify, say, 812, a
    different number from the same blocks."

    Design: Difficulty/dual_variant_calc/precinct_voters_provisional_vs_certified
    """
    j = create_jurisdiction(api, name="Jp2", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="G1", population=1200, voting_age_population=1000, minority_vap=300, registered_voters=812)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    certified = validate_success(api.certify_precinct(pr["id"], CLERK))
    assert certified["voter_count_basis"] == "CERTIFIED"
    assert certified["registered_voters"] == 812, f"certified count must be 812, got {certified['registered_voters']}"


# ----------------------------------- non_linear: split fork
def test_split_moves_parent_to_split_state(api):
    """PRD §3.6: "moves the original precinct to `SPLIT` with its `registered_voters`
    set to 0."

    Design: Difficulty/non_linear_state_machine/precinct_split_branch
    """
    jid, s1, s2, pr = _setup_split_precinct(api, "Jsp")
    validate_success(api.split_precinct(pr["id"], split_payload("PR-A", ["S1"], "PR-B", ["S2"]), CLERK), 201)
    parent = validate_success(api.get_precinct(pr["id"], CLERK))
    assert parent["status"] == "SPLIT"
    assert parent["registered_voters"] == 0, "parent registered_voters is forced to 0 on split"


def test_split_creates_two_child_precincts(api):
    """PRD §3.6: "the system creates child precinct A and child precinct B, each
    with parent_precinct_id set to the original; ... recomputes both children's
    registered_voters from their newly assigned blocks".

    Design: Difficulty/non_linear_state_machine/precinct_split_branch
    """
    jid, s1, s2, pr = _setup_split_precinct(api, "Jsp2")
    validate_success(api.split_precinct(pr["id"], split_payload("PR-A", ["S1"], "PR-B", ["S2"]), CLERK), 201)
    children, meta = validate_paginated(api.list_precincts(CLERK, params={"parent_precinct_id": pr["id"]}))
    assert meta["total_count"] == 2, f"exactly two child precincts expected, got {meta['total_count']}"
    child_s1 = get_precinct_of_block(api, s1["id"])
    child_s2 = get_precinct_of_block(api, s2["id"])
    assert child_s1["registered_voters"] == 340, f"child covering S1 (400 VAP) -> round(340), got {child_s1['registered_voters']}"
    assert child_s2["registered_voters"] == 510, f"child covering S2 (600 VAP) -> round(510), got {child_s2['registered_voters']}"


# ----------------------------------- transitive_cascade: split reassign -> recompute
def test_split_reassigns_block_precinct_ids(api):
    """PRD §3.6: "reassigns each census block's `precinct_id` to its child;
    recomputes both children's `registered_voters` from their newly assigned blocks".

    Design: Difficulty/transitive_cascade/precinct_split_reassign_recompute
    """
    jid, s1, s2, pr = _setup_split_precinct(api, "Jsr")
    validate_success(api.split_precinct(pr["id"], split_payload("PR-A", ["S1"], "PR-B", ["S2"]), CLERK), 201)
    b1 = validate_success(api.get_census_block(s1["id"], CLERK))
    b2 = validate_success(api.get_census_block(s2["id"], CLERK))
    assert b1["precinct_id"] != pr["id"], "S1 must be reassigned away from the split parent"
    assert b2["precinct_id"] != pr["id"], "S2 must be reassigned away from the split parent"
    assert b1["precinct_id"] != b2["precinct_id"], "S1 and S2 go to distinct child precincts"


def test_split_recomputes_child_registered_voters(api):
    """PRD §3.6: "recomputes both children's `registered_voters` from their newly
    assigned blocks". The recompute is downstream of the block move.

    Design: Difficulty/transitive_cascade/precinct_split_reassign_recompute
    """
    jid, s1, s2, pr = _setup_split_precinct(api, "Jsr2")
    validate_success(api.split_precinct(pr["id"], split_payload("PR-A", ["S1"], "PR-B", ["S2"]), CLERK), 201)
    child_s1 = get_precinct_of_block(api, s1["id"])
    child_s2 = get_precinct_of_block(api, s2["id"])
    assert child_s1["registered_voters"] == 340, f"round(400*0.85)=340, got {child_s1['registered_voters']}"
    assert child_s2["registered_voters"] == 510, f"round(600*0.85)=510, got {child_s2['registered_voters']}"


# ----------------------------------- corner: retire non-empty precinct
def test_retire_nonempty_precinct_rejected(api):
    """PRD §3.6: "An ACTIVE precinct with no active census blocks and no active
    polling assignment is retired ... If it still holds blocks or still has an
    active polling assignment, the request is rejected with ERR_PRECINCT_NOT_EMPTY."

    Design: Corner/state_machines/retire_nonempty_precinct_rejected
    """
    j = create_jurisdiction(api, name="Jr", target_district_count=1)
    jid = j["id"]
    blk = add_block(api, jid, geoid="G1", population=500, voting_age_population=400, minority_vap=100, registered_voters=300)
    pr = create_precinct(api, jid, name="PR", census_block_ids=[blk["id"]])
    validate_error(api.retire_precinct(pr["id"], CLERK), ApiErrorId.ERR_PRECINCT_NOT_EMPTY.value)


# ----------------------------------- corner: split non-partitioning groups
def test_split_non_partitioning_groups_rejected(api):
    """PRD §3.6: "the two geoid groups must exactly partition the precinct's
    current blocks: every block appears in exactly one group and no foreign block
    is named, or the request is rejected with ERR_INCOMPLETE_PARTITION."

    Design: Corner/state_machines/split_non_partitioning_groups_rejected
    """
    jid, s1, s2, pr = _setup_split_precinct(api, "Jsp3")
    validate_error(
        api.split_precinct(pr["id"], split_payload("A", ["S1"], "B", ["S1"]), CLERK),
        ApiErrorId.ERR_INCOMPLETE_PARTITION.value,
    )
